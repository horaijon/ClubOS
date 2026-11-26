"""Event-scoped sponsor CRM tools. A tentative offer cannot enter the funding ledger."""
import json
import re
from datetime import date,timedelta
from . import intelligence
from .db import insert,now,encode
from .state import scoped,choice,number,required,STAGES,funding,task,Missing,Invalid,Conflict,due_in,iso,prospects
from .recovery import currency,optimize

def update_email(f, p):
    s = sponsor(f, p.get('sponsor_id'))
    email = required(p, 'contact_email', 254).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise Invalid('Enter a valid sponsor contact email address.')
    f.c.execute('UPDATE sponsors SET contact_email=? WHERE id=?', (email, s['id']))
    f.note('Sponsor contact email updated', f'{s["name"]} · {email}', 'Magnet')
    return dict(message='Sponsor contact email saved.', contact_email=email)


def add_demo_sponsor(f, p):
    name = required(p, 'name', 160)
    email = required(p, 'contact_email', 254).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise Invalid('Enter a valid sponsor contact email address.')
    industry = (p.get('industry') or 'Technology & Developer Tools').strip()[:120]
    desc = (p.get('description') or f'Live demo sponsor contact ({email}).').strip()[:1500]
    pid = insert(
        f.c, 'profiles', event_scope=f.id, name=name, industry=industry,
        description=desc, tags='hackathon,student,tech', sponsorship_type='Financial',
    )
    sid = insert(
        f.c, 'sponsors', event_id=f.id, prospect_id=pid,
        stage='Shortlisted', contact_email=email,
    )
    f.log('Magnet', 'rank_sponsors', f'Added {name} ({email}) to sponsorship pipeline.')
    f.note('Real sponsor added', f'{name} ({email})', 'Magnet')
    outreach = draft(f, {'sponsor_id': sid}, 'outreach')
    return dict(message=f'Added {name} and drafted a pitch.', sponsor_id=sid, draft=outreach['text'])


def parse_email_subject_and_body(text: str, event_name: str, sponsor_name: str) -> tuple[str, str]:
    lines = (text or '').strip().splitlines()
    if lines and lines[0].lower().startswith('subject:'):
        subject = lines[0].split(':', 1)[1].strip() or f'Sponsorship Partnership — {event_name}'
        body = '\n'.join(lines[1:]).lstrip()
        return subject, body or text
    return f'Sponsorship Partnership — {event_name} × {sponsor_name}', text


def send_email(f, p):
    from . import gmail_integration
    s = sponsor(f, p.get('sponsor_id'))
    to_email = (p.get('to_email') or s.get('contact_email') or '').strip()
    if not to_email:
        raise Invalid('Add a recipient email address for this sponsor first.')
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to_email):
        raise Invalid('Enter a valid recipient email address.')
    if to_email != (s.get('contact_email') or ''):
        f.c.execute('UPDATE sponsors SET contact_email=? WHERE id=?', (to_email, s['id']))

    raw_text = (p.get('body') or s.get('draft') or '').strip()
    if not raw_text:
        raw_text = draft(f, {'sponsor_id': s['id']}, 'outreach')['text']
    default_subj, default_body = parse_email_subject_and_body(raw_text, f.e['name'], s['name'])
    subject = (p.get('subject') or default_subj).strip()[:200]
    body = (p.get('body') if p.get('subject') else default_body).strip()

    try:
        res = gmail_integration.send_sponsor_email(
            club_id=f.e['club_id'],
            event_id=f.id,
            sponsor_id=s['id'],
            to_email=to_email,
            subject=subject,
            body=body,
            conn=f.c,
        )
    except gmail_integration.GmailUnavailable as exc:
        raise Conflict(str(exc)) from exc

    follow = (date.today() + timedelta(days=s['follow_up_days'])).isoformat()
    f.c.execute(
        "UPDATE sponsors SET stage='Contacted', draft=?, follow_up_date=? WHERE id=?",
        (f'Subject: {subject}\n\n{body}', follow, s['id']),
    )
    insert(f.c, 'communications', event_id=f.id, sponsor_id=s['id'], kind='gmail_outreach', text=f'Subject: {subject}\n\n{body}', created_at=now())
    summary = f'Magnet sent sponsorship pitch to {to_email} via Gmail.'
    with f.tool('Magnet', 'send_email', {'sponsor_id': s['id'], 'to_email': to_email}) as step:
        step.update(summary=summary, mode='Gmail API', output={'message_id': res['message_id'], 'thread_id': res['thread_id']})
    f.note(f'Sent pitch to {s["name"]}', summary, 'Magnet')
    return dict(message=summary, **res)


