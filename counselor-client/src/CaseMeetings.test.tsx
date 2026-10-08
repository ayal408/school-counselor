// These workflows prevent loss or unauthorized publication of sensitive notes.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MeetingEditor } from './CaseMeetings'
import { dataClient } from './api/http'
vi.mock('./api/http',()=>({dataClient:{get:vi.fn(),put:vi.fn(),post:vi.fn()},errorMessage:(e:unknown)=>e instanceof Error?e.message:'Error'}))
vi.mock('./DateFields',()=>({HebrewDateTimeField:()=>null}))
vi.mock('./Recorder',()=>({Recorder:({onTranscript}:{onTranscript:(s:string,a:boolean)=>void})=><button type="button" onClick={()=>onTranscript('תמלול אוטומטי',true)}>תמלול בדיקה</button>}))
function open(initial?:Parameters<typeof MeetingEditor>[0]['initial']){
 const close=vi.fn();const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})
 render(<QueryClientProvider client={client}><MeetingEditor sid="s" initial={initial} onClose={close}/></QueryClientProvider>);return close
}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(dataClient.get).mockResolvedValue({data:{version:0,document:null}});vi.mocked(dataClient.put).mockResolvedValue({data:{version:1}});vi.mocked(dataClient.post).mockResolvedValue({data:{}})})
afterEach(()=>cleanup())
describe('meeting drafts',()=>{
 it('restores an encrypted server draft, autosaves changes and publishes the matching version',async()=>{
  vi.mocked(dataClient.get).mockResolvedValue({data:{version:7,document:{notes:'טיוטה קודמת',starts_at:'2026-10-08T09:00:00Z'}}})
  vi.mocked(dataClient.put).mockResolvedValue({data:{version:8}})
  const close=open();const notes=await screen.findByLabelText('תיעוד והערות');expect((notes as HTMLTextAreaElement).value).toBe('טיוטה קודמת')
  fireEvent.change(notes,{target:{value:'תיעוד חדש'}})
  await waitFor(()=>expect(dataClient.put).toHaveBeenCalled(),{timeout:2500})
  const request=vi.mocked(dataClient.put).mock.calls[0][1] as {document:{notes:string};expected_version:number;meeting_id:string}
  expect(request.document.notes).toBe('תיעוד חדש');expect(request.expected_version).toBe(7);expect(request.meeting_id).toBe('')
  await screen.findByText(/טיוטה נשמרה מוצפנת/)
  fireEvent.click(screen.getByRole('button',{name:'אישור ושמירת פגישה'}))
  await waitFor(()=>expect(close).toHaveBeenCalled())
  expect(dataClient.post).toHaveBeenCalledWith('/students/s/draft/publish',{expected_version:8,meeting_id:''})
 })
 it('does not publish on an autosave conflict',async()=>{
  vi.mocked(dataClient.put).mockRejectedValue(Error('הטיוטה שונתה בחלון אחר'))
  const close=open();fireEvent.change(await screen.findByLabelText('תיעוד והערות'),{target:{value:'חדש'}})
  await screen.findByText('הטיוטה שונתה בחלון אחר',{}, {timeout:2500})
  expect((screen.getByRole('button',{name:'אישור ושמירת פגישה'}) as HTMLButtonElement).disabled).toBe(true)
  expect(dataClient.post).not.toHaveBeenCalled();expect(close).not.toHaveBeenCalled()
 })
 it('keeps edit drafts separate and requires review of automatic transcription',async()=>{
  const close=open({id:'m',student_id:'s',starts_at:'2026-10-08T09:00:00Z',notes:'ישן',summary:'',version:4})
  await screen.findByLabelText('תיעוד והערות')
  expect(dataClient.get).toHaveBeenCalledWith('/students/s/draft',{params:{meeting_id:'m'}})
  fireEvent.click(screen.getByRole('button',{name:'תמלול בדיקה'}))
  const publish=screen.getByRole('button',{name:'אישור ושמירת פגישה'}) as HTMLButtonElement
  expect(publish.disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
  await waitFor(()=>expect(dataClient.put).toHaveBeenCalled(),{timeout:2500})
  const request=vi.mocked(dataClient.put).mock.calls[0][1] as {meeting_id:string;document:{expected_version:number;ai_reviewed:boolean}}
  expect(request.meeting_id).toBe('m');expect(request.document.expected_version).toBe(4);expect(request.document.ai_reviewed).toBe(true)
  await screen.findByText(/טיוטה נשמרה מוצפנת/);fireEvent.click(publish)
  await waitFor(()=>expect(close).toHaveBeenCalled());expect(dataClient.post).toHaveBeenCalledWith('/students/s/draft/publish',{expected_version:1,meeting_id:'m'})
 })
})
