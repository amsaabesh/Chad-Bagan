import io
import os
import re
import secrets
import smtplib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import UniqueConstraint, func, or_
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"

database_url = os.getenv("DATABASE_URL", "sqlite:///chad_bagan.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "এই পেজটি দেখতে আগে লগইন করুন।"

CONTACT_INFO = "Designed By: Ahmed Mahir Shoaib. If you need any help, contact with us at mahiraabesh@gmail.com"

CATEGORIES = {
    "গাছ": ["ফল গাছ", "ফুল গাছ", "শোভা বর্ধক", "ওষধি", "সবজি"],
    "সার": ["জৈব সার", "রাসায়নিক সার", "তরল সার"],
    "মাছ": ["পোনা", "মাছের খাদ্য", "জলজ উপকরণ"],
    "চাষাবাদ আনুষাঙ্গিক": ["বীজ", "টব", "যন্ত্রপাতি", "সেচ উপকরণ"],
    "অন্যান্য": ["অন্যান্য"],
}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(40), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    admin_approved = db.Column(db.Boolean, nullable=False, default=False)
    is_banned = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    cart_items = db.relationship("CartItem", backref="user", cascade="all, delete-orphan", lazy=True)
    orders = db.relationship("Order", backref="user", lazy=True)

    @property
    def is_admin(self):
        return self.role == "admin" and self.admin_approved and not self.is_banned


class Blacklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    phone = db.Column(db.String(40), unique=True, nullable=True, index=True)
    reason = db.Column(db.String(255), nullable=True)
    banned_user_id = db.Column(db.Integer, nullable=True)
    created_by_admin_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class AdminNotification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    related_user_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    category = db.Column(db.String(80), nullable=False, index=True)
    subcategory = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(db.Text, nullable=True)
    image_data = db.Column(db.LargeBinary, nullable=False)
    image_mimetype = db.Column(db.String(60), nullable=False, default="image/jpeg")
    is_visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    product = db.relationship("Product")
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(80), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    delivery_address = db.Column(db.Text, nullable=False)
    customer_note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan", lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, nullable=True)
    product_code = db.Column(db.String(80), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_globals():
    cart_count = 0
    unread_count = 0
    if current_user.is_authenticated:
        if current_user.role == "user":
            cart_count = db.session.query(func.coalesce(func.sum(CartItem.quantity), 0)).filter_by(user_id=current_user.id).scalar() or 0
        if current_user.is_admin:
            unread_count = AdminNotification.query.filter_by(recipient_admin_id=current_user.id, is_read=False).count()
    return {
        "CATEGORIES": CATEGORIES,
        "CONTACT_INFO": CONTACT_INFO,
        "cart_count": int(cart_count),
        "unread_count": unread_count,
    }


@app.before_request
def kick_banned_sessions():
    if current_user.is_authenticated and current_user.is_banned:
        if request.endpoint not in {"banned", "logout", "static"}:
            logout_user()
            return redirect(url_for("banned"))


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login", mode="admin"))
        if not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


def user_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login", mode="user"))
        if current_user.role != "user" or current_user.is_banned:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone(value):
    value = (value or "").strip()
    prefix = "+" if value.startswith("+") else ""
    digits = re.sub(r"\D", "", value)
    return prefix + digits


def strong_password(password):
    return len(password or "") >= 8


def registration_conflict(email, phone):
    existing = User.query.filter(
        User.is_banned.is_(False),
        or_(func.lower(User.email) == email, User.phone == phone),
    ).first()
    if existing:
        if normalize_email(existing.email) == email:
            return "এই ইমেইল দিয়ে ইতোমধ্যে একটি সক্রিয়/পেন্ডিং একাউন্ট আছে।"
        return "এই ফোন নাম্বার দিয়ে ইতোমধ্যে একটি সক্রিয়/পেন্ডিং একাউন্ট আছে।"

    blocked = Blacklist.query.filter(or_(func.lower(Blacklist.email) == email, Blacklist.phone == phone)).first()
    if blocked:
        return "এই ইমেইল বা ফোন নাম্বারটি ব্যান লিস্টে আছে। অ্যাডমিনের সাথে যোগাযোগ করুন।"
    return None


def send_email(to_address, subject, body):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM") or user
    if not all([host, user, password, mail_from, to_address]):
        app.logger.warning("SMTP is not configured. Email skipped: %s -> %s", subject, to_address)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = to_address
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        app.logger.exception("Email sending failed: %s", exc)
        return False


def notify_admins(title, message, related_user_id=None, email_subject=None):
    admins = User.query.filter_by(role="admin", admin_approved=True, is_banned=False).all()
    for admin in admins:
        db.session.add(AdminNotification(
            recipient_admin_id=admin.id,
            title=title,
            message=message,
            related_user_id=related_user_id,
        ))
    db.session.commit()
    for admin in admins:
        send_email(admin.email, email_subject or title, message)


def validate_product_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None, "৩০০ x ৩০০ পিক্সেলের একটি ছবি দিন।"
    raw = file_storage.read()
    if len(raw) > 3 * 1024 * 1024:
        return None, None, "ছবির সাইজ ৩ MB-এর বেশি হতে পারবে না।"
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
        if img.size != (300, 300):
            return None, None, "ছবিটি অবশ্যই ঠিক ৩০০ x ৩০০ পিক্সেল হতে হবে।"
        if img.format not in {"JPEG", "PNG", "WEBP"}:
            return None, None, "শুধু JPG, PNG বা WEBP ছবি গ্রহণযোগ্য।"
        mimetype = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[img.format]
        return raw, mimetype, None
    except Exception:
        return None, None, "সঠিক ইমেজ ফাইল দিন।"


def validate_category(category, subcategory):
    return category in CATEGORIES and subcategory in CATEGORIES[category]


def money(value):
    return f"{Decimal(value):,.2f}"


@app.template_filter("money")
def money_filter(value):
    return money(value)


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard" if current_user.is_admin else "home"))
    return redirect(url_for("login"))


@app.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard" if current_user.is_admin else "home"))
    mode = request.args.get("mode", "user")
    if mode not in {"user", "admin"}:
        mode = "user"
    return render_template("login.html", mode=mode)


def process_login(role):
    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    if not identifier or not password:
        flash("ইমেইল/ফোন এবং পাসওয়ার্ড দিন।", "danger")
        return redirect(url_for("login", mode=role))

    email_key = normalize_email(identifier)
    phone_key = normalize_phone(identifier)
    candidates = User.query.filter(
        User.role == role,
        or_(func.lower(User.email) == email_key, User.phone == phone_key),
    ).order_by(User.is_banned.asc(), User.created_at.desc()).all()

    matched = None
    for account in candidates:
        if check_password_hash(account.password_hash, password):
            matched = account
            break

    if not matched:
        flash("লগইন তথ্য সঠিক নয়।", "danger")
        return redirect(url_for("login", mode=role))
    if matched.is_banned:
        return redirect(url_for("banned"))
    if role == "admin" and not matched.admin_approved:
        flash("আপনার অ্যাডমিন রেজিস্ট্রেশন এখনো অনুমোদনের অপেক্ষায় আছে।", "warning")
        return redirect(url_for("login", mode="admin"))

    login_user(matched, remember=True)
    return redirect(url_for("admin_dashboard" if role == "admin" else "home"))


@app.post("/login/user")
def login_user_route():
    return process_login("user")


@app.post("/login/admin")
def login_admin_route():
    return process_login("admin")


@app.route("/register/user", methods=["GET", "POST"])
def register_user():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = normalize_email(request.form.get("email"))
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not all([name, email, phone, password, confirm]):
            flash("সব ঘর পূরণ করুন।", "danger")
        elif "@" not in email:
            flash("সঠিক ইমেইল দিন।", "danger")
        elif len(phone) < 8:
            flash("সঠিক ফোন নাম্বার দিন।", "danger")
        elif not strong_password(password):
            flash("পাসওয়ার্ড কমপক্ষে ৮ অক্ষরের হতে হবে।", "danger")
        elif password != confirm:
            flash("দুইটি পাসওয়ার্ড মিলছে না।", "danger")
        else:
            conflict = registration_conflict(email, phone)
            if conflict:
                flash(conflict, "danger")
            else:
                db.session.add(User(
                    name=name,
                    email=email,
                    phone=phone,
                    password_hash=generate_password_hash(password),
                    role="user",
                    admin_approved=False,
                ))
                db.session.commit()
                flash("রেজিস্ট্রেশন সফল। এখন লগইন করুন।", "success")
                return redirect(url_for("login", mode="user"))
    return render_template("register.html", account_type="user")


@app.route("/register/admin", methods=["GET", "POST"])
def register_admin():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = normalize_email(request.form.get("email"))
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not all([name, email, phone, password, confirm]):
            flash("সব ঘর পূরণ করুন।", "danger")
        elif "@" not in email:
            flash("সঠিক ইমেইল দিন।", "danger")
        elif len(phone) < 8:
            flash("সঠিক ফোন নাম্বার দিন।", "danger")
        elif not strong_password(password):
            flash("পাসওয়ার্ড কমপক্ষে ৮ অক্ষরের হতে হবে।", "danger")
        elif password != confirm:
            flash("দুইটি পাসওয়ার্ড মিলছে না।", "danger")
        else:
            conflict = registration_conflict(email, phone)
            if conflict:
                flash(conflict, "danger")
            else:
                first_admin = User.query.filter_by(role="admin").count() == 0
                admin = User(
                    name=name,
                    email=email,
                    phone=phone,
                    password_hash=generate_password_hash(password),
                    role="admin",
                    admin_approved=first_admin,
                )
                db.session.add(admin)
                db.session.commit()
                if first_admin:
                    flash("প্রথম অ্যাডমিন একাউন্ট সফলভাবে তৈরি হয়েছে। এখন লগইন করুন।", "success")
                else:
                    notify_admins(
                        "নতুন অ্যাডমিন রেজিস্ট্রেশন",
                        f"{name} ({email}, {phone}) অ্যাডমিন হিসেবে রেজিস্ট্রেশন করেছে। ড্যাশবোর্ড থেকে অনুমোদন করুন।",
                        related_user_id=admin.id,
                        email_subject="ছাদ বাগান - নতুন অ্যাডমিন রেজিস্ট্রেশন",
                    )
                    flash("রেজিস্ট্রেশন জমা হয়েছে। বিদ্যমান অ্যাডমিনদের নোটিফিকেশন ও ইমেইল পাঠানো হয়েছে। অনুমোদনের পর লগইন করতে পারবেন।", "warning")
                return redirect(url_for("login", mode="admin"))
    return render_template("register.html", account_type="admin")


@app.route("/banned")
def banned():
    return render_template("banned.html")


@app.route("/logout")
def logout():
    logout_user()
    flash("আপনি লগআউট করেছেন।", "success")
    return redirect(url_for("login"))


@app.route("/home")
@user_required
def home():
    category = request.args.get("category")
    subcategory = request.args.get("subcategory")
    q = (request.args.get("q") or "").strip()
    products = Product.query.filter_by(is_visible=True)
    if category in CATEGORIES:
        products = products.filter_by(category=category)
    if category in CATEGORIES and subcategory in CATEGORIES[category]:
        products = products.filter_by(subcategory=subcategory)
    if q:
        products = products.filter(or_(Product.name.ilike(f"%{q}%"), Product.product_code.ilike(f"%{q}%")))
    products = products.order_by(Product.created_at.desc()).all()
    return render_template("home.html", products=products, category=category, subcategory=subcategory, q=q)


@app.route("/product/<int:product_id>")
@user_required
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_visible:
        abort(404)
    return render_template("product_detail.html", product=product)


@app.route("/product-image/<int:product_id>")
def product_image(product_id):
    product = Product.query.get_or_404(product_id)
    response = make_response(product.image_data)
    response.headers["Content-Type"] = product.image_mimetype
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.post("/cart/add/<int:product_id>")
@user_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_visible:
        abort(404)
    try:
        quantity = max(1, min(int(request.form.get("quantity", 1)), 99))
    except ValueError:
        quantity = 1
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product.id).first()
    if item:
        item.quantity = min(item.quantity + quantity, 99)
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=product.id, quantity=quantity))
    db.session.commit()
    flash("পণ্যটি কার্টে যোগ হয়েছে।", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/cart", methods=["GET", "POST"])
@user_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if request.method == "POST":
        for item in items:
            raw = request.form.get(f"qty_{item.id}", str(item.quantity))
            try:
                qty = int(raw)
            except ValueError:
                qty = item.quantity
            if qty <= 0:
                db.session.delete(item)
            else:
                item.quantity = min(qty, 99)
        db.session.commit()
        flash("কার্ট আপডেট হয়েছে।", "success")
        return redirect(url_for("cart"))
    total = sum((Decimal(item.product.price) * item.quantity for item in items), Decimal("0.00"))
    return render_template("cart.html", items=items, total=total)


@app.post("/cart/remove/<int:item_id>")
@user_required
def remove_from_cart(item_id):
    item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("পণ্যটি কার্ট থেকে সরানো হয়েছে।", "success")
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
@user_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not items:
        flash("আপনার কার্ট খালি।", "warning")
        return redirect(url_for("home"))
    total = sum((Decimal(item.product.price) * item.quantity for item in items), Decimal("0.00"))

    if request.method == "POST":
        address = (request.form.get("delivery_address") or "").strip()
        note = (request.form.get("customer_note") or "").strip()
        if len(address) < 8:
            flash("ডেলিভারি ঠিকানা লিখুন।", "danger")
            return render_template("checkout.html", items=items, total=total)

        invoice_no = f"HB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.randbelow(9000) + 1000}"
        order = Order(
            invoice_no=invoice_no,
            user_id=current_user.id,
            total_amount=total,
            delivery_address=address,
            customer_note=note or None,
        )
        db.session.add(order)
        db.session.flush()
        for item in items:
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=item.product.id,
                product_code=item.product.product_code,
                product_name=item.product.name,
                unit_price=item.product.price,
                quantity=item.quantity,
            ))
            db.session.delete(item)
        db.session.commit()

        notify_admins(
            "নতুন অর্ডার",
            f"ইনভয়েস {invoice_no} - {current_user.name} মোট ৳{money(total)} টাকার অর্ডার করেছে।",
            related_user_id=current_user.id,
        )
        flash("অর্ডার সম্পন্ন হয়েছে এবং ইনভয়েস তৈরি হয়েছে।", "success")
        return redirect(url_for("invoice", order_id=order.id))

    return render_template("checkout.html", items=items, total=total)


