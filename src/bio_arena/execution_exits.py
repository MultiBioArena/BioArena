"""Persistent exits for real holdings, independent of the paper portfolio ledger."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

import httpx

from .meme_market import DEX_CHAINS, address_key, pair_quote


@dataclass(frozen=True)
class ExitSettings:
    minimum_hold_seconds: int = 120
    maximum_hold_seconds: int = 1800
    position_stop_fraction: float = 0.15
    exit_margin_bps: float = 100
    retry_seconds: int = 30
    quote_max_age_seconds: int = 30

    def __post_init__(self):
        for key,low,high in [('minimum_hold_seconds',0,3600),('maximum_hold_seconds',60,86400),
                              ('retry_seconds',5,300),('quote_max_age_seconds',1,60)]:
            value=getattr(self,key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Invalid exit setting: {key}')
        if self.maximum_hold_seconds < self.minimum_hold_seconds:
            raise ValueError('Maximum holding time is shorter than minimum holding time')
        if (type(self.position_stop_fraction) not in (int,float) or not 0 < self.position_stop_fraction < 1
                or type(self.exit_margin_bps) not in (int,float) or not math.isfinite(self.exit_margin_bps) or self.exit_margin_bps <= 0):
            raise ValueError('Invalid exit risk threshold')


class LiveExitManager:
    def __init__(self, store, settings, quote_client):
        self.store,self.settings,self.client=store,settings,quote_client
        self.cache,self.fetched,self.observations={},{},{}
        store.db.execute('''CREATE TABLE IF NOT EXISTS exit_requests(
            entry_id TEXT PRIMARY KEY,bio TEXT,asset TEXT,created_at REAL,reason TEXT,
            source_id TEXT,last_attempt REAL,attempts INTEGER)''')

    def quote(self, asset, state, now):
        rows=state.get('assets') or []
        q=next((r.get('quote') for r in rows if r.get('asset_id')==asset['asset_id']),None)
        if q and q.get('asset_id')==asset['asset_id'] and 0 <= now-q.get('received_at',0) <= self.settings.quote_max_age_seconds:
            self.cache[asset['asset_id']]=q
        else:
            key=asset['asset_id']
            if now-self.fetched.get(key,-1e30)>=10:
                self.fetched[key]=now
                try:
                    response=self.client.get('https://api.dexscreener.com/tokens/v1/'+DEX_CHAINS[asset['chain']]+'/'+asset['address'])
                    response.raise_for_status()
                    rows=response.json()
                    if isinstance(rows,list):
                        fresh=pair_quote(asset,rows,now,self.cache.get(key,{}).get('pair_address'))
                        if fresh:self.cache[key]=fresh
                except (httpx.HTTPError,ValueError,KeyError,TypeError):
                    pass
            q=self.cache.get(key)
        if q and 0 <= now-q.get('received_at',0) <= self.settings.quote_max_age_seconds:
            price=q.get('price')
            if type(price) in (int,float) and math.isfinite(price) and price>0:return q
        return None

    def review(self, bio, state, decisions, now, *, close_all=False):
        result=[]
        if self.store.pending(bio):return result
        for p in self.store.holdings(bio):
            entry=p['buy_id'];chain,address=p['asset_id'].split(':',1)
            asset={'asset_id':p['asset_id'],'chain':chain,'address':address_key(chain,address)}
            evidence=json.loads(self.store.db.execute('SELECT evidence FROM orders WHERE id=?',(entry,)).fetchone()[0])
            debit=evidence.get('cash_delta_usd')
            cost=-debit if type(debit) in (int,float) and math.isfinite(debit) and debit<0 else None
            q=self.quote(asset,state,now)
            value=int(p['raw_quantity'])/10**p['decimals']*q['price'] if q else None
            pnl=value/cost-1 if value is not None and cost else None
            age=now-p['opened_at']
            source=None;reason=None
            # A matching Bio SELL becomes a durable request. A later HOLD or a
            # paper exit cannot cancel the responsibility to close this entry.
            matching=[d for d in decisions if d.get('bio_id')==bio and d.get('action')=='SELL'
                and (d.get('asset') or {}).get('asset_id')==p['asset_id']
                and p['opened_at'] <= d.get('created_at',0) <= now]
            if matching:
                d=max(matching,key=lambda row:row['created_at'])
                reason='Bio requested exit from this real holding';source=d['id']
            if pnl is not None and pnl <= -self.settings.position_stop_fraction:
                reason='Real position drawdown limit reached';source=q['id']
            if not reason and age >= self.settings.minimum_hold_seconds and state.get('status')=='running' and 0 <= now-state.get('server_time',0) <= 10:
                participant=next((b for b in state.get('bios',[]) if b.get('id')==bio),{})
                score=next((e for e in participant.get('selection',[]) if e.get('asset_id')==p['asset_id']),{})
                prediction=score.get('prediction_net_bps')
                if (q and score.get('model_version') and type(prediction) in (int,float) and math.isfinite(prediction)
                        and prediction < -self.settings.exit_margin_bps
                        and 0 <= now-score.get('evaluated_at',0) <= self.store.limits.decision_age_seconds):
                    reason='Current Bio readout favors exiting the real holding';source=score.get('observation_id')
            if age >= self.settings.maximum_hold_seconds:
                reason='Maximum real holding time reached';source=None
            if close_all:
                reason='Entry window ended; close the remaining real holding';source=None
            if reason:
                with self.store.db:
                    self.store.db.execute('INSERT OR IGNORE INTO exit_requests VALUES (?,?,?,?,?,?,NULL,0)',
                        (entry,bio,p['asset_id'],now,reason,source))
            request=self.store.db.execute('SELECT reason,source_id,last_attempt,attempts FROM exit_requests WHERE entry_id=?',(entry,)).fetchone()
            self.observations[p['asset_id']]={'bio_id':bio,'asset':asset,'age_seconds':age,'cost_basis_usd':cost,
                'reference_value_usd':value,'return_fraction':pnl,'price_fresh':q is not None,
                'exit_requested':request is not None,'reason':request[0] if request else 'Watching the real holding'}
            if not request or request[2] is not None and now-request[2]<self.settings.retry_seconds:
                continue
            # Unknown/attempting receipts lock the whole account in ExecutionStore.
            # Only a definitively unsubmitted attempt can reach a later review.
            attempt=request[3]+1
            key='exit-'+hashlib.sha256(entry.encode()).hexdigest()[:20]+'-'+str(attempt)
            result.append({'id':key,'bio_id':bio,'created_at':now,'action':'SELL','asset':asset,
                'reason':request[0],'policy':{'exploration':False,'model_version':None,'exit_manager':True},
                'intent':{'action':'SELL','asset_id':p['asset_id'],'risk_exit':request[0] in (
                    'Real position drawdown limit reached','Maximum real holding time reached',
                    'Entry window ended; close the remaining real holding')},
                'exit_evidence':{'entry_id':entry,'source_decision_id':request[1],
                    'attempt':attempt,'reference_quote':q,'cost_basis_usd':cost,'return_fraction':pnl,
                    'settings':asdict(self.settings)}})
            with self.store.db:
                self.store.db.execute('UPDATE exit_requests SET last_attempt=?,attempts=? WHERE entry_id=?',(now,attempt,entry))
        held={p['asset_id'] for p in self.store.holdings(bio)}
        self.observations={k:v for k,v in self.observations.items() if v['bio_id']!=bio or k in held}
        return result

    def summary(self):
        return list(self.observations.values())
