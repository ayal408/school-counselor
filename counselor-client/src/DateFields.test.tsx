import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { HebrewDateTimeField } from './DateFields'
vi.mock('react-hebrew-datepicker',()=>({default:()=>null}))
afterEach(cleanup)
it('allows searching without a date range while meeting dates remain required',()=>{
 const first=render(<HebrewDateTimeField name="after" label="מתאריך" required={false}/>);
 expect((first.container.querySelector('input[type=time]') as HTMLInputElement).required).toBe(false)
 first.unmount();const second=render(<HebrewDateTimeField name="starts_at" label="מועד"/>);
 expect((second.container.querySelector('input[type=time]') as HTMLInputElement).required).toBe(true)
})
