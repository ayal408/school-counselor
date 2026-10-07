import os, sys, hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest, jwt
from cryptography.fernet import Fernet
os.environ["JWT_SECRET"] = "test-only-" + "x"*40
os.environ["INTERNAL_SERVICE_KEY"] = "test-only-" + "y"*40
os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app, hasher
from app.models import Base, User, Student
from app.database import get_db
@pytest.fixture()
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id="one", email="one@example.test", name="One", password_hash=hasher.hash("long-test-password")), User(id="two", email="two@example.test", name="Two", password_hash=hasher.hash("long-test-password"))]); db.commit()
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client: yield client, factory
    app.dependency_overrides.clear(); engine.dispose()
def token(uid):
    now = datetime.now(timezone.utc)
    return {"Authorization": "Bearer " + jwt.encode({"sub": uid, "iat": now, "exp": now+timedelta(minutes=5), "iss": "counselor-auth", "aud": "counselor-api"}, os.environ["JWT_SECRET"], algorithm="HS256")}
def test_auth_required(setup):
    c,_=setup
    assert c.get("/api/students").status_code == 401
    assert c.post("/internal/verify-password", json={"email":"one@example.test","password":"long-test-password"}).status_code == 403
def test_student_isolation_and_encryption(setup):
    c,f=setup
    created=c.post("/api/students", headers=token("one"), json={"name":"תלמידת בדיקה","classroom":"ז1","referral":"מידע רגיש"})
    assert created.status_code==201
    sid=created.json()["id"]
    assert c.get("/api/students",headers=token("two")).json()==[]
    assert c.get(f"/api/students/{sid}/meetings",headers=token("two")).status_code==404
    assert c.put(f"/api/students/{sid}",headers=token("two"),json={"name":"אחר","classroom":"ז2"}).status_code==404
    with f() as db:
        row=db.get(Student,sid)
        assert "תלמידת" not in row.name and "מידע" not in row.referral
    assert c.get("/api/students",headers=token("one")).json()[0]["name"]=="תלמידת בדיקה"
def test_meeting_and_archive(setup):
    c,_=setup; h=token("one")
    sid=c.post("/api/students",headers=h,json={"name":"בדיקה","classroom":"ח"}).json()["id"]
    body={"starts_at":"2026-10-07T09:00:00+03:00","notes":"תיעוד","summary":"המשך"}
    assert c.post(f"/api/students/{sid}/meetings",headers=token("two"),json=body).status_code==404
    assert c.post(f"/api/students/{sid}/meetings",headers=h,json=body).status_code==201
    assert c.get(f"/api/students/{sid}/meetings",headers=h).json()[0]["notes"]=="תיעוד"
    assert c.post(f"/api/students/{sid}/archive",headers=h).status_code==200
    assert c.post(f"/api/students/{sid}/meetings",headers=h,json=body).status_code==409
def test_refresh_single_use_and_disabled_user(setup):
    c,f=setup; h={"X-Internal-Key":os.environ["INTERNAL_SERVICE_KEY"]}
    old=hashlib.sha256(b"old").hexdigest(); new=hashlib.sha256(b"new").hexdigest()
    expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    assert c.post("/internal/sessions",headers=h,json={"token_hash":old,"user_id":"one","expires_at":expiry}).status_code==201
    body={"token_hash":old,"new_hash":new,"expires_at":expiry}
    assert c.post("/internal/sessions/rotate",headers=h,json=body).status_code==200
    assert c.post("/internal/sessions/rotate",headers=h,json=body).status_code==401
    with f() as db:
        db.get(User,"one").active=False;db.commit()
    assert c.get("/api/me",headers=token("one")).status_code==401
def test_password_verification(setup):
    c,_=setup;h={"X-Internal-Key":os.environ["INTERNAL_SERVICE_KEY"]}
    assert c.post("/internal/verify-password",headers=h,json={"email":"one@example.test","password":"wrong"}).status_code==401
    assert c.post("/internal/verify-password",headers=h,json={"email":"one@example.test","password":"long-test-password"}).json()["id"]=="one"

def test_planning_privacy_conflicts_tasks(setup):
    c,f=setup;h=token("one");other=token("two")
    sid=c.post("/api/students",headers=h,json={"name":"בדיקה","classroom":"ח"}).json()["id"]
    appointment={"student_id":sid,"starts_at":"2026-10-07T09:00:00+03:00","ends_at":"2026-10-07T10:00:00+03:00"}
    assert c.post("/api/appointments",headers=other,json=appointment).status_code==404
    a=c.post("/api/appointments",headers=h,json=appointment).json()
    assert c.post("/api/appointments",headers=h,json=appointment).status_code==409
    assert c.get("/api/appointments",headers=other).json()==[]
    assert c.patch('/api/appointments/'+a['id'],headers=other,json={"status":"cancelled"}).status_code==404
    assert c.patch('/api/appointments/'+a['id'],headers=h,json={"status":"cancelled"}).status_code==200
    assert c.post("/api/appointments",headers=h,json=appointment).status_code==201
    assert c.patch('/api/appointments/'+a['id'],headers=h,json={"status":"planned"}).status_code==409
    body={"student_id":sid,"title":"מעקב רגיש","due_at":"2026-10-08T09:00:00+03:00"}
    t=c.post("/api/tasks",headers=h,json=body).json()
    assert c.get("/api/tasks",headers=other).json()==[]
    assert c.patch('/api/tasks/'+t['id'],headers=other,json={"status":"done"}).status_code==404
    assert c.patch('/api/tasks/'+t['id'],headers=h,json={"status":"done"}).json()['status']=='done'
    from app.models import Task
    with f() as db: assert 'רגיש' not in db.get(Task,t['id']).title
    assert c.post("/api/tasks",headers=h,json={**body,"title":"  "}).status_code==422
    assert c.post("/api/appointments",headers=h,json={**appointment,"ends_at":appointment['starts_at']}).status_code==422
