import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import type {BioId,Graph,Trace} from './types';
import {hash,routePoint,specimenLayout,type Point} from './specimenLayout';
import {displayNames} from './english';

const PLAYBACK_MS=3000;
type Playback={trace:Trace|null;started:number;bins:Float32Array};

export function BrainGraph({bio,graph,trace,color,active}:{bio:BioId;graph:Graph|undefined;trace:Trace|null;color:string;active:boolean}){
  const canvas=useRef<HTMLCanvasElement>(null),positions=useRef<Point[]>([]);
  const playback=useRef<Playback>({trace:null,started:0,bins:new Float32Array()});
  const enabled=useRef(active),refresh=useRef(()=>{});
  const [hover,setHover]=useState<number|null>(null);

  useLayoutEffect(()=>{
    enabled.current=active;
    if(trace?.id!==playback.current.trace?.id){
      const bins=new Float32Array(20*(trace?.sample_size||0));
      for(const [bin,node,count] of trace?.raster||[])bins[bin*trace!.sample_size+node]=count;
      playback.current={trace,started:performance.now(),bins};
    }
    refresh.current();
  },[trace,active]);

  useEffect(()=>{
    if(!graph||!canvas.current)return;
    const el=canvas.current,ctx=el.getContext('2d')!;
    const background=document.createElement('canvas'),back=background.getContext('2d')!;
    const glow=document.createElement('canvas');glow.width=glow.height=64;
    const g=glow.getContext('2d')!,gradient=g.createRadialGradient(32,32,0,32,32,32);
    gradient.addColorStop(0,color+'d9');gradient.addColorStop(.18,color+'70');gradient.addColorStop(.48,color+'20');gradient.addColorStop(1,color+'00');
    g.fillStyle=gradient;g.fillRect(0,0,64,64);
    const motion=matchMedia('(prefers-reduced-motion: reduce)');
    let frame=0,w=0,h=0,dpr=1,visible=true,lastFrame=0;
    let p:Point[]=[],paths:Path2D[]=[],routes:Point[][]=[],body=new Path2D();
    const light=new Float32Array(graph.nodes.length);
    const phase=graph.nodes.map(n=>hash(n.id+'pulse')*.35);
    // Cache geometry and static links; telemetry updates keep the animation loop.
    const resize=()=>{
      const rect=el.getBoundingClientRect();w=rect.width;h=rect.height;dpr=Math.min(devicePixelRatio||1,2);
      el.width=background.width=Math.round(w*dpr);el.height=background.height=Math.round(h*dpr);
      const layout=specimenLayout(bio,graph,w,h);p=layout.positions;routes=layout.routes;body=layout.body;positions.current=p;
      back.setTransform(dpr,0,0,dpr,0,0);back.clearRect(0,0,w,h);
      back.fillStyle=color+'08';back.fill(body);back.strokeStyle=color+'50';back.lineWidth=1;back.stroke(body);
      back.strokeStyle=color+'36';back.stroke(layout.details);
      paths=routes.map(points=>{const path=new Path2D();points.forEach((point,i)=>i?path.lineTo(point.x,point.y):path.moveTo(point.x,point.y));return path});
      back.save();back.clip(body);back.lineWidth=.6;back.strokeStyle=color+'12';for(const path of paths)back.stroke(path);back.restore();
      cancelAnimationFrame(frame);frame=0;draw(performance.now(),true);
    };
    const draw=(now:number,force=false)=>{
      frame=0;if((!visible&&!force)||document.hidden||!w||!h)return;
      const current=playback.current,t=current.trace,animate=enabled.current&&visible&&!motion.matches&&!!t;
      const elapsed=now-current.started,position=elapsed/PLAYBACK_MS*20;
      const delta=Math.max(0,Math.min(80,lastFrame?now-lastFrame:16.7));lastFrame=Math.max(lastFrame,now);
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.globalAlpha=1;ctx.clearRect(0,0,w,h);ctx.drawImage(background,0,0,w,h);
      for(let i=0;i<p.length;i++){
        let target=0;
        if(animate&&position<21){
          const bin=Math.floor(position);
          for(let b=Math.max(0,bin-2);b<=Math.min(19,bin);b++){
            const count=current.bins[b*t!.sample_size+i],age=position-b-phase[i];
            if(count&&age>=0)target=Math.max(target,Math.min(1,.45+count*.2)*Math.exp(-age*2.7));
          }
          light[i]=target>light[i]?light[i]+(target-light[i])*(1-Math.exp(-delta/24)):light[i]*Math.exp(-delta/115);
        }else light[i]=animate?light[i]*Math.exp(-delta/115):0;
      }
      // Travel shows real links with illustrative timing, not measured conduction.
      ctx.save();ctx.clip(body);
      for(let e=0;e<graph.edges.length;e++){
        const [a,b,,sign]=graph.edges[e],pulse=light[a];
        if(pulse>.05){ctx.globalAlpha=pulse*.22;ctx.strokeStyle=color;ctx.lineWidth=sign<0?.6:.9;ctx.stroke(paths[e])}
        if(!animate||e%5!==0||position>23)continue;
        const travel=2.3+(e%7)*.19,firstBin=Math.max(0,Math.floor(position-travel-phase[a]));
        for(let bin=firstBin;bin<=Math.min(19,Math.floor(position));bin++){
          if(!current.bins[bin*t!.sample_size+a])continue;
          const progress=(position-bin-phase[a])/travel;if(progress<0||progress>1)continue;
          const head=routePoint(routes[e],progress),tail=routePoint(routes[e],Math.max(0,progress-.12));
          ctx.strokeStyle=color;ctx.lineWidth=1.15;ctx.globalAlpha=.55*Math.sin(progress*Math.PI);
          ctx.beginPath();ctx.moveTo(tail.x,tail.y);ctx.lineTo(head.x,head.y);ctx.stroke();
          ctx.globalAlpha=.85;ctx.fillStyle='#f2ffe7';ctx.beginPath();ctx.arc(head.x,head.y,1.05,0,Math.PI*2);ctx.fill();
        }
      }
      ctx.restore();
      graph.nodes.forEach((node,i)=>{
        const count=t?.sample_counts[i]||0,level=light[i],base=node.role==='inter'?1.25:2.25;
        if(count){
          const size=animate?9+level*22:12;
          ctx.globalAlpha=animate?.14+level*.8:.55;ctx.drawImage(glow,p[i].x-size/2,p[i].y-size/2,size,size);
        }
        ctx.globalAlpha=count?(animate?.38+level*.62:.85):.24;ctx.fillStyle=count?color:'#b6c5b0';
        ctx.beginPath();ctx.arc(p[i].x,p[i].y,base+level*1.2,0,Math.PI*2);ctx.fill();
        if(level>.3&&node.role!=='inter'){
          ctx.globalAlpha=level*.45;ctx.strokeStyle=color;ctx.lineWidth=.7;
          ctx.beginPath();ctx.arc(p[i].x,p[i].y,base+2+(1-level)*5,0,Math.PI*2);ctx.stroke();
        }
      });ctx.globalAlpha=1;
      if(animate&&elapsed<PLAYBACK_MS+600)schedule();
    };
    function schedule(){if(!frame&&visible&&!document.hidden)frame=requestAnimationFrame(draw)}
    refresh.current=()=>{if(visible)schedule();else draw(performance.now(),true)};
    const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(el);
    const intersection=new IntersectionObserver(([entry])=>{
      visible=entry.isIntersecting;if(visible)schedule();else{cancelAnimationFrame(frame);frame=0}
    });intersection.observe(el);
    const visibility=()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0}else schedule()};
    document.addEventListener('visibilitychange',visibility);motion.addEventListener('change',schedule);resize();
    return()=>{cancelAnimationFrame(frame);resizeObserver.disconnect();intersection.disconnect();document.removeEventListener('visibilitychange',visibility);motion.removeEventListener('change',schedule);refresh.current=()=>{}};
  },[bio,graph,color]);

  const neuron=hover!==null?graph?.nodes[hover]:null;
  return <div className="brain-graph" data-playback={active?'active':'stopped'}>
    <div className="graph-label left">{displayNames[bio].toUpperCase()} HEAD</div><div className="graph-label right">NOT ANATOMICAL</div>
    <canvas ref={canvas} aria-label={displayNames[bio]+' head silhouette with '+(graph?.sample_size||0)+' sampled neurons. Illustrative layout, not anatomical positions. Recorded spike playback.'} onMouseLeave={()=>setHover(null)} onMouseMove={e=>{
      const r=e.currentTarget.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
      let nearest=-1,d=12;positions.current.forEach((p,i)=>{const dist=Math.hypot(p.x-x,p.y-y);if(dist<d){d=dist;nearest=i}});setHover(nearest<0?null:nearest);
    }}/>
    <span className="playback-label" title="Recorded spike bins stretched across the display interval. Moving signals follow real connections; their travel times are illustrative.">{active?'SPIKE PLAYBACK':'LAST WINDOW'} <i/></span>
    {neuron&&hover!==null&&<div className="node-tooltip"><strong>{neuron.name}</strong><span>{neuron.id} · {neuron.role==='input'?'Sensory':neuron.role==='buy'?'Buy readout':neuron.role==='sell'?'Sell readout':'Interneuron'}</span><span>{trace?.sample_counts[hover]||0} spikes · {trace?.sample_v_mv[hover]?.toFixed(1)??'—'} mV</span></div>}
  </div>
}

export function Raster({trace,color,active}:{trace:Trace|null;color:string;active:boolean}){
  return <svg className="raster" viewBox="0 0 400 35" preserveAspectRatio="none" role="img" aria-label="Sampled spike counts by simulated time bin">
    {[0,100,200,300,400].map(x=><line key={x} x1={x} x2={x} y1={0} y2={35} stroke="#ffffff0b"/>)}
    {trace?.raster.map(([t,n,count])=><rect key={t+'-'+n} x={t*20+2} y={n/trace.sample_size*32} width={1.5+Math.min(count,3)} height={1.5} fill={color} opacity={.5+Math.min(count,5)*.1}/>)}
    {trace&&active&&<line key={trace.id} className="raster-playhead" x1={0} x2={0} y1={0} y2={35} stroke={color} strokeWidth={1} opacity={.7}/>}
  </svg>
}
