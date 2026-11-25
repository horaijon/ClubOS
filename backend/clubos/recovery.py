"""Deterministic detection and proposed changes. Only an organizer can apply a plan."""
import json
from datetime import date, timedelta
from .db import insert,now,rows
from .state import budgets,funding,prospects,task_rows,scoped,Conflict,Missing,Invalid,number,iso,due_in,task

def currency(n):
    return f'₹{n/100:,.0f}' if n%100==0 else f'₹{n/100:,.2f}'

def existing(flow,fingerprint):
    r=flow.c.execute("""SELECT r.id risk_id,a.id approval_id FROM risks r LEFT JOIN approvals a ON a.risk_id=r.id
        WHERE r.event_id=? AND r.fingerprint=? ORDER BY a.rowid DESC LIMIT 1""",(flow.id,fingerprint)).fetchone()
    return dict(r) if r else None

def optimize(flow,source='Budget review',*,requested=0,protected=(),previous=None,withdrawn=None):
    c,e=flow.c,flow.e
    with flow.tool('Sentinel','detect') as step:
        facts=funding(c,e)
        gap=facts['shortfall']
        step.update(summary=f'Projected balance: {currency(facts["balance"])}.',output=facts)
    if not gap and not requested and not withdrawn:
        return dict(message='Funding covers the current plan.',shortfall=0)
    risk=None
    if gap and not requested:
        cached=existing(flow,'funding-gap')
        if cached and cached['approval_id']:
            prior=scoped(c,'approvals',cached['approval_id'],flow.id)
            if prior['status']=='Pending':
                c.execute("UPDATE approvals SET status='Superseded',decided_at=? WHERE id=?",(now(),prior['id']))
        impact=f'{currency(previous)} → {currency(facts["balance"])} projected balance.' if previous is not None else f'{currency(gap)} shortfall.'
        risk=flow.risk('funding-gap','Projected funding shortfall',
            f'{source} leaves {currency(facts["projected_funding"])} secured against {currency(facts["exposure"])} in planned or incurred costs.',
            'High',impact,'Review discretionary allocations and backup sponsor drafts.',['Sentinel','Nexus','Ledger','Magnet','Atlas'])
    target=requested or gap
    actions=[]
    remaining=target
    with flow.tool('Ledger','project_balance',dict(target=target,protected=sorted(protected))) as step:
        for b in sorted(budgets(c,flow.id),key=lambda b:-b['adjustable']):
            if b['category'].lower() in protected:continue
            saving=min(remaining,b['adjustable'],max(0,b['planned']-b['actual']))
            if saving<=0:continue
            actions.append(dict(type='reduce_budget',title=f'Reduce {b["category"].lower()} by {currency(saving)}',
                category_id=b['id'],before=b['planned'],after=b['planned']-saving,saving=saving))
            remaining-=saving
        step.update(summary=f'Found {currency(target-remaining)} in unspent adjustable allocations.',
                    output=dict(savings=target-remaining,balance_after=facts['balance']+target-remaining))
    if remaining and gap and not requested:
        stages={r[0]:r[1] for r in c.execute('SELECT prospect_id,stage FROM sponsors WHERE event_id=?',(flow.id,))}
        with flow.tool('Magnet','rank_sponsors') as step:
            available=[p for p in prospects(c,e) if stages.get(p['id']) in (None,'Shortlisted','Identified')]
            backups=sorted(available,key=lambda p:stages.get(p['id'])!='Shortlisted')[:2]
            step.update(summary=f'Selected {len(backups)} eligible backup partners.',output=dict(partners=[p['name'] for p in backups]))
        for index,partner in enumerate(backups):
            amount=remaining//len(backups)+(index<remaining%len(backups))
            if not amount:continue
            body=f'Hello {partner["name"]} team,\n\n{e["name"]} expects {e["target"]} students. {partner["reason"]} Could we discuss a {currency(amount)} partnership before {e["start_date"]}?\n\n{e["club"]}'
            draft=flow.consult('Magnet','draft_outreach',dict(partner=partner['name'],audience=e['target'],
                event_name=e['name'],theme=e['goals'],amount=amount,start=e['start_date']),body)
            actions.append(dict(type='backup_outreach',title=f'Draft {currency(amount)} request for {partner["name"]}',
                                prospect_id=partner['id'],text=draft['text'],target=amount))
    if (gap and not requested) or withdrawn:
        with flow.tool('Atlas','revise_deliverables',dict(sponsor_id=withdrawn)) as step:
            blocked=[t for t in task_rows(c,flow.id) if withdrawn and t['sponsor_id']==withdrawn and t['status'] not in ('Completed','Blocked')]
            actions.extend(dict(type='pause_deliverable',title=f'Pause {t["title"]}',task_id=t['id'],before=t['status'],after='Blocked') for t in blocked)
            actions.append(dict(type='create_task',title='Review revised vendor orders and delivery scope',
                                department='Operations',due_date=due_in(e,2),priority='High'))
            step.update(summary=f'Prepared {len(blocked)} deliverable changes and a vendor review.',output=dict(tasks=[t['id'] for t in blocked]))
    after=facts['balance']+target-remaining
    summary=f'Projected balance: {currency(facts["balance"])} → {currency(after)}. Proposed savings: {currency(target-remaining)}.'
    if remaining:summary+=f' {currency(remaining)} of the requested adjustment remains uncovered.'
    if any(a['type']=='backup_outreach' for a in actions):summary+=' Backup drafts do not count toward funding.'
    if not actions:return dict(message=summary,text=summary,shortfall=gap,mode='deterministic')
    review=flow.consult('Nexus','review_proposal',dict(balance=facts['balance'],balance_after=after,
        possible_savings=target-remaining,remaining=remaining,protected=sorted(protected)),summary)
    description=summary if review['text']==summary else summary+' '+review['text']
    aid=flow.approval('Review budget reductions' if requested else 'Recover the funding shortfall',description,actions,risk,facts['balance'])
    return dict(message='Recovery plan is ready for review.',text=summary,risk_id=risk,approval_id=aid,shortfall=gap,
                mode=review['mode'],before=facts['balance'],after=after)

