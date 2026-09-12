import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {Maximize2,RotateCcw,X} from 'lucide-react';
import type {BioId,Trace} from './types';
import {displayNames} from './english';
import {decodeActivity,type NeuralGeometry,type CellConnections} from './neuralData';
import {pointVertex,pointFragment,bodyVertex,bodyFragment} from './neuralShaders';
import './neuralView.css';

export default function NeuralView({bio,trace,color,active}:{bio:BioId;trace:Trace|null;color:string;active:boolean}){
  const root=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null);
  const [geometry,setGeometry]=useState<NeuralGeometry|null>(null),[error,setError]=useState('');
  const [selected,setSelected]=useState<number|null>(null),[pinned,setPinned]=useState(false),[expanded,setExpanded]=useState(false);
  const [connections,setConnections]=useState<CellConnections|null>(null),[connectionError,setConnectionError]=useState('');
  const activity=useMemo(()=>decodeActivity(trace),[trace?.id]);
  const live=useRef({trace,activity,active,started:performance.now()-10000}),selection=useRef({selected,pinned,connections});
  const redraw=useRef(()=>{}),reset=useRef(()=>{}),cache=useRef(new Map<string,CellConnections>());

  useEffect(()=>{const controller=new AbortController();setGeometry(null);setError('');
    fetch(`/connectomes/${bio}.json`,{signal:controller.signal}).then(r=>{if(!r.ok)throw Error('Geometry could not be loaded');return r.json()}).then(setGeometry).catch(e=>{if(e.name!=='AbortError')setError(e.message)});
    return()=>controller.abort();
  },[bio]);
  useLayoutEffect(()=>{
    live.current={trace,activity,active,started:trace?.id!==live.current.trace?.id?performance.now():live.current.started};redraw.current();
  },[trace,activity,active]);
  useLayoutEffect(()=>{selection.current={selected,pinned,connections};redraw.current()},[selected,pinned,connections]);
  useEffect(()=>{
    setConnections(null);setConnectionError('');
    const cell=selected!==null?geometry?.points[selected]:null;if(!cell||cell.index<0)return;
    const cached=cache.current.get(cell.id);if(cached){setConnections(cached);return}
    const controller=new AbortController();
    const timer=setTimeout(()=>fetch(`/api/connectomes/${bio}/cell/${cell.id}`,{signal:controller.signal}).then(r=>{
      if(!r.ok)throw Error('Connections unavailable');return r.json();
    }).then(data=>{if(cache.current.size>=64)cache.current.delete(cache.current.keys().next().value!);cache.current.set(cell.id,data);setConnections(data)}).catch(e=>{if(e.name!=='AbortError')setConnectionError(e.message)}),160);
    return()=>{clearTimeout(timer);controller.abort()};
  },[selected,geometry,bio]);

  useEffect(()=>{
    if(!geometry||!canvas.current||!root.current)return;
    const el=canvas.current,container=root.current,motion=matchMedia('(prefers-reduced-motion: reduce)');
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({canvas:el,alpha:true,antialias:false,powerPreference:'low-power'})}
    catch{setError('3D rendering is unavailable on this device.');return}
    renderer.setClearColor(0,0);renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,40);
    const controls=new OrbitControls(camera,el);controls.enableDamping=true;controls.dampingFactor=.12;controls.enablePan=false;controls.minDistance=1.4;controls.maxDistance=12;
    const positions=new Float32Array(geometry.points.flatMap(p=>p.position));
    const masks=new Float32Array(geometry.points.length),counts=new Float32Array(geometry.points.length),picked=new Float32Array(geometry.points.length);
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(positions,3));
    g.setAttribute('aMask',new THREE.BufferAttribute(masks,1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aCount',new THREE.BufferAttribute(counts,1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aSelected',new THREE.BufferAttribute(picked,1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aSimulated',new THREE.Float32BufferAttribute(geometry.points.map(p=>p.index>=0?1:0),1));
    const uniforms={uColor:{value:new THREE.Color(color)},uPhase:{value:-1},uPixelRatio:{value:renderer.getPixelRatio()},uTime:{value:0},uWorm:{value:bio==='worm'?1:0},uForward:{value:0},uReverse:{value:0}};
    const material=new THREE.ShaderMaterial({vertexShader:pointVertex,fragmentShader:pointFragment,uniforms,transparent:true,depthWrite:false});
    const cloud=new THREE.Points(g,material);scene.add(cloud);
    let body:THREE.Mesh<THREE.TubeGeometry,THREE.ShaderMaterial>|null=null;
    if(bio==='worm'){
      const bodyGeometry=new THREE.TubeGeometry(new THREE.LineCurve3(new THREE.Vector3(0,1.53,0),new THREE.Vector3(0,-1.53,0)),120,.12,16,false);
      const surface=bodyGeometry.attributes.position;
      for(let i=0;i<surface.count;i++){const axis=THREE.MathUtils.clamp(.5-surface.getY(i)/3.06,0,1);const taper=Math.pow(Math.sin(Math.PI*axis),.22);surface.setX(i,surface.getX(i)*taper);surface.setZ(i,surface.getZ(i)*taper)}
      bodyGeometry.computeVertexNormals();
      body=new THREE.Mesh(bodyGeometry,
        new THREE.ShaderMaterial({vertexShader:bodyVertex,fragmentShader:bodyFragment,uniforms,transparent:true,depthWrite:false,side:THREE.DoubleSide}));scene.add(body);
    }
    const edgeMaterial=new THREE.LineBasicMaterial({color,transparent:true,opacity:.28});
    const edges=new THREE.LineSegments(new THREE.BufferGeometry(),edgeMaterial);scene.add(edges);
    const pointById=new Map(geometry.points.map((p,i)=>[p.id,i]));
    const raycaster=new THREE.Raycaster();raycaster.params.Points={threshold:.022};
    let frame=0,lastFrame=0,visible=true,disposed=false,force=true,width=1,height=1,fitDistance=5,hadSize=false,lastHover=0;
    let lastTrace:string|undefined,lastSelected:number|null=null,lastConnections:CellConnections|null=null;
    let dragging=false,downX=0,downY=0;
    const wormCell=(prefix:string)=>geometry.points.filter(p=>p.name.startsWith(prefix)).map(p=>p.index);
    const forward=wormCell('AVB'),reverse=wormCell('AVA');
    const deformPoint=(p:THREE.Vector3)=>{
      if(bio==='worm'){const u=Math.max(0,Math.min(1,.5-p.y/3));p.x+=.07*Math.sin(u*7)+.2*(uniforms.uForward.value*Math.sin(u*9-uniforms.uTime.value*2.8)+uniforms.uReverse.value*Math.sin(u*9+uniforms.uTime.value*2.8))/Math.max(1,uniforms.uForward.value+uniforms.uReverse.value)}return p;
    };
    function schedule(){if(!frame&&!disposed&&!document.hidden&&(visible||force))frame=requestAnimationFrame(draw)}
    function draw(now:number){
      frame=0;if(disposed||document.hidden||(!visible&&!force)||(document.fullscreenElement&&document.fullscreenElement!==container))return;
      if(!force&&now-lastFrame<1000/30-.5){schedule();return}lastFrame=now;force=false;
      const state=live.current,animate=state.active&&!motion.matches,elapsed=now-state.started;
      if(lastTrace!==state.trace?.id){
        geometry!.points.forEach((p,i)=>{masks[i]=p.index>=0?state.activity?.masks[p.index]||0:0;counts[i]=p.index>=0?state.activity?.counts[p.index]||0:0});
        g.attributes.aMask.needsUpdate=g.attributes.aCount.needsUpdate=true;lastTrace=state.trace?.id;
      }
      uniforms.uPhase.value=animate&&elapsed<3150?elapsed/3000*20:-1;
      uniforms.uTime.value=animate?now/1000:0;
      const mean=(indices:number[])=>indices.reduce((sum,i)=>sum+(state.activity?.counts[i]||0),0)/Math.max(1,indices.length);
      uniforms.uForward.value=animate&&elapsed<3150?Math.min(1,mean(forward)/6):0;uniforms.uReverse.value=animate&&elapsed<3150?Math.min(1,mean(reverse)/6):0;
      const current=selection.current;
      if(lastSelected!==current.selected){picked.fill(0);if(current.selected!==null)picked[current.selected]=1;g.attributes.aSelected.needsUpdate=true;lastSelected=current.selected}
      if(lastConnections!==current.connections||edges.userData.selected!==current.selected){
        const lines:number[]=[];const cell=current.selected!==null?geometry!.points[current.selected]:null;
        if(cell&&current.connections?.node.id===cell.id)for(const edge of current.connections.connections){const partner=pointById.get(edge.partner_id);if(partner!==undefined)lines.push(...cell.position,...geometry!.points[partner].position)}
        edges.geometry.dispose();edges.geometry=new THREE.BufferGeometry();edges.geometry.setAttribute('position',new THREE.Float32BufferAttribute(lines,3));
        lastConnections=current.connections;edges.userData.selected=current.selected;
      }
      // Worm's body moves; incident lines follow the same displayed endpoints.
      if(bio==='worm'&&current.selected!==null&&current.connections?.node.id===geometry!.points[current.selected].id){
        const lines:number[]=[];for(const edge of current.connections.connections){const partner=pointById.get(edge.partner_id);if(partner!==undefined){lines.push(...deformPoint(new THREE.Vector3(...geometry!.points[current.selected].position)).toArray(),...deformPoint(new THREE.Vector3(...geometry!.points[partner].position)).toArray())}}
        edges.geometry.setAttribute('position',new THREE.Float32BufferAttribute(lines,3));
      }
      controls.update();renderer.render(scene,camera);el.dataset.points=String(geometry!.points.length);el.dataset.edges=String(edges.geometry.attributes.position.count/2);
      if(animate&&visible&&elapsed<3150)schedule();
    }
    redraw.current=()=>{force=true;schedule()};
    reset.current=()=>{camera.position.set(0,.05,fitDistance);controls.target.set(0,0,0);controls.update();redraw.current()};
    const resize=()=>{width=container.clientWidth;height=container.clientHeight;renderer.setSize(width,height,false);camera.aspect=width/Math.max(1,height);camera.updateProjectionMatrix();
      const xSpan=bio==='adult'?3.55:1.5,ySpan=bio==='adult'?2.25:3.65;
      const previousFit=fitDistance;fitDistance=Math.max(xSpan/camera.aspect,ySpan)/(2*Math.tan(THREE.MathUtils.degToRad(20)));
      if(!hadSize){hadSize=true;reset.current()}else camera.position.sub(controls.target).multiplyScalar(fitDistance/previousFit).add(controls.target);
      force=true;schedule();};
    const pick=(event:PointerEvent)=>{
      if(event.buttons||selection.current.pinned||performance.now()-lastHover<55)return;lastHover=performance.now();
      const r=el.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;let index:number|null=null;
      if(bio==='worm'){
        let closest=8;geometry!.points.forEach((p,i)=>{const v=deformPoint(new THREE.Vector3(...p.position)).project(camera);const distance=Math.hypot((v.x+1)*width/2-x,(1-v.y)*height/2-y);if(distance<closest){closest=distance;index=i}});
      }else{raycaster.setFromCamera(new THREE.Vector2(x/width*2-1,-y/height*2+1),camera);const hit=raycaster.intersectObject(cloud)[0];index=hit?.index??null}
      setSelected(index);return index;
    };
    const pointerDown=(e:PointerEvent)=>{downX=e.clientX;downY=e.clientY;dragging=false};
    const pointerMove=(e:PointerEvent)=>{if(e.buttons&&Math.hypot(e.clientX-downX,e.clientY-downY)>5)dragging=true;pick(e)};
    const pointerUp=(e:PointerEvent)=>{if(dragging)return;if(selection.current.pinned){setPinned(false);return}lastHover=0;const index=pick(e);setPinned(index!==undefined&&index!==null)};
    const pointerLeave=()=>{if(!selection.current.pinned)setSelected(null)};
    const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(container);
    const intersection=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;if(visible)schedule();else{cancelAnimationFrame(frame);frame=0}});intersection.observe(container);
    const visibility=()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0}else schedule()};
    const contextLost=(event:Event)=>{event.preventDefault();if(!disposed){setError('3D context was lost. Refresh to reconnect this view.');disposed=true;cancelAnimationFrame(frame);frame=0}};
    controls.addEventListener('change',schedule);el.addEventListener('pointerdown',pointerDown);el.addEventListener('pointermove',pointerMove);el.addEventListener('pointerup',pointerUp);el.addEventListener('pointerleave',pointerLeave);el.addEventListener('webglcontextlost',contextLost);
    document.addEventListener('visibilitychange',visibility);document.addEventListener('fullscreenchange',redraw.current);motion.addEventListener('change',redraw.current);resize();
    return()=>{disposed=true;cancelAnimationFrame(frame);resizeObserver.disconnect();intersection.disconnect();controls.dispose();
      el.removeEventListener('pointerdown',pointerDown);el.removeEventListener('pointermove',pointerMove);el.removeEventListener('pointerup',pointerUp);el.removeEventListener('pointerleave',pointerLeave);el.removeEventListener('webglcontextlost',contextLost);
      document.removeEventListener('visibilitychange',visibility);document.removeEventListener('fullscreenchange',redraw.current);motion.removeEventListener('change',redraw.current);
      g.dispose();material.dispose();body?.geometry.dispose();body?.material.dispose();edges.geometry.dispose();edgeMaterial.dispose();renderer.dispose();renderer.forceContextLoss();redraw.current=()=>{};reset.current=()=>{};};
  },[geometry,bio,color]);

  useEffect(()=>{const change=()=>setExpanded(document.fullscreenElement===root.current);document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change)},[]);
  const expand=()=>{if(document.fullscreenElement===root.current)void document.exitFullscreen();else void root.current?.requestFullscreen().catch(()=>setError('Fullscreen is unavailable in this browser.'))};
  const cell=selected!==null?geometry?.points[selected]:null;
  const rates=(prefix:string)=>(geometry?.points.filter(p=>p.name.startsWith(prefix)).reduce((sum,p)=>sum+(activity?.counts[p.index]||0),0)||0)*1000/(trace?.simulated_ms||200)/2;
  return <div ref={root} className={`neural-view neural-${bio}`} aria-label={`${displayNames[bio]} interactive neural view`}>
    <canvas ref={canvas} aria-label={`${displayNames[bio]} ${geometry?.method||'neural geometry'}. Drag to rotate, scroll to zoom, click a cell to inspect.`}/>
    <div className="neural-view-title"><span>{bio==='worm'?'BODY AXIS':bio==='adult'?'FLYWIRE / v783':bio==='larva'?'BILATERAL CIRCUIT':'NEURAL GEOMETRY'}</span><span className={active?'neural-live':'neural-static'}>{active?'RECORDED SPIKES':'LAST WINDOW'}</span></div>
    <div className="neural-view-tools"><button onClick={()=>reset.current()} aria-label={`Reset ${displayNames[bio]} view`} title="Reset view"><RotateCcw size={13}/></button><button onClick={expand} aria-label={`${expanded?'Close':'Expand'} ${displayNames[bio]} neural view`} title="Fullscreen">{expanded?<X size={14}/>:<Maximize2 size={14}/>}</button></div>
    {(!geometry||error)&&<p className="neural-loading">{error||'Loading source geometry…'}</p>}
    {bio==='worm'&&<div className="worm-axis-labels"><span>ANTERIOR / SENSORY</span><span>POSTERIOR / MOTOR</span></div>}
    {bio==='larva'&&<div className="larva-axis-labels"><span>LEFT</span><span>RIGHT</span></div>}
    {cell&&<div className={`neural-cell-info ${pinned?'pinned':''}`}>
      <strong>{cell.name}</strong><span>{cell.id}</span><span>{cell.type} · {cell.region}</span>
      <b>{cell.index<0?'Anatomical context':`${activity?.counts[cell.index]??'—'} spikes / ${trace?.simulated_ms||200} ms`}</b>
      {cell.index>=0&&<small>{connectionError||(connections?.node.id===cell.id?`${connections.shown_connections} / ${connections.total_connections} incident connections · simulated graph`:'Loading synaptic partners…')}</small>}
      {pinned&&<button aria-label="Clear selected neuron" onClick={()=>{setPinned(false);setSelected(null)}}><X size={13}/></button>}
    </div>}
    <div className="neural-view-bottom"><div>{bio==='worm'?<><span>AVB <b>{rates('AVB').toFixed(0)} Hz</b> →</span><span>← AVA <b>{rates('AVA').toFixed(0)} Hz</b></span></>:bio==='adult'?<><span><i className="sim-dot"/> {geometry?.located_simulated.toLocaleString()||'—'} simulated</span><span><i className="context-dot"/> {geometry?(geometry.displayed_points-geometry.located_simulated).toLocaleString():'—'} context</span></>:<><span>{geometry?.displayed_points.toLocaleString()||'—'} cells</span><span>{bio==='larva'?'Curated pairs + cell types':'Dataset geometry'}</span></>}</div><small>DRAG TO ROTATE · SCROLL TO ZOOM · CLICK TO PIN</small></div>
  </div>
}
