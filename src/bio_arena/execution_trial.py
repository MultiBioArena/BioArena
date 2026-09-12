"""One operator-started Bio round trip, with durable stop/completion evidence."""
import hashlib
import json
import math
import re
from dataclasses import asdict

from .auto_execution import ExecutionLimits, encoded


def normalized_settings(value):
    result = json.loads(value)
    result['limits'] = asdict(ExecutionLimits(**result['limits']))
    return result


class ExecutionTrial:
    def __init__(self, store, trial_id, bio_id, now, seconds=3600, *, context=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',trial_id) or bio_id not in store.bindings:
            raise ValueError('Invalid trial ID or Bio binding')
        if type(seconds) is not int or not 60 <= seconds <= 86400 or not math.isfinite(now):
            raise ValueError('Trial duration must be 60–86400 seconds')
        self.store, self.id, self.bio = store, trial_id, bio_id
        self.db = store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS execution_trials(
            id TEXT PRIMARY KEY, bio TEXT, started_at REAL, deadline REAL,
            settings TEXT, terminal_result TEXT)''')
        settings_data={'seconds':seconds,'limits':store.limits.__dict__}
        if context is not None:
            settings_data['context']=context
        settings=encoded(settings_data)
        with self.db:
            previous=self.db.execute('SELECT bio,settings,deadline FROM execution_trials WHERE id=?',(trial_id,)).fetchone()
            if previous:
                if previous[0] != bio_id or normalized_settings(previous[1]) != settings_data:
                    raise ValueError('Trial identity and limits are immutable; inspect the existing trial')
                self.deadline=previous[2]
            else:
                if store.holding(bio_id) or store.pending(bio_id):
                    raise ValueError('Start a trial only with an empty, resolved execution account')
                active=self.db.execute('SELECT id FROM execution_trials WHERE bio=? AND terminal_result IS NULL AND deadline>?',
                                       (bio_id,now)).fetchone()
                if active:
                    raise ValueError('Resume the existing trial instead of starting another')
                self.deadline=now+seconds
                self.db.execute('INSERT INTO execution_trials VALUES (?,?,?,?,?,NULL)',
                                (trial_id,bio_id,now,self.deadline,settings))

    def state(self, now):
        terminal=self.db.execute('SELECT terminal_result FROM execution_trials WHERE id=?',(self.id,)).fetchone()[0]
        if terminal:
            return json.loads(terminal)
        result={'trial_id':self.id,'bio_id':self.bio,'phase':'waiting_buy','deadline':self.deadline,
                'complete':False,'real_orders_verified':0,'buy_id':None,'sell_id':None}
        orders=[]
        for key,status,payload,evidence in self.db.execute('SELECT id,status,intent,evidence FROM orders WHERE bio=? ORDER BY rowid',(self.bio,)):
            intent=json.loads(payload)
            if intent.get('trial_id')==self.id:
                orders.append((key,status,intent,json.loads(evidence)))
        fills=[row for row in orders if row[1]=='filled']
        result['real_orders_verified']=len(fills)
        unresolved=self.store.pending(self.bio)
        if unresolved:
            return {**result,'phase':'review_required','reason':'Unresolved order; no automatic retry','order_id':unresolved[0]}
        buys=[row for row in fills if row[2]['action']=='BUY']
        sells=[row for row in fills if row[2]['action']=='SELL']
        if len(buys)>1 or len(sells)>1 or (sells and not buys):
            return {**result,'phase':'review_required','reason':'Unexpected order sequence'}
        holding=self.store.holding(self.bio)
        if buys:
            buy=buys[0]
            result.update(phase='waiting_sell',buy_id=buy[0],asset_id=buy[2]['asset_id'],real_orders_verified=1)
            if sells:
                sell=sells[0]
                if (holding or sell[2]['asset_id']!=buy[2]['asset_id'] or sell[2]['quantity_raw']!=buy[3]['position_after']['raw_quantity']
                        or sell[3]['observed_at']<=buy[3]['observed_at'] or buy[3]['route_id']==sell[3]['route_id']):
                    return {**result,'phase':'review_required','reason':'Exit evidence does not close this entry'}
                deltas=[row[3].get('cash_delta_usd') for row in (buy,sell)]
                if not all(type(d) in (int,float) and math.isfinite(d) for d in deltas) or not deltas[0]<0<deltas[1]:
                    return {**result,'phase':'review_required','reason':'Complete cash deltas are missing'}
                result.update(phase='complete',complete=True,sell_id=sell[0],real_orders_verified=2,
                    completed_at=sell[3]['observed_at'],cash_change_usd=sum(deltas),
                    routes=[row[3]['route_id'] for row in (buy,sell)],
                    evidence_sha256=hashlib.sha256(encoded([row[3] for row in (buy,sell)]).encode()).hexdigest(),
                    scope='Matching FOMO-reported fills and balance deltas; independent chain finality not verified')
                with self.db:
                    self.db.execute('UPDATE execution_trials SET terminal_result=? WHERE id=?',(encoded(result),self.id))
                return result
            if not holding or holding['buy_id']!=buy[0]:
                return {**result,'phase':'review_required','reason':'The entry holding no longer matches the execution ledger'}
        elif holding:
            return {**result,'phase':'review_required','reason':'An unrelated position exists'}
        if now>=self.deadline:
            return {**result,'phase':'expired','reason':'Trial deadline reached; any remaining holding is not automatically liquidated'}
        return result

    def accepts(self, decision, now):
        state=self.state(now)
        if decision['bio_id']!=self.bio:
            return False
        if state['phase']=='waiting_buy':
            return decision['action']=='BUY'
        if state['phase']=='waiting_sell':
            return decision['action']=='SELL' and decision['asset']['asset_id']==state['asset_id']
        return False


class PortfolioTrial(ExecutionTrial):
    """Bound entries by time/count, then keep managing every verified holding."""

    def __init__(self, store, trial_id, bio_id, now, seconds=3600, *, entry_target=2, exit_settings=None):
        if type(entry_target) is not int or not 1 <= entry_target <= 20:
            raise ValueError('Invalid portfolio trial entry target')
        self.entry_target = entry_target
        super().__init__(store, trial_id, bio_id, now, seconds, context={
            'source_kind':'managed_portfolio_trial', 'entry_target':entry_target,
            'exit_settings':exit_settings or {}})

    def state(self, now):
        terminal = self.db.execute('SELECT terminal_result FROM execution_trials WHERE id=?', (self.id,)).fetchone()[0]
        if terminal:
            return json.loads(terminal)
        rows = []
        for key,status,payload,evidence in self.db.execute('SELECT id,status,intent,evidence FROM orders WHERE bio=? ORDER BY rowid', (self.bio,)):
            intent = json.loads(payload)
            if intent.get('trial_id') == self.id and status == 'filled':
                rows.append((key,intent,json.loads(evidence)))
        buys = {key:(intent,evidence) for key,intent,evidence in rows if intent['action'] == 'BUY'}
        sells = [(key,intent,evidence) for key,intent,evidence in rows if intent['action'] == 'SELL']
        holdings = self.store.holdings(self.bio)
        closing = now >= self.deadline or len(buys) >= self.entry_target
        result = {'trial_id':self.id,'bio_id':self.bio,'managed_portfolio':True,'deadline':self.deadline,
            'phase':'closing_positions' if holdings and closing else 'managing_positions' if holdings else 'waiting_buy',
            'complete':False,'real_orders_verified':len(rows),'entry_count':len(buys),
            'entry_target':self.entry_target,'open_positions':len(holdings),'completed_round_trips':len(sells)}
        if self.store.pending(self.bio):
            return {**result,'phase':'review_required','reason':'Unresolved order; no automatic resubmission'}
        if any(p['buy_id'] not in buys for p in holdings) or len(buys) > self.entry_target:
            return {**result,'phase':'review_required','reason':'Portfolio does not match trial entries'}
        closed = set()
        for _,intent,evidence in sells:
            entry = intent.get('entry_id')
            if entry not in buys or entry in closed:
                return {**result,'phase':'review_required','reason':'Exit cannot be paired to one verified entry'}
            buy_intent,buy_evidence = buys[entry]
            if (intent['asset_id'] != buy_intent['asset_id'] or intent['quantity_raw'] != buy_evidence['position_after']['raw_quantity']
                    or evidence['observed_at'] <= buy_evidence['observed_at'] or evidence['route_id'] == buy_evidence['route_id']):
                return {**result,'phase':'review_required','reason':'Exit evidence does not close its entry'}
            closed.add(entry)
        if {p['buy_id'] for p in holdings} != set(buys)-closed:
            return {**result,'phase':'review_required','reason':'A holding disappeared without a verified exit'}
        if closing and not holdings:
            if not buys:
                return {**result,'phase':'expired','reason':'Entry window ended without a verified buy'}
            deltas = [e.get('cash_delta_usd') for _,_,e in rows]
            if not all(type(d) in (int,float) and math.isfinite(d) for d in deltas):
                return {**result,'phase':'review_required','reason':'Cash evidence is incomplete'}
            if any(e['cash_delta_usd'] >= 0 for _,e in buys.values()) or any(e['cash_delta_usd'] <= 0 for _,_,e in sells):
                return {**result,'phase':'review_required','reason':'Cash evidence has an invalid direction'}
            result.update(phase='complete',complete=True,completed_at=max(e['observed_at'] for _,_,e in sells),
                entry_target_reached=len(buys)==self.entry_target,cash_change_usd=sum(deltas),
                evidence_sha256=hashlib.sha256(encoded(rows).encode()).hexdigest())
            with self.db:
                self.db.execute('UPDATE execution_trials SET terminal_result=? WHERE id=?', (encoded(result),self.id))
        return result

    def accepts(self, decision, now):
        state = self.state(now)
        if decision['bio_id'] != self.bio or state['phase'] not in ('waiting_buy','managing_positions','closing_positions'):
            return False
        if decision['action'] == 'SELL':
            return self.store.holding(self.bio, decision['asset']['asset_id']) is not None
        return (decision['action'] == 'BUY' and now < self.deadline and state['entry_count'] < self.entry_target
                and state['open_positions'] < self.store.limits.max_positions)
