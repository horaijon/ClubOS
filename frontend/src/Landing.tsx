import { ArrowRight, CalendarRange, Handshake, ShieldCheck } from 'lucide-react'
import { LogoMark } from './Identity'
import { Hero } from './components/ui/hero'
import type { AuthSession } from './data'
import './landing.css'

export function SiteBrand(){
  return <a className="site-brand" href="#" aria-label="ClubOS home"><LogoMark/><span>ClubOS</span></a>
}

const workflow=[
  {title:'Turn an idea into a plan',body:'Add your event details. Use the planning agents to draft a budget, build a timeline, and assign work to your team.',icon:CalendarRange},
  {title:'Keep sponsorships moving',body:'Track who you contacted, what they committed, and which deliverables are due. Review offers and agreements in one place.',icon:Handshake},
  {title:'Recover when plans change',body:'See the impact of a shortfall or missed deadline. Review proposed changes before anything is applied.',icon:ShieldCheck},
]

export default function Landing({onDemo, busy, error, session}:{
  onDemo:()=>void; busy:boolean; error:string; session:AuthSession|null
}){
  const workspaceHref=session&&!session.demo?(session.club?"#dashboard":"#setup"):null
  return <main className="site">
    <section className="site-blue">
      <header className="site-header">
        <SiteBrand/>
        <nav className="site-nav" aria-label="About ClubOS"><a href="#how-it-works">How it works</a><a href="#see-the-demo">Live demo</a></nav>
        <a className="site-login" href={workspaceHref||"#login"}>{workspaceHref?"Open workspace":"Log in"}</a>
      </header>
      <Hero onDemo={onDemo} busy={busy} workspaceHref={workspaceHref}/>
      {error && <p className="site-error site-demo-error" role="alert">{error}</p>}
    </section>
    <section className="site-workflow" id="how-it-works">
      <div className="site-section-head"><p className="site-eyebrow">How it works</p><h2>From idea to event day.</h2></div>
      <div className="site-workflow-grid">
        {workflow.map(({title,body,icon:Icon})=><article key={title}>
          <Icon size={28} strokeWidth={1.65} aria-hidden="true"/><h3>{title}</h3><p>{body}</p>
        </article>)}
      </div>
    </section>
    <section className="site-demo" id="see-the-demo">
      <div><h2>See a recovery plan in action.</h2><p>Open CodeStorm, a fictional hackathon. Run a sponsor withdrawal and see how the proposed changes affect its budget.</p></div>
      <button className="site-button site-button-primary" disabled={busy} onClick={onDemo}>{busy?'Opening demo…':'Open the demo'} <ArrowRight size={18} aria-hidden="true"/></button>
    </section>
    <footer className="site-footer"><SiteBrand/><a href={workspaceHref||"#login"}>{workspaceHref?"Open workspace":"Log in"}</a></footer>
  </main>
}
