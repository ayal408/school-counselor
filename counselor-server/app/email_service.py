"""DOMix style Gmail sender, branded Hebrew messages and encrypted outbox."""
import os, re, json, base64, hashlib
from datetime import datetime, timezone, timedelta
from html import escape
from email.message import EmailMessage
from email.utils import formataddr
from email.policy import SMTP
import httpx
from sqlalchemy import select
from .models import EmailSettings, EmailOutbox
from .security import encrypt, decrypt
from .ai import tls_context
class MailFailure(Exception):
    def __init__(self,code,uncertain=False,retry=False):self.code=code;self.uncertain=uncertain;self.retry=retry

def environment(name):
    aliases={'GMAIL_CLIENT_ID':'GMAIL__CLIENTID','GMAIL_CLIENT_SECRET':'GMAIL__CLIENTSECRET','GMAIL_REFRESH_TOKEN':'GMAIL__REFRESHTOKEN','GMAIL_EMAIL':'GMAIL__EMAIL'}
    return os.environ.get(name,os.environ.get(aliases.get(name,''),''))
def origin():
    value=os.environ.get('CLIENT_ORIGIN','http://localhost:8088').rstrip('/')
    from urllib.parse import urlparse
    parsed=urlparse(value)
    if parsed.scheme not in ['https','http'] or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ['', '/']:raise ValueError('Invalid CLIENT_ORIGIN')
    return value
def redirect_uri():return os.environ.get('GMAIL_REDIRECT_URI','') or origin()+'/api/email/gmail/callback'
def oauth_available():return bool(environment('GMAIL_CLIENT_ID') and environment('GMAIL_CLIENT_SECRET'))
def mailbox(value):
    return isinstance(value,str) and len(value)<=254 and bool(re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}',value))
def settings(db):
    row=db.get(EmailSettings,1)
    if row:return row
    return EmailSettings(id=1,generation=0,sender_email=environment('GMAIL_EMAIL'),sender_name='מרחב',reply_to='',signature='',enabled=bool(environment('GMAIL_REFRESH_TOKEN')),updated_at=datetime.now(timezone.utc))
def connected(db):
    row=settings(db)
    return bool(row.enabled and mailbox(row.sender_email) and oauth_available() and (row.refresh_token or environment('GMAIL_REFRESH_TOKEN')))
def configuration_json(db):
    row=settings(db)
    return {'sender_email':row.sender_email,'sender_name':row.sender_name,'reply_to':row.reply_to,'signature':row.signature,'enabled':row.enabled,'connected':connected(db),'oauth_available':oauth_available(),'redirect_uri':redirect_uri(),'updated_at':row.updated_at}
def enqueue(db,recipient,kind,title,text,link=None,user_id=None):
    if not mailbox(recipient):return None
    payload={'title':title,'text':text,'link':link}
    row=EmailOutbox(recipient=recipient,user_id=user_id,kind=kind,payload=encrypt(json.dumps(payload,ensure_ascii=False)))
    db.add(row);return row

def render(payload,signature=''):
    title=escape(payload['title']);text=escape(payload['text']).replace('\n','<br>')
    link=payload.get('link');button=''
    if link:
        if link!=origin() and not link.startswith(origin()+'/'):raise ValueError('Untrusted email action')
        button=f'<p style="margin:28px 0"><a href="{escape(link,quote=True)}" style="display:inline-block;background:#256553;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none">פתיחה במרחב</a></p>'
    sig=('<hr style="border:0;border-top:1px solid #dbe6df"><p>'+escape(signature).replace('\n','<br>')+'</p>') if signature else ''
    return f'''<!doctype html><html lang="he" dir="rtl"><body style="margin:0;background:#f2f5ef;font-family:Arial,sans-serif;color:#24392e"><table role="presentation" width="100%" dir="rtl"><tr><td align="center" style="padding:30px 12px"><table role="presentation" width="560" style="width:100%;max-width:560px;background:white;border-radius:18px"><tr><td style="background:#256553;color:white;padding:24px;font-size:26px;border-radius:18px 18px 0 0">◈ מרחב <span style="font-size:13px">ייעוץ בית ספרי</span></td></tr><tr><td style="padding:28px;text-align:right"><h1 style="font-size:23px">{title}</h1><p style="line-height:1.8">{text}</p>{button}{sig}<p style="font-size:12px;color:#647367;line-height:1.7">הודעת מערכת ממרחב. מידע מקצועי על תלמידות מופיע רק במערכת לאחר כניסה מורשית.</p></td></tr></table></td></tr></table></body></html>'''

