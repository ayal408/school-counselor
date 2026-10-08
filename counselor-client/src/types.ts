export type Student = { id: string; name: string; classroom: string; referral: string; archived: boolean; can_edit?: boolean; school_year:string }
export type Meeting = { id: string; student_id: string; starts_at: string; notes: string; summary: string; ai_assisted?: boolean; ai_reviewed?: boolean; version:number; topic?:string; subjects?:string; decisions?:string[]; next_steps?:string }
export type User = { id: string; name: string; email: string; role?: string }
