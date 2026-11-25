import { useState } from 'react'
import { Activity, ArrowRight, Check, ChevronRight, CircuitBoard, FlaskConical, Play, ScanLine, ShieldAlert, X } from 'lucide-react'
import { AgentMark, agentIdentity } from '../Identity'
import { Button, Dialog, Empty, Head, Notice, Panel, Pill, StatGrid, Tabs, day, human, money, useAction } from './ui'
import type { Row, ViewProps } from './ui'
import { Terms } from './Sponsors'
import type { Metrics } from '../data'

export const scenarios=[
  {id:'demo_withdraw',name:'Sponsor withdrawal',desc:'Withdraw the unpaid ₹20,000 demo commitment. Ledger recalculates funding and Nexus requests approval for a recovery plan.'},
  {id:'demo_delay',name:'Critical task delay',desc:'Record a delay to a critical task and assess the effect on dependent deadlines.'},
  {id:'demo_registration',name:'Registration shortfall',desc:'Check the demo registration milestone and prepare a promotional response.'},
  {id:'demo_agreement',name:'Sponsorship agreement',desc:'Analyze sample terms and review payment and deliverable actions.'},
  {id:'demo_response',name:'Conditional sponsor offer',desc:'Analyze a sample reply and review the proposed negotiation steps.'},
  {id:'demo_deadline',name:'Deliverable deadline',desc:'Check a sponsor deliverable approaching its deadline and review a corrective plan.'},
]
export function Risks({data,act,navigate}:ViewProps) {
  const [tab,setTab]=useState('Risk register'),[confirm,setConfirm]=useState<Row|null>(null)
  const state=useAction(act),risks:Row[]=data.risks
  const runDemo=()=>{if(confirm)state.run(confirm.id,{},undefined,r=>{setConfirm(null);setTab('Risk register');if(r.approval_id)navigate('approvals')})}
  return <><Head title="Risk & recovery" sub="Inspect the issue, follow the agent response and review proposed changes." action={<Button onClick={()=>state.run('risk_scan',{},'Risk scan completed.')} busy={state.busy}><ScanLine/> Scan event</Button>}/>
    <StatGrid items={[{label:'Active risks',value:data.metrics.active_risks,tone:'amber'},{label:'Pending approvals',value:data.metrics.pending_approvals,tone:'purple'},{label:'Projected shortfall',value:money(data.metrics.shortfall),tone:data.metrics.shortfall?'red':undefined}]}/>
    {data.event.is_demo&&<div className="m-toolrow"><Tabs current={tab} onChange={setTab} options={['Risk register','Demo scenarios']}/></div>}<Notice state={state}/>
    {tab==='Risk register' && <div className="m-stack">{risks.map(r=><article key={r.id} className="m-card"><div className="m-titleline"><div className="m-agentinline"><span className="m-symbol amber"><ShieldAlert size={18}/></span><div><h3>{r.title}</h3><span className="m-sub">{human(r.source)} · {day(r.created_at)}</span></div></div><div className="m-agentinline"><Pill>{r.severity}</Pill><Pill>{r.status}</Pill></div></div><p>{r.description}</p>{r.impact&&<p><strong>Impact</strong> · {r.impact}</p>}{r.recommendation&&<p><strong>Recommended response</strong> · {r.recommendation}</p>}<div className="m-titleline"><span className="m-sub">{(r.agents||[]).join(' → ')}</span>{data.approvals.some((a:Row)=>a.risk_id===r.id)&&<Button onClick={()=>navigate('approvals')}>View recovery plan <ArrowRight/></Button>}</div></article>)}{!risks.length&&<Panel><Empty title="No risks detected" detail="Run a scan to check current event conditions."/></Panel>}</div>}
    {tab==='Demo scenarios' && <div className="m-grid">{scenarios.map(s=><article key={s.id} className="m-card"><FlaskConical size={19} className="ink-purple"/><h3 style={{marginTop:12}}>{s.name}</h3><p>{s.desc}</p><Button onClick={()=>setConfirm(s)}><Play/> Run scenario</Button></article>)}</div>}
    {confirm&&<Dialog title={confirm.name} onClose={()=>setConfirm(null)}><Notice state={state}/><p className="m-copy">{confirm.desc}</p><p className="m-copy">This updates the {data.event.name} demo workspace.</p><div className="m-actions"><Button onClick={()=>setConfirm(null)}>Cancel</Button><Button primary onClick={runDemo} busy={state.busy}>Run scenario</Button></div></Dialog>}
  </>
}

