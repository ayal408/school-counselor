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

def test_ai_consent_authorization_and_review(setup, monkeypatch):
    c,f=setup;h=token("one");other=token("two")
    sid=c.post("/api/students",headers=h,json={"name":"בדיקה","classroom":"ח"}).json()["id"]
    from app import ai
    calls=[]
    async def fake(path, **kwargs):
        calls.append((path,kwargs))
        return {"text":"תמלול בדיקה"} if path=='audio/transcriptions' else {"choices":[{"message":{"content":"טיוטת סיכום"}}]}
    monkeypatch.setattr(ai,'provider',fake)
    monkeypatch.setenv('AI_ENABLED','false')
    assert c.get('/api/ai/status',headers=h).json()['enabled'] is False
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={"transcript":"בדיקה","consent":True}).status_code==503
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('OPENAI_API_KEY','test-not-a-real-key')
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=other,json={"transcript":"בדיקה","consent":True}).status_code==404
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={"transcript":"בדיקה"}).status_code==422
    assert calls==[]
    audio_headers={**h,'Content-Type':'audio/webm','X-Recording-Consent':'true'}
    assert c.post(f'/api/ai/students/{sid}/transcribe',headers=audio_headers,content=b'invalid').status_code==415
    result=c.post(f'/api/ai/students/{sid}/transcribe',headers=audio_headers,content=b'\x1a\x45\xdf\xa3fake-test-audio')
    assert result.json()['transcript']=='תמלול בדיקה'
    result=c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={"transcript":"תמלול בדיקה","consent":True})
    assert result.json()['draft'] is True
    assert calls[-1][1]['json']['store'] is False
    body={"starts_at":"2026-10-07T09:00:00+03:00","notes":"תמלול בדיקה","summary":"טיוטת סיכום","ai_assisted":True,"consent_recorded":True}
    assert c.post(f'/api/students/{sid}/meetings',headers=h,json=body).status_code==422
    saved=c.post(f'/api/students/{sid}/meetings',headers=h,json={**body,'ai_reviewed':True})
    assert saved.status_code==201
    from app.models import Meeting
    with f() as db:
        row=db.get(Meeting,saved.json()['id'])
        assert row.ai_assisted and row.ai_reviewed and row.consent_recorded
        assert 'תמלול' not in row.notes
    monkeypatch.setattr(ai,'MAX_AUDIO',2)
    assert c.post(f'/api/ai/students/{sid}/transcribe',headers=audio_headers,content=b'long').status_code==413

def test_multiple_providers_routing_and_secrets(setup,monkeypatch):
    import httpx,json,base64
    from app import ai
    c,_=setup;h=token('one')
    sid=c.post('/api/students',headers=h,json={'name':'בדיקה','classroom':'ח'}).json()['id']
    for key in ['OPENAI_API_KEY','GEMINI_API_KEY','GROQ_API_KEY']:monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','private-gemini-test-key');monkeypatch.setenv('GROQ_API_KEY','private-groq-test-key')
    info=c.get('/api/ai/status',headers=h).json()
    assert info['default_provider']=='gemini'
    assert 'private-' not in json.dumps(info)
    assert [p['enabled'] for p in info['providers']]==[False,True,True]
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.host=='generativelanguage.googleapis.com':
            payload=json.loads(request.content)
            assert request.headers['x-goog-api-key']=='private-gemini-test-key'
            assert 'private-' not in str(request.url)
            if 'inlineData' in payload['contents'][0]['parts'][-1]:
                part=payload['contents'][0]['parts'][-1]['inlineData']
                assert base64.b64decode(part['data']).startswith(b'\x1a\x45\xdf\xa3')
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'hidden reasoning','thought':True},{'text':'תוצר בדיקה'}]}}]})
        assert request.url.host=='api.groq.com'
        assert request.headers['Authorization']=='Bearer private-groq-test-key'
        if request.url.path.endswith('audio/transcriptions'):return httpx.Response(200,json={'text':'תמלול Groq'})
        payload=json.loads(request.content)
        assert 'store' not in payload
        assert payload['model']=='openai/gpt-oss-120b'
        return httpx.Response(200,json={'choices':[{'message':{'content':'סיכום Groq'}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    header={**h,'Content-Type':'audio/webm','X-Recording-Consent':'true','X-AI-Provider':'gemini'}
    a=c.post(f'/api/ai/students/{sid}/transcribe',headers=header,content=b'\x1a\x45\xdf\xa3sample')
    assert a.status_code==200 and a.json()['transcript']=='תוצר בדיקה'
    result=c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={'transcript':'בדיקה','consent':True,'provider':'groq'})
    assert result.json()['summary']=='סיכום Groq'
    result=c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={'transcript':'בדיקה','consent':True,'provider':'gemini'})
    assert result.json()['summary']=='תוצר בדיקה'
    header['X-AI-Provider']='groq'
    assert c.post(f'/api/ai/students/{sid}/transcribe',headers=header,content=b'\x1a\x45\xdf\xa3sample').json()['transcript']=='תמלול Groq'
    before=len(seen)
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={'transcript':'בדיקה','consent':True,'provider':'untrusted'}).status_code==422
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={'transcript':'בדיקה','consent':True,'provider':'openai'}).status_code==503
    assert len(seen)==before

