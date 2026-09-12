import type {Bio,MarketAsset,Quote} from './types';

export function tokenPrice(value:number){
  if(value===0)return '0.00';
  if(value>=1)return value.toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2});
  if(value>=.000001)return value.toLocaleString('en-US',{maximumSignificantDigits:5});
  return value.toExponential(3);
}

export function deskMarket(bio:Bio,assets:MarketAsset[],pin:string|undefined,eventAsset:string|undefined){
  const positions=bio.account.positions||[];
  const focus=bio.focus_asset_id||undefined;
  const selected=eventAsset||(pin&&positions.some(p=>p.asset_id===pin)?pin:undefined)
    ||(positions.some(p=>p.asset_id===focus)?focus:positions[0]?.asset_id)||focus;
  const asset=assets.find(a=>a.asset_id===selected);
  const position=positions.find(p=>p.asset_id===selected);
  const traceQuote=bio.telemetry?.input_quote;
  const quote:Quote|null=asset?.quote||(bio.market?.asset_id===selected?bio.market:null)
    ||(traceQuote?.asset_id===selected?traceQuote:null)||null;
  return {quote,positions,position,selected,history:selected?bio.asset_histories?.[selected]||[]:[],fresh:!!asset?.fresh};
}
