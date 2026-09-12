"""Scan configured EVM wallets without signing, submitting or modifying accounts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import httpx
from bio_arena.capital_flows import FlowStore, scan
from bio_arena.evm_readonly import EvmReader


async def run(args):
    os.umask(0o077)
    config=json.loads(args.config.read_text());args.database.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    store=FlowStore(args.database)
    try:
        async with httpx.AsyncClient() as client:
            result=[]
            for binding in config['accounts']:
                network=config['networks'][binding['network']]
                reader=EvmReader(network['rpc_url'],network['chain_id'],client,network.get('confirmations',3))
                try:result.append({'bio_id':binding['bio_id'],**await scan(reader,store,binding,span=args.span)})
                except Exception:result.append({'bio_id':binding['bio_id'],'status':'review_required'})
            if args.valuations:
                for row in json.loads(args.valuations.read_text()):store.reconcile(row['bio_id'],row['tx_hash'],row['valuation'])
            args.output.write_text(json.dumps({'observed_at':time.time(),'accounts':result,'funds_moved':False},indent=2))
            print(json.dumps({'accounts':len(result),'review_required':sum(r.get('status')=='review_required' for r in result),'transactions_submitted':0}))
    finally:store.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--valuations',type=Path)
    p.add_argument('--span',type=int,default=200,help='Maximum confirmed blocks per account, 1–1000')
    asyncio.run(run(p.parse_args()))
