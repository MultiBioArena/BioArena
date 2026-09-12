"""Bounded process-health decisions, separate from model state and trading."""


class HealthWatch:
    def __init__(self,started,timeout=180,unreachable=30):
        self.timeout=timeout;self.unreachable=unreachable;self.last_reply=started
        self.last_progress=started;self.sequence=None;self.run=None

    def check(self,state,now):
        if state is None:
            return 'http_unreachable' if now-self.last_reply>=self.unreachable else None
        self.last_reply=now
        if state.get('status')=='error':return 'engine_error'
        identity=(state.get('run_id'),state.get('sequence'))
        if identity!=(self.run,self.sequence):
            self.run,self.sequence=identity;self.last_progress=now
        if (state.get('paused') or state.get('status') in ('finished','waiting_market','warming')
                or not state.get('market_fresh') or not any(b['account']['alive'] for b in state.get('bios',[]))):
            self.last_progress=now;return None
        if now-self.last_progress>=self.timeout:return 'decision_stalled'
        return None
