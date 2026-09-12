import asyncio
import json
import time

import httpx
import pytest

from bio_arena.evm_readonly import EvmReader, TRANSFER

WALLET='0x'+'1'*40
TOKEN='0x'+'2'*40
OTHER='0x'+'3'*40
TX='0x'+'a'*64
BLOCK='0x'+'b'*64


def fixture(*, pending=False, reverted=False, chain=4663, reorg=False, duplicate=False, old=False, depth=10):
    calls=[];block_reads=0
    def handle(request):
        nonlocal block_reads
        p=json.loads(request.content);calls.append(p);method=p['method']
        log={'address':TOKEN,'topics':[TRANSFER,'0x'+OTHER[2:].rjust(64,'0'),'0x'+WALLET[2:].rjust(64,'0')],
             'data':'0x'+f'{2**100:064x}','logIndex':'0x0','blockHash':BLOCK,'transactionHash':TX,'removed':False}
        if method=='eth_getBlockByNumber':
            block_reads+=1
            result={'number':p['params'][0],'hash':'0x'+'c'*64 if reorg and block_reads>1 else BLOCK,
                    'timestamp':hex(int(time.time())-(200 if old else 1))}
        else:
            result={'eth_chainId':hex(chain),'eth_blockNumber':hex(100+depth),'eth_getBalance':'0x10',
                    'eth_getCode':'0x6000','eth_call':'0x'+f'{2**100:064x}',
                    'eth_getTransactionReceipt':None if pending else {'transactionHash':TX,'blockNumber':hex(100),
                    'blockHash':BLOCK,'status':'0x0' if reverted else '0x1','gasUsed':'0x64',
                    'effectiveGasPrice':'0x2','from':OTHER,'logs':[] if reverted else [log,log] if duplicate else [log]}}[method]
        return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':result})
    return httpx.MockTransport(handle),calls


def test_fixed_block_balances_exact_raw_integer_and_no_writes():
    async def run():
        transport,calls=fixture()
        async with httpx.AsyncClient(transport=transport) as client:
            reader=EvmReader('https://rpc.invalid',4663,client)
            result=await reader.balances(WALLET,[TOKEN])
            assert result['tokens_raw'][TOKEN]==str(2**100)
            assert result['native_wei']=='16' and result['block_number']==107
            with pytest.raises(ValueError,match='read-only'):
                await reader.rpc('eth_sendRawTransaction',['0xsigned'])
        assert all(p['params'][-1]=='0x6b' for p in calls if p['method'] in ('eth_getBalance','eth_getCode','eth_call'))
    asyncio.run(run())


@pytest.mark.parametrize('changes',[{'chain':1},{'reorg':True},{'old':True}])
def test_bad_balance_evidence_rejected(changes):
    async def run():
        transport,_=fixture(**changes)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError):await EvmReader('https://rpc.invalid',4663,client).balances(WALLET,[TOKEN])
    asyncio.run(run())


@pytest.mark.parametrize('changes,status',[({},'confirmed_success'),({'pending':True},'pending_or_unknown'),
    ({'reverted':True},'confirmed_reverted'),({'depth':1},'confirming')])
def test_receipt_status_is_not_mistaken_for_a_verified_trade(changes,status):
    async def run():
        transport,_=fixture(**changes)
        async with httpx.AsyncClient(transport=transport) as client:
            result=await EvmReader('https://rpc.invalid',4663,client).receipt(TX,WALLET,[TOKEN])
        assert result['status']==status and not result['trade_verified']
        if status=='confirmed_success':
            assert result['token_deltas_raw'][TOKEN]==str(2**100)
            assert result['transaction_fee_wei']=='200' and result['fee_payer']==OTHER
            assert result['transfers'][0]['event_id']==f'4663:{TX}:0'
    asyncio.run(run())


@pytest.mark.parametrize('changes',[{'reorg':True},{'duplicate':True}])
def test_receipt_reorg_and_duplicate_logs_rejected(changes):
    async def run():
        transport,_=fixture(**changes)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError):await EvmReader('https://rpc.invalid',4663,client).receipt(TX,WALLET,[TOKEN])
    asyncio.run(run())
