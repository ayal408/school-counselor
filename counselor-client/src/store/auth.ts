import { create } from 'zustand'
import type { User } from '../types'
export const useAuth = create<{token: string | null; user: User | null; set: (token: string, user: User)=>void; clear: ()=>void}>(set=>({token:null,user:null,set:(token,user)=>set({token,user}),clear:()=>set({token:null,user:null})}))
