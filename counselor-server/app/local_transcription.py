"""Optional internal offline speech recognition; never falls back to a cloud."""
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .database import get_db
from .models import User
from .security import current_user
from .config import INTERNAL_SERVICE_KEY
from .casework import writable, require_consent, audit
router=APIRouter(prefix='/api/local-transcription')
def url():return os.environ.get('LOCAL_TRANSCRIPTION_URL','').rstrip('/')
@router.get('/status')
async def status(u:User=Depends(current_user)):
    if not url():return {'enabled':False,'message':'תמלול מקומי אינו מותקן. ניתן להקליט ולתמלל ידנית.'}
    try:
        async with httpx.AsyncClient(timeout=3) as c:r=await c.get(url()+'/health',headers={'X-Internal-Key':INTERNAL_SERVICE_KEY})
        return {'enabled':r.status_code==200,'message':'מודל מקומי מוכן' if r.status_code==200 else 'המודל המקומי אינו מוכן'}
    except httpx.HTTPError:return {'enabled':False,'message':'שירות התמלול המקומי אינו זמין'}
@router.post('/students/{sid}')
async def transcribe(sid:str,request:Request,u:User=Depends(current_user),db:Session=Depends(get_db)):
    writable(db,u,sid)
    for purpose in ['recording','transcription']:require_consent(db,sid,purpose)
    if not url():raise HTTPException(503,'תמלול מקומי אינו מופעל')
    from .ai import FORMATS
    content_type=request.headers.get('content-type','').split(';')[0]
    if content_type not in FORMATS:raise HTTPException(415,'פורמט שמע אינו נתמך')
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>20*1024*1024:raise HTTPException(413,'הקלטה גדולה מדי')
        data.extend(chunk)
    if not data:raise HTTPException(422,'הקלטה ריקה')
    try:
        async with httpx.AsyncClient(timeout=600) as c:r=await c.post(url()+'/transcribe',content=bytes(data),headers={'X-Internal-Key':INTERNAL_SERVICE_KEY,'Content-Type':content_type})
        if r.status_code!=200:raise HTTPException(502,'התמלול המקומי נכשל. בדקי פורמט ומשך עד 10 דקות')
        text=r.json()['transcript']
        if not isinstance(text,str) or len(text)>20000:raise ValueError()
    except (httpx.HTTPError,ValueError,KeyError):raise HTTPException(502,'שירות התמלול המקומי אינו זמין')
    audit(db,u,'transcription.local',sid);db.commit();return {'transcript':text}
