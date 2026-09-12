import type {BioId,Graph} from './types';

export type Point={x:number;y:number};
export const hash=(s:string)=>{let h=2166136261;for(const c of s)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0)/4294967296};

// Head-inspired display masks. These do not assign anatomical locations to neurons.
export function specimenLayout(bio:BioId,graph:Graph,w:number,h:number){
  const body=new Path2D(),details=new Path2D(),neural=new Path2D();
  const ellipse=(path:Path2D,x:number,y:number,rx:number,ry:number)=>{
    path.moveTo(w*(x+rx),h*y);path.ellipse(w*x,h*y,w*rx,h*ry,0,0,Math.PI*2);
  };
  if(bio==='worm'){
    body.moveTo(w*.87,h*.24);
    body.bezierCurveTo(w*.64,h*.24,w*.36,h*.18,w*.19,h*.36);
    body.bezierCurveTo(w*.10,h*.44,w*.10,h*.56,w*.19,h*.64);
    body.bezierCurveTo(w*.36,h*.82,w*.64,h*.76,w*.87,h*.76);body.closePath();
    // Ring motif and longitudinal bands evoke the head nerve ring and cords.
    ellipse(neural,.43,.5,.115,.225);
    ellipse(neural,.43,.5,.06,.105);
    for(const side of [-1,1]){
      neural.rect(w*.42,h*(.5+side*.13-.035),w*.4,h*.07);
      details.moveTo(w*.15,h*(.5+side*.04));
      details.bezierCurveTo(w*.3,h*(.5+side*.07),w*.32,h*(.5+side*.035),w*.39,h*(.5+side*.035));
      details.moveTo(w*.49,h*(.5+side*.035));details.lineTo(w*.83,h*(.5+side*.035));
    }
    ellipse(details,.15,.5,.018,.055);
  }else if(bio==='adult'){
    body.moveTo(w*.31,h*.29);
    body.bezierCurveTo(w*.35,h*.18,w*.65,h*.18,w*.69,h*.29);
    body.bezierCurveTo(w*.86,h*.26,w*.88,h*.62,w*.7,h*.72);
    body.bezierCurveTo(w*.61,h*.81,w*.39,h*.81,w*.3,h*.72);
    body.bezierCurveTo(w*.12,h*.62,w*.14,h*.26,w*.31,h*.29);body.closePath();
    for(const side of [-1,1]){
      ellipse(details,.5+side*.235,.5,.085,.202);
      ellipse(neural,.5+side*.16,.51,.09,.16);
      ellipse(neural,.5+side*.065,.49,.105,.22);
      details.moveTo(w*(.5+side*.045),h*.27);
      details.quadraticCurveTo(w*(.5+side*.095),h*.12,w*(.5+side*.15),h*.13);
      ellipse(details,.5+side*.047,.255,.025,.046);
      for(let row=0;row<7;row++)for(let col=0;col<4;col++){
        const x=.5+side*(.19+col*.024),y=.36+row*.046+(col%2)*.018;
        if(((x-(.5+side*.235))/.074)**2+((y-.5)/.185)**2<1)ellipse(details,x,y,.003,.006);
      }
    }
    ellipse(details,.5,.72,.034,.06);
  }else{
    body.moveTo(w*.41,h*.24);
    body.bezierCurveTo(w*.33,h*.21,w*.28,h*.36,w*.25,h*.49);
    body.bezierCurveTo(w*.23,h*.62,w*.24,h*.74,w*.29,h*.81);
    body.quadraticCurveTo(w*.5,h*.87,w*.71,h*.81);
    body.bezierCurveTo(w*.76,h*.74,w*.77,h*.62,w*.75,h*.49);
    body.bezierCurveTo(w*.72,h*.36,w*.67,h*.21,w*.59,h*.24);
    body.quadraticCurveTo(w*.5,h*.29,w*.41,h*.24);body.closePath();
    for(const side of [-1,1]){
      ellipse(neural,.5+side*.095,.53,.12,.18);
      details.moveTo(w*(.5+side*.115),h*.255);
      details.lineTo(w*(.5+side*.12),h*.185);
      details.lineTo(w*(.5+side*.14),h*.175);
      details.moveTo(w*(.5+side*.04),h*.28);
      details.quadraticCurveTo(w*(.5+side*.095),h*.33,w*(.5+side*.045),h*.39);
    }
    neural.rect(w*.46,h*.57,w*.08,h*.14);
  }
  const hit=document.createElement('canvas').getContext('2d')!;
  const positions=graph.nodes.map(n=>{
    for(let k=0;k<3000;k++){
      const p={x:w*(.16+hash(n.id+'x'+k)*.68),y:h*(.23+hash(n.id+'y'+k)*.54)};
      if(hit.isPointInPath(neural,p.x,p.y,bio==='worm'?'evenodd':'nonzero'))return p;
    }
    return{x:w*.5,y:h*.5};
  });
  const routes=graph.edges.map(([a,b],i)=>{
    const start=positions[a],end=positions[b],bend=((i%5)-2)*.035;
    return Array.from({length:17},(_,step)=>{
      const t=step/16;
      return{x:start.x+(end.x-start.x)*t-(end.y-start.y)*bend*2*t*(1-t),y:start.y+(end.y-start.y)*t+(end.x-start.x)*bend*2*t*(1-t)};
    });
  });
  return{body,details,positions,routes};
}

export function routePoint(points:Point[],t:number):Point{
  const scaled=Math.max(0,Math.min(1,t))*(points.length-1),i=Math.min(points.length-2,Math.floor(scaled)),mix=scaled-i;
  return{x:points[i].x+(points[i+1].x-points[i].x)*mix,y:points[i].y+(points[i+1].y-points[i].y)*mix};
}
