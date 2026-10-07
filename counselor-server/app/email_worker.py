"""Run separately: python -m app.email_worker. Never logs message bodies or credentials."""
import asyncio, logging
from sqlalchemy.exc import SQLAlchemyError
from .database import SessionLocal
from .email_service import process_one, connected, enqueue, origin
from .models import EmailOutbox, User
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
def reminders(db):
    now=datetime.now(timezone.utc)
    if not connected(db):return
    candidates=db.scalars(select(User).where(User.active.is_(True),User.email_verified.is_(True)).with_for_update(skip_locked=True)).all()
    for user in candidates:
        from .mfa import utc
        if user.last_backup and utc(user.last_backup)>now-timedelta(days=7):continue
        sent=db.scalar(select(EmailOutbox.id).where(EmailOutbox.user_id==user.id,EmailOutbox.kind=='backup_reminder',EmailOutbox.created_at>now-timedelta(days=7)).limit(1))
        if not sent:enqueue(db,user.email,'backup_reminder','תזכורת לגיבוי במרחב','לא נוצר גיבוי אישי בשבוע האחרון. ניתן ליצור גיבוי מוצפן במסך ההגדרות. ודאי שהקובץ וסיסמת הגיבוי נשמרים במקום מוגן.',origin()+'/settings',user_id=user.id)
    db.commit()

async def main():
    next_reminder=0
    while True:
        try:
            with SessionLocal() as db:
                now=datetime.now(timezone.utc)
                # Obsolete account links and stale notifications must not be sent later.
                rows=db.scalars(select(EmailOutbox).where(EmailOutbox.status.in_(['pending','sending']),EmailOutbox.created_at<now-timedelta(hours=24))).all()
                for row in rows:
                    row.status='expired' if row.status=='pending' else 'uncertain';row.payload=None;row.failure_code='EXPIRED' if row.status=='expired' else 'DELIVERY_UNKNOWN'
                reset_rows=db.scalars(select(EmailOutbox).where(EmailOutbox.status=='pending',EmailOutbox.kind=='password_reset',EmailOutbox.created_at<now-timedelta(minutes=30))).all()
                for row in reset_rows:row.status='expired';row.payload=None;row.failure_code='EXPIRED'
                uncertain=db.scalars(select(EmailOutbox).where(EmailOutbox.status=='sending',EmailOutbox.next_attempt<now-timedelta(minutes=5))).all()
                for row in uncertain:row.status='uncertain';row.payload=None;row.failure_code='DELIVERY_UNKNOWN'
                db.commit()
                if asyncio.get_running_loop().time()>=next_reminder:
                    reminders(db);next_reminder=asyncio.get_running_loop().time()+3600
            processed=await process_one(SessionLocal)
        except SQLAlchemyError:
            logging.warning('Email worker database is not ready');processed=False
        except Exception:
            logging.warning('Email worker temporarily unavailable');processed=False
        await asyncio.sleep(1 if processed else 10)
if __name__=='__main__':asyncio.run(main())
