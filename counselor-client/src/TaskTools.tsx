import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { dataClient, errorMessage } from './api/http'
import { HebrewDateTimeField } from './DateFields'
export type Task={id:string;student_id:string;title:string;due_at:string;status:'open'|'done'}
export function withinTaskRange(t:Task,range:string,now:Date){
 const due=new Date(t.due_at),start=new Date(now.getFullYear(),now.getMonth(),now.getDate()),end=new Date(start)
 if(range==='overdue')return t.status==='open'&&due<now
 if(range==='today'){end.setDate(end.getDate()+1);return due>=start&&due<end}
 if(range==='week'){end.setDate(end.getDate()+7);return due>=start&&due<end}
 return true
}
export function TaskEditor({task,onClose}:{task:Task;onClose:()=>void}){
 const [base]=useState(task)
 const qc=useQueryClient(),[error,setError]=useState('')
 const edit=useMutation({mutationFn:(body:object)=>dataClient.put('/tasks/'+task.id,body),onSuccess:()=>{void qc.invalidateQueries({queryKey:['tasks']});onClose()},onError:()=>void qc.invalidateQueries({queryKey:['tasks']})})
 function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();setError('');const f=new FormData(e.currentTarget);const due=new Date(String(f.get('due_at')||''));if(!Number.isFinite(due.getTime())){setError('יש לבחור תאריך ושעה');return}edit.mutate({title:f.get('title'),due_at:due.toISOString(),status:f.get('status'),expected:{title:base.title,due_at:base.due_at,status:base.status}})}
 return <form className="task-editor" onSubmit={submit}><h3>עריכת משימה</h3><label>תיאור המשימה<textarea name="title" defaultValue={base.title} required maxLength={2000}/></label><HebrewDateTimeField name="due_at" label="מועד יעד חדש" value={base.due_at}/><label>מצב המשימה<select name="status" defaultValue={base.status}><option value="open">פתוחה</option><option value="done">הושלמה</option></select></label><div className="row"><button disabled={edit.isPending}>שמירת המשימה</button><button type="button" className="secondary" disabled={edit.isPending} onClick={onClose}>ביטול</button></div>{(edit.error||error)&&<p className="error" role="alert">{error||errorMessage(edit.error)}</p>}</form>
}
