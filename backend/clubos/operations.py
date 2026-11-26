"""Club operations tools: task validation, registration, content and finance."""
import re
from datetime import date,timedelta
from .db import insert,now,rows
from .state import (Invalid,Conflict,Missing,scoped,required,number,choice,iso,task,task_rows,
                    TASK_STATES,PRIORITIES,team,funding,budgets,owner,due_in,prospects)
from . import recovery

def validate_graph(tasks):
    due={t['id']:t['due_date'] for t in tasks}
    deps={t['id']:set(t['dependencies']) for t in tasks}
    for k,parents in deps.items():
        if any(parent not in due for parent in parents):raise Invalid('A dependency is outside this event.')
        if any(due[parent]>due[k] for parent in parents):raise Invalid('Schedule dependent tasks on or after their prerequisite.')
    # Remove nodes with no prerequisites until only a cycle could remain.
    while deps:
        ready={k for k,p in deps.items() if not p}
        if not ready:raise Invalid('Task dependencies must not form a cycle.')
        deps={k:p-ready for k,p in deps.items() if k not in ready}

def edit_task(f,p,update):
    c=f.c
    old=scoped(c,'tasks',p.get('task_id'),f.id) if update else {}
    fields={**old,**p}
    title=required(fields,'title',500)
    dept=required({'department':fields.get('department','Planning')},'department',100)
    d=iso(fields.get('due_date',f.e['start_date']))
    if d>iso(f.e['end_date']):raise Invalid('Task deadline falls after the event ends.')
    priority=choice(fields.get('priority','Medium'),PRIORITIES,'priority')
    status=choice(fields.get('status','To Do'),TASK_STATES,'task status')
    owner_id=fields.get('owner_id') or owner(c,f.id,dept)
    if not isinstance(owner_id, str) or owner_id not in {m['id'] for m in team(c,f.id)}: raise Invalid('Select a member from this event team.')
    description=fields.get('description','')
    if not isinstance(description,str) or len(description)>4000:raise Invalid('Task notes must be under 4,000 characters.')
    if update:
        tid=old['id']
        completed=(old['completed_at'] or now()) if status=='Completed' else None
        c.execute('UPDATE tasks SET title=?,department=?,due_date=?,priority=?,status=?,owner_id=?,description=?,completed_at=? WHERE id=?',
                  (title,dept,d.isoformat(),priority,status,owner_id,description,completed,tid))
    else:
        tid=task(c,f.id,title,dept,d.isoformat(),'Organizer',priority,status,description,owner_id=owner_id)
    if 'dependencies' in p:
        deps=p['dependencies']
        if not isinstance(deps,list) or len(deps)>100 or not all(isinstance(x,str) for x in deps): raise Invalid('Use a list of prerequisite task IDs.')
        c.execute('DELETE FROM dependencies WHERE task_id=?',(tid,))
        for dep in set(deps):
            if dep==tid:raise Invalid('A task cannot depend on itself.')
            scoped(c,'tasks',dep,f.id)
            c.execute('INSERT INTO dependencies VALUES (?,?)',(tid,dep))
    validate_graph(task_rows(c,f.id))
    if status=='Completed' or d>=date.today():
        c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint=?", (f.id,'overdue:'+tid))
    f.note('Task updated' if update else 'Task created',title,'Atlas')
    return dict(message='Task saved.',task_id=tid)

def participant(f,p,duplicate_ok=False):
    name=required(p,'name',120)
    email=required(p,'email',254).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email):raise Invalid('Enter a valid participant email address.')
    if f.c.execute('SELECT 1 FROM participants WHERE event_id=? AND email=?',(f.id,email)).fetchone():
        if duplicate_ok:return None
        raise Conflict('This participant is already registered.')
    return insert(f.c,'participants',event_id=f.id,name=name,email=email,created_at=now())

def import_rows(p):
    ds=p.get('rows')
    if not isinstance(ds,list) or not 1<=len(ds)<=2000 or not all(isinstance(d,dict) for d in ds):raise Invalid('Import 1–2,000 CSV rows with named columns.')
    return ds

