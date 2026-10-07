import base64, json, secrets, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, Student, StudentShare, AIConfig, Audit
from .security import current_user, admin_user, encrypt, decrypt
from .mfa import authenticate, hasher, revoke_all, totp, recovery_hash, utc
router=APIRouter(prefix='/api')
class Proof(BaseModel):
    password:str=Field(min_length=1,max_length=256)
    otp:str=Field(default='',max_length=64)
def prove(db,user,body):return authenticate(db,user,body.password,body.otp)
def audit(db,user,action,rid):db.add(Audit(user_id=user.id,action=action,record_id=rid))
def user_json(u):return {'id':u.id,'email':u.email,'name':u.name,'active':u.active,'role':u.role,'mfa_enabled':bool(u.mfa_secret),'session_version':u.session_version}
@router.get('/settings/security')
def security(user:User=Depends(current_user)):
    return {'mfa_enabled':bool(user.mfa_secret),'role':user.role,'recovery_remaining':len(json.loads(user.recovery_hashes)),'last_backup':user.last_backup}
@router.post('/settings/mfa/setup')
def setup(body:Proof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.mfa_secret:raise HTTPException(409,'אימות דו־שלבי כבר מופעל')
    secret=base64.b32encode(secrets.token_bytes(20)).decode()
    user.mfa_pending=encrypt(secret);user.mfa_pending_until=datetime.now(timezone.utc)+timedelta(minutes=10)
    db.commit()
    return {'secret':secret,'uri':f'otpauth://totp/{quote("Merhav:"+user.email)}?secret={secret}&issuer=Merhav&algorithm=SHA1&digits=6&period=30'}
@router.post('/settings/mfa/confirm')
def confirm(body:Proof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    user=authenticate(db,user,body.password,body.otp,reset_failures=False)
    if not user.mfa_pending or not user.mfa_pending_until or utc(user.mfa_pending_until)<datetime.now(timezone.utc):raise HTTPException(409,'ההגדרה פגה. התחילי מחדש')
    secret=decrypt(user.mfa_pending);step=int(time.time()//30)
    matched=next((n for n in [step-1,step,step+1] if secrets.compare_digest(totp(secret,n),body.otp)),None) if len(body.otp)==6 and body.otp.isascii() and body.otp.isdigit() else None
    if matched is None:
        user.failed_logins+=1
        if user.failed_logins>=5:
            user.mfa_pending=None;user.mfa_pending_until=None;user.failed_logins=0;user.locked_until=datetime.now(timezone.utc)+timedelta(minutes=15)
        db.commit();raise HTTPException(422,'קוד האימות שגוי')
    codes=[secrets.token_hex(8) for _ in range(10)]
    user.mfa_secret=user.mfa_pending;user.mfa_pending=None;user.mfa_pending_until=None;user.mfa_last_step=matched
    user.failed_logins=0
    user.recovery_hashes=json.dumps([recovery_hash(user,c) for c in codes]);revoke_all(db,user)
    audit(db,user,'mfa.enable',user.id);db.commit();return {'recovery_codes':codes,'login_required':True}
@router.post('/settings/mfa/disable')
def disable(body:Proof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    user=prove(db,user,body);user.mfa_secret=None;user.mfa_pending=None;user.recovery_hashes='[]';user.mfa_last_step=-1
    revoke_all(db,user);audit(db,user,'mfa.disable',user.id);db.commit();return {'login_required':True}
class NewUser(Proof):
    email:str=Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    name:str=Field(min_length=1,max_length=120)
    new_password:str=Field(min_length=12,max_length=256)
    role:Literal['admin','counselor']='counselor'
    @field_validator('name')
    @classmethod
    def name_required(cls,v):
        if not v.strip():raise ValueError('שם חובה')
        return v.strip()
class EditUser(Proof):
    active:bool
    role:Literal['admin','counselor']
    new_password:str=Field(default='',max_length=256)
@router.get('/admin/users')
def users(user:User=Depends(admin_user),db:Session=Depends(get_db)):
    return [user_json(u) for u in db.scalars(select(User).order_by(User.name)).all()]
@router.post('/admin/users',status_code=201)
def add_user(body:NewUser,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    user=prove(db,user,body)
    if user.role!="admin":raise HTTPException(403,"נדרשת הרשאת מנהלת")
    row=User(email=body.email.lower().strip(),name=body.name,role=body.role,password_hash=hasher.hash(body.new_password))
    db.add(row)
    try:db.flush()
    except IntegrityError:db.rollback();raise HTTPException(409,'כתובת המייל כבר קיימת')
    audit(db,user,'user.create',row.id);db.commit();return user_json(row)
@router.patch('/admin/users/{uid}')
def edit_user(uid:str,body:EditUser,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    # Lock administrators in deterministic order to prevent concurrent removal of the last admin.
    db.scalars(select(User).where(User.role=='admin').order_by(User.id).with_for_update()).all()
    user=prove(db,user,body)
    if user.role!="admin":raise HTTPException(403,"נדרשת הרשאת מנהלת")
    row=db.scalar(select(User).where(User.id==uid).with_for_update().execution_options(populate_existing=True))
    if not row:raise HTTPException(404,'המשתמשת לא נמצאה')
    if row.id==user.id and (not body.active or body.role!='admin'):raise HTTPException(409,'לא ניתן להסיר את הרשאותייך או להשבית את עצמך')
    if body.new_password and len(body.new_password)<12:raise HTTPException(422,'נדרשת סיסמה באורך 12 תווים לפחות')
    row.active=body.active;row.role=body.role
    if body.new_password:row.password_hash=hasher.hash(body.new_password)
    revoke_all(db,row);audit(db,user,'user.update',row.id);db.commit();return user_json(row)
@router.get('/directory')
def directory(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return [{'id':u.id,'name':u.name,'email':u.email} for u in db.scalars(select(User).where(User.active.is_(True),User.id!=user.id)).all()]
def owner(db,user,sid):
    row=db.scalar(select(Student).where(Student.id==sid,Student.owner_id==user.id).with_for_update())
    if not row:raise HTTPException(404,'הכרטיס אינו בבעלותך')
    return row
@router.get('/students/{sid}/shares')
def shares(sid:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    owner(db,user,sid)
    return [{'id':u.id,'name':u.name,'email':u.email} for u in db.scalars(select(User).join(StudentShare,StudentShare.user_id==User.id).where(StudentShare.student_id==sid)).all()]
class ShareInput(Proof):user_id:str
@router.post('/students/{sid}/shares')
def share(sid:str,body:ShareInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    owner(db,user,sid);prove(db,user,body);target=db.get(User,body.user_id)
    if not target or not target.active or target.id==user.id:raise HTTPException(422,'יש לבחור יועצת מורשית אחרת')
    if not db.get(StudentShare,(sid,target.id)):db.add(StudentShare(student_id=sid,user_id=target.id))
    audit(db,user,'share.create',sid);db.commit();return {'ok':True}
@router.post('/students/{sid}/shares/{uid}/revoke')
def unshare(sid:str,uid:str,body:Proof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    owner(db,user,sid);prove(db,user,body);row=db.get(StudentShare,(sid,uid))
    if row:db.delete(row)
    audit(db,user,'share.revoke',sid);db.commit();return {'ok':True}
class AIInput(Proof):
    api_key:str=Field(default='',max_length=500)
    clear_key:bool=False
    enabled:bool
    preferred:bool=False
    transcription_model:str=Field(min_length=1,max_length=120,pattern=r'^[A-Za-z0-9_./-]+$')
    summary_model:str=Field(min_length=1,max_length=120,pattern=r'^[A-Za-z0-9_./-]+$')
@router.get('/settings/ai')
def ai_settings(user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .ai import PROVIDERS
    result=[]
    for name,cfg in PROVIDERS.items():
        row=db.get(AIConfig,(user.id,name))
        result.append({'id':name,'name':cfg['name'],'enabled':row.enabled if row else False,'configured':bool(row and row.key),'preferred':bool(row and row.preferred),'transcription_model':row.transcription_model if row else cfg['transcription'],'summary_model':row.summary_model if row else cfg['summary']})
    return result
@router.put('/settings/ai/{name}')
def save_ai(name:str,body:AIInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .ai import PROVIDERS
    if name not in PROVIDERS:raise HTTPException(422,'ספק לא נתמך')
    if name=='gemini' and ('/' in body.transcription_model or body.summary_model!=body.transcription_model):raise HTTPException(422,'ב־Gemini יש להגדיר אותו מודל לשתי הפעולות ללא לוכסן')
    prove(db,user,body)
    # Serialize preferred-provider changes for the same account.
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    row=db.get(AIConfig,(user.id,name))
    if not row:row=AIConfig(user_id=user.id,provider=name,transcription_model=body.transcription_model,summary_model=body.summary_model);db.add(row)
    if body.clear_key:row.key=None
    elif body.api_key.strip():row.key=encrypt(body.api_key.strip())
    if body.enabled and not row.key:raise HTTPException(422,'יש להזין מפתח לפני הפעלה')
    if body.preferred:
        for r in db.scalars(select(AIConfig).where(AIConfig.user_id==user.id)).all():r.preferred=False
    row.enabled=body.enabled;row.preferred=body.preferred;row.transcription_model=body.transcription_model;row.summary_model=body.summary_model
    audit(db,user,'ai.configure',user.id);db.commit();return {'ok':True}
@router.post('/settings/ai/{name}/test')
async def test_ai(name:str,body:Proof,user:User=Depends(current_user),db:Session=Depends(get_db)):
    import httpx
    from .ai import PROVIDERS,tls_context
    if name not in PROVIDERS:raise HTTPException(422,'ספק לא נתמך')
    prove(db,user,body);row=db.get(AIConfig,(user.id,name))
    if not row or not row.key:raise HTTPException(422,'שמרי מפתח לפני בדיקה')
    key=decrypt(row.key)
    try:
        async with httpx.AsyncClient(timeout=15,verify=tls_context()) as client:
            url='https://generativelanguage.googleapis.com/v1beta/models' if name=='gemini' else ('https://api.openai.com/v1/models' if name=='openai' else 'https://api.groq.com/openai/v1/models')
            headers={'x-goog-api-key':key} if name=='gemini' else {'Authorization':'Bearer '+key}
            result=await client.get(url,headers=headers)
        if result.status_code!=200:raise HTTPException(502,'בדיקת החיבור נכשלה. בדקי מפתח והרשאות')
        audit(db,user,'ai.test',user.id);db.commit()
        return {'message':'החיבור ומפתח ה־API תקינים. הרשאה לתמלול ולמודל הנבחר תיבדק בעת העיבוד.'}
    except (httpx.HTTPError,OSError):raise HTTPException(502,'לא ניתן להתחבר לספק')
