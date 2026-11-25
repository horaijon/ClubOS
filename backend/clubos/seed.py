"""Reproducible fictional demonstration data. Reset affects only CodeStorm."""
import csv
from datetime import date,timedelta
from pathlib import Path
from .db import insert,now,encode
from .planning import Flow,PLAN,generate
from .state import get_event,task,owner

DEMO='codestorm-2026'
BUILD='build-night-2026'
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
    upgrade_demo(c)
    if not c.execute('SELECT 1 FROM events WHERE id=?',(BUILD,)).fetchone():
        seed_build(c)

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
    for i in range(136):
        insert(c,'participants',event_id=DEMO,name=person(i),email=f'builder{i+1:03}@example.test',created_at=day(-13)+'T09:00:00+00:00')
    for title,channel,body,n in [('Mentor spotlight','Social','Meet the mentors helping CodeStorm teams turn early prototypes into working projects.',2),('Volunteer briefing','WhatsApp','Volunteer leads, please review your check-in and auditorium assignments before rehearsal.',6)]:
        insert(c,'marketing',event_id=DEMO,title=title,channel=channel,body=body,scheduled_date=day(n))
    f.risk('wifi-rehearsal','Auditorium network verification','The overnight power and Wi-Fi checklist is awaiting its technical rehearsal.','Medium','Connectivity for 200 expected builders.','Complete the venue walkthrough and verify backup access.',['Relay','Sentinel'])
    f.note('Network rehearsal flagged','Relay is tracking the auditorium connectivity check.','Sentinel')
    f.note('Sponsor payments reconciled','₹20,000 received from two confirmed fictional partners.','Ledger')
    f.note('Registration milestone reached','136 builders registered toward a target of 200.','Relay')
    upgrade_demo(c)
    c.execute("INSERT OR IGNORE INTO receivables SELECT id,? FROM sponsors WHERE event_id=? AND stage='Confirmed'",(day(12),DEMO))


TASK_DETAILS=[
    'Confirm the event goal, track eligibility, judging criteria and escalation contacts with faculty.',
    'Get written permission for overnight auditorium access and confirm when campus security locks the gates.',
    'Set cash and in-kind tiers and agree which logo placements and booth sizes can be promised.',
    'Score developer tooling and infrastructure partners by track fit, campus reach and contribution history.',
    'Publish team-size rules, eligibility and the accessibility contact with the registration form.',
    'Prepare the campus poster, social crop and a high-contrast version for foyer displays.',
    'Compare catering, network rental and security quotes with taxes included.',
    'Confirm one faculty judge per track and identify an alternate for the final round.',
    'Share the registration link with department societies and resident student groups.',
    'Mark power drops, cable paths and backup hotspot locations on the auditorium floor plan.',
    'Check the partner audience, specific benefits and proposed amount before reviewing each draft.',
    'Confirm the vegetarian split, allergy labels, second meal window and late delivery contact.',
    'Assign registration, floor support, mentor escort and overnight escalation shifts.',
    'Match written commitments to remittance dates and agree on follow-up owners.',
    'Share scoring weights for technical depth, creativity and demo evidence with all judges.',
    'Collect approved logo files and confirm acknowledgements against the partner agreement.',
    'Measure Wi-Fi in each seating block and test the guest network under simultaneous load.',
    'Confirm mentor office hours, track rooms and a queue for blocked teams.',
    'Compare confirmed registrations with capacity and ask department reps about thin tracks.',
    'Map check-in, mentor rooms, power strips and emergency exits for printed signage.',
    'Verify every pledged logo, booth and speaking slot against the sponsor agreement.',
    'Attach meal, venue and equipment receipts and match deposits to vendor quotations.',
    'Test check-in and prepare a spreadsheet fallback for the auditorium entrance.',
    'Send bring-list, arrival times, sleep arrangements and demo submission deadlines for review.',
    'Check judging, sponsor announcements and meal windows against the run of show.',
    'Rehearse projector handover, overnight connectivity and emergency announcements.',
    'Confirm shift leads, handover slots and the escalation channel for check-in issues.',
    'Assign wristbands, verify team attendance and handle late registration at the desk.',
    'Save the checked-in headcount and reconcile it with the published registration tally.',
    'Collect approved photos, logo placements and booth attendance evidence for each partner.',
]

