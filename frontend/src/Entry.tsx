import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, Building2, CircleAlert } from 'lucide-react'
import Landing, { SiteBrand } from './Landing'
import { api, type AuthSession } from './data'

const Workspace = lazy(()=>import('./App'))
const publicSections = new Set(['','how-it-works','see-the-demo'])
const readRoute = ()=>location.hash.slice(1)

function AccountForm({view,onSubmit,busy,error,session}:{
  view:'login'|'signup'|'setup';onSubmit:(e:FormEvent<HTMLFormElement>)=>void;busy:boolean;error:string;session:AuthSession|null
}){
  const heading=useRef<HTMLHeadingElement>(null)
  useEffect(()=>{window.scrollTo(0,0);heading.current?.focus()},[view])
  const setup=view==='setup'
  const signup=view==='signup'
  const title=setup?'Set up your club':signup?'Create your account':'Log in to ClubOS'
  return <main className="site-entry">
    <header className="site-entry-header glass glass--cobalt"><SiteBrand/><a href="#" className="entry-return"><ArrowLeft size={16}/> Back to ClubOS</a></header>
    <div className="entry-layout">
      <aside className="entry-side">
        <Building2 size={34} strokeWidth={1.5} aria-hidden="true"/>
        <p className="entry-side-title">Make room for your next big event.</p>
        <p>One workspace for the plan, the people, and the budget.</p>
      </aside>
      <div className="entry-panel">
        {view!=='login'&&<p className="entry-step">{setup?'Step 2 of 2 · Club details':'Step 1 of 2 · Organizer account'}</p>}
        <h1 ref={heading} tabIndex={-1}>{title}</h1>
        <p className="entry-description">{setup?`Hi ${session?.name}. Add the details your team will see in the workspace.`:signup?'Set up an organizer account for your campus club.':'Pick up where you left off in your club workspace.'}</p>
        {error&&<p className="site-error" role="alert"><CircleAlert size={17}/>{error}</p>}
        <form className="entry-form" onSubmit={onSubmit} key={view}>
          {setup ? <>
            <label>Club name<input name="name" autoComplete="organization" maxLength={120} required placeholder="e.g. Robotics Society"/></label>
            <label>College or institution<input name="college" maxLength={120} required placeholder="e.g. Ramaiah Institute of Technology"/></label>
            <label>Available club funds (₹)<input name="available_funds" type="number" min="0" step=".01" defaultValue="0" required/></label>
            <label>Your role<input name="role" autoComplete="organization-title" maxLength={120} defaultValue="Organizer" required/></label>
          </> : <>
            {signup&&<label>Full name<input name="name" autoComplete="name" maxLength={120} required/></label>}
            <label>Email<input name="email" type="email" autoComplete="username" maxLength={254} required/></label>
            <label>Password<input name="password" type="password" minLength={8} maxLength={200} autoComplete={signup?'new-password':'current-password'} aria-describedby={signup?'password-hint':undefined} required/></label>
            {signup&&<small id="password-hint">Use at least 8 characters</small>}
          </>}
          <button className="site-button entry-submit" disabled={busy}>
            {busy?'Saving…':setup?'Create club workspace':signup?'Create account':'Log in'} <ArrowRight size={17} aria-hidden="true"/>
          </button>
        </form>
        {setup?<p className="entry-footer">Your first event starts with the details you enter.</p>:
         <p className="entry-footer">{signup?'Already have an account?':'New to ClubOS?'} <a href={signup?'#login':'#signup'}>{signup?'Log in':'Create an account'}</a></p>}
      </div>
    </div>
  </main>
}

export default function Entry(){
  const [route,setRoute]=useState(readRoute)
  const [session,setSession]=useState<AuthSession|null>(null)
  const [ready,setReady]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [connection,setConnection]=useState('')
  const [reload,setReload]=useState(0)
  useEffect(()=>{
    const navigate=()=>{setRoute(readRoute());setError('')}
    window.addEventListener('hashchange',navigate)
    return ()=>window.removeEventListener('hashchange',navigate)
  },[])
  useEffect(()=>{
    let active=true
    api<{session:AuthSession|null}>('/api/auth/session')
      .then(data=>{if(active)setSession(data.session)})
      .catch(()=>{if(active)setConnection('Could not connect to ClubOS.')})
      .finally(()=>{if(active)setReady(true)})
    return ()=>{active=false}
  },[reload])

  function go(page:string){
    if(readRoute()!==page)location.hash=page
    setRoute(page)
    window.scrollTo(0,0)
  }

  async function send(path:string, data:Record<string,unknown>={}){
    await api('/api/auth/'+path,{method:'POST',body:JSON.stringify(data)})
    const result=await api<{session:AuthSession|null}>('/api/auth/session')
    setSession(result.session)
    setReady(true)
    return result.session
  }

  async function demo(){
    setBusy(true);setError('')
    try{
      if(!session?.demo)await send('demo')
      go('dashboard')
    }catch(err){setError((err as Error).message)}
    finally{setBusy(false)}
  }

  async function exit(){
    setBusy(true);setError('')
    try{await send('logout');go('')}
    catch(err){setError((err as Error).message)}
    finally{setBusy(false)}
  }

  const view=route==='signup'?'signup':session&&!session.club?'setup':'login'
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    const form=Object.fromEntries(new FormData(event.currentTarget))
    setBusy(true);setError('')
    try{
      const current=await send(view==='setup'?'club':view,view==='setup'?{...form,available_funds:Math.round(Number(form.available_funds)*100)}:form)
      go(current?.club?'dashboard':'setup')
    }catch(err){setError((err as Error).message)}
    finally{setBusy(false)}
  }

  if(publicSections.has(route))return <Landing session={session} onDemo={demo} busy={busy} error={error}/>
  if(!ready)return <main className="shell-loading" role="status">Checking workspace session…</main>
  if(connection)return <main className="shell-loading" role="alert">{connection} <button className="subtle-button" onClick={()=>{setConnection('');setReady(false);setReload(n=>n+1)}}>Retry</button></main>
  if(route==='login'||route==='signup'||!session?.club)return <AccountForm view={view} session={session} onSubmit={submit} busy={busy} error={error}/>
  return <Suspense fallback={<main className="shell-loading" role="status">Opening workspace…</main>}><Workspace key={session.club.id} session={session} onExit={exit} exitPending={busy} sessionError={error}/></Suspense>
}
