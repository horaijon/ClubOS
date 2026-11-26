import {useEffect,useRef,useState,type FormEvent} from 'react'
import {ArrowRight,LoaderCircle,Mic,Sparkles} from 'lucide-react'
import {Dialog} from './Dialog'
import {api,saved,save,type Snapshot} from './data'
import {TraceView,useLiveTrace} from './LiveTrace'
import {useDictation} from './useDictation'
import './launch.css'

const sample='Teams of 2 to 4 will build projects in accessibility or campus tools. Each team must submit a GitHub link. Winners receive hardware kits. We need developer tool and food sponsors.'
type Job={status:string;id:string|null;detail:string}
type Details={fields?:string[];tracks?:string[];team_rules?:string;prizes?:string;sponsor_needs?:string;notes?:string;[key:string]:unknown}

export default function Wizard({data,college,clubFunds,jobKey,close,complete}:{data:Snapshot|null;college:string;clubFunds:number;jobKey:string;close:()=>void;complete:(id:string)=>Promise<void>}){
  const [job,setJob]=useState(()=>saved(jobKey)||''),[status,setStatus]=useState(''),[error,setError]=useState('')
  const [brief,setBrief]=useState(''),[reviewed,setReviewed]=useState(''),[details,setDetails]=useState<Details|null>(null),[mode,setMode]=useState('')
  const [busy,setBusy]=useState(false)
  const [form,setForm]=useState({name:'',type:'',college:data?.event.college||college,venue:'',start_date:'',end_date:'',target:'100',initial_budget:String(clubFunds/100),estimated_budget:'',registration_deadline:'',submission_deadline:''})
  const request=useRef<{body:string;key:string}|null>(null)
  const mic=useDictation()
  const trace=useLiveTrace(job?'/api/jobs/'+encodeURIComponent(job)+'/trace':'',undefined,true)
  const showReview=details&&brief===reviewed

  useEffect(()=>{
    if(!job)return
    let active=true
    let timer:ReturnType<typeof setTimeout>
    async function poll(){
      try{
        const result=await api<Job>('/api/jobs/'+encodeURIComponent(job))
        if(!active)return
        if(result.status==='completed'&&result.id){await complete(result.id);save(jobKey,'');return}
        if(result.status==='failed'){request.current=null;save(jobKey,'');setJob('');setError(result.detail||'Planning stopped. Check the event details and retry.');return}
        setStatus(result.detail||'Nexus is coordinating the agents.')
      }catch{if(active)setStatus('Reconnecting to your planning job…')}
      if(active)timer=setTimeout(poll,1200)
    }
    void poll()
    return()=>{active=false;clearTimeout(timer)}
  },[job,complete,jobKey])

  async function analyze(){
    if(!brief.trim()||busy)return
    setBusy(true);setError('')
    try{
      const result=await api<{details:Details;mode:string}>('/api/event-brief/preview',{method:'POST',body:JSON.stringify({brief})})
      setForm(current=>({...current,
        registration_deadline:typeof result.details.registration_deadline==='string'?result.details.registration_deadline:'',
        submission_deadline:typeof result.details.submission_deadline==='string'?result.details.submission_deadline:'',
      }))
      setReviewed(brief);setDetails(result.details);setMode(result.mode)
    }catch(err){setError((err as Error).message)}
    finally{setBusy(false)}
  }

  async function submit(event:FormEvent){
    event.preventDefault()
    if(!showReview||busy)return
    const {registration_deadline,submission_deadline,...eventFields}=form
    const funds=Math.round(Number(form.initial_budget)*100)
    const estimate=form.estimated_budget?Math.round(Number(form.estimated_budget)*100):null
    if(estimate!==null&&estimate<funds){setError('Total budget must cover the club funds allocated to this event.');return}
    const body=JSON.stringify({...eventFields,brief,type:form.type||'Other',end_date:form.end_date||form.start_date,target:Number(form.target),initial_budget:funds,estimated_budget:estimate,brief_plan:{
      registration_deadline:registration_deadline||form.start_date,
      submission_deadline:submission_deadline||form.end_date||form.start_date,
      estimated_budget:estimate??Math.max(funds,Number(form.target)*30000),
      fields:details.fields||[],tracks:details.tracks||[],team_rules:details.team_rules||'',prizes:details.prizes||'',sponsor_needs:details.sponsor_needs||'',notes:details.notes||'',
    }})
    setBusy(true);setError('')
    if(request.current?.body!==body)request.current={body,key:crypto.randomUUID()}
    try{
      const result=await api<{job_id:string}>('/api/planning-jobs',{method:'POST',body,headers:{'Idempotency-Key':request.current.key}})
      save(jobKey,result.job_id);setJob(result.job_id);setStatus('Your planning job is queued.')
    }catch(err){setError((err as Error).message)}
    finally{setBusy(false)}
  }

  function field(label:string,key:keyof typeof form,options:React.InputHTMLAttributes<HTMLInputElement>={}){
    return <label>{label}<input {...options} value={form[key]} onChange={event=>setForm({...form,[key]:event.target.value})}/></label>
  }

  return <Dialog title={job?'Agents are building your event':'Create an event'} onClose={close}>
    {job?<div className="job-view"><p role="status"><LoaderCircle className="spin" size={16}/>{status}</p><TraceView steps={trace.steps} connected={trace.connected} compact plain/><button className="subtle-button" onClick={close}>Back to workspace</button></div>:
    <form className="event-wizard" onSubmit={submit}>
      <div className="wizard-fields">
          {field('Event name','name',{required:true,maxLength:160})}{field('Event type','type',{maxLength:160})}
          {field('College or organization','college',{required:true,maxLength:200})}{field('Venue','venue',{required:true,maxLength:220})}
          {field('Start date','start_date',{type:'date',required:true})}{field('End date','end_date',{type:'date',required:true,min:form.start_date})}
          {field('Expected participants','target',{type:'number',required:true,min:1,max:100000})}
          {field('Available club funds (₹)','initial_budget',{type:'number',required:true,min:0,step:.01})}
          {field('Estimated total budget (₹)','estimated_budget',{type:'number',min:0,step:.01,placeholder:'Use the suggested estimate'})}
      </div>
      <div className="event-composer">
        <div className="event-composer-heading"><span className="event-composer-icon"><Sparkles size={19}/></span><div>
          <label htmlFor="event-brief">Describe your event</label>
          <p>Add your event format, team sizes, tracks, deadlines, prizes, or sponsor needs. Short notes work too.</p>
        </div></div>
        <textarea id="event-brief" value={brief} onChange={e=>setBrief(e.target.value)} disabled={busy} maxLength={6500} rows={6} placeholder="Teams of four will build campus tools. Each team should submit a GitHub link…"/>
        <div className="launch-tools">
          <button type="button" className="subtle-button" disabled={busy||mic.listening} onClick={()=>setBrief(sample)}>Try sample brief</button>
          {mic.supported&&<button type="button" className="subtle-button" disabled={busy} aria-pressed={mic.listening} onClick={()=>mic.toggle(brief,setBrief)}><Mic size={15}/>{mic.listening?'Stop dictation':'Dictate brief'}</button>}
          <button type="button" className="brand-button" disabled={busy||mic.listening||!brief.trim()} onClick={()=>void analyze()}>{busy&&!showReview?<LoaderCircle size={16} className="spin"/>:<Sparkles size={16}/>} {busy&&!showReview?'Analyzing…':'Analyze brief'}</button>
        </div>
        {mic.error&&<p role="alert">{mic.error}</p>}
      </div>
      {showReview&&<section className="event-review">
        <div className="event-review-heading"><h3>Review brief details</h3><p role="status">{mode==='Deterministic fallback'?'Review the details found in your brief.':'Review the details Nexus found in your brief.'}</p></div>
        <div className="wizard-fields">
          {field('Registration deadline (optional)','registration_deadline',{type:'date',max:form.start_date})}
          {field('Submission deadline (optional)','submission_deadline',{type:'date',min:form.start_date,max:form.end_date||form.start_date})}
          <p className="wide event-deadline-note">Blank deadlines use the event start for registration and the event end for submissions.</p>
          {(['team_rules','prizes','sponsor_needs'] as const).map((key,i)=><label key={key}>{['Team rules','Prizes','Sponsor needs'][i]}<input value={details[key]||''} maxLength={i===0?400:500} onChange={e=>setDetails({...details,[key]:e.target.value})}/></label>)}
          <label className="wide">Format, duration, and other details<textarea rows={2} value={details.notes||''} maxLength={1500} onChange={e=>setDetails({...details,notes:e.target.value})}/></label>
          {details.tracks?.length?<p className="wide">Tracks · {details.tracks.join(', ')}</p>:null}
        </div>
      </section>}
      {error&&<p className="form-error" role="alert">{error}</p>}
      {showReview&&<footer className="wizard-footer"><button className="brand-button" type="submit" disabled={busy||mic.listening}>Launch AI Agents <ArrowRight size={16}/></button></footer>}
    </form>}
  </Dialog>
}
