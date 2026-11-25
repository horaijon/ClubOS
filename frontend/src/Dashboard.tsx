import { useMemo, useState, type ReactNode } from 'react';
import { ArrowRight, ArrowUpRight, CalendarDays, CheckCheck, ChevronDown, CircleCheck, Clock3, Layers3, MapPin, Radio, ShieldAlert, Target } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AgentMark } from './Identity';
import { dateOf, money, ratio, shortDate, type Snapshot } from './data';

type Props={data:Snapshot;navigate:(page:string)=>void};
const stages=['Identified','Shortlisted','Outreach Drafted','Contacted','Responded','Negotiating','Confirmed','Declined','Withdrawn'];
function Metric({title,value,children,onClick}:{title:string;value:ReactNode;children:ReactNode;onClick:()=>void}){
 return <button className="metric" onClick={onClick}>
  <span className="metric-head">{title}<ArrowUpRight size={16} className="metric-link" aria-hidden="true"/></span>
  <strong>{value}</strong>
  <span className="metric-detail">{children}</span>
 </button>
}

function PanelHead({title,children}:{title:string;children?:ReactNode}){
 return <header className="panel-head"><h2>{title}</h2>{children}</header>
}

function Readiness({score, funding, registrations, tasks, underfunded}:{
 score:number; funding:number; registrations:number; tasks:number; underfunded:boolean;
}){
 const rows = [
  {label:'Funding coverage', value:funding, warning:underfunded},
  {label:'Registration target', value:registrations},
  {label:'Tasks completed', value:tasks},
 ];
 return <div className="readiness-board">
  <div className="readiness-heading"><h3>Event readiness</h3><strong>{score}%</strong></div>
  <ul className="readiness-lanes">
   {rows.map(({label, value, warning}) => <li key={label} className={warning?'below-target':undefined}>
    <span>{label}</span>
    <span className="readiness-track" aria-hidden="true"><span style={{width:Math.min(100,Math.max(0,value))+'%'}}/></span>
    <strong>{value}%</strong>
   </li>)}
  </ul>
 </div>;
}

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
 <div className="page-intro">
  <h1>Command center</h1>
  <button className="subtle-button event-report-button" onClick={()=>navigate('reports')}><Layers3 size={16}/> Event reports</button>
 </div>
 <section className="event-hero" aria-label="Selected event">
  <div className="event-copy">
   <div className="event-kicker"><span>{e.type || 'Club event'}</span><span className="countdown"><Clock3 size={16}/>{daysLeft>0?daysLeft+' days to go':daysLeft===0?'Starts today':'Started '+shortDate(e.start_date)}</span></div>
   <h2>{e.name}</h2>
   <div className="event-details">
    <span><CalendarDays size={16}/>{shortDate(e.start_date,true)}</span>
    {e.venue && <span><MapPin size={16}/>{e.venue}</span>}
   </div>
  </div>
  <Readiness score={m.readiness} funding={funding} registrations={registered} tasks={taskPercent} underfunded={m.balance<0}/>
 </section>
 <section className="metric-grid" aria-label="Event metrics">
  <Metric title="Projected funding" value={money(m.projected_funding)} onClick={()=>navigate('finance')}>
   <span className={m.balance<0?'risk-text':m.balance>0?'mint-text':undefined}>{m.balance===0?'Budget covered':money(Math.abs(m.balance))+(m.balance<0?' shortfall':' surplus')}</span>
  </Metric>
  <Metric title="Registrations" value={<>{m.registered}<small> / {m.target}</small></>} onClick={()=>navigate('operations')}><span>{registered}% of target</span></Metric>
  <Metric title="Task completion" value={<>{taskPercent}<small className="percent-sign">%</small></>} onClick={()=>navigate('tasks')}><span>{m.completed} of {m.total_tasks} complete</span></Metric>
  <Metric title="Active risks" value={m.active_risks} onClick={()=>navigate('risks')}>
   <span className={m.active_risks?'amber-text':'mint-text'}>{m.pending_approvals?m.pending_approvals+' pending '+(m.pending_approvals===1?'approval':'approvals'):m.active_risks?'Monitoring required':'All clear'}</span>
  </Metric>
 </section>
 <div className="primary-panels">
 <section className="dash-panel registration-panel"><PanelHead title="Registration growth"><label className="select-wrap"><select aria-label="Registration chart date range" value={days} onChange={e=>setDays(Number(e.target.value))}><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option></select><ChevronDown size={12}/></label></PanelHead>
   <div className="chart-meta"><span className="chart-total">{m.registered}</span><span className="legend"><i/> Participants</span><span className="chart-gain">+{dailyGain} this period</span></div>
   <div className="registration-chart" role="group" aria-label={`Cumulative registrations over the last ${days} days, ending at ${chart[chart.length-1]?.total??0}`}><ResponsiveContainer width="100%" height="100%" minWidth={0}>
    <AreaChart data={chart} margin={{left:-17,right:12,top:6,bottom:0}}><defs><linearGradient id="registrations-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#aa82fa" stopOpacity=".28"/><stop offset="100%" stopColor="#aa82fa" stopOpacity=".015"/></linearGradient></defs><CartesianGrid stroke="#33353c" strokeDasharray="2 4" vertical={false}/><XAxis dataKey="date" tickFormatter={v=>shortDate(String(v))} minTickGap={30} axisLine={false} tickLine={false} tickMargin={10} tick={{fill:'#a6a8b0',fontSize:12}}/><YAxis domain={[0,'auto']} allowDecimals={false} tickCount={5} axisLine={false} tickLine={false} tick={{fill:'#a6a8b0',fontSize:12}}/><Tooltip cursor={{stroke:'#88799c',strokeDasharray:'3 4'}} contentStyle={{background:'#232129',border:'1px solid #46424f',borderRadius:8,fontSize:12,color:'#f6f4ff'}} labelFormatter={v=>shortDate(String(v))} formatter={v=>[String(v),'Participants']}/><Area dataKey="total" type="monotone" stroke="#bb9eff" strokeWidth={2.5} fill="url(#registrations-fill)" activeDot={{r:4,fill:'#d5c0ff',stroke:'#211e2a'}} isAnimationActive={false}/></AreaChart>
   </ResponsiveContainer></div></section>
 <section className="dash-panel agent-panel"><PanelHead title="Agent activity">{go('agents')}</PanelHead><div className="agent-list">
 {runs.length?runs.map(r=><button key={r.id} onClick={()=>navigate('agents')} className="run-row"><AgentMark name={r.agent}/><span className="run-copy"><strong>{r.agent}<span className="run-timestamp">{timestamp(r.created_at)}</span></strong><span title={r.summary}>{r.summary||r.trigger}</span></span></button>):<p className="dash-empty">Agent runs will appear after the first workflow.</p>}
 </div><div className="panel-foot">{data.runs.length} recorded agent {data.runs.length===1?'run':'runs'}</div></section>
 </div>
 <div className="secondary-panels">
 <section className="dash-panel"><PanelHead title="Upcoming deadlines">{go('tasks')}</PanelHead>{due.length?due.map(t=><button key={t.id} className="deadline-row" onClick={()=>navigate('tasks')}><span className="date-block"><strong>{dateOf(t.due_date).getDate()}</strong><small>{dateOf(t.due_date).toLocaleString('en',{month:'short'})}</small></span><span><strong>{t.title}</strong><small>{t.owner||t.department||'Unassigned'}</small></span><ArrowUpRight size={13}/></button>):<p className="dash-empty">No open deadlines.</p>}<div className="panel-foot">{pending} pending tasks · {m.overdue} overdue</div></section>
 <section className="dash-panel"><PanelHead title="Funding overview">{go('finance')}</PanelHead><div className="finance-rows">{[['Planned expenses',m.planned],['Actual expenses',m.actual],['Sponsor commitments',m.committed],['Sponsorship received',m.received],['Projected balance',m.balance]].map(([label,value])=><div key={label}><span>{label}</span><strong>{money(Number(value))}</strong></div>)}</div></section>
 <section className="dash-panel"><PanelHead title="Budget allocation">{go('finance')}</PanelHead><div className="bar-list">{data.budget.length?data.budget.map(b=><button key={b.id} onClick={()=>navigate('finance')} title={`Planned ${money(b.planned)}, actual ${money(b.actual)}`}><span>{b.category}<strong>{money(b.planned)}</strong></span><i><b style={{width:Math.max(1,b.planned/maxBudget*100)+'%'}}/></i><i className="actual-bar"><b style={{width:Math.min(100,b.actual/maxBudget*100)+'%'}}/></i></button>):<p className="dash-empty">Your budget is ready for allocations.</p>}</div><div className="panel-foot"><span className="chart-key lavender"/> Planned <span className="chart-key mint"/> Actual</div></section>
 <section className="dash-panel"><PanelHead title="Sponsorship pipeline">{go('sponsors')}</PanelHead><div className="bar-list">{pipeline.length?pipeline.map(s=><button key={s.stage} onClick={()=>navigate('sponsors')}><span>{s.stage}<strong>{s.count}</strong></span><i><b style={{width:(s.count/data.sponsors.length*100)+'%'}}/></i></button>):<p className="dash-empty">Add a prospect to start your pipeline.</p>}</div></section>
 <section className="dash-panel"><PanelHead title="Risks & approvals">{go('risks')}</PanelHead><button className="inline-alert" onClick={()=>navigate('approvals')}><CheckCheck size={17}/>{m.pending_approvals} pending approvals<ArrowRight size={14}/></button>{openRisks.slice(0,3).map(r=><button className="simple-row" key={r.id} onClick={()=>navigate('risks')}><ShieldAlert size={14}/>{r.title}<small>{r.severity}</small></button>)}</section>
 <section className="dash-panel"><PanelHead title="Recent activity"/>{data.activity.slice(0,4).map(a=><div className="simple-row" key={a.id}><Radio size={14}/><span>{a.title}</span><small>{timestamp(a.created_at)}</small></div>)}{!data.activity.length&&<p className="dash-empty">Event actions will appear here.</p>}<div className="panel-foot"><CircleCheck size={13}/>{m.actions} automated actions <Target size={13}/>{m.minutes_saved} min estimated savings</div></section>
 </div></div>
}
