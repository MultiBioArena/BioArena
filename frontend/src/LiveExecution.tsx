import {useEffect,useState} from 'react';
import {Activity,ArrowUpRight,Clock3,Radio} from 'lucide-react';
import type {Bio,MarketAsset} from './types';
import {displayNames} from './english';
import './liveExecution.css';

type Asset={asset_id:string;chain:string;address:string};
type Position=Asset&{quantity_raw:string;decimals:number};
type Account={bio_id:string;selected:boolean;phase:string;holding:Position|null;holdings?:Position[];verified_fills:number;blocked_attempts:number;unresolved:boolean};
type Order={source_kind?:string;bio_id:string;action:string;status:string;at:number|null;asset:Asset|null;reason_code:string|null;cash_delta_usd:number|null;balance_verified:boolean;estimated_fee_usd:number|null;estimated_fee_pct:number|null};
type Audit={actions:Record<string,number>;outcomes:Record<string,number>;reasons:Record<string,number>};
type Snapshot={policy_audit?:Record<string,Audit>;execution_kind?:string;check_stage?:string|null;as_of:number;available:boolean;fresh:boolean;running:boolean;executor_state:string;updated_at:number|null;feed_error?:boolean;
  limits:{buy_usd:number;max_buy_usd:number;max_fee_usd:number;max_positions:number;max_fee_pct:number|null}|null;
  trial:{bio_id:string;phase:string;complete:boolean;deadline:number|null;cash_change_usd:number|null;managed_portfolio?:boolean;completed_round_trips?:number;entry_target_reached?:boolean}|null;
  bios:Account[];orders:Order[];orders_truncated:boolean};

const phases:Record<string,string>={waiting_buy:'Waiting for BUY',waiting_sell:'Waiting for SELL',managing_positions:'Managing real positions',closing_positions:'Managing remaining exits',complete:'Round trip verified',expired:'Trial expired',review_required:'Needs reconciliation',submitting:'Awaiting order result',not_enabled:'Not enabled',stopped:'Executor stopped',observing:'Observing',check_incomplete:'Check incomplete'};
const checkStages:Record<string,string>={preparing_buy:'Preparing BUY',buy_verified:'BUY verified',exit_cooldown:'Exit cooldown',preparing_sell:'Preparing full SELL',complete:'Execution check passed',incomplete:'Execution check incomplete',quote_only:'Quote rehearsal',stopped:'Execution check stopped'};
const reasons:Record<string,string>={hold:'Bio chose HOLD',trial_filter:'Different trial leg or token',position_mismatch:'No matching live holding',position_limit:'Live position capacity reached',fee_limit:'Fee limit exceeded',impact_limit:'Price impact exceeded',slippage_limit:'Quoted slippage exceeded',unsupported_chain:'Chain not supported for execution',platform_block:'Platform requires attention',trade_form_block:'Trade form unavailable',cash_limit:'Insufficient cash with fee reserve',expired_signal:'Signal expired',entry_budget:'Entry budget reached',cooldown:'Execution cooldown',paper_exploration:'Paper exploration excluded',execution_check:'Execution check did not pass'};
const amount=(n:number)=>n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const name=(id:string)=>displayNames[id]||id;

