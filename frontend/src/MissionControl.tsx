import {useState,type FormEvent} from 'react'
import {ArrowRight, QrCode} from 'lucide-react'
import {Dialog} from './Dialog'
import {TraceView} from './LiveTrace'
import {api, money, shortDate, type RegistrationForm} from './data'
import {Button, CopyButton, Head, Notice, Panel, useAction, day, type Row, type ViewProps} from './modules/ui'
import './modules.css'
import './launch.css'

function RegistrationLinks({form}:{form:RegistrationForm}){
  const [qr,setQr]=useState(false)
  const link=form.public_url||location.origin+'/register/'+form.slug
  return <><a className="registration-link" href={link} target="_blank" rel="noreferrer">{link}</a>
    <div className="m-actions"><CopyButton value={link}/><a className="m-btn" href={link} target="_blank" rel="noreferrer">Open public form <ArrowRight size={14}/></a>
      <Button onClick={()=>setQr(true)}><QrCode size={15}/> QR code</Button></div>
    {qr&&<Dialog compact title="Registration QR code" onClose={()=>setQr(false)}><img className="registration-qr" src={'/api/registration/'+form.slug+'/qr.svg'} alt="QR code for the public registration form"/></Dialog>}
  </>
}

export default function MissionControl({data,act,navigate,trace,traceConnected,onCreate}:ViewProps & {onCreate:()=>void}){
  const action=useAction(act), m=data.metrics, e=data.event, form=data.registration_form
  const pending:Row[]=data.approvals.filter((item:Row)=>item.status==='Pending')
  const stages=(name:string)=>data.sponsors.filter((partner:Row)=>partner.stage===name).length
  return <div className="m-view">
    <Head title="Mission Control" sub={e.name+' · '+shortDate(e.start_date,true)+' · '+e.college} action={<Button primary onClick={onCreate}>New event</Button>}/>
    <Notice state={action}/>
    <div className="mission-outcomes">
      <section className="m-card"><h3>Registration form</h3><p><strong>{m.registered} / {m.target}</strong> registered</p>
        {form?<><p>Closes {shortDate(form.deadline,true)}</p><RegistrationLinks form={form}/></>:<Button onClick={()=>navigate('registrations')}>Publish registration form</Button>}
      </section>
      <section className="m-card"><h3>Sponsorship progress</h3><p><strong>{money(m.committed)}</strong> secured of {money(e.sponsorship_target)}</p>
        <progress aria-label="Sponsorship funding" value={Math.min(m.committed,e.sponsorship_target)} max={e.sponsorship_target||1}/>
        <p>{stages('Contacted')} contacted · {stages('Responded')} replied · {stages('Confirmed')} confirmed</p>
        <div className="m-actions"><Button onClick={()=>navigate('sponsors')}>View sponsors</Button>{stages('Outreach Drafted')>0&&<Button busy={action.busy} onClick={()=>action.run('prepare_outreach')}>Prepare outreach</Button>}</div>
      </section>
      <section className="m-card"><h3>Budget & readiness</h3><p><strong>{money(m.projected_funding)}</strong> secured of {money(m.planned)} planned</p>
        <p>{money(e.initial_budget)} club funds · {money(m.committed)} confirmed sponsors</p>
        <Button onClick={()=>navigate('finance')}>Open plan & budget</Button>
      </section>
    </div>
    <div className="mission-feed">
      <TraceView steps={trace} connected={traceConnected} plain/>
      <Panel title="Needs your approval">
        {pending.length?<div className="m-pad m-stack">{pending.slice(0,5).map(item=><article className="m-card" key={item.id}>
          <h3>{item.title}</h3><p>{item.description}</p>
          <div className="m-actions"><Button primary busy={action.busy} onClick={()=>action.run('approve',{approval_id:item.id})}>Approve</Button><Button busy={action.busy} onClick={()=>action.run('reject',{approval_id:item.id})}>Reject</Button></div>
        </article>)}</div>:<div className="m-pad"><p>No decisions pending.</p></div>}
        <div className="m-pad"><Button onClick={()=>navigate('approvals')}>Review approval history</Button></div>
      </Panel>
    </div>
    {e.id==='codestorm-2026'&&<div className="m-actions"><Button onClick={()=>navigate('risks')}>Simulate disruption</Button></div>}
  </div>
}

