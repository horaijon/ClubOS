import { ArrowRight, CalendarDays, Check, CircleAlert, ClipboardList, MoveUpRight } from 'lucide-react'

export function Hero({onDemo, busy, workspaceHref}:{onDemo:()=>void; busy:boolean; workspaceHref:string|null}){
  return <div className="site-hero">
    <div className="site-hero-copy">
      <p className="site-eyebrow">The event workspace for campus clubs</p>
      <h1><span>Big events.</span><span>Small teams.</span></h1>
      <p className="site-lead">Turn your club’s next idea into a plan. Track sponsors, assign tasks, and recover when the budget changes.</p>
      <div className="site-actions">
        <a href={workspaceHref||"#signup"} className="site-button site-button-primary">{workspaceHref?"Open workspace":"Create your workspace"} <ArrowRight size={19} aria-hidden="true"/></a>
        <button className="site-button site-button-ghost" onClick={onDemo} disabled={busy}>{busy?'Opening demo…':'Try the demo'}</button>
      </div>
    </div>
    <div className="hero-art" aria-hidden="true">
      <div className="hero-run-sheet glass">
        <div className="art-label"><ClipboardList size={16}/> Event plan</div>
        <h2>Campus build night</h2>
        <div className="art-meta"><CalendarDays size={15}/> Event run sheet</div>
        <div className="art-check"><Check size={15}/> Confirm venue</div>
        <div className="art-check"><Check size={15}/> Assign volunteer leads</div>
        <div className="art-check art-check-open"><span/> Check in participants</div>
        <div className="art-ticket-bottom"><span>ClubOS</span><i/></div>
      </div>
      <div className="hero-funding glass glass--lime">
        <div className="art-label"><CircleAlert size={16}/> Budget change</div>
        <strong>Sponsor withdrew</strong>
        <div className="art-recovery">Review recovery plan <MoveUpRight size={16}/></div>
      </div>
      <div className="hero-tape">Event workspace preview</div>
    </div>
  </div>
}
