import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, Check, CircleAlert, LoaderCircle, Network } from 'lucide-react';
import { Dialog } from './Dialog';
import { api, saved, save, type Snapshot } from './data';

const steps=['Event details','Resources','Planning brief'];
function dateInput(offset:number){const d=new Date();d.setDate(d.getDate()+offset);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
type Job={status:'queued'|'running'|'completed'|'failed';id:string|null;detail:string};
export default function Wizard({data,close,complete}:{data:Snapshot|null;close:()=>void;complete:(id:string)=>Promise<void>}) {
 const [step,setStep]=useState(0),[job,setJob]=useState(()=>saved('planning_job')||''),[status,setStatus]=useState(''),[error,setError]=useState(''),[posting,setPosting]=useState(false);
 const request = useRef<{body:string;key:string}|null>(null);
 const [form,setForm]=useState({name:'',type:'Hackathon',description:'',college:data?.event.college||'',venue:'',start_date:dateInput(14),end_date:dateInput(15),target:'100',initial_budget:'0',sponsorship_target:'0',members:'',goals:'',requirements:'',constraints:''});
 function change(key:keyof typeof form,value:string){setForm(f=>({...f,[key]:value,...(key==='start_date'&&value>f.end_date?{end_date:value}:{})}));}
 useEffect(()=>{
  if(!job)return;let active=true;let timer:ReturnType<typeof setTimeout>;
  async function poll(){
   try {const result=await api<Job>('/api/jobs/'+encodeURIComponent(job));if(!active)return;
    if(result.status==='completed'&&result.id){await complete(result.id);save('planning_job','');return}
    if(result.status==='failed'){request.current=null;save('planning_job','');setJob('');setError(result.detail||'Planning stopped. Review your event details and try again.');return}
    setStatus(result.detail||(result.status==='queued'?'Your planning job is queued.':'Nexus is coordinating your event plan.'));
   }catch(err){if(!active)return;setStatus('Connection interrupted. Reconnecting to your planning job.');}
   if(active)timer=setTimeout(poll,1200);
  }
  void poll();return()=>{active=false;clearTimeout(timer)};
 },[job,complete]);
 async function submit(ev:FormEvent){ev.preventDefault();if(step<2){setStep(step+1);return}setPosting(true);setError('');
  const body=JSON.stringify({...form,target:Number(form.target),initial_budget:Math.round(Number(form.initial_budget)*100),sponsorship_target:Math.round(Number(form.sponsorship_target)*100),members:form.members.split(/[,\n]/).map(v=>v.trim()).filter(Boolean)});
  if(request.current?.body!==body)request.current={body,key:crypto.randomUUID()};
  try {
   const result=await api<{job_id:string}>('/api/planning-jobs',{method:'POST',body,headers:{'Idempotency-Key':request.current.key}});
   save('planning_job',result.job_id);
   setJob(result.job_id);
   setStatus('Your planning job is queued.');
  }
  catch(err){setError((err as Error).message)}finally{setPosting(false)}
 }
 function field(label:string,key:keyof typeof form,opts:{type?:string;wide?:boolean;required?:boolean;placeholder?:string;min?:number|string;step?:number;max?:number}={}){
  return <label className={opts.wide?'wide':''}>{label}{opts.required?' *':''}<input type={opts.type||'text'} value={form[key]} required={opts.required} min={opts.min} max={opts.max} step={opts.step} placeholder={opts.placeholder} maxLength={400} onChange={e=>change(key,e.target.value)}/></label>
 }
 function area(label:string,key:keyof typeof form,placeholder:string){return <label className="wide">{label}<textarea rows={2} maxLength={2000} value={form[key]} placeholder={placeholder} onChange={e=>change(key,e.target.value)}/></label>}
 return <Dialog title={job?'Event planning':'Create event'} onClose={close}>
 {job?<div className="job-view"><span className="job-icon"><Network size={31}/></span><h3>Nexus is planning your event</h3><p role="status"><LoaderCircle className="spin" size={16}/>{status||'Connecting to your planning job…'}</p><p>You can close this window and return to the planning job from the event selector.</p><button className="subtle-button" onClick={close}>Back to workspace</button></div>:<form onSubmit={submit}>
 <ol className="wizard-steps">{steps.map((s,i)=><li className={i===step?'current':i<step?'done':''} key={s} aria-current={i===step?'step':undefined}><span>{i<step?<Check size={12}/>:i+1}</span>{s}</li>)}</ol>
 <div className="wizard-fields" key={step}>
 {step===0?<>{field('Event name','name',{required:true,placeholder:'e.g. Build Night 2026',wide:true})}<label>Event type<select value={form.type} onChange={e=>change('type',e.target.value)}>{['Hackathon','Workshop','Conference','Meetup','Competition','Other'].map(t=><option key={t}>{t}</option>)}</select></label>{field('College or organization','college',{required:true})}{field('Start date','start_date',{type:'date',required:true})}{field('End date','end_date',{type:'date',required:true,min:form.start_date})}{field('Venue','venue',{wide:true,placeholder:'Campus venue or online'})}{area('Description','description','What will participants do at this event?')}</>:null}
 {step===1?<>{field('Expected participants','target',{type:'number',required:true,min:1,max:100000,wide:true})}{field('Initial club budget (₹)','initial_budget',{type:'number',min:0,step:.01,required:true})}{field('Sponsorship target (₹)','sponsorship_target',{type:'number',min:0,step:.01,required:true})}{area('Organizing team','members','Enter member names separated by commas.')}</>:null}
 {step===2?<>{area('Event goals','goals','What would a successful event achieve?')}{area('Special requirements','requirements','Equipment, accessibility, speakers, or partner commitments')}{area('Constraints','constraints','Deadlines, venue restrictions, or spending limits')}<div className="planning-note"><Network size={18}/><span>Nexus will coordinate the agents to generate tasks, budget allocations, sponsor matches, and a risk assessment.</span></div></>:null}
 </div>{error&&<p className="form-error" role="alert"><CircleAlert size={15}/>{error}</p>}
 <footer className="wizard-footer">{step?<button type="button" className="subtle-button" onClick={()=>setStep(step-1)}><ArrowLeft size={14}/>Back</button>:<button type="button" className="subtle-button" onClick={close}>Cancel</button>}<button disabled={posting} className="brand-button">{posting?'Launching…':step===2?'Launch AI Planning':'Continue'}{posting?<LoaderCircle size={15} className="spin"/>:<ArrowRight size={15}/>}</button></footer>
 </form>}</Dialog>
}
