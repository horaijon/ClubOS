import Sponsors from './modules/Sponsors'
import { Tasks, Finance } from './modules/Work'
import { Approvals, Agents, Risks } from './modules/Recovery'
import { Marketing, Operations, Reports, Workspace, Copilot } from './modules/Operations'
import type { ModuleProps, ViewProps } from './modules/ui'
import type { ComponentType } from 'react'
import './modules.css'

const views:Record<string,ComponentType<ViewProps>>={
  sponsors:Sponsors,finance:Finance,tasks:Tasks,marketing:Marketing,operations:Operations,
  risks:Risks,approvals:Approvals,agents:Agents,reports:Reports,copilot:Copilot,workspace:Workspace,
}
export default function Modules(props:ModuleProps) {
  const Page=views[props.page]
  if(!Page)return <p role="alert">This page is unavailable.</p>
  return <main className="m-view" key={props.data.event.id+props.page}><Page {...props}/></main>
}
