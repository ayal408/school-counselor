import os, secrets, hashlib
from datetime import datetime, timedelta, timezone
import httpx, jwt
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
SECRET = os.environ["JWT_SECRET"]
KEY = os.environ["INTERNAL_SERVICE_KEY"]
if min(len(SECRET), len(KEY)) < 32: raise RuntimeError("Secrets must be at least 32 characters")
DATA_URL = os.environ.get("DATA_SERVICE_URL", "http://localhost:8080")
ORIGIN = os.environ.get("CLIENT_ORIGIN", "http://localhost:8088")
SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
COOKIE = "counselor_refresh"
app = FastAPI(title="Counselor Authentication", docs_url=None, redoc_url=None)
class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
@app.exception_handler(RequestValidationError)
async def invalid(request, exc): return JSONResponse(status_code=422, content={"detail": "יש לבדוק את פרטי ההתחברות"})
@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
def csrf(request):
    if request.headers.get("origin") != ORIGIN or request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise HTTPException(403, "הגישה אינה מורשית")
def digest(token): return hashlib.sha256(token.encode()).hexdigest()
async def data(path, body):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(DATA_URL + path, json=body, headers={"X-Internal-Key": KEY})
        if r.status_code >= 500: raise HTTPException(503, "שירות ההתחברות אינו זמין כרגע")
        if r.status_code >= 400: raise HTTPException(401, "פרטי ההתחברות שגויים או שההתחברות פגה")
        return r.json()
    except httpx.HTTPError: raise HTTPException(503, "שירות ההתחברות אינו זמין כרגע")
def issue(response, user, refresh):
    now = datetime.now(timezone.utc)
    access = jwt.encode({"sub": user["id"], "iat": now, "exp": now + timedelta(minutes=10), "iss": "counselor-auth", "aud": "counselor-api"}, SECRET, algorithm="HS256")
    response.set_cookie(COOKIE, refresh, httponly=True, secure=SECURE, samesite="strict", path="/api/auth", max_age=8*3600)
    return {"accessToken": access, "user": user}
@app.get("/healthz/live")
def live(): return {"status": "ok"}
@app.post("/api/auth/login")
async def login(body: Login, request: Request, response: Response):
    csrf(request)
    user = await data("/internal/verify-password", body.model_dump())
    refresh = secrets.token_urlsafe(48)
    await data("/internal/sessions", {"token_hash": digest(refresh), "user_id": user["id"], "expires_at": (datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()})
    return issue(response, user, refresh)
@app.post("/api/auth/refresh")
async def refresh(request: Request, response: Response):
    csrf(request)
    old = request.cookies.get(COOKIE)
    if not old: raise HTTPException(401, "יש להתחבר למערכת")
    token = secrets.token_urlsafe(48)
    user = await data("/internal/sessions/rotate", {"token_hash": digest(old), "new_hash": digest(token), "expires_at": (datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()})
    return issue(response, user, token)
@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    csrf(request)
    old = request.cookies.get(COOKIE)
    if old: await data("/internal/sessions/revoke", {"token_hash": digest(old)})
    response.delete_cookie(COOKIE, path="/api/auth", secure=SECURE, httponly=True, samesite="strict")
    return {"ok": True}
