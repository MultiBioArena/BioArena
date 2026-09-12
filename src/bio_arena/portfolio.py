"""Contract-bound paper portfolios. Market prices and all costs are estimates."""
from dataclasses import asdict, dataclass, field
import math
import time
from .registry import DEFAULT_BIOS, roster


@dataclass
class Position:
    asset_id: str
    chain: str
    address: str
    symbol: str
    quantity: float
    cost_basis: float
    opened_at: float


@dataclass
class Portfolio:
    bio_id: str
    initial_cash: float
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    marks: dict = field(default_factory=dict)
    fees: float = 0.
    turnover: float = 0.
    trades: int = 0
    realized_pnl: float = 0.
    alive: bool = True
    liquidating: bool = False
    last_trade_ts: float = -1e30

    def mark(self, quotes):
        for key in self.positions:
            if key in quotes:
                self.marks[key] = dict(quotes[key])

    def equity(self):
        return self.cash + sum(p.quantity * self.marks[k]['price'] for k, p in self.positions.items())

    def public(self, now=None, max_age=30):
        now = now or time.time()
        positions = []
        for k, p in self.positions.items():
            q = self.marks[k]
            value = p.quantity * q['price']
            positions.append({**asdict(p), 'price': q['price'], 'value': value,
                              'unrealized_pnl': value - p.cost_basis,
                              'return_pct': (value / p.cost_basis - 1) * 100,
                              'mark_received_at': q['received_at'],
                              'mark_stale': not 0 <= now - q['received_at'] <= max_age})
        equity = self.equity()
        return {'bio_id': self.bio_id, 'initial_cash': self.initial_cash, 'cash': self.cash,
                'equity': equity, 'pnl': equity - self.initial_cash,
                'return_pct': (equity / self.initial_cash - 1) * 100,
                'position_pct': (equity - self.cash) / max(equity, 1e-9) * 100,
                'positions': positions, 'position_count': len(positions),
                'fees': self.fees, 'trades': self.trades, 'turnover': self.turnover,
                'realized_pnl': self.realized_pnl, 'alive': self.alive,
                'liquidating': self.liquidating, 'valuation_stale': any(p['mark_stale'] for p in positions)}


def position_limit(settings, mode):
    if mode not in ('paper', 'live'):
        raise ValueError('Unknown execution mode')
    value = settings['paper_max_positions'] if mode == 'paper' else settings['live_max_positions']
    if type(value) is not int or not 1 <= value <= (5 if mode == 'paper' else 2):
        raise ValueError('Paper supports at most five positions; live is limited to two')
    return value


def cost_bps(settings, quote, notional):
    liquidity = quote.get('liquidity_usd', 0)
    if not math.isfinite(liquidity) or liquidity <= 0:
        return None
    impact = notional / (liquidity / 2) * 10000
    gas = settings['network_cost_usd'] / max(notional, 1e-9) * 10000
    return 2 * (settings['fee_bps'] + settings['slippage_bps'] + impact + gas)


