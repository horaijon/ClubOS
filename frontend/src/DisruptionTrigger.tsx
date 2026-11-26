import {useState,type FormEvent} from 'react'
import {MailCheck,Send,ShieldAlert,Zap} from 'lucide-react'
import {Dialog} from './Dialog'
import {DecisionExplainControl} from './DecisionExplain'
import {Button,Notice,Pill,day,useAction,type ViewProps,type Row} from './modules/ui'

export default function DisruptionTrigger({data,act}:Pick<ViewProps,'data'|'act'>){
  const action=useAction(act)
  const [open,setOpen]=useState(false),[kind,setKind]=useState('venue')
  const [scope,setScope]=useState<'session'|'event'>('session')
  const [notify,setNotify]=useState(true)
  const records:Row[]=data.disruptions||[]
  // Past alerts start collapsed; one raised while this page is open expands on its own.
  const [earlier]=useState(()=>new Set(records.map(record=>record.id)))
  const tracks:string[]=data.event_brief?.details?.tracks||[]
  const openTasks:Row[]=data.tasks.filter((task:Row)=>task.status!=='Completed')

  function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    const raw=Object.fromEntries(new FormData(event.currentTarget))
    const payload:Record<string,unknown>={
      kind,
      reason:raw.reason?String(raw.reason).trim():'',
      notify_participants:notify,
    }
    if(kind==='venue'){
      payload.venue=raw.venue
    }else if(kind==='asset'){
      payload.task_id=raw.task_id
      payload.days=Number(raw.days)
      if(raw.asset_name)payload.asset_name=raw.asset_name
    }else if(kind==='cutoff'){
      if(raw.deadline)payload.deadline=raw.deadline
      if(raw.eligibility_note)payload.eligibility_note=raw.eligibility_note
      if(raw.target)payload.target=Number(raw.target)
    }else if(kind==='cancellation'){
      payload.scope=scope
      if(scope==='session'){
        if(raw.task_id)payload.task_id=raw.task_id
        if(raw.track)payload.track=raw.track
      }
    }
    action.run('campus_disruption',payload,undefined,()=>{
      setOpen(false)
    })
  }

  return <section className="m-card disruption-panel">
    <div className="m-titleline">
      <div>
        <h3>Campus Chaos Re-Router</h3>
        <p>Change a venue, deadline or session and alert everyone affected.</p>
      </div>
      <Button onClick={()=>setOpen(true)}><ShieldAlert size={16}/> Trigger disruption</Button>
    </div>
    <Notice state={action}/>
    {records.length>0&&<div className="disruption-list" aria-live="polite">
      {records.map(record=>{
        const notifs:Row[]=record.notifications||[]
        const actionsTaken:string[]=record.actions_taken||[]
        const sentCount=notifs.filter(n=>n.status==='sent').length
        const queuedCount=notifs.filter(n=>n.status==='queued'||n.status==='failed').length
        const simCount=notifs.filter(n=>n.status==='simulated').length
        return <details key={record.id} open={!earlier.has(record.id)} className="disruption-record">
          <summary>
            <span><strong>{record.title}</strong> · {record.changes.length} change{record.changes.length===1?'':'s'}</span>
            {sentCount>0&&<Pill tone="mint">{sentCount} emailed</Pill>}
            {queuedCount>0&&<Pill tone="amber">{queuedCount} queued</Pill>}
            {simCount>0&&sentCount===0&&<Pill tone="neutral">{simCount} demo simulated</Pill>}
            {record.created_at&&<small style={{color:'#64748B',marginLeft:'auto'}}>{day(record.created_at)}</small>}
          </summary>
          {record.summary&&<p className="disruption-summary">{record.summary}</p>}
          {actionsTaken.length>0&&<div className="disruption-actions-strip">
            {actionsTaken.map((item,idx)=><span key={idx} className="disruption-action-chip"><Zap size={12}/> {item}</span>)}
          </div>}
          <div className="m-tablewrap"><table className="m-table">
            <thead><tr><th>Record</th><th>Before</th><th>After</th><th>Notify</th></tr></thead>
            <tbody>{record.changes.map((row:Row,i:number)=><tr key={i}>
              <td><strong>{row.record}</strong><br/><small>{row.field}</small></td>
              <td><span className="diff-before">{row.before}</span></td>
              <td><span className="diff-after">{row.after}</span></td>
              <td>{row.audience}</td>
            </tr>)}</tbody>
          </table></div>
          {notifs.length>0&&<div className="disruption-notifs">
            <div className="disruption-notifs-head">
              <span><MailCheck size={14}/> <strong>Stakeholder notifications ({notifs.length})</strong> : {sentCount} sent, {queuedCount} queued, {simCount} simulated</span>
              {queuedCount>0&&<Button busy={action.busy} onClick={()=>action.run('retry_disruption_emails',{disruption_id:record.id},'Sent queued disruption alerts.')}>
                <Send size={13}/> Send queued emails via Gmail
              </Button>}
            </div>
            <details>
              <summary style={{fontSize:12,color:'#475569'}}>View recipient delivery log ({notifs.length})</summary>
              <div className="m-tablewrap"><table className="m-table">
                <thead><tr><th>Recipient</th><th>Role</th><th>Channel</th><th>Status</th></tr></thead>
                <tbody>{notifs.slice(0,25).map((n:Row,idx:number)=><tr key={idx}>
                  <td><strong>{n.recipient_name}</strong><br/><small>{n.recipient_email}</small></td>
                  <td>{n.role}</td>
                  <td>{n.channel}</td>
                  <td><Pill tone={n.status==='sent'?'mint':n.status==='failed'?'red':n.status==='queued'?'amber':'neutral'}>{n.status}</Pill>{n.detail?<small style={{display:'block',color:'#64748B'}}>{n.detail}</small>:null}</td>
                </tr>)}</tbody>
              </table></div>
            </details>
          </div>}
          <div className="disruption-explain"><DecisionExplainControl data={data} act={act} targetType="disruption" targetId={record.id} compact/></div>
        </details>
      })}
    </div>}
    {open&&<Dialog title="Trigger a campus disruption" onClose={()=>{if(!action.busy)setOpen(false)}}>
      <form className="m-form m-pad" onSubmit={submit}>
        <Notice state={action}/>
        <label className="m-field">What changed?
          <select value={kind} onChange={e=>setKind(e.target.value)}>
            <option value="venue">Venue unavailable / relocated</option>
            <option value="asset">Asset unavailable or damaged</option>
            <option value="cutoff">Registration or eligibility cutoff changed</option>
            <option value="cancellation">Last-minute session or event cancellation</option>
          </select>
        </label>
        {kind==='venue'&&<label className="m-field">Replacement venue<input name="venue" required maxLength={220} placeholder="e.g. ESB Auditorium 2"/></label>}
        {kind==='asset'&&<>
          <label className="m-field">Unavailable or damaged asset<input name="asset_name" maxLength={120} placeholder="e.g. Main Hall Projector / Stage Audio"/></label>
          <label className="m-field">Task affected by the asset
            <select name="task_id" required defaultValue="">
              <option value="" disabled>Select an open task</option>
              {openTasks.map((task:Row)=><option key={task.id} value={task.id}>{task.title} ({day(task.due_date)})</option>)}
            </select>
          </label>
          <label className="m-field">Delay in days<input name="days" type="number" min="1" max="30" defaultValue="1" required/></label>
        </>}
        {kind==='cutoff'&&<>
          <label className="m-field">New registration cutoff<input name="deadline" type="date" max={data.event.start_date}/></label>
          <label className="m-field">Updated eligibility criteria (optional)<input name="eligibility_note" maxLength={400} placeholder="e.g. Open to all Engineering & MCA students, teams of 2-4"/></label>
          <label className="m-field">Revised participant capacity (optional)<input name="target" type="number" min="1" max="100000" placeholder={String(data.event.target)}/></label>
        </>}
        {kind==='cancellation'&&<>
          <label className="m-field">Cancellation scope
            <select value={scope} onChange={e=>setScope(e.target.value as 'session'|'event')}>
              <option value="session">Session, track, or scheduled task</option>
              <option value="event">Full event cancellation / postponement</option>
            </select>
          </label>
          {scope==='session'&&<>
            <label className="m-field">Task or session affected (optional)
              <select name="task_id" defaultValue="">
                <option value="">None selected</option>
                {openTasks.map((task:Row)=><option key={task.id} value={task.id}>{task.title}</option>)}
              </select>
            </label>
            <label className="m-field">Cancelled track or speaker session{tracks.length?' (or choose track)':''}
              <input name="track" list="disruption-tracks" maxLength={120} placeholder="e.g. Hardware Track / Keynote"/>
              {tracks.length>0&&<datalist id="disruption-tracks">{tracks.map(t=><option key={t} value={t}/>)}</datalist>}
            </label>
          </>}
        </>}
        <label className="m-field">Reason / organizer note (included in stakeholder emails)
          <input name="reason" maxLength={400} placeholder="e.g. Auditorium maintenance scheduled; relocated with full seating."/>
        </label>
        <label style={{display:'flex',alignItems:'center',gap:8,fontSize:13,color:'#334155',cursor:'pointer'}}>
          <input type="checkbox" checked={notify} onChange={e=>setNotify(e.target.checked)}/>
          Automatically email affected participants &amp; confirmed sponsors via Gmail
        </label>
        <div className="m-actions"><Button primary type="submit" busy={action.busy}>Apply change &amp; generate alerts</Button></div>
      </form>
    </Dialog>}
  </section>
}
