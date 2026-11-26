"""Nexus planning tools and their role-specific execution records."""
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from . import intelligence
from .db import encode, insert, now
from .state import iso, due_in, task, prospects, team, funding

TOOLS = {
    'FormFlow':{'publish_registration','receive_registration'},
    'OpsLedger':{'build_event_plan'},
    'Nexus':{'dispatch','consolidate','answer','apply_plan','query_event_state','review_proposal','propose_approval_action','decode_brief'},
    'Atlas':{'plan_tasks','trace_dependencies','reassign','create_task','revise_deliverables'},
    'Ledger':{'allocate_budget','project_balance','review_terms','record_payment','create_sponsor_receivable','update_budget_allocation','record_expense'},
    'Magnet':{'rank_sponsors','draft_outreach','extract_terms','propose_package','follow_up','send_email'},
    'Echo':{'draft_campaign','plan_branding'},
    'Relay':{'work_checklist','schedule_deliverables','register'},
    'Sentinel':{'scan','detect','verify','raise_risk_alert'},
    'Canvas':{'generate_poster','revise_poster'},
}

class Flow:
    def __init__(self,c,event,wid,trigger,local=False,execution=None):
        self.c,self.e,self.wid,self.trigger,self.local=c,event,wid,trigger,local
        self.id=event['id']
        self.execution=execution
        self.provider_detail=""

    def note(self,title,description='',agent='Nexus'):
        return insert(self.c,'activity',event_id=self.id,title=title,description=description,agent=agent,created_at=now())

    def advice(self,agent,context,fallback):
        if self.local:
            return dict(text=fallback,mode='deterministic')
        if self.provider_detail:
            return dict(text=fallback,mode='Deterministic fallback',detail=self.provider_detail)
        try:
            answer=intelligence.advise(agent,dict(event=self.e['name'],**context),fallback)
            if answer['mode']=='Deterministic fallback':
                self.provider_detail=answer['detail']
            return answer
        except Exception:
            self.provider_detail='The provider could not complete the request.'
            return dict(text=fallback,mode='Deterministic fallback',detail=self.provider_detail)

    def log(self,agent,tool,summary,mode='deterministic',status='Completed',journal=True):
        if tool not in TOOLS[agent]:
            raise RuntimeError('Agent tool permission mismatch')
        insert(self.c,'runs',event_id=self.id,workflow_id=self.wid,agent=agent,trigger=self.trigger,tool=tool,summary=summary,mode=mode,status=status,created_at=now())
        if journal and self.execution:
            with self.execution.step(agent,tool) as step:
                step.update(summary=summary,output={"mode":mode},status=status)
        return summary

    @contextmanager
    def tool(self,agent,tool,inputs=None):
        if tool not in TOOLS[agent]:
            raise RuntimeError('Agent tool permission mismatch')
        capture=self.execution.step(agent,tool,inputs) if self.execution else nullcontext({})
        with capture as step:
            yield step
            self.log(agent,tool,step["summary"],step.get("mode","deterministic"),step.get("status","Completed"),journal=False)

    def consult(self,agent,tool,context,fallback):
        with self.tool(agent,tool,{"context_fields":sorted(context)}) as step:
            answer=self.advice(agent,context,fallback)
            summary=f'{agent} prepared {tool.replace("_"," ")} using current event context.'
            step.update(summary=summary,mode=answer['mode'],output={"mode":answer['mode'],"text":answer['text']})
        return answer

    def risk(self,fingerprint,title,description,severity,impact,recommendation,agents):
        with self.tool('Sentinel','raise_risk_alert',dict(fingerprint=fingerprint,severity=severity)) as step:
            existing=self.c.execute('SELECT id FROM risks WHERE event_id=? AND fingerprint=?',(self.id,fingerprint)).fetchone()
            values=(title,description,severity,impact,recommendation,encode(agents))
            if existing:
                key=existing[0]
                self.c.execute("UPDATE risks SET title=?,description=?,severity=?,impact=?,recommendation=?,agents=?,status='Open' WHERE id=?",(*values,key))
            else:
                key=insert(self.c,'risks',event_id=self.id,fingerprint=fingerprint,title=title,description=description,
                           severity=severity,source=self.trigger,impact=impact,recommendation=recommendation,agents=encode(agents),created_at=now())
            step.update(summary=title,output=dict(risk_id=key,impact=impact))
        return key

    def approval(self,title,description,actions,risk_id=None,basis_balance=None):
        with self.tool('Nexus','propose_approval_action',dict(action_types=[action['type'] for action in actions])) as step:
            key=insert(self.c,'approvals',event_id=self.id,workflow_id=self.wid,risk_id=risk_id,title=title,description=description,
                       actions=encode(actions),created_at=now(),basis_balance=basis_balance)
            step.update(summary=f'Queued {len(actions)} proposed actions for organizer review.',
                        output=dict(approval_id=key,actions=len(actions)),status='Awaiting Approval')
        self.note(title,description)
        if self.execution:
            self.execution.emit('proposal_created',title,outputs={'approval_id':key,'actions':len(actions)},status='Awaiting Approval')
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
    with flow.tool('Atlas','plan_tasks',{'start_date':e['start_date'],'team_size':len(team(c,eid))}) as step:
        for i,(title,dept,offset,priority,dep) in enumerate(PLAN):
            day=max(earliest,start-timedelta(days=offset)).isoformat()
            status=('Completed' if i<10 else 'In Progress' if i<17 else 'To Do') if seed else 'To Do'
            k=task(c,eid,title,dept,day,priority=priority,status=status,description=f'{dept} lead verifies completion and records the outcome for {e["name"]}.')
            ids.append(k)
            if dep is not None: c.execute('INSERT INTO dependencies VALUES (?,?)',(k,ids[dep]))
        for title,offset in [('Kickoff & partner discovery',20),('Registration checkpoint',5),('Production rehearsal',1),('Event day',0)]:
            insert(c,'milestones',event_id=eid,title=title,due_date=max(earliest,start-timedelta(days=offset)).isoformat())
        step.update(summary=f'Assigned {len(ids)} dependency-linked tasks.',output={'tasks_created':len(ids)})
    total=6_000_000 if seed and eid=="codestorm-2026" else e['initial_budget']+e['sponsorship_target']
    with flow.tool('Ledger','allocate_budget',{'budget_paise':total}) as step:
        left=total
        for i,(category,share,flex) in enumerate(CATEGORIES):
            amt=total*share//100 if i<len(CATEGORIES)-1 else left
            left-=amt
            insert(c,'budget',event_id=eid,category=category,planned=amt,adjustable=amt*flex//100)
        step.update(summary=f'Allocated ₹{total/100:,.2f} across {len(CATEGORIES)} categories.',output={'allocated_paise':total,'categories':len(CATEGORIES)})
    matches=prospects(c,e)
    for name,pct,benefits in PACKAGES:
        insert(c,'packages',event_id=eid,name=name,amount=e['sponsorship_target']*pct//100,benefits=benefits)
    top=', '.join(p['name'] for p in matches[:3])
    contexts=[
        ('Magnet','rank_sponsors',dict(event_type=e['type'],goals=e['goals'],matches=[{'name':p['name'],'reason':p['reason']} for p in matches[:3]]),(f'Prioritize {top} according to event fit and recorded relationships.' if top else 'Import sponsor prospects to rank opportunities for this event.')),
        ('Echo','draft_campaign',dict(instruction='Write an editable short announcement.',venue=e['venue'],start_date=e['start_date'],event_type=e['type'],goals=e['goals']),f'Join {e["name"]} on {e["start_date"]} at {e["venue"]}. Bring your team to our {e["type"]} and build alongside other students. Registration is open.'),
    ]
    existing_titles = [entry[0] for entry in PLAN]
    if not seed:
        with flow.tool('Atlas','plan_tasks',dict(event_type=e['type'])) as step:
            extra,mode,detail=intelligence.plan_tasks(e,existing_titles)
            if mode=='Deterministic fallback':
                flow.provider_detail=detail
            known={title.casefold() for title in existing_titles}
            original=len(ids)
            for item in extra:
                title=item.title.strip()
                if len(title)<8 or title.casefold() in known:continue
                due=max(earliest,start-timedelta(days=item.days_before_event)).isoformat()
                ids.append(task(c,eid,title,item.department,due,description=item.description,priority=item.priority))
                known.add(title.casefold())
            step.update(summary=detail or f'Added {len(ids)-original} tasks tailored to the event brief.',
                        mode=mode,output=dict(tasks_added=len(ids)-original))
    outputs=[flow.consult(agent,tool,context,fallback) for agent,tool,context,fallback in contexts]
    if not seed and matches:
        from . import sponsorship
        for match in matches[:2]:
            partner=sponsorship.add_prospect(flow,{'prospect_id':match['id']})
            c.execute("UPDATE sponsors SET stage='Shortlisted' WHERE id=?",(partner['sponsor_id'],))
            sponsorship.draft(flow,{'sponsor_id':partner['sponsor_id']},'proposal')
    insert(c,'marketing',event_id=eid,title='Registration launch announcement',channel='Social',body=outputs[1]['text'],scheduled_date=due_in(e,0))
    flow.log('Relay','work_checklist','Prepared venue, power, check-in and volunteer checklists with accountable owners.')
    f=funding(c,e)
    if not seed and f['shortfall']:
        flow.risk('funding-gap','Sponsorship funding still to secure','Planned expenses exceed currently committed funds.','High',f'₹{f["shortfall"]/100:,.2f} projected shortfall.','Build the sponsor pipeline or review adjustable expenses.',['Ledger','Magnet','Sentinel'])
    flow.log('Sentinel','scan','Checked projected funding, task dependencies and event deadlines.')
    try:
        from . import poster_studio
        poster_studio.create_poster_record(c, eid, use_ai_image=False)
    except Exception:
        pass
    flow.note('Event plan launched',f'{len(ids)} assigned tasks and {len(matches)} matched sponsor profiles.','Atlas')
