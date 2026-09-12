"""Non-submitting order review and durable intent status. No wallet or order API."""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from .meme_market import address_key
from .registry import validate_bio_id


def usd(value):
    try:amount=Decimal(str(value))
    except InvalidOperation:raise ValueError('Invalid monetary value') from None
    if not amount.is_finite() or amount<0:raise ValueError('Non-negative finite money is required')
    return amount


@dataclass(frozen=True)
class LivePlan:
    enabled: bool = False
    planned_capital_usd: str = '100'
    allowed_buys_usd: tuple = ('2','5','10')
    max_positions: int = 1
    max_snapshot_age_seconds: int = 15

    def __post_init__(self):
        if self.enabled:raise ValueError('Real execution adapter is not connected')
        if type(self.max_positions) is not int or not 1<=self.max_positions<=2:raise ValueError('Live preparation supports at most two holdings per Bio')
        if usd(self.planned_capital_usd)<=0 or not self.allowed_buys_usd or not 1<=self.max_snapshot_age_seconds<=30:
            raise ValueError('Invalid live preparation limits')
        if any(not 0<usd(x)<=min(usd(self.planned_capital_usd),Decimal('10')) for x in self.allowed_buys_usd):
            raise ValueError('Order size exceeds the 10 USD ceiling or planned capital')


