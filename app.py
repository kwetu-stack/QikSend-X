import os, sqlite3, datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, abort
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR/'data'/'qiksendx.db'

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    (BASE_DIR/'data').mkdir(exist_ok=True)
    db = get_db()
    # Base tables
    db.executescript('''
        CREATE TABLE IF NOT EXISTS parcels(
            id INTEGER PRIMARY KEY,
            tracking_code TEXT UNIQUE,
            sender_name TEXT, sender_phone TEXT,
            recipient_name TEXT, recipient_phone TEXT,
            description TEXT DEFAULT '',
            weight REAL DEFAULT 0,
            fee REAL DEFAULT 0,
            -- include new columns for fresh DBs
            origin TEXT DEFAULT '',
            destination TEXT DEFAULT '',
            current_status TEXT DEFAULT 'CREATED',
            created_at TEXT, updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS locations(
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            is_active INTEGER DEFAULT 1
        );
    ''')
    # Safe migration for existing DBs
    cols = {r['name'] for r in db.execute("PRAGMA table_info(parcels)")}
    if 'origin' not in cols:
        db.execute("ALTER TABLE parcels ADD COLUMN origin TEXT DEFAULT ''")
    if 'destination' not in cols:
        db.execute("ALTER TABLE parcels ADD COLUMN destination TEXT DEFAULT ''")
    db.commit()

def seed():
    db = get_db()
    # Seed demo parcel if empty
    if db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0] == 0:
        now = datetime.datetime.now().isoformat(timespec='seconds')
        db.execute('INSERT INTO parcels(tracking_code,sender_name,sender_phone,recipient_name,recipient_phone,description,weight,fee,current_status,created_at,updated_at,origin,destination) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('QK-20250826-00001','Bundi','+254700','Jane','+254711','Small electronics',1.2,350,'IN_TRANSIT',now,now,'Nairobi CBD','Eldoret Depot'))
        db.commit()
    # Seed locations if empty
    if db.execute('SELECT COUNT(*) FROM locations').fetchone()[0] == 0:
        db.executemany('INSERT INTO locations(name,is_active) VALUES(?,1)',
                       [('Nairobi CBD',), ('Thika Rd Hub',), ('Eldoret Depot',),
                        ('Mombasa Port',), ('Kisumu City Branch',)])
        db.commit()

@app.before_request
def setup(): 
    init_db(); 
    seed()

@app.route('/')
@login_required
def dashboard():
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
    delivered = db.execute("SELECT COUNT(*) FROM parcels WHERE current_status='DELIVERED'").fetchone()[0]
    recent = db.execute('SELECT tracking_code,sender_name,recipient_name,current_status,updated_at FROM parcels ORDER BY updated_at DESC LIMIT 8').fetchall()
    return render_template('dashboard.html', stats={'total': total, 'delivered': delivered}, recent=recent)

@app.route('/parcels')
@login_required
def parcels():
    rows = get_db().execute('SELECT * FROM parcels ORDER BY updated_at DESC').fetchall()
    return render_template('parcels.html', parcels=rows)

@app.route('/parcels/new', methods=['GET','POST'])
@login_required
def new_parcel():
    db = get_db()
    if request.method == 'POST':
        f = request.form; now = datetime.datetime.now().isoformat(timespec='seconds')
        code = 'QK-'+datetime.datetime.now().strftime('%Y%m%d')+'-'+str(int(datetime.datetime.now().timestamp()))[-5:]
        origin = f.get('origin','').strip()
        destination = f.get('destination','').strip()
        db.execute('''
            INSERT INTO parcels(
                tracking_code,sender_name,sender_phone,
                recipient_name,recipient_phone,description,
                weight,fee,origin,destination,
                current_status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (code,
              f['sender_name'], f['sender_phone'],
              f['recipient_name'], f['recipient_phone'],
              f.get('description',''),
              float(f.get('weight') or 0),
              float(f.get('fee') or 0),
              origin, destination,
              'CREATED', now, now))
        g.db.commit(); flash('Parcel created '+code); return redirect(url_for('parcels'))

    locations = db.execute('SELECT id, name FROM locations WHERE is_active=1 ORDER BY name').fetchall()
    return render_template('new_parcel.html', locations=locations)

@app.route('/parcels/<tracking>/receipt')
@login_required
def parcel_receipt(tracking):
    p = get_db().execute('SELECT * FROM parcels WHERE tracking_code=?', (tracking,)).fetchone()
    if not p:
        abort(404)
    return render_template('parcel_receipt.html', p=p)

# NEW: status update endpoint (CREATED -> IN_TRANSIT -> DELIVERED)
@app.route('/parcels/<tracking>/status/<new_status>', methods=['POST'])
@login_required
def update_status(tracking, new_status):
    allowed = ['CREATED', 'IN_TRANSIT', 'DELIVERED']
    if new_status not in allowed:
        abort(400)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    db = get_db()
    db.execute('UPDATE parcels SET current_status=?, updated_at=? WHERE tracking_code=?',
               (new_status, now, tracking))
    db.commit()
    flash(f"Status updated to {new_status}")
    return redirect(url_for('parcels'))

@app.route('/customers')
@login_required
def customers():
    return render_template('customers.html', customers=[{'name':'Bundi','phone':'+254700','type':'sender'},{'name':'Jane','phone':'+254711','type':'recipient'}])

@app.route('/track', methods=['GET'])
def track_home():
    code = request.args.get('code'); item = None
    if code: item = get_db().execute('SELECT * FROM parcels WHERE tracking_code=?',(code,)).fetchone()
    return render_template('track_home.html', item=item)

@app.route('/track/<code>')
def public_track(code):
    p = get_db().execute('SELECT * FROM parcels WHERE tracking_code=?',(code,)).fetchone()
    if not p: abort(404)
    tl=[('CREATED',p['created_at'])]
    if p['current_status'] in ('IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED'): tl.append(('IN_TRANSIT',p['updated_at']))
    if p['current_status'] in ('OUT_FOR_DELIVERY','DELIVERED'): tl.append(('OUT_FOR_DELIVERY',p['updated_at']))
    if p['current_status']=='DELIVERED': tl.append(('DELIVERED',p['updated_at']))
    return render_template('public_track.html', p=p, timeline=tl)

@app.route('/login', methods=['GET','POST'])
def login():
    error=None
    if request.method=='POST':
        u=request.form.get('username',''); p=request.form.get('password','')
        if u=='admin@qiksend.local' and p=='kwetutech002':
            session['user']='admin'; flash('Welcome admin'); return redirect(url_for('dashboard'))
        error='Invalid username or password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear(); flash('Logged out'); return redirect(url_for('login'))

@app.errorhandler(404)
def nf(e): return render_template('404.html'),404

if __name__=='__main__': app.run(debug=True)