class PortfolioBroker:
    def __init__(self, initial_cash, settings, stop_fraction, mode='paper', keys=None):
        self.limit = position_limit(settings, mode)
        if mode != 'paper':
            raise ValueError('Real execution is not implemented')
        self.settings, self.stop_fraction = settings, stop_fraction
        self.accounts = {k: Portfolio(k, initial_cash, initial_cash) for k in roster({'competitors': keys if keys is not None else DEFAULT_BIOS})}
        self.seen = {}

    def mark(self, quotes):
        for account in self.accounts.values():
            account.mark(quotes)
            if account.equity() <= account.initial_cash * self.stop_fraction:
                account.liquidating = True
                if not account.positions:
                    account.alive = False

    def execute(self, intent, quote, now=None, entry_allowed=True):
        now = time.time() if now is None else now
        key = intent['id']
        if key in self.seen:
            return {**self.seen[key], 'status': 'duplicate'}
        asset = intent['asset_id']
        action = intent['action']
        account = self.accounts[intent['bio_id']]
        base = {'intent_id': key, 'bio_id': account.bio_id, 'asset_id': asset,
                'chain': quote.get('chain'), 'address': quote.get('address'),
                'symbol': quote.get('symbol'), 'quote_id': quote.get('id'),
                'timestamp': now, 'action': action, 'status': 'held',
                'notional': 0., 'quantity': 0., 'fee': 0., 'reason': intent['reason'],
                'execution_model': 'paper pool-depth estimate; not a routed or signed transaction'}

        def finish(reason=None, **values):
            result = {**base, **values}
            if reason is not None:
                result['reason'] = reason
            self.seen[key] = result
            return result

        if action not in ('BUY', 'SELL', 'HOLD'):
            return finish('Unknown action', status='rejected')
        if quote.get('asset_id') != asset:
            return finish('Execution quote belongs to a different asset', status='rejected')
        price = quote.get('price', 0)
        if not math.isfinite(price) or price <= 0 or not 0 <= now - quote['received_at'] <= self.settings['quote_max_age_seconds']:
            return finish('Execution price is stale or invalid', status='unfilled')
        if quote['received_at'] <= intent['created_at']:
            return finish('Awaiting a price observation after this decision', status='unfilled')
        if not account.alive:
            return finish('Account has exited')
        account.mark({asset: quote})
        if account.equity() <= account.initial_cash * self.stop_fraction:
            account.liquidating = True
        if action == 'HOLD':
            return finish()
        position = account.positions.get(asset)
        if action == 'SELL' and position is None:
            return finish('This account does not hold this contract')
        if action == 'BUY':
            if account.liquidating:
                return finish('Account risk exit is in progress')
            if not entry_allowed:
                return finish('Entry conditions changed before settlement')
            if account.public(now, self.settings['quote_max_age_seconds'])['valuation_stale']:
                return finish('An existing holding has a stale mark; new exposure is paused')
            if position is None and len(account.positions) >= self.limit:
                return finish('Maximum simultaneous positions reached')
        urgent = action == 'SELL' and (account.liquidating or intent.get('risk_exit', False))
        if not urgent and now - account.last_trade_ts < self.settings['trade_cooldown_seconds']:
            return finish('Waiting before the next portfolio trade')
        equity = account.equity()
        if action == 'BUY':
            fraction = intent.get('allocation_fraction', 0)
            if not math.isfinite(fraction) or not 0 < fraction <= self.settings['max_asset_fraction']:
                return finish('Invalid allocation', status='rejected')
            held_value = position.quantity * price if position else 0
            notional = min(equity * fraction,
                           equity * self.settings['max_asset_fraction'] - held_value,
                           equity * self.settings['max_total_fraction'] - (equity - account.cash))
        else:
            fraction = intent.get('sell_fraction', 1.)
            if not math.isfinite(fraction) or not 0 < fraction <= 1:
                return finish('Invalid sell fraction', status='rejected')
            notional = position.quantity * price * fraction
        liquidity, volume = quote.get('liquidity_usd', 0), quote.get('volume_5m_usd', 0)
        if not all(math.isfinite(v) and v > 0 for v in (liquidity, volume)) or quote.get('sells_5m', 0) < 1:
            return finish('No usable pool depth or recent sell activity', status='unfilled')
        capacity = min(liquidity * self.settings['max_pool_fraction'], volume * self.settings['max_volume_fraction'])
        notional = max(0, min(notional, capacity))
        fee_rate = self.settings['fee_bps'] / 10000
        gas = self.settings['network_cost_usd']
        if action == 'BUY':
            notional = min(notional, max(0, (account.cash - gas) / (1 + fee_rate)))
        impact = notional / (liquidity / 2)
        slip = self.settings['slippage_bps'] / 10000 + impact
        if slip >= .25 or notional <= 0:
            return finish('Trade cannot be represented by the paper cost model', status='unfilled')
        fill_price = price * (1 + slip if action == 'BUY' else 1 - slip)
        quantity = notional / fill_price if action == 'BUY' else min(position.quantity, notional / price)
        notional = quantity * fill_price
        # A final dust exit may be smaller than the usual minimum, but must cover costs.
        if (notional < self.settings['minimum_trade_value'] and not (action == 'SELL' and quantity >= position.quantity * (1 - 1e-10))) or notional <= gas:
            return finish('Available size is below the minimum trade value')
        fee = notional * fee_rate + gas
        realized = 0.
        if action == 'BUY':
            account.cash -= notional + fee
            if position:
                position.quantity += quantity
                position.cost_basis += notional + fee
            else:
                account.positions[asset] = Position(asset, quote['chain'], quote['address'], quote['symbol'],
                                                    quantity, notional + fee, now)
            account.marks[asset] = dict(quote)
        else:
            removed_basis = position.cost_basis * quantity / position.quantity
            realized = notional - fee - removed_basis
            account.realized_pnl += realized
            account.cash += notional - fee
            remainder = position.quantity - quantity
            if remainder <= position.quantity * 1e-10:
                del account.positions[asset]
                account.marks.pop(asset, None)
            else:
                position.quantity = remainder
                position.cost_basis -= removed_basis
        if abs(account.cash) < 1e-8:
            account.cash = 0.
        account.trades += 1
        account.fees += fee
        account.turnover += notional
        account.last_trade_ts = now
        if account.liquidating and not account.positions:
            account.alive = False
        return finish(status='filled', fill_price=fill_price, quantity=quantity, notional=notional,
                      fee=fee, network_cost_usd=gas, slippage_bps=slip * 10000,
                      fee_bps=self.settings['fee_bps'], cash_after=account.cash,
                      equity_after=account.equity(), realized_pnl=realized,
                      positions_after=len(account.positions))
