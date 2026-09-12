import {useEffect, useState} from 'react';
import type {FormEvent} from 'react';
import {Clock3, ArrowUpRight, Check, ChevronDown} from 'lucide-react';
import type {BioId} from './types';
import {displayNames} from './english';
import './hourlyChallenge.css';

type Gate = {enabled:boolean; mode:'disabled'|'paper_test'|'token_holder'; chain_id:number|null; token:string|null; minimum_raw:string};
type Result = {outcome:string; winners:BioId[]; rows:{bio_id:BioId; start_equity:number; end_equity:number; eligible:boolean; return_pct:number|null; pnl_usd:number|null}[]};
type Round = {id:string; start:number; end:number; vote_close:number; status:string; reason:string|null; opening_at:number|null; closing_at:number|null; latest_at:number|null; result:Result|null; counts:Record<BioId,number>; rules:{gate:Gate;participants?:BioId[]}};
type Overview = {server_time:number; fresh:boolean; error:string|null; gate:Gate; current:Round|null; history:Round[]};
type Receipt = {receipt:string; round_id:string; bio_id:BioId; address_hint:string; prediction_status:string};
const usd = (n:number)=>n.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2});
const utc = (n:number)=>new Date(n*1000).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'});
const countdown = (seconds:number)=>`${Math.floor(Math.max(0,seconds)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,seconds)%60).toString().padStart(2,'0')}`;
const outcome = (r:Round)=>r.status==='void'?'Round void':r.result?.outcome==='winner'?`${displayNames[r.result.winners[0]]} wins`:r.result?.outcome==='tie'?`Tie · ${r.result.winners.map(b=>displayNames[b]).join(' / ')}`:r.result?.outcome==='no_loss'?'No loss winner':'Not enough participants';

