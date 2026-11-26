"""Turn an organizer brief into a bounded registration and event plan."""
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import intelligence, db
from .registration import publish
from .state import due_in, iso, prospects, task

class BriefPlan(BaseModel):
    registration_deadline: date
    submission_deadline: date
    estimated_budget: int = Field(ge=0,le=100_000_000_000)
    fields: list[Literal['team_name','team_size','track','github','college','diet','experience','accessibility']] = Field(max_length=8)
    team_rules: str = Field(default='',max_length=400)

def interpret(data,brief,budget):
    start,end=iso(data['start_date']),iso(data['end_date'])
    money=re.search(r'(?:total budget|estimated budget|budget)\s*(?:is|of|:)?\s*(?:₹|INR|Rs\.?)\s*([\d,]+(?:\.\d{1,2})?)\s*(k\b)?',brief,re.I)
    estimate=budget
    if estimate is None and money:
        estimate=min(100_000_000_000,int(Decimal(money[1].replace(',',''))*100*(1000 if money[2] else 1)))
    def deadline(pattern,default):
        month=r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
        match=re.search(pattern+r'[^.;\n]{0,30}?(20\d\d-\d\d-\d\d|'+month+r'\s+\d{1,2}|\d{1,2}\s+'+month+r')',brief,re.I)
        if not match:return default
        try:
            value=match[1].split()
            if len(value)==1:return date.fromisoformat(value[0])
            day,mon=value if value[0].isdigit() else value[::-1]
            from datetime import datetime
            return date(start.year,datetime.strptime(mon[:3],'%b').month,int(day))
        except ValueError:return default
    fields=[key for key,pattern in {'team_name':r'\bteams?\b','team_size':r'\bteams?\b','track':r'\btracks?\b',
                                   'github':r'github','college':r'campus|college','diet':r'diet|meal|food'}.items() if re.search(pattern,brief,re.I)]
    fallback=BriefPlan(registration_deadline=min(start,max(date.today(),deadline(r'registration (?:closes|deadline)',start-timedelta(days=3)))),
                       submission_deadline=max(start,min(end,deadline(r'(?:project )?submission(?: deadline| closes| is)?',end))),
                       estimated_budget=estimate if estimate is not None else max(data['initial_budget'],data['target']*30_000),
                       fields=fields,team_rules=(re.search(r'teams? of [^.;,]{1,70}',brief,re.I) or [''])[0])
    decoded,mode,detail=intelligence.structured('Nexus',{'task':'Extract event registration and submission deadlines, team rules, registration fields and total estimated budget in integer paise. Use dates consistent with event dates.','event':data,'brief':brief,'defaults':fallback.model_dump(mode='json')},BriefPlan,fallback)
    decoded.registration_deadline=min(start,max(min(date.today(),start),decoded.registration_deadline))
    decoded.submission_deadline=max(start,min(end,decoded.submission_deadline))
    decoded.estimated_budget=max(data['initial_budget'],budget if budget is not None else decoded.estimated_budget)
    return decoded,mode,detail

def build(flow,plan):
    from .planning import PACKAGES
    from . import sponsorship
    c,e=flow.c,flow.e
    total=plan.estimated_budget
    with flow.tool('FormFlow','publish_registration',{'registration_deadline':plan.registration_deadline.isoformat()}) as step:
        form=publish(c,flow.id,plan.registration_deadline.isoformat(),plan.fields)
        gf_msg=""
        try:
            from . import google_oauth, forms_integration
            if google_oauth.is_club_connected(e['club_id']):
                questions = forms_integration.suggest_questions(e['name'], e.get('type', 'Event'), e.get('description', '') or brief if 'brief' in locals() else e.get('goals', ''))
                gf = forms_integration.create_google_form(
                    club_id=e['club_id'],
                    event_id=flow.id,
                    event_name=e['name'],
                    event_data={**e, 'deadline': plan.registration_deadline.isoformat()},
                    questions=questions,
                    conn=c,
                )
                form = publish(c, flow.id, plan.registration_deadline.isoformat(), plan.fields)
                gf_msg = f" Google Form live ({gf['question_count']} questions)."
        except Exception:
            pass
        step.update(summary=f"Published the registration form with {2+len(form['fields'])} fields.{gf_msg}",output=form)
    with flow.tool('OpsLedger','build_event_plan',{'total_budget_paise':total}) as step:
        share=0
        for index,(category,percent,adjustable) in enumerate([('Venue',24,0),('Food & refreshments',30,0),('Prizes',26,0),('Merchandise',12,65),('Marketing',8,55)]):
            amount=total*percent//100 if index<4 else total-share
            share+=amount
            db.insert(c,'budget',event_id=flow.id,category=category,planned=amount,adjustable=amount*adjustable//100)
        start=iso(e['start_date'])
        registration=plan.registration_deadline
        schedule=[
            ('Confirm venue and event format','Operations',min(registration,start-timedelta(days=7))),
            ('Review sponsor pitches','Sponsorship',min(registration,start-timedelta(days=5))),
            ('Publish registration invitation','Marketing',registration-timedelta(days=3)),
            ('Close registrations and confirm roster','Operations',registration),
            ('Brief volunteers and confirm vendors','Operations',max(registration,start-timedelta(days=1))),
            ('Open the event and check in participants','Operations',start),
            ('Close project submissions','Planning',plan.submission_deadline),
            ('Publish results and recap partner deliverables','Planning',iso(e['end_date'])),
        ]
        previous=None
        for title,department,day in sorted(schedule,key=lambda row:row[2]):
            db.insert(c,'milestones',event_id=flow.id,title=title,due_date=day.isoformat())
            key=task(c,flow.id,title,department,day.isoformat(),'OpsLedger')
            if previous:c.execute('INSERT INTO dependencies VALUES (?,?)',(key,previous))
            previous=key
        step.update(summary=f'Allocated ₹{total/100:,.0f} across five categories and scheduled eight milestones.',output={'budget_paise':total,'milestones':8})
    for name,pct,benefits in PACKAGES:
        db.insert(c,'packages',event_id=flow.id,name=name,amount=e['sponsorship_target']*pct//100,benefits=benefits)
    with flow.tool('Magnet','rank_sponsors',{'funding_gap_paise':e['sponsorship_target']}) as step:
        matches=[p for p in prospects(c,e,include_directory=True)][:4] if e['sponsorship_target'] else []
        for match in matches:
            key=db.insert(c,'sponsors',event_id=flow.id,prospect_id=match['id'],stage='Shortlisted')
            sponsorship.draft(flow,{'sponsor_id':key},'outreach')
        step.update(summary=f'Prepared {len(matches)} sponsor pitches for organizer review.',output={'partners':[p['name'] for p in matches]})
    with flow.tool('Canvas','generate_poster',{'event_name':e['name']}) as step:
        from . import poster_studio
        poster=poster_studio.create_poster_record(c,flow.id,use_ai_image=False)
        step.update(summary=f"Created event poster ({poster['theme']}) with event details and QR.",output={'poster_id':poster['id'],'theme':poster['theme']})
