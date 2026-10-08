"""New workflows use synthetic records only; provider traffic is mocked."""
import json
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from test_api import setup,token,proof,grant
from app.models import Meeting,MeetingRevision,CaseRecord,CaseConsent,Student,User,Task,CaseTransfer
from app.security import decrypt

def student(c,owner='one',name='תלמידת בדיקה',classroom='ח1'):
    return c.post('/api/students',headers=token(owner),json={'name':name,'classroom':classroom}).json()['id']
def document(**values):return {'starts_at':'2026-10-08T09:00:00Z','notes':'תיעוד רגיש','summary':'סיכום','subjects':'נושאים','decisions':['תיאום פגישה','מעקב'],'next_steps':'לבדוק בשבוע הבא','topic':'social','template':'first',**values}
def test_immutable_revisions_conflicts_isolation_and_legacy(setup):
    c,f=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}/meetings'
    m=c.post(url,headers=h,json=document()).json();assert m['version']==1
    assert c.put(url+'/'+m['id'],headers=token('two'),json=document()).status_code==404
    response=c.put(url+'/'+m['id'],headers=h,json=document(notes='עריכה',expected_version=1));assert response.status_code==200,response.text
    assert response.json()['version']==2
    assert c.put(url+'/'+m['id'],headers=h,json=document(notes='דריסה',expected_version=1)).status_code==409
    history=c.get(url+'/'+m['id']+'/history',headers=h).json();assert [r['version'] for r in history]==[2,1]
    assert history[1]['document']['notes']=='תיעוד רגיש' and history[0]['actor']=='One'
    assert c.get(url+'/'+m['id']+'/history',headers=token('two')).status_code==404
    with f() as db:
        assert all('רגיש' not in r.document for r in db.scalars(select(MeetingRevision)).all())
        # Simulate a pre-migration meeting without a historical actor.
        legacy=Meeting(student_id=sid,starts_at=datetime.now(timezone.utc),notes=__import__('app.security',fromlist=['encrypt']).encrypt('ישן'),summary=__import__('app.security',fromlist=['encrypt']).encrypt(''))
        db.add(legacy);db.commit();mid=legacy.id
    assert c.put(url+'/'+mid,headers=h,json=document(expected_version=1)).status_code==200
    assert c.get(url+'/'+mid+'/history',headers=h).json()[1]['document']['notes']=='ישן'

def test_encrypted_draft_autosave_conflict_publish_review(setup):
    c,f=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}/draft'
    assert c.get(url,headers=token('two')).status_code==404
    assert c.get(url,headers=h).json()['version']==0
    b={'expected_version':0,'document':document(ai_assisted=True,consent_recorded=True,ai_reviewed=False)}
    assert c.put(url,headers=h,json=b).json()['version']==1
    assert c.put(url,headers=h,json=b).status_code==409
    assert c.post(url+'/publish',headers=h,json={'expected_version':1}).status_code==422
    with f() as db:assert 'רגיש' not in db.scalar(select(CaseRecord)).document
    assert c.get(url,headers=h).json()['document']['notes']=='תיעוד רגיש'
    b['expected_version']=1;b['document']['ai_reviewed']=True
    assert c.put(url,headers=h,json=b).json()['version']==2
    assert c.post(url+'/publish',headers=h,json={'expected_version':1}).status_code==409
    assert c.post(url+'/publish',headers=h,json={'expected_version':2}).status_code==201
    assert c.get(url,headers=h).json()['document'] is None
    assert c.post(url+'/publish',headers=h,json={'expected_version':2}).status_code==409

