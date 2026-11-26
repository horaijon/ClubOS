import { useEffect, useState } from 'react'
import { ArrowRight, Building2, ChevronRight, Download, FileText, Mail, MailCheck, Plus, RefreshCw, Send, Sparkles, Trash2, Upload, Users } from 'lucide-react'
import { Button, CopyButton, Dialog, Empty, Field, Head, Notice, Panel, Pill, SearchBox, Tabs, day, formValues, human, money, useAction } from './ui'
import type { Row, ViewProps } from './ui'
import { api } from '../data'
import { TraceView } from '../LiveTrace'
import ImportCsv from './ImportCsv'

export const stages = ['Identified', 'Shortlisted', 'Outreach Drafted', 'Contacted', 'Responded', 'Negotiating', 'Confirmed', 'Declined', 'Withdrawn']

interface OutreachItem {
  sponsor_id: string
  name: string
  industry: string
  website?: string
  description?: string
  score: number
  reason: string
  stage: string
  contact_email: string
  subject: string
  body: string
}

export default function Sponsors(props: ViewProps) {
  const { data, act, googleStatus, onConnectGoogle, refresh } = props
  const [tab, setTab] = useState('Pipeline'), [query, setQuery] = useState(''), [open, setOpen] = useState(''), [importing, setImporting] = useState(false), [editing, setEditing] = useState<Row | null>(null)
  const [addingReal, setAddingReal] = useState(false)
  const [checkingReplies, setCheckingReplies] = useState(false)
  const [replyNotice, setReplyNotice] = useState('')
  const [queue, setQueue] = useState<OutreachItem[]>([])
  const [discovering, setDiscovering] = useState(false)
  const [sendingAll, setSendingAll] = useState(false)
  const [addingInline, setAddingInline] = useState(false)
  const [newContact, setNewContact] = useState({ name: '', contact_email: '', industry: 'Developer Tools & AI' })
  const state = useAction(act)
  const sponsors: Row[] = data.sponsors, prospects: Row[] = data.prospects, packages: Row[] = data.packages || []
  const match = (x: Row) => [x.name, x.industry, x.contact_email || ''].join(' ').toLowerCase().includes(query.toLowerCase())
  const filtered = sponsors.filter(match)
  const selected = sponsors.find(s => s.id === open)

  async function discoverQueue() {
    setDiscovering(true)
    setReplyNotice('')
    try {
      const res = await api<{ items: OutreachItem[]; message: string }>(
        `/api/events/${encodeURIComponent(data.event.id)}/outreach-list/discover`,
        { method: 'POST' },
      )
      setQueue(res.items || [])
      setTab('Outreach Queue')
      setReplyNotice(res.message)
      await refresh?.()
    } catch (err) {
      setReplyNotice((err as Error).message)
    } finally {
      setDiscovering(false)
    }
  }

  function updateQueueItem(sponsorId: string, patch: Partial<OutreachItem>) {
    setQueue(prev => prev.map(item => (item.sponsor_id === sponsorId ? { ...item, ...patch } : item)))
  }

  function removeQueueItem(sponsorId: string) {
    setQueue(prev => prev.filter(item => item.sponsor_id !== sponsorId))
  }

  async function addInlineContact(e: React.FormEvent) {
    e.preventDefault()
    if (!newContact.name.trim() || !newContact.contact_email.trim()) return
    setAddingInline(true)
    setReplyNotice('')
    try {
      const res = await act('add_demo_sponsor', {
        name: newContact.name.trim(),
        contact_email: newContact.contact_email.trim(),
        industry: newContact.industry.trim() || 'Technology',
      })
      const draftText: string = res.draft || ''
      const firstLine = draftText.split('\n')[0] || ''
      const subject = firstLine.toLowerCase().startsWith('subject:')
        ? firstLine.slice(8).trim()
        : `Sponsorship Partnership — ${data.event.name} × ${newContact.name.trim()}`
      const body = firstLine.toLowerCase().startsWith('subject:')
        ? draftText.split('\n').slice(1).join('\n').trim()
        : draftText
      setQueue(prev => [
        {
          sponsor_id: res.sponsor_id,
          name: newContact.name.trim(),
          industry: newContact.industry.trim() || 'Technology',
          score: 95,
          reason: 'Organizer-added contact.',
          stage: 'Outreach Drafted',
          contact_email: newContact.contact_email.trim(),
          subject,
          body,
        },
        ...prev,
      ])
      setNewContact({ name: '', contact_email: '', industry: 'Developer Tools & AI' })
      setReplyNotice(`Added ${newContact.name.trim()} with a specialized Magnet email.`)
    } catch (err) {
      setReplyNotice((err as Error).message)
    } finally {
      setAddingInline(false)
    }
  }

  async function regenerateOne(sponsorId: string) {
    try {
      const res = await act('outreach', { sponsor_id: sponsorId })
      const draftText: string = res.text || ''
      const firstLine = draftText.split('\n')[0] || ''
      const subject = firstLine.toLowerCase().startsWith('subject:')
        ? firstLine.slice(8).trim()
        : undefined
      const body = firstLine.toLowerCase().startsWith('subject:')
        ? draftText.split('\n').slice(1).join('\n').trim()
        : draftText
      updateQueueItem(sponsorId, { ...(subject ? { subject } : {}), body })
    } catch (err) {
      setReplyNotice((err as Error).message)
    }
  }

  async function sendAllConfirmed() {
    const ready = queue.filter(i => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(i.contact_email.trim()) && i.subject.trim() && i.body.trim())
    if (!ready.length) {
      setReplyNotice('Add a valid contact email for at least one contact before sending.')
      return
    }
    setSendingAll(true)
    setReplyNotice('')
    try {
      const res = await api<{ sent_count: number; failed_count: number; sent: { sponsor_id: string }[]; message: string }>(
        `/api/events/${encodeURIComponent(data.event.id)}/outreach-list/send-all`,
        {
          method: 'POST',
          body: JSON.stringify({
            simulate: !googleStatus?.connected,
            items: ready.map(i => ({
              sponsor_id: i.sponsor_id,
              to_email: i.contact_email.trim(),
              subject: i.subject.trim(),
              body: i.body.trim(),
            })),
          }),
        },
      )
      const sentIds = new Set((res.sent || []).map(s => s.sponsor_id))
      setQueue(prev => prev.filter(i => !sentIds.has(i.sponsor_id)))
      setReplyNotice(res.message)
      await refresh?.()
    } catch (err) {
      setReplyNotice((err as Error).message)
    } finally {
      setSendingAll(false)
    }
  }

  async function checkInboxNow() {
    setCheckingReplies(true)
    setReplyNotice('')
    try {
      const res = await api<{ message: string; count: number }>(`/api/events/${encodeURIComponent(data.event.id)}/check-replies`, { method: 'POST' })
      setReplyNotice(res.message)
      if (res.count > 0) props.navigate('approvals')
    } catch (err) {
      setReplyNotice((err as Error).message)
    } finally {
      setCheckingReplies(false)
    }
  }

  const readyCount = queue.filter(i => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(i.contact_email.trim()) && i.subject.trim() && i.body.trim()).length

  return <>
    <Head
      title="Sponsorships"
      sub="Discover contacts, review specialized Magnet emails, customize the list, and send all in one click."
      action={
        <div className="m-actions" style={{ margin: 0 }}>
          <Button primary busy={discovering} onClick={discoverQueue}><Sparkles size={15} /> Find Contacts &amp; Draft Emails</Button>
          {googleStatus?.connected && <Button busy={checkingReplies} onClick={checkInboxNow}><MailCheck size={15} /> Check Gmail Replies Now</Button>}
          <Button onClick={() => setImporting(true)}><Upload size={15} /> Import CSV</Button>
          <Button onClick={() => setAddingReal(true)}><Plus size={15} /> Add Real Demo Sponsor</Button>
        </div>
      }
    />

    {!googleStatus?.connected && (
      <div className="mc-banner-info" style={{ marginBottom: 14 }}>
        <span>Simulation mode active — connect Google in the top bar for real Gmail delivery and automatic inbox reply tracking.</span>
        <Button onClick={onConnectGoogle}>Connect Google</Button>
      </div>
    )}

    <section className="m-card" style={{ marginBottom: 16 }}>
      <h3>Sponsorship funding</h3>
      <p>{money(data.event.initial_budget)} club funds + {money(data.metrics.committed)} confirmed · {money(data.metrics.planned)} planned</p>
      <progress aria-label="Funding progress" value={Math.min(data.metrics.projected_funding, data.metrics.planned)} max={data.metrics.planned || 1} />
      {sponsors.some(s => s.stage === 'Outreach Drafted') && (
        <div className="m-actions">
          <Button busy={state.busy} onClick={() => state.run('prepare_outreach', {}, undefined, () => props.navigate('approvals'))}>
            {googleStatus?.connected ? 'Review & Send Outreach' : 'Review simulated outreach'}
          </Button>
        </div>
      )}
    </section>

    <div className="m-toolrow">
      <Tabs
        current={tab}
        onChange={next => {
          setTab(next)
          if (next === 'Outreach Queue' && queue.length === 0 && !discovering) void discoverQueue()
        }}
        options={['Pipeline', 'Outreach Queue', 'Discover', 'Packages']}
      />
      {tab !== 'Packages' && tab !== 'Outreach Queue' && <SearchBox placeholder="Search sponsors" value={query} onChange={setQuery} />}
    </div>
    {replyNotice && <div className="m-notice success" role="status">{replyNotice}<button onClick={() => setReplyNotice('')} aria-label="Dismiss">✕</button></div>}
    <Notice state={state} />

    {tab === 'Outreach Queue' && (
      <div className="m-stack">
        {/* Bulk Action Bar */}
        <section className="m-card" style={{ background: '#F8FAFC' }}>
          <div className="m-titleline">
            <div>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Users size={17} /> Magnet Outreach List ({queue.length} contacts)
              </h3>
              <p className="m-copy" style={{ margin: '4px 0 0' }}>
                Edit any email or body below, remove contacts you want to skip, or add new contacts.{' '}
                <strong>{readyCount} of {queue.length}</strong> have email addresses ready to send.
              </p>
            </div>
            <div className="m-actions" style={{ margin: 0 }}>
              <Button busy={discovering} onClick={discoverQueue}><RefreshCw size={14} /> Refresh Contacts</Button>
              <Button
                primary
                busy={sendingAll}
                disabled={readyCount === 0}
                onClick={sendAllConfirmed}
              >
                <Send size={14} /> {googleStatus?.connected ? `Confirm & Send All (${readyCount})` : `Simulate Send All (${readyCount})`}
              </Button>
            </div>
          </div>
        </section>

        {/* Add Contact Inline */}
        <section className="m-card">
          <h3 style={{ marginBottom: 10 }}>Add Contact to Outreach List</h3>
          <form onSubmit={addInlineContact} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr) minmax(0,1fr) auto', gap: 10, alignItems: 'end' }}>
            <Field label="Sponsor / Company">
              <input required placeholder="e.g. Vercel / Judge Corp" value={newContact.name} onChange={e => setNewContact(c => ({ ...c, name: e.target.value }))} />
            </Field>
            <Field label="Contact Email">
              <input required type="email" placeholder="sponsor@company.com" value={newContact.contact_email} onChange={e => setNewContact(c => ({ ...c, contact_email: e.target.value }))} />
            </Field>
            <Field label="Industry">
              <input placeholder="Cloud / AI / Hardware" value={newContact.industry} onChange={e => setNewContact(c => ({ ...c, industry: e.target.value }))} />
            </Field>
            <Button primary type="submit" busy={addingInline}><Plus size={14} /> Add &amp; Draft</Button>
          </form>
        </section>

        {/* Editable Contact & Specialized Email Cards */}
        {queue.length ? queue.map(item => {
          const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(item.contact_email.trim())
          return (
            <article key={item.sponsor_id} className="m-card">
              <div className="m-titleline" style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <h3 style={{ fontSize: 16 }}>{item.name}</h3>
                  <Pill tone="purple">{item.score}% match</Pill>
                  <Pill>{item.industry}</Pill>
                  <Pill tone={emailValid ? 'mint' : 'amber'}>{emailValid ? 'Ready to send' : 'Needs email'}</Pill>
                  {item.website && (
                    <a href={item.website} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#2563EB', textDecoration: 'underline' }}>
                      {item.website.replace(/^https?:\/\/(www\.)?/, '')} ↗
                    </a>
                  )}
                </div>
                <div className="m-actions" style={{ margin: 0 }}>
                  <Button busy={state.busy} onClick={() => regenerateOne(item.sponsor_id)}><Sparkles size={13} /> Regenerate</Button>
                  <Button danger onClick={() => removeQueueItem(item.sponsor_id)}><Trash2 size={13} /> Remove</Button>
                </div>
              </div>
              {item.description && <p className="m-copy" style={{ margin: '0 0 10px', fontSize: 12.5 }}>{item.description}</p>}

              <div className="m-fields2" style={{ marginBottom: 10 }}>
                <Field label="Recipient email">
                  <input
                    type="email"
                    placeholder="Enter sponsor email (e.g. partner@company.com)"
                    value={item.contact_email}
                    onChange={e => updateQueueItem(item.sponsor_id, { contact_email: e.target.value })}
                  />
                </Field>
                <Field label="Email subject">
                  <input
                    value={item.subject}
                    onChange={e => updateQueueItem(item.sponsor_id, { subject: e.target.value })}
                  />
                </Field>
              </div>

              <Field label="Specialized email body (tailored by Magnet)">
                <textarea
                  rows={5}
                  value={item.body}
                  onChange={e => updateQueueItem(item.sponsor_id, { body: e.target.value })}
                />
              </Field>
            </article>
          )
        }) : (
          <Panel><Empty title="Outreach list is empty" detail="Click Refresh Contacts above or add a custom sponsor contact." /></Panel>
        )}
      </div>
    )}

    {tab === 'Pipeline' && (
      <Panel title="Sponsor pipeline" action={<span className="m-sub">{filtered.length} partners</span>}>
        {filtered.map(x => (
          <button key={x.id} type="button" className="simple-row" onClick={() => setOpen(x.id)} aria-label={'Open ' + x.name}>
            <strong>{x.name}</strong>
            <span>{x.contact_email ? `${x.contact_email} · ` : ''}{x.industry} · {x.score}% match</span>
            <Pill>{x.stage}</Pill>
            <ChevronRight size={14} />
          </button>
        ))}
        {!filtered.length && <Empty title="No partners found" detail="Click Find Contacts & Draft Emails or Add Real Demo Sponsor." />}
      </Panel>
    )}

    {tab === 'Discover' && (
      <div className="m-grid">
        {prospects.filter(match).map((x: Row) => {
          const added = sponsors.find(s => s.name === x.name)
          return (
            <article className="m-card" key={x.id}>
              <div className="m-titleline"><span className="m-symbol"><Building2 size={18} /></span><Pill tone="mint">{x.score}% match</Pill></div>
              <h3 style={{ marginTop: 13 }}>{x.name}</h3>
              <small className="m-sub">{x.industry}</small>
              <p>{x.description}</p>
              <p><strong>Match rationale</strong> · {x.reason}</p>
              <div className="m-actions">
                {added ? <Button onClick={() => setOpen(added.id)}>View partner <ArrowRight /></Button> : <Button busy={state.busy} onClick={() => state.run('add_prospect', { prospect_id: x.id }, x.name + ' added to pipeline.')}><Plus /> Add to pipeline</Button>}
              </div>
            </article>
          )
        })}
        {!prospects.some(match) && <Empty title="No matching prospects" />}
      </div>
    )}

    {tab === 'Packages' && (
      <div className="m-grid">
        {packages.map(p => (
          <article key={p.id} className="m-card">
            <div className="m-titleline"><FileText size={20} className="ink-purple" /><Pill>Proposed package</Pill></div>
            <h3 style={{ marginTop: 15 }}>{p.name}</h3>
            <p className="m-value">{money(p.amount)}</p>
            <p>{Array.isArray(p.benefits) ? p.benefits.join(' · ') : p.benefits}</p>
            <Button onClick={() => setEditing(p)}>Edit package</Button>
          </article>
        ))}
        {!packages.length && <Empty title="No sponsorship packages yet" />}
      </div>
    )}

    {selected && <Partner key={selected.id} sponsor={selected} {...props} onClose={() => setOpen('')} />}
    {importing && <ImportCsv kind="sponsors" act={act} onClose={() => setImporting(false)} />}

    {addingReal && (
      <Dialog title="Add Real Demo Sponsor" onClose={() => setAddingReal(false)}>
        <Notice state={state} />
        <p className="m-copy">Enter a teammate's or judge's email address so Magnet can send a real Gmail pitch and track their reply live.</p>
        <form className="m-form" onSubmit={e => {
          const v = formValues(e)
          state.run('add_demo_sponsor', v, undefined, r => {
            setAddingReal(false)
            if (r?.sponsor_id) setOpen(r.sponsor_id)
          })
        }}>
          <Field label="Sponsor / Company name"><input name="name" required placeholder="e.g. Acme Cloud" /></Field>
          <Field label="Contact email"><input name="contact_email" type="email" required placeholder="teammate@gmail.com" /></Field>
          <Field label="Industry"><input name="industry" defaultValue="Developer Tools & AI" /></Field>
          <div className="m-actions">
            <Button onClick={() => setAddingReal(false)}>Cancel</Button>
            <Button primary busy={state.busy} type="submit"><Sparkles size={14} /> Add &amp; Draft Pitch</Button>
          </div>
        </form>
      </Dialog>
    )}

    {editing && (
      <Dialog title="Edit sponsorship package" onClose={() => setEditing(null)}>
        <Notice state={state} />
        <form className="m-form" onSubmit={e => {
          const v = formValues(e)
          state.run('update_package', { package_id: editing.id, ...v, amount: Math.round(Number(v.amount) * 100) }, undefined, () => setEditing(null))
        }}>
          <Field label="Tier name"><input name="name" required defaultValue={editing.name} /></Field>
          <Field label="Requested amount (₹)"><input name="amount" type="number" min="0" step=".01" required defaultValue={editing.amount / 100} /></Field>
          <Field label="Benefits"><textarea name="benefits" required defaultValue={editing.benefits} /></Field>
          <Button primary busy={state.busy} type="submit">Save package</Button>
        </form>
      </Dialog>
    )}
  </>
}

