"""Paper execution with independent ledgers and future-quote settlement."""
from .registry import roster
from dataclasses import dataclass, asdict
import math
from typing import Protocol

class ExecutionAdapter(Protocol):
    """Future external adapters must reconcile actual fills using an idempotency key."""
    def execute(self, intent: dict, quote: dict) -> dict: ...

@dataclass
class Account:
    bio_id: str
    initial_cash: float
    cash: float
    quantity: float = 0.0
    fees: float = 0.0
    turnover: float = 0.0
    trades: int = 0
    alive: bool = True
    last_trade_ts: float = -1e30

    def equity(self, price):return self.cash+self.quantity*price

    def public(self, price):
        e=self.equity(price)
        return dict(asdict(self),equity=round(e,4),pnl=round(e-self.initial_cash,4),
                    return_pct=(e/self.initial_cash-1)*100,position_pct=self.quantity*price/max(e,1e-9)*100)

class PaperBroker:
    def __init__(self, config):
        self.config=config
        self.accounts={k:Account(k,config['initial_cash'],config['initial_cash']) for k in roster(config)}
        self.seen=set()

    def execute(self, intent, quote):
        key=intent['id']
        if key in self.seen:
            return {'status':'duplicate','intent_id':key}
        if quote['received_at']<=intent['created_at']:
            raise ValueError('Execution quote must arrive after decision completion')
        for name in ['bid','ask','price']:
            if not math.isfinite(quote[name]) or quote[name]<=0:raise ValueError('Invalid quote')
        if quote['bid']>quote['ask']:raise ValueError('Crossed quote')
        self.seen.add(key)
        a=self.accounts[intent['bio_id']]
        base={'intent_id':key,'bio_id':a.bio_id,'quote_id':quote['id'],'timestamp':quote['received_at'],
              'decision_action':intent['action'],'action':intent['action'],'quantity':0,'notional':0,'fee':0,
              'status':'held','reason':intent['reason']}
        if not a.alive:return dict(base,reason='This account has been eliminated.')
        equity=a.equity(quote['price'])
        stopped=equity<=a.initial_cash*self.config['stop_equity_fraction']
        if stopped:
            action='SELL'; quantity=a.quantity
            base.update(action=action,reason='Stop threshold reached. Position closed; account eliminated.')
            a.alive=False
        elif intent['action']=='HOLD':return base
        elif quote['received_at']-a.last_trade_ts<self.config['cooldown_seconds']:
            return dict(base,reason='Trade cooldown. The neural decision is retained.')
        else:
            action=intent['action']
            if 'target_position_fraction' in intent:
                target=intent['target_position_fraction']
                if not math.isfinite(target) or not 0<=target<=1:raise ValueError('Invalid target position')
                difference=target*equity-a.quantity*quote['price']
                value=min(equity*self.config['max_position_step'],max(0,difference if action=='BUY' else -difference))
            else:value=equity*self.config['max_position_step']*min(1,abs(intent['score']))
            quantity=value/quote['price']
        fee_rate=self.config['fee_bps']/10000
        slip=self.config['slippage_bps']/10000
        price=quote['ask']*(1+slip) if action=='BUY' else quote['bid']*(1-slip)
        quantity=min(quantity, a.cash/(price*(1+fee_rate))) if action=='BUY' else min(quantity,a.quantity)
        notional=quantity*price
        if quantity<=0 or (not stopped and notional<self.config['minimum_trade_value']):
            return dict(base,reason='Insufficient cash or position, or below the minimum order size.')
        fee=notional*fee_rate
        if action=='BUY':a.cash-=notional+fee;a.quantity+=quantity
        else:a.cash+=notional-fee;a.quantity-=quantity
        if abs(a.cash)<1e-8:a.cash=0.0
        if abs(a.quantity)<1e-12:a.quantity=0.0
        a.fees+=fee;a.turnover+=notional;a.trades+=1;a.last_trade_ts=quote['received_at']
        return dict(base,status='filled',action=action,quantity=quantity,notional=notional,fee=fee,
                    fill_price=price,cash_after=a.cash,quantity_after=a.quantity,equity_after=a.equity(quote['price']),
                    fee_bps=self.config['fee_bps'],slippage_bps=self.config['slippage_bps'])

class FomoAdapter:
    """Reserved boundary. No login, signing or live submission is implemented."""
    def execute(self, intent, quote):
        raise NotImplementedError('FOMO live execution is not connected; paper mode only')
