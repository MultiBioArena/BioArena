"""Confirmed transfer discovery and conservative external-capital reconciliation."""
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from .challenge import CapitalFlow
from .evm_readonly import TRANSFER, hash32, uint
from .execution_preflight import usd
from .voting import evm_address


class FlowStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,bio TEXT,chain INTEGER,wallet TEXT,tx TEXT,block INTEGER,at REAL,kind TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS capital(id TEXT PRIMARY KEY,bio TEXT,at REAL,payload TEXT);
        CREATE TABLE IF NOT EXISTS cursors(key TEXT PRIMARY KEY,height INTEGER,hash TEXT,config TEXT,blocked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS coverage(key TEXT PRIMARY KEY,bio TEXT,start REAL,end REAL,blocked INTEGER);
        CREATE INDEX IF NOT EXISTS capital_by_bio_time ON capital(bio,at);
        ''')

    def close(self):self.db.close()

    def record(self,bio,receipt,at,kind):
        if kind not in ('deposit','withdrawal','trade','bridge','internal','review'):raise ValueError('Unknown transfer classification')
        if receipt['status']!='confirmed_success':raise ValueError('Only canonical successful transfers can be recorded')
        with self.db:
            for transfer in receipt['transfers']:
                if int(transfer['delta_raw'])==0:continue
                ledger_id=f'{bio}:{receipt["wallet"]}:{transfer["event_id"]}'
                payload={'transfer':transfer,'block_hash':receipt['block_hash'],'classification':kind,
                         'receipt_scope':receipt['scope'],'fee_payer':receipt['fee_payer']}
                encoded=json.dumps(payload,sort_keys=True)
                old=self.db.execute('SELECT payload,bio FROM transfers WHERE id=?',(ledger_id,)).fetchone()
                if old:
                    if old!=(encoded,bio):raise ValueError('Conflicting transfer evidence or classification')
                    continue
                self.db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?,?)',
                    (ledger_id,bio,receipt['chain_id'],receipt['wallet'],receipt['tx_hash'],receipt['block_number'],at,kind,encoded))

    def reconcile(self,bio,tx_hash,valuation):
        """Local reconciler input must bind raw transfers to one common price snapshot."""
        rows=self.db.execute('SELECT id,chain,wallet,at,kind,payload FROM transfers WHERE bio=? AND tx=? ORDER BY id',(bio,tx_hash)).fetchall()
        if not rows or any(r[4] not in ('deposit','withdrawal') for r in rows):
            raise ValueError('Unclassified or trading transfers cannot become capital flows')
        if len({(r[1],r[2],r[3],r[4]) for r in rows})!=1:raise ValueError('Ambiguous multi-chain capital movement')
        chain,wallet,at,kind=rows[0][1:5]
        if (valuation.get('chain_id')!=chain or valuation.get('wallet')!=wallet
                or valuation.get('tx_hash')!=tx_hash or not valuation.get('reference')
                or not valuation.get('price_snapshot_id') or valuation.get('balances_verified') is not True
                or abs(float(valuation.get('at',0))-at)>20):raise ValueError('Missing bound balance and price evidence')
        total=Decimal(0)
        for event_id,_,__,___,____,raw in rows:
            transfer=json.loads(raw)['transfer'];mark=valuation['tokens'].get(transfer['token'])
            if not mark or mark.get('price_snapshot_id')!=valuation['price_snapshot_id'] or not mark.get('source'):
                raise ValueError('Every transfer needs the same verified price snapshot')
            decimals=mark['decimals']
            if not isinstance(decimals,int) or not 0<=decimals<=36:raise ValueError('Invalid token decimals')
            delta=Decimal(transfer['delta_raw'])/Decimal(10)**decimals
            price=usd(mark['price_usd'])
            if price<=0 or abs(float(mark.get('observed_at',0))-at)>20:raise ValueError('Stale or zero transfer valuation')
            if str(valuation.get('balance_changes_raw',{}).get(transfer['token']))!=transfer['delta_raw']:
                raise ValueError('Raw balance change differs from the transfer')
            total+=delta*price
        if (kind=='deposit' and total<=0) or (kind=='withdrawal' and total>=0):raise ValueError('Transfer direction does not match classification')
        before,after=usd(valuation['equity_before']),usd(valuation['equity_after'])
        fees=usd(valuation.get('transaction_cost_usd',0))
        if abs(after-before-total+fees)>Decimal('0.000001'):raise ValueError('Balances, capital and transaction cost do not reconcile')
        # Charge transaction costs to performance immediately before the external flow.
        flow=CapitalFlow(f'{bio}:{chain}:{tx_hash}',at,float(total),float(before-fees),float(after),valuation['reference'])
        if flow.equity_before<0:raise ValueError('Transaction costs exceed the account equity')
        encoded=json.dumps({'flow':asdict(flow),'valuation':valuation,'transfer_ids':[r[0] for r in rows]},sort_keys=True,allow_nan=False)
        with self.db:
            old=self.db.execute('SELECT payload FROM capital WHERE id=?',(flow.event_id,)).fetchone()
            if old and old[0]!=encoded:raise ValueError('Capital reconciliation is immutable')
            self.db.execute('INSERT OR IGNORE INTO capital VALUES (?,?,?,?)',(flow.event_id,bio,at,encoded))
        return flow

    def for_interval(self,bio,start,end,require_coverage=True):
        if require_coverage:
            coverage=self.db.execute('SELECT start,end,blocked FROM coverage WHERE bio=?',(bio,)).fetchall()
            if not coverage or any(a>start or b<=end or blocked for a,b,blocked in coverage):
                raise ValueError('Complete confirmed scanning coverage is required')
        # Pending classification/valuation invalidates a live scoring interval.
        unresolved=self.db.execute('''SELECT COUNT(*) FROM transfers t WHERE bio=? AND at>? AND at<=?
            AND kind IN ('review','deposit','withdrawal') AND NOT EXISTS
            (SELECT 1 FROM capital c WHERE c.id=t.bio||':'||t.chain||':'||t.tx)''',(bio,start,end)).fetchone()[0]
        if unresolved:raise ValueError('Unreconciled transfers prevent hourly scoring')
        return [CapitalFlow(**json.loads(r[0])['flow']) for r in self.db.execute(
            'SELECT payload FROM capital WHERE bio=? AND at>? AND at<=? ORDER BY at,id',(bio,start,end))]


async def scan(reader,store,binding,span=200):
    bio=binding['bio_id'];wallet=evm_address(binding['wallet']);tokens=[evm_address(t) for t in binding['tokens']]
    if not tokens or len(tokens)>16 or not 1<=span<=1000:raise ValueError('Configure 1–16 monitored tokens and a bounded range')
    peers={evm_address(p) for p in binding.get('external_wallets',[])}
    own={evm_address(p) for p in binding.get('internal_wallets',[])}|{wallet}
    config=json.dumps({'tokens':sorted(tokens),'peers':sorted(peers),'own':sorted(own),'start_block':binding['start_block'],
                       'operations':binding.get('operations',{})},sort_keys=True)
    cursor_key=f'{bio}:{reader.chain_id}:{wallet}'
    cursor=store.db.execute('SELECT height,hash,config,blocked FROM cursors WHERE key=?',(cursor_key,)).fetchone()
    if cursor:
        if cursor[2]!=config or cursor[3]:raise ValueError('Scanner configuration changed or recovery review is required')
        if (await reader.block(cursor[0]))['hash']!=cursor[1]:
            with store.db:
                store.db.execute('UPDATE cursors SET blocked=1 WHERE key=?',(cursor_key,))
                store.db.execute('UPDATE coverage SET blocked=1 WHERE key=?',(cursor_key,))
            raise ValueError('Chain reorganization detected; capital results require review')
    head=await reader.height()-reader.confirmations
    start=cursor[0]+1 if cursor else int(binding['start_block'])
    if start<0:raise ValueError('Invalid starting block')
    if start>head:return {'scanned':0,'through_block':cursor[0] if cursor else None}
    end=min(head,start+span-1);boundary=await reader.block(end);first_block=await reader.block(start)
    topic='0x'+wallet[2:].rjust(64,'0');found={}
    for topics in ([TRANSFER,topic],[TRANSFER,None,topic]):
        logs=await reader.rpc('eth_getLogs',[{'fromBlock':hex(start),'toBlock':hex(end),'address':tokens,'topics':topics}])
        if not isinstance(logs,list):raise ValueError('Malformed transfer logs')
        for log in logs:
            number=uint(log['blockNumber'])
            if not start<=number<=end:raise ValueError('Transfer lies outside the requested range')
            key=(hash32(log['transactionHash']),uint(log['logIndex']))
            if key in found and found[key]!=log:raise ValueError('Conflicting log copies')
            found[key]=log
    records=[]
    for tx in sorted({k[0] for k in found}):
        receipt=await reader.receipt(tx,wallet,tokens)
        if receipt['status']!='confirmed_success':raise ValueError('A scanned transfer has no confirmed successful receipt')
        indices={t['log_index'] for t in receipt['transfers']}
        if not start<=receipt['block_number']<=end or any(index not in indices for found_tx,index in found if found_tx==tx):
            raise ValueError('Scanned logs differ from confirmed wallet transfers')
        transaction=await reader.rpc('eth_getTransactionByHash',[tx])
        if not transaction or hash32(transaction['hash'])!=tx:raise ValueError('Transaction identity missing')
        kind='review'
        explicit=binding.get('operations',{}).get(tx)
        if explicit and explicit.get('kind') in ('trade','bridge') and explicit.get('reference'):
            kind=explicit['kind']
        elif len(receipt['transfers'])==1:
            t=receipt['transfers'][0];sender=t['from'];recipient=t['to']
            if sender in own and recipient in own:kind='internal'
            else:
                data=transaction.get('input','').lower()
                # Only an exact direct ERC-20 transfer from an expected funding wallet.
                expected='0xa9059cbb'+recipient[2:].rjust(64,'0')+f'{abs(int(t["delta_raw"])):064x}'
                direct=(transaction.get('from','').lower()==sender and transaction.get('to','').lower()==t['token'] and data==expected)
                if direct and int(t['delta_raw'])>0 and sender in peers:kind='deposit'
                elif direct and int(t['delta_raw'])<0 and recipient in peers:kind='withdrawal'
        block=await reader.block(receipt['block_number'])
        if block['hash']!=receipt['block_hash']:raise ValueError('Receipt changed during classification')
        records.append((receipt,uint(block['timestamp']),kind))
    if (await reader.block(end))['hash']!=boundary['hash']:raise ValueError('Chain changed during scanning')
    # Records are idempotent; a crash before advancing the cursor safely scans them again.
    for receipt,at,kind in records:store.record(bio,receipt,at,kind)
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?,0)',(cursor_key,end,boundary['hash'],config))
        store.db.execute('INSERT INTO coverage VALUES (?,?,?,?,0) ON CONFLICT(key) DO UPDATE SET end=excluded.end',
            (cursor_key,bio,uint(first_block['timestamp']),uint(boundary['timestamp'])))
    return {'scanned':end-start+1,'through_block':end,'transactions':len(records),'classifications':[r[2] for r in records]}
