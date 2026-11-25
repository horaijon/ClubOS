"""Reproducible fictional demonstration data. Reset affects only CodeStorm."""
import csv
from datetime import date,timedelta
from pathlib import Path
from .db import insert,now,encode
from .planning import Flow,generate
from .state import get_event,task,owner

DEMO='codestorm-2026'
CLUB='nexus-technical-club'
PEOPLE=[('Aarav Rao','Club President','Planning'),('Mira Shah','Event Coordinator','Planning'),('Anika Iyer','Sponsorship Lead','Sponsorship'),('Dev Menon','Finance Lead','Finance'),('Sana Ali','Marketing Lead','Marketing'),('Rohan Das','Operations Lead','Operations'),('Diya Patel','Volunteer Coordinator','Operations'),('Kabir Shah','Partnership Associate','Sponsorship'),('Tara Bose','Design Lead','Marketing'),('Ishaan Sen','Technical Lead','Operations'),('Nila Roy','Treasurer','Finance'),('Riya Mehta','Program Coordinator','Planning')]

def bootstrap(c):
    if not c.execute('SELECT 1 FROM clubs WHERE id=?',(CLUB,)).fetchone():
        insert(c,'clubs',id=CLUB,name='Nexus Technical Club',college='Illustrative campus workspace')
        for i,(name,role,dept) in enumerate(PEOPLE):
            insert(c,'members',id=f'member-{i+1}',club_id=CLUB,name=name,role=role,department=dept)
    if not c.execute('SELECT 1 FROM profiles WHERE event_scope IS NULL').fetchone():
        with open(Path(__file__).resolve().parents[2]/'demo'/'sponsor_profiles.csv',encoding='utf8') as f:
            for p in csv.DictReader(f):
                insert(c,'profiles',id=p['name'].lower().replace(' ','-'),description=f"Illustrative {p['industry'].lower()} partner for student-led events.",**p)
    if not c.execute('SELECT 1 FROM events WHERE id=?',(DEMO,)).fetchone():
        seed_event(c)

def seed_event(c):
    today=date.today()
    day=lambda n:(today+timedelta(days=n)).isoformat()
    insert(c,'events',id=DEMO,club_id=CLUB,name='CodeStorm 2026',type='24-hour hackathon',description='A student hackathon bringing builders, mentors and industry partners together for 24 hours of hands-on development.',venue='Innovation Auditorium',start_date=day(14),end_date=day(15),target=200,initial_budget=2_000_000,sponsorship_target=4_500_000,college='Illustrative campus workspace',goals='Build student developer projects and connect with industry mentors.',requirements='Overnight access and participant Wi-Fi',constraints_text='Campus facilities and confirmed funding',is_demo=1,registration_milestone=130,milestone_date=day(-1),created_at=day(-18)+'T09:00:00+00:00')
    for i in range(12):
        c.execute('INSERT INTO team VALUES (?,?)',(DEMO,f'member-{i+1}'))
    w=insert(c,'workflows',event_id=DEMO,trigger='Event created',request_id='initial-plan',input_hash='seed',created_at=now(),result='{}')
    f=Flow(c,get_event(c,DEMO),w,'Event created',True)
    generate(f,True)
    for slug,stage,commit,received in [('vectorforge','Confirmed',2_000_000,0),('circuit-harbor','Confirmed',1_500_000,1_500_000),('bytebrew-labs','Confirmed',1_000_000,500_000),('kernel-grove','Negotiating',0,0),('northloop-coffee','Contacted',0,0),('patchline-studio','Outreach Drafted',0,0),('oscilla-works','Shortlisted',0,0),('stackward-academy','Identified',0,0)]:
        sid=insert(c,'sponsors',event_id=DEMO,prospect_id=slug,stage=stage,committed=commit,follow_up_date=day(2) if stage=='Contacted' else None)
        if received: insert(c,'payments',event_id=DEMO,sponsor_id=sid,amount=received,created_at=day(-3)+'T12:00:00+00:00')
        if stage=='Confirmed':
            name=c.execute('SELECT name FROM profiles WHERE id=?',(slug,)).fetchone()[0]
            tid=task(c,DEMO,f'Approve {name} logo placement','Marketing',day(5),'Echo','High',sponsor_id=sid)
            insert(c,'deliverables',event_id=DEMO,sponsor_id=sid,task_id=tid)
        if slug=='kernel-grove':
            insert(c,'communications',event_id=DEMO,sponsor_id=sid,kind='response',text='We are interested in supporting CodeStorm. Please send us the proposed partner benefits for review.',terms=None,created_at=day(-2)+'T12:00:00+00:00')
    for category,amount,desc in [('Venue',500_000,'Auditorium reservation deposit'),('Food & refreshments',350_000,'Refreshment vendor deposit'),('Equipment',100_000,'Network equipment rental')]:
        bid=c.execute('SELECT id FROM budget WHERE event_id=? AND category=?',(DEMO,category)).fetchone()[0]
        insert(c,'expenses',event_id=DEMO,category_id=bid,amount=amount,description=desc,created_at=day(-2)+'T11:00:00+00:00')
    first=['Anya','Kabir','Tara','Arun','Ira','Dev','Maya','Neel','Sana','Riya','Vikram','Leena']
    last=['Shah','Rao','Iyer','Das','Bose','Sen','Patel','Ali','Roy','Nair','Gupta','Sethi']
    for i in range(136):
        insert(c,'participants',event_id=DEMO,name=f'{first[i%12]} {last[i//12]}',email=f'builder{i+1:03}@example.test',created_at=day(-13+i//10)+f'T{9+i%9:02}:00:00+00:00')
    for title,channel,body,n in [('Mentor spotlight','Social','Meet the mentors helping CodeStorm teams turn early prototypes into working projects.',2),('Volunteer briefing','WhatsApp','Volunteer leads, please review your check-in and auditorium assignments before rehearsal.',6)]:
        insert(c,'marketing',event_id=DEMO,title=title,channel=channel,body=body,scheduled_date=day(n))
    f.risk('wifi-rehearsal','Auditorium network verification','The overnight power and Wi-Fi checklist is awaiting its technical rehearsal.','Medium','Connectivity for 200 expected builders.','Complete the venue walkthrough and verify backup access.',['Relay','Sentinel'])
    f.note('Network rehearsal flagged','Relay is tracking the auditorium connectivity check.','Sentinel')
    f.note('Sponsor payments reconciled','₹20,000 received from two confirmed fictional partners.','Ledger')
    f.note('Registration milestone reached','136 builders registered toward a target of 200.','Relay')
