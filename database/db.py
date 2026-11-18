"""Database module for Spendly.

Owns the SQLite schema, connection lifecycle, and every helper that touches
the database. Routes in app.py should never call ``sqlite3`` directly — go
through the helpers here so SQL stays in one place.
"""
from __future__ import annotations

import os
import psycopg2
from psycopg2 import pool
from typing import Any, Iterable, Optional

# PostgreSQL connection URL from environment variable
# Format: postgresql://user:password@host:port/database
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/spendly"
)

# Connection pool for PostgreSQL
connection_pool = None

# For testing, can override with test database URL
TEST_DB_URL = os.environ.get("SPENDLY_TEST_DB")

# Categories seeded for every new user (SPEC §4 "Defaults").
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "Food",
    "Travel",
    "Bills",
    "Shopping",
    "Other",
)


# ------------------------------------------------------------------ #
# Connection lifecycle                                                #
# ------------------------------------------------------------------ #

def get_db():
    """Return a PostgreSQL connection scoped to the current app context.

    The connection is created lazily from the connection pool and stored on
    ``flask.g`` so the same connection is reused for the duration of a request.
    """
    from flask import current_app, g

    global connection_pool
    
    if connection_pool is None:
        db_url = TEST_DB_URL if TEST_DB_URL else DATABASE_URL
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url
        )
    
    if "db" not in g:
        g.db = connection_pool.getconn()
    return g.db


def close_db(_exc: Optional[BaseException] = None) -> None:
    """Close the request-scoped connection, if any."""
    from flask import g

    db = g.pop("db", None)
    if db is not None:
        connection_pool.putconn(db)


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expenses (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    amount      NUMERIC NOT NULL CHECK (amount > 0),
    date        DATE    NOT NULL,
    note        TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id)     REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_expenses_user_date
    ON expenses (user_id, date);
