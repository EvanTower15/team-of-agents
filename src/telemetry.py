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
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

_REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _REPO_ROOT / "data" / "chat_history.db"

# Groq free-tier ceiling for gpt-oss-120b, in tokens per minute. This is the
# limit that actually bites during a TEAM question -- the 200k/day cap is the
# one everyone notices, but per-minute is what stalls a live demo.
TPM_LIMIT_120B = 8000

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
    is_rate_limit  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls (created_at);
"""

_lock = threading.Lock()
_initialised = False

# The node label for calls happening right now. LangChain callbacks don't know
# which orchestrator node invoked them, and threading a parameter through every
# call site would touch the frozen agent contract (PROJECT_PLAN §5.2). A module
# level label set by the orchestrator around each stage is the smaller change.
_current_node = "unknown"


def set_node(name: str) -> None:
    """Label subsequent LLM calls with the pipeline stage making them."""
    global _current_node
    _current_node = name or "unknown"


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if not _initialised:
        conn.executescript(_SCHEMA)
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
) -> None:
    """Write one call row. Never raises -- telemetry must not break a consult."""
    try:
        total = None
        if input_tokens is not None or output_tokens is not None:
            total = (input_tokens or 0) + (output_tokens or 0)
        is_rl = bool(error_type and "ratelimit" in error_type.replace("_", "").lower())
        with _lock:
            conn = _connect()
            conn.execute(
                "INSERT INTO llm_calls (created_at, node, model, input_tokens,"
                " output_tokens, total_tokens, latency_ms, ok, error_type, is_rate_limit)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
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
            node=_current_node, model=model, input_tokens=inp, output_tokens=out,
            latency_ms=latency, ok=True,
        )

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        record_call(
            node=_current_node, model=None, input_tokens=None, output_tokens=None,
            latency_ms=self._elapsed_ms(run_id), ok=False,
            error_type=type(error).__name__,
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


def summary() -> dict:
    """Totals since the table was created."""
    rows = _query(
        "SELECT COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(SUM(is_rate_limit),0),"
        " COALESCE(AVG(latency_ms),0),"
        " COALESCE(SUM(CASE WHEN latency_ms > ? THEN 1 ELSE 0 END),0)"
        " FROM llm_calls",
        (SLOW_CALL_MS,),
    )
    if not rows:
        return {"calls": 0, "tokens": 0, "rate_limits": 0, "avg_latency_ms": 0, "throttled": 0}
    calls, tokens, rls, avg, slow = rows[0]
    return {
        "calls": calls or 0,
        "tokens": tokens or 0,
        "rate_limits": rls or 0,   # explicit 429s -- usually 0, see SLOW_CALL_MS
        "avg_latency_ms": int(avg or 0),
        "throttled": slow or 0,    # the metric that actually detects throttling
    }


def by_node() -> list[dict]:
    """Per-stage totals -- which architectural decision costs what."""
    rows = _query(
        "SELECT node, COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(AVG(latency_ms),0),"
        " COALESCE(SUM(is_rate_limit),0),"
        " COALESCE(SUM(CASE WHEN latency_ms > ? THEN 1 ELSE 0 END),0)"
        " FROM llm_calls GROUP BY node ORDER BY SUM(total_tokens) DESC",
        (SLOW_CALL_MS,),
    )
    return [
        {"node": r[0], "calls": r[1], "tokens": r[2],
         "avg_latency_ms": int(r[3] or 0), "rate_limits": r[4],
         "throttled": r[5] or 0}
        for r in rows
    ]


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
