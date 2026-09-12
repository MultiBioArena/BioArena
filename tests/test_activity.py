import json

from bio_arena.activity import ActivityPolicy


def test_activity_is_independent_and_away_time_is_bounded():
    policies=[ActivityPolicy(b,7) for b in ('worm','adult','larva')]
    starts={p.bio:[] for p in policies}
    for now in range(3600):
        for p in policies:
            event=p.step(now,fresh=True)
            if event and event['state']=='exploring':starts[p.bio].append(now)
            assert p.away_time(now)<=60.00001
    assert all(len(v)>10 for v in starts.values())
    assert starts['worm'] != starts['adult'] != starts['larva']


def test_activity_alert_returns_without_delaying_a_trade_and_outage_blocks_trips():
    policy=ActivityPolicy('adult',7)
    policy.step(0,fresh=True);policy.next_trip=1
    event=policy.step(1,fresh=True)
    assert event['state']=='exploring'
    event=policy.step(2,fresh=True,risk=True)
    assert event['state']=='returning' and event['ends_at']<=5
    assert policy.step(6,fresh=True,risk=True)['state']=='attentive'
    for now in range(100,1000):
        policy.step(now,fresh=False)
        assert policy.current['state']=='observing' and not policy.trip
    assert policy.step(1001,fresh=True,paused=True)['state']=='resting'


def test_recovery_preserves_presentation_stream_and_upcoming_decision_keeps_desk():
    policy=ActivityPolicy('worm',3);policy.step(0,fresh=True);policy.next_trip=1
    policy.step(1,fresh=True,due_at=3)
    assert policy.current['state']=='attentive'
    restored=ActivityPolicy('worm',3);restored.restore(json.loads(json.dumps(policy.checkpoint())))
    for now in range(10,200):
        assert policy.step(now,fresh=True)==restored.step(now,fresh=True)
