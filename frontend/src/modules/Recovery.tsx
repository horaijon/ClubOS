import { useState } from 'react'
import { ArrowRight, Check, FlaskConical, Play, ScanLine, ShieldAlert, X } from 'lucide-react'
import { AgentMark, agentIdentity } from '../Identity'
import { Button, Dialog, Empty, Field, formValues, Head, Notice, Panel, Pill, StatGrid, Tabs, day, human, money, useAction } from './ui'
import type { Row, ViewProps } from './ui'
import { Terms } from './Sponsors'
import type { Metrics } from '../data'
import { TraceView } from '../LiveTrace'

export const scenarios=[
  {id:'demo_withdraw',name:'Sponsor withdrawal',desc:'Withdraw the unpaid ₹20,000 demo commitment. Ledger recalculates funding and Nexus requests approval for a recovery plan.'},
  {id:'demo_overrun',name:'Venue cost overrun',desc:'Record a ₹12,000 venue charge and review the funding impact.'},
  {id:'demo_delay',name:'Critical task delay',desc:'Record a delay to a critical task and assess the effect on dependent deadlines.'},
  {id:'demo_registration',name:'Registration shortfall',desc:'Check the demo registration milestone and prepare a promotional response.'},
  {id:'demo_agreement',name:'Sponsorship agreement',desc:'Analyze sample terms and review payment and deliverable actions.'},
  {id:'demo_response',name:'Conditional sponsor offer',desc:'Analyze a sample reply and review the proposed negotiation steps.'},
  {id:'demo_deadline',name:'Deliverable deadline',desc:'Check a sponsor deliverable approaching its deadline and review a corrective plan.'},
]
export function Risks({data,act,navigate,embedded}:ViewProps & {embedded?:boolean}) {
  const [tab,setTab]=useState('Risk register'),[confirm,setConfirm]=useState<Row|null>(null)
  const state=useAction(act),risks:Row[]=data.risks
  const runDemo=()=>{if(confirm)state.run(confirm.id,{},undefined,r=>{setConfirm(null);setTab('Risk register');if(r.approval_id)navigate('approvals')})}
  return <><Head embedded={embedded} title="Risk & recovery" sub="Inspect the issue, follow the agent response and review proposed changes." action={<Button onClick={()=>state.run('risk_scan',{},'Risk scan completed.')} busy={state.busy}><ScanLine/> Scan event</Button>}/>
    <StatGrid items={[{label:'Active risks',value:data.metrics.active_risks,tone:'amber'},{label:'Pending approvals',value:data.metrics.pending_approvals,tone:'purple'},{label:'Projected shortfall',value:money(data.metrics.shortfall),tone:data.metrics.shortfall?'red':undefined}]}/>
    {data.event.id==='codestorm-2026'&&<div className="m-toolrow"><Tabs current={tab} onChange={setTab} options={['Risk register','Demo scenarios']}/></div>}<Notice state={state}/>
    {tab==='Risk register' && <div className="m-stack">{risks.map(r=><article key={r.id} className="m-card"><div className="m-titleline"><div className="m-agentinline"><span className="m-symbol amber"><ShieldAlert size={18}/></span><div><h3>{r.title}</h3><span className="m-sub">{human(r.source)} · {day(r.created_at)}</span></div></div><div className="m-agentinline"><Pill>{r.severity}</Pill><Pill>{r.status}</Pill></div></div><p>{r.description}</p>{r.impact&&<p><strong>Impact</strong> · {r.impact}</p>}{r.recommendation&&<p><strong>Recommended response</strong> · {r.recommendation}</p>}<div className="m-titleline"><span className="m-sub">{(r.agents||[]).join(' → ')}</span>{data.approvals.some((a:Row)=>a.risk_id===r.id)&&<Button onClick={()=>navigate('approvals')}>View recovery plan <ArrowRight/></Button>}</div></article>)}{!risks.length&&<Panel><Empty title="No risks detected" detail="Run a scan to check current event conditions."/></Panel>}</div>}
    {tab==='Demo scenarios' && <div className="m-grid">{scenarios.map(s=><article key={s.id} className="m-card"><FlaskConical size={19} className="ink-purple"/><h3 style={{marginTop:12}}>{s.name}</h3><p>{s.desc}</p><Button onClick={()=>setConfirm(s)}><Play/> Run scenario</Button></article>)}</div>}
    {confirm&&<Dialog title={confirm.name} onClose={()=>setConfirm(null)}><Notice state={state}/><p className="m-copy">{confirm.desc}</p><p className="m-copy">This updates the {data.event.name} demo workspace.</p><div className="m-actions"><Button onClick={()=>setConfirm(null)}>Cancel</Button><Button primary onClick={runDemo} busy={state.busy}>Run scenario</Button></div></Dialog>}
  </>
}

