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
from .models import User, Student, Meeting, Appointment, Task, BackupImport, Audit
from .security import current_user, encrypt, decrypt
from .management import Proof, prove
from .schemas import StudentInput, MeetingInput
from .planning import AppointmentInput, TaskInput
router=APIRouter(prefix='/api/settings/backup')
LIMIT=20*1024*1024
class BackupProof(Proof):backup_password:str=Field(min_length=16,max_length=256)
class StoredStudent(StudentInput):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=36)
    archived:bool=False
    meetings:list[MeetingInput]=Field(default_factory=list,max_length=10000)
    appointments:list[AppointmentInput]=Field(default_factory=list,max_length=10000)
    tasks:list[TaskInput]=Field(default_factory=list,max_length=10000)
    appointment_statuses:list[str]=Field(default_factory=list,max_length=10000)
    task_statuses:list[str]=Field(default_factory=list,max_length=10000)
    @model_validator(mode='after')
    def valid(self):
        if len(self.appointments)!=len(self.appointment_statuses) or len(self.tasks)!=len(self.task_statuses):raise ValueError('Invalid statuses')
        if any(s not in ['planned','completed','cancelled'] for s in self.appointment_statuses) or any(s not in ['open','done'] for s in self.task_statuses):raise ValueError('Invalid status')
        if any(r.student_id!=self.id for r in self.appointments+self.tasks):raise ValueError('Invalid association')
        if len(self.meetings)+len(self.appointments)+len(self.tasks)>10000:raise ValueError('Too many records')
        return self
class Archive(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=1,le=1)
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
        students.append({'id':s.id,'name':decrypt(s.name),'classroom':decrypt(s.classroom),'referral':decrypt(s.referral),'archived':s.archived,
            'meetings':[{'starts_at':utc(m.starts_at).isoformat(),'notes':decrypt(m.notes),'summary':decrypt(m.summary),'ai_assisted':m.ai_assisted,'consent_recorded':m.consent_recorded,'ai_reviewed':m.ai_reviewed} for m in ms],
            'appointments':[{'student_id':s.id,'starts_at':utc(a.starts_at).isoformat(),'ends_at':utc(a.ends_at).isoformat()} for a in aps],
            'appointment_statuses':[a.status for a in aps],
            'tasks':[{'student_id':s.id,'title':decrypt(t.title),'due_at':utc(t.due_at).isoformat()} for t in ts],'task_statuses':[t.status for t in ts]})
    payload=Archive.model_validate({'version':1,'students':students}).model_dump_json().encode()
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
        row=Student(owner_id=user.id,name=encrypt(s.name),classroom=encrypt(s.classroom),referral=encrypt(s.referral),archived=s.archived)
        db.add(row);db.flush()
        for m in s.meetings:
            values=m.model_dump();values['notes']=encrypt(m.notes);values['summary']=encrypt(m.summary)
            db.add(Meeting(student_id=row.id,**values))
        for a,status in zip(s.appointments,s.appointment_statuses):
            values=a.model_dump(exclude={'student_id'});db.add(Appointment(student_id=row.id,status=status,**values))
        for t,status in zip(s.tasks,s.task_statuses):db.add(Task(student_id=row.id,title=encrypt(t.title),due_at=t.due_at,status=status))
    db.add(Audit(user_id=user.id,action='backup.restore',record_id=user.id));db.commit()
    return {'students':len(archive.students),'message':'השחזור הושלם. הכרטיסים נוספו ככרטיסים חדשים ללא הרשאות שיתוף.'}
