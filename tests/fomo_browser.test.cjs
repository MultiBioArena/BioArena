// Offline protocol/UI fixture: no browser profiles or network are accessed.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/bio_arena/fomo_browser.js','utf8');
const networks = JSON.parse(fs.readFileSync('src/bio_arena/fomo_networks.json','utf8'));
const cashToken = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const token = '0x'+'1'.repeat(40), wallet = '0x'+'2'.repeat(40), cashWallet = '1'.repeat(32);

function fixture(change={}) {
  const chain=change.chain||'robinhood', network=networks[chain]||networks.robinhood;
  const address=change.address||(chain==='solana'?'So11111111111111111111111111111111111111112':token);
  const receiving=chain==='solana'?cashWallet:wallet;
  let currentUrl=`https://fomo.family/tokens/${chain}/${change.pageAddress||address}`,navigations=0;
  let clock=101, handler, clicked=0, tab='Buy', value='2', feeAcknowledged=false,identityReads=0;
  const opts={live:true, networks, account:{profile:'fixture',user_id:'fixture-id',chain:'robinhood',chain_id:4663,
      token_wallet:wallet,cash_wallet:cashWallet},
    limits:{max_buy_usd:'10',max_fee_usd:'0.30',max_fee_bps:300,max_price_impact_bps:200,
      decision_age_seconds:45,acknowledge_network_fee:false},
    intent:{id:'one',bio_id:'worm',account_ref:'a',asset_id:chain+':'+address,chain,address,
      action:'BUY',amount_usd:'2',created_at:100}};
  if(change.sell) opts.intent={...opts.intent,action:'SELL',quantity_raw:'2000000',decimals:6};
  if(change.shadow)opts.live=false;
  if(change.acknowledge)opts.limits.acknowledge_network_fee=true;
  const q={originChainId:792703809,destinationChainId:network.relay_id,originAddress:cashWallet,destinationAddress:receiving,
    originTokenAddress:cashToken,destinationTokenAddress:address,amount:'2000000',inputHumanAmount:2,
    expectedOutHumanAmount:2, inAmountUsd:2,swapUsdValue:1.98,usdFees:{app:'0.009',relay:'0.02'},
    priceImpactPct:0.01,relaySwapId:'route'};
  if(change.sell)Object.assign(q,{originChainId:network.relay_id,destinationChainId:792703809,originAddress:receiving,destinationAddress:cashWallet,
    originTokenAddress:address,destinationTokenAddress:cashToken});
  Object.assign(q,change.quote||{});
  const native={feeTokenAddress:cashToken,feePayerAddress:'4'.repeat(32),flatFee:0.01,feeTierBps:0,
    swapUsdValue:1.98,expectedOutHumanAmount:2,dynamicSlippageBps:100,priceImpactPct:0.01,...change.nativeQuote};
  const request={inTokenId:change.sell?`${address}:${network.balance_id}`:`${cashToken}:1399811149`,
    outTokenId:change.sell?`${cashToken}:1399811149`:`${address}:${network.balance_id}`,amount:'2000000',...change.nativeRequest};
  const balanceRow=(address,networkId,decimals,raw,wallet)=>({
    balance:{tokenId:`${address}:${networkId}`,tokenAddress:address,balance:raw,address:wallet},
    tokenFilterResult:{priceUSD:'1',token:{address,networkId,decimals}}});
  const balances=()=>{
    const bought=clicked>0 && !change.timeout;
    const rows=[balanceRow(cashToken,1399811149,6,bought?(change.sell?'12000000':'8000000'):'10000000',cashWallet)];
    if(change.sell?!bought:bought)rows.push(balanceRow(change.balanceAddress||address,change.balanceChain||network.balance_id,6,change.wrongDelta?'1':'2000000',change.balanceWallet||receiving));
    if(change.extraHolding)rows.push(balanceRow('0x'+'3'.repeat(40),4663,6,bought&&change.changeOther?'99':'100',wallet));
    return {balances:rows,nativeEvmBalances:[]};
  };
  const response=(path,method,data)=>({url:()=>`https://prod-api.fomo.family${path}`,request:()=>({method:()=>method,postDataJSON:()=>request}),
    ok:()=>true,json:async()=>({success:true,responseObject:data})});
  const emit=async()=>{
    if(!handler)return;
    await handler(response('/v2/users/fixture-id/balances','GET',balances()));
    await handler(response('/swaps/v2','POST',change.native?{v1Swap:native}:{v2Swap:q}));
    if(change.native)await handler(response('/v2/users/fixture-id/swaps','GET',{swaps:clicked?[{
      id:'new-swap',signature:'3'.repeat(88),address:cashWallet,recipient:cashWallet,
      inNetworkId:1399811149,outNetworkId:1399811149,
      inTokenAddress:change.sell?address:cashToken,outTokenAddress:change.sell?cashToken:address,
      createdAt:new Date(clock*1000).toISOString(),...change.nativeHistory}]:[]}));
  };
  const page={
    evaluate:async(fn,requestId)=>{
      if(change.native){
        assert.ok(fn.toString().includes("method:'getTransaction'"));assert.equal(requestId,'3'.repeat(88));assert.equal(clicked,1);
        if(change.timeout)return null;
        const row=(mint,amount)=>({mint,owner:cashWallet,uiTokenAmount:{amount}});
        return {slot:7,blockTime:Math.floor(clock),transaction:{signatures:[requestId],message:{accountKeys:[{pubkey:cashWallet}]}},
          meta:{err:change.nativeFailure?'failed':null,preBalances:[100],postBalances:[change.nativeDebit?99:100],
            preTokenBalances:[row(cashToken,'10000000'),...(change.sell?[row(address,'2000000')]:[])],
            postTokenBalances:[row(cashToken,change.sell?'12000000':'8000000'),...(!change.sell?[row(change.wrongMint?cashWallet:address,'2000000')]:[])]}};
      }
      assert.ok(fn.toString().includes('https://api.relay.link/intents/status/v3?requestId='));
      assert.equal(requestId,'route');
      assert.equal(clicked,1);
      return {status:change.timeout?'pending':'success',
        originChainId:change.wrongRoute?1:q.originChainId,destinationChainId:q.destinationChainId,
        inTxHashes:['fixture-incoming-transaction'],txHashes:change.missingTransactions?[]:['fixture-outgoing-transaction']};
    },
    url:()=>currentUrl,
    goto:async url=>{currentUrl=url;navigations++;}, on:(_,h)=>{handler=h;},off:()=>{handler=null;},route:async()=>{},unroute:async()=>{},
    waitForTimeout:async(ms)=>{clock+=ms/1000;await emit();},
    locator:selector=>({count:async()=>selector.includes('/profile/')?(change.duplicateIdentity?2:change.missingIdentity?0:identityReads++<(change.identityDelay||0)?0:1):1,fill:async(v)=>{value=v;await emit();},inputValue:async()=>value,
      locator:()=>({count:async()=>1,getByRole:(...args)=>page.getByRole(...args)})}),
    getByRole:(role,query)=>{
      const name=query.name;
      if(name==='Buy'||name==='Sell')return {click:async()=>{tab=name;}};
      if(name==='100%')return {click:async()=>{await emit();}};
      if(String(name).includes('High network fee')){
        assert.equal(role,'checkbox');
        return {count:async()=>1,getAttribute:async()=>change.alreadyAcknowledged?'true':'false',click:async()=>{feeAcknowledged=true;}};
      }
      return {count:async()=>1,isEnabled:async()=>!change.disabled||feeAcknowledged,
        click:async()=>{assert.equal(tab,change.sell?'Sell':'Buy');clicked++;await emit();if(change.clickError)throw Error('page disconnected');}};
    }
  };
  class Clock extends Date {static now(){return clock*1000;}}
  const execute=vm.runInNewContext(source,{Date:Clock,Error});
  return {run:()=>execute(page,opts),clicks:()=>clicked,navigations:()=>navigations,options:opts};
}

