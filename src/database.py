"""
src/database.py — multi-session chat persistence (SQLAlchemy + SQLite).

Ported from the opim-5517 HW8 "Relational Persistence" module and extended for
this project's multi-agent answers, so a user can keep several conversations
going and come back to any of them later.

Two tables:

    chat_sessions      one row per conversation (session_id, title, timestamps)
    chat_transcripts   one row per *turn* — the user question, the team's answer,
                       which route fired, which specialists were consulted, the
                       sources/constraints they cited, and token + cost metrics

Design choice — turn-per-row (not message-per-row): one row holds a complete
exchange, which maps 1:1 to what the UI renders for an assistant turn and makes
route/specialist analytics trivial (`GROUP BY route_used`). Chat replay still
works: load a session's transcripts ordered by id.

Design choice — the multi-agent render metadata (`agents_consulted`, `sources`,
`constraints`, `execution_trace`) is stored as JSON text rather than normalized
into child tables. Those fields are display payloads the UI reads back whole and
never joins or filters on, so normalizing them would buy nothing and cost four
more tables; `route_used` and the token/cost columns — the fields we actually
aggregate over — stay first-class typed columns.

SQLite specifics:
    • WAL journal mode      — readers and one writer proceed concurrently instead
                              of SQLite's default whole-database lock, so two
                              browser tabs (two live chats) don't block each other.
    • foreign_keys = ON     — SQLite ignores FKs unless this pragma is set; we turn
                              it on so an orphan transcript is a real error.
Both are applied on every new connection via a `connect` event listener.

Public API:
    init_db()                  -> Engine   (idempotent; creates tables + pragmas)
    create_session()           -> str      (new session_id)
    save_transcript(...)       -> int      (new transcript row id)
    save_result(...)           -> int      (same, from an orchestrator result dict)
    get_session_transcripts()  -> list[ChatTranscript]
    list_sessions()            -> list[ChatSession]
    session_stats()            -> dict     (turns, tokens, cost for one session)
    rename_session()           -> bool
    delete_session()           -> bool
    transcript_meta()          -> dict     (decoded JSON, shaped for the UI)

The DB file defaults to data/chat_history.db (gitignored) but can be overridden
with the CHAT_DB_URL env var — handy for tests and CI.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = REPO_ROOT / "data" / "chat_history.db"

# Absolute sqlite URL (forward slashes, even on Windows) so the DB resolves no
# matter which directory the app/tests run from. Overridable for tests/CI.
DEFAULT_DB_URL = os.getenv("CHAT_DB_URL", f"sqlite:///{_DEFAULT_DB_PATH.as_posix()}")

# How much of the first question becomes the conversation's sidebar title.
TITLE_MAX_CHARS = 60

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# ORM models
# ─────────────────────────────────────────────────────────────────────────────


class ChatSession(Base):
    """One conversation.

    `title` is derived from the first question (or set by the user) so the
    sidebar can list chats by what they're about instead of by uuid.
    `updated_at` is bumped on every saved turn, which is what "most recent
    conversations" sorts on. `user_metadata` is a JSON string (client info, etc.).
    """

    __tablename__ = "chat_sessions"

    session_id = Column(String, primary_key=True)
    title = Column(String)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    user_metadata = Column(Text)  # JSON-encoded dict


class ChatTranscript(Base):
    """One turn: the question, the team's answer, and how it was produced.

    The four JSON-encoded columns mirror the orchestrator's §5.4 result dict, so
    a replayed turn renders with the same specialist badges, sources, binding
    restrictions, and debug trace as a live one.
    """

    __tablename__ = "chat_transcripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String,
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_query = Column(Text, nullable=False)
    agent_response = Column(Text)
    route_used = Column(String)  # TEAM, PT_ONLY, RED_FLAG, CLARIFY, ...
    route_confidence = Column(Float, nullable=True)
    agents_consulted = Column(Text)  # JSON list[str]
    sources = Column(Text)  # JSON dict[agent, list[filename]]
    constraints = Column(Text)  # JSON dict[agent, list[constraint dict]]
    execution_trace = Column(Text)  # JSON list[str]
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Engine / connection setup
# ─────────────────────────────────────────────────────────────────────────────


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL + FK enforcement on each new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache(maxsize=None)
def _engine_for(db_url: str) -> Engine:
    """Build (once per URL) an engine with pragmas set and tables created.

    lru_cache keyed on the URL means Streamlit's per-interaction reruns reuse a
    single engine, while tests that pass a distinct temp-file URL get their own.
    """
    is_sqlite = db_url.startswith("sqlite")
    if is_sqlite:
        # First run on a fresh clone: data/ exists, but don't assume it.
        db_path = db_url.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        db_url,
        # SQLite + Streamlit: the connection may be touched from a different
        # thread than the one that created it, so relax the same-thread check.
        connect_args={"check_same_thread": False} if is_sqlite else {},
        future=True,
    )
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _set_sqlite_pragma)
    Base.metadata.create_all(engine)
    return engine


def init_db(db_url: str = DEFAULT_DB_URL) -> Engine:
    """Create the engine, tables, and pragmas if needed; return the engine.

    Safe to call on every Streamlit rerun — the engine is cached per URL.
    """
    return _engine_for(db_url)


# ─────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ─────────────────────────────────────────────────────────────────────────────


def _dumps(value) -> str:
    """Encode a JSON column, tolerating values that aren't JSON-serializable."""
    try:
        return json.dumps(value if value is not None else None, default=str)
    except (TypeError, ValueError):
        return json.dumps(None)


