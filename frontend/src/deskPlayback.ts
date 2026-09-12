import type {Action,Trace} from './types';
import type {ScreenExecution} from './fomoScreens';

export const DESK_REPLAY_MS=2400;
export const buttonLabels:Record<Action,string>={BUY:'BUY',SELL:'SELL',HOLD:'HOLD'};
export const buttonX:Record<Action,number>={BUY:-.72,SELL:.72,HOLD:0};
export const buttonColors:Record<Action,string>={BUY:'#b2e482',SELL:'#e8987d',HOLD:'#a3adc1'};
const smooth=(x:number)=>{const t=Math.max(0,Math.min(1,x));return t*t*(3-2*t)};

export function recordedAction(trace:Trace|null|undefined):Action{
  return trace?.fill.status==='filled'&&trace.fill.action?trace.fill.action:trace?.action||'HOLD';
}

export function deskPlayback(trace:Trace|null,elapsed:number,playing:boolean){
  // A risk exit may execute a SELL even when the neural signal was HOLD or BUY.
  const filled=trace?.fill.status==='filled';
  const action=recordedAction(trace);
  const override=!!trace&&filled&&action!==trace.action;
  const moving=!!trace&&action!=='HOLD'&&playing&&elapsed<DESK_REPLAY_MS;
  const reach=moving?smooth((elapsed-250)/550)*(1-smooth((elapsed-1650)/650)):0;
  const press=moving?smooth((elapsed-900)/150)*(1-smooth((elapsed-1350)/220)):0;
  const result=trace?(filled?'Paper filled':action==='HOLD'?'No trade':'No fill'):'Waiting for a decision';
  const label=action==='HOLD'?'Watching · No trade':!trace?result:!moving?`${override?'Risk exit · ':''}${buttonLabels[action]} · ${result}`:elapsed<250?`${buttonLabels[action]} alert`:elapsed<1450?`${override?'Risk exit · ':''}Press ${buttonLabels[action]}`:result;
  return{action,override,reach,press,moving,label,result,confirmed:!!filled&&(!moving||elapsed>=1450)};
}

export function executionPlayback(execution:ScreenExecution|undefined,elapsed:number,playing:boolean):ReturnType<typeof deskPlayback>{
  const order=execution?.order,verified=order?.status==='filled'&&order.balance_verified===true;
  const action=order?.action||'HOLD',moving=!!verified&&playing&&elapsed<DESK_REPLAY_MS;
  const reach=moving?smooth((elapsed-250)/550)*(1-smooth((elapsed-1650)/650)):0;
  const press=moving?smooth((elapsed-900)/150)*(1-smooth((elapsed-1350)/220)):0;
  const phase=execution?.phase;
  let label=!execution?.fresh?'Waiting for execution feed':!execution.running?'Execution not enabled':['waiting_sell','managing_positions','closing_positions'].includes(phase||'')?'Watching live holdings':'Waiting for strategy';
  if(order?.status==='attempting')label=`${action} · execution in progress`;
  else if(order?.status==='unknown')label=`${action} · needs reconciliation`;
  else if(order?.status==='blocked')label=`${action} blocked · no order submitted`;
  else if(moving)label=`Verified ${action} · replay`;
  return {action,override:false,reach,press,moving,label,result:verified?'Real fill verified':'No verified fill',confirmed:!!verified&&moving};
}
