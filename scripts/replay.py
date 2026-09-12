"""Recompute recorded neural decisions and ledger fills from a saved run."""
import argparse,hashlib,json,sqlite3
from pathlib import Path
import yaml
from bio_arena.simulation import Brain
from bio_arena.trading import PaperBroker
from bio_arena.market import FeatureEncoder
from bio_arena.policy import OpportunityPolicy

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run');parser.add_argument('--steps',type=int,default=20)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    folder=root/'runs'/args.run
    config=yaml.safe_load((folder/'arena.yaml').read_text())
    manifest=json.loads((folder/'manifest.json').read_text())
    for key,metadata in manifest['connectomes'].items():
        for name,digest in metadata['processed_sha256'].items():
            assert hashlib.sha256((root/'data/processed'/key/name).read_bytes()).hexdigest()==digest, f'Data version mismatch: {key}/{name}'
    brains={k:Brain(root,k,config) for k in ['worm','adult','larva']};broker=PaperBroker(config)
    encoder=FeatureEncoder(config);sequence=None;features=None;quote=None
    independent={k:FeatureEncoder(config) for k in brains}
    policies={k:OpportunityPolicy(config) for k in brains} if 'opportunity_policy' in config else {}
    db=sqlite3.connect(f'file:{folder}/events.sqlite?mode=ro',uri=True)
    rows=db.execute('SELECT payload FROM decisions WHERE seq<=? ORDER BY seq,bio_id',(args.steps,)).fetchall()
    if not rows:raise SystemExit('No completed decisions to replay')
    for row in rows:
        d=json.loads(row[0])
        if d.get('schedule',{}).get('encoding')=='per_bio_decisions':
            quote=d['input_quote'];features=independent[d['bio_id']].encode(quote)
        elif d['market_sequence']!=sequence:
            sequence=d['market_sequence'];quote=d['input_quote'];features=encoder.encode(quote)
        assert d['input_quote']==quote and d['features']==features, f'Input / feature mismatch: {d["id"]}'
        r=brains[d['bio_id']].step(features)
        assert r['counts_sha256']==d['counts_sha256'],f'Spike mismatch: {d["id"]}'
        assert r['score']==d['score'] and r['action']==d.get('neural_action',d['action']),f'Neural decision mismatch: {d["id"]}'
        extra={}
        if 'policy' in d:
            policy=policies[d['bio_id']].decide(r,quote,broker.accounts[d['bio_id']])
            assert policy==d['policy'],f'Policy mismatch: {d["id"]}'
            r.update(action=policy['action'],reason=policy['reason'])
            extra['target_position_fraction']=policy['target_position_fraction']
        assert r['action']==d['action'],f'Trade intent mismatch: {d["id"]}'
        if d['execution_quote'] and d['fill']['reason']!='Paused by the operator.':
            f=broker.execute(dict(id=d['id'],bio_id=d['bio_id'],created_at=d['created_at'],
                action=r['action'],score=r['score'],reason=r['reason'],**extra),d['execution_quote'])
            assert f==d['fill'],f'Fill mismatch: {d["id"]}'
        print(d['id'],r['action'],'input + spikes + decision + fill verified')
    print(f'PASS: {len(rows)} decisions replayed')
