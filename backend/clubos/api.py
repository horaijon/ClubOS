"""HTTP boundary for the local demo workspace."""
from datetime import date,timedelta
from typing import Any,Annotated
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict,StringConstraints,model_validator
from . import db,engine,trace,launch
from .auth import Workspace, authorize_event
from .state import Invalid,Missing,Conflict

router=APIRouter(prefix='/api')
Name=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
Money=Annotated[int,Field(strict=True,ge=0,le=100_000_000_000)]

class EventCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:Name
    type:Name='Hackathon'
    description:str=Field(default='',max_length=3500)
    venue:str=Field(default='Campus auditorium',max_length=220)
    start_date:date=Field(default_factory=lambda:date.today()+timedelta(days=14))
    end_date:date|None=None
    target:int=Field(default=100,ge=1,le=100000,strict=True)
    initial_budget:Money=0
    sponsorship_target:Money=0
    college:str=Field(default='Illustrative campus workspace',max_length=200)
    goals:str=Field(default='',max_length=2500)
    requirements:str=Field(default='',max_length=2500)
    constraints:str=Field(default='',max_length=2500)
    brief:str=Field(default='',max_length=6500)
    estimated_budget:Money|None=None
    brief_plan:launch.BriefPlan|None=None
    members:list[Name]=Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def date_order(self):
        self.end_date=self.end_date or self.start_date
        if self.end_date<self.start_date:raise ValueError('End date precedes start date.')
        if self.brief_plan:
            if not self.brief:
                raise ValueError('Include the reviewed event brief.')
            if (self.brief_plan.registration_deadline>self.start_date or
                    not self.start_date<=self.brief_plan.submission_deadline<=self.end_date):
                raise ValueError('Registration must close by the event start, and submissions must close during the event.')
            if self.brief_plan.estimated_budget<self.initial_budget:
                raise ValueError('Total budget must cover the club funds allocated to the event.')
        return self

class BriefInput(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    brief:str=Field(min_length=1,max_length=6500)

@router.post('/event-brief/preview')
def preview_brief(input:BriefInput,club:Workspace):
    details,mode,_=launch.extract(input.brief)
    return dict(details=details,mode=mode)

class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    type:Annotated[str,StringConstraints(min_length=1,max_length=65,pattern='^[a-z_]+$')]
    payload:dict[str,Any]=Field(default_factory=dict)
    request_id:Annotated[str,StringConstraints(min_length=1,max_length=150)]

def error(exc):
    return HTTPException(404 if isinstance(exc,Missing) else 409 if isinstance(exc,Conflict) else 422,str(exc))

@router.get('/events')
def events(club:Workspace):
    with db.transaction() as c:
        return db.rows(c,"SELECT id,name FROM events WHERE club_id=? ORDER BY (id='codestorm-2026') DESC,is_demo DESC,created_at DESC",(club['id'],))

@router.post('/events',status_code=201)
def create_event(input:EventCreate,club:Workspace):
    try:
        execution=trace.Execution(club['id'],None,None,'Create event')
        with execution.recording(), db.transaction(True) as c:
            return engine.create(c,input.model_dump(mode='json'),club['id'],execution)
    except Invalid as exc:raise error(exc) from exc

@router.get('/events/{event_id}')
def event(event_id:str,club:Workspace):
    try:
        with db.transaction() as c:
            authorize_event(c,event_id,club['id'])
            return engine.workspace(c,event_id)
    except Invalid as exc:raise error(exc) from exc

@router.post('/events/{event_id}/actions')
def action(event_id:str,input:Action,club:Workspace):
    try:
        with db.transaction() as c:
            authorize_event(c,event_id,club['id'])
        execution=trace.Execution(club['id'],event_id,input.request_id,input.type)
        with execution.recording(), db.transaction(True) as c:
            authorize_event(c,event_id,club['id'])
            return engine.dispatch(c,event_id,input.type,input.payload,input.request_id,execution)
    except Invalid as exc:raise error(exc) from exc


@router.get('/events/{event_id}/explain/{target_type}/{target_id}')
def explain_decision(event_id:str,target_type:str,target_id:str,club:Workspace):
    from . import explainability
    try:
        with db.transaction() as c:
            authorize_event(c,event_id,club['id'])
            return explainability.explain(c,event_id,target_type,target_id)
    except Invalid as exc:raise error(exc) from exc


@router.get('/events/{event_id}/trace')
def event_trace(event_id:str,request:Request,club:Workspace):
    with db.transaction() as c:
        authorize_event(c,event_id,club['id'])
    return trace.stream(request,club['id'],"event_id",event_id)