def delay(flow,tid,days):
    c=flow.c
    days=number(days,'Delay',1,60)
    root=scoped(c,'tasks',tid,flow.id)
    if root['status']=='Completed': raise Conflict('Choose an unfinished task to delay.')
    fp=f'delay:{tid}:{root["due_date"]}:{days}'
    cached=existing(flow,fp)
    if cached: return dict(message='This delay already has a recovery record.',**cached)
    tasks={t['id']:t for t in task_rows(c,flow.id)}
    queue=[tid]
    affected=set()
    while queue:
        key=queue.pop()
        if key in affected: continue
        affected.add(key)
        queue.extend(t['id'] for t in tasks.values() if key in t['dependencies'] and t['status']!='Completed')
    cap=iso(flow.e['end_date'])
    moves=[]
    for t in tasks.values():
        if t['id'] not in affected: continue
        proposed=min(cap,iso(t['due_date'])+timedelta(days=days)).isoformat()
        if proposed!=t['due_date']: moves.append(dict(type='move_deadline',title=f'{t["title"]} → {proposed}',task_id=t['id'],before=t['due_date'],after=proposed))
    if not moves:
        moves.append(dict(type='create_task',title=f'Coordinate same-day cover for {root["title"]}',department=root['department'],due_date=cap.isoformat(),priority='Critical'))
    impact=f'{len(affected)-1} dependent tasks in scope. Revised deadlines stay within {cap}.'
    risk=flow.risk(fp,'Critical timeline delay',f'{root["title"]} has a reported delay of {days} days.','High',impact,'Review the proposed deadlines and brief affected owners.',['Sentinel','Atlas','Relay'])
    flow.log('Sentinel','detect',impact)
    flow.log('Atlas','trace_dependencies',f'Prepared {len(moves)} changes from the task dependency graph.')
    aid=flow.approval('Approve revised task timeline',impact,moves,risk)
    return dict(message='Revised timeline is ready.',approval_id=aid,risk_id=risk)

