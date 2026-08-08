"""
src/auth.py — accounts, password auth, and roles.

This project is coursework and nobody is actually charged. The point of this
module is that every mechanism a paid product needs is genuinely present and
wired to real data — accounts, hashed credentials, a role split between the
customer app and the business console, and a plan attached to each user that
`business/plans.py` meters against. What is absent is the payment processor,
and only that.

**Honest scope statement** (this project has a standing convention of not
overclaiming — see D13, D23, D26, D30). This is real password authentication,
not a mock: passwords are salted and hashed with scrypt and never stored or
logged in the clear, and comparison is constant-time. It is nonetheless NOT
production-grade auth, and the gaps are deliberate rather than overlooked:

    * no email verification, password reset, or account recovery
    * no rate limiting or lockout on repeated failed logins
    * no session tokens or expiry — Streamlit's server-side `session_state`
      holds the logged-in user for the life of the browser session
    * no TLS assumption; a real deployment must terminate HTTPS in front

Do not reuse this as-is for anything handling real credentials.

Why stdlib scrypt and not bcrypt/passlib/streamlit-authenticator: this project
has already had to reject a dependency (`llm-guard`) for downgrading
`transformers` and breaking MiniLM retrieval for all four agents. `hashlib`
ships with Python, adds nothing to requirements.txt, and scrypt is a memory-hard
KDF designed for exactly this. The tradeoff is that we hand-roll the encoding
format, which is ~15 lines and covered by tests.

Storage: a `users` table on `database.py`'s SQLAlchemy Base, so accounts live in
the same SQLite file as conversations and telemetry and a per-user cost query is
a plain join rather than a cross-store reconciliation.

Public API:
    init_auth(db_url)                    -> Engine   (idempotent; migrates too)
    hash_password(pw)                    -> str
    verify_password(pw, stored)          -> bool
    create_user(email, pw, ...)          -> User
    authenticate(email, pw)              -> User | None
    get_user(user_id) / get_user_by_email(email)
    list_users()                         -> list[User]
    set_plan(user_id, plan_id)           -> bool
    set_role(user_id, role)              -> bool
    seed_demo_users()                    -> list[tuple[str, str, str]]
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.database import DEFAULT_DB_URL, Base, _engine_for, _utcnow

# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────

# scrypt cost parameters. n=2**14 with r=8/p=1 needs ~16 MB and ~50-100 ms per
# hash on a laptop -- slow enough to make offline guessing expensive, fast
# enough that a login does not feel broken. `maxmem` is set explicitly because
# OpenSSL's default (32 MB) is uncomfortably close to what these params need.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_KEY_LEN = 32

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ROLES = ("user", "admin")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    """Salt and hash a password. Returns a self-describing string.

    Format: ``scrypt$<n>$<r>$<p>$<salt_b64>$<key_b64>``. The parameters are
    stored alongside the hash so raising the cost later does not invalidate
    existing accounts — `verify_password` reads whatever each row was made
    with, rather than assuming today's constants.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_KEY_LEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check of a password against a stored hash.

    Never raises on malformed input — a corrupt or empty hash is a failed
    login, not a 500. Returns False rather than propagating so a bad row in the
    database cannot take the login page down.
    """
    if not password or not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            maxmem=_SCRYPT_MAXMEM,
            dklen=len(_unb64(key_b64)),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(candidate, _unb64(key_b64))


# ─────────────────────────────────────────────────────────────────────────────
# Model
# ─────────────────────────────────────────────────────────────────────────────


class User(Base):
    """One account.

    `plan_id` is a soft reference to `business.plans.PLANS` rather than a
    foreign key to a plans table: plans are code-defined pricing config that
    changes with a deploy, not user data. Storing the id keeps a user pinned to
    the plan they signed up on even if the catalogue is edited.

    `role` gates the business dashboard. Two values only ("user", "admin") —
    a full permission system is not what this demonstrates.
    """

    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    plan_id = Column(String, nullable=False, default="free")
    created_at = Column(DateTime, default=_utcnow)
    last_login_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# Chat sessions predate accounts (D31), so the column linking them to an owner
# has to be added to an existing table. SQLAlchemy's create_all only creates
# missing tables -- it never alters an existing one -- so this is explicit.
_SESSION_MIGRATIONS = {
    "user_id": "ALTER TABLE chat_sessions ADD COLUMN user_id TEXT",
}


def init_auth(db_url: str = DEFAULT_DB_URL) -> Engine:
    """Create the users table, migrate chat_sessions, return the engine.

    Idempotent and safe to call on every Streamlit rerun. Calls create_all
    directly rather than relying on database.init_db having imported this
    module, so the users table exists regardless of import order.
    """
    engine = _engine_for(db_url)
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        existing = {
            row[1] for row in conn.execute(text("PRAGMA table_info(chat_sessions)"))
        }
        if existing:  # empty tuple => table absent; create_all will have made it
            for column, ddl in _SESSION_MIGRATIONS.items():
                if column not in existing:
                    conn.execute(text(ddl))
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# Accounts
# ─────────────────────────────────────────────────────────────────────────────


def create_user(
    email: str,
    password: str,
    *,
    display_name: str | None = None,
    role: str = "user",
    plan_id: str = "free",
    db_url: str = DEFAULT_DB_URL,
) -> User:
    """Register an account. Raises ValueError on bad input or duplicate email.

    Email is lower-cased and stripped before storage and lookup, so
    "Evan@X.com " and "evan@x.com" are the same account rather than two.
    """
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")

    init_auth(db_url)
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        if s.scalar(select(User).where(User.email == email)):
            raise ValueError("An account with that email already exists.")
        user = User(
            user_id=uuid.uuid4().hex,
            email=email,
            display_name=(display_name or email.split("@")[0]).strip(),
            password_hash=hash_password(password),
            role=role,
            plan_id=plan_id,
        )
        s.add(user)
        s.commit()
        s.expunge(user)
        return user


def authenticate(
    email: str, password: str, *, db_url: str = DEFAULT_DB_URL
) -> User | None:
    """Return the user on a correct password, else None.

    Deliberately does not distinguish "no such account" from "wrong password"
    to the caller, so the UI cannot leak which emails are registered. The
    password is still verified against a dummy hash when the account is missing,
    so the two paths take comparable time and absence is not detectable by
    response latency.
    """
    email = (email or "").strip().lower()
    init_auth(db_url)
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        user = s.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            # Burn comparable time so a missing account is not timing-visible.
            verify_password(password or "x", _DUMMY_HASH)
            return None
        if not verify_password(password, user.password_hash):
            return None
        user.last_login_at = _utcnow()
        s.commit()
        s.expunge(user)
        return user


# Computed once at import: a real scrypt hash of a random value, used only to
# equalise the timing of a failed lookup against a failed password check.
_DUMMY_HASH = hash_password(uuid.uuid4().hex)


def get_user(user_id: str, *, db_url: str = DEFAULT_DB_URL) -> User | None:
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        user = s.get(User, user_id)
        if user is not None:
            s.expunge(user)
        return user


def get_user_by_email(email: str, *, db_url: str = DEFAULT_DB_URL) -> User | None:
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        user = s.scalar(select(User).where(User.email == (email or "").strip().lower()))
        if user is not None:
            s.expunge(user)
        return user


def list_users(*, db_url: str = DEFAULT_DB_URL) -> list[User]:
    """All accounts, newest first — the dashboard's user table."""
    init_auth(db_url)
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        rows = list(s.scalars(select(User).order_by(User.created_at.desc())))
        s.expunge_all()
        return rows


