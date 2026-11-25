import { memo } from 'react';

function Landscape({funding,tasks,registrations}:{funding:number;tasks:number;registrations:number}) {
 // Each summit represents one operational measure. Orthographic projection keeps the grid legible at small sizes.
 const values=[funding,tasks,registrations].map(v=>Math.max(0,Math.min(1,v/100)));
 const heights=(u:number,v:number)=>{
   const peak=(x:number,y:number,sx:number,sy:number,h:number)=>h*Math.exp(-(((u-x)/sx)**2+((v-y)/sy)**2));
   return peak(.31,.38,.125,.31,16+values[0]*88)+peak(.56,.48,.15,.22,15+values[1]*102)+peak(.765,.38,.14,.24,15+values[2]*90);
 };
 const point=(u:number,v:number)=>[(u*440+v*96-7).toFixed(1),(69+94*v-18*u-heights(u,v)).toFixed(1)];
 function curve(cross:boolean,frac:number){return Array.from({length:81},(_,i)=>{const [x,y]=cross?point(frac,i/80):point(i/80,frac);return (i?'L':'M')+x+' '+y;}).join(' ')}
 return <svg viewBox="0 -10 530 190" preserveAspectRatio="xMidYMid meet" role="img" aria-label={`Event readiness terrain. Funding ${funding}%, tasks ${tasks}%, registrations ${registrations}%.`} className="terrain">
 <defs>
  <linearGradient id="terrain-line" x1="0" x2="1" y1=".5" y2=".35"><stop stopColor="#554281" stopOpacity=".22"/><stop offset=".24" stopColor="#9c75ed"/><stop offset=".53" stopColor="#c8a6ff"/><stop offset=".8" stopColor="#af82fa"/><stop offset="1" stopColor="#7752bc" stopOpacity=".3"/></linearGradient>
  <radialGradient id="terrain-light"><stop stopColor="#9871e8" stopOpacity=".19"/><stop offset="1" stopColor="#9871e8" stopOpacity="0"/></radialGradient>
 </defs>
 <ellipse cx="285" cy="88" rx="226" ry="82" fill="url(#terrain-light)"/>
 {Array.from({length:35},(_,i)=><path key={'r'+i} d={curve(false,i/34)} stroke="url(#terrain-line)" strokeWidth={i%4===0?1.05:.68} fill="none" opacity={.58+.4*i/34}/>)}
 {Array.from({length:66},(_,i)=><path key={'c'+i} d={curve(true,i/65)} stroke="url(#terrain-line)" strokeWidth=".59" opacity=".6" fill="none"/>)}
 </svg>
}
export const Terrain=memo(Landscape);
