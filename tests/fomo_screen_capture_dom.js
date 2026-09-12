// Use an isolated QA browser. Every request is fulfilled locally.
(async function testCapture(page,capture){
  const tab=await page.context().newPage();
  const url='https://fomo.family/tokens/robinhood/0x'+'1'.repeat(40);
  const html=`<style>body{margin:0;background:#111;color:white}iframe{position:absolute;left:328px;top:126px;width:640px;height:360px;border:0}.trade{position:absolute;left:980px;top:72px;width:320px;height:280px;background:#242}button{margin:10px}aside{position:absolute;left:980px;top:352px;background:red;width:320px;height:134px}</style><iframe title="Financial Chart" srcdoc="<body style='background:#123;color:white'>PUBLIC CHART</body>"></iframe><div class="trade"><button>Buy</button><button>Sell</button><input placeholder="0"><button>Buy TEST</button></div><aside>PRIVATE ACCOUNT AREA</aside>`;
  const results=[];
  await tab.setViewportSize({width:1420,height:850});
  await tab.route('**/*',route=>route.fulfill({status:200,contentType:'text/html',body:html}));
  try{
    await tab.goto(url);
    const live=await capture(tab);
    if(live.state!=='live'||!live.jpeg||live.mask.height<=0||live.mask.width!==320)throw Error('Missing constrained image/mask');
    results.push({case:'token page',state:live.state,mask:live.mask});
    for(const role of ['dialog','menu']){
      await tab.evaluate(role=>{const node=document.createElement('div');node.id='private';node.setAttribute('role',role);node.textContent='PRIVATE';document.body.append(node)},role);
      const row=await capture(tab);if(row.state!=='private_page'||row.jpeg)throw Error('Private overlay captured');
      results.push({case:role,state:row.state});await tab.locator('#private').evaluate(n=>n.remove());
    }
    await tab.goto('https://fomo.family/profile/fixture');
    const profile=await capture(tab);if(profile.state!=='private_page'||profile.jpeg)throw Error('Profile captured');
    results.push({case:'profile',state:profile.state});
    await tab.goto(url);await tab.locator('iframe').evaluate(n=>n.style.width='100px');
    const layout=await capture(tab);if(layout.state!=='unsupported_layout'||layout.jpeg)throw Error('Unknown layout captured');
    results.push({case:'unknown layout',state:layout.state});
    await tab.goto(url);
    let inspections=0;
    const race={evaluate:async (fn,args)=>{if(++inspections===2)return {state:'private_page'};return tab.evaluate(fn,args)},context:()=>({newCDPSession:()=>tab.context().newCDPSession(tab)})};
    const changed=await capture(race);if(changed.state==='live'||changed.jpeg)throw Error('Navigation race captured');
    results.push({case:'page changes during capture',state:changed.state});
    for(const [chain,address]of [['solana','So11111111111111111111111111111111111111112'],...['base','bnb','ethereum','monad'].map(chain=>[chain,'0x'+'1'.repeat(40)])]){
      await tab.goto(`https://fomo.family/tokens/${chain}/${address}`);
      const row=await capture(tab);if(row.state!=='live'||!row.jpeg)throw Error('Supported chain hidden: '+chain);
      results.push({case:chain,state:row.state});
    }
    return {results,real_orders:0};
  }finally{await tab.close()}
})