def set_plan(user_id: str, plan_id: str, *, db_url: str = DEFAULT_DB_URL) -> bool:
    """Move a user onto a different plan. Returns False if they don't exist."""
    with Session(_engine_for(db_url)) as s:
        user = s.get(User, user_id)
        if user is None:
            return False
        user.plan_id = plan_id
        s.commit()
        return True


def set_role(user_id: str, role: str, *, db_url: str = DEFAULT_DB_URL) -> bool:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    with Session(_engine_for(db_url)) as s:
        user = s.get(User, user_id)
        if user is None:
            return False
        user.role = role
        s.commit()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Demo seeding
# ─────────────────────────────────────────────────────────────────────────────

# Credentials are in source on purpose: nobody is charged, the graders and
# teammates need to get in, and there is no real data behind them. A deployment
# handling anything real must delete these.
DEMO_ACCOUNTS = [
    ("demo@recoveryteam.app", "recovery2026", "user", "free", "Demo Patient"),
    ("paid@recoveryteam.app", "recovery2026", "user", "recovery", "Paid Patient"),
    ("admin@recoveryteam.app", "recovery2026", "admin", "clinic", "Business Admin"),
]


def seed_demo_users(*, db_url: str = DEFAULT_DB_URL) -> list[tuple[str, str, str]]:
    """Create the demo accounts if absent. Returns (email, password, role).

    Idempotent: an existing email is left exactly as-is, so a demo account
    whose plan was changed during a presentation is not silently reset on the
    next app start.
    """
    created = []
    init_auth(db_url)
    for email, password, role, plan, name in DEMO_ACCOUNTS:
        if get_user_by_email(email, db_url=db_url) is None:
            create_user(
                email,
                password,
                display_name=name,
                role=role,
                plan_id=plan,
                db_url=db_url,
            )
            created.append((email, password, role))
    return created
