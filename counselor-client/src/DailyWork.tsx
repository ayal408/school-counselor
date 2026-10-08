import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dataClient, errorMessage } from './api/http'
import type { Student } from './types'
type Entry={id:string;student_id:string;status:string;title?:string;due_at?:string;starts_at?:string}
type Consent={id:string;student_id:string;purpose:string;expires_at:string}
export const schoolDay=(value:string|Date)=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jerusalem',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value))
const purposes:Record<string,string>={recording:'הקלטה',transcription:'תמלול',sharing:'שיתוף',browser:'זיהוי דיבור בדפדפן',ai:'עיבוד AI'}
export function DailyWork(){
 const [now,setNow]=useState(()=>new Date()),[tab,setTab]=useState<'today'|'late'|'consents'>('today')
 useEffect(()=>{const timer=setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(timer)},[])
 const students=useQuery({queryKey:['students'],queryFn:async()=>(await dataClient.get<Student[]>('/students')).data})
 const tasks=useQuery({queryKey:['tasks'],queryFn:async()=>(await dataClient.get<Entry[]>('/tasks')).data,refetchInterval:60000})
 const appointments=useQuery({queryKey:['appointments'],queryFn:async()=>(await dataClient.get<Entry[]>('/appointments')).data,refetchInterval:60000})
 const consents=useQuery({queryKey:['consent-reminders'],queryFn:async()=>(await dataClient.get<Consent[]>('/consent-reminders')).data,refetchInterval:60000})
 const active=new Map(students.data?.filter(s=>!s.archived).map(s=>[s.id,s]))
 const pending=(tasks.data||[]).filter(t=>t.status==='open'&&active.has(t.student_id)).sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!))
 const late=pending.filter(t=>Date.parse(t.due_at!)<now.getTime()),today=pending.filter(t=>schoolDay(t.due_at!)===schoolDay(now))
 const meetings=(appointments.data||[]).filter(a=>a.status==='planned'&&active.has(a.student_id)&&schoolDay(a.starts_at!)===schoolDay(now)).sort((a,b)=>Date.parse(a.starts_at!)-Date.parse(b.starts_at!))
 const error=students.error||tasks.error||appointments.error||consents.error,loading=students.isPending||tasks.isPending||appointments.isPending||consents.isPending
 const entries=tab==='today'?today:late
 return <><header><span className="eyebrow">המרחב שלי • לפי שעון ישראל</span><h1>היום שלי ותזכורות</h1><p>{now.toLocaleDateString('he-IL',{timeZone:'Asia/Jerusalem',dateStyle:'full'})} • מתעדכן בכל דקה</p></header>{error&&<p className="error" role="alert">{errorMessage(error)}</p>}{loading?<p>טוענת את סדר היום…</p>:error?null:<><div className="tasks-summary"><button className={tab==='today'?'':'secondary'} onClick={()=>setTab('today')}>משימות היום ({today.length})</button><button className={tab==='late'?'':'secondary'} onClick={()=>setTab('late')}>באיחור ({late.length})</button><button className={tab==='consents'?'':'secondary'} onClick={()=>setTab('consents')}>הסכמות לפקיעה ({consents.data?.length||0})</button></div><div className="dashboard-columns"><section className="card"><h2>פגישות היום ({meetings.length})</h2>{!meetings.length&&<p>אין פגישות מתוכננות להיום.</p>}{meetings.map(a=><Link className="list-item" key={a.id} to={'/students/'+a.student_id}><strong>{active.get(a.student_id)?.name}</strong><span>{new Date(a.starts_at!).toLocaleTimeString('he-IL',{timeZone:'Asia/Jerusalem',hour:'2-digit',minute:'2-digit'})}</span></Link>)}<Link to="/calendar">ליומן הפגישות ←</Link></section><section className="card"><h2>{tab==='consents'?'הסכמות שיפוגו ב־14 הימים הקרובים':tab==='late'?'משימות באיחור':'משימות להיום'}</h2>{tab==='consents'?<>{!consents.data?.length&&<p>אין הסכמות שעומדות לפוג.</p>}{consents.data?.map(c=><Link className="list-item" key={c.id} to={'/students/'+c.student_id}><div><strong>{active.get(c.student_id)?.name}</strong><small>{purposes[c.purpose]||c.purpose} • בתוקף עד {new Date(c.expires_at).toLocaleString('he-IL',{timeZone:'Asia/Jerusalem'})}</small></div></Link>)}</>:<>{!entries.length&&<p>אין משימות בטווח שנבחר.</p>}{entries.map(t=><Link className="list-item" key={t.id} to={'/students/'+t.student_id}><div><strong>{t.title}</strong><small>{active.get(t.student_id)?.name} • {new Date(t.due_at!).toLocaleString('he-IL',{timeZone:'Asia/Jerusalem'})}</small></div>{Date.parse(t.due_at!)<now.getTime()&&<span className="badge overdue">באיחור</span>}</Link>)}<Link to="/tasks">לניהול המשימות ←</Link></>}</section></div><p className="muted">התזכורות מוצגות במערכת. רשימת ההסכמות כוללת רק כרטיסים שבבעלותך.</p></>}</>
}
