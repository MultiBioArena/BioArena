import {useState} from 'react';
import {displayNames} from './english';
import type {Bio} from './types';
export function EquityChart({bios,initial}:{bios:Bio[];initial:number}){
  const [hover,setHover]=useState<number|null>(null);
  const all=bios.flatMap(b=>b.history.map(p=>p.equity));
  const times=bios.flatMap(b=>b.history.map(p=>p.time));
  const low=Math.min(initial,...all),high=Math.max(initial,...all),range=Math.max(2,high-low);
  const min=low-range*.18,max=high+range*.18+(range-(high-low));
  const first=Math.min(...times),last=Math.max(...times);
  const y=(v:number)=>185-(v-min)/(max-min)*160;
  const x=(t:number)=>64+(t-first)/Math.max(1,last-first)*676;
  const format=(t:number)=>new Date(t*1000).toLocaleTimeString('en-GB',{hour12:false});
  return <div className="equity-chart">
    {!all.length?<div className="empty-chart">Waiting for the first neural decision<span>Equity history will follow actual paper fills.</span></div>:<>
      <svg viewBox="0 0 780 220" role="img" aria-label="Recorded equity of three independent paper accounts" onMouseLeave={()=>setHover(null)} onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setHover(Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*780-64)/676)))}}>
        {[0,1,2,3,4].map(i=>{const v=min+(max-min)*i/4;return <g key={i}><line x1={64} x2={740} y1={y(v)} y2={y(v)} stroke="#ffffff0a"/><text x={49} y={y(v)+4} textAnchor="end">{v.toFixed(1)}</text></g>})}
        <line x1={64} x2={740} y1={y(initial)} y2={y(initial)} stroke="#ffffff26" strokeDasharray="3 5"/>
        {bios.map(b=><g key={b.id}><polyline points={b.history.map(p=>`${x(p.time)},${y(p.equity)}`).join(' ')} fill="none" stroke={b.metadata.color} strokeWidth="2" strokeLinejoin="round"/>{b.history.length>0&&<circle cx={x(b.history.at(-1)!.time)} cy={y(b.history.at(-1)!.equity)} r={3} fill={b.metadata.color}/>}</g>)}
        {[0,.5,1].map(v=><text key={v} x={64+676*v} y={210} textAnchor={v===0?'start':v===1?'end':'middle'}>{format(first+v*(last-first))}</text>)}
        {hover!==null&&<line x1={64+hover*676} x2={64+hover*676} y1={20} y2={185} stroke="#ffffff44" strokeDasharray="2 3"/>}
      </svg>
      {hover!==null&&<div className="chart-tooltip"><span>{format(first+hover*(last-first))}</span>{bios.map(b=>{const point=b.history.reduce((a,p)=>Math.abs(p.time-(first+hover*(last-first)))<Math.abs(a.time-(first+hover*(last-first)))?p:a,b.history[0]);return <span key={b.id} style={{color:b.metadata.color}}>{displayNames[b.id]}: {point?.equity.toFixed(2)}</span>})}</div>}
    </>}
  </div>
}
