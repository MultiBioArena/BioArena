"""Fit readout centering/scaling on a fixed synthetic stimulus tape, never market PnL."""
from pathlib import Path
import hashlib,json
import numpy as np
import yaml
from bio_arena.simulation import Brain,model_signature

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    config=yaml.safe_load((root/'configs/arena.yaml').read_text())
    protocol=[dict(approach=a,avoid=b,volume=v,volatility=s) for a,b,v,s in [
        (0,0,.5,.2),(.9,0,.5,.2),(0,.9,.5,.2),(0,0,.2,.1),(.3,0,.8,.7),(0,.3,.8,.7),(.7,0,.3,.4),(0,.7,.3,.4)]]
    for k in ['worm','larva','adult']:
        brain=Brain(root,k,config,use_calibration=False)
        brain.rng=np.random.default_rng(brain.seed+1000000)
        scores=[];activity=[];saturation=[]
        for tick in range(40):
            result=brain.step(protocol[tick%len(protocol)])
            if tick>=8:
                scores.append(result['raw_score'])
                activity.append(result['readout_rates']['buy']+result['readout_rates']['sell'])
                saturation.append(result['saturated_fraction'])
        if np.mean(activity)<=0:raise RuntimeError(k+': readout pools do not respond')
        calibration={'method':'32 fixed symmetric synthetic stimuli after 8 warmup windows; no market data, labels or PnL',
            'model_signature':model_signature(config),'seed':brain.seed+1000000,'protocol':protocol,
            'center':float(np.mean(scores)),'scale':max(.03,2*float(np.std(scores))),
            'raw_score_std':float(np.std(scores)),'mean_output_rate_sum_hz':float(np.mean(activity)),
            'max_saturated_fraction':float(max(saturation)),
            'formula':'raw=(mean_hz_A-mean_hz_B)/(mean_hz_A+mean_hz_B+rate_floor); score=tanh((raw-center)/scale); silent outputs override score=0'}
        folder=root/'data/processed'/k
        path=folder/'calibration.json';path.write_text(json.dumps(calibration,indent=2))
        manifest=json.loads((folder/'manifest.json').read_text())
        manifest['processed_sha256']['calibration.json']=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['calibration']=calibration
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        print(k,json.dumps({x:calibration[x] for x in ['center','scale','mean_output_rate_sum_hz','max_saturated_fraction']}),flush=True)
