import type {BioId,Activity} from './types';
export type Placement={x:number;y:number;z:number;yaw:number};
export type DeskMotion=Placement&{home:boolean;state:'at-desk'|'wandering'|'flying'|'perched'|'returning';airborne:number};
const home:Placement={x:0,y:0,z:0,yaw:0};
const smooth=(n:number)=>{const t=Math.max(0,Math.min(1,n));return t*t*(3-2*t)};
const mix=(a:Placement,b:Placement,t:number):Placement=>{
  const k=smooth(t),angle=((b.yaw-a.yaw+Math.PI)%(Math.PI*2)+Math.PI*2)%(Math.PI*2)-Math.PI;
  return {x:a.x+(b.x-a.x)*k,y:a.y+(b.y-a.y)*k,z:a.z+(b.z-a.z)*k,yaw:a.yaw+angle*k};
};
type Stop={at:number;p:Placement;state:DeskMotion['state']};
const p=(x:number,y:number,z:number,yaw=0):Placement=>({x,y,z,yaw});
const routes:Record<BioId,Stop[]>={
  worm:[{at:0,p:home,state:'wandering'},{at:4,p:p(-.45,0,-.03,.42),state:'wandering'},{at:8,p:p(-.56,0,-.06,.15),state:'wandering'},{at:12,p:p(.25,0,-.04,-.3),state:'wandering'},{at:17,p:home,state:'at-desk'}],
  larva:[{at:0,p:home,state:'wandering'},{at:5,p:p(.43,0,-.1,-.3),state:'wandering'},{at:10,p:p(.51,0,-.11,-.12),state:'wandering'},{at:15,p:p(-.22,0,-.07,.25),state:'wandering'},{at:21,p:home,state:'at-desk'}],
  adult:[{at:0,p:home,state:'flying'},{at:2,p:p(0,.9,.3,1.1),state:'flying'},{at:6,p:p(-3.7,1.7,.15,1.1),state:'flying'},
    {at:9,p:p(-3.7,1.3,-1.3,0),state:'perched'},{at:13,p:p(-3.7,1.3,-1.3,0),state:'flying'},
    {at:15,p:p(-3.3,1.8,.2,-1.2),state:'flying'},{at:20,p:p(3.7,1.8,.2,-1.2),state:'flying'},
    {at:23,p:p(3.7,1.3,-1.3,0),state:'perched'},{at:27,p:p(3.7,1.3,-1.3,0),state:'flying'},
    {at:29,p:p(3.2,1.8,.2,1.2),state:'flying'},{at:32,p:p(0,.8,.2,0),state:'flying'},{at:34,p:home,state:'at-desk'}]
};
function sample(route:Stop[],time:number){
  for(let i=1;i<route.length;i++)if(time<route[i].at){const a=route[i-1],b=route[i];return {...mix(a.p,b.p,(time-a.at)/(b.at-a.at)),state:a.state}}
  return {...home,state:'at-desk' as const};
}

export function createDeskMotion(id:BioId){
  let epoch:number|undefined,last:DeskMotion={...home,home:true,state:'at-desk',airborne:0},called=false;
  let returning:{start:number;duration:number;from:Placement}|null=null;
  const delay=id==='worm'?4:id==='adult'?9:17,period=id==='worm'?43:id==='adult'?71:51;
  return {step(time:number,enabled:boolean,callHome:boolean,activity?:Activity):DeskMotion{
    if(activity&&activity.state!=='exploring')callHome=true;
    epoch??=time;
    if(!enabled){epoch=time;returning=null;called=callHome;return last={...home,home:true,state:'at-desk',airborne:0}}
    if(callHome&&!called){
      const distance=Math.hypot(last.x,last.y,last.z);
      returning=distance>.005?{start:time,duration:id==='adult'?2.8+distance*.12:1.2+distance*.4,from:{...last}}:null;
    }
    if(!callHome&&called){epoch=time;returning=null}
    called=callHome;
    if(callHome){
      if(returning){
        const t=(time-returning.start)/returning.duration;
        if(t<1){
          const from=returning.from;
          const placement=id==='adult'?sample([
            {at:0,p:from,state:'returning'},{at:.25,p:p(from.x,Math.max(1.2,from.y+.25),.25,from.yaw),state:'returning'},
            {at:.78,p:p(0,.8,.2,0),state:'returning'},{at:1,p:home,state:'at-desk'}],t):mix(from,home,t);
          return last={...placement,home:false,state:'returning',airborne:id==='adult'?Math.min(1,placement.y*3):0};
        }
        returning=null;
      }
      return last={...home,home:true,state:'at-desk',airborne:0};
    }
    if(activity){
      const route=routes[id];
      if(!route||activity.ends_at===null)return last={...home,home:true,state:'at-desk',airborne:0};
      const fraction=Math.max(0,Math.min(1,(time-activity.started_at)/Math.max(.1,activity.ends_at-activity.started_at)));
      const placement=sample(route,fraction*route[route.length-1].at),atHome=placement.state==='at-desk';
      return last={...placement,home:atHome,state:placement.state,airborne:placement.state==='flying'?Math.min(1,placement.y*3):0};
    }
    const elapsed=time-epoch-delay;
    if(elapsed<0)return last={...home,home:true,state:'at-desk',airborne:0};
    const placement=sample(routes[id],elapsed%period),atHome=placement.state==='at-desk';
    return last={...placement,home:atHome,state:placement.state,airborne:placement.state==='flying'?Math.min(1,placement.y*3):0};
  }};
}
