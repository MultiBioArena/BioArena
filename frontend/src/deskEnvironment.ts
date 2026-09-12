import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import type {BioId} from './types';
import type {CandidateScreen} from './candidateScreens';
import {tokenPrice} from './marketDisplay';

const smooth=(x:number)=>{const t=THREE.MathUtils.clamp(x,0,1);return t*t*(3-2*t)};
const compact=(n:number|undefined)=>n===undefined?'—':n>=1e6?`${(n/1e6).toFixed(1)}M`:n>=1e3?`${(n/1e3).toFixed(1)}K`:Math.round(n).toString();

export function buildDeskEnvironment(id:BioId,color:string){
  const scene=new THREE.Group();
  const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>();
  const mat=(c:string,roughness=.5,metalness=.2)=>{const m=new THREE.MeshStandardMaterial({color:c,roughness,metalness});materials.add(m);return m};
  const charcoal=mat('#17201f'),aluminum=mat('#63706c',.32,.7),rubber=mat('#101918',.86),ceramic=mat('#d5cbb4',.26),leaf=mat('#607954',.6),wood=mat('#9f7f52',.6);
  const accent=mat(color,.3);accent.emissive.set(color);accent.emissiveIntensity=.3;
  const glow=new THREE.MeshBasicMaterial({color:'#f5dca9'});
  const add=(g:THREE.BufferGeometry,m:THREE.Material,parent:THREE.Object3D=scene)=>{geometries.add(g);materials.add(m);const mesh=new THREE.Mesh(g,m);parent.add(mesh);return mesh};
  const boxes=new Map<string,THREE.BufferGeometry>();
  const box=(x:number,y:number,z:number,w:number,h:number,d:number,m:THREE.Material=charcoal,parent:THREE.Object3D=scene)=>{
    const key=[w,h,d].join('/');let g=boxes.get(key);if(!g){g=new RoundedBoxGeometry(w,h,d,2,Math.min(.022,w/5,h/5,d/5));boxes.set(key,g)}
    const mesh=add(g,m,parent);mesh.position.set(x,y,z);mesh.receiveShadow=true;return mesh;
  };
  const rod=(a:number[],b:number[],r:number,m=aluminum,parent:THREE.Object3D=scene)=>{
    const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b),dir=end.clone().sub(start);
    const mesh=add(new THREE.CylinderGeometry(r,r,dir.length(),10),m,parent);mesh.position.copy(start).lerp(end,.5);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),dir.normalize());return mesh;
  };
  const sphere=new THREE.SphereGeometry(1,20,14);
  const ellipsoid=(x:number,y:number,z:number,sx:number,sy:number,sz:number,m:THREE.Material,parent:THREE.Object3D=scene)=>{const mesh=add(sphere,m,parent);mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);return mesh};
  const cable=(points:number[][])=>add(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p))),20,.013,6,false),rubber);

  for(const x of [-.62,.62]){
    box(x,1.42,-1.27,.055,2.52,.07,aluminum);
    box(x,.17,-1.18,.42,.05,.4,rubber);
  }
  for(const y of [1.93,2.59])box(0,y,-1.25,2.72,.052,.055,aluminum);
  const monitors=Array.from({length:6},(_,i)=>{
    const column=i%3-1,row=Math.floor(i/3),group=new THREE.Group();group.position.set(column*1.045,1.94+row*.66,-1.13+Math.abs(column)*.085);group.rotation.y=-column*.13;scene.add(group);
    box(0,0,0,1.015,.612,.067,charcoal,group).castShadow=true;
    box(0,0,-.043,.53,.34,.045,rubber,group);
    box(0,-.278,.037,.25,.007,.008,aluminum,group);
    box(.452,-.278,.039,.018,.009,.009,accent,group);
    const canvas=document.createElement('canvas');canvas.width=480;canvas.height=270;
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;textures.add(texture);
    const screen=add(new THREE.PlaneGeometry(.954,.538),new THREE.MeshBasicMaterial({map:texture,toneMapped:false}),group);screen.position.z=.036;
    screen.userData.candidateSlot=i;
    cable([[column*1.04,1.9+row*.66,-1.24],[column*.8,1.5,-1.39],[.62,.65,-1.32],[.96,.23,-.64]]);
    return {ctx:canvas.getContext('2d')!,texture,screen,key:''};
  });

  box(0,.459,.40,2.35,.012,1.30,rubber);
  box(0,.47,.965,2.18,.006,.012,accent);
  box(1.11,.09,-.42,.31,.37,.56,charcoal).castShadow=true;
  for(let i=0;i<8;i++)box(1.11,-.025+i*.03,-.13,.23,.008,.012,aluminum);
  box(1.11,.20,-.13,.19,.014,.013,accent);
  cable([[.02,.46,-.6],[.24,.47,-.72],[.94,.42,-.8],[1.11,.17,-.55]]);
  // One instanced key bed per keyboard keeps the small repeated details inexpensive.
  const keyboard=new THREE.Group();keyboard.position.set(-.98,.49,.20);keyboard.rotation.y=-.18;scene.add(keyboard);
  box(0,0,0,.48,.037,.24,aluminum,keyboard);
  const keyGeometry=new THREE.BoxGeometry(.035,.016,.038);geometries.add(keyGeometry);
  const keys=new THREE.InstancedMesh(keyGeometry,charcoal,40),matrix=new THREE.Matrix4();keyboard.add(keys);
  for(let i=0;i<40;i++){matrix.makeTranslation((i%10-4.5)*.043,.026,(Math.floor(i/10)-1.5)*.051);keys.setMatrixAt(i,matrix)}
  ellipsoid(-1.1,.505,.43,.065,.029,.09,charcoal);
  box(-1.1,.535,.409,.008,.005,.023,aluminum);

  const cupX=-1.03,cupZ=.77;
  rod([cupX,.468,cupZ],[cupX,.482,cupZ],.139,ceramic);
  const cup=add(new THREE.CylinderGeometry(.083,.069,.15,24,1,true),ceramic);cup.position.set(cupX,.56,cupZ);cup.castShadow=true;
  rod([cupX,.621,cupZ],[cupX,.624,cupZ],.075,mat('#302117',.24));
  const handle=add(new THREE.TorusGeometry(.051,.013,8,20),ceramic);handle.position.set(cupX-.093,.566,cupZ);
  box(.97,.479,.8,.37,.02,.28,wood).rotation.y=-.12;
  const paper=box(.97,.492,.8,.345,.006,.255,mat('#c3be9c',.9));paper.rotation.y=-.12;
  for(let i=0;i<4;i++)box(.97,.497,.73+i*.042,.24,.002,.003,aluminum).rotation.y=-.12;
  rod([.90,.511,.91],[1.10,.511,.70],.009,accent);

  const lampX=-1.19;
  rod([lampX,.46,-.44],[lampX,.49,-.44],.11,charcoal);
  rod([lampX,.49,-.44],[lampX,1.10,-.50],.018,aluminum);
  rod([lampX,1.10,-.50],[lampX+.18,1.35,-.28],.018,aluminum);
  ellipsoid(lampX,1.1,-.5,.041,.041,.041,charcoal);
  box(lampX+.22,1.34,-.25,.35,.06,.13,charcoal);
  box(lampX+.22,1.303,-.25,.29,.008,.09,glow);
  const pot=add(new THREE.CylinderGeometry(.10,.07,.16,20),wood);pot.position.set(1.15,.54,-.43);
  rod([1.15,.6,-.43],[1.15,.85,-.43],.009,leaf);
  for(let i=0;i<5;i++){
    const angle=i*2.4,l=ellipsoid(1.15+Math.cos(angle)*.06,.68+i*.037,-.43+Math.sin(angle)*.05,.065,.012,.027,leaf);l.rotation.z=Math.cos(angle)*.7;l.rotation.y=angle;
  }

  const toy=new THREE.Group();toy.position.set(.62,.465,.38);scene.add(toy);
  let toyMotion:(amount:number,time:number)=>void;
  const target=new THREE.Vector3(.60,.56,.37);
  if(id==='worm'){
    box(0,.008,0,.3,.014,.26,wood,toy);
    const bead=ellipsoid(0,.066,0,.054,.054,.054,accent,toy);
    const ring=add(new THREE.TorusGeometry(.055,.007,8,24),aluminum,bead);ring.rotation.x=Math.PI/2;
    toyMotion=(amount,time)=>{bead.position.x=amount*.085;bead.rotation.z=-amount*1.5;bead.position.z=Math.sin(time*4)*.007*amount};
  }else if(id==='adult'){
    box(0,.012,0,.28,.024,.24,wood,toy);
    for(const x of [-.09,.09])rod([x,.02,0],[x,.26,0],.011,aluminum,toy);
    rod([-.11,.26,0],[.11,.26,0],.012,aluminum,toy);
    const pendulum=new THREE.Group();pendulum.position.set(0,.25,0);toy.add(pendulum);
    rod([0,0,0],[0,-.135,0],.004,aluminum,pendulum);
    ellipsoid(0,-.16,0,.04,.04,.04,accent,pendulum);
    target.set(.62,.56,.36);
    toyMotion=(amount,time)=>{pendulum.rotation.z=Math.sin(time*7)*amount*.6};
  }else{
    box(0,.009,0,.28,.018,.25,wood,toy);
    const sprig=new THREE.Group();toy.add(sprig);sprig.position.y=.022;
    rod([0,0,0],[.045,.09,0],.008,leaf,sprig);
    const l=ellipsoid(.025,.075,0,.095,.012,.041,leaf,sprig);l.rotation.z=.25;
    toyMotion=amount=>{sprig.rotation.z=-amount*.25};
  }
  // Batch the static furniture by material; screens and the interactive toy stay separate.
  scene.updateMatrixWorld(true);
  const batches=new Map<string,THREE.Mesh[]>();
  scene.traverse(object=>{
    if(!(object instanceof THREE.Mesh)||object instanceof THREE.InstancedMesh||Array.isArray(object.material))return;
    for(let parent:THREE.Object3D|null=object;parent;parent=parent.parent)if(parent===toy)return;
    const key=`${object.material.uuid}/${object.castShadow}/${object.receiveShadow}`;
    const group=batches.get(key)||[];group.push(object);batches.set(key,group);
  });
  for(const group of batches.values()){
    if(group.length<2)continue;
    const pieces=group.map(object=>{
      let geometry=object.geometry.clone().applyMatrix4(object.matrixWorld);
      if(geometry.index){const expanded=geometry.toNonIndexed();geometry.dispose();geometry=expanded}
      return geometry;
    });
    const geometry=mergeGeometries(pieces);pieces.forEach(piece=>piece.dispose());
    if(!geometry)continue;
    const combined=add(geometry,group[0].material as THREE.Material);combined.castShadow=group[0].castShadow;combined.receiveShadow=group[0].receiveShadow;
    group.forEach(object=>object.removeFromParent());
  }
  let started:number|undefined;
  const interaction=(time:number,idle:boolean,trading:boolean)=>{
    started??=time;
    const offset=id==='worm'?5:id==='adult'?17:29,period=id==='worm'?37:id==='adult'?43:49;
    const phase=(time-started-offset+period)%period;
    const reach=idle&&!trading&&phase<5.5?smooth(phase/1.4)*(1-smooth((phase-3.8)/1.7)):0;
    toyMotion(reach,time);return {reach,target,name:id==='worm'?'bead':id==='adult'?'pendulum':'leaf'};
  };

  const updateCandidates=(candidates:CandidateScreen[],feedFresh:boolean)=>{
    monitors.forEach((monitor,i)=>{
      const item=candidates[i],a=item?.asset,q=a?.quote,fresh=!!a?.fresh&&feedFresh;
      const key=[a?.asset_id,q?.id,fresh,a?.entry_problem,item?.reviewed,item?.held,item?.history.length].join('|');
      if(key===monitor.key)return;monitor.key=key;monitor.screen.userData.asset=a?.asset_id||'';
      const ctx=monitor.ctx;ctx.fillStyle='#091714';ctx.fillRect(0,0,480,270);
      ctx.fillStyle=color;ctx.fillRect(0,0,480,3);
      ctx.font='14px monospace';ctx.fillStyle='#8bafa0';ctx.fillText(`0${i+1} / ${a?.chain.toUpperCase()||'CANDIDATE'}`,20,29);
      ctx.textAlign='right';ctx.fillStyle=fresh?'#a9c995':'#d8ae75';ctx.fillText(!a?'OPEN SLOT':!fresh?'STALE':a.entry_problem?'WATCH':item.held?'HELD':item.reviewed?'REVIEWED':'TRENDING',460,29);ctx.textAlign='left';
      if(!a){ctx.font='23px monospace';ctx.fillStyle='#648677';ctx.fillText('Waiting for candidates',20,98);ctx.font='14px monospace';ctx.fillText('FOMO Trending',20,129);monitor.texture.needsUpdate=true;return}
      ctx.fillStyle='#e6eee0';ctx.font='bold 29px monospace';ctx.fillText(a.symbol.slice(0,17),20,70,440);
      ctx.font='bold 30px monospace';ctx.fillText(q?'$'+tokenPrice(q.price):'No quote',20,107,310);
      const change=q?.change_5m_pct;ctx.textAlign='right';ctx.fillStyle=(change??0)<0?'#e99980':'#b0d793';ctx.font='19px monospace';ctx.fillText(change===undefined?'—':`${change>=0?'+':''}${change.toFixed(2)}%`,460,89);ctx.fillStyle='#718f82';ctx.font='12px monospace';ctx.fillText('5 MIN',460,109);ctx.textAlign='left';
      ctx.strokeStyle='#213c31';ctx.lineWidth=1;
      for(const y of [137,165,193]){ctx.beginPath();ctx.moveTo(20,y);ctx.lineTo(460,y);ctx.stroke()}
      const history=item.history;
      if(history.length>1){
        const values=history.map(p=>p.price),low=Math.min(...values),high=Math.max(...values),span=Math.max(high-low,(q?.price||1)*.00001),first=history[0].time,duration=history[history.length-1].time-first;
        ctx.strokeStyle=fresh?color:'#6d8074';ctx.lineWidth=2.5;ctx.beginPath();history.forEach((p,j)=>{const x=20+(p.time-first)/Math.max(1,duration)*440,y=190-(p.price-low)/span*49;if(j)ctx.lineTo(x,y);else ctx.moveTo(x,y)});ctx.stroke();
      }else{ctx.font='13px monospace';ctx.fillStyle='#749283';ctx.fillText(q?'Collecting price history…':'Waiting for reference price',20,170)}
      ctx.fillStyle='#96b09f';ctx.font='15px monospace';ctx.fillText(`LIQ $${compact(q?.liquidity_usd)}`,20,224);ctx.textAlign='right';ctx.fillText(`VOL 5M $${compact(q?.volume_5m_usd)}`,460,224);ctx.textAlign='left';
      ctx.fillStyle='#658574';ctx.font='11px monospace';ctx.fillText(`${a.address.slice(0,7)}…${a.address.slice(-5)} / DEX REFERENCE`,20,252);
      monitor.texture.needsUpdate=true;
    });
  };
  return {scene,interaction,updateCandidates,dispose(){geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose())}};
}
