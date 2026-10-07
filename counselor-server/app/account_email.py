import secrets, hashlib
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from .database import get_db
from .models import User,AccountEmailToken,Audit
from .security import current_user
from .email_service import enqueue,origin,mailbox,connected
from .mfa import hasher,revoke_all
router=APIRouter(prefix='/api/account')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def queue_token(db,user,purpose):
    expiry=datetime.now(timezone.utc)+timedelta(minutes=30 if purpose=='reset' else 24*60)
    # Rate limit per account, independent of client IP; replace prior tokens only after a minute.
    current=db.scalar(select(AccountEmailToken).where(AccountEmailToken.user_id==user.id,AccountEmailToken.purpose==purpose,AccountEmailToken.expires_at>expiry-timedelta(minutes=1)))
    if current:return
    db.execute(delete(AccountEmailToken).where(AccountEmailToken.user_id==user.id,AccountEmailToken.purpose==purpose))
    token=secrets.token_urlsafe(48)
    db.add(AccountEmailToken(token_hash=digest(token),user_id=user.id,purpose=purpose,expires_at=expiry))
    if purpose=='reset':title='בחירת סיסמה למרחב';text='התקבלה בקשה לבחירת סיסמה לחשבונך במרחב. הקישור תקף ל־30 דקות ולשימוש אחד. אם לא ביקשת זאת, אפשר להתעלם. אימות דו־שלבי, אם הופעל, נשאר פעיל.'
    else:title='אימות כתובת המייל במרחב';text='לחצי על הקישור כדי לאמת את כתובת המייל של חשבונך. הקישור תקף ל־24 שעות ולשימוש אחד. אם לא ביקשת זאת, אפשר להתעלם.'
    enqueue(db,user.email,'password_reset' if purpose=='reset' else 'email_verify',title,text,origin()+'/account/'+purpose+'#token='+token,user_id=user.id)
class ResetRequest(BaseModel):email:str=Field(min_length=3,max_length=254)
@router.post('/reset/request')
def request_reset(body:ResetRequest,db:Session=Depends(get_db)):
    if mailbox(body.email.strip()):
        user=db.scalar(select(User).where(User.email==body.email.strip().lower(),User.active.is_(True)).with_for_update())
        if user and connected(db):queue_token(db,user,'reset');db.commit()
    return {'message':'אם קיים חשבון פעיל בכתובת זו והמייל מוגדר, יישלח קישור לבחירת סיסמה.'}
class TokenInput(BaseModel):token:str=Field(min_length=32,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
class ResetComplete(TokenInput):password:str=Field(min_length=12,max_length=256)
@router.post('/reset/complete')
def reset(body:ResetComplete,db:Session=Depends(get_db)):
    row=db.scalar(select(AccountEmailToken).where(AccountEmailToken.token_hash==digest(body.token),AccountEmailToken.purpose=='reset',AccountEmailToken.expires_at>datetime.now(timezone.utc)))
    if not row:raise HTTPException(422,'הקישור אינו תקין, כבר נוצל או פג תוקף')
    user=db.scalar(select(User).where(User.id==row.user_id).with_for_update())
    if not user or not user.active:raise HTTPException(422,'הקישור אינו תקין, כבר נוצל או פג תוקף')
    consumed=db.execute(delete(AccountEmailToken).where(AccountEmailToken.token_hash==digest(body.token),AccountEmailToken.purpose=='reset',AccountEmailToken.expires_at>datetime.now(timezone.utc)).returning(AccountEmailToken.user_id).execution_options(synchronize_session=False)).first()
    if not consumed:raise HTTPException(422,'הקישור אינו תקין, כבר נוצל או פג תוקף')
    user.password_hash=hasher.hash(body.password);user.failed_logins=0;user.locked_until=None;user.email_verified=True
    revoke_all(db,user)
    db.add(Audit(user_id=user.id,action='password.reset',record_id=user.id))
    enqueue(db,user.email,'account_security','הסיסמה שלך במרחב שונתה','הסיסמה שונתה באמצעות קישור למייל. כל ההתחברויות הקודמות בוטלו. אם לא ביצעת זאת, פני למנהלת המערכת.',origin(),user_id=user.id)
    db.commit();return {'message':'הסיסמה עודכנה. התחברי מחדש; אימות דו־שלבי, אם הופעל, עדיין נדרש.'}
@router.post('/verify/request')
def request_verify(user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not connected(db):raise HTTPException(409,'המייל עדיין אינו מחובר')
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    queue_token(db,user,'verify');db.commit();return {'message':'מייל אימות נוסף לתור השליחה.'}
@router.post('/verify/complete')
def verify(body:TokenInput,db:Session=Depends(get_db)):
    pending=db.scalar(select(AccountEmailToken).where(AccountEmailToken.token_hash==digest(body.token),AccountEmailToken.purpose=='verify',AccountEmailToken.expires_at>datetime.now(timezone.utc)))
    if not pending:raise HTTPException(422,'הקישור אינו תקין, כבר נוצל או פג תוקף')
    user=db.scalar(select(User).where(User.id==pending.user_id).with_for_update())
    if not user or not user.active:raise HTTPException(422,'החשבון אינו פעיל')
    consumed=db.execute(delete(AccountEmailToken).where(AccountEmailToken.token_hash==digest(body.token),AccountEmailToken.purpose=='verify',AccountEmailToken.expires_at>datetime.now(timezone.utc)).returning(AccountEmailToken.user_id).execution_options(synchronize_session=False)).first()
    if not consumed:raise HTTPException(422,'הקישור אינו תקין, כבר נוצל או פג תוקף')
    user.email_verified=True;db.add(Audit(user_id=user.id,action='email.verify',record_id=user.id));db.commit();return {'message':'כתובת המייל אומתה בהצלחה.'}
