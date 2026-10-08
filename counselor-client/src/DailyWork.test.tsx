import { expect,it } from 'vitest'
import { schoolDay } from './DailyWork'
it('uses the school day in Israel across UTC midnight and winter/summer offsets',()=>{
 expect(schoolDay('2026-10-08T22:30:00Z')).toBe('2026-10-09')
 expect(schoolDay('2026-01-08T21:30:00Z')).toBe('2026-01-08')
 expect(schoolDay('2026-01-08T22:30:00Z')).toBe('2026-01-09')
})
