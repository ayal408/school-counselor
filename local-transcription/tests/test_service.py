"""Decode synthetic WAV in memory; no model download and no network inference."""
import io,wave,importlib.util
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
spec=importlib.util.spec_from_file_location('speech_service',Path(__file__).resolve().parents[1]/'service.py')
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
def audio(seconds=1):
    data=io.BytesIO()
    with wave.open(data,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x00'*(16000*seconds))
    return data.getvalue()
class Model:
    def __init__(self):self.calls=0
    def transcribe(self,data,**kwargs):
        self.calls+=1;assert kwargs['language']=='he' and kwargs['vad_filter'] and len(data)==16000
        return iter([SimpleNamespace(text=' תמלול סינתטי')]),None

def test_auth_decode_duration_and_single_slot(monkeypatch):
    monkeypatch.setenv('INTERNAL_SERVICE_KEY','synthetic-'+40*'x');model=Model();monkeypatch.setattr(service,'model',model)
    client=TestClient(service.app);h={'X-Internal-Key':'synthetic-'+40*'x','Content-Type':'audio/wav'}
    assert client.post('/transcribe',content=audio()).status_code==403
    assert client.get('/health',headers=h).status_code==200
    response=client.post('/transcribe',headers=h,content=audio());assert response.status_code==200 and response.json()['transcript']=='תמלול סינתטי'
    assert model.calls==1
    monkeypatch.setattr(service,'MAX_SECONDS',1)
    assert client.post('/transcribe',headers=h,content=audio(2)).status_code==413
    assert client.post('/transcribe',headers=h,content=b'invalid').status_code==422
    service.slot.acquire()
    try:assert client.post('/transcribe',headers=h,content=audio()).status_code==429
    finally:service.slot.release()
    assert model.calls==1

def test_startup_is_explicit_offline_local_directory(monkeypatch):
    import faster_whisper
    calls=[]
    monkeypatch.setattr(faster_whisper,'WhisperModel',lambda *a,**kw:calls.append((a,kw)) or Model())
    service.load();assert calls[0][0]==('/models/whisper',)
    assert calls[0][1]['local_files_only'] is True and calls[0][1]['device']=='cpu'
    import os
    assert os.environ['HF_HUB_OFFLINE']=='1'
