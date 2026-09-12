export const deform=`
uniform float uTime;
uniform float uForward;
uniform float uReverse;
uniform float uWorm;
vec3 bodyPosition(vec3 p) {
  if(uWorm>0.5){
    float axis=clamp(0.5-p.y/3.0,0.0,1.0);
    p.x+=0.07*sin(axis*7.0)+0.2*(uForward*sin(axis*9.0-uTime*2.8)+uReverse*sin(axis*9.0+uTime*2.8))/max(1.0,uForward+uReverse);
  }
  return p;
}
`;

export const pointVertex=deform+`
attribute float aMask;
attribute float aCount;
attribute float aSimulated;
attribute float aSelected;
uniform float uPhase;
uniform float uPixelRatio;
varying float vPulse;
varying float vSimulated;
varying float vSelected;
float hasSpike(float mask,float bin){return bin<0.0||bin>19.0?0.0:mod(floor(mask/pow(2.0,bin)),2.0);}
void main(){
  float bin=floor(uPhase);
  float age=uPhase-bin;
  vPulse=uPhase>=0.0&&uPhase<21.0?max(hasSpike(aMask,bin)*exp(-age*6.0),hasSpike(aMask,bin-1.0)*exp(-(age+1.0)*6.0)):0.0;
  vPulse*=aSimulated;
  vSimulated=aSimulated;vSelected=aSelected;
  vec4 mv=modelViewMatrix*vec4(bodyPosition(position),1.0);
  gl_Position=projectionMatrix*mv;
  float size=mix(1.65,1.8,aSimulated)+vPulse*2.5+aSelected*4.0;
  gl_PointSize=clamp(size*uPixelRatio*4.2/max(1.0,-mv.z),1.0,14.0*uPixelRatio);
}
`;
export const pointFragment=`
uniform vec3 uColor;
uniform float uWorm;
varying float vPulse;
varying float vSimulated;
varying float vSelected;
void main(){
  vec2 p=gl_PointCoord*2.0-1.0;
  if(uWorm>0.5)p.y*=2.6;
  float r=length(p);if(r>1.0)discard;
  vec3 color=mix(vec3(0.49,0.56,0.50),uColor,vSimulated);
  color=mix(color,vec3(0.94,1.0,0.9),max(vPulse*.7,vSelected));
  float alpha=(1.0-smoothstep(.32,1.0,r))*(mix(.43,.52,vSimulated)+vPulse*.4+vSelected*.3);
  gl_FragColor=vec4(color,alpha);
}
`;
export const bodyVertex=deform+`
varying vec3 vNormal;
void main(){vNormal=normalize(normalMatrix*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(bodyPosition(position),1.0);}
`;
export const bodyFragment=`
uniform vec3 uColor;
varying vec3 vNormal;
void main(){float rim=pow(1.0-abs(vNormal.z),2.0);gl_FragColor=vec4(uColor,.025+rim*.24);}
`;
