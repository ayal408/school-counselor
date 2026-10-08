"""Encrypted casework, immutable revisions, scoped search and safe aggregate reports."""
import json
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, AwareDatetime, model_validator, ValidationError
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, Student, Meeting, MeetingRevision, CaseRecord, CaseConsent, CaseTransfer, StudentShare, Task, Appointment, Audit, now
from .security import current_user, readable_student, visible_condition, encrypt, decrypt
from .schemas import MeetingInput
from .mfa import utc
from .management import Proof, prove
router=APIRouter(prefix='/api')
TOPICS={'social':'חברה','learning':'למידה','emotional':'רגש','attendance':'נוכחות','family':'משפחה','other':'אחר'}
def pack(v):return encrypt(json.dumps(v,ensure_ascii=False,default=lambda x:x.isoformat()))
def unpack(v):return json.loads(decrypt(v)) if v else {}
def audit(db,u,action,rid):db.add(Audit(user_id=u.id,action=action,record_id=rid))
def writable(db,u,sid,archived=False):
    expected=u.session_version
    locked=db.scalar(select(User).where(User.id==u.id).with_for_update().execution_options(populate_existing=True))
    if not locked.active or locked.session_version!=expected:raise HTTPException(401,"יש להתחבר מחדש")
    s=db.scalar(select(Student).where(Student.id==sid).with_for_update().execution_options(populate_existing=True))
    if not s or s.owner_id!=u.id:raise HTTPException(404,'הכרטיס אינו בבעלותך')
    if s.archived and not archived:raise HTTPException(409,'הכרטיס בארכיון')
    return s
def require_consent(db,sid,purpose,recipient=''):
    if not db.scalar(select(CaseConsent.id).where(CaseConsent.student_id==sid,CaseConsent.purpose==purpose,CaseConsent.recipient==recipient,CaseConsent.revoked.is_(False),CaseConsent.granted_at<=now(),CaseConsent.expires_at>now())):
        raise HTTPException(403,'יש לתעד הסכמה תקפה בכרטיס התלמידה: '+purpose)
def snapshot(m):
    return dict(unpack(m.document),starts_at=utc(m.starts_at).isoformat(),notes=decrypt(m.notes),summary=decrypt(m.summary),ai_assisted=m.ai_assisted,consent_recorded=m.consent_recorded,ai_reviewed=m.ai_reviewed)
def meeting_json(m):return dict(snapshot(m),id=m.id,student_id=m.student_id,version=m.version,updated_at=m.updated_at)
def revision(db,m,u):
    db.add(MeetingRevision(meeting_id=m.id,version=m.version,actor_id=u.id if u else None,created_at=now() if u else m.created_at,document=pack(snapshot(m))))
def apply(m,b):
    m.starts_at=b.starts_at;m.notes=encrypt(b.notes);m.summary=encrypt(b.summary)
    m.ai_assisted=b.ai_assisted;m.ai_reviewed=b.ai_reviewed;m.consent_recorded=b.consent_recorded
    m.document=pack(b.model_dump(exclude={'starts_at','notes','summary','ai_assisted','ai_reviewed','consent_recorded','expected_version'}));m.updated_at=now()
@router.put('/students/{sid}/meetings/{mid}')
def edit_meeting(sid:str,mid:str,b:MeetingInput,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid)
    m=db.scalar(select(Meeting).where(Meeting.id==mid,Meeting.student_id==sid).with_for_update())
    if not m:raise HTTPException(404)
    if m.version!=b.expected_version:raise HTTPException(409,'הפגישה שונתה. טעני מחדש לפני עריכה')
    if not db.get(MeetingRevision,(mid,m.version)):revision(db,m,None);db.flush()
    apply(m,b);m.version+=1;revision(db,m,u);audit(db,u,'meeting.update',mid);db.commit();return meeting_json(m)