"""


def init_db(db_url: Optional[str] = None) -> None:
    """Create all tables and indexes if they don't already exist.

    Uses the DATABASE_URL environment variable or the provided db_url.
    """
    url = db_url if db_url else (TEST_DB_URL if TEST_DB_URL else DATABASE_URL)
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Users                                                               #
# ------------------------------------------------------------------ #

def create_user(email: str, display_name: str, password_hash: str) -> int:
    """Insert a new user and return the assigned id.

    Raises ``psycopg2.IntegrityError`` if the email is already taken.
    """
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (email, display_name, password_hash),
        )
        user_id = cur.fetchone()[0]
    db.commit()
    seed_default_categories(user_id)
    return user_id


def get_user_by_id(user_id: int):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, email, display_name, password_hash, created_at "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            return dict(zip(columns, row))
        return None


def get_user_by_email(email: str):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, email, display_name, password_hash, created_at "
            "FROM users WHERE email = %s",
            (email,),
        )
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            return dict(zip(columns, row))
        return None


# ------------------------------------------------------------------ #
# Categories                                                          #
# ------------------------------------------------------------------ #

def get_categories(user_id: int):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM categories WHERE user_id = %s ORDER BY name",
            (user_id,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_category(user_id: int, category_id: int):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM categories WHERE id = %s AND user_id = %s",
            (category_id, user_id),
        )
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            return dict(zip(columns, row))
        return None


def create_category(user_id: int, name: str) -> int:
    """Insert a new category and return the assigned id.

    Raises ``psycopg2.IntegrityError`` on duplicate (user_id, name).
    """
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO categories (user_id, name) VALUES (%s, %s) RETURNING id",
            (user_id, name),
        )
        category_id = cur.fetchone()[0]
    db.commit()
    return category_id


def update_category(user_id: int, category_id: int, name: str) -> None:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE categories SET name = %s WHERE id = %s AND user_id = %s",
            (name, category_id, user_id),
        )
    db.commit()


def delete_category(user_id: int, category_id: int) -> None:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM categories WHERE id = %s AND user_id = %s",
            (category_id, user_id),
        )
    db.commit()


def category_in_use(category_id: int) -> bool:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM expenses WHERE category_id = %s LIMIT 1",
            (category_id,),
        )
        return cur.fetchone() is not None


def seed_default_categories(user_id: int) -> None:
    """Populate the standard set of categories for a new user."""
    for name in DEFAULT_CATEGORIES:
        try:
            create_category(user_id, name)
        except psycopg2.IntegrityError:
            # Already exists — shouldn't happen for a new user, but stay
            # defensive in case seed is rerun.
            continue


# ------------------------------------------------------------------ #
# Expenses                                                            #
# ------------------------------------------------------------------ #

def create_expense(
    user_id: int,
    category_id: int,
    amount: float,
    date: str,
    note: Optional[str],
) -> int:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO expenses (user_id, category_id, amount, date, note) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, category_id, amount, date, note),
        )
        expense_id = cur.fetchone()[0]
    db.commit()
    return expense_id


def get_expense(user_id: int, expense_id: int):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT e.id, e.user_id, e.category_id, e.amount, e.date, e.note, "
            "       c.name AS category_name "
            "FROM expenses e "
            "JOIN categories c ON c.id = e.category_id "
            "WHERE e.id = %s AND e.user_id = %s",
            (expense_id, user_id),
        )
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            return dict(zip(columns, row))
        return None


def update_expense(
    user_id: int,
    expense_id: int,
    category_id: int,
    amount: float,
    date: str,
    note: Optional[str],
) -> None:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE expenses "
            "SET category_id = %s, amount = %s, date = %s, note = %s "
            "WHERE id = %s AND user_id = %s",
            (category_id, amount, date, note, expense_id, user_id),
        )
    db.commit()


def delete_expense(user_id: int, expense_id: int) -> None:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM expenses WHERE id = %s AND user_id = %s",
            (expense_id, user_id),
        )
    db.commit()


def list_expenses(
    user_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
):
    """Return the user's expenses, newest first, with filters applied.

    All filters are AND'd. A None or empty value means "no filter for that
    column". The caller is responsible for any input validation; this
    function trusts that ``date_from``/``date_to`` are ISO strings and
    ``category_id`` is a valid integer referencing a row owned by the user.
    """
    sql = (
        "SELECT e.id, e.amount, e.date, e.note, "
        "       c.id AS category_id, c.name AS category_name "
        "FROM expenses e "
        "JOIN categories c ON c.id = e.category_id "
        "WHERE e.user_id = %s "
    )
    params: list[Any] = [user_id]
    if date_from:
        sql += "AND e.date >= %s "
        params.append(date_from)
    if date_to:
        sql += "AND e.date <= %s "
        params.append(date_to)
    if category_id:
        sql += "AND e.category_id = %s "
        params.append(category_id)
    sql += "ORDER BY e.date DESC, e.id DESC"
    
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def sum_expenses(
    user_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
) -> float:
    """Sum amounts over the same filter set as ``list_expenses``."""
    sql = "SELECT COALESCE(SUM(e.amount), 0) AS total FROM expenses e WHERE e.user_id = %s "
    params: list[Any] = [user_id]
    if date_from:
        sql += "AND e.date >= %s "
        params.append(date_from)
    if date_to:
        sql += "AND e.date <= %s "
        params.append(date_to)
    if category_id:
        sql += "AND e.category_id = %s "
        params.append(category_id)
    
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return float(row[0])


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    """Return (first_day, first_day_of_next_month) for a calendar month.

    The interval is half-open: ``[first, next_first)`` so callers can use
    ``date >= first AND date < next_first`` and never worry about the
    varying length of February or leap years.
    """
    if month == 12:
        return (f"{year:04d}-12-01", f"{year + 1:04d}-01-01")
    return (f"{year:04d}-{month:02d}-01", f"{year:04d}-{month + 1:02d}-01")


def sum_for_month(user_id: int, year: int, month: int) -> float:
    """Total spending in a single calendar month (1-indexed month)."""
    first, next_first = _month_bounds(year, month)
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses "
            "WHERE user_id = %s AND date >= %s AND date < %s",
            (user_id, first, next_first),
        )
        row = cur.fetchone()
        return float(row[0])


def by_category_for_month(
    user_id: int, year: int, month: int
):
    """Per-category totals for a month, ordered by amount descending.

    Categories with zero spending in the month are omitted (``HAVING
    total > 0``).
    """
    first, next_first = _month_bounds(year, month)
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT c.id AS category_id, c.name AS category_name, "
            "       COALESCE(SUM(e.amount), 0) AS total "
            "FROM categories c "
            "LEFT JOIN expenses e "
            "  ON e.category_id = c.id "
            " AND e.date >= %s AND e.date < %s "
            "WHERE c.user_id = %s "
            "GROUP BY c.id, c.name "
            "HAVING total > 0 "
            "ORDER BY total DESC",
            (first, next_first, user_id),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def recent_expenses(user_id: int, limit: int = 5):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT e.id, e.amount, e.date, e.note, "
            "       c.name AS category_name "
            "FROM expenses e "
            "JOIN categories c ON c.id = e.category_id "
            "WHERE e.user_id = %s "
            "ORDER BY e.date DESC, e.id DESC "
            "LIMIT %s",
            (user_id, limit),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
