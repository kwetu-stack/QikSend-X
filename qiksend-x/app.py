from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'qiksend_secret'

DATABASE = 'qiksendx.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- ROUTES ----------

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if email == 'admin@qiksend.com' and password == 'admin123':
            session['user'] = 'admin'
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    total_deliveries = conn.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]
    pending_deliveries = conn.execute("SELECT COUNT(*) FROM deliveries WHERE status = 'Pending'").fetchone()[0]
    total_riders = conn.execute('SELECT COUNT(*) FROM riders').fetchone()[0]
    conn.close()

    return render_template('dashboard.html',
                           total_deliveries=total_deliveries,
                           pending_deliveries=pending_deliveries,
                           total_riders=total_riders)

# --- Deliveries ---

@app.route('/deliveries')
def deliveries():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    deliveries = conn.execute('''
        SELECT d.id, d.sender_name, d.receiver_name, d.status, d.payment_status, 
               r.name AS rider_name
        FROM deliveries d
        LEFT JOIN riders r ON d.rider_id = r.id
        ORDER BY d.id DESC
    ''').fetchall()
    conn.close()
    return render_template('deliveries.html', deliveries=deliveries)

@app.route('/add-delivery', methods=['GET', 'POST'])
def add_delivery():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    if request.method == 'POST':
        sender = request.form['sender_name']
        receiver = request.form['receiver_name']
        status = request.form['status']
        rider_id = request.form['rider_id']
        payment = request.form['payment_status']

        conn.execute('''
            INSERT INTO deliveries (sender_name, receiver_name, status, rider_id, payment_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender, receiver, status, rider_id, payment))
        conn.commit()
        conn.close()
        flash('Delivery added successfully.')
        return redirect(url_for('deliveries'))

    riders = conn.execute('SELECT * FROM riders').fetchall()
    conn.close()
    return render_template('add-delivery.html', riders=riders)

# --- Riders ---

@app.route('/riders')
def riders():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    riders = conn.execute('SELECT * FROM riders ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('riders.html', riders=riders)

@app.route('/add-rider', methods=['GET', 'POST'])
def add_rider():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']

        conn = get_db_connection()
        conn.execute('INSERT INTO riders (name, phone) VALUES (?, ?)', (name, phone))
        conn.commit()
        conn.close()
        flash('Rider added successfully.')
        return redirect(url_for('riders'))

    return render_template('add-rider.html')

# --- 404 Handler ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# ---------- START ----------

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        conn = get_db_connection()
        conn.execute('''
            CREATE TABLE riders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                receiver_name TEXT NOT NULL,
                status TEXT NOT NULL,
                rider_id INTEGER,
                payment_status TEXT NOT NULL,
                FOREIGN KEY (rider_id) REFERENCES riders(id)
            )
        ''')
        conn.commit()
        conn.close()

    app.run(debug=True)
