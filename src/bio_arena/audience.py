"""Separate audience service: reads paper equity, stores rounds and test predictions."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
import fcntl
import os
from pathlib import Path
import time

from fastapi import FastAPI, HTTPException, Request
import httpx

from .challenge import ChallengeStore, paper_snapshot
from .registry import validate_bio_id
from .voting import EvmEligibility, HoldingUnavailable, VoteSettings, evm_address


class RequestBudget:
    def __init__(self):
        self.minute, self.total, self.clients = -1, 0, OrderedDict()

    def take(self, client, now):
        minute = int(now // 60)
        if minute != self.minute:
            self.minute, self.total = minute, 0
            self.clients.clear()
        count = self.clients.get(client, 0)
        if self.total >= 60 or count >= 8:
            raise HTTPException(429, 'Too many vote attempts. Please retry in a minute.')
        self.total += 1
        self.clients[client] = count + 1


def create_app(db_path=None, settings=None, source=None, collect=True, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or VoteSettings.from_env()
        path = db_path or os.getenv('BIO_AUDIENCE_DB', '.private/audience/arena.sqlite3')
        lock = None
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = open(str(path) + '.lock', 'a')
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock.close()
                raise RuntimeError('Run only one audience worker per database') from None
        store = ChallengeStore(path)
        app.state.store, app.state.settings = store, config
        app.state.last_received, app.state.error = None, 'Waiting for account valuations'
        app.state.budget, app.state.rpc_slots = RequestBudget(), asyncio.Semaphore(2)
        async with httpx.AsyncClient(timeout=8, transport=transport) as client:
            app.state.eligibility = EvmEligibility(config, client)

            async def poll():
                url = source or os.getenv('BIO_AUDIENCE_SOURCE', 'http://127.0.0.1:8140/api/state')
                while True:
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        state = response.json()
                        # Reject live states even if an operator changes only the upstream mode.
                        if state.get('mode') != 'paper':
                            store.invalidate('Source mode changed; live cash-flow reconciliation is required')
                        snapshot = paper_snapshot(state, time.time())
                        store.observe(snapshot, config.public())
                        app.state.last_received, app.state.error = snapshot['at'], None
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        app.state.error = 'Account data unavailable or stale; settlement is waiting'
                        store.expire(time.time())
                    await asyncio.sleep(5)

            task = asyncio.create_task(poll()) if collect else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                store.close()
                if lock:
                    lock.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/challenge')
    async def overview():
        now = time.time()
        fresh = app.state.last_received is not None and now - app.state.last_received <= 20 and app.state.error is None
        return app.state.store.view(now) | {'server_time': now, 'fresh': fresh,
                'last_received': app.state.last_received, 'error': app.state.error,
                'gate': app.state.settings.public(), 'live_execution': 'not_connected',
                'rewards': 'not_enabled'}

    @app.post('/api/challenge/votes')
    async def vote(request: Request):
        app.state.budget.take(request.client.host if request.client else 'unknown', time.time())
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Send a JSON vote')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024:
                raise HTTPException(413, 'Vote request is too large')
        try:
            import json
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) != {'round_id', 'address', 'bio_id'}:
                raise ValueError('Provide a round, an EVM address and a Bio')
            address = evm_address(data['address'])
            round_id, bio = data['round_id'], data['bio_id']
            validate_bio_id(bio)
            if not isinstance(round_id, str) or len(round_id) > 160:
                raise ValueError('Invalid round or Bio')
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        store, now = app.state.store, time.time()
        store.expire(now)
        row = store.get(round_id)
        if (not row or row['status'] != 'open' or not row['start'] <= now < row['vote_close']
                or row['rules']['gate'] != app.state.settings.public()
                or bio not in row['opening']['accounts']):
            raise HTTPException(409, 'Voting is closed; wait for the next round')
        if not row['rules']['gate']['enabled']:
            raise HTTPException(403, 'Voting is not enabled')
        prior = store.prior_vote(round_id, address)
        if prior:
            if prior['bio_id'] != bio:
                raise HTTPException(409, 'This address already voted in this round; votes cannot be changed')
            return store.receipt(prior['receipt'])
        if app.state.last_received is None or now - app.state.last_received > 20 or app.state.error:
            raise HTTPException(503, 'Account data is stale; please wait before voting')
        try:
            async with asyncio.timeout(12):
                async with app.state.rpc_slots:
                    evidence = await app.state.eligibility.check(address)
            if time.time() - app.state.last_received > 20 or app.state.error:
                raise HTTPException(503, 'Account data became stale; no vote was recorded')
            if not evidence['eligible']:
                raise HTTPException(403, 'This address does not meet the token holding requirement')
            saved = store.cast(round_id, address, bio, evidence, time.time())
            return store.receipt(saved['receipt'])
        except TimeoutError:
            raise HTTPException(503, 'Holding lookup timed out; no vote was recorded') from None
        except HoldingUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get('/api/challenge/rounds/{round_id}')
    async def round_evidence(round_id: str):
        row = app.state.store.get(round_id) if len(round_id) <= 160 else None
        if row is None:
            raise HTTPException(404, 'Round not found')
        return row | {'counts': app.state.store.public_round(row)['counts']}

    @app.get('/api/challenge/receipts/{receipt}')
    async def receipt(receipt: str):
        if len(receipt) != 32:
            raise HTTPException(404, 'Receipt not found')
        record = app.state.store.receipt(receipt)
        if record is None:
            raise HTTPException(404, 'Receipt not found')
        return record

    return app


app = create_app()