for(const sell of [false,true])test(`two-position portfolio ${sell?'sell preserves other holding':'buy adds second holding'}`,async()=>{
  const f=fixture({sell,extraHolding:true});f.options.limits.max_positions=2;
  f.options.intent.known_positions=[{asset_id:'robinhood:0x'+'3'.repeat(40),raw_quantity:'100',decimals:6},
    ...(sell?[{asset_id:f.options.intent.asset_id,raw_quantity:'2000000',decimals:6}]:[])];
  const result=await f.run();assert.equal(result.status,'filled',JSON.stringify(result));assert.equal(f.clicks(),1);
  assert.equal(result.balances_after.positions.length,sell?1:2);
});

test('two-position settlement rejects changes to the unrelated holding',async()=>{
  const f=fixture({sell:true,extraHolding:true,changeOther:true});f.options.limits.max_positions=2;
  f.options.intent.known_positions=[{asset_id:'robinhood:0x'+'3'.repeat(40),raw_quantity:'100',decimals:6},
    {asset_id:f.options.intent.asset_id,raw_quantity:'2000000',decimals:6}];
  const result=await f.run();assert.equal(result.status,'unknown');assert.equal(f.clicks(),1);
});

test('two-position capacity cannot silently adopt an unrecorded balance',async()=>{
  const f=fixture({extraHolding:true});f.options.limits.max_positions=2;f.options.intent.known_positions=[];
  const result=await f.run();assert.equal(result.status,'blocked');assert.equal(f.clicks(),0);
});

