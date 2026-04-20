import os
import uuid
from datetime import datetime
from functools import wraps
from flask import Flask, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import CSRFError
from flask_wtf.csrf import generate_csrf
from werkzeug.security import check_password_hash, generate_password_hash


# -----------------------------
# APP CONFIG
# -----------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["RATELIMIT_STORAGE_URI"] = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = False  # change to True in production
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["WTF_CSRF_CHECK_DEFAULT"] = False

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "qiksendx.db")

database_url = os.environ.get("DATABASE_URL")
if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

csrf = CSRFProtect(app)
db = SQLAlchemy(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)


# -----------------------------
# MODELS
# -----------------------------
class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    location = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Parcel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tracking_code = db.Column(db.String(50), unique=True, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    recipient_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    origin_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    destination_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    courier_id = db.Column(db.Integer, db.ForeignKey("courier.id"), nullable=True)
    description = db.Column(db.String(255))
    amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="Created")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ParcelStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey("parcel.id"))
    status = db.Column(db.String(20))
    note = db.Column(db.String(255), nullable=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="staff")
    courier_id = db.Column(db.Integer, nullable=True)
    session_token = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(100), nullable=False)

    entity = db.Column(db.String(100), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)

    details = db.Column(db.Text, nullable=True)

    ip_address = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
# -----------------------------
# HELPERS
# -----------------------------
def generate_tracking_code():
    return "QX-" + uuid.uuid4().hex[:7].upper()


def generate_session_token():
    return uuid.uuid4().hex


def wants_json_response():
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return request.is_json or (
        best == "application/json"
        and request.accept_mimetypes[best] >= request.accept_mimetypes["text/html"]
    )


def format_datetime(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def latest_parcel_history(parcel_id):
    return (
        ParcelStatusHistory.query.filter_by(parcel_id=parcel_id)
        .order_by(ParcelStatusHistory.timestamp.desc())
        .first()
    )


def serialize_branch(branch):
    return {
        "id": branch.id,
        "name": branch.name,
        "phone": branch.phone,
        "location": branch.location,
        "created_at": format_datetime(branch.created_at),
    }


def serialize_customer(customer):
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "created_at": format_datetime(customer.created_at),
    }


def serialize_courier(courier):
    return {
        "id": courier.id,
        "name": courier.name,
        "phone": courier.phone,
        "active": courier.active,
        "created_at": format_datetime(courier.created_at),
    }


def serialize_parcel(parcel):
    sender = db.session.get(Customer, parcel.sender_id)
    recipient = db.session.get(Customer, parcel.recipient_id)
    origin_branch = db.session.get(Branch, parcel.origin_branch_id)
    destination_branch = db.session.get(Branch, parcel.destination_branch_id)
    courier = db.session.get(Courier, parcel.courier_id) if parcel.courier_id else None
    history = latest_parcel_history(parcel.id)
    updated_at = history.timestamp if history else parcel.created_at

    return {
        "id": parcel.id,
        "tracking_code": parcel.tracking_code,
        "sender_id": parcel.sender_id,
        "sender_name": sender.name if sender else "Unknown",
        "sender_phone": sender.phone if sender else "",
        "recipient_id": parcel.recipient_id,
        "recipient_name": recipient.name if recipient else "Unknown",
        "recipient_phone": recipient.phone if recipient else "",
        "origin_branch_id": parcel.origin_branch_id,
        "origin_branch_name": origin_branch.name if origin_branch else "Unknown",
        "origin_branch_location": origin_branch.location if origin_branch else "",
        "destination_branch_id": parcel.destination_branch_id,
        "destination_branch_name": destination_branch.name if destination_branch else "Unknown",
        "destination_branch_location": destination_branch.location if destination_branch else "",
        "courier_id": parcel.courier_id,
        "courier_name": courier.name if courier else None,
        "courier_phone": courier.phone if courier else None,
        "description": parcel.description or "",
        "amount": parcel.amount or 0,
        "current_status": parcel.status or "Created",
        "created_at": format_datetime(parcel.created_at),
        "updated_at": format_datetime(updated_at),
    }


