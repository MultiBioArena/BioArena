import asyncio
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import sqlite3
import time
import yaml
from .market import LiveMarket, FeatureEncoder
from .simulation import initialize, advance, save_checkpoint
from .trading import PaperBroker
from .scheduling import DecisionSchedule
from .policy import OpportunityPolicy
from .registry import DEFAULT_BIOS, roster
from .activity import ActivityPolicy

KEYS=list(DEFAULT_BIOS)

class Arena:
    def __init__(self,root,config=None):
        self.root=Path(root)
        self.config=config if config is not None else yaml.safe_load((self.root/'configs/arena.yaml').read_text())
        if self.config['execution']['mode']!='paper':raise ValueError('Only paper execution is implemented')
        self.keys=roster(self.config)
        self.run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns())[-6:]
        self.run_dir=self.root/'runs'/self.run_id
        self.run_dir.mkdir(parents=True,exist_ok=False)
        self.metadata={k:json.loads((self.root/f'data/processed/{k}/manifest.json').read_text()) for k in self.keys}
        self.visual={k:json.loads((self.root/f'data/processed/{k}/visual.json').read_text()) for k in self.keys}
        code_paths=sorted((self.root/'src').rglob('*.py'))+sorted((self.root/'scripts').glob('*.py'))
        code_hashes={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
        manifest={'run_id':self.run_id,'config':self.config,'connectomes':self.metadata,
            'code_sha256':code_hashes,'python':platform.python_version(),'platform':platform.platform(),
            'execution':'paper','created_at':time.time()}
        (self.run_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        (self.run_dir/'arena.yaml').write_text(yaml.safe_dump(self.config))
        self.market_file=(self.run_dir/'market.jsonl').open('a',buffering=1)
        self.db=sqlite3.connect(self.run_dir/'events.sqlite')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE decisions (id TEXT PRIMARY KEY, seq INTEGER, bio_id TEXT, ts REAL, payload TEXT)')
        self.db.execute('CREATE INDEX decisions_by_sequence ON decisions (seq DESC, bio_id)')
        self.db.execute('CREATE INDEX decisions_by_bio_sequence ON decisions (bio_id, seq DESC)')
        self.db.execute('CREATE TABLE fills (intent_id TEXT PRIMARY KEY, ts REAL, payload TEXT)')
        self.db.execute('CREATE TABLE experiences (id TEXT PRIMARY KEY, bio_id TEXT, ts REAL, payload TEXT)')
        self.encoders={k:FeatureEncoder(self.config) for k in self.keys}
        self.schedule=DecisionSchedule(self.config,self.keys)
        self.phases={k:'waiting' for k in self.keys}
        self.activities={k:ActivityPolicy(k,self.config['seed'],self.config.get('activity')) for k in self.keys}
        self.db.execute('CREATE TABLE activity_events (id TEXT PRIMARY KEY, bio_id TEXT, ts REAL, payload TEXT)')
        self.policies={k:OpportunityPolicy(self.config) for k in self.keys}
        self.broker=PaperBroker(self.config)
        self.market=LiveMarket(self.config,self.record_quote)
        self.histories={k:deque(maxlen=1200) for k in self.keys}
        self.market_history=deque(maxlen=240)
        self.telemetry={k:None for k in self.keys}
        self.recent=deque(maxlen=80)
        self.pools={}
        self.tasks=[]
        self.sequence=0
        self.started_at=None
        self.status='warming'
        self.error=None
        self.paused=False
        self.closed=False
        self.final_price=None
        self.ended_at=None
        self.subscribers=set()

    def record_quote(self,q):
        self.market_file.write(json.dumps(q,allow_nan=False)+'\n')
        self.market_history.append({'time':q['received_at'],'price':q['price']})

    async def start(self):
        context=multiprocessing.get_context('spawn')
        for k in self.keys:
            self.pools[k]=ProcessPoolExecutor(max_workers=1,mp_context=context,
                initializer=initialize,initargs=(str(self.root),k,self.config,getattr(self,'worker_checkpoint',None)))
        self.tasks=[asyncio.create_task(self.market.run()),asyncio.create_task(self.run()),asyncio.create_task(self.broadcast()),asyncio.create_task(self.activity_loop())]

    def state(self):
        quote=self.market.latest
        price=self.final_price if self.final_price is not None else (quote['price'] if quote else 0)
        accounts={k:a.public(price) for k,a in self.broker.accounts.items()}
        ranks=sorted(self.keys,key=lambda k:(accounts[k]['alive'],accounts[k]['equity']),reverse=True)
        bios=[]
        for k in self.keys:
            bios.append({'id':k,'metadata':self.metadata[k],'account':accounts[k],
                         'activity':self.activities[k].current,'rank':ranks.index(k)+1,'telemetry':self.telemetry[k],'history':list(self.histories[k]),
                         'training':self.policies[k].summary(),
                         'decision_clock':{'phase':self.phases[k] if accounts[k]['alive'] else 'out',
                             'next_at':self.schedule.effective_due(k) if accounts[k]['alive'] else None,
                             'interval_seconds':self.schedule.interval,'jitter_seconds':self.schedule.jitter}})
        return {'run_id':self.run_id,'competitors':self.keys,'mode':'paper','status':self.status,'paused':self.paused,
                'server_time':time.time(),'started_at':self.started_at,'ended_at':self.ended_at,'sequence':self.sequence,
                'market':quote,'market_fresh':self.market.fresh(),'market_error':self.market.error,
                'market_history':list(self.market_history),
                'error':self.error,'bios':bios,'recent_decisions':list(self.recent),
                'rules':{k:self.config[k] for k in ['initial_cash','fee_bps','slippage_bps','round_seconds',
                    'stop_equity_fraction','tick_seconds','simulated_ms','cooldown_seconds','readout_threshold']},
                'fomo':{'platform':'https://fomo.family/','status':'not_connected','accounts':len(self.keys)}}

    async def activity_loop(self):
        while True:
            now=time.time()
            for key,policy in self.activities.items():
                account=self.broker.accounts[key]
                positions=getattr(account,'positions',{})
                fresh=self.market.fresh() and all(self.market.quote_fresh(asset) for asset in positions)
                record=policy.step(now,fresh=fresh,alive=account.alive,paused=self.paused or self.status in ('finished','error'),
                    phase=self.phases[key],due_at=self.schedule.effective_due(key),
                    risk=getattr(account,'liquidating',False),trade_at=account.last_trade_ts)
                if record:
                    record['inputs']={'fresh':fresh,'alive':account.alive,'paused':self.paused,'phase':self.phases[key],
                                      'due_at':self.schedule.effective_due(key),'risk':getattr(account,'liquidating',False),
                                      'last_trade_at':account.last_trade_ts,'telemetry_id':(self.telemetry[key] or {}).get('id')}
                    record['away_seconds']=policy.away_time(now)
                    self.db.execute('INSERT INTO activity_events VALUES (?,?,?,?)',
                                    (record['event_id'],key,now,json.dumps(record,allow_nan=False)))
            self.db.commit()
            await asyncio.sleep(1)

    async def broadcast(self):
        while True:
            if self.subscribers:
                payload=json.dumps(self.state(),ensure_ascii=False,allow_nan=False)
                for queue in list(self.subscribers):
                    if queue.full():queue.get_nowait()
                    queue.put_nowait(payload)
            await asyncio.sleep(1)

    def time_limit_reached(self,now):
        duration=self.config['round_seconds']
        return duration>0 and self.started_at is not None and now-self.started_at>=duration

    async def run(self):
        try:
            # Precompile each persistent worker, then reset it in initializer. A ping verifies readiness.
            await asyncio.gather(*[asyncio.wrap_future(p.submit(bool,True)) for p in self.pools.values()])
            self.status='waiting_market'
            await self.recovery_checkpoint()
            while not self.closed:
                if self.paused:
                    self.status='paused';await asyncio.sleep(.25);continue
                if not self.market.fresh():
                    self.status='waiting_market';await asyncio.sleep(.5);continue
                if self.started_at is None:
                    self.started_at=time.time();self.schedule.start(self.started_at)
                if self.time_limit_reached(time.time()):
                    self.finish();break
                active=[k for k in self.keys if self.broker.accounts[k].alive]
                if not active:
                    self.finish();break
                self.status='running'
                k=self.schedule.ready(time.time(),active)
                if k is None:
                    await asyncio.sleep(.1);continue
                timing=self.schedule.dispatch(k,time.time())
                source_quote=dict(self.market.latest)
                features=self.encoders[k].encode(source_quote)
                self.phases[k]='thinking'
                result=await asyncio.wait_for(asyncio.wrap_future(self.pools[k].submit(advance,features)),30)
                outcome=self.policies[k].observe(self.broker.accounts[k],source_quote)
                if outcome:self.db.execute('INSERT INTO experiences VALUES (?,?,?,?)',
                    (outcome['decision_id'],k,outcome['observed_at'],json.dumps(outcome,allow_nan=False)))
                policy=self.policies[k].decide(result,source_quote,self.broker.accounts[k])
                neural_action=result['action']
                result.update(neural_action=neural_action,action=policy['action'],reason=policy['reason'],policy=policy)
                completed=time.time()
                self.phases[k]='settling'
                # Each brain settles against a fresh quote after its own computation completes.
                try:fill_quote=await self.market.after(completed)
                except asyncio.TimeoutError:fill_quote=None
                self.sequence+=1
                decision_id=f'{self.run_id}:{self.sequence}:{k}'
                intent=dict(id=decision_id,bio_id=k,created_at=completed,
                    action=result['action'],score=result['score'],reason=result['reason'],
                    target_position_fraction=policy['target_position_fraction'])
                self.policies[k].remember(decision_id,k,policy,features,result,self.broker.accounts[k],source_quote)
                if fill_quote is None:
                    fill=dict(status='unfilled',reason='No fresh execution quote available.',intent_id=decision_id,bio_id=k)
                elif self.paused:
                    fill=dict(status='held',reason='Paused by the operator.',intent_id=decision_id,bio_id=k)
                else:fill=self.broker.execute(intent,fill_quote)
                if not self.broker.accounts[k].alive:
                    terminal=self.policies[k].observe(self.broker.accounts[k],fill_quote or source_quote)
                    if terminal:self.db.execute('INSERT INTO experiences VALUES (?,?,?,?)',
                        (terminal['decision_id'],k,terminal['observed_at'],json.dumps(terminal,allow_nan=False)))
                timing['completed_at']=completed
                result.update(id=decision_id,run_id=self.run_id,market_sequence=self.sequence,event_sequence=self.sequence,
                    input_quote=source_quote,features=features,created_at=completed,schedule=timing,
                    fill=fill,execution_quote=fill_quote,
                    training_outcome=outcome,
                    account=self.broker.accounts[k].public((fill_quote or source_quote)['price']))
                self.telemetry[k]=result
                self.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',
                    (decision_id,self.sequence,k,completed,json.dumps(result,ensure_ascii=False,allow_nan=False)))
                if fill['status']=='filled':
                    self.db.execute('INSERT INTO fills VALUES (?,?,?)',
                        (decision_id,fill['timestamp'],json.dumps(fill,ensure_ascii=False,allow_nan=False)))
                self.recent.appendleft({field:result[field] for field in ['id','bio_id','created_at','action','score','spikes','fill']})
                self.db.commit()
                self.schedule.completed(time.time());self.phases[k]='waiting'
                current=fill_quote or source_quote
                for key,a in self.broker.accounts.items():
                    self.histories[key].append({'time':current['received_at'],'equity':a.equity(current['price'])})
                await self.recovery_checkpoint()
                if self.sequence%100==0:await self.checkpoint()
            await self.checkpoint()
        except asyncio.CancelledError:raise
        except Exception as e:
            self.status='error';self.error=f'{type(e).__name__}: {e}'
            (self.run_dir/'error.txt').write_text(self.error)
        finally:
            if self.status in ['finished','error']:
                self.tasks[0].cancel()

    def finish(self):
        self.status='finished'
        self.ended_at=time.time()
        self.final_price=self.market.latest['price']
        for k,a in self.broker.accounts.items():
            self.histories[k].append({'time':self.ended_at,'equity':a.equity(self.final_price)})
        result={'run_id':self.run_id,'ended_at':self.ended_at,'mark_quote':self.market.latest,
                'settlement':'mark-to-market; positions retained, no final liquidation fee',
                'accounts':{k:a.public(self.final_price) for k,a in self.broker.accounts.items()}}
        (self.run_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))

    async def checkpoint(self):
        folder=self.run_dir/'checkpoints'/str(self.sequence)
        await asyncio.gather(*[asyncio.wrap_future(p.submit(save_checkpoint,str(folder))) for p in self.pools.values()])
        (folder/'accounts.json').write_text(json.dumps({k:asdict(a) for k,a in self.broker.accounts.items()}))

    async def recovery_checkpoint(self):
        from .recovery import publish
        return await publish(self)

    def decision(self,id):
        row=self.db.execute('SELECT payload FROM decisions WHERE id=?',(id,)).fetchone()
        return json.loads(row[0]) if row else None

    def decisions(self,limit=100):
        return [json.loads(x[0]) for x in self.db.execute('SELECT payload FROM decisions ORDER BY seq DESC,bio_id LIMIT ?',(limit,))]

    def history(self,bio,limit=25,before=None):
        rows=self.db.execute('SELECT seq,payload FROM decisions WHERE bio_id=? AND seq<? ORDER BY seq DESC LIMIT ?',
                             (bio,before if before is not None else self.sequence+1,limit+1)).fetchall()
        items=[]
        for seq,payload in rows[:limit]:
            record=json.loads(payload)
            item={k:record[k] for k in ['id','bio_id','sequence','created_at','action','score','spikes','fill']}
            item['asset']=record.get('asset')
            item['event_sequence']=seq;items.append(item)
        return {'run_id':self.run_id,'items':items,'next_before':items[-1]['event_sequence'] if len(rows)>limit else None}

    async def stop(self):
        self.closed=True
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        for p in self.pools.values():p.shutdown(wait=True,cancel_futures=True)
        self.db.close();self.market_file.close()
