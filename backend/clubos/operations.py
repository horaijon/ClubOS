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
        c.execute('UPDATE tasks SET title=?,department=?,due_date=?,priority=?,status=?,owner_id=?,description=? WHERE id=?',(title,dept,d.isoformat(),priority,status,owner_id,description,tid))
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
    if status=='Completed':
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
    if update:f.c.execute('UPDATE expenses SET category_id=?,amount=?,description=? WHERE id=?',(cat['id'],amt,desc,old['id']))
    else:insert(f.c,'expenses',event_id=f.id,category_id=cat['id'],amount=amt,description=desc,created_at=now())
    actual=f.c.execute('SELECT SUM(amount) FROM expenses WHERE category_id=?',(cat['id'],)).fetchone()[0]
    if actual>cat['planned']:
        f.risk('overspend:'+cat['id'],f'{cat["category"]} allocation exceeded',desc,'High',recovery.currency(actual-cat['planned'])+' over allocation','Review vendor charges and future discretionary expenses.',['Ledger','Sentinel'])
        f.log('Sentinel','detect',f'{cat["category"]} has exceeded its approved allocation.')
    else:
        f.c.execute("UPDATE risks SET status='Resolved' WHERE event_id=? AND fingerprint=?",(f.id,'overspend:'+cat['id']))
    f.note('Expense updated' if update else 'Expense recorded',desc,'Ledger')
    return dict(message='Expense saved.')

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
    context={'question':q}
    if re.search('proposal|follow.up',lower):
        from .sponsorship import draft
        stage='Contacted' if 'follow' in lower else 'Negotiating'
        r=f.c.execute('SELECT id FROM sponsors WHERE event_id=? ORDER BY (stage=?) DESC,rowid LIMIT 1',(f.id,stage)).fetchone()
        if r:
            result=draft(f,{'sponsor_id':r[0]},'followup' if 'follow' in lower else 'proposal')
            return dict(message='Prepared a draft in Sponsorships.',text=result['text'],mode=result['mode'])
    if 'assign' in lower and 'marketing' in lower:
        selected=[t for t in ts if t['department']=='Marketing' and t['status']!='Completed']
        if selected:
            assignee=owner(f.c,f.id,'Marketing')
            actions=[dict(type='assign',title=f'Reassign {t["title"]}',task_id=t['id'],owner_id=assignee) for t in selected]
            aid=f.approval('Review marketing assignments','Assign open marketing work to the available marketing owner.',actions)
            return dict(message='Assignment review queued.',approval_id=aid,text=f'{len(actions)} marketing assignments are ready for approval.',mode='Deterministic')
    if re.search('budget|expenses|funding|cost|reduc',lower):
        agent='Ledger'
        context['finance']=m
        match=re.search(r'(?:₹|inr\s*|rs\.?\s*)([\d,]+(?:\.\d{1,2})?)',lower)
        if match and re.search('reduc|less|cut',lower):
            from decimal import Decimal
            delta=int(Decimal(match[1].replace(',',''))*100)
            text=f'Reducing secured funding by {recovery.currency(delta)} would put projected funding at {recovery.currency(m["projected_funding"]-delta)}. The resulting balance would be {recovery.currency(m["balance"]-delta)}.'
        else:
            b=budgets(f.c,f.id)
            flexible=sum(min(i['adjustable'],max(0,i['planned']-i['actual'])) for i in b)
            text=f'Secured funding is {recovery.currency(m["projected_funding"])} against {recovery.currency(m["planned"])} planned. The projected balance is {recovery.currency(m["balance"])}. Up to {recovery.currency(flexible)} in unspent allocations is adjustable.'
    elif 'task' in lower or 'overdue' in lower:
        agent='Atlas'
        selected=[t['title'] for t in ts if t['status']!='Completed' and ('overdue' not in lower or t['due_date']<date.today().isoformat())]
        context['tasks']=selected[:15]
        text=f'{len(selected)} matching tasks. '+', '.join(selected[:8]) if selected else 'No overdue tasks are recorded for this event.'
    elif re.search('sponsor|risk|commitment',lower):
        agent='Sentinel'
        risk=rows(f.c,"SELECT title,impact FROM risks WHERE event_id=? AND status<>'Resolved'",(f.id,))
        context['risks']=risk
        text='Open risks: '+('; '.join(r['title']+' — '+r['impact'] for r in risk) or 'none recorded.')
    else:
        agent='Nexus'
        context['finance']=m
        context['open_tasks']=sum(t['status']!='Completed' for t in ts)
        text=f'{f.e["name"]} has {context["open_tasks"]} open tasks and a projected balance of {recovery.currency(m["balance"])}. Open Reports for the current event summary.'
    tool={'Ledger':'project_balance','Atlas':'trace_dependencies','Sentinel':'scan','Nexus':'answer'}[agent]
    out=f.consult(agent,tool,context,text)
    return dict(message='Copilot answered.',**out)