def serialize_parcel_history(parcel_id):
    history = (
        ParcelStatusHistory.query.filter_by(parcel_id=parcel_id)
        .order_by(ParcelStatusHistory.timestamp.asc())
        .all()
    )
    return [
        {
            "status": item.status,
            "note": item.note,
            "timestamp": format_datetime(item.timestamp),
        }
        for item in history
    ]


def customer_choices():
    return [serialize_customer(customer) for customer in Customer.query.order_by(Customer.name.asc()).all()]


def branch_choices():
    return [serialize_branch(branch) for branch in Branch.query.order_by(Branch.name.asc()).all()]


def courier_choices():
    return [serialize_courier(courier) for courier in Courier.query.order_by(Courier.name.asc()).all()]


def parcel_form_context(parcel=None, error=None):
    return {
        "parcel": serialize_parcel(parcel) if parcel else None,
        "customers": customer_choices(),
        "branches": branch_choices(),
        "couriers": courier_choices(),
        "error": error,
    }


def create_parcel_record(data):
    try:
        # Validate IDs
        sender_id = int(data.get("sender_id"))
        recipient_id = int(data.get("recipient_id"))
        origin_branch_id = int(data.get("origin_branch_id"))
        destination_branch_id = int(data.get("destination_branch_id"))

        if not data.get("courier_id"):
            raise ValueError("Courier must be assigned")

        courier_id = int(data["courier_id"])

        # Validate amount before creating the parcel.
        raw_amount = data.get("amount", 0)

        try:
            amount = float(raw_amount)
        except (ValueError, TypeError):
            raise ValueError("Amount must be a valid number")

        if amount < 0:
            raise ValueError("Amount cannot be negative")

        if amount > 1000000:
            raise ValueError("Amount too large")

    except Exception as e:
        raise ValueError(str(e))

    # Create parcel after validation.
    parcel = Parcel(
        tracking_code=generate_tracking_code(),
        sender_id=sender_id,
        recipient_id=recipient_id,
        origin_branch_id=origin_branch_id,
        destination_branch_id=destination_branch_id,
        courier_id=courier_id,
        description=data.get("description"),
        amount=amount,
        status="Created",
    )

    db.session.add(parcel)
    db.session.flush()

    db.session.add(
        ParcelStatusHistory(
            parcel_id=parcel.id,
            status="Created",
            note="Parcel created",
        )
    )

    return parcel


def save_login_session(user):
    # Generate fresh session token
    token = generate_session_token()

    # Store token in DB
    user.session_token = token
    db.session.commit()

    # Preserve CSRF token before clearing session
    csrf_token = session.get("csrf_token")

    # Clear session to prevent fixation
    session.clear()

    # Restore CSRF token
    if csrf_token:
        session["csrf_token"] = csrf_token

    # Set fresh session data
    session["user_id"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    session["courier_id"] = user.courier_id
    session["session_token"] = token


def forbidden_response():
    if wants_json_response():
        return jsonify({"error": "Forbidden"}), 403
    return render_template("403.html"), 403


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get("user_id")
        token = session.get("session_token")

        if not user_id or not token:
            if wants_json_response():
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login"))

        user = db.session.get(User, user_id)
        if not user or user.session_token != token:
            session.clear()
            if wants_json_response():
                return jsonify({"error": "Invalid session"}), 401
            flash("Please log in again.")
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                if wants_json_response():
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for("login"))

            user = db.session.get(User, user_id)
            if not user:
                if wants_json_response():
                    return jsonify({"error": "User not found"}), 401
                flash("User not found.")
                return redirect(url_for("login"))

            if user.role != required_role:
                return forbidden_response()

            return f(*args, **kwargs)

        return decorated_function

    return decorator

def log_action(action, entity=None, entity_id=None, details=None, commit=True, fail_silently=True):
    try:
        from flask import request, session

        user_id = session.get("user_id")
        ip_address = request.remote_addr

        log = AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address
        )

        db.session.add(log)
        if commit:
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"[AuditLog Error] {e}")
        if not fail_silently:
            raise


