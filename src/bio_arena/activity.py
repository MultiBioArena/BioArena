"""Recorded presentation behavior; independent of trading and learner random streams."""
from collections import deque
import random

from .registry import seed_offset


class ActivityPolicy:
    VERSION = 'activity-v1'

    def __init__(self,bio,seed,settings=None):
        self.bio=bio
        self.random=random.Random(int(seed)+seed_offset(bio,'activity'))
        self.settings={'window_seconds':600,'away_fraction':.10,'minimum_gap_seconds':60,
                       'minimum_trip_seconds':5,'maximum_trip_seconds':12, **(settings or {})}
        s=self.settings
        if not (0<s['away_fraction']<=.1 and s['window_seconds']>=60
                and 60<=s['minimum_gap_seconds'] and 5<=s['minimum_trip_seconds']<=s['maximum_trip_seconds']<=12):
            raise ValueError('Activity must reserve at least 90% of the observation window for the desk')
        self.completed=deque();self.trip=None;self.next_trip=None;self.event=0
        self.current={'version':self.VERSION,'state':'observing','reason':'Waiting for market context',
                      'event_id':f'{bio}:0','started_at':0,'ends_at':None,'presentation_only':True}

    def away_time(self,now):
        cutoff=now-self.settings['window_seconds']
        while self.completed and self.completed[0][1]<=cutoff:self.completed.popleft()
        used=sum(end-max(start,cutoff) for start,end in self.completed)
        if self.trip:used+=max(0,now-max(self.trip['start'],cutoff))
        return used

    def _set(self,state,reason,now,ends_at=None):
        if self.current['state']==state and self.current['reason']==reason:return None
        self.event+=1
        self.current={'version':self.VERSION,'state':state,'reason':reason,'event_id':f'{self.bio}:{self.event}',
                      'started_at':now,'ends_at':ends_at,'presentation_only':True}
        return dict(self.current,bio_id=self.bio)

    def step(self,now,*,fresh,alive=True,paused=False,phase='waiting',due_at=None,risk=False,trade_at=None):
        if self.next_trip is None:self.next_trip=now+self.random.uniform(65,100)
        if self.trip and now>=self.trip['end']:
            self.completed.append((self.trip['start'],self.trip['end']))
            self.trip=None;self.next_trip=now+self.random.uniform(60,100)
        alert=(risk or phase!='waiting' or (due_at is not None and due_at-now<=5)
               or (trade_at is not None and 0<=now-trade_at<=6))
        blocked=paused or not alive or not fresh or alert
        if self.trip and blocked:
            # A three-second presentation return never delays the trading engine.
            if self.current['state']!='returning':
                self.trip['end']=min(self.trip['end'],now+3)
                return self._set('returning','Market or risk alert: return to the desk',now,self.trip['end'])
            return None
        if self.trip:return None
        if paused or not alive:return self._set('resting','Arena paused or account inactive',now)
        if not fresh:return self._set('observing','Waiting for fresh market data',now)
        if alert:return self._set('attentive','Reviewing a decision or monitoring risk',now)
        s=self.settings;duration=self.random.uniform(s['minimum_trip_seconds'],s['maximum_trip_seconds']) if now>=self.next_trip else 0
        if (duration and (due_at is None or due_at-now>duration+5)
                and self.away_time(now)+duration<=s['window_seconds']*s['away_fraction']):
            self.trip={'start':now,'end':now+duration}
            return self._set('exploring','Quiet market window within the activity budget',now,now+duration)
        return self._set('observing','Watching candidates and positions',now)

    def checkpoint(self):
        return {'version':self.VERSION,'bio_id':self.bio,'random_state':self.random.getstate(),
                'completed':list(self.completed),'trip':self.trip,'next_trip':self.next_trip,
                'event':self.event,'current':dict(self.current)}

    def restore(self,payload):
        from .recovery import tuples
        if payload['version']!=self.VERSION or payload['bio_id']!=self.bio:raise ValueError('Activity checkpoint mismatch')
        self.random.setstate(tuples(payload['random_state']))
        self.completed=deque(tuple(row) for row in payload['completed'])
        self.trip=payload['trip'];self.next_trip=payload['next_trip'];self.event=payload['event'];self.current=payload['current']
