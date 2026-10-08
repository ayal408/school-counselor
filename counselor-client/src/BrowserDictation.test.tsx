import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserDictation } from './BrowserDictation'
import { dataClient } from './api/http'
vi.mock('./api/http',()=>({dataClient:{post:vi.fn()},errorMessage:(e:unknown)=>e instanceof Error?e.message:'Error'}))
class Recognition {
 static latest:Recognition
 lang='';continuous=false;interimResults=true
 onresult:((e: {resultIndex:number;results:{isFinal:boolean;0:{transcript:string}}[]})=>void)|null=null
 onend:(()=>void)|null=null
 onerror:((e:{error:string})=>void)|null=null
 constructor(){Recognition.latest=this}
 start=vi.fn();stop=vi.fn(()=>this.onend?.());abort=vi.fn()
}
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('SpeechRecognition',Recognition);vi.mocked(dataClient.post).mockResolvedValue({data:{ok:true}})})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
function open(){const transcript=vi.fn(),busy=vi.fn();const rendered=render(<BrowserDictation sid="s" disabled={false} onTranscript={transcript} onBusy={busy}/>);return {transcript,busy,...rendered}}
async function start(){fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'התחלת הכתבה בדפדפן'}));await screen.findByText('מקשיבה בעברית…');return Recognition.latest}
it('authorizes before browser capture, fixes Hebrew and emits final text only once',async()=>{
 const {transcript}=open();const r=await start()
 expect(dataClient.post).toHaveBeenCalledWith('/students/s/browser-dictation-authorize');expect(r.lang).toBe('he-IL');expect(r.start).toHaveBeenCalledOnce()
 const event={resultIndex:0,results:[{isFinal:false,0:{transcript:'טיוטה'}}]};act(()=>r.onresult?.(event));expect(transcript).not.toHaveBeenCalled()
 event.results[0]={isFinal:true,0:{transcript:' תיעוד בעברית '}}
 act(()=>{r.onresult?.(event);r.onresult?.(event)});expect(transcript).toHaveBeenCalledExactlyOnceWith('תיעוד בעברית')
 fireEvent.click(screen.getByRole('button',{name:'עצירת הכתבה'}));expect(r.stop).toHaveBeenCalledOnce();expect(screen.getByRole('button',{name:'התחלת הכתבה בדפדפן'})).toBeTruthy()
})
it('does not start recognition when server consent is denied',async()=>{
 vi.mocked(dataClient.post).mockRejectedValue(Error('יש לתעד הסכמה תקפה'));open();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'התחלת הכתבה בדפדפן'}));await screen.findByText('יש לתעד הסכמה תקפה');expect(screen.getByRole('button',{name:'התחלת הכתבה בדפדפן'})).toBeTruthy()
})
it('aborts and detaches listeners when navigating away',async()=>{
 const {unmount,transcript}=open();const r=await start();unmount();expect(r.abort).toHaveBeenCalledOnce();expect(r.onresult).toBeNull();expect(transcript).not.toHaveBeenCalled()
})
it('shows unsupported browsers and does not silently use a provider',()=>{
 vi.stubGlobal('SpeechRecognition',undefined);vi.stubGlobal('webkitSpeechRecognition',undefined);open();expect(screen.getByText(/ההכתבה אינה נתמכת/)).toBeTruthy();expect(dataClient.post).not.toHaveBeenCalled()
})

it('stops when the server-authorized consent deadline expires',async()=>{
 vi.useFakeTimers();vi.mocked(dataClient.post).mockResolvedValue({data:{ok:true,valid_until:new Date(Date.now()+1000).toISOString()}})
 open();await act(async()=>{fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'התחלת הכתבה בדפדפן'}));await Promise.resolve()})
 const r=Recognition.latest;expect(r.start).toHaveBeenCalledOnce()
 act(()=>vi.advanceTimersByTime(1001));expect(r.stop).toHaveBeenCalledOnce()
})
