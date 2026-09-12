// Read-only capture of the current token page. Never navigate or send input.
(async function captureFomoScreen(page, networkNames) {
  const inspect = networks => {
    const visible = el => {
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    const path=/^\/tokens\/([a-z]+)\/([a-zA-Z0-9]+)$/.exec(location.pathname);
    if (location.origin !== 'https://fomo.family' || !path || !networks.includes(path[1]) ||
        !(path[1]==='solana'?/^[1-9A-HJ-NP-Za-km-z]{32,44}$/:/^0x[0-9a-fA-F]{40}$/).test(path[2]))
      return {state:'private_page'};
    if (devicePixelRatio !== 1) return {state:'unsupported_layout'};
    if ([...document.querySelectorAll('[role="dialog"], [role="menu"], [aria-modal="true"], input[type="password"], iframe[src*="privy.io"]')].some(visible))
      return {state:'private_page'};
    const charts = [...document.querySelectorAll('iframe[title="Financial Chart"]')].filter(visible);
    const inputs = [...document.querySelectorAll('input[placeholder="0"]')].filter(visible);
    if (charts.length !== 1 || inputs.length !== 1) return {state:'page_loading'};
    let panel = inputs[0].parentElement;
    while (panel && !['Buy','Sell'].every(label => [...panel.querySelectorAll('button')].some(b => b.textContent.trim() === label))) panel = panel.parentElement;
    if (!panel) return {state:'page_loading'};
    const c = charts[0].getBoundingClientRect(), p = panel.getBoundingClientRect();
    // Only the token header/chart and its trade form are eligible. Navigation,
    // account menus and the account activity below the trade form are excluded.
    if (p.x < c.right || p.y < 64 || c.width < 250 || p.width > 500 || p.height > 650 || p.bottom > innerHeight || c.bottom > innerHeight)
      return {state:'unsupported_layout'};
    const x=Math.ceil(c.x), y=Math.ceil(p.y), right=Math.floor(p.right), bottom=Math.floor(Math.max(c.bottom,p.bottom));
    if (x < 200 || right > innerWidth || bottom-y < 200 || y >= c.y) return {state:'unsupported_layout'};
    return {state:'live',path:location.pathname,clip:{x,y,width:right-x,height:bottom-y,scale:1},
      mask:{x:Math.max(0,Math.floor(p.x)-x),y:Math.max(0,Math.floor(p.bottom)-y),width:right-Math.floor(p.x),height:Math.max(0,bottom-Math.floor(p.bottom))}};
  };
  const before=await page.evaluate(inspect,networkNames);
  if (before.state !== 'live') return before;
  const session=await page.context().newCDPSession(page);
  let frame;
  try {
    frame=await session.send('Page.captureScreenshot',{format:'jpeg',quality:65,clip:before.clip,captureBeyondViewport:false,fromSurface:true});
  } finally { await session.detach(); }
  const after=await page.evaluate(inspect,networkNames);
  if (JSON.stringify(before)!==JSON.stringify(after)) return {state:'page_loading'};
  return {...before,captured_at:Date.now()/1000,jpeg:frame.data};
})
