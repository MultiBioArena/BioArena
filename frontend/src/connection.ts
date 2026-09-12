import type {ArenaState} from './types';

export function connectArena(onState:(state:ArenaState)=>void,onConnection:(connected:boolean)=>void){
  let disposed=false;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let request:AbortController|undefined;
  let ws:WebSocket|undefined;
  let pending=false;
  let ended=false;
  const polling=import.meta.env.VITE_ARENA_TRANSPORT==='poll';

  const poll=async()=>{
    if(disposed||pending||document.hidden)return;
    pending=true;
    request=new AbortController();
    const timeout=setTimeout(()=>request?.abort(),10000);
    let delay=ended?30000:3000;
    try{
      const response=await fetch('/api/state',{cache:'no-store',signal:request.signal});
      if(!response.ok)throw Error(`Arena HTTP ${response.status}`);
      const state:ArenaState=await response.json();
      if(disposed)return;
      onState(state);onConnection(true);
      ended=['finished','error'].includes(state.status);
      delay=ended?30000:3000;
    }catch{
      if(!disposed)onConnection(false);
      delay=10000;
    }finally{
      clearTimeout(timeout);pending=false;
      if(!disposed&&!document.hidden)timer=setTimeout(poll,delay);
    }
  };
  const visibility=()=>{
    clearTimeout(timer);
    if(!document.hidden)void poll();
  };
  const connect=()=>{
    ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
    ws.onopen=()=>{if(!disposed)onConnection(true)};
    ws.onmessage=event=>{if(!disposed)onState(JSON.parse(event.data))};
    ws.onclose=()=>{if(!disposed){onConnection(false);timer=setTimeout(connect,2500)}};
    ws.onerror=()=>ws?.close();
  };
  if(polling){document.addEventListener('visibilitychange',visibility);void poll()}
  else connect();
  return()=>{
    disposed=true;clearTimeout(timer);request?.abort();ws?.close();
    document.removeEventListener('visibilitychange',visibility);
  };
}
