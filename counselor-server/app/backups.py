"""Password encrypted, portable personal data export and non-destructive import."""
import base64, hashlib, json, secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict, ValidationError, model_validator
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, Student, Meeting, Appointment, Task, BackupImport, Audit, CaseRecord, CaseConsent, MeetingRevision
from .security import current_user, encrypt, decrypt
from .management import Proof, prove
from .schemas import StudentInput, MeetingInput
from .planning import AppointmentInput, TaskInput
from .casework import pack, unpack, snapshot, apply, Contact, Plan, DraftDocument, Consent, TOPICS
from .mfa import utc
from typing import Literal
class StoredTask(TaskInput):
    id:str=Field(default="",max_length=36)
class StoredRevision(BaseModel):
    version:int=Field(ge=1)
    at:datetime
    actor:str=Field(max_length=120)
    document:MeetingInput
class StoredMeeting(MeetingInput):
    id:str=Field(default="",max_length=36)
    version:int=Field(default=1,ge=1)
    revisions:list[StoredRevision]=Field(default_factory=list,max_length=10000)
class StoredRecord(BaseModel):
    id:str=Field(max_length=36)
    actor:str=Field(default="",max_length=120)
    kind:Literal["contact","plan","draft","plan_history","year_history","decision_task"]
    version:int=Field(ge=1)
    document:dict
    at:datetime
    @model_validator(mode="after")
    def validate_document(self):
        if len(json.dumps(self.document))>100000:raise ValueError("Record too big")
        schema={"contact":Contact,"plan":Plan,"draft":DraftDocument}.get(self.kind)
        if schema:schema.model_validate(self.document)
        return self
class StoredConsent(Consent):revoked:bool=False
router=APIRouter(prefix='/api/settings/backup')
LIMIT=20*1024*1024
class BackupProof(Proof):backup_password:str=Field(min_length=16,max_length=256)
class StoredStudent(StudentInput):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=36)
    archived:bool=False
    school_year:str=Field(default="2026-2027",pattern=r"^\d{4}-\d{4}$")
    records:list[StoredRecord]=Field(default_factory=list,max_length=10000)
    consents:list[StoredConsent]=Field(default_factory=list,max_length=10000)
    meetings:list[StoredMeeting]=Field(default_factory=list,max_length=10000)
    appointments:list[AppointmentInput]=Field(default_factory=list,max_length=10000)
    tasks:list[StoredTask]=Field(default_factory=list,max_length=10000)
    appointment_statuses:list[str]=Field(default_factory=list,max_length=10000)
    task_statuses:list[str]=Field(default_factory=list,max_length=10000)
    @model_validator(mode='after')
    def valid(self):
        if len(self.appointments)!=len(self.appointment_statuses) or len(self.tasks)!=len(self.task_statuses):raise ValueError('Invalid statuses')
        if any(s not in ['planned','completed','cancelled'] for s in self.appointment_statuses) or any(s not in ['open','done'] for s in self.task_statuses):raise ValueError('Invalid status')
        if any(r.student_id!=self.id for r in self.appointments+self.tasks):raise ValueError('Invalid association')
        if len({t.id for t in self.tasks if t.id})!=sum(bool(t.id) for t in self.tasks):raise ValueError("Invalid task identities")
        mids={m.id for m in self.meetings if m.id}
        if len(mids)!=sum(bool(m.id) for m in self.meetings) or any(r.kind=="draft" and r.document.get("_meeting_id") and r.document["_meeting_id"] not in mids for r in self.records):raise ValueError("Invalid meeting identities")
        if len({r.id for r in self.records})!=len(self.records) or len({r.document.get('_meeting_id','') for r in self.records if r.kind=='draft'})!=sum(r.kind=='draft' for r in self.records):raise ValueError("Invalid record identities")
        if len(self.meetings)+len(self.appointments)+len(self.tasks)+len(self.records)+len(self.consents)>10000:raise ValueError('Too many records')
        return self
class Archive(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=1,le=2)
    students:list[StoredStudent]=Field(max_length=5000)
def key(password,salt):
    return Fernet(base64.urlsafe_b64encode(PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=600000).derive(password.encode())))
