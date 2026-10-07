export type Student = { id: string; name: string; classroom: string; referral: string; archived: boolean }
export type Meeting = { id: string; student_id: string; starts_at: string; notes: string; summary: string; ai_assisted?: boolean; ai_reviewed?: boolean }
export type User = { id: string; name: string; email: string }