# -----------------------------
# SEED DATA
# -----------------------------
def seed_data():
    if Branch.query.first():
        return

    b1 = Branch(name="Nairobi CBD", phone="0710000000", location="Nairobi")
    b2 = Branch(name="Westlands", phone="0720000000", location="Nairobi")
    b3 = Branch(name="Mombasa", phone="0730000000", location="Mombasa")
    db.session.add_all([b1, b2, b3])

    c1 = Courier(name="John Rider", phone="0700000001", active=True)
    c2 = Courier(name="Mike Express", phone="0700000002", active=True)
    c3 = Courier(name="Inactive Rider", phone="0700000003", active=False)
    db.session.add_all([c1, c2, c3])

    customers = []
    for i in range(1, 6):
        customers.append(Customer(name=f"Customer {i}", phone=f"079000000{i}"))
    db.session.add_all(customers)
    db.session.commit()

    parcels = []
    courier_cycle = [c1.id, c2.id, None]
    for i in range(10):
        parcels.append(
            Parcel(
                tracking_code=generate_tracking_code(),
                sender_id=customers[i % 5].id,
                recipient_id=customers[(i + 1) % 5].id,
                origin_branch_id=b1.id,
                destination_branch_id=b2.id,
                courier_id=courier_cycle[i % len(courier_cycle)],
                description=f"Package {i + 1}",
                amount=100 + i * 10,
                status=["Created", "In_Transit", "Delivered"][i % 3],
            )
        )
    db.session.add_all(parcels)
    db.session.commit()

    for parcel in parcels:
        db.session.add(
            ParcelStatusHistory(
                parcel_id=parcel.id,
                status=parcel.status,
                note="Seeded parcel",
            )
        )

    if not User.query.filter_by(username="admin").first():
        db.session.add(
            User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin",
            )
        )

    if not User.query.filter_by(username="courier1").first():
        db.session.add(
            User(
                username="courier1",
                password=generate_password_hash("1234"),
                role="staff",
                courier_id=c1.id,
            )
        )

    if not User.query.filter_by(username="courier2").first():
        db.session.add(
            User(
                username="courier2",
                password=generate_password_hash("1234"),
                role="staff",
                courier_id=c2.id,
            )
        )

    db.session.commit()

AUTH_EXEMPT_ENDPOINTS = {"login", "logout", "static", "track", "health", "debug_csrf"}


def clear_session_preserving_csrf():
    csrf_token = session.get("csrf_token")
    session.clear()
    if csrf_token:
        session["csrf_token"] = csrf_token


@app.before_request
def validate_session():
    if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
        return

    user_id = session.get("user_id")
    session_token = session.get("session_token")

    if not user_id or not session_token:
        return

    user = db.session.get(User, user_id)

    if not user or user.session_token != session_token:
        session.clear()
        return redirect(url_for("login"))

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/health")
@limiter.limit("10 per minute")
def health():
    return jsonify({"status": "OK"}), 200


@app.route("/debug/csrf", methods=["GET"])
def debug_csrf():
    token = generate_csrf()
    return jsonify({
        "csrf_token": token,
        "has_token": bool(token),
    }), 200


@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    return response


@app.before_request
def protect_html_forms():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.is_json:
        csrf.protect()


@app.shell_context_processor
def make_shell_context():
    return {
        "app": app,
        "db": db,
        "Branch": Branch,
        "Courier": Courier,
        "Customer": Customer,
        "Parcel": Parcel,
        "ParcelStatusHistory": ParcelStatusHistory,
        "User": User,
    }


