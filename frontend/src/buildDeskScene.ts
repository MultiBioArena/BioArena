import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import type {Action,BioId,Quote,Position} from './types';
import type {CandidateScreen} from './candidateScreens';
import {tokenPrice} from './marketDisplay';
import {buildDeskEnvironment} from './deskEnvironment';
import {createDeskMotion} from './deskMotion';
import type {DeskMotion} from './deskMotion';
import {buttonColors,buttonLabels,buttonX,deskPlayback} from './deskPlayback';
import {paintBrowserScreen} from './fomoScreens';
import type {BrowserScreen} from './fomoScreens';

type Pose=ReturnType<typeof deskPlayback>;
type ScreenPortfolio={held:boolean;positions:Position[];maxPositions:number};
const v=(x:number,y:number,z:number)=>new THREE.Vector3(x,y,z);
const up=v(0,1,0);

export function buildDeskScene(id:BioId,color:string,browserMode=false){
  const scene=new THREE.Group();scene.userData.bio=id;
  const choreography=createDeskMotion(id);
  let travel:DeskMotion={x:0,y:0,z:0,yaw:0,home:true,state:'at-desk',airborne:0};
  const creatureRoot=new THREE.Group(),creature=new THREE.Group();scene.add(creatureRoot);creatureRoot.add(creature);creature.position.set(0,-.6,-.65);
  const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>();
  const material=(c:string,roughness=.55)=>{const m=new THREE.MeshStandardMaterial({color:c,roughness,metalness:.08});materials.add(m);return m};
  const mesh=(g:THREE.BufferGeometry,m:THREE.Material,parent:THREE.Object3D=scene)=>{geometries.add(g);materials.add(m);const object=new THREE.Mesh(g,m);object.castShadow=true;object.receiveShadow=true;parent.add(object);return object};
  const dark=material('#35433c',.48),trim=material('#67776e',.32),black=material('#101b17');
  const skin=new THREE.MeshPhysicalMaterial({color:id==='worm'?'#d1d9ad':'#d6caa2',roughness:.35,clearcoat:.32,clearcoatRoughness:.25,vertexColors:true});materials.add(skin);
  const box=(x:number,y:number,z:number,sx:number,sy:number,sz:number,m=dark)=>{const o=mesh(new RoundedBoxGeometry(sx,sy,sz,2,Math.min(.035,sx/5,sy/5,sz/5)),m);o.position.set(x,y,z);return o};
  const sphereGeometry=new THREE.SphereGeometry(1,24,16);
  const ellipsoid=(parent:THREE.Object3D,m:THREE.Material,x:number,y:number,z:number,sx:number,sy:number,sz:number)=>{const o=mesh(sphereGeometry,m,parent);o.position.set(x,y,z);o.scale.set(sx,sy,sz);return o};
  const segmentGeometry=new THREE.CylinderGeometry(1,1,1,7);
  const segment=(parent:THREE.Object3D,m:THREE.Material)=>mesh(segmentGeometry,m,parent);
  const line=(o:THREE.Mesh,a:THREE.Vector3,b:THREE.Vector3,r=.014)=>{o.position.copy(a).lerp(b,.5);o.scale.set(r,a.distanceTo(b),r);o.quaternion.setFromUnitVectors(up,v(0,0,0).subVectors(b,a).normalize())};

  box(0,.38,.16,2.85,.14,2.04);box(0,.29,.16,2.68,.08,1.87,black);
  const environment=buildDeskEnvironment(id,color);scene.add(environment.scene);
  const shadowCanvas=document.createElement('canvas');shadowCanvas.width=64;shadowCanvas.height=64;
  const shadowContext=shadowCanvas.getContext('2d')!,gradient=shadowContext.createRadialGradient(32,32,4,32,32,32);
  gradient.addColorStop(0,'rgba(0,0,0,.48)');gradient.addColorStop(.5,'rgba(0,0,0,.24)');gradient.addColorStop(1,'rgba(0,0,0,0)');shadowContext.fillStyle=gradient;shadowContext.fillRect(0,0,64,64);
  const shadowTexture=new THREE.CanvasTexture(shadowCanvas);textures.add(shadowTexture);
  const shadowMaterial=new THREE.MeshBasicMaterial({map:shadowTexture,transparent:true,depthWrite:false,toneMapped:false});
  let creatureShadow:THREE.Mesh;
  for(const [width,depth,y,z] of [[id==='worm'?.55:.85,1.25,.468,.64],[3.15,2.55,-.069,.15]]){
    const shadow=mesh(new THREE.PlaneGeometry(width,depth),shadowMaterial);shadow.rotation.x=-Math.PI/2;shadow.position.set(0,y,z);shadow.castShadow=false;shadow.receiveShadow=false;
    if(y>0)creatureShadow=shadow;
  }
  for(const x of [-1.08,1.08])for(const z of [-.48,.78])box(x,.13,z,.055,.3,.055,trim);
  box(0,.47,-.61,.65,.035,.33,trim);box(0,.85,-.7,.07,.75,.06,trim);
  box(0,1.28,-.69,1.71,.94,.09,black);box(0,1.28,-.68,1.78,1.01,.025,trim);
  const screen=document.createElement('canvas');screen.width=browserMode?1024:512;screen.height=browserMode?576:288;
  const screenContext=screen.getContext('2d')!,screenTexture=new THREE.CanvasTexture(screen);screenTexture.colorSpace=THREE.SRGBColorSpace;textures.add(screenTexture);
  const screenMaterial=new THREE.MeshBasicMaterial({map:screenTexture,toneMapped:false});
  const display=mesh(new THREE.PlaneGeometry(1.6,.84),screenMaterial);display.position.set(0,1.28,-.635);
  display.userData.browserScreen=browserMode?id:null;
  const caps={} as Record<Action,THREE.Group>,capMaterials={} as Record<Action,THREE.MeshStandardMaterial>;
  for(const action of ['BUY','SELL'] as Action[]){
    const x=buttonX[action];box(x,.47,-.02,.59,.065,.44,black);
    const cap=new THREE.Group();cap.position.set(x,.525,-.02);scene.add(cap);caps[action]=cap;
    const m=material(buttonColors[action],.32);m.emissive.set(buttonColors[action]);m.emissiveIntensity=.07;capMaterials[action]=m;
    mesh(new THREE.BoxGeometry(.54,.072,.38),m,cap);
    const label=document.createElement('canvas');label.width=256;label.height=128;
    const ctx=label.getContext('2d')!;ctx.fillStyle='#111a14';ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='bold 65px monospace';ctx.fillText(buttonLabels[action],128,64);
    const texture=new THREE.CanvasTexture(label);texture.colorSpace=THREE.SRGBColorSpace;textures.add(texture);
    const top=mesh(new THREE.PlaneGeometry(.44,.22),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false}),cap);
    top.rotation.x=-Math.PI/2;top.position.y=.037;
  }
  const alertMaterial=material(color,.3);alertMaterial.emissive.set(color);alertMaterial.emissiveIntensity=.2;
  const alertLight=box(0,.483,-.02,.32,.014,.035,alertMaterial);
  alertLight.userData.alert=true;

  type Interaction=ReturnType<typeof environment.interaction>;
  let animateCreature:(time:number,pose:Pose,idle:boolean,interaction:Interaction)=>void;
  if(id==='adult'){
    const fly=new THREE.Group();creature.add(fly);
    const shell=material('#b48b43',.46),stripe=material('#463d24'),eye=material('#933827',.28),leg=material('#584b2f');
    ellipsoid(fly,shell,0,.69,.73,.17,.14,.28);
    for(let k=0;k<4;k++)ellipsoid(fly,stripe,0,.696,.66+k*.076,.17-k*.015,.138-k*.012,.025);
    ellipsoid(fly,shell,0,.76,.42,.155,.165,.2);
    const head=new THREE.Group();head.position.set(0,.78,.22);fly.add(head);
    ellipsoid(head,shell,0,0,0,.155,.105,.12);
    const facetGeometry=new THREE.IcosahedronGeometry(1,0);geometries.add(facetGeometry);
    for(const side of [-1,1]){
      const eyeMesh=ellipsoid(head,eye,side*.113,.015,-.032,.072,.094,.085);
      const facets=new THREE.InstancedMesh(facetGeometry,material('#bc5239',.25),28);head.add(facets);
      const matrix=new THREE.Matrix4();
      for(let k=0;k<28;k++){
        const angle=k*2.39996,z=1-(k+.5)/28,r=Math.sqrt(1-z*z);
        matrix.compose(v(side*.113+side*z*.072,.015+Math.cos(angle)*r*.093,-.032+Math.sin(angle)*r*.084),new THREE.Quaternion(),v(.005,.005,.005));facets.setMatrixAt(k,matrix);
      }
      eyeMesh.castShadow=false;
      const antenna=segment(head,leg);line(antenna,v(side*.036,.04,-.08),v(side*.06,.09,-.185),.008);
    }
    const wingMaterial=new THREE.MeshStandardMaterial({color:'#dde7cb',transparent:true,opacity:.38,roughness:.28,side:THREE.DoubleSide,depthWrite:false});
    const wings:THREE.Mesh[]=[];
    for(const side of [-1,1]){
      const wing=ellipsoid(fly,wingMaterial,side*.19,.84,.75,.135,.012,.38);wing.rotation.y=side*.28;wings.push(wing);
      wing.castShadow=false;
      const veinMaterial=new THREE.LineBasicMaterial({color:'#86947b',transparent:true,opacity:.55});materials.add(veinMaterial);
      for(const end of [-.65,0,.65]){
        const g=new THREE.BufferGeometry().setFromPoints([v(0,.7,-.85),v(end*.45,.8,0),v(end,.5,.70)]);geometries.add(g);wing.add(new THREE.Line(g,veinMaterial));
      }
    }
    const legs=Array.from({length:6},()=>[segment(fly,leg),segment(fly,leg)]);
    animateCreature=(time,pose,idle,interaction)=>{
      const breathing=idle?Math.sin(time*1.7)*.005:0;head.rotation.x=pose.reach*.1+breathing;head.rotation.y=-interaction.reach*.2;
      wings.forEach((wing,i)=>wing.rotation.z=(i?1:-1)*((idle?.02*Math.sin(time*5):0)+pose.reach*.045+travel.airborne*(.45+.8*Math.sin(time*36))));
      legs.forEach(([upper,lower],i)=>{
        const side=i%2?1:-1,pair=Math.floor(i/2),a=v(side*.105,.74,.36+pair*.19),knee=v(side*(.28+pair*.05),.63,.19+pair*.3);
        const foot=v(side*(.34+pair*.075),.46,.17+pair*.36);
        if(travel.airborne){foot.lerp(v(side*.13,.66,.4+pair*.14),travel.airborne);knee.lerp(v(side*.18,.73,.39+pair*.15),travel.airborne)}
        if(travel.state==='perched'){foot.z=.63;foot.x=side*.22;knee.z=.48+pair*.1}
        if(pair===0&&side===(buttonX[pose.action]>0?1:-1)){
          foot.lerp(v(buttonX[pose.action],.572-pose.press*.035,-.02),pose.reach);
          knee.lerp(v(buttonX[pose.action]*.6,.77,.11),pose.reach);
        }
        if(pair===0&&side===1&&interaction.reach){foot.lerp(interaction.target,interaction.reach);knee.lerp(v(.44,.76,.27),interaction.reach)}
        line(upper,a,knee);line(lower,knee,foot,.01);
      });
    };
  }else{
    const length=64,around=16,geometry=new THREE.BufferGeometry(),points=new Float32Array((length+1)*(around+1)*3),colors=new Float32Array(points.length),indices:number[]=[];
    for(let i=0;i<length;i++)for(let j=0;j<around;j++){const a=i*(around+1)+j,b=a+around+1;indices.push(a,a+1,b,b,a+1,b+1)}
    geometry.setAttribute('position',new THREE.BufferAttribute(points,3).setUsage(THREE.DynamicDrawUsage));geometry.setIndex(indices);
    for(let i=0;i<=length;i++)for(let j=0;j<=around;j++){
      const shade=.84+.16*Math.sin(j/around*Math.PI*2),at=(i*(around+1)+j)*3;
      colors[at]=shade;colors[at+1]=shade;colors[at+2]=shade*(id==='larva'?.91:.96);
    }
    geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
    const body=mesh(geometry,skin,creature);body.frustumCulled=false;
    const tip=ellipsoid(creature,material(id==='larva'?'#665140':'#d1d9ad',.3),0,.65,.19,.045,.04,.045);
    const path=(u:number,time:number,reach:number,action:Action,press:number,idle:boolean,interaction:Interaction)=>{
      const sway=idle?Math.sin(time*(travel.home?1.6:3.2)-u*7)*(travel.home?.018:.038):0;
      const base=v(Math.sin(u*5.8+.6)*(id==='worm'?.19:.065)+sway,(id==='worm'?.50:.59)+Math.pow(u,5)*(id==='worm'?.20:.12),1.03-u*.82);
      base.lerp(interaction.target,Math.pow(u,4)*interaction.reach);
      return base.lerp(v(buttonX[action],.602-press*.035,-.02),Math.pow(u,5)*reach);
    };
    animateCreature=(time,pose,idle,interaction)=>{
      for(let i=0;i<=length;i++){
        const u=i/length,point=path(u,time,pose.reach,pose.action,pose.press,idle,interaction);
        const tangent=path(Math.min(1,u+.002),time,pose.reach,pose.action,pose.press,idle,interaction).sub(path(Math.max(0,u-.002),time,pose.reach,pose.action,pose.press,idle,interaction)).normalize();
        const normal=v(0,1,0).cross(tangent).normalize(),binormal=tangent.clone().cross(normal).normalize();
        const taper=Math.pow(Math.sin(Math.PI*(.025+u*.95)),id==='worm'?.35:.5);
        const radius=(id==='worm'?.058:.14)*taper*(id==='larva'?.92+.08*Math.cos(u*Math.PI*22):1);
        for(let j=0;j<=around;j++){
          const theta=j/around*Math.PI*2,at=(i*(around+1)+j)*3;
          points[at]=point.x+radius*(normal.x*Math.cos(theta)+binormal.x*Math.sin(theta));
          points[at+1]=point.y+radius*(normal.y*Math.cos(theta)+binormal.y*Math.sin(theta));
          points[at+2]=point.z+radius*(normal.z*Math.cos(theta)+binormal.z*Math.sin(theta));
        }
      }
      geometry.attributes.position.needsUpdate=true;geometry.computeVertexNormals();
      tip.position.copy(path(1,time,pose.reach,pose.action,pose.press,idle,interaction));
    };
  }
  let lastScreen='';
  const updateScreen=(pose:Pose,market:Quote|null,marketHistory:{time:number;price:number}[],fresh:boolean,portfolio?:ScreenPortfolio,browser?:BrowserScreen)=>{
    if(browserMode){
      const frame=browser||{state:'connecting',sequence:0},key=`browser:${frame.state}:${frame.sequence}`;
      if(key===lastScreen)return;lastScreen=key;paintBrowserScreen(screenContext,frame,color);screenTexture.needsUpdate=true;return;
    }
    const key=(market?.id||'waiting')+pose.label+fresh+JSON.stringify(portfolio);if(key===lastScreen)return;lastScreen=key;
    const ctx=screenContext;ctx.fillStyle='#071810';ctx.fillRect(0,0,512,288);
    ctx.fillStyle=color;ctx.font='bold 22px monospace';ctx.fillText((market?.symbol||'DISCOVERING').slice(0,17),24,36);
    ctx.fillStyle='#91aa9a';ctx.font='13px monospace';ctx.fillText(portfolio?`${market?.chain?.toUpperCase()||'FOMO'} / ${portfolio.held?'HELD':'OBSERVING'}`:'SOL / USDT',24,60);
    ctx.fillStyle='#eff5e8';ctx.font='bold 30px monospace';ctx.fillText(market?'$'+tokenPrice(market.price):'Waiting',24,104,portfolio?250:464);
    ctx.fillStyle=fresh?'#91a990':'#d1a36c';ctx.font='12px monospace';ctx.fillText(fresh?(portfolio?'DEX REFERENCE / PAPER':'LIVE PRICE / BINANCE'):market?'LAST PRICE / STALE':'WAITING FOR MARKET',24,130);
    const history=marketHistory.map(p=>p.price),low=history.length?Math.min(...history):0,span=Math.max((market?.price||1)*.00001,Math.max(...history)-low);
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();history.forEach((value,i)=>{const x=24+i/Math.max(1,history.length-1)*(portfolio?245:464),y=210-(value-low)/span*58;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y)});ctx.stroke();
    if(portfolio){
      ctx.strokeStyle='#2b4334';ctx.beginPath();ctx.moveTo(290,24);ctx.lineTo(290,222);ctx.stroke();
      ctx.fillStyle='#a6b99d';ctx.font='13px monospace';ctx.fillText(`HOLDINGS ${portfolio.positions.length}/${portfolio.maxPositions}`,308,38);
      portfolio.positions.forEach((p,i)=>{
        const y=72+i*30;ctx.fillStyle=p.asset_id===market?.asset_id?color:'#b8c9b4';ctx.font='bold 13px monospace';ctx.fillText(p.symbol.slice(0,10),308,y);
        ctx.fillStyle=p.mark_stale?'#d1a36c':p.return_pct<0?'#e8987d':'#b2e482';ctx.font='12px monospace';ctx.textAlign='right';ctx.fillText(p.mark_stale?'STALE':`$${Math.round(p.value)}`,488,y);ctx.textAlign='left';
      });
      if(!portfolio.positions.length){ctx.fillStyle='#748e79';ctx.font='13px monospace';ctx.fillText('Cash / observing',308,80)}
    }
    ctx.fillStyle=pose.confirmed?buttonColors[pose.action]:'#adbca4';ctx.font='17px monospace';ctx.fillText(pose.label,24,258,464);
    screenTexture.needsUpdate=true;
  };
  const name=document.createElement('canvas');name.width=512;name.height=96;
  const nameContext=name.getContext('2d')!;nameContext.textAlign='center';nameContext.fillStyle=color;nameContext.font='36px monospace';nameContext.fillText(id==='worm'?'01 / WORM':id==='adult'?'02 / FLY':'03 / LARVA',256,54);
  const nameTexture=new THREE.CanvasTexture(name);nameTexture.colorSpace=THREE.SRGBColorSpace;textures.add(nameTexture);
  const nameMaterial=new THREE.SpriteMaterial({map:nameTexture,transparent:true,depthWrite:false});materials.add(nameMaterial);
  const nameLabel=new THREE.Sprite(nameMaterial);nameLabel.position.set(0,3.16,-1.1);nameLabel.scale.set(1.8,.337,1);scene.add(nameLabel);
  return{scene,updateCandidates:environment.updateCandidates,move(time:number,enabled:boolean,callHome:boolean,activity?:import('./types').Activity){travel=choreography.step(time,enabled,callHome,activity);return travel},update(pose:Pose,time:number,idle:boolean,market:Quote|null,marketHistory:{time:number;price:number}[],fresh:boolean,portfolio?:ScreenPortfolio,browser?:BrowserScreen){
    const interaction=environment.interaction(time,idle&&travel.home&&!browserMode,pose.moving);
    creatureRoot.position.set(travel.x,.6+travel.y,.65+travel.z);creatureRoot.rotation.y=travel.yaw;
    creatureRoot.rotation.z=id==='adult'?travel.airborne*Math.sin(time*2)*.065:0;
    creatureShadow!.visible=id!=='adult'||travel.home;creatureShadow!.position.x=travel.x;creatureShadow!.position.z=.64+travel.z;creatureShadow!.rotation.z=travel.yaw;
    scene.userData.travel=travel.state;scene.userData.offset=[travel.x,travel.y,travel.z];scene.userData.atDesk=travel.home;
    alertMaterial.emissiveIntensity=(travel.state==='returning'||pose.moving)? .5+.5*Math.sin(time*9):.12;
    scene.userData.idleProp=interaction.name;scene.userData.idleReach=interaction.reach;
    animateCreature(time,pose,idle,interaction);updateScreen(pose,market,marketHistory,fresh,portfolio,browser);
    for(const action of ['BUY','SELL'] as Action[]){
      const selected=action===pose.action;
      caps[action].position.y=.525-(selected?pose.press*.035:0);
      capMaterials[action].emissiveIntensity=.07+(selected?(pose.press*.4+(pose.confirmed?.15:0)):0);
    }
  },dispose(){environment.dispose();geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose())}};
}
