"""Hourly audience scoring, independent of trading and model training."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
import uuid

from .registry import DEFAULT_BIOS, roster, validate_bio_id

BIOS = DEFAULT_BIOS
HOUR = 3600
BOUNDARY_GRACE = 20
RULE_VERSION = 'hourly-twr-v1'


@dataclass(frozen=True)
class CapitalFlow:
    event_id: str
    at: float
    amount: float  # Positive deposit, negative withdrawal; not a trading cash movement.
    equity_before: float
    equity_after: float
    evidence: str  # Reconciled transaction / ledger reference supplied by a future adapter.


def performance(start, end, opened_at, closed_at, flows=()):
    """Link returns around externally reconciled flows; never infer deposits from P&L."""
    if closed_at < opened_at:
        raise ValueError('Closing valuation precedes the opening')
    if not all(math.isfinite(x) and x >= 0 for x in (start, end)) or start <= 0:
        raise ValueError('A funded, non-negative valuation is required')
    base, factor, net_flow, bankrupt = start, 1.0, 0.0, False
    seen, previous = set(), opened_at
    for flow in sorted(flows, key=lambda f: f.at):
        values = (flow.at, flow.amount, flow.equity_before, flow.equity_after)
        if (not all(math.isfinite(x) for x in values) or not flow.evidence
                or not flow.event_id or flow.event_id in seen
                or not previous < flow.at <= closed_at
                or min(flow.equity_before, flow.equity_after) < 0
                or not math.isclose(flow.equity_before + flow.amount, flow.equity_after,
                                    rel_tol=0, abs_tol=0.000001)):
            raise ValueError('Incomplete or inconsistent capital-flow evidence')
        seen.add(flow.event_id)
        previous = flow.at
        net_flow += flow.amount
        if not bankrupt:
            if base <= 0:
                raise ValueError('Capital was fully withdrawn; wait for a new funded round')
            factor *= flow.equity_before / base
            bankrupt = flow.equity_before == 0
        base = flow.equity_after
    if not bankrupt:
        if base <= 0:
            raise ValueError('Capital was fully withdrawn; wait for a new funded round')
        factor *= end / base
        bankrupt = end == 0
    return {'return_pct': (factor - 1) * 100, 'pnl_usd': end - start - net_flow,
            'net_flow_usd': net_flow, 'bankrupt': bankrupt}


def score(opening, closing, flows=None):
    flows = flows or {}
    results = []
    participants = roster({'competitors': list(opening['accounts'])})
    if not set(participants).issubset(closing['accounts']):
        raise ValueError('A frozen participant valuation is missing')
    for bio in participants:
        first, last = opening['accounts'][bio], closing['accounts'][bio]
        row = {'bio_id': bio, 'start_equity': first['equity'], 'end_equity': last['equity'],
               'eligible': first['alive'] and first['equity'] > 0, 'return_pct': None,
               'pnl_usd': None, 'net_flow_usd': 0, 'bankrupt': False}
        if row['eligible']:
            row.update(performance(first['equity'], last['equity'], opening['at'],
                                   closing['at'], flows.get(bio, ())))
        results.append(row)
    ranked = [r for r in results if r['eligible']]
    # One-millionth of a percentage point is the published tie precision.
    worst = min((round(r['return_pct'], 6) for r in ranked), default=0)
    winners = [r['bio_id'] for r in ranked if round(r['return_pct'], 6) == worst]
    outcome = 'insufficient_participants' if len(ranked) < 2 else 'no_loss' if worst >= 0 else 'tie' if len(winners) > 1 else 'winner'
    return {'rows': results, 'winners': winners if outcome in ('winner', 'tie') else [],
            'outcome': outcome}


def paper_snapshot(state, now):
    """Current adapter accepts only the existing paper ledger, which has no transfers."""
    if state.get('mode') != 'paper':
        raise ValueError('Live valuation and capital-flow reconciliation are not connected')
    cash_only = bool(state.get('bios')) and all(
        not b['account'].get('positions') and b['account'].get('cash') == b['account'].get('equity')
        for b in state['bios'])
    valid_status = state.get('status') == 'running' or (state.get('status') == 'finished' and cash_only)
    if (not valid_status or state.get('paused')
            or not (state.get('market_fresh') or cash_only) or not state.get('run_id')
            or not math.isfinite(state.get('server_time', float('nan')))
            or not -2 <= now - state['server_time'] <= 10):
        raise ValueError('Waiting for a fresh running arena')
    accounts = {}
    for bio in state['bios']:
        validate_bio_id(bio['id'])
        if bio['id'] in accounts:
            raise ValueError('Unexpected account set')
        account = bio['account']
        equity = account['equity']
        if (not isinstance(equity, (int, float)) or not math.isfinite(equity) or equity < 0
                or account.get('valuation_stale')
                or any(p.get('mark_stale', True) for p in account.get('positions', []))):
            raise ValueError('Waiting for fresh account valuations')
        accounts[bio['id']] = {'equity': equity, 'alive': bool(account['alive'])}
    expected = roster({'competitors': state.get('competitors', list(BIOS))})
    if set(accounts) != set(expected):
        raise ValueError('All registered account valuations are required')
    return {'run_id': state['run_id'], 'at': now, 'source_at': state['server_time'],
            'sequence': state['sequence'], 'accounts': accounts, 'capital_flows': []}


class ChallengeStore:
    def __init__(self, path, flow_provider=None):
        self.flow_provider=flow_provider
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS rounds (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, start INTEGER NOT NULL,
                end INTEGER NOT NULL, vote_close INTEGER NOT NULL, status TEXT NOT NULL,
                rules TEXT NOT NULL, opening TEXT, latest TEXT, closing TEXT,
                result TEXT, reason TEXT, UNIQUE(run_id,start)
            );
            CREATE INDEX IF NOT EXISTS rounds_by_start ON rounds(start DESC);
            CREATE TABLE IF NOT EXISTS votes (
                receipt TEXT PRIMARY KEY, round_id TEXT NOT NULL REFERENCES rounds(id),
                address TEXT NOT NULL COLLATE NOCASE, bio_id TEXT NOT NULL, created_at REAL NOT NULL,
                eligibility TEXT NOT NULL, UNIQUE(round_id,address)
            );
        ''')

    def interval_score(self, opening, closing):
        flows=None
        if self.flow_provider:
            flows={bio:self.flow_provider.for_interval(bio,opening['at'],closing['at']) for bio in opening['accounts']}
            closing['capital_flows']=[{'bio_id':bio,**flow.__dict__} for bio,rows in flows.items() for flow in rows]
        elif closing.get('capital_flows'):
            raise ValueError('Capital-flow snapshots require a reconciled local provider')
        return score(opening,closing,flows)

    def close(self):
        self.db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        row = dict(row)
        for field in ('rules', 'opening', 'latest', 'closing', 'result'):
            row[field] = json.loads(row[field]) if row[field] else None
        return row

    def get(self, round_id):
        return self.decode(self.db.execute('SELECT * FROM rounds WHERE id=?', (round_id,)).fetchone())

    def invalidate(self, reason):
        with self.db:
            self.db.execute("UPDATE rounds SET status='void', reason=? WHERE status='open'", (reason,))

    def expire(self, now):
        with self.db:
            self.db.execute("UPDATE rounds SET status='void', reason='Missing a fresh closing boundary' WHERE status='open' AND end+?<?", (BOUNDARY_GRACE, now))

    def observe(self, snapshot, gate):
        now, run_id = snapshot['at'], snapshot['run_id']
        start = int(now // HOUR) * HOUR
        self.expire(now)
        with self.db:
            self.db.execute("UPDATE rounds SET status='void', reason='Arena run changed during the round' WHERE status='open' AND run_id!=?", (run_id,))
            for record in self.db.execute("SELECT * FROM rounds WHERE status='open' AND end<=?", (now,)).fetchall():
                row = self.decode(record)
                if row['run_id'] == run_id and row['end'] + BOUNDARY_GRACE >= now:
                    if not set(row['opening']['accounts']).issubset(snapshot['accounts']):
                        self.db.execute("UPDATE rounds SET status='void', reason='A frozen participant valuation is missing' WHERE id=?", (row['id'],))
                        continue
                    try:
                        result = self.interval_score(row['opening'], snapshot)
                    except ValueError:
                        self.db.execute("UPDATE rounds SET status='void', reason='Capital-flow evidence incomplete or inconsistent' WHERE id=?",(row['id'],))
                        continue
                    self.db.execute("UPDATE rounds SET status='settled', closing=?, latest=?, result=? WHERE id=? AND status='open'",
                                    (json.dumps(snapshot), json.dumps(snapshot), json.dumps(result), row['id']))
            round_id = f'paper:{run_id}:{start}'
            if self.get(round_id) is None:
                full = now - start <= BOUNDARY_GRACE
                rules = {'version': RULE_VERSION, 'mode': 'paper', 'metric': 'time_weighted_return_pct',
                         'boundary_grace_seconds': BOUNDARY_GRACE, 'tie_decimals': 6,
                         'vote_window_seconds': 900, 'gate': gate, 'rewards': 'not_enabled',
                         'participants': list(snapshot['accounts'])}
                self.db.execute('INSERT INTO rounds VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                (round_id, run_id, start, start + HOUR, start + 900,
                                 'open' if full else 'warmup', json.dumps(rules),
                                 json.dumps(snapshot) if full else None, json.dumps(snapshot), None, None,
                                 None if full else 'Collection began after the opening boundary; starts next UTC hour'))
            self.db.execute("UPDATE rounds SET latest=? WHERE id=? AND status IN ('open','warmup')", (json.dumps(snapshot), round_id))

    def public_round(self, row):
        if row is None:
            return None
        participants = row['rules'].get('participants', list(BIOS))
        counts = {bio: 0 for bio in participants}
        for item in self.db.execute('SELECT bio_id,COUNT(*) AS n FROM votes WHERE round_id=? GROUP BY bio_id', (row['id'],)):
            counts[item['bio_id']] = item['n']
        result = row['result']
        if row['status'] == 'open' and row['opening'] and row['latest']:
            if set(row['opening']['accounts']).issubset(row['latest']['accounts']):
                try:result = self.interval_score(row['opening'], row['latest'])
                except ValueError:result = None
        return {key: row[key] for key in ('id', 'start', 'end', 'vote_close', 'status', 'rules', 'reason')} | {
            'result': result, 'counts': counts,
            'opening_at': row['opening']['at'] if row['opening'] else None,
            'closing_at': row['closing']['at'] if row['closing'] else None,
            'latest_at': row['latest']['at'] if row['latest'] else None}

    def view(self, now):
        self.expire(now)
        rows = [self.decode(r) for r in self.db.execute('SELECT * FROM rounds ORDER BY start DESC,rowid DESC LIMIT 7')]
        current = rows[0] if rows and rows[0]['end'] + BOUNDARY_GRACE >= now else None
        return {'current': self.public_round(current),
                'history': [self.public_round(r) for r in rows if r != current and r['status'] in ('settled', 'void')][:6]}

    def prior_vote(self, round_id, address):
        return self.db.execute('SELECT * FROM votes WHERE round_id=? AND address=?', (round_id, address)).fetchone()

    def cast(self, round_id, address, bio, evidence, now):
        with self.db:
            row = self.get(round_id)
            if (not row or row['status'] != 'open' or not row['start'] <= now < row['vote_close']
                    or bio not in row['opening']['accounts'] or not row['opening']['accounts'][bio]['alive']
                    or row['opening']['accounts'][bio]['equity'] <= 0):
                raise ValueError('Voting is closed or this Bio is not participating')
            if (not row['rules']['gate']['enabled'] or not evidence.get('eligible')
                    or evidence.get('address') != address or evidence.get('token') != row['rules']['gate']['token']
                    or evidence.get('chain_id') != row['rules']['gate']['chain_id']
                    or (row['rules']['gate']['mode'] == 'token_holder' and not evidence.get('holdings_verified'))
                    or not 0 <= now - evidence.get('checked_at', 0) <= 30):
                raise ValueError('Fresh holding evidence is required')
            # The unique constraint, not a browser flag, makes retries and parallel votes idempotent.
            receipt = uuid.uuid4().hex
            self.db.execute('INSERT OR IGNORE INTO votes VALUES (?,?,?,?,?,?)',
                            (receipt, round_id, address, bio, now, json.dumps(evidence)))
            saved = self.prior_vote(round_id, address)
            if saved['bio_id'] != bio:
                raise ValueError('This address already voted in this round; votes cannot be changed')
            return dict(saved)

    def receipt(self, receipt):
        vote = self.db.execute('SELECT * FROM votes WHERE receipt=?', (receipt,)).fetchone()
        if vote is None:
            return None
        row = self.get(vote['round_id'])
        status = 'pending'
        if row['status'] == 'void':
            status = 'void'
        elif row['status'] == 'settled':
            outcome = row['result']['outcome']
            status = ('correct' if vote['bio_id'] in row['result']['winners'] else 'incorrect') if outcome == 'winner' else outcome
        return {'receipt': receipt, 'round_id': vote['round_id'], 'bio_id': vote['bio_id'],
                'created_at': vote['created_at'], 'prediction_status': status,
                'address_hint': vote['address'][:4] + '…' + vote['address'][-4:],
                'ownership_verified': False, 'rewards': 'not_enabled'}
