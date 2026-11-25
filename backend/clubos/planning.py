"""Nexus planning tools and their role-specific execution records."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from . import intelligence
from .db import encode, insert, now
from .state import iso, due_in, task, prospects, team, funding

TOOLS = {
    'Nexus':{'dispatch','consolidate','answer','apply_plan'},
    'Atlas':{'plan_tasks','trace_dependencies','reassign'},
    'Ledger':{'allocate_budget','project_balance','review_terms','record_payment'},
    'Magnet':{'rank_sponsors','draft_outreach','extract_terms','propose_package','follow_up'},
    'Echo':{'draft_campaign','plan_branding'},
    'Relay':{'work_checklist','schedule_deliverables','register'},
    'Sentinel':{'scan','detect','verify'}
}

class Flow:
    def __init__(self,c,event,wid,trigger,local=False):
        self.c,self.e,self.wid,self.trigger,self.local=c,event,wid,trigger,local
        self.id=event['id']

    def note(self,title,description='',agent='Nexus'):
        return insert(self.c,'activity',event_id=self.id,title=title,description=description,agent=agent,created_at=now())

    def advice(self,agent,context,fallback):
        if self.local:
            return dict(text=fallback,mode='deterministic')
        try:
            return intelligence.advise(agent,dict(event=self.e['name'],**context),fallback)
        except Exception:
            return dict(text=fallback,mode='fallback')

    def log(self,agent,tool,summary,mode='deterministic',status='Completed'):
        if tool not in TOOLS[agent]:
            raise RuntimeError('Agent tool permission mismatch')
        insert(self.c,'runs',event_id=self.id,workflow_id=self.wid,agent=agent,trigger=self.trigger,tool=tool,summary=summary,mode=mode,status=status,created_at=now())
        return summary

    def consult(self,agent,tool,context,fallback):
        answer=self.advice(agent,context,fallback)
        self.log(agent,tool,answer['text'],answer['mode'])
        return answer

    def risk(self,fingerprint,title,description,severity,impact,recommendation,agents):
        existing=self.c.execute('SELECT id FROM risks WHERE event_id=? AND fingerprint=?',(self.id,fingerprint)).fetchone()
        values=(title,description,severity,impact,recommendation,encode(agents))
        if existing:
            self.c.execute("UPDATE risks SET title=?,description=?,severity=?,impact=?,recommendation=?,agents=?,status='Open' WHERE id=?",(*values,existing[0]))
            return existing[0]
        return insert(self.c,'risks',event_id=self.id,fingerprint=fingerprint,title=title,description=description,severity=severity,source=self.trigger,impact=impact,recommendation=recommendation,agents=encode(agents),created_at=now())

    def approval(self,title,description,actions,risk_id=None):
        key=insert(self.c,'approvals',event_id=self.id,workflow_id=self.wid,risk_id=risk_id,title=title,description=description,actions=encode(actions),created_at=now())
        self.log('Nexus','consolidate',f'Queued {len(actions)} proposed actions for organizer review.','deterministic','Awaiting Approval')
        self.note(title,description)
        return key

# relative days before event, department, priority and preceding task index
PLAN = [
 ('Approve event brief','Planning',20,'High',None),('Confirm venue and access hours','Operations',18,'Critical',0),
 ('Finalize sponsorship packages','Sponsorship',18,'High',0),('Build sponsor shortlist','Sponsorship',16,'High',2),
 ('Open participant registrations','Marketing',15,'High',0),('Prepare event artwork','Marketing',14,'Medium',0),
 ('Review vendor estimates','Finance',14,'High',1),('Confirm judging panel','Planning',12,'High',0),
 ('Publish launch announcement','Marketing',12,'High',4),('Map equipment and power needs','Operations',11,'High',1),
 ('Send sponsor proposal drafts for review','Sponsorship',10,'High',3),('Confirm catering headcount','Operations',9,'Medium',6),
 ('Prepare volunteer assignments','Operations',8,'Medium',1),('Review payment schedule','Finance',8,'High',2),
 ('Build judging rubric','Planning',7,'Medium',7),('Schedule sponsor acknowledgements','Marketing',7,'Medium',5),
 ('Test Wi-Fi coverage','Operations',6,'High',9),('Brief track mentors','Planning',6,'Medium',7),
 ('Review registration milestone','Marketing',5,'High',4),('Prepare signage layout','Operations',5,'Medium',5),
 ('Verify sponsor deliverables','Sponsorship',4,'High',10),('Reconcile purchase receipts','Finance',4,'Medium',6),
 ('Prepare check-in desk','Operations',3,'High',12),('Schedule final participant briefing','Marketing',3,'Medium',18),
 ('Approve event-day schedule','Planning',2,'Critical',14),('Conduct technical rehearsal','Operations',1,'Critical',16),
 ('Brief volunteer leads','Operations',1,'Medium',12),('Run opening check-in','Operations',0,'High',22),
 ('Archive attendance report','Operations',0,'Medium',27),('Collect sponsor fulfilment evidence','Sponsorship',0,'High',20),
]
CATEGORIES=[('Food & refreshments',28,0),('Prizes',20,0),('Merchandise',15,50),('Venue',12,0),('Equipment',10,15),('Logistics',8,40),('Marketing',4,50),('Printing',3,40)]
PACKAGES=[('Title Sponsor',100,'Naming recognition, opening address and a dedicated exhibition booth.'),('Platinum Sponsor',75,'Main-stage recognition, a speaking opportunity and branded posters.'),('Gold Sponsor',50,'Partner booth, logo placement and two social acknowledgements.'),('Silver Sponsor',25,'Website logo and a partner acknowledgement.'),('Community Partner',10,'Community recognition and campus newsletter inclusion.'),('In-Kind Partner',0,'Recognition corresponding to documented equipment or service contributions.')]

def generate(flow,seed=False):
    c,e,eid=flow.c,flow.e,flow.id
    flow.log('Nexus','dispatch','Dispatched planning, finance, sponsorship, marketing, operations and risk checks.')
    start=iso(e['start_date'])
    import datetime
    today=datetime.date.today()
    earliest=today-timedelta(days=14) if seed else min(today,start)
    ids=[]
    for i,(title,dept,offset,priority,dep) in enumerate(PLAN):
        day=max(earliest,start-timedelta(days=offset)).isoformat()
        status=('Completed' if i<10 else 'In Progress' if i<17 else 'To Do') if seed else 'To Do'
        k=task(c,eid,title,dept,day,priority=priority,status=status,description=f'{dept} lead verifies completion and records the outcome for {e["name"]}.')
        ids.append(k)
        if dep is not None: c.execute('INSERT INTO dependencies VALUES (?,?)',(k,ids[dep]))
    flow.log('Atlas','plan_tasks',f'Assigned {len(ids)} tasks across {len(team(c,eid))} team members, with timeline dependencies.')
    for title,offset in [('Kickoff & partner discovery',20),('Registration checkpoint',5),('Production rehearsal',1),('Event day',0)]:
        insert(c,'milestones',event_id=eid,title=title,due_date=max(earliest,start-timedelta(days=offset)).isoformat())
    total=6_000_000 if seed else e['initial_budget']+e['sponsorship_target']
    left=total
    for i,(category,share,flex) in enumerate(CATEGORIES):
        amt=total*share//100 if i<len(CATEGORIES)-1 else left
        left-=amt
        insert(c,'budget',event_id=eid,category=category,planned=amt,adjustable=amt*flex//100)
    flow.log('Ledger','allocate_budget',f'Allocated ₹{total/100:,.2f} across {len(CATEGORIES)} categories. Sponsorship targets remain prospective.')
    matches=prospects(c,e)
    for name,pct,benefits in PACKAGES:
        insert(c,'packages',event_id=eid,name=name,amount=e['sponsorship_target']*pct//100,benefits=benefits)
    top=', '.join(p['name'] for p in matches[:3])
    contexts=[
        ('Magnet','rank_sponsors',dict(event_type=e['type'],goals=e['goals'],matches=[{'name':p['name'],'reason':p['reason']} for p in matches[:3]]),(f'Prioritize {top} according to event fit and recorded relationships.' if top else 'Import sponsor prospects to rank opportunities for this event.')),
        ('Echo','draft_campaign',dict(instruction='Write an editable short announcement.',venue=e['venue'],start_date=e['start_date'],event_type=e['type'],goals=e['goals']),f'Join {e["name"]} on {e["start_date"]} at {e["venue"]}. Bring your team to our {e["type"]} and build alongside other students. Registration is open.'),
    ]
    existing_titles = [entry[0] for entry in PLAN]
    with ThreadPoolExecutor(max_workers=3) as pool:
        tailored = None if seed else pool.submit(intelligence.plan_tasks, e, existing_titles)
        outputs = list(pool.map(lambda item: flow.advice(item[0], item[2], item[3]), contexts))
        extra, mode, detail = tailored.result() if tailored else ([], 'deterministic', '')
    if not seed:
        known = {title.casefold() for title in existing_titles}
        count = 0
        for item in extra:
            title = item.title.strip()
            if len(title) < 8 or title.casefold() in known:
                continue
            due = max(earliest, start-timedelta(days=item.days_before_event)).isoformat()
            ids.append(task(c, eid, title, item.department, due, description=item.description, priority=item.priority))
            known.add(title.casefold())
            count += 1
        flow.log('Atlas','plan_tasks',detail or f'Added {count} tasks tailored to the event brief.',mode)
    for (agent,tool,_,_),answer in zip(contexts,outputs):
        flow.log(agent,tool,answer['text'],answer['mode'])
    insert(c,'marketing',event_id=eid,title='Registration launch announcement',channel='Social',body=outputs[1]['text'],scheduled_date=due_in(e,0))
    flow.log('Relay','work_checklist','Prepared venue, power, check-in and volunteer checklists with accountable owners.')
    f=funding(c,e)
    if not seed and f['shortfall']:
        flow.risk('funding-gap','Sponsorship funding still to secure','Planned expenses exceed currently committed funds.','High',f'₹{f["shortfall"]/100:,.2f} projected shortfall.','Build the sponsor pipeline or review adjustable expenses.',['Ledger','Magnet','Sentinel'])
    flow.log('Sentinel','scan','Checked projected funding, task dependencies and event deadlines.')
    flow.note('Event plan launched',f'{len(ids)} assigned tasks and {len(matches)} matched sponsor profiles.','Atlas')
