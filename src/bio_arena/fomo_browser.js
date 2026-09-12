// Evaluated by the operator's Playwright runner. No direct order API or key access.
// Only the live branch presses a submit button; shadow uses the same checks.
(async function fomoExecution(page, options) {
  const {intent, limits, account, live} = options;
  const outputToleranceBps = limits.max_slippage_bps ?? limits.max_price_impact_bps;
  const network = Object.hasOwn(options.networks || {}, intent.chain) ? options.networks[intent.chain] : null;
  const targetChain = network?.balance_id, routeChain = network?.relay_id;
  const targetWallet = network?.wallet === 'cash_wallet' ? account.cash_wallet : account.token_wallet;
  const now = () => Date.now() / 1000;
  const cashToken = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
  const cashChain = 1399811149;
  // FOMO token IDs and Relay routes use different IDs for Solana.
  const relayCashChain = 792703809;
  const assetId = intent.asset_id;
  let clicked = false, balances = null, quote = null, relayStatus = null;
  let failure = null, lastRoute = null, submittedRoute = null, relayEvidence = null;
  let balancesBefore = null, nextRelayPoll = 0;
  let nativeSwap = null, nativeEvidence = null, submitAt = null;
  const oldSwapIds = new Set();
  let stage = 'identity';
  let quotesFrozen = false;
  const quoteEndpoint = 'https://prod-api.fomo.family/swaps/v2';
  const blockNewQuote = route => route.abort('blockedbyclient');
  const base = {account_ref:intent.account_ref, asset_id:assetId, action:intent.action};
  const fail = reason => { throw new Error(reason); };
  const number = (value, signed=false) => {
    if (!['number','string'].includes(typeof value) || value === '') fail('Missing numeric evidence');
    const n = Number(value);
    if (!Number.isFinite(n) || (!signed && n < 0)) fail('Invalid numeric evidence');
    return n;
  };
  const raw = value => {
    if (typeof value !== 'string' || !/^\d+$/.test(value)) fail('Missing exact token quantity');
    return BigInt(value);
  };
  const sameAddress = (a,b,chain) => typeof a === 'string' && typeof b === 'string' &&
    (chain === cashChain || chain === relayCashChain ? a === b : a.toLowerCase() === b.toLowerCase());
  const tokenId = (a,chain) => `${chain === cashChain ? a : a.toLowerCase()}:${chain}`;
  const target = tokenId(intent.address, targetChain);
  const cashId = tokenId(cashToken, cashChain);
  const parseBalances = data => {
    if (!Array.isArray(data?.balances) || !Array.isArray(data?.nativeEvmBalances)) fail('Unrecognized balance schema');
    const rows = new Map();
    for (const row of data.balances) {
      const b = row.balance, t = row.tokenFilterResult?.token;
      if (!b || !t || !Number.isInteger(t.networkId) || !Number.isInteger(t.decimals) || t.decimals < 0 || t.decimals > 36) fail('Incomplete token balance');
      const id = tokenId(t.address,t.networkId);
      if (b.tokenId !== `${t.address}:${t.networkId}` || !sameAddress(b.tokenAddress,t.address,t.networkId) || rows.has(id)) fail('Ambiguous balance identity');
      rows.set(id, {raw:raw(b.balance), decimals:t.decimals, wallet:b.address,
        price:row.tokenFilterResult.priceUSD == null ? null : number(row.tokenFilterResult.priceUSD)});
    }
    const cash = rows.get(cashId);
    if (!cash || cash.decimals !== 6 || !sameAddress(cash.wallet,account.cash_wallet,cashChain)) fail('Unified cash wallet is not verified');
    return {rows,cash,at:now()};
  };
  const positionRows = b => [...b.rows.entries()].filter(([id,p]) => id !== cashId && p.raw > 0n);
  const recordedPositions = () => {
    const rows = intent.known_positions ?? (intent.action === 'SELL'
      ? [{asset_id:assetId,raw_quantity:intent.quantity_raw,decimals:intent.decimals}] : []);
    if (!Array.isArray(rows) || ((limits.max_positions ?? 1) > 1 && !Array.isArray(intent.known_positions)))
      fail('Recorded portfolio is missing');
    const expected = new Map();
    for (const p of rows) {
      const [chain,address] = p.asset_id.split(':'), n = options.networks[chain];
      if (!n || !address || raw(p.raw_quantity) <= 0n) fail('Recorded portfolio is invalid');
      const id = tokenId(address,n.balance_id);
      if (expected.has(id)) fail('Recorded portfolio has duplicate tokens');
      expected.set(id,{raw:raw(p.raw_quantity),decimals:p.decimals,
        wallet:account[n.wallet],chain:n.balance_id});
    }
    return expected;
  };
  const auditPortfolio = b => {
    const expected = recordedPositions(), actual = positionRows(b);
    if (actual.length !== expected.size) fail('Account positions differ from the recorded portfolio');
    for (const [id,p] of actual) {
      const e = expected.get(id);
      if (!e || p.raw !== e.raw || p.decimals !== e.decimals || !sameAddress(p.wallet,e.wallet,e.chain))
        fail('Account positions differ from the recorded portfolio');
    }
  };
  const nativeQuote = (q, request) => {
    if (intent.chain !== 'solana') fail('Native quote on a different network');
    const buy = intent.action === 'BUY';
    if (request.inTokenId !== (buy ? cashId : target) || request.outTokenId !== (buy ? target : cashId))
      fail('Native quote token or network mismatch');
    const amount = raw(request.amount);
    const input = Number(amount) / 10**(buy ? 6 : intent.decimals);
    const notional = buy ? input : input*number(balances?.rows.get(target)?.price);
    if (q.feeTokenAddress !== cashToken || q.jitoTipTx || typeof q.feePayerAddress !== 'string' ||
        !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(q.feePayerAddress) || q.feePayerAddress === account.cash_wallet)
      fail('Native quote fee coverage is not verified');
    const fee = Math.max(number(q.flatFee)+notional*number(q.feeTierBps)/10000,
      notional-number(q.swapUsdValue),0);
    return {kind:'solana_native',originChainId:relayCashChain,destinationChainId:relayCashChain,
      originAddress:account.cash_wallet,destinationAddress:account.cash_wallet,
      originTokenAddress:buy?cashToken:intent.address,destinationTokenAddress:buy?intent.address:cashToken,
      amount:request.amount,inputHumanAmount:input,expectedOutHumanAmount:number(q.expectedOutHumanAmount),
      inAmountUsd:notional,fee_reserve_usd:fee,priceImpactPct:number(q.priceImpactPct,true),
      dynamicSlippageBps:number(q.dynamicSlippageBps),relaySwapId:'solana-quote-'+now(),at:now()};
  };
  const observeNativeSwaps = rows => {
    if (!Array.isArray(rows)) return;
    if (!clicked) { for (const row of rows) oldSwapIds.add(row.id); return; }
    if (quote?.kind !== 'solana_native') return;
    const buy = intent.action === 'BUY';
    const matches = rows.filter(row => !oldSwapIds.has(row.id) && typeof row.id === 'string' &&
      row.inNetworkId === cashChain && row.outNetworkId === cashChain &&
      row.address === account.cash_wallet && row.recipient === account.cash_wallet &&
      row.inTokenAddress === (buy?cashToken:intent.address) && row.outTokenAddress === (buy?intent.address:cashToken) &&
      Date.parse(row.createdAt)/1000 >= submitAt-2 && Date.parse(row.createdAt)/1000 <= now()+2 &&
      typeof row.signature === 'string' && /^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(row.signature));
    if (matches.length > 1) fail('Multiple native swaps need reconciliation');
    if (matches.length === 1) nativeSwap = {id:matches[0].id,signature:matches[0].signature};
  };
  const readResponse = async response => {
    if (!response.url().startsWith('https://prod-api.fomo.family/')) return;
    const path = response.url().split('?')[0];
    try {
      if (path === `https://prod-api.fomo.family/v2/users/${account.user_id}/balances` && response.request().method() === 'GET') {
        const body = await response.json();
        if (!response.ok() || body.success !== true) fail('Account balance request failed');
        balances = parseBalances(body.responseObject);
      } else if (path === `https://prod-api.fomo.family/v2/users/${account.user_id}/swaps` && response.request().method() === 'GET') {
        const body = await response.json();
        if (response.ok() && body.success === true) observeNativeSwaps(body.responseObject?.swaps);
      } else if (path === 'https://prod-api.fomo.family/swaps/v2' && response.request().method() === 'POST') {
        if (quotesFrozen || clicked) return;
        const body = await response.json();
        // Only sanitize an app-generated quote. Transaction/signature payloads
        // are deliberately excluded from the result and from local journals.
        if (response.ok() && body.success === true && body.responseObject?.v1Swap) {
          quote = nativeQuote(body.responseObject.v1Swap,response.request().postDataJSON());
          return;
        }
        const q = body.responseObject?.v2Swap;
        if (!response.ok() || body.success !== true || !q) { quote = null; return; }
        quote = Object.fromEntries(['originChainId','destinationChainId','originAddress','destinationAddress',
          'originTokenAddress','destinationTokenAddress','amount','inputHumanAmount','expectedOutHumanAmount',
          'inAmountUsd','swapUsdValue','usdFees','priceImpactPct','relaySwapId'].map(k=>[k,q[k]]));
        quote.at = now();
      }
    } catch { failure = 'Account or quote evidence could not be decoded'; }
  };
  const waitUntil = async (test, seconds) => {
    const deadline = now() + seconds;
    while (!(await test())) {
      if (failure) fail(failure);
      if (now() >= deadline) fail('Timed out waiting for fresh account or order evidence');
      await page.waitForTimeout(100);
    }
  };
  const pollRelay = async () => {
    if (now() < nextRelayPoll || relayStatus === 'SUCCESS') return;
    nextRelayPoll = now()+2;
    let body;
    try {
      body = await page.evaluate(async requestId => {
        const controller = new AbortController();
        const timer = setTimeout(()=>controller.abort(),5000);
        try {
          const response = await fetch('https://api.relay.link/intents/status/v3?requestId='+encodeURIComponent(requestId),
            {method:'GET',credentials:'omit',signal:controller.signal});
          return response.ok ? await response.json() : null;
        } finally { clearTimeout(timer); }
      },submittedRoute);
    } catch { return; }
    if (!body) return;
    if (body.status !== 'success') {
      if (['failure','refund','refunded'].includes(body.status)) fail('Relay reported failure or refund');
      return;
    }
    const buy = intent.action === 'BUY';
    if (body.originChainId !== (buy ? relayCashChain : routeChain) ||
        body.destinationChainId !== (buy ? routeChain : relayCashChain) ||
        !Array.isArray(body.inTxHashes) || !body.inTxHashes.length ||
        !Array.isArray(body.txHashes) || !body.txHashes.length ||
        ![...body.inTxHashes,...body.txHashes].every(v=>typeof v==='string' && v.length>20))
      fail('Relay settlement chains or transaction evidence do not match');
    relayEvidence = Object.fromEntries(['status','originChainId','destinationChainId','inTxHashes','txHashes','updatedAt','quoteCreatedAt'].map(k=>[k,body[k]??null]));
    relayStatus = 'SUCCESS';
  };
  const pollNative = async () => {
    if (!nativeSwap || nativeEvidence || now() < nextRelayPoll) return;
    nextRelayPoll = now()+2;
    let tx;
    try {
      tx = await page.evaluate(async signature => {
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
        try {
          // This is a read-only RPC method. No serialized transaction is sent.
          const response=await fetch('https://api.mainnet-beta.solana.com',{method:'POST',credentials:'omit',
            headers:{'Content-Type':'application/json'},signal:controller.signal,
            body:JSON.stringify({jsonrpc:'2.0',id:1,method:'getTransaction',
              params:[signature,{encoding:'jsonParsed',commitment:'confirmed',maxSupportedTransactionVersion:0}]})});
          return response.ok?(await response.json()).result:null;
        } finally {clearTimeout(timer)}
      },nativeSwap.signature);
    } catch { return; }
    if (!tx) return;
    if (tx.meta?.err !== null || tx.transaction?.signatures?.[0] !== nativeSwap.signature ||
        !Number.isSafeInteger(tx.slot) || tx.slot <= 0 || !(tx.blockTime >= intent.created_at-2 && tx.blockTime <= now()+2))
      fail('Native transaction confirmation does not match');
    const total = (rows,mint) => {
      if (!Array.isArray(rows)) fail('Native token balances unavailable');
      return rows.filter(r=>r.owner===account.cash_wallet && r.mint===mint)
        .reduce((sum,r)=>sum+raw(r.uiTokenAmount?.amount),0n);
    };
    const cashChange=total(tx.meta.postTokenBalances,cashToken)-total(tx.meta.preTokenBalances,cashToken);
    const tokenChange=total(tx.meta.postTokenBalances,intent.address)-total(tx.meta.preTokenBalances,intent.address);
    if (!balancesBefore || !balances || cashChange !== balances.cash.raw-raw(balancesBefore.cash_raw) ||
        (intent.action==='BUY' ? tokenChange !== (balances.rows.get(target)?.raw??0n) || tokenChange<=0n
          : tokenChange !== -raw(intent.quantity_raw) || (balances.rows.get(target)?.raw??0n)!==0n))
      return; // The app may not have received its final balance refresh yet.
    const keys=tx.transaction.message?.accountKeys;
    const owner=Array.isArray(keys)?keys.findIndex(k=>k.pubkey===account.cash_wallet):-1;
    if (owner<0 || !Number.isSafeInteger(tx.meta.preBalances?.[owner]) ||
        !Number.isSafeInteger(tx.meta.postBalances?.[owner]) || tx.meta.postBalances[owner]<tx.meta.preBalances[owner])
      fail('Unquoted native SOL debit needs reconciliation');
    nativeEvidence={swap_id:nativeSwap.id,signature:nativeSwap.signature,slot:tx.slot,commitment:'confirmed',
      owner_balances_verified:true,cash_delta_raw:cashChange.toString(),token_delta_raw:tokenChange.toString()};
    submittedRoute=nativeSwap.signature;
  };
  const balanceSnapshot = b => b ? {at:b.at,cash_raw:b.cash.raw.toString(),
    positions:positionRows(b).map(([id,p])=>({token_id:id,raw_quantity:p.raw.toString(),decimals:p.decimals}))} : null;
  const identity = async () => {
    // The pinned user ID and both custody wallets must ALSO match the app's
    // balance and quote responses; a public profile link alone is insufficient.
    // DOMContentLoaded can precede the signed-in navigation rendering. Wait for
    // that exact account link, while retaining the origin and uniqueness gates.
    const deadline=now()+8;
    while (true) {
      if (!page.url().startsWith('https://fomo.family/')) fail('Unexpected browser origin');
      const count=await page.locator(`a[href="/profile/${account.profile}"]`).count();
      if (count===1) return;
      if (count>1 || now()>=deadline) fail('Account profile link missing or ambiguous');
      await page.waitForTimeout(100);
    }
  };
  const audit = () => {
    if (failure) fail(failure);
    if (!balances || now()-balances.at > 15 || !quote || now()-quote.at > 5) fail('Fresh balances and route required');
    if (now()-intent.created_at < 0 || now()-intent.created_at > limits.decision_age_seconds) fail('Bio decision expired during preparation');
    const buy = intent.action === 'BUY';
    const originChain = buy ? relayCashChain : routeChain, destinationChain = buy ? routeChain : relayCashChain;
    const originToken = buy ? cashToken : intent.address, destinationToken = buy ? intent.address : cashToken;
    const originWallet = buy ? account.cash_wallet : targetWallet, destinationWallet = buy ? targetWallet : account.cash_wallet;
    if (quote.originChainId !== originChain || quote.destinationChainId !== destinationChain ||
        !sameAddress(quote.originTokenAddress,originToken,originChain) || !sameAddress(quote.destinationTokenAddress,destinationToken,destinationChain) ||
        !sameAddress(quote.originAddress,originWallet,originChain) || !sameAddress(quote.destinationAddress,destinationWallet,destinationChain)) fail('Route chain, token or custody wallet mismatch');
    if (typeof quote.relaySwapId !== 'string' || !quote.relaySwapId) fail('Missing route identity');
    const native = quote.kind === 'solana_native';
    if (!native && (!quote.usdFees || Object.keys(quote.usdFees).sort().join(',') !== 'app,relay')) fail('Unrecognized complete fee breakdown');
    const fee = native ? number(quote.fee_reserve_usd) : number(quote.usdFees.app) + number(quote.usdFees.relay);
    if (native && number(quote.dynamicSlippageBps) > (limits.max_slippage_bps ?? limits.max_price_impact_bps)) fail('Quoted slippage exceeds configured limit');
    const notional = number(quote.inAmountUsd);
    if (notional <= 0 || number(quote.expectedOutHumanAmount) <= 0) fail('Empty quote');
    if (fee > number(limits.max_fee_usd) || (limits.max_fee_bps != null && fee/notional*10000 > limits.max_fee_bps)) fail('Quoted fees exceed configured limits');
    if (Math.abs(number(quote.priceImpactPct,true))*10000 > limits.max_price_impact_bps) fail('Quoted price impact exceeds configured limit');
    const positions = positionRows(balances);
    auditPortfolio(balances);
    if (buy) {
      const amount = number(intent.amount_usd);
      if (!(amount >= 2 && amount <= number(limits.max_buy_usd) && amount <= 10)) fail('Buy exceeds the 10 USD ceiling');
      if (positions.length >= (limits.max_positions ?? 1) || (balances.rows.get(target)?.raw ?? 0n) > 0n) fail('Live position capacity reached or token already held');
      if (number(quote.inputHumanAmount) !== amount || raw(String(quote.amount)) !== BigInt(Math.round(amount*1e6))) fail('Quote input differs from the Bio order');
      // Reserve fees separately even when the platform deducts them from input.
      if (Number(balances.cash.raw)/1e6 < amount+fee) fail('Insufficient cash with fee reserve');
    } else {
      const held = balances.rows.get(target);
      if (!held || held.raw !== raw(intent.quantity_raw) || held.decimals !== intent.decimals) fail('Sell holding differs from the recorded position');
      if (!sameAddress(held.wallet,targetWallet,targetChain) || raw(String(quote.amount)) !== raw(intent.quantity_raw)) fail('Sell route does not cover exactly this holding');
      if (number(quote.expectedOutHumanAmount) <= fee) fail('Sell proceeds do not cover conservative fee reserve');
    }
    return {route_id:quote.relaySwapId,fee_usd:fee,input_usd:notional,expected_output:number(quote.expectedOutHumanAmount),quoted_at:quote.at,
      provider:native?'solana_native':'relay',fee_scope:native?'Conservative native quote cost reserve':'App plus Relay quote fees'};
  };
  page.on('response',readResponse);
  try {
    if (typeof live !== 'boolean' || !['BUY','SELL'].includes(intent.action)) fail('Invalid execution request');
    if (!network || !Number.isSafeInteger(targetChain) || !Number.isSafeInteger(routeChain)) fail('Unsupported FOMO network');
    const solana = intent.chain === 'solana';
    if (!(solana ? /^[1-9A-HJ-NP-Za-km-z]{32,44}$/ : /^0x[0-9a-fA-F]{40}$/).test(intent.address)) fail('Invalid token address for this network');
    if (assetId !== `${intent.chain}:${solana ? intent.address : intent.address.toLowerCase()}`) fail('Decision asset and network mismatch');
    if (target === cashId) fail('Unified cash is not a tradable position');
    if (!/^[A-Za-z0-9_-]+$/.test(account.profile) || !/^[A-Za-z0-9_-]+$/.test(account.user_id)) fail('Invalid pinned account identity');
    await identity();
    const url = `https://fomo.family/tokens/${intent.chain}/${intent.address}`;
    // Solana addresses are case-sensitive, including in browser navigation.
    if (page.url() !== url) await page.goto(url,{waitUntil:'domcontentloaded'});
    await identity();
    stage = 'await_balances';
    await waitUntil(()=>balances !== null, 15);
    stage = 'inspect_form';
    const input = page.locator('input[placeholder="0"]');
    if (await input.count() !== 1) fail('Trade amount input is ambiguous');
    const panel = input.locator('xpath=ancestor::*[.//button[normalize-space(.)="Buy"] and .//button[normalize-space(.)="Sell"]][1]');
    if (await panel.count() !== 1) fail('Trade panel is ambiguous');
    // These are tab/preset controls, never Quick Buy buttons.
    stage = 'select_side';
    await panel.getByRole('button',{name:intent.action === 'BUY' ? 'Buy' : 'Sell',exact:true}).click();
    quote = null;
    stage = 'select_amount';
    if (intent.action === 'BUY') await input.fill(intent.amount_usd);
    else await panel.getByRole('button',{name:'100%',exact:true}).click();
    stage = 'await_quote';
    await waitUntil(()=>quote !== null, 10);
    stage = 'audit_quote';
    lastRoute = audit();
    const button = panel.getByRole('button',{name:intent.action === 'BUY' ? /^Buy\s+\S+$/ : /^Sell\s+\S+$/});
    if (await button.count() !== 1) fail('Trade submit button is ambiguous');
    if (!live) return {...base,status:'shadow',clicked:false,quote:lastRoute,
      submit_disabled:!(await button.isEnabled()),scope:'Quote rehearsal only; no order sent'};
    // Only this precisely named network-fee warning can be acknowledged by an
    // operator-configured rule. Token-risk, compliance and wallet prompts stop.
    if (!(await button.isEnabled()) && limits.acknowledge_network_fee === true) {
      stage = 'acknowledge_fee';
      const warning = panel.getByRole('checkbox',{name:/^High network fee\b/});
      if (await warning.count() === 1 && await warning.getAttribute('aria-checked') === 'false') await warning.click();
    }
    await identity();
    if (!(await button.isEnabled())) fail('Platform requires attention or blocks trading');
    // FOMO may internally retry with a new quote. This attempt is limited to its
    // reviewed cached quote; a replacement route must wait for a new Bio intent.
    await page.route(quoteEndpoint,blockNewQuote);
    quotesFrozen = true;
    lastRoute = audit();
    if (await page.locator('input[placeholder="0"]').count() !== 1) fail('Trade form changed');
    if (intent.action === 'BUY' && await page.locator('input[placeholder="0"]').inputValue() !== intent.amount_usd) fail('Trade amount changed');
    const before = balances, expected = number(quote.expectedOutHumanAmount);
    balancesBefore = balanceSnapshot(before);
    submittedRoute = lastRoute.route_id;
    // Persisted Python intent is already attempting before this call. From this
    // point on, any error is unknown and must never trigger another click.
    clicked = true;
    submitAt = now();
    stage = 'submit';
    await button.click({timeout:3000});
    const clickedAt = now();
    stage = 'await_settlement';
    await waitUntil(async()=>{
      if (quote.kind === 'solana_native') await pollNative(); else await pollRelay();
      return (nativeEvidence !== null || relayStatus === 'SUCCESS') && balances.at > clickedAt &&
        (intent.action === 'BUY' ? (balances.rows.get(target)?.raw ?? 0n) > 0n : (balances.rows.get(target)?.raw ?? 0n) === 0n);
    }, 50);
    const after = balances, positions = positionRows(after);
    stage = 'verify_balances';
    for (const [id,p] of positionRows(before)) {
      if (id === target) continue;
      const other = after.rows.get(id);
      if (!other || other.raw !== p.raw || other.decimals !== p.decimals || other.wallet !== p.wallet)
        fail('An unrelated holding changed during settlement');
    }
    let position = null;
    if (intent.action === 'BUY') {
      if (positions.length !== positionRows(before).length+1 || !after.rows.get(target) || after.cash.raw >= before.cash.raw) fail('Buy balances do not match a single new holding');
      const p = after.rows.get(target), received = Number(p.raw)/10**p.decimals;
      const debit = Number(before.cash.raw-after.cash.raw)/1e6;
      if (!sameAddress(p.wallet,targetWallet,targetChain) || debit > number(intent.amount_usd)+lastRoute.fee_usd+0.000001 ||
          debit < number(intent.amount_usd)-0.01 || received < expected*(1-outputToleranceBps/10000) || received > expected*1.05) fail('Buy balance delta is outside the quoted bounds');
      position = {asset_id:assetId,raw_quantity:p.raw.toString(),decimals:p.decimals};
    } else {
      const credit = Number(after.cash.raw-before.cash.raw)/1e6;
      if (positions.length !== positionRows(before).length-1 || (after.rows.get(target)?.raw ?? 0n) !== 0n || credit <= 0 || credit < expected*(1-outputToleranceBps/10000)-lastRoute.fee_usd || credit > expected*1.05) fail('Sell balance delta is outside the quoted bounds');
    }
    return {...base,status:'filled',clicked:true,route_id:submittedRoute,relay_status:relayStatus,
      settlement_provider:nativeEvidence?'solana':'relay',solana_evidence:nativeEvidence,
      relay_evidence:relayEvidence,balances_before:balancesBefore,balances_after:balanceSnapshot(after),
      quote:lastRoute,balances_verified:true,position_after:position,observed_at:now(),
      cash_delta_usd:Number(after.cash.raw-before.cash.raw)/1e6,
      scope:nativeEvidence?'FOMO swap record, confirmed Solana transaction and matching account balance deltas; not finalized'
        :'FOMO relay success plus account balance deltas; not independent multi-chain finality'};
  } catch (error) {
    // Error messages originate in the fixed checks above. Avoid dumping website
    // diagnostics, request payloads or browser credentials to the journal.
    const reason = error instanceof Error && !/locator|page\.|browser|Timeout/.test(error.message)
      ? error.message.slice(0,160) : 'Browser operation failed';
    return {...base,status:clicked?'unknown':'blocked',clicked,route_id:submittedRoute,
      failure_stage:stage,retryable:!clicked && ['await_balances','select_side','select_amount','await_quote'].includes(stage) &&
        ['Browser operation failed','Timed out waiting for fresh account or order evidence'].includes(reason),
      quote_diagnostics:quote?{input_usd:quote.inAmountUsd,expected_output:quote.expectedOutHumanAmount,
        price_impact:quote.priceImpactPct,slippage_bps:quote.dynamicSlippageBps??null,
        native_fee_reserve_usd:quote.fee_reserve_usd??null,app_fee:quote.usdFees?.app??null,relay_fee:quote.usdFees?.relay??null}:null,
      relay_evidence:relayEvidence,balances_before:balancesBefore,balances_after:balanceSnapshot(balances),
      solana_evidence:nativeEvidence,
      quote:lastRoute,reason,observed_at:now()};
  } finally {
    page.off('response',readResponse);
    if (quotesFrozen) await page.unroute(quoteEndpoint,blockNewQuote);
  }
})
