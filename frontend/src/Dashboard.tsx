import { useMemo, useState, type ReactNode } from 'react';
import { ArrowRight, ArrowUpRight, CalendarDays, CheckCheck, CircleCheck, Clock3, Layers3, MapPin, Radio, ShieldAlert, Target, TrendingUp, Users, Wallet, Zap, ListChecks, type LucideIcon } from 'lucide-react';
import { AgentMark } from './Identity';
import { dateOf, money, ratio, shortDate, type Snapshot } from './data';

import { AutomationChart, PeriodControl, Trends, type Period } from './DashboardAnalytics';
import './dashboard.css';

type Props={data:Snapshot;navigate:(page:string)=>void; view?:'overview'|'trends'};
const stages=['Identified','Shortlisted','Outreach Drafted','Contacted','Responded','Negotiating','Confirmed','Declined','Withdrawn'];
function Metric({title,value,icon:Icon,children,onClick,featured=false}:{
 title:string;value:ReactNode;icon:LucideIcon;children:ReactNode;onClick:()=>void;featured?:boolean;
}){
 return <button className={featured?"metric metric-featured":"metric"} onClick={onClick}>
  <span className="metric-head">{title}<span className="metric-mark"><Icon size={17} aria-hidden="true"/></span></span>
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
 return <section className="dash-panel readiness-board">
  <div className="readiness-heading"><h3>Event readiness</h3><strong>{score}%</strong></div>
  <ul className="readiness-lanes">
   {rows.map(({label, value, warning}) => <li key={label} className={warning?'below-target':undefined}>
    <span>{label}</span>
    <span className="readiness-track" aria-hidden="true"><span style={{width:Math.min(100,Math.max(0,value))+'%'}}/></span>
    <strong>{value}%</strong>
   </li>)}
  </ul>
 </section>;
}