def registration(flow):
    c,e=flow.c,flow.e
    n=c.execute('SELECT COUNT(*) FROM participants WHERE event_id=?',(flow.id,)).fetchone()[0]
    expected=e['registration_milestone']
    if n>=expected: return dict(message='Registration milestone is on track.')
    fp=f'registration:{expected}:{e["milestone_date"]}'
    cached=existing(flow,fp)
    if cached:return dict(message='Registration recovery is already tracked.',**cached)
    gap=expected-n
    risk=flow.risk(fp,'Registration milestone missed',f'{n} registered against the {expected}-participant checkpoint.','Medium',f'{gap} additional registrations needed.','Approve a focused campus campaign and assign a marketing owner.',['Sentinel','Echo','Atlas'])
    flow.log('Sentinel','detect',f'Registration count is {gap} below the checkpoint.')
    draft=flow.consult('Echo','draft_campaign',dict(registered=n,target=expected,venue=e['venue'],start=e['start_date']),f'{e["name"]} is welcoming more builders. Join {n} registered participants on {e["start_date"]} at {e["venue"]}. Share the invitation with your campus community.')
    actions=[dict(type='campaign',title='Campus registration drive',channel='WhatsApp',body=draft['text'],scheduled_date=due_in(e,1)),dict(type='create_task',title='Coordinate campus registration drive',department='Marketing',due_date=due_in(e,2),priority='High')]
    aid=flow.approval('Launch registration recovery',f'Prepare an editable campaign and an assigned outreach task for the {gap}-participant gap.',actions,risk)
    return dict(message='Registration recovery queued.',approval_id=aid,risk_id=risk)

def deadline(flow,d):
    fp=f'deliverable:{d["id"]}'
    existing_risk=existing(flow,fp)
    overdue=d['due_date']<date.today().isoformat()
    if existing_risk:
        if overdue:flow.c.execute("UPDATE risks SET severity='High' WHERE id=?",(existing_risk['risk_id'],))
        return existing_risk
    impact=f'{d["owner"]} owns {d["title"]}, due {d["due_date"]}.'
    risk=flow.risk(fp,'Sponsor deliverable deadline',impact,'High' if overdue else 'Medium','Outstanding partner commitment','Collect evidence and review the commitment with the assigned owner.',['Sentinel','Relay','Echo'])
    flow.log('Sentinel','detect',impact)
    flow.log('Relay','schedule_deliverables',f'Flagged the assigned deliverable for {d["owner"]}.')
    flow.note('Sponsor fulfilment reminder',impact,'Relay')
    return dict(risk_id=risk)

