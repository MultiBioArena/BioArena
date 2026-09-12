import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';

export type BoardQuote={symbol:string;name:string;kind?:string;currency?:string;price:number|null;change_pct?:number;change_period?:string;source?:string;source_time?:string;quote_time?:number|null;received_at?:number;market_state?:string;delayed?:boolean;fresh:boolean;error?:string|null;history:{time:number;price:number}[];history_label?:string};
export type BoardFeed={as_of:number;quotes:BoardQuote[];received:number;failed?:boolean};
const symbols=['BTC','ETH','SOL','NVDA','AAPL'];
export function connectMarketWall(onData:(data:BoardFeed)=>void){
  let disposed=false,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined,pending=false;
  let last:BoardFeed={as_of:0,quotes:[],received:performance.now(),failed:false};
  async function poll(){
    if(disposed||pending||document.hidden)return;pending=true;request=new AbortController();const abort=setTimeout(()=>request?.abort(),10000);
    try{const response=await fetch('/api/market-board',{signal:request.signal});if(!response.ok)throw Error('Market display unavailable');const payload=await response.json();
      if(!Array.isArray(payload.quotes)||!Number.isFinite(payload.as_of))throw Error('Invalid market display');
      if(!disposed){last={...payload,received:performance.now(),failed:false};onData(last)}
    }catch{if(!disposed){last={...last,failed:true};onData(last)}}
    finally{clearTimeout(abort);pending=false;if(!disposed&&!document.hidden)timer=setTimeout(poll,20000)}
  }
  const visibility=()=>{clearTimeout(timer);if(!document.hidden)void poll()};document.addEventListener('visibilitychange',visibility);void poll();
  return()=>{disposed=true;clearTimeout(timer);request?.abort();document.removeEventListener('visibilitychange',visibility)};
}

