"""Export a read-only training and paper-account evidence report."""
import argparse
import json
from pathlib import Path
from bio_arena.evaluation import report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    source=root/'runs'/args.run
    if source.resolve().parent!=(root/'runs').resolve():parser.error('Use a run ID from this workspace')
    result=report(source);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'run_id':result['run_id'],'decision_sequence':result['decision_sequence'],'report':str(args.output)}))
