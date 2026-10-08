import { useId, useState } from 'react'
import HebrewDatePicker from 'react-hebrew-datepicker'

/** The package returns Gregorian YYYY-MM-DD, while displaying the Hebrew calendar. */
export function HebrewDateField({name,label,value,onChange}:{name:string;label:string;value:string;onChange:(value:string)=>void}) {
 const id=useId()
 return <div className="hebrew-date-field"><label htmlFor={id}>{label}</label><HebrewDatePicker id={id} name={name} value={value} onChange={e=>onChange(e.target.value)} label={null} showGregorian allowClear={false} dir="rtl" usePortal className="counselor-datepicker" popupClassName="counselor-calendar"/></div>
}

export function HebrewDateTimeField({name,label,value,onChange,required=true}:{name:string;label:string;value?:string;onChange?:(value:string)=>void;required?:boolean}) {
 const local=value?new Date(value):null
 const pad=(v:number)=>String(v).padStart(2,'0')
 const [date,setDate]=useState(local&&Number.isFinite(local.getTime())?`${local.getFullYear()}-${pad(local.getMonth()+1)}-${pad(local.getDate())}`:''),[time,setTime]=useState(local&&Number.isFinite(local.getTime())?`${pad(local.getHours())}:${pad(local.getMinutes())}`:'')
 const id=useId()
 return <fieldset className="hebrew-datetime"><legend>{label}</legend><div className="date-time-grid"><HebrewDateField name={`${name}_date`} label="תאריך עברי / לועזי" value={date} onChange={v=>{setDate(v);onChange?.(v&&time?`${v}T${time}`:'')}}/><div><label htmlFor={id}>שעה</label><input id={id} type="time" value={time} onChange={e=>{setTime(e.target.value);onChange?.(date&&e.target.value?`${date}T${e.target.value}`:'')}} required={required}/></div></div><input type="hidden" name={name} value={date&&time?`${date}T${time}`:''}/></fieldset>
}
