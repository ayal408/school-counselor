import asyncio, base64, hashlib, json
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse,parse_qs,parse_qsl
from email import message_from_bytes
from email.policy import default
import httpx
from sqlalchemy import select
from test_api import setup, token, proof, make_admin
from app.models import User,EmailSettings,EmailConsent,EmailOutbox,AccountEmailToken
from app.security import encrypt,decrypt
from app import email_service, email_api

def google_env(monkeypatch):
    monkeypatch.setenv('GMAIL_CLIENT_ID','test-client-id');monkeypatch.setenv('GMAIL_CLIENT_SECRET','test-client-secret');monkeypatch.setenv('COOKIE_SECURE','false')
    for key in ['GMAIL_EMAIL','GMAIL_REFRESH_TOKEN','GMAIL__EMAIL','GMAIL__REFRESHTOKEN']:monkeypatch.delenv(key,raising=False)
def sender(factory):
    with factory() as db:
        db.add(EmailSettings(id=1,sender_email='system@example.test',sender_name='בית הספר',refresh_token=encrypt('private-refresh'),enabled=True,signature='<script>חתימה</script>'))
        db.commit()
def fake_network(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr(email_service.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler)))
def link_token(factory,kind):
    with factory() as db:
        row=db.scalar(select(EmailOutbox).where(EmailOutbox.kind==kind).order_by(EmailOutbox.created_at.desc()))
        payload=json.loads(decrypt(row.payload))
        return parse_qs(urlparse(payload['link']).fragment)['token'][0]

def test_gmail_admin_connection_pkce_encryption_and_single_use(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;h=token('one');make_admin(f)
    assert c.get('/api/email/settings',headers=token('two')).status_code==403
    assert c.post('/api/email/gmail/connect',headers=token('two'),json=proof()).status_code==403
    result=c.post('/api/email/gmail/connect',headers=h,json=proof())
    assert result.status_code==200
    params=parse_qs(urlparse(result.json()['authorization_url']).query);state=params['state'][0]
    assert 'gmail.send' in params['scope'][0] and params['code_challenge_method']==['S256']
    with f() as db:
        pending=db.get(EmailConsent,hashlib.sha256(state.encode()).hexdigest())
        verifier=decrypt(pending.verifier)
        assert verifier not in pending.verifier
        assert params['code_challenge'][0]==base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.host=='oauth2.googleapis.com':
            form=dict(parse_qsl(request.content.decode()))
            assert form['code_verifier']==verifier and form['grant_type']=='authorization_code'
            return httpx.Response(200,json={'access_token':'private-access','refresh_token':'private-refresh','scope':'openid email '+email_api.SCOPE})
        assert request.url.host=='openidconnect.googleapis.com'
        return httpx.Response(200,json={'email':'system@example.test','email_verified':True})
    fake_network(monkeypatch,handler)
    callback=c.get('/api/email/gmail/callback',params={'state':state,'code':'private-code'},follow_redirects=False)
    assert callback.headers['location'].endswith('/admin/email?gmail=connected')
    info=c.get('/api/email/settings',headers=h).json();assert info['connected'] and 'private-' not in json.dumps(info)
    with f() as db:
        assert 'private-refresh' not in db.get(EmailSettings,1).refresh_token
        assert db.get(EmailConsent,hashlib.sha256(state.encode()).hexdigest()) is None
    assert c.get('/api/email/gmail/callback',params={'state':state,'code':'private-code'},follow_redirects=False).headers['location'].endswith('gmail=failed')
    assert len(seen)==2

def test_oauth_rechecks_admin_and_rejects_callback_without_cookie(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;h=token('one');make_admin(f)
    url=c.post('/api/email/gmail/connect',headers=h,json=proof()).json()['authorization_url'];state=parse_qs(urlparse(url).query)['state'][0]
    seen=[]
    fake_network(monkeypatch,lambda r:seen.append(r) or httpx.Response(400))
    c.cookies.clear()
    assert c.get('/api/email/gmail/callback',params={'state':state,'code':'code'},follow_redirects=False).headers['location'].endswith('gmail=failed')
    assert seen==[]
    url=c.post('/api/email/gmail/connect',headers=h,json=proof()).json()['authorization_url'];state=parse_qs(urlparse(url).query)['state'][0]
    with f() as db:db.get(User,'one').role='counselor';db.commit()
    assert c.get('/api/email/gmail/callback',params={'state':state,'code':'code'},follow_redirects=False).headers['location'].endswith('gmail=failed')
    assert seen==[]

def test_outbox_gmail_mime_design_no_secrets_history(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);make_admin(f);h=token('one')
    result=c.post('/api/email/send-test',headers=h,json=proof(recipient='owned@example.test'))
    assert result.status_code==200 and result.json()['queued'] is True
    def handler(request):
        if request.url.host=='oauth2.googleapis.com':return httpx.Response(200,json={'access_token':'private-access'})
        assert str(request.url)=='https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
        assert request.headers['Authorization']=='Bearer private-access'
        raw=json.loads(request.content)['raw'];mime=message_from_bytes(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)),policy=default)
        assert 'בית הספר' in str(mime['From']) and 'system@example.test' in str(mime['From'])
        html=mime.get_body(preferencelist=('html',)).get_content()
        assert 'dir="rtl"' in html and '◈ מרחב' in html and '&lt;script&gt;' in html and '<script>' not in html
        assert 'private-refresh' not in html and 'private-access' not in html
        return httpx.Response(200,json={'id':'sent'})
    fake_network(monkeypatch,handler)
    assert asyncio.run(email_service.process_one(f)) is True
    history=c.get('/api/email/history',headers=h).json()
    assert history[0]['status']=='sent' and 'payload' not in history[0] and 'private-' not in json.dumps(history)
    with f() as db:assert db.get(EmailOutbox,result.json()['id']).payload is None