@app.route("/orders")
@user_required
def orders():
    rows = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("orders.html", orders=rows)


@app.route("/invoice/<int:order_id>")
def invoice(order_id):
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    order = Order.query.get_or_404(order_id)
    if not (current_user.is_admin or order.user_id == current_user.id):
        abort(403)
    return render_template("invoice.html", order=order)


def ascii_safe(text):
    return (text or "").encode("ascii", "ignore").decode("ascii") or "Item"


@app.route("/invoice/<int:order_id>/pdf")
def invoice_pdf(order_id):
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    order = Order.query.get_or_404(order_id)
    if not (current_user.is_admin or order.user_id == current_user.id):
        abort(403)

    buffer = io.BytesIO()
    font_name = "Helvetica"
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            font_name = "DejaVuSans"
        except Exception:
            font_name = "Helvetica"

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    for style_name in ["Title", "Heading2", "Normal"]:
        styles[style_name].fontName = font_name
    story = [
        Paragraph("Chad Bagan - Invoice", styles["Title"]),
        Spacer(1, 6),
        Paragraph(f"Invoice: {order.invoice_no}", styles["Normal"]),
        Paragraph(f"Customer: {order.user.name}", styles["Normal"]),
        Paragraph(f"Email: {order.user.email}", styles["Normal"]),
        Paragraph(f"Phone: {order.user.phone}", styles["Normal"]),
        Paragraph(f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]),
        Spacer(1, 10),
    ]
    data = [["Product", "Code", "Qty", "Unit Price", "Subtotal"]]
    for item in order.items:
        name = item.product_name if font_name == "DejaVuSans" else ascii_safe(item.product_name)
        subtotal = Decimal(item.unit_price) * item.quantity
        data.append([name, item.product_code, str(item.quantity), f"Tk {money(item.unit_price)}", f"Tk {money(subtotal)}"])
    data.append(["", "", "", "Total", f"Tk {money(order.total_amount)}"])
    table = Table(data, colWidths=[55*mm, 30*mm, 15*mm, 30*mm, 35*mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#dff3e6")),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("ALIGN", (2,1), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("TOPPADDING", (0,0), (-1,0), 8),
    ]))
    story += [table, Spacer(1, 12), Paragraph("Thank you for shopping with Chad Bagan.", styles["Normal"])]
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{order.invoice_no}.pdf", mimetype="application/pdf")


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "users": User.query.filter_by(role="user", is_banned=False).count(),
        "products": Product.query.filter_by(is_visible=True).count(),
        "orders": Order.query.count(),
        "pending_admins": User.query.filter_by(role="admin", admin_approved=False, is_banned=False).count(),
        "blacklist": Blacklist.query.count(),
    }
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", stats=stats, recent_orders=recent_orders)


