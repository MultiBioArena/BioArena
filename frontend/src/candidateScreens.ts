import type {Bio,MarketAsset} from './types';

export type CandidateScreen={asset:MarketAsset;reviewed:boolean;held:boolean;history:{time:number;price:number}[]};
type Samples={quoteId:string;pair?:string;points:{time:number;price:number}[]};

// Only received quotes are plotted. Changing pools starts a new series.
export function collectCandidatePrices(cache:Map<string,Samples>,assets:MarketAsset[]){
  const current=new Set(assets.map(a=>a.asset_id));
  for(const key of cache.keys())if(!current.has(key))cache.delete(key);
  for(const asset of assets){
    const q=asset.quote;if(!q||!asset.fresh||q.asset_id!==asset.asset_id||!Number.isFinite(q.price)||q.price<=0)continue;
    const old=cache.get(asset.asset_id);
    if(old?.quoteId===q.id)continue;
    const points=old&&old.pair===q.pair_address?old.points.slice(-59):[];
    if(points.length&&q.received_at<=points[points.length-1].time)continue;
    points.push({time:q.received_at,price:q.price});
    cache.set(asset.asset_id,{quoteId:q.id,pair:q.pair_address,points});
  }
}

export function candidateScreens(bio:Bio,assets:MarketAsset[],cache:Map<string,Samples>):CandidateScreen[]{
  const held=new Set((bio.account.positions||[]).map(p=>p.asset_id));
  const reviewed=new Set((bio.selection||[]).map(s=>s.asset_id));
  const score=(a:MarketAsset)=>(a.fresh?8:0)+(!a.entry_problem?4:0)+(!held.has(a.asset_id)?2:0)+(reviewed.has(a.asset_id)?1:0);
  const seen=new Set<string>();
  return assets.filter(a=>{if(!a.in_trending||seen.has(a.asset_id))return false;seen.add(a.asset_id);return true})
    .sort((a,b)=>score(b)-score(a)).slice(0,6)
    .map(asset=>({asset,held:held.has(asset.asset_id),reviewed:reviewed.has(asset.asset_id),history:cache.get(asset.asset_id)?.points||[]}));
}