def proof(**extra):return {'password':'long-test-password',**extra}
def make_admin(factory):
    with factory() as db:db.get(User,'one').role='admin';db.commit()

def test_administration_and_session_revocation(setup):
    c,f=setup;h=token('one');other=token('two')
    assert c.get('/api/admin/users',headers=h).status_code==403
    make_admin(f)
    assert c.get('/api/admin/users',headers=h).status_code==200
    body=proof(email='three@example.test',name='שלישית',new_password='another-long-password',role='counselor')
    assert c.post('/api/admin/users',headers=other,json=body).status_code==403
    assert c.post('/api/admin/users',headers=h,json={**body,'password':'wrong'}).status_code==401
    uid=c.post('/api/admin/users',headers=h,json=body).json()['id']
    assert c.post('/api/admin/users',headers=h,json=body).status_code==409
    assert c.patch('/api/admin/users/one',headers=h,json=proof(active=False,role='counselor')).status_code==409
    assert c.patch('/api/admin/users/two',headers=h,json=proof(active=False,role='counselor')).status_code==200
    assert c.get('/api/students',headers=other).status_code==401
    assert c.patch('/api/admin/users/two',headers=h,json=proof(active=True,role='counselor')).status_code==200
    assert c.get('/api/students',headers=other).status_code==401 # old JWT stays revoked
    assert uid in [u['id'] for u in c.get('/api/admin/users',headers=h).json()]

def test_read_only_share_and_revocation(setup):
    c,_=setup;h=token('one');other=token('two')
    sid=c.post('/api/students',headers=h,json={'name':'משותפת','classroom':'ח'}).json()['id']
    c.post(f'/api/students/{sid}/meetings',headers=h,json={'starts_at':'2026-10-07T09:00:00Z','notes':'תיעוד'})
    c.post('/api/tasks',headers=h,json={'student_id':sid,'title':'מעקב','due_at':'2026-10-08T09:00:00Z'})
    assert c.post(f'/api/students/{sid}/shares',headers=h,json=proof(user_id='two')).status_code==200
    assert c.get('/api/students',headers=other).json()[0]['can_edit'] is False
    assert c.get(f'/api/students/{sid}/meetings',headers=other).json()[0]['notes']=='תיעוד'
    assert len(c.get('/api/tasks',headers=other).json())==1
    assert c.post(f'/api/students/{sid}/archive',headers=other).status_code==404
    assert c.post(f'/api/students/{sid}/shares',headers=other,json=proof(user_id='one')).status_code==404
    assert c.post('/api/tasks',headers=other,json={'student_id':sid,'title':'שינוי','due_at':'2026-10-08T09:00:00Z'}).status_code==404
    assert c.post(f'/api/students/{sid}/shares/two/revoke',headers=h,json=proof()).status_code==200
    assert c.get('/api/students',headers=other).json()==[]
    assert c.get(f'/api/students/{sid}/meetings',headers=other).status_code==404

