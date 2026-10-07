from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
import jwt, secrets
from .config import JWT_SECRET, INTERNAL_SERVICE_KEY, DATA_ENCRYPTION_KEY
from .database import get_db
from .models import User
cipher = Fernet(DATA_ENCRYPTION_KEY.encode())
bearer = HTTPBearer(auto_error=False)
def encrypt(value): return cipher.encrypt(value.encode()).decode()
def decrypt(value): return cipher.decrypt(value.encode()).decode()
def internal(x_internal_key: str = Header(default="")):
    if not secrets.compare_digest(x_internal_key, INTERNAL_SERVICE_KEY):
        raise HTTPException(403, "הגישה אינה מורשית")
def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    try:
        if credentials is None: raise ValueError()
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"], audience="counselor-api", issuer="counselor-auth", options={"require": ["exp", "sub", "iat"]})
        user = db.get(User, claims["sub"])
        if not user or not user.active or claims.get("v", 0) != user.session_version: raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "יש להתחבר למערכת")

def admin_user(user: User = Depends(current_user)):
    if user.role != "admin": raise HTTPException(403, "נדרשת הרשאת מנהלת")
    return user

def visible_condition(user):
    from sqlalchemy import or_, select
    from .models import Student, StudentShare
    return or_(Student.owner_id == user.id, Student.id.in_(select(StudentShare.student_id).where(StudentShare.user_id == user.id)))

def readable_student(db, user, sid):
    from sqlalchemy import select
    from .models import Student
    row = db.scalar(select(Student).where(Student.id == sid, visible_condition(user)))
    if not row: raise HTTPException(404, "התלמידה לא נמצאה")
    return row
