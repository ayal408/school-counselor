import os, secrets, hashlib, base64, json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, EmailSettings, EmailConsent, EmailOutbox, Audit
from .security import current_user, admin_user, encrypt, decrypt
from .management import Proof, prove
from .email_service import settings,configuration_json,oauth_available,environment,redirect_uri,origin,mailbox,enqueue,connected
from .ai import tls_context
router=APIRouter(prefix='/api/email')
SCOPE='https://www.googleapis.com/auth/gmail.send'
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
class SettingsInput(Proof):
    sender_name:str=Field(min_length=1,max_length=100)
    reply_to:str=Field(default='',max_length=254)
    signature:str=Field(default='',max_length=2000)
    @field_validator('sender_name')
    @classmethod
    def name(cls,v):
        if not v.strip() or any(ord(c)<32 for c in v):raise ValueError('שם שולח לא תקין')
        return v.strip()
    @field_validator('reply_to')
    @classmethod
    def address(cls,v):
        if v and not mailbox(v):raise ValueError('כתובת מענה אינה תקינה')
        return v
@router.get('/settings')
def get_settings(user:User=Depends(admin_user),db:Session=Depends(get_db)):return configuration_json(db)
@router.put('/settings')
def save(body:SettingsInput,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.role!='admin':raise HTTPException(403,'נדרשת הרשאת מנהלת')
    row=settings(db);row.sender_name=body.sender_name;row.reply_to=body.reply_to;row.signature=body.signature;row.updated_at=datetime.now(timezone.utc)
    db.add(row);db.add(Audit(user_id=user.id,action='email.configure',record_id=user.id));db.commit();return configuration_json(db)
@router.post('/gmail/connect')
def connect(body:Proof,response:Response,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.role!='admin':raise HTTPException(403,'נדרשת הרשאת מנהלת')
    if not oauth_available():raise HTTPException(409,'יש להגדיר מזהה וסוד לקוח Google בשרת')
    configuration=db.scalar(select(EmailSettings).where(EmailSettings.id==1).with_for_update().execution_options(populate_existing=True)) or settings(db);db.add(configuration);db.flush()
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    db.execute(delete(EmailConsent).where(EmailConsent.expires_at<datetime.now(timezone.utc)))
    db.execute(delete(EmailConsent).where(EmailConsent.user_id==user.id))
    db.add(EmailConsent(state_hash=digest(state),user_id=user.id,session_version=user.session_version,generation=configuration.generation,verifier=encrypt(verifier),expires_at=datetime.now(timezone.utc)+timedelta(minutes=10)))
    db.commit()
    response.set_cookie('merhav_gmail_state',state,max_age=600,httponly=True,secure=os.environ.get('COOKIE_SECURE','true').lower()=='true',samesite='lax',path='/api/email/gmail/callback')
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params={'client_id':environment('GMAIL_CLIENT_ID'),'redirect_uri':redirect_uri(),'response_type':'code','scope':'openid email '+SCOPE,'access_type':'offline','prompt':'consent select_account','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
    return {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params)}
@router.get('/gmail/callback')
async def callback(request:Request,db:Session=Depends(get_db)):
    state=request.query_params.get('state','');code=request.query_params.get('code','');cookie=request.cookies.get('merhav_gmail_state','')
    result='failed';pending=None
    if state and len(state)<=128 and state.isascii() and cookie and secrets.compare_digest(state,cookie):
        row=db.execute(delete(EmailConsent).where(EmailConsent.state_hash==digest(state),EmailConsent.expires_at>datetime.now(timezone.utc)).returning(EmailConsent.user_id,EmailConsent.session_version,EmailConsent.verifier,EmailConsent.generation)).first()
        if row:pending=(row[0],row[1],decrypt(row[2]),row[3])
        db.commit()
    if pending and code and len(code)<4096 and not request.query_params.get('error'):
        user=db.get(User,pending[0])
        if user and user.active and user.role=='admin' and user.session_version==pending[1]:
            try:
                async with httpx.AsyncClient(timeout=20,verify=tls_context()) as client:
                    token=await client.post('https://oauth2.googleapis.com/token',data={'client_id':environment('GMAIL_CLIENT_ID'),'client_secret':environment('GMAIL_CLIENT_SECRET'),'code':code,'code_verifier':pending[2],'redirect_uri':redirect_uri(),'grant_type':'authorization_code'})
                    if token.status_code!=200:raise ValueError()
                    tokens=token.json()
                    if SCOPE not in tokens.get('scope','').split() or not tokens.get('refresh_token') or not tokens.get('access_token'):raise ValueError()
                    identity=await client.get('https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+tokens['access_token']})
                    if identity.status_code!=200:raise ValueError()
                    profile=identity.json()
                    if profile.get('email_verified') is not True or not mailbox(profile.get('email')):raise ValueError()
                # Check role and session again after the network round trip.
                user=db.scalar(select(User).where(User.id==pending[0]).with_for_update().execution_options(populate_existing=True))
                if not user or not user.active or user.role!='admin' or user.session_version!=pending[1]:raise ValueError()
                row=db.scalar(select(EmailSettings).where(EmailSettings.id==1).with_for_update().execution_options(populate_existing=True))
                if not row or row.generation!=pending[3]:raise ValueError()
                row.generation+=1;row.sender_email=profile['email'];row.refresh_token=encrypt(tokens['refresh_token']);row.enabled=True;row.updated_at=datetime.now(timezone.utc)
                db.add(row);db.add(Audit(user_id=user.id,action='email.connect',record_id=user.id));db.commit();result='connected'
            except (httpx.HTTPError,ValueError,TypeError,KeyError,OSError):db.rollback()
    response=RedirectResponse(origin()+'/admin/email?gmail='+result,status_code=303)
    response.delete_cookie('merhav_gmail_state',path='/api/email/gmail/callback',secure=os.environ.get('COOKIE_SECURE','true').lower()=='true',httponly=True,samesite='lax')
    return response
@router.post('/gmail/disconnect')
def disconnect(body:Proof,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.role!='admin':raise HTTPException(403,'נדרשת הרשאת מנהלת')
    row=db.scalar(select(EmailSettings).where(EmailSettings.id==1).with_for_update().execution_options(populate_existing=True)) or settings(db);row.generation+=1;row.enabled=False;row.refresh_token=None;row.updated_at=datetime.now(timezone.utc);db.add(row)
    db.execute(delete(EmailConsent))
    # Remove pending messages so reconnect does not silently send an old backlog.
    for delivery in db.scalars(select(EmailOutbox).where(EmailOutbox.status=='pending')).all():delivery.status='cancelled';delivery.payload=None
    db.add(Audit(user_id=user.id,action='email.disconnect',record_id=user.id));db.commit();return {'ok':True}
class TestInput(Proof):
    recipient:str=Field(max_length=254)
@router.post('/send-test')
def test(body:TestInput,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.role!='admin':raise HTTPException(403,'נדרשת הרשאת מנהלת')
    if not mailbox(body.recipient):raise HTTPException(422,'כתובת הנמען אינה תקינה')
    if not connected(db):raise HTTPException(409,'יש לחבר חשבון שולח קודם')
    row=enqueue(db,body.recipient,'test','בדיקת חיבור המייל של מרחב','מייל הבדיקה נשלח מחשבון המערכת שהגדרת. כל הודעות המערכת נשלחות מאותו חשבון.',origin()+'/settings')
    db.flush();uid=row.id;db.commit();return {'queued':True,'id':uid,'message':'המייל נוסף לתור. תוכלי לראות את תוצאת השליחה בהיסטוריה.'}
@router.get('/history')
def history(user:User=Depends(admin_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(EmailOutbox).order_by(EmailOutbox.created_at.desc()).limit(50)).all()
    return [{'id':r.id,'recipient':r.recipient,'kind':r.kind,'status':r.status,'attempts':r.attempts,'failure_code':r.failure_code,'created_at':r.created_at,'sent_at':r.sent_at} for r in rows]
