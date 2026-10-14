import os, json, hmac, hashlib, secrets, io, csv
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, session, redirect, render_template_string, jsonify, send_file
import psycopg
from psycopg.rows import dict_row

app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','1')=='1')
USERNAME=os.environ.get('APP_USERNAME','edwcristea')
PASSWORD_HASH=os.environ.get('APP_PASSWORD_HASH','')

def db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)

def init():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS pigeons (id BIGSERIAL PRIMARY KEY, ring TEXT NOT NULL UNIQUE, year INTEGER, sex TEXT, color TEXT, breeder TEXT, owner TEXT, name TEXT, line TEXT, notes TEXT, father_id BIGINT REFERENCES pigeons(id) ON DELETE SET NULL, mother_id BIGINT REFERENCES pigeons(id) ON DELETE SET NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS revisions (id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT now(), action TEXT NOT NULL, pigeon_id BIGINT, snapshot JSONB NOT NULL)')

def auth(f):
    @wraps(f)
    def wrapped(*args,**kwargs):
        if not session.get('authenticated'): return redirect('/login')
        return f(*args,**kwargs)
    return wrapped

def check_password(password):
    if not PASSWORD_HASH: return False
    try:
        salt, digest=PASSWORD_HASH.split('$',1)
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000)
        return hmac.compare_digest(actual.hex(),digest)
    except Exception: return False

STYLE='''<style>body{font:16px system-ui;background:#f4f7fb;color:#17243a;margin:0}header{background:#12365d;color:white;padding:16px 5%;display:flex;justify-content:space-between;align-items:center}main{max-width:1100px;margin:28px auto;padding:0 16px}.panel{background:white;border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 2px 12px #17365a14}input,select,textarea{padding:10px;border:1px solid #cbd5e1;border-radius:7px;max-width:100%;box-sizing:border-box}button,.btn{background:#1674c9;color:white;padding:10px 14px;border:0;border-radius:7px;cursor:pointer;text-decoration:none;display:inline-block}.muted{color:#64748b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.pigeon{border:1px solid #dce4ed;padding:15px;border-radius:9px}label{display:block;margin:8px 0}label input,label select{display:block;width:100%;margin-top:5px}a{color:#176eb8} @media print{header,.no-print{display:none!important}body{background:white}.panel{box-shadow:none}} </style>'''

def page(body, **kwargs):
    return render_template_string('<!doctype html><html lang="ro"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EDW Pigeons</title>'+STYLE+'<header><strong>EDW PIGEONS</strong><nav><a style="color:white" href="/">Porumbei</a> &nbsp; <a style="color:white" href="/export">Export backup</a> &nbsp; <a style="color:white" href="/logout">Delogare</a></nav></header><main>'+body+'</main></html>',**kwargs)

@app.get('/login')
def login_form():
    return page('<section class="panel" style="max-width:380px;margin:60px auto"><h2>Autentificare</h2><form method="post"><label>Utilizator<input name="username" required></label><label>Parolă<input name="password" type="password" required></label><button>Intră în aplicație</button></form></section>')
@app.post('/login')
def login():
    if hmac.compare_digest(request.form.get('username',''),USERNAME) and check_password(request.form.get('password','')):
        session.clear();session['authenticated']=True;return redirect('/')
    return page('<div class="panel">Date de autentificare incorecte. <a href="/login">Încearcă din nou</a>.</div>'),401
@app.get('/logout')
def logout(): session.clear();return redirect('/login')
@app.get('/')
@auth
def home():
    init()
    with db() as c: birds=c.execute('SELECT * FROM pigeons ORDER BY year DESC NULLS LAST,ring').fetchall()
    cards=''.join(f'<div class="pigeon"><b>{esc(p["ring"])}</b><p>{esc(p["name"] or "")} · {esc(p["sex"] or "")} · {esc(p["color"] or "")}</p><a href="/pigeon/{p["id"]}">Editează / Pedigree</a></div>' for p in birds)
    return page(f'<h1>Evidența crescătoriei</h1><p>{len(birds)} porumbei în baza de date</p><a class="btn" href="/pigeon/new">+ Adaugă porumbel</a><section class="panel"><div class="grid">{cards}</div></section>')
def esc(v):
    import html
    return html.escape(str(v or ''),quote=True)
