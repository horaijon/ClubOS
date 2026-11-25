"""Scoped reads, scheduling constraints and exact financial projections."""
import json
import re
from collections import Counter
from datetime import date, timedelta
from .db import rows, insert, now

class Invalid(ValueError):
    pass

class Missing(Invalid):
    pass

class Conflict(Invalid):
    pass

TASK_STATES = ('To Do','In Progress','Blocked','Review','Completed')
PRIORITIES = ('Low','Medium','High','Critical')
STAGES = ('Identified','Shortlisted','Outreach Drafted','Contacted','Responded','Negotiating','Confirmed','Declined','Withdrawn')

def required(p, key, length=500):
    s = p.get(key)
    if not isinstance(s,str) or not s.strip() or len(s.strip())>length:
        raise Invalid(f'Enter a {key.replace("_"," ")} between 1 and {length} characters.')
    return s.strip()

def number(value, label, low=0, high=100_000_000_000):
    if type(value) is not int or not low <= value <= high:
        raise Invalid(f'{label} must be a whole number between {low} and {high}.')
    return value

def iso(value):
    try:
        return date.fromisoformat(value)
    except (TypeError,ValueError):
        raise Invalid('Use a valid date in YYYY-MM-DD format.')

def choice(value, options, label):
    if value not in options:
        raise Invalid(f'Choose a valid {label} ({", ".join(options)}).')
    return value

def get_event(c, eid):
    r = c.execute('SELECT e.*,c.name club FROM events e JOIN clubs c ON e.club_id=c.id WHERE e.id=?',(eid,)).fetchone()
    if not r:
        raise Missing('Event not found.')
    event = dict(r)
    event['is_demo'] = bool(event['is_demo'])
    event['constraints'] = event.pop('constraints_text')
    return event

def scoped(c, table, key, eid):
    if not isinstance(key, str) or not key or len(key) > 150:
        raise Invalid('Supply a valid record ID.')
    r = c.execute(f'SELECT * FROM {table} WHERE id=? AND event_id=?',(key,eid)).fetchone()
    if not r:
        raise Missing(f'{table.capitalize()} record not found in this event.')
    return dict(r)

def team(c,eid):
    return rows(c,'SELECT m.* FROM members m JOIN team t ON t.member_id=m.id WHERE t.event_id=? ORDER BY m.name',(eid,))

def owner(c,eid,dept):
    r = c.execute("""SELECT m.id,COUNT(t.id) workload FROM members m JOIN team tm ON tm.member_id=m.id
        LEFT JOIN tasks t ON t.event_id=tm.event_id AND t.owner_id=m.id AND t.status<>'Completed'
        WHERE tm.event_id=? GROUP BY m.id ORDER BY (m.department=?) DESC,workload,m.name LIMIT 1""",(eid,dept)).fetchone()
    return r[0] if r else None

def task(c,eid,title,dept,due,agent='Atlas',priority='Medium',status='To Do',description='',sponsor_id=None,owner_id=None):
    timestamp=now()
    return insert(c,'tasks',event_id=eid,title=title,description=description,department=dept,owner_id=owner_id or owner(c,eid,dept),
                  due_date=due,status=status,priority=priority,sponsor_id=sponsor_id,agent=agent,created_at=timestamp,
                  completed_at=timestamp if status=='Completed' else None)

def due_in(event, days):
    return min(date.today()+timedelta(days=days), iso(event['end_date'])).isoformat()

def budgets(c,eid):
    return rows(c,"""SELECT b.*,COALESCE(SUM(x.amount),0) actual FROM budget b LEFT JOIN expenses x ON x.category_id=b.id
        WHERE b.event_id=? GROUP BY b.id ORDER BY b.planned DESC,b.category""",(eid,))

def prospects(c,event,include_directory=False):
    words = set(re.findall(r'[a-z0-9]+',' '.join(str(event[k]).lower() for k in ['type','name','goals','description','college','venue']).replace('hackathons','hackathon')))
    from .seed import CLUB
    found = rows(c,'''SELECT * FROM profiles WHERE event_scope=? OR (event_scope IS NULL AND
        (? OR ?=? OR EXISTS (SELECT 1 FROM registration_forms WHERE event_id=?)))''',
        (event['id'],include_directory,event['club_id'],CLUB,event['id']))
    for p in found:
        tags=p.pop('tags').split(',')
        matches=[t for t in tags if t in words]
        p['score']=min(99,55+min(3,len(matches))*11+(6 if p['relationship'] else 0)+(4 if 'student' in tags else 0))
        p['reason']=(f"{p['industry']} profile aligned with {', '.join(matches)}." if matches else f"{p['industry']} partner offering {p['sponsorship_type'].lower()} support for campus events.") + (f" {p['relationship']}" if p['relationship'] else '')
    return sorted(found,key=lambda x:(-x['score'],x['name']))

def task_rows(c,eid):
    result=rows(c,'SELECT t.*,m.name owner FROM tasks t LEFT JOIN members m ON t.owner_id=m.id WHERE t.event_id=? ORDER BY due_date,t.rowid',(eid,))
    deps={}
    for r in c.execute('SELECT d.task_id,d.depends_on FROM dependencies d JOIN tasks t ON d.task_id=t.id WHERE t.event_id=?',(eid,)):
        deps.setdefault(r[0],[]).append(r[1])
    for r in result:
        r['dependencies']=deps.get(r['id'],[])
    return result

def funding(c,event):
    eid=event['id']
    amounts=budgets(c,eid)
    planned=sum(x['planned'] for x in amounts)
    actual=sum(x['actual'] for x in amounts)
    committed=c.execute("SELECT COALESCE(SUM(committed),0) FROM sponsors WHERE event_id=? AND stage='Confirmed'",(eid,)).fetchone()[0]
    received=c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE event_id=?",(eid,)).fetchone()[0]
    projected=event['initial_budget']+committed
    exposure=sum(max(x['planned'],x['actual']) for x in amounts)
    return dict(planned=planned,actual=actual,committed=committed,received=received,projected_funding=projected,exposure=exposure,balance=projected-exposure,cash_balance=event['initial_budget']+received-actual,shortfall=max(0,exposure-projected),outstanding=committed-received)

def workspace(c,eid):
    e=get_event(c,eid)
    result=dict(event=e,members=team(c,eid),tasks=task_rows(c,eid),budget=budgets(c,eid))
    for table in ['participants','marketing','milestones','packages','risks','approvals','runs','activity','communications','payments','workflows']:
        result[table]=rows(c,f'SELECT * FROM {table} WHERE event_id=? ORDER BY rowid DESC',(eid,))
    for w in result['workflows']:
        w.pop('input_hash',None)
        w.pop('result',None)
    for a in result['approvals']:
        a['actions']=json.loads(a['actions'])
    for r in result['risks']:
        r['agents']=json.loads(r['agents'])
    for cm in result['communications']:
        cm['terms']=json.loads(cm['terms']) if cm['terms'] else None
    result['expenses']=rows(c,'SELECT x.*,b.category FROM expenses x JOIN budget b ON b.id=x.category_id WHERE x.event_id=? ORDER BY x.rowid DESC',(eid,))
    profiles=prospects(c,e)
    pmap={p['id']:p for p in profiles}
    sponsors=rows(c,"""SELECT s.*,COALESCE(SUM(p.amount),0) received FROM sponsors s LEFT JOIN payments p ON p.sponsor_id=s.id WHERE s.event_id=? GROUP BY s.id ORDER BY s.rowid""",(eid,))
    deliverables=rows(c,"""SELECT d.*,t.title,t.status,t.due_date,m.name owner FROM deliverables d JOIN tasks t ON t.id=d.task_id LEFT JOIN members m ON t.owner_id=m.id WHERE d.event_id=?""",(eid,))
    receivables={r['sponsor_id']:r for r in rows(c,
        'SELECT r.* FROM receivables r JOIN sponsors s ON s.id=r.sponsor_id WHERE s.event_id=?',(eid,))}
    today=date.today().isoformat()
    for s in sponsors:
        for k,v in pmap[s['prospect_id']].items():
            if k!='id': s[k]=v
        due=receivables.get(s['id'])
        if due:
            outstanding=max(0,s['committed']-s['received'])
            due.update(amount=s['committed'],received=s['received'],outstanding=outstanding,sponsor_name=s['name'],
                       status='Withdrawn' if s['stage']=='Withdrawn' else 'Paid' if not outstanding else
                       'Overdue' if due['due_date']<today else 'Part paid' if s['received'] else 'Open')
        s['receivable']=due
        s['deliverables']=[d for d in deliverables if d['sponsor_id']==s['id']]
    result['sponsors']=sponsors
    result['receivables']=list(receivables.values())
    from .registration import form_for_event
    result['registration_form']=form_for_event(c,eid)
    answers={row['participant_id']:json.loads(row['answers']) for row in rows(c,
             'SELECT a.* FROM registration_answers a JOIN participants p ON p.id=a.participant_id WHERE p.event_id=?',(eid,))}
    for participant in result['participants']:
        participant['answers']=answers.get(participant['id'],{})
    pipeline={s['prospect_id'] for s in sponsors}
    result['prospects']=[p for p in profiles if p['id'] not in pipeline]
    today=date.today().isoformat()
    m=funding(c,e)
    m.update(registered=len(result['participants']),target=e['target'],completed=sum(t['status']=='Completed' for t in result['tasks']),total_tasks=len(result['tasks']),overdue=sum(t['due_date']<today and t['status']!='Completed' for t in result['tasks']),active_risks=sum(r['status'] not in ('Resolved','Closed') for r in result['risks']),pending_approvals=sum(a['status']=='Pending' for a in result['approvals']))
    m['readiness']=round(35*m['completed']/max(1,m['total_tasks'])+35*min(1,m['registered']/m['target'])+30*min(1,m['projected_funding']/max(1,m['exposure'])))
    efforts={'Atlas':8,'Relay':5,'Sentinel':5,'Echo':10,'Magnet':12,'Ledger':8,'Nexus':2}
    m['actions']=len(result['runs'])
    m['minutes_saved']=sum(efforts.get(r['agent'],3) for r in result['runs'])
    from .planning import TOOLS
    result['agent_tools']={agent:sorted(tools) for agent,tools in TOOLS.items()}
    result['metrics']=m
    counts=Counter(p['created_at'][:10] for p in result['participants'])
    cumulative=0
    result['registration_history']=[]
    for day,n in sorted(counts.items()):
        cumulative+=n
        result['registration_history'].append(dict(date=day,count=n,cumulative=cumulative))
    return result