def test_mfa_rfc_vectors_enrollment_login_replay_recovery(setup):
    import base64,time
    from app.mfa import totp
    secret=base64.b32encode(b'12345678901234567890').decode()
    # SHA-1 RFC 6238 Appendix B, independently specified vectors.
    assert totp(secret,59//30,8)=='94287082'
    assert totp(secret,1111111109//30,8)=='07081804'
    c,f=setup;h=token('one');internal={'X-Internal-Key':os.environ['INTERNAL_SERVICE_KEY']}
    setup_result=c.post('/api/settings/mfa/setup',headers=h,json=proof()).json()
    secret=setup_result['secret'];step=int(time.time()//30)
    result=c.post('/api/settings/mfa/confirm',headers=h,json=proof(otp=totp(secret,step)))
    assert result.status_code==200
    codes=result.json()['recovery_codes'];assert len(codes)==10
    assert c.get('/api/me',headers=h).status_code==401
    login={'email':'one@example.test','password':'long-test-password'}
    assert c.post('/internal/verify-password',headers=internal,json=login).status_code==401
    assert c.post('/internal/verify-password',headers=internal,json={**login,'otp':totp(secret,step)}).status_code==401
    assert c.post('/internal/verify-password',headers=internal,json={**login,'otp':codes[0]}).status_code==200
    assert c.post('/internal/verify-password',headers=internal,json={**login,'otp':codes[0]}).status_code==401
    with f() as db:
        u=db.get(User,'one');assert secret not in u.mfa_secret and codes[0] not in u.recovery_hashes
    assert c.post('/internal/sessions',headers=internal,json={'token_hash':'c'*64,'user_id':'one','expires_at':'2026-12-01T00:00:00Z','session_version':0}).status_code==401

def test_lockout_and_invalid_setup_codes(setup):
    c,_=setup;h=token('one');internal={'X-Internal-Key':os.environ['INTERNAL_SERVICE_KEY']}
    c.post('/api/settings/mfa/setup',headers=h,json=proof())
    for _ in range(5):assert c.post('/api/settings/mfa/confirm',headers=h,json=proof(otp='invalid')).status_code==422
    assert c.post('/api/settings/mfa/setup',headers=h,json=proof()).status_code==401
    for _ in range(5):assert c.post('/internal/verify-password',headers=internal,json={'email':'two@example.test','password':'wrong'}).status_code==401
    assert c.post('/internal/verify-password',headers=internal,json={'email':'two@example.test','password':'long-test-password'}).status_code==401

def test_personal_ai_encryption_isolation_and_runtime(setup,monkeypatch):
    import json
    from app.models import AIConfig
    from app import ai
    c,f=setup;h=token('one');other=token('two')
    body=proof(api_key='private-personal-key',enabled=True,preferred=True,transcription_model='whisper-1',summary_model='gpt-4.1-mini')
    assert c.put('/api/settings/ai/openai',headers=h,json=body).status_code==200
    with f() as db:assert 'private-personal-key' not in db.get(AIConfig,('one','openai')).key
    assert 'private-personal-key' not in json.dumps(c.get('/api/settings/ai',headers=h).json())
    monkeypatch.setenv('AI_ENABLED','false')
    assert c.get('/api/ai/status',headers=h).json()['enabled'] is True
    assert c.get('/api/ai/status',headers=other).json()['enabled'] is False
    sid=c.post('/api/students',headers=h,json={'name':'בדיקה','classroom':'ח'}).json()['id']
    async def fake(path,**kwargs):
        assert ai.ai_runtime.get()['openai']['key']=='private-personal-key'
        return {'choices':[{'message':{'content':'סיכום'}}]}
    monkeypatch.setattr(ai,'provider',fake)
    assert c.post(f'/api/ai/students/{sid}/summarize',headers=h,json={'transcript':'בדיקה','consent':True}).status_code==200
    assert c.put('/api/settings/ai/openai',headers=h,json={**body,'api_key':'','enabled':False,'clear_key':True}).status_code==200
    assert c.get('/api/ai/status',headers=h).json()['enabled'] is False

def test_encrypted_backup_roundtrip_wrong_password_and_duplicate(setup):
    import json
    from app.models import Meeting,StudentShare
    c,f=setup;h=token('one');other=token('two')
    sid=c.post('/api/students',headers=h,json={'name':'תלמידת גיבוי','classroom':'ח','referral':'מידע'}).json()['id']
    c.post(f'/api/students/{sid}/meetings',headers=h,json={'starts_at':'2026-10-07T09:00:00Z','notes':'מידע רגיש'})
    c.post('/api/tasks',headers=h,json={'student_id':sid,'title':'משימה','due_at':'2026-10-08T09:00:00Z'})
    c.post('/api/appointments',headers=h,json={'student_id':sid,'starts_at':'2026-10-08T10:00:00Z','ends_at':'2026-10-08T11:00:00Z'})
    b=proof(backup_password='separate-backup-password')
    archive=c.post('/api/settings/backup/export',headers=h,json=b).json()
    assert 'מידע' not in json.dumps(archive) and 'תלמידת' not in json.dumps(archive)
    body={**b,'archive':archive,'confirmed':True}
    assert c.post('/api/settings/backup/restore',headers=other,json={**body,'backup_password':'wrong-backup-password'}).status_code==422
    assert c.get('/api/students',headers=other).json()==[]
    assert c.post('/api/settings/backup/restore',headers=other,json=body).json()['students']==1
    assert c.post('/api/settings/backup/restore',headers=other,json=body).status_code==409
    rows=c.get('/api/students',headers=other).json();assert len(rows)==1 and rows[0]['name']=='תלמידת גיבוי'
    new_sid=rows[0]['id'];assert new_sid!=sid
    assert c.get(f'/api/students/{new_sid}/meetings',headers=other).json()[0]['notes']=='מידע רגיש'
    assert len(c.get('/api/tasks',headers=other).json())==1 and len(c.get('/api/appointments',headers=other).json())==1
    with f() as db:
        assert 'רגיש' not in db.scalar(select(Meeting).where(Meeting.student_id==new_sid)).notes
        assert db.get(User,'one').last_backup is not None
        assert db.scalars(select(StudentShare)).all()==[]

def test_ai_connection_test_uses_saved_key_and_no_student_content(setup,monkeypatch):
    import httpx
    from app import ai
    c,_=setup;h=token('one');other=token('two')
    c.put('/api/settings/ai/groq',headers=h,json=proof(api_key='test-private-key',enabled=True,transcription_model='whisper-large-v3',summary_model='openai/gpt-oss-120b'))
    seen=[]
    def handler(request):
        seen.append(request)
        assert request.method=='GET' and request.url.host=='api.groq.com' and request.url.path=='/openai/v1/models'
        assert request.headers['Authorization']=='Bearer test-private-key' and not request.content
        return httpx.Response(200,json={'data':[]})
    original=httpx.AsyncClient
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    result=c.post('/api/settings/ai/groq/test',headers=h,json=proof())
    assert result.status_code==200 and 'test-private-key' not in result.text
    assert c.post('/api/settings/ai/groq/test',headers=other,json=proof()).status_code==422
    assert len(seen)==1
