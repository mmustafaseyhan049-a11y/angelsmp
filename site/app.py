import os, secrets, time, threading, hmac
from flask import Flask, request, jsonify, send_from_directory, session, abort

app=Flask(__name__, static_folder=None)
PASSWORD=os.environ.get('PANEL_PASSWORD','')
KEY=os.environ.get('AGENT_KEY','')
app.secret_key=os.environ.get('SESSION_SECRET') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Strict',MAX_CONTENT_LENGTH=16384)
lock=threading.Lock()
state={'seen':0,'running':False,'ready':False,'players':None,'max_players':None,'uptime':0,'restarting':False,'pending':None,'result':''}
last_attempt={}
def eq(a,b): return isinstance(a,str) and bool(b) and hmac.compare_digest(a.encode(),b.encode())
def configured(): return len(PASSWORD)>=12 and len(KEY)>=32 and PASSWORD!=KEY
@app.after_request
def headers(r):
    r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='no-referrer';r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";return r
@app.get('/')
def home(): return send_from_directory('web','index.html')
@app.get('/assets/<name>')
def assets(name):
    if name not in ('style.css','app.js'): abort(404)
    return send_from_directory('web',name)
def browser_post():
    if request.headers.get('X-Angel-Request')!='1' or not request.is_json: abort(403)
def auth():
    if not configured() or session.get('ok') is not True: abort(401)
def agent_auth():
    if not configured() or not eq(request.headers.get('Authorization',''), 'Bearer '+KEY): abort(401)
@app.post('/api/login')
def login():
    browser_post()
    if not configured(): return jsonify(error='Render ortam değişkenleri henüz ayarlanmadı.'),503
    with lock:
        now=time.monotonic(); ip=request.remote_addr
        if len(last_attempt)>3000: last_attempt.clear()
        if now-last_attempt.get(ip,-100)<1.5: return jsonify(error='Biraz sonra tekrar dene.'),429
        last_attempt[ip]=now
    if not eq((request.get_json() or {}).get('password'),PASSWORD): return jsonify(error='Şifre yanlış.'),401
    session.clear();session['ok']=True;return jsonify(ok=True)
@app.post('/api/logout')
def logout(): browser_post();session.clear();return jsonify(ok=True)
@app.get('/api/status')
def status():
    auth()
    with lock:
        connected=time.time()-state['seen']<45
        return jsonify(connected=connected,running=state['running'] if connected else None,ready=state['ready'] if connected else False,players=state['players'] if connected else None,max_players=state['max_players'] if connected else None,uptime=state['uptime'] if connected else 0,restarting=state['restarting'] if connected else False,pending=bool(state['pending'] and state['pending']['expires']>time.time()),result=state['result'])
@app.post('/api/control')
def control():
    browser_post();auth(); action=(request.get_json() or {}).get('action')
    if action not in ('start','stop','restart'): abort(400)
    with lock:
        if time.time()-state['seen']>=45: return jsonify(error='Bilgisayardaki bağlantı programı çevrimdışı.'),409
        if state['pending'] and state['pending']['expires']>time.time(): return jsonify(error='Önceki işlemin sonucu bekleniyor.'),409
        state['pending']={'id':secrets.token_hex(12),'action':action,'expires':time.time()+40};state['result']='İşlem sıraya alındı.'
    return jsonify(ok=True)
@app.post('/api/agent')
def agent():
    agent_auth();d=request.get_json(silent=True)
    if not isinstance(d,dict): abort(400)
    with lock:
        state['seen']=time.time()
        for k in ('running','ready','restarting'): state[k]=d.get(k) is True
        for k in ('players','max_players','uptime'):
            v=d.get(k);state[k]=max(0,min(v,100000000)) if type(v) is int else None
        p=state['pending']
        if p and p['expires']<=time.time(): state['pending']=None;state['result']='İşlem zaman aşımına uğradı.';p=None
        if p and d.get('completed')==p['id']:
            state['result']='İşlem yerel panele iletildi.' if d.get('success') is True else 'Yerel panel işlemi reddetti veya ulaşılamadı.';state['pending']=None;p=None
        return jsonify(command=p)
if __name__=='__main__': app.run(host='127.0.0.1',port=10000)
