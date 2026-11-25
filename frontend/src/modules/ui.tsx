import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { CheckCircle2, Inbox, LoaderCircle, Search, X } from 'lucide-react'

export interface ModuleProps {
  page: string
  data: any
  act: (type: string, payload?: Record<string, any>) => Promise<any>
  navigate: (page: string) => void
  refresh: () => Promise<void>
}
export type Row = Record<string, any>
export type ViewProps = Pick<ModuleProps, 'data' | 'act' | 'navigate'>
export const money = (value: number = 0) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value / 100)
export function day(value?: string, year = false) {
  if (!value) return 'No date'
  const d = new Date(value.length === 10 ? value + 'T12:00:00' : value)
  return isNaN(+d) ? value : d.toLocaleDateString('en-IN', {day:'numeric',month:'short',...(year ? {year:'numeric'} : {})})
}
export const human = (v: any) => String(v ?? '').replace(/[_-]/g, ' ').replace(/^./, x => x.toUpperCase())
export const initials = (s: string) => (s || 'Club').split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase()
export function Head({title,sub,action}:{title:string,sub:string,action?:ReactNode}) {
  return <header className="m-head"><div><h1>{title}</h1><p>{sub}</p></div>{action}</header>
}
export function StatGrid({items}:{items: {label:string,value:ReactNode,detail?:ReactNode,tone?:string}[]}) {
  return <div className="m-stats">{items.map(item => <div className="m-stat" key={item.label}><span>{item.label}</span><strong className={item.tone ? 'ink-'+item.tone : ''}>{item.value}</strong>{item.detail && <small>{item.detail}</small>}</div>)}</div>
}
export function Tabs({options,current,onChange}:{options:string[],current:string,onChange:(val:string)=>void}) {
  return <div className="m-tabs" aria-label="Views">{options.map(x=><button key={x} type="button" aria-pressed={current===x} onClick={()=>onChange(x)}>{x}</button>)}</div>
}
export function Pill({children,tone}:{children:ReactNode,tone?:string}) {
  const v=String(children).toLowerCase()
  const color=tone || (/approved|confirmed|complete|paid|checked|resolved|executed/.test(v)?'mint':/high|critical|declined|reject|withdraw|failed|blocked|overdue/.test(v)?'red':/pending|risk|negotiat|waiting|review|medium/.test(v)?'amber':/progress|draft|shortlist|running|active/.test(v)?'purple':'neutral')
  return <span className={'m-pill pill-'+color}>{children}</span>
}
export function Panel({title,action,children}:{title?:string,action?:ReactNode,children:ReactNode}) {
  return <section className="m-panel">{title && <div className="m-panelhead"><h2>{title}</h2>{action}</div>}{children}</section>
}
export function Empty({title,detail}:{title:string,detail?:string}) {
  return <div className="m-empty"><Inbox size={23}/><strong>{title}</strong>{detail && <small>{detail}</small>}</div>
}
export function SearchBox({value,onChange,placeholder}:{value:string,onChange:(v:string)=>void,placeholder:string}) {
  return <label className="m-search"><Search size={16}/><input type="search" value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}/></label>
}
export function Dialog({title,children,onClose}:{title:string,children:ReactNode,onClose:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null)
  const titleId=useId()
  useEffect(()=>{const node=ref.current; node?.showModal();return ()=>node?.close()},[])
  return <dialog className="m-dialog m-view" aria-labelledby={titleId} ref={ref} onCancel={e=>{e.preventDefault();onClose()}} onClick={e=>{if(e.target===e.currentTarget)onClose()}}><div className="m-dialoginner"><div className="m-dialoghead"><h2 id={titleId}>{title}</h2><button type="button" className="m-icon" aria-label="Close dialog" onClick={onClose}><X size={18}/></button></div>{children}</div></dialog>
}
export function Field({label,children}:{label:string,children:ReactNode}) {
  return <label className="m-field"><span>{label}</span>{children}</label>
}
export function useAction(act:ModuleProps['act']){
  const [busy,setBusy]=useState(false), [error,setError]=useState(''), [message,setMessage]=useState('')
  const lock=useRef(false)
  async function run(action:string,payload:Row={},success?:string,done?:(result:any)=>void) {
    if (lock.current) return
    setError(''); setMessage(''); lock.current=true; setBusy(true)
    try {
      const result=await act(action,payload)
      done?.(result)
      if(success)setMessage(success)
    } catch(e) {setError(e instanceof Error?e.message:'The operation could not be completed. Please try again.')}
    finally {lock.current=false;setBusy(false)}
  }
  return {busy,error,message,run,clear:()=>{setError('');setMessage('')}}
}
export type ActionState = ReturnType<typeof useAction>
export function Notice({state}:{state:ActionState}){
  if (!state.error && !state.message) return null
  return <div role={state.error?'alert':'status'} className={'m-notice '+(state.error?'error':'success')}><CheckCircle2 size={16}/>{state.error || state.message}<button onClick={state.clear} aria-label="Dismiss message"><X size={14}/></button></div>
}
export function Button({children,onClick,busy=false,primary=false,danger=false,disabled=false,type='button'}:{children:ReactNode,onClick?:()=>void,busy?:boolean,primary?:boolean,danger?:boolean,disabled?:boolean,type?:'submit'|'button'}){
  return <button type={type} className={'m-btn '+(primary?'primary ': '')+(danger?'danger':'')} disabled={busy||disabled} onClick={onClick}>{busy && <LoaderCircle className="m-spin" size={15}/>} {children}</button>
}
export function formValues(event: FormEvent<HTMLFormElement>):Row {
  event.preventDefault()
  return Object.fromEntries(new FormData(event.currentTarget))
}
export function CopyButton({value}:{value:string}){
  const [message,setMessage]=useState('')
  return <><Button onClick={async()=>{try {await navigator.clipboard.writeText(value);setMessage('Copied')} catch {setMessage('Select the draft text to copy it manually.')}}}>Copy text</Button>{message && <small role="status">{message}</small>}</>
}