@app.route('/pigeon/<key>',methods=['GET','POST'])
@auth
def pigeon(key):
    init()
    with db() as c:
        if request.method=='POST':
            fields=['ring','name','year','sex','color','breeder','owner','line','notes','father_id','mother_id']
            d={k:(request.form.get(k) or None) for k in fields}
            if not d['ring']:return 'Seria inelului este obligatorie',400
            for k in ('year','father_id','mother_id'):
                if d[k]:
                    try:d[k]=int(d[k])
                    except ValueError:return 'Valoare numerică invalidă',400
            if d['father_id'] and d['mother_id'] and d['father_id']==d['mother_id']:return 'Părinții trebuie să fie diferiți',400
            if key!='new' and (d['father_id']==int(key) or d['mother_id']==int(key)):return 'Un porumbel nu poate fi propriul părinte',400
            if key=='new':
                cols=','.join(fields);params=','.join(['%s']*len(fields));row=c.execute(f'INSERT INTO pigeons ({cols}) VALUES ({params}) RETURNING id',list(d.values())).fetchone();pid=row['id'];action='create'
            else:
                pid=int(key);sets=','.join(f'{k}=%s' for k in fields);c.execute(f'UPDATE pigeons SET {sets} WHERE id=%s',list(d.values())+[pid]);action='update'
            snapshot=c.execute('SELECT * FROM pigeons WHERE id=%s',(pid,)).fetchone()
            c.execute('INSERT INTO revisions (action,pigeon_id,snapshot) VALUES (%s,%s,%s::jsonb)',(action,pid,json.dumps(snapshot,default=str)))
            return redirect(f'/pigeon/{pid}')
        p=c.execute('SELECT * FROM pigeons WHERE id=%s',(int(key),)).fetchone() if key!='new' else {}
        if key!='new' and not p:return 'Porumbel inexistent',404
        birds=c.execute('SELECT id,ring,sex FROM pigeons ORDER BY ring').fetchall()
    opts=lambda selected,sex: '<option value="">Necunoscut</option>'+''.join(f'<option value="{b["id"]}" {"selected" if b["id"]==selected else ""}>{esc(b["ring"])}</option>' for b in birds if b['id']!=p.get('id') and (b['sex']==sex or not b['sex']))
    labels={'ring':'Serie inel','name':'Nume','year':'An','sex':'Sex','color':'Culoare','breeder':'Crescător','owner':'Proprietar','line':'Linie','notes':'Observații'}
    fields=''
    for k,label in labels.items():
        if k=='sex':inp='<select name="sex"><option value="">Nespecificat</option>'+''.join(f'<option {"selected" if p.get(k)==v else ""}>{v}</option>' for v in ['M','F'])+'</select>'
        else:inp=f'<input name="{k}" value="{esc(p.get(k))}" {"required" if k=="ring" else ""}>'
        fields+=f'<label>{label}{inp}</label>'
    fields+=f'<label>Tată<select name="father_id">{opts(p.get("father_id"),"M")}</select></label><label>Mamă<select name="mother_id">{opts(p.get("mother_id"),"F")}</select></label>'
    link=f'<p><a href="/pedigree/{key}">Vezi pedigree / tipărește PDF din browser</a></p>' if key!='new' else ''
    return page(f'<h2>{"Adaugă" if key=="new" else "Editează"} porumbel</h2><div class="panel"><form method="post"><div class="grid">{fields}</div><button>Salvează</button></form>{link}</div>')
@app.get('/pedigree/<int:pid>')
@auth
def pedigree(pid):
    init()
    with db() as c: birds={p['id']:p for p in c.execute('SELECT * FROM pigeons').fetchall()}
    if pid not in birds:return 'Porumbel inexistent',404
    def tree(i,depth,seen):
        if not i or i not in birds:return '<div class="pigeon muted">Necunoscut</div>'
        p=birds[i]
        title=f'<div class="pigeon"><b>{esc(p["ring"])}</b> {esc(p["name"])}<small> {esc(p["color"])} · {esc(p["line"])}</small></div>'
        if depth==0 or i in seen:return title
        return '<div style="display:grid;grid-template-columns:1fr 2fr;gap:8px;align-items:center;margin:4px 0">'+title+'<div>'+tree(p['father_id'],depth-1,seen|{i})+tree(p['mother_id'],depth-1,seen|{i})+'</div></div>'
    return page(f'<div class="no-print"><button onclick="window.print()">Tipărește / Salvează PDF</button></div><h2>Pedigree – {esc(birds[pid]["ring"])}</h2><section class="panel">{tree(pid,3,set())}</section>')
@app.get('/export')
@auth
def export():
    init()
    with db() as c:
        data={'exported_at':datetime.now(timezone.utc).isoformat(),'pigeons':c.execute('SELECT * FROM pigeons ORDER BY id').fetchall(),'revisions':c.execute('SELECT * FROM revisions ORDER BY id').fetchall()}
    blob=json.dumps(data,default=str,ensure_ascii=False,indent=2).encode()
    return send_file(io.BytesIO(blob),mimetype='application/json',as_attachment=True,download_name='edw-pigeons-backup.json')
@app.get('/health')
def health():return 'OK'
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