def test_uncertain_send_is_not_automatically_retried_and_disconnect_blocks_fallback(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);make_admin(f);h=token('one')
    uid=c.post('/api/email/send-test',headers=h,json=proof(recipient='owned@example.test')).json()['id'];calls=[]
    def handler(request):
        if request.url.host=='oauth2.googleapis.com':return httpx.Response(200,json={'access_token':'token'})
        calls.append(request);raise httpx.ReadTimeout('simulated timeout')
    fake_network(monkeypatch,handler)
    asyncio.run(email_service.process_one(f));assert asyncio.run(email_service.process_one(f)) is False
    with f() as db:
        row=db.get(EmailOutbox,uid);assert row.status=='uncertain' and row.payload is None
    assert len(calls)==1
    c.post('/api/email/send-test',headers=h,json=proof(recipient='owned@example.test'))
    monkeypatch.setenv('GMAIL_EMAIL','fallback@example.test');monkeypatch.setenv('GMAIL_REFRESH_TOKEN','legacy-token')
    assert c.post('/api/email/gmail/disconnect',headers=h,json=proof()).status_code==200
    assert c.get('/api/email/settings',headers=h).json()['connected'] is False
    with f() as db:assert all(r.status!='pending' and r.payload is None for r in db.scalars(select(EmailOutbox)).all())

def test_password_reset_private_single_use_preserves_mfa_and_revokes_sessions(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f)
    known=c.post('/api/account/reset/request',json={'email':'one@example.test'});unknown=c.post('/api/account/reset/request',json={'email':'unknown@example.test'})
    assert known.json()==unknown.json() and known.status_code==unknown.status_code==200
    c.post('/api/account/reset/request',json={'email':'one@example.test'})
    with f() as db:
        assert len(db.scalars(select(AccountEmailToken)).all())==1
        assert len(db.scalars(select(EmailOutbox)).all())==1
        db.get(User,'one').mfa_secret=encrypt('TEST-MFA-REMAINS');db.commit()
    opaque=link_token(f,'password_reset')
    with f() as db:assert opaque not in db.scalar(select(AccountEmailToken)).token_hash
    body={'token':opaque,'password':'new-long-password'}
    assert c.post('/api/account/reset/complete',json=body).status_code==200
    assert c.post('/api/account/reset/complete',json=body).status_code==422
    assert c.get('/api/students',headers=token('one')).status_code==401
    with f() as db:
        from app.mfa import hasher
        user=db.get(User,'one');assert user.mfa_secret and hasher.verify(user.password_hash,'new-long-password') and user.email_verified

def test_expired_link_verification_and_header_injection(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);h=token('one');make_admin(f)
    assert c.put('/api/email/settings',headers=h,json=proof(sender_name='sender\r\nBCC: bad@example.test')).status_code==422
    assert c.put('/api/email/settings',headers=h,json=proof(sender_name='בית הספר',reply_to='bad@example.test\n')).status_code==422
    assert c.post('/api/account/verify/request',headers=h).status_code==200
    opaque=link_token(f,'email_verify')
    assert c.post('/api/account/verify/complete',json={'token':opaque}).status_code==200
    assert c.post('/api/account/verify/complete',json={'token':opaque}).status_code==422
    c.post('/api/account/reset/request',json={'email':'one@example.test'});opaque=link_token(f,'password_reset')
    with f() as db:db.scalar(select(AccountEmailToken)).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.post('/api/account/reset/complete',json={'token':opaque,'password':'new-long-password'}).status_code==422