@router.post('/export')
def export(body:BackupProof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    prove(db,user,body)
    students=[]
    for s in db.scalars(select(Student).where(Student.owner_id==user.id)).all():
        ms=db.scalars(select(Meeting).where(Meeting.student_id==s.id)).all()
        aps=db.scalars(select(Appointment).where(Appointment.student_id==s.id)).all()
        ts=db.scalars(select(Task).where(Task.student_id==s.id)).all()
        from .mfa import utc
        students.append({'id':s.id,'name':decrypt(s.name),'classroom':decrypt(s.classroom),'referral':decrypt(s.referral),'archived':s.archived,'school_year':s.school_year,
            'records':[{'id':r.id,'kind':r.kind,'actor':unpack(r.document).get('_source_actor',db.get(User,r.actor_id).name),'version':r.version,'at':utc(r.updated_at).isoformat(),'document':unpack(r.document)} for r in db.scalars(select(CaseRecord).where(CaseRecord.student_id==s.id,CaseRecord.kind.in_(['contact','plan','draft','plan_history','year_history','decision_task']))).all()],
            'consents':[dict(purpose=r.purpose,recipient=r.recipient,granted_at=utc(r.granted_at).isoformat(),expires_at=utc(r.expires_at).isoformat(),evidence=decrypt(r.evidence),revoked=r.revoked) for r in db.scalars(select(CaseConsent).where(CaseConsent.student_id==s.id)).all()],
            'meetings':[dict(snapshot(m),id=m.id,version=m.version,revisions=[{'version':v.version,'at':utc(v.created_at).isoformat(),'actor':db.get(User,v.actor_id).name if v.actor_id else unpack(v.document).get('source_actor','תיעוד קודם'),'document':unpack(v.document)} for v in db.scalars(select(MeetingRevision).where(MeetingRevision.meeting_id==m.id)).all()]) for m in ms],
            'appointments':[{'student_id':s.id,'starts_at':utc(a.starts_at).isoformat(),'ends_at':utc(a.ends_at).isoformat()} for a in aps],
            'appointment_statuses':[a.status for a in aps],
            'tasks':[{'id':t.id,'student_id':s.id,'title':decrypt(t.title),'due_at':utc(t.due_at).isoformat()} for t in ts],'task_statuses':[t.status for t in ts]})
    payload=Archive.model_validate({'version':2,'students':students}).model_dump_json().encode()
    if len(payload)>LIMIT//2:raise HTTPException(413,'הגיבוי גדול מדי לייצוא דרך הממשק')
    salt=secrets.token_bytes(16);token=key(body.backup_password,salt).encrypt(payload).decode()
    user.last_backup=datetime.now(timezone.utc);db.add(Audit(user_id=user.id,action='backup.export',record_id=user.id));db.commit()
    return {'format':'merhav-backup-v1','salt':base64.b64encode(salt).decode(),'data':token}
class Restore(BackupProof):
    archive:dict
    confirmed:bool=False
@router.post('/restore')
async def restore(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>LIMIT:raise HTTPException(413,'קובץ גדול מדי')
        data.extend(chunk)
    try:body=Restore.model_validate_json(data)
    except ValidationError:raise HTTPException(422,'בקשת שחזור אינה תקינה')
    prove(db,user,body)
    if not body.confirmed:raise HTTPException(422,'יש לאשר שהשחזור מוסיף כרטיסים חדשים')
    try:
        a=body.archive
        if set(a)!= {'format','salt','data'} or a['format']!='merhav-backup-v1':raise ValueError()
        salt=base64.b64decode(a['salt'],validate=True)
        if len(salt)!=16:raise ValueError()
        plaintext=key(body.backup_password,salt).decrypt(a['data'].encode())
        archive=Archive.model_validate_json(plaintext)
        if len({s.id for s in archive.students})!=len(archive.students):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError,InvalidToken):raise HTTPException(422,'הסיסמה שגויה או שקובץ הגיבוי אינו תקין')
    receipt=hashlib.sha256(a['data'].encode()).hexdigest()
    if db.get(BackupImport,(user.id,receipt)):raise HTTPException(409,'גיבוי זה כבר שוחזר בחשבונך')
    db.add(BackupImport(user_id=user.id,digest=receipt))
    try:db.flush()
    except IntegrityError:db.rollback();raise HTTPException(409,'גיבוי זה כבר שוחזר בחשבונך')
    for s in archive.students:
        row=Student(owner_id=user.id,name=encrypt(s.name),classroom=encrypt(s.classroom),referral=encrypt(s.referral),archived=s.archived,school_year=s.school_year)
        db.add(row);db.flush()
        meeting_ids={}
        for m in s.meetings:
            meeting=Meeting(student_id=row.id);apply(meeting,m);meeting.version=m.version;db.add(meeting);db.flush();meeting_ids[m.id]=meeting.id
            if len({v.version for v in m.revisions})!=len(m.revisions) or any(v.version>m.version for v in m.revisions):raise HTTPException(422,'גרסאות גיבוי אינן תקינות')
            for v in m.revisions:
                db.add(MeetingRevision(meeting_id=meeting.id,version=v.version,actor_id=None,created_at=v.at,document=pack(dict(v.document.model_dump(),source_actor=v.actor))))
        task_ids={t.id:__import__('uuid').uuid4().__str__() for t in s.tasks if t.id}
        record_ids={r.id:__import__('uuid').uuid4().__str__() for r in s.records}
        for r in s.records:
            document=dict(r.document)
            if r.actor:document["_source_actor"]=r.actor
            if r.kind=='plan_history':document['plan_id']=record_ids.get(document.get('plan_id'),'')
            if r.kind=='draft' and document.get('_meeting_id'):document['_meeting_id']=meeting_ids.get(document['_meeting_id'],'')
            if r.kind=='decision_task':
                parts=document.get('key','').split(':')
                if len(parts)!=3 or parts[0] not in meeting_ids or document.get('task_id') not in task_ids:continue
                document['key']=':'.join([meeting_ids[parts[0]],*parts[1:]]);document['task_id']=task_ids[document['task_id']]
            db.add(CaseRecord(id=record_ids[r.id],student_id=row.id,kind=r.kind,actor_id=user.id,version=r.version,document=pack(document),updated_at=r.at,created_at=r.at))
        for c in s.consents:
            values=c.model_dump();values['evidence']=encrypt(c.evidence)
            # A restored archive cannot grant access to another account.
            if c.purpose=='sharing':values['revoked']=True
            db.add(CaseConsent(student_id=row.id,actor_id=user.id,**values))
        for a,status in zip(s.appointments,s.appointment_statuses):
            values=a.model_dump(exclude={'student_id'});db.add(Appointment(student_id=row.id,status=status,**values))
        for t,status in zip(s.tasks,s.task_statuses):db.add(Task(id=task_ids.get(t.id) or __import__('uuid').uuid4().__str__(),student_id=row.id,title=encrypt(t.title),due_at=t.due_at,status=status))
    db.add(Audit(user_id=user.id,action='backup.restore',record_id=user.id));db.commit()
    return {'students':len(archive.students),'message':'השחזור הושלם. הכרטיסים נוספו ככרטיסים חדשים ללא הרשאות שיתוף.'}
