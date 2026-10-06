import os, sys, importlib.util
from pathlib import Path
from datetime import datetime, timezone
os.environ["JWT_SECRET"]="test-only-"+"x"*40
os.environ["INTERNAL_SERVICE_KEY"]="test-only-"+"y"*40
os.environ["COOKIE_SECURE"]="true"
spec=importlib.util.spec_from_file_location("auth_service",Path(__file__).resolve().parents[1]/"app.py")
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
from fastapi.testclient import TestClient

def test_csrf_rejected():
    with TestClient(service.app) as c:
        assert c.post("/api/auth/login",json={"email":"test@example.test","password":"password"}).status_code==403

def test_login_cookie_and_refresh(monkeypatch):
    calls=[]
    async def fake(path, body):
        calls.append((path,body))
        return {"id":"one","email":"test@example.test","name":"Test"}
    monkeypatch.setattr(service,"data",fake)
    with TestClient(service.app,base_url="https://testserver") as c:
        h={"Origin":service.ORIGIN,"X-Requested-With":"XMLHttpRequest"}
        r=c.post("/api/auth/login",headers=h,json={"email":"test@example.test","password":"password"})
        assert r.status_code==200
        cookie=r.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert len(calls[1][1]["token_hash"])==64
        assert c.post("/api/auth/refresh",headers=h).status_code==200
        assert c.post("/api/auth/logout",headers=h).status_code==200
        assert calls[-1][0]=="/internal/sessions/revoke"
