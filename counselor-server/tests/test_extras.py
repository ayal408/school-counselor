from datetime import datetime,timezone
from sqlalchemy import select
from test_api import setup,token,grant
from test_casework import student,document
from app.models import Task,Audit
from app.security import decrypt

def test_task_edit_owner_encryption_conflict_and_archive(setup):
 c,f=setup;h=token('one');sid=student(c)
 t=c.post('/api/tasks',headers=h,json={'student_id':sid,'title':'משימה מקורית','due_at':'2026-10-08T09:00:00Z'}).json()
 edit={'title':'עדכון רגיש','due_at':'2026-10-10T09:00:00Z','status':'open','expected':{k:t[k] for k in ['title','due_at','status']}}
 assert c.put('/api/tasks/'+t['id'],headers=token('two'),json=edit).status_code==404
 grant(c,sid,'sharing','two');c.post(f'/api/students/{sid}/shares',headers=h,json={'user_id':'two','password':'long-test-password'})
 assert c.put('/api/tasks/'+t['id'],headers=token('two'),json=edit).status_code==404
 result=c.put('/api/tasks/'+t['id'],headers=h,json=edit);assert result.status_code==200,result.text
 assert c.put('/api/tasks/'+t['id'],headers=h,json=edit).status_code==409
 with f() as db:assert 'רגיש' not in db.get(Task,t['id']).title and decrypt(db.get(Task,t['id']).title)=='עדכון רגיש'
 changed=result.json();edit['expected']={k:changed[k] for k in ['title','due_at','status']}
 c.patch('/api/tasks/'+t['id'],headers=h,json={'status':'done'})
 assert c.put('/api/tasks/'+t['id'],headers=h,json=edit).status_code==409
 c.post(f'/api/students/{sid}/archive',headers=h)
 assert c.put('/api/tasks/'+t['id'],headers=h,json=edit).status_code==409

def test_restore_preserves_history_and_does_not_reactivate_cancelled_appointments(setup):
 c,_=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}'
 c.post(url+'/meetings',headers=h,json=document())
 a=c.post('/api/appointments',headers=h,json={'student_id':sid,'starts_at':'2027-09-01T09:00:00Z','ends_at':'2027-09-01T10:00:00Z'}).json()
 c.patch('/api/appointments/'+a['id'],headers=h,json={'status':'cancelled'})
 c.post(url+'/archive',headers=h)
 assert c.post(url+'/restore',headers=token('two')).status_code==404
 assert c.post(url+'/restore',headers=h).json()['archived'] is False
 assert len(c.get(url+'/meetings',headers=h).json())==1
 assert c.get('/api/appointments',headers=h).json()[0]['status']=='cancelled'
 assert c.post(url+'/restore',headers=h).status_code==409

def test_student_edit_stale_snapshot_is_not_overwritten(setup):
 c,_=setup;sid=student(c);h=token('one');base={'name':'תלמידת בדיקה','classroom':'ח1','referral':''}
 b={**base,'name':'שם מעודכן','expected':base}
 assert c.put(f'/api/students/{sid}',headers=h,json=b).status_code==200
 assert c.put(f'/api/students/{sid}',headers=h,json={**b,'name':'דריסה'}).status_code==409
 assert c.get('/api/students',headers=h).json()[0]['name']=='שם מעודכן'

def test_print_requires_current_visibility_and_logs_selected_meeting(setup):
 c,f=setup;sid=student(c);h=token('one');url=f'/api/students/{sid}'
 m=c.post(url+'/meetings',headers=h,json=document()).json();print_url=url+'/meetings/'+m['id']+'/print'
 assert c.get(print_url,headers=token('two')).status_code==404
 grant(c,sid,'sharing','two');c.post(url+'/shares',headers=h,json={'user_id':'two','password':'long-test-password'})
 response=c.get(print_url,headers=token('two'));assert response.status_code==200 and response.json()['meeting']['notes']=='תיעוד רגיש'
 assert response.headers['cache-control']=='no-store'
 c.post(url+'/shares/two/revoke',headers=h,json={'password':'long-test-password'})
 assert c.get(print_url,headers=token('two')).status_code==404
 other=student(c,'two');assert c.get(f'/api/students/{other}/meetings/{m["id"]}/print',headers=token('two')).status_code==404
 with f() as db:assert db.scalar(select(Audit).where(Audit.action=='meeting.print',Audit.user_id=='two')).record_id==m['id']
