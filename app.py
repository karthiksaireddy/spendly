"""Spendly — Flask application entrypoint.

Run with ``python app.py`` (port 5001). Routes are organized by area: auth,
dashboard, expenses, categories. All persistent data lives in SQLite via
``database/db.py``.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Optional

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    request,
)
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
import jwt

from database import DATABASE_URL, close_db, get_db, init_db

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #

DEFAULT_PORT = 5001
DEV_SECRET = "dev-secret-change-me"

# Minimal RFC-5322-ish check; good enough to catch typos, not for
# validating every legal RFC address. Server-side only.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ #
# App factory                                                         #
# ------------------------------------------------------------------ #

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", DEV_SECRET)
    app.config["DATABASE"] = DATABASE_URL
    app.config["JWT_SECRET_KEY"] = os.environ.get("SECRET_KEY", DEV_SECRET)
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
    
    # Enable CORS for frontend
    CORS(app)

    # Initialize database tables
    init_db()

    # Make sure the connection is closed at the end of every request.
    app.teardown_appcontext(close_db)

    register_routes(app)
    register_error_handlers(app)
    return app


# ------------------------------------------------------------------ #
# Auth helpers                                                        #
# ------------------------------------------------------------------ #

def _load_current_user_from_token():
    """Load user from JWT token in Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(
            token,
            os.environ.get("SECRET_KEY", DEV_SECRET),
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id")
        if user_id:
            from database import get_user_by_id
            return get_user_by_id(user_id)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    return None


def login_required(view):
    """Reject requests without valid JWT token."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _load_current_user_from_token()
        if user is None:
            return jsonify({"error": "Unauthorized"}), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

def register_routes(app: Flask) -> None:
    # ----- Health check -----
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    # ----- Auth endpoints -----
    @app.route("/api/register", methods=["POST"])
    def register():
        return _handle_register()

    @app.route("/api/login", methods=["POST"])
    def login():
        return _handle_login()

    # ----- Dashboard -----
    @app.route("/api/dashboard")
    @login_required
    def dashboard():
        return _handle_dashboard()

    # ----- Expenses -----
    @app.route("/api/expenses", methods=["GET"])
    @login_required
    def list_expenses():
        return _handle_list_expenses()

    @app.route("/api/expenses", methods=["POST"])
    @login_required
    def create_expense():
        return _handle_create_expense()

    @app.route("/api/expenses/<int:expense_id>", methods=["GET"])
    @login_required
    def get_expense(expense_id: int):
        return _handle_get_expense(expense_id)

    @app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
    @login_required
    def update_expense(expense_id: int):
        return _handle_update_expense(expense_id)

    @app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
    @login_required
    def delete_expense(expense_id: int):
        return _handle_delete_expense(expense_id)

    # ----- Categories -----
    @app.route("/api/categories", methods=["GET"])
    @login_required
    def list_categories():
        return _handle_list_categories()

    @app.route("/api/categories", methods=["POST"])
    @login_required
    def create_category():
        return _handle_create_category()

    @app.route("/api/categories/<int:category_id>", methods=["PUT"])
    @login_required
    def update_category(category_id: int):
        return _handle_update_category(category_id)

    @app.route("/api/categories/<int:category_id>", methods=["DELETE"])
    @login_required
    def delete_category(category_id: int):
        return _handle_delete_category(category_id)


# ------------------------------------------------------------------ #
# Handlers — auth                                                     #
# ------------------------------------------------------------------ #

def _handle_register():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""

    error = _validate_registration(email, name, password, confirm)
    if error:
        return jsonify({"error": error}), 400

    from database import create_user

    user_id = create_user(email, name, generate_password_hash(password))
    
    # Generate JWT token
    token = jwt.encode(
        {"user_id": user_id, "exp": datetime.utcnow() + timedelta(hours=24)},
        os.environ.get("SECRET_KEY", DEV_SECRET),
        algorithm="HS256"
    )
    
    return jsonify({
        "message": "Registration successful",
        "token": token,
        "user": {"id": user_id, "email": email, "display_name": name}
    }), 201


def _validate_registration(
    email: str, name: str, password: str, confirm: str
) -> Optional[str]:
    if not name:
        return "Please enter your name."
    if not EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "Passwords do not match."
    from database import get_user_by_email
    if get_user_by_email(email) is not None:
        return "An account with that email already exists."
    return None


def _handle_login():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    from database import get_user_by_email
    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Generate JWT token
    token = jwt.encode(
        {"user_id": user["id"], "exp": datetime.utcnow() + timedelta(hours=24)},
        os.environ.get("SECRET_KEY", DEV_SECRET),
        algorithm="HS256"
    )
    
    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}
    })


# ------------------------------------------------------------------ #
# Handlers — dashboard                                                #
# ------------------------------------------------------------------ #

def _handle_dashboard():
    from database import by_category_for_month, recent_expenses, sum_for_month

    user_id = g.current_user["id"]
    year, month = _parse_month(request.args.get("month"))
    prev_year, prev_month = _previous_month(year, month)

    return jsonify({
        "year": year,
        "month": month,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "total_this_month": sum_for_month(user_id, year, month),
        "total_last_month": sum_for_month(user_id, prev_year, prev_month),
        "by_category": by_category_for_month(user_id, year, month),
        "recent": recent_expenses(user_id, limit=5),
    })


def _parse_month(raw: Optional[str]) -> tuple[int, int]:
    today = date.today()
    if not raw:
        return today.year, today.month
    try:
        parsed = datetime.strptime(raw, "%Y-%m")
        return parsed.year, parsed.month
    except ValueError:
        return today.year, today.month


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


# ------------------------------------------------------------------ #
# Handlers — expenses                                                 #
# ------------------------------------------------------------------ #

def _parse_expense_data() -> tuple[Optional[dict], Optional[str]]:
    """Pull and validate the expense fields from JSON request body."""
    data = request.get_json()
    
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return None, "Amount must be a number."
    if amount <= 0:
        return None, "Amount must be greater than zero."

    category_id = data.get("category_id")
    if not category_id or not isinstance(category_id, int):
        return None, "Please choose a category."

    date_raw = data.get("date")
    try:
        datetime.strptime(date_raw, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, "Please enter a valid date (YYYY-MM-DD)."

    note = data.get("note", "").strip()
    if len(note) > 200:
        return None, "Note must be 200 characters or fewer."

    return (
        {
            "amount": amount,
            "category_id": category_id,
            "date": date_raw,
            "note": note or None,
        },
        None,
    )


def _handle_create_expense():
    user_id = g.current_user["id"]
    parsed, error = _parse_expense_data()
    if error:
        return jsonify({"error": error}), 400

    from database import get_category
    if get_category(user_id, parsed["category_id"]) is None:
        return jsonify({"error": "Please choose a category."}), 400

    from database import create_expense
    expense_id = create_expense(
        user_id=user_id,
        category_id=parsed["category_id"],
        amount=parsed["amount"],
        date=parsed["date"],
        note=parsed["note"],
    )
    return jsonify({"message": "Expense created", "id": expense_id}), 201


def _handle_get_expense(expense_id: int):
    from database import get_expense
    user_id = g.current_user["id"]
    expense = get_expense(user_id, expense_id)
    if expense is None:
        return jsonify({"error": "Expense not found"}), 404
    return jsonify(expense)


def _handle_update_expense(expense_id: int):
    from database import get_category, get_expense, update_expense
    user_id = g.current_user["id"]
    if get_expense(user_id, expense_id) is None:
        return jsonify({"error": "Expense not found"}), 404

    parsed, error = _parse_expense_data()
    if error:
        return jsonify({"error": error}), 400

    if get_category(user_id, parsed["category_id"]) is None:
        return jsonify({"error": "That category doesn't exist."}), 400

    update_expense(
        user_id=user_id,
        expense_id=expense_id,
        category_id=parsed["category_id"],
        amount=parsed["amount"],
        date=parsed["date"],
        note=parsed["note"],
    )
    return jsonify({"message": "Expense updated"})


def _handle_delete_expense(expense_id: int):
    from database import delete_expense, get_expense
    user_id = g.current_user["id"]
    if get_expense(user_id, expense_id) is None:
        return jsonify({"error": "Expense not found"}), 404
    delete_expense(user_id, expense_id)
    return jsonify({"message": "Expense deleted"})


def _handle_list_expenses():
    from database import list_expenses, sum_expenses, get_categories
    user_id = g.current_user["id"]
    date_from = _normalize_date(request.args.get("from"))
    date_to = _normalize_date(request.args.get("to"))
    category_raw = (request.args.get("category") or "").strip()
    category_id = int(category_raw) if category_raw.isdigit() else None

    return jsonify({
        "expenses": list_expenses(user_id, date_from, date_to, category_id),
        "total": sum_expenses(user_id, date_from, date_to, category_id),
        "categories": get_categories(user_id),
        "filters": {
            "from": date_from or "",
            "to": date_to or "",
            "category": category_raw,
        },
    })


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


# ------------------------------------------------------------------ #
# Handlers — categories                                               #
# ------------------------------------------------------------------ #

def _handle_list_categories():
    from database import category_in_use, get_categories
    user_id = g.current_user["id"]
    categories = get_categories(user_id)
    annotated = [
        {"id": c["id"], "name": c["name"], "in_use": category_in_use(c["id"])}
        for c in categories
    ]
    return jsonify({"categories": annotated})


def _handle_create_category():
    from database import create_category
    data = request.get_json()
    name = (data.get("name") or "").strip()
    error = _validate_category_name(name)
    if error:
        return jsonify({"error": error}), 400
    try:
        category_id = create_category(g.current_user["id"], name)
        return jsonify({"message": "Category created", "id": category_id, "name": name}), 201
    except Exception:
        return jsonify({"error": "You already have a category with that name."}), 400


def _handle_update_category(category_id: int):
    from database import get_category, update_category
    user_id = g.current_user["id"]
    if get_category(user_id, category_id) is None:
        return jsonify({"error": "Category not found"}), 404
    data = request.get_json()
    name = (data.get("name") or "").strip()
    error = _validate_category_name(name)
    if error:
        return jsonify({"error": error}), 400
    try:
        update_category(user_id, category_id, name)
        return jsonify({"message": "Category updated"})
    except Exception:
        return jsonify({"error": "You already have a category with that name."}), 400


def _handle_delete_category(category_id: int):
    from database import category_in_use, delete_category, get_category
    user_id = g.current_user["id"]
    category = get_category(user_id, category_id)
    if category is None:
        return jsonify({"error": "Category not found"}), 404
    if category_in_use(category_id):
        return jsonify({
            "error": f"Can't delete “{category['name']}” — it's used by an expense. Reassign those expenses first."
        }), 400
    delete_category(user_id, category_id)
    return jsonify({"message": "Category deleted"})


def _validate_category_name(name: str) -> Optional[str]:
    if not name:
        return "Please enter a category name."
    if len(name) > 40:
        return "Category name must be 40 characters or fewer."
    return None


# ------------------------------------------------------------------ #
# Error handlers                                                      #
# ------------------------------------------------------------------ #

def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": str(e.description)}), 400

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify({"error": "Internal server error"}), 500


# ------------------------------------------------------------------ #
# Entry point                                                         #
# ------------------------------------------------------------------ #

app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=DEFAULT_PORT)