def register(f,p,kind):
    if kind=='check_in':
        who=scoped(f.c,'participants',p.get('participant_id'),f.id)
        f.c.execute('UPDATE participants SET checked_in=1 WHERE id=?',(who['id'],))
        f.note('Participant checked in',who['name'],'Relay')
        return dict(message='Attendance recorded.')
    items=import_rows(p) if kind=='import_participants' else [p]
    n=sum(participant(f,v,kind=='import_participants') is not None for v in items)
    f.log('Relay','register',f'Registered {n} participants.')
    f.note('Registration updated',f'{n} participant records added.','Relay')
    return dict(message=f'{n} participants registered.',count=n)

def expense(f,p,update):
    old=scoped(f.c,'expenses',p.get('expense_id'),f.id) if update else {}
    fields={**old,**p}
    cat=scoped(f.c,'budget',fields.get('category_id'),f.id)
    amt=number(fields.get('amount'),'Expense',1)
    desc=required(fields,'description',1000)
    before=funding(f.c,f.e)
    with f.tool('Ledger','record_expense',dict(category=cat['category'],amount=amt)) as step:
        if update:f.c.execute('UPDATE expenses SET category_id=?,amount=?,description=? WHERE id=?',(cat['id'],amt,desc,old['id']))
        else:insert(f.c,'expenses',event_id=f.id,category_id=cat['id'],amount=amt,description=desc,created_at=now())
        actual=f.c.execute('SELECT SUM(amount) FROM expenses WHERE category_id=?',(cat['id'],)).fetchone()[0]
        step.update(summary=f'Recorded {recovery.currency(amt)} in {cat["category"]}.',output=dict(actual=actual))
    if actual>cat['planned']:
        f.risk('overspend:'+cat['id'],f'{cat["category"]} allocation exceeded',desc,'High',recovery.currency(actual-cat['planned'])+' over allocation','Review vendor charges and future discretionary expenses.',['Ledger','Sentinel'])
        f.log('Sentinel','detect',f'{cat["category"]} has exceeded its approved allocation.')
    else:
        f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint=?",(f.id,'overspend:'+cat['id']))
    f.note('Expense updated' if update else 'Expense recorded',desc,'Ledger')
    after=funding(f.c,f.e)
    if after['shortfall']>before['shortfall']:
        return recovery.optimize(f,'Expense recorded',previous=before['balance'])
    if not after['shortfall']:
        f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint='funding-gap'",(f.id,))
    return dict(message='Expense saved.')

def delete_expense(f,p):
    old=scoped(f.c,'expenses',p.get('expense_id'),f.id)
    cat=scoped(f.c,'budget',old['category_id'],f.id)
    with f.tool('Ledger','record_expense',dict(category=cat['category'],amount=old['amount'])) as step:
        f.c.execute('DELETE FROM expenses WHERE id=?',(old['id'],))
        actual=f.c.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE category_id=?',(cat['id'],)).fetchone()[0]
        step.update(summary=f'Deleted {recovery.currency(old["amount"])} from {cat["category"]}.',output=dict(actual=actual))
    if actual<=cat['planned']:
        f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint=?",(f.id,'overspend:'+cat['id']))
    if not funding(f.c,f.e)['shortfall']:
        f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint='funding-gap'",(f.id,))
    f.note('Expense deleted',old['description'],'Ledger')
    return dict(message='Expense deleted.')

def campaign(f,p,generate):
    if generate:
        title=required({'title':p.get('title') or 'Campus event announcement'},'title',300)
        channel=required({'channel':p.get('channel') or 'Social'},'channel',60)
        a=f.consult('Echo','draft_campaign',dict(channel=channel,audience=f.e['target'],date=f.e['start_date'],event_type=f.e['type']),f'Join {f.e["name"]} at {f.e["venue"]} on {f.e["start_date"]}. Connect with students, build something new and share your work. Register with {f.e["club"]}.')
        body=a['text']
        mode=a['mode']
    else:
        mode='Organizer'
        title=required(p,'title',300)
        body=required(p,'body',12000)
        channel=required(p,'channel',60)
    day=iso(p.get('scheduled_date') or due_in(f.e,0)).isoformat()
    if p.get('id'):
        scoped(f.c,'marketing',p['id'],f.id)
        f.c.execute('UPDATE marketing SET title=?,channel=?,body=?,scheduled_date=? WHERE id=?',(title,channel,body,day,p['id']))
        key=p['id']
    else:key=insert(f.c,'marketing',event_id=f.id,title=title,channel=channel,body=body,scheduled_date=day)
    f.note('Campaign draft saved',title,'Echo')
    return dict(message='Marketing draft saved.',id=key,text=body,mode=mode)