def message(recipient,row,payload):
    if not mailbox(recipient) or not mailbox(row.sender_email) or (row.reply_to and not mailbox(row.reply_to)):raise MailFailure('INVALID_ADDRESS')
    title=payload['title']
    if not title.strip() or any(ord(c)<32 for c in title) or any(ord(c)<32 for c in row.sender_name):raise MailFailure('INVALID_HEADER')
    email=EmailMessage(policy=SMTP)
    email['To']=recipient;email['From']=formataddr((row.sender_name,row.sender_email));email['Subject']=title
    if row.reply_to:email['Reply-To']=row.reply_to
    email.set_content(payload['text']+('\n'+payload['link'] if payload.get('link') else '')+'\n'+row.signature)
    email.add_alternative(render(payload,row.signature),subtype='html')
    return base64.urlsafe_b64encode(email.as_bytes()).decode().rstrip('=')

async def send(db,recipient,payload):
    row=settings(db)
    if not connected(db):raise MailFailure('EMAIL_NOT_CONNECTED',retry=True)
    refresh=decrypt(row.refresh_token) if row.refresh_token else environment('GMAIL_REFRESH_TOKEN')
    try:
        async with httpx.AsyncClient(timeout=20,verify=tls_context()) as client:
            result=await client.post('https://oauth2.googleapis.com/token',data={'client_id':environment('GMAIL_CLIENT_ID'),'client_secret':environment('GMAIL_CLIENT_SECRET'),'refresh_token':refresh,'grant_type':'refresh_token'})
            if result.status_code!=200:raise MailFailure('TOKEN_REFRESH_FAILED',retry=result.status_code==429 or result.status_code>=500)
            access=result.json().get('access_token')
            if not isinstance(access,str) or not access:raise MailFailure('TOKEN_REFRESH_FAILED')
            raw=message(recipient,row,payload)
            try:
                result=await client.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',headers={'Authorization':'Bearer '+access},json={'raw':raw})
            except httpx.HTTPError:raise MailFailure('DELIVERY_UNKNOWN',uncertain=True)
            if result.status_code==429:raise MailFailure('RATE_LIMITED',retry=True)
            if result.status_code>=500:raise MailFailure('DELIVERY_UNKNOWN',uncertain=True)
            if result.status_code not in [200,201]:raise MailFailure('EMAIL_SEND_FAILED')
    except (httpx.HTTPError,ValueError,OSError,TypeError):raise MailFailure('CONNECTION_FAILED',retry=True)

async def process_one(factory):
    # Claim durably before the external request. A crash after claiming is not auto-retried.
    with factory() as db:
        row=db.scalar(select(EmailOutbox).where(EmailOutbox.status=='pending',EmailOutbox.next_attempt<=datetime.now(timezone.utc)).order_by(EmailOutbox.created_at).with_for_update(skip_locked=True).limit(1))
        if not row:return False
        if not connected(db):return False
        row.status='sending';row.attempts+=1;row.next_attempt=datetime.now(timezone.utc);uid=row.id;db.commit()
    with factory() as db:
        row=db.get(EmailOutbox,uid)
        try:
            await send(db,row.recipient,json.loads(decrypt(row.payload)))
            row.status='sent';row.sent_at=datetime.now(timezone.utc);row.failure_code=None;row.payload=None
        except MailFailure as exc:
            row.failure_code=exc.code
            row.status='uncertain' if exc.uncertain else 'pending' if exc.retry and row.attempts<3 else 'failed'
            row.next_attempt=datetime.now(timezone.utc)+timedelta(minutes=5*row.attempts)
            if row.status!='pending':row.payload=None
        except Exception:
            row.status='uncertain';row.failure_code='DELIVERY_UNKNOWN';row.payload=None
        db.commit()
    return True
