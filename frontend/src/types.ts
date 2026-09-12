export type KnownBioId = 'worm' | 'adult' | 'larva';
export type BioId = string;
export interface Activity {version:string;state:string;reason:string;event_id:string;started_at:number;ends_at:number|null;presentation_only:true}
export type Action = 'BUY' | 'SELL' | 'HOLD';
export interface AssetIdentity {asset_id:string;chain:string;address:string;symbol:string;url?:string}
export interface Quote {id:string; price:number; bid:number; ask:number; symbol:string; source:string; received_at:number; minute_volume:number;asset_id?:string;chain?:string;address?:string;liquidity_usd?:number;volume_5m_usd?:number;change_5m_pct?:number;pair_address?:string;quote_kind?:string}
export interface MarketAsset extends AssetIdentity {quote:Quote|null;fresh:boolean;in_trending:boolean;entry_problem:string|null}
export interface Position extends AssetIdentity {quantity:number;cost_basis:number;price:number;value:number;unrealized_pnl:number;return_pct:number;mark_stale:boolean;mark_received_at:number}
export interface Selection extends AssetIdentity {action:Action;reason:string;held:boolean;prediction_net_bps:number;neural_score:number;model_version:number;model_kind:string;exploration:boolean}
export interface Training {mode:string;samples:number;last_reward_bps:number|null;updates?:number;active_version?:number;candidate_version?:number|null;validation_samples?:number;validation_required?:number;pending_samples?:number;updated_at?:number|null;horizon_seconds?:number}
export interface Neuron {id:string; name:string; cell_type:string; index:number; role:string; channel:string|null; side:string; polarity:string}
export interface Graph {nodes:Neuron[]; edges:number[][]; sample_size:number; layout:string}
export interface OutputNeuron {id:string; name:string; spikes:number; rate_hz:number; role:string}
export interface Fill {status:string; reason:string; action?:Action; notional?:number; fee?:number; fill_price?:number; timestamp?:number;asset_id?:string;symbol?:string;execution_model?:string}
export interface Trace {
  asset?:AssetIdentity;selection?:Selection[];training?:Training;
  neural_action?:Action;
  event_sequence?:number;
  policy?:{version:string;mode:string;action:Action;neural_action:Action;reason:string;target_position_fraction:number;candidate_target_fraction:number;position_fraction:number;signal_strength:number;confirmation_count:number;context_samples:number;recent_move_bps:number;recent_range_bps:number;estimated_round_trip_cost_bps:number;prediction_net_bps?:number;model_version?:number;model_kind?:string;exploration?:boolean};
  schedule?:{started_at:number;scheduled_at:number;completed_at:number;next_at:number;interval_seconds:number};
  neural_activity?:{codec:string;neurons:number;bins:number;counts_u16:string;spike_mask_u32:string};
  id:string; bio_id:BioId; sequence:number; created_at:number; action:Action; score:number; reason:string;
  spikes:number; active_neurons:number; mean_rate_hz:number; compute_ms:number; simulated_ms:number;
  readout_rates:Record<string,number>; threshold:number; rate_floor_hz:number;
  raw_score:number; readout_calibration:{center:number;scale:number;method:string}|null;
  sample_counts:number[]; sample_v_mv:number[]; sample_size:number; raster:number[][]; raster_truncated:boolean;
  sensory:{channel:string; value:number; current_mv:number; neurons:number}[];
  features:Record<string,number>; input_quote:Quote; execution_quote:Quote|null;
  output_a:OutputNeuron[]; output_b:OutputNeuron[]; top_neurons:OutputNeuron[]; counts_sha256:string; seed:number; fill:Fill;
}
export interface Metadata {id:BioId; name:string; subtitle:string; color:string; neurons:number; edges:number; electrical_directed_edges:number; paper:string; license:string; selection:string; weight_units:string; assumptions:string[]; groups:Record<string,number>; sensory_output_reachability:Record<string,number>; mean_retained_input_fraction?:number; sources:Record<string,{url:string; sha256:string; version:string}>}
export interface Bio {id:BioId;activity?:Activity; rank:number; metadata:Metadata; telemetry:Trace|null; history:{time:number;equity:number}[];decision_clock?:{phase:string;next_at:number|null;interval_seconds:number;jitter_seconds:number};training?:Training; account:{equity:number; pnl:number; cash:number; quantity?:number; position_pct:number; fees:number; trades:number; alive:boolean; return_pct:number;positions?:Position[];position_count?:number;valuation_stale?:boolean;liquidating?:boolean};focus_asset_id?:string|null;market?:Quote|null;market_fresh?:boolean;market_history?:{time:number;price:number}[];asset_histories?:Record<string,{time:number;price:number}[]>;selection?:Selection[];max_positions?:number}
export interface ArenaState {run_id:string; status:string; paused:boolean; mode:string;market_mode?:string;assets?:MarketAsset[]; market:Quote|null; market_history?:{time:number;price:number}[]; market_fresh:boolean; market_error:string|null; error:string|null; sequence:number; server_time:number; started_at:number|null; bios:Bio[]; recent_decisions:Pick<Trace,'id'|'bio_id'|'created_at'|'action'|'score'|'spikes'|'fill'|'asset'>[]; rules:Record<string,number>; fomo:{platform:string; status:string;accounts:number;candidate_count?:number;board_observed_at?:number|null;complete_board?:boolean}}
