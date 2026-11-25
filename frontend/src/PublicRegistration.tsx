import { useEffect, useState, type FormEvent } from 'react'
import { api, shortDate, type RegistrationForm } from './data'
import { LogoMark } from './Identity'
import './launch.css'

type PublicForm = RegistrationForm & { name: string; description: string; venue: string; start_date: string }
export default function PublicRegistration({ slug }: { slug: string }) {
  const [form, setForm] = useState<PublicForm>(), [error, setError] = useState(''), [busy, setBusy] = useState(false), [done, setDone] = useState(false)
  const url = '/api/registration/' + encodeURIComponent(slug)
  useEffect(() => { api<PublicForm>(url).then(setForm).catch(err => setError(err.message)) }, [url])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    const name = values.get('name'), email = values.get('email')
    const answers = Object.fromEntries(form!.fields.map(field => [field.key, values.get(field.key)]))
    setBusy(true); setError('')
    try { await api(url, { method: 'POST', body: JSON.stringify({ name, email, answers }) }); setDone(true) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  return <main className="public-registration">
    <section className="public-form glass">
      <a href="/" className="wordmark"><LogoMark />ClubOS</a>
      <h1>{form?.name || 'Event registration'}</h1>
      {error && <p role="alert">{error}</p>}
      {!form && !error && <p role="status">Loading registration…</p>}
      {form && <><p>{shortDate(form.start_date, true)} · {form.venue}</p><p>{form.description}</p>
        {done ? <h2 role="status">Registration received</h2> : <form className="public-fields" onSubmit={submit}>
          <p>Registration closes {shortDate(form.deadline, true)}.</p>
          <label>Full name<input name="name" required maxLength={120} autoComplete="name" /></label>
          <label>Email address<input name="email" type="email" required maxLength={254} autoComplete="email" /></label>
          {form.fields.map(field => <label key={field.key}>{field.label}<input name={field.key} type={field.key === 'github' ? 'url' : field.key === 'team_size' ? 'number' : 'text'} min={field.key === 'team_size' ? 1 : undefined} maxLength={500} /></label>)}
          <button className="brand-button" disabled={busy}>{busy ? 'Submitting…' : 'Register'}</button>
        </form>}
      </>}
    </section>
  </main>
}