export function HourlyChallenge(){
  const [data,setData]=useState<Overview|null>(null),[failed,setFailed]=useState(false),[now,setNow]=useState(0);
  const [address,setAddress]=useState(''),[bio,setBio]=useState<BioId>('worm'),[sending,setSending]=useState(false),[message,setMessage]=useState('');
  const [receipt,setReceipt]=useState<Receipt|null>(null);
  useEffect(()=>{
    let stopped=false,timer:ReturnType<typeof setTimeout>,controller:AbortController|null=null,serverOffset=0;
    const poll=async()=>{
      if(document.hidden){timer=setTimeout(poll,10000);return}
      controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),8000);
      try{
        const response=await fetch('/api/challenge',{signal:controller.signal,cache:'no-store'});
        if(!response.ok)throw Error('Unavailable');
        const next:Overview=await response.json();
        if(!stopped){serverOffset=next.server_time-Date.now()/1000;setData(next);setNow(next.server_time);setFailed(false)}
      }catch{if(!stopped)setFailed(true)}
      finally{clearTimeout(timeout);if(!stopped)timer=setTimeout(poll,10000)}
    };
    const tick=setInterval(()=>{if(!document.hidden)setNow(Date.now()/1000+serverOffset)},1000);
    void poll();
    return()=>{stopped=true;clearTimeout(timer);clearInterval(tick);controller?.abort()};
  },[]);
  const round=data?.current,gate=round?.rules.gate||data?.gate;
  const ids=round?.rules.participants||Object.keys(round?.counts||{worm:0,adult:0,larva:0});
  const choicesKey=ids.join(',');
  useEffect(()=>{if(ids.length&&!ids.includes(bio))setBio(ids[0])},[choicesKey,bio]);
  const isTest=gate?.mode==='paper_test';
  const open=!!round&&round.status==='open';
  const active=!!data?.fresh&&!failed&&!!round?.latest_at&&now-round.latest_at<=20;
  const canVote=open&&active&&!!gate?.enabled&&now<round.vote_close;
  const warmup=!round||round.status==='warmup';
  const nextHour=Math.floor(now/3600)*3600+3600;
  const target=warmup?nextHour:round.end;
  const canSubmit=canVote&&ids.includes(bio)&&round?.result?.rows.find(r=>r.bio_id===bio)?.eligible!==false&&!sending&&/^0x[0-9a-fA-F]{40}$/.test(address.trim());
  useEffect(()=>{
    setMessage('');
    if(!round)return;
    let cancelled=false;
    try{
      const token=localStorage.getItem('bio:last-vote');
      if(token)void fetch(`/api/challenge/receipts/${encodeURIComponent(token)}`).then(r=>r.ok?r.json():null).then(r=>{if(r&&!cancelled)setReceipt(r)}).catch(()=>{});
    }catch{/* Storage can be unavailable in private browsing. */}
    return()=>{cancelled=true};
  },[round?.id]);
  useEffect(()=>{
    if(!receipt||receipt.prediction_status!=='pending'||!data)return;
    if(!data.history.some(r=>r.id===receipt.round_id&&['settled','void'].includes(r.status))&&!(round?.id===receipt.round_id&&['settled','void'].includes(round.status)))return;
    let stopped=false;
    void fetch(`/api/challenge/receipts/${receipt.receipt}`).then(r=>r.ok?r.json():null).then(r=>{if(r&&!stopped)setReceipt(r)}).catch(()=>{});
    return()=>{stopped=true};
  },[data,receipt,round]);
  const submit=async(event:FormEvent)=>{
    event.preventDefault();if(!canSubmit||!round)return;
    setSending(true);setMessage('');
    try{
      const response=await fetch('/api/challenge/votes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({round_id:round.id,address:address.trim(),bio_id:bio}),signal:AbortSignal.timeout(15000)});
      const result=await response.json();
      if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Could not record your vote');
      setReceipt(result);setMessage(`${isTest?'Test vote':'Prediction'} recorded for ${displayNames[result.bio_id as BioId]}.`);
      try{localStorage.setItem('bio:last-vote',result.receipt)}catch{}
      const refresh=await fetch('/api/challenge',{cache:'no-store'});if(refresh.ok)setData(await refresh.json());
    }catch(error){setMessage(error instanceof Error?error.message:'Vote could not be recorded. Please retry.')}
    finally{setSending(false)}
  };
  return <section className="panel hourly-challenge" id="hourly-challenge" aria-labelledby="challenge-title">
    <div className="challenge-heading"><div><span className="eyebrow">AUDIENCE EXPERIMENT / PAPER PREVIEW</span><h2 id="challenge-title">The hourly loss challenge</h2><p>Who loses the largest percentage this hour? The brains still trade to earn.</p></div><div className="challenge-timer"><span><Clock3 size={12}/>{warmup?'NEXT ROUND IN':now>=target?'SETTLING':'ROUND ENDS IN'}</span><strong>{data?countdown(target-now):'—:—'}</strong><small>{round?`${utc(round.start)}–${utc(round.end)} UTC`:'Hourly · UTC'}</small></div></div>
    {(!active||warmup)&&<p className="challenge-notice" role="status">{failed?'Hourly data unavailable. Last values are retained; voting is paused.':warmup?'Collecting the opening snapshot for the next full UTC hour. Test voting opens with the round.':data?.error||'Waiting for fresh account valuations. Voting is paused.'}</p>}
    <div className="challenge-body"><div className="challenge-standings">
      <div className="challenge-column-labels"><span>COMPETITOR / OPEN → NOW</span><span>HOURLY RETURN</span></div>
      {ids.map(id=>{
        const row=round?.result?.rows.find(r=>r.bio_id===id),pct=row?.return_pct;
        const leading=open&&!!round?.result?.winners.includes(id);
        return <div className={`challenge-row ${id}`} key={id}><span className="challenge-bio-dot"/><div><strong>{displayNames[id]}{leading&&<small>LOSS LEADER</small>}</strong><span>{row?`${usd(row.start_equity)} → ${usd(row.end_equity)}`:'Waiting for opening equity'}</span></div><div className="challenge-return"><strong className={pct!=null&&pct<0?'negative':''}>{pct==null?'—':`${pct>=0?'+':''}${pct.toFixed(3)}%`}</strong><span>{row&&!row.eligible?'SITTING OUT':pct!=null?`${usd(row?.pnl_usd||0)} P&L`:'NOT SCORED'}</span></div></div>
      })}
      <p className="challenge-footnote">Percentage return resets each hour. Account balances and learning continue.</p>
      {round?.status==='settled'&&<div className="challenge-result"><Check size={15}/>{outcome(round)}</div>}
    </div><form className="challenge-vote" onSubmit={submit}>
      <div className="vote-title"><h3>Pick the loss leader</h3><span>{isTest?'TEST VOTE':gate?.mode==='token_holder'?'TOKEN HOLDERS':'COMING LATER'}</span></div>
      <p>{isTest?'Paper test · any non-zero EVM address. Holdings are not checked. No rewards.':gate?.mode==='token_holder'?`ERC-20 holder check · chain ${gate.chain_id}. One address, one vote per round.`:'EVM holder voting will open after the network and token are configured.'}</p>
      <fieldset disabled={!canVote||sending}><legend className="sr-only">Choose a Bio</legend><div className="vote-options">{ids.map(id=><label key={id} className={bio===id?'chosen':''}><input type="radio" name="challenge-bio" value={id} checked={bio===id} onChange={()=>setBio(id)} disabled={round?.result?.rows.find(r=>r.bio_id===id)?.eligible===false}/><strong>{displayNames[id]}</strong><small>{round?.counts[id]||0} votes</small></label>)}</div><label className="vote-address-label" htmlFor="vote-address">EVM wallet address</label><input id="vote-address" className="vote-address" value={address} onChange={e=>setAddress(e.target.value)} placeholder="0x…" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={42} pattern="0x[0-9a-fA-F]{40}" aria-describedby="vote-ownership"/></fieldset>
      <button className="vote-submit" disabled={!canSubmit} type="submit">{sending?'Recording…':warmup?'Opens next round':!gate?.enabled?'Voting not enabled':!open||now>=round!.vote_close?'Voting closed':isTest?'Cast test vote':'Check holdings & vote'}<ArrowUpRight size={15}/></button>
      <small className="vote-cutoff">Voting closes 15 minutes after the UTC hour. Choices are final.</small>
      <p id="vote-ownership" className="vote-ownership">No wallet connection. Entering an address does not prove ownership. Predictions are not reward claims.</p>
      {message&&<p role="status" className="vote-message">{message}</p>}
      {receipt&&<div className="vote-receipt"><Check size={13}/><span>{displayNames[receipt.bio_id]} · {receipt.address_hint} · {receipt.prediction_status}<small>Receipt {receipt.receipt.slice(0,12)}</small></span></div>}
    </form></div>
    <details className="challenge-rules"><summary>Round rules & recent results <ChevronDown size={14}/></summary><div className="challenge-rule-content"><p>Ranking uses each Bio’s hourly percentage return, including marked holdings, fees and trading costs. Different account sizes are comparable. A tie shares the result; if nobody loses, there is no loss winner. An unfunded or inactive Bio sits out the next round.</p><p>Paper boundaries use the first fresh snapshot within 20 seconds of each UTC hour. Missing boundaries or an arena reset void the round. Live scoring is not connected: it will require reconciled deposits and withdrawals with valuations before and after each flow. Refills do not erase earlier losses.</p>{round?.opening_at&&<p className="challenge-evidence">Opening sample: {new Date(round.opening_at*1000).toISOString()}{round.closing_at?` · Closing sample: ${new Date(round.closing_at*1000).toISOString()}`:''}</p>}{gate?.token&&<p className="challenge-evidence">Token: {gate.token} · chain {gate.chain_id} · minimum {gate.minimum_raw} raw units</p>}
      {data?.history.length?<div className="challenge-history">{data.history.map(r=><div key={r.id}><time>{new Date(r.start*1000).toISOString().slice(5,10)} · {utc(r.start)}–{utc(r.end)} UTC</time><strong>{outcome(r)}</strong><a href={`/api/challenge/rounds/${encodeURIComponent(r.id)}`} target="_blank" rel="noreferrer">Round evidence ↗</a>{r.reason&&<small>{r.reason}</small>}</div>)}</div>:<p className="challenge-empty">Completed rounds will appear here. No results have been generated yet.</p>}</div></details>
  </section>;
}
