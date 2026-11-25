import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowRight, Bell, Bot, Building2, CalendarDays, ChartNoAxesCombined, Check, ChevronDown, ChevronRight, ChevronsUpDown, CircleAlert, ClipboardCheck, Command, FlaskConical, FolderKanban, Handshake, LayoutDashboard, ListChecks, LoaderCircle, Menu, MessageSquare, PanelLeftClose, Plus, RadioTower, Search, Settings2, ShieldAlert, Sparkles, Users, Wallet, X, type LucideIcon } from 'lucide-react';
import { LogoMark } from './Identity';
import { Dialog } from './Dialog';
import Dashboard from './Dashboard';
import Wizard from './Wizard';
import { api, save, saved, type AuthSession, type EventOption, type Snapshot } from './data';

const Modules=lazy(()=>import('./Modules'));
type Nav=[string,string,LucideIcon];
const groups:{name:string;items:Nav[]}[]=[
 {name:'Workspace',items:[['dashboard','Overview',LayoutDashboard],['events','Events',CalendarDays],['agents','AI agents',Bot]]},
 {name:'Event management',items:[['sponsors','Sponsorships',Handshake],['finance','Finance',Wallet],['tasks','Tasks & timeline',ListChecks],['marketing','Marketing',RadioTower],['operations','Participants',Users]]},
 {name:'Oversight',items:[['risks','Risks & recovery',ShieldAlert],['approvals','Approvals',ClipboardCheck],['reports','Reports',ChartNoAxesCombined]]},
];
const items:Nav[]=[...groups.flatMap(g=>g.items),['workspace','Workspace settings',Settings2],['copilot','AI Copilot',Sparkles]];
const valid=new Set(items.map(item=>item[0]));
function currentPage(){const id=location.hash.slice(1);return valid.has(id)?id:'dashboard';}
const eventUrl=(id:string)=>'/api/events/'+encodeURIComponent(id);
type Modal='search'|'notifications'|'events'|'wizard'|'workspace'|'profile'|null;
export default function App({session,onExit,exitPending,sessionError}:{
 session:AuthSession;onExit:()=>void;exitPending:boolean;sessionError:string;
}){
 const accountClub=session.club!;
 const eventKey='event.'+accountClub.id;
 const jobKey='planning_job.'+accountClub.id;
 const [page,setPage]=useState(currentPage),[options,setOptions]=useState<EventOption[]>([]),[id,setId]=useState(''),[data,setData]=useState<Snapshot|null>(null);
 const [error,setError]=useState(''),[booting,setBooting]=useState(true),[retry,setRetry]=useState(0);
 const [modal,setModal]=useState<Modal>(null),[query,setQuery]=useState(''),[collapsed,setCollapsed]=useState(()=>saved('narrow')==='yes'),[mobile,setMobile]=useState(false);
 const [toast,setToast]=useState('');const latest=useRef(''),version=useRef(0),drawer=useRef<HTMLElement>(null),menuTrigger=useRef<HTMLButtonElement>(null);
 const navigate=useCallback((dest:string)=>{if(!valid.has(dest))return;location.hash=dest;setPage(dest);setModal(null);setMobile(false);window.scrollTo({top:0});},[]);
 useEffect(()=>{const track=()=>{setPage(currentPage());setMobile(false);setModal(null)};window.addEventListener('hashchange',track);return()=>window.removeEventListener('hashchange',track)},[]);
 useEffect(()=>{const handle=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'&&!document.querySelector('dialog[open]')){e.preventDefault();setQuery('');setMobile(false);setModal('search')}};window.addEventListener('keydown',handle);return()=>window.removeEventListener('keydown',handle)},[]);
 useEffect(()=>{if(!mobile)return;const prev=document.body.style.overflow;document.body.style.overflow='hidden';const nav=drawer.current;nav?.querySelector<HTMLButtonElement>('button')?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setMobile(false);if(e.key==='Tab'&&nav){const controls=[...nav.querySelectorAll<HTMLElement>('button,a[href]')].filter(el=>el.offsetParent!==null);if(e.shiftKey&&document.activeElement===controls[0]){e.preventDefault();controls.at(-1)?.focus()}else if(!e.shiftKey&&document.activeElement===controls.at(-1)){e.preventDefault();controls[0]?.focus()}}};document.addEventListener('keydown',key);return()=>{document.body.style.overflow=prev;document.removeEventListener('keydown',key);menuTrigger.current?.focus()}},[mobile]);
 useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),4200);return()=>clearTimeout(timer)},[toast]);
 useEffect(()=>{let live=true;setBooting(true);setError('');api<EventOption[]>('/api/events').then(list=>{if(!live)return;setOptions(list);const selected=list.some(e=>e.id===saved(eventKey))?saved(eventKey)!:list[0]?.id||'';latest.current=selected;setId(selected)}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setBooting(false)});return()=>{live=false}},[retry,eventKey]);
 const refresh=useCallback(async()=>{const eid=latest.current;if(!eid)return;const rev=++version.current;const next=await api<Snapshot>(eventUrl(eid));if(eid===latest.current&&rev===version.current){setData(next);setError('')}},[]);
 useEffect(()=>{if(!id)return;let live=true;const load=()=>refresh().catch(e=>{if(live)setError(e.message)});void load();const timer=setInterval(()=>{if(document.visibilityState==='visible')void load()},15000);return()=>{live=false;clearInterval(timer)}},[id,refresh,retry]);
 const switchEvent=useCallback((eid:string)=>{if(eid!==latest.current){setData(null);latest.current=eid;version.current++;setId(eid);save(eventKey,eid)}setError('');navigate('dashboard')},[navigate,eventKey]);
 const complete=useCallback(async(eid:string)=>{const list=await api<EventOption[]>('/api/events');setOptions(list);switchEvent(eid);setToast('Event plan ready')},[switchEvent]);
 const act=useCallback(async(type:string,payload:Record<string,any>={})=>{const eid=latest.current;if(!eid)throw new Error('Select an event to continue.');
  const result=await api<any>(eventUrl(eid)+'/actions',{method:'POST',body:JSON.stringify({type,payload,request_id:crypto.randomUUID()})});
  if(eid===latest.current){await refresh();setToast('Workspace updated')}return result;
 },[refresh]);
 const open=(m:Modal)=>{setMobile(false);setQuery('');setModal(m)};
 const name=items.find(x=>x[0]===page)?.[1]||'Overview';
 const club=accountClub.name, organizer=session.demo?data?.members[0]:data?.members.find(m=>m.name===session.name), displayName=session.demo?(organizer?.name||session.name):session.name, initials=displayName.split(' ').slice(0,2).map(s=>s[0]).join('');
 const navItem=([dest,label,Icon]:Nav)=>{
  const badge=dest==='approvals'?data?.metrics.pending_approvals:0;
  return <a className={'nav-link'+(page===dest?' active':'')} aria-current={page===dest?'page':undefined} aria-label={label} title={label} key={dest} href={'#'+dest} onClick={e=>{if(!e.metaKey&&!e.ctrlKey&&!e.shiftKey){e.preventDefault();navigate(dest)}}}><Icon size={17} strokeWidth={1.65}/><span>{label}</span>{badge?<b>{badge}</b>:null}</a>
 };
 const searchItems=[...items.map(([key,label])=>({key,label,kind:'Page'})),...(query.trim()?[
 ...(data?.tasks??[]).map(t=>({key:'tasks',label:t.title,kind:'Task'})),...(data?.sponsors??[]).map(s=>({key:'sponsors',label:s.name,kind:'Sponsor'})),...(data?.risks??[]).map(r=>({key:'risks',label:r.title,kind:'Risk'}))]:[])].filter(x=>x.label.toLowerCase().includes(query.toLowerCase())).slice(0,12);
 const chooseEvents=<div className="event-options">{options.map(option=><button className="option-row" key={option.id} onClick={()=>switchEvent(option.id)}><span className="option-icon"><FolderKanban size={18}/></span><span>{option.name}</span>{option.id===id?<Check size={16}/>:<ChevronRight size={15}/>}</button>)}<button className="option-row create-option" onClick={()=>open('wizard')}><Plus size={17}/>{saved(jobKey)?'View planning progress':'Create event'}</button></div>;
 return <div className={'shell'+(collapsed?' narrow':'')+(mobile?' drawer-open':'')}>
 <a className="skip" href="#main-content" onClick={e=>{e.preventDefault();document.getElementById('main-content')?.focus()}}>Skip to content</a>
 {mobile&&<button aria-label="Close navigation" className="drawer-backdrop" onClick={()=>setMobile(false)}/>}
 <aside className="sidebar" ref={drawer} aria-label="Workspace sidebar" role={mobile?'dialog':undefined} aria-modal={mobile||undefined}>
  <div className="brand-row"><button className="wordmark" aria-label="ClubOS overview" onClick={()=>navigate('dashboard')}><LogoMark/><span>Club<span className="brand-os">OS</span></span></button><button className="collapse" onClick={()=>{if(mobile){setMobile(false);return}setCollapsed(!collapsed);save('narrow',collapsed?'no':'yes')}} aria-label={mobile?'Close navigation':collapsed?'Expand sidebar':'Collapse sidebar'}>{mobile?<X size={16}/>:<PanelLeftClose size={15}/>}</button></div>
  <button className="club-select" onClick={()=>open('workspace')} title="Club workspace"><span className="club-icon"><Building2 size={17}/></span><span className="club-copy"><strong>{club}</strong><small>{session.demo?'Demo workspace':'Club workspace'}</small></span><ChevronsUpDown size={13}/></button>
  <nav aria-label="Main navigation">{groups.map(g=><section className="nav-group" key={g.name}><h2>{g.name}</h2>{g.items.map(navItem)}</section>)}</nav>
  <div className="sidebar-bottom">{navItem(['workspace','Settings',Settings2])}<button className="profile" onClick={()=>open('profile')}><span className="avatar">{initials}</span><span><strong>{displayName}</strong><small>{organizer?.role||session.role}</small></span><ChevronsUpDown size={13}/></button></div>
 </aside>
 <div className="shell-main" inert={mobile||undefined}>
  <header className="topbar"><button ref={menuTrigger} className="mobile-menu icon-button" aria-label="Open navigation" onClick={()=>setMobile(true)}><Menu size={20}/></button>
  <div className="breadcrumb"><button onClick={()=>open('events')} aria-label="Switch event"><FolderKanban size={15}/><span>{data?.event.name||'Events'}</span><ChevronDown size={12}/></button><span className="crumb-divider">/</span><span>{name}</span></div>
  <div className="top-actions"><button className="search-btn" aria-label="Search workspace" onClick={()=>open('search')}><Search size={16}/><span>Search</span><kbd>⌘ K</kbd></button><button className="notifications icon-button" aria-label="Notifications" onClick={()=>open('notifications')}><Bell size={17}/>{(data?.metrics.pending_approvals||data?.metrics.active_risks)?<i/>:null}</button><span className="toolbar-divider"/><button className="copilot-btn" onClick={()=>navigate('copilot')}><Sparkles size={15}/><span>AI Copilot</span></button></div></header>
   <main className="main-content" id="main-content" tabIndex={-1}>
   {(error||sessionError)&&<div className="error-banner" role="alert"><CircleAlert size={17}/>{error||sessionError}{error&&<button onClick={()=>setRetry(n=>n+1)}>Retry</button>}</div>}
   {page==='events'?<><div className="page-intro"><div><h1>Events</h1><p>Select an event or launch a new plan.</p></div><button className="brand-button" onClick={()=>open('wizard')}><Plus size={15}/>Create event</button></div>{chooseEvents}</>:data?(page==='dashboard'?<Dashboard data={data} navigate={navigate}/>:<Suspense fallback={<div className="shell-loading" role="status">Opening {name}…</div>}><Modules key={id+page} page={page} data={data} navigate={navigate} act={act} refresh={refresh}/></Suspense>):booting||id&&!error?<div className="shell-loading" role="status"><LoaderCircle className="spin" size={20}/>Opening workspace…</div>:!error?<section className="workspace-empty">
     <span className="workspace-empty-icon"><CalendarDays size={24} strokeWidth={1.6}/></span>
     <h1>Your next event starts here</h1>
     <p>{accountClub.name} is ready. Add your first event to plan its budget, assign tasks, and track sponsorships.</p>
     <button className="brand-button" onClick={()=>open('wizard')}><Plus size={16}/> Create your first event</button>
   </section>:null}
   </main>
 </div>
 {modal==='events'&&<Dialog compact title="Switch event" onClose={()=>setModal(null)}>{chooseEvents}</Dialog>}
 {modal==='wizard'&&<Wizard data={data} college={accountClub.college} jobKey={jobKey} close={()=>setModal(null)} complete={complete}/>}
 {modal==='search'&&<Dialog compact title="Search workspace" onClose={()=>setModal(null)}><div className="search-field"><Search size={18}/><input autoFocus aria-label="Search pages, tasks, sponsors, and risks" placeholder="Search pages, tasks, sponsors, risks…" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="search-results">{searchItems.map((r,i)=><button key={r.kind+r.key+i} onClick={()=>navigate(r.key)}><span>{r.label}</span><small>{r.kind}</small><ArrowRight size={13}/></button>)}{!searchItems.length&&<p className="dash-empty">No matches for “{query}”.</p>}</div></Dialog>}
 {modal==='notifications'&&<Dialog compact title="Notifications" onClose={()=>setModal(null)}><div className="event-options">{data?.approvals.filter(a=>a.status?.toLowerCase()==='pending').map(a=><button className="option-row" key={a.id} onClick={()=>navigate('approvals')}><ClipboardCheck size={16}/><span>{a.title}</span><ChevronRight size={14}/></button>)}{data?.risks.filter(r=>!['closed','resolved'].includes(r.status?.toLowerCase())).map(r=><button className="option-row" key={r.id} onClick={()=>navigate('risks')}><ShieldAlert size={16}/><span>{r.title}</span><ChevronRight size={14}/></button>)}{!data?.metrics.pending_approvals&&!data?.metrics.active_risks&&<p className="dash-empty">No pending approvals or open risks.</p>}</div></Dialog>}
 {modal==='workspace'&&<Dialog compact title="Club workspace" onClose={()=>setModal(null)}><div className="event-options"><div className="option-row"><Building2 size={17}/><span>{club}</span><Check size={15}/></div><button className="option-row" onClick={()=>navigate('workspace')}><Settings2 size={16}/><span>Workspace settings</span><ChevronRight size={15}/></button></div></Dialog>}
 {modal==='profile'&&<Dialog compact title="Organizer profile" onClose={()=>setModal(null)}><div className="profile-sheet"><span className="avatar">{initials}</span><div><strong>{displayName}</strong><p>{organizer?.role||session.role} · {club}</p></div></div><button className="option-row" onClick={()=>navigate('workspace')}><Users size={15}/><span>View organizing team</span><ChevronRight size={15}/></button><button className="option-row" disabled={exitPending} onClick={onExit}><span>{session.demo?'Exit demo':'Log out'}</span><ChevronRight size={14}/></button>{sessionError&&<p className="dash-empty" role="alert">{sessionError}</p>}</Dialog>}
 {toast&&<div className="shell-toast" role="status"><Check size={15}/>{toast}<button aria-label="Dismiss notification" onClick={()=>setToast('')}><X size={13}/></button></div>}
 </div>
}
