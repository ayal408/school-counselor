from datetime import timedelta
from test_api import setup,token
from test_casework import student
from app.models import CaseConsent,Student,now
from app.security import encrypt

def test_reminders_are_owner_only_current_and_active(setup):
 c,f=setup;sid=student(c);other=student(c,'two')
 with f() as db:
  for identifier,student_id,days,revoked in [('soon',sid,3,False),('foreign',other,2,False),('expired',sid,-1,False),('later',sid,20,False),('revoked',sid,2,True)]:
   db.add(CaseConsent(id=identifier,student_id=student_id,actor_id='one',purpose='recording',granted_at=now()-timedelta(days=10),expires_at=now()+timedelta(days=days),revoked=revoked,evidence=encrypt('פרט רגיש')))
  db.commit()
 r=c.get('/api/consent-reminders',headers=token('one'))
 assert r.status_code==200 and r.headers['cache-control']=='no-store'
 assert [x['id'] for x in r.json()]==['soon']
 assert 'evidence' not in r.json()[0]
 with f() as db:db.get(Student,sid).archived=True;db.commit()
 assert c.get('/api/consent-reminders',headers=token('one')).json()==[]
 assert c.get('/api/consent-reminders').status_code==401