def sponsor(flow,key):
    s=scoped(flow.c,'sponsors',key,flow.id)
    s.update(dict(flow.c.execute('SELECT name,industry,description FROM profiles WHERE id=?',(s['prospect_id'],)).fetchone()))
    return s

def add_prospect(f,p):
    key=required(p,'prospect_id')
    prof=next((x for x in prospects(f.c,f.e) if x['id']==key),None)
    if not prof: raise Missing('Prospect unavailable in this event.')
    existing=f.c.execute('SELECT id FROM sponsors WHERE event_id=? AND prospect_id=?',(f.id,key)).fetchone()
    if existing: return dict(message='Sponsor already in the pipeline.',sponsor_id=existing[0])
    sid=insert(f.c,'sponsors',event_id=f.id,prospect_id=key,stage='Identified')
    f.log('Magnet','rank_sponsors',f'Added {prof["name"]} with match score {prof["score"]}.')
    f.note('Sponsor added to pipeline',prof['name'],'Magnet')
    return dict(message='Sponsor added to the pipeline.',sponsor_id=sid)

def draft(f,p,kind):
    s=sponsor(f,p.get('sponsor_id'))
    packages=f.c.execute('SELECT * FROM packages WHERE event_id=? ORDER BY amount DESC',(f.id,)).fetchall()
    match=next(p for p in prospects(f.c,f.e) if p['id']==s['prospect_id'])
    if (match['sponsorship_type'] or '').replace('-',' ').lower()=='in kind':
        tier='In-Kind Partner'
        rationale='This package pairs an equipment or service contribution with campus recognition.'
    elif match['score']>=70:
        tier='Gold Sponsor'
        rationale=f'A booth puts your team in front of {f.e["target"]} builders working on related projects.'
    else:
        tier='Silver Sponsor'
        rationale='A website acknowledgement gives your team a focused way to reach students.'
    pkg=next((p for p in packages if p['name']==tier),packages[min(2,len(packages)-1)])
    intro=f'{f.e["club"]} ({f.e["college"]}) is organizing {f.e["name"]} on {f.e["start_date"]} for {f.e["target"]} students at {f.e["venue"]}. Our focus is {f.e["goals"].strip().rstrip(".") or f.e["type"]}.'
    if kind=='proposal':
        fallback=f'Subject: Sponsorship Proposal — {f.e["name"]} × {s["name"]}\n\n{intro} As a {s["industry"].lower()} organization, your team can introduce practical tools to our campus community.\n\nProposed {pkg["name"]} package · {currency(pkg["amount"])}\n{pkg["benefits"]} {rationale}\n\nNext step: discuss the proposed scope and agree on deliverables together.'
    else:
        fallback=f'Subject: {"Following up on" if kind=="followup" else "Partnership invitation for"} {f.e["name"]}\n\nHello {s["name"]} team,\n\n{intro} We would love to explore a {pkg["name"]} partnership with your {s["industry"].lower()} team. The proposed {currency(pkg["amount"])} package includes {pkg["benefits"].lower()} {rationale}\n\nWould you be available to discuss this next week?\n\n{f.e["club"]}'
    a=f.consult('Magnet','propose_package' if kind=='proposal' else 'draft_outreach',dict(kind=kind,company=s['name'],industry=s['industry'],event_type=f.e['type'],event_date=f.e['start_date'],college=f.e['college'],package=pkg['name'],requested_paise=pkg['amount'],audience=f.e['target'],theme=f.e['goals'],event_name=f.e['name'],benefits=pkg['benefits'],fit=match['reason'],tier_rationale=rationale),fallback)
    stage='Outreach Drafted' if s['stage'] in ('Identified','Shortlisted') and kind=='outreach' else s['stage']
    f.c.execute('UPDATE sponsors SET draft=?,stage=? WHERE id=?',(a['text'],stage,s['id']))
    insert(f.c,'communications',event_id=f.id,sponsor_id=s['id'],kind=kind,text=a['text'],created_at=now())
    f.note(f'{kind.capitalize()} drafted',s['name'],'Magnet')
    return dict(message='Draft saved.',**a)