def _loads(raw: str | None, default):
    """Decode a JSON column, falling back to `default` on NULL or bad JSON."""
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return default if value is None else value


def _derive_title(user_query: str) -> str:
    """Squash the first question into a short sidebar label."""
    text = " ".join((user_query or "").split())
    if not text:
        return "New chat"
    if len(text) <= TITLE_MAX_CHARS:
        return text
    return text[: TITLE_MAX_CHARS - 1].rstrip() + "…"


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────


def create_session(
    user_metadata: dict | None = None,
    *,
    title: str | None = None,
    db_url: str = DEFAULT_DB_URL,
) -> str:
    """Create a new conversation row and return its session_id (uuid4 hex).

    `title` is optional: left None, it is back-filled from the first question
    the session saves (see save_transcript).
    """
    session_id = uuid.uuid4().hex
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        s.add(
            ChatSession(
                session_id=session_id,
                title=title,
                user_metadata=json.dumps(user_metadata or {}),
            )
        )
        s.commit()
    return session_id


def save_transcript(
    session_id: str,
    user_query: str,
    agent_response: str,
    route_used: str | None,
    *,
    route_confidence: float | None = None,
    agents_consulted: list | None = None,
    sources: dict | None = None,
    constraints: dict | None = None,
    execution_trace: list | None = None,
    tokens: dict | None = None,
    cost_usd: float | None = None,
    db_url: str = DEFAULT_DB_URL,
) -> int:
    """Persist one conversation turn; return the new transcript row id.

    Also bumps the parent session's `updated_at` and back-fills its `title` from
    this question if the session doesn't have one yet — both in the same
    transaction as the turn, so the sidebar can never show a session whose
    timestamp disagrees with its transcripts.

    `tokens` is the estimator's dict ({"input_tokens", "output_tokens",
    "total_tokens"}); missing keys default to 0.
    """
    tokens = tokens or {}
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        row = ChatTranscript(
            session_id=session_id,
            user_query=user_query,
            agent_response=agent_response,
            route_used=route_used,
            route_confidence=route_confidence,
            agents_consulted=_dumps(agents_consulted or []),
            sources=_dumps(sources or {}),
            constraints=_dumps(constraints or {}),
            execution_trace=_dumps(execution_trace or []),
            input_tokens=int(tokens.get("input_tokens", 0) or 0),
            output_tokens=int(tokens.get("output_tokens", 0) or 0),
            total_tokens=int(tokens.get("total_tokens", 0) or 0),
            cost_usd=float(cost_usd or 0.0),
        )
        s.add(row)

        # Missing parent => the FK check fails at commit (IntegrityError), which
        # is the behavior we want; just skip the session touch-up in that case.
        parent = s.get(ChatSession, session_id)
        if parent is not None:
            parent.updated_at = _utcnow()
            if not parent.title:
                parent.title = _derive_title(user_query)

        s.commit()
        return row.id


def save_result(
    session_id: str,
    user_query: str,
    result: dict,
    *,
    tokens: dict | None = None,
    cost_usd: float | None = None,
    db_url: str = DEFAULT_DB_URL,
) -> int:
    """Persist a turn straight from an orchestrator §5.4 result dict.

    Keeps knowledge of the result-dict keys in one place instead of spread across
    every caller (app.py, the CLI, tests).
    """
    return save_transcript(
        session_id,
        user_query,
        result.get("final_answer", ""),
        result.get("route"),
        route_confidence=result.get("route_confidence"),
        agents_consulted=result.get("agents_consulted") or [],
        sources=result.get("sources") or {},
        constraints=result.get("constraints") or {},
        execution_trace=result.get("execution_trace") or [],
        tokens=tokens,
        cost_usd=cost_usd,
        db_url=db_url,
    )