def person(index):
    given=('Aadhya','Pranav','Meher','Siddharth','Fatima','Ritvik','Ishita','Vivek','Charvi','Armaan',
           'Tanishka','Varun','Zoya','Harini','Kavya','Yash','Eshaan','Nandini','Soham','Avni',
           'Tanvi','Prisha','Reyansh','Lakshmi','Atharv','Anushka','Aditya','Khushi','Samar','Nihal','Rhea')
    family=('Banerjee','Kini','Narayanan','Bhat','Mirza','Chatterjee','Srinivasan','Saxena','Shetty',
            'Deshpande','Barua','Qureshi','Malhotra','Kashyap','Subramanian','Acharya','Reddy')
    return f'{given[index%len(given)]} {family[(index*7+index//len(given))%len(family)]}'

def upgrade_demo(c):
    if c.execute("SELECT 1 FROM workflows WHERE event_id=? AND request_id='seed-review-pack-v2'",(DEMO,)).fetchone():return
    today=date.today()
    for (title,*_),description in zip(PLAN,TASK_DETAILS):
        c.execute("UPDATE tasks SET description=? WHERE event_id=? AND title=? AND description LIKE '%lead verifies completion%'",(description,DEMO,title))
    histogram=(2,3,4,6,8,12,16,20,18,15,12,9,7,4)
    index=0
    for offset,count in enumerate(histogram):
        day=today-timedelta(days=13-offset)
        for j in range(count):
            c.execute("UPDATE participants SET name=?,created_at=? WHERE event_id=? AND email=?",
                      (person(index),f'{day}T{9+j%9:02}:30:00+00:00',DEMO,f'builder{index+1:03}@example.test'))
            index+=1
    for i,(title,*_) in enumerate(PLAN[:10]):
        created=(today-timedelta(days=17)).isoformat()+'T09:00:00+00:00'
        completed=(today-timedelta(days=13-i)).isoformat()+'T16:00:00+00:00'
        c.execute("UPDATE tasks SET created_at=?,completed_at=? WHERE event_id=? AND title=? AND status='Completed' AND agent='Atlas'",
                  (created,completed,DEMO,title))
    initial=c.execute("SELECT id FROM workflows WHERE event_id=? AND request_id='initial-plan'",(DEMO,)).fetchone()
    if initial:
        for i,row in enumerate(c.execute('SELECT id FROM runs WHERE workflow_id=? ORDER BY rowid',(initial[0],)).fetchall()):
            day=today-timedelta(days=max(1,13-i))
            c.execute('UPDATE runs SET created_at=? WHERE id=?',(f'{day}T10:30:00+00:00',row['id']))
    wid=insert(c,'workflows',event_id=DEMO,trigger='Demo review queue',request_id='seed-review-pack-v2',
               input_hash='seed',created_at=now(),result='{}')
    f=Flow(c,get_event(c,DEMO),wid,'Demo review queue',True)
    from .sponsorship import draft
    partner=c.execute("SELECT id,stage FROM sponsors WHERE event_id=? AND prospect_id='oscilla-works'",(DEMO,)).fetchone()
    if partner and partner['stage']=='Shortlisted':
        out=draft(f,{'sponsor_id':partner['id']},'proposal')
        f.approval('Review Oscilla Works outreach','Magnet prepared a partnership pitch for the hardware track.',
                   [dict(type='draft_review',title='Approve Oscilla Works draft',sponsor_id=partner['id'],text=out['text'])])
    by_category={r['category']:r for r in c.execute('SELECT * FROM budget WHERE event_id=?',(DEMO,))}
    source,dest=by_category.get('Merchandise'),by_category.get('Food & refreshments')
    if source and dest and source['adjustable']>=400_000:
        f.approval('Move ₹4,000 to refreshments','Ledger proposes moving unused merchandise funds to the overnight meal budget.',
                   [dict(type='reallocate_budget',title='Move ₹4,000 from merchandise to refreshments',
                         category_id=source['id'],destination_id=dest['id'],amount=400_000,before=source['planned'],
                         after=source['planned']-400_000,destination_before=dest['planned'],destination_after=dest['planned']+400_000)])

