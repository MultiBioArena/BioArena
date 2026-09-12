// Run on an isolated dashboard browser. Fixtures change responses only.
(async function testScreenUI(page){
  await page.setViewportSize({width:1440,height:1000});
  const response=await page.request.get(page.url().split('/').slice(0,3).join('/')+'/api/fomo-screens'),base=await response.json();
  const historicalAt=Date.now()/1000-600;
  let state='history',fail=false;const writes=[];
  const observe=request=>{if(!['GET','HEAD','OPTIONS'].includes(request.method()))writes.push(request.method())};
  page.on('request',observe);
  const route=async route=>{
    if(fail)return route.fulfill({status:503,body:'unavailable'});
    const d=JSON.parse(JSON.stringify(base)),now=Date.now()/1000;d.as_of=now;
    for(const [bio,s]of Object.entries(d.screens)){
      if(s.state==='live')s.captured_at=now-10;
      s.execution={fresh:true,running:bio==='adult',phase:bio==='adult'?'waiting_buy':'not_enabled',order:null};
    }
    d.screens.adult.execution.order={action:'BUY',status:state==='blocked'?'blocked':'filled',at:state==='history'?historicalAt:historicalAt+1,source_kind:'bio_policy',balance_verified:state!=='blocked'};
    if(state==='private'){d.screens.adult.state='private_page';d.screens.adult.captured_at=null;d.screens.adult.page_path=null}
    if(state==='stale')d.screens.adult.captured_at=now-60;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(d)});
  };
  const paper=async route=>{
    const response=await route.fetch(),d=await response.json();
    if(d.bios)for(const b of d.bios)b.activity={state:'exploring',started_at:Date.now()/1000,ends_at:Date.now()/1000+300,reason:'Isolated display fixture'};
    await route.fulfill({response,json:d});
  };
  await page.route('**/api/fomo-screens',route);await page.route('**/api/state*',paper);
  try{
    await page.reload();await page.locator('.desk-stage').scrollIntoViewIfNeeded();await page.waitForTimeout(4000);
    const station=page.getByRole('button',{name:'View Fly decision history',exact:true});
    if(await station.getAttribute('data-playing')==='true')throw Error('Historical fill replayed');
    state='blocked';await page.waitForTimeout(3000);
    if(await station.getAttribute('data-playing')==='true')throw Error('Blocked order animated as fill');
    state='filled';await page.waitForFunction(()=>document.querySelector('[aria-label="View Fly decision history"]').dataset.playing==='true',null,{timeout:9000});
    await page.waitForTimeout(3000);
    const homes=await page.locator('.desk-station').evaluateAll(nodes=>nodes.map(n=>n.dataset.atDesk));
    if(homes.some(x=>x!=='true'))throw Error('A creature left its desk');
    for(const step of ['stale','private']){
      state=step;await page.waitForTimeout(3000);await page.getByRole('button',{name:'Open Fly FOMO screen'}).click();
      if(await page.locator('dialog img').count())throw Error(step+' retained old frame');
      await page.keyboard.press('Escape');
    }
    fail=true;await page.waitForTimeout(3000);
    if(await station.getAttribute('data-browser-screen')!=='unavailable')throw Error('Failed feed retained image');
    return {historical_replay:false,blocked_replay:false,verified_fill_replay:true,all_at_desks:homes,stale_private_failed_frames_removed:true,mutation_requests:writes};
  }finally{
    await page.unroute('**/api/fomo-screens',route);await page.unroute('**/api/state*',paper);page.off('request',observe);await page.reload();
  }
})