def test_consent_expiry_revocation_and_cloud_separation(setup,monkeypatch):
    c,f=setup;sid=student(c);h=token('one');other=token('two');url=f'/api/students/{sid}'
    assert c.post(url+'/recording-authorize',headers=h).status_code==403
    recording=grant(c,sid,'recording','');assert c.post(url+'/recording-authorize',headers=h).status_code==200
    assert c.post(url+'/shares',headers=h,json=proof(user_id='two')).status_code==403
    shared=grant(c,sid,'sharing','two');assert c.post(url+'/shares',headers=h,json=proof(user_id='two')).status_code==200
    assert c.get('/api/students',headers=other).json()[0]['id']==sid
    with f() as db:db.get(CaseConsent,shared).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.get('/api/students',headers=other).json()==[]
    assert c.get(url+'/records/contact',headers=other).status_code==404
    grant(c,sid,'sharing','two');assert len(c.get('/api/students',headers=other).json())==1
    assert c.post(url+'/consents/'+recording+'/revoke',headers=h).status_code==200
    assert c.post(url+'/recording-authorize',headers=h).status_code==403
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('OPENAI_API_KEY','synthetic-key')
    from app import ai
    async def fail(*a,**kw):raise AssertionError('Must not contact provider')
    monkeypatch.setattr(ai,'provider',fail)
    assert c.post('/api/ai/students/'+sid+'/summarize',headers=h,json={'transcript':'בדיקה','consent':True}).status_code==403
    grant(c,sid,'cloud','groq')
    assert c.post('/api/ai/students/'+sid+'/summarize',headers=h,json={'transcript':'בדיקה','consent':True}).status_code==403

def test_contacts_plans_history_decisions_and_search(setup):
    c,f=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}'
    contact={'kind':'parent','at':'2026-10-08T09:00:00Z','name':'הורה בדיקה','notes':'תיאום רגיש'}
    assert c.post(url+'/contacts',headers=token('two'),json=contact).status_code==404
    assert c.post(url+'/contacts',headers=h,json=contact).status_code==201
    plan={'title':'ליווי','goals':[{'title':'קשר חברתי','measure':'שיחה אחת בשבוע','due_at':'2026-12-01T09:00:00Z','progress':0,'note':''}]}
    r=c.post(url+'/plans',headers=h,json=plan).json()
    updated={**plan,'expected_version':r['version']};updated['goals'][0]['progress']=40
    assert c.put(url+'/plans/'+r['id'],headers=h,json=updated).json()['version']==2
    assert c.put(url+'/plans/'+r['id'],headers=h,json=updated).status_code==409
    history=c.get(url+'/plans/'+r['id']+'/history',headers=h).json();assert history[0]['document']['document']['goals'][0]['progress']==0
    m=c.post(url+'/meetings',headers=h,json=document()).json()
    body={'expected_version':1,'index':0,'due_at':'2026-10-09T09:00:00Z'}
    assert c.post(url+'/meetings/'+m['id']+'/tasks',headers=h,json=body).status_code==201
    assert c.post(url+'/meetings/'+m['id']+'/tasks',headers=h,json=body).status_code==409
    matches=c.get('/api/search',headers=h,params={'student':'בדיקה','classroom':'ח1','topic':'social','after':'2026-10-08T00:00:00Z','open_tasks':'true'}).json();assert [r['id'] for r in matches]==[sid]
    assert c.get('/api/search',headers=token('two'),params={'student':'בדיקה'}).json()==[]
    assert c.get('/api/search',headers=h,params={'topic':'family'}).json()==[]
    with f() as db:assert all('רגיש' not in r.document for r in db.scalars(select(CaseRecord)).all())

def test_transfer_two_party_ownership_draft_and_consent(setup):
    c,f=setup;sid=student(c);h=token('one');other=token('two');url=f'/api/students/{sid}'
    assert c.post(url+'/transfer',headers=h,json=proof(to_id='two',reason='החלפת יועצת')).status_code==403
    grant(c,sid,'sharing','two');c.put(url+'/draft',headers=h,json={'expected_version':0,'document':document()})
    rid=c.post(url+'/transfer',headers=h,json=proof(to_id='two',reason='החלפת יועצת')).json()['id']
    assert c.post('/api/transfers/'+rid,headers=h,json=proof(action='accept')).status_code==403
    assert c.post('/api/transfers/'+rid,headers=other,json=proof(action='accept')).status_code==200
    assert c.get('/api/students',headers=h).json()==[]
    assert c.get(url+'/draft',headers=h).status_code==404
    assert c.get(url+'/draft',headers=other).json()['document']['notes']=='תיעוד רגיש'
    assert c.post('/api/transfers/'+rid,headers=other,json=proof(action='accept')).status_code==409
    with f() as db:assert db.get(Student,sid).owner_id=='two' and db.get(CaseTransfer,rid).status=='accepted'