function ActionDetail({action:a,data,edit}:{action:Row,data:any,edit?:()=>void}){
  const category=data.budget.find((b:Row)=>b.id===a.category_id)
  const sponsor=data.sponsors.find((s:Row)=>s.id===a.sponsor_id)
  const task=data.tasks.find((t:Row)=>t.id===a.task_id)
  const prospect=data.prospects.find((p:Row)=>p.id===a.prospect_id)
  const details=Object.fromEntries(Object.entries(a).filter(([key])=>!['type','title'].includes(key)&&!key.endsWith('_id')))
  const context=['reduce_budget','reallocate_budget'].includes(a.type) ? null : category?.category || sponsor?.name || task?.title || prospect?.name
  return <li className="m-proposed">
    <div>
      <strong>{a.title||human(a.type)}</strong>
      {context&&<small>{context}</small>}
      {['reduce_budget','reallocate_budget'].includes(a.type) ?
        <small className="m-action-amount">From {money(a.before)} to {money(a.after)}{a.type==='reallocate_budget'&&<> · Destination {money(a.destination_before)} → {money(a.destination_after)}</>}</small> :
        Object.keys(details).length>0&&<details><summary>Action details</summary><Terms terms={details}/></details>}
    </div>
    {edit&&<Button onClick={edit}>Edit</Button>}
  </li>
}

function BudgetImpact({metrics,actions}:{metrics:Metrics;actions:Row[]}){
  const savings=actions.filter(action=>action.type==='reduce_budget').reduce((sum,action)=>sum+action.saving,0)
  if (!savings) return null
  const plannedAfter=metrics.planned-savings
  const shortfallAfter=Math.max(0,metrics.exposure-savings-metrics.projected_funding)
  return <div className="m-budget-impact">
    <h4>Projected impact after approval</h4>
    <table aria-label="Projected budget impact">
      <thead><tr><th scope="col">Budget metric</th><th scope="col">Current</th><th scope="col">Proposed</th></tr></thead>
      <tbody>
        <tr><th scope="row">Planned expenses</th><td>{money(metrics.planned)}</td><td>{money(plannedAfter)}</td></tr>
        <tr><th scope="row">Projected balance</th><td>{money(metrics.balance)}</td><td>{money(metrics.balance+savings)}</td></tr>
        <tr><th scope="row">Funding shortfall</th><td>{money(metrics.shortfall)}</td><td>{money(shortfallAfter)}</td></tr>
      </tbody>
    </table>
    {actions.some(action=>action.type==='backup_outreach')&&<p>Backup outreach is a draft. New funding enters the budget when a sponsor confirms.</p>}
  </div>
}

