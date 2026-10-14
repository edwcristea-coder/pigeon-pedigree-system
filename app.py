import os, json, hmac, hashlib, secrets, io, html
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, session, redirect, render_template_string, send_file, abort
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
if not os.environ.get('SECRET_KEY'):
    raise RuntimeError('Configureaza SECRET_KEY in Render')
app.secret_key = os.environ['SECRET_KEY']
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=True)
USERNAME = os.environ.get('APP_USERNAME', 'edwcristea')
PASSWORD_HASH = os.environ.get('APP_PASSWORD_HASH', '')


def db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pigeons (id BIGSERIAL PRIMARY KEY, ring TEXT NOT NULL UNIQUE, year INTEGER, sex TEXT, color TEXT, breeder TEXT, owner TEXT, name TEXT, line TEXT, notes TEXT, father_id BIGINT REFERENCES pigeons(id) ON DELETE SET NULL, mother_id BIGINT REFERENCES pigeons(id) ON DELETE SET NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS revisions (id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT now(), action TEXT NOT NULL, pigeon_id BIGINT, snapshot JSONB NOT NULL)''')


def auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapped


def check_password(password):
    try:
        salt, digest = PASSWORD_HASH.split('$', 1)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)

STYLE = '''<style>
*{box-sizing:border-box}body{font:15px system-ui,sans-serif;background:#f3f6fa;color:#17243a;margin:0}header{background:#12365d;color:white;padding:15px max(16px,5%);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}header a{color:white}main{max-width:1150px;margin:25px auto;padding:0 16px}.panel{background:white;border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 2px 12px #17365a14}input,select,textarea{padding:10px;border:1px solid #cbd5e1;border-radius:7px;width:100%;max-width:100%}button,.btn{background:#1674c9;color:white;padding:10px 14px;border:0;border-radius:7px;cursor:pointer;text-decoration:none;display:inline-block}.muted{color:#64748b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.pigeon{border:1px solid #dce4ed;padding:15px;border-radius:9px}label{display:block;margin:8px 0}label input,label select{display:block;margin-top:5px}.ped-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}.ped-col{display:flex;flex-direction:column;gap:5px}.ped-cell{flex:1;min-height:55px;border:1px solid #b9c9d9;border-radius:4px;padding:7px;font-size:12px;overflow-wrap:anywhere}.ped-cell b{display:block;color:#12365d}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}@media(max-width:680px){.ped-grid{overflow-x:auto;grid-template-columns:repeat(4,minmax(160px,1fr))}}@media print{header,.no-print{display:none!important}body{background:white}.panel{box-shadow:none}}
</style>'''


def page(body):
    return render_template_string('<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EDW Pigeons</title>'+STYLE+'</head><body><header><strong>EDW PIGEONS</strong><nav><a href="/">Porumbei</a> &nbsp; <a href="/export">Export backup</a> &nbsp; <a href="/logout">Delogare</a></nav></header><main>'+body+'</main></body></html>')


@app.get('/login')
def login_form():
    return page('<section class="panel" style="max-width:400px;margin:60px auto"><h2>Autentificare</h2><form method="post"><label>Utilizator<input name="username" required autocomplete="username"></label><label>Parolă<input name="password" type="password" required autocomplete="current-password"></label><button>Intră</button></form></section>')


@app.post('/login')
def login():
    if hmac.compare_digest(request.form.get('username', ''), USERNAME) and check_password(request.form.get('password', '')):
        session.clear()
        session['authenticated'] = True
        return redirect('/')
    return page('<section class="panel">Date de autentificare incorecte. <a href="/login">Încearcă din nou</a>.</section>'), 401


@app.get('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.get('/')
@auth
def home():
    init()
    q = request.args.get('q', '').strip()
    with db() as c:
        if q:
            birds = c.execute('SELECT * FROM pigeons WHERE ring ILIKE %s OR name ILIKE %s OR line ILIKE %s ORDER BY year DESC NULLS LAST,ring', tuple(['%'+q+'%']*3)).fetchall()
        else:
            birds = c.execute('SELECT * FROM pigeons ORDER BY year DESC NULLS LAST,ring').fetchall()
    cards = ''.join(f'<div class="pigeon"><b>{esc(p["ring"])}</b><p>{esc(p["name"])} · {esc(p["sex"])} · {esc(p["color"])}</p><a href="/pigeon/{p["id"]}">Editează</a> &nbsp; <a href="/pedigree/{p["id"]}">Pedigree</a></div>' for p in birds)
    return page(f'<h1>Evidența crescătoriei</h1><p>{len(birds)} porumbei afișați</p><div class="toolbar"><a class="btn" href="/pigeon/new">+ Adaugă porumbel</a><form method="get" class="toolbar"><input name="q" placeholder="Caută inel, nume, linie" value="{esc(q)}" style="width:260px"><button>Caută</button><a href="/">Resetează</a></form></div><section class="panel"><div class="grid">{cards or "Nu există porumbei pentru această căutare."}</div></section>')


def creates_cycle(birds, pid, parent_id):
    seen = set()
    stack = [parent_id]
    while stack:
        i = stack.pop()
        if i == pid:
            return True
        if i in seen or i not in birds:
            continue
        seen.add(i)
        stack.extend(x for x in (birds[i]['father_id'], birds[i]['mother_id']) if x)
    return False


@app.route('/pigeon/<key>', methods=['GET', 'POST'])
@auth
def pigeon(key):
    init()
    if key != 'new' and not key.isdigit():
        abort(404)
    with db() as c:
        if request.method == 'POST':
            fields = ['ring','name','year','sex','color','breeder','owner','line','notes','father_id','mother_id']
            d = {k: (request.form.get(k, '').strip() or None) for k in fields}
            if not d['ring']:
                return 'Seria inelului este obligatorie', 400
            for k in ('year','father_id','mother_id'):
                if d[k]:
                    try:
                        d[k] = int(d[k])
                    except ValueError:
                        return 'Valoare numerică invalidă', 400
            if d['sex'] not in (None,'M','F'):
                return 'Sex invalid', 400
            if d['father_id'] and d['father_id'] == d['mother_id']:
                return 'Părinții trebuie să fie diferiți', 400
            birds = {b['id']:b for b in c.execute('SELECT id, father_id, mother_id, sex FROM pigeons').fetchall()}
            pid = None if key == 'new' else int(key)
            if pid is not None and pid not in birds:
                abort(404)
            for k,sex in (('father_id','M'),('mother_id','F')):
                parent = d[k]
                if parent and (parent not in birds or birds[parent]['sex'] not in (None,sex)):
                    return f'{k}: porumbel inexistent sau sex incompatibil',400
                if parent and pid is not None and creates_cycle(birds,pid,parent):
                    return 'Legătură genealogică circulară: un descendent nu poate deveni strămoș',400
            try:
                if key == 'new':
                    cols = ','.join(fields)
                    placeholders = ','.join(['%s']*len(fields))
                    pid = c.execute(f'INSERT INTO pigeons ({cols}) VALUES ({placeholders}) RETURNING id',list(d.values())).fetchone()['id']
                    action = 'create'
                else:
                    sets = ','.join(f'{k}=%s' for k in fields)
                    c.execute(f'UPDATE pigeons SET {sets} WHERE id=%s',list(d.values())+[pid])
                    action = 'update'
                snapshot = c.execute('SELECT * FROM pigeons WHERE id=%s',(pid,)).fetchone()
                c.execute('INSERT INTO revisions (action,pigeon_id,snapshot) VALUES (%s,%s,%s::jsonb)',(action,pid,json.dumps(snapshot,default=str)))
            except UniqueViolation:
                return 'Seria inelului există deja în baza de date',409
            return redirect(f'/pigeon/{pid}')
        p = c.execute('SELECT * FROM pigeons WHERE id=%s',(int(key),)).fetchone() if key!='new' else {}
        if key!='new' and not p:
            abort(404)
        birds = c.execute('SELECT id,ring,sex FROM pigeons ORDER BY ring').fetchall()
    def opts(selected,sex):
        return '<option value="">Necunoscut</option>' + ''.join(f'<option value="{b["id"]}" {"selected" if b["id"]==selected else ""}>{esc(b["ring"])}</option>' for b in birds if b['id']!=p.get('id') and b['sex'] in (None,sex))
    labels = {'ring':'Serie inel','name':'Nume','year':'An','sex':'Sex','color':'Culoare','breeder':'Crescător','owner':'Proprietar','line':'Linie','notes':'Observații'}
    fields = ''
    for k,label in labels.items():
        if k == 'sex':
            inp = '<select name="sex"><option value="">Nespecificat</option>' + ''.join(f'<option value="{v}" {"selected" if p.get(k)==v else ""}>{v}</option>' for v in ('M','F')) + '</select>'
        elif k == 'notes':
            inp = f'<textarea name="notes" rows="3">{esc(p.get(k))}</textarea>'
        else:
            inp = f'<input name="{k}" value="{esc(p.get(k))}" {"required" if k=="ring" else ""}>'
        fields += f'<label>{label}{inp}</label>'
    fields += f'<label>Tată (porumbel existent)<select name="father_id">{opts(p.get("father_id"),"M")}</select></label><label>Mamă (porumbel existent)<select name="mother_id">{opts(p.get("mother_id"),"F")}</select></label>'
    link = f'<p><a class="btn" href="/pedigree/{key}">Vezi pedigree</a> &nbsp; <a href="/pedigree/{key}/pdf">Descarcă PDF A4</a></p>' if key!='new' else ''
    return page(f'<h2>{"Adaugă" if key=="new" else "Editează"} porumbel</h2><section class="panel"><form method="post"><div class="grid">{fields}</div><button>Salvează</button></form>{link}</section>')


def ancestry(birds, pid):
    generations = [[pid]]
    for _ in range(3):
        next_gen = []
        for i in generations[-1]:
            p = birds.get(i) if i else None
            next_gen.extend([p['father_id'],p['mother_id']] if p else [None,None])
        generations.append(next_gen)
    return generations


@app.get('/pedigree/<int:pid>')
@auth
def pedigree(pid):
    init()
    with db() as c:
        birds = {p['id']:p for p in c.execute('SELECT * FROM pigeons').fetchall()}
    if pid not in birds:
        abort(404)
    generations = ancestry(birds,pid)
    cols = ''
    for i,gen in enumerate(generations):
        cells = ''
        for bird_id in gen:
            p = birds.get(bird_id) if bird_id else None
            if p:
                cells += f'<div class="ped-cell"><b>{esc(p["ring"])}</b>{esc(p["name"])}<div class="muted">{esc(p["color"])} · {esc(p["line"])}</div></div>'
            else:
                cells += '<div class="ped-cell muted">Necunoscut</div>'
        cols += '<div class="ped-col">'+cells+'</div>'
    return page(f'<div class="toolbar no-print"><a class="btn" href="/pedigree/{pid}/pdf">Descarcă PDF A4</a><a href="/pigeon/{pid}">Înapoi la fișă</a></div><h2>Pedigree – {esc(birds[pid]["ring"])}</h2><section class="panel"><div class="ped-grid">{cols}</div></section>')


def pdf_font():
    candidates = [('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),('DejaVuSans.ttf','DejaVuSans-Bold.ttf')]
    for regular,bold in candidates:
        if os.path.isfile(regular) and os.path.isfile(bold):
            pdfmetrics.registerFont(TTFont('EDWRegular',regular))
            pdfmetrics.registerFont(TTFont('EDWBold',bold))
            return 'EDWRegular','EDWBold'
    return 'Helvetica','Helvetica-Bold'


def short(s,n=35):
    s = str(s or '')
    return s if len(s)<=n else s[:n-1]+'…'


@app.get('/pedigree/<int:pid>/pdf')
@auth
def pedigree_pdf(pid):
    init()
    with db() as c:
        birds = {p['id']:p for p in c.execute('SELECT * FROM pigeons').fetchall()}
    if pid not in birds:
        abort(404)
    gens = ancestry(birds,pid)
    buff = io.BytesIO()
    pdf = canvas.Canvas(buff,pagesize=A4)
    regular,bold = pdf_font()
    W,H = A4
    pdf.setFillColorRGB(.07,.21,.36)
    pdf.rect(0,H-90,W,90,fill=1,stroke=0)
    pdf.setFillColorRGB(1,1,1)
    pdf.setFont(bold,21)
    pdf.drawString(35,H-43,'EDW PIGEONS')
    pdf.setFont(regular,10)
    pdf.drawString(35,H-65,'PEDIGREE - 4 GENERATII')
    pdf.setFillColorRGB(.07,.21,.36)
    pdf.setFont(bold,12)
    pdf.drawString(35,H-116,'Porumbel: '+short(birds[pid]['ring'],45))
    pdf.setFont(regular,9)
    pdf.drawString(35,H-133,'Crescator: '+short(birds[pid].get('breeder'),48))
    pdf.drawString(35,H-148,'Proprietar: '+short(birds[pid].get('owner'),48))
    margin=25; gap=5; top=H-174; bottom=55
    colw=(W-2*margin-3*gap)/4
    headers=['PORUMBEL','PARINTI','BUNICI','STRABUNICI']
    for j,gen in enumerate(gens):
        x=margin+j*(colw+gap)
        pdf.setFillColorRGB(.07,.21,.36)
        pdf.setFont(bold,8)
        pdf.drawString(x,top,headers[j])
        start=top-12
        height=(start-bottom)/len(gen)
        for k,bird_id in enumerate(gen):
            y=start-(k+1)*height+2
            pdf.setStrokeColorRGB(.72,.79,.86)
            pdf.setFillColorRGB(.96,.98,1)
            pdf.roundRect(x,y,colw,height-4,4,stroke=1,fill=1)
            p=birds.get(bird_id) if bird_id else None
            pdf.setFillColorRGB(.07,.21,.36)
            if p:
                maxchars=18 if j==3 else 21
                lines=[(bold,7.2,short(p.get('ring'),maxchars)),(regular,6.5,short(p.get('name'),maxchars)),(regular,6.2,short(p.get('color'),maxchars)),(regular,6.2,short(p.get('line'),maxchars))]
            else:
                lines=[(regular,7,'Necunoscut')]
            yy=y+height-17
            for font,size,value in lines:
                if yy<y+5:break
                pdf.setFont(font,size)
                pdf.drawString(x+5,yy,value)
                yy-=10
    pdf.setFillColorRGB(.4,.45,.52)
    pdf.setFont(regular,8)
    pdf.drawString(margin,25,'Generat cu EDW Pigeons')
    pdf.drawRightString(W-margin,25,datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    pdf.showPage();pdf.save();buff.seek(0)
    return send_file(buff,mimetype='application/pdf',as_attachment=True,download_name=f'pedigree-{pid}.pdf')


@app.get('/export')
@auth
def export():
    init()
    with db() as c:
        data={'exported_at':datetime.now(timezone.utc).isoformat(),'pigeons':c.execute('SELECT * FROM pigeons ORDER BY id').fetchall(),'revisions':c.execute('SELECT * FROM revisions ORDER BY id').fetchall()}
    blob=json.dumps(data,default=str,ensure_ascii=False,indent=2).encode('utf-8')
    return send_file(io.BytesIO(blob),mimetype='application/json',as_attachment=True,download_name='edw-pigeons-backup.json')


@app.get('/health')
def health():
    return 'OK'


if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
