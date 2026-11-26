import { useState, type FormEvent } from 'react'
import { Activity, ArrowRight, ArrowUpRight, Bot, CalendarDays, Check, Clock3, Copy, ExternalLink, Handshake, Link2, MailCheck, MapPin, Plus, QrCode, RefreshCw, Sparkles, Users, Wallet } from 'lucide-react'
import { Dialog } from './Dialog'
import { AgentMark } from './Identity'
import type { TraceStep } from './LiveTrace'
import { api, dateOf, money, ratio, shortDate, type ApprovalItem, type RegistrationForm } from './data'
import { Button, CopyButton, Head, Notice, Panel, Pill, useAction, day, type Row, type ViewProps } from './modules/ui'
import './modules.css'
import './launch.css'

function compactFormUrl(form: RegistrationForm) {
  if (form.is_google_form && form.responder_uri) {
    return form.responder_uri.replace(/^https?:\/\//, '').slice(0, 38) + (form.responder_uri.length > 46 ? '…' : '')
  }
  return '/register/' + form.slug.slice(0, 12) + '…'
}

function relativeTime(iso: string) {
  const diffMin = Math.max(0, Math.floor((Date.now() - dateOf(iso).getTime()) / 60000))
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`
  return shortDate(iso)
}

function impactLabel(item: ApprovalItem): { text: string; money?: boolean } {
  const actions = item.actions || []
  const confirm = actions.find(a => a.type === 'confirm' && typeof a.amount === 'number')
  if (confirm && typeof confirm.amount === 'number') {
    return { text: '+' + money(confirm.amount), money: true }
  }
  const saving = actions.reduce((acc, a) => acc + (typeof a.saving === 'number' ? a.saving : 0), 0)
  if (saving > 0) return { text: 'Save ' + money(saving), money: true }
  if (actions.some(a => a.type === 'send_reply_email' || a.type === 'dispatch_simulated_pitch')) return { text: 'Send Email' }
  if (actions.some(a => a.type === 'reallocate_budget' || a.type === 'reduce_budget')) return { text: 'Budget Shift' }
  if (actions.some(a => a.type === 'move_deadline')) return { text: 'Timeline' }
  return { text: `${actions.length} action${actions.length === 1 ? '' : 's'}` }
}

function inferAgent(item: ApprovalItem, runs: Row[]): string {
  const run = runs.find(r => r.workflow_id === item.workflow_id)
  if (run?.agent) return run.agent
  const types = (item.actions || []).map(a => a.type)
  if (types.some(t => /confirm|negotiate|dispatch|send_reply|backup_outreach|draft_review/.test(t))) return 'Magnet'
  if (types.some(t => /budget/.test(t))) return 'Ledger'
  if (types.some(t => /deadline|deliverable|task/.test(t))) return 'Atlas'
  if (types.some(t => /campaign/.test(t))) return 'Echo'
  return 'Nexus'
}

export default function MissionControl({ data, act, navigate, trace, traceConnected, onCreate, refresh, googleStatus, onConnectGoogle }: ViewProps & { onCreate: () => void; refresh?: () => Promise<void> }) {
  const action = useAction(act)
  const m = data.metrics, e = data.event, form = data.registration_form
  const [qrOpen, setQrOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [syncingForm, setSyncingForm] = useState(false)
  const [checkingInbox, setCheckingInbox] = useState(false)
  const [creatingForm, setCreatingForm] = useState(false)
  const [statusBanner, setStatusBanner] = useState('')

  const pending: ApprovalItem[] = data.approvals.filter((item: ApprovalItem) => item.status === 'Pending')
  const stages = (name: string) => data.sponsors.filter((partner: Row) => partner.stage === name).length
  const regPercent = Math.min(100, ratio(m.registered, m.target))
  const sponsorPercent = Math.min(100, ratio(m.committed, e.sponsorship_target || 1))
  const totalBudget = Math.max(m.planned, m.projected_funding, 1)
  const clubWidth = Math.min(100, Math.round((e.initial_budget * 100) / totalBudget))
  const sponsorWidth = Math.min(100 - clubWidth, Math.round((m.committed * 100) / totalBudget))

  const formLink = form ? (form.is_google_form && form.responder_uri ? form.responder_uri : (form.public_url || location.origin + '/register/' + form.slug)) : ''
  const qrSrc = form ? (form.is_google_form ? `/api/events/${encodeURIComponent(e.id)}/google-form/qr.svg` : `/api/registration/${form.slug}/qr.svg`) : ''

  async function copyLink() {
    if (!formLink) return
    try {
      await navigator.clipboard.writeText(formLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* fallback ignored */ }
  }

  async function handleCreateGoogleForm() {
    setCreatingForm(true)
    setStatusBanner('')
    try {
      const res = await api<{ message: string }>(`/api/events/${encodeURIComponent(e.id)}/create-google-form`, { method: 'POST', body: '{}' })
      setStatusBanner(res.message)
      await refresh?.()
    } catch (err) {
      setStatusBanner((err as Error).message)
    } finally {
      setCreatingForm(false)
    }
  }

  async function handleSyncResponses() {
    setSyncingForm(true)
    setStatusBanner('')
    try {
      const res = await api<{ message: string }>(`/api/events/${encodeURIComponent(e.id)}/sync-form-responses`, { method: 'POST' })
      setStatusBanner(res.message)
      await refresh?.()
    } catch (err) {
      setStatusBanner((err as Error).message)
    } finally {
      setSyncingForm(false)
    }
  }

  async function handleCheckInbox() {
    if (!googleStatus?.connected) {
      navigate('sponsors')
      return
    }
    setCheckingInbox(true)
    setStatusBanner('')
    try {
      const res = await api<{ message: string }>(`/api/events/${encodeURIComponent(e.id)}/check-replies`, { method: 'POST' })
      setStatusBanner(res.message)
      await refresh?.()
    } catch (err) {
      setStatusBanner((err as Error).message)
    } finally {
      setCheckingInbox(false)
    }
  }

  // Build clean, human-readable Live Agent Activity timeline (filtering out robotic boilerplate)
  const latestWorkflowCompleted = trace.some(step => step.kind === 'run_completed')
  const feedItems = (() => {
    const noisy = /agent started|received the workflow|prepared propose_package|prepared draft_outreach/i
    const items: { id: string; agent: string; title: string; description: string; timestamp: string; payload?: Record<string, unknown> }[] = []
    for (const r of [...data.runs].slice(0, 12)) {
      if (noisy.test(r.summary || '')) continue
      items.push({
        id: 'run-' + r.id,
        agent: r.agent || 'Nexus',
        title: r.agent || 'Nexus',
        description: r.summary || r.trigger,
        timestamp: r.created_at,
        payload: { tool: r.tool, mode: r.mode, status: r.status },
      })
    }
    for (const a of [...data.activity].slice(0, 10)) {
      if (!items.some(x => x.description === a.description && Math.abs(dateOf(x.timestamp).getTime() - dateOf(a.created_at).getTime()) < 5000)) {
        items.push({
          id: 'act-' + a.id,
          agent: a.agent || 'Nexus',
          title: a.title,
          description: a.description || a.title,
          timestamp: a.created_at,
        })
      }
    }
    return items.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 8)
  })()

  const contactedCount = stages('Contacted')

  return <div className="mc-shell m-view">
    {/* First screen: the agent strip below it only shows after scrolling */}
    <div className="mc-shell mc-first-screen">
    <header className="mc-header">
      <div className="mc-title-group">
        <h1>Mission Control</h1>
        <div className="mc-meta-pills">
          <span className="mc-meta-pill mc-meta-pill--event">{e.name}</span>
          <span className="mc-meta-pill"><CalendarDays size={13} /> {shortDate(e.start_date, true)}</span>
          {e.venue && <span className="mc-meta-pill"><MapPin size={13} /> {e.venue}</span>}
          {form?.deadline && <span className="mc-meta-pill"><Clock3 size={13} /> Reg closes {shortDate(form.deadline)}</span>}
          <button
            type="button"
            className={'mc-meta-pill ' + (googleStatus?.connected ? 'mc-meta-pill--live' : 'mc-meta-pill--offline')}
            onClick={onConnectGoogle}
          >
            <span className={googleStatus?.connected ? 'mc-live-dot' : ''} />
            {googleStatus?.connected ? '● Google Connected' : 'Local Mode · Connect Google'}
          </button>
        </div>
      </div>
      <div className="mc-header-actions">
        {e.id === 'codestorm-2026' && <Button onClick={() => navigate('risks')}>Simulate disruption</Button>}
        <button type="button" className="mc-new-event-btn" onClick={onCreate}><Plus size={15} /> New Event</button>
      </div>
    </header>

    {statusBanner && <div className="m-notice success" role="status">{statusBanner}<button onClick={() => setStatusBanner('')} aria-label="Dismiss"><span style={{ fontSize: 12 }}>✕</span></button></div>}
    <Notice state={action} />

    {/* Top 3 Outcome Cards */}
    <div className="mc-outcomes">
      {/* Card 1: Registrations (FormFlow) */}
      <section className="mc-kpi-card">
        <div>
          <div className="mc-kpi-top">
            <div className="mc-kpi-label">
              <span className="mc-kpi-icon emerald"><Users size={17} /></span>
              <div>
                <div className="mc-kpi-title">Registrations</div>
                <span className="mc-kpi-agent">FormFlow</span>
              </div>
            </div>
            {form && <Pill tone={form.is_google_form ? 'mint' : 'neutral'}>{form.is_google_form ? 'Google Form Live' : 'Local Form'}</Pill>}
          </div>
          <div className="mc-kpi-metric" style={{ marginTop: 14 }}>
            <strong className="mc-kpi-number">{m.registered} / {m.target}</strong>
            <span className="mc-kpi-sub">{regPercent}% of target</span>
          </div>
          <div className="mc-progress" style={{ marginTop: 10 }} aria-label="Registration progress">
            <div className="mc-progress-fill emerald" style={{ width: `${regPercent}%` }} />
          </div>
        </div>

        {form ? <>
          <a className="mc-link-pill" href={formLink} target="_blank" rel="noreferrer" title={formLink}>
            <Link2 size={12} />
            <span>{compactFormUrl(form)}</span>
          </a>
          <div className="mc-card-actions">
            <button type="button" className="m-btn" onClick={copyLink}><Copy size={13} /> {copied ? 'Copied' : 'Copy Link'}</button>
            <a className="m-btn" href={formLink} target="_blank" rel="noreferrer" aria-label="Open public form">Open Form <ArrowUpRight size={13} /></a>
            <button type="button" className="m-btn" onClick={() => setQrOpen(true)}><QrCode size={13} /> QR</button>
            {form.is_google_form && <button type="button" className="m-btn" disabled={syncingForm} onClick={handleSyncResponses} title="Sync Google Form responses now"><RefreshCw size={13} className={syncingForm ? 'm-spin' : ''} /></button>}
          </div>
        </> : (
          <div className="mc-card-actions">
            {googleStatus?.connected ? (
              <Button primary busy={creatingForm} onClick={handleCreateGoogleForm}><Sparkles size={13} /> Create Google Form</Button>
            ) : (
              <Button onClick={() => navigate('registrations')}>Publish registration form</Button>
            )}
          </div>
        )}
      </section>

      {/* Card 2: Sponsorships (Magnet) */}
      <section className="mc-kpi-card">
        <div>
          <div className="mc-kpi-top">
            <div className="mc-kpi-label">
              <span className="mc-kpi-icon blue"><Handshake size={17} /></span>
              <div>
                <div className="mc-kpi-title">Sponsorships</div>
                <span className="mc-kpi-agent">Magnet</span>
              </div>
            </div>
            <Pill tone="purple">{sponsorPercent}% funded</Pill>
          </div>
          <div className="mc-kpi-metric" style={{ marginTop: 14 }}>
            <strong className="mc-kpi-number">{money(m.committed)}</strong>
            <span className="mc-kpi-sub">of {money(e.sponsorship_target)} target</span>
          </div>
          <div className="mc-progress" style={{ marginTop: 10 }} aria-label="Sponsorship funding">
            <div className="mc-progress-fill blue" style={{ width: `${sponsorPercent}%` }} />
          </div>
        </div>

        <div className="mc-pipeline-pills">
          <span className="mc-mini-pill confirmed">{stages('Confirmed')} Confirmed</span>
          <span className="mc-mini-pill">{contactedCount} Contacted</span>
          <span className="mc-mini-pill replied">{stages('Responded')} Replied</span>
        </div>

        <div className="mc-card-actions">
          <button type="button" className="m-btn" disabled={checkingInbox} onClick={handleCheckInbox}>
            <MailCheck size={13} /> {checkingInbox ? 'Checking…' : 'Check Inbox'}
          </button>
          <button type="button" className="m-btn" onClick={() => navigate('sponsors')}>Manage Sponsors</button>
          {stages('Outreach Drafted') > 0 && (
            <button type="button" className="m-btn primary" disabled={action.busy} onClick={() => action.run('prepare_outreach')}>Send Pitches</button>
          )}
        </div>
      </section>

      {/* Card 3: Budget & Readiness (OpsLedger) */}
      <section className="mc-kpi-card">
        <div>
          <div className="mc-kpi-top">
            <div className="mc-kpi-label">
              <span className="mc-kpi-icon slate"><Wallet size={17} /></span>
              <div>
                <div className="mc-kpi-title">Budget & Readiness</div>
                <span className="mc-kpi-agent">OpsLedger</span>
              </div>
            </div>
            <Pill tone={m.balance >= 0 ? 'mint' : 'amber'}>
              {money(Math.abs(m.balance))} {m.balance >= 0 ? 'surplus' : 'shortfall'}
            </Pill>
          </div>
          <div className="mc-kpi-metric" style={{ marginTop: 14 }}>
            <strong className="mc-kpi-number">{money(m.projected_funding)}</strong>
            <span className="mc-kpi-sub">vs {money(m.planned)} planned</span>
          </div>
          <div className="mc-progress-split" style={{ marginTop: 10 }} title={`Club Funds ${money(e.initial_budget)} + Sponsors ${money(m.committed)}`}>
            <div className="mc-split-club" style={{ width: `${clubWidth}%` }} />
            <div className="mc-split-sponsor" style={{ width: `${sponsorWidth}%` }} />
          </div>
        </div>

        <div className="mc-pipeline-pills">
          <span className="mc-mini-pill">Club Funds {money(e.initial_budget)}</span>
          <span className="mc-mini-pill confirmed">Sponsors {money(m.committed)}</span>
        </div>

        <div className="mc-card-actions">
          <button type="button" className="m-btn" onClick={() => navigate('finance')}>Open Plan & Budget <ArrowRight size={13} /></button>
        </div>
      </section>
    </div>

    {/* Bottom 60 / 40 Split View */}
    <div className="mc-split">
      {/* Left 60%: Live Agent Activity */}
      <section className="mc-panel" aria-label="Live orchestration trace">
        <header className="mc-panel-head">
          <h2><Activity size={16} color="#2563EB" /> Live Agent Activity</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {latestWorkflowCompleted && <Pill tone="mint">Workflow complete.</Pill>}
            <Button onClick={() => navigate('agents')}><Bot size={14} /> Inspector</Button>
          </div>
        </header>
        {feedItems.length ? (
          <ul className="mc-feed-list">
            {feedItems.map(item => (
              <li key={item.id} className="mc-feed-item">
                <AgentMark name={item.agent} />
                <div className="mc-feed-body">
                  <div className="mc-feed-top">
                    <span className="mc-feed-agent">{item.agent}</span>
                    <span className="mc-feed-time">{relativeTime(item.timestamp)}</span>
                  </div>
                  <p className="mc-feed-desc">{item.description}</p>
                  {item.payload && (
                    <details className="mc-feed-payload">
                      <summary>View payload</summary>
                      <pre>{JSON.stringify(item.payload, null, 2)}</pre>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="m-pad"><p className="m-copy">Agent activity will appear here as workflows run.</p></div>
        )}
      </section>

      {/* Right 40%: Needs Your Approval */}
      <section className="mc-panel">
        <header className="mc-panel-head">
          <h2>Needs Your Approval</h2>
          <Pill tone={pending.length ? 'amber' : 'neutral'}>{pending.length} pending</Pill>
        </header>
        {pending.length ? (
          <div className="mc-approvals-stack">
            {pending.slice(0, 5).map(item => {
              const agent = inferAgent(item, data.runs)
              const impact = impactLabel(item)
              return (
                <article className="mc-approval-card" key={item.id}>
                  <div className="mc-approval-badges">
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <AgentMark name={agent} />
                      <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>{agent}</span>
                    </div>
                    <span className={'mc-impact-chip' + (impact.money ? ' money' : '')}>{impact.text}</span>
                  </div>
                  <h3>{item.title}</h3>
                  {item.description && <p className="mc-approval-summary">{item.description}</p>}
                  <div className="mc-approval-actions">
                    <button type="button" className="m-btn approve-btn" disabled={action.busy} onClick={() => action.run('approve', { approval_id: item.id })}>
                      <Check size={14} /> Approve
                    </button>
                    <button type="button" className="m-btn reject-btn" disabled={action.busy} onClick={() => action.run('reject', { approval_id: item.id })}>
                      Reject
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="m-pad"><p className="m-copy">No decisions pending. Agents are monitoring live feeds.</p></div>
        )}
        <div className="m-pad" style={{ borderTop: '1px solid #F1F5F9', paddingTop: 12, paddingBottom: 14 }}>
          <Button onClick={() => navigate('approvals')}>Review approval history <ArrowRight size={14} /></Button>
        </div>
      </section>
    </div>
    </div>

    {/* Compact Live Agent Team Strip */}
    <div className="mc-agent-strip" role="region" aria-label="Live Agent Team">
      <button type="button" className="mc-agent-pill" onClick={() => navigate('agents')}>
        <AgentMark name="Nexus" />
        <div className="mc-agent-pill-copy">
          <strong>Nexus · Orchestrator</strong>
          <small>{traceConnected ? 'Live stream active' : 'Ready'}</small>
        </div>
        <span className="mc-agent-status">Active</span>
      </button>

      <button type="button" className="mc-agent-pill" onClick={() => navigate('registrations')}>
        <AgentMark name="FormFlow" />
        <div className="mc-agent-pill-copy">
          <strong>FormFlow · Google Forms</strong>
          <small>{form?.is_google_form ? 'Auto-syncing every 18s' : form ? 'Local form live' : 'Not published'}</small>
        </div>
        <span className={'mc-agent-status' + (form?.is_google_form ? '' : ' muted')}>{form?.is_google_form ? 'Live' : 'Local'}</span>
      </button>

      <button type="button" className="mc-agent-pill" onClick={() => navigate('sponsors')}>
        <AgentMark name="Magnet" />
        <div className="mc-agent-pill-copy">
          <strong>Magnet · Gmail Outreach</strong>
          <small>{googleStatus?.connected ? `Monitoring ${contactedCount} thread${contactedCount === 1 ? '' : 's'}` : 'Simulation mode'}</small>
        </div>
        <span className={'mc-agent-status' + (googleStatus?.connected ? '' : ' muted')}>{googleStatus?.connected ? 'Gmail' : 'Demo'}</span>
      </button>

      <button type="button" className="mc-agent-pill" onClick={() => navigate('finance')}>
        <AgentMark name="OpsLedger" />
        <div className="mc-agent-pill-copy">
          <strong>OpsLedger · Budget & Timeline</strong>
          <small>{m.balance >= 0 && m.overdue === 0 ? `${m.readiness}% readiness` : m.balance < 0 ? 'Funding shortfall' : `${m.overdue} overdue tasks`}</small>
        </div>
        <span className={'mc-agent-status' + (m.balance < 0 || m.overdue > 0 ? ' alert' : '')}>
          {m.balance < 0 || m.overdue > 0 ? 'Alert' : 'On track'}
        </span>
      </button>
    </div>

    {qrOpen && qrSrc && (
      <Dialog compact title="Registration QR Code" onClose={() => setQrOpen(false)}>
        <div style={{ padding: 16, textAlign: 'center' }}>
          <img className="registration-qr" src={qrSrc} alt="QR code for registration form" />
          <p style={{ fontSize: 12.5, color: '#64748B', marginTop: 10 }}>
            {form?.is_google_form ? 'Scan to open the live Google Form on any phone.' : 'Scan to open the registration form.'}
          </p>
        </div>
      </Dialog>
    )}
  </div>
}

const fieldOptions = {
  team_name: 'Team name', team_size: 'Team size', track: 'Track', github: 'GitHub link',
  college: 'College / university', diet: 'Dietary requirements', experience: 'Experience level', accessibility: 'Accessibility requirements',
}

export function Registrations({ data, act, refresh, googleStatus, onConnectGoogle }: ViewProps & { refresh: () => Promise<void> }) {
  const [editing, setEditing] = useState(false), [query, setQuery] = useState(''), [message, setMessage] = useState('')
  const [busyGoogle, setBusyGoogle] = useState(false), [qrOpen, setQrOpen] = useState(false)
  const action = useAction(act), form: RegistrationForm | null = data.registration_form
  const participants: Row[] = data.participants
  const filtered = participants.filter(p => (p.name || '').toLowerCase().includes(query.trim().toLowerCase()))

  const formLink = form ? (form.is_google_form && form.responder_uri ? form.responder_uri : (form.public_url || location.origin + '/register/' + form.slug)) : ''
  const qrSrc = form ? (form.is_google_form ? `/api/events/${encodeURIComponent(data.event.id)}/google-form/qr.svg` : `/api/registration/${form.slug}/qr.svg`) : ''

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    try {
      await api('/api/events/' + data.event.id + '/registration', {
        method: 'PUT',
        body: JSON.stringify({ deadline: fields.get('deadline'), fields: fields.getAll('field') }),
      })
      setEditing(false)
      setMessage('Registration form saved.')
      await refresh()
    } catch (err) {
      setMessage((err as Error).message)
    }
  }

  async function createGoogleForm() {
    setBusyGoogle(true); setMessage('')
    try {
      const res = await api<{ message: string }>(`/api/events/${encodeURIComponent(data.event.id)}/create-google-form`, { method: 'POST', body: '{}' })
      setMessage(res.message)
      await refresh()
    } catch (err) {
      setMessage((err as Error).message)
    } finally {
      setBusyGoogle(false)
    }
  }

  async function syncNow() {
    setBusyGoogle(true); setMessage('')
    try {
      const res = await api<{ message: string }>(`/api/events/${encodeURIComponent(data.event.id)}/sync-form-responses`, { method: 'POST' })
      setMessage(res.message)
      await refresh()
    } catch (err) {
      setMessage((err as Error).message)
    } finally {
      setBusyGoogle(false)
    }
  }

  function exportCsv() {
    const cols = Object.keys(fieldOptions)
    const safe = (value: unknown) => '"' + String(value ?? '').replace(/^[=+\-@\t\r]/, "'$&").replaceAll('"', '""') + '"'
    const content = [['Name', 'Email', 'Checked in', ...Object.values(fieldOptions)], ...participants.map(p => [p.name, p.email, p.checked_in ? 'Yes' : 'No', ...cols.map(key => p.answers?.[key])])].map(row => row.map(safe).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'clubos-registrations.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <>
    <Head
      title="Registrations & Form"
      sub={data.event.name}
      action={
        <div className="m-actions" style={{ margin: 0 }}>
          {googleStatus?.connected && <Button primary busy={busyGoogle} onClick={createGoogleForm}><Sparkles size={15} /> {form?.is_google_form ? 'Regenerate Google Form' : 'Create Google Form'}</Button>}
          {form?.is_google_form && googleStatus?.connected && <Button busy={busyGoogle} onClick={syncNow}><RefreshCw size={15} /> Sync Responses Now</Button>}
          <Button onClick={() => setEditing(true)}>{form ? 'Edit local form' : 'Publish form'}</Button>
        </div>
      }
    />

    {!googleStatus?.connected && (
      <div className="mc-banner-info" style={{ marginBottom: 14 }}>
        <span>Connect Google in the top bar so FormFlow creates a real Google Form and syncs submissions automatically.</span>
        <Button onClick={onConnectGoogle}>Connect Google</Button>
      </div>
    )}

    {message && <div className="m-notice success" role="status">{message}<button onClick={() => setMessage('')} aria-label="Dismiss">✕</button></div>}
    <Notice state={action} />

    {form && (
      <section className="m-card" style={{ marginBottom: 16 }}>
        <div className="m-titleline">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h3>{form.is_google_form ? 'Live Google Form' : 'Public registration form'}</h3>
            <Pill tone={form.is_google_form ? 'mint' : 'neutral'}>{form.is_google_form ? 'Google Forms API' : 'Local Form'}</Pill>
          </div>
          {form.deadline && <span className="m-sub">Closes {day(form.deadline, true)}</span>}
        </div>
        <p style={{ marginTop: 8 }}>
          {form.is_google_form
            ? `Responses sync automatically every 18s (${form.response_count ?? 0} synced from Google Forms).`
            : `Full name, email${form.fields.map(field => ', ' + field.label).join('')}`}
        </p>
        <div className="m-actions" style={{ marginTop: 12 }}>
          <CopyButton icon label="Copy form link" value={formLink} />
          <a className="m-btn" href={formLink} target="_blank" rel="noreferrer" aria-label="Open public form">Open Form <ArrowUpRight size={14} /></a>
          {form.edit_uri && <a className="m-btn" href={form.edit_uri} target="_blank" rel="noreferrer">Edit in Google Forms <ExternalLink size={13} /></a>}
          <Button onClick={() => setQrOpen(true)}><QrCode size={14} /> QR Code</Button>
        </div>
      </section>
    )}

    <Panel title={participants.length + ' registrations'} action={<Button onClick={exportCsv}>Export CSV</Button>}>
      <div className="m-pad"><label className="m-field">Search participants<input type="search" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
      <div className="m-tablewrap m-scrolltable is-tall" role="region" aria-label="Registrants" tabIndex={0}>
        <table className="m-table">
          <thead><tr><th>Name</th><th>Email</th>{form?.fields.map(field => <th key={field.key}>{field.label}</th>)}<th>Attendance</th></tr></thead>
          <tbody>
            {filtered.map(p => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.email}</td>
                {form?.fields.map(field => <td key={field.key}>{p.answers?.[field.key]}</td>)}
                <td>{p.checked_in ? 'Checked in' : <Button busy={action.busy} onClick={() => action.run('check_in', { participant_id: p.id })}>Check in</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>

    {qrOpen && qrSrc && (
      <Dialog compact title="Registration QR Code" onClose={() => setQrOpen(false)}>
        <div style={{ padding: 16, textAlign: 'center' }}>
          <img className="registration-qr" src={qrSrc} alt="QR code for registration form" />
          <p className="m-copy">Scan with any phone camera to open and submit the form.</p>
        </div>
      </Dialog>
    )}

    {editing && <Dialog title="Registration form settings" onClose={() => setEditing(false)}>
      <form className="m-form m-pad" onSubmit={save}>
        <label className="m-field">Registration deadline<input name="deadline" type="date" required defaultValue={form?.deadline || data.event.start_date} max={data.event.start_date} /></label>
        <fieldset><legend>Additional fields</legend>{Object.entries(fieldOptions).map(([key, label]) => <label className="m-row" key={key}><input name="field" value={key} type="checkbox" defaultChecked={form?.fields.some(field => field.key === key)} />{label}</label>)}</fieldset>
        <Button primary type="submit">Save public form</Button>
      </form>
    </Dialog>}
  </>
}
