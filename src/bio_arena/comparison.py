"""Conditional policy experiments on an immutable, historically observed tape."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3

from .learning import ReadoutLearner, model_features
from .portfolio import PortfolioBroker
from .registry import roster, seed_offset
from .simulation import Brain

MODES=('adaptive','fixed_neural','momentum','cash')
VERSION='conditional-policy-comparison-v1'


def capture(run, limit):
    """Only complete source decisions whose entire candidate slate was captured."""
    run=Path(run);manifest=json.loads((run/'manifest.json').read_text());keys=roster(manifest['config'])
    with sqlite3.connect(f'file:{run}/events.sqlite?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        observations=[]
        for key in keys:
            rows=db.execute('SELECT payload FROM observations WHERE bio_id=? ORDER BY rowid DESC LIMIT ?',(key,limit)).fetchall()
            observations.extend(json.loads(row[0]) for row in reversed(rows))
        ids={o['id'] for o in observations}
        first=min(o['evaluated_at'] for o in observations);last=max(o['evaluated_at'] for o in observations)
        decisions=[]
        for (raw,) in db.execute('SELECT payload FROM decisions WHERE ts>=? AND ts<=? ORDER BY seq',(first,last+60)):
            d=json.loads(raw);slate=[e['observation_id'] for e in d['selection']]
            if slate and set(slate)<=ids:
                decisions.append({'id':d['id'],'bio_id':d['bio_id'],'at':d['created_at'],'slate':slate})
    if not decisions:raise ValueError('No complete candidate decisions in the requested tape')
    end=max(d['at'] for d in decisions)+manifest['config']['memecoin']['quote_max_age_seconds']
    quotes=[]
    with (run/'market.jsonl').open() as file:
        for line in file:
            try:q=json.loads(line)
            except json.JSONDecodeError:break  # A concurrent final partial line is not evidence.
            if first<=q['received_at']<=end:quotes.append(q)
    return {'version':VERSION,'source_run':manifest['run_id'],'config':manifest['config'],
            'connectomes':manifest['connectomes'],'observations':observations,'decisions':decisions,
            'quotes':quotes,'first_at':first,'last_at':max((q['received_at'] for q in quotes),default=last)}


def choose(bio, slate, broker, learner, mode, rng, now, settings):
    account=broker.accounts[bio];scores=[]
    for row in slate:
        q=row['input_quote'];neural=row['neural'];cost=row['evaluation']['round_trip_cost_bps']
        prior=neural['score']*180+math.tanh(q['change_5m_pct']/5)*180-cost
        score=(learner.estimate(row['vector']) if learner.active_version else prior) if mode=='adaptive' else (
            prior if mode=='fixed_neural' else math.tanh(q['change_5m_pct']/5)*180-cost)
        held=account.positions.get(q['asset_id']);risk=False;action='HOLD'
        if held:
            risk=account.liquidating or held.quantity*q['price']/held.cost_basis-1<=-settings['position_stop_fraction']
            if risk or (now-held.opened_at>=settings['minimum_hold_seconds'] and score < -settings['exit_margin_bps']):action='SELL'
        elif (row['evaluation']['entry_problem'] is None and row['features']['history_samples']>=settings['bio_warmup_observations']
              and score>settings['entry_margin_bps']):action='BUY'
        scores.append((row,score,action,risk))
    if mode=='cash':return None
    exits=[s for s in scores if s[2]=='SELL']
    entries=[s for s in scores if s[2]=='BUY']
    fraction=settings['allocation_fraction']
    if exits:selected=max(exits,key=lambda s:(s[3],-s[1]))
    elif entries:selected=max(entries,key=lambda s:s[1])
    else:
        draw=rng.random()
        candidates=[s for s in scores if s[0]['input_quote']['asset_id'] not in account.positions
                    and s[0]['evaluation']['entry_problem'] is None
                    and s[0]['features']['history_samples']>=settings['bio_warmup_observations']]
        if not candidates or draw>=settings['learning']['paper_exploration_probability']:return None
        selected=rng.choice(candidates);selected=(*selected[:2],'BUY',False)
        fraction=settings['learning']['exploration_fraction']
    row,score,action,risk=selected
    return {'id':'','bio_id':bio,'asset_id':row['input_quote']['asset_id'],'action':action,'created_at':now,
            'allocation_fraction':fraction,'sell_fraction':1.,'risk_exit':risk,
            'reason':f'{VERSION}: {mode}', 'entry_allowed':row['evaluation']['entry_problem'] is None}


def experiment(root, tape, seed, *, brain_factory=Brain):
    config=tape['config'];keys=roster(config);settings=config['memecoin']
    brains={k:brain_factory(root,k,config) for k in keys}
    # Keep synthetic calibration fixed; vary the neural noise stream explicitly.
    for key,brain in brains.items():
        brain.seed=seed+seed_offset(key,'brain');brain.reset()
    learners={k:ReadoutLearner(k,seed,settings['learning']) for k in keys}
    brokers={mode:PortfolioBroker(config['initial_cash'],settings,config['stop_equity_fraction'],keys=keys) for mode in MODES}
    rng={mode:{k:random.Random(seed+seed_offset(k,'learner')) for k in keys} for mode in MODES}
    events=[(q['received_at'],0,i,'quote',q) for i,q in enumerate(tape['quotes'])]
    events += [(o['evaluated_at'],1,i,'observation',o) for i,o in enumerate(tape['observations'])]
    events += [(d['at'],2,i,'decision',d) for i,d in enumerate(tape['decisions'])]
    current={};observed={};pending={mode:{} for mode in MODES};fills=[];predictions=defaultdict(list)
    scores={};spikes={k:hashlib.sha256() for k in keys};peak={m:{k:config['initial_cash'] for k in keys} for m in MODES}
    drawdown={m:{k:0. for k in keys} for m in MODES}
    for at,_,__,kind,row in sorted(events,key=lambda e:e[:3]):
        if kind=='quote':
            asset=row['asset_id'];current[asset]=row
            for learner in learners.values():
                for label in learner.pending:
                    if label['asset_id']==asset and label['pair_address']==row['pair_address'] and at>label['observed_at']:
                        label['minimum_price']=min(label['minimum_price'],row['price'])
            for mode,broker in brokers.items():
                broker.mark({asset:row})
                for bio,intent in list(pending[mode].items()):
                    if at>intent['created_at']+settings['quote_max_age_seconds']:
                        del pending[mode][bio];continue
                    if intent['asset_id']==asset and at>intent['created_at']:
                        entry=intent.pop('entry_allowed') and not row.get('pool_changed',False)
                        fill=broker.execute(intent,row,now=at,entry_allowed=entry)
                        if fill['status']=='filled':fills.append({'mode':mode,**fill,'decision_at':intent['created_at']})
                        del pending[mode][bio]
                for bio,account in broker.accounts.items():
                    if not account.public(at,settings['quote_max_age_seconds'])['valuation_stale']:
                        equity=account.equity();peak[mode][bio]=max(peak[mode][bio],equity)
                        drawdown[mode][bio]=max(drawdown[mode][bio],1-equity/peak[mode][bio])
        elif kind=='observation':
            bio=row['bio_id'];neural=brains[bio].step(row['features'])
            spikes[bio].update(neural['counts_sha256'].encode())
            vector=model_features(neural,row['features'],row['input_quote'],row['evaluation']['round_trip_cost_bps'])
            observed[row['id']]={**row,'neural':neural,'vector':vector}
            if row['evaluation']['round_trip_cost_bps']<3000:
                learner=learners[bio]
                learner.watch(row['id'],row['input_quote'],vector,row['evaluation']['round_trip_cost_bps'],at)
                q=row['input_quote'];cost=row['evaluation']['round_trip_cost_bps']
                scores[row['id']]={'adaptive':learner.estimate(vector),
                    'fixed_neural':neural['score']*180+math.tanh(q['change_5m_pct']/5)*180-cost,
                    'momentum':math.tanh(q['change_5m_pct']/5)*180-cost,'cash':0.}
        else:
            bio=row['bio_id'];learner=learners[bio]
            for outcome in learner.observe(current,at,settings['quote_max_age_seconds']):
                predictions[bio].append({'id':outcome['id'],'target':outcome['training_target_bps'],'predictions':scores.pop(outcome['id'])})
            slate=[observed[id] for id in row['slate'] if id in observed]
            if len(slate)!=len(row['slate']):raise ValueError('A decision precedes its observations')
            for mode,broker in brokers.items():
                if bio in pending[mode]:continue
                intent=choose(bio,slate,broker,learner,mode,rng[mode][bio],at,settings)
                if intent:
                    intent['id']=f'{seed}:{mode}:{row["id"]}'
                    pending[mode][bio]=intent
    result={}
    for mode,broker in brokers.items():
        result[mode]={}
        for bio,account in broker.accounts.items():
            public=account.public(tape['last_at'],settings['quote_max_age_seconds'])
            labels=predictions[bio]
            result[mode][bio]={'equity':public['equity'],'return_pct':public['return_pct'] if not public['valuation_stale'] else None,
                'valuation_stale':public['valuation_stale'],'max_drawdown_pct':drawdown[mode][bio]*100,
                'fees_usd':account.fees,'trades':account.trades,'open_positions':len(account.positions),
                'prediction_samples':len(labels),'prediction_mse':sum((r['predictions'][mode]-r['target'])**2 for r in labels)/len(labels) if labels else None}
    return {'seed':seed,'results':result,'learners':{k:l.summary() for k,l in learners.items()},
            'spike_tape_hashes':{k:h.hexdigest() for k,h in spikes.items()},'fills':fills}


def compare(root, tape, seeds):
    runs=[experiment(root,tape,seed) for seed in seeds]
    return {'version':VERSION,'source_run':tape['source_run'],'seeds':seeds,'first_at':tape['first_at'],'last_at':tape['last_at'],
        'observations':len(tape['observations']),'decisions':len(tape['decisions']),'experiments':runs,
        'limitations':['Conditional comparison using candidate slates and features observed by the original arena; selection is not independent.',
        'Fresh benchmark brains, learners and paper accounts; fixed source synthetic calibration, explicit neural noise seeds.',
        'No future quote can fill an earlier timestamp; the first available later matching quote is used with the same paper broker costs.',
        'Labels are delayed hypothetical outcomes; correlated samples and a short tape do not establish profitability.',
        'Recorded coverage can omit assets an alternative policy would later hold; stale ending valuations have no reported return.',
        'Fixed and momentum policies share allocation, risk, cooldown and exploration controls; this is not a replay of the production strategy.']}
