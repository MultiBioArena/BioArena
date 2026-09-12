"""FOMO discovery plus public DEX observations, with per-contract histories."""
import asyncio
from collections import defaultdict, deque
from datetime import datetime
import json
import math
import re
import sys
import time

import httpx

DEX_CHAINS = {'bnb': 'bsc', 'solana': 'solana', 'robinhood': 'robinhood',
              'ethereum': 'ethereum', 'base': 'base', 'arbitrum': 'arbitrum', 'monad': 'monad'}


def address_key(chain, address):
    if chain == 'solana':
        if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', address):
            raise ValueError('Invalid Solana address')
        return address
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
        raise ValueError('Invalid EVM address')
    return address.lower()


def finite(value, fallback=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def read_board(payload, now, max_age):
    if payload.get('schema') != 'bio_arena.fomo_market_snapshot.v2' or payload.get('board') != 'trending':
        raise ValueError('Unrecognized FOMO snapshot')
    observed = datetime.fromisoformat(payload['observed_at'].replace('Z', '+00:00')).timestamp()
    if not 0 <= now - observed <= max_age:
        raise ValueError('FOMO candidate snapshot is stale')
    result = {}
    for row in payload['candidates']:
        chain = row['chain']
        if chain not in DEX_CHAINS:
            continue
        address = address_key(chain, row['address'])
        asset_id = f'{chain}:{address}'
        if row['asset_id'] != asset_id:
            raise ValueError('Candidate identity mismatch')
        result[asset_id] = {'asset_id': asset_id, 'chain': chain, 'address': address,
                            'symbol': str(row['symbol'])[:32], 'url': row['url'],
                            'visible_position': row['visible_global_position'],
                            'discovered_at': observed, 'discovery': 'FOMO Trending (rendered subset)'}
    if not result:
        raise ValueError('No supported FOMO candidates')
    return observed, result


def pair_quote(asset, rows, received_at, preferred_pair=None):
    """Only baseToken prices on the requested chain are usable for this asset."""
    eligible = []
    for row in rows:
        try:
            matches = (row['chainId'] == DEX_CHAINS[asset['chain']] and
                       address_key(asset['chain'], row['baseToken']['address']) == asset['address'])
        except (KeyError, TypeError, ValueError):
            continue
        price = finite(row.get('priceUsd'))
        liquidity = finite((row.get('liquidity') or {}).get('usd'), 0)
        if matches and price and price > 0 and liquidity > 0 and row.get('pairAddress'):
            eligible.append(row)
    if not eligible:
        return None
    row = next((r for r in eligible if r['pairAddress'] == preferred_pair), None)
    if row is None:
        row = max(eligible, key=lambda r: float(r['liquidity']['usd']))
    price = float(row['priceUsd'])
    tx = (row.get('txns') or {}).get('m5') or {}
    volume = max(0, finite((row.get('volume') or {}).get('m5'), 0))
    return {**asset, 'id': f'dex:{asset["asset_id"]}:{time.time_ns()}',
            'source': 'DEX Screener public REST', 'source_market_timestamp': None,
            'received_at': received_at, 'price': price, 'bid': price, 'ask': price,
            'quote_kind': 'aggregate_reference; no executable bid/ask',
            'executable_quote': False, 'liquidity_usd': float(row['liquidity']['usd']),
            'volume_5m_usd': volume, 'minute_volume': volume / 5,
            'volume_semantics': 'rolling five-minute USD volume divided by five',
            'buys_5m': max(0, finite(tx.get('buys'), 0)),
            'sells_5m': max(0, finite(tx.get('sells'), 0)),
            'change_5m_pct': finite((row.get('priceChange') or {}).get('m5'), 0),
            'pair_address': row['pairAddress'], 'dex': row.get('dexId'),
            'pair_created_at': finite(row.get('pairCreatedAt'), 0) / 1000,
            'provider_url': row.get('url')}


class MemeMarket:
    def __init__(self, root, settings, on_quote, on_board, retained_assets):
        self.root, self.settings = root, settings
        self.on_quote, self.on_board, self.retained_assets = on_quote, on_board, retained_assets
        self.assets, self.candidates, self.quotes = {}, {}, {}
        self.histories = defaultdict(lambda: deque(maxlen=360))
        self.changed = asyncio.Condition()
        self.latest = None
        self.error = None
        self.discovery_error = None
        self.board_at = None
        self.capture = None

    def board_fresh(self, now=None):
        return self.board_at is not None and 0 <= (now or time.time()) - self.board_at <= self.settings['candidate_max_age_seconds']

    def quote_fresh(self, asset_id, now=None):
        q = self.quotes.get(asset_id)
        return q is not None and 0 <= (now or time.time()) - q['received_at'] <= self.settings['quote_max_age_seconds']

    def fresh(self):
        return any(self.quote_fresh(k) for k in self.quotes)

    async def discovery_loop(self):
        while True:
            try:
                self.capture = await asyncio.create_subprocess_exec(
                    sys.executable, str(self.root / 'scripts/capture_fomo_market.py'),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                code = await asyncio.wait_for(self.capture.wait(), 40)
                if code:
                    raise RuntimeError('FOMO browser capture needs attention')
                payload = json.loads((self.root / 'output/fomo-market-snapshot.json').read_text())
                observed, candidates = read_board(payload, time.time(), self.settings['candidate_max_age_seconds'])
                self.board_at, self.candidates = observed, candidates
                self.assets.update(candidates)
                self.on_board({'observed_at': observed, 'complete_board': False,
                               'source': payload['source'], 'candidates': list(candidates.values())})
                self.discovery_error = None
            except asyncio.CancelledError:
                if self.capture and self.capture.returncode is None:
                    self.capture.terminate()
                    await self.capture.wait()
                raise
            except Exception:
                self.discovery_error = 'FOMO discovery unavailable; new entries stop when the last board expires'
                if self.capture and self.capture.returncode is None:
                    self.capture.kill()
                    await self.capture.wait()
            await asyncio.sleep(self.settings['candidate_refresh_seconds'])

    async def run(self):
        discovery = asyncio.create_task(self.discovery_loop())
        try:
            async with httpx.AsyncClient(timeout=10, headers={'User-Agent': 'BioArena/0.2'}) as client:
                while True:
                    started = time.monotonic()
                    wanted = set(self.candidates) | set(self.retained_assets())
                    groups = defaultdict(list)
                    for key in sorted(wanted):
                        if key in self.assets:
                            groups[self.assets[key]['chain']].append(self.assets[key])
                    async def fetch(chain, assets):
                        url = 'https://api.dexscreener.com/tokens/v1/' + DEX_CHAINS[chain] + '/' + ','.join(a['address'] for a in assets)
                        response = await client.get(url)
                        response.raise_for_status()
                        rows = response.json()
                        if not isinstance(rows, list):
                            raise ValueError('Unexpected DEX response')
                        received = time.time()
                        return [q for a in assets if (q := pair_quote(a, rows, received,
                                self.quotes.get(a['asset_id'], {}).get('pair_address'))) is not None]
                    jobs = [fetch(chain, assets[i:i+30]) for chain, assets in groups.items() for i in range(0, len(assets), 30)]
                    results = await asyncio.gather(*jobs, return_exceptions=True)
                    errors = 0
                    async with self.changed:
                        for result in results:
                            if isinstance(result, Exception):
                                errors += 1
                                continue
                            for q in result:
                                key = q['asset_id']
                                previous = self.quotes.get(key)
                                q['pool_changed'] = bool(previous and previous['pair_address'] != q['pair_address'])
                                if q['pool_changed']:
                                    self.histories[key].clear()
                                self.quotes[key] = q
                                self.histories[key].append(q)
                                self.latest = q
                                self.on_quote(q)
                        self.changed.notify_all()
                    self.error = 'Some DEX feeds are unavailable; affected assets cannot trade' if errors else None
                    # Unheld, retired assets have bounded caches; active training labels retain theirs.
                    for key in set(self.assets) - wanted:
                        self.assets.pop(key, None)
                        self.quotes.pop(key, None)
                        self.histories.pop(key, None)
                    await asyncio.sleep(max(.5, self.settings['quote_poll_seconds'] - (time.monotonic() - started)))
        finally:
            discovery.cancel()
            await asyncio.gather(discovery, return_exceptions=True)

    async def after(self, asset_id, timestamp, timeout=25):
        async with self.changed:
            await asyncio.wait_for(self.changed.wait_for(lambda: self.quote_fresh(asset_id) and
                self.quotes[asset_id]['received_at'] > timestamp), timeout)
            return dict(self.quotes[asset_id])

    def entry_problem(self, key, now=None):
        now = now or time.time()
        if not self.board_fresh(now) or key not in self.candidates:
            return 'Not in a fresh FOMO candidate snapshot'
        if not self.quote_fresh(key, now):
            return 'Price observation is stale or unavailable'
        q = self.quotes[key]
        if q['liquidity_usd'] < self.settings['minimum_liquidity_usd']:
            return 'Pool liquidity is below the entry limit'
        if q['volume_5m_usd'] < self.settings['minimum_volume_5m_usd'] or min(q['buys_5m'], q['sells_5m']) < 1:
            return 'Waiting for observed two-way market activity'
        if not q['pair_created_at'] or now - q['pair_created_at'] < self.settings['minimum_pool_age_seconds']:
            return 'Pool age is unknown or below the entry limit'
        history = self.histories[key]
        if len(history) < self.settings['warmup_quotes'] or now - history[0]['received_at'] < self.settings['warmup_seconds']:
            return 'Building this token’s own market history'
        if len(history) > 1 and abs(math.log(q['price'] / history[-2]['price'])) > .4:
            return 'Large price discontinuity; waiting for another observation'
        return None