@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def admin_product_add():
    if request.method == "POST":
        code = (request.form.get("product_code") or "").strip()
        name = (request.form.get("name") or "").strip()
        category = request.form.get("category") or ""
        subcategory = request.form.get("subcategory") or ""
        details = (request.form.get("details") or "").strip()
        try:
            price = Decimal(request.form.get("price") or "0").quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            price = Decimal("-1")

        image_data, image_mimetype, image_error = validate_product_image(request.files.get("image"))
        error = None
        if not code or not name:
            error = "পণ্যের নাম ও ইউনিক আইডি দিন।"
        elif Product.query.filter_by(product_code=code).first():
            error = "এই প্রডাক্ট আইডি ইতোমধ্যে ব্যবহার হয়েছে।"
        elif price < 0:
            error = "সঠিক দাম দিন।"
        elif not validate_category(category, subcategory):
            error = "সঠিক ক্যাটাগরি ও সাব-ক্যাটাগরি নির্বাচন করুন।"
        elif image_error:
            error = image_error

        if error:
            flash(error, "danger")
        else:
            db.session.add(Product(
                product_code=code,
                name=name,
                price=price,
                category=category,
                subcategory=subcategory,
                details=details or None,
                image_data=image_data,
                image_mimetype=image_mimetype,
            ))
            db.session.commit()
            flash("পণ্য সফলভাবে যোগ হয়েছে।", "success")
            return redirect(url_for("admin_products"))
    return render_template("admin/product_form.html", product=None)


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        code = (request.form.get("product_code") or "").strip()
        name = (request.form.get("name") or "").strip()
        category = request.form.get("category") or ""
        subcategory = request.form.get("subcategory") or ""
        details = (request.form.get("details") or "").strip()
        try:
            price = Decimal(request.form.get("price") or "0").quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            price = Decimal("-1")

        duplicate = Product.query.filter(Product.product_code == code, Product.id != product.id).first()
        error = None
        if not code or not name:
            error = "পণ্যের নাম ও ইউনিক আইডি দিন।"
        elif duplicate:
            error = "এই প্রডাক্ট আইডি অন্য পণ্যে ব্যবহার হয়েছে।"
        elif price < 0:
            error = "সঠিক দাম দিন।"
        elif not validate_category(category, subcategory):
            error = "সঠিক ক্যাটাগরি ও সাব-ক্যাটাগরি নির্বাচন করুন।"

        new_image = request.files.get("image")
        image_data = image_mimetype = None
        if not error and new_image and new_image.filename:
            image_data, image_mimetype, image_error = validate_product_image(new_image)
            if image_error:
                error = image_error

        if error:
            flash(error, "danger")
        else:
            product.product_code = code
            product.name = name
            product.price = price
            product.category = category
            product.subcategory = subcategory
            product.details = details or None
            if image_data:
                product.image_data = image_data
                product.image_mimetype = image_mimetype
            db.session.commit()
            flash("পণ্য আপডেট হয়েছে।", "success")
            return redirect(url_for("admin_products"))
    return render_template("admin/product_form.html", product=product)


