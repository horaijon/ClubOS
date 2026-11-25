import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, CircleAlert, LoaderCircle, Mic, Network } from 'lucide-react';
import { Dialog } from './Dialog';
import { api, saved, save, type Snapshot } from './data';

import { useDictation } from './useDictation';

const sample='A 24-hour AI hackathon for student builders. Teams of 2 to 4 choose an accessibility or campus tools track and submit a GitHub link. Registration closes three days before the event. Ask developer tool companies and food partners for sponsorship. The total budget is ₹60,000.';
function dateInput(offset:number){const d=new Date();d.setDate(d.getDate()+offset);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
type Job={status:'queued'|'running'|'completed'|'failed';id:string|null;detail:string};
import { TraceView, useLiveTrace } from './LiveTrace';

export default function Wizard({data,college,clubFunds,jobKey,close,complete}:{data:Snapshot|null;college:string;clubFunds:number;jobKey:string;close:()=>void;complete:(id:string)=>Promise<void>}) {
 const [job,setJob]=useState(()=>saved(jobKey)||''),[status,setStatus]=useState(''),[error,setError]=useState(''),[posting,setPosting]=useState(false);
 const trace=useLiveTrace(job?'/api/jobs/'+encodeURIComponent(job)+'/trace':'',undefined,true);
 const request = useRef<{body:string;key:string}|null>(null);
 const [form,setForm]=useState({name:'',type:'Hackathon',description:'',college:data?.event.college||college,venue:'',start_date:dateInput(14),end_date:dateInput(15),target:'100',initial_budget:String(clubFunds/100),estimated_budget:'',brief:''});
 const mic=useDictation();
 function change(key:keyof typeof form,value:string){setForm(f=>({...f,[key]:value,...(key==='start_date'&&value>f.end_date?{end_date:value}:{})}));}
 useEffect(()=>{
  if(!job)return;let active=true;let timer:ReturnType<typeof setTimeout>;
  async function poll(){
   try {const result=await api<Job>('/api/jobs/'+encodeURIComponent(job));if(!active)return;
    if(result.status==='completed'&&result.id){await complete(result.id);save(jobKey,'');return}
    if(result.status==='failed'){request.current=null;save(jobKey,'');setJob('');setError(result.detail||'Planning stopped. Review your event details and try again.');return}
    setStatus(result.detail||(result.status==='queued'?'Your planning job is queued.':'Nexus is coordinating your event plan.'));
   }catch(err){if(!active)return;setStatus('Connection interrupted. Reconnecting to your planning job.');}
   if(active)timer=setTimeout(poll,1200);
  }
  void poll();return()=>{active=false;clearTimeout(timer)};
 },[job,complete,jobKey]);
 async function submit(ev:FormEvent){ev.preventDefault();setPosting(true);setError('');
  const body=JSON.stringify({...form,target:Number(form.target),initial_budget:Math.round(Number(form.initial_budget)*100),estimated_budget:form.estimated_budget===''?null:Math.round(Number(form.estimated_budget)*100)});
  if(request.current?.body!==body)request.current={body,key:crypto.randomUUID()};
  try {
   const result=await api<{job_id:string}>('/api/planning-jobs',{method:'POST',body,headers:{'Idempotency-Key':request.current.key}});
   save(jobKey,result.job_id);
   setJob(result.job_id);
   setStatus('Your planning job is queued.');
  }
  catch(err){setError((err as Error).message)}finally{setPosting(false)}
 }
 function field(label:string,key:keyof typeof form,opts:{type?:string;wide?:boolean;required?:boolean;placeholder?:string;min?:number|string;step?:number;max?:number}={}){
  return <label className={opts.wide?'wide':''}>{label}{opts.required?' *':''}<input type={opts.type||'text'} value={form[key]} required={opts.required} min={opts.min} max={opts.max} step={opts.step} placeholder={opts.placeholder} maxLength={400} onChange={e=>change(key,e.target.value)}/></label>
 }
 return <Dialog title={job?'Agents are building your event':'Create an event'} onClose={close}>
 {job?<div className="job-view"><span className="job-icon"><Network size={28}/></span><p role="status"><LoaderCircle className="spin" size={16}/>{status||'Connecting to the agents…'}</p><TraceView steps={trace.steps} connected={trace.connected} compact plain/><button className="subtle-button" onClick={close}>Back to workspace</button></div>:<form onSubmit={submit}>
  <div className="wizard-fields">
   {field('Event name','name',{required:true,placeholder:'HackBlitz'})}
   <label>Event type<select value={form.type} onChange={e=>change('type',e.target.value)}>{['Hackathon','Workshop','Tech Talk','Competition','Other'].map(t=><option key={t}>{t}</option>)}</select></label>
   {field('College or organization','college',{required:true})}{field('Venue','venue',{required:true})}
   {field('Start date','start_date',{type:'date',required:true})}{field('End date','end_date',{type:'date',required:true,min:form.start_date})}
   {field('Expected participants','target',{type:'number',required:true,min:1,max:100000})}
   {field('Available club funds (₹)','initial_budget',{type:'number',min:0,step:.01,required:true})}
   {field('Estimated total budget (₹)','estimated_budget',{type:'number',min:0,step:.01,placeholder:'Let Nexus estimate'})}
   <label className="wide">Describe your event<textarea value={form.brief} onChange={e=>change('brief',e.target.value)} required maxLength={6500} rows={5} placeholder="Include your tracks, team rules, registration and submission deadlines, prizes, and the sponsors you need."/></label>
   <div className="wide launch-tools">
    <button type="button" className="subtle-button" onClick={()=>change('brief',sample)}>Try sample brief</button>
    <button type="button" className="subtle-button" disabled={!mic.supported} aria-pressed={mic.listening} onClick={()=>mic.toggle(form.brief,value=>change('brief',value))}><Mic size={15}/>{mic.listening?'Listening… Stop':'Dictate brief'}</button>
    {!mic.supported&&<small>Voice input is unavailable in this browser.</small>}
    {mic.error&&<small role="alert">{mic.error}</small>}
   </div>
  </div>{error&&<p className="form-error" role="alert"><CircleAlert size={15}/>{error}</p>}
  <footer className="wizard-footer"><button className="brand-button" type="submit" disabled={posting||mic.listening}>Launch AI Agents <ArrowRight size={16}/></button></footer>
 </form>}
 </Dialog>
}
