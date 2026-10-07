from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, Student, Appointment, Task, Audit
from .security import current_user, encrypt, decrypt, visible_condition
router = APIRouter(prefix="/api")
class AppointmentInput(BaseModel):
    student_id: str
    starts_at: datetime
    ends_at: datetime
    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None: raise ValueError("נדרש אזור זמן")
        return value
    @model_validator(mode="after")
    def interval(self):
        if self.ends_at <= self.starts_at: raise ValueError("שעת הסיום חייבת להיות לאחר ההתחלה")
        return self
class AppointmentStatus(BaseModel):
    status: Literal["planned", "completed", "cancelled"]
class TaskInput(BaseModel):
    student_id: str
    title: str = Field(min_length=1, max_length=2000)
    due_at: datetime
    @field_validator("title")
    @classmethod
    def title_required(cls, value):
        if not value.strip(): raise ValueError("שדה חובה")
        return value.strip()
    @field_validator("due_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None: raise ValueError("נדרש אזור זמן")
        return value
class TaskStatus(BaseModel):
    status: Literal["open", "done"]
def student(db, user, sid):
    row = db.scalar(select(Student).where(Student.id == sid, Student.owner_id == user.id))
    if not row: raise HTTPException(404, "התלמידה לא נמצאה")
    return row
def owned_record(db, user, model, rid):
    row = db.scalar(select(model).join(Student, model.student_id == Student.id).where(model.id == rid, Student.owner_id == user.id))
    if not row: raise HTTPException(404, "הרשומה לא נמצאה")
    return row
def audit(db, user, action, rid): db.add(Audit(user_id=user.id, action=action, record_id=rid))
def appointment_json(a):
    return {"id": a.id, "student_id": a.student_id, "starts_at": a.starts_at, "ends_at": a.ends_at, "status": a.status}
def task_json(t):
    return {"id": t.id, "student_id": t.student_id, "title": decrypt(t.title), "due_at": t.due_at, "status": t.status}
@router.get("/appointments")
def appointments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Appointment).join(Student).where(visible_condition(user)).order_by(Appointment.starts_at)).all()
    audit(db,user,"appointments.list",user.id);db.commit()
    return [appointment_json(a) for a in rows]
@router.post("/appointments", status_code=201)
def create_appointment(body: AppointmentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = student(db,user,body.student_id)
    if s.archived: raise HTTPException(409, "הכרטיס בארכיון")
    # Serialize planning requests for one counselor, including across API workers.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    overlap = db.scalar(select(Appointment.id).join(Student).where(Student.owner_id == user.id, Appointment.status == "planned", Appointment.starts_at < body.ends_at, Appointment.ends_at > body.starts_at).limit(1))
    if overlap: raise HTTPException(409, "כבר מתוכננת פגישה בשעות אלו")
    row = Appointment(**body.model_dump());db.add(row);db.flush();audit(db,user,"appointment.create",row.id);db.commit()
    return appointment_json(row)
@router.patch("/appointments/{rid}")
def change_appointment(rid: str, body: AppointmentStatus, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = owned_record(db,user,Appointment,rid)
    if body.status == "planned" and row.status != "planned":
        overlap = db.scalar(select(Appointment.id).join(Student).where(Student.owner_id == user.id, Appointment.id != rid, Appointment.status == "planned", Appointment.starts_at < row.ends_at, Appointment.ends_at > row.starts_at).limit(1))
        if overlap: raise HTTPException(409, "כבר מתוכננת פגישה בשעות אלו")
    row.status=body.status;audit(db,user,"appointment.status",rid);db.commit();return appointment_json(row)
@router.get("/tasks")
def tasks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows=db.scalars(select(Task).join(Student).where(visible_condition(user)).order_by(Task.due_at)).all()
    audit(db,user,"tasks.list",user.id);db.commit();return [task_json(t) for t in rows]
@router.post("/tasks", status_code=201)
def create_task(body: TaskInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s=student(db,user,body.student_id)
    if s.archived: raise HTTPException(409, "הכרטיס בארכיון")
    row=Task(student_id=body.student_id,title=encrypt(body.title),due_at=body.due_at)
    db.add(row);db.flush();audit(db,user,"task.create",row.id);db.commit();return task_json(row)
@router.patch("/tasks/{rid}")
def change_task(rid: str, body: TaskStatus, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row=owned_record(db,user,Task,rid);row.status=body.status
    audit(db,user,"task.status",rid);db.commit();return task_json(row)