def test_rollover_atomic_class_archive_and_history(setup):
    c,f=setup;a=student(c);b=student(c);other=student(c,'two');h=token('one')
    body=proof(source_year='2026-2027',target_year='2027-2028',confirmed=True,rows=[{'student_id':a,'classroom':'ט1'},{'student_id':other,'graduate':True}])
    assert c.post('/api/school-years/rollover',headers=h,json=body).status_code==404
    assert c.get('/api/students',headers=h).json()[0]['school_year']=='2026-2027'
    body['rows']=[{'student_id':a,'classroom':'ט1'},{'student_id':b,'graduate':True}]
    assert c.post('/api/school-years/rollover',headers=h,json=body).json()['updated']==2
    rows={r['id']:r for r in c.get('/api/students',headers=h).json()};assert rows[a]['school_year']=='2027-2028' and rows[a]['classroom']=='ט1' and rows[b]['archived']
    assert c.post('/api/school-years/rollover',headers=h,json=body).status_code==409
    assert c.post(f'/api/students/{b}/contacts',headers=h,json={'kind':'staff','at':'2026-10-08T09:00:00Z','name':'בדיקה','notes':'בדיקה'}).status_code==409
    with f() as db:assert len(db.scalars(select(CaseRecord).where(CaseRecord.kind=='year_history')).all())==2

def test_report_suppression_topics_and_owner_scope(setup):
    c,_=setup;h=token('one')
    assert c.get('/api/reports',headers=h).json()['suppressed']
    for i in range(5):
        sid=student(c,name='שם סודי '+str(i));c.post(f'/api/students/{sid}/meetings',headers=h,json=document())
    # Another counselor's records do not enter reports.
    sid=student(c,'two','פרטי');c.post(f'/api/students/{sid}/meetings',headers=token('two'),json=document())
    result=c.get('/api/reports',headers=h).json();assert not result['suppressed'] and result['meetings']==5 and result['topics']==[{'topic':'חברה','meetings':5}]
    assert 'סודי' not in json.dumps(result,ensure_ascii=False) and 'תיעוד' not in json.dumps(result,ensure_ascii=False)
    assert c.get('/api/reports',headers=token('two')).json()['suppressed']
    assert c.get('/api/reports',headers=h,params={'after':'2027-01-01T00:00:00Z'}).json()['suppressed']

def test_local_offline_disabled_and_authorization(setup,monkeypatch):
    c,_=setup;sid=student(c);h=token('one');url='/api/local-transcription/students/'+sid
    monkeypatch.delenv('LOCAL_TRANSCRIPTION_URL',raising=False)
    assert not c.get('/api/local-transcription/status',headers=h).json()['enabled']
    assert c.post(url,headers=token('two'),content=b'fake').status_code==404
    assert c.post(url,headers=h,content=b'fake').status_code==403
    for purpose in ['recording','transcription']:grant(c,sid,purpose,'')
    assert c.post(url,headers=h,content=b'fake').status_code==503
    import httpx
    from app import local_transcription
    monkeypatch.setenv('LOCAL_TRANSCRIPTION_URL','http://local-transcription:8090')
    calls=[]
    def handler(request):
        calls.append(request);assert request.url.host=='local-transcription';assert request.headers.get('X-Internal-Key')
        return httpx.Response(200,json={'transcript':'תמלול מקומי'})
    original=httpx.AsyncClient
    monkeypatch.setattr(local_transcription.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler)))
    result=c.post(url,headers={**h,'Content-Type':'audio/webm'},content=b'fake')
    assert result.status_code==200 and result.json()['transcript']=='תמלול מקומי' and len(calls)==1

