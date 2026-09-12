"""Read-only EVM balance and receipt evidence. Never signs or submits transactions."""
import re
import time

import httpx

from .voting import evm_address

TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
METHODS = frozenset(('eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
                    'eth_getBalance', 'eth_getCode', 'eth_call', 'eth_getTransactionReceipt',
                    'eth_getLogs', 'eth_getTransactionByHash'))


def hash32(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
        raise ValueError('Expected a 32-byte hash')
    return value.lower()


def uint(value, word=False):
    pattern = r'0x[0-9a-fA-F]{64}' if word else r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Invalid unsigned RPC value')
    return int(value, 16)


class EvmReader:
    def __init__(self, url, chain_id, client, confirmations=3):
        if not url.startswith(('https://', 'http://')) or not isinstance(chain_id, int) or chain_id<=0:
            raise ValueError('An operator-configured RPC and chain ID are required')
        if not isinstance(confirmations, int) or not 1<=confirmations<=1000:
            raise ValueError('Confirmation depth must be configured')
        self.url, self.chain_id, self.client, self.confirmations = url, chain_id, client, confirmations

    async def rpc(self, method, params):
        if method not in METHODS:
            raise ValueError('Only read-only RPC methods are permitted')
        try:
            response = await self.client.post(self.url, json={'jsonrpc':'2.0','id':1,'method':method,'params':params}, timeout=15)
            response.raise_for_status(); payload=response.json()
            if payload.get('id') != 1 or payload.get('error') or 'result' not in payload:
                raise ValueError('Invalid RPC response')
            return payload['result']
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ValueError('Read-only chain evidence is unavailable') from None

    async def height(self):
        if uint(await self.rpc('eth_chainId', [])) != self.chain_id:
            raise ValueError('RPC chain does not match the configured account chain')
        return uint(await self.rpc('eth_blockNumber', []))

    async def block(self, height):
        block=await self.rpc('eth_getBlockByNumber', [hex(height),False])
        if not block or uint(block['number'])!=height:
            raise ValueError('Missing canonical block')
        hash32(block['hash'])
        return block

    async def balances(self, wallet, tokens):
        wallet=evm_address(wallet);tokens=list(dict.fromkeys(evm_address(t) for t in tokens))
        if len(tokens)>16:raise ValueError('At most sixteen configured token balances per snapshot')
        height=await self.height()-self.confirmations
        if height<0:raise ValueError('Insufficient chain history')
        block=await self.block(height);tag=hex(height)
        timestamp=uint(block['timestamp'])
        if not -5<=time.time()-timestamp<=120:
            raise ValueError('Chain snapshot is stale')
        native=uint(await self.rpc('eth_getBalance',[wallet,tag]));balances={}
        for token in tokens:
            code=await self.rpc('eth_getCode',[token,tag])
            if not isinstance(code,str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+',code):
                raise ValueError('Configured token has no contract code')
            amount=uint(await self.rpc('eth_call',[{'to':token,'data':'0x70a08231'+wallet[2:].rjust(64,'0')},tag]),word=True)
            balances[token]=str(amount)
        if (await self.block(height))['hash']!=block['hash']:
            raise ValueError('Chain reorganized during the balance lookup')
        return {'chain_id':self.chain_id,'wallet':wallet,'block_number':height,'block_hash':block['hash'],
                'block_time':timestamp,'observed_at':time.time(),'native_wei':str(native),'tokens_raw':balances,
                'scope':'On-chain raw balances only; no USD valuation or FOMO cash aggregation'}

    async def receipt(self, tx_hash, wallet, tokens):
        tx_hash=hash32(tx_hash);wallet=evm_address(wallet);tokens={evm_address(t) for t in tokens}
        height=await self.height()
        receipt=await self.rpc('eth_getTransactionReceipt',[tx_hash])
        base={'chain_id':self.chain_id,'tx_hash':tx_hash,'wallet':wallet,'trade_verified':False,'observed_at':time.time()}
        if receipt is None:return {**base,'status':'pending_or_unknown'}
        if hash32(receipt['transactionHash'])!=tx_hash:raise ValueError('Receipt transaction mismatch')
        number=uint(receipt['blockNumber']);block=await self.block(number)
        if hash32(receipt['blockHash'])!=hash32(block['hash']):raise ValueError('Receipt is not on the canonical chain')
        depth=height-number
        if depth<self.confirmations:return {**base,'status':'confirming','confirmation_depth':depth}
        status=uint(receipt['status'])
        if status not in (0,1):raise ValueError('Invalid receipt status')
        deltas={t:0 for t in tokens};transfers=[];seen=set()
        for log in receipt['logs']:
            topics=log.get('topics',[])
            if log.get('address','').lower() not in tokens or not topics or topics[0].lower()!=TRANSFER:continue
            if len(topics)!=3:continue  # NFT Transfer events have a different indexed layout.
            if log.get('removed') or hash32(log['transactionHash'])!=tx_hash or hash32(log['blockHash'])!=hash32(block['hash']):
                raise ValueError('Transfer evidence is removed or belongs to another transaction')
            index=uint(log['logIndex'])
            if index in seen:raise ValueError('Duplicate transfer log')
            seen.add(index);token=evm_address(log['address']);amount=uint(log['data'],word=True)
            addresses=[]
            for topic in topics[1:]:
                word=hash32(topic)
                if word[2:26]!='0'*24:raise ValueError('Invalid indexed transfer address')
                addresses.append('0x'+word[-40:])
            sender,recipient=addresses
            delta=amount*(int(recipient==wallet)-int(sender==wallet))
            if sender==wallet or recipient==wallet:
                deltas[token]+=delta
                transfers.append({'event_id':f'{self.chain_id}:{tx_hash}:{index}','token':token,'delta_raw':str(delta),
                                  'from':sender,'to':recipient,'log_index':index})
        if (await self.block(number))['hash']!=block['hash']:raise ValueError('Receipt reorganized during verification')
        return {**base,'status':'confirmed_success' if status else 'confirmed_reverted',
                'block_number':number,'block_hash':block['hash'],'confirmation_depth':depth,
                'transaction_fee_wei':str(uint(receipt['gasUsed'])*uint(receipt['effectiveGasPrice'])),
                'fee_payer':evm_address(receipt['from']),
                'token_deltas_raw':{t:str(v) for t,v in deltas.items()},'transfers':transfers,
                'scope':'Single-chain receipt; does not prove swap intent, cross-chain completion, USD value or external deposit classification'}
