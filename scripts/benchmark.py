from pathlib import Path
import argparse,json,time
import psutil,yaml
from bio_arena.simulation import Brain

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rounds',type=int,default=6)
    parser.add_argument('--background',type=float)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    config=yaml.safe_load((root/'configs/arena.yaml').read_text())
    if args.background is not None:config['lif']['background_current_mv']=args.background
    records=[]
    for key in ['worm','larva','adult']:
        brain=Brain(root,key,config,use_calibration=args.background is None)
        brain.step(dict(approach=0,avoid=0,volume=0,volatility=0),1)
        brain.reset()
        for tick in range(args.rounds):
            f=dict(approach=1.0 if tick%2==0 else 0,avoid=0 if tick%2==0 else 1.0,volume=.5,volatility=.3)
            r=brain.step(f)
            row={k:r[k] for k in ['bio_id','sequence','compute_ms','active_neurons','spikes','action','score','readout_rates','saturated_fraction']}
            row['rss_mb']=psutil.Process().memory_info().rss/1024**2
            records.append(row);print(json.dumps(row),flush=True)
    (root/'output/benchmark.json').write_text(json.dumps({'config':config,'records':records},indent=2))
