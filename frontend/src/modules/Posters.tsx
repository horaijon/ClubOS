import { useEffect, useRef, useState } from 'react'
import { Check, Download, Image as ImageIcon, KeyRound, Palette, RefreshCw, Sparkles, Trash2, Upload, Wand2 } from 'lucide-react'
import { AgentMark } from '../Identity'
import { api, type PosterItem } from '../data'
import { Button, Dialog, Empty, Field, Head, Panel, Pill, day, type ViewProps } from './ui'

const promptSuggestions = [
  'Cyberpunk neon city with glowing circuit lines and Prize Pool ₹50,000',
  'Futuristic robotic mecha blueprint with metallic cyan & amber accents',
  'Swiss minimalist editorial poster on crisp off-white paper with bold typography',
  'Retro 80s synthwave grid sunset with glowing magenta & cyan horizon',
]

export default function Posters({ data, refresh }: ViewProps & { refresh?: () => Promise<void> }) {
  const eid = data.event.id
  const [posters, setPosters] = useState<PosterItem[]>(data.posters || [])
  const [selectedId, setSelectedId] = useState<string>('')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<'reference' | 'final' | null>(null)
  const [notice, setNotice] = useState('')
  const [aiWarning, setAiWarning] = useState('')
  const [error, setError] = useState('')
  const [aiStatus, setAiStatus] = useState<{ openai_configured: boolean; gemini_configured: boolean }>({ openai_configured: false, gemini_configured: false })
  const [keyModal, setKeyModal] = useState(false)
  const [openaiKey, setOpenaiKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const refInput = useRef<HTMLInputElement>(null)
  const finalInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api<{ posters: PosterItem[] }>(`/api/events/${encodeURIComponent(eid)}/posters`)
      .then(res => setPosters(res.posters || []))
      .catch(() => { })
    api<{ openai_configured: boolean; gemini_configured: boolean }>('/api/integrations/ai/status')
      .then(setAiStatus)
      .catch(() => { })
  }, [eid, data.posters?.length])

  const activePoster = posters.find(p => p.is_active) || posters.find(p => p.kind !== 'reference') || posters[0]
  const viewed = posters.find(p => p.id === selectedId) || activePoster
  const references = posters.filter(p => p.kind === 'reference')
  const latestRef = references[0]

  async function saveKeys(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await api<{ openai_configured: boolean; gemini_configured: boolean; message: string }>(
        '/api/integrations/ai/keys',
        {
          method: 'POST',
          body: JSON.stringify({
            ...(openaiKey.trim() ? { openai_api_key: openaiKey.trim() } : {}),
            ...(geminiKey.trim() ? { gemini_api_key: geminiKey.trim() } : {}),
          }),
        },
      )
      setAiStatus({ openai_configured: res.openai_configured, gemini_configured: res.gemini_configured })
      setOpenaiKey(''); setGeminiKey('')
      setKeyModal(false)
      setAiWarning('')
      setNotice('AI key saved! Try generating a poster with any prompt now.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function generatePoster(customPrompt?: string, useRefId?: string) {
    setBusy(true); setError(''); setNotice(''); setAiWarning('')
    try {
      const pText = (customPrompt ?? prompt).trim()
      const baseId = viewed?.kind === 'generated' ? viewed.id : undefined
      const res = await api<{ message: string; poster: PosterItem & { ai_notice?: string }; posters: PosterItem[] }>(
        `/api/events/${encodeURIComponent(eid)}/posters/generate`,
        {
          method: 'POST',
          body: JSON.stringify({
            prompt: pText,
            reference_poster_id: useRefId || latestRef?.id || null,
            base_poster_id: pText ? baseId : null,
          }),
        },
      )
      setPosters(res.posters)
      setSelectedId(res.poster.id)
      setNotice(res.message)
      if (res.poster.ai_notice) {
        setAiWarning(res.poster.ai_notice)
      }
      if (!customPrompt) setPrompt('')
      await refresh?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function uploadPoster(mode: 'reference' | 'final', file: File | undefined) {
    if (!file) return
    setUploading(mode); setError(''); setNotice(''); setAiWarning('')
    try {
      const fd = new FormData()
      fd.append('mode', mode)
      fd.append('prompt', prompt.trim())
      fd.append('file', file)
      const res = await fetch(`/api/events/${encodeURIComponent(eid)}/posters/upload`, { method: 'POST', body: fd })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.detail || 'Upload failed.')
      setPosters(body.posters || [])
      if (body.generated?.id) {
        setSelectedId(body.generated.id)
        if (body.generated.ai_notice) {
          setAiWarning(String(body.generated.ai_notice))
        }
      } else if (body.uploaded_id) {
        setSelectedId(body.uploaded_id)
      }
      setNotice(body.message)
      await refresh?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(null)
    }
  }

  async function setAsFinal(posterId: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await api<{ message: string; posters: PosterItem[] }>(
        `/api/events/${encodeURIComponent(eid)}/posters/${encodeURIComponent(posterId)}/activate`,
        { method: 'POST' },
      )
      setPosters(res.posters)
      setSelectedId(posterId)
      setNotice(res.message)
      await refresh?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function removePoster(posterId: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await api<{ message: string; posters: PosterItem[] }>(
        `/api/events/${encodeURIComponent(eid)}/posters/${encodeURIComponent(posterId)}`,
        { method: 'DELETE' },
      )
      setPosters(res.posters)
      if (selectedId === posterId) setSelectedId('')
      setNotice(res.message)
      await refresh?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function downloadPng(poster: PosterItem) {
    if (poster.mime_type !== 'image/svg+xml') {
      const a = document.createElement('a')
      a.href = poster.image_url
      a.download = `${data.event.id}-poster.png`
      a.click()
      return
    }
    try {
      const svgText = await (await fetch(poster.image_url)).text()
      const blob = new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const img = new window.Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = 1080
        canvas.height = 1350
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.drawImage(img, 0, 0, 1080, 1350)
          const pngUrl = canvas.toDataURL('image/png')
          const a = document.createElement('a')
          a.href = pngUrl
          a.download = `${data.event.id}-poster.png`
          a.click()
        }
        URL.revokeObjectURL(url)
      }
      img.src = url
    } catch {
      setError('Could not export PNG.')
    }
  }

  return <>
    <Head
      title="Poster Studio"
      sub={`Canvas designs AI posters for ${data.event.name} using OpenAI gpt-image-1 / Google Nano Banana with your prompts and reference posters.`}
      action={
        <div className="m-actions" style={{ margin: 0 }}>
          <Button onClick={() => setKeyModal(true)}>
            <KeyRound size={14} /> {aiStatus.openai_configured ? 'OpenAI Image Active' : 'Add ChatGPT / AI Key'}
          </Button>
          {viewed && <>
            <a className="m-btn" href={viewed.image_url} download={`${data.event.id}-poster.${viewed.mime_type === 'image/svg+xml' ? 'svg' : 'png'}`}>
              <Download size={14} /> Download {viewed.mime_type === 'image/svg+xml' ? 'SVG' : 'PNG'}
            </a>
            {viewed.mime_type === 'image/svg+xml' && (
              <Button onClick={() => downloadPng(viewed)}><Download size={14} /> Export PNG</Button>
            )}
          </>}
          <Button primary busy={busy} onClick={() => generatePoster(prompt || 'Design a striking modern technical event poster')}>
            <RefreshCw size={14} /> Generate Poster
          </Button>
        </div>
      }
    />

    {!aiStatus.openai_configured && (
      <div className="mc-banner-info" style={{ marginBottom: 14 }}>
        <span>
          <strong>AI Image Tip:</strong> Add your OpenAI (ChatGPT) API key so Canvas uses <code>gpt-image-1</code> to render real bespoke posters from your prompts and uploaded reference images (or enable billing for Google Nano Banana).
        </span>
        <Button onClick={() => setKeyModal(true)}><KeyRound size={14} /> Add OpenAI API Key</Button>
      </div>
    )}

    {error && <div className="m-notice error" role="alert">{error}</div>}
    {aiWarning && <div className="m-notice error" role="status">{aiWarning}</div>}
    {notice && <div className="m-notice success" role="status">{notice}</div>}

    <div className="mc-split" style={{ gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)' }}>
      {/* Left: Poster Preview */}
      <Panel
        title={viewed ? viewed.title : 'Event Poster Preview'}
        action={viewed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Pill tone={viewed.is_active ? 'mint' : viewed.kind === 'reference' ? 'amber' : 'neutral'}>
              {viewed.is_active ? 'Final / Active' : viewed.kind === 'reference' ? 'Reference' : 'Draft'}
            </Pill>
            {!viewed.is_active && viewed.kind !== 'reference' && (
              <Button primary busy={busy} onClick={() => setAsFinal(viewed.id)}><Check size={13} /> Set as Final</Button>
            )}
          </div>
        )}
      >
        <div className="m-pad" style={{ background: '#F8FAFC', display: 'grid', placeItems: 'center', position: 'relative' }}>
          {busy && (
            <div style={{ padding: '8px 14px', borderRadius: 999, background: '#0F172A', color: '#fff', fontSize: 12.5, fontWeight: 600, marginBottom: 12 }}>
              Canvas is designing your AI poster…
            </div>
          )}
          {viewed ? (
            <div style={{ width: '100%', maxWidth: 460 }}>
              <img
                src={viewed.image_url + '?t=' + encodeURIComponent(viewed.created_at)}
                alt={viewed.title}
                style={{
                  width: '100%',
                  borderRadius: 12,
                  border: '1px solid #E2E8F0',
                  boxShadow: '0 10px 30px rgba(15, 23, 42, 0.12)',
                  display: 'block',
                  background: '#0F172A',
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, fontSize: 12, color: '#64748B' }}>
                <span>Created by <strong>{viewed.created_by}</strong> · {viewed.theme}</span>
                <span>{day(viewed.created_at)}</span>
              </div>
              {viewed.prompt && (
                <p style={{ marginTop: 6, fontSize: 12.5, color: '#475569', background: '#FFFFFF', padding: '8px 10px', borderRadius: 8, border: '1px solid #E2E8F0' }}>
                  <strong>Prompt:</strong> {viewed.prompt}
                </p>
              )}
            </div>
          ) : (
            <Empty title="No poster generated yet" detail="Click Generate Poster to let Canvas create an event poster." />
          )}
        </div>
      </Panel>

      {/* Right: Prompt Editor + Uploads + Versions */}
      <div className="m-stack">
        <section className="m-card">
          <div className="m-titleline" style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <AgentMark name="Canvas" />
              <div>
                <h3>Generate / Edit Poster with Prompt</h3>
                <span className="m-sub">Uses OpenAI gpt-image-1 / Google Nano Banana with full event context</span>
              </div>
            </div>
            {latestRef && <Pill tone="purple">Reference Attached</Pill>}
          </div>

          <form className="m-form" onSubmit={e => { e.preventDefault(); void generatePoster() }}>
            <Field label="Design prompt">
              <textarea
                rows={3}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                placeholder='e.g. "Futuristic robotic hackathon poster with glowing cyan mecha illustration, ₹50,000 prize pool, bold geometric typography"'
              />
            </Field>
            <div className="m-actions" style={{ marginTop: 0 }}>
              {promptSuggestions.map(s => (
                <button
                  key={s}
                  type="button"
                  className="m-btn"
                  style={{ fontSize: 11.5, padding: '4px 9px' }}
                  onClick={() => { setPrompt(s); void generatePoster(s) }}
                >
                  <Sparkles size={11} /> {s.split(' ').slice(0, 4).join(' ')}…
                </button>
              ))}
            </div>
            <div className="m-actions">
              <Button primary type="submit" busy={busy} disabled={!prompt.trim() && !posters.length}>
                <Wand2 size={14} /> Apply Prompt &amp; Generate
              </Button>
            </div>
          </form>
        </section>

        {/* User Upload: Reference or Final Poster */}
        <section className="m-card">
          <div className="m-titleline" style={{ marginBottom: 8 }}>
            <h3>Upload Your Own Poster</h3>
            <Pill>PNG · JPG · WEBP · SVG</Pill>
          </div>
          <p className="m-copy" style={{ marginTop: 0 }}>
            Upload a poster as a <strong>Reference</strong> for Canvas to match its style, layout, and colors, or upload your finished design directly as the <strong>Final Poster</strong>.
          </p>

          <input
            ref={refInput}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml,.png,.jpg,.jpeg,.webp,.svg"
            style={{ display: 'none' }}
            onChange={e => { void uploadPoster('reference', e.target.files?.[0]); e.target.value = '' }}
          />
          <input
            ref={finalInput}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml,.png,.jpg,.jpeg,.webp,.svg"
            style={{ display: 'none' }}
            onChange={e => { void uploadPoster('final', e.target.files?.[0]); e.target.value = '' }}
          />

          <div className="m-actions">
            <Button busy={uploading === 'reference'} onClick={() => refInput.current?.click()}>
              <Palette size={14} /> Upload Reference Poster
            </Button>
            <Button primary busy={uploading === 'final'} onClick={() => finalInput.current?.click()}>
              <Upload size={14} /> Upload Final Poster
            </Button>
          </div>

          {latestRef && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, padding: 10, borderRadius: 10, background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
              <img
                src={latestRef.image_url}
                alt="Reference poster"
                style={{ width: 44, height: 55, objectFit: 'cover', borderRadius: 6, border: '1px solid #CBD5E1' }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ display: 'block', fontSize: 12.5 }}>{latestRef.title}</strong>
                <small style={{ color: '#64748B', fontSize: 11.5 }}>Active style reference for Canvas</small>
              </div>
              <Button busy={busy} onClick={() => generatePoster(prompt || 'Generate an event poster matching the uploaded reference poster style', latestRef.id)}>
                Apply Style
              </Button>
            </div>
          )}
        </section>

        {/* Version History */}
        <Panel title={`Poster Versions (${posters.length})`}>
          {posters.length ? (
            <div className="m-list">
              {posters.map(p => (
                <div
                  key={p.id}
                  className="m-row"
                  style={{
                    background: viewed?.id === p.id ? '#EFF6FF' : undefined,
                    cursor: 'pointer',
                  }}
                  onClick={() => setSelectedId(p.id)}
                >
                  <img
                    src={p.image_url}
                    alt={p.title}
                    style={{ width: 38, height: 48, objectFit: 'cover', borderRadius: 6, border: '1px solid #CBD5E1', flexShrink: 0 }}
                  />
                  <div className="m-rowbody">
                    <strong>{p.title}</strong>
                    <small>{p.created_by} · {p.kind === 'reference' ? 'Reference upload' : p.kind === 'final' ? 'Final upload' : p.theme}</small>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} onClick={e => e.stopPropagation()}>
                    {p.is_active ? (
                      <Pill tone="mint">Active</Pill>
                    ) : p.kind !== 'reference' ? (
                      <Button onClick={() => setAsFinal(p.id)}><ImageIcon size={12} /> Use</Button>
                    ) : (
                      <Pill tone="amber">Ref</Pill>
                    )}
                    {posters.length > 1 && (
                      <button
                        type="button"
                        className="m-icon"
                        aria-label="Delete poster"
                        onClick={() => removePoster(p.id)}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No poster versions yet" />
          )}
        </Panel>
      </div>
    </div>

    {keyModal && (
      <Dialog title="Configure AI Image & Search Keys" onClose={() => setKeyModal(false)}>
        <p className="m-copy">
          Paste your <strong>OpenAI (ChatGPT) API key</strong> so Canvas uses <code>gpt-image-1</code> (or <code>dall-e-3</code>) to generate real bespoke posters from prompts and reference images, and Magnet uses GPT for sponsor discovery. Saved securely to <code>.env</code>.
        </p>
        <form className="m-form" onSubmit={saveKeys}>
          <Field label={`OpenAI API Key ${aiStatus.openai_configured ? '(Configured)' : ''}`}>
            <input
              type="password"
              placeholder="sk-..."
              value={openaiKey}
              onChange={e => setOpenaiKey(e.target.value)}
            />
          </Field>
          <Field label={`Gemini API Key ${aiStatus.gemini_configured ? '(Configured)' : ''}`}>
            <input
              type="password"
              placeholder="AIza... (optional override)"
              value={geminiKey}
              onChange={e => setGeminiKey(e.target.value)}
            />
          </Field>
          <div className="m-actions">
            <Button onClick={() => setKeyModal(false)}>Cancel</Button>
            <Button primary busy={busy} type="submit" disabled={!openaiKey.trim() && !geminiKey.trim()}>Save Keys</Button>
          </div>
        </form>
      </Dialog>
    )}
  </>
}
