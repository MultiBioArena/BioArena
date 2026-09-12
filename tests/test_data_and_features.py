from pathlib import Path
import hashlib,json
import numpy as np
import pytest,yaml
from bio_arena.market import FeatureEncoder

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('key,n',[('worm',302),('larva',3016),('adult',10000)])
@pytest.mark.requires_data
def test_real_graph_integrity_and_port_reachability(key,n):
    folder=ROOT/'data/processed'/key
    m=json.loads((folder/'manifest.json').read_text())
    assert m['neurons']==n
    assert min(m['sensory_output_reachability'].values())>0
    for name,digest in m['processed_sha256'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
    z=np.load(folder/'graph.npz')
    assert z['pre'].min()>=0 and z['post'].max()<n
    assert len(z['pre'])==m['edges']
    for name,source in m['sources'].items():
        assert hashlib.sha256((ROOT/'data/raw'/name).read_bytes()).hexdigest()==source['sha256']

def test_features_are_causal_and_bounded():
    c=yaml.safe_load((ROOT/'configs/arena.yaml').read_text())
    a,b=FeatureEncoder(c),FeatureEncoder(c)
    prefix=[dict(id=str(i),price=100+i*.1,minute_volume=10+i) for i in range(20)]
    first=[a.encode(q) for q in prefix]
    second=[b.encode(q) for q in prefix]
    a.encode(dict(id='future',price=10000,minute_volume=99999))
    assert first==second
    for f in first:
        assert all(0<=f[k]<=1 for k in ['approach','avoid','volume','volatility'])
    assert first[0]['history_samples']==0 and first[0]['log_return']==0