def terms(f,p,kind):
    c=f.c
    s=sponsor(f,p.get('sponsor_id'))
    if s['stage'] in ('Withdrawn','Declined'):raise Conflict('Reopen this partnership before reviewing new terms.')
    text=required(p,'text',24000)
    old=c.execute('SELECT terms FROM communications WHERE sponsor_id=? AND kind=? AND text=? AND terms IS NOT NULL',(s['id'],kind,text)).fetchone()
    if old:
        saved=json.loads(old[0])
        return dict(message='These terms were already reviewed.',approval_id=saved.get('approval_id'),terms=saved)
    t=intelligence.extract_terms(text,kind)
    f.log('Magnet','extract_terms',f'Reviewed {kind} for {s["name"]}; {len(t["deliverables"])} possible deliverables.',t['mode'])
    c.execute('UPDATE sponsors SET follow_up_date=NULL WHERE id=?',(s['id'],))
    actions=[]
    base=dict(sponsor_id=s['id'],before_stage=s['stage'],before_amount=s['committed'])
    if kind=='agreement':
        if t['amount'] is not None:
            amt=number(t['amount'],'Proposed amount')
            actions.append(dict(type='confirm',title=f'Confirm {currency(amt)} from {s["name"]}',amount=amt,due_date=t.get('payment_date') or f.e['start_date'],**base))
        for title in dict.fromkeys(t['deliverables']):
            if re.search('payment|instalment|installment',title,re.I) and not re.search('booth|speak|brand|logo',title,re.I):continue
            dept='Operations' if re.search('booth|speak|slot|stall|room|equipment',title,re.I) else 'Marketing'
            actions.append(dict(type='deliverable',title=title[:500],department=dept,sponsor_id=s['id'],due_date=f.e['start_date']))
        if t['amount']:
            due=t.get('payment_date') or f.e['start_date']
            actions.append(dict(type='payment_task',title=f'Verify {s["name"]} payment of {currency(t["amount"])}'+(f' due {due}' if t.get('payment_date') else ''),department='Finance',sponsor_id=s['id'],due_date=min(due,f.e['end_date'])))
        f.log('Ledger','review_terms','Prepared the proposed commitment and payment check. No funds recorded as received.')
        f.log('Relay','schedule_deliverables',f'Prepared {sum(a["type"]=="deliverable" for a in actions)} assigned obligations for review.')
    elif s['stage']!='Confirmed' and t['interest']=='interested':
        actions.append(dict(type='negotiate',title=f'Move {s["name"]} to Negotiating',**base))
    if kind=='response':
        actions.append(dict(type='create_task',title=f'Reply to {s["name"]} about the proposed terms',department='Sponsorship',sponsor_id=s['id'],priority='High',due_date=min(t.get('follow_up_date') or due_in(f.e,2),f.e['end_date'])))
    aid=None
    if actions:
        aid=f.approval(f'Review {s["name"]} {kind}',t['summary'],actions)
    saved=dict(t,approval_id=aid)
    insert(c,'communications',event_id=f.id,sponsor_id=s['id'],kind=kind,text=text,terms=encode(saved),created_at=now())
    f.note(f'Sponsor {kind} analyzed',s['name'],'Magnet')
    return dict(message='Extracted terms are available for organizer review.',terms=t,approval_id=aid,mode=t['mode'])

def confirm(f,s,amount,due_date=None,defaults=True):
    c=f.c
    paid=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE sponsor_id=?',(s['id'],)).fetchone()[0]
    if amount<paid:raise Conflict('The commitment cannot fall below recorded payments.')
    first=s['stage']!='Confirmed'
    due=iso(due_date).isoformat() if due_date else f.e['start_date']
    with f.tool('Ledger','create_sponsor_receivable',dict(sponsor_id=s['id'],amount=amount,due_date=due)) as step:
        c.execute("UPDATE sponsors SET stage='Confirmed',committed=?,follow_up_date=NULL WHERE id=?",(amount,s['id']))
        if amount:
            c.execute('INSERT INTO receivables VALUES (?,?) ON CONFLICT(sponsor_id) DO UPDATE SET due_date=excluded.due_date',(s['id'],due))
        step.update(summary=f'Recorded {currency(amount)} committed by {s["name"]}.',output=dict(outstanding=amount-paid,due_date=due))
    if first and defaults:
        with f.tool('Atlas','create_task',dict(sponsor_id=s['id'])) as step:
            ids=[]
            artwork_due=min(due_in(f.e,5),f.e['start_date'])
            for title,dept,due in [(f'Confirm {s["name"]} logo placement on the stage banner','Marketing',artwork_due),
                                   (f'Set up the {s["name"]} partner booth','Operations',f.e['start_date'])]:
                key=task(c,f.id,title,dept,due,'Atlas','High',sponsor_id=s['id'])
                insert(c,'deliverables',event_id=f.id,sponsor_id=s['id'],task_id=key)
                ids.append(key)
            c.execute('INSERT INTO dependencies VALUES (?,?)',(ids[1],ids[0]))
            step.update(summary=f'Created {len(ids)} linked deliverables for {s["name"]}.',output=dict(task_ids=ids))
    if first:
        draft=f.consult('Echo','draft_campaign',dict(sponsor=s['name'],target=f.e['target'],venue=f.e['venue'],start=f.e['start_date']),
             f'Welcome {s["name"]} as a partner for {f.e["name"]}. We look forward to bringing together {f.e["target"]} students on {f.e["start_date"]} at {f.e["venue"]}.')
        insert(c,'marketing',event_id=f.id,title=f'Welcome {s["name"]}',channel='Social',body=draft['text'],scheduled_date=due_in(f.e,2))
    if not funding(c,f.e)['shortfall']:
        c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint='funding-gap'",(f.id,))
        c.execute("UPDATE approvals SET status='Superseded',decided_at=? WHERE status='Pending' AND risk_id IN (SELECT id FROM risks WHERE event_id=? AND fingerprint='funding-gap')",(now(),f.id))
    f.note('Sponsor commitment confirmed',f'{s["name"]} committed {currency(amount)}.','Ledger')
    return dict(message='Commitment recorded. Atlas linked deliverables and Echo saved an announcement draft.')

