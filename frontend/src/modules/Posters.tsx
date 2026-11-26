import { useEffect, useRef, useState } from 'react'
import { Check, Download, Image as ImageIcon, KeyRound, Palette, Trash2, Upload, Wand2 } from 'lucide-react'
import { DecisionExplainControl } from '../DecisionExplain'
import { api, type PosterItem } from '../data'
import { Button, Dialog, Empty, Field, Head, Panel, Pill, Tabs, day, type ViewProps } from './ui'

const promptSuggestions = [
  ['Cyberpunk', 'Cyberpunk neon city with glowing circuit lines and Prize Pool ₹50,000'],
  ['Robotic blueprint', 'Futuristic robotic mecha blueprint with metallic cyan & amber accents'],
  ['Swiss minimal', 'Swiss minimalist editorial poster on crisp off-white paper with bold typography'],
  ['Retro synthwave', 'Retro 80s synthwave grid sunset with glowing magenta & cyan horizon'],
]

export default function Posters({ data, act, refresh }: ViewProps & { refresh?: () => Promise<void> }) {
  const eid = data.event.id
  const [posters, setPosters] = useState<PosterItem[]>(data.posters || [])
  const [selectedId, setSelectedId] = useState<string>('')
  const [prompt, setPrompt] = useState('')
  const [referenceChoice, setReferenceChoice] = useState('')
  const [revise, setRevise] = useState(false)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<'reference' | 'final' | null>(null)
  const [notice, setNotice] = useState('')
  const [aiWarning, setAiWarning] = useState('')
  const [error, setError] = useState('')
  const [aiStatus, setAiStatus] = useState<{ openai_configured: boolean; gemini_configured: boolean; cloudflare_configured?: boolean; free_ai_available?: boolean }>({ openai_configured: false, gemini_configured: false, free_ai_available: true })
  const [keyModal, setKeyModal] = useState(false)
  const [openaiKey, setOpenaiKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [cfAccountId, setCfAccountId] = useState('')
  const [cfApiToken, setCfApiToken] = useState('')
  const [tab, setTab] = useState('Create')
  const refInput = useRef<HTMLInputElement>(null)
  const finalInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api<{ posters: PosterItem[] }>(`/api/events/${encodeURIComponent(eid)}/posters`)
      .then(res => setPosters(res.posters || []))
      .catch(() => { })
    api<{ openai_configured: boolean; gemini_configured: boolean; cloudflare_configured?: boolean; free_ai_available?: boolean }>('/api/integrations/ai/status')
      .then(setAiStatus)
      .catch(() => { })
  }, [eid, data.posters?.length])

  const activePoster = posters.find(p => p.is_active) || posters.find(p => p.kind !== 'reference') || posters[0]
  const viewed = posters.find(p => p.id === selectedId) || activePoster
  const references = posters.filter(p => p.kind === 'reference')
  const latestRef = references.find(item=>item.id===referenceChoice)
  const raster = viewed && /^image\/(png|jpeg|webp)$/.test(viewed.mime_type)

  async function saveKeys(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await api<{ openai_configured: boolean; gemini_configured: boolean; cloudflare_configured?: boolean; free_ai_available?: boolean; message: string }>(
        '/api/integrations/ai/keys',
        {
          method: 'POST',
          body: JSON.stringify({
            ...(openaiKey.trim() ? { openai_api_key: openaiKey.trim() } : {}),
            ...(geminiKey.trim() ? { gemini_api_key: geminiKey.trim() } : {}),
            ...(cfAccountId.trim() ? { cloudflare_account_id: cfAccountId.trim() } : {}),
            ...(cfApiToken.trim() ? { cloudflare_api_token: cfApiToken.trim() } : {}),
          }),
        },
      )
      setAiStatus({ openai_configured: res.openai_configured, gemini_configured: res.gemini_configured, cloudflare_configured: res.cloudflare_configured, free_ai_available: res.free_ai_available })
      setOpenaiKey(''); setGeminiKey(''); setCfAccountId(''); setCfApiToken('')
      setKeyModal(false)
      setAiWarning('')
      setNotice('AI provider settings saved! Try generating a poster with any prompt now.')
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
      const referenceId = useRefId || latestRef?.id
      const baseId = revise && raster && !referenceId ? viewed.id : undefined
      const res = await api<{ message: string; poster: PosterItem & { ai_notice?: string }; posters: PosterItem[] }>(
        `/api/events/${encodeURIComponent(eid)}/posters/generate`,
        {
          method: 'POST',
          body: JSON.stringify({
            prompt: pText,
            reference_poster_id: referenceId || null,
            require_ai: true,
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
      fd.append('generate', 'false')
      fd.append('prompt', prompt.trim())
      fd.append('file', file)
      const res = await fetch(`/api/events/${encodeURIComponent(eid)}/posters/upload`, { method: 'POST', body: fd })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.detail || 'Upload failed.')
      setPosters(body.posters || [])
      if (mode==='reference') setReferenceChoice(body.uploaded_id)
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
      sub={`Canvas designs AI posters for ${data.event.name} from your design prompts and saved event details.`}
      action={
        <div className="m-actions" style={{ margin: 0 }}>
          <Button onClick={() => setKeyModal(true)}>
            <KeyRound size={14} /> AI settings
          </Button>
          {viewed && <>
            <a className="m-btn" href={viewed.image_url} download={`${data.event.id}-poster.${viewed.mime_type === 'image/svg+xml' ? 'svg' : 'png'}`}>
              <Download size={14} /> Download {viewed.mime_type === 'image/svg+xml' ? 'SVG' : 'PNG'}
            </a>
            {viewed.mime_type === 'image/svg+xml' && (
              <Button onClick={() => downloadPng(viewed)}><Download size={14} /> Export PNG</Button>
            )}
          </>}
        </div>
      }
    />

    {!aiStatus.openai_configured && !aiStatus.gemini_configured && !aiStatus.cloudflare_configured && (
      <div className="mc-banner-info" style={{ marginBottom: 14 }}>
        <span>
          <strong>Free AI Studio Active:</strong> Prompts generate custom artwork with <strong>FLUX.1-schnell</strong> (no paid key needed) and overlay your verified event details &amp; QR code. Optionally add Cloudflare Workers AI, OpenAI, or Gemini keys.
        </span>
        <Button onClick={() => setKeyModal(true)}><KeyRound size={14} /> Configure Providers</Button>
      </div>
    )}

    {error && <div className="m-notice error" role="alert">{error}</div>}
    {aiWarning && <div className="m-notice error" role="status">{aiWarning}</div>}
    {notice && <div className="m-notice success" role="status">{notice}</div>}

    <div className="studio-grid">
      {/* Left: Poster Preview */}
      <Panel
        title="Preview"
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
        <div className="m-pad studio-preview">
          {busy && <p className="studio-busy" role="status">Canvas is designing your AI poster…</p>}
          {viewed ? <>
            <img src={viewed.image_url + '?t=' + encodeURIComponent(viewed.created_at)} alt={viewed.title} />
            <p className="studio-caption" title={viewed.title}>{viewed.title}</p>
            <details className="studio-details" key={viewed.id}>
              <summary>Poster details</summary>
              <p>Created by <strong>{viewed.created_by}</strong> · {viewed.theme} · {day(viewed.created_at)}</p>
              {viewed.prompt && <p><strong>Prompt:</strong> {viewed.prompt}</p>}
              <DecisionExplainControl data={data} act={act} targetType="poster" targetId={viewed.id} />
            </details>
          </> : (
            <Empty title="No poster generated yet" detail="Describe a design and click Generate to create an event poster." />
          )}
        </div>
      </Panel>

      {/* Right: Prompt Editor + Uploads + Versions */}
      <section className="m-card studio-side">
        <Tabs options={['Create', 'Upload', 'Versions']} current={tab} onChange={setTab} />

        {tab === 'Create' && (
          <form className="m-form" onSubmit={e => { e.preventDefault(); void generatePoster(prompt.trim() || latestRef ? undefined : 'Design a striking modern technical event poster') }}>
            <Field label="Design prompt">
              <textarea
                rows={4}
                maxLength={1200}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                placeholder="Describe the artwork, layout and mood. Event details are added for you."
              />
            </Field>
            {references.length>0&&<Field label="Style reference"><select value={referenceChoice} onChange={event=>setReferenceChoice(event.target.value)}>
              <option value="">None</option>{references.filter(item=>/^image\/(png|jpeg|webp)$/.test(item.mime_type)).map(item=><option value={item.id} key={item.id}>{item.title}</option>)}
            </select></Field>}
            {raster&&viewed.kind!=='reference'&&!latestRef&&<label className="studio-check"><input type="checkbox" checked={revise} onChange={event=>setRevise(event.target.checked)}/> Revise the selected poster</label>}
            <div className="studio-ideas">
              <span>Ideas</span>
              {promptSuggestions.map(([label, text]) => (
                <button key={label} type="button" title={text} aria-pressed={prompt === text} onClick={() => setPrompt(text)}>{label}</button>
              ))}
            </div>
            <Button primary type="submit" busy={busy}>
              <Wand2 size={14} /> Generate poster
            </Button>
          </form>
        )}

        {tab === 'Upload' && <div className="studio-upload">
          <p className="m-copy">A <strong>reference</strong> guides Canvas on style. A <strong>final poster</strong> is used as is. PNG, JPG, WEBP, or SVG for final posters.</p>

          <input
            ref={refInput}
            type="file"
            accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
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
                Generate from reference
              </Button>
            </div>
          )}
        </div>}

        {tab === 'Versions' && <div className="studio-versions">
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
        </div>}
      </section>
    </div>

    {keyModal && (
      <Dialog title="Configure AI Image Providers" onClose={() => setKeyModal(false)}>
        <p className="m-copy">
          Free <strong>FLUX.1-schnell</strong> generation is already enabled with no key required. You can optionally add <strong>Cloudflare Workers AI</strong> (free daily tier), <strong>OpenAI</strong>, or <strong>Gemini</strong> keys.
        </p>
        <form className="m-form" onSubmit={saveKeys}>
          <Field label={`Cloudflare Account ID ${aiStatus.cloudflare_configured ? '(Configured)' : '(Free tier optional)'}`}>
            <input
              type="text"
              placeholder="32-char Cloudflare account ID"
              value={cfAccountId}
              onChange={e => setCfAccountId(e.target.value)}
            />
          </Field>
          <Field label={`Cloudflare API Token ${aiStatus.cloudflare_configured ? '(Configured)' : '(Free tier optional)'}`}>
            <input
              type="password"
              placeholder="Cloudflare Workers AI token"
              value={cfApiToken}
              onChange={e => setCfApiToken(e.target.value)}
            />
          </Field>
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
            <Button primary busy={busy} type="submit" disabled={!openaiKey.trim() && !geminiKey.trim() && !(cfAccountId.trim() && cfApiToken.trim())}>Save Keys</Button>
          </div>
        </form>
      </Dialog>
    )}
  </>
}