def imports(f,p):
    count=0
    for v in import_rows(p):
        name=required(v,'name',160)
        if f.c.execute('SELECT 1 FROM profiles WHERE name=? COLLATE NOCASE AND (event_scope IS NULL OR event_scope=?)',(name,f.id)).fetchone():continue
        industry=required(v,'industry',120)
        desc=v.get('description') or f'Organizer-provided {industry} profile.'
        if not isinstance(desc,str) or len(desc)>1500:raise Invalid('Sponsor description is too long.')
        insert(f.c,'profiles',event_scope=f.id,name=name,industry=industry,description=desc,tags=industry.lower(),sponsorship_type='Unspecified')
        count+=1
    f.note('Sponsor profiles imported',f'{count} added to discovery.','Magnet')
    return dict(message=f'{count} prospects imported.',count=count)

def copilot(f,p):
    q=required(p,'question',1200)
    lower=q.lower()
    m=funding(f.c,f.e)
    ts=task_rows(f.c,f.id)
    f.log('Nexus','query_event_state',f'Loaded event funding, open work and risks for {f.e["name"]}.')
    context={'question':q}
    extension=re.search(r'extend (?:the )?registration deadline by (\d+) days?',lower)
    if extension:
        from .registration import form_for_event, publish
        form=form_for_event(f.c,f.id)
        if not form:raise Conflict('Publish the registration form first.')
        old=iso(form['deadline'])
        new=old+timedelta(days=number(int(extension[1]),'Days',1,90))
        if new>iso(f.e['start_date']):raise Invalid('Registration must close by the event start date.')
        with f.tool('FormFlow','publish_registration',{'previous_deadline':old.isoformat()}) as step:
            publish(f.c,f.id,new.isoformat(),[field['key'] for field in form['fields']])
            f.c.execute("UPDATE events SET milestone_date=? WHERE id=?",(new.isoformat(),f.id))
            for table in ('tasks','milestones'):
                f.c.execute(f"UPDATE {table} SET due_date=? WHERE event_id=? AND title='Close registrations and confirm roster'",
                            (new.isoformat(),f.id))
            f.c.execute("UPDATE tasks SET due_date=MAX(due_date,?) WHERE event_id=? AND title='Brief volunteers and confirm vendors'",
                        (new.isoformat(),f.id))
            f.c.execute("UPDATE milestones SET due_date=MAX(due_date,?) WHERE event_id=? AND title='Brief volunteers and confirm vendors'",
                        (new.isoformat(),f.id))
            step.update(summary=f'Extended registration to {new}.',output={'deadline':new.isoformat()})
        text=f'Registration now closes on {new}.'
        if 'sponsor' in lower:
            from .sponsorship import add_prospect,draft
            used={row[0] for row in f.c.execute('SELECT prospect_id FROM sponsors WHERE event_id=?',(f.id,))}
            candidates=[entry for entry in prospects(f.c,f.e) if entry['id'] not in used]
            if 'food' in lower:
                candidates.sort(key=lambda entry:not re.search('food|beverage|coffee|snack|cater',entry['industry'],re.I))
            if candidates:
                partner=candidates[0]
                selected=add_prospect(f,{'prospect_id':partner['id']})
                draft(f,selected,'outreach')
                text+=f' Magnet drafted a pitch for {partner["name"]}.'
        return dict(message=text,text=text)
    if re.search(r'follow.up',lower):
        from .sponsorship import draft
        selected=rows(f.c,"""SELECT s.id,p.name FROM sponsors s JOIN profiles p ON p.id=s.prospect_id
            WHERE s.event_id=? AND s.stage='Contacted' AND NOT EXISTS
            (SELECT 1 FROM communications c WHERE c.sponsor_id=s.id AND c.kind='response') ORDER BY s.rowid""",(f.id,))
        if not selected:return dict(message='No unanswered contacted sponsors.',text='No contacted sponsors are awaiting a reply.')
        if 'all' not in lower:selected=selected[:1]
        actions=[]
        for sponsor in selected:
            result=draft(f,{'sponsor_id':sponsor['id']},'followup')
            actions.append(dict(type='draft_review',title=f'Review follow-up to {sponsor["name"]}',sponsor_id=sponsor['id'],text=result['text']))
        aid=f.approval('Review sponsor follow-ups','Review the drafts before sending them to the partners.',actions)
        return dict(message='Follow-ups queued for review.',approval_id=aid,
                    text=f'Prepared {len(actions)} follow-up drafts for '+', '.join(s['name'] for s in selected)+'.',mode=result['mode'])
    if 'proposal' in lower:
        from .sponsorship import draft
        r=f.c.execute("SELECT id FROM sponsors WHERE event_id=? AND stage IN ('Negotiating','Shortlisted') ORDER BY (stage='Negotiating') DESC,rowid LIMIT 1",(f.id,)).fetchone()
        if r:
            result=draft(f,{'sponsor_id':r[0]},'proposal')
            return dict(message='Prepared a draft in Sponsorships.',text=result['text'],mode=result['mode'])
    if 'assign' in lower and 'marketing' in lower:
        selected=[t for t in ts if t['department']=='Marketing' and t['status']!='Completed']
        if selected:
            assignee=owner(f.c,f.id,'Marketing')
            actions=[dict(type='assign',title=f'Reassign {t["title"]}',task_id=t['id'],owner_id=assignee) for t in selected]
            aid=f.approval('Review marketing assignments','Assign open marketing work to the available marketing owner.',actions)
            return dict(message='Assignment review queued.',approval_id=aid,text=f'{len(actions)} marketing assignments are ready for approval.',mode='Deterministic')
    if re.search(r'budget|expenses|funding|cost|reduc|\bcut\b|rebalanc',lower):
        agent='Ledger'
        context['finance']=m
        match=re.search(r'(?:₹|inr\s*|rs\.?\s*|\bcut\s+)([\d,]+(?:\.\d{1,2})?)\s*(k\b|lakh\b)?',lower)
        if match and re.search('reduc|less|cut|rebalanc|sav',lower):
            from decimal import Decimal
            delta=int(Decimal(match[1].replace(',',''))*100*{None:1,'k':1000,'lakh':100_000}[match[2]])
            protected={b['category'].lower() for b in budgets(f.c,f.id)
                       if 'without' in lower and b['category'].lower() in lower.split('without',1)[1]}
            return recovery.optimize(f,'Copilot budget review',requested=number(delta,'Savings target',1),protected=protected)
        else:
            b=budgets(f.c,f.id)
            flexible=sum(min(i['adjustable'],max(0,i['planned']-i['actual'])) for i in b)
            text=f'Secured funding is {recovery.currency(m["projected_funding"])} against {recovery.currency(m["planned"])} planned. The projected balance is {recovery.currency(m["balance"])}. Up to {recovery.currency(flexible)} in unspent allocations is adjustable.'
    elif 'task' in lower or 'overdue' in lower:
        agent='Atlas'
        selected=[t['title'] for t in ts if t['status']!='Completed' and ('overdue' not in lower or t['due_date']<date.today().isoformat())]
        context['tasks']=selected[:15]
        text=f'{len(selected)} matching tasks. '+', '.join(selected[:8]) if selected else 'No overdue tasks are recorded for this event.'
    elif re.search('sponsor|risk|commitment|blocker',lower):
        agent='Sentinel'
        risk=rows(f.c,"SELECT title,impact FROM risks WHERE event_id=? AND status NOT IN ('Resolved','Closed') ORDER BY CASE severity WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,created_at DESC",(f.id,))
        context['risks']=risk
        text='Open risks: '+('; '.join(r['title']+' — '+r['impact'] for r in risk) or 'none recorded.')
    else:
        agent='Nexus'
        context['finance']=m
        context['open_tasks']=sum(t['status']!='Completed' for t in ts)
        text=f'{f.e["name"]} has {context["open_tasks"]} open tasks and a projected balance of {recovery.currency(m["balance"])}. See Command Center for the current event summary.'
    tool={'Ledger':'project_balance','Atlas':'trace_dependencies','Sentinel':'scan','Nexus':'answer'}[agent]
    out=f.consult(agent,tool,context,text)
    return dict(message='Copilot answered.',**out)
