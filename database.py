"""SQLite persistence for ClearMind accounts and signed-in prompt history."""

import re
import sqlite3
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash


# Vercel mounts the deployed application as read-only. Its temporary directory
# is writable for a single function instance, while local development keeps the
# database next to the source file. A custom path can be supplied for another
# persistent host or database volume.
_default_database_path = (
    Path(tempfile.gettempdir()) / "clearmind.db"
    if os.environ.get("VERCEL")
    else Path(__file__).with_name("clearmind.db")
)
DATABASE_PATH = Path(os.environ.get("CLEARMIND_DATABASE_PATH", _default_database_path))
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@contextmanager
def connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> None:
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_prompts_user_created
                ON prompts(user_id, id DESC);
        """)


def create_user(name: str, email: str, password: str) -> dict:
    name = name.strip()
    email = email.strip().lower()
    if not name or len(name) > 100:
        raise ValueError("Please enter a name of up to 100 characters.")
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Please enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    try:
        with connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            return {"id": cursor.lastrowid, "name": name, "email": email}
    except sqlite3.IntegrityError as error:
        raise ValueError("An account already exists for that email address.") from error


def authenticate_user(email: str, password: str) -> Optional[dict]:
    with connection() as conn:
        user = conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return None
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


def save_prompt(user_id: int, session_id: str, prompt: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO prompts (user_id, session_id, prompt) VALUES (?, ?, ?)",
            (user_id, session_id, prompt),
        )


def get_prompts(user_id: int) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, prompt, session_id, created_at FROM prompts "
            "WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]