export function buildMarketWall(){
  const scene=new THREE.Group();scene.position.set(0,3.95,-2.25);
  const frameGeometry=new RoundedBoxGeometry(11.12,1.70,.12,2,.045),frameMaterial=new THREE.MeshStandardMaterial({color:'#172524',roughness:.4,metalness:.5});
  const frame=new THREE.Mesh(frameGeometry,frameMaterial);scene.add(frame);
  const backGeometry=new THREE.BoxGeometry(10.5,.06,.25),metal=new THREE.MeshStandardMaterial({color:'#465852',metalness:.7,roughness:.4});
  const rail=new THREE.Mesh(backGeometry,metal);rail.position.set(0,0,-.15);scene.add(rail);
  const legGeometry=new THREE.BoxGeometry(.065,3.8,.08);
  for(const x of [-4.75,4.75]){const leg=new THREE.Mesh(legGeometry,metal);leg.position.set(x,-2.05,-.15);scene.add(leg)}
  const canvas=document.createElement('canvas');canvas.width=1800;canvas.height=260;
  const ctx=canvas.getContext('2d')!,texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  const planeGeometry=new THREE.PlaneGeometry(10.98,1.59),screenMaterial=new THREE.MeshBasicMaterial({map:texture,toneMapped:false});
  const screen=new THREE.Mesh(planeGeometry,screenMaterial);screen.position.z=.066;scene.add(screen);
  let lastKey='',epoch:number|undefined;
  return {scene,update(time:number,reduced:boolean,feed:BoardFeed){
    epoch??=time;const index=reduced?0:Math.floor((time-epoch)/12)%symbols.length,symbol=symbols[index];
    const now=feed.as_of+(performance.now()-feed.received)/1000,q=feed.quotes.find(q=>q.symbol===symbol);
    const fresh=!!q?.fresh&&!feed.failed&&!!q.received_at&&now-q.received_at<(q.kind==='stock'?300:60);
    const key=[symbol,feed.received,feed.failed,Math.floor(time)].join('/');if(key===lastKey)return {symbol,fresh};lastKey=key;
    const closed=q?.market_state?.toLowerCase()==='closed',oldStock=q?.kind==='stock'&&(!q.quote_time||now-q.quote_time>900);
    const status=!q?.price?'CONNECTING':!fresh?'STALE / LAST QUOTE':closed?'MARKET CLOSED':oldStock?'LAST REPORTED / '+q?.market_state?.toUpperCase():q?.delayed?'DELAYED / '+q.market_state?.toUpperCase():q?.kind==='stock'?q.market_state?.toUpperCase()+' / REFERENCE':'LIVE REFERENCE';
    const green='#beddaa',red='#e99c83',muted='#7c9d8c';
    ctx.fillStyle='#061511';ctx.fillRect(0,0,1800,260);
    ctx.fillStyle='#9db6a5';ctx.font='15px monospace';ctx.fillText('GLOBAL MARKETS / '+String(index+1).padStart(2,'0')+' OF 05',28,29);
    ctx.fillStyle=fresh?'#aacaaf':'#d5ad76';ctx.textAlign='right';ctx.fillText(status,1360,29);ctx.textAlign='left';
    ctx.fillStyle='#e1edde';ctx.font='bold 47px monospace';ctx.fillText(symbol+(q?.kind==='crypto'?' / USDT':''),28,91,470);
    ctx.font='bold 53px monospace';ctx.fillText(q?.price!=null?'$'+q.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—',28,155,510);
    const change=q?.change_pct;ctx.fillStyle=(change??0)<0?red:green;ctx.font='24px monospace';ctx.fillText(change===undefined?'Waiting for quote':`${change>=0?'+':''}${change.toFixed(2)}%  ${q?.change_period||''}`,28,199,510);
    ctx.fillStyle=muted;ctx.font='14px monospace';ctx.fillText(`${q?.source||'Market feed'} · ${q?.source_time||'Awaiting source timestamp'}`,28,234,1290);
    for(const y of [68,114,160,206]){ctx.strokeStyle='#183b2d';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(560,y);ctx.lineTo(1360,y);ctx.stroke()}
    const history=q?.history||[];
    if(history.length>1){
      const low=Math.min(...history.map(p=>p.price)),high=Math.max(...history.map(p=>p.price)),span=Math.max(high-low,(q?.price||1)*.00001),start=history[0].time,duration=history.at(-1)!.time-start;
      ctx.strokeStyle=fresh?((change??0)<0?red:green):muted;ctx.lineWidth=3;ctx.beginPath();
      history.forEach((p,i)=>{const x=560+(p.time-start)/Math.max(1,duration)*800,y=195-(p.price-low)/span*119;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
      ctx.fillStyle=muted;ctx.font='12px monospace';ctx.fillText(q?.history_label||'RECEIVED QUOTES',560,53);
    }else{ctx.fillStyle=muted;ctx.font='24px monospace';ctx.fillText(closed?'LAST REPORTED SESSION PRICE':'COLLECTING PRICE HISTORY',580,130);ctx.font='16px monospace';ctx.fillText(closed?'Trading resumes with the next session.':'Only received prices are plotted.',580,162)}
    ctx.strokeStyle='#294b3b';ctx.beginPath();ctx.moveTo(1400,22);ctx.lineTo(1400,236);ctx.stroke();
    symbols.forEach((s,i)=>{
      const item=feed.quotes.find(q=>q.symbol===s),y=42+i*42;
      if(i===index){ctx.fillStyle='#223d2d';ctx.fillRect(1421,y-24,357,36)}
      ctx.fillStyle=i===index?'#e8efe0':muted;ctx.font='bold 21px monospace';ctx.fillText(s,1435,y);
      ctx.textAlign='right';ctx.font='20px monospace';ctx.fillText(item?.price!=null?'$'+item.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—',1764,y);ctx.textAlign='left';
    });
    ctx.fillStyle='#526f57';ctx.fillRect(0,256,1800,4);ctx.fillStyle=green;ctx.fillRect(0,256,reduced?1800:1800*((time-epoch)%12)/12,4);
    texture.needsUpdate=true;return {symbol,fresh};
  },dispose(){[frameGeometry,backGeometry,legGeometry,planeGeometry].forEach(g=>g.dispose());[frameMaterial,metal,screenMaterial].forEach(m=>m.dispose());texture.dispose()}};
}
