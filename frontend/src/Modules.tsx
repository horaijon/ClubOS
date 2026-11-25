import Sponsors from './modules/Sponsors'
import { Tasks, Finance } from './modules/Work'
import { Approvals, Agents, Risks } from './modules/Recovery'
import { Marketing, Operations, Reports, Workspace, Copilot } from './modules/Operations'
import type { ModuleProps, ViewProps } from './modules/ui'
import {useState, type ComponentType} from 'react'
import { Head, Tabs } from './modules/ui'
import './modules.css'

function TasksOps(props:ViewProps){
  const [view,setView]=useState('Tasks')
  return <><Head title="Tasks & Ops" sub="Schedule work, track event-day readiness, and check in participants."/>
    <div className="orchestration-tabs"><Tabs options={['Tasks','Event operations','Campaign drafts']} current={view} onChange={setView}/></div>
    {view==='Tasks'?<Tasks {...props} embedded/>:view==='Event operations'?<Operations {...props} embedded/>:<Marketing {...props} embedded/>}</>
}
function Governance(props:ViewProps){
  const [view,setView]=useState('Approvals')
  return <><Head title="Approvals & Risks" sub="Review incoming proposals and monitor event risks."/>
    <div className="orchestration-tabs"><Tabs options={['Approvals','Risk register']} current={view} onChange={setView}/></div>
    {view==='Approvals'?<Approvals {...props} embedded/>:<Risks {...props} embedded/>}</>
}
const views:Record<string,ComponentType<ViewProps>>={
  sponsors:Sponsors,finance:Finance,tasks:TasksOps,marketing:Marketing,operations:Operations,
  risks:Risks,approvals:Governance,agents:Agents,reports:Reports,copilot:Copilot,'copilot-drawer':props=><Copilot {...props} embedded/>,workspace:Workspace,
}
export default function Modules(props:ModuleProps) {
  const Page=views[props.page]
  if(!Page)return <p role="alert">This page is unavailable.</p>
  return <div className="m-view" key={props.data.event.id+props.page}><Page {...props}/></div>
}
