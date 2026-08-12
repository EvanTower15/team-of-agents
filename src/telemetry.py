"""
src/telemetry.py — real per-call token accounting for every Groq request.

Why this exists: until now the only cost number in this project came from
`CostCalculator.estimate_tokens`, a chars/4 heuristic applied to the user's
question and the final synthesized answer. That misses the router, the planner,
every specialist draft, every tool round, the constraint extractions, and the
compliance check — i.e. most of the work. A four-specialist TEAM question is
12–18 model calls; the heuristic priced roughly one of them.

Groq returns exact counts on every response, and LangChain surfaces them as
``response.usage_metadata``. This module attaches a callback that records them,
so the question "what does a TEAM question actually cost?" has an answer taken
from the provider rather than inferred from string length.

It also records what the heuristic could never see:

* **Latency per call**, so slow stages are identifiable rather than guessed at.
* **Throttling — which does NOT arrive as an error.** Groq's free tier caps
  `gpt-oss-120b` at 8,000 tokens/minute, and a single specialist question
  already exceeds that. But the SDK absorbs the retry below the callback layer,
  so the request eventually *succeeds*: `on_llm_error` never fires and the 429
  count stays at zero. Measured: a three-specialist TEAM question took 204s
  with **zero** recorded rate-limit errors while individual calls took 30s+.
  **Latency is the only observable signature**, which is why `SLOW_CALL_MS`
  exists and why the UI reports "throttled calls" rather than "429s". Plotting
  tokens/minute against the ceiling is what turns "it froze" into "it was
  throttled, here is the evidence".

Design constraints this respects:

* **Never breaks a request.** Every hook is wrapped; a telemetry failure must
  not fail a consult. Same convention as the agents, which return errors in a
  field rather than raising.
* **Its own table, its own module.** `src/database.py` (D31) owns conversation
  persistence. This writes to `llm_calls` in the same SQLite file via plain
  sqlite3, so the two never contend over schema ownership.
* **Best-effort, not authoritative.** If a provider stops returning usage
  metadata the row records nulls rather than a fabricated estimate — the same
  reason `compliance_check` distinguishes "could not check" from "clean".

Extended 2026-08-08 for monetization (D32/D34), keeping all of the above:

* **Rows carry money.** `cost_usd` is priced at insert from
  `business.pricing`, so a row reflects the rate in force when it was made
  rather than being repriced retroactively when Groq changes its list. A call
  with no usage metadata gets NULL, never 0.0 — an unmeasured call has to stay
  distinguishable from a free one or every average drifts toward optimism.
* **Rows carry an owner.** `user_id` / `session_id` make per-user
  cost-to-serve and quota enforcement possible. Attribution moved from a module
  global to ContextVars for this: a raced stage label mislabels a chart, but a
  raced user label invoices the wrong customer. Unattributed rows are reported
  as `(unattributed)` rather than dropped, so per-user totals always reconcile
  with `summary()`.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from src.business.pricing import price_call

_REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _REPO_ROOT / "data" / "chat_history.db"

# Groq free-tier ceiling for gpt-oss-120b, in tokens per minute. This is the
# limit that actually bites during a TEAM question -- the 200k/day cap is the
# one everyone notices, but per-minute is what stalls a live demo.
TPM_LIMIT_120B = 8000

# Groq free-tier DAILY token cap. Verified against console.groq.com/docs/rate-limits
# and independently by this team hitting it more than once during testing.
#
# TPM and TPD constrain different things and it is worth keeping them straight:
#   TPM (8,000/min)     -> why ONE question is slow. A TEAM question needs 4.8
#                          minutes of budget, so Groq stalls it. A latency problem.
#   TPD (200,000/day)   -> how many questions exist per day at all. ~5 TEAM
#                          questions and the account is done until tomorrow.
#                          A volume problem, and the one that caps the business.
# The per-minute limit is what breaks a live demo; the daily limit is what makes
# the free tier unable to host paying customers.
TPD_LIMIT = 200_000

# A call taking longer than this is almost certainly being throttled rather than
# thinking. Measured baseline: an unthrottled specialist consult returns in
# ~1-4s; under throttling the same call takes 30s+.
#
# This threshold exists because counting 429s does NOT detect Groq throttling.
# The SDK retries below the callback layer, so the request eventually SUCCEEDS
# and on_llm_error never fires -- a measured four-specialist TEAM question took
# 204s with ZERO recorded rate-limit errors while individual calls took 30s+.
# Latency is the only observable signature we get.
SLOW_CALL_MS = 10_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT    NOT NULL,
    node           TEXT,              -- which pipeline stage made the call
    model          TEXT,
    input_tokens   INTEGER,           -- NULL when the provider returned none
    output_tokens  INTEGER,
    total_tokens   INTEGER,
    latency_ms     INTEGER,
    ok             INTEGER NOT NULL,  -- 1 success, 0 error
    error_type     TEXT,              -- e.g. RateLimitError
    is_rate_limit  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL,              -- NULL when usage was unavailable (D32)
    user_id        TEXT,              -- who to bill; NULL = unattributed (D34)
    session_id     TEXT               -- which conversation, for per-chat cost
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls (created_at);
"""

