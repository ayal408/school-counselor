"""Offline model mounted by operator. Audio decoded in memory, never persisted."""
import os, io, secrets, threading
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
from fastapi import FastAPI, Request, HTTPException
from starlette.concurrency import run_in_threadpool
app=FastAPI(docs_url=None,redoc_url=None)
model=None
slot=threading.Lock()
MAX_SECONDS=600
def auth(request):
    expected=os.environ.get('INTERNAL_SERVICE_KEY','')
    if len(expected)<32 or not secrets.compare_digest(request.headers.get('X-Internal-Key',''),expected):raise HTTPException(403)
@app.on_event('startup')
def load():
    global model
    from faster_whisper import WhisperModel
    model=WhisperModel('/models/whisper',device='cpu',compute_type='int8',local_files_only=True,cpu_threads=int(os.environ.get('CPU_THREADS','4')),num_workers=1)
@app.get('/health')
def health(request:Request):
    auth(request)
    if model is None:raise HTTPException(503)
    return {'ready':True}
def recognize(data):
    if not slot.acquire(blocking=False):raise HTTPException(429,'busy')
    try:
        # Limit decoding before a large compressed stream allocates an unbounded array.
        import av
        from faster_whisper.audio import decode_audio
        with av.open(io.BytesIO(data)) as container:
            total=0;rate=None
            for frame in container.decode(audio=0):
                rate=frame.sample_rate;total+=frame.samples
                if not rate or total/rate>MAX_SECONDS:raise HTTPException(413,'duration')
        audio=decode_audio(io.BytesIO(data),sampling_rate=16000)
        if len(audio)>MAX_SECONDS*16000:raise HTTPException(413,'duration')
        segments,_=model.transcribe(audio,language='he',beam_size=5,vad_filter=True)
        text=''
        for segment in segments:
            text+=segment.text
            if len(text)>20000:raise HTTPException(413,'text')
        return {'transcript':text.strip()}
    except HTTPException:raise
    except Exception:raise HTTPException(422,'invalid audio')
    finally:slot.release()
@app.post('/transcribe')
async def transcribe(request:Request):
    auth(request);data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>20*1024*1024:raise HTTPException(413)
        data.extend(chunk)
    if not data or model is None:raise HTTPException(503)
    return await run_in_threadpool(recognize,bytes(data))
