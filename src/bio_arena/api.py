from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import os
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .arena import Arena
from .meme_arena import MemecoinArena
from .cell_connections import cell_connections

ROOT=Path(__file__).resolve().parents[2]
arena=None

@asynccontextmanager
async def lifespan(app):
    global arena
    config=yaml.safe_load(Path(os.environ.get('BIO_ARENA_CONFIG',ROOT/'configs/arena.yaml')).read_text())
    resume=os.getenv('BIO_ARENA_RESUME')
    migrate=os.getenv('BIO_ARENA_MIGRATE_LEGACY')
    if resume and migrate:raise ValueError('Choose recovery or explicit legacy migration')
    if migrate:
        from .migration import inspect_legacy
        config=inspect_legacy(ROOT,migrate)['manifest']['config']
    if resume:
        from .recovery import load_bundle
        bundle,payload=load_bundle(ROOT,resume)
        config=payload['config']
    arena=(MemecoinArena if config.get('market_source')=='fomo_trending' else Arena)(ROOT,config)
    try:
        if resume:
            from .recovery import fork_restore
            fork_restore(arena,bundle,payload)
        if migrate:
            from .migration import migrate_legacy
            migrate_legacy(arena,migrate)
        await arena.start()
        yield
    finally:
        await arena.stop()

app=FastAPI(title='Bio Arena',version='0.1.0',lifespan=lifespan)

@app.get('/api/health')
def health():return {'ok':arena.status!='error','status':arena.status,'run_id':arena.run_id}

@app.get('/api/state')
async def state():return arena.state()

@app.get('/api/connectomes')
async def connectomes():return arena.metadata

@app.get('/api/connectomes/{bio_id}/graph')
async def graph(bio_id: str):
    if bio_id not in arena.visual:raise HTTPException(404,'Unknown bio')
    return arena.visual[bio_id]

@app.get('/api/connectomes/{bio_id}/cell/{node_id}')
def cell(bio_id:str,node_id:str):
    if bio_id not in arena.metadata:raise HTTPException(404,'Unknown bio')
    result=cell_connections(bio_id,node_id)
    if result is None:raise HTTPException(404,'Cell is outside the simulated subgraph')
    return result

@app.get('/api/decisions')
async def decisions(limit:int=30):return arena.decisions(max(1,min(100,limit)))

@app.get('/api/connectomes/{bio_id}/decisions')
async def history(bio_id:str,limit:int=25,before:int|None=None):
    if bio_id not in arena.metadata:raise HTTPException(404,'Unknown bio')
    return arena.history(bio_id,max(1,min(50,limit)),before)

@app.get('/api/decisions/{decision_id}')
async def decision(decision_id: str):
    d=arena.decision(decision_id)
    if d is None:raise HTTPException(404,'Decision not found')
    return d

@app.get('/api/run/manifest')
async def manifest():return FileResponse(arena.run_dir/'manifest.json',filename=f'{arena.run_id}-manifest.json')

@app.post('/api/control/{action}')
async def control(action: str,request: Request):
    # Only the operator on this host can alter a running experiment. Remote viewers are read-only.
    if request.client.host not in ['127.0.0.1','::1','localhost']:
        raise HTTPException(403,'Remote viewers are read-only; use an SSH tunnel for controls')
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Cross-origin control is disabled')
    if action not in ['pause','resume']:raise HTTPException(400,'Use pause or resume')
    if arena.status in ['error','finished']:raise HTTPException(409,'Run has ended; restart the service for a new experiment')
    arena.paused=action=='pause'
    return {'paused':arena.paused}

@app.websocket('/ws')
async def websocket(ws: WebSocket):
    await ws.accept()
    queue=asyncio.Queue(maxsize=1)
    arena.subscribers.add(queue)
    try:
        await ws.send_json(arena.state())
        while True:
            await asyncio.wait_for(ws.send_text(await queue.get()),timeout=10)
    except (WebSocketDisconnect,RuntimeError,asyncio.TimeoutError):pass
    finally:arena.subscribers.discard(queue)

dist=ROOT/'frontend/dist'
if dist.exists():
    app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
