import os
import csv
from io import StringIO
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    abort, Response
)
from flask_sqlalchemy import SQLAlchemy

# ========================= Config =========================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_SQLITE = f"sqlite:///{DATA_DIR/'qiksendx.db'}"

def _pick_database_url():
    url = os.getenv("DATABASE_URL", "").strip()
    # Render / Heroku may give postgres:// – SQLAlchemy expects postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url or "://" not in url:
        return DEFAULT_SQLITE
    return url

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-qiksendx")
app.config["SQLALCHEMY_DATABASE_URI"] = _pick_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ========================= Models =========================
STATUS_CREATED = "Created"
STATUS_IN_TRANSIT = "In_Transit"
STATUS_DELIVERED = "Delivered"
STATUS_CHOICES = (STATUS_CREATED, STATUS_IN_TRANSIT, STATUS_DELIVERED)

class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    phone = db.Column(db.String(50))
    location = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.String(32), default=lambda: now_str())

class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.String(32), default=lambda: now_str())

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.String(32), default=lambda: now_str())

class Parcel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tracking_code = db.Column(db.String(64), nullable=False, unique=True)

    sender_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    origin_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    destination_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    courier_id = db.Column(db.Integer, db.ForeignKey("courier.id"), nullable=True)

    description = db.Column(db.String(255), default="")
    amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(32), default=STATUS_CREATED)
    created_at = db.Column(db.String(32), default=lambda: now_str())
    updated_at = db.Column(db.String(32), default=lambda: now_str())

    sender = db.relationship("Customer", foreign_keys=[sender_id])
    recipient = db.relationship("Customer", foreign_keys=[recipient_id])
    origin_branch = db.relationship("Branch", foreign_keys=[origin_branch_id])
    destination_branch = db.relationship("Branch", foreign_keys=[destination_branch_id])
    courier = db.relationship("Courier", foreign_keys=[courier_id])

class ParcelStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey("parcel.id"), nullable=False)
    status = db.Column(db.String(32), nullable=False)
    note = db.Column(db.String(255))
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    timestamp = db.Column(db.String(32), default=lambda: now_str())

# ========================= Helpers =========================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def tc():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"QSX-{ts}"

def parcel_to_row(p: Parcel):
    return {
        "id": p.id,
        "tracking_code": p.tracking_code,
        "sender_name": p.sender.name,
        "sender_phone": p.sender.phone,
        "recipient_name": p.recipient.name,
        "recipient_phone": p.recipient.phone,
        "origin_branch_name": p.origin_branch.name,
        "origin_branch_location": p.origin_branch.location,
        "destination_branch_name": p.destination_branch.name,
        "destination_branch_location": p.destination_branch.location,
        "courier_name": p.courier.name if p.courier else None,
        "courier_phone": p.courier.phone if p.courier else None,
        "description": p.description or "",
        "amount": p.amount or 0.0,
        "current_status": p.status,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }

def customers_list():
    return [{"id": c.id, "name": c.name, "phone": c.phone} for c in Customer.query.order_by(Customer.name).all()]

def branches_list():
    return [{"id": b.id, "name": b.name, "location": b.location, "phone": b.phone or ""} for b in Branch.query.order_by(Branch.name).all()]

def couriers_list():
    return [{"id": r.id, "name": r.name, "phone": r.phone, "active": bool(r.active)} for r in Courier.query.order_by(Courier.name).all()]

# ========================= DB Seed =========================
def seed_if_empty():
    if Branch.query.count() == 0:
        db.session.add_all([
            Branch(name="Nairobi CBD", phone="+254700000001", location="Nairobi CBD"),
            Branch(name="Westlands", phone="+254700000002", location="Westlands"),
            Branch(name="Mombasa", phone="+254700000003", location="Mombasa"),
        ])
        db.session.commit()
    if Courier.query.count() == 0:
        db.session.add_all([
            Courier(name="Rider A", phone="+254711111111", active=True),
            Courier(name="Rider B", phone="+254722222222", active=True),
            Courier(name="Rider C", phone="+254733333333", active=False),
        ])
        db.session.commit()
    if Customer.query.count() == 0:
        db.session.add_all([
            Customer(name="Alice W.", phone="+254740000001"),
            Customer(name="Bundi K.", phone="+254740000002"),
            Customer(name="Jane M.", phone="+254740000003"),
            Customer(name="Peter N.", phone="+254740000004"),
            Customer(name="Mary A.", phone="+254740000005"),
        ])
        db.session.commit()
    if Parcel.query.count() == 0:
        customers = Customer.query.all()
        branches = Branch.query.all()
        couriers = Courier.query.all()
        def mk(sender, recipient, o, d, status, with_courier=True):
            return Parcel(
                tracking_code=tc(),
                sender_id=sender.id,
                recipient_id=recipient.id,
                origin_branch_id=o.id,
                destination_branch_id=d.id,
                courier_id=(couriers[0].id if with_courier else None),
                description="Demo parcel",
                amount=300.0,
                status=status,
            )
        db.session.add_all([
            mk(customers[0], customers[1], branches[0], branches[1], STATUS_CREATED, False),
            mk(customers[1], customers[2], branches[1], branches[2], STATUS_CREATED, True),
            mk(customers[2], customers[3], branches[0], branches[2], STATUS_IN_TRANSIT, True),
            mk(customers[3], customers[4], branches[2], branches[0], STATUS_IN_TRANSIT, True),
            mk(customers[4], customers[0], branches[1], branches[0], STATUS_DELIVERED, True),
            mk(customers[0], customers[2], branches[2], branches[1], STATUS_DELIVERED, False),
            mk(customers[2], customers[4], branches[0], branches[1], STATUS_CREATED, True),
            mk(customers[4], customers[1], branches[1], branches[2], STATUS_IN_TRANSIT, True),
            mk(customers[1], customers[3], branches[2], branches[0], STATUS_DELIVERED, True),
            mk(customers[3], customers[0], branches[0], branches[2], STATUS_CREATED, False),
        ])
        db.session.commit()

