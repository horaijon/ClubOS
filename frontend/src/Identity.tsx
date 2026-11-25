import { Activity, Antenna, AudioLines, Boxes, Command, Compass, Feather, Hexagon, Layers3, Radar, ShieldCheck, Wallet, type LucideIcon } from 'lucide-react';

export function LogoMark({small=false}:{small?:boolean}) {
 return <svg className={small?'logo-mark small':'logo-mark'} viewBox="0 0 38 38" fill="none" aria-hidden="true"><path d="m19 2 14.9 8.6v6.6l-6.3 3.6v-6.6l-8.6-5-8.6 5v9.7l8.6 5 14.9-8.6v7.1L19 36 4.1 27.4V10.6L19 2Z" fill="currentColor"/><path d="m19 12.5 5.2 3v6L19 24.6l-5.2-3.1v-6l5.2-3Z" fill="currentColor" opacity=".78"/></svg>
}
const identities:Record<string,{icon:LucideIcon;color:string;role:string}>={
 nexus:{icon:Hexagon,color:'#b89bff',role:'Orchestrator'},atlas:{icon:Compass,color:'#83adf7',role:'Planning'},
 magnet:{icon:Antenna,color:'#c19bff',role:'Sponsorship'},ledger:{icon:Layers3,color:'#79d4b0',role:'Finance'},
 echo:{icon:AudioLines,color:'#eeaf8d',role:'Marketing'},relay:{icon:Boxes,color:'#79cacf',role:'Operations'},
 sentinel:{icon:ShieldCheck,color:'#f2c375',role:'Risk & recovery'}
};
export const agentIdentity=(name:string)=>identities[name?.toLowerCase()?.trim()?.split(' ')[0]]??{icon:Activity,color:'#b2aec5',role:'Workflow'};
export function AgentMark({name}:{name:string}) {const {icon:Icon,color}=agentIdentity(name);return <span className="agent-mark" style={{color,backgroundColor:color+'12',borderColor:color+'28'}}><Icon size={17} strokeWidth={1.65}/></span>}
export {Command, Feather, Radar, Wallet};
