"""Operator-requested execution acceptance check, independent of strategy signals."""
import json
import re
import time

from .auto_execution import AutoExecutor
from .execution_trial import ExecutionTrial


class ExecutionCheck:
    def __init__(self, store, adapter, bio, token, check_id, *, seconds=600,
                 clock=time.time, sleep=time.sleep, enabled=lambda: True, observe=lambda _: None):
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', token):
            raise ValueError('A Robinhood token contract is required')
        self.store, self.bio, self.token = store, bio, token.lower()
        self.clock, self.sleep, self.enabled, self.observe = clock, sleep, enabled, observe
        self.asset_id = 'robinhood:'+self.token
        self.trial = ExecutionTrial(store, check_id, bio, clock(), seconds,
            context={'source_kind':'operator_execution_check','asset_id':self.asset_id})
        self.executor = AutoExecutor(store, adapter, clock=clock, enabled=enabled,
            trial_id=check_id, source_kind='operator_execution_check')
        self.last = None
        self.allow_exit_retry = False

    def attempts(self, action):
        rows = []
        for key,status,payload,evidence in self.store.db.execute(
                'SELECT id,status,intent,evidence FROM orders WHERE bio=? AND action=? ORDER BY rowid',
                (self.bio,action)):
            intent = json.loads(payload)
            if intent.get('trial_id')==self.trial.id and intent['asset_id']==self.asset_id:
                rows.append((key,status,json.loads(evidence)))
        return rows

    def resume_exit_window(self, seconds=600):
        """Explicit operator restart after reconciliation; never admit another BUY."""
        if type(seconds) is not int or not 60 <= seconds <= 3600:
            raise ValueError('Exit window must be 60–3600 seconds')
        now = self.clock()
        state = self.trial.state(now)
        if state['complete']:
            return
        holding = self.store.holding(self.bio)
        exits = self.attempts('SELL')
        retry_safe = not exits or (len(exits)<3 and exits[-1][1]=='blocked' and exits[-1][2].get('clicked') is False)
        if (state['phase'] not in ('waiting_sell','expired') or state['real_orders_verified'] != 1
                or not holding or holding['asset_id'] != self.asset_id
                or holding['buy_id'] != state['buy_id'] or self.store.pending(self.bio)
                or not retry_safe):
            raise ValueError('Resume requires one verified entry and an unsubmitted exit within the retry limit')
        self.allow_exit_retry = bool(exits)
        deadline = max(self.trial.deadline,now+seconds)
        with self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS execution_exit_windows(
                trial_id TEXT, at REAL, previous_deadline REAL, deadline REAL, reason TEXT)''')
            self.store.db.execute('INSERT INTO execution_exit_windows VALUES (?,?,?,?,?)',
                (self.trial.id,now,self.trial.deadline,deadline,'Operator restarted the verified entry exit only'))
            self.store.db.execute('UPDATE execution_trials SET deadline=? WHERE id=?',(deadline,self.trial.id))
        self.trial.deadline = deadline

    def snapshot(self, stage, *, running=True):
        result = {**self.store.report(), 'last':self.last, 'error':None,
            'source':'Operator-requested execution acceptance check; no Bio strategy signal',
            'execution_kind':'operator_check', 'check_stage':stage,
            'live_enabled':self.store.mode=='live', 'process_running':running,
            'independent_chain_finality_verified':False, 'trial':self.trial.state(self.clock())}
        self.observe(result)
        return result

    def decision(self, action, key=None):
        return {'id':key or self.trial.id+':'+action,'bio_id':self.bio,'created_at':self.clock(),
            'action':action,'reason':'Operator-requested execution acceptance check; not a Bio strategy decision',
            'asset':{'asset_id':self.asset_id,'chain':'robinhood','address':self.token},
            'intent':{'action':action,'asset_id':self.asset_id},
            'policy':{'exploration':False,'model_version':None},
            'source_kind':'operator_execution_check'}

    def execute_action(self, action):
        while True:
            expected = 'waiting_buy' if action=='BUY' else 'waiting_sell'
            if not self.enabled() or self.trial.state(self.clock())['phase']!=expected:
                return {'status':'held','reason':'Execution stopped or check leg no longer active'}
            previous = self.attempts(action)
            if previous:
                _,status,evidence = previous[-1]
                explicit_exit = action=='SELL' and self.allow_exit_retry
                if (len(previous)>=3 or status!='blocked' or evidence.get('clicked') is not False
                        or not (evidence.get('retryable') is True or explicit_exit)):
                    return {'status':'held','reason':'Previous attempt is not eligible for an automatic retry'}
                self.allow_exit_retry = False
            key = self.trial.id+':'+action+(f':retry-{len(previous)+1}' if previous else '')
            result = self.executor.process(self.decision(action,key))
            receipt = result.get('evidence') or {}
            if not (result['status']=='blocked' and receipt.get('clicked') is False
                    and receipt.get('retryable') is True and len(previous)<2):
                return result
            self.last = result
            self.snapshot('preparing_'+action.lower())
            self.sleep(2)

    def run(self):
        phase = self.trial.state(self.clock())['phase']
        if phase == 'complete':
            return self.snapshot('complete', running=False)
        if not self.enabled():
            return self.snapshot('stopped', running=False)
        if phase not in ('waiting_buy','waiting_sell'):
            return self.snapshot('incomplete', running=False)
        if phase == 'waiting_buy':
            self.snapshot('preparing_buy')
            self.last = self.execute_action('BUY')
            if self.last['status'] != 'filled':
                # Cost/risk rejections and ambiguous submits remain incomplete.
                stage = 'quote_only' if self.last['status']=='shadow' else 'incomplete'
                return self.snapshot(stage, running=False)
            self.snapshot('buy_verified')
        # Respect the configured execution cooldown even in an acceptance check.
        # A restart with a verified entry continues toward SELL without a second BUY.
        holding = self.store.holding(self.bio)
        if not holding:
            return self.snapshot('incomplete', running=False)
        ready = holding['opened_at']+self.store.limits.cooldown_seconds
        while self.clock() < ready:
            if not self.enabled():
                return self.snapshot('stopped', running=False)
            if self.trial.state(self.clock())['phase'] != 'waiting_sell':
                return self.snapshot('incomplete', running=False)
            self.snapshot('exit_cooldown')
            self.sleep(min(1,ready-self.clock()))
        if not self.enabled() or self.trial.state(self.clock())['phase'] != 'waiting_sell':
            return self.snapshot('incomplete', running=False)
        self.snapshot('preparing_sell')
        self.last = self.execute_action('SELL')
        complete = self.trial.state(self.clock())['complete']
        return self.snapshot('complete' if complete else 'incomplete', running=False)
