"""Export matured paper-policy outcomes, without changing a running experiment."""
import argparse
import json
from pathlib import Path
import sqlite3

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('run');parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    db=sqlite3.connect(f'file:{root}/runs/{args.run}/events.sqlite?mode=ro',uri=True)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    counts={row[0]:0 for row in db.execute('SELECT DISTINCT bio_id FROM experiences')}
    with path.open('w') as output:
        for bio,payload in db.execute('SELECT bio_id,payload FROM experiences ORDER BY ts,id'):
            output.write(payload+'\n');counts[bio]+=1
    db.close()
    print(json.dumps({'file':str(path),'run_id':args.run,'samples':counts,'scope':'Matured transitions only; pending outcomes are excluded.'}))
