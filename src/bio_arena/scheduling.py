"""Reproducible per-brain deadlines with a minimum gap between completed decisions."""
import random


class DecisionSchedule:
    def __init__(self,config,keys):
        settings=config.get('decision_schedule',{})
        self.keys=list(keys)
        self.interval=float(config['tick_seconds'])
        self.jitter=float(settings.get('jitter_seconds',0))
        self.gap=float(settings.get('minimum_gap_seconds',0))
        if self.interval<=0 or not 0<=self.jitter<self.interval or self.gap<0:
            raise ValueError('Invalid decision cadence')
        self.offsets={k:float(settings.get('initial_offsets',{}).get(k,0)) for k in keys}
        if any(v<0 for v in self.offsets.values()):raise ValueError('Negative initial offset')
        self.random={k:random.Random(config['seed']+100003*(i+1)) for i,k in enumerate(keys)}
        self.next_at={k:None for k in keys}
        self.last_completed=None

    def start(self,now):
        self.next_at={k:now+self.offsets[k] for k in self.keys}

    def effective_due(self,key):
        due=self.next_at[key]
        if due is None:return None
        return max(due,self.last_completed+self.gap) if self.last_completed is not None else due

    def ready(self,now,active):
        eligible=[k for k in active if self.effective_due(k) is not None and self.effective_due(k)<=now]
        return min(eligible,key=lambda k:self.next_at[k]) if eligible else None

    def dispatch(self,key,now):
        scheduled=self.next_at[key]
        interval=self.interval+self.random[key].uniform(-self.jitter,self.jitter)
        self.next_at[key]=now+interval
        return {'mode':'staggered','scheduled_at':scheduled,'started_at':now,
                'interval_seconds':interval,'next_at':self.next_at[key],
                'minimum_gap_seconds':self.gap,'encoding':'per_bio_decisions'}

    def completed(self,now):
        self.last_completed=now
