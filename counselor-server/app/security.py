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
        if not user or not user.active: raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "יש להתחבר למערכת")