@router.get('/students/{sid}/meetings/{mid}/history')
def history(sid:str,mid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    readable_student(db,u,sid)
    m=db.scalar(select(Meeting).where(Meeting.id==mid,Meeting.student_id==sid))
    if not m:raise HTTPException(404)
    rows=db.scalars(select(MeetingRevision).where(MeetingRevision.meeting_id==mid).order_by(MeetingRevision.version.desc())).all()
    audit(db,u,'meeting.history',mid);db.commit()
    return [{'version':r.version,'actor':db.get(User,r.actor_id).name if r.actor_id and db.get(User,r.actor_id) else unpack(r.document).get('source_actor','תיעוד קודם — עורכת לא ידועה'),'at':r.created_at,'document':unpack(r.document)} for r in rows] or [{'version':m.version,'actor':'תיעוד קודם — עורכת לא ידועה','at':m.created_at,'document':snapshot(m)}]
class DraftDocument(MeetingInput):
    @model_validator(mode="after")
    def require_ai_review(self):return self
class DraftBody(BaseModel):
    expected_version:int=Field(default=0,ge=0)
    document:DraftDocument
    meeting_id:str=Field(default='',max_length=36)
def find_draft(db,sid,mid):
    if mid and not db.scalar(select(Meeting.id).where(Meeting.id==mid,Meeting.student_id==sid)):raise HTTPException(404)
    rows=db.scalars(select(CaseRecord).where(CaseRecord.student_id==sid,CaseRecord.kind=='draft')).all()
    return next((r for r in rows if unpack(r.document).get('_meeting_id','')==mid),None)
@router.get('/students/{sid}/draft')
def draft(sid:str,meeting_id:str=Query('',max_length=36),u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=find_draft(db,sid,meeting_id)
    return {'version':r.version,'document':unpack(r.document),'updated_at':r.updated_at} if r else {'version':0,'document':None}
@router.put('/students/{sid}/draft')
def save_draft(sid:str,b:DraftBody,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=find_draft(db,sid,b.meeting_id)
    if (r.version if r else 0)!=b.expected_version:raise HTTPException(409,'הטיוטה שונתה בחלון אחר. טעני מחדש')
    if not r:r=CaseRecord(student_id=sid,kind='draft',actor_id=u.id,version=0);db.add(r)
    r.version+=1;r.document=pack(dict(b.document.model_dump(),_meeting_id=b.meeting_id));r.updated_at=now();r.actor_id=u.id
    db.commit();return {'version':r.version,'updated_at':r.updated_at}
class DraftConsume(BaseModel):
    expected_version:int=Field(ge=1)
    meeting_id:str=Field(default='',max_length=36)
@router.post('/students/{sid}/draft/publish',status_code=201)
def publish(sid:str,b:DraftConsume,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=find_draft(db,sid,b.meeting_id)
    if not r or r.version!=b.expected_version:raise HTTPException(409,'הטיוטה שונתה. טעני מחדש')
    try:body=MeetingInput.model_validate(unpack(r.document))
    except ValidationError:raise HTTPException(422,'יש לבדוק ולאשר את התמלול לפני שמירה')
    if b.meeting_id:
        m=db.scalar(select(Meeting).where(Meeting.id==b.meeting_id,Meeting.student_id==sid).with_for_update())
        if m.version!=body.expected_version:raise HTTPException(409,'הפגישה שונתה מאז פתיחת הטיוטה. טעני מחדש והשווי לגרסה הנוכחית')
        if not db.get(MeetingRevision,(m.id,m.version)):revision(db,m,None);db.flush()
        m.version+=1
    else:m=Meeting(student_id=sid);db.add(m)
    apply(m,body);db.flush();revision(db,m,u)
    db.delete(r);audit(db,u,'meeting.publish',m.id);db.commit();return meeting_json(m)
class Contact(BaseModel):
    kind:Literal['parent','staff','other']
    at:AwareDatetime
    name:str=Field(min_length=1,max_length=120)
    notes:str=Field(min_length=1,max_length=10000)
class Goal(BaseModel):
    title:str=Field(min_length=1,max_length=500)
    measure:str=Field(default='',max_length=1000)
    due_at:AwareDatetime
    progress:int=Field(default=0,ge=0,le=100)
    note:str=Field(default='',max_length=2000)
class Plan(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    status:Literal['active','completed']='active'
    goals:list[Goal]=Field(min_length=1,max_length=30)
    expected_version:int=Field(default=0,ge=0)
def record_json(db,r):return {'id':r.id,'version':r.version,'at':r.updated_at,'actor':unpack(r.document).get('_source_actor',db.get(User,r.actor_id).name),'document':unpack(r.document)}
@router.get('/students/{sid}/records/{kind}')
def records(sid:str,kind:Literal['contact','plan'],u:User=Depends(current_user),db:Session=Depends(get_db)):
    readable_student(db,u,sid);return [record_json(db,r) for r in db.scalars(select(CaseRecord).where(CaseRecord.student_id==sid,CaseRecord.kind==kind).order_by(CaseRecord.updated_at.desc())).all()]
@router.post('/students/{sid}/contacts',status_code=201)
def contact(sid:str,b:Contact,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=CaseRecord(student_id=sid,kind='contact',actor_id=u.id,document=pack(b.model_dump()));db.add(r);db.flush();audit(db,u,'contact.create',r.id);db.commit();return record_json(db,r)
@router.post('/students/{sid}/plans',status_code=201)
def plan(sid:str,b:Plan,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=CaseRecord(student_id=sid,kind='plan',actor_id=u.id,document=pack(b.model_dump(exclude={'expected_version'})));db.add(r);db.flush();audit(db,u,'plan.create',r.id);db.commit();return record_json(db,r)
@router.put('/students/{sid}/plans/{rid}')
def edit_plan(sid:str,rid:str,b:Plan,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);r=db.scalar(select(CaseRecord).where(CaseRecord.id==rid,CaseRecord.student_id==sid,CaseRecord.kind=='plan'))
    if not r:raise HTTPException(404)
    if r.version!=b.expected_version:raise HTTPException(409,'התוכנית שונתה. טעני מחדש')
    db.add(CaseRecord(student_id=sid,kind='plan_history',actor_id=r.actor_id,document=pack({'plan_id':rid,'version':r.version,'at':utc(r.updated_at).isoformat(),'document':unpack(r.document)})))
    r.document=pack(b.model_dump(exclude={'expected_version'}));r.version+=1;r.actor_id=u.id;r.updated_at=now();audit(db,u,'plan.update',rid);db.commit();return record_json(db,r)
@router.get('/students/{sid}/plans/{rid}/history')
def plan_history(sid:str,rid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    readable_student(db,u,sid)
    return [record_json(db,r) for r in db.scalars(select(CaseRecord).where(CaseRecord.student_id==sid,CaseRecord.kind=='plan_history')).all() if unpack(r.document).get('plan_id')==rid]
class Consent(BaseModel):
    purpose:Literal['recording','transcription','cloud','sharing','browser']
    recipient:str=Field(default='',max_length=36)
    granted_at:AwareDatetime
    expires_at:AwareDatetime
    evidence:str=Field(min_length=5,max_length=4000)
    @model_validator(mode='after')
    def valid(self):
        if self.expires_at<=self.granted_at:raise ValueError('תוקף לא תקין')
        if self.purpose=='cloud' and self.recipient not in ['openai','groq','gemini']:raise ValueError('בחרי ספק')
        if self.purpose=='sharing' and not self.recipient:raise ValueError('בחרי יועצת')
        if self.purpose in ['recording','transcription','browser'] and self.recipient:raise ValueError('ללא נמען')
        return self
@router.get('/students/{sid}/consents')
def consents(sid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid,True)
    return [{'id':r.id,'purpose':r.purpose,'recipient':r.recipient,'granted_at':r.granted_at,'expires_at':r.expires_at,'evidence':decrypt(r.evidence),'revoked':r.revoked,'active':not r.revoked and utc(r.granted_at)<=now()<utc(r.expires_at)} for r in db.scalars(select(CaseConsent).where(CaseConsent.student_id==sid)).all()]
@router.post('/students/{sid}/consents',status_code=201)
def consent(sid:str,b:Consent,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid)
    if b.purpose=='sharing':
        target=db.get(User,b.recipient)
        if not target or not target.active or target.id==u.id:raise HTTPException(422,'יש לבחור יועצת פעילה אחרת')
    v=b.model_dump();v['evidence']=encrypt(b.evidence);r=CaseConsent(student_id=sid,actor_id=u.id,**v);db.add(r);db.flush();audit(db,u,'consent.create',r.id);db.commit();return {'id':r.id}
@router.post('/students/{sid}/consents/{rid}/revoke')
def revoke_consent(sid:str,rid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid,True);r=db.scalar(select(CaseConsent).where(CaseConsent.id==rid,CaseConsent.student_id==sid))
    if not r:raise HTTPException(404)
    r.revoked=True;audit(db,u,'consent.revoke',rid);db.commit();return {'ok':True}
@router.post('/students/{sid}/recording-authorize')
def recording_authorize(sid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);require_consent(db,sid,'recording');audit(db,u,'recording.authorize',sid);db.commit();return {'ok':True}
@router.post('/students/{sid}/browser-dictation-authorize')
def browser_authorize(sid:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid)
    for purpose in ['recording','transcription','browser']:require_consent(db,sid,purpose)
    deadlines=[]
    for purpose in ['recording','transcription','browser']:
        dates=db.scalars(select(CaseConsent.expires_at).where(CaseConsent.student_id==sid,CaseConsent.purpose==purpose,CaseConsent.recipient=='',CaseConsent.revoked.is_(False),CaseConsent.granted_at<=now(),CaseConsent.expires_at>now())).all()
        if not dates:raise HTTPException(403,'ההסכמה פגה. תעדי הסכמה חדשה')
        deadlines.append(max(utc(d) for d in dates))
    deadline=min(deadlines)
    audit(db,u,'dictation.browser',sid);db.commit();return {'ok':True,'valid_until':deadline}
class DecisionTask(BaseModel):
    expected_version:int=Field(ge=1)
    index:int=Field(ge=0,le=29)
    due_at:AwareDatetime
@router.post('/students/{sid}/meetings/{mid}/tasks',status_code=201)
def decision_task(sid:str,mid:str,b:DecisionTask,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid);m=db.scalar(select(Meeting).where(Meeting.id==mid,Meeting.student_id==sid))
    if not m:raise HTTPException(404)
    if m.version!=b.expected_version:raise HTTPException(409,'הפגישה שונתה')
    decisions=unpack(m.document).get('decisions',[])
    if b.index>=len(decisions):raise HTTPException(422)
    key=f'{mid}:{m.version}:{b.index}'
    if any(unpack(r.document).get('key')==key for r in db.scalars(select(CaseRecord).where(CaseRecord.student_id==sid,CaseRecord.kind=='decision_task')).all()):raise HTTPException(409,'כבר נוצרה משימה מהחלטה זו')
    t=Task(student_id=sid,title=encrypt(decisions[b.index]),due_at=b.due_at);db.add(t);db.flush();db.add(CaseRecord(student_id=sid,kind='decision_task',actor_id=u.id,document=pack({'key':key,'task_id':t.id})));audit(db,u,'decision.task',t.id);db.commit();return {'id':t.id}
@router.get('/search')
def search(student:str=Query('',max_length=120),classroom:str=Query('',max_length=40),topic:str=Query('',max_length=30),after:AwareDatetime|None=None,before:AwareDatetime|None=None,open_tasks:bool=False,u:User=Depends(current_user),db:Session=Depends(get_db)):
    if topic and topic not in TOPICS:raise HTTPException(422)
    if after and before and after>before:raise HTTPException(422)
    result=[]
    for s in db.scalars(select(Student).where(visible_condition(u))).all():
        name=decrypt(s.name);cl=decrypt(s.classroom)
        if student not in name or classroom not in cl:continue
        tasks=db.scalars(select(Task).where(Task.student_id==s.id,Task.status=='open')).all()
        if open_tasks and not tasks:continue
        ms=db.scalars(select(Meeting).where(Meeting.student_id==s.id)).all()
        matches=[m for m in ms if (not topic or unpack(m.document).get('topic','other')==topic) and (not after or utc(m.starts_at)>=after) and (not before or utc(m.starts_at)<=before)]
        if (topic or after or before) and not matches:continue
        result.append({'id':s.id,'name':name,'classroom':cl,'open_tasks':len(tasks),'meetings':len(matches),'archived':s.archived})
    audit(db,u,'search',u.id);db.commit();return result
@router.get('/reports')
def reports(after:AwareDatetime|None=None,before:AwareDatetime|None=None,u:User=Depends(current_user),db:Session=Depends(get_db)):
    if after and before and after>before:raise HTTPException(422)
    ids=list(db.scalars(select(Student.id).where(Student.owner_id==u.id)).all())
    meetings=[m for m in db.scalars(select(Meeting).where(Meeting.student_id.in_(ids))).all() if (not after or utc(m.starts_at)>=after) and (not before or utc(m.starts_at)<=before)]
    cohort={m.student_id for m in meetings}
    if len(cohort)<5:return {'suppressed':True,'message':'הדוח יוצג כשיש פגישות עבור לפחות 5 תלמידות בטווח. קבוצות קטנות מוסתרות להגנת הפרטיות.'}
    groups={t:[m for m in meetings if unpack(m.document).get('topic','other')==t] for t in TOPICS}
    topics=[{'topic':TOPICS[t],'meetings':len(ms)} for t,ms in groups.items() if len({m.student_id for m in ms})>=5]
    # No dates, class identifiers, names, free text or record IDs in aggregate output.
    plans=[(r.student_id,unpack(r.document)) for r in db.scalars(select(CaseRecord).where(CaseRecord.student_id.in_(cohort),CaseRecord.kind=='plan')).all()]
    progress=None
    if len({sid for sid,p in plans})>=5:
        values=[g['progress'] for sid,p in plans for g in p['goals']]
        progress=round(sum(values)/len(values)) if values else None
    audit(db,u,'reports',u.id);db.commit();return {'suppressed':False,'meetings':len(meetings),'students':len(cohort),'topics':topics,'plan_progress':progress,'message':'נתונים מצרפיים ללא שמות; קבוצות קטנות מוסתרות. אין בכך הבטחה לאנונימיות בכל הקשר.'}
class TransferInput(Proof):
    to_id:str=Field(max_length=36)
    reason:str=Field(min_length=5,max_length=2000)
@router.post('/students/{sid}/transfer',status_code=201)
def transfer(sid:str,b:TransferInput,u:User=Depends(current_user),db:Session=Depends(get_db)):
    prove(db,u,b);writable(db,u,sid);target=db.get(User,b.to_id)
    if not target or not target.active or target.id==u.id:raise HTTPException(422)
    require_consent(db,sid,'sharing',target.id)
    if db.scalar(select(CaseTransfer).where(CaseTransfer.student_id==sid,CaseTransfer.status=='pending')):raise HTTPException(409,'כבר קיימת בקשת העברה')
    r=CaseTransfer(student_id=sid,from_id=u.id,to_id=target.id,reason=encrypt(b.reason));db.add(r);db.flush();audit(db,u,'transfer.request',r.id);db.commit();return {'id':r.id}
@router.get('/transfers')
def transfers(u:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(CaseTransfer).where((CaseTransfer.to_id==u.id)|(CaseTransfer.from_id==u.id)).order_by(CaseTransfer.created_at.desc())).all()
    return [{'id':r.id,'incoming':r.to_id==u.id,'student_id':r.student_id,'status':r.status,'reason':decrypt(r.reason),'from_name':db.get(User,r.from_id).name,'to_name':db.get(User,r.to_id).name,'at':r.created_at} for r in rows]
class TransferAction(Proof):action:Literal['accept','reject','cancel']
@router.post('/transfers/{rid}')
def transfer_action(rid:str,b:TransferAction,u:User=Depends(current_user),db:Session=Depends(get_db)):
    r=db.get(CaseTransfer,rid)
    if not r or u.id not in [r.from_id,r.to_id]:raise HTTPException(404)
    db.scalars(select(User).where(User.id.in_([r.from_id,r.to_id])).order_by(User.id).with_for_update()).all();prove(db,u,b)
    s=db.scalar(select(Student).where(Student.id==r.student_id).with_for_update().execution_options(populate_existing=True))
    r=db.scalar(select(CaseTransfer).where(CaseTransfer.id==rid).with_for_update().execution_options(populate_existing=True))
    if r.status!='pending' or s.owner_id!=r.from_id:raise HTTPException(409,'הבקשה אינה פעילה')
    if b.action=='cancel' and u.id!=r.from_id or b.action!='cancel' and u.id!=r.to_id:raise HTTPException(403)
    if b.action=='accept':
        if s.archived or not db.get(User,r.from_id).active:raise HTTPException(409,'הכרטיס או המעבירה אינם פעילים')
        require_consent(db,s.id,'sharing',u.id)
        incoming=db.scalars(select(Appointment).where(Appointment.student_id==s.id,Appointment.status=='planned')).all()
        existing=db.scalars(select(Appointment).join(Student).where(Student.owner_id==u.id,Appointment.status=='planned')).all()
        if any(a.starts_at<b.ends_at and b.starts_at<a.ends_at for a in incoming for b in existing):raise HTTPException(409,'קיימת חפיפה ביומן. תקני אותה לפני קבלת הכרטיס')
        s.owner_id=u.id;db.execute(delete(StudentShare).where(StudentShare.student_id==s.id))
    r.status={'accept':'accepted','reject':'rejected','cancel':'cancelled'}[b.action];r.completed_at=now();audit(db,u,'transfer.'+b.action,r.id);db.commit();return {'ok':True}
class RolloverRow(BaseModel):
    student_id:str=Field(max_length=36)
    classroom:str=Field(default='',max_length=40)
    graduate:bool=False
class Rollover(Proof):
    source_year:str=Field(pattern=r'^\d{4}-\d{4}$')
    target_year:str=Field(pattern=r'^\d{4}-\d{4}$')
    rows:list[RolloverRow]=Field(min_length=1,max_length=5000)
    confirmed:bool=False
    @model_validator(mode='after')
    def valid(self):
        a,b=map(int,self.source_year.split('-'));c,d=map(int,self.target_year.split('-'))
        if not 2000<=a<=2198 or b!=a+1 or c!=b or d!=c+1 or len({r.student_id for r in self.rows})!=len(self.rows):raise ValueError('מעבר שנה אינו תקין')
        if any(not r.graduate and not r.classroom.strip() for r in self.rows):raise ValueError('כיתה חובה')
        return self
@router.post('/school-years/rollover')
def rollover(b:Rollover,u:User=Depends(current_user),db:Session=Depends(get_db)):
    prove(db,u,b)
    if not b.confirmed:raise HTTPException(422,'יש לאשר את רשימת המעבר')
    for item in sorted(b.rows,key=lambda x:x.student_id):
        s=writable(db,u,item.student_id)
        if s.school_year!=b.source_year:raise HTTPException(409,'שנת הלימודים השתנתה. רענני את הרשימה')
        old={'school_year':s.school_year,'classroom':decrypt(s.classroom),'archived':s.archived}
        if item.graduate:
            s.archived=True
            for a in db.scalars(select(Appointment).where(Appointment.student_id==s.id,Appointment.status=='planned',Appointment.starts_at>=datetime(int(b.target_year[:4]),9,1,tzinfo=timezone.utc))).all():a.status='cancelled'
            db.execute(delete(StudentShare).where(StudentShare.student_id==s.id))
        else:s.classroom=encrypt(item.classroom.strip());s.school_year=b.target_year
        db.add(CaseRecord(student_id=s.id,kind='year_history',actor_id=u.id,document=pack({'before':old,'target_year':b.target_year,'graduate':item.graduate})));audit(db,u,'year.rollover',s.id)
    db.commit();return {'updated':len(b.rows)}