def execute(flow,a,defaults=True):
    c,eid=flow.c,flow.id
    kind=a['type']
    if kind=='reduce_budget':
        b=scoped(c,'budget',a['category_id'],eid)
        spent=c.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE category_id=?',(b['id'],)).fetchone()[0]
        if b['planned']!=a['before'] or a['after']<spent:raise Conflict('An allocation changed. Reject this plan and run a new budget review.')
        if a['saving']>b['adjustable']:raise Conflict('The remaining adjustable amount changed.')
        with flow.tool('Ledger','update_budget_allocation',dict(category=b['category'],before=a['before'])) as step:
            c.execute('UPDATE budget SET planned=?,adjustable=adjustable-? WHERE id=?',(a['after'],a['saving'],b['id']))
            step.update(summary=a['title'],output=dict(after=a['after'],saving=a['saving']))
    elif kind=='reallocate_budget':
        source=scoped(c,'budget',a['category_id'],eid)
        destination=scoped(c,'budget',a['destination_id'],eid)
        current=next(b for b in budgets(c,eid) if b['id']==source['id'])
        if (source['planned']!=a['before'] or destination['planned']!=a['destination_before'] or
                a['after']<current['actual'] or a['amount']>source['adjustable']):
            raise Conflict('The allocations changed. Review a new plan.')
        with flow.tool('Ledger','update_budget_allocation',dict(category=source['category'],before=a['before'])) as step:
            c.execute('UPDATE budget SET planned=?,adjustable=adjustable-? WHERE id=?',(a['after'],a['amount'],source['id']))
            c.execute('UPDATE budget SET planned=? WHERE id=?',(a['destination_after'],destination['id']))
            step.update(summary=a['title'],output=dict(after=a['after'],destination_after=a['destination_after']))
    elif kind=='backup_outreach':
        sponsor=c.execute('SELECT id,stage FROM sponsors WHERE event_id=? AND prospect_id=?',(eid,a['prospect_id'])).fetchone()
        if sponsor and sponsor['stage'] not in ('Shortlisted','Identified'):
            raise Conflict('A backup partner progressed in the pipeline. Request a new recovery plan.')
        with flow.tool('Magnet','draft_outreach',dict(prospect_id=a['prospect_id'])) as step:
            if sponsor:
                sid=sponsor['id']
                c.execute("UPDATE sponsors SET stage='Outreach Drafted',draft=? WHERE id=?",(a['text'],sid))
            else:
                sid=insert(c,'sponsors',event_id=eid,prospect_id=a['prospect_id'],stage='Outreach Drafted',draft=a['text'])
            insert(c,'communications',event_id=eid,sponsor_id=sid,kind='outreach',text=a['text'],created_at=now())
            step.update(summary=a['title'],output=dict(sponsor_id=sid))
    elif kind=='create_task':
        with flow.tool('Atlas','create_task',dict(department=a['department'])) as step:
            tid=task(c,eid,a['title'],a['department'],a['due_date'],'Atlas',a.get('priority','Medium'),sponsor_id=a.get('sponsor_id'))
            step.update(summary=a['title'],output=dict(task_id=tid))
    elif kind=='pause_deliverable':
        t=scoped(c,'tasks',a['task_id'],eid)
        if t['status']!=a['before']:raise Conflict('A sponsor deliverable changed. Review an updated plan.')
        with flow.tool('Atlas','revise_deliverables',dict(task_id=t['id'],before=t['status'])) as step:
            c.execute("UPDATE tasks SET status='Blocked' WHERE id=?",(t['id'],))
            step.update(summary=a['title'],output=dict(status='Blocked'))
    elif kind=='move_deadline':
        t=scoped(c,'tasks',a['task_id'],eid)
        if t['due_date']!=a['before'] or t['status']=='Completed':raise Conflict('A task changed after this proposal. Review a new timeline.')
        with flow.tool('Atlas','trace_dependencies',dict(task_id=t['id'],due_date=t['due_date'])) as step:
            c.execute('UPDATE tasks SET due_date=? WHERE id=?',(a['after'],t['id']))
            step.update(summary=a['title'],output=dict(due_date=a['after']))
        flow.note('Task deadline revised',f'{t["title"]} is now due {a["after"]}.','Atlas')
    elif kind=='campaign':
        with flow.tool('Echo','draft_campaign',dict(channel=a['channel'])) as step:
            key=insert(c,'marketing',event_id=eid,title=a['title'],channel=a['channel'],body=a['body'],scheduled_date=a['scheduled_date'])
            step.update(summary=a['title'],output=dict(campaign_id=key))
    elif kind in ('confirm','negotiate','deliverable','payment_task','draft_review'):
        s=scoped(c,'sponsors',a['sponsor_id'],eid)
        if kind in ('confirm','negotiate'):
            if s['stage']!=a['before_stage'] or s['committed']!=a['before_amount']:raise Conflict('Sponsor terms have changed. Review a fresh proposal.')
            if kind=='confirm':
                from .sponsorship import confirm,sponsor
                confirm(flow,sponsor(flow,s["id"]),a['amount'],a.get('due_date'),defaults)
            else: c.execute("UPDATE sponsors SET stage='Negotiating',follow_up_date=NULL WHERE id=?",(s['id'],))
        elif kind in ('deliverable','payment_task'):
            found=c.execute('SELECT id FROM tasks WHERE event_id=? AND sponsor_id=? AND title=?',(eid,s['id'],a['title'])).fetchone()
            if not found:
                agent='Ledger' if kind=='payment_task' else 'Echo' if a['department']=='Marketing' else 'Relay'
                tid=task(c,eid,a['title'],a['department'],a['due_date'],agent,'High',sponsor_id=s['id'])
                if kind=='deliverable':insert(c,'deliverables',event_id=eid,sponsor_id=s['id'],task_id=tid)
        elif kind=='draft_review':
            flow.note('Outreach draft approved','The draft is ready for an organizer to send manually.','Magnet')
    elif kind=='assign':
        t=scoped(c,'tasks',a['task_id'],eid)
        if t['status']=='Completed':raise Conflict('Task was completed before reassignment.')
        c.execute('UPDATE tasks SET owner_id=? WHERE id=?',(a['owner_id'],t['id']))
    else:raise Invalid('Unknown recovery action.')
    flow.note(a['title'],'Applied by organizer approval.')