@app.route("/")
@login_required
def dashboard():
    parcel_rows = [serialize_parcel(parcel) for parcel in Parcel.query.order_by(Parcel.created_at.desc()).all()]
    stats = {
        "created": sum(1 for row in parcel_rows if row["current_status"] == "Created"),
        "in_transit": sum(1 for row in parcel_rows if row["current_status"] == "In_Transit"),
        "delivered": sum(1 for row in parcel_rows if row["current_status"] == "Delivered"),
    }
    recent = sorted(parcel_rows, key=lambda row: row["updated_at"], reverse=True)[:5]
    return render_template("dashboard.html", stats=stats, recent=recent)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    data = request.get_json() if request.is_json else request.form
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        log_action(
            action="FAILED_LOGIN",
            entity="User",
            entity_id=None,
            details="Missing credentials",
        )
        if wants_json_response():
            return jsonify({"error": "Missing credentials"}), 400
        return render_template("login.html", error="Missing credentials"), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password, password):
        log_action(
            action="FAILED_LOGIN",
            entity="User",
            entity_id=user.id if user else None,
            details=f"Failed login attempt for username: {username}",
        )
        if wants_json_response():
            return jsonify({"error": "Invalid username or password"}), 401
        return render_template("login.html", error="Invalid username or password"), 401

    save_login_session(user)
    log_action(
        action="LOGIN",
        entity="User",
        entity_id=user.id,
        details=f"User {user.username} logged in",
    )

    if wants_json_response():
        return jsonify({
            "message": "Login successful",
            "user": user.username,
            "role": user.role,
        }), 200

    flash("Login successful.")
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            user.session_token = None
            db.session.commit()

    session.clear()

    if wants_json_response():
        return jsonify({"message": "Logged out successfully"}), 200

    flash("Logged out successfully.")
    return redirect(url_for("login"))


@app.route("/parcels", methods=["GET"], endpoint="parcels")
@login_required
def parcels_page():
    rows = [serialize_parcel(parcel) for parcel in Parcel.query.order_by(Parcel.created_at.desc()).all()]
    if wants_json_response():
        return jsonify(rows), 200
    return render_template("parcels.html", parcels=rows)


@app.route("/api/parcels", methods=["GET"])
@login_required
def list_parcels():
    rows = [serialize_parcel(parcel) for parcel in Parcel.query.order_by(Parcel.created_at.desc()).all()]
    return jsonify(rows), 200