def review(intent,account,quote,bindings,now,plan=None):
    """Review caller-supplied evidence. A passed review is not proof of a fill."""
    plan=plan or LivePlan();bio=validate_bio_id(intent['bio_id']);problems=[]
    if len(set(bindings.values()))!=len(bindings) or any(not value for value in bindings.values()):
        problems.append('Account bindings must be distinct and non-empty')
    if bio not in bindings or account.get('account_ref')!=bindings.get(bio) or account.get('identity_verified') is not True:
        problems.append('Account identity does not match this Bio')
    for label,record in [('account',account),('quote',quote)]:
        at=record.get('observed_at')
        if not isinstance(at,(float,int)) or not math.isfinite(at) or not 0<=now-at<=plan.max_snapshot_age_seconds:
            problems.append(f'Stale or missing {label} evidence')
    chain=intent['chain'];address=address_key(chain,intent['address'])
    asset=f'{chain}:{address}'
    if quote.get('asset_id')!=asset or quote.get('account_ref')!=account.get('account_ref'):
        problems.append('Quote is not bound to this account and chain/contract')
    if quote.get('executable_quote') is not True or quote.get('side')!=intent['action'] or not quote.get('route_id'):
        problems.append('An account-specific executable route is required')
    if not isinstance(quote.get('expires_at'),(int,float)) or not math.isfinite(quote['expires_at']) or not now<quote['expires_at']:
        problems.append('Executable quote is expired or has no expiry')
    positions=account.get('positions')
    if not isinstance(positions,list):
        positions=[];problems.append('Reconciled holdings are missing')
    if any(row.get('status') in ('prepared','submitted','unknown') for row in account.get('pending_orders',[])):
        problems.append('Resolve the outstanding order before preparing another')
    if intent['action']=='BUY':
        amount=usd(intent['amount_usd'])
        if amount not in [usd(x) for x in plan.allowed_buys_usd]:problems.append('Buy size must match the configured sizes within the 10 USD ceiling')
        if len(positions)>=plan.max_positions or any(p.get('asset_id')==asset for p in positions):problems.append('Live position capacity reached or token already held')
        if quote.get('amount_usd') is None or usd(quote['amount_usd'])!=amount:problems.append('Executable quote amount differs from the intent')
        if quote.get('total_cost_usd') is None or usd(quote['total_cost_usd'])<amount:
            problems.append('A complete cost quote is required')
        elif usd(account.get('cash_usd',0))<usd(quote['total_cost_usd']):problems.append('Insufficient cash including quoted costs')
    elif intent['action']=='SELL':
        held=next((p for p in positions if p.get('asset_id')==asset),None)
        quantity=usd(intent['quantity'])
        if held is None or not 0<quantity<=usd(held.get('quantity',0)):problems.append('Sell quantity is not covered by the matching contract holding')
        if quote.get('quantity') is None or usd(quote['quantity'])!=quantity:problems.append('Executable sell quantity differs from the intent')
        if quote.get('minimum_proceeds_usd') is None or usd(quote['minimum_proceeds_usd'])<=0 or quote.get('all_fees_included') is not True:
            problems.append('A positive minimum sell receipt including all fees is required')
    else:raise ValueError('Only BUY or SELL intents can be reviewed')
    if not (account.get('gas_sufficient') is True or quote.get('fee_sponsorship_verified') is True):
        problems.append('Native fee balance or route sponsorship is not verified')
    if account.get('balances_reconciled') is not True:problems.append('Displayed balances have not been reconciled')
    intent_hash=hashlib.sha256(json.dumps(intent,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return {'bio_id':bio,'asset_id':asset,'intent_sha256':intent_hash,'account_ref':account.get('account_ref'),'checked_at':now,'checks_passed':not problems,'blockers':problems,
            'can_submit':False,'execution_adapter':'not_connected','plan':asdict(plan),
            'scope':'Review of supplied evidence only; no order sent, signed, or confirmed'}


class IntentJournal:
    """Operator/import journal; importing a status is not remote chain verification."""
    transitions={'prepared':{'submitted','rejected'},'submitted':{'unknown','filled','rejected'},
                 'unknown':{'filled','rejected'},'filled':set(),'rejected':set()}

    def __init__(self,path):
        if str(path)!=':memory:':Path(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,bio TEXT,account TEXT,hash TEXT,status TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,intent_id TEXT,at REAL,payload TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_unresolved_account ON intents(account) WHERE status IN ('prepared','submitted','unknown');
        ''')

    def prepare(self,intent,account_ref,review_result,*,now=None):
        if not review_result['checks_passed'] or review_result['can_submit']:raise ValueError('A successful non-submitting preflight is required')
        now=time.time() if now is None else now
        if not 0<=now-review_result['checked_at']<=15:raise ValueError('Preflight evidence expired')
        asset=f"{intent['chain']}:{address_key(intent['chain'],intent['address'])}"
        if review_result['bio_id']!=intent['bio_id'] or review_result['asset_id']!=asset:raise ValueError('Preflight identity mismatch')
        encoded=json.dumps({'intent':intent,'account_ref':account_ref},sort_keys=True,allow_nan=False)
        fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
        with self.db:
            previous=self.db.execute('SELECT hash,status FROM intents WHERE id=?',(intent['id'],)).fetchone()
            if previous:
                if previous[0]!=fingerprint:raise ValueError('Intent ID reused with different order content')
                return previous[1]
            intent_hash=hashlib.sha256(json.dumps(intent,sort_keys=True,allow_nan=False).encode()).hexdigest()
            if review_result.get('intent_sha256')!=intent_hash or review_result.get('account_ref')!=account_ref:
                raise ValueError('Preflight order content or account mismatch')
            self.db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?)',(intent['id'],intent['bio_id'],account_ref,fingerprint,'prepared',encoded))
        return 'prepared'

    def observe(self,intent_id,event_id,status,evidence,now):
        if not event_id or not isinstance(evidence,dict) or not evidence.get('reference'):
            raise ValueError('A referenced imported order event is required')
        payload=json.dumps({'status':status,'evidence':evidence},sort_keys=True,allow_nan=False)
        with self.db:
            prior=self.db.execute('SELECT intent_id,payload FROM events WHERE event_id=?',(event_id,)).fetchone()
            if prior:
                if prior!=(intent_id,payload):raise ValueError('Conflicting event ID')
                return
            row=self.db.execute('SELECT status FROM intents WHERE id=?',(intent_id,)).fetchone()
            if not row or status not in self.transitions[row[0]]:raise ValueError('Invalid order transition; unknown orders cannot be resubmitted')
            self.db.execute('INSERT INTO events VALUES (?,?,?,?)',(event_id,intent_id,now,payload))
            self.db.execute('UPDATE intents SET status=? WHERE id=?',(status,intent_id))

    def close(self):self.db.close()
