#!/usr/bin/env python3
import os, sqlite3
from pathlib import Path
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qiksend.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-qiksend")
app.config["DATABASE"] = str(DB_PATH)

# ------------- DB helpers -------------
def get_db():
    if "db" not in g:
        conn = sqlite3.connect(app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None: conn.close()

def q1(sql, params=()):
    return get_db().execute(sql, params).fetchone()

def qall(sql, params=()):
    return get_db().execute(sql, params).fetchall()

def exec_(sql, params=()):
    db = get_db(); db.execute(sql, params); db.commit()

# ------------- Schema & seed -------------
def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS customers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      phone TEXT,
      id_no TEXT
    );
    CREATE TABLE IF NOT EXISTS transactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      customer_id INTEGER NOT NULL,
      amount REAL NOT NULL CHECK (amount>0),
      currency TEXT NOT NULL DEFAULT 'KES',
      fee REAL NOT NULL DEFAULT 0,
      to_name TEXT NOT NULL,
      to_phone TEXT,
      channel TEXT NOT NULL DEFAULT 'M-Pesa',
      status TEXT NOT NULL DEFAULT 'Pending',
      created_at DATETIME NOT NULL DEFAULT (DATETIME('now')),
      FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
    );
    """)
    if not q1("SELECT id FROM users WHERE email=?", ("admin@qiksend.local",)):
        exec_("INSERT INTO users (name,email,password_hash) VALUES (?,?,?)",
              ("Admin","admin@qiksend.local", generate_password_hash("kwetutech002")))

@app.before_request
def _ensure():
    init_db()

# ------------- Auth helpers -------------
def login_required(view):
    from functools import wraps
    @wraps(view)
    def w(*a, **k):
        if "user_id" not in session: return redirect(url_for("login"))
        return view(*a, **k)
    return w

# ------------- Routes -------------
@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        u = q1("SELECT * FROM users WHERE email=?", (email,))
        if u and check_password_hash(u["password_hash"], password):
            session["user_id"]=u["id"]; session["user_name"]=u["name"]
            return redirect(url_for("dashboard"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    today = date.today().isoformat()
    kpis = {
        "tx_today": q1("SELECT COUNT(*) AS n FROM transactions WHERE DATE(created_at)=DATE('now')")["n"],
        "volume_today": q1("SELECT COALESCE(SUM(amount),0) AS s FROM transactions WHERE DATE(created_at)=DATE('now')")["s"],
        "pending": q1("SELECT COUNT(*) AS n FROM transactions WHERE status='Pending'")["n"],
    }
    recent = qall("""
      SELECT t.*, c.name AS customer_name FROM transactions t
      JOIN customers c ON c.id=t.customer_id
      ORDER BY t.id DESC LIMIT 15
    """)
    return render_template("dashboard.html", kpis=kpis, recent=recent, today=today)

# Customers
@app.route("/customers", methods=["GET","POST"])
@login_required
def customers():
    if request.method=="POST":
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip()
        id_no = request.form.get("id_no","").strip()
        exec_("INSERT INTO customers (name,phone,id_no) VALUES (?,?,?)", (name,phone,id_no))
        flash("Customer added"); return redirect(url_for("customers"))
    rows = qall("SELECT * FROM customers ORDER BY id DESC")
    return render_template("customers.html", rows=rows)

# Transactions
@app.route("/transactions", methods=["GET","POST"])
@login_required
def transactions():
    if request.method=="POST":
        customer_id = request.form.get("customer_id")
        amount = float(request.form.get("amount") or 0)
        currency = request.form.get("currency","KES")
        to_name = request.form.get("to_name","").strip()
        to_phone = request.form.get("to_phone","").strip()
        channel = request.form.get("channel","M-Pesa")
        fee = round(amount * 0.01, 2)  # 1% fee baseline
        exec_("""INSERT INTO transactions (customer_id,amount,currency,fee,to_name,to_phone,channel,status)
                 VALUES (?,?,?,?,?,?,?, 'Pending')""", (customer_id,amount,currency,fee,to_name,to_phone,channel))
        flash("Transaction created"); return redirect(url_for("transactions"))
    customers = qall("SELECT id,name FROM customers ORDER BY name")
    recent = qall("""
        SELECT t.*, c.name AS customer_name FROM transactions t
        JOIN customers c ON c.id=t.customer_id
        ORDER BY t.id DESC LIMIT 30
    """)
    return render_template("transactions.html", customers=customers, recent=recent)

@app.route("/transactions/<int:tx_id>/status", methods=["POST"])
@login_required
def tx_status(tx_id):
    status = request.form.get("status","Completed")
    exec_("UPDATE transactions SET status=? WHERE id=?", (status, tx_id))
    flash("Status updated"); return redirect(url_for("transactions"))

@app.errorhandler(404)
def nf(_): return render_template("404.html"), 404

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