def test_backup_new_casework_and_revisions_roundtrip(setup):
    c,_=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}'
    m=c.post(url+'/meetings',headers=h,json=document()).json();c.put(url+'/meetings/'+m['id'],headers=h,json=document(notes='חדש',expected_version=1))
    c.post(url+'/contacts',headers=h,json={'kind':'parent','at':'2026-10-08T09:00:00Z','name':'הורה','notes':'פרטי'})
    p=c.post(url+'/plans',headers=h,json={'title':'ליווי','goals':[{'title':'התקדמות','measure':'שיחה','due_at':'2026-12-01T09:00:00Z','progress':10}]}).json()
    c.put(url+'/plans/'+p['id'],headers=h,json={**p['document'],'expected_version':1,'status':'completed'})
    c.put(url+'/draft',headers=h,json={'expected_version':0,'document':document()});grant(c,sid,'sharing','two')
    b=proof(backup_password='separate-long-backup-password');archive=c.post('/api/settings/backup/export',headers=h,json=b)
    assert archive.status_code==200,archive.text
    result=c.post('/api/settings/backup/restore',headers=token('two'),json={**b,'archive':archive.json(),'confirmed':True});assert result.status_code==200,result.text
    restored=c.get('/api/students',headers=token('two')).json()[0]['id'];prefix=f'/api/students/{restored}'
    meetings=c.get(prefix+'/meetings',headers=token('two')).json();assert meetings[0]['version']==2
    assert c.get(prefix+'/meetings/'+meetings[0]['id']+'/history',headers=token('two')).json()[1]['document']['notes']=='תיעוד רגיש'
    assert c.get(prefix+'/records/contact',headers=token('two')).json()[0]['document']['notes']=='פרטי'
    plan=c.get(prefix+'/records/plan',headers=token('two')).json()[0]
    assert len(c.get(prefix+'/plans/'+plan['id']+'/history',headers=token('two')).json())==1
    assert c.get(prefix+'/draft',headers=token('two')).json()['document']['notes']=='תיעוד רגיש'
    assert c.get(prefix+'/consents',headers=token('two')).json()[0]['revoked']

def test_edit_drafts_are_separate_and_require_current_meeting_version(setup):
    c,_=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}'
    m=c.post(url+'/meetings',headers=h,json=document()).json()
    b={'meeting_id':m['id'],'expected_version':0,'document':document(expected_version=1,notes='טיוטת עריכה')}
    assert c.put(url+'/draft',headers=h,json=b).json()['version']==1
    assert c.get(url+'/draft',headers=h).json()['document'] is None
    assert c.get(url+'/draft',headers=h,params={'meeting_id':m['id']}).json()['document']['notes']=='טיוטת עריכה'
    assert c.post(url+'/draft/publish',headers=h,json={'meeting_id':m['id'],'expected_version':1}).json()['version']==2
    assert c.get(url+'/draft',headers=h,params={'meeting_id':m['id']}).json()['document'] is None
    b['document']=document(expected_version=2)
    assert c.put(url+'/draft',headers=h,json=b).json()['version']==1
    assert c.put(url+'/meetings/'+m['id'],headers=h,json=document(expected_version=2)).json()['version']==3
    assert c.post(url+'/draft/publish',headers=h,json={'meeting_id':m['id'],'expected_version':1}).status_code==409
    assert c.get(url+'/draft',headers=h,params={'meeting_id':m['id']}).json()['document'] is not None


def test_transfer_checks_expired_consent_and_appointment_conflict(setup):
    c,f=setup;sid=student(c);target=student(c,'two');h=token('one');other=token('two')
    consent=grant(c,sid,'sharing','two')
    rid=c.post(f'/api/students/{sid}/transfer',headers=h,json=proof(to_id='two',reason='העברה מסודרת')).json()['id']
    with f() as db:db.get(CaseConsent,consent).revoked=True;db.commit()
    assert c.post('/api/transfers/'+rid,headers=other,json=proof(action='accept')).status_code==403
    grant(c,sid,'sharing','two')
    a={'starts_at':'2026-12-01T09:00:00Z','ends_at':'2026-12-01T10:00:00Z'}
    c.post('/api/appointments',headers=h,json=dict(a,student_id=sid))
    c.post('/api/appointments',headers=other,json=dict(a,student_id=target))
    assert c.post('/api/transfers/'+rid,headers=other,json=proof(action='accept')).status_code==409
    with f() as db:assert db.get(Student,sid).owner_id=='one'
    assert c.post('/api/transfers/'+rid,headers=other,json=proof(action='reject')).status_code==200

def test_browser_dictation_requires_explicit_browser_consent(setup):
    c,f=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}/browser-dictation-authorize'
    assert c.post(url,headers=token('two')).status_code==404
    assert c.post(url,headers=h).status_code==403
    for purpose in ['recording','transcription']:grant(c,sid,purpose,'')
    # A provider consent does not authorize browser-managed recognition.
    grant(c,sid,'cloud','openai');assert c.post(url,headers=h).status_code==403
    browser=grant(c,sid,'browser','');assert c.post(url,headers=h).status_code==200
    with f() as db:db.get(CaseConsent,browser).revoked=True;db.commit()
    assert c.post(url,headers=h).status_code==403
