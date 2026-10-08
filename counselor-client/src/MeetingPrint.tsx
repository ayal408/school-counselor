import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dataClient, errorMessage } from './api/http'
import { topics } from './CaseMeetings'
import type { Meeting } from './types'
export function MeetingPrint(){
 const {id,mid}=useParams(),[names,setNames]=useState(false)
 const q=useQuery({queryKey:['meeting-print',id,mid],queryFn:async()=>(await dataClient.get<{student:{name:string;classroom:string;school_year:string};meeting:Meeting}>(`/students/${id}/meetings/${mid}/print`)).data})
 const m=q.error?undefined:q.data?.meeting,s=q.error?undefined:q.data?.student
 return <><div className="no-print"><Link to={'/students/'+id}>← חזרה לכרטיס התלמידה</Link><header><h1>תיעוד פגישה להדפסה</h1><p>אפשר להדפיס או לבחור ״שמירה כ־PDF״ בחלון ההדפסה של הדפדפן.</p></header><div className="card row"><label><input type="checkbox" checked={names} onChange={e=>setNames(e.target.checked)}/> לכלול שם תלמידה וכיתה</label><button disabled={!m} onClick={()=>window.print()}>הדפסה / שמירה כ־PDF</button></div>{q.isPending&&<p>טוענת תיעוד…</p>}{q.error&&<p role="alert" className="error">{errorMessage(q.error)}</p>}</div>{m&&s&&<article className="card print-view"><header><span className="eyebrow">◈ מרחב • ייעוץ בית ספרי</span><h1>תיעוד פגישה</h1>{names&&<p>{s.name} • כיתה {s.classroom}</p>}<p>{new Date(m.starts_at).toLocaleString('he-IL')} • שנת לימודים {s.school_year} • גרסה {m.version}</p><p>נושא: {topics[m.topic as keyof typeof topics]||'אחר'}</p></header>{m.subjects&&<section><h2>נושאים שעלו</h2><p className="pre">{m.subjects}</p></section>}<section><h2>תיעוד והערות</h2><p className="pre">{m.notes||'ללא הערות'}</p></section><section><h2>סיכום</h2><p className="pre">{m.summary||'ללא סיכום'}</p></section>{Boolean(m.decisions?.length)&&<section><h2>החלטות</h2><ol>{m.decisions?.map((d,i)=><li key={i}>{d}</li>)}</ol></section>}{m.next_steps&&<section><h2>צעדי המשך</h2><p className="pre">{m.next_steps}</p></section>}{m.ai_assisted&&<p className="muted">התיעוד נעזר בזיהוי דיבור / AI ונבדק ואושר.</p>}<footer>מסמך פנימי • הופק {new Date().toLocaleDateString('he-IL')}</footer></article>}</>
}
