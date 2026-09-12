"""Replay every observed candidate through LIF, and audit recorded portfolio fills."""
import argparse
import json
from pathlib import Path
import sqlite3

import yaml

from bio_arena.market import FeatureEncoder
from bio_arena.portfolio import PortfolioBroker
from bio_arena.simulation import Brain
from bio_arena.registry import roster


def replay(root, run, observations):
    folder = root / 'runs' / run
    config = yaml.safe_load((folder / 'arena.yaml').read_text())
    if config.get('market_source') != 'fomo_trending':
        raise ValueError('Use scripts/replay.py for SOL baseline runs')
    db = sqlite3.connect(f'file:{folder}/events.sqlite?mode=ro', uri=True)
    counts = {}
    for bio in roster(config):
        brain = Brain(root, bio, config)
        encoders, pairs = {}, {}
        rows = db.execute('SELECT payload FROM observations WHERE bio_id=? ORDER BY ts,id LIMIT ?',
                          (bio, observations)).fetchall()
        for (payload,) in rows:
            row = json.loads(payload)
            quote = row['input_quote']
            key = quote['asset_id']
            if pairs.get(key) != quote['pair_address']:
                pairs[key] = quote['pair_address']
                encoders[key] = FeatureEncoder(config)
            features = encoders[key].encode(quote)
            assert features == row['features'], f'Feature mismatch: {row["id"]}'
            result = brain.step(features)
            assert result['sequence'] == row['brain_sequence']
            assert result['counts_sha256'] == row['counts_sha256'], f'Spike mismatch: {row["id"]}'
            assert result['score'] == row['neural_score']
            assert result['readout_rates'] == row['readout_rates']
        counts[bio] = len(rows)
    broker = PortfolioBroker(config['initial_cash'], config['memecoin'], config['stop_equity_fraction'], keys=roster(config))
    quotes = iter(json.loads(line) for line in (folder / 'market.jsonl').read_text().splitlines())
    current = next(quotes, None)
    fills = 0
    # The arena runs one decision/settlement at a time. Replay public marks up to
    # each fill before applying that contract's recorded intent and later quote.
    for (payload,) in db.execute('SELECT payload FROM decisions ORDER BY seq'):
        record = json.loads(payload)
        fill = record['fill']
        if fill['status'] != 'filled':
            continue
        while current and current['received_at'] <= fill['timestamp']:
            broker.mark({current['asset_id']: current})
            current = next(quotes, None)
        actual = broker.execute(record['intent'], record['execution_quote'], now=fill['timestamp'])
        for field in ('status', 'asset_id', 'action', 'quantity', 'notional', 'fee', 'fill_price', 'cash_after', 'equity_after'):
            assert actual[field] == fill[field], f'Fill mismatch {record["id"]}: {field}'
        fills += 1
    db.close()
    return {'run_id': run, 'neural_observations_verified': counts, 'fills_verified': fills,
            'scope': 'Per-token encoding, all preceding LIF observations in each selected prefix, exact filled ledger arithmetic; not a strategy profit backtest'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--observations', type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(replay(Path(__file__).resolve().parents[1], args.run, args.observations)))