function timestamp(value:string){
 const date=dateOf(value), age=Math.max(0,(Date.now()-date.getTime())/60000);
 if(age<1)return 'Just now';if(age<60)return Math.floor(age)+'m ago';if(age<1440)return Math.floor(age/60)+'h ago';return shortDate(value);
}
export default function Dashboard({data,navigate,view='overview'}:Props){
 const [days,setDays]=useState<Period>(7);
 const m=data.metrics, e=data.event;
 const registered=ratio(m.registered,m.target);
 const taskPercent=ratio(m.completed,m.total_tasks);
 const funding=ratio(m.projected_funding,m.planned);
 const runs=useMemo(()=>[...data.runs].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,4),[data.runs]);
 const due=useMemo(()=>data.tasks.filter(t=>!['completed','done'].includes(t.status?.toLowerCase())&&t.due_date).sort((a,b)=>a.due_date.localeCompare(b.due_date)).slice(0,4),[data.tasks]);
 const daysLeft=Math.ceil((dateOf(e.start_date).setHours(0,0,0,0)-new Date().setHours(0,0,0,0))/86400000);
 const go=(id:string)=><button className="text-link" onClick={()=>navigate(id)}>View all <ArrowRight size={13}/></button>;
 const pending=m.total_tasks-m.completed;
 const openRisks=data.risks.filter(r=>!['closed','resolved'].includes(r.status?.toLowerCase()));
 const approvals=data.approvals.filter(approval=>approval.status.toLowerCase()==='pending');
 const pipeline=stages.map(stage=>({stage,count:data.sponsors.filter(s=>s.stage.toLowerCase()===stage.toLowerCase()).length})).filter(s=>s.count);
 const maxBudget=Math.max(...data.budget.map(b=>Math.max(b.planned,b.actual)),1);
 const balanceText=m.balance===0?'Budget covered':money(Math.abs(m.balance))+(m.balance<0?' projected shortfall':' projected surplus');

 if(view==='trends')return <Trends data={data} days={days} setDays={setDays}/>;
 return <div className="dashboard dash-workspace">
  <div className="dash-heading">
   <div>
    <h1>Command center</h1>
    <div className="dash-event-context">
     <h2>{e.name}</h2>
     <span><CalendarDays size={15}/>{shortDate(e.start_date,true)}</span>
     {e.venue&&<span><MapPin size={15}/>{e.venue}</span>}
     <span><Clock3 size={15}/>{daysLeft>0?daysLeft+' days to go':daysLeft===0?'Starts today':'Event started'}</span>
    </div>
   </div>
   <div className="dash-heading-actions">
    <PeriodControl value={days} onChange={setDays}/>
    <button className="subtle-button event-report-button" onClick={()=>navigate('reports')}><Layers3 size={16}/> Event reports</button>
   </div>
  </div>
  <div className="dash-summary-grid">
   <section className="dash-funding" aria-labelledby="projected-funding-title">
    <div className="dash-funding-head"><h2 id="projected-funding-title">Projected funding</h2><Wallet size={21} aria-hidden="true"/></div>
    <p className="dash-funding-amount">{money(m.projected_funding)}</p>
    <p className={m.balance<0?'dash-balance shortfall':'dash-balance'}>{balanceText}</p>
    <div className="dash-funding-actions">
     <button className="brand-button" onClick={()=>navigate('finance')}>Open finance</button>
     <button className="subtle-button" onClick={()=>navigate('trends')}><TrendingUp size={16}/> Event trends</button>
    </div>
    <dl className="dash-funding-sources">
     <div><dt>Club funds</dt><dd>{money(e.initial_budget)}</dd></div>
     <div><dt>Sponsor commitments</dt><dd>{money(m.committed)}</dd></div>
     <div><dt>Payments received</dt><dd>{money(m.received)}</dd></div>
    </dl>
   </section>
   <section className="metric-grid dash-metrics" aria-label="Event metrics">
    <Metric title="Agent runs" value={data.runs.length.toLocaleString('en-IN')} icon={Zap} onClick={()=>navigate('agents')} featured>Across this event</Metric>
    <Metric title="Registrations" value={<>{m.registered}<small> / {m.target}</small></>} icon={Users} onClick={()=>navigate('operations')}>{registered}% of target</Metric>
    <Metric title="Task completion" value={<>{taskPercent}<small className="percent-sign">%</small></>} icon={ListChecks} onClick={()=>navigate('tasks')}>{m.completed} of {m.total_tasks} complete</Metric>
    <Metric title="Active risks" value={m.active_risks} icon={ShieldAlert} onClick={()=>navigate('risks')}>
     <span className={m.active_risks?'amber-text':'mint-text'}>{m.active_risks?'Monitoring required':'All clear'}</span>
    </Metric>
   </section>
  </div>
  <div className="dash-detail-grid">
   <AutomationChart data={data} days={days}/>
   <div className="dash-watch">
    <Readiness score={m.readiness} funding={funding} registrations={registered} tasks={taskPercent} underfunded={m.balance<0}/>
    <section className="dash-panel dash-review">
     <PanelHead title="Approvals">{go('approvals')}</PanelHead>
     <p className="dash-review-note">{approvals.length?approvals.length+(approvals.length===1?' decision':' decisions')+' awaiting review':'No decisions awaiting review'}</p>
     {approvals.slice(0,2).map(approval=><button className="simple-row" key={approval.id} onClick={()=>navigate('approvals')}><CheckCheck size={16}/>{approval.title}<ArrowRight size={14}/></button>)}
    </section>
   </div>
  </div>
  <div className="secondary-panels">
 <section className="dash-panel agent-panel"><PanelHead title="Agent activity">{go('agents')}</PanelHead><div className="agent-list">
 {runs.length?runs.map(r=><button key={r.id} onClick={()=>navigate('agents')} className="run-row"><AgentMark name={r.agent}/><span className="run-copy"><strong>{r.agent}<span className="run-timestamp">{timestamp(r.created_at)}</span></strong><span title={r.summary}>{r.summary||r.trigger}</span></span></button>):<p className="dash-empty">Agent runs will appear after the first workflow.</p>}
 </div><div className="panel-foot">{data.runs.length} recorded agent {data.runs.length===1?'run':'runs'}</div></section>

 <section className="dash-panel"><PanelHead title="Upcoming deadlines">{go('tasks')}</PanelHead>{due.length?due.map(t=><button key={t.id} className="deadline-row" onClick={()=>navigate('tasks')}><span className="date-block"><strong>{dateOf(t.due_date).getDate()}</strong><small>{dateOf(t.due_date).toLocaleString('en',{month:'short'})}</small></span><span><strong>{t.title}</strong><small>{t.owner||t.department||'Unassigned'}</small></span><ArrowUpRight size={13}/></button>):<p className="dash-empty">No open deadlines.</p>}<div className="panel-foot">{pending} pending tasks · {m.overdue} overdue</div></section>
 <section className="dash-panel"><PanelHead title="Funding overview">{go('finance')}</PanelHead><div className="finance-rows">{[['Planned expenses',m.planned],['Actual expenses',m.actual],['Sponsor commitments',m.committed],['Sponsorship received',m.received],['Projected balance',m.balance]].map(([label,value])=><div key={label}><span>{label}</span><strong>{money(Number(value))}</strong></div>)}</div></section>
 <section className="dash-panel"><PanelHead title="Budget allocation">{go('finance')}</PanelHead><div className="bar-list">{data.budget.length?data.budget.map(b=><button key={b.id} onClick={()=>navigate('finance')} title={`Planned ${money(b.planned)}, actual ${money(b.actual)}`}><span>{b.category}<strong>{money(b.planned)}</strong></span><i><b style={{width:Math.max(1,b.planned/maxBudget*100)+'%'}}/></i><i className="actual-bar"><b style={{width:Math.min(100,b.actual/maxBudget*100)+'%'}}/></i></button>):<p className="dash-empty">Your budget is ready for allocations.</p>}</div><div className="panel-foot"><span className="chart-key lavender"/> Planned <span className="chart-key mint"/> Actual</div></section>
 <section className="dash-panel"><PanelHead title="Sponsorship pipeline">{go('sponsors')}</PanelHead><div className="bar-list">{pipeline.length?pipeline.map(s=><button key={s.stage} onClick={()=>navigate('sponsors')}><span>{s.stage}<strong>{s.count}</strong></span><i><b style={{width:(s.count/data.sponsors.length*100)+'%'}}/></i></button>):<p className="dash-empty">Add a prospect to start your pipeline.</p>}</div></section>
 <section className="dash-panel"><PanelHead title="Risks & approvals">{go('risks')}</PanelHead><button className="inline-alert" onClick={()=>navigate('approvals')}><CheckCheck size={17}/>{m.pending_approvals} pending approvals<ArrowRight size={14}/></button>{openRisks.slice(0,3).map(r=><button className="simple-row" key={r.id} onClick={()=>navigate('risks')}><ShieldAlert size={14}/>{r.title}<small>{r.severity}</small></button>)}</section>
 <section className="dash-panel"><PanelHead title="Recent activity"/>{data.activity.slice(0,4).map(a=><div className="simple-row" key={a.id}><Radio size={14}/><span>{a.title}</span><small>{timestamp(a.created_at)}</small></div>)}{!data.activity.length&&<p className="dash-empty">Event actions will appear here.</p>}<div className="panel-foot"><CircleCheck size={13}/>{m.actions} automated actions <Target size={13}/>{m.minutes_saved} min estimated savings</div></section>
  </div>
 </div>
}