# ========================= Bootstrap (Flask 3 safe) =========================
def _bootstrap():
    try:
        with app.app_context():
            db.create_all()
            seed_if_empty()
    except Exception as e:
        app.logger.error(f"DB init error: {e}")

_bootstrap()

# ========================= Auth =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == "admin@qiksend.local" and p == "kwetutech002":
            session["user"] = "admin"
            flash("Welcome admin")
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out")
    return redirect(url_for("login"))

# ========================= Dashboard =========================
@app.route("/")
@login_required
def dashboard():
    stats = {
        "created": Parcel.query.filter_by(status=STATUS_CREATED).count(),
        "in_transit": Parcel.query.filter_by(status=STATUS_IN_TRANSIT).count(),
        "delivered": Parcel.query.filter_by(status=STATUS_DELIVERED).count(),
    }
    recent = [parcel_to_row(p) for p in Parcel.query.order_by(Parcel.updated_at.desc()).limit(8)]
    return render_template("dashboard.html", stats=stats, recent=recent)

# ========================= Parcels CRUD =========================
@app.route("/parcels")
@login_required
def parcels():
    rows = [parcel_to_row(p) for p in Parcel.query.order_by(Parcel.updated_at.desc()).all()]
    return render_template("parcels.html", parcels=rows)

@app.route("/parcels/new", methods=["GET", "POST"])
@login_required
def new_parcel():
    if request.method == "POST":
        f = request.form
        p = Parcel(
            tracking_code=tc(),
            sender_id=int(f["sender_id"]),
            recipient_id=int(f["recipient_id"]),
            origin_branch_id=int(f["origin_branch_id"]),
            destination_branch_id=int(f["destination_branch_id"]),
            courier_id=int(f["courier_id"]) if f.get("courier_id") else None,
            description=f.get("description", ""),
            amount=float(f.get("amount") or 0),
            status=STATUS_CREATED,
            created_at=now_str(),
            updated_at=now_str(),
        )
        db.session.add(p)
        db.session.commit()
        flash(f"Parcel created {p.tracking_code}")
        return redirect(url_for("parcels"))
    return render_template("new_parcel.html", customers=customers_list(), branches=branches_list(), couriers=couriers_list())

@app.route("/parcels/<int:id>")
@login_required
def parcel_detail(id):
    p = Parcel.query.get_or_404(id)
    return render_template("parcel_detail.html", p=parcel_to_row(p))

