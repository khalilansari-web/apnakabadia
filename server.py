"""APNA KABADI request handlers. Local preview plus a hosted public-test adapter."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qs
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.cookies import SimpleCookie
import argparse, os, json, sqlite3, secrets, re, hashlib, mimetypes, time, threading, csv, io, math

ROOT=Path(__file__).parent.resolve(); PUBLIC=ROOT/'public'
LOCAL=Path(os.environ.get('APNA_DATA_DIR',ROOT/'.local')).resolve(); LOCAL.mkdir(parents=True,exist_ok=True)
os.chmod(LOCAL,0o700)
DB=LOCAL/'apna.sqlite3'; TZ=ZoneInfo('Asia/Kolkata')
PUBLIC_TEST=os.environ.get('APNA_MODE')=='public-test'
PUBLIC_HOSTS={x.strip().lower() for x in os.environ.get('APNA_ALLOWED_HOSTS','').split(',') if x.strip()}
if os.environ.get('RAILWAY_PUBLIC_DOMAIN'):PUBLIC_HOSTS.add(os.environ['RAILWAY_PUBLIC_DOMAIN'].lower())
PUBLIC_URL=os.environ.get('APNA_PUBLIC_URL','').rstrip('/')
if PUBLIC_URL:
    parsed=urlsplit(PUBLIC_URL)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:raise RuntimeError('APNA_PUBLIC_URL must be a complete HTTPS origin.')
    PUBLIC_HOSTS.add(parsed.netloc.lower())
if PUBLIC_TEST and not os.environ.get('APNA_ADMIN_KEY'):raise RuntimeError('Configure APNA_ADMIN_KEY before starting a public test.')
CSRF=secrets.token_urlsafe(30); SESSIONS={}; LIMITS={}; LOCK=threading.Lock()
KEY_FILE=LOCAL/'desk-key.txt'
if not KEY_FILE.exists(): KEY_FILE.write_text(secrets.token_urlsafe(18)+'\n'); os.chmod(KEY_FILE,0o600)
ADMIN_KEY=os.environ.get('APNA_ADMIN_KEY') or KEY_FILE.read_text().strip()
STATUSES=['Requested','Confirmed','On the way','Arrived','Completed','Cancelled','Waitlisted']
TRANSITIONS={'Requested':['Confirmed','Waitlisted','Cancelled'],'Waitlisted':['Confirmed','Cancelled'],'Confirmed':['On the way','Waitlisted','Cancelled'],'On the way':['Arrived','Cancelled'],'Arrived':['Completed'],'Completed':[],'Cancelled':[]}
CATALOGUE=json.loads((PUBLIC/'catalogue.json').read_text())
MATERIALS=CATALOGUE['materials']
SERVICES=json.loads((PUBLIC/'services.json').read_text())
LOCALITIES=json.loads((PUBLIC/'localities.json').read_text())
ARTICLES=json.loads((PUBLIC/'articles.json').read_text())
DEFAULT={'articles':ARTICLES,'pressFeatures':[],'instagramUrl':'','facebookUrl':'','businessNumber':'','email':'','domain':'','legalName':'','address':'','serviceLocalities':[],'serviceHours':'Pickup windows are confirmed by the dispatcher.','capacityPerDay':4,'materials':MATERIALS,'ratesUpdatedAt':CATALOGUE['reviewedAt'],'rateRevision':CATALOGUE['rateRevision'],'catalogueVersion':CATALOGUE['version'],'rateSource':CATALOGUE['source']}
ROUTES=['/','/news','/materials','/how-it-works','/rates','/baripada','/book','/track','/about','/contact','/faq','/privacy','/terms','/desk','/credits','/services']+[('/services/'+s['id']) for s in SERVICES]

def now():return datetime.now(TZ).isoformat(timespec='seconds')
def connect():
    c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=10000');return c
with connect() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL, digest TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, booking TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL);''')
    c.execute('INSERT OR IGNORE INTO settings VALUES (1,?)',(json.dumps(DEFAULT),))
    saved=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
    if saved.get('catalogueVersion',1)<CATALOGUE['version'] or saved.get('rateRevision')!=CATALOGUE['rateRevision']:
        previous={m['id']:m for m in saved.get('materials',[])}
        import_rates=saved.get('rateRevision')!=CATALOGUE['rateRevision']
        saved['materials']=[{**m,'rate':m['rate'] if import_rates else previous.get(m['id'],{}).get('rate',m['rate'])} for m in MATERIALS]
        saved['catalogueVersion']=CATALOGUE['version'];saved['rateSource']=CATALOGUE['source'];saved['rateRevision']=CATALOGUE['rateRevision']
        if import_rates:saved['ratesUpdatedAt']=CATALOGUE['reviewedAt']
        c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(saved),))

def settings():
    with connect() as c:return {**DEFAULT,**json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])}
def phone(value):return re.sub(r'\D','',str(value)).removeprefix('91') if len(re.sub(r'\D','',str(value)))==12 else re.sub(r'\D','',str(value))
def text(value,maxlen=200):return str(value or '').strip()[:maxlen]
class Problem(Exception):
    def __init__(self,status,message,fields=None):self.status=status;self.message=message;self.fields=fields
def validate_booking(b,config):
    errors={};p={k:text(b.get(k),lim) for k,lim in [('name',80),('phone',30),('locality',100),('address',400),('landmark',120),('pincode',6),('city',80),('date',10),('slot',30),('notes',500),('weight',20)]}
    p['phone']=phone(p['phone'])
    if len(p['name'])<2:errors['name']='Enter your full name.'
    if not re.fullmatch(r'[6-9]\d{9}',p['phone']):errors['phone']='Enter a valid 10-digit Indian mobile number.'
    if p['city'].casefold()!='baripada':errors['city']='This pilot is for Baripada only.'
    if len(p['locality'])<2 or p['locality']=='__other':errors['locality']='Enter your locality in Baripada.'
    ward=text(b.get('ward'),20)
    if ward:
        match=next((w for w in LOCALITIES['wards'] if str(w['ward'])==ward),None)
        if not match or p['locality']!=match['name']:errors['ward']='Choose the matching ward and locality, or select Other / not sure.'
        else:p['ward']=int(ward)
    if 'quoteRequested' in b and not isinstance(b['quoteRequested'],bool):errors['quoteRequested']='Check the quote request option.'
    if b.get('quoteRequested') is True:p['quoteRequested']=True
    if len(p['address'])<8:errors['address']='Enter a complete pickup address.'
    if p['pincode'] and not re.fullmatch(r'[1-9]\d{5}',p['pincode']):errors['pincode']='Enter a valid 6-digit PIN code.'
    try:
        day=datetime.strptime(p['date'],'%Y-%m-%d').date();today=datetime.now(TZ).date()
        if not today+timedelta(days=1)<=day<=today+timedelta(days=14):raise ValueError()
    except ValueError:errors['date']='Choose a date from tomorrow through the next 14 days.'
    if p['slot'] not in ['Morning','Afternoon']:errors['slot']='Choose a preferred pickup window.'
    allowed={m['id'] for m in config['materials']}
    p['materials']=b.get('materials') if isinstance(b.get('materials'),list) else []
    if not p['materials'] or any(x not in allowed for x in p['materials']):errors['materials']='Select at least one listed material.'
    try:
        if p['weight'] and not 0<float(p['weight'])<=10000:raise ValueError()
    except ValueError:errors['weight']='Enter a weight greater than zero, or leave it blank.'
    if b.get('quantities'):
        quantities=b['quantities'];catalog={m['id']:m for m in config['materials']}
        if not isinstance(quantities,dict) or len(quantities)>len(catalog):errors['quantities']='Check the material quantities.'
        else:
            clean={}
            for id,raw in quantities.items():
                try:
                    qty=float(raw)
                    if id not in p['materials'] or id not in catalog or not math.isfinite(qty) or not 0<qty<=10000 or (catalog[id]['unit']=='item' and not qty.is_integer()):raise ValueError()
                    clean[id]=int(qty) if catalog[id]['unit']=='item' else qty
                except (ValueError,TypeError):errors['quantities']='Use positive weights and whole-number piece quantities for selected materials.'
            if clean:p['quantities']=clean
    service=text(b.get('service'),80)
    if service and service not in {x['id'] for x in SERVICES}:errors['service']='Choose a listed service.'
    if service:p['service']=service
    if b.get('consent') is not True:errors['consent']='Please agree to use these details for this request.'
    if errors:raise Problem(422,'Please check the highlighted details.',errors)
    p['materials']=list(dict.fromkeys(p['materials']));p['city']='Baripada';p['consentAt']=now()
    return p

class Handler(BaseHTTPRequestHandler):
    server_version='ApnaLocal/1.0';sys_version=''
    def log_message(self,fmt,*args):
        # Never log bodies, passcodes, reference query strings or customer data.
        pass
    def finish_headers(self):
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        self.send_header('X-Frame-Options','DENY');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
    def reply(self,status,data,headers=None):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.finish_headers();self.wfile.write(raw)
    def host_check(self):
        host=self.headers.get('Host','').lower()
        if PUBLIC_TEST:
            if host=='healthcheck.railway.app' and urlsplit(self.path).path=='/healthz':return
            if host not in PUBLIC_HOSTS:raise Problem(403,'This hostname is not enabled for the test website.')
        elif host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:raise Problem(403,'This preview is available on this device only.')
    def body(self):
        origin=self.headers.get('Origin')
        expected={('https://'+h) for h in PUBLIC_HOSTS} if PUBLIC_TEST else {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
        if origin and origin not in expected:raise Problem(403,'Cross-origin requests are not allowed.')
        if self.headers.get('X-Apna-CSRF')!=CSRF:raise Problem(403,'Please refresh this page and try again.')
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise Problem(415,'Send JSON data.')
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise Problem(400,'Invalid request size.')
        if not 1<=length<=16384:raise Problem(413,'This request is too large or empty.')
        try:
            obj=json.loads(self.rfile.read(length))
            if not isinstance(obj,dict):raise ValueError()
            return obj
        except (ValueError,UnicodeDecodeError):raise Problem(400,'We could not read that request. Please try again.')
    def admin(self):
        cookie=SimpleCookie(self.headers.get('Cookie',''));token=cookie.get('apna_desk')
        if not token or SESSIONS.get(token.value,0)<time.time():raise Problem(401,'Unlock the booking desk first.')
    def limited(self,kind,maximum=30):
        key=(self.client_address[0],kind);nowtime=time.time()
        with LOCK:
            if len(LIMITS)>10000:
                for stale in list(LIMITS):
                    if not any(t>nowtime-60 for t in LIMITS[stale]):LIMITS.pop(stale,None)
            entries=[t for t in LIMITS.get(key,[]) if nowtime-t<60]
            if len(entries)>=maximum:raise Problem(429,'Too many attempts. Please try again in a minute.')
            LIMITS[key]=entries+[nowtime]
    def booking_row(self,b):
        ref=text(b.get('reference'),40).upper();num=phone(b.get('phone',''))
        with connect() as c:row=c.execute('SELECT * FROM bookings WHERE id=? AND phone=?',(ref,num)).fetchone()
        if not row:raise Problem(404,'No matching request found. Check the reference and mobile number.')
        return row
    def do_GET(self):self.run('GET')
    def do_POST(self):self.run('POST')
    def do_PATCH(self):self.run('PATCH')
    def do_HEAD(self):self.run('HEAD')
    def run(self,method):
        try:self.host_check();self.dispatch(method)
        except (BrokenPipeError,ConnectionResetError):pass
        except Problem as e:self.reply(e.status,{'error':e.message,'fields':e.fields or {}})
        except (sqlite3.Error,OSError):self.reply(503,{'error':'Preview storage is temporarily unavailable. Please try again.'})
        except (ValueError,KeyError,TypeError):self.reply(400,{'error':'Please check the request details.'})
    def dispatch(self,method):
        path=unquote(urlsplit(self.path).path).rstrip('/') or '/'
        if path=='/healthz' and method in ['GET','HEAD']:
            with connect() as c:c.execute('SELECT 1').fetchone()
            return self.reply(200,{'ok':True,'mode':'public-test' if PUBLIC_TEST else 'local'})
        if method in ['GET','HEAD'] and not path.startswith('/api/'):
            if path=='/articles.json':raise Problem(404,'Not found.')
            article_route=path.startswith('/news/') and any(a['slug']==path.removeprefix('/news/') and a['status']!='draft' for a in settings()['articles'])
            if path in ROUTES or article_route or '.' not in path.rsplit('/',1)[-1]:target=PUBLIC/'index.html';status=200 if path in ROUTES or article_route else 404
            else:
                target=(PUBLIC/path.lstrip('/')).resolve();status=200
                if not target.is_relative_to(PUBLIC):raise Problem(404,'Not found.')
            if not target.is_file():raise Problem(404,'Not found.')
            raw=target.read_bytes();self.send_response(status);mime=mimetypes.guess_type(target)[0] or 'application/octet-stream';self.send_header('Content-Type',mime+('; charset=utf-8' if mime.startswith('text/') else ''));self.send_header('Content-Length',str(len(raw)));self.finish_headers()
            if method!='HEAD':self.wfile.write(raw)
            return
        if method=='GET' and path=='/api/config':
            c=settings();c['articles']=[a for a in c['articles'] if a['status']!='draft'];return self.reply(200,{**c,'csrf':CSRF,'mode':'public-test' if PUBLIC_TEST else 'local','today':datetime.now(TZ).date().isoformat(),'brand':'APNA KABADI','tagline':'Apna kabadi, sahi daam.','services':SERVICES,'localityDirectory':LOCALITIES})
        if method=='GET' and path=='/api/slots':
            day=parse_qs(urlsplit(self.path).query).get('date',[''])[0]
            try:datetime.strptime(day,'%Y-%m-%d')
            except ValueError:raise Problem(422,'Choose a valid pickup date.')
            with connect() as c:rows=c.execute("SELECT payload FROM bookings WHERE status IN ('Confirmed','On the way','Arrived','Completed')").fetchall()
            counts={s:sum(json.loads(r[0]).get('date')==day and json.loads(r[0]).get('slot')==s for r in rows) for s in ['Morning','Afternoon']}
            cap=settings()['capacityPerDay'];return self.reply(200,{'slots':[{'name':s,'available':counts[s]<max(1,(cap+1)//2) and sum(counts.values())<cap} for s in counts],'note':'This is a preference. A dispatcher confirms the final window.'})
        if method=='GET' and path.startswith('/api/admin/'):
            self.admin()
            if path=='/api/admin/settings':return self.reply(200,settings())
            if path=='/api/admin/bookings':
                with connect() as c:rows=c.execute('SELECT * FROM bookings ORDER BY created DESC,id DESC').fetchall()
                return self.reply(200,{'bookings':[{**dict(r),'payload':json.loads(r['payload'])} for r in rows]})
            if path=='/api/admin/export':
                stream=io.StringIO();w=csv.writer(stream);w.writerow(['Reference','Name','Phone','Locality','Preferred date','Window','Materials','Service','Ward','Bulk / special quote','Status','Created'])
                with connect() as c:rows=c.execute('SELECT * FROM bookings ORDER BY created DESC').fetchall()
                for r in rows:
                    p=json.loads(r['payload']);values=[r['id'],r['name'],r['phone'],p['locality'],p['date'],p['slot'],', '.join(p['materials']),next((x['title'] for x in SERVICES if x['id']==p.get('service')),''),str(p.get('ward','')),'Requested' if p.get('quoteRequested') else '',r['status'],r['created']]
                    w.writerow(["'"+v if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in values])
                raw=stream.getvalue().encode();self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="apna-kabadi-local-requests.csv"');self.finish_headers();self.wfile.write(raw);return
        if method not in ['POST','PATCH']:raise Problem(404,'Not found.')
        b=self.body()
        if path=='/api/bookings' and method=='POST':
            self.limited('book',20);c=settings();p=validate_booking(b,c);key=text(b.get('requestKey'),80)
            if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):raise Problem(422,'Refresh the form before submitting.')
            digest=hashlib.sha256(json.dumps({k:v for k,v in p.items() if k!='consentAt'},sort_keys=True).encode()).hexdigest()
            with connect() as db:
                db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM bookings WHERE request_key=?',(key,)).fetchone()
                if old:
                    if old['digest']!=digest:raise Problem(409,'This submission has changed. Refresh the form to create a new request.')
                    return self.reply(200,{'reference':old['id'],'status':old['status'],'mode':'public-test' if PUBLIC_TEST else 'local','notified':False})
                wl=c['serviceLocalities'];special=any(m.get('reviewOnly') and m['id'] in p['materials'] for m in c['materials']) or any(x['id']==p.get('service') and x.get('reviewOnly') for x in SERVICES) or p.get('quoteRequested',False);status='Waitlisted' if special or (wl and p['locality'].casefold() not in [x.casefold() for x in wl]) else 'Requested'
                ref='AK-'+datetime.now(TZ).strftime('%y%m%d')+'-'+secrets.token_hex(4).upper();stamp=now()
                db.execute('INSERT INTO bookings VALUES (?,?,?,?,?,1,?,?,?,?)',(ref,p['name'],p['phone'],json.dumps(p),status,stamp,stamp,key,digest));db.execute('INSERT INTO events(booking,status,note,created) VALUES (?,?,?,?)',(ref,status,'Saved in the public testing preview.' if PUBLIC_TEST else 'Saved in the local website preview.',stamp))
            return self.reply(201,{'reference':ref,'status':status,'mode':'public-test' if PUBLIC_TEST else 'local','notified':False})
        if path in ['/api/lookup','/api/cancel']:
            self.limited('lookup');row=self.booking_row(b);p=json.loads(row['payload'])
            if path=='/api/cancel':
                if row['status'] not in ['Requested','Confirmed','Waitlisted']:raise Problem(409,'This request can no longer be cancelled here. Please contact the dispatcher.')
                with connect() as c:
                    result=c.execute('UPDATE bookings SET status=?,version=version+1,updated=? WHERE id=? AND version=?',('Cancelled',now(),row['id'],row['version']))
                    if result.rowcount!=1:raise Problem(409,'The request changed. Please check its latest status.')
                    c.execute('INSERT INTO events(booking,status,note,created) VALUES (?,?,?,?)',(row['id'],'Cancelled','Cancelled through the test request page.',now()))
                row=self.booking_row(b)
            with connect() as c:events=[dict(r) for r in c.execute('SELECT status,note,created FROM events WHERE booking=? ORDER BY id',(row['id'],))]
            return self.reply(200,{'reference':row['id'],'name':row['name'].split()[0],'status':row['status'],'date':p['date'],'slot':p['slot'],'locality':p['locality'],'materials':p['materials'],'service':p.get('service',''),'quantities':p.get('quantities',{}),'ward':p.get('ward'),'quoteRequested':p.get('quoteRequested',False),'events':events,'mode':'public-test' if PUBLIC_TEST else 'local'})
        if path=='/api/admin/login':
            self.limited('login',10)
            if not secrets.compare_digest(text(b.get('key'),200),ADMIN_KEY):raise Problem(401,'That desk passcode is incorrect.')
            token=secrets.token_urlsafe(32);SESSIONS[token]=time.time()+8*3600
            return self.reply(200,{'ok':True},{'Set-Cookie':f'apna_desk={token}; HttpOnly; SameSite=Strict; Path=/api/admin; Max-Age=28800'+('; Secure' if PUBLIC_TEST else '')})
        if path=='/api/admin/logout':
            cookie=SimpleCookie(self.headers.get('Cookie',''));item=cookie.get('apna_desk')
            if item:SESSIONS.pop(item.value,None)
            return self.reply(200,{'ok':True},{'Set-Cookie':'apna_desk=; HttpOnly; SameSite=Strict; Path=/api/admin; Max-Age=0'+('; Secure' if PUBLIC_TEST else '')})
        if path=='/api/admin/article' and method=='PATCH':
            self.admin();c=settings();article={k:text(b.get(k),limit) for k,limit in [('slug',80),('title',140),('category',50),('excerpt',300),('body',14000),('image',80),('status',20)]}
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',article['slug']) or len(article['title'])<3 or len(article['body'])<20 or not article['category']:raise Problem(422,'Add a title, URL slug, category and article text.')
            if article['status'] not in ['preview','visible','draft']:raise Problem(422,'Choose an article visibility.')
            if article['image'] not in {m['id'] for m in MATERIALS}:raise Problem(422,'Choose a material cover image.')
            sources=b.get('sources',[])
            if not isinstance(sources,list) or len(sources)>8:raise Problem(422,'Use up to eight source links.')
            article['sources']=[]
            for source in sources:
                if not isinstance(source,dict):raise Problem(422,'Check the article sources.')
                url=text(source.get('url'),500);u=urlsplit(url)
                if u.scheme!='https' or not u.hostname or u.username or u.password:raise Problem(422,'Source links must be complete HTTPS addresses.')
                article['sources'].append({'title':text(source.get('title'),150) or u.hostname,'url':url})
            previous=text(b.get('originalSlug'),80);others=[a for a in c['articles'] if a['slug']!=previous]
            if any(a['slug']==article['slug'] for a in others):raise Problem(422,'That article URL already exists.')
            if len(others)>=50:raise Problem(422,'The local editor supports up to 50 articles.')
            c['articles']=[article]+others
            with connect() as db:db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(c),))
            return self.reply(200,{'ok':True,'slug':article['slug']})
        if path=='/api/admin/press' and method=='PATCH':
            self.admin();features=b.get('features')
            if not isinstance(features,list) or len(features)>20:raise Problem(422,'Use up to 20 media features.')
            clean=[]
            for f in features:
                if not isinstance(f,dict):raise Problem(422,'Check the media feature details.')
                title=text(f.get('title'),180);outlet=text(f.get('outlet'),100);url=text(f.get('url'),500);u=urlsplit(url)
                if not title or not outlet or u.scheme!='https' or not u.hostname or u.username or u.password:raise Problem(422,'Add an outlet, title and full HTTPS coverage link.')
                clean.append({'title':title,'outlet':outlet,'url':url})
            c=settings();c['pressFeatures']=clean
            with connect() as db:db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(c),))
            return self.reply(200,{'ok':True})
        if path=='/api/admin/settings' and method=='PATCH':
            self.admin();c=settings()
            for field,limit in [('businessNumber',20),('email',150),('domain',200),('legalName',150),('address',300),('serviceHours',200),('instagramUrl',250),('facebookUrl',250)]:
                if field in b:c[field]=text(b[field],limit)
            if c['businessNumber'] and not re.fullmatch(r'91[6-9]\d{9}',c['businessNumber']):raise Problem(422,'Use 91 followed by a valid 10-digit business number.')
            if c['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',c['email']):raise Problem(422,'Enter a valid email address.')
            if c['domain'] and not re.fullmatch(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',c['domain']):raise Problem(422,'Enter a domain without a path or protocol.')
            for field,hosts in [('instagramUrl',{'instagram.com','www.instagram.com'}),('facebookUrl',{'facebook.com','www.facebook.com','m.facebook.com'})]:
                if c[field]:
                    u=urlsplit(c[field])
                    if u.scheme!='https' or u.hostname not in hosts or u.username or u.password:raise Problem(422,'Use the complete HTTPS link to the correct social profile.')
            if 'serviceLocalities' in b:
                if not isinstance(b['serviceLocalities'],list) or len(b['serviceLocalities'])>100:raise Problem(422,'Enter up to 100 localities.')
                c['serviceLocalities']=[text(x,100) for x in b['serviceLocalities'] if text(x,100)]
            if 'capacityPerDay' in b:
                cap=int(b['capacityPerDay'])
                if not 1<=cap<=100:raise Problem(422,'Capacity must be between 1 and 100.')
                c['capacityPerDay']=cap
            if 'rates' in b:
                if not isinstance(b['rates'],dict):raise Problem(422,'Enter rates by material.')
                for m in c['materials']:
                    if m['id'] not in b['rates']:continue
                    raw=b['rates'].get(m['id']);rate=None if raw in ['',None] else float(raw)
                    if rate is not None and (not 0<=rate<=10000):raise Problem(422,'Buying rates must be between 0 and 10,000 per kg.')
                    m['rate']=rate
                c['ratesUpdatedAt']=now()
            with connect() as db:db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(c),))
            return self.reply(200,{'ok':True})
        if path.startswith('/api/admin/bookings/') and method=='PATCH':
            self.admin();ref=path.rsplit('/',1)[-1];new=b.get('status');note=text(b.get('note'),500)
            with connect() as c:
                c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM bookings WHERE id=?',(ref,)).fetchone()
                if not row:raise Problem(404,'Request not found.')
                if b.get('version')!=row['version']:raise Problem(409,'Another change was saved first. Refresh the desk.')
                if new not in TRANSITIONS.get(row['status'],[]):raise Problem(422,'That status change is not available.')
                if new=='Confirmed':
                    p=json.loads(row['payload']);rows=c.execute("SELECT payload FROM bookings WHERE status IN ('Confirmed','On the way','Arrived','Completed') AND id!=?",(ref,)).fetchall();day=[json.loads(r[0]) for r in rows if json.loads(r[0])['date']==p['date']];cap=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])['capacityPerDay']
                    if len(day)>=cap or sum(x['slot']==p['slot'] for x in day)>=max(1,(cap+1)//2):raise Problem(409,'The configured capacity for this window has been reached.')
                c.execute('UPDATE bookings SET status=?,version=version+1,updated=? WHERE id=?',(new,now(),ref));c.execute('INSERT INTO events(booking,status,note,created) VALUES (?,?,?,?)',(ref,new,note or 'Updated in the booking desk.',now()))
            return self.reply(200,{'ok':True})
        raise Problem(404,'Not found.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8427);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'APNA KABADI local preview: http://127.0.0.1:{args.port}',flush=True)
    print(f'Local desk passcode is in {KEY_FILE}. No messages or payments are sent.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()
