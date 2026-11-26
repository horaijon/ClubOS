import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, Clock, Flag, HelpCircle, Scale, ShieldCheck } from 'lucide-react'
import { api, type AppealRecord, type AuditLogRecord, type Snapshot } from './data'
import { AgentMark } from './Identity'
import { Dialog } from './Dialog'
import { Button, Field, Notice, Pill, day, useAction } from './modules/ui'

export type TargetType = 'approval' | 'risk' | 'disruption' | 'sponsor' | 'run' | 'poster'

interface ExplainResponse {
  target_type: TargetType
  target_id: string
  title: string
  agent: string
  mode: string
  outcome_status: string
  summary: string
  rules: { name: string; condition: string; result: string; passed: boolean }[]
  constraints: { label: string; limit: string; actual: string }[]
  scores: { metric: string; value: string; weight_or_basis: string }[]
  inputs: Record<string, unknown>
  appeals: AppealRecord[]
  audit_log: AuditLogRecord[]
}

const statusTone = (status?: string) =>
  status === 'Overridden' ? 'mint' : status === 'Under Review' ? 'purple' : status === 'Flagged' ? 'amber' : 'neutral'

export function DecisionExplainControl({
  data,
  act,
  targetType,
  targetId,
  compact = false,
}: {
  data: Snapshot
  act: (type: string, payload?: Record<string, unknown>) => Promise<any>
  targetType: TargetType
  targetId: string
  compact?: boolean
}) {
  const [open, setOpen] = useState<'explain' | 'appeal' | null>(null)
  const [info, setInfo] = useState<ExplainResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [reason, setReason] = useState('')
  const [overrideReq, setOverrideReq] = useState('')
  const [resNote, setResNote] = useState('')
  const [applyOverride, setApplyOverride] = useState(false)
  const action = useAction(act)

  const matchingAppeals = (data.appeals || []).filter(
    a => a.target_type === targetType && a.target_id === targetId,
  )
  const latestAppeal = matchingAppeals[0]

  const fetchExplain = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const res = await api<ExplainResponse>(
        `/api/events/${encodeURIComponent(data.event.id)}/explain/${encodeURIComponent(targetType)}/${encodeURIComponent(targetId)}`,
      )
      setInfo(res)
    } catch (err) {
      setLoadError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [data.event.id, targetType, targetId])

  useEffect(() => {
    if (open) void fetchExplain()
  }, [open, fetchExplain])

  function submitAppeal(e: FormEvent) {
    e.preventDefault()
    if (!reason.trim()) return
    action.run(
      'appeal_decision',
      {
        target_type: targetType,
        target_id: targetId,
        reason: reason.trim(),
        override_request: overrideReq.trim(),
      },
      'Appeal recorded and logged.',
      () => {
        setReason('')
        setOverrideReq('')
        setOpen('explain')
        void fetchExplain()
      },
    )
  }

  function transition(appealId: string, nextStatus: 'Under Review' | 'Overridden' | 'Dismissed' | 'Flagged') {
    action.run(
      'update_appeal_status',
      {
        appeal_id: appealId,
        status: nextStatus,
        resolution_note: resNote.trim(),
        apply_override: nextStatus === 'Overridden' ? applyOverride : false,
      },
      `Appeal marked ${nextStatus}.`,
      () => {
        setResNote('')
        setApplyOverride(false)
        void fetchExplain()
      },
    )
  }

  return (
    <>
      <span className="explain-controls" onClick={e => e.stopPropagation()}>
        <button
          type="button"
          className="m-btn explain-btn"
          aria-label="Why did the system decide this?"
          onClick={() => setOpen('explain')}
        >
          <HelpCircle size={13} />
          <span>{compact ? 'Why decided?' : 'Why did the system decide this?'}</span>
        </button>
        <button
          type="button"
          className={'m-btn explain-btn' + (latestAppeal ? ' flagged' : '')}
          aria-label="Appeal or flag this decision"
          onClick={() => setOpen('appeal')}
        >
          <Flag size={13} />
          <span>{latestAppeal ? latestAppeal.status : compact ? 'Appeal' : 'Appeal / Flag'}</span>
        </button>
      </span>

      {open && (
        <Dialog
          title="Decision Explainability & Appeal Trail"
          onClose={() => {
            if (!action.busy) setOpen(null)
          }}
        >
          <div className="explain-dialog-body">
            {loadError && <div className="m-notice error" role="alert">{loadError}</div>}
            <Notice state={action} />
            {loading && !info && <p className="m-copy">Loading decision rules and audit trail…</p>}

            {info && (
              <>
                <div className="explain-header-card">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <AgentMark name={info.agent} />
                    <div>
                      <strong style={{ display: 'block', fontSize: 15 }}>{info.title}</strong>
                      <small style={{ color: '#64748B' }}>
                        {info.agent} · {info.mode} · Status: {info.outcome_status}
                      </small>
                    </div>
                  </div>
                  {info.appeals[0] && (
                    <Pill tone={statusTone(info.appeals[0].status)}>Appeal: {info.appeals[0].status}</Pill>
                  )}
                </div>

                {info.summary && <p className="m-copy" style={{ margin: '8px 0 0' }}>{info.summary}</p>}

                {info.scores.length > 0 && (
                  <section className="explain-section">
                    <h4><Scale size={14} /> Scores &amp; Quantitative Basis</h4>
                    <div className="explain-scores-grid">
                      {info.scores.map((sc, idx) => (
                        <div key={idx} className="explain-score-card">
                          <small>{sc.metric}</small>
                          <strong>{sc.value}</strong>
                          <span>{sc.weight_or_basis}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {info.rules.length > 0 && (
                  <section className="explain-section">
                    <h4><ShieldCheck size={14} /> Evaluated Rules &amp; Logic</h4>
                    <ul className="explain-rule-list">
                      {info.rules.map((r, idx) => (
                        <li key={idx}>
                          <div className="explain-rule-head">
                            <strong>{r.name}</strong>
                            <Pill tone={r.passed ? 'mint' : 'neutral'}>{r.passed ? 'Triggered' : 'Checked'}</Pill>
                          </div>
                          <code>{r.condition}</code>
                          <span className="explain-rule-result">{r.result}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {info.constraints.length > 0 && (
                  <section className="explain-section">
                    <h4>Constraints &amp; Guardrails</h4>
                    <div className="m-tablewrap">
                      <table className="m-table">
                        <thead>
                          <tr>
                            <th>Constraint</th>
                            <th>Rule / Limit</th>
                            <th>Observed Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {info.constraints.map((c, idx) => (
                            <tr key={idx}>
                              <td><strong>{c.label}</strong></td>
                              <td>{c.limit}</td>
                              <td>{c.actual}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}

                {info.appeals.length > 0 && (
                  <section className="explain-section">
                    <h4><Flag size={14} /> Active Dispute / Override Requests</h4>
                    {info.appeals.map(ap => (
                      <div key={ap.id} className="explain-appeal-card">
                        <div className="m-titleline">
                          <strong>{ap.reason}</strong>
                          <Pill tone={statusTone(ap.status)}>{ap.status}</Pill>
                        </div>
                        {ap.override_request && (
                          <p className="m-copy" style={{ margin: '4px 0', fontSize: 12.5 }}>
                            <strong>Requested override:</strong> {ap.override_request}
                          </p>
                        )}
                        {ap.resolution_note && (
                          <p className="m-copy" style={{ margin: '4px 0', fontSize: 12.5 }}>
                            <strong>Resolution note:</strong> {ap.resolution_note}
                          </p>
                        )}
                        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                          <input
                            type="text"
                            placeholder="Add resolution / transition note (optional)"
                            value={resNote}
                            onChange={e => setResNote(e.target.value)}
                          />
                          {(targetType === 'risk' || targetType === 'approval') && (
                            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
                              <input
                                type="checkbox"
                                checked={applyOverride}
                                onChange={e => setApplyOverride(e.target.checked)}
                              />
                              Apply override directly to underlying {targetType} record when approving override
                            </label>
                          )}
                          <div className="m-actions" style={{ marginTop: 2 }}>
                            {ap.status !== 'Under Review' && (
                              <Button busy={action.busy} onClick={() => transition(ap.id, 'Under Review')}>
                                Mark Under Review
                              </Button>
                            )}
                            {ap.status !== 'Overridden' && (
                              <Button primary busy={action.busy} onClick={() => transition(ap.id, 'Overridden')}>
                                <CheckCircle2 size={13} /> Approve Override
                              </Button>
                            )}
                            {ap.status !== 'Dismissed' && (
                              <Button busy={action.busy} onClick={() => transition(ap.id, 'Dismissed')}>
                                Dismiss Flag
                              </Button>
                            )}
                            {ap.status !== 'Flagged' && (
                              <Button busy={action.busy} onClick={() => transition(ap.id, 'Flagged')}>
                                Re-flag
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </section>
                )}

                <section className="explain-section">
                  <div className="m-titleline" style={{ marginBottom: 8 }}>
                    <h4>Submit Dispute or Override Request</h4>
                    {open !== 'appeal' && (
                      <Button onClick={() => setOpen('appeal')}>New appeal</Button>
                    )}
                  </div>
                  {(open === 'appeal' || info.appeals.length === 0) && (
                    <form className="m-form" onSubmit={submitAppeal}>
                      <Field label="Why are you flagging or disputing this decision?">
                        <textarea
                          rows={2}
                          required
                          maxLength={1000}
                          placeholder="e.g. Merchandise allocation is locked for speaker hoodies; cut Logistics instead."
                          value={reason}
                          onChange={e => setReason(e.target.value)}
                        />
                      </Field>
                      <Field label="Requested override (optional)">
                        <input
                          type="text"
                          maxLength={1000}
                          placeholder="e.g. Override reduction and preserve Merchandise budget"
                          value={overrideReq}
                          onChange={e => setOverrideReq(e.target.value)}
                        />
                      </Field>
                      <div className="m-actions" style={{ marginTop: 4 }}>
                        <Button primary type="submit" busy={action.busy} disabled={!reason.trim()}>
                          <Flag size={13} /> Submit Appeal &amp; Log
                        </Button>
                      </div>
                    </form>
                  )}
                </section>

                <section className="explain-section">
                  <h4><Clock size={14} /> Timestamped Audit Log ({info.audit_log.length})</h4>
                  <ol className="explain-audit-list">
                    {info.audit_log.map(entry => (
                      <li key={entry.id}>
                        <div className="explain-audit-head">
                          <span>
                            {entry.from_status ? (
                              <><strong>{entry.from_status}</strong> → <strong>{entry.to_status}</strong></>
                            ) : (
                              <strong>{entry.to_status}</strong>
                            )}
                          </span>
                          <small>{entry.actor} · {day(entry.created_at)} · {entry.created_at.slice(11, 19)} UTC</small>
                        </div>
                        {entry.note && <p>{entry.note}</p>}
                      </li>
                    ))}
                  </ol>
                </section>
              </>
            )}
          </div>
        </Dialog>
      )}
    </>
  )
}