# Columns added after the table first shipped (2026-08-08). SQLite has no
# `ADD COLUMN IF NOT EXISTS`, so they are applied against a live PRAGMA read.
# Without this, anyone with an existing chat_history.db keeps the old 11-column
# table and every INSERT below fails -- silently, because record_call swallows.
_MIGRATIONS = {
    "cost_usd": "ALTER TABLE llm_calls ADD COLUMN cost_usd REAL",
    "user_id": "ALTER TABLE llm_calls ADD COLUMN user_id TEXT",
    "session_id": "ALTER TABLE llm_calls ADD COLUMN session_id TEXT",
}

# Indexes over migrated columns MUST run after _MIGRATIONS, never inside
# _SCHEMA. On a database that already has llm_calls, `CREATE TABLE IF NOT
# EXISTS` is a no-op, so the column does not exist yet and the CREATE INDEX
# raises `no such column` -- which record_call would then swallow, leaving the
# table permanently un-migrated and every insert failing in silence.
_POST_MIGRATION_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_user ON llm_calls (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls (session_id)",
)

_lock = threading.Lock()
_initialised = False

# Attribution for calls happening right now. LangChain callbacks don't know
# which orchestrator node invoked them, and threading a parameter through every
# call site would touch the frozen agent contract (PROJECT_PLAN §5.2), so the
# stage label is set out-of-band by the orchestrator around each node.
#
# These are ContextVars, not module globals (D34). The original `_current_node`
# global was a deliberate, documented tradeoff and it is fine for stage labels:
# two concurrent users racing over a label mislabels a chart. It is NOT fine for
# `_current_user` -- Streamlit serves every browser session on its own thread,
# and a racing global there would invoice user A for user B's tokens. ContextVars
# are per-thread, so concurrent requests attribute independently.
#
# Deliberate consequence: a callback fired from a worker thread that never had
# these set records NULL rather than inheriting another request's identity.
# Unattributed is recoverable; misattributed billing is not.
_current_node: ContextVar[str] = ContextVar("telemetry_node", default="unknown")
_current_user: ContextVar[str | None] = ContextVar("telemetry_user", default=None)
_current_session: ContextVar[str | None] = ContextVar("telemetry_session", default=None)


def set_node(name: str) -> None:
    """Label subsequent LLM calls with the pipeline stage making them."""
    _current_node.set(name or "unknown")


def set_user(user_id: str | None, session_id: str | None = None) -> None:
    """Attribute subsequent LLM calls to a user (and optionally a chat session).

    Called once per request by the UI before the orchestrator runs. Everything
    downstream on this thread bills to that user with no further plumbing.
    """
    _current_user.set(user_id)
    if session_id is not None:
        _current_session.set(session_id)