@app.post("/admin/products/<int:product_id>/toggle")
@admin_required
def admin_product_toggle(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_visible = not product.is_visible
    db.session.commit()
    flash("পণ্যের ভিজিবিলিটি আপডেট হয়েছে।", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@app.post("/admin/users/<int:user_id>/ban")
@admin_required
def admin_ban_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("নিজের একাউন্ট ব্যান করা যাবে না।", "danger")
        return redirect(url_for("admin_users"))
    if user.role == "admin" and user.admin_approved:
        active_admins = User.query.filter_by(role="admin", admin_approved=True, is_banned=False).count()
        if active_admins <= 1:
            flash("শেষ সক্রিয় অ্যাডমিনকে ব্যান করা যাবে না।", "danger")
            return redirect(url_for("admin_users"))
    if user.is_banned:
        flash("এই একাউন্ট ইতোমধ্যে ব্যান করা।", "warning")
        return redirect(url_for("admin_users"))

    reason = (request.form.get("reason") or "নীতিমালা ভঙ্গ").strip()
    user.is_banned = True
    existing = Blacklist.query.filter(or_(func.lower(Blacklist.email) == normalize_email(user.email), Blacklist.phone == user.phone)).first()
    if not existing:
        db.session.add(Blacklist(
            email=normalize_email(user.email),
            phone=user.phone,
            reason=reason,
            banned_user_id=user.id,
            created_by_admin_id=current_user.id,
        ))
    db.session.commit()
    flash("একাউন্ট ব্যান করা হয়েছে এবং ইমেইল/ফোন ব্যান লিস্টে যোগ হয়েছে।", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/blacklist")
@admin_required
def admin_blacklist():
    entries = Blacklist.query.order_by(Blacklist.created_at.desc()).all()
    return render_template("admin/blacklist.html", entries=entries)


@app.post("/admin/blacklist/<int:entry_id>/delete")
@admin_required
def admin_blacklist_delete(entry_id):
    entry = Blacklist.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash("ইমেইল/ফোন ব্যান লিস্ট থেকে মুছে ফেলা হয়েছে। এখন নতুন একাউন্টে এটি আবার ব্যবহার করা যাবে।", "success")
    return redirect(url_for("admin_blacklist"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    rows = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin/orders.html", orders=rows)


@app.post("/admin/orders/<int:order_id>/status")
@admin_required
def admin_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    status = request.form.get("status") or "Pending"
    allowed = {"Pending", "Confirmed", "Processing", "Shipped", "Delivered", "Cancelled"}
    if status not in allowed:
        abort(400)
    order.status = status
    db.session.commit()
    flash("অর্ডারের স্ট্যাটাস আপডেট হয়েছে।", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/notifications")
@admin_required
def admin_notifications():
    notifications = AdminNotification.query.filter_by(recipient_admin_id=current_user.id).order_by(AdminNotification.created_at.desc()).all()
    pending_admins = User.query.filter_by(role="admin", admin_approved=False, is_banned=False).order_by(User.created_at.desc()).all()
    return render_template("admin/notifications.html", notifications=notifications, pending_admins=pending_admins)


@app.post("/admin/notifications/<int:notification_id>/read")
@admin_required
def admin_notification_read(notification_id):
    n = AdminNotification.query.filter_by(id=notification_id, recipient_admin_id=current_user.id).first_or_404()
    n.is_read = True
    db.session.commit()
    return redirect(url_for("admin_notifications"))


@app.post("/admin/admins/<int:user_id>/approve")
@admin_required
def admin_approve_admin(user_id):
    admin = User.query.filter_by(id=user_id, role="admin", admin_approved=False, is_banned=False).first_or_404()
    admin.admin_approved = True
    db.session.commit()
    send_email(admin.email, "ছাদ বাগান - অ্যাডমিন একাউন্ট অনুমোদিত", "আপনার অ্যাডমিন একাউন্ট অনুমোদিত হয়েছে। এখন আপনি লগইন করতে পারবেন।")
    flash("নতুন অ্যাডমিন অনুমোদিত হয়েছে।", "success")
    return redirect(url_for("admin_notifications"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("403.html"), 403


@app.errorhandler(413)
def too_large(_error):
    flash("ফাইল খুব বড়। সর্বোচ্চ ৪ MB আপলোড করুন।", "danger")
    return redirect(request.referrer or url_for("index"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
