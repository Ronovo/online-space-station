"""SQLite storage: accounts and each account's single character save."""

import datetime
import json
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    portfolio_sub TEXT UNIQUE,
    security_question TEXT,
    security_answer_hash TEXT,
    reset_failures INTEGER NOT NULL DEFAULT 0,
    reset_locked_until REAL NOT NULL DEFAULT 0
);

-- user_id is the primary key, so an account can never hold two characters.
CREATE TABLE IF NOT EXISTS characters (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    player_data TEXT NOT NULL,
    ui_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        # isolation_level=None: transactions are opened explicitly with BEGIN IMMEDIATE.
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db = get_db()
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        close_db()


def create_user(username, password_hash, portfolio_sub=None):
    """Insert an account. Returns the new id, or None if the username (or portfolio account) is taken."""
    try:
        cursor = get_db().execute(
            "INSERT INTO users (username, password_hash, created_at, portfolio_sub) VALUES (?, ?, ?, ?)",
            (username, password_hash, _now(), portfolio_sub),
        )
    except sqlite3.IntegrityError:
        return None
    return cursor.lastrowid


def get_user_by_name(username):
    return get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def set_security_question(user_id, question, answer_hash):
    get_db().execute("UPDATE users SET security_question = ?, security_answer_hash = ? WHERE id = ?",
                     (question, answer_hash, user_id))


def get_reset_user(username):
    """An account that has a security question, with its reset bookkeeping, or None."""
    return get_db().execute(
        "SELECT * FROM users WHERE username = ? AND security_answer_hash IS NOT NULL", (username,)
    ).fetchone()


def count_reset_try(user_id, now):
    """Counts one more reset try and returns the count so far, or None while resets are locked. It is one
    statement, so tries sent at the same moment each get their own count."""
    row = get_db().execute("""UPDATE users SET reset_failures = reset_failures + 1
                              WHERE id = ? AND reset_locked_until <= ? RETURNING reset_failures""",
                           (user_id, now)).fetchone()
    return row[0] if row else None


def lock_resets(user_id, until):
    get_db().execute("UPDATE users SET reset_failures = 0, reset_locked_until = ? WHERE id = ?", (until, user_id))


def set_password(user_id, password_hash):
    get_db().execute(
        "UPDATE users SET password_hash = ?, reset_failures = 0, reset_locked_until = 0 WHERE id = ?",
        (password_hash, user_id),
    )


def get_user_by_portfolio(sub):
    return get_db().execute("SELECT * FROM users WHERE portfolio_sub = ?", (sub,)).fetchone()


def link_portfolio(user_id, sub):
    """Links an account to a portfolio account. False when either one is already linked."""
    try:
        return get_db().execute("UPDATE users SET portfolio_sub = ? WHERE id = ? AND portfolio_sub IS NULL",
                                (sub, user_id)).rowcount == 1
    except sqlite3.IntegrityError:
        return False


def load_save(user_id):
    """The account's save and when it was last written, or (None, None) before it has one."""
    row = get_db().execute("SELECT player_data, updated_at FROM characters WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None, None
    return json.loads(row["player_data"]), row["updated_at"]


def ensure_save(user_id, save, ui_state):
    """Give the account its save if it doesn't have one yet."""
    now = _now()
    get_db().execute(
        "INSERT OR IGNORE INTO characters (user_id, player_data, ui_state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, json.dumps(save), json.dumps(ui_state), now, now),
    )


def delete_character(user_id):
    get_db().execute("DELETE FROM characters WHERE user_id = ?", (user_id,))


def update_character(user_id, fn):
    """Load, mutate, and store an account's save atomically.

    fn(save, ui_state) -> (result, save, ui_state). Returns result, or None if
    the account has no save. BEGIN IMMEDIATE serializes concurrent requests
    (e.g. a poll racing a click) so neither overwrites the other's changes.
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            "SELECT player_data, ui_state FROM characters WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            db.execute("ROLLBACK")
            return None
        result, save, ui_state = fn(json.loads(row["player_data"]), json.loads(row["ui_state"]))
        db.execute(
            "UPDATE characters SET player_data = ?, ui_state = ?, updated_at = ? WHERE user_id = ?",
            (json.dumps(save), json.dumps(ui_state), _now(), user_id),
        )
        db.execute("COMMIT")
        return result
    except Exception:
        db.execute("ROLLBACK")
        raise
