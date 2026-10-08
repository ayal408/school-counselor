import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Recorder } from './Recorder'
import { dataClient } from './api/http'
vi.mock('./api/http',()=>({dataClient:{get:vi.fn(),post:vi.fn()},errorMessage:(e:unknown)=>e instanceof Error?e.message:'Error'}))
class Recording {
 static isTypeSupported(){return true}
 state='inactive';onstop:()=>void=()=>{};ondataavailable:(e:{data:Blob})=>void=()=>{};onerror:()=>void=()=>{}
 start(){this.state='recording'}
 stop(){this.state='inactive';this.ondataavailable({data:new Blob(['synthetic'],{type:'audio/webm'})});this.onstop()}
 pause(){this.state='paused'}
 resume(){this.state='recording'}
}
const mic=vi.fn(),stop=vi.fn()
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('MediaRecorder',Recording);Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:mic}});mic.mockResolvedValue({getTracks:()=>[{stop}]});Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:synthetic')});Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});vi.mocked(dataClient.get).mockImplementation(async()=>({data:{enabled:false,providers:[]}}));vi.mocked(dataClient.post).mockResolvedValue({data:{ok:true}})})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function open(){const transcript=vi.fn();render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><Recorder studentId="s" onTranscript={transcript} onSummary={vi.fn()} onBusy={vi.fn()}/></QueryClientProvider>);return transcript}
it('records and allows manual transcription and playback with no AI provider',async()=>{
 const transcript=open();await waitFor(()=>expect(dataClient.get).toHaveBeenCalledTimes(2))
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'התחלת הקלטה'}));fireEvent.click(await screen.findByRole('button',{name:'עצירה'}))
 expect(document.querySelector('audio')?.hasAttribute('controls')).toBe(true)
 fireEvent.change(screen.getByLabelText('מהירות'),{target:{value:'0.75'}});expect(document.querySelector('audio')?.playbackRate).toBe(.75)
 fireEvent.change(screen.getByLabelText('כתיבת תמלול ידני'),{target:{value:'תמלול שלי'}})
 expect(transcript).toHaveBeenLastCalledWith('תמלול שלי',false)
 expect(dataClient.post).toHaveBeenCalledWith('/students/s/recording-authorize')
 expect(vi.mocked(dataClient.post).mock.calls.some(([path])=>String(path).includes('/ai/'))).toBe(false)
 expect(stop).toHaveBeenCalled()
})
it('checks recorded consent before requesting microphone access',async()=>{
 vi.mocked(dataClient.post).mockRejectedValue(Error('נדרשת הסכמה תקפה'));open()
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'התחלת הקלטה'}));await screen.findByText('נדרשת הסכמה תקפה')
 expect(mic).not.toHaveBeenCalled()
})
