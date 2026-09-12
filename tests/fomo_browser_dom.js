// Runs only in an empty QA browser, with EVERY request intercepted locally.
(async function checkBrowser(page, execute, networks) {
  const wallet='0x'+'2'.repeat(40), cashWallet='1'.repeat(32);
  const cash='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
  const api='https://prod-api.fomo.family';
  const results=[];
  for (const scenario of ['buy','sell','shadow','fee_block','network_fee_ack','network_fee_shadow','delayed_identity','unknown','portfolio_buy','portfolio_sell',
      'native_buy','native_sell','native_shadow','native_slippage_block',
      ...['solana','base','bnb','ethereum','monad'].flatMap(chain=>[chain+'_buy',chain+'_sell'])]) {
    let submitted=0, seen=0;
    const native=scenario.startsWith('native_');
    const chain=native?'solana':networks[scenario.split('_')[0]]?scenario.split('_')[0]:'robinhood',network=networks[chain];
    const token=chain==='solana'?'So11111111111111111111111111111111111111112':'0x'+'1'.repeat(40);
    const receiving=chain==='solana'?cashWallet:wallet;
    const sell=scenario.endsWith('sell'), warning=scenario.startsWith('network_fee_'),portfolio=scenario.startsWith('portfolio_');
    const other='0x'+'3'.repeat(40);
    const row=(a,n,d,b,w)=>({balance:{tokenId:`${a}:${n}`,tokenAddress:a,balance:b,address:w},
      tokenFilterResult:{token:{address:a,networkId:n,decimals:d},priceUSD:'1'}});
    const balance=()=>({nativeEvmBalances:[],balances:[
      row(cash,1399811149,6,submitted?(sell?'12000000':'8000000'):'10000000',cashWallet),
      ...((sell?!submitted:submitted)?[row(token,network.balance_id,6,'2000000',receiving)]:[]),
      ...(portfolio?[row(other,4663,6,'100',wallet)]:[])]});
    const q={originChainId:sell?network.relay_id:792703809,destinationChainId:sell?792703809:network.relay_id,
      originAddress:sell?receiving:cashWallet,destinationAddress:sell?cashWallet:receiving,
      originTokenAddress:sell?token:cash,destinationTokenAddress:sell?cash:token,
      amount:'2000000',inputHumanAmount:2,expectedOutHumanAmount:2,inAmountUsd:2,swapUsdValue:1.97,
      usdFees:{app:'0.009',relay:scenario==='fee_block'?'0.20':'0.02'},priceImpactPct:0.01,relaySwapId:'fixture-route'};
    const nq={feeTokenAddress:cash,feePayerAddress:'4'.repeat(32),flatFee:0.01,feeTierBps:0,
      swapUsdValue:1.98,expectedOutHumanAmount:2,dynamicSlippageBps:scenario==='native_slippage_block'?2000:100,priceImpactPct:0.01};
    const quoteRequest={inTokenId:(sell?token:cash)+':1399811149',outTokenId:(sell?cash:token)+':1399811149',amount:'2000000'};
    const html=`<!doctype html><html><body>${scenario==='delayed_identity'?'':'<a href="/profile/fixture">Profile</a>'}
      <section id="trade-panel">
      <button id="buy">Buy</button><button id="sell">Sell</button>
      <input placeholder="0" value="2"><button id="max">100%</button>
      <button id="submit" ${warning?'disabled':''}>${sell?'Sell':'Buy'} TEST</button>
      ${warning?'<div id="warning" role="checkbox" aria-checked="false" tabindex="0">High network fee <span>Network fee: $0.02</span></div>':''}
      </section><aside><button id="quick-percent">100%</button></aside>
      <script>
        ${scenario==='delayed_identity'?"setTimeout(()=>{const link=document.createElement('a');link.href='/profile/fixture';link.textContent='Profile';document.body.prepend(link)},500);":''}
        const base=${JSON.stringify(api)};
        const get=path=>fetch(base+path).catch(()=>{});
        const quote=()=>fetch(base+'/swaps/v2',{method:'POST',body:JSON.stringify(${JSON.stringify(quoteRequest)})}).catch(()=>{});
        const warning=document.querySelector('#warning');
        document.querySelector('#quick-percent').onclick=()=>{throw Error('Wrong quick-action control');};
        if(warning)warning.onclick=()=>{warning.setAttribute('aria-checked','true');document.querySelector('#submit').disabled=false;};
        document.querySelector('#buy').onclick=()=>{document.querySelector('#submit').textContent='Buy TEST';quote();};
        document.querySelector('#sell').onclick=()=>{document.querySelector('#submit').textContent='Sell TEST';quote();};
        document.querySelector('input').oninput=quote;
        document.querySelector('#max').onclick=quote;
        document.querySelector('#submit').onclick=async()=>{await fetch(base+'/fixture/submit',{method:'POST'});get('/v2/users/fixture-id/balances');};
        setInterval(()=>get('/v2/users/fixture-id/balances'),250);
        ${native?"setInterval(()=>get('/v2/users/fixture-id/swaps'),250);":''}
        setInterval(quote,500);
      </script></body></html>`;
    const intercept=async route=>{
      seen++;
      const url=route.request().url();
      if(native && url==='https://api.mainnet-beta.solana.com/'){
        const headers={'access-control-allow-origin':'*','access-control-allow-headers':'Content-Type','access-control-allow-methods':'POST'};
        if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers});
        const request=route.request().postDataJSON();
        if(request.method!=='getTransaction'||request.params[0]!=='3'.repeat(88))throw Error('Unexpected native RPC');
        const row=(mint,amount)=>({mint,owner:cashWallet,uiTokenAmount:{amount}});
        return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify({result:{slot:7,blockTime:Math.floor(Date.now()/1000),
          transaction:{signatures:['3'.repeat(88)],message:{accountKeys:[{pubkey:cashWallet}]}},
          meta:{err:null,preBalances:[100],postBalances:[100],
            preTokenBalances:[row(cash,'10000000'),...(sell?[row(token,'2000000')]:[])],
            postTokenBalances:[row(cash,sell?'12000000':'8000000'),...(!sell?[row(token,'2000000')]:[])]}}})});
      }
      if(url===`https://fomo.family/tokens/${chain}/${token}`)
        return route.fulfill({status:200,contentType:'text/html',body:html});
      if(url==='https://api.relay.link/intents/status/v3?requestId=fixture-route')
        return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},
          body:JSON.stringify({status:submitted&&scenario!=='unknown'?'success':'pending',
            originChainId:q.originChainId,destinationChainId:q.destinationChainId,
            inTxHashes:['fixture-incoming-transaction'],txHashes:['fixture-outgoing-transaction']})});
      let body;
      if(url===api+'/v2/users/fixture-id/balances')body=balance();
      else if(url===api+'/swaps/v2')body=native?{v1Swap:nq}:{v2Swap:q};
      else if(native && url===api+'/v2/users/fixture-id/swaps')body={swaps:submitted?[{
        id:'new-native',signature:'3'.repeat(88),address:cashWallet,recipient:cashWallet,
        inNetworkId:1399811149,outNetworkId:1399811149,inTokenAddress:sell?token:cash,outTokenAddress:sell?cash:token,createdAt:new Date().toISOString()}]:[]};
      else if(url===api+'/fixture/submit'){submitted++;body={};}
      else return route.abort();
      return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},
        body:JSON.stringify({success:true,responseObject:body})});
    };
    await page.route('**/*',intercept);
    try {
      await page.goto(`https://fomo.family/tokens/${chain}/${token}`,{waitUntil:'domcontentloaded'});
      const options={networks,live:!scenario.endsWith('shadow'),account:{profile:'fixture',user_id:'fixture-id',cash_wallet:cashWallet,token_wallet:wallet},
        limits:{max_buy_usd:'10',max_fee_usd:'0.30',max_fee_bps:300,max_price_impact_bps:200,decision_age_seconds:45,acknowledge_network_fee:warning},
        intent:{id:'fixture-'+scenario,bio_id:'worm',account_ref:'fixture-account',created_at:Date.now()/1000,
          chain,address:token,asset_id:chain+':'+token,action:sell?'SELL':'BUY',
          amount_usd:'2',quantity_raw:'2000000',decimals:6}};
      if(portfolio){options.limits.max_positions=2;options.intent.known_positions=[
        {asset_id:'robinhood:'+other,raw_quantity:'100',decimals:6},
        ...(sell?[{asset_id:chain+':'+token,raw_quantity:'2000000',decimals:6}]:[])];}
      const result=await execute(page,options);
      const expected=scenario.endsWith('block')?'blocked':scenario.endsWith('shadow')?'shadow':scenario==='unknown'?'unknown':'filled';
      if(result.status!==expected)throw Error(scenario+': '+JSON.stringify(result));
      if(submitted!==(['filled','unknown'].includes(expected)?1:0))throw Error('Unexpected submit count');
      if(warning && await page.getByRole('checkbox').getAttribute('aria-checked') !== (scenario==='network_fee_ack'?'true':'false'))throw Error('Unexpected fee acknowledgment');
      results.push({scenario,status:result.status,fixture_submits:submitted,intercepted_requests:seen});
    } finally {
      await page.goto('about:blank');
      await page.unroute('**/*',intercept);
    }
  }
  return {results,real_orders:0,scope:'Empty browser and locally fulfilled HTTP fixtures only'};
})
