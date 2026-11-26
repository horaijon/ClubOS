"""Public registration forms and their organizer-owned configuration."""
from datetime import date
import json
import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing

from . import db, trace
from .auth import Workspace, authorize_event

router = APIRouter(prefix="/api")

SCHEMA = """
CREATE TABLE IF NOT EXISTS registration_forms (
    event_id TEXT PRIMARY KEY REFERENCES events ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE, deadline TEXT NOT NULL, fields TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registration_answers (
    participant_id TEXT PRIMARY KEY REFERENCES participants ON DELETE CASCADE,
    answers TEXT NOT NULL
);
"""

FIELDS = {
    'team_name': 'Team name', 'team_size': 'Team size', 'track': 'Track',
    'github': 'GitHub link', 'college': 'College / university', 'diet': 'Dietary requirements',
    'experience': 'Experience level', 'accessibility': 'Accessibility requirements',
}


def publish(c, event_id, deadline, fields):
    c.execute(
        "INSERT INTO registration_forms VALUES (?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET deadline=excluded.deadline,fields=excluded.fields",
        (event_id, db.uid(), deadline, db.encode([key for key in dict.fromkeys(fields) if key in FIELDS])),
    )
    return form_for_event(c, event_id)


def _google_form_row(c, event_id):
    try:
        row = c.execute(
            "SELECT google_form_id, responder_uri, edit_uri, created_at FROM google_forms WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        cnt = c.execute(
            "SELECT COUNT(*) FROM google_form_responses WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        return {**dict(row), "response_count": cnt}
    except Exception:
        return None


def metadata(row, google_form=None):
    if row is None and google_form is None:
        return None
    record = dict(row) if row else {"slug": "", "deadline": "", "fields": "[]"}
    public_url = os.getenv('CLUBOS_PUBLIC_URL', '').rstrip('/')
    if google_form:
        record['is_google_form'] = True
        record['google_form_id'] = google_form['google_form_id']
        record['responder_uri'] = google_form['responder_uri']
        record['edit_uri'] = google_form['edit_uri']
        record['response_count'] = google_form.get('response_count', 0)
        record['public_url'] = google_form['responder_uri']
    else:
        record['is_google_form'] = False
        if public_url and record.get('slug'):
            record['public_url'] = public_url + '/register/' + record['slug']
    raw_fields = record.get('fields', '[]')
    keys = json.loads(raw_fields) if isinstance(raw_fields, str) else raw_fields
    record['fields'] = [dict(key=key, label=FIELDS[key]) for key in keys if key in FIELDS]
    return record


def form_for_event(c, event_id):
    row = c.execute('SELECT * FROM registration_forms WHERE event_id=?', (event_id,)).fetchone()
    gf = _google_form_row(c, event_id)
    if row is None and gf is None:
        return None
    record = metadata(row, gf)
    if record and not record.get('deadline'):
        ev = c.execute('SELECT milestone_date, start_date FROM events WHERE id=?', (event_id,)).fetchone()
        if ev:
            record['deadline'] = ev['milestone_date'] or ev['start_date']
    return record


def public_form(c, slug):
    row = c.execute("""SELECT f.*,e.name,e.description,e.start_date,e.venue FROM registration_forms f
        JOIN events e ON e.id=f.event_id WHERE f.slug=?""", (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Registration form unavailable.')
    gf = _google_form_row(c, row['event_id'])
    form = metadata(row, gf)
    form.pop('event_id', None)
    return form


class Submission(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    answers: dict[str, str] = Field(default_factory=dict, max_length=8)


class FormSettings(BaseModel):
    deadline: date
    fields: list[str] = Field(max_length=8)


@router.get('/registration/{slug}')
def get_form(slug: str):
    with db.transaction() as c:
        return public_form(c, slug)


@router.post('/registration/{slug}', status_code=201)
def submit(slug: str, data: Submission):
    from .operations import participant
    from .state import Invalid
    from .planning import Flow
    with db.transaction() as c:
        public_form(c, slug)
        eid, club_id = c.execute("""SELECT e.id,e.club_id FROM events e JOIN registration_forms f
            ON f.event_id=e.id WHERE f.slug=?""", (slug,)).fetchone()
    execution = trace.Execution(club_id, eid, db.uid(), 'Public registration')
    with execution.recording(), db.transaction(write=True) as c:
        form = public_form(c, slug)
        if form['deadline'] < date.today().isoformat():
            raise HTTPException(409, 'Registration has closed.')
        fields = {field['key'] for field in form['fields']}
        if data.answers.keys() - fields or any(len(value) > 500 for value in data.answers.values()):
            raise HTTPException(422, 'Check your answers and try again.')
        with execution.step('FormFlow', 'receive_registration') as step:
            try:
                key = participant(Flow(c, {'id': eid}, None, 'Public registration'), data.model_dump())
            except Invalid as exc:
                raise HTTPException(422, str(exc)) from exc
            c.execute('INSERT INTO registration_answers VALUES (?,?)', (key, db.encode(data.answers)))
            step.update(summary='A participant registered through the public form.')
    return {'message': 'Registration received.'}


@router.get('/registration/{slug}/qr.svg')
def qr(slug: str, request: Request):
    with db.transaction() as c:
        form = public_form(c, slug)
    target_url = form.get('responder_uri') or form.get('public_url') or str(request.base_url) + 'register/' + slug
    widget = QrCodeWidget(target_url, barWidth=180, barHeight=180)
    drawing = Drawing(180, 180)
    drawing.add(widget)
    return Response(renderSVG.drawToString(drawing), media_type='image/svg+xml')


@router.put('/events/{event_id}/registration')
def edit_form(event_id: str, data: FormSettings, club: Workspace):
    with db.transaction(write=True) as c:
        authorize_event(c, event_id, club['id'])
        start = c.execute('SELECT start_date FROM events WHERE id=?', (event_id,)).fetchone()[0]
        if data.deadline.isoformat() > start or set(data.fields) - FIELDS.keys():
            raise HTTPException(422, 'Use supported fields and a deadline by the event start date.')
        return publish(c, event_id, data.deadline.isoformat(), data.fields)