test('absolute fee cap can explicitly replace the percentage cap',async()=>{
  const f=fixture({quote:{usdFees:{app:'0.1',relay:'0.4'}}});
  f.options.limits.max_fee_bps=null;f.options.limits.max_fee_usd='2';
  const result=await f.run();assert.equal(result.status,'filled');assert.equal(f.clicks(),1);
});

test('native quoted slippage uses its separate configured ceiling',async()=>{
  const f=fixture({chain:'solana',native:true,nativeQuote:{dynamicSlippageBps:2000}});
  f.options.limits.max_slippage_bps=2000;
  const result=await f.run();assert.equal(result.status,'filled');assert.equal(f.clicks(),1);
});

for(const sell of [false,true])test(`native Solana ${sell?'sell':'buy'} needs both chain and account receipt`,async()=>{
  const f=fixture({chain:'solana',native:true,sell}),r=await f.run();
  assert.equal(r.status,'filled',JSON.stringify(r));assert.equal(f.clicks(),1);
  assert.equal(r.settlement_provider,'solana');assert.equal(r.relay_status,null);
  assert.equal(r.solana_evidence.commitment,'confirmed');assert.equal(r.solana_evidence.owner_balances_verified,true);
});

for(const change of [
  {nativeQuote:{dynamicSlippageBps:2000}}, {nativeQuote:{flatFee:1}},
  {nativeQuote:{feeTokenAddress:wallet}}, {nativeQuote:{feePayerAddress:cashWallet}},
  {nativeRequest:{outTokenId:cashToken+':1399811149'}},
])test(`native preparation blocks ${JSON.stringify(change)}`,async()=>{
  const f=fixture({chain:'solana',native:true,...change}),r=await f.run();
  assert.equal(r.status,'blocked');assert.equal(f.clicks(),0);
});

for(const change of [{timeout:true},{nativeFailure:true},{nativeDebit:true},{wrongMint:true},
    {nativeHistory:{recipient:wallet}},{nativeHistory:{inNetworkId:792703809}}])
  test(`native receipt mismatch remains unknown ${JSON.stringify(change)}`,async()=>{
    const f=fixture({chain:'solana',native:true,...change}),r=await f.run();
    assert.equal(r.status,'unknown');assert.equal(f.clicks(),1);
  });

for(const chain of Object.keys(networks))test(`${chain} buys and sells with its own route and balance network`,async()=>{
  for(const sell of [false,true]){
    const f=fixture({chain,sell}),r=await f.run();
    assert.equal(r.status,'filled',JSON.stringify(r));assert.equal(f.clicks(),1);
    assert.equal(r.relay_evidence[sell?'originChainId':'destinationChainId'],networks[chain].relay_id);
    if(!sell)assert.ok(r.balances_after.positions[0].token_id.endsWith(':'+networks[chain].balance_id));
  }
});

test('Solana token case is retained in navigation and quote checks',async()=>{
  const address='So11111111111111111111111111111111111111112';
  const f=fixture({chain:'solana',pageAddress:address.toLowerCase()});
  assert.equal((await f.run()).status,'filled');assert.equal(f.navigations(),1);
  const wrong=fixture({chain:'solana',quote:{destinationTokenAddress:address.toLowerCase()}});
  assert.equal((await wrong.run()).status,'blocked');assert.equal(wrong.clicks(),0);
});