def decide(flow,p,approve):
    c=flow.c
    record=scoped(c,'approvals',p.get('approval_id'),flow.id)
    if record['status']!='Pending': raise Conflict('This request already has a decision.')
    actions=json.loads(record['actions'])
    if approve:
        if record['basis_balance'] is not None and funding(c,flow.e)['balance']!=record['basis_balance']:
            raise Conflict('The projected balance changed. Reject this plan and request a fresh review.')
        custom={a['sponsor_id'] for a in actions if a['type']=='deliverable'}
        for a in actions:execute(flow,a,a.get('sponsor_id') not in custom)
        if any(a['type']=='move_deadline' for a in actions):
            from .operations import validate_graph
            validate_graph(task_rows(c,flow.id))
        flow.log('Nexus','apply_plan',f'Executed {len(actions)} reviewed actions in one transaction.')
    status='Approved' if approve else 'Rejected'
    c.execute('UPDATE approvals SET status=?,decided_at=? WHERE id=?',(status,now(),record['id']))
    if approve and record['risk_id']:
        r=scoped(c,'risks',record['risk_id'],flow.id)
        residual=(r['fingerprint']=='funding-gap' and funding(c,flow.e)['shortfall']>0) or r['fingerprint'].startswith('registration:')
        c.execute('UPDATE risks SET status=? WHERE id=?',('Monitoring' if residual else 'Resolved',r['id']))
    flow.note(f'{record["title"]} · {status.lower()}',f'{len(actions) if approve else 0} actions executed.')
    return dict(message=f'Plan {status.lower()}.',status=status)

def edit(flow,p):
    record=scoped(flow.c,'approvals',p.get('approval_id'),flow.id)
    if record['status']!='Pending':raise Conflict('Only pending proposals can be edited.')
    if record['basis_balance'] is not None and funding(flow.c,flow.e)['balance']!=record['basis_balance']:
        raise Conflict('The projected balance changed. Request a fresh review.')
    actions=json.loads(record['actions'])
    i=number(p.get('index'),'Action index',0,len(actions)-1)
    a=actions[i]
    if a['type'] in ('reduce_budget','reallocate_budget'):
        b=next(b for b in budgets(flow.c,flow.id) if b['id']==a['category_id'])
        if b['planned']!=a['before']:raise Conflict('The allocation changed. Request a new plan.')
        amount=number(p.get('amount'),'Adjustment',1,min(b['adjustable'],b['planned']-b['actual']))
        a['after']=a['before']-amount
        if a['type']=='reduce_budget':
            a.update(saving=amount,title=f'Reduce {b["category"].lower()} by {currency(amount)}')
        else:
            destination=scoped(flow.c,'budget',a['destination_id'],flow.id)
            a.update(amount=amount,destination_after=a['destination_before']+amount,
                     title=f'Move {currency(amount)} from {b["category"]} to {destination["category"]}')
    elif a['type']=='backup_outreach' or a['type']=='campaign':
        from .state import required
        a['text' if a['type']=='backup_outreach' else 'body']=required(p,'text',16000)
    elif a['type']=='move_deadline':
        value=iso(p.get('date')).isoformat()
        if value>flow.e['end_date']:raise Invalid('Choose a deadline within the event window.')
        a['after']=value
        a['title']=scoped(flow.c,'tasks',a['task_id'],flow.id)['title']+' → '+value
    else:
        raise Invalid('This action has no editable fields.')
    from .db import encode
    description=record['description']
    if a['type']=='reduce_budget':
        current=funding(flow.c,flow.e)['balance']
        savings=sum(x['saving'] for x in actions if x['type']=='reduce_budget')
        description=f'Projected balance: {currency(current)} → {currency(current+savings)}. Proposed savings: {currency(savings)}.'
    flow.c.execute('UPDATE approvals SET actions=?,description=? WHERE id=?',(encode(actions),description,record['id']))
    flow.log('Nexus','review_proposal',f'Updated proposed action: {a["title"]}.')
    return dict(message='Proposal updated.',approval_id=record['id'])
