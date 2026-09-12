from pathlib import Path
import base64
import hashlib
import numpy as np
import pytest,yaml
from bio_arena.simulation import Brain,integrate

ROOT=Path(__file__).resolve().parents[1]

def single(drive,steps=1000):
    v=np.array([-52.],np.float32);g=np.zeros(1,np.float32);ref=np.zeros(1,np.float32)
    counts,_,_=integrate(v,g,ref,np.zeros((2,1),np.float32),0,
        np.array([0,0],np.int32),np.array([],np.int32),np.array([],np.float32),
        np.array([],np.int32),np.array([],np.int32),np.array([],np.float32),
        np.array([drive],np.float32),np.array([0],np.int32),steps,.1,20.,5.,-52.,-45.,-52.,2.2,1)
    return v[0],counts[0]

def test_subthreshold_leak_matches_analytic_solution():
    v,spikes=single(3,200)
    expected=-52+3*(1-np.exp(-20/20))
    assert abs(v-expected)<.005
    assert spikes==0

def test_constant_drive_firing_rate_matches_lif_interval():
    _,spikes=single(10,10000)
    first=-20*np.log(1-7/10)
    expected=1+int((1000-first)/(first+2.2))
    assert abs(spikes-expected)<=1

@pytest.mark.parametrize('key',['worm','adult','larva'])
@pytest.mark.requires_data
def test_identical_seed_and_input_reproduce_spikes_and_decisions(key):
    config=yaml.safe_load((ROOT/'configs/arena.yaml').read_text())
    brain=Brain(ROOT,key,config)
    tape=[dict(approach=.7,avoid=0,volume=.4,volatility=.1),dict(approach=0,avoid=.8,volume=.9,volatility=.5)]
    first=[brain.step(f) for f in tape]
    brain.reset()
    second=[brain.step(f) for f in tape]
    assert [r['counts_sha256'] for r in first]==[r['counts_sha256'] for r in second]
    assert [r['score'] for r in first]==[r['score'] for r in second]
    assert sum(r['readout_rates']['buy']+r['readout_rates']['sell'] for r in first)>0
    for result in first:
        activity=result['neural_activity']
        counts=np.frombuffer(base64.b64decode(activity['counts_u16']),dtype='<u2')
        masks=np.frombuffer(base64.b64decode(activity['spike_mask_u32']),dtype='<u4')
        assert len(counts)==len(masks)==brain.n
        assert counts.sum()==result['spikes']
        assert hashlib.sha256(counts.astype(np.int32).tobytes()).hexdigest()==result['counts_sha256']
        assert np.array_equal(counts>0,masks>0)
        assert np.all(masks<2**20)
        assert counts[brain.sample].tolist()==result['sample_counts']
        for time_bin,sample_index,_ in result['raster']:
            assert int(masks[brain.sample[sample_index]]) & (1<<time_bin)

def test_no_input_and_no_noise_do_not_invent_spikes():
    v,spikes=single(0,1000)
    assert v==-52 and spikes==0
