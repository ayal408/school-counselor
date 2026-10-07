from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, delete, text
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from .database import get_db
from .models import User, Student, Meeting, RefreshSession, Audit
from .schemas import StudentInput, MeetingInput, LoginInput, SessionCreate, SessionInput, SessionRotate
from .security import internal, current_user, encrypt, decrypt, visible_condition, readable_student
app = FastAPI(title="School Counselor Data API", docs_url=None, redoc_url=None)
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("timing-equalization-only")
@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": "יש לבדוק את השדות ואת פורמט התאריך"})
def audit(db, user, action, record): db.add(Audit(user_id=user.id, action=action, record_id=record))
def owned(db, user, sid):
    s = db.scalar(select(Student).where(Student.id == sid, Student.owner_id == user.id))
    if not s: raise HTTPException(404, "התלמידה לא נמצאה")
    return s
def student_json(s, user=None):
    return {"id": s.id, "name": decrypt(s.name), "classroom": decrypt(s.classroom), "referral": decrypt(s.referral), "archived": s.archived, "can_edit": user is None or s.owner_id == user.id}
def meeting_json(m):
    return {"id": m.id, "student_id": m.student_id, "starts_at": m.starts_at, "notes": decrypt(m.notes), "summary": decrypt(m.summary), "ai_assisted": m.ai_assisted, "ai_reviewed": m.ai_reviewed}
@app.get("/healthz/live")
def live(): return {"status": "ok"}
@app.get("/healthz/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1")); return {"status": "ok"}
@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "session_version": user.session_version}
@app.get("/api/students")
def students(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Student).where(visible_condition(user)).order_by(Student.created_at.desc())).all()
    audit(db, user, "students.list", user.id); db.commit()
    return [student_json(s,user) for s in rows]
@app.post("/api/students", status_code=201)
def create_student(body: StudentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = Student(owner_id=user.id, name=encrypt(body.name), classroom=encrypt(body.classroom), referral=encrypt(body.referral))
    db.add(s); db.flush(); audit(db, user, "student.create", s.id); db.commit(); return student_json(s)
@app.put("/api/students/{sid}")
def update_student(sid: str, body: StudentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, user, sid)
    s.name, s.classroom, s.referral = encrypt(body.name), encrypt(body.classroom), encrypt(body.referral)
    audit(db, user, "student.update", s.id); db.commit(); return student_json(s)
@app.post("/api/students/{sid}/archive")
def archive(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, user, sid); s.archived = True
    audit(db, user, "student.archive", s.id); db.commit(); return student_json(s)
@app.get("/api/students/{sid}/meetings")
def meetings(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    readable_student(db, user, sid)
    rows = db.scalars(select(Meeting).where(Meeting.student_id == sid).order_by(Meeting.starts_at.desc())).all()
    audit(db, user, "meetings.list", sid); db.commit(); return [meeting_json(m) for m in rows]
@app.post("/api/students/{sid}/meetings", status_code=201)
def add_meeting(sid: str, body: MeetingInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, user, sid)
    if s.archived: raise HTTPException(409, "הכרטיס בארכיון")
    m = Meeting(student_id=sid, starts_at=body.starts_at, notes=encrypt(body.notes), summary=encrypt(body.summary), ai_assisted=body.ai_assisted, consent_recorded=body.consent_recorded, ai_reviewed=body.ai_reviewed)
    db.add(m); db.flush(); audit(db, user, "meeting.create", m.id); db.commit(); return meeting_json(m)
@app.post("/internal/verify-password", dependencies=[Depends(internal)])
def verify(body: LoginInput, db: Session = Depends(get_db)):
    from .mfa import authenticate
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    user = authenticate(db,user,body.password,body.otp)
    db.commit()
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "session_version": user.session_version}
@app.post("/internal/sessions", dependencies=[Depends(internal)], status_code=201)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    u = db.get(User, body.user_id)
    if not u or not u.active or u.session_version != body.session_version: raise HTTPException(401)
    db.add(RefreshSession(**body.model_dump(exclude={"session_version"}))); db.commit(); return {"ok": True}
@app.post("/internal/sessions/rotate", dependencies=[Depends(internal)])
def rotate(body: SessionRotate, db: Session = Depends(get_db)):
    # Atomic consume: parallel refreshes cannot both succeed.
    row = db.execute(delete(RefreshSession).where(RefreshSession.token_hash == body.token_hash, RefreshSession.expires_at > datetime.now(timezone.utc)).returning(RefreshSession.user_id)).first()
    if not row: raise HTTPException(401, "ההתחברות פגה")
    user = db.get(User, row[0])
    if not user or not user.active: db.commit(); raise HTTPException(401)
    db.add(RefreshSession(token_hash=body.new_hash, user_id=user.id, expires_at=body.expires_at)); db.commit()
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "session_version": user.session_version}
@app.post("/internal/sessions/revoke", dependencies=[Depends(internal)])
def revoke(body: SessionInput, db: Session = Depends(get_db)):
    db.execute(delete(RefreshSession).where(RefreshSession.token_hash == body.token_hash)); db.commit(); return {"ok": True}

from .planning import router as planning_router
app.include_router(planning_router)

from .ai import router as ai_router
app.include_router(ai_router)

@app.middleware("http")
async def limit_ai_memory(request, call_next):
    if request.url.path.startswith("/api/ai/students/"):
        from .ai import processing_slots
        async with processing_slots:
            return await call_next(request)
    return await call_next(request)

from .management import router as management_router
from .backups import router as backups_router
app.include_router(management_router)
app.include_router(backups_router)

from .email_api import router as email_router
from .account_email import router as account_email_router
app.include_router(email_router)
app.include_router(account_email_router)
