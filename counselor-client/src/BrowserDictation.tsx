import { useEffect, useRef, useState } from 'react'
import { dataClient, errorMessage } from './api/http'
interface Result { isFinal:boolean; [index:number]:{transcript:string} }
interface ResultEvent {resultIndex:number;results:{length:number;[index:number]:Result}}
interface Recognition {
 lang:string;continuous:boolean;interimResults:boolean
 start:()=>void;stop:()=>void;abort:()=>void
 onresult:((e:ResultEvent)=>void)|null
 onerror:((e:{error:string})=>void)|null
 onend:(()=>void)|null
}
type Constructor=new()=>Recognition
function constructor():Constructor|undefined {
 const w=window as unknown as {SpeechRecognition?:Constructor;webkitSpeechRecognition?:Constructor}
 return w.SpeechRecognition||w.webkitSpeechRecognition
}
const errors:Record<string,string>={
 'not-allowed':'הגישה למיקרופון נדחתה. בדקי הרשאות דפדפן.',
 'service-not-allowed':'שירות ההכתבה חסום בדפדפן או ברשת.',
 'network':'שירות ההכתבה של הדפדפן אינו זמין. בדקי את החיבור והרשת.',
 'no-speech':'לא זוהה דיבור. אפשר לנסות שוב.',
 'audio-capture':'לא ניתן לגשת למיקרופון.',
 'language-not-supported':'זיהוי דיבור בעברית אינו נתמך בדפדפן זה.',
}
/** Same browser-native mechanism as chatapp-next; no app-side STT or summary API. */
export function BrowserDictation({sid,disabled,onTranscript,onBusy}:{sid:string;disabled:boolean;onTranscript:(text:string)=>void;onBusy:(busy:boolean)=>void}) {
 const [supported,setSupported]=useState(false),[consent,setConsent]=useState(false),[phase,setPhase]=useState('idle'),[error,setError]=useState<unknown>(null)
 const instance=useRef<Recognition|null>(null),alive=useRef(true),pending=useRef(false),timer=useRef<ReturnType<typeof setTimeout>|null>(null),callback=useRef(onTranscript)
 callback.current=onTranscript
 const busy=phase!=='idle'
 useEffect(()=>{onBusy(busy)},[busy,onBusy])
 useEffect(()=>{alive.current=true;setSupported(Boolean(constructor()));return()=>{alive.current=false;if(timer.current)clearTimeout(timer.current);if(instance.current){instance.current.onresult=null;instance.current.onerror=null;instance.current.onend=null;instance.current.abort()}}},[sid])
 useEffect(()=>{if(!busy)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};const guard=(e:MouseEvent)=>{if((e.target as Element).closest?.('a[href]')&&!window.confirm('המעבר יפסיק את ההכתבה. להמשיך?')){e.preventDefault();e.stopPropagation()}};window.addEventListener('beforeunload',warn);document.addEventListener('click',guard,true);return()=>{window.removeEventListener('beforeunload',warn);document.removeEventListener('click',guard,true)}},[busy])
 function stop(){setPhase('stopping');instance.current?.stop()}
 async function start(){
  if(pending.current||busy||disabled||!consent)return
  const Ctor=constructor();if(!Ctor)return
  pending.current=true;setError(null);setPhase('starting')
  try {
   const {data}=await dataClient.post(`/students/${sid}/browser-dictation-authorize`)
   const remaining=data.valid_until?new Date(data.valid_until).getTime()-Date.now():600000
   if(!Number.isFinite(remaining)||remaining<=0)throw Error('ההסכמה פגה. תעדי הסכמה חדשה')
   if(!alive.current)return
   const recognition=new Ctor();instance.current=recognition
   recognition.lang='he-IL';recognition.continuous=true;recognition.interimResults=false
   const seen=new Set<number>()
   recognition.onresult=e=>{
    if(!alive.current)return
    try{for(let i=e.resultIndex??0;i<e.results.length;i++){if(!e.results[i].isFinal||seen.has(i))continue;seen.add(i);const text=e.results[i][0].transcript.trim();if(text)callback.current(text)}}catch(err){setError(err);recognition.stop()}
   }
   recognition.onerror=e=>{if(alive.current&&e.error!=='aborted')setError(Error(errors[e.error]||'ההכתבה נכשלה. אפשר להמשיך לכתוב ידנית.'))}
   recognition.onend=()=>{if(timer.current)clearTimeout(timer.current);instance.current=null;if(alive.current)setPhase('idle')}
   recognition.start();setPhase('listening');timer.current=setTimeout(()=>recognition.stop(),Math.min(600000,remaining))
  }catch(e){instance.current=null;if(alive.current){setError(e);setPhase('idle')}}finally{pending.current=false}
 }
 return <section className="recorder-panel"><span className="eyebrow">כמו ב־Chat App Next</span><h3>הכתבה בעברית בדפדפן</h3><p>ללא מפתח API, ללא התקנת Whisper וללא יצירת סיכום. הדפדפן עשוי להעביר שמע לשירות הזיהוי שלו — זו אינה הבטחה לעיבוד מקומי. התוצאה מתווספת לתיעוד ולשמירת הטיוטה המוצפנת.</p>{!supported?<p role="status">ההכתבה אינה נתמכת בדפדפן זה. ניתן להמשיך להקליט ולתמלל ידנית.</p>:<><label><input type="checkbox" checked={consent} disabled={busy||disabled} onChange={e=>setConsent(e.target.checked)}/> קיימת הסכמה תקפה להקלטה, לתמלול ולזיהוי דיבור בדפדפן, כולל אפשרות לעיבוד חיצוני</label><div className="row">{busy?<><span role="status">{phase==='starting'?'בודקת הסכמות…':phase==='stopping'?'מסיימת הכתבה…':'מקשיבה בעברית…'}</span><button type="button" onClick={stop} disabled={phase!=='listening'}>עצירת הכתבה</button></>:<button type="button" onClick={()=>void start()} disabled={!consent||disabled}>התחלת הכתבה בדפדפן</button>}</div></>}{Boolean(error)&&<p className="error" role="alert">{errorMessage(error)}</p>}</section>
}
