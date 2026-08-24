from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import anthropic

import os
from datetime import datetime, timedelta


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

# ------------------------------------------------------------
# SECRET_KEY must be set as a real environment variable when
# this app is deployed on the internet. The fallback below is
# only for local testing on your own machine.
# ------------------------------------------------------------

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "the-peniers-change-this-secret"
)

_database_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///database.db"
)

# Some hosts (e.g. Render, Heroku) hand out "postgres://" URLs,
# but SQLAlchemy needs "postgresql://".
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = _database_url

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Cookies should only travel over HTTPS once the site is live.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "FLASK_ENV"
) == "production"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

MAX_UPLOAD_MB = 5
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

db = SQLAlchemy(app)


# ============================================================
# DATABASE MODELS
# ============================================================

class Customer(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    fullname = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    phone = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    address = db.Column(
        db.String(250),
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    # --------------------------------------------------------
    # SAVED AUTO-DEBIT ACCOUNT
    # A customer can save one bank account here. If it's set,
    # checkout offers "Auto-Debit" as a payment option, which
    # marks the order as Paid immediately instead of Unpaid.
    # --------------------------------------------------------

    bank_name = db.Column(
        db.String(100),
        nullable=True
    )

    account_name = db.Column(
        db.String(120),
        nullable=True
    )

    account_number = db.Column(
        db.String(20),
        nullable=True
    )

    auto_debit_enabled = db.Column(
        db.Boolean,
        default=False
    )

    orders = db.relationship(
        "Order",
        backref="customer",
        lazy=True
    )

    def has_saved_account(self):

        return bool(
            self.account_number
        )

    def masked_account_number(self):

        if not self.account_number:
            return ""

        last4 = self.account_number[-4:]

        return "*" * (
            len(self.account_number) - 4
        ) + last4


class Book(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    author = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    price = db.Column(
        db.Float,
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=0
    )

    image = db.Column(
        db.String(300),
        nullable=True
    )

    category = db.Column(
        db.String(50),
        nullable=True
    )

    # Optional "was" price. When set higher than price, the
    # storefront shows a strike-through price and a % off badge.
    original_price = db.Column(
        db.Float,
        nullable=True
    )

    def discount_percent(self):

        if not self.original_price:
            return 0

        if self.original_price <= self.price:
            return 0

        discount = (
            (self.original_price - self.price)
            / self.original_price
            * 100
        )

        return int(discount)


class Order(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )

    total = db.Column(
        db.Float,
        nullable=False
    )

    status = db.Column(
        db.String(50),
        default="Pending"
    )

    payment_status = db.Column(
        db.String(50),
        default="Unpaid"
    )

    payment_method = db.Column(
        db.String(100),
        nullable=True
    )

    # Human-friendly reference like TPB-NG-20260820-0007
    # (store code - country - order date - daily sequence number)
    order_number = db.Column(
        db.String(40),
        unique=True,
        nullable=True
    )

    delivery_address = db.Column(
        db.String(250),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    items = db.relationship(
        "OrderItem",
        backref="order",
        lazy=True,
        cascade="all, delete-orphan"
    )


class OrderItem(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id"),
        nullable=False
    )

    book_id = db.Column(
        db.Integer,
        db.ForeignKey("book.id"),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    price = db.Column(
        db.Float,
        nullable=False
    )

    book = db.relationship(
        "Book"
    )


class ChatMessage(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=True
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    ai_response = db.Column(
        db.Text,
        nullable=True
    )

    is_complaint = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    customer = db.relationship(
        "Customer"
    )


class Comment(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    book_id = db.Column(
        db.Integer,
        db.ForeignKey("book.id"),
        nullable=False
    )

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )

    content = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    book = db.relationship(
        "Book",
        backref=db.backref(
            "comments",
            lazy=True,
            order_by="Comment.created_at.desc()"
        )
    )

    customer = db.relationship(
        "Customer"
    )


class Feedback(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=True
    )

    feedback_type = db.Column(
        db.String(20),
        default="Comment"
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    customer = db.relationship(
        "Customer"
    )


# ============================================================
# DATABASE SETUP
# ============================================================

with app.app_context():
    db.create_all()


# ------------------------------------------------------------
# Warn loudly if this is running with default secrets in an
# environment that looks like production. This does not stop
# the app from starting, it just reminds you to set env vars.
# ------------------------------------------------------------

if os.environ.get("FLASK_ENV") == "production":

    if app.config["SECRET_KEY"] == "the-peniers-change-this-secret":
        print(
            "WARNING: SECRET_KEY env var is not set. "
            "Set a random SECRET_KEY before going live."
        )

    if os.environ.get("ADMIN_PASSWORD") is None:
        print(
            "WARNING: ADMIN_PASSWORD env var is not set. "
            "The default admin password is NOT safe for a public site."
        )


# ============================================================
# CUSTOMER HELPERS
# ============================================================

def customer_logged_in():

    return "customer_id" in session


def get_current_customer():

    if "customer_id" not in session:
        return None

    return db.session.get(
        Customer,
        session["customer_id"]
    )


def admin_logged_in():

    return session.get("admin_logged_in") is True


def sales_logged_in():

    return (
        session.get("sales_logged_in") is True
        or admin_logged_in()
    )


# ============================================================
# ORDER NUMBER GENERATOR
# ============================================================

STORE_CODE = "TPB"
STORE_COUNTRY_CODE = "NG"


def generate_order_number():

    today_str = datetime.utcnow().strftime("%Y%m%d")

    day_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    orders_today = Order.query.filter(
        Order.created_at >= day_start
    ).count()

    sequence = orders_today + 1

    return (
        f"{STORE_CODE}-{STORE_COUNTRY_CODE}-"
        f"{today_str}-{sequence:04d}"
    )


# ============================================================
# AI SUPPORT CHAT
# ============================================================
#
# This is scoped on purpose: it only knows and talks about
# The Peniers Bookstore (delivery, returns, categories, contact,
# order help). It's instructed to decline anything unrelated and
# steer back to the store, rather than acting as a general-purpose
# assistant.
#
# EDIT THE BLOCK BELOW to match your store's real details.
# ============================================================

STORE_INFO = """
Store name: The Peniers Bookstore
Location: Lagos, Nigeria
Delivery: Free delivery on orders over ₦10,000. Delivery within Lagos \
usually takes 1-3 business days; other states 3-7 business days.
Returns: Books can be returned within 7 days of delivery if unused and \
undamaged. Contact support to start a return.
Payment methods: Auto-Debit (saved bank account), Card, Bank Transfer, \
Cash on Delivery.
Categories: Novel, Education, Motivation, Business, Religion, Children.
Contact: support@thepeniers.com
Order tracking: customers can see their orders and status under \
"My Orders" after logging in.
"""

CHAT_SYSTEM_PROMPT = f"""You are the customer support assistant for The \
Peniers Bookstore, an online bookstore. You ONLY answer questions about \
this store: its books, categories, delivery, returns, payment methods, \
order help, and how to use the site. You also help customers who want to \
complain or report a problem with an order.

Store details you can share with customers:
{STORE_INFO}

Rules:
- If someone asks about anything unrelated to this store (general \
knowledge, coding help, other companies, etc.), politely decline and \
steer the conversation back to how you can help with The Peniers \
Bookstore.
- Keep answers short and friendly, a few sentences at most.
- Never invent store details that are not listed above - if you don't \
know something specific (e.g. the status of one exact order), tell the \
customer to check "My Orders" or contact support@thepeniers.com.

Format your reply EXACTLY like this, with nothing before the first line:
COMPLAINT: yes
or
COMPLAINT: no
(then a blank line, then your reply to the customer on the next lines)

Mark COMPLAINT: yes only if the customer is reporting a problem, \
expressing dissatisfaction, or asking for a refund/compensation.
"""


def get_anthropic_client():

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return None

    return anthropic.Anthropic(
        api_key=api_key
    )


@app.route(
    "/api/chat",
    methods=["POST"]
)
def api_chat():

    client = get_anthropic_client()

    if client is None:

        return jsonify({
            "reply": (
                "Chat support isn't set up yet. Please email "
                "support@thepeniers.com."
            )
        }), 200

    data = request.get_json(
        silent=True
    ) or {}

    user_message = (
        data.get("message", "")
    ).strip()

    if not user_message:

        return jsonify({
            "error": "Message is required."
        }), 400

    if len(user_message) > 1000:

        user_message = user_message[:1000]

    try:

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=CHAT_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message}
            ]
        )

        raw_reply = response.content[0].text.strip()

    except Exception:

        return jsonify({
            "reply": (
                "Sorry, support chat is having trouble right now. "
                "Please email support@thepeniers.com."
            )
        }), 200

    is_complaint = raw_reply.lower().startswith("complaint: yes")

    reply_text = raw_reply

    if "\n" in raw_reply:

        first_line, rest = raw_reply.split(
            "\n",
            1
        )

        if first_line.lower().startswith("complaint:"):
            reply_text = rest.strip()

    chat_log = ChatMessage(
        customer_id=session.get("customer_id"),
        message=user_message,
        ai_response=reply_text,
        is_complaint=is_complaint
    )

    db.session.add(chat_log)
    db.session.commit()

    return jsonify({
        "reply": reply_text
    })


# ============================================================
# GENERAL FEEDBACK / BUG REPORT
# ============================================================

@app.route(
    "/feedback",
    methods=["GET", "POST"]
)
def feedback():

    if request.method == "POST":

        feedback_type = request.form.get(
            "feedback_type",
            "Comment"
        )

        message = request.form.get(
            "message",
            ""
        ).strip()

        if not message:

            flash(
                "Please write a message before submitting.",
                "error"
            )

            return render_template(
                "feedback.html"
            )

        entry = Feedback(
            customer_id=session.get("customer_id"),
            feedback_type=feedback_type,
            message=message
        )

        db.session.add(entry)
        db.session.commit()

        flash(
            "Thanks! Your feedback has been sent to our team.",
            "success"
        )

        return redirect(
            url_for("feedback")
        )

    return render_template(
        "feedback.html"
    )


@app.route("/admin/feedback")
def admin_feedback():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    feedback_entries = Feedback.query.order_by(
        Feedback.created_at.desc()
    ).all()

    return render_template(
        "admin_feedback.html",
        feedback_entries=feedback_entries
    )


# ============================================================
# CUSTOMER HOME
# ============================================================

BOOK_CATEGORIES = [
    "Novel",
    "Education",
    "Motivation",
    "Business",
    "Religion",
    "Children"
]


@app.route("/")
def home():

    selected_category = request.args.get(
        "category",
        ""
    ).strip()

    search_query = request.args.get(
        "q",
        ""
    ).strip()

    query = Book.query

    if selected_category and selected_category in BOOK_CATEGORIES:

        query = query.filter_by(
            category=selected_category
        )

    if search_query:

        like_pattern = f"%{search_query}%"

        query = query.filter(
            db.or_(
                Book.title.ilike(like_pattern),
                Book.author.ilike(like_pattern)
            )
        )

    books = query.order_by(
        Book.id.desc()
    ).all()

    return render_template(
        "index.html",
        books=books,
        categories=BOOK_CATEGORIES,
        selected_category=selected_category,
        search_query=search_query
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        fullname = request.form.get(
            "fullname",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not all([
            fullname,
            email,
            phone,
            address,
            password
        ]):

            flash(
                "Please complete all fields.",
                "error"
            )

            return render_template(
                "register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template(
                "register.html"
            )

        existing_email = Customer.query.filter_by(
            email=email
        ).first()

        if existing_email:

            flash(
                "That email address is already registered.",
                "error"
            )

            return render_template(
                "register.html"
            )

        existing_phone = Customer.query.filter_by(
            phone=phone
        ).first()

        if existing_phone:

            flash(
                "That phone number is already registered.",
                "error"
            )

            return render_template(
                "register.html"
            )

        hashed_password = generate_password_hash(
            password
        )

        customer = Customer(
            fullname=fullname,
            email=email,
            phone=phone,
            address=address,
            password=hashed_password
        )

        db.session.add(customer)
        db.session.commit()

        flash(
            "Account created successfully. Please log in.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# ============================================================
# CUSTOMER LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # ------------------------------------------------------
        # Check admin credentials first. If they match, this is
        # the admin logging in through the normal login page —
        # send them straight to the admin dashboard instead of
        # treating this as a customer login.
        # ------------------------------------------------------

        admin_email = os.environ.get(
            "ADMIN_EMAIL",
            "admin@thepeniers.com"
        )

        admin_password = os.environ.get(
            "ADMIN_PASSWORD",
            "ChangeThisPassword123!"
        )

        if (
            email == admin_email
            and
            password == admin_password
        ):

            session["admin_logged_in"] = True

            return redirect(
                url_for("admin_dashboard")
            )

        customer = Customer.query.filter_by(
            email=email
        ).first()

        if not customer:

            flash(
                "Invalid email or password.",
                "error"
            )

            return render_template(
                "login.html"
            )

        if not check_password_hash(
            customer.password,
            password
        ):

            flash(
                "Invalid email or password.",
                "error"
            )

            return render_template(
                "login.html"
            )

        session["customer_id"] = customer.id
        session["customer_name"] = customer.fullname

        return redirect(
            url_for("home")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# CUSTOMER LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.pop(
        "customer_id",
        None
    )

    session.pop(
        "customer_name",
        None
    )

    return redirect(
        url_for("home")
    )


# ============================================================
# BOOK DETAILS
# ============================================================

@app.route("/book/<int:id>")
def book_details(id):

    book = Book.query.get_or_404(id)

    return render_template(
        "book_details.html",
        book=book
    )


# ============================================================
# BOOK COMMENTS
# ============================================================

@app.route(
    "/book/<int:id>/comment",
    methods=["POST"]
)
def add_comment(id):

    book = Book.query.get_or_404(id)

    if not customer_logged_in():

        flash(
            "Please log in to leave a comment.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not content:

        flash(
            "Comment can't be empty.",
            "error"
        )

        return redirect(
            url_for("book_details", id=id) + "#comments"
        )

    comment = Comment(
        book_id=book.id,
        customer_id=session.get("customer_id"),
        content=content
    )

    db.session.add(comment)
    db.session.commit()

    flash(
        "Comment posted.",
        "success"
    )

    return redirect(
        url_for("book_details", id=id) + "#comments"
    )


# ============================================================
# ADD TO CART
# ============================================================

@app.route(
    "/add-to-cart/<int:book_id>",
    methods=["POST"]
)
def add_to_cart(book_id):

    if not customer_logged_in():

        flash(
            "Please log in before adding books to your cart.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    book = Book.query.get_or_404(
        book_id
    )

    try:

        quantity = int(
            request.form.get(
                "quantity",
                1
            )
        )

    except ValueError:

        quantity = 1

    if quantity < 1:

        quantity = 1

    if book.quantity < quantity:

        flash(
            "There is not enough stock.",
            "error"
        )

        return redirect(
            url_for(
                "book_details",
                id=book.id
            )
        )

    cart = session.get(
        "cart",
        {}
    )

    book_key = str(
        book.id
    )

    current_quantity = cart.get(
        book_key,
        0
    )

    new_quantity = (
        current_quantity +
        quantity
    )

    if new_quantity > book.quantity:

        new_quantity = book.quantity

    cart[book_key] = new_quantity

    session["cart"] = cart
    session.modified = True

    flash(
        "Book added to your cart.",
        "success"
    )

    return redirect(
        url_for("cart")
    )


# ============================================================
# CART
# ============================================================

@app.route("/cart")
def cart():

    cart_data = session.get(
        "cart",
        {}
    )

    cart_items = []
    total = 0

    for book_id, quantity in cart_data.items():

        book = db.session.get(
            Book,
            int(book_id)
        )

        if not book:
            continue

        item_total = (
            book.price *
            quantity
        )

        total += item_total

        cart_items.append({
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "price": book.price,
            "quantity": quantity,
            "image": book.image,
            "total": item_total
        })

    return render_template(
        "cart.html",
        cart=cart_items,
        total=total
    )


# ============================================================
# REMOVE CART ITEM
# ============================================================

@app.route(
    "/remove-from-cart/<int:book_id>"
)
def remove_from_cart(book_id):

    cart = session.get(
        "cart",
        {}
    )

    cart.pop(
        str(book_id),
        None
    )

    session["cart"] = cart
    session.modified = True

    return redirect(
        url_for("cart")
    )


# ============================================================
# CHECKOUT
# ============================================================

@app.route(
    "/checkout",
    methods=["GET", "POST"]
)
def checkout():

    if not customer_logged_in():

        flash(
            "Please log in before checkout.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    customer = get_current_customer()

    cart_data = session.get(
        "cart",
        {}
    )

    if not cart_data:

        flash(
            "Your cart is empty.",
            "error"
        )

        return redirect(
            url_for("cart")
        )

    cart_items = []
    total = 0

    for book_id, quantity in cart_data.items():

        book = db.session.get(
            Book,
            int(book_id)
        )

        if not book:
            continue

        if quantity > book.quantity:

            flash(
                f"Not enough stock for {book.title}.",
                "error"
            )

            return redirect(
                url_for("cart")
            )

        item_total = (
            book.price *
            quantity
        )

        total += item_total

        cart_items.append({
            "book": book,
            "quantity": quantity,
            "total": item_total
        })

    if request.method == "POST":

        fullname = request.form.get(
            "fullname",
            customer.fullname
        ).strip()

        phone = request.form.get(
            "phone",
            customer.phone
        ).strip()

        address = request.form.get(
            "address",
            customer.address
        ).strip()

        payment = request.form.get(
            "payment",
            "Bank Transfer"
        )

        if not fullname or not phone or not address:

            flash(
                "Please complete your delivery information.",
                "error"
            )

            return render_template(
                "checkout.html",
                cart=cart_items,
                total=total,
                customer=customer
            )

        if payment == "Auto-Debit" and not customer.has_saved_account():

            flash(
                "You have no saved auto-debit account. Please add one first.",
                "error"
            )

            return redirect(
                url_for("add_account")
            )

        if payment == "Card":

            card_name = request.form.get(
                "card_name",
                ""
            ).strip()

            card_number = request.form.get(
                "card_number",
                ""
            ).replace(" ", "").strip()

            card_expiry = request.form.get(
                "card_expiry",
                ""
            ).strip()

            card_cvv = request.form.get(
                "card_cvv",
                ""
            ).strip()

            if (
                not card_name
                or not card_number
                or not card_expiry
                or not card_cvv
            ):

                flash(
                    "Please complete all card details.",
                    "error"
                )

                return render_template(
                    "checkout.html",
                    cart=cart_items,
                    total=total,
                    customer=customer
                )

            if not card_number.isdigit() or not (
                13 <= len(card_number) <= 19
            ):

                flash(
                    "Please enter a valid card number.",
                    "error"
                )

                return render_template(
                    "checkout.html",
                    cart=cart_items,
                    total=total,
                    customer=customer
                )

            if not card_cvv.isdigit() or not (
                3 <= len(card_cvv) <= 4
            ):

                flash(
                    "Please enter a valid CVV.",
                    "error"
                )

                return render_template(
                    "checkout.html",
                    cart=cart_items,
                    total=total,
                    customer=customer
                )

        # ----------------------------------------------------
        # Auto-Debit and Card both simulate an instant charge,
        # so the order is marked Paid right away. Every other
        # payment method still requires separate confirmation,
        # so those orders stay Unpaid until that happens.
        #
        # IMPORTANT: the full card number and CVV are never
        # saved anywhere, not even here in memory beyond this
        # request - only the last 4 digits are kept, purely so
        # the order history can show which card was used.
        # ----------------------------------------------------

        if payment == "Auto-Debit":

            payment_status = "Paid"

            payment_method = (
                f"Auto-Debit - {customer.bank_name} "
                f"({customer.masked_account_number()})"
            )

        elif payment == "Card":

            payment_status = "Paid"

            payment_method = f"Card - **** {card_number[-4:]}"

        else:

            payment_status = "Unpaid"

            payment_method = payment

        order = Order(
            customer_id=customer.id,
            total=total,
            status="Pending",
            payment_status=payment_status,
            payment_method=payment_method,
            order_number=generate_order_number(),
            delivery_address=address
        )

        db.session.add(order)
        db.session.flush()

        for item in cart_items:

            order_item = OrderItem(
                order_id=order.id,
                book_id=item["book"].id,
                quantity=item["quantity"],
                price=item["book"].price
            )

            db.session.add(
                order_item
            )

            item["book"].quantity -= (
                item["quantity"]
            )

        db.session.commit()

        session["cart"] = {}
        session.modified = True

        flash(
            "Your order has been placed.",
            "success"
        )

        return redirect(
            url_for("my_orders")
        )

    return render_template(
        "checkout.html",
        cart=cart_items,
        total=total,
        customer=customer
    )


# ============================================================
# MY ORDERS
# ============================================================

@app.route("/my-orders")
def my_orders():

    if not customer_logged_in():

        return redirect(
            url_for("login")
        )

    customer = get_current_customer()

    orders = Order.query.filter_by(
        customer_id=customer.id
    ).order_by(
        Order.created_at.desc()
    ).all()

    return render_template(
        "my_orders.html",
        orders=orders
    )


# ============================================================
# CUSTOMER PROFILE
# ============================================================

@app.route("/profile")
def profile():

    if not customer_logged_in():

        return redirect(
            url_for("login")
        )

    customer = get_current_customer()

    return render_template(
        "profile.html",
        customer=customer
    )


# ============================================================
# ADD / UPDATE AUTO-DEBIT ACCOUNT
# ============================================================

@app.route(
    "/add-account",
    methods=["GET", "POST"]
)
def add_account():

    if not customer_logged_in():

        flash(
            "Please log in first.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    customer = get_current_customer()

    if request.method == "POST":

        bank_name = request.form.get(
            "bank_name",
            ""
        ).strip()

        account_name = request.form.get(
            "account_name",
            ""
        ).strip()

        account_number = request.form.get(
            "account_number",
            ""
        ).strip()

        if not bank_name or not account_name or not account_number:

            flash(
                "Please complete all account fields.",
                "error"
            )

            return render_template(
                "add_account.html",
                customer=customer
            )

        if not account_number.isdigit() or not (
            9 <= len(account_number) <= 12
        ):

            flash(
                "Please enter a valid account number.",
                "error"
            )

            return render_template(
                "add_account.html",
                customer=customer
            )

        customer.bank_name = bank_name
        customer.account_name = account_name
        customer.account_number = account_number
        customer.auto_debit_enabled = True

        db.session.commit()

        flash(
            "Auto-debit account saved.",
            "success"
        )

        return redirect(
            url_for("profile")
        )

    return render_template(
        "add_account.html",
        customer=customer
    )


# ============================================================
# REMOVE AUTO-DEBIT ACCOUNT
# ============================================================

@app.route(
    "/remove-account",
    methods=["POST"]
)
def remove_account():

    if not customer_logged_in():

        return redirect(
            url_for("login")
        )

    customer = get_current_customer()

    customer.bank_name = None
    customer.account_name = None
    customer.account_number = None
    customer.auto_debit_enabled = False

    db.session.commit()

    flash(
        "Auto-debit account removed.",
        "success"
    )

    return redirect(
        url_for("profile")
    )


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route("/admin-logout")
def admin_logout():

    session.pop(
        "admin_logged_in",
        None
    )

    return redirect(
        url_for("login")
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
def admin_dashboard():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    books_count = Book.query.count()

    customers_count = Customer.query.count()

    orders_count = Order.query.count()

    total_sales = db.session.query(
        db.func.sum(Order.total)
    ).filter(
        Order.payment_status == "Paid"
    ).scalar()

    if total_sales is None:
        total_sales = 0

    recent_orders = Order.query.order_by(
        Order.created_at.desc()
    ).limit(10).all()

    return render_template(
        "admin_dashboard.html",
        books_count=books_count,
        customers_count=customers_count,
        orders_count=orders_count,
        total_sales=total_sales,
        recent_orders=recent_orders
    )


# ============================================================
# SALES LOGIN
# ============================================================

@app.route(
    "/sales-login",
    methods=["GET", "POST"]
)
def sales_login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        sales_username = os.environ.get(
            "SALES_USERNAME",
            "@thepeniers"
        )

        sales_password = os.environ.get(
            "SALES_PASSWORD",
            "ChangeThisSalesPassword123!"
        )

        if (
            username == sales_username
            and
            password == sales_password
        ):

            session["sales_logged_in"] = True

            return redirect(
                url_for("sales_report")
            )

        flash(
            "Invalid username or password."
        )

    return render_template(
        "sales_login.html"
    )


@app.route("/sales-logout")
def sales_logout():

    session.pop(
        "sales_logged_in",
        None
    )

    return redirect(
        url_for("sales_login")
    )


# ============================================================
# SALES REPORT + CHART
# ============================================================

@app.route("/sales-report")
def sales_report():

    if not sales_logged_in():

        return redirect(
            url_for("sales_login")
        )

    orders_count = Order.query.count()

    paid_orders_count = Order.query.filter_by(
        payment_status="Paid"
    ).count()

    total_sales = db.session.query(
        db.func.sum(Order.total)
    ).filter(
        Order.payment_status == "Paid"
    ).scalar() or 0

    average_order_value = (
        total_sales / paid_orders_count
        if paid_orders_count
        else 0
    )

    # ---- Daily sales for the last 14 days (for the line chart) ----

    today = datetime.utcnow().date()

    daily_labels = []
    daily_totals = []

    for days_ago in range(13, -1, -1):

        day = today - timedelta(days=days_ago)

        day_start = datetime(
            day.year, day.month, day.day
        )

        day_end = day_start + timedelta(days=1)

        day_total = db.session.query(
            db.func.sum(Order.total)
        ).filter(
            Order.payment_status == "Paid",
            Order.created_at >= day_start,
            Order.created_at < day_end
        ).scalar() or 0

        daily_labels.append(
            day.strftime("%d %b")
        )

        daily_totals.append(
            round(day_total, 2)
        )

    # ---- Revenue by book category (for the bar chart) ----

    category_rows = db.session.query(
        Book.category,
        db.func.sum(OrderItem.price * OrderItem.quantity)
    ).join(
        OrderItem, OrderItem.book_id == Book.id
    ).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Order.payment_status == "Paid"
    ).group_by(
        Book.category
    ).all()

    category_labels = [
        (row[0] or "Uncategorized") for row in category_rows
    ]

    category_totals = [
        round(row[1] or 0, 2) for row in category_rows
    ]

    recent_orders = Order.query.order_by(
        Order.created_at.desc()
    ).limit(10).all()

    return render_template(
        "sales_report.html",
        orders_count=orders_count,
        paid_orders_count=paid_orders_count,
        total_sales=total_sales,
        average_order_value=average_order_value,
        daily_labels=daily_labels,
        daily_totals=daily_totals,
        category_labels=category_labels,
        category_totals=category_totals,
        recent_orders=recent_orders
    )


# ============================================================
# MANAGE BOOKS
# ============================================================

@app.route("/manage-books")
def manage_books():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    books = Book.query.order_by(
        Book.id.desc()
    ).all()

    return render_template(
        "manage_books.html",
        books=books
    )


# ============================================================
# ADD BOOK
# ============================================================

@app.route(
    "/add-book",
    methods=["GET", "POST"]
)
def add_book():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        author = request.form.get(
            "author",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        price = request.form.get(
            "price",
            "0"
        )

        quantity = request.form.get(
            "quantity",
            "0"
        )

        image = request.form.get(
            "image",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        original_price = request.form.get(
            "original_price",
            ""
        ).strip()

        try:

            price = float(price)

            quantity = int(quantity)

            original_price = (
                float(original_price)
                if original_price
                else None
            )

        except ValueError:

            flash(
                "Price, original price, or quantity is invalid.",
                "error"
            )

            return render_template(
                "add_book.html"
            )

        if not title or not author:

            flash(
                "Title and author are required.",
                "error"
            )

            return render_template(
                "add_book.html"
            )

        book = Book(
            title=title,
            author=author,
            description=description,
            price=price,
            original_price=original_price,
            quantity=quantity,
            image=image,
            category=category or None
        )

        db.session.add(book)
        db.session.commit()

        flash(
            "Book added successfully.",
            "success"
        )

        return redirect(
            url_for("manage_books")
        )

    return render_template(
        "add_book.html"
    )


# ============================================================
# DELETE BOOK
# ============================================================

@app.route(
    "/delete-book/<int:book_id>",
    methods=["POST", "GET"]
)
def delete_book(book_id):

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    book = Book.query.get_or_404(
        book_id
    )

    db.session.delete(book)
    db.session.commit()

    flash(
        "Book deleted.",
        "success"
    )

    return redirect(
        url_for("manage_books")
    )


# ============================================================
# ADMIN ORDERS
# ============================================================

@app.route("/admin-orders")
def admin_orders():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    orders = Order.query.order_by(
        Order.created_at.desc()
    ).all()

    return render_template(
        "admin_orders.html",
        orders=orders
    )


@app.route("/admin/complaints")
def admin_complaints():

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    complaints = ChatMessage.query.filter_by(
        is_complaint=True
    ).order_by(
        ChatMessage.created_at.desc()
    ).all()

    return render_template(
        "admin_complaints.html",
        complaints=complaints
    )


# ============================================================
# ADMIN ORDER DETAILS
# ============================================================

@app.route("/admin/order/<int:order_id>")
def admin_order_details(order_id):

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    order = Order.query.get_or_404(
        order_id
    )

    return render_template(
        "admin_order_details.html",
        order=order
    )


# ============================================================
# UPDATE ORDER STATUS
# ============================================================

@app.route(
    "/admin/order/<int:order_id>/status",
    methods=["POST"]
)
def update_order_status(order_id):

    if not admin_logged_in():

        return redirect(
            url_for("login")
        )

    order = Order.query.get_or_404(
        order_id
    )

    status = request.form.get(
        "status",
        "Pending"
    )

    allowed_statuses = [
        "Pending",
        "Processing",
        "Shipped",
        "Delivered",
        "Cancelled"
    ]

    if status not in allowed_statuses:

        flash(
            "Invalid order status.",
            "error"
        )

        return redirect(
            url_for("admin_orders")
        )

    order.status = status

    db.session.commit()

    flash(
        "Order status updated.",
        "success"
    )

    return redirect(
        url_for("admin_orders")
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return """
    <h1>404 - Page Not Found</h1>
    <p>The page you requested does not exist.</p>
    """, 404


@app.errorhandler(500)
def server_error(error):

    return """
    <h1>500 - Server Error</h1>
    <p>Something went wrong on the server.</p>
    """, 500


# ============================================================
# RUN APP
# ============================================================

if __name__ == "__main__":

    # Debug mode is OFF unless you explicitly turn it on locally
    # with: FLASK_DEBUG=1 python3 app.py
    # Never run debug=True on a live/public site.

    debug_mode = os.environ.get(
        "FLASK_DEBUG",
        "0"
    ) == "1"

    app.run(
        debug=debug_mode,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )