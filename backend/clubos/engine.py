"""Nexus dispatches explicit tools. The caller owns a single SQLite transaction."""
import hashlib
import json
from datetime import date,timedelta
from .db import insert,rows,now,encode,uid
from .state import (workspace,get_event,number,choice,iso,required,task_rows,scoped,Invalid,Missing,Conflict,
                    due_in,funding,prospects,task)
from .planning import Flow,TOOLS,generate
from . import sponsorship as crm
from . import operations as ops
from . import recovery
from .seed import DEMO,seed_event

def create(c,data,club_id,execution=None):
    eid=uid()
    if iso(data['start_date'])>iso(data['end_date']):raise Invalid('Event end date must be on or after the start.')
    chosen=data.pop('members',[])
    if 'constraints' in data:data['constraints_text']=data.pop('constraints')
    insert(c,'events',id=eid,club_id=club_id,registration_milestone=max(1,data['target']//2),milestone_date=min(iso(data['start_date']),max(date.today(),iso(data['start_date'])-timedelta(days=7))).isoformat(),created_at=now(),**data)
    members=rows(c,'SELECT * FROM members WHERE club_id=? ORDER BY rowid',(club_id,))
    if chosen:
        ids=[]
        for name in chosen:
            member=next((m for m in members if m['id']==name or m['name'].lower()==name.lower()),None)
            mid=member['id'] if member else insert(c,'members',club_id=club_id,name=name,department='Planning',role='Organizer')
            if mid not in ids:ids.append(mid)
    else:ids=[m['id'] for m in members[:12]]
    c.executemany('INSERT INTO team VALUES (?,?)',[(eid,k) for k in ids])
    wid=insert(c,'workflows',event_id=eid,trigger='Event created',request_id='initial-plan',input_hash='plan',result='{}',created_at=now())
    if execution: execution.attach_event(eid)
    generate(Flow(c,get_event(c,eid),wid,'Event created',execution=execution))
    return dict(id=eid)

def due_items(c,e):
    today=date.today().isoformat()
    limit=(date.today()+timedelta(days=3)).isoformat()
    eid=e['id']
    deliverables=rows(c,"""SELECT d.id,t.title,t.due_date,m.name owner FROM deliverables d JOIN tasks t ON d.task_id=t.id JOIN sponsors s ON s.id=d.sponsor_id LEFT JOIN members m ON m.id=t.owner_id WHERE d.event_id=? AND s.stage='Confirmed' AND t.status<>'Completed' AND t.due_date<=? AND NOT EXISTS (SELECT 1 FROM risks r WHERE r.event_id=d.event_id AND r.fingerprint='deliverable:'||d.id AND (t.due_date>=? OR r.severity='High'))""",(eid,limit,today))
    follows=rows(c,"SELECT id FROM sponsors WHERE event_id=? AND stage='Contacted' AND follow_up_date<=?",(eid,today))
    overdue=rows(c,"""SELECT t.* FROM tasks t WHERE event_id=? AND status<>'Completed' AND due_date<? AND NOT EXISTS (SELECT 1 FROM risks r WHERE r.event_id=t.event_id AND r.fingerprint='overdue:'||t.id)""",(eid,today))
    count=c.execute('SELECT COUNT(*) FROM participants WHERE event_id=?',(eid,)).fetchone()[0]
    reg=False
    if e['milestone_date'] and e['milestone_date']<=today and count<e['registration_milestone']:
        reg=not c.execute('SELECT 1 FROM risks WHERE event_id=? AND fingerprint=?',(eid,f'registration:{e["registration_milestone"]}:{e["milestone_date"]}')).fetchone()
    payment_limit=(date.today()+timedelta(days=10)).isoformat()
    collections=rows(c,"""SELECT s.id,p.name,r.due_date,s.committed-COALESCE(SUM(x.amount),0) outstanding
        FROM receivables r JOIN sponsors s ON s.id=r.sponsor_id JOIN profiles p ON p.id=s.prospect_id
        LEFT JOIN payments x ON x.sponsor_id=s.id
        WHERE s.event_id=? AND s.stage='Confirmed' AND (r.due_date<=? OR ?<=?)
          AND NOT EXISTS (SELECT 1 FROM risks rr WHERE rr.event_id=s.event_id AND rr.fingerprint='payment:'||s.id)
        GROUP BY s.id HAVING outstanding>0""",(eid,payment_limit,e['start_date'],payment_limit))
    return deliverables,follows,overdue,reg,collections

def scan(f,items=None):
    ds,ss,ts,reg,collections=items if items is not None else due_items(f.c,f.e)
    for d in ds:recovery.deadline(f,d)
    for s in ss:
        s=crm.sponsor(f,s['id'])
        result=crm.draft(f,dict(sponsor_id=s['id']),'followup')
        f.c.execute('UPDATE sponsors SET follow_up_date=NULL WHERE id=?',(s['id'],))
        task(f.c,f.id,f'Review follow-up for {s["name"]}','Sponsorship',due_in(f.e,1),'Magnet','High',sponsor_id=s['id'])
        f.approval(f'Review {s["name"]} follow-up','Review the saved draft before sending it manually.',[dict(type='draft_review',title=f'Approve follow-up for {s["name"]}',sponsor_id=s['id'])])
    for t in ts:
        f.risk('overdue:'+t['id'],'Overdue task: '+t['title'],f'Original deadline was {t["due_date"]}.','High' if t['priority'] in ('High','Critical') else 'Medium','A milestone may slip.','Review the task with its owner or propose a revised timeline.',['Sentinel','Atlas'])
        if t['priority']=='Critical' and date.today().isoformat()<=f.e['end_date']:
            recovery.delay(f,t['id'],max(1,min(60,(date.today()-iso(t['due_date'])).days+1)))
    for s in collections:
        f.risk('payment:'+s['id'],f'Collect {s["name"]} payment',f'Payment milestone: {s["due_date"]}.','High',
            f'{recovery.currency(s["outstanding"])} outstanding.','Contact the sponsor to verify its remittance date.',['Sentinel','Ledger'])
    if reg:recovery.registration(f)
    f.log('Sentinel','scan',f'Checked event state: {len(ds)} deliverable alerts, {len(ss)} follow-ups, {len(ts)} newly overdue tasks, {len(collections)} payment alerts.')
    return dict(message='Risk scan complete.')

def tick(eid):
    from . import db,trace
    with db.transaction() as c:
        event=get_event(c,eid)
        if not any(due_items(c,event)):return
    request_id=uid()
    execution=trace.Execution(event['club_id'],eid,request_id,'Scheduled scan')
    with execution.recording(),db.transaction(write=True) as c:
        e=get_event(c,eid)
        items=due_items(c,e)
        if any(items):
            wid=insert(c,'workflows',event_id=eid,trigger='Scheduled scan',request_id=request_id,input_hash='scheduled',result='{}',created_at=now())
            return scan(Flow(c,e,wid,'Scheduled scan',execution=execution),items)

def demo(f,kind):
    if f.id!=DEMO or not f.e['is_demo']:raise Invalid('This scenario requires the seeded CodeStorm workspace.')
    c=f.c
    def partner(slug):
        r=c.execute('SELECT id FROM sponsors WHERE event_id=? AND prospect_id=?',(f.id,slug)).fetchone()
        return r[0]
    if kind=='demo_withdraw':return crm.withdraw(f,dict(sponsor_id=partner('vectorforge')))
    if kind=='demo_overrun':
        desc='Unexpected venue surcharge'
        if c.execute('SELECT 1 FROM expenses WHERE event_id=? AND description=?',(f.id,desc)).fetchone():
            raise Conflict('The venue surcharge has already been recorded.')
        venue=c.execute("SELECT id FROM budget WHERE event_id=? AND category='Venue'",(f.id,)).fetchone()[0]
        return ops.expense(f,dict(category_id=venue,amount=1_200_000,description=desc),False)
    if kind=='demo_delay':
        # Prefer an unfinished prerequisite with live dependants.
        t=c.execute("""SELECT t.id FROM tasks t WHERE event_id=? AND status<>'Completed'
              AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN tasks p ON p.id=d.depends_on
                WHERE d.task_id=t.id AND p.status<>'Completed')
            ORDER BY (EXISTS (SELECT 1 FROM dependencies d JOIN tasks child ON child.id=d.task_id WHERE d.depends_on=t.id AND child.status<>'Completed')) DESC,(priority='Critical') DESC,(priority='High') DESC,t.due_date LIMIT 1""",(f.id,)).fetchone()
        if not t:raise Conflict('No open tasks remain.')
        yesterday=(date.today()-timedelta(days=1)).isoformat()
        c.execute("UPDATE tasks SET due_date=MIN(due_date,?) WHERE id=?",(yesterday,t[0]))
        return recovery.delay(f,t[0],2)
    if kind=='demo_registration':
        count=c.execute('SELECT COUNT(*) FROM participants WHERE event_id=?',(f.id,)).fetchone()[0]
        if count>=f.e['target']:raise Conflict('This event has met its full registration target.')
        target=min(f.e['target'],max(count+1,f.e['target']*4//5))
        c.execute('UPDATE events SET registration_milestone=?,milestone_date=? WHERE id=?',(target,date.today().isoformat(),f.id))
        f.e=get_event(c,f.id)
        return recovery.registration(f)
    if kind in ('demo_agreement','demo_response'):
        text=('Kernel Grove agrees to sponsor CodeStorm 2026 for ₹25,000. Display our logo on the event posters. Provide a 10-minute speaking slot. Provide a partner booth during the event.' if kind=='demo_agreement' else 'We are interested in supporting CodeStorm with ₹25,000 provided our logo appears on all event posters and we receive a 10-minute speaking slot.')
        return crm.terms(f,dict(sponsor_id=partner('kernel-grove'),text=text),'agreement' if kind=='demo_agreement' else 'response')
    if kind=='demo_deadline':
        r=c.execute("""SELECT d.id,d.task_id,t.title,m.name owner FROM deliverables d JOIN tasks t ON t.id=d.task_id JOIN sponsors s ON s.id=d.sponsor_id LEFT JOIN members m ON m.id=t.owner_id WHERE d.event_id=? AND s.stage='Confirmed' AND t.status<>'Completed' ORDER BY d.rowid LIMIT 1""",(f.id,)).fetchone()
        if not r:raise Conflict('No open confirmed deliverable is available.')
        day=due_in(f.e,1)
        c.execute('UPDATE tasks SET due_date=? WHERE id=?',(day,r['task_id']))
        return dict(message='Sponsor deadline checked.',**recovery.deadline(f,dict(r,due_date=day)))
    raise Invalid('Unknown demo scenario.')

def route(f,k,p):
    c=f.c
    if k.startswith('demo_'):return demo(f,k)
    if k in ('approve','reject'):return recovery.decide(f,p,k=='approve')
    if k=='budget_optimize':return recovery.optimize(f)
    if k=='delay_task':return recovery.delay(f,p.get('task_id'),p.get('days',2))
    if k=='risk_scan':return scan(f)
    if k=='edit_approval':return recovery.edit(f,p)
    if k=='agent_check':
        agent=choice(p.get('agent'),TOOLS,'agent')
        if agent=='Sentinel':return scan(f)
        if agent=='Echo':return ops.campaign(f,dict(title='Registration reminder',channel='Social'),True)
        check={
            'Atlas':('trace_dependencies',lambda:dict(open_tasks=sum(t['status']!='Completed' for t in task_rows(c,f.id)),
                dependencies=sum(len(t['dependencies']) for t in task_rows(c,f.id)))),
            'Ledger':('project_balance',lambda:funding(c,f.e)),
            'Magnet':('rank_sponsors',lambda:dict(matches=[dict(name=s['name'],fit=s['score']) for s in prospects(c,f.e)[:3]])),
            'Relay':('work_checklist',lambda:dict(open_operations=[t['title'] for t in task_rows(c,f.id)
                 if t['department']=='Operations' and t['status']!='Completed'])),
            'Nexus':('query_event_state',lambda:workspace(c,f.id)['metrics']),
        }
        tool,compute=check[agent]
        with f.tool(agent,tool) as step:
            result=compute()
            step.update(summary=f'{agent} checked {f.e["name"]}.',output=result)
        return dict(message=f'{agent} check complete.',**result)
    if k=='withdraw':return crm.withdraw(f,p)
    if k=='add_prospect':return crm.add_prospect(f,p)
    if k=='sponsor_stage':return crm.stage(f,p)
    if k in ('outreach','proposal','followup'):return crm.draft(f,p,k)
    if k in ('analyze_response','analyze_agreement'):return crm.terms(f,p,k.split('_')[1])
    if k=='record_payment':return crm.payment(f,p)
    if k in ('save_draft','follow_up','approve_draft'):
        s=crm.sponsor(f,p.get('sponsor_id'))
        if k=='save_draft':
            text=required(p,'text',16000)
            c.execute('UPDATE sponsors SET draft=? WHERE id=?',(text,s['id']))
        elif k=='approve_draft':
            if not s['draft']:raise Conflict('Save a draft first.')
            aid=f.approval('Review outreach draft',f'Approve the saved draft for {s["name"]}.',[dict(type='draft_review',title=f'Approve draft for {s["name"]}',sponsor_id=s['id'])])
            return dict(message='Draft queued for review.',approval_id=aid)
        else:
            days=number(p.get('days'),'Follow-up interval',1,60)
            c.execute('UPDATE sponsors SET follow_up_days=?,follow_up_date=? WHERE id=?',(days,(date.today()+timedelta(days=days)).isoformat() if s['stage']=='Contacted' else None,s['id']))
        f.note('Sponsor draft saved' if k=='save_draft' else 'Follow-up interval updated',s['name'],'Magnet')
        return dict(message='Sponsor updated.')
    if k in ('add_task','update_task'):return ops.edit_task(f,p,k=='update_task')
    if k in ('add_participant','check_in','import_participants'):return ops.register(f,p,k)
    if k in ('add_expense','edit_expense'):return ops.expense(f,p,k=='edit_expense')
    if k in ('save_marketing','generate_marketing'):return ops.campaign(f,p,k=='generate_marketing')
    if k=='copilot':return ops.copilot(f,p)
    if k=='import_sponsors':return ops.imports(f,p)
    if k=='update_package':
        b=scoped(c,'packages',p.get('package_id'),f.id)
        c.execute('UPDATE packages SET name=?,amount=?,benefits=? WHERE id=?',(required(p,'name',120),number(p.get('amount'),'Package amount'),required(p,'benefits',3500),b['id']))
        f.note('Proposed package updated',b['name'],'Magnet')
        return dict(message='Package updated.')
    if k=='add_member':
        m=insert(c,'members',club_id=f.e['club_id'],name=required(p,'name',120),role=required(p,'role',100),department=required(p,'department',100))
        c.execute('INSERT INTO team VALUES (?,?)',(f.id,m))
        f.note('Organizer added to event',p['name'],'Relay')
        return dict(message='Team member added.',id=m)
    if k=='complete_deliverable':
        d=scoped(c,'deliverables',p.get('deliverable_id'),f.id)
        evidence=required(p,'evidence',3000)
        c.execute('UPDATE deliverables SET evidence=? WHERE id=?',(evidence,d['id']))
        c.execute("UPDATE tasks SET status='Completed',completed_at=COALESCE(completed_at,?) WHERE id=?",(now(),d['task_id']))
        c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint IN (?,?)",(f.id,'deliverable:'+d['id'],'overdue:'+d['task_id']))
        f.note('Sponsor deliverable completed','Completion evidence recorded.','Relay')
        return dict(message='Evidence saved.')
    raise Invalid('Unknown action type.')

def dispatch(c,eid,kind,p,request_id,execution=None):
    e=get_event(c,eid)
    signature=hashlib.sha256(json.dumps([kind,p],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    previous=c.execute('SELECT input_hash,result FROM workflows WHERE event_id=? AND request_id=?',(eid,request_id)).fetchone()
    if previous:
        if previous['input_hash']!=signature:raise Conflict('Request ID already used for a different action.')
        return json.loads(previous['result'])
    if kind=='demo_reset':
        if eid!=DEMO or not e['is_demo']:raise Invalid('Only the seeded demo can be reset.')
        c.execute('DELETE FROM events WHERE id=?',(eid,))
        seed_event(c)
    wid=insert(c,'workflows',event_id=eid,trigger=kind,request_id=request_id,input_hash=signature,created_at=now())
    f=Flow(c,e,wid,kind,execution=execution)
    result=dict(message='Demo workspace restored.') if kind=='demo_reset' else route(f,kind,p)
    result.setdefault('workflow_id',wid)
    c.execute('UPDATE workflows SET result=? WHERE id=?',(encode(result),wid))
    return result
