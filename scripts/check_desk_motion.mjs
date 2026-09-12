import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const code=ts.transpile(readFileSync(new URL('../frontend/src/deskMotion.ts',import.meta.url),'utf8'),{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022});
const {createDeskMotion}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
for(const id of ['worm','adult','larva']){
  const c=createDeskMotion(id);let away,states=new Set(),previous;
  for(let t=0;t<90;t+=.05){const m=c.step(t,true,false);states.add(m.state);if(!m.home)away=t;
    assert.ok([m.x,m.y,m.z,m.yaw].every(Number.isFinite));assert.ok(Math.abs(m.x)<=4&&m.y>=0&&m.y<2);
    if(previous)assert.ok(Math.hypot(m.x-previous.x,m.y-previous.y,m.z-previous.z)<.18,'No position jumps');previous=m;
  }
  assert.ok(away!==undefined);assert.ok(states.has(id==='adult'?'flying':'wandering'));if(id==='adult')assert.ok(states.has('perched'));
  const returner=createDeskMotion(id);returner.step(0,true,false);
  const at=id==='worm'?10:id==='adult'?17:25;
  const start=returner.step(at,true,false);assert.equal(start.home,false);
  const called=returner.step(at+.01,true,true);assert.equal(called.state,'returning');assert.equal(called.home,false);
  assert.ok(Math.hypot(start.x-called.x,start.y-called.y,start.z-called.z)<.001,'Recall begins from the actual position');
  let done;
  for(let t=at+.02;t<at+6;t+=.05)done=returner.step(t,true,true);
  assert.equal(done.home,true);assert.deepEqual([done.x,done.y,done.z],[0,0,0]);
  const released=returner.step(at+6,true,false);assert.equal(released.home,true,'Roaming must restart from home after a trade');
  const reduced=returner.step(at+40,false,false);assert.equal(reduced.home,true);assert.equal(reduced.airborne,0);
}
console.log('Independent roaming, flight/perching, smooth recall, home before trading, pause/reduced motion and post-trade restart passed.');
for(const id of ['worm','adult','larva']){
  const motion=createDeskMotion(id);
  const activity={version:'activity-v1',state:'exploring',reason:'Quiet window',event_id:`${id}:1`,started_at:100,ends_at:110,presentation_only:true};
  assert.equal(motion.step(100,true,false,activity).home,false);
  assert.equal(motion.step(104,true,false,activity).home,false);
  const recalled={...activity,state:'returning',started_at:104,ends_at:107};
  assert.equal(motion.step(104.01,true,false,recalled).state,'returning');
  assert.equal(motion.step(109,true,false,{...recalled,state:'attentive'}).home,true);
  assert.equal(motion.step(111,true,false,{...activity,event_id:`${id}:2`,started_at:110,ends_at:120}).home,false);
  assert.equal(motion.step(121,true,false,{...activity,event_id:`${id}:2`,started_at:110,ends_at:120}).home,true);
}
console.log('Recorded activity windows, alert return and natural trip completion passed.');