for(const change of [
  {chain:'unsupported'}, {chain:'solana',address:token}, {chain:'base',address:cashWallet},
  {chain:'solana',address:cashToken},
  {chain:'solana',quote:{destinationChainId:1399811149}},
  {chain:'solana',sell:true,balanceChain:792703809},
  {chain:'base',sell:true,balanceChain:56},
  {chain:'solana',sell:true,balanceWallet:wallet},
])test(`network mismatch is blocked: ${JSON.stringify(change)}`,async()=>{
  const f=fixture(change);assert.equal((await f.run()).status,'blocked');assert.equal(f.clicks(),0);
});

test('buy and sell each submit exactly once and reconcile the actual holding',async()=>{
  for(const sell of [false,true]){
    const f=fixture({sell}); const r=await f.run();
    assert.equal(r.status,'filled',JSON.stringify(r)); assert.equal(f.clicks(),1);
    assert.equal(r.balances_verified,true);
    assert.equal(r.relay_evidence.status,'success');
    assert.equal(r.balances_before.cash_raw,'10000000');
    assert.equal(r.position_after?.raw_quantity,sell?undefined:'2000000');
  }
});

test('shadow rehearses the same quote and never presses submit',async()=>{
  const f=fixture({shadow:true});const r=await f.run();
  assert.equal(r.status,'shadow');assert.equal(f.clicks(),0);
});

test('signed-in navigation can render after DOMContentLoaded',async()=>{
  const f=fixture({identityDelay:5});
  assert.equal((await f.run()).status,'filled');assert.equal(f.clicks(),1);
});

for(const key of ['missingIdentity','duplicateIdentity'])test(`${key} never bypasses account identity`,async()=>{
  const f=fixture({[key]:true}),result=await f.run();
  assert.equal(result.status,'blocked');assert.equal(result.clicked,false);
  assert.equal(result.reason,'Account profile link missing or ambiguous');assert.equal(f.clicks(),0);
});

for(const [name,change] of Object.entries({
  fee:{quote:{usdFees:{app:'0.009',relay:'0.2'}}},
  impact:{quote:{priceImpactPct:0.1}},
  negativeImpactLimit:{quote:{priceImpactPct:-0.1}},
  invalidImpact:{quote:{priceImpactPct:'NaN'}},
  contract:{quote:{destinationTokenAddress:wallet}},
  wallet:{quote:{destinationAddress:token}},
  chain:{quote:{destinationChainId:8453}},
  amount:{quote:{amount:'5000000'}},
  feeSchema:{quote:{usdFees:{relay:'0.01'}}},
  extraPosition:{extraHolding:true},
  platformBlock:{disabled:true},
}))test(`${name} blocks before any submit`,async()=>{
  const f=fixture(change); const r=await f.run();
  assert.equal(r.status,'blocked',JSON.stringify(r));assert.equal(f.clicks(),0);
});

test('configured fee acknowledgment is bounded and shadow cannot acknowledge',async()=>{
  const f=fixture({disabled:true,acknowledge:true});assert.equal((await f.run()).status,'filled');
  const expensive=fixture({disabled:true,acknowledge:true,quote:{usdFees:{relay:1,app:0.01}}});
  assert.equal((await expensive.run()).status,'blocked');assert.equal(expensive.clicks(),0);
  const shadow=fixture({disabled:true,acknowledge:true,shadow:true});const r=await shadow.run();
  assert.equal(r.status,'shadow');assert.equal(r.submit_disabled,true);
  const blocked=fixture({disabled:true,acknowledge:true,alreadyAcknowledged:true});
  assert.equal((await blocked.run()).status,'blocked');assert.equal(blocked.clicks(),0);
});

test('signed price improvement is valid within the same absolute impact cap',async()=>{
  const f=fixture({sell:true,quote:{priceImpactPct:-0.001}});
  assert.equal((await f.run()).status,'filled');
  assert.equal(f.clicks(),1);
});

for(const change of [{timeout:true},{wrongDelta:true},{wrongRoute:true},{missingTransactions:true},{clickError:true}])
test(`uncertain post-click evidence remains locked: ${JSON.stringify(change)}`,async()=>{
  const f=fixture(change);const r=await f.run();
  assert.equal(r.status,'unknown',JSON.stringify(r));assert.equal(f.clicks(),1);
});
