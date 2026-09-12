"""Persistent single-compartment LIF with delayed signed chemical and electrical inputs.

Units: ms and mV. The engine uses forward Euler with a fixed dt. Connectivity
is empirical; membrane constants, weight normalization and port mappings are
experiment assumptions. This is not a physiological whole-animal emulator.
"""
from pathlib import Path
import hashlib
import base64
import json
import time
import numpy as np
from numba import njit
from .registry import seed_offset, validate_bio_id

@njit(cache=True)
def integrate(v, g, refractory, pending, cursor, indptr, targets, weights,
              gap_pre, gap_post, gap_weights, drive, sample_map, steps, dt,
              tau_m, tau_s, rest, threshold, reset, refractory_ms, delay, activity=None):
    n = len(v)
    counts = np.zeros(n, np.int32)
    raster = np.zeros((20, np.sum(sample_map >= 0)), np.int32)
    gap_current = np.zeros(n, np.float32)
    for t in range(steps):
        gap_current[:] = 0
        for e in range(len(gap_pre)):
            gap_current[gap_post[e]] += gap_weights[e] * (v[gap_pre[e]] - v[gap_post[e]])
        for i in range(n):
            g[i] += pending[cursor,i]
            pending[cursor,i] = 0
            if refractory[i] <= 0:
                v[i] += dt/tau_m*(rest-v[i]+g[i]+drive[i]+gap_current[i])
                if v[i] >= threshold:
                    counts[i] += 1
                    if activity is not None:
                        activity[i] |= np.uint32(1 << min(19,t*20//steps))
                    k = sample_map[i]
                    if k >= 0:
                        raster[min(19,t*20//steps),k] += 1
                    v[i] = reset
                    refractory[i] = refractory_ms
                    arrival = (cursor+delay) % len(pending)
                    for e in range(indptr[i],indptr[i+1]):
                        pending[arrival, targets[e]] += weights[e]
            else:
                refractory[i] = max(0.0,refractory[i]-dt)
            g[i] *= 1-dt/tau_s
        cursor = (cursor+1) % len(pending)
    return counts, raster, cursor

def model_signature(config):
    values={k:config[k] for k in ['lif','seed','simulated_ms','readout_rate_floor_hz']}
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

class Brain:
    def __init__(self, root: str | Path, key: str, config: dict, use_calibration=True):
        validate_bio_id(key)
        self.key = key
        self.config = config
        self.p = config['lif']
        folder = Path(root)/'data/processed'/key
        self.manifest = json.loads((folder/'manifest.json').read_text())
        for name, expected in self.manifest['processed_sha256'].items():
            if name=='calibration.json' and not use_calibration:continue
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
                raise ValueError(f'{key}: processed file hash mismatch: {name}')
        self.calibration=None
        if use_calibration:
            self.calibration=json.loads((folder/'calibration.json').read_text())
            if self.calibration['model_signature']!=model_signature(config):
                raise ValueError('Model parameters changed: rerun scripts/calibrate.py')
        self.nodes = json.loads((folder/'nodes.json').read_text())
        self.groups = {k:np.asarray(v,np.int32) for k,v in json.loads((folder/'mapping.json').read_text()).items()}
        z = np.load(folder/'graph.npz',allow_pickle=False)
        self.n = len(self.nodes)
        self.sample = z['sample']
        self.sample_map = np.full(self.n,-1,np.int32)
        self.sample_map[self.sample] = np.arange(len(self.sample),dtype=np.int32)
        pre,post,raw = z['pre'],z['post'],z['raw']
        incoming = np.bincount(post,weights=raw,minlength=self.n)
        normalization = np.maximum(1,incoming/self.p['incoming_normalization'])
        order = np.argsort(pre,kind='stable')
        self.targets = post[order].astype(np.int32)
        self.weights = (raw*z['sign']*self.p['synapse_scale_mv']/normalization[post])[order].astype(np.float32)
        self.indptr = np.r_[0,np.cumsum(np.bincount(pre,minlength=self.n))].astype(np.int32)
        self.gap_pre,self.gap_post = z['gap_pre'],z['gap_post']
        gap_in = np.bincount(self.gap_post,weights=z['gap_raw'],minlength=self.n)
        self.gap_weights = (z['gap_raw']/np.maximum(1,gap_in[self.gap_post])*self.p['gap_gain']).astype(np.float32)
        self.seed = int(config['seed']) + seed_offset(key, 'brain')
        self.reset()

    def restore(self, folder):
        path=Path(folder)
        state=json.loads((path/f'{self.key}.json').read_text())
        if state['seed']!=self.seed:raise ValueError('Brain checkpoint seed mismatch')
        with np.load(path/f'{self.key}.npz',allow_pickle=False) as saved:
            values={name:saved[name] for name in ('v','g','refractory','pending')}
        for name,value in values.items():
            if value.shape!=getattr(self,name).shape or value.dtype!=np.float32 or not np.isfinite(value).all():
                raise ValueError('Invalid neural checkpoint array')
        if not 0<=state['cursor']<self.pending.shape[0] or not isinstance(state['sequence'],int) or state['sequence']<0:
            raise ValueError('Invalid neural checkpoint cursor')
        for name,value in values.items():setattr(self,name,value.copy())
        self.cursor,self.sequence=state['cursor'],state['sequence']
        self.rng.bit_generator.state=state['rng_state']

    def reset(self):
        self.rng = np.random.default_rng(self.seed)
        self.v = np.full(self.n,self.p['resting_mv'],np.float32)
        self.g = np.zeros(self.n,np.float32)
        self.refractory = np.zeros(self.n,np.float32)
        self.delay = max(1,round(self.p['delay_ms']/self.p['dt_ms']))
        self.pending = np.zeros((self.delay+1,self.n),np.float32)
        self.cursor = self.sequence = 0

    def step(self, features: dict, duration_ms: float | None = None):
        start = time.perf_counter()
        duration_ms = duration_ms or self.config['simulated_ms']
        steps = round(duration_ms/self.p['dt_ms'])
        duration_ms = steps*self.p['dt_ms']
        drive = self.rng.normal(self.p['background_current_mv'],self.p['noise_std_mv'],self.n).astype(np.float32)
        sensory = []
        for channel in ['approach','avoid','volume','volatility']:
            value = float(np.clip(features[channel],0,1))
            current = self.p['sensory_base_mv']+self.p['sensory_gain_mv']*value
            drive[self.groups[channel]] += current
            sensory.append({'channel':channel,'value':value,'current_mv':current,'neurons':len(self.groups[channel])})
        activity=np.zeros(self.n,np.uint32)
        counts,raster,self.cursor = integrate(self.v,self.g,self.refractory,self.pending,self.cursor,
            self.indptr,self.targets,self.weights,self.gap_pre,self.gap_post,self.gap_weights,drive,self.sample_map,
            steps,self.p['dt_ms'],self.p['tau_membrane_ms'],self.p['tau_synapse_ms'],self.p['resting_mv'],
            self.p['threshold_mv'],self.p['reset_mv'],self.p['refractory_ms'],self.delay,activity)
        rates = {k:float(counts[v].mean()*1000/duration_ms) for k,v in self.groups.items()}
        a,b = rates['buy'],rates['sell']
        floor = self.config['readout_rate_floor_hz']
        raw_score = (a-b)/(a+b+floor)
        score=float(np.tanh((raw_score-self.calibration['center'])/self.calibration['scale'])) if self.calibration else raw_score
        if a+b==0:score=0.0
        threshold = self.config['readout_threshold']
        action = 'BUY' if score>threshold else 'SELL' if score < -threshold else 'HOLD'
        if action == 'HOLD':
            reason = 'Readout pools are silent. Position held.' if a+b==0 else 'Readout difference is within the hold threshold.'
        else:
            reason = 'Activity favors buying relative to the calibrated baseline.' if score>0 else 'Activity favors selling relative to the calibrated baseline.'
        def top(indices,limit=12):
            ordered = indices[np.argsort(-counts[indices],kind='stable')[:limit]]
            return [{'id':self.nodes[i]['id'],'name':self.nodes[i]['name'],'spikes':int(counts[i]),
                     'rate_hz':float(counts[i]*1000/duration_ms),'role':self.nodes[i]['role']} for i in ordered]
        bins,indices = np.nonzero(raster)
        events = [[int(t),int(i),int(raster[t,i])] for t,i in zip(bins,indices)]
        displayed_events = [events[i] for i in np.linspace(0,len(events)-1,600,dtype=int)] if len(events)>600 else events
        self.sequence += 1
        elapsed = (time.perf_counter()-start)*1000
        return {'bio_id':self.key,'sequence':self.sequence,'seed':self.seed,'simulated_ms':duration_ms,
                'total_simulated_ms':self.sequence*duration_ms,'compute_ms':round(elapsed,2),
                'action':action,'score':round(score,8),'raw_score':raw_score,'readout_calibration':self.calibration,
                'reason':reason,'threshold':threshold,
                'rate_floor_hz':floor,'readout_rates':rates,'sensory':sensory,
                'spikes':int(counts.sum()),'active_neurons':int(np.count_nonzero(counts)),
                'mean_rate_hz':float(counts.mean()*1000/duration_ms),
                'saturated_fraction':float(np.mean(counts*1000/duration_ms>300)),
                'sample_counts':counts[self.sample].tolist(),'raster':displayed_events,
                'raster_truncated':len(events)>600,'sample_size':len(self.sample),
                'sample_v_mv':np.round(self.v[self.sample],2).tolist(),
                'top_neurons':top(np.flatnonzero(counts)),'output_a':top(self.groups['buy']),
                'output_b':top(self.groups['sell']),
                'neural_activity':{'codec':'base64-le','neurons':self.n,'bins':20,
                    'counts_u16':base64.b64encode(counts.astype('<u2').tobytes()).decode(),
                    'spike_mask_u32':base64.b64encode(activity.astype('<u4').tobytes()).decode()},
                'counts_sha256':hashlib.sha256(counts.tobytes()).hexdigest()}

    def checkpoint(self, folder: str):
        path=Path(folder);path.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(path/f'{self.key}.npz',v=self.v,g=self.g,refractory=self.refractory,pending=self.pending)
        (path/f'{self.key}.json').write_text(json.dumps({'cursor':self.cursor,'sequence':self.sequence,
            'rng_state':self.rng.bit_generator.state,'seed':self.seed}))

_brain: Brain | None = None
def initialize(root, key, config, checkpoint=None):
    global _brain
    _brain = Brain(root,key,config)
    _brain.step(dict(approach=0,avoid=0,volume=0,volatility=0),1.0)
    _brain.reset()
    if checkpoint:_brain.restore(checkpoint)

def advance(features):
    return _brain.step(features)

def save_checkpoint(folder):
    _brain.checkpoint(folder)
