import type {BioId,Trace} from './types';

export interface NeuralPoint {id:string;name:string;type:string;index:number;position:[number,number,number];region:string;side:string;axis?:number;pair_id?:number;source_position_um?:number[]}
export interface NeuralGeometry {bio_id:BioId;version:string;method:string;source:string;details:Record<string,unknown>;points:NeuralPoint[];simulated_neurons:number;located_simulated:number;displayed_points:number}
export interface CellConnections {node:{id:string};connections:{partner_id:string;direction:string;weight:number;sign:number}[];total_connections:number;shown_connections:number;scope:string}

export function decodeActivity(trace:Trace|null){
  const data=trace?.neural_activity;if(!data)return null;
  try{
  const countsBytes=Uint8Array.from(atob(data.counts_u16),c=>c.charCodeAt(0));
  const maskBytes=Uint8Array.from(atob(data.spike_mask_u32),c=>c.charCodeAt(0));
  if(data.codec!=='base64-le'||data.bins!==20||countsBytes.length!==data.neurons*2||maskBytes.length!==data.neurons*4)return null;
  const countsView=new DataView(countsBytes.buffer),maskView=new DataView(maskBytes.buffer);
  const counts=new Uint16Array(data.neurons),masks=new Uint32Array(data.neurons);
  for(let i=0;i<data.neurons;i++){counts[i]=countsView.getUint16(i*2,true);masks[i]=maskView.getUint32(i*4,true)}
  return{counts,masks};
  }catch{return null}
}
