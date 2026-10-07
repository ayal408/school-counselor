import { useId, useState } from 'react'
import HebrewDatePicker from 'react-hebrew-datepicker'

/** The package returns Gregorian YYYY-MM-DD, while displaying the Hebrew calendar. */
export function HebrewDateField({name,label,value,onChange}:{name:string;label:string;value:string;onChange:(value:string)=>void}) {
 const id=useId()
 return <div className="hebrew-date-field"><label htmlFor={id}>{label}</label><HebrewDatePicker id={id} name={name} value={value} onChange={e=>onChange(e.target.value)} label={null} showGregorian allowClear={false} dir="rtl" usePortal className="counselor-datepicker" popupClassName="counselor-calendar"/></div>
}

export function HebrewDateTimeField({name,label}:{name:string;label:string}) {
 const [date,setDate]=useState(''),[time,setTime]=useState('')
 const id=useId()
 return <fieldset className="hebrew-datetime"><legend>{label}</legend><div className="date-time-grid"><HebrewDateField name={`${name}_date`} label="תאריך עברי / לועזי" value={date} onChange={setDate}/><div><label htmlFor={id}>שעה</label><input id={id} type="time" value={time} onChange={e=>setTime(e.target.value)} required/></div></div><input type="hidden" name={name} value={date&&time?`${date}T${time}`:''}/></fieldset>
}
