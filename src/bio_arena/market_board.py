"""Read-only market and execution displays, independent of trading control."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import time
from typing import Literal

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from .execution_telemetry import public_snapshot

CRYPTO = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana'}
STOCKS = {'NVDA': 'NVIDIA', 'AAPL': 'Apple'}
BINANCE = 'https://data-api.binance.vision/api/v3'


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing numeric value')
    value = float(str(value).replace('$', '').replace(',', '').replace('%', ''))
    if not math.isfinite(value):
        raise ValueError('Non-finite number')
    return value


def parse_crypto(row, now):
    symbol = row['symbol'].removesuffix('USDT')
    if symbol not in CRYPTO or row['symbol'] != symbol + 'USDT':
        raise ValueError('Unexpected crypto symbol')
    price, timestamp = number(row['lastPrice']), number(row['closeTime']) / 1000
    if price <= 0 or not now - 120 <= timestamp <= now + 30:
        raise ValueError('Invalid or old quote')
    return {'symbol': symbol, 'name': CRYPTO[symbol], 'kind': 'crypto', 'currency': 'USDT',
            'price': price, 'change_pct': number(row['priceChangePercent']), 'change_period': '24H',
            'source': 'Binance', 'source_time': datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'quote_time': timestamp, 'received_at': now, 'market_state': '24/7', 'delayed': False,
            'error': None, 'history': [], 'history_label': '5 MIN PRICE BARS'}


def parse_stock(payload, symbol, now):
    data = payload.get('data') or {}
    if symbol not in STOCKS or data.get('symbol') != symbol:
        raise ValueError('Unexpected stock symbol')
    primary = data.get('primaryData') or {}
    price = number(primary.get('lastSalePrice'))
    if price <= 0 or not primary.get('lastTradeTimestamp'):
        raise ValueError('Missing stock quote')
    source_time = primary['lastTradeTimestamp']
    try:
        timestamp = datetime.strptime(source_time.removesuffix(' ET'), '%b %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
    except ValueError:
        timestamp = None  # A date-only close has no precise intraday timestamp.
    return {'symbol': symbol, 'name': STOCKS[symbol], 'kind': 'stock', 'currency': 'USD',
            'price': price, 'change_pct': number(primary.get('percentageChange')), 'change_period': 'SESSION',
            'source': 'Nasdaq', 'source_time': source_time, 'quote_time': timestamp,
            'received_at': now, 'market_state': data.get('marketStatus') or 'Unknown',
            'delayed': primary.get('isRealTime') is not True, 'error': None,
            'history': [], 'history_label': 'RECEIVED QUOTES'}


class MarketBoard:
    def __init__(self):
        self.quotes = {}
        self.next_stock = self.next_bars = 0

    def unavailable(self, symbol):
        old = self.quotes.get(symbol)
        if old:
            self.quotes[symbol] = {**old, 'error': 'Feed unavailable'}
        else:
            self.quotes[symbol] = {'symbol': symbol, 'name': (CRYPTO | STOCKS)[symbol],
                'kind': 'crypto' if symbol in CRYPTO else 'stock', 'price': None,
                'received_at': None, 'history': [], 'error': 'Feed unavailable'}

    async def crypto(self, client):
        try:
            response = await client.get(BINANCE + '/ticker/24hr', params={'symbols': '["BTCUSDT","ETHUSDT","SOLUSDT"]'})
            response.raise_for_status()
            rows = response.json()
            parsed = {q['symbol']: q for q in (parse_crypto(row, time.time()) for row in rows)}
            for symbol in CRYPTO:
                if symbol not in parsed:
                    self.unavailable(symbol)
                    continue
                parsed[symbol]['history'] = self.quotes.get(symbol, {}).get('history', [])
                self.quotes[symbol] = parsed[symbol]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            for symbol in CRYPTO:
                self.unavailable(symbol)

    async def stock(self, client, symbol):
        try:
            response = await client.get(f'https://api.nasdaq.com/api/quote/{symbol}/info', params={'assetclass': 'stocks'})
            response.raise_for_status()
            q = parse_stock(response.json(), symbol, time.time())
            old = self.quotes.get(symbol, {})
            history = old.get('history', [])[-59:]
            # A repeated closing quote is not a new market sample.
            timestamp = q['quote_time']
            if (q['market_state'].lower() != 'closed' and timestamp and 0 <= time.time() - timestamp <= 900
                    and (not history or timestamp > history[-1]['time'])):
                history = [*history, {'time': timestamp, 'price': q['price']}]
            q['history'] = history
            self.quotes[symbol] = q
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self.unavailable(symbol)

    async def bars(self, client, symbol):
        try:
            response = await client.get(BINANCE + '/klines', params={'symbol': symbol + 'USDT', 'interval': '5m', 'limit': 48})
            response.raise_for_status()
            history = [{'time': number(row[0]) / 1000, 'price': number(row[4])} for row in response.json()]
            if not history or any(p['price'] <= 0 for p in history):
                return
            if symbol in self.quotes:
                self.quotes[symbol] = {**self.quotes[symbol], 'history': history}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            pass

    async def run(self):
        async with httpx.AsyncClient(timeout=8, headers={'User-Agent': 'Mozilla/5.0 (compatible; BioArena market display)', 'Accept': 'application/json'}) as client:
            while True:
                await self.crypto(client)
                now = time.monotonic()
                jobs = []
                if now >= self.next_stock:
                    jobs.extend(self.stock(client, symbol) for symbol in STOCKS)
                    self.next_stock = now + 120
                if now >= self.next_bars:
                    jobs.extend(self.bars(client, symbol) for symbol in CRYPTO)
                    self.next_bars = now + 120
                if jobs:
                    await asyncio.gather(*jobs)
                await asyncio.sleep(15)

    def snapshot(self):
        now = time.time()
        return {'as_of': now, 'display_only': True, 'quotes': [
            {**self.quotes.get(symbol, {'symbol': symbol, 'name': (CRYPTO | STOCKS)[symbol], 'price': None, 'history': [], 'error': 'Connecting'}),
             'fresh': bool(self.quotes.get(symbol, {}).get('received_at') and
                 now - self.quotes[symbol]['received_at'] < (60 if symbol in CRYPTO else 300) and
                 not self.quotes[symbol].get('error'))}
            for symbol in [*CRYPTO, *STOCKS]]}


board = MarketBoard()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(board.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/api/market-board')
async def quotes():
    return JSONResponse(board.snapshot(), headers={'Cache-Control': 'public, max-age=10', 'X-Content-Type-Options': 'nosniff'})


@app.get('/api/execution')
def execution():
    return JSONResponse(public_snapshot(), headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


async def screen_proxy(bio=None):
    """Expose only the local collector's two display resources, never controls."""
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    path = '/api/fomo-screens' + (f'/{bio}/frame' if bio else '')
    media_type = 'image/jpeg' if bio else 'application/json'
    limit = 500_000 if bio else 100_000

    async def fetch():
        async with httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False) as client:
            async with client.stream('GET', 'http://127.0.0.1:8144' + path) as upstream:
                if upstream.status_code != 200 or upstream.headers.get('content-type', '').split(';')[0] != media_type:
                    raise ValueError('Screen unavailable')
                body = bytearray()
                async for chunk in upstream.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ValueError('Screen response too large')
                if bio:
                    timestamp = number(upstream.headers.get('x-frame-time'))
                    sequence = int(upstream.headers.get('x-frame-sequence', ''))
                    if not time.time() - 12 <= timestamp <= time.time() + 1 or sequence < 0 or not body.startswith(b'\xff\xd8'):
                        raise ValueError('Invalid screen frame')
                    headers.update({'X-Frame-Time': str(timestamp), 'X-Frame-Sequence': str(sequence)})
                return Response(bytes(body), media_type=media_type, headers=headers)

    try:
        return await asyncio.wait_for(fetch(), timeout=3)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        return JSONResponse({'error': 'Screen unavailable'}, status_code=503, headers=headers)


@app.get('/api/fomo-screens')
async def screens():
    return await screen_proxy()


@app.get('/api/fomo-screens/{bio}/frame')
async def screen_frame(bio: Literal['worm', 'adult', 'larva']):
    return await screen_proxy(bio)
