"""Sanitized inspection of the active FOMO page and its ordinary balance response."""
import json


def browser_probe(expected_profile):
    """Wait for the app's existing GET; no requests, clicks, storage or credentials."""
    return '''async page => {
      if (!page.url().startsWith('https://fomo.family/')) throw Error('FOMO is not open');
      const visible=await page.evaluate(expected => {
        const text=document.body.innerText;
        const available=text.match(/\\$([0-9,]+(?:\\.[0-9]+)?)\\s+available/i);
        const cash=text.match(/Total cash\\s*\\$([0-9,]+(?:\\.[0-9]+)?)/i);
        const path=location.pathname.match(/^\\/tokens\\/([^/]+)\\/([^/]+)$/);
        const buttons=[...document.querySelectorAll('button')];
        const buy=buttons.filter(b=>/^Buy\\s+[^\\s]+$/.test(b.innerText.trim()));
        const sell=buttons.filter(b=>b.innerText.trim()==='Sell');
        return {identity_matches:[...document.querySelectorAll('a[href]')].some(a=>a.getAttribute('href')===expected),
          chain:path?.[1]??null,token_address:path?.[2]??null,
          displayed_available_usd:available?available[1].replaceAll(',',''):null,
          displayed_total_cash_usd:cash?cash[1].replaceAll(',',''):null,
          buy_submit_disabled:buy.length===1?buy[0].disabled:null,
          sell_tab_disabled:sell.length===1?sell[0].disabled:null,
          amount_input_present:document.querySelectorAll('input[placeholder="0"]').length===1};
      },EXPECTED);
      let balances={status:'unavailable'};
      try {
        const r=await page.waitForResponse(r=>r.request().method()==='GET' &&
          /^https:\\/\\/prod-api\\.fomo\\.family\\/v2\\/users\\/[^/?]+\\/balances(?:\\?|$)/.test(r.url()),{timeout:12000});
        const j=await r.json(), b=j.responseObject;
        if(r.ok() && j.success===true && Array.isArray(b?.balances) && Array.isArray(b?.nativeEvmBalances)) {
          balances={status:'observed',observed_at:Date.now()/1000,token_rows:b.balances.length,
            native_chain_rows:b.nativeEvmBalances.map(r=>({chain_id:r.networkId,
              balance:typeof r.balance==='string'?r.balance:null})),
            scope:'FOMO-reported balances; raw quantities and custody addresses still require chain reconciliation'};
        } else balances={status:'unrecognized_schema'};
      } catch {}
      return {...visible,balances,can_submit:false,orders_submitted:0,
        scope:'Read-only page inspection; no route quote or signed transaction requested'};
    }'''.replace('EXPECTED',json.dumps('/profile/'+expected_profile))
