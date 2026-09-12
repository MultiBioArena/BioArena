"""Archive stopped runs after checksum verification; active lineage is excluded."""
import argparse
import json
from pathlib import Path
from bio_arena.archival import archive, protected_runs

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run');p.add_argument('--minimum-age-hours',type=float,default=24)
    p.add_argument('--prune-verified',action='store_true');args=p.parse_args();root=Path(__file__).resolve().parents[1]
    if args.minimum_age_hours<0:p.error('Age cannot be negative')
    keys=[args.run] if args.run else [p.name for p in (root/'runs').iterdir() if p.is_dir() and p.name not in protected_runs(root)]
    results=[]
    for key in keys:
        try:
            result=archive(root,key,args.minimum_age_hours*3600,args.prune_verified)
            results.append({k:result[k] for k in ('run_id','original_bytes','archive_bytes','verified')})
        except ValueError:
            if args.run:raise
    print(json.dumps({'archives':results,'pruned_verified_sources':args.prune_verified}))