export default function LiveExecution({bios,assets=[]}:{bios:Bio[];assets?:MarketAsset[]}){
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[failed,setFailed]=useState(false),[received,setReceived]=useState(0),[now,setNow]=useState(Date.now()/1000),[filter,setFilter]=useState('all');
  useEffect(()=>{
    let stopped=false,timer:ReturnType<typeof setTimeout>,controller:AbortController|null=null;
    const poll=async()=>{
      const request=new AbortController();controller=request;
      const abort=setTimeout(()=>request.abort(),8000);
      try{
        const response=await fetch('/api/execution',{cache:'no-store',signal:request.signal});
        if(!response.ok)throw Error('Execution feed unavailable');
        const data:Snapshot=await response.json();
        if(!data||!Array.isArray(data.bios)||!Array.isArray(data.orders)||typeof data.as_of!=='number')throw Error('Invalid execution feed');
        if(!stopped){setSnapshot(data);setReceived(Date.now()/1000);setFailed(false)}
      }catch{if(!stopped)setFailed(true)}finally{clearTimeout(abort);if(!stopped)timer=setTimeout(poll,3000)}
    };
    void poll();const clock=setInterval(()=>setNow(Date.now()/1000),1000);
    return()=>{stopped=true;clearTimeout(timer);clearInterval(clock);controller?.abort()};
  },[]);
  const stale=failed||!!snapshot?.available&&(!snapshot.fresh||now-received>12);
  const running=!!snapshot?.running&&!stale;
  const rows=filter==='all'?snapshot?.orders||[]:(snapshot?.orders||[]).filter(r=>r.bio_id===filter);
  const selected=snapshot?.bios.find(b=>b.selected);
  const operatorCheck=snapshot?.execution_kind==='operator_check';
  const left=snapshot?.trial?.deadline?Math.max(0,Math.ceil(snapshot.trial.deadline-(snapshot.as_of+now-received))):null;
  const stateLabel=!snapshot?'Connecting':!snapshot.available?(snapshot.executor_state==='not_started'?'Not started':'Status unavailable'):stale?'Last report · stale':running?'Executor running':'Executor stopped';
  const label=(a:Asset)=>assets.find(x=>x.asset_id===a.asset_id)?.symbol||`${a.address.slice(0,6)}…${a.address.slice(-4)}`;
  return <section className="panel live-execution" aria-labelledby="live-execution-heading" data-execution-state={running?'running':stale?'stale':snapshot?.executor_state||'loading'}>
    <div className="live-execution-heading"><div><span className="live-preview-kicker">PREVIEW · REAL ACCOUNT OBSERVATIONS</span><h2 id="live-execution-heading"><Radio size={18}/> Live execution</h2></div><span className={`execution-health ${running?'is-running':''}`} role="status"><i/>{stateLabel}</span></div>
    <div className="execution-overview"><p>{snapshot?.trial?`${name(snapshot.trial.bio_id)} · ${operatorCheck?'Execution acceptance check':'Strategy execution trial'}`:'FOMO account execution'}<span>{snapshot?.limits?`$${amount(snapshot.limits.buy_usd)} per entry · up to ${snapshot.limits.max_positions} holdings · $${amount(snapshot.limits.max_fee_usd)}${snapshot.limits.max_fee_pct===null?'':` and ${snapshot.limits.max_fee_pct}%`} fee cap per order`:'Waiting for an execution report'}</span></p><div className="execution-progress"><Clock3 size={14}/>{running&&snapshot?.trial?.managed_portfolio&&snapshot.trial.phase==='closing_positions'&&left===0?'Entry window closed · managing exits':running&&left!==null?`${Math.floor(left/60)}m ${String(left%60).padStart(2,'0')}s remaining`:operatorCheck?checkStages[snapshot?.check_stage||'']||'Execution check':snapshot?.trial?phases[snapshot.trial.phase]:'No active trial'}</div></div>
    {(stale||snapshot?.feed_error)&&<p className="execution-warning" role="status">{stale?'Execution status is out of date. Values below are the last reported observations.':'Decision feed is unavailable. New entries are paused; managed exits use separate price checks.'}</p>}
    <div className="execution-accounts">{(snapshot?.bios.length?snapshot.bios:bios.map(b=>({bio_id:b.id,selected:false,phase:'not_enabled',holding:null,holdings:[] as Position[],verified_fills:0,blocked_attempts:0,unresolved:false}))).map(account=>{
      const bio=bios.find(b=>b.id===account.bio_id),policy=bio?.telemetry;
      const positions=account.holdings||(account.holding?[account.holding]:[]),audit=snapshot?.policy_audit?.[account.bio_id];
      return <article key={account.bio_id} className={`execution-account ${account.selected?'is-selected':''}`} style={{'--execution-bio':bio?.metadata.color||'#9cb689'} as React.CSSProperties}>
        <div className="execution-account-title"><strong>{name(account.bio_id)}</strong><span>{account.selected?(operatorCheck?'EXECUTION CHECK':'LIVE TRIAL'):'STANDBY'}</span></div>
        <h3>{!snapshot?.available?'Status unavailable':phases[account.phase]||'Status unavailable'}</h3>
        <div className="execution-position"><span>Recorded live holdings</span>{positions.length?positions.map(position=><a key={position.asset_id} href={`https://fomo.family/tokens/${position.chain}/${position.address}`} target="_blank" rel="noopener noreferrer">{label(position)} <small>{(Number(position.quantity_raw)/10**position.decimals).toLocaleString('en-US',{maximumFractionDigits:6})} tokens</small><ArrowUpRight size={13}/></a>):<strong>{snapshot?.available?'No executor-owned position':'—'}</strong>}</div>
        <div className="execution-counts"><span><b>{snapshot?.available?account.verified_fills:'—'}</b> verified fills</span><span><b>{snapshot?.available?account.blocked_attempts:'—'}</b> blocked</span></div>
        {account.selected&&operatorCheck?<div className="execution-policy"><span>Operator execution check <b>{checkStages[snapshot?.check_stage||'']||'CHECK'}</b></span><p>Buy the specified token, verify the fill, then sell the full position after the execution cooldown.</p><small>Execution acceptance test · No Bio strategy signal</small></div>:account.selected&&policy?<div className="execution-policy"><span><Activity size={12}/> Latest strategy signal <b>{policy.action}</b></span><p>{policy.reason}</p><small>{policy.asset?.symbol||'Token observation'} · {new Date(policy.created_at*1000).toLocaleTimeString('en-GB',{hour12:false})} · {now-policy.created_at>90?'last reported':'paper policy source'}</small></div>:<p className="execution-standby">{account.selected?'Waiting for strategy telemetry.':'This account is outside the current trial.'}</p>}
        {account.selected&&!operatorCheck&&audit&&<div className="execution-policy"><span>Observed strategy signals</span><p>BUY {audit.actions.BUY||0} · SELL {audit.actions.SELL||0} · HOLD {audit.actions.HOLD||0}</p><small>Filtered {(audit.outcomes.filtered||0)+(audit.outcomes.held||0)} · Blocked {audit.outcomes.blocked||0} · Verified fills {audit.outcomes.filled||0}</small>{Object.entries(audit.reasons).map(([key,count])=><small key={key}>{reasons[key]||'Execution check required'}: {count}</small>)}</div>}
      </article>
    })}</div>
    <details className="execution-orders"><summary>Real orders & receipts <span>{snapshot?.bios.reduce((n,b)=>n+b.verified_fills,0)||0} verified fills</span></summary><div className="execution-filter" role="group" aria-label="Filter real orders">{['all',...(snapshot?.bios||[]).map(b=>b.bio_id)].map(id=><button key={id} aria-pressed={filter===id} onClick={()=>setFilter(id)}>{id==='all'?'All Bios':name(id)}</button>)}</div>{rows.length?<div className="table-scroll"><table><thead><tr><th>TIME</th><th>BIO</th><th>ACTION / TOKEN</th><th>RESULT</th><th>QUOTED TOTAL FEE</th><th>CASH CHANGE</th></tr></thead><tbody>{rows.map((row,index)=><tr key={`${row.at}-${row.bio_id}-${index}`}><td>{row.at?new Date(row.at*1000).toLocaleTimeString('en-GB',{hour12:false}):'—'}</td><td>{name(row.bio_id)}</td><td>{row.action} · {row.asset?label(row.asset):'Unsupported asset'}<small>{row.source_kind==='operator_execution_check'?'Execution check':row.source_kind==='live_position_exit'?'Real position exit':'Bio policy'}</small></td><td>{row.status==='filled'&&row.balance_verified?'Verified fill':row.status==='unknown'||row.status==='attempting'?'Unresolved':row.status}{row.reason_code&&<small>{reasons[row.reason_code]}</small>}</td><td>{row.estimated_fee_usd===null?'—':`$${amount(row.estimated_fee_usd)}${row.estimated_fee_pct===null?'':` · ${row.estimated_fee_pct.toFixed(2)}%`}`}</td><td>{row.cash_delta_usd===null?'—':`${row.cash_delta_usd>=0?'+':'−'}$${amount(Math.abs(row.cash_delta_usd))}`}</td></tr>)}</tbody></table></div>:<p className="execution-empty">{snapshot?.available?'No real order attempts recorded for this selection.':'Real order records are unavailable.'}</p>}{snapshot?.orders_truncated&&<p className="execution-empty">Showing the latest 40 attempts.</p>}</details>
    <div className="execution-scope"><p>{selected?.phase==='expired'&&selected.holding?'The trial expired with a recorded holding. Expiry does not liquidate positions.':snapshot?.trial?.complete?`Verified round trip cash change: $${amount(snapshot.trial.cash_change_usd||0)}.`:snapshot?.trial?.managed_portfolio?'The entry deadline stops new buys. Existing holdings remain under exit management until verified closed or reconciliation is required.':'Completion requires a verified buy, a matching full sell, and account balance changes.'}</p><span>Main studio monitors show real browser snapshots; gestures replay verified real fills. Equity, portfolios and neural views remain paper data. Live account equity and learning feedback are pending.</span></div>
  </section>;
}