def get_session_transcripts(
    session_id: str, *, db_url: str = DEFAULT_DB_URL
) -> list[ChatTranscript]:
    """Return a session's turns in chronological order (detached, read-only)."""
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        rows = list(
            s.scalars(
                select(ChatTranscript)
                .where(ChatTranscript.session_id == session_id)
                .order_by(ChatTranscript.id)
            )
        )
        s.expunge_all()
        return rows


def list_sessions(
    limit: int = 25, *, db_url: str = DEFAULT_DB_URL
) -> list[ChatSession]:
    """Return the most recently *active* sessions first, detached and read-only.

    Sorted on `updated_at` (not `created_at`) so a long-running conversation the
    user keeps returning to stays at the top of the sidebar.
    """
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        rows = list(
            s.scalars(
                select(ChatSession)
                .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
                .limit(limit)
            )
        )
        s.expunge_all()
        return rows


def get_session(session_id: str, *, db_url: str = DEFAULT_DB_URL) -> ChatSession | None:
    """Return one session row (detached), or None if it doesn't exist."""
    with Session(_engine_for(db_url), expire_on_commit=False) as s:
        row = s.get(ChatSession, session_id)
        if row is not None:
            s.expunge(row)
        return row


def session_stats(session_id: str, *, db_url: str = DEFAULT_DB_URL) -> dict:
    """Aggregate one session: turn count, tokens, and estimated Groq spend.

    Lets the sidebar show accumulated cost that survives a page reload, which
    the in-memory BudgetOverrunGuard (src/business/unit_economics.py) can't.
    """
    with Session(_engine_for(db_url)) as s:
        turns, total_tokens, cost = s.execute(
            select(
                func.count(ChatTranscript.id),
                func.coalesce(func.sum(ChatTranscript.total_tokens), 0),
                func.coalesce(func.sum(ChatTranscript.cost_usd), 0.0),
            ).where(ChatTranscript.session_id == session_id)
        ).one()
    return {
        "turns": int(turns or 0),
        "total_tokens": int(total_tokens or 0),
        "cost_usd": float(cost or 0.0),
    }


def rename_session(
    session_id: str, title: str, *, db_url: str = DEFAULT_DB_URL
) -> bool:
    """Set a conversation's sidebar title. Returns False if it doesn't exist."""
    with Session(_engine_for(db_url)) as s:
        row = s.get(ChatSession, session_id)
        if row is None:
            return False
        row.title = _derive_title(title)
        s.commit()
        return True


def delete_session(session_id: str, *, db_url: str = DEFAULT_DB_URL) -> bool:
    """Delete a conversation and its turns. Returns False if it doesn't exist.

    Transcripts are removed explicitly rather than relying on ON DELETE CASCADE,
    so the delete behaves identically even on a connection where the SQLite
    foreign-keys pragma is off.
    """
    with Session(_engine_for(db_url)) as s:
        row = s.get(ChatSession, session_id)
        if row is None:
            return False
        s.execute(
            delete(ChatTranscript).where(ChatTranscript.session_id == session_id)
        )
        s.delete(row)
        s.commit()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Read-side helper for the UI
# ─────────────────────────────────────────────────────────────────────────────


def transcript_meta(transcript: ChatTranscript) -> dict:
    """Decode a transcript's JSON columns into the metadata dict app.py renders.

    Keeps json.loads out of the UI layer and guarantees the keys the renderer
    expects are always present (a missing `route_confidence` would otherwise
    blow up the `:.2f` format in the route chip).
    """
    return {
        "route": transcript.route_used or "?",
        "route_confidence": (
            transcript.route_confidence if transcript.route_confidence is not None else 0.0
        ),
        "agents_consulted": _loads(transcript.agents_consulted, []),
        "sources": _loads(transcript.sources, {}),
        "constraints": _loads(transcript.constraints, {}),
        "execution_trace": _loads(transcript.execution_trace, []),
        "tokens": {
            "input_tokens": transcript.input_tokens or 0,
            "output_tokens": transcript.output_tokens or 0,
            "total_tokens": transcript.total_tokens or 0,
        },
        "cost_usd": transcript.cost_usd or 0.0,
    }
