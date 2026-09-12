"""Run independent neural-noise seeds against common paper policy controls."""
import argparse
import hashlib
import json
from pathlib import Path
from bio_arena.comparison import capture, compare

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',help='Run ID or active')
    p.add_argument('--observations',type=int,default=240);p.add_argument('--seeds',type=int,nargs='+',default=[20260911,20260912,20260913])
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if not 60<=args.observations<=10000 or not 2<=len(args.seeds)<=8 or len(set(args.seeds))!=len(args.seeds):p.error('Use 60–10000 observations per Bio and 2–8 distinct seeds')
    root=Path(__file__).resolve().parents[1];run=json.loads((root/'runs/active-run.json').read_text())['run_id'] if args.run=='active' else args.run
    source=root/'runs'/run
    if source.resolve().parent!=(root/'runs').resolve():p.error('Use a local run ID')
    args.output.mkdir(parents=True,exist_ok=False)
    tape=capture(source,args.observations);encoded=json.dumps(tape,allow_nan=False).encode()
    (args.output/'tape.json').write_bytes(encoded)
    result=compare(root,tape,args.seeds);result['tape_sha256']=hashlib.sha256(encoded).hexdigest()
    result['code_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'src/bio_arena').glob('*.py')}
    (args.output/'results.json').write_text(json.dumps(result,allow_nan=False,indent=2))
    print(json.dumps({'source_run':run,'observations':result['observations'],'decisions':result['decisions'],'seeds':args.seeds,'saved':True}))
