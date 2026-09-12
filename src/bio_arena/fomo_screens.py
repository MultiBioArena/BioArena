"""Image-only browser observations, isolated from the execution service."""
import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from .execution_telemetry import public_snapshot
from .fomo_networks import NETWORKS, valid_token_path

BIOS = ('worm', 'adult', 'larva')
STATES = {'private_page', 'page_loading', 'unsupported_layout', 'unavailable'}
MAX_AGE = 12
CAPTURE = Path(__file__).with_name('fomo_screen_capture.js').read_text()


def jpeg_dimensions(data):
    offset=2
    while offset+4 <= len(data):
        if data[offset]!=255:break
        while offset<len(data) and data[offset]==255:offset+=1
        if offset>=len(data):break
        marker=data[offset];offset+=1
        if marker in (0xDA,0xD9):break
        if offset+2>len(data):break
        length=int.from_bytes(data[offset:offset+2],'big')
        if length<2 or offset+length>len(data):break
        if marker in (0xC0,0xC1,0xC2):
            if length<8:break
            return int.from_bytes(data[offset+5:offset+7],'big'),int.from_bytes(data[offset+3:offset+5],'big')
        offset+=length
    raise ValueError('Image dimensions unavailable')


async def stop_process(proc):
    if proc.returncode is None:
        with suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
        await proc.wait()


def validate_frame(frame, now):
    if frame.get('state') != 'live':
        return None
    if not valid_token_path(frame.get('path')):
        raise ValueError('Invalid page')
    timestamp = frame.get('captured_at')
    if type(timestamp) not in (int, float) or not 0 <= now-timestamp <= MAX_AGE:
        raise ValueError('Expired frame')
    clip, mask = frame['clip'], frame['mask']
    for box in (clip, mask):
        if not all(type(box.get(k)) is int and 0 <= box[k] <= 4096 for k in ('x','y','width','height')):
            raise ValueError('Invalid crop')
    if not 250 <= clip['width'] <= 2000 or not 200 <= clip['height'] <= 1000:
        raise ValueError('Unsupported dimensions')
    if mask['x']+mask['width'] > clip['width'] or mask['y']+mask['height'] > clip['height']:
        raise ValueError('Mask outside frame')
    if not isinstance(frame.get('jpeg'), str) or len(frame['jpeg']) > 4_000_000:
        raise ValueError('Invalid image')
    data = base64.b64decode(frame['jpeg'], validate=True)
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('Invalid JPEG')
    if jpeg_dimensions(data)!=(clip['width'],clip['height']):
        raise ValueError('Screenshot scale does not match the privacy mask')
    return data


async def render_frame(frame, data):
    mask = frame['mask']
    filters = []
    if mask['width'] and mask['height']:
        filters.append('drawbox=x={x}:y={y}:w={width}:h={height}:color=0x0b1014:t=fill'.format(**mask))
    filters += ['scale=960:540:force_original_aspect_ratio=decrease',
                'pad=960:540:(ow-iw)/2:(oh-ih)/2:color=0x0b1014']
    proc = await asyncio.create_subprocess_exec('ffmpeg','-hide_banner','-loglevel','error',
        '-threads','1','-f','image2pipe','-i','pipe:0','-vf',','.join(filters),
        '-frames:v','1','-threads','1','-q:v','5','-f','image2pipe','-vcodec','mjpeg','pipe:1',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
    try:
        out,_ = await asyncio.wait_for(proc.communicate(data),5)
        if proc.returncode or not out:
            raise ValueError('Image processing failed')
        return out
    finally:
        await stop_process(proc)


@dataclass
class Screen:
    state: str = 'unavailable'
    image: bytes | None = None
    captured_at: float = 0
    sequence: int = 0
    path: str | None = None

    def public(self, now):
        fresh = self.state == 'live' and self.image is not None and 0 <= now-self.captured_at <= MAX_AGE
        return {'state':'live' if fresh else 'stale' if self.state=='live' else self.state,
                'captured_at':self.captured_at if fresh else None,
                'sequence':self.sequence,'page_path':self.path if fresh else None}


class ScreenFeed:
    def __init__(self, config=None):
        self.config = config or {}
        self.screens = {bio:Screen() for bio in BIOS}

    async def capture(self, bio, account):
        wrapper=self.config['wrapper']
        proc = await asyncio.create_subprocess_exec('bash',wrapper,'run-code',
            'async page => await '+CAPTURE+'(page,'+json.dumps(list(NETWORKS))+')',cwd=account['browser_directory'],
            env={**os.environ,'PLAYWRIGHT_CLI_SESSION':account['session']},
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
        try:
            output,_ = await asyncio.wait_for(proc.communicate(),10)
            text=output.decode(); marker='### Result\n'
            if proc.returncode or marker not in text:
                raise ValueError('Capture unavailable')
            frame,_=json.JSONDecoder().raw_decode(text.split(marker,1)[1].lstrip())
            data=validate_frame(frame,time.time())
            old=self.screens[bio]
            if data is None:
                self.screens[bio]=Screen(state=frame.get('state') if frame.get('state') in STATES else 'unavailable',sequence=old.sequence+1)
                return
            image=await render_frame(frame,data)
            if time.time()-frame['captured_at'] > MAX_AGE:
                raise ValueError('Capture expired')
            self.screens[bio]=Screen('live',image,frame['captured_at'],old.sequence+1,frame['path'])
        finally:
            await stop_process(proc)

    async def worker(self,bio,account):
        while True:
            try:
                await self.capture(bio,account)
            except (OSError,ValueError,KeyError,TypeError,asyncio.TimeoutError):
                self.screens[bio]=Screen(sequence=self.screens[bio].sequence+1)
            await asyncio.sleep(2)


def create_app(feed=None):
    @asynccontextmanager
    async def lifespan(app):
        if feed is None:
            config=json.loads(Path(os.environ['BIO_FOMO_SCREENS_CONFIG']).read_text())
            app.state.feed=ScreenFeed(config)
            tasks=[asyncio.create_task(app.state.feed.worker(bio,a)) for bio,a in config['accounts'].items() if bio in BIOS]
        else:
            app.state.feed=feed
            tasks=[]
        try:
            yield
        finally:
            for task in tasks:task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):await task

    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
        return response

    @app.get('/api/fomo-screens')
    async def metadata():
        now=time.time()
        execution=public_snapshot(now=now)
        screens={bio:s.public(now) for bio,s in app.state.feed.screens.items()}
        for bio,screen in screens.items():
            account=next((a for a in execution['bios'] if a['bio_id']==bio),{})
            order=next((r for r in execution['orders'] if r['bio_id']==bio),None)
            screen['execution']={'fresh':execution['fresh'],'running':execution['running'] and account.get('selected',False),
                'phase':account.get('phase','not_enabled'),
                'order':{k:order[k] for k in ('action','status','at','source_kind','balance_verified')} if order else None}
        return JSONResponse({'as_of':now,'refresh_seconds':2,'max_age_seconds':MAX_AGE,
            'screens':screens})

    @app.get('/api/fomo-screens/{bio}/frame')
    async def frame(bio:str):
        screen=app.state.feed.screens.get(bio)
        if screen is None:raise HTTPException(404,'Unknown screen')
        if screen.public(time.time())['state']!='live':raise HTTPException(503,'Screen unavailable')
        return Response(screen.image,media_type='image/jpeg',headers={'X-Frame-Time':str(screen.captured_at),'X-Frame-Sequence':str(screen.sequence)})

    return app


app=create_app()