export function Approvals({data,act,embedded}:ViewProps & {embedded?:boolean}){
  const state=useAction(act), [filter,setFilter]=useState('Pending'),[selected,setSelected]=useState<Row|null>(null)
  const [editing,setEditing]=useState<{id:string;index:number;action:Row}|null>(null)
  const editable=['reduce_budget','reallocate_budget','move_deadline','backup_outreach','campaign']
  const approvals:Row[]=data.approvals
  const found=approvals.filter(a=>filter==='History'?a.status!=='Pending':a.status==='Pending')
  return <><Head embedded={embedded} title="Approvals" sub="Review proposed changes to your event before applying them"/><div className="m-toolrow"><Tabs current={filter} onChange={setFilter} options={['Pending','History']}/><span className="m-sub">{found.length} {filter==='Pending'?'awaiting review':'reviewed'}</span></div><Notice state={state}/>
    <div className="m-stack">{found.map(a=>{
      const risk=data.risks.find((r:Row)=>r.id===a.risk_id),runs:Row[]=data.runs.filter((r:Row)=>r.workflow_id===a.workflow_id)
      return <article key={a.id} className="m-card m-approval"><div className="m-titleline"><div><h3>{a.title}</h3><span className="m-sub">{day(a.created_at,true)} · {a.actions.length} proposed {a.actions.length===1?'action':'actions'}</span></div><Pill>{a.status}</Pill></div><p>{a.description}</p>
      {risk&&<div className="m-riskline"><ShieldAlert size={15}/><strong>{risk.title}</strong><Pill>{risk.severity}</Pill></div>}{risk?.impact&&<p>{risk.impact}</p>}
      {a.status==='Pending'&&<BudgetImpact metrics={data.metrics} actions={a.actions}/>}
      <ul className="m-planlist" aria-label="Proposed actions">{a.actions.map((x:Row,i:number)=><ActionDetail key={i} action={x} data={data} edit={a.status==='Pending'&&editable.includes(x.type)?()=>setEditing({id:a.id,index:i,action:x}):undefined}/>)}</ul>{runs.length>0&&<div className="m-workflowchips" aria-label="Agents involved">{[...new Set(runs.map(x=>x.agent))].map(agent=><span key={agent}><AgentMark name={agent}/>{agent}</span>)}</div>}
      {a.status==='Pending'&&<div className="m-actions m-approval-actions"><Button primary busy={state.busy} onClick={()=>setSelected({approval:a,decision:'approve'})}><Check/> Approve plan</Button><Button onClick={()=>setSelected({approval:a,decision:'reject'})} busy={state.busy}><X/> Reject plan</Button></div>}</article>
    })}{!found.length&&<Panel><Empty title={filter==='Pending'?'No approvals waiting':'No reviewed plans yet'} detail={filter==='Pending'?'New agent proposals appear here when an organizer decision is needed.':undefined}/></Panel>}</div>
    {editing&&<Dialog title="Edit proposed action" onClose={()=>setEditing(null)}>
      <Notice state={state}/>
      <form className="m-form" onSubmit={event=>{
        const form=formValues(event)
        state.run('edit_approval',{approval_id:editing.id,index:editing.index,...form,...(form.amount?{amount:Math.round(Number(form.amount)*100)}:{})},undefined,()=>setEditing(null))
      }}>
        <p className="m-copy">{editing.action.title}</p>
        {editing.action.type==='move_deadline'?<Field label="Proposed deadline"><input type="date" name="date" required defaultValue={editing.action.after}/></Field>:
          ['campaign','backup_outreach'].includes(editing.action.type)?<Field label="Draft text"><textarea name="text" rows={8} required defaultValue={editing.action.text||editing.action.body}/></Field>:
          <Field label="Proposed adjustment (₹)"><input type="number" name="amount" min=".01" step=".01" required defaultValue={(editing.action.saving||editing.action.amount)/100}/></Field>}
        <Button primary type="submit" busy={state.busy}>Save proposal</Button>
      </form>
    </Dialog>}
    {selected&&<Dialog title={selected.decision==='approve'?'Approve and apply this plan?':'Reject this plan?'} onClose={()=>setSelected(null)}><Notice state={state}/><p className="m-copy"><strong>{selected.approval.title}</strong></p>{selected.decision==='approve'&&<BudgetImpact metrics={data.metrics} actions={selected.approval.actions}/>}<p className="m-copy">{selected.decision==='approve'?'ClubOS will apply the listed actions to '+data.event.name+' and record the result in the event history.':'ClubOS will close this proposal and keep the current event data.'}</p><div className="m-actions"><Button autoFocus onClick={()=>setSelected(null)}>Cancel</Button><Button primary={selected.decision==='approve'} danger={selected.decision==='reject'} busy={state.busy} onClick={()=>state.run(selected.decision,{approval_id:selected.approval.id},undefined,()=>{setSelected(null);setFilter('History')})}>{selected.decision==='approve'?'Approve and apply':'Reject proposal'}</Button></div></Dialog>}
  </>
}

export const agentNames=['Nexus','Atlas','Magnet','Ledger','Echo','Relay','Sentinel']
export function Agents({data,act,trace,traceConnected}:ViewProps){
  const state=useAction(act)
  const runs:Row[]=data.runs
  const lastByRun=new Map(trace.map(step=>[step.run_id,step]))
  const pendingWorkflows=new Set(data.approvals.filter((approval:Row)=>approval.status==='Pending').map((approval:Row)=>approval.workflow_id))
  return <><Head title="Agent Orchestrator" sub="Watch handoffs, inspect tool calls, and run checks against the current event."/>
    <TraceView steps={trace} connected={traceConnected}/>
    <Notice state={state}/>
    <div className="m-grid agent-roster">{agentNames.map(name=>{
      const history=runs.filter(r=>r.agent===name)
      const running=[...lastByRun.values()].some(step=>step.agent_name===name&&step.status==='Running')
      const waiting=history.some(run=>pendingWorkflows.has(run.workflow_id))
      return <article key={name} className="m-card"><div className="m-titleline"><AgentMark name={name}/><Pill>{running?'Running':waiting?'Waiting Approval':'Idle'}</Pill></div>
        <h3>{name}</h3><span className="m-sub">{agentIdentity(name).role}</span>
        <dl className="m-facts"><div><dt>Recorded tool runs</dt><dd>{history.length}</dd></div></dl>
        <details className="agent-tools"><summary>Owned tools</summary><ul>{(data.agent_tools[name]||[]).map((tool:string)=><li key={tool}>{human(tool)}</li>)}</ul></details>
        <div className="m-actions"><Button busy={state.busy} onClick={()=>state.run('agent_check',{agent:name})}><Play/> Run {name} check</Button></div>
      </article>
    })}</div>
  </>
}
