import {useEffect,useState} from 'react';
import type {BioId} from './types';

export type ScreenExecution={fresh:boolean;running:boolean;phase:string;order:{action:'BUY'|'SELL';status:string;at:number;source_kind:string;balance_verified:boolean}|null};
export type BrowserScreen={state:string;sequence:number;image?:HTMLImageElement;url?:string;capturedAt?:number;pagePath?:string;expiresAt?:number;execution?:ScreenExecution};
type Metadata={as_of:number;max_age_seconds:number;screens:Record<string,{state:string;sequence:number;captured_at:number|null;page_path:string|null;execution?:ScreenExecution}>};
const ids=['worm','adult','larva'];
const tokenPath=/^\/tokens\/(?:solana\/[1-9A-HJ-NP-Za-km-z]{32,44}|(?:robinhood|ethereum|base|bnb|monad)\/0x[0-9a-fA-F]{40})$/;
const empty=()=>Object.fromEntries(ids.map(id=>[id,{state:'connecting',sequence:0}])) as Record<BioId,BrowserScreen>;
export const screenState=(state:string)=>({live:'Live browser',connecting:'Connecting',private_page:'Private page hidden',page_loading:'Page changing',unsupported_layout:'View unavailable',stale:'Screen expired',unavailable:'Screen offline'}[state]||'Screen offline');

export function useFomoScreens(enabled:boolean){
  const [screens,setScreens]=useState<Record<BioId,BrowserScreen>>(empty);
  useEffect(()=>{
    if(!enabled)return;
    let stopped=false,timer:ReturnType<typeof setTimeout>,request:AbortController|null=null;
    let current=empty();
    const replace=(next:Record<BioId,BrowserScreen>)=>{
      for(const id of ids)if(current[id]?.url&&current[id].url!==next[id]?.url)URL.revokeObjectURL(current[id].url!);
      current=next;if(!stopped)setScreens(next);
    };
    const poll=async()=>{
      const controller=new AbortController();request=controller;
      const timeout=setTimeout(()=>controller.abort(),8000);
      try{
        const response=await fetch('/api/fomo-screens',{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw Error('Screen metadata unavailable');
        const data:Metadata=await response.json();
        if(!Number.isFinite(data.as_of)||data.max_age_seconds!==12||!data.screens)throw Error('Invalid screen metadata');
        const next={...current};
        await Promise.all(ids.map(async id=>{
          const row=data.screens[id];
          if(!row||row.state!=='live'||typeof row.captured_at!=='number'||!tokenPath.test(row.page_path||'')){
            next[id]={state:row?.state||'unavailable',sequence:row?.sequence||0,execution:row?.execution};return;
          }
          const age=data.as_of-row.captured_at;
          if(age<0||age>data.max_age_seconds){next[id]={state:'stale',sequence:row.sequence,execution:row.execution};return}
          if(current[id].sequence===row.sequence&&current[id].image&&performance.now()<(current[id].expiresAt||0)){next[id]={...current[id],execution:row.execution};return}
          let url:string|undefined;
          try{
            const received=performance.now();
            const frame=await fetch(`/api/fomo-screens/${id}/frame`,{cache:'no-store',signal:controller.signal});
            if(!frame.ok||!frame.headers.get('content-type')?.startsWith('image/jpeg'))throw Error('Frame unavailable');
            const at=Number(frame.headers.get('x-frame-time')),sequence=Number(frame.headers.get('x-frame-sequence'));
            if(!Number.isFinite(at)||!Number.isSafeInteger(sequence)||at<row.captured_at||at>data.as_of+10)throw Error('Frame timing mismatch');
            const blob=await frame.blob();if(blob.size>500_000)throw Error('Oversized frame');
            url=URL.createObjectURL(blob);const image=new Image();image.src=url;await image.decode();
            if(image.naturalWidth!==960||image.naturalHeight!==540)throw Error('Invalid frame dimensions');
            if(stopped){URL.revokeObjectURL(url);return}
            next[id]={state:'live',sequence,image,url,capturedAt:at,pagePath:row.page_path!,execution:row.execution,expiresAt:received+(data.max_age_seconds-Math.max(0,data.as_of-at))*1000};
          }catch{if(url)URL.revokeObjectURL(url);next[id]={state:'unavailable',sequence:row.sequence,execution:row.execution}}
        }));
        if(!stopped)replace(next);
      }catch{if(!stopped)replace(Object.fromEntries(ids.map(id=>[id,{state:'unavailable',sequence:0}])))}
      finally{clearTimeout(timeout);if(!stopped)timer=setTimeout(poll,2000)}
    };
    const expiry=setInterval(()=>{
      let changed=false;const next={...current};
      for(const id of ids)if(current[id].image&&performance.now()>=(current[id].expiresAt||0)){next[id]={state:'stale',sequence:current[id].sequence,execution:current[id].execution};changed=true}
      if(changed)replace(next);
    },1000);
    void poll();
    return()=>{stopped=true;clearTimeout(timer);clearInterval(expiry);request?.abort();for(const row of Object.values(current))if(row.url)URL.revokeObjectURL(row.url)};
  },[enabled]);
  return screens;
}

export function paintBrowserScreen(ctx:CanvasRenderingContext2D,screen:BrowserScreen,color:string){
  const w=ctx.canvas.width,h=ctx.canvas.height,footer=Math.round(h*.09);
  ctx.fillStyle='#0b1014';ctx.fillRect(0,0,w,h);
  if(screen.state==='live'&&screen.image){
    const scale=Math.min(w/960,(h-footer)/540),dw=960*scale,dh=540*scale;
    ctx.drawImage(screen.image,(w-dw)/2,(h-footer-dh)/2,dw,dh);
  }else{
    ctx.fillStyle=color;ctx.font=`600 ${w*.045}px monospace`;ctx.textAlign='center';ctx.fillText('FOMO',w/2,h*.39);
    ctx.fillStyle='#bcc6cb';ctx.font=`${w*.027}px monospace`;ctx.fillText(screenState(screen.state),w/2,h*.53);
    ctx.fillStyle='#738089';ctx.font=`${w*.02}px monospace`;ctx.fillText('READ-ONLY BROWSER VIEW',w/2,h*.63);ctx.textAlign='left';
  }
  ctx.fillStyle='#15201f';ctx.fillRect(0,h-footer,w,footer);
  ctx.fillStyle=screen.state==='live'?color:'#9dabb1';ctx.font=`${w*.022}px monospace`;
  ctx.fillText(screen.state==='live'?'● FOMO BROWSER · LIVE SNAPSHOTS':screenState(screen.state).toUpperCase(),w*.025,h-footer*.32);
}
