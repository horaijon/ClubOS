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

def optimize(flow,source='Budget review'):
    c,e=flow.c,flow.e
    facts=funding(c,e)
    gap=facts['shortfall']
    if gap==0:
        flow.log('Ledger','project_balance',f'Projected surplus of {currency(facts["balance"])}. No deficit to recover.')
        return dict(message='Funding covers the current plan.',shortfall=0)
    cached=existing(flow,'funding-gap')
    if cached and cached['approval_id']:
        prior=scoped(c,'approvals',cached['approval_id'],flow.id)
        if prior['status']=='Pending': return dict(message='The funding plan is already awaiting review.',**cached,shortfall=gap)
    risk=flow.risk('funding-gap','Projected funding shortfall',f'{source} leaves {currency(facts["projected_funding"])} secured against {currency(facts["planned"])} of planned expenses.','High',f'{currency(gap)} shortfall','Review discretionary allocations, contact a backup partner and verify the revised plan.',['Sentinel','Nexus','Ledger','Magnet','Atlas','Relay'])
    flow.log('Sentinel','detect',f'Detected a {currency(gap)} projected shortfall.')
    flow.log('Nexus','dispatch','Dispatched finance, sponsorship, planning and operations reviews.')
    actions=[]
    remaining=gap
    for b in sorted(budgets(c,flow.id),key=lambda b:-b['adjustable']):
        saving=min(remaining,b['adjustable'],max(0,b['planned']-b['actual']))
        if saving<=0: continue
        actions.append(dict(type='reduce_budget',title=f'Reduce {b["category"].lower()} by {currency(saving)}',category_id=b['id'],before=b['planned'],after=b['planned']-saving,saving=saving))
        remaining-=saving
    flow.log('Ledger','project_balance',f'Identified {currency(gap-remaining)} in unspent adjustable allocations. Remaining funding need: {currency(remaining)}.')
    used={r[0] for r in c.execute('SELECT prospect_id FROM sponsors WHERE event_id=?',(flow.id,))}
    backup=next((p for p in prospects(c,e) if p['id'] not in used),None)
    if backup and remaining:
        body=f'Hello {backup["name"]} team,\n\nWe are organizing {e["name"]} for {e["target"]} students. {backup["reason"]} Would you consider a partnership of {currency(remaining)}? We would welcome a conversation about benefits that suit your team.\n\n{e["club"]}'
        actions.append(dict(type='backup_outreach',title=f'Draft {currency(remaining)} backup request for {backup["name"]}',prospect_id=backup['id'],text=body,target=remaining))
    flow.log('Magnet','rank_sponsors',f'{backup["name"]} is the highest-ranked available backup.' if backup else 'No new backup profiles remain.')
    tasks=[t for t in task_rows(c,flow.id) if t['status']!='Completed' and t['department'] in ('Finance','Operations')]
    actions.append(dict(type='create_task',title='Review revised vendor orders and delivery scope',department='Operations',due_date=due_in(e,2),priority='High'))
    flow.log('Atlas','trace_dependencies',f'Reviewed {len(tasks)} open finance and operations tasks for the revised budget.')
    flow.log('Relay','work_checklist','Prepared a vendor review task for the operations team.')
    advice=flow.consult('Nexus','consolidate',{'secured_paise':facts['projected_funding'],'shortfall_paise':gap,'possible_savings_paise':gap-remaining,'remaining_gap_paise':remaining},f'Approve {currency(gap-remaining)} in allocation reductions. {currency(remaining)} would still need funding. Backup outreach creates a draft only.')
    aid=flow.approval('Recover the funding shortfall',advice['text'],actions,risk)
    return dict(message='Recovery plan is ready for review.',risk_id=risk,approval_id=aid,shortfall=gap)

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

def execute(flow,a):
    c,eid=flow.c,flow.id
    kind=a['type']
    if kind=='reduce_budget':
        b=scoped(c,'budget',a['category_id'],eid)
        spent=c.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE category_id=?',(b['id'],)).fetchone()[0]
        if b['planned']!=a['before'] or a['after']<spent:raise Conflict('An allocation changed. Reject this plan and run a new budget review.')
        c.execute('UPDATE budget SET planned=?,adjustable=MAX(0,adjustable-?) WHERE id=?',(a['after'],a['saving'],b['id']))
    elif kind=='backup_outreach':
        if c.execute('SELECT 1 FROM sponsors WHERE event_id=? AND prospect_id=?',(eid,a['prospect_id'])).fetchone():
            raise Conflict('Backup partner is already in the pipeline. Request a new recovery plan.')
        insert(c,'sponsors',event_id=eid,prospect_id=a['prospect_id'],stage='Outreach Drafted',draft=a['text'])
    elif kind=='create_task':
        task(c,eid,a['title'],a['department'],a['due_date'],'Atlas',a.get('priority','Medium'),sponsor_id=a.get('sponsor_id'))
    elif kind=='move_deadline':
        t=scoped(c,'tasks',a['task_id'],eid)
        if t['due_date']!=a['before'] or t['status']=='Completed':raise Conflict('A task changed after this proposal. Review a new timeline.')
        c.execute('UPDATE tasks SET due_date=? WHERE id=?',(a['after'],t['id']))
        flow.note('Task deadline revised',f'{t["title"]} is now due {a["after"]}.','Atlas')
    elif kind=='campaign':
        insert(c,'marketing',event_id=eid,title=a['title'],channel=a['channel'],body=a['body'],scheduled_date=a['scheduled_date'])
    elif kind in ('confirm','negotiate','deliverable','payment_task','draft_review'):
        s=scoped(c,'sponsors',a['sponsor_id'],eid)
        if kind in ('confirm','negotiate'):
            if s['stage']!=a['before_stage'] or s['committed']!=a['before_amount']:raise Conflict('Sponsor terms have changed. Review a fresh proposal.')
            if kind=='confirm':
                paid=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE sponsor_id=?',(s['id'],)).fetchone()[0]
                if a['amount']<paid: raise Conflict('The agreement cannot reduce a commitment below recorded payments.')
                c.execute("UPDATE sponsors SET stage='Confirmed',committed=?,follow_up_date=NULL WHERE id=?",(a['amount'],s['id']))
                flow.log('Ledger','review_terms',f'Approved commitment of {currency(a["amount"])}. No receipt recorded.')
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
        for a in actions: execute(flow,a)
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
