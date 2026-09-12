from collections import deque
import asyncio
import math
import time
import httpx
import numpy as np

class FeatureEncoder:
    def __init__(self, config):
        self.window=config['encoding']['window']
        self.floor=config['encoding']['return_scale_floor']
        self.prices=deque(maxlen=self.window)
        self.returns=deque(maxlen=self.window)
        self.volumes=deque(maxlen=self.window)

    def encode(self, quote):
        price=quote['price']; volume=quote['minute_volume']
        r=math.log(price/self.prices[-1]) if self.prices else 0.0
        past_std=max(self.floor,float(np.std(self.returns)) if len(self.returns)>2 else self.floor)
        z=math.tanh(r/(2*past_std))
        volume_mean=float(np.mean(self.volumes)) if self.volumes else max(volume,1)
        volume_signal=volume/(volume+max(volume_mean,1e-9))
        volatility=(float(np.std(self.returns)) if len(self.returns)>2 else 0.0)
        result={'approach':max(0.0,z),'avoid':max(0.0,-z),'volume':volume_signal,
                'volatility':volatility/(volatility+self.floor), 'log_return':r,
                'return_bps':r*10000,'past_return_std':past_std,'minute_volume':volume,
                'history_samples':len(self.prices),'input_quote_id':quote['id']}
        self.prices.append(price);self.returns.append(r);self.volumes.append(volume)
        return result

class LiveMarket:
    def __init__(self, config, on_quote):
        self.config=config
        self.on_quote=on_quote
        self.latest=None
        self.error=None
        self.changed=asyncio.Condition()
        self.request_count=0

    async def run(self):
        async with httpx.AsyncClient(timeout=7,headers={'User-Agent':'BioArena/0.1'}) as client:
            while True:
                started=time.monotonic()
                try:
                    book_response,bar_response=await asyncio.gather(
                        client.get('https://api.binance.com/api/v3/ticker/bookTicker',params={'symbol':self.config['market_symbol']}),
                        client.get('https://api.binance.com/api/v3/klines',params={'symbol':self.config['market_symbol'],'interval':'1m','limit':1}))
                    book_response.raise_for_status();bar_response.raise_for_status()
                    book,bar=book_response.json(),bar_response.json()[0]
                    bid,ask=float(book['bidPrice']),float(book['askPrice'])
                    if not all(math.isfinite(x) and x>0 for x in [bid,ask]) or bid>ask:raise ValueError('Invalid bid/ask')
                    volume=float(bar[5])
                    if not math.isfinite(volume) or volume<0:raise ValueError('Invalid volume')
                    self.request_count+=1
                    q={'id':f'binance-receipt-{time.time_ns()}-{self.request_count}','source':'Binance public REST',
                       'symbol':self.config['market_symbol'],'price':(bid+ask)/2,'bid':bid,'ask':ask,
                       'minute_volume':volume,'minute_open_ms':int(bar[0]),'received_at':time.time()}
                    self.on_quote(q)
                    async with self.changed:
                        self.latest=q;self.error=None;self.changed.notify_all()
                except asyncio.CancelledError:raise
                except Exception as e:
                    self.error=f'{type(e).__name__}: {str(e)[:200]}'
                await asyncio.sleep(max(.1,self.config['market_poll_seconds']-(time.monotonic()-started)))

    def fresh(self):
        return self.latest is not None and time.time()-self.latest['received_at']<=self.config['max_quote_age_seconds']

    async def after(self, timestamp, timeout=15):
        async with self.changed:
            await asyncio.wait_for(self.changed.wait_for(lambda:self.latest is not None and
                self.latest['received_at']>timestamp and self.fresh()),timeout)
            return dict(self.latest)
