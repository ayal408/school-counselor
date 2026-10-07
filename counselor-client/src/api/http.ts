import axios from 'axios'
import { useAuth } from '../store/auth'
export const authClient = axios.create({baseURL:'/api/auth',withCredentials:true,timeout:15000,headers:{'X-Requested-With':'XMLHttpRequest'}})
export const dataClient = axios.create({baseURL:'/api',timeout:20000})
let pending: Promise<boolean> | null = null
export function restore(): Promise<boolean> {
 if (!pending) pending = authClient.post('/refresh').then(({data})=>{useAuth.getState().set(data.accessToken,data.user);return true}).catch(()=>{useAuth.getState().clear();return false}).finally(()=>{pending=null})
 return pending
}
dataClient.interceptors.request.use(config=>{const token=useAuth.getState().token;if(token) config.headers.Authorization=`Bearer ${token}`;return config})
dataClient.interceptors.response.use(r=>r,async error=>{
 const config=error.config
 if(error.response?.status===401 && config && !config._retry){config._retry=true;if(await restore())return dataClient(config)}
 return Promise.reject(error)
})
export function errorMessage(error: unknown): string {
 if(axios.isAxiosError(error)) {
  if(error.response?.status===429)return 'בוצעו יותר מדי ניסיונות. נסי שוב בעוד דקה.'
  const detail=error.response?.data?.detail
  return typeof detail==='string'?detail:'לא ניתן להשלים את הפעולה. בדקי את החיבור ונסי שוב.'
 }
 if(error instanceof Error)return error.message
 return 'אירעה שגיאה. נסי שוב.'
}