const fieldOptions={team_name:'Team name',team_size:'Team size',track:'Track',github:'GitHub link',college:'College / university',diet:'Dietary requirements',experience:'Experience level',accessibility:'Accessibility requirements'}
export function Registrations({data,act,refresh}:ViewProps & {refresh:()=>Promise<void>}){
  const [editing,setEditing]=useState(false),[query,setQuery]=useState(''),[message,setMessage]=useState('')
  const action=useAction(act), form:RegistrationForm|null=data.registration_form
  const participants:Row[]=data.participants
  const filtered=participants.filter(p=>p.name.toLowerCase().includes(query.trim().toLowerCase()))
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    const fields=new FormData(event.currentTarget)
    try{await api('/api/events/'+data.event.id+'/registration',{method:'PUT',body:JSON.stringify({deadline:fields.get('deadline'),fields:fields.getAll('field')})});setEditing(false);setMessage('Registration form saved.');await refresh()}
    catch(err){setMessage((err as Error).message)}
  }
  function exportCsv(){
    const cols=Object.keys(fieldOptions)
    const safe=(value:unknown)=>'"'+String(value??'').replace(/^[=+\-@\t\r]/,"'$&").replaceAll('"','""')+'"'
    const content=[['Name','Email','Checked in',...Object.values(fieldOptions)],...participants.map(p=>[p.name,p.email,p.checked_in?'Yes':'No',...cols.map(key=>p.answers?.[key])])].map(row=>row.map(safe).join(',')).join('\r\n')
    const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'}))
    const link=document.createElement('a');link.href=url;link.download='clubos-registrations.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  return <><Head title="Registrations & Form" sub={data.event.name} action={<Button onClick={()=>setEditing(true)}>{form?'Edit form':'Publish form'}</Button>}/>
    {message&&<p role="status">{message}</p>}<Notice state={action}/>
    {form&&<section className="m-card"><h3>Public registration form</h3><p>Closes {day(form.deadline,true)} · Full name, email{form.fields.map(field=>', '+field.label)}</p><RegistrationLinks form={form}/></section>}
    <Panel title={participants.length+' registrations'} action={<Button onClick={exportCsv}>Export CSV</Button>}>
      <div className="m-pad"><label className="m-field">Search participants<input type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
      <div className="m-tablewrap"><table className="m-table"><thead><tr><th>Name</th><th>Email</th>{form?.fields.map(field=><th key={field.key}>{field.label}</th>)}<th>Attendance</th></tr></thead>
      <tbody>{filtered.map(p=><tr key={p.id}><td>{p.name}</td><td>{p.email}</td>{form?.fields.map(field=><td key={field.key}>{p.answers?.[field.key]}</td>)}<td>{p.checked_in?'Checked in':<Button busy={action.busy} onClick={()=>action.run('check_in',{participant_id:p.id})}>Check in</Button>}</td></tr>)}</tbody></table></div>
    </Panel>
    {editing&&<Dialog title="Registration form settings" onClose={()=>setEditing(false)}><form className="m-form m-pad" onSubmit={save}>
      <label className="m-field">Registration deadline<input name="deadline" type="date" required defaultValue={form?.deadline||data.event.start_date} max={data.event.start_date}/></label>
      <fieldset><legend>Additional fields</legend>{Object.entries(fieldOptions).map(([key,label])=><label className="m-row" key={key}><input name="field" value={key} type="checkbox" defaultChecked={form?.fields.some(field=>field.key===key)}/>{label}</label>)}</fieldset>
      <Button primary type="submit">Save public form</Button>
    </form></Dialog>}
  </>
}