@app.route("/parcels/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_parcel(id):
    p = Parcel.query.get_or_404(id)
    if request.method == "POST":
        f = request.form
        p.sender_id = int(f["sender_id"])
        p.recipient_id = int(f["recipient_id"])
        p.origin_branch_id = int(f["origin_branch_id"])
        p.destination_branch_id = int(f["destination_branch_id"])
        p.courier_id = int(f["courier_id"]) if f.get("courier_id") else None
        p.description = f.get("description", "")
        p.amount = float(f.get("amount") or 0)
        p.updated_at = now_str()
        db.session.commit()
        flash("Parcel updated")
        return redirect(url_for("parcel_detail", id=p.id))
    return render_template("new_parcel.html", customers=customers_list(), branches=branches_list(), couriers=couriers_list())

@app.route("/parcels/<int:id>/delete", methods=["POST"])
@login_required
def delete_parcel(id):
    p = Parcel.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash("Parcel deleted")
    return redirect(url_for("parcels"))

@app.route("/parcels/<int:id>/status", methods=["POST"])
@login_required
def update_status(id):
    p = Parcel.query.get_or_404(id)
    new_status = request.form.get("new_status", "")
    if new_status not in STATUS_CHOICES:
        abort(400)
    p.status = new_status
    p.updated_at = now_str()
    db.session.add(ParcelStatusHistory(parcel_id=p.id, status=new_status))
    db.session.commit()
    flash(f"Status updated to {new_status}")
    return redirect(url_for("parcel_detail", id=p.id))

# ========================= Track (public) =========================
@app.route("/track", methods=["GET"])
def track():
    code = request.args.get("code", "").strip()
    result = None
    if code:
        p = Parcel.query.filter_by(tracking_code=code).first()
        if p:
            result = type("R", (), parcel_to_row(p))()
    return render_template("track.html", result=result)

# ========================= Couriers CRUD =========================
@app.route("/couriers")
@login_required
def couriers():
    return render_template("couriers.html", couriers=Courier.query.order_by(Courier.name).all())

@app.route("/couriers/new", methods=["GET", "POST"])
@login_required
def new_courier():
    if request.method == "POST":
        c = Courier(name=request.form["name"], phone=request.form["phone"], active=bool(int(request.form.get("active", "1"))))
        db.session.add(c)
        db.session.commit()
        flash("Courier added")
        return redirect(url_for("couriers"))
    return render_template("courier_form.html", courier=None)

@app.route("/couriers/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_courier(id):
    c = Courier.query.get_or_404(id)
    if request.method == "POST":
        c.name = request.form["name"]
        c.phone = request.form["phone"]
        c.active = bool(int(request.form.get("active", "1")))
        db.session.commit()
        flash("Courier updated")
        return redirect(url_for("couriers"))
    return render_template("courier_form.html", courier=c)

@app.route("/couriers/<int:id>/delete", methods=["POST"])
@login_required
def delete_courier(id):
    c = Courier.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    flash("Courier deleted")
    return redirect(url_for("couriers"))

# ========================= Branches CRUD =========================
@app.route("/branches")
@login_required
def branches():
    return render_template("branches.html", branches=Branch.query.order_by(Branch.name).all())

@app.route("/branches/new", methods=["GET", "POST"])
@login_required
def new_branch():
    if request.method == "POST":
        b = Branch(name=request.form["name"], phone=request.form.get("phone") or "", location=request.form["location"])
        db.session.add(b)
        db.session.commit()
        flash("Branch created")
        return redirect(url_for("branches"))
    return render_template("branch_form.html", branch=None)

@app.route("/branches/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_branch(id):
    b = Branch.query.get_or_404(id)
    if request.method == "POST":
        b.name = request.form["name"]
        b.phone = request.form.get("phone") or ""
        b.location = request.form["location"]
        db.session.commit()
        flash("Branch updated")
        return redirect(url_for("branches"))
    return render_template("branch_form.html", branch=b)

@app.route("/branches/<int:id>/delete", methods=["POST"])
@login_required
def delete_branch(id):
    b = Branch.query.get_or_404(id)
    db.session.delete(b)
    db.session.commit()
    flash("Branch deleted")
    return redirect(url_for("branches"))

# ========================= Customers CRUD =========================
@app.route("/customers")
@login_required
def customers():
    return render_template("customers.html", customers=Customer.query.order_by(Customer.name).all())

@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        c = Customer(name=request.form["name"], phone=request.form["phone"])
        db.session.add(c)
        db.session.commit()
        flash("Customer created")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=None)

@app.route("/customers/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(id):
    c = Customer.query.get_or_404(id)
    if request.method == "POST":
        c.name = request.form["name"]
        c.phone = request.form["phone"]
        db.session.commit()
        flash("Customer updated")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=c)

@app.route("/customers/<int:id>/delete", methods=["POST"])
@login_required
def delete_customer(id):
    c = Customer.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    flash("Customer deleted")
    return redirect(url_for("customers"))

# ========================= Reports =========================
@app.route("/reports")
@login_required
def reports():
    q = Parcel.query
    start_date = request.args.get("start_date") or ""
    end_date = request.args.get("end_date") or ""
    status = request.args.get("status") or ""
    term = request.args.get("q") or ""
    export = (request.args.get("export") == "csv")
    if status in STATUS_CHOICES:
        q = q.filter(Parcel.status == status)
    if start_date:
        q = q.filter(Parcel.created_at >= f"{start_date} 00:00:00")
    if end_date:
        q = q.filter(Parcel.created_at <= f"{end_date} 23:59:59")
    if term:
        like = f"%{term}%"
        q = q.join(Parcel.sender).join(Parcel.recipient).join(Parcel.origin_branch).join(Parcel.destination_branch)
        q = q.filter(db.or_(
            Parcel.tracking_code.ilike(like),
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
            Branch.name.ilike(like),
            Branch.location.ilike(like),
        ))
    parcels = q.order_by(Parcel.created_at.desc()).all()
    results = [parcel_to_row(p) for p in parcels]
    if export:
        si = StringIO()
        writer = csv.writer(si)
        writer.writerow(["Tracking", "Sender", "Recipient", "Route", "Courier", "Amount", "Status", "Created", "Updated"])
        for r in results:
            writer.writerow([
                r["tracking_code"],
                f"{r['sender_name']} ({r['sender_phone']})",
                f"{r['recipient_name']} ({r['recipient_phone']})",
                f"{r['origin_branch_name']} → {r['destination_branch_name']}",
                r["courier_name"] or "",
                f"{r['amount']:.2f}",
                r["current_status"],
                r["created_at"],
                r["updated_at"],
            ])
        return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=parcels_report.csv"})
    return render_template("reports.html", results=results)

# ========================= Health & Errors =========================
@app.route("/health")
def health():
    return "OK", 200

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

# ========================= Main =========================
if __name__ == "__main__":
    app.run(debug=True)