def seed_build(c):
    today=date.today()
    start=(today+timedelta(days=28)).isoformat()
    insert(c,'events',id=BUILD,club_id=CLUB,name='Build Night 2026',type='Prototype workshop',
           description='A hands-on evening to build and demo a first prototype.',venue='Campus Makerspace',
           start_date=start,end_date=start,target=60,initial_budget=900_000,sponsorship_target=400_000,
           college='Illustrative campus workspace',goals='Build small hardware and software prototypes.',
           requirements='Soldering stations, extension boards and lab mentors',constraints_text='One evening. Lab capacity is 60.',
           is_demo=1,registration_milestone=30,milestone_date=(today+timedelta(days=20)).isoformat(),created_at=now())
    for i in (0,1,2,3,5,8):
        c.execute('INSERT INTO team VALUES (?,?)',(BUILD,f'member-{i+1}'))
    wid=insert(c,'workflows',event_id=BUILD,trigger='Event created',request_id='initial-plan',input_hash='seed',created_at=now(),result='{}')
    f=Flow(c,get_event(c,BUILD),wid,'Event created',True)
    from .planning import CATEGORIES,PACKAGES
    for category,share,flex in CATEGORIES:
        value=1_300_000*share//100
        insert(c,'budget',event_id=BUILD,category=category,planned=value,adjustable=value*flex//100)
    c.execute("UPDATE budget SET category='Demo supplies' WHERE event_id=? AND category='Prizes'",(BUILD,))
    for name,pct,benefits in PACKAGES:
        insert(c,'packages',event_id=BUILD,name=name,amount=400_000*pct//100,benefits=benefits)
    schedule=[
        ('Reserve the makerspace benches','Operations','Confirm six benches, soldering ventilation and lab induction.',19),
        ('Build the materials checklist','Operations','Count kits, USB leads and protective eyewear for each bench.',13),
        ('Publish prototype sign-ups','Marketing','Collect track preference and prior experience from participants.',10),
        ('Allocate workshop mentors','Planning','Assign a mentor to each bench and confirm the demo rotation.',4),
        ('Run the prototype showcase','Operations','Test the projector and give every group a five-minute demo.',0),
    ]
    previous=None
    for i,(title,dept,description,offset) in enumerate(schedule):
        tid=task(c,BUILD,title,dept,(today+timedelta(days=28-offset)).isoformat(),status='Completed' if i==0 else 'To Do',description=description)
        if i==0:
            c.execute('UPDATE tasks SET created_at=?,completed_at=? WHERE id=?',
                      ((today-timedelta(days=13)).isoformat()+'T09:00:00+00:00',(today-timedelta(days=11)).isoformat()+'T15:00:00+00:00',tid))
        if previous:c.execute('INSERT INTO dependencies VALUES (?,?)',(tid,previous))
        previous=tid
    index=0
    for days,count in [(13,1),(11,2),(9,2),(7,4),(5,3),(3,5),(1,3)]:
        created=(today-timedelta(days=days)).isoformat()+'T11:30:00+00:00'
        for _ in range(count):
            insert(c,'participants',event_id=BUILD,name=person(136+index),email=f'prototype{index+1:03}@example.test',created_at=created)
            index+=1
    for days,agent,tool,summary in [(12,'Atlas','plan_tasks','Scheduled five makerspace milestones.'),
                                   (9,'Ledger','allocate_budget','Allocated ₹13,000 across workshop costs.'),
                                   (4,'Relay','work_checklist','Confirmed bench access and equipment needs.')]:
        f.log(agent,tool,summary)
        c.execute('UPDATE runs SET created_at=? WHERE id=(SELECT id FROM runs WHERE workflow_id=? ORDER BY rowid DESC LIMIT 1)',
                  ((today-timedelta(days=days)).isoformat()+'T14:00:00+00:00',wid))