def test_reminders_deduplicate_and_notifications_exclude_student_content(setup,monkeypatch):
    from app.email_worker import reminders
    google_env(monkeypatch);c,f=setup;sender(f);h=token('one')
    with f() as db:reminders(db);reminders(db)
    with f() as db:assert len(db.scalars(select(EmailOutbox).where(EmailOutbox.kind=='backup_reminder')).all())==2
    sid=c.post('/api/students',headers=h,json={'name':'שם רגיש','classroom':'ח','referral':'סיכום רגיש'}).json()['id']
    from test_api import grant
    grant(c,sid,'sharing','two')
    c.post(f'/api/students/{sid}/shares',headers=h,json=proof(user_id='two'))
    with f() as db:
        row=db.scalar(select(EmailOutbox).where(EmailOutbox.kind=='share'))
        payload=decrypt(row.payload)
        assert 'שם רגיש' not in payload and 'סיכום רגיש' not in payload and sid not in payload

def test_account_changes_invalidate_old_reset_links(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);make_admin(f);h=token('one')
    c.post('/api/account/reset/request',json={'email':'two@example.test'});opaque=link_token(f,'password_reset')
    assert c.patch('/api/admin/users/two',headers=h,json=proof(active=True,role='counselor',new_password='admin-replaced-password')).status_code==200
    assert c.post('/api/account/reset/complete',json={'token':opaque,'password':'old-link-new-password'}).status_code==422
    with f() as db:
        row=db.scalar(select(EmailOutbox).where(EmailOutbox.kind=='password_reset'))
        assert row.status=='cancelled' and row.payload is None

def test_stale_oauth_completion_cannot_replace_a_new_configuration(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);make_admin(f);h=token('one')
    url=c.post('/api/email/gmail/connect',headers=h,json=proof()).json()['authorization_url'];state=parse_qs(urlparse(url).query)['state'][0]
    def handler(request):
        if request.url.host=='oauth2.googleapis.com':return httpx.Response(200,json={'access_token':'token','refresh_token':'new-refresh','scope':email_api.SCOPE})
        with f() as db:
            row=db.get(EmailSettings,1);row.generation+=1;row.enabled=False;row.refresh_token=None;db.commit()
        return httpx.Response(200,json={'email':'different@example.test','email_verified':True})
    fake_network(monkeypatch,handler)
    result=c.get('/api/email/gmail/callback',params={'state':state,'code':'code'},follow_redirects=False)
    assert result.headers['location'].endswith('gmail=failed')
    with f() as db:assert db.get(EmailSettings,1).enabled is False and db.get(EmailSettings,1).sender_email=='system@example.test'

def test_google_failure_classification_does_not_leak_provider_text():
    cases=[(403,{'details':[{'reason':'SERVICE_DISABLED'}]},'GMAIL_API_DISABLED'),(403,{'errors':[{'reason':'insufficientPermissions'}]},'GMAIL_PERMISSION_MISSING'),(403,{'errors':[{'reason':'domainPolicy'}]},'GMAIL_DOMAIN_POLICY'),(403,{'errors':[{'reason':'userRateLimitExceeded'}]},'RATE_LIMITED'),(400,{'status':'FAILED_PRECONDITION'},'GMAIL_ACCOUNT_NOT_READY'),(401,{},'GMAIL_RECONNECT_REQUIRED'),(500,{},'DELIVERY_UNKNOWN')]
    for status,error,expected in cases:
        error['message']='private-token-and-private-message'
        failure=email_service.google_failure(httpx.Response(status,json={'error':error}))
        assert failure.code==expected
        assert 'private-' not in email_service.failure_message(failure.code)
    assert email_service.google_failure(httpx.Response(403,text='<html>private proxy error</html>')).code=='GMAIL_HTTP_403'
    assert email_service.google_failure(httpx.Response(400,json={'error':'invalid_grant'}),token_refresh=True).code=='GMAIL_RECONNECT_REQUIRED'

def test_rejected_send_history_has_safe_actionable_reason(setup,monkeypatch):
    google_env(monkeypatch);c,f=setup;sender(f);make_admin(f);h=token('one')
    c.post('/api/email/send-test',headers=h,json=proof(recipient='owned@example.test'))
    def handler(request):
        if request.url.host=='oauth2.googleapis.com':return httpx.Response(200,json={'access_token':'private-access'})
        return httpx.Response(403,json={'error':{'message':'private-token','details':[{'reason':'SERVICE_DISABLED'}]}})
    fake_network(monkeypatch,handler)
    asyncio.run(email_service.process_one(f))
    info=c.get('/api/email/history',headers=h).json()[0]
    assert info['failure_code']=='GMAIL_API_DISABLED' and 'Gmail API' in info['failure_message']
    assert 'private-token' not in json.dumps(info)
