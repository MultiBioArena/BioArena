import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const code=ts.transpile(readFileSync(new URL('../frontend/src/deskPlayback.ts',import.meta.url),'utf8'),{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022});
const {deskPlayback,recordedAction}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const trace=(action,status,fillAction)=>({action,fill:{status,action:fillAction}});
for(const action of ['BUY','SELL']){
  for(let elapsed=0;elapsed<=3000;elapsed+=50){const p=deskPlayback(trace(action,'skipped'),elapsed,true);assert.equal(p.action,action);assert.equal(p.confirmed,false);assert.ok(p.press>=0&&p.press<=1)}
  assert.equal(deskPlayback(trace(action,'skipped'),1200,true).press,1);
}
for(let elapsed=0;elapsed<=3000;elapsed+=50){const p=deskPlayback(trace('HOLD','held'),elapsed,true);assert.equal(p.press,0);assert.equal(p.reach,0);assert.equal(p.moving,false);assert.equal(p.label,'Watching · No trade')}
assert.equal(deskPlayback(trace('BUY','unfilled'),1700,true).confirmed,false);
assert.equal(deskPlayback(trace('BUY','filled','BUY'),1100,true).confirmed,false);
assert.equal(deskPlayback(trace('BUY','filled','BUY'),1700,true).confirmed,true);
const risk=deskPlayback(trace('HOLD','filled','SELL'),1200,true);assert.equal(risk.action,'SELL');assert.equal(risk.press,1);assert.equal(risk.override,true);assert.match(risk.label,/Risk exit/);
assert.equal(recordedAction(null),'HOLD');assert.equal(deskPlayback(null,1200,true).moving,false);
assert.equal(deskPlayback(trace('SELL','filled','SELL'),3000,true).press,0);
console.log('BUY/SELL playback, silent HOLD, no fake fill, risk exit override and completion passed.');