def withdraw(f,p):
    s=sponsor(f,p.get('sponsor_id'))
    if s['stage']=='Withdrawn': return dict(message='Withdrawal already recorded.')
    if s['stage']!='Confirmed':raise Conflict('Only a confirmed commitment can be withdrawn.')
    if f.c.execute('SELECT 1 FROM payments WHERE sponsor_id=?',(s['id'],)).fetchone():
        raise Conflict('This sponsor has recorded payments. Reconcile a refund separately before withdrawing.')
    before=funding(f.c,f.e)['balance']
    f.c.execute("UPDATE sponsors SET stage='Withdrawn',committed=0,follow_up_date=NULL WHERE id=?",(s['id'],))
    f.note(f'{s["name"]} withdrew',f'{currency(s["committed"])} removed from projected funding.','Magnet')
    return optimize(f,f'{s["name"]} withdrawal',previous=before,withdrawn=s["id"])

def stage(f,p):
    s=sponsor(f,p.get('sponsor_id'))
    dest=choice(p.get('stage'),STAGES,'sponsorship stage')
    if dest==s['stage']:return dict(message='Sponsor already has this stage.')
    if dest=='Withdrawn':return withdraw(f,p)
    if s['stage']=='Confirmed':raise Conflict('Use the withdrawal workflow for a confirmed sponsor.')
    if s['stage'] in ('Withdrawn','Declined') and dest not in ('Identified','Shortlisted'): raise Conflict('Reopen the sponsor as Identified or Shortlisted first.')
    if dest=='Confirmed':
        return confirm(f,s,number(p.get('amount'),'Commitment amount'),p.get('due_date'))
    follow=(date.today()+timedelta(days=s['follow_up_days'])).isoformat() if dest=='Contacted' else None
    f.c.execute('UPDATE sponsors SET stage=?,follow_up_date=? WHERE id=?',(dest,follow,s['id']))
    f.note(f'{s["name"]} moved to {dest}',f'Previous stage: {s["stage"]}.','Magnet')
    return dict(message='Pipeline updated.')

def payment(f,p):
    s=sponsor(f,p.get('sponsor_id'))
    if s['stage']!='Confirmed':raise Conflict('Only confirmed sponsors can record payments.')
    amt=number(p.get('amount'),'Payment',1)
    received=f.c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE sponsor_id=?',(s['id'],)).fetchone()[0]
    if amt>s['committed']-received:raise Conflict('Payment exceeds the outstanding commitment.')
    with f.tool('Ledger','record_payment',dict(sponsor_id=s['id'],amount=amt)) as step:
        insert(f.c,'payments',event_id=f.id,sponsor_id=s['id'],amount=amt,created_at=now())
        remaining=s['committed']-received-amt
        if not remaining:
            f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint=?",(f.id,'payment:'+s['id']))
        step.update(summary=f'Recorded incoming {currency(amt)} from {s["name"]}.',output=dict(outstanding=remaining))
    f.note('Sponsor payment received',f'{s["name"]} paid {currency(amt)}.','Ledger')
    return dict(message='Payment recorded.')
