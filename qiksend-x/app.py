# app.py — QikSend-X
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os
from pathlib import Path

# ---- Paths & Config ----
BASE_DIR = Path(__file__).resolve().parent

# Force subfolder paths (your repo keeps templates/static under qiksend-x/)
app = Flask(
    __name__,
    template_folder="qiksend-x/templates",
    static_folder="qiksend-x/static",
)

# Secrets & admin credentials (override in Render → Environment)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "qiksend_secret")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@qiksend.com")
ADMIN_PASS  = os.getenv("ADMIN_PASS",  "admin123")

# SQLite location (Render-friendly)
DATA_DIR = os.getenv("DATA_DIR", str(BASE_DIR / "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE = os.path.join(DATA_DIR, "qiksendx.db")


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist (safe to run on every boot)."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS riders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_name TEXT NOT NULL,
            receiver_name TEXT NOT NULL,
            status TEXT NOT NULL,
            rider_id INTEGER,
            payment_status TEXT NOT NULL,
            FOREIGN KEY (rider_id) REFERENCES riders(id)
        )
    """)
    conn.commit()
    conn.close()


# Ensure DB exists when running under Gunicorn
init_db()

# Health check (helps diagnose 502s quickly)
@app.get("/healthz")
def healthz():
    return "ok", 200

# ---------- ROUTES ----------

@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL and password == ADMIN_PASS:
            session["user"] = "admin"
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials. Try again.")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    total_deliveries   = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
    pending_deliveries = conn.execute("SELECT COUNT(*) FROM deliveries WHERE status = 'Pending'").fetchone()[0]
    total_riders       = conn.execute("SELECT COUNT(*) FROM riders").fetchone()[0]
    conn.close()

    return render_template(
        "dashboard.html",
        total_deliveries=total_deliveries,
        pending_deliveries=pending_deliveries,
        total_riders=total_riders,
    )


# --- Deliveries ---

@app.route("/deliveries")
def deliveries():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    deliveries_rows = conn.execute(
        """
        SELECT d.id, d.sender_name, d.receiver_name, d.status, d.payment_status,
               r.name AS rider_name
        FROM deliveries d
        LEFT JOIN riders r ON d.rider_id = r.id
        ORDER BY d.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("deliveries.html", deliveries=deliveries_rows)


@app.route("/add-delivery", methods=["GET", "POST"])
def add_delivery():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    if request.method == "POST":
        sender   = request.form.get("sender_name", "").strip()
        receiver = request.form.get("receiver_name", "").strip()
        status   = request.form.get("status", "Pending").strip()
        rider_id = request.form.get("rider_id", "").strip()
        payment  = request.form.get("payment_status", "Unpaid").strip()

        rider_id_val = int(rider_id) if rider_id.isdigit() else None

        conn.execute(
            """
            INSERT INTO deliveries (sender_name, receiver_name, status, rider_id, payment_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sender, receiver, status, rider_id_val, payment),
        )
        conn.commit()
        conn.close()
        flash("Delivery added successfully.")
        return redirect(url_for("deliveries"))

    riders_rows = conn.execute("SELECT * FROM riders ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("add-delivery.html", riders=riders_rows)


# --- Riders ---

@app.route("/riders")
def riders():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM riders ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("riders.html", riders=rows)


@app.route("/add-rider", methods=["GET", "POST"])
def add_rider():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        conn = get_db_connection()
        conn.execute("INSERT INTO riders (name, phone) VALUES (?, ?)", (name, phone))
        conn.commit()
        conn.close()
        flash("Rider added successfully.")
        return redirect(url_for("riders"))

    return render_template("add-rider.html")


# --- 404 ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


# ---------- DEV ENTRYPOINT ----------
# (Production uses Gunicorn via wsgi.py -> wsgi:app)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