@app.route("/parcels/new", methods=["GET", "POST"], endpoint="new_parcel")
@login_required
@role_required("admin")
def create_parcel():
    if request.method == "GET":
        return render_template("new_parcel.html", **parcel_form_context())

    data = request.get_json() if request.is_json else request.form

    try:
        parcel = create_parcel_record(data)

        log_action(
            action="CREATE",
            entity="Parcel",
            entity_id=parcel.id,
            details=f"Parcel {parcel.tracking_code} created"
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        if wants_json_response():
            return jsonify({"error": str(e)}), 400
        return render_template(
            "new_parcel.html",
            **parcel_form_context(error=str(e))
        ), 400

    if wants_json_response():
        return jsonify({
            "message": "Parcel created",
            "tracking_code": parcel.tracking_code,
        }), 201

    flash(f"Parcel created successfully: {parcel.tracking_code}")
    return redirect(url_for("parcel_detail", id=parcel.id))


@app.route("/parcels/<int:id>", methods=["GET"], endpoint="parcel_detail")
def parcel_detail(id):
    parcel = db.session.get(Parcel, id)
    if not parcel:
        return render_template("404.html"), 404

    payload = serialize_parcel(parcel)
    payload["history"] = serialize_parcel_history(parcel.id)
    return render_template("parcel_detail.html", p=payload)


@app.route("/parcels/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_parcel")
@login_required
@role_required("admin")
def edit_parcel(id):
    parcel = db.session.get(Parcel, id)
    if not parcel:
        return render_template("404.html"), 404

    if request.method == "POST":
        data = request.form
        try:
            parcel.sender_id = int(data.get("sender_id"))
            parcel.recipient_id = int(data.get("recipient_id"))
            parcel.origin_branch_id = int(data.get("origin_branch_id"))
            parcel.destination_branch_id = int(data.get("destination_branch_id"))
            parcel.courier_id = int(data["courier_id"]) if data.get("courier_id") else None
            parcel.description = data.get("description")
            parcel.amount = float(data.get("amount", 0) or 0)
            db.session.commit()
            flash("Parcel updated successfully.")
            return redirect(url_for("parcel_detail", id=parcel.id))
        except Exception as e:
            db.session.rollback()
            return render_template("new_parcel.html", **parcel_form_context(parcel=parcel, error=str(e))), 400

    return render_template("new_parcel.html", **parcel_form_context(parcel=parcel))


@app.route("/parcels/<int:id>/delete", methods=["POST"], endpoint="delete_parcel")
@login_required
@role_required("admin")
def delete_parcel(id):
    parcel = db.session.get(Parcel, id)
    if not parcel:
        return render_template("404.html"), 404

    # Log before deletion.
    log_action(
        action="DELETE",
        entity="Parcel",
        entity_id=parcel.id,
        details=f"Parcel {parcel.tracking_code} deleted"
    )

    # Delete related history first
    ParcelStatusHistory.query.filter_by(parcel_id=parcel.id).delete()

    # Delete parcel
    db.session.delete(parcel)

    # Commit everything
    db.session.commit()

    flash("Parcel deleted.")
    return redirect(url_for("parcels"))

@app.route("/parcels/<int:id>/status", methods=["POST"], endpoint="update_status")
@login_required
@limiter.limit("5 per minute")
def update_parcel_status(id):
    if session.get("role") not in ["admin", "staff"]:
        return forbidden_response()

    data = request.get_json() if request.is_json else request.form
    new_status = data.get("status") or data.get("new_status")
    valid_statuses = {"Created", "In_Transit", "Delivered"}

    if new_status not in valid_statuses:
        if wants_json_response():
            return jsonify({"error": "Invalid status"}), 400
        flash("Invalid status.")
        return redirect(url_for("parcel_detail", id=id))

    allowed_transitions = {
        "Created": "In_Transit",
        "In_Transit": "Delivered",
    }

    parcel = db.session.get(Parcel, id)
    if not parcel:
        if wants_json_response():
            return jsonify({"error": "Parcel not found"}), 404
        flash("Parcel not found.")
        return redirect(url_for("parcels"))

    # Staff users can only update parcels assigned to them.
    if session.get("role") == "staff":
        if parcel.courier_id != session.get("courier_id"):
            return forbidden_response()

    current_status = parcel.status
    if current_status not in allowed_transitions:
        if wants_json_response():
            return jsonify({
                "error": f"Parcel already in final state: {current_status}"
            }), 400
        flash("No further updates allowed for this parcel.")
        return redirect(url_for("parcel_detail", id=parcel.id))

    if allowed_transitions[current_status] != new_status:
        if wants_json_response():
            return jsonify({
                "error": f"Invalid transition from {current_status} to {new_status}",
            }), 400
        flash(f"Invalid transition from {current_status} to {new_status}.")
        return redirect(url_for("parcel_detail", id=parcel.id))

    previous_status = current_status
    parcel.status = new_status
    db.session.add(
        ParcelStatusHistory(
            parcel_id=parcel.id,
            status=new_status,
            note="Status updated",
        )
    )
    log_action(
        action="UPDATE_STATUS",
        entity="Parcel",
        entity_id=parcel.id,
        details=f"Parcel {parcel.tracking_code} status changed from {previous_status} to {new_status}",
        commit=False,
        fail_silently=False,
    )
    db.session.commit()

    if wants_json_response():
        return jsonify({
            "message": "Status updated",
            "new_status": new_status,
        }), 200

    flash(f"Parcel marked as {new_status}.")
    return redirect(url_for("parcel_detail", id=parcel.id))
@app.route("/quick-fix")
def quick_fix():
    user = User.query.filter_by(username="courier1").first()
    if user:
        user.courier_id = 2  # Mike Express
        db.session.commit()
        return "Courier linked ✅"
    return "User not found"


@app.route("/track", methods=["GET"], endpoint="track")
def track():
    code = (request.args.get("code") or "").strip()
    result = None

    if code:
        parcel = Parcel.query.filter_by(tracking_code=code).first()
        if parcel:
            result = serialize_parcel(parcel)

    return render_template("track.html", result=result)
@app.route("/api/track/<tracking_code>", methods=["GET"])
@limiter.limit("10 per minute")
def track_parcel(tracking_code):
    if not tracking_code.startswith("QX-"):
        return jsonify({"error": "Invalid tracking code"}), 400

    parcel = Parcel.query.filter_by(tracking_code=tracking_code).first()
    if not parcel:
        return jsonify({"error": "Parcel not found"}), 404

    return jsonify({
        "parcel": serialize_parcel(parcel),
        "history": serialize_parcel_history(parcel.id),
    }), 200


@app.route("/branches", methods=["GET"], endpoint="branches")
@login_required
def branches_page():
    rows = [serialize_branch(branch) for branch in Branch.query.order_by(Branch.created_at.desc()).all()]
    return render_template("branches.html", branches=rows)


@app.route("/branches/new", methods=["GET", "POST"], endpoint="new_branch")
@login_required
@role_required("admin")
def new_branch():
    if request.method == "POST":
        db.session.add(
            Branch(
                name=request.form.get("name"),
                phone=request.form.get("phone"),
                location=request.form.get("location"),
            )
        )
        db.session.commit()
        flash("Branch created.")
        return redirect(url_for("branches"))

    return render_template("branch_form.html", branch=None)


@app.route("/branches/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_branch")
@login_required
@role_required("admin")
def edit_branch(id):
    branch = db.session.get(Branch, id)
    if not branch:
        return render_template("404.html"), 404

    if request.method == "POST":
        branch.name = request.form.get("name")
        branch.phone = request.form.get("phone")
        branch.location = request.form.get("location")
        db.session.commit()
        flash("Branch updated.")
        return redirect(url_for("branches"))

    return render_template("branch_form.html", branch=branch)


@app.route("/branches/<int:id>/delete", methods=["POST"], endpoint="delete_branch")
@login_required
@role_required("admin")
def delete_branch(id):
    branch = db.session.get(Branch, id)
    if not branch:
        return render_template("404.html"), 404

    db.session.delete(branch)
    db.session.commit()
    flash("Branch deleted.")
    return redirect(url_for("branches"))


@app.route("/customers", methods=["GET"], endpoint="customers")
@login_required
def customers_page():
    rows = [serialize_customer(customer) for customer in Customer.query.order_by(Customer.created_at.desc()).all()]
    return render_template("customers.html", customers=rows)


@app.route("/customers/new", methods=["GET", "POST"], endpoint="new_customer")
@login_required
@role_required("admin")
def new_customer():
    if request.method == "POST":
        db.session.add(
            Customer(
                name=request.form.get("name"),
                phone=request.form.get("phone"),
            )
        )
        db.session.commit()
        flash("Customer created.")
        return redirect(url_for("customers"))

    return render_template("customer_form.html", customer=None)


@app.route("/customers/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_customer")
@login_required
@role_required("admin")
def edit_customer(id):
    customer = db.session.get(Customer, id)
    if not customer:
        return render_template("404.html"), 404

    if request.method == "POST":
        customer.name = request.form.get("name")
        customer.phone = request.form.get("phone")
        db.session.commit()
        flash("Customer updated.")
        return redirect(url_for("customers"))

    return render_template("customer_form.html", customer=customer)


@app.route("/customers/<int:id>/delete", methods=["POST"], endpoint="delete_customer")
@login_required
@role_required("admin")
def delete_customer(id):
    customer = db.session.get(Customer, id)
    if not customer:
        return render_template("404.html"), 404

    db.session.delete(customer)
    db.session.commit()
    flash("Customer deleted.")
    return redirect(url_for("customers"))


@app.route("/couriers", methods=["GET"], endpoint="couriers")
@login_required
def couriers_page():
    rows = [serialize_courier(courier) for courier in Courier.query.order_by(Courier.created_at.desc()).all()]
    return render_template("couriers.html", couriers=rows)


@app.route("/couriers/new", methods=["POST"], endpoint="new_courier")
@login_required
@role_required("admin")
def new_courier():
    db.session.add(
        Courier(
            name=request.form.get("name"),
            phone=request.form.get("phone"),
            active=request.form.get("active", "1") == "1",
        )
    )
    db.session.commit()
    flash("Courier created.")
    return redirect(url_for("couriers"))


@app.route("/couriers/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_courier")
@login_required
@role_required("admin")
def edit_courier(id):
    courier = db.session.get(Courier, id)
    if not courier:
        return render_template("404.html"), 404

    if request.method == "POST":
        courier.name = request.form.get("name")
        courier.phone = request.form.get("phone")
        courier.active = request.form.get("active", "1") == "1"
        db.session.commit()
        flash("Courier updated.")
        return redirect(url_for("couriers"))

    return render_template("courier_form.html", courier=courier)


@app.route("/couriers/<int:id>/delete", methods=["POST"], endpoint="delete_courier")
@login_required
@role_required("admin")
def delete_courier(id):
    courier = db.session.get(Courier, id)
    if not courier:
        return render_template("404.html"), 404

    db.session.delete(courier)
    db.session.commit()
    flash("Courier deleted.")
    return redirect(url_for("couriers"))


@app.route("/reports", methods=["GET"], endpoint="reports")
@login_required
def reports_page():
    results = [serialize_parcel(parcel) for parcel in Parcel.query.order_by(Parcel.created_at.desc()).all()]

    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    status = (request.args.get("status") or "").strip()
    search = (request.args.get("q") or "").strip().lower()

    if start_date:
        results = [item for item in results if item["created_at"][:10] >= start_date]
    if end_date:
        results = [item for item in results if item["created_at"][:10] <= end_date]
    if status:
        results = [item for item in results if item["current_status"] == status]
    if search:
        results = [
            item
            for item in results
            if search in item["tracking_code"].lower()
            or search in item["sender_name"].lower()
            or search in item["recipient_name"].lower()
            or search in item["origin_branch_name"].lower()
            or search in item["destination_branch_name"].lower()
        ]

    if request.args.get("export") == "csv":
        lines = [
            "tracking_code,sender,recipient,origin_branch,destination_branch,courier,amount,status,created_at,updated_at"
        ]
        for item in results:
            lines.append(
                ",".join([
                    item["tracking_code"],
                    item["sender_name"],
                    item["recipient_name"],
                    item["origin_branch_name"],
                    item["destination_branch_name"],
                    item["courier_name"] or "",
                    f"{item['amount']:.2f}",
                    item["current_status"],
                    item["created_at"],
                    item["updated_at"],
                ])
            )
        response = make_response("\n".join(lines))
        response.headers["Content-Type"] = "text/csv"
        response.headers["Content-Disposition"] = "attachment; filename=reports.csv"
        return response

    return render_template("reports.html", results=results)



@app.route("/test-status", methods=["POST"])
@login_required
def test_status():
    user_id = session.get("user_id")
    token = session.get("session_token")
    if not user_id or not token:
        return jsonify({"error": "Unauthorized"}), 401

    user = db.session.get(User, user_id)
    if not user or user.session_token != token:
        session.clear()
        return jsonify({"error": "Invalid session"}), 401

    # Simulate current status (from DB)
    current_status = "Created"

    # Simulate attacker trying to skip steps
    data = request.get_json()
    new_status = data.get("status") if data else None

    VALID_STATUSES = {"Created", "In_Transit", "Delivered"}

    if new_status not in VALID_STATUSES:
        return jsonify({"error": "Invalid status"}), 400

    # Define allowed transitions
    allowed_transitions = {
        "Created": ["In_Transit"],
        "In_Transit": ["Delivered"],
        "Delivered": []
    }

    # Check if transition is allowed
    if new_status not in allowed_transitions[current_status]:
        return jsonify({
            "error": f"Invalid transition from {current_status} to {new_status}"
        }), 400

    return jsonify({
        "message": "Status updated",
        "new_status": new_status
    }), 200





@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    if wants_json_response():
        return jsonify({"error": error.description}), 400
    flash("Your session expired or the form token is missing. Please try again.")
    return redirect(request.referrer or url_for("login"))


# -----------------------------
# INIT DB
# -----------------------------
with app.app_context():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    db.create_all()
    seed_data()
    
   


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=False)
