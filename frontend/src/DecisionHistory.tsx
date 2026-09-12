import {useEffect,useRef,useState,type ReactNode} from 'react';
import {X,ArrowUpRight} from 'lucide-react';
import type {Bio,Trace} from './types';
import {displayNames,englishReason} from './english';
import './decisionHistory.css';

type Item=Pick<Trace,'id'|'bio_id'|'sequence'|'created_at'|'action'|'score'|'spikes'|'fill'|'asset'>&{event_sequence:number};
type Page={run_id:string;items:Item[];next_before:number|null};
export default function DecisionHistory({bio,runId,onClose,renderTrace}:{bio:Bio;runId:string;onClose:()=>void;renderTrace:(trace:Trace|null)=>ReactNode}){
  const [items,setItems]=useState<Item[]>([]),[next,setNext]=useState<number|null>(null),[selected,setSelected]=useState<string|null>(bio.telemetry?.id||null);
  const [trace,setTrace]=useState<Trace|null>(bio.telemetry),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const root=useRef<HTMLElement>(null),abort=useRef<AbortController|null>(null),alive=useRef(true),close=useRef(onClose);close.current=onClose;
  useEffect(()=>{
    alive.current=true;const previous=document.activeElement as HTMLElement|null,overflow=document.body.style.overflow;document.body.style.overflow='hidden';root.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const key=(event:KeyboardEvent)=>{if(event.key==='Escape')close.current();if(event.key!=='Tab')return;
      const controls=root.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]');if(!controls?.length)return;const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}};
    document.addEventListener('keydown',key);return()=>{alive.current=false;abort.current?.abort();document.removeEventListener('keydown',key);document.body.style.overflow=overflow;previous?.focus()};
  },[]);
  const load=async(before?:number)=>{
    abort.current?.abort();const controller=new AbortController();abort.current=controller;setBusy(true);setError('');
    try{const response=await fetch(`/api/connectomes/${bio.id}/decisions?limit=25${before?`&before=${before}`:''}`,{signal:controller.signal});if(!response.ok)throw Error('Decision history could not load.');const page:Page=await response.json();
      if(page.run_id!==runId)throw Error('The session changed. Reopen history to see the new run.');
      setItems(previous=>before?[...previous,...page.items.filter(item=>!previous.some(p=>p.id===item.id))]:page.items);setNext(page.next_before);if(!selected&&page.items.length)setSelected(page.items[0].id);
    }catch(e){if(!controller.signal.aborted&&alive.current)setError(e instanceof Error?e.message:'History unavailable.')}finally{if(!controller.signal.aborted&&alive.current)setBusy(false)}
  };
  useEffect(()=>{void load();return()=>abort.current?.abort()},[bio.id,runId]);
  useEffect(()=>{
    if(!selected){setTrace(null);return}if(bio.telemetry?.id===selected){setTrace(bio.telemetry);return}
    const controller=new AbortController();setTrace(null);
    fetch(`/api/decisions/${encodeURIComponent(selected)}`,{signal:controller.signal}).then(r=>{if(!r.ok)throw Error('Decision details could not load.');return r.json()}).then(setTrace).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return()=>controller.abort();
  },[selected,bio.telemetry?.id]);
  return <div className="history-backdrop" onClick={onClose}><section className="history-dialog" ref={root} role="dialog" aria-modal="true" aria-label={`${displayNames[bio.id]} decision history`} style={{'--bio':bio.metadata.color} as React.CSSProperties} onClick={e=>e.stopPropagation()}>
    <header className="history-heading"><div><span className="eyebrow">INDIVIDUAL DECISION RECORD</span><h2>{displayNames[bio.id]} <span>Decision history</span></h2></div><button className="icon-button" aria-label="Close decision history" onClick={onClose}><X size={20}/></button></header>
    <div className="history-summary"><span>{bio.account.trades} filled orders</span><span>{bio.training?.samples||0} outcome samples</span><button onClick={()=>void load()} disabled={busy}>Refresh records</button></div>
    {error&&<p className="history-error" role="status">{error}</p>}
    <div className="history-columns"><div className="history-list" aria-label="Recorded decisions">
      {items.map(item=><button className={`history-row ${item.id===selected?'selected':''}`} key={item.id} onClick={()=>setSelected(item.id)} aria-label={`Open ${displayNames[bio.id]} decision ${item.sequence}`} aria-pressed={item.id===selected}>
        <span><b>#{String(item.sequence).padStart(4,'0')}</b><time>{new Date(item.created_at*1000).toLocaleTimeString('en-GB',{hour12:false})}</time><strong className={`history-action ${item.action.toLowerCase()}`}>{item.action}</strong><ArrowUpRight size={12}/></span>
        {item.asset&&<small className="history-token">{item.asset.symbol} · {item.asset.chain}</small>}<small>{item.fill.status==='filled'?`Filled $${(item.fill.notional||0).toFixed(2)}`:englishReason(item.fill.reason)}</small>
      </button>)}
      {!items.length&&<p className="history-empty">{busy?'Loading records…':'No decisions yet. This brain is waiting for its first check.'}</p>}
      {next!==null&&<button className="outline-button history-more" disabled={busy} onClick={()=>void load(next)}>{busy?'Loading…':'Load earlier decisions'}</button>}
    </div><div className="history-detail">{renderTrace(trace)}</div></div>
  </section></div>
}
