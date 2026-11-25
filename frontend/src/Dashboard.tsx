import { useMemo, useState, type ReactNode } from 'react';
import { Activity, ArrowRight, ArrowUpRight, AudioLines, CalendarDays, CheckCheck, ChevronDown, CircleCheck, Clock3, Flag, Layers3, ListChecks, MapPin, Radio, ShieldAlert, Target, TrendingUp, Users, Wallet, type LucideIcon } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AgentMark } from './Identity';
import { Terrain } from './Terrain';
import { dateOf, money, ratio, shortDate, type Snapshot } from './data';

type Props={data:Snapshot;navigate:(page:string)=>void};
const stages=['Identified','Shortlisted','Outreach Drafted','Contacted','Responded','Negotiating','Confirmed','Declined','Withdrawn'];
function Metric({title,value,icon:Icon,tone,children,onClick}:{title:string;value:ReactNode;icon:LucideIcon;tone:string;children:ReactNode;onClick:()=>void}){
 return <button className={'metric sch-'+tone} onClick={onClick}><span className="metric-head"><span className="metric-icon"><Icon size={16}/></span>{title}<ArrowUpRight size={13} className="metric-link"/></span><strong>{value}</strong><span className="metric-detail">{children}</span></button>
}
function PanelHead({title,icon:Icon,children}:{title:string;icon:LucideIcon;children?:ReactNode}){
 return <header className="panel-head"><h2><Icon size={17} strokeWidth={1.7}/>{title}</h2>{children}</header>
}
function Steps({percentage,tone}:{percentage:number;tone:string}){return <span className={'metric-steps '+tone} aria-hidden="true">{Array.from({length:12},(_,i)=><i key={i} className={i<Math.round(Math.min(100,percentage)*.12)?'filled':''}/>)}</span>}
function timestamp(value:string){
 const date=dateOf(value), age=Math.max(0,(Date.now()-date.getTime())/60000);
 if(age<1)return 'Just now';if(age<60)return Math.floor(age)+'m ago';if(age<1440)return Math.floor(age/60)+'h ago';return shortDate(value);
}
function registrations(data:Snapshot,days:number){
 const totals=new Map<string,number>();
 const history=data.registration_history;
 if(history?.length)history.forEach(r=>totals.set(r.date.slice(0,10),r.count));
 else data.participants.forEach(p=>{if(p.created_at){const k=p.created_at.slice(0,10);totals.set(k,(totals.get(k)??0)+1);}});
 const end=new Date();const start=new Date(end);start.setUTCDate(start.getUTCDate()-days+1);
 const startKey=start.toISOString().slice(0,10);
 let running=0;totals.forEach((v,k)=>{if(k<startKey)running+=v});
 return Array.from({length:days},(_,i)=>{const day=new Date(start);day.setUTCDate(day.getUTCDate()+i);const key=day.toISOString().slice(0,10);running+=totals.get(key)??0;return {date:key,total:running,new:totals.get(key)??0}});
}
export default function Dashboard({data,navigate}:Props){
 const [days,setDays]=useState(14);
 const m=data.metrics, e=data.event;
 const registered=ratio(m.registered,m.target),taskPercent=ratio(m.completed,m.total_tasks), funding=ratio(m.projected_funding,m.planned);
 const chart=useMemo(()=>registrations(data,days),[data,days]);
 const runs=useMemo(()=>[...data.runs].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,4),[data.runs]);
 const due=useMemo(()=>data.tasks.filter(t=>!['completed','done'].includes(t.status?.toLowerCase())&&t.due_date).sort((a,b)=>a.due_date.localeCompare(b.due_date)).slice(0,4),[data.tasks]);
 const daysLeft=Math.ceil((dateOf(e.start_date).setHours(0,0,0,0)-new Date().setHours(0,0,0,0))/86400000);
 const dailyGain=chart.reduce((n,p)=>n+p.new,0);
 const go=(id:string)=><button className="text-link" onClick={()=>navigate(id)}>View all <ArrowRight size={13}/></button>;
 const pending=m.total_tasks-m.completed;
 const openRisks=data.risks.filter(r=>!['closed','resolved'].includes(r.status?.toLowerCase()));
 const pipeline=stages.map(stage=>({stage,count:data.sponsors.filter(s=>s.stage.toLowerCase()===stage.toLowerCase()).length})).filter(s=>s.count);
 const maxBudget=Math.max(...data.budget.map(b=>Math.max(b.planned,b.actual)),1);
 return <div className="dashboard">
 <div className="page-intro"><div><h1>Command center</h1><p>Your event operations at a glance.</p></div><button className="subtle-button" onClick={()=>navigate('reports')}><Layers3 size={15}/> Event reports <ArrowUpRight size={13}/></button></div>
 <section className="event-hero" aria-label="Selected event">
   <div className="event-copy"><div className="event-status"><span className="signal-dot"/> {daysLeft>=0?'Active event':'Event workspace'}</div><h2>{e.name}</h2><p>{e.type || 'Club event'}</p><div className="event-details"><span><CalendarDays size={14}/>{shortDate(e.start_date,true)}</span>{e.venue&&<span><MapPin size={14}/>{e.venue}</span>}</div></div>
   <div className="terrain-box"><Terrain funding={funding} tasks={taskPercent} registrations={registered}/><div className="readiness"><Activity size={13}/> Event readiness <strong>{m.readiness}%</strong></div></div>
   <div className="countdown"><Clock3 size={12}/>{daysLeft>0?daysLeft+' days to go':daysLeft===0?'Starts today':'Started '+shortDate(e.start_date)}</div>
 </section>
 <section className="metric-grid" aria-label="Event metrics">
  <Metric title="Projected funding" value={money(m.projected_funding)} icon={Wallet} tone="mint" onClick={()=>navigate('finance')}><span className={m.balance<0?'risk-text':'mint-text'}><TrendingUp size={12}/>{money(Math.abs(m.balance))} {m.balance<0?'shortfall':'surplus'}</span></Metric>
  <Metric title="Registrations" value={<>{m.registered}<small> / {m.target}</small></>} icon={Users} tone="lavender" onClick={()=>navigate('operations')}><span>{registered}% of target</span><Steps percentage={registered} tone="lavender"/></Metric>
  <Metric title="Task completion" value={<>{taskPercent}<small className="percent-sign">%</small></>} icon={ListChecks} tone="blue" onClick={()=>navigate('tasks')}><span>{m.completed} of {m.total_tasks} complete</span><Steps percentage={taskPercent} tone="blue"/></Metric>
  <Metric title="Active risks" value={m.active_risks} icon={ShieldAlert} tone="amber" onClick={()=>navigate('risks')}><span className={m.active_risks?'amber-text':'mint-text'}><i className="tiny-dot"/>{m.active_risks?'Monitoring required':'All clear'}</span></Metric>
 </section>
 <div className="primary-panels">
 <section className="dash-panel registration-panel"><PanelHead title="Registration growth" icon={TrendingUp}><label className="select-wrap"><select aria-label="Registration chart date range" value={days} onChange={e=>setDays(Number(e.target.value))}><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option></select><ChevronDown size={12}/></label></PanelHead>
   <div className="chart-meta"><span className="chart-total">{m.registered}</span><span className="legend"><i/> Participants</span><span className="chart-gain">+{dailyGain} this period</span></div>
   <div className="registration-chart" aria-label={`Cumulative registrations over the last ${days} days, ending at ${chart[chart.length-1]?.total??0}`}><ResponsiveContainer width="100%" height="100%" minWidth={0}>
    <AreaChart data={chart} margin={{left:-17,right:12,top:6,bottom:0}}><defs><linearGradient id="registrations-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#aa82fa" stopOpacity=".28"/><stop offset="100%" stopColor="#aa82fa" stopOpacity=".015"/></linearGradient></defs><CartesianGrid stroke="#36343f" strokeDasharray="3 5" vertical={false}/><XAxis dataKey="date" tickFormatter={v=>shortDate(String(v))} minTickGap={30} axisLine={false} tickLine={false} tickMargin={10} tick={{fill:'#94919f',fontSize:10}}/><YAxis domain={[0,'auto']} allowDecimals={false} tickCount={5} axisLine={false} tickLine={false} tick={{fill:'#94919f',fontSize:10}}/><Tooltip cursor={{stroke:'#88799c',strokeDasharray:'3 4'}} contentStyle={{background:'#232129',border:'1px solid #46424f',borderRadius:8,fontSize:12,color:'#f6f4ff'}} labelFormatter={v=>shortDate(String(v))} formatter={v=>[String(v),'Participants']}/><Area dataKey="total" type="monotone" stroke="#b390ff" strokeWidth={2.7} fill="url(#registrations-fill)" activeDot={{r:4,fill:'#d5c0ff',stroke:'#211e2a'}} isAnimationActive={false}/></AreaChart>
   </ResponsiveContainer></div></section>
 <section className="dash-panel agent-panel"><PanelHead title="Agent activity" icon={AudioLines}>{go('agents')}</PanelHead><div className="agent-list">
 {runs.length?runs.map(r=><button key={r.id} onClick={()=>navigate('agents')} className="run-row"><AgentMark name={r.agent}/><span className="run-copy"><strong>{r.agent}<span className="run-timestamp">{timestamp(r.created_at)}</span></strong><span title={r.summary}>{r.summary||r.trigger}</span></span></button>):<p className="dash-empty">Agent runs will appear after the first workflow.</p>}
 </div><div className="panel-foot"><span className="signal-dot"/> {data.runs.length} recorded agent {data.runs.length===1?'run':'runs'}</div></section>
 </div>
 <div className="secondary-panels">
 <section className="dash-panel"><PanelHead title="Upcoming deadlines" icon={CalendarDays}>{go('tasks')}</PanelHead>{due.length?due.map(t=><button key={t.id} className="deadline-row" onClick={()=>navigate('tasks')}><span className="date-block"><strong>{dateOf(t.due_date).getDate()}</strong><small>{dateOf(t.due_date).toLocaleString('en',{month:'short'})}</small></span><span><strong>{t.title}</strong><small>{t.owner||t.department||'Unassigned'}</small></span><ArrowUpRight size={13}/></button>):<p className="dash-empty">No open deadlines.</p>}<div className="panel-foot">{pending} pending tasks · {m.overdue} overdue</div></section>
 <section className="dash-panel"><PanelHead title="Funding overview" icon={Wallet}>{go('finance')}</PanelHead><div className="finance-rows">{[['Planned expenses',m.planned],['Actual expenses',m.actual],['Sponsor commitments',m.committed],['Sponsorship received',m.received],['Projected balance',m.balance]].map(([label,value])=><div key={label}><span>{label}</span><strong>{money(Number(value))}</strong></div>)}</div></section>
 <section className="dash-panel"><PanelHead title="Budget allocation" icon={Layers3}>{go('finance')}</PanelHead><div className="bar-list">{data.budget.length?data.budget.map(b=><button key={b.id} onClick={()=>navigate('finance')} title={`Planned ${money(b.planned)}, actual ${money(b.actual)}`}><span>{b.category}<strong>{money(b.planned)}</strong></span><i><b style={{width:Math.max(1,b.planned/maxBudget*100)+'%'}}/></i><i className="actual-bar"><b style={{width:Math.min(100,b.actual/maxBudget*100)+'%'}}/></i></button>):<p className="dash-empty">Your budget is ready for allocations.</p>}</div><div className="panel-foot"><span className="chart-key lavender"/> Planned <span className="chart-key mint"/> Actual</div></section>
 <section className="dash-panel"><PanelHead title="Sponsorship pipeline" icon={Flag}>{go('sponsors')}</PanelHead><div className="bar-list">{pipeline.length?pipeline.map(s=><button key={s.stage} onClick={()=>navigate('sponsors')}><span>{s.stage}<strong>{s.count}</strong></span><i><b style={{width:(s.count/data.sponsors.length*100)+'%'}}/></i></button>):<p className="dash-empty">Add a prospect to start your pipeline.</p>}</div></section>
 <section className="dash-panel"><PanelHead title="Risks & approvals" icon={ShieldAlert}>{go('risks')}</PanelHead><button className="inline-alert" onClick={()=>navigate('approvals')}><CheckCheck size={17}/>{m.pending_approvals} pending approvals<ArrowRight size={14}/></button>{openRisks.slice(0,3).map(r=><button className="simple-row" key={r.id} onClick={()=>navigate('risks')}><ShieldAlert size={14}/>{r.title}<small>{r.severity}</small></button>)}</section>
 <section className="dash-panel"><PanelHead title="Recent activity" icon={Activity}/>{data.activity.slice(0,4).map(a=><div className="simple-row" key={a.id}><Radio size={14}/><span>{a.title}</span><small>{timestamp(a.created_at)}</small></div>)}{!data.activity.length&&<p className="dash-empty">Event actions will appear here.</p>}<div className="panel-foot"><CircleCheck size={13}/>{m.actions} automated actions <Target size={13}/>{m.minutes_saved} min estimated savings</div></section>
 </div></div>
}
