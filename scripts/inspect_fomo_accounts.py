"""Inspect already-open FOMO pages without navigation, clicks, credentials or orders."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def inspect(account,wrapper,balances=False):
    # The expected public handle stays in the private browser command, not the report.
    expected=json.dumps('/profile/'+account['observed_fomo_username'])
    code='''async page => {
      if (!page.url().startsWith('https://fomo.family/')) throw Error('FOMO is not open');
      return await page.evaluate(expected => {
        const links=[...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href'));
        const text=document.body.innerText;
        const available=text.match(/\\$([0-9,]+(?:\\.[0-9]+)?)\\s+available/i);
        const cash=text.match(/Total cash\\s*\\$([0-9,]+(?:\\.[0-9]+)?)/i);
        const buys=[...document.querySelectorAll('button')].filter(b=>/^Buy\\s+[^\\s]+$/.test(b.innerText.trim()));
        const sell=[...document.querySelectorAll('button')].filter(b=>b.innerText.trim()==='Sell');
        return {identity_matches:links.includes(expected),
          displayed_available_usd:available?available[1].replaceAll(',',''):null,
          displayed_total_cash_usd:cash?cash[1].replaceAll(',',''):null,
          buy_submit_visible:buys.length===1,buy_submit_disabled:buys.length===1?buys[0].disabled:null,
          sell_tab_visible:sell.length===1,sell_tab_disabled:sell.length===1?sell[0].disabled:null,
          token_page:new URL(location.href).pathname.startsWith('/tokens/'),
          scope:'Rendered UI only; no chain reconciliation or execution verification'};
      },EXPECTED);
    }'''.replace('EXPECTED',expected)
    if balances:
        from bio_arena.fomo_inspection import browser_probe
        code=browser_probe(account['observed_fomo_username'])
    profile=Path(account['profile_directory']).resolve()
    result=subprocess.run(['bash',str(wrapper),'run-code',code],cwd=profile.parent,
        env={**os.environ,'PLAYWRIGHT_CLI_SESSION':account['playwright_session']},
        text=True,capture_output=True,timeout=30)
    marker='### Result\n'
    if result.returncode or marker not in result.stdout:raise RuntimeError('Private browser inspection unavailable')
    payload,_=json.JSONDecoder().raw_decode(result.stdout.split(marker,1)[1].lstrip())
    return {'bio_id':account['intended_bio'],'account_ref':f"account-{account['slot']}",
            'checked_at':time.time(),'live_execution_enabled':False,**payload}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--balances',action='store_true',help='Observe the existing account balance GET without sending a request')
    parser.add_argument('--wrapper',type=Path,default=Path.home()/'.codex/skills/playwright/scripts/playwright_cli.sh')
    args=parser.parse_args();accounts=json.loads(args.bindings.read_text())['accounts'];results=[]
    for account in accounts:
        try:results.append(inspect(account,args.wrapper,args.balances))
        except Exception:results.append({'bio_id':account['intended_bio'],'checked_at':time.time(),'error':'Read-only page inspection unavailable','live_execution_enabled':False})
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as output:json.dump({'accounts':results,'can_trade':False},output,indent=2)
    os.chmod(args.output,0o600)
    print(json.dumps({'accounts':len(results),'identity_matches':sum(bool(r.get('identity_matches')) for r in results),
                      'inspect_errors':sum('error' in r for r in results),'real_orders_submitted':0}))