function ActionDetail({action:a,data}:{action:Row,data:any}){
  const category=data.budget.find((b:Row)=>b.id===a.category_id)
  const sponsor=data.sponsors.find((s:Row)=>s.id===a.sponsor_id)
  const task=data.tasks.find((t:Row)=>t.id===a.task_id)
  const prospect=data.prospects.find((p:Row)=>p.id===a.prospect_id)
  const details=Object.fromEntries(Object.entries(a).filter(([key])=>!['type','title'].includes(key)&&!key.endsWith('_id')))
  const context=a.type==='reduce_budget' ? null : category?.category || sponsor?.name || task?.title || prospect?.name
  return <li className="m-proposed">
    <div>
      <strong>{a.title||human(a.type)}</strong>
      {context&&<small>{context}</small>}
      {a.type==='reduce_budget' ?
        <small className="m-action-amount">From {money(a.before)} to {money(a.after)}</small> :
        Object.keys(details).length>0&&<details><summary>Action details</summary><Terms terms={details}/></details>}
    </div>
  </li>
}

function BudgetImpact({metrics,actions}:{metrics:Metrics;actions:Row[]}){
  const savings=actions.filter(action=>action.type==='reduce_budget').reduce((sum,action)=>sum+action.saving,0)
  if (!savings) return null
  const plannedAfter=metrics.planned-savings
  const shortfallAfter=Math.max(0,plannedAfter-metrics.projected_funding)
  return <div className="m-budget-impact">
    <h4>Projected impact after approval</h4>
    <table aria-label="Projected budget impact">
      <thead><tr><th scope="col">Budget metric</th><th scope="col">Current</th><th scope="col">Proposed</th></tr></thead>
      <tbody>
        <tr><th scope="row">Planned expenses</th><td>{money(metrics.planned)}</td><td>{money(plannedAfter)}</td></tr>
        <tr><th scope="row">Funding shortfall</th><td>{money(metrics.shortfall)}</td><td>{money(shortfallAfter)}</td></tr>
      </tbody>
    </table>
    {actions.some(action=>action.type==='backup_outreach')&&<p>Backup outreach is a draft. New funding enters the budget when a sponsor confirms.</p>}
  </div>
}

export function Approvals({data,act}:ViewProps){
  const state=useAction(act), [filter,setFilter]=useState('Pending'),[selected,setSelected]=useState<Row|null>(null)
  const approvals:Row[]=data.approvals
  const found=approvals.filter(a=>filter==='History'?a.status!=='Pending':a.status==='Pending')
  return <><Head title="Approvals" sub="Review proposed changes to your event before applying them"/><div className="m-toolrow"><Tabs current={filter} onChange={setFilter} options={['Pending','History']}/><span className="m-sub">{found.length} {filter==='Pending'?'awaiting review':'reviewed'}</span></div><Notice state={state}/>
    <div className="m-stack">{found.map(a=>{
      const risk=data.risks.find((r:Row)=>r.id===a.risk_id),runs:Row[]=data.runs.filter((r:Row)=>r.workflow_id===a.workflow_id)
      return <article key={a.id} className="m-card m-approval"><div className="m-titleline"><div><h3>{a.title}</h3><span className="m-sub">{day(a.created_at,true)} · {a.actions.length} proposed {a.actions.length===1?'action':'actions'}</span></div><Pill>{a.status}</Pill></div><p>{a.description}</p>
      {risk&&<div className="m-riskline"><ShieldAlert size={15}/><strong>{risk.title}</strong><Pill>{risk.severity}</Pill></div>}{risk?.impact&&<p>{risk.impact}</p>}
      {a.status==='Pending'&&<BudgetImpact metrics={data.metrics} actions={a.actions}/>}
      <ul className="m-planlist" aria-label="Proposed actions">{a.actions.map((x:Row,i:number)=><ActionDetail key={i} action={x} data={data}/>)}</ul>{runs.length>0&&<div className="m-workflowchips" aria-label="Agents involved">{[...new Set(runs.map(x=>x.agent))].map(agent=><span key={agent}><AgentMark name={agent}/>{agent}</span>)}</div>}
      {a.status==='Pending'&&<div className="m-actions m-approval-actions"><Button primary busy={state.busy} onClick={()=>setSelected({approval:a,decision:'approve'})}><Check/> Approve plan</Button><Button onClick={()=>setSelected({approval:a,decision:'reject'})} busy={state.busy}><X/> Reject plan</Button></div>}</article>
    })}{!found.length&&<Panel><Empty title={filter==='Pending'?'No approvals waiting':'No reviewed plans yet'} detail={filter==='Pending'?'New agent proposals appear here when an organizer decision is needed.':undefined}/></Panel>}</div>
    {selected&&<Dialog title={selected.decision==='approve'?'Approve and apply this plan?':'Reject this plan?'} onClose={()=>setSelected(null)}><Notice state={state}/><p className="m-copy"><strong>{selected.approval.title}</strong></p>{selected.decision==='approve'&&<BudgetImpact metrics={data.metrics} actions={selected.approval.actions}/>}<p className="m-copy">{selected.decision==='approve'?'ClubOS will apply the listed actions to '+data.event.name+' and record the result in the event history.':'ClubOS will close this proposal and keep the current event data.'}</p><div className="m-actions"><Button autoFocus onClick={()=>setSelected(null)}>Cancel</Button><Button primary={selected.decision==='approve'} danger={selected.decision==='reject'} busy={state.busy} onClick={()=>state.run(selected.decision,{approval_id:selected.approval.id},undefined,()=>{setSelected(null);setFilter('History')})}>{selected.decision==='approve'?'Approve and apply':'Reject proposal'}</Button></div></Dialog>}
  </>
}

