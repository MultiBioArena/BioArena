"""Durable strategy-to-executor observations, including signals that never submit."""
import json
import sqlite3

from .auto_execution import encoded


def require_execution_check(store, check_id, bio):
    """A policy trial can require a verified operator check on this same account."""
    try:
        row = store.db.execute('SELECT bio,settings,terminal_result FROM execution_trials WHERE id=?',
                               (check_id,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row and store.mode == 'live' and row[0] == bio:
        settings, result = json.loads(row[1]), json.loads(row[2] or '{}')
        if (settings.get('context', {}).get('source_kind') == 'operator_execution_check'
                and result.get('complete') is True and result.get('real_orders_verified') == 2):
            return
    raise ValueError('The required execution check has not verified both real fills for this Bio')


class PolicyExecutionAudit:
    def __init__(self, store, scope):
        self.store, self.scope = store, scope
        store.db.execute('''CREATE TABLE IF NOT EXISTS policy_signals(
            scope TEXT, id TEXT, bio TEXT, at REAL, action TEXT, status TEXT,
            reason TEXT, decision TEXT, result TEXT, PRIMARY KEY(scope,id))''')

    def process(self, decision, executor, trial, now):
        if trial and not trial.accepts(decision, now):
            result = {'status':'filtered', 'reason': 'Bio chose HOLD' if decision['action']=='HOLD'
                      else 'Signal does not match the current trial leg or held token'}
        else:
            result = executor.process(decision)
        reason = result.get('reason') or (result.get('evidence') or {}).get('reason')
        with self.store.db:
            self.store.db.execute('INSERT OR IGNORE INTO policy_signals VALUES (?,?,?,?,?,?,?,?,?)',
                (self.scope, decision['id'], decision['bio_id'], now, decision['action'],
                 result['status'], reason, encoded(decision), encoded(result)))
        return result

    def summary(self):
        result = {}
        for bio in self.store.bindings:
            rows = self.store.db.execute('SELECT action,status,reason,at FROM policy_signals WHERE scope=? AND bio=?',
                                         (self.scope,bio)).fetchall()
            actions, outcomes, reasons = {}, {}, {}
            for action, status, reason, _ in rows:
                actions[action] = actions.get(action,0)+1
                outcomes[status] = outcomes.get(status,0)+1
                if reason:
                    reasons[reason] = reasons.get(reason,0)+1
            result[bio] = {'observed':len(rows), 'actions':actions, 'outcomes':outcomes,
                           'reasons':reasons, 'latest_at':max((r[3] for r in rows), default=None)}
        return result
