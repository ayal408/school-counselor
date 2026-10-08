import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { dataClient, errorMessage } from './api/http'
import type { Student } from './types'
export function StudentDetails({s}:{s:Student}) {
 const [editing,setEditing]=useState(false),[base,setBase]=useState(s),qc=useQueryClient()
 const update=useMutation({mutationFn:(body:object)=>dataClient.put(`/students/${s.id}`,body),onSuccess:()=>{void qc.invalidateQueries({queryKey:['students']});setEditing(false)}})
 const restore=useMutation({mutationFn:()=>dataClient.post(`/students/${s.id}/restore`),onSuccess:()=>void qc.invalidateQueries({queryKey:['students']})})
 function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();update.mutate({...Object.fromEntries(new FormData(e.currentTarget)),expected:{name:base.name,classroom:base.classroom,referral:base.referral}})}
 return <section className="card"><div className="row"><h2>פרטי הכרטיס</h2>{s.can_edit!==false&&<div className="row"><button className="secondary" disabled={update.isPending} onClick={()=>{update.reset();setBase(s);setEditing(!editing)}}>{editing?'ביטול עריכה':'עריכת פרטים'}</button>{s.archived&&<button disabled={restore.isPending} onClick={()=>{if(window.confirm('להחזיר את הכרטיס לליווי פעיל? פגישות שבוטלו והרשאות שיתוף שהוסרו לא יחודשו.'))restore.mutate()}}>החזרה לליווי</button>}</div>}</div>{editing?<form onSubmit={submit}><div className="form-grid"><label>שם מלא<input name="name" defaultValue={base.name} required maxLength={120}/></label><label>כיתה<input name="classroom" defaultValue={base.classroom} required maxLength={40}/></label></div><label>סיבת הפניה<textarea name="referral" defaultValue={base.referral} maxLength={4000} rows={4}/></label><button disabled={update.isPending}>שמירת פרטי הכרטיס</button></form>:<><p>כיתה {s.classroom} • שנת לימודים {s.school_year}</p><h3>סיבת הפניה</h3><p className="pre">{s.referral||'לא הוזנה סיבת הפניה'}</p></>}{(update.error||restore.error)&&<p role="alert" className="error">{errorMessage(update.error||restore.error)}</p>}</section>
}
