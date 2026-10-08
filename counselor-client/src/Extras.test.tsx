import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { dataClient } from './api/http'
import { StudentDetails } from './StudentDetails'
import { MeetingPrint } from './MeetingPrint'
import { TaskEditor, withinTaskRange, type Task } from './TaskTools'
import { Planning } from './Planning'
vi.mock('./api/http',()=>({dataClient:{get:vi.fn(),put:vi.fn(),post:vi.fn(),patch:vi.fn()},errorMessage:(e:unknown)=>e instanceof Error?e.message:'Error'}))
vi.mock('./DateFields',()=>({HebrewDateTimeField:({name,value}:{name:string;value:string})=><input type="hidden" name={name} value={value}/>,HebrewDateField:()=>null}))
const student={id:'s',name:'שם פרטי לבדיקה',classroom:'ח1',referral:'מידע',school_year:'2026-2027',archived:false,can_edit:true}
function provider(children:React.ReactNode){return <QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>{children}</QueryClientProvider>}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(dataClient.put).mockResolvedValue({data:{}});vi.mocked(dataClient.post).mockResolvedValue({data:{}})})
afterEach(cleanup)
it('edits student details with the original snapshot and hides actions from shared readers',async()=>{
 const view=render(provider(<StudentDetails s={student}/>));fireEvent.click(screen.getByRole('button',{name:'עריכת פרטים'}));fireEvent.change(screen.getByLabelText('שם מלא'),{target:{value:'שם חדש'}});fireEvent.click(screen.getByRole('button',{name:'שמירת פרטי הכרטיס'}))
 await waitFor(()=>expect(dataClient.put).toHaveBeenCalledWith('/students/s',{name:'שם חדש',classroom:'ח1',referral:'מידע',expected:{name:student.name,classroom:'ח1',referral:'מידע'}}))
 view.unmount();render(provider(<StudentDetails s={{...student,can_edit:false,archived:true}}/>));expect(screen.queryByRole('button',{name:'עריכת פרטים'})).toBeNull();expect(screen.queryByRole('button',{name:'החזרה לליווי'})).toBeNull()
})
it('does not include identifying fields in the print view until selected',async()=>{
 vi.mocked(dataClient.get).mockResolvedValue({data:{student,meeting:{id:'m',student_id:'s',starts_at:'2026-10-08T09:00:00Z',version:2,notes:'תיעוד',summary:'סיכום',topic:'social'}}})
 render(provider(<MemoryRouter initialEntries={['/students/s/meetings/m/print']}><Routes><Route path="/students/:id/meetings/:mid/print" element={<MeetingPrint/>}/></Routes></MemoryRouter>))
 await screen.findByText('תיעוד');expect(screen.queryByText(/שם פרטי לבדיקה/)).toBeNull()
 fireEvent.click(screen.getByRole('checkbox'));expect(screen.getByText(/שם פרטי לבדיקה/)).toBeTruthy();expect(dataClient.get).toHaveBeenCalledWith('/students/s/meetings/m/print')
})
it('keeps the task edit snapshot when a query refreshes mid-edit',async()=>{
 const original:Task={id:'t',student_id:'s',title:'מקור',due_at:'2026-10-08T09:00:00Z',status:'open'}
 const close=vi.fn(),client=new QueryClient();const view=render(<QueryClientProvider client={client}><TaskEditor task={original} onClose={close}/></QueryClientProvider>)
 fireEvent.change(screen.getByLabelText('תיאור המשימה'),{target:{value:'עריכה'}})
 view.rerender(<QueryClientProvider client={client}><TaskEditor task={{...original,title:'עדכון מחלון אחר'}} onClose={close}/></QueryClientProvider>)
 fireEvent.click(screen.getByRole('button',{name:'שמירת המשימה'}));await waitFor(()=>expect(dataClient.put).toHaveBeenCalled())
 expect(vi.mocked(dataClient.put).mock.calls[0][1]).toEqual({title:'עריכה',due_at:new Date(original.due_at).toISOString(),status:'open',expected:{title:'מקור',due_at:original.due_at,status:'open'}})
})
it('filters overdue tasks and excludes archived cards by default',async()=>{
 const now=new Date(),past=new Date(now.getTime()-86400000).toISOString(),future=new Date(now.getTime()+86400000).toISOString()
 vi.mocked(dataClient.get).mockImplementation(async path=>({data:path==='/students'?[student,{...student,id:'archive',archived:true}]:[
 {id:'late',student_id:'s',title:'צריך מעקב',due_at:past,status:'open'},
 {id:'later',student_id:'s',title:'בהמשך',due_at:future,status:'open'},
 {id:'done',student_id:'s',title:'כבר הסתיים',due_at:past,status:'done'},
 {id:'archived',student_id:'archive',title:'משימה מהארכיון',due_at:past,status:'open'}]}))
 render(provider(<MemoryRouter><Planning kind="tasks"/></MemoryRouter>));await screen.findByText('צריך מעקב');await waitFor(()=>expect(screen.queryByText('משימה מהארכיון')).toBeNull())
 fireEvent.change(screen.getByLabelText('מועד יעד'),{target:{value:'overdue'}})
 expect(screen.getByText('צריך מעקב')).toBeTruthy();expect(screen.queryByText('בהמשך')).toBeNull();expect(screen.queryByText('כבר הסתיים')).toBeNull()
 fireEvent.click(screen.getByRole('checkbox'));expect(screen.getByText('משימה מהארכיון')).toBeTruthy()
})
it('uses local day boundaries and excludes completed overdue tasks',()=>{
 const now=new Date(2026,9,8,12),base:Task={id:'t',student_id:'s',title:'בדיקה',due_at:new Date(2026,9,9,0).toISOString(),status:'open'}
 expect(withinTaskRange(base,'today',now)).toBe(false)
 expect(withinTaskRange({...base,due_at:new Date(2026,9,8,0).toISOString()},'today',now)).toBe(true)
 expect(withinTaskRange({...base,due_at:new Date(2026,9,15,0).toISOString()},'week',now)).toBe(false)
 expect(withinTaskRange({...base,due_at:new Date(2026,9,7).toISOString(),status:'done'},'overdue',now)).toBe(false)
})
