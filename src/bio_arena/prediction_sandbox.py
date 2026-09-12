"""Offline, non-transferable test points for hourly outcome-pool experiments.

No wallet, deposits, token contract, secondary trading, or public endpoint.
"""
import hashlib
import json
from pathlib import Path
import sqlite3

from .registry import roster


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


class PredictionSandbox:
    def __init__(self,path):
        if str(path)!=':memory:':Path(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS balances(player TEXT PRIMARY KEY,points INTEGER NOT NULL CHECK(points>=0));
            CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY,player TEXT,points INTEGER);
            CREATE TABLE IF NOT EXISTS pools(id TEXT PRIMARY KEY,opening TEXT,settlement TEXT);
            CREATE TABLE IF NOT EXISTS stakes(id TEXT PRIMARY KEY,pool TEXT,player TEXT,bio TEXT,points INTEGER,payout INTEGER);
        ''')

    def grant(self,event_id,player,points):
        if not event_id or not player or type(points)!=int or not 0<points<=10**9:raise ValueError('Invalid test-point grant')
        with self.db:
            prior=self.db.execute('SELECT player,points FROM grants WHERE id=?',(event_id,)).fetchone()
            if prior:
                if prior!=(player,points):raise ValueError('Conflicting grant ID')
                return
            balance=self.balance(player)
            if balance+points>10**12:raise ValueError('Test-point account limit exceeded')
            self.db.execute('INSERT INTO grants VALUES (?,?,?)',(event_id,player,points))
            self.db.execute('INSERT INTO balances VALUES (?,?) ON CONFLICT(player) DO UPDATE SET points=points+excluded.points',(player,points))

    def balance(self,player):
        row=self.db.execute('SELECT points FROM balances WHERE player=?',(player,)).fetchone()
        return row[0] if row else 0

    def open(self,round_record):
        if round_record['status']!='open':raise ValueError('A complete open hourly round is required')
        participants=roster({'competitors':round_record['rules']['participants']})
        if len(participants)<2:raise ValueError('At least two outcomes are required')
        opening=encoded({'id':round_record['id'],'start':round_record['start'],
                         'closes_at':round_record['vote_close'],'participants':participants,
                         'rules':round_record['rules'],'opening':round_record['opening']})
        with self.db:
            prior=self.db.execute('SELECT opening FROM pools WHERE id=?',(round_record['id'],)).fetchone()
            if prior:
                if prior[0]!=opening:raise ValueError('Pool outcomes and rules are frozen')
                return
            self.db.execute('INSERT INTO pools VALUES (?,?,NULL)',(round_record['id'],opening))

    def stake(self,event_id,pool,player,bio,points,now):
        if not event_id or type(points)!=int or not 0<points<=10**9:raise ValueError('Use positive integer test points')
        with self.db:
            prior=self.db.execute('SELECT pool,player,bio,points FROM stakes WHERE id=?',(event_id,)).fetchone()
            if prior:
                if prior!=(pool,player,bio,points):raise ValueError('Conflicting stake ID')
                return
            row=self.db.execute('SELECT opening,settlement FROM pools WHERE id=?',(pool,)).fetchone()
            if not row or row[1]:raise ValueError('Pool is closed')
            opening=json.loads(row[0]);account=opening['opening']['accounts'].get(bio)
            if (not opening['start']<=now<opening['closes_at'] or bio not in opening['participants']
                    or not account or not account['alive'] or account['equity']<=0):raise ValueError('Outcome unavailable or entry window closed')
            changed=self.db.execute('UPDATE balances SET points=points-? WHERE player=? AND points>=?',(points,player,points))
            if changed.rowcount!=1:raise ValueError('Insufficient test points')
            self.db.execute('INSERT INTO stakes VALUES (?,?,?,?,?,NULL)',(event_id,pool,player,bio,points))

    def settle(self,round_record):
        if round_record['status'] not in ('settled','void'):raise ValueError('Hourly scoring has not finalized')
        pool=round_record['id'];result=round_record['result']
        evidence=encoded({'status':round_record['status'],'result':result,'closing':round_record['closing'],'reason':round_record['reason']})
        fingerprint=hashlib.sha256(evidence.encode()).hexdigest()
        with self.db:
            stored=self.db.execute('SELECT opening,settlement FROM pools WHERE id=?',(pool,)).fetchone()
            if not stored:raise ValueError('Pool not found')
            opening=json.loads(stored[0])
            if stored[1]:
                previous=json.loads(stored[1])
                if previous['evidence_sha256']!=fingerprint:raise ValueError('Settlement is immutable')
                return previous
            if opening['rules']!=round_record['rules'] or opening['opening']!=round_record['opening']:
                raise ValueError('Settlement rules or opening differ from the frozen pool')
            stakes=self.db.execute('SELECT id,player,bio,points FROM stakes WHERE pool=? ORDER BY id',(pool,)).fetchall()
            winners=(result or {}).get('winners',[])
            winner=winners[0] if round_record['status']=='settled' and result['outcome']=='winner' and len(winners)==1 else None
            if winner and winner not in opening['participants']:raise ValueError('Winner is not a frozen outcome')
            winning=[r for r in stakes if r[2]==winner]
            total=sum(r[3] for r in stakes);winning_total=sum(r[3] for r in winning)
            payouts={r[0]:0 for r in stakes}
            refund=not winner or not winning_total
            if refund:payouts={r[0]:r[3] for r in stakes}
            else:
                for row in winning:payouts[row[0]]=row[3]*total//winning_total
                remainder=total-sum(payouts.values())
                # Largest fractional remainders, then event ID, conserve every integer point.
                ordered=sorted(winning,key=lambda r:(-(r[3]*total%winning_total),r[0]))
                for row in ordered[:remainder]:payouts[row[0]]+=1
            for stake_id,player,bio,points in stakes:
                self.db.execute('UPDATE balances SET points=points+? WHERE player=?',(payouts[stake_id],player))
                self.db.execute('UPDATE stakes SET payout=? WHERE id=?',(payouts[stake_id],stake_id))
            settlement={'evidence_sha256':fingerprint,'total_points':total,'payouts':payouts,
                        'mode':'refund' if refund else 'proportional_pool','real_money':False,
                        'rules':'Tie, no loss, void, or no winning stake refunds all points; no fee'}
            self.db.execute('UPDATE pools SET settlement=? WHERE id=?',(encoded(settlement),pool))
            return settlement

    def close(self):self.db.close()
