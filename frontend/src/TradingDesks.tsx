import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {Maximize2,Minus,Plus,RotateCcw,ArrowUpRight,X} from 'lucide-react';
import type {Bio,BioId,Trace,Quote,MarketAsset} from './types';
import {deskMarket,tokenPrice} from './marketDisplay';
import {candidateScreens,collectCandidatePrices} from './candidateScreens';
import {displayNames,englishReason} from './english';
import {buildDeskScene} from './buildDeskScene';
import {DESK_REPLAY_MS,deskPlayback,recordedAction,executionPlayback} from './deskPlayback';
import {buildMarketWall,connectMarketWall} from './marketWall';
import type {BoardFeed} from './marketWall';
import './tradingDesks.css';
import {useFomoScreens,screenState} from './fomoScreens';
import FomoScreenDialog from './FomoScreenDialog';

const browserScreens=import.meta.env.VITE_EXECUTION_PREVIEW==='true';

type Playback={trace:Trace|null;started:number;playing:boolean;manual:boolean;stage:'return'|'press'};
type Props={bios:Bio[];active:boolean;market:Quote|null;marketHistory:{time:number;price:number}[];marketFresh:boolean;serverTime:number;onHistory:(id:BioId)=>void;assets?:MarketAsset[]};

export default function TradingDesks(props:Props){
  const {bios,active,market,marketHistory,marketFresh,serverTime,onHistory}=props;
  const assets=props.assets||[];
  const [screenPins,setScreenPins]=useState<Partial<Record<BioId,string>>>({});
  const frames=useFomoScreens(browserScreens),frameRef=useRef(frames);frameRef.current=frames;
  const [screenBio,setScreenBio]=useState<string|null>(null);
  const executionReplays=useRef(new Map<string,{key:string;started:number;playing:boolean}>());
  const pins=useRef(screenPins);pins.current=screenPins;
  const multi=bios.some(b=>b.account.positions!==undefined);
  const root=useRef<HTMLElement>(null),host=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null);
  const stations=useRef(new Map<BioId,HTMLButtonElement>()),statuses=useRef(new Map<BioId,HTMLSpanElement>()),clocks=useRef(new Map<BioId,HTMLSpanElement>());
  const records=useRef(new Map<BioId,Playback>()),latest=useRef({...props,received:performance.now()});
  const refresh=useRef(()=>{}),focus=useRef((_:string)=>{}),zoom=useRef((_:number)=>{}),replay=useRef((_:BioId)=>{});
  const [failed,setFailed]=useState(false),[ready,setReady]=useState(false),[expanded,setExpanded]=useState(false),[cameraFocus,setCameraFocus]=useState('all');
  const signature=bios.map(b=>b.id+b.metadata.color).join(',');
  useEffect(()=>{
    for(const [id,frame] of Object.entries(frames)){
      if(!frame.execution)continue;
      const order=frame.execution?.order,key=order?`${order.at}:${order.action}:${order.status}`:'none',previous=executionReplays.current.get(id);
      if(previous?.key!==key)executionReplays.current.set(id,{key,started:performance.now(),playing:!!previous&&frame.execution?.fresh===true&&order?.status==='filled'&&order.balance_verified});
    }
    refresh.current();
  },[frames]);

  useLayoutEffect(()=>{
    latest.current={...props,received:performance.now()};
    for(const bio of bios){
      const previous=records.current.get(bio.id);
      if(!previous||previous.trace?.id!==bio.telemetry?.id){
        const fresh=!!bio.telemetry&&serverTime-bio.telemetry.created_at<8;
        records.current.set(bio.id,{trace:bio.telemetry,started:performance.now(),playing:!!previous&&active&&fresh&&bio.account.alive&&recordedAction(bio.telemetry)!=='HOLD',manual:false,stage:'return'});
      }else if(!active&&!previous.manual)previous.playing=false;
    }
    refresh.current();
  },[bios,active,market,marketHistory,marketFresh,serverTime,onHistory,props.assets,screenPins]);

  useEffect(()=>{
    if(!root.current||!host.current||!canvas.current)return;
    const section=root.current,container=host.current,el=canvas.current,motion=matchMedia('(prefers-reduced-motion: reduce)');
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({canvas:el,alpha:true,antialias:true,powerPreference:'low-power'})}
    catch{setFailed(true);return}
    const gl=renderer.getContext(),debug=gl.getExtension('WEBGL_debug_renderer_info');
    const software=!!debug&&/swiftshader|llvmpipe|software/i.test(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL));
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,software?1:1.5));renderer.setClearColor(0,0);
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2;
    renderer.shadowMap.enabled=!software;renderer.shadowMap.type=THREE.PCFShadowMap;
    el.dataset.lighting=software?'contact':'shadow';
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(36,1,.1,80);
    scene.add(new THREE.HemisphereLight(0xe9f1e0,0x202921,2));
    const light=new THREE.DirectionalLight(0xffefdb,3.5);light.position.set(-3,7,5);scene.add(light);
    light.castShadow=true;light.shadow.mapSize.set(1024,1024);Object.assign(light.shadow.camera,{left:-7,right:7,top:5,bottom:-5,near:1,far:20});light.shadow.normalBias=.025;light.shadow.bias=-.0002;
    const rim=new THREE.DirectionalLight(0xbed9df,2);rim.position.set(4,4,-4);scene.add(rim);
    const controls=new OrbitControls(camera,el);controls.enablePan=false;controls.enableDamping=true;controls.dampingFactor=.13;
    controls.minDistance=2.5;controls.maxDistance=35;controls.minPolarAngle=.08;controls.maxPolarAngle=Math.PI-.08;
    const floorGeometry=new THREE.BoxGeometry(11.8,.09,4.7),floorMaterial=new THREE.MeshStandardMaterial({color:'#23312b',roughness:.72,metalness:.12});
    const floor=new THREE.Mesh(floorGeometry,floorMaterial);floor.position.set(0,-.12,-.45);floor.receiveShadow=true;scene.add(floor);
    const borderGeometry=new THREE.EdgesGeometry(floorGeometry),borderMaterial=new THREE.LineBasicMaterial({color:'#607451',transparent:true,opacity:.38});
    const border=new THREE.LineSegments(borderGeometry,borderMaterial);border.position.copy(floor.position);scene.add(border);
    const modelBios=latest.current.bios.filter(b=>['worm','adult','larva'].includes(b.id));
    const desks=new Map(modelBios.map((bio,i)=>{
      const desk=buildDeskScene(bio.id,bio.metadata.color,browserScreens);desk.scene.position.set((i-(modelBios.length-1)/2)*3.7,0,0);scene.add(desk.scene);return [bio.id,desk] as const;
    }));
    const wall=buildMarketWall();scene.add(wall.scene);
    let boardFeed:BoardFeed={as_of:0,quotes:[],received:performance.now()};
    const stopBoard=connectMarketWall(data=>{boardFeed=data;refresh.current()});
    const priceSamples:Parameters<typeof collectCandidatePrices>[0]=new Map();let lastData:typeof latest.current|undefined;
    const raycaster=new THREE.Raycaster();let frame=0,lastFrame=0,disposed=false,visible=true,force=true,fit=7,currentFocus='all',hadSize=false;
    let dragged=false,downX=0,downY=0;
    const focusCamera=(id:string)=>{
      currentFocus=id;const desk=desks.get(id as BioId),marketWall=id==='market';controls.target.set(desk?.scene.position.x||0,marketWall?3.95:desk?1.52:2.45,marketWall?-2.25:-.25);
      const distance=marketWall?Math.max(3.4,11.6/camera.aspect/(2*Math.tan(THREE.MathUtils.degToRad(18)))):desk?Math.max(6.5,3.8/camera.aspect):fit;
      camera.position.copy(controls.target).add(new THREE.Vector3(.025,marketWall?.05:.42,marketWall?.999:.907).normalize().multiplyScalar(distance));controls.update();force=true;schedule();
    };
    focus.current=focusCamera;
    zoom.current=factor=>{const offset=camera.position.clone().sub(controls.target);offset.setLength(THREE.MathUtils.clamp(offset.length()*factor,controls.minDistance,controls.maxDistance));camera.position.copy(controls.target).add(offset);controls.update();force=true;schedule()};
    const updateStatus=(bio:Bio,record:Playback|undefined,pose:ReturnType<typeof deskPlayback>,now:number)=>{
      const label=statuses.current.get(bio.id),station=stations.current.get(bio.id),clock=clocks.current.get(bio.id);if(!label||!station)return;
      label.textContent=!browserScreens&&bio.activity&&!pose.moving&&['exploring','returning','resting'].includes(bio.activity.state)?`${bio.activity.state==='exploring'?'Exploring':bio.activity.state==='returning'?'Returning to desk':'Resting'} · ${pose.label}`:pose.label;label.title=browserScreens?'Actual execution observations':bio.activity?.reason||'';label.dataset.filled=String(pose.confirmed);
      station.dataset.action=pose.action;station.dataset.press=pose.press.toFixed(3);station.dataset.trace=record?.trace?.id||'';
      station.dataset.playing=String(pose.moving);station.dataset.result=pose.result;
      if(clock){
        if(browserScreens){clock.textContent=frameRef.current[bio.id]?.execution?.running?'At the desk · live executor':'At the desk · standby';return}
        const state=bio.decision_clock;const time=latest.current.serverTime+(now-latest.current.received)/1000;
        clock.textContent=!bio.account.alive?'OUT':!latest.current.marketFresh?'Waiting for feed':!latest.current.active?'Paused / recorded':state?.phase==='thinking'?'Evaluating signal':state?.phase==='settling'?'Awaiting execution quote':state?.next_at?`Next check ~${Math.max(0,Math.ceil(state.next_at-time))}s`:'Waiting for next check';
      }
    };
    function draw(now:number){
      frame=0;if(disposed||document.hidden||(document.fullscreenElement&&document.fullscreenElement!==section)||(!visible&&!force))return;
      if(!force&&now-lastFrame<1000/30-.5){schedule();return}lastFrame=now;force=false;
      let moving=false;controls.enableDamping=!motion.matches;
      const dataChanged=lastData!==latest.current;
      if(dataChanged){collectCandidatePrices(priceSamples,latest.current.assets||[]);lastData=latest.current}
      for(const bio of latest.current.bios){
        const desk=desks.get(bio.id);if(!desk)continue;
        const record=records.current.get(bio.id);
        const idle=latest.current.active&&bio.account.alive&&!motion.matches;
        const serverNow=latest.current.serverTime+(now-latest.current.received)/1000;
        const activity=bio.activity?{...bio.activity,started_at:now/1000+bio.activity.started_at-serverNow,ends_at:bio.activity.ends_at===null?null:now/1000+bio.activity.ends_at-serverNow}:undefined;
        const travel=desk.move(now/1000,idle&&!browserScreens,!!record?.playing&&!motion.matches,activity);
        if(record?.playing&&record.stage==='return'&&travel.home){record.stage='press';record.started=now}
        const elapsed=record?Math.max(0,now-record.started):DESK_REPLAY_MS;
        const actual=executionReplays.current.get(bio.id);
        let pose=browserScreens?executionPlayback(frameRef.current[bio.id]?.execution,actual?now-actual.started:DESK_REPLAY_MS,!!actual?.playing&&!motion.matches):deskPlayback(record?.trace||null,elapsed,!!record?.playing&&record.stage==='press'&&!motion.matches);
        const returning=!browserScreens&&!!record?.playing&&record.stage==='return'&&!motion.matches;
        if(returning)pose={...pose,label:`${pose.action} alert · Returning to desk`,confirmed:false};
        updateStatus(bio,record,pose,now);
        if(record&&record.stage==='press'&&elapsed>=DESK_REPLAY_MS){record.playing=false;record.manual=false}
        const multi=bio.account.positions!==undefined;
        const view=deskMarket(bio,latest.current.assets||[],pins.current[bio.id],record?.playing?record?.trace?.asset?.asset_id:undefined);
        const quote=multi?view.quote:latest.current.market;
        const fresh=latest.current.marketFresh&&(multi?view.fresh:true);
        const station=stations.current.get(bio.id);
        if(dataChanged){
          const candidates=candidateScreens(bio,latest.current.assets||[],priceSamples);
          desk.updateCandidates(candidates,latest.current.marketFresh);
          if(station){station.dataset.candidates=JSON.stringify(candidates.map(c=>({asset:c.asset.asset_id,symbol:c.asset.symbol,price:c.asset.quote?.price,fresh:c.asset.fresh,reviewed:c.reviewed,held:c.held})));station.dataset.candidateScreens='6'}
        }
        if(station){station.dataset.market=quote?.symbol||'';station.dataset.price=String(quote?.price??'');station.dataset.asset=view.selected||'';station.dataset.holding=String(!!view.position)}
        desk.update(pose,now/1000,idle,quote,multi?view.history:latest.current.marketHistory,fresh,
          multi?{held:!!view.position,positions:view.positions,maxPositions:bio.max_positions||5}:undefined,frameRef.current[bio.id]);
        if(station&&browserScreens)station.dataset.browserScreen=frameRef.current[bio.id]?.state||'unavailable';
        if(station){station.dataset.idleProp=desk.scene.userData.idleProp;station.dataset.idleReach=desk.scene.userData.idleReach.toFixed(3);station.dataset.travel=travel.state;station.dataset.atDesk=String(travel.home);station.dataset.offset=JSON.stringify([travel.x,travel.y,travel.z]);station.dataset.alert=String(returning||pose.moving);station.dataset.buttons='BUY,SELL'}
        moving ||= idle||pose.moving||returning;
      }
      const board=wall.update(now/1000,motion.matches,boardFeed);el.dataset.wallSymbol=board.symbol;el.dataset.wallFresh=String(board.fresh);
      moving ||= !motion.matches;
      controls.update();renderer.render(scene,camera);
      el.dataset.azimuth=controls.getAzimuthalAngle().toFixed(3);el.dataset.distance=controls.getDistance().toFixed(3);el.dataset.stations=String(desks.size);el.dataset.screens=String(desks.size*7+1);
      if(moving&&visible)schedule();
    }
    function schedule(){if(!frame&&!disposed&&!document.hidden&&(visible||force))frame=requestAnimationFrame(draw)}
    refresh.current=()=>{force=true;schedule()};
    replay.current=id=>{const bio=latest.current.bios.find(b=>b.id===id);if(!bio?.telemetry||recordedAction(bio.telemetry)==='HOLD')return;records.current.set(id,{trace:bio.telemetry,started:performance.now(),playing:true,manual:true,stage:'return'});refresh.current()};
    const resize=()=>{
      const width=container.clientWidth,height=container.clientHeight;renderer.setSize(width,height,false);camera.aspect=width/Math.max(1,height);camera.updateProjectionMatrix();
      const oldFit=fit;fit=Math.max(12.7/camera.aspect,5.9)/(2*Math.tan(THREE.MathUtils.degToRad(18)));
      if(!hadSize){hadSize=true;focusCamera('all')}else if(currentFocus==='all')camera.position.sub(controls.target).multiplyScalar(fit/oldFit).add(controls.target);
      refresh.current();
    };
    const pointerDown=(event:PointerEvent)=>{if(!event.isPrimary){dragged=true;return}downX=event.clientX;downY=event.clientY;dragged=false};
    const pointerMove=(event:PointerEvent)=>{if(event.buttons&&Math.hypot(event.clientX-downX,event.clientY-downY)>6)dragged=true};
    const pointerUp=(event:PointerEvent)=>{
      if(dragged||!event.isPrimary)return;const rect=el.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
      for(const hit of raycaster.intersectObjects([...desks.values()].map(d=>d.scene),true)){
        if(browserScreens&&hit.object.userData.browserScreen){setScreenBio(hit.object.userData.browserScreen);break}
        let node:THREE.Object3D|null=hit.object;while(node&&!node.userData.bio)node=node.parent;
        if(node?.userData.bio){latest.current.onHistory(node.userData.bio);break}
      }
    };
    const visibility=()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0}else refresh.current()};
    const lost=(event:Event)=>{event.preventDefault();if(!disposed){setFailed(true);disposed=true;cancelAnimationFrame(frame)}};
    const observer=new ResizeObserver(resize);observer.observe(container);
    const intersection=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;if(visible)schedule();else{cancelAnimationFrame(frame);frame=0}});intersection.observe(container);
    controls.addEventListener('change',schedule);el.addEventListener('pointerdown',pointerDown);el.addEventListener('pointermove',pointerMove);el.addEventListener('pointerup',pointerUp);el.addEventListener('webglcontextlost',lost);
    document.addEventListener('visibilitychange',visibility);document.addEventListener('fullscreenchange',refresh.current);motion.addEventListener('change',refresh.current);
    resize();setReady(true);
    return()=>{
      disposed=true;cancelAnimationFrame(frame);observer.disconnect();intersection.disconnect();controls.dispose();
      el.removeEventListener('pointerdown',pointerDown);el.removeEventListener('pointermove',pointerMove);el.removeEventListener('pointerup',pointerUp);el.removeEventListener('webglcontextlost',lost);
      document.removeEventListener('visibilitychange',visibility);document.removeEventListener('fullscreenchange',refresh.current);motion.removeEventListener('change',refresh.current);
      refresh.current=()=>{};focus.current=()=>{};zoom.current=()=>{};replay.current=()=>{};
      stopBoard();wall.dispose();desks.forEach(d=>d.dispose());light.shadow.map?.dispose();floorGeometry.dispose();floorMaterial.dispose();borderGeometry.dispose();borderMaterial.dispose();renderer.dispose();renderer.forceContextLoss();
    };
  },[signature]);
  useEffect(()=>{const change=()=>setExpanded(document.fullscreenElement===root.current);document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change)},[]);
  const expand=()=>{if(document.fullscreenElement===root.current)void document.exitFullscreen();else void root.current?.requestFullscreen().catch(()=>{})};
  return <section ref={root} className="desk-stage shared-stage" aria-label="Shared 3D trading arena">
    <div className="desk-stage-heading"><h2>At the controls <span>{bios.length} INDEPENDENT BRAINS / ONE MARKET</span></h2><div className="arena-camera-tools">
      <select aria-label="Camera focus" value={cameraFocus} onChange={event=>{setCameraFocus(event.target.value);focus.current(event.target.value)}}><option value="all">Whole studio</option><option value="market">Global screen</option>{bios.map(b=><option key={b.id} value={b.id}>{displayNames[b.id]}</option>)}</select>
      <button aria-label="Zoom in arena" title="Zoom in" onClick={()=>zoom.current(.8)}><Plus size={15}/></button><button aria-label="Zoom out arena" title="Zoom out" onClick={()=>zoom.current(1.25)}><Minus size={15}/></button>
      <button aria-label="Reset arena camera" title="Reset view" onClick={()=>{setCameraFocus('all');focus.current('all')}}><RotateCcw size={14}/></button><button aria-label={expanded?'Close arena fullscreen':'Expand arena fullscreen'} title="Fullscreen" onClick={expand}>{expanded?<X size={15}/>:<Maximize2 size={15}/>}</button>
    </div></div>
    <div className="arena-world" ref={host}><canvas ref={canvas} className="arena-canvas" aria-label="Roaming creatures at trading desks with BUY and SELL buttons, six candidate screens each, and a rotating BTC, ETH, SOL, NVIDIA and Apple market wall. Drag to orbit, scroll to zoom, click a desk for decision history."/>
      {(failed||!ready)&&<p className="desk-fallback">{failed?'3D is unavailable on this device. Decision history is available below.':'Preparing the shared trading arena…'}</p>}
      <span className="arena-gesture-hint">DRAG TO ORBIT · GLOBAL SCREEN / BIO CLOSE-UPS IN CAMERA MENU</span>
    </div>
    <div className={`arena-stations ${multi?'with-portfolios':''}`}>{bios.map(bio=><div key={bio.id} className="arena-station-wrap" style={{'--bio':bio.metadata.color} as React.CSSProperties}>
      <button className="desk-station" ref={el=>{if(el)stations.current.set(bio.id,el);else stations.current.delete(bio.id)}} onClick={()=>onHistory(bio.id)} title={bio.telemetry?englishReason(bio.telemetry.fill.reason):'View decision history'} aria-label={`View ${displayNames[bio.id]} decision history`}>
        <span className="station-title"><strong>{displayNames[bio.id]}</strong><small ref={el=>{if(el)clocks.current.set(bio.id,el);else clocks.current.delete(bio.id)}}/></span>
        {!['worm','adult','larva'].includes(bio.id)&&<small>3D model pending · neural data available below</small>}
        <span className="station-status"><span ref={el=>{if(el)statuses.current.set(bio.id,el);else statuses.current.delete(bio.id)}}/><ArrowUpRight size={13}/></span>
      </button>{!browserScreens&&<button className="station-replay" disabled={!bio.telemetry||recordedAction(bio.telemetry)==='HOLD'||failed} onClick={()=>replay.current(bio.id)} aria-label={`Replay ${displayNames[bio.id]} decision`} title="Replay a recorded BUY or SELL"><RotateCcw size={12}/></button>}
      {browserScreens&&frames[bio.id]&&<button className="fomo-screen-open" onClick={()=>setScreenBio(bio.id)} aria-label={`Open ${displayNames[bio.id]} FOMO screen`}><span>FOMO screen ↗</span><small>{screenState(frames[bio.id].state)}</small></button>}
      {bio.account.positions!==undefined&&<div className="desk-portfolio" aria-label={`${displayNames[bio.id]} paper portfolio`}>
        <div className="portfolio-balance"><span>{browserScreens?'Paper cash':'Cash'} <b>${bio.account.cash.toLocaleString('en-US',{maximumFractionDigits:0})}</b></span><span>{bio.account.positions.length} / {bio.max_positions||5} held</span></div>
        {!browserScreens&&<label className="screen-picker"><span>On screen</span><select aria-label={`${displayNames[bio.id]} screen token`} value={bio.account.positions.some(p=>p.asset_id===screenPins[bio.id])?screenPins[bio.id]:'auto'} onChange={e=>setScreenPins(previous=>({...previous,[bio.id]:e.target.value==='auto'?undefined:e.target.value}))}>
          <option value="auto">Auto · {deskMarket(bio,assets,undefined,undefined).quote?.symbol||'Observing'}</option>
          {bio.account.positions.map(p=><option key={p.asset_id} value={p.asset_id}>{p.symbol} · {p.chain}</option>)}
        </select></label>}
        <div className="portfolio-holdings">{bio.account.positions.length?bio.account.positions.map(p=><button key={p.asset_id} className={!browserScreens&&deskMarket(bio,assets,screenPins[bio.id],undefined).selected===p.asset_id?'on-screen':''} onClick={()=>browserScreens?onHistory(bio.id):setScreenPins(previous=>({...previous,[bio.id]:p.asset_id}))} title={`${p.chain} · ${p.address} · ${p.quantity.toPrecision(5)} tokens · $${tokenPrice(p.price)}`} aria-label={browserScreens?`View ${displayNames[bio.id]} paper decisions`:`Show ${p.symbol} ${p.chain} on ${displayNames[bio.id]} screen`}>
          <span><b>{p.symbol}</b><small>{p.chain}{p.mark_stale?' · stale':''}</small></span><strong>${p.value.toLocaleString('en-US',{maximumFractionDigits:0})}</strong><em className={p.return_pct<0?'negative':'positive'}>{p.return_pct>=0?'+':''}{p.return_pct.toFixed(1)}%</em>
        </button>):<p className="portfolio-empty">No holdings yet.<br/>Observing {bio.market?.symbol||'the candidate pool'}.</p>}</div>
        <div className="portfolio-learning"><span>{bio.training?.mode==='learning'?'Learning':bio.training?.updates?'Training':'Collecting'} <b>· model v{bio.training?.active_version||0}</b></span><small>{bio.training?.updates||0} updates · {bio.training?.pending_samples||0} pending labels</small></div>
        {bio.account.valuation_stale&&<p className="portfolio-warning">A holding has a stale price. New entries paused.</p>}
      </div>}
    </div>)}</div>
    <p className="desk-caption">{browserScreens?'Main monitors show actual FOMO browser snapshots. Click a monitor to enlarge. Bios stay at their desks; gestures replay newly verified real fills. Candidate screens, portfolios and neural views remain paper data. ':`${multi?'FOMO candidate screens + each brain’s own portfolio.':'SOL / USDT live prices.'} Roaming is decorative. Recorded BUY / SELL alerts bring a brain back to its desk; HOLD stays quiet. `}Global screen: <a href="https://developers.binance.com/en/docs/products/spot/rest-api" target="_blank" rel="noreferrer">Binance</a> / <a href="https://www.nasdaq.com/market-activity/stocks" target="_blank" rel="noreferrer">Nasdaq</a> reference quotes; stock session and delays shown.</p>
    {screenBio&&<FomoScreenDialog bio={screenBio} screens={frames} onSelect={setScreenBio} onClose={()=>setScreenBio(null)}/>}
  </section>
}
