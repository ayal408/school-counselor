"""RFC 6238, 30 second SHA-1 TOTP with replay protection and recovery codes."""
import base64, hashlib, hmac, json, secrets, struct, time
from datetime import datetime, timezone, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from sqlalchemy import select, delete
from .models import User, RefreshSession
from .security import decrypt
hasher=PasswordHasher()
DUMMY_HASH=hasher.hash('timing-equalization-only')
def utc(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
def totp(secret, step, digits=6):
    mac=hmac.new(base64.b32decode(secret),struct.pack('>Q',step),hashlib.sha1).digest()
    off=mac[-1]&15
    return str((struct.unpack('>I',mac[off:off+4])[0]&0x7fffffff)%10**digits).zfill(digits)
def recovery_hash(user, code):return hashlib.sha256((user.id+':'+code.strip().lower()).encode()).hexdigest()
def check_otp(user, code):
    if not user.mfa_secret:return True
    step=int(time.time()//30)
    if len(code)==6 and code.isascii() and code.isdigit():
        for candidate in [step-1,step,step+1]:
            if candidate>user.mfa_last_step and hmac.compare_digest(totp(decrypt(user.mfa_secret),candidate),code):
                user.mfa_last_step=candidate;return True
    hashes=json.loads(user.recovery_hashes)
    found=recovery_hash(user,code)
    if found in hashes:
        hashes.remove(found);user.recovery_hashes=json.dumps(hashes);return True
    return False
def authenticate(db, user, password, otp='', reset_failures=True):
    # Row lock serializes failed attempts and consumes OTP/recovery codes once.
    if user:user=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    locked=user and user.locked_until and utc(user.locked_until)>datetime.now(timezone.utc)
    try: valid=hasher.verify(user.password_hash if user else DUMMY_HASH,password)
    except (VerificationError,InvalidHashError):valid=False
    if not user or not user.active or locked or not valid or not check_otp(user,otp):
        if user and not locked:
            user.failed_logins+=1
            if user.failed_logins>=5:
                user.locked_until=datetime.now(timezone.utc)+timedelta(minutes=15);user.failed_logins=0
            db.commit()
        raise HTTPException(401,'פרטי ההתחברות או קוד האימות שגויים. לאחר ניסיונות רבים יש להמתין 15 דקות.')
    if reset_failures:user.failed_logins=0
    user.locked_until=None
    return user

def revoke_all(db,user):
    user.session_version+=1
    db.execute(delete(RefreshSession).where(RefreshSession.user_id==user.id))