export const agentNames=['Nexus','Atlas','Magnet','Ledger','Echo','Relay','Sentinel']
export function Agents({data}:ViewProps){
  const [agent,setAgent]=useState('All agents'),[mode,setMode]=useState('Agent team'),[flow,setFlow]=useState('')
  const runs:Row[]=data.runs
  const flows:Row[]=data.workflows||[]
  const selected=flows.find(f=>f.id===flow)||flows.find(f=>runs.some(r=>r.workflow_id===f.id))
  const currentRuns=runs.filter(r=>r.workflow_id===selected?.id).slice().reverse()
  return <><Head title="Agent command center" sub="Inspect agent responsibilities, validated tool calls and workflow history."/><div className="m-toolrow"><Tabs current={mode} onChange={setMode} options={['Agent team','Workflows','Execution log']}/></div>
    {mode==='Agent team'&&<div className="m-grid">{agentNames.map(name=>{
      const history=runs.filter(r=>r.agent===name),last=history[0]
      return <article key={name} className="m-card"><div className="m-titleline"><AgentMark name={name}/><Pill>{last?.status||'Idle'}</Pill></div><h3 style={{marginTop:14}}>{name}</h3><span className="m-sub">{agentIdentity(name).role}</span><p>{last?.summary||'Waiting for its first event workflow.'}</p><dl className="m-facts"><div><dt>Recorded runs</dt><dd>{history.length}</dd></div>{last&&<div><dt>Last execution</dt><dd>{day(last.created_at,true)}</dd></div>}</dl><div className="m-actions"><Button onClick={()=>{setAgent(name);setMode('Execution log')}}>Execution history <ArrowRight/></Button></div></article>
    })}</div>}
    {mode==='Workflows'&&<div className="m-grid-aside"><Panel title={selected?human(selected.trigger):'Workflow detail'}>{currentRuns.map((r,i)=><div className="m-row" key={r.id}><AgentMark name={r.agent}/><div className="m-rowbody"><strong>{i+1}. {r.agent} · {human(r.tool||r.trigger)}</strong><small>{r.summary}</small><small>{human(r.mode)}</small></div><Pill>{r.status}</Pill></div>)}{!currentRuns.length&&<Empty title="No agent runs in this workflow"/>}</Panel><Panel title="Recent workflows">{flows.filter(f=>runs.some(r=>r.workflow_id===f.id)).map(f=><button className={'m-flowbutton '+(selected?.id===f.id?'selected':'')} key={f.id} onClick={()=>setFlow(f.id)}><CircuitBoard size={17}/><span>{human(f.trigger)}<small>{day(f.created_at,true)}</small></span><ChevronRight size={15}/></button>)}{!flows.length&&<Empty title="No workflows yet"/>}</Panel></div>}
    {mode==='Execution log'&&<Panel title="Execution log" action={<select className="m-select" aria-label="Filter by agent" value={agent} onChange={e=>setAgent(e.target.value)}>{['All agents',...agentNames].map(x=><option key={x}>{x}</option>)}</select>}>{runs.filter(r=>agent==='All agents'||r.agent===agent).map(r=><div className="m-row m-compactrow" key={r.id}><AgentMark name={r.agent}/><div className="m-rowbody"><strong>{r.agent} · {human(r.tool||r.trigger)}</strong><small>{r.summary}</small><small>{human(r.trigger)} · {new Date(r.created_at).toLocaleString('en-IN')}</small></div><Pill>{human(r.mode)}</Pill><Pill>{r.status}</Pill></div>)}{!runs.some(r=>agent==='All agents'||r.agent===agent)&&<Empty title="No executions recorded"/>}</Panel>}
  </>
}
