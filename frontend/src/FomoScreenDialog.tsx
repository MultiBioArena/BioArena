import {useEffect,useRef,useState} from 'react';
import {X,Plus,Minus} from 'lucide-react';
import type {BrowserScreen} from './fomoScreens';
import {screenState} from './fomoScreens';
import {displayNames} from './english';
import './fomoScreens.css';

export default function FomoScreenDialog({bio,screens,onSelect,onClose}:{bio:string;screens:Record<string,BrowserScreen>;onSelect:(id:string)=>void;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null),row=screens[bio];
  const [scale,setScale]=useState(1);
  useEffect(()=>setScale(1),[bio]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    dialog.current?.showModal();
    return()=>{dialog.current?.close();previous?.focus()};
  },[]);
  return <dialog ref={dialog} className="fomo-screen-dialog" aria-labelledby="fomo-screen-title" onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="fomo-screen-heading"><div><span className="fomo-screen-eyebrow">ACTUAL BROWSER / READ ONLY</span><h2 id="fomo-screen-title">{displayNames[bio]||bio} · FOMO screen</h2></div><button onClick={onClose} aria-label="Close FOMO screen"><X size={20}/></button></div>
    <div className="fomo-screen-tabs" aria-label="Choose a browser screen">{['worm','adult','larva'].map(id=><button key={id} aria-pressed={bio===id} onClick={()=>onSelect(id)}>{displayNames[id]}</button>)}<span className={row?.state==='live'?'is-live':''}>{screenState(row?.state||'unavailable')}</span></div>
    <div className={`fomo-screen-image ${scale>1?'is-zoomed':''}`} style={{'--screen-zoom':scale} as React.CSSProperties}>{row?.state==='live'&&row.url?<img src={row.url} alt={`${displayNames[bio]} current FOMO token page. This image cannot place orders.`}/>:<div><strong>{screenState(row?.state||'unavailable')}</strong><p>Only the current token chart and trade form can be shown.</p></div>}</div>
    <div className="fomo-screen-zoom"><span>{row?.capturedAt?`Captured ${new Date(row.capturedAt*1000).toLocaleTimeString('en-GB',{hour12:false})}`:'No public frame'}</span><button disabled={scale===1} onClick={()=>setScale(s=>Math.max(1,s-.5))} aria-label="Zoom out FOMO screen"><Minus size={16}/></button><small>{Math.round(scale*100)}%</small><button disabled={scale===3} onClick={()=>setScale(s=>Math.min(3,s+.5))} aria-label="Zoom in FOMO screen"><Plus size={16}/></button></div>
    <p className="fomo-screen-note">Live snapshots refresh every few seconds. A token page or quote does not confirm a fill. Bios stay at their desks; gestures replay verified real fills. Portfolio cards remain paper data.</p>
  </dialog>;
}
