"""Inspect operator-configured raw EVM balances or a transaction, without signing."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import httpx
from bio_arena.evm_readonly import EvmReader


async def run(args):
    config=json.loads(args.config.read_text())
    async with httpx.AsyncClient() as client:
        reader=EvmReader(config['rpc_url'],config['chain_id'],client,config.get('confirmations',3))
        if args.tx:
            result=await reader.receipt(args.tx,config['wallet'],config.get('tokens',[]))
        else:
            result=await reader.balances(config['wallet'],config.get('tokens',[]))
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as file:json.dump(result,file,indent=2,allow_nan=False)
    os.chmod(args.output,0o600)
    print(json.dumps({'saved':True,'chain_id':result['chain_id'],'status':result.get('status','balances_observed'),
                      'trade_verified':False,'transactions_submitted':0}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tx')
    asyncio.run(run(parser.parse_args()))
