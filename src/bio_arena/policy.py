"""A transparent paper-policy baseline, with delayed outcomes for later training."""
from collections import deque
import math


class OpportunityPolicy:
    VERSION='opportunity-v1'

    def __init__(self,config):
        self.config=config;self.settings=config['opportunity_policy']
        self.prices=deque(maxlen=self.settings['history_steps'])
        self.last_signal='HOLD';self.streak=0
        self.pending=None;self.peak=config['initial_cash'];self.samples=0;self.last_reward=None

    def decide(self,neural,quote,account):
        self.prices.append(quote['price'])
        signal=neural['action'];strength=abs(neural['score'])
        self.streak=self.streak+1 if signal==self.last_signal else 1;self.last_signal=signal
        equity=account.equity(quote['price'])
        position=account.quantity*quote['price']/max(equity,1e-9)
        target=self.settings['max_position_fraction']*max(0,neural['score'])
        trend=math.log(self.prices[-1]/self.prices[0])*10000
        recent_range=(max(self.prices)/min(self.prices)-1)*10000
        spread=(quote['ask']-quote['bid'])/quote['price']*10000
        costs=2*(self.config['fee_bps']+self.config['slippage_bps'])+spread
        reason=None
        if len(self.prices)<self.settings['history_steps']:reason='Building market context'
        elif signal=='HOLD' or strength<self.settings['minimum_signal']:reason='Neural signal is too weak'
        elif self.streak<self.settings['confirmation_steps']:reason='Waiting for repeated neural confirmation'
        elif abs(target-position)<self.settings['rebalance_band']:reason='Position is already near the target'
        elif signal=='BUY' and target<=position:reason='Current exposure already covers this signal'
        elif signal=='SELL' and account.quantity<=0:reason='No position to reduce'
        elif quote['received_at']-account.last_trade_ts<self.config['cooldown_seconds']:reason='Waiting before the next rebalance'
        elif signal=='BUY' and trend<=0:reason='Waiting for market direction to agree'
        elif signal=='BUY' and recent_range<costs*self.settings['cost_buffer']:reason='Recent price range is too small relative to trading costs'
        action='HOLD' if reason else signal
        return {'version':self.VERSION,'mode':'collecting','action':action,'neural_action':signal,
                'reason':reason or ('Increase exposure toward the target' if signal=='BUY' else 'Reduce exposure toward the target'),
                'target_position_fraction':position if reason else target,
                'candidate_target_fraction':target,'position_fraction':position,
                'signal_strength':strength,'confirmation_count':self.streak,'context_samples':len(self.prices),
                'recent_move_bps':trend,'recent_range_bps':recent_range,'estimated_round_trip_cost_bps':costs,
                'edge_model':'untrained; historical range is a filter, not a return forecast'}

    def observe(self,account,quote):
        equity=account.equity(quote['price']);self.peak=max(self.peak,equity)
        drawdown=1-equity/max(self.peak,1e-9)
        previous=self.pending
        if previous is None:return None
        net_bps=(equity/previous['equity_before']-1)*10000
        penalty=self.settings['drawdown_penalty']*max(0,drawdown-previous['drawdown_before'])*10000
        sample={**previous,'next_quote_id':quote['id'],'observed_at':quote['received_at'],
                'equity_after':equity,'net_return_bps':net_bps,'drawdown_penalty_bps':penalty,
                'reward_bps':net_bps-penalty,'holding_seconds':quote['received_at']-previous['observed_at'],
                'market_return_bps':(quote['price']/previous['price_before']-1)*10000,
                'terminal':not account.alive}
        self.pending=None;self.samples+=1;self.last_reward=sample['reward_bps']
        return sample

    def remember(self,decision_id,bio,policy,features,neural,account,quote):
        equity=account.equity(quote['price']);self.peak=max(self.peak,equity)
        self.pending={'decision_id':decision_id,'bio_id':bio,'policy_version':self.VERSION,
            'action':policy['action'],'target_position_fraction':policy['target_position_fraction'],
            'neural_score':neural['score'],'readout_rates':neural['readout_rates'],'features':features,
            'input_quote_id':quote['id'],'observed_at':quote['received_at'],'price_before':quote['price'],
            'equity_before':equity,'drawdown_before':1-equity/max(self.peak,1e-9),
            'position_fraction_before':account.quantity*quote['price']/max(equity,1e-9),
            'cash_before':account.cash,'quantity_before':account.quantity,
            'behavior':'deterministic opportunity filter; no exploration or online weight updates'}

    def summary(self):
        return {'mode':'collecting','policy_version':self.VERSION,'samples':self.samples,'last_reward_bps':self.last_reward}