function Partner({ sponsor: s, data, act, navigate, onClose, trace, traceConnected, traceRequest, googleStatus }: ViewProps & { sponsor: Row; onClose: () => void }) {
  const [tab, setTab] = useState('Overview'), [draft, setDraft] = useState(s.draft || ''), [contactEmail, setContactEmail] = useState(s.contact_email || '')
  const [subject, setSubject] = useState(() => {
    const first = (s.draft || '').split('\n')[0] || ''
    return first.toLowerCase().startsWith('subject:') ? first.slice(8).trim() : `Partnership Invitation — ${data.event.name} × ${s.name}`
  })
  const [emails, setEmails] = useState<Row[]>([])
  const [sendingReal, setSendingReal] = useState(false), [emailStatus, setEmailStatus] = useState('')
  const [source, setSource] = useState(''), [docType, setDocType] = useState('Sponsor response'), [result, setResult] = useState<Row | null>(null)
  const [uploadError, setUploadError] = useState(''), [loading, setLoading] = useState(false), [withdrawing, setWithdrawing] = useState(false)
  const [stage, setStage] = useState(s.stage), [evidence, setEvidence] = useState('')
  const state = useAction(act)
  const payload = { sponsor_id: s.id }
  const goApprovals = () => { onClose(); navigate('approvals') }
  const tabChange = (v: string) => { setTab(v); state.clear(); setEmailStatus('') }
  const confirmation = trace.some(step => step.request_id === traceRequest && step.input_payload.trigger === 'sponsor_stage' && s.stage === 'Confirmed')
  const confirming = state.busy && stage === 'Confirmed' && s.stage !== stage

  useEffect(() => {
    api<{ emails: Row[] }>(`/api/events/${encodeURIComponent(data.event.id)}/sponsors/${encodeURIComponent(s.id)}/emails`)
      .then(res => setEmails(res.emails || []))
      .catch(() => { })
  }, [data.event.id, s.id, sendingReal])

  async function sendRealGmail() {
    if (!contactEmail.trim()) {
      setEmailStatus('Enter a recipient email address first.')
      return
    }
    setSendingReal(true); setEmailStatus('')
    try {
      const cleanBody = draft.toLowerCase().startsWith('subject:') ? draft.split('\n').slice(1).join('\n').trim() : draft
      await state.run('send_real_email', { sponsor_id: s.id, to_email: contactEmail.trim(), subject, body: cleanBody || draft }, undefined, () => {
        setEmailStatus(`Sent via Gmail to ${contactEmail.trim()}.`)
      })
    } finally {
      setSendingReal(false)
    }
  }

  return (
    <Dialog title={s.name} onClose={onClose}>
      <Tabs current={tab} onChange={tabChange} options={['Overview', 'Outreach', 'Intelligence', 'Deliverables']} />
      <Notice state={state} />
      {emailStatus && <div className="m-notice success" role="status">{emailStatus}</div>}

      {tab === 'Overview' && (
        <div className="m-stack">
          <div className="m-titleline"><span className="m-sub">{s.industry}</span><Pill>{s.stage}</Pill></div>
          <p className="m-copy">{s.reason || s.description}</p>

          <form className="m-form" onSubmit={e => {
            e.preventDefault()
            state.run('update_sponsor_email', { sponsor_id: s.id, contact_email: contactEmail }, 'Contact email saved.')
          }}>
            <Field label="Sponsor contact email">
              <div style={{ display: 'flex', gap: 8 }}>
                <input type="email" value={contactEmail} onChange={e => setContactEmail(e.target.value)} placeholder="sponsor@company.com" />
                <Button type="submit" busy={state.busy}>Save</Button>
              </div>
            </Field>
          </form>

          {s.stage === 'Contacted' && !googleStatus?.connected && (
            <Button busy={state.busy} onClick={() => state.run('simulate_reply', payload, undefined, goApprovals)}>Simulate sponsor reply</Button>
          )}

          {s.draft && <details><summary>View sponsor pitch</summary><p className="m-copy" style={{ whiteSpace: 'pre-wrap' }}>{s.draft}</p></details>}

          <dl className="m-facts">
            <div><dt>Confirmed commitment</dt><dd>{money(s.committed)}</dd></div>
            <div><dt>Payments received</dt><dd>{money(s.received)}</dd></div>
            {s.receivable && <div><dt>Payment deadline</dt><dd>{day(s.receivable.due_date, true)}</dd></div>}
          </dl>

          <form className="m-form" onSubmit={e => {
            const v = formValues(e)
            state.run('sponsor_stage', { ...payload, stage, ...(stage === 'Confirmed' ? { amount: Math.round(Number(v.amount) * 100), due_date: v.due_date } : {}) }, stage === 'Confirmed' ? 'Commitment recorded. Linked tasks and the announcement draft are ready.' : 'Pipeline stage updated.')
          }}>
            <Field label="Pipeline stage"><select value={stage} onChange={e => setStage(e.target.value)}>{stages.filter(x => x !== 'Withdrawn' || s.stage === 'Withdrawn').map(x => <option key={x}>{x}</option>)}</select></Field>
            {stage === 'Confirmed' && s.stage !== stage && <>
              <Field label="Commitment amount (₹)"><input required name="amount" type="number" min=".01" step=".01" /></Field>
              <Field label="Payment due"><input required name="due_date" type="date" defaultValue={data.event.start_date} /></Field>
              <p className="m-copy">Confirming creates a receivable, linked deliverables, and an announcement draft.</p>
            </>}
            <div><Button type="submit" busy={state.busy} disabled={s.stage === stage}>Update stage</Button></div>
          </form>

          {s.stage === 'Confirmed' && s.committed > s.received && (
            <form className="m-form" onSubmit={e => {
              const v = formValues(e)
              state.run('record_payment', { ...payload, amount: Math.round(Number(v.amount) * 100) }, 'Sponsor payment recorded.')
            }}>
              <Field label="Record payment (₹)"><input name="amount" type="number" min=".01" step=".01" max={(s.committed - s.received) / 100} required /></Field>
              <div><Button type="submit" busy={state.busy}>Record payment</Button></div>
            </form>
          )}

          {s.stage === 'Confirmed' && !s.received && (
            <div>
              {withdrawing ? <>
                <p className="m-copy">Withdrawing {money(s.committed)} removes this unpaid commitment from projected funding and starts a risk assessment.</p>
                <div className="m-actions">
                  <Button danger busy={state.busy} onClick={() => state.run('withdraw', payload, 'Withdrawal recorded. Review the resulting risks and approvals.', () => setWithdrawing(false))}>Confirm withdrawal</Button>
                  <Button onClick={() => setWithdrawing(false)}>Cancel</Button>
                </div>
              </> : <Button danger onClick={() => setWithdrawing(true)}>Record withdrawal</Button>}
            </div>
          )}

          <a className="m-btn" href={'/api/events/' + data.event.id + '/sponsors/' + s.id + '/report.pdf'} download><Download size={15} /> Sponsor impact report</a>
        </div>
      )}

      {tab === 'Outreach' && (
        <div className="m-stack">
          <div className="m-actions">
            {['outreach', 'proposal'].map(x => (
              <Button key={x} busy={state.busy} onClick={() => state.run(x, payload, undefined, r => {
                setDraft(r.text)
                const firstLine = (r.text || '').split('\n')[0] || ''
                if (firstLine.toLowerCase().startsWith('subject:')) setSubject(firstLine.slice(8).trim())
                state.clear()
              })}>
                <Sparkles /> {x === 'outreach' ? 'Draft outreach with Magnet' : 'Generate proposal'}
              </Button>
            ))}
          </div>

          <Field label="Recipient email">
            <input type="email" value={contactEmail} onChange={e => setContactEmail(e.target.value)} placeholder="sponsor@company.com" />
          </Field>
          <Field label="Email subject">
            <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Sponsorship Partnership" />
          </Field>
          <Field label="Email body">
            <textarea value={draft} rows={8} placeholder="Generate outreach or write a pitch for this partner." onChange={e => setDraft(e.target.value)} />
          </Field>

          <div className="m-actions">
            {googleStatus?.connected && (
              <Button primary disabled={!draft.trim() || !contactEmail.trim()} busy={sendingReal || state.busy} onClick={sendRealGmail}>
                <Send size={14} /> Send Real Email via Gmail
              </Button>
            )}
            <Button disabled={!draft.trim()} busy={state.busy} onClick={() => state.run('save_draft', { ...payload, text: draft }, 'Draft saved.')}>Save draft</Button>
            {draft && <CopyButton value={draft} />}
          </div>

          {emails.length > 0 && (
            <Panel title={`Gmail Thread (${emails.length})`}>
              <div className="m-pad m-stack">
                {emails.map(em => (
                  <div key={em.id} className="m-card" style={{ padding: 12 }}>
                    <div className="m-titleline">
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 650, fontSize: 12.5 }}>
                        <Mail size={13} /> {em.direction === 'outbound' ? `Sent to ${em.recipient_email}` : `Reply from ${em.recipient_email}`}
                      </span>
                      <Pill tone={em.direction === 'inbound' ? 'mint' : 'purple'}>
                        {em.direction === 'inbound' ? (em.parsed_status || 'Inbound') : 'Sent'}
                      </Pill>
                    </div>
                    <p style={{ margin: '6px 0 0', fontSize: 12.5, whiteSpace: 'pre-wrap' }}>{em.body}</p>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <form className="m-form" onSubmit={e => {
            const v = formValues(e)
            state.run('follow_up', { ...payload, days: Number(v.days) }, 'Follow-up scheduled.')
          }}>
            <Field label="Follow up after (days)"><input name="days" defaultValue={s.follow_up_days || 5} min="1" max="60" required type="number" /></Field>
            <div><Button type="submit" busy={state.busy}>Schedule follow-up</Button></div>
          </form>
        </div>
      )}

      {tab === 'Intelligence' && (
        <div className="m-stack">
          <Field label="Source">
            <select value={docType} onChange={e => { setDocType(e.target.value); setResult(null); setSource('') }}>
              <option>Sponsor response</option>
              <option>Sponsorship agreement</option>
            </select>
          </Field>
          {docType === 'Sponsorship agreement' && (
            <Field label="Extract text from a PDF">
              <input type="file" accept="application/pdf,.pdf" disabled={loading} onChange={async e => {
                const file = e.target.files?.[0]; if (!file) return
                setLoading(true); setUploadError('')
                try {
                  if (file.size > 4_000_000) throw new Error('Choose a PDF smaller than 4 MB.')
                  const fd = new FormData(); fd.append('file', file)
                  const res = await fetch('/api/events/' + data.event.id + '/agreement-text', { method: 'POST', body: fd })
                  const out = await res.json()
                  if (!res.ok) throw new Error(out.detail || 'Could not read this PDF.')
                  setSource(out.text); setResult(null)
                } catch (err) {
                  setUploadError((err as Error).message)
                } finally {
                  setLoading(false)
                }
              }} />
            </Field>
          )}
          {uploadError && <div className="m-notice error" role="alert">{uploadError}</div>}
          <Field label={docType === 'Sponsor response' ? 'Response text' : 'Agreement text'}>
            <textarea rows={6} value={source} onChange={e => { setSource(e.target.value); setResult(null) }} placeholder="Paste the original text for Magnet to analyze." />
          </Field>
          <div>
            <Button primary busy={loading || state.busy} disabled={!source.trim()} onClick={() => state.run(docType === 'Sponsor response' ? 'analyze_response' : 'analyze_agreement', { ...payload, text: source }, undefined, setResult)}>
              <Sparkles /> Analyze terms
            </Button>
          </div>
          {result && (
            <Panel title="Extracted terms">
              <div className="m-pad">
                <Terms terms={result.terms} />
                <div className="m-actions"><Button onClick={goApprovals}>Review approval <ArrowRight /></Button></div>
              </div>
            </Panel>
          )}
        </div>
      )}

      {tab === 'Deliverables' && <>
        <div className="m-stack">
          {(s.deliverables || []).map((d: Row) => (
            <article className="m-card" key={d.id}>
              <div className="m-titleline"><h3>{d.title}</h3><Pill>{d.status}</Pill></div>
              <p>{d.owner} · Due {day(d.due_date)}</p>
              {d.evidence && <p>Evidence · {d.evidence}</p>}
              {d.status !== 'Completed' && (evidence === d.id ? (
                <form className="m-form" onSubmit={e => {
                  const v = formValues(e)
                  state.run('complete_deliverable', { deliverable_id: d.id, evidence: v.evidence }, 'Deliverable completed.', () => setEvidence(''))
                }}>
                  <Field label="Evidence or reference link"><input name="evidence" required /></Field>
                  <Button type="submit" busy={state.busy}>Save completion</Button>
                </form>
              ) : <Button onClick={() => setEvidence(d.id)}>Record completion</Button>)}
            </article>
          ))}
        </div>
        {!s.deliverables?.length && <Empty title="No approved deliverables" detail="Analyze an agreement and approve its terms to create assigned deliverables." />}
      </>}

      {(confirming || confirmation) && <TraceView steps={trace} connected={traceConnected} requestId={traceRequest} compact />}
    </Dialog>
  )
}

export function Terms({ terms }: { terms: any }) {
  if (terms == null) return null
  if (typeof terms !== 'object') return <span>{String(terms)}</span>
  if (Array.isArray(terms)) return <ul>{terms.map((v, i) => <li key={i}><Terms terms={v} /></li>)}</ul>
  return <dl className="m-terms">{Object.entries(terms).filter(([k, v]) => v != null && v !== '' && !k.endsWith('_id')).map(([k, v]) => <div key={k}><dt>{human(k)}</dt><dd>{(typeof v === 'number' && /amount|funding|committed|received|planned|shortfall|saving|target_paise|impact_paise/.test(k)) ? money(v) : <Terms terms={v} />}</dd></div>)}</dl>
}