@contextmanager
def attributed_to(user_id: str | None, session_id: str | None = None):
    """Scope attribution to a block, restoring whatever was set before.

    Preferred over bare `set_user` where the caller is not the whole request --
    tests and the CLI use it so one metered run cannot leak its identity into
    the next.
    """
    utoken = _current_user.set(user_id)
    stoken = _current_session.set(session_id)
    try:
        yield
    finally:
        _current_user.reset(utoken)
        _current_session.reset(stoken)


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if not _initialised:
        conn.executescript(_SCHEMA)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
        for column, ddl in _MIGRATIONS.items():
            if column not in existing:
                conn.execute(ddl)
        for ddl in _POST_MIGRATION_INDEXES:
            conn.execute(ddl)
        conn.commit()
        _initialised = True
    return conn


def record_call(
    *,
    node: str,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    ok: bool,
    error_type: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Write one call row. Never raises -- telemetry must not break a consult.

    `cost_usd` is computed here rather than at read time so a row is priced at
    the rate in force when it was made; repricing history retroactively after a
    Groq price change would quietly rewrite last month's reported margin.
    """
    try:
        total = None
        if input_tokens is not None or output_tokens is not None:
            total = (input_tokens or 0) + (output_tokens or 0)
        is_rl = bool(error_type and "ratelimit" in error_type.replace("_", "").lower())
        # None (not 0.0) when the provider reported no usage -- an unmeasured
        # call must stay distinguishable from a genuinely free one.
        cost = price_call(model, input_tokens, output_tokens)
        with _lock:
            conn = _connect()
            conn.execute(
                "INSERT INTO llm_calls (created_at, node, model, input_tokens,"
                " output_tokens, total_tokens, latency_ms, ok, error_type,"
                " is_rate_limit, cost_usd, user_id, session_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    node,
                    model,
                    input_tokens,
                    output_tokens,
                    total,
                    latency_ms,
                    1 if ok else 0,
                    error_type,
                    1 if is_rl else 0,
                    cost,
                    user_id,
                    session_id,
                ),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass  # a telemetry write must never surface to the user


class UsageCallback(BaseCallbackHandler):
    """Records real token usage, latency, and failures for every LLM call.

    Attached to the shared ChatGroq clients in rag_core, so it covers the
    router, planner, specialists, tool rounds, constraint extraction, the peer
    back-channel, synthesis, and the compliance check without any of them
    knowing it exists.
    """

    def __init__(self) -> None:
        self._starts: dict[str, float] = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        try:
            self._starts[str(run_id)] = time.perf_counter()
        except Exception:
            pass

    def _elapsed_ms(self, run_id) -> int | None:
        t0 = self._starts.pop(str(run_id), None)
        return int((time.perf_counter() - t0) * 1000) if t0 else None

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        latency = self._elapsed_ms(run_id)
        inp = out = None
        model = None
        try:
            # LangChain exposes provider counts in two places depending on
            # version and provider; prefer the normalised one, fall back to raw.
            usage = (response.llm_output or {}).get("token_usage") if response.llm_output else None
            if not usage:
                for gen_list in response.generations or []:
                    for gen in gen_list:
                        msg = getattr(gen, "message", None)
                        um = getattr(msg, "usage_metadata", None)
                        if um:
                            inp = um.get("input_tokens")
                            out = um.get("output_tokens")
                            break
                    if inp is not None:
                        break
            else:
                inp = usage.get("prompt_tokens")
                out = usage.get("completion_tokens")
            model = (response.llm_output or {}).get("model_name") if response.llm_output else None
        except Exception:
            pass
        record_call(
            node=_current_node.get(), model=model, input_tokens=inp,
            output_tokens=out, latency_ms=latency, ok=True,
            user_id=_current_user.get(), session_id=_current_session.get(),
        )

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        record_call(
            node=_current_node.get(), model=None, input_tokens=None,
            output_tokens=None, latency_ms=self._elapsed_ms(run_id), ok=False,
            error_type=type(error).__name__,
            user_id=_current_user.get(), session_id=_current_session.get(),
        )


# ── read side, for the Observability tab ─────────────────────────────────────

def _query(sql: str, params: tuple = ()) -> list[tuple]:
    try:
        conn = _connect()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _projected_cost_sql() -> str:
    """SQL expression projecting each row onto the production stack (D35).

    Generated from `pricing.PRODUCTION_STACK` rather than written out, so the
    scenario is defined in exactly one place and a rate change cannot leave a
    hand-written CASE behind. NULL in, NULL out: a row with no usage metadata
    projects to NULL, never 0.0, matching how `cost_usd` treats the same case.
    """
    from src.business import pricing

    branches = []
    for measured_model, rate in pricing.PRODUCTION_STACK.items():
        branches.append(
            f"WHEN model = '{measured_model}' THEN"
            f" (COALESCE(input_tokens,0) * {rate.input} / 1000000.0)"
            f" + (COALESCE(output_tokens,0) * {rate.output} / 1000000.0)"
        )
    fallback = pricing._PRODUCTION_FALLBACK
    return (
        "CASE WHEN input_tokens IS NULL AND output_tokens IS NULL THEN NULL "
        + " ".join(branches)
        + f" ELSE (COALESCE(input_tokens,0) * {fallback.input} / 1000000.0)"
        f" + (COALESCE(output_tokens,0) * {fallback.output} / 1000000.0) END"
    )


def summary() -> dict:
    """Totals since the table was created."""
    rows = _query(
        "SELECT COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(SUM(is_rate_limit),0),"
        " COALESCE(AVG(latency_ms),0),"
        " COALESCE(SUM(CASE WHEN latency_ms > ? THEN 1 ELSE 0 END),0),"
        " COALESCE(SUM(cost_usd),0),"
        f" COALESCE(SUM({_projected_cost_sql()}),0)"
        " FROM llm_calls",
        (SLOW_CALL_MS,),
    )
    if not rows:
        return {"calls": 0, "tokens": 0, "rate_limits": 0, "avg_latency_ms": 0,
                "throttled": 0, "cost_usd": 0.0, "projected_usd": 0.0}
    calls, tokens, rls, avg, slow, cost, projected = rows[0]
    return {
        "calls": calls or 0,
        "tokens": tokens or 0,
        "rate_limits": rls or 0,   # explicit 429s -- usually 0, see SLOW_CALL_MS
        "avg_latency_ms": int(avg or 0),
        "throttled": slow or 0,    # the metric that actually detects throttling
        "cost_usd": float(cost or 0.0),
        "projected_usd": float(projected or 0.0),
    }


def by_node() -> list[dict]:
    """Per-stage totals -- which architectural decision costs what."""
    rows = _query(
        "SELECT node, COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(AVG(latency_ms),0),"
        " COALESCE(SUM(is_rate_limit),0),"
        " COALESCE(SUM(CASE WHEN latency_ms > ? THEN 1 ELSE 0 END),0),"
        " COALESCE(SUM(cost_usd),0),"
        f" COALESCE(SUM({_projected_cost_sql()}),0)"
        " FROM llm_calls GROUP BY node ORDER BY SUM(total_tokens) DESC",
        (SLOW_CALL_MS,),
    )
    return [
        {"node": r[0], "calls": r[1], "tokens": r[2],
         "avg_latency_ms": int(r[3] or 0), "rate_limits": r[4],
         "throttled": r[5] or 0, "cost_usd": float(r[6] or 0.0),
         "projected_usd": float(r[7] or 0.0)}
        for r in rows
    ]


# ── billing read side (D34) ──────────────────────────────────────────────────
#
# These exist so the business layer never re-derives cost from string length.
# `cost_usd` is summed straight out of the rows Groq's own counts produced.


def session_cost(session_id: str) -> dict:
    """Real metered cost and tokens for one conversation.

    Replaces `CostCalculator.calculate_query_cost` as the number the UI shows
    for a chat: that estimated from the visible question and answer only, and
    priced at a retired model's rates (D32).
    """
    rows = _query(
        "SELECT COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(SUM(cost_usd),0),"
        f" COALESCE(SUM({_projected_cost_sql()}),0)"
        " FROM llm_calls WHERE session_id = ?",
        (session_id,),
    )
    calls, tokens, cost, projected = rows[0] if rows else (0, 0, 0.0, 0.0)
    return {
        "calls": calls or 0,
        "tokens": tokens or 0,
        "cost_usd": float(cost or 0.0),
        "projected_usd": float(projected or 0.0),
    }


def user_usage(user_id: str, since: str | None = None) -> dict:
    """One user's metered consumption, optionally from an ISO timestamp.

    `since` is how a billing period is expressed -- pass the period start and
    the numbers are that period's, which is what quota enforcement needs.
    `questions` counts distinct chat sessions touched, not model calls.
    """
    where = "WHERE user_id = ?"
    params: tuple = (user_id,)
    if since:
        where += " AND created_at >= ?"
        params = (user_id, since)

    rows = _query(
        f"SELECT COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(SUM(cost_usd),0),"
        f" COALESCE(SUM(CASE WHEN latency_ms > ? THEN 1 ELSE 0 END),0),"
        f" COALESCE(SUM({_projected_cost_sql()}),0)"
        f" FROM llm_calls {where}",
        (SLOW_CALL_MS,) + params,
    )
    calls, tokens, cost, throttled, projected = (
        rows[0] if rows else (0, 0, 0.0, 0, 0.0)
    )
    return {
        "calls": calls or 0,
        "tokens": tokens or 0,
        "cost_usd": float(cost or 0.0),
        "throttled": throttled or 0,
        "projected_usd": float(projected or 0.0),
    }


def cost_by_user(since: str | None = None, limit: int = 100) -> list[dict]:
    """Per-user cost-to-serve, dearest first -- the dashboard's margin table.

    Rows with a NULL user_id are real calls that ran outside an attributed
    request (CLI runs, tests, anything before login shipped). They are returned
    under the label "(unattributed)" rather than dropped, so total cost on this
    table always reconciles with `summary()`.
    """
    where = "WHERE created_at >= ?" if since else ""
    params: tuple = (since,) if since else ()
    rows = _query(
        f"SELECT COALESCE(user_id,'(unattributed)'), COUNT(*),"
        f" COALESCE(SUM(total_tokens),0), COALESCE(SUM(cost_usd),0),"
        f" COUNT(DISTINCT session_id)"
        f" FROM llm_calls {where}"
        f" GROUP BY user_id ORDER BY SUM(cost_usd) DESC LIMIT ?",
        params + (limit,),
    )
    return [
        {"user_id": r[0], "calls": r[1], "tokens": r[2],
         "cost_usd": float(r[3] or 0.0), "sessions": r[4] or 0}
        for r in rows
    ]


def unpriced_calls() -> int:
    """Successful calls carrying no cost -- i.e. the provider returned no usage.

    Surfaced in the dashboard so "cost looks low" can be checked against "cost
    was measurable" rather than assumed.
    """
    rows = _query("SELECT COUNT(*) FROM llm_calls WHERE ok = 1 AND cost_usd IS NULL")
    return rows[0][0] if rows else 0


def tokens_per_minute(limit: int = 30) -> list[dict]:
    """Token volume bucketed by minute, for plotting against TPM_LIMIT_120B."""
    rows = _query(
        "SELECT substr(created_at,1,16) AS minute, COALESCE(SUM(total_tokens),0),"
        " COALESCE(SUM(is_rate_limit),0) FROM llm_calls"
        " GROUP BY minute ORDER BY minute DESC LIMIT ?",
        (limit,),
    )
    return [{"minute": r[0], "tokens": r[1], "rate_limits": r[2]} for r in reversed(rows)]


def recent_calls(limit: int = 25) -> list[dict]:
    rows = _query(
        "SELECT created_at, node, model, input_tokens, output_tokens, latency_ms,"
        " ok, error_type FROM llm_calls ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [
        {"created_at": r[0], "node": r[1], "model": r[2], "input_tokens": r[3],
         "output_tokens": r[4], "latency_ms": r[5], "ok": bool(r[6]), "error_type": r[7]}
        for r in rows
    ]
