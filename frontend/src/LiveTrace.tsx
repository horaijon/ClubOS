import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowDown, CircleCheck, GitBranch, LoaderCircle } from 'lucide-react'
import { AgentMark } from './Identity'
import './trace.css'

export interface TraceStep {
  sequence: number
  trace_id: string
  request_id: string | null
  run_id: string
  parent_run_id: string | null
  kind: string
  agent_name: string
  tool_name: string | null
  reasoning_summary: string
  status: string
  latency_ms: number | null
  timestamp: string
  input_payload: Record<string, unknown>
  output_payload: Record<string, unknown>
}

const terminal = (step: TraceStep) => step.kind === 'run_completed' || step.kind === 'run_failed'
const readable = (value: string) => value.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())

export function useLiveTrace(url: string, onCommit?: () => void, finite = false) {
  const [feed, setFeed] = useState<{url: string; steps: TraceStep[]; connected: boolean}>({url: '', steps: [], connected: false})
  const commit = useRef(onCommit)
  useEffect(() => {commit.current = onCommit}, [onCommit])

  useEffect(() => {
    if (!url) return
    let live = true
    let commitTimer: ReturnType<typeof setTimeout>
    const source = new EventSource(url)
    const connection = (connected: boolean) => {
      if (live) setFeed(current => ({url, steps: current.url === url ? current.steps : [], connected}))
    }
    source.onopen = () => connection(true)
    source.onerror = () => connection(false)
    source.onmessage = ({data}) => {
      if (!live) return
      const step: TraceStep = JSON.parse(data)
      setFeed(current => {
        const steps = current.url === url ? current.steps : []
        if (steps.some(item => item.sequence === step.sequence)) return current
        return {url, steps: [...steps.slice(-249), step], connected: true}
      })
      if (step.kind === 'state_updated' && commit.current) {
        clearTimeout(commitTimer)
        commitTimer = setTimeout(() => commit.current?.(), 180)
      }
      if (finite && terminal(step)) source.close()
    }
    return () => {
      live = false
      clearTimeout(commitTimer)
      source.close()
    }
  }, [url, finite])

  return feed.url === url ? feed : {steps: [], connected: false}
}

export function TraceView({steps, connected, requestId, compact = false, plain = false}: {
  steps: TraceStep[]; connected?: boolean; requestId?: string; compact?: boolean; plain?: boolean
}) {
  const [selected, setSelected] = useState('')
  const list=useRef<HTMLOListElement>(null)
  const filtered = requestId ? steps.filter(step => step.request_id === requestId) : steps
  const flows = new Map<string, {label: string; latest: TraceStep}>()
  for (const step of filtered) {
    const existing = flows.get(step.trace_id)
    const trigger = step.input_payload.trigger
    flows.set(step.trace_id, {
      label: typeof trigger === 'string' ? readable(trigger) : existing?.label || 'Workflow',
      latest: step,
    })
  }
  const choices = [...flows.entries()].reverse()
  const id = flows.has(selected) && !compact ? selected : choices[0]?.[0]
  const current = id ? flows.get(id) : undefined
  const rows = filtered.filter(step => step.trace_id === id)
  const calls = new Map(rows.filter(step => step.kind === 'tool_called').map(step => [step.run_id, step]))
  const completedTools = new Set(rows.filter(step => step.kind === 'tool_finished').map(step => step.run_id))
  const timeline = rows.filter(step =>
    ['handoff', 'tool_finished', 'proposal_created', 'state_updated', 'run_completed', 'run_failed'].includes(step.kind) ||
    step.kind === 'agent_started' && !step.parent_run_id ||
    step.kind === 'tool_called' && !completedTools.has(step.run_id))
  const running = Boolean(current && !terminal(current.latest))
  const latestSequence=current?.latest.sequence
  useEffect(()=>{
    if(compact&&list.current)list.current.scrollTop=list.current.scrollHeight
  },[compact,latestSequence])

  return <section className={'trace-panel'+(compact?' trace-compact':'')} aria-label="Live orchestration trace">
    <header className="trace-head">
      <h2><Activity size={17}/> Live orchestration trace</h2>
      <span className="trace-connection" data-live={connected}>{running ? 'Running' : connected ? 'Connected' : current&&terminal(current.latest) ? 'Recorded' : 'Connecting'}</span>
    </header>
    {choices.length>1&&!compact&&<label className="trace-choice"><span>Workflow</span><select value={id} onChange={event=>setSelected(event.target.value)}>
      {choices.map(([key, flow])=><option value={key} key={key}>{flow.label} · {new Date(flow.latest.timestamp).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</option>)}
    </select></label>}
    {current ? <ol ref={list} className="trace-timeline" aria-label={current.label}>{(compact?timeline.slice(-8):timeline).map(step=>{
      const call=calls.get(step.run_id)
      return <li key={step.sequence} className={step.kind==='handoff'?'trace-handoff':''}>
        {step.kind==='handoff'?<GitBranch size={16}/>:step.kind==='tool_called'?<LoaderCircle size={16} className="spin"/>:<AgentMark name={step.agent_name}/>}
        <div className="trace-body"><strong>{step.kind==='handoff'?'Nexus → '+step.agent_name:step.tool_name?step.agent_name+' · '+readable(step.tool_name):readable(step.kind)}</strong>
          <p>{step.reasoning_summary}</p>
          {step.kind==='tool_finished'&&(!plain||Object.keys(step.output_payload).length>0)&&<details><summary>Tool details{!plain&&step.latency_ms!==null?` · ${step.latency_ms} ms`:''}</summary>
            <div className="trace-payload">{!plain&&<><span>Run {step.run_id}{step.parent_run_id&&<> · Parent {step.parent_run_id}</>}</span><br/><span>Input</span><pre>{JSON.stringify(call?.input_payload||{},null,2)}</pre></>}
              <span>Output</span><pre>{JSON.stringify(step.output_payload,null,2)}</pre></div>
          </details>}
        </div>
        {step.kind==='run_completed'?<CircleCheck size={16}/>:step.kind==='proposal_created'?<ArrowDown size={16}/>:null}
      </li>
    })}</ol> : <p className="trace-empty">{requestId?'Waiting for Nexus to start this workflow.':'Start a workflow or run an agent check to see the handoffs here.'}</p>}
  </section>
}
