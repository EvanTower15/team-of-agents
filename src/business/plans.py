"""
src/business/plans.py — pricing tiers, quota enforcement, and billing rollups.

The revenue model is **subscription with an included quota, then metered
overage** — what most real AI products land on, and the one that gives the
business dashboard something to say beyond a headcount.

Nobody is charged. Every number here is computed from real data (metered token
cost from `telemetry.llm_calls`, real accounts from `auth.users`); what is
missing is a payment processor. `record_payment` writes an invoice row exactly
as a Stripe webhook would, so swapping one in is a single call site.

Why a question is the billing unit rather than a token
------------------------------------------------------
Two reasons, one commercial and one that only became visible once real
measurement existed:

1. Patients cannot estimate tokens. "250 questions a month" is a promise
   someone can evaluate against their own recovery; "2 million tokens" is not.
2. Token cost per question varies ~3.3x by route (a single-specialist question
   measured 11,564 tokens, a three-specialist TEAM question 38,141) and the
   *user* does not choose the route — the planner does (D28). Billing by token
   would charge a patient more because our orchestrator decided their question
   needed the surgeon, which is not a defensible thing to put on an invoice.

So the customer sees a flat per-question price and we absorb route variance.
`margin_report()` exists to prove that absorbing it is safe.

The real constraint is throughput, not COGS
-------------------------------------------
Measured cost to serve is roughly $0.0024 for a single-specialist question and
~$0.009 for a TEAM question, against a $0.12 overage price — so gross margin on
tokens is ~93-98%. Cost is not what limits this business.

Groq's free tier caps `gpt-oss-120b` at 8,000 tokens/minute. A TEAM question
consumes 38,141 tokens, i.e. **4.8 minutes of budget for one question**, and
measured 204.8 s wall-clock because the SDK silently backs off. That ceiling —
not token price — is what caps concurrent users, and `capacity_report()` states
it in the units a business audience cares about: how many customers this can
actually serve before the tier has to change.

Public API:
    PLANS                                -> dict[str, Plan]
    get_plan(plan_id)                    -> Plan
    period_start(now)                    -> str   (ISO, start of billing month)
    usage_for(user_id, ...)              -> UsageSummary
    check_quota(user_id, ...)            -> QuotaVerdict
    record_question(user_id, ...)        -> int
    record_payment(user_id, ...)         -> int
    revenue_report(...)                  -> dict
    margin_report(...)                   -> dict
    capacity_report(...)                 -> dict
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.business import pricing

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _REPO_ROOT / "data" / "chat_history.db"


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    monthly_price_usd: float
    included_questions: int
    overage_per_question_usd: float
    seats: int
    specialists: tuple[str, ...]
    features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_free(self) -> bool:
        return self.monthly_price_usd == 0.0

    def overage_cost(self, questions_used: int) -> float:
        """USD owed beyond the subscription for this much usage."""
        over = max(0, questions_used - self.included_questions)
        return round(over * self.overage_per_question_usd, 2)


# Anchoring note for the report: a physical-therapy visit runs $75-150 and a
# session with a trainer $40-80. Recovery at $19/mo undercuts a SINGLE visit
# while covering a month, which is the value claim the product was pitched on
# (PROJECT_PLAN section 1). Clinic is priced per-provider, not per-patient.
PLANS: dict[str, Plan] = {
    "free": Plan(
        plan_id="free",
        name="Free",
        monthly_price_usd=0.0,
        included_questions=15,
        # Free users are blocked, not billed, at the cap -- charging someone who
        # never entered a card is the one thing a free tier must not do.
        overage_per_question_usd=0.0,
        seats=1,
        specialists=("physical_therapist", "gym_trainer"),
        features=("Text questions", "2 specialists", "Conversation history"),
    ),
    "recovery": Plan(
        plan_id="recovery",
        name="Recovery",
        monthly_price_usd=19.0,
        included_questions=250,
        overage_per_question_usd=0.12,
        seats=1,
        specialists=(
            "orthopedic_surgeon",
            "physical_therapist",
            "gym_trainer",
            "nutritionist",
        ),
        features=(
            "All 4 specialists",
            "Photo upload (vision)",
            "Agent-to-agent consults",
            "Full conversation history",
        ),
    ),
    "clinic": Plan(
        plan_id="clinic",
        name="Clinic",
        monthly_price_usd=99.0,
        included_questions=2000,
        overage_per_question_usd=0.08,  # volume discount vs Recovery
        seats=5,
        specialists=(
            "orthopedic_surgeon",
            "physical_therapist",
            "gym_trainer",
            "nutritionist",
        ),
        features=(
            "Everything in Recovery",
            "5 provider seats",
            "Transcript export",
            "Priority throughput",
        ),
    ),
}

DEFAULT_PLAN = "free"


def get_plan(plan_id: str | None) -> Plan:
    """Look up a plan, falling back to Free for an unknown id.

    Unknown ids resolve to the *least* privileged plan deliberately: a typo in
    stored data must not hand someone the Clinic tier.
    """
    return PLANS.get(plan_id or "", PLANS[DEFAULT_PLAN])


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────
#
# Plain sqlite3 against the same file, matching telemetry.py's convention: this
# owns its own tables and does not contend with database.py (D31) over schema.

_SCHEMA = """
CREATE TABLE IF NOT EXISTS billing_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    session_id   TEXT,
    plan_id      TEXT NOT NULL,
    route        TEXT,             -- TEAM / PT_ONLY / ... : route drives cost
    cost_usd     REAL,             -- metered cost to serve, NULL if unmeasured
    billable     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_billing_user ON billing_events (user_id, created_at);

CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    plan_id       TEXT NOT NULL,
    period_start  TEXT NOT NULL,
    subscription_usd REAL NOT NULL DEFAULT 0,
    overage_usd      REAL NOT NULL DEFAULT 0,
    total_usd        REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'simulated'
);
CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices (user_id, period_start);
"""

_initialised = False


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if not _initialised:
        conn.executescript(_SCHEMA)
        conn.commit()
        _initialised = True
    return conn


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    try:
        conn = _connect()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def period_start(now: datetime | None = None) -> str:
    """ISO timestamp for the start of the current billing month (UTC)."""
    now = now or datetime.now(timezone.utc)
    return now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Recording
# ─────────────────────────────────────────────────────────────────────────────


def record_question(
    user_id: str,
    *,
    session_id: str | None = None,
    plan_id: str = DEFAULT_PLAN,
    route: str | None = None,
    cost_usd: float | None = None,
    billable: bool = True,
) -> int:
    """Log one answered question against a user's quota. Returns the row id.

    `billable=False` records the event without counting it toward quota — used
    for RED_FLAG safety responses, which are a deterministic regex short-circuit
    that never reaches a specialist. Charging a patient for being told to seek
    emergency care would be indefensible, and it costs us nothing to serve.
    """
    try:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO billing_events (created_at, user_id, session_id, plan_id,"
            " route, cost_usd, billable) VALUES (?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                user_id,
                session_id,
                plan_id,
                route,
                cost_usd,
                1 if billable else 0,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id or 0
    except Exception:
        return 0


def record_payment(
    user_id: str,
    *,
    plan_id: str,
    subscription_usd: float,
    overage_usd: float,
    period: str | None = None,
    status: str = "simulated",
) -> int:
    """Write an invoice row.

    Shaped exactly as a Stripe `invoice.paid` webhook handler would write it,
    so monetising for real is a matter of calling this from that handler and
    changing `status`. `status='simulated'` marks every row this project
    creates, so a real payment could never be confused with a demo one.
    """
    try:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO invoices (created_at, user_id, plan_id, period_start,"
            " subscription_usd, overage_usd, total_usd, status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                user_id,
                plan_id,
                period or period_start(),
                subscription_usd,
                overage_usd,
                round(subscription_usd + overage_usd, 2),
                status,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id or 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Quota
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class UsageSummary:
    user_id: str
    plan: Plan
    questions_used: int
    included: int
    overage_questions: int
    overage_usd: float
    subscription_usd: float
    total_billed_usd: float
    cost_to_serve_usd: float

    @property
    def remaining(self) -> int:
        return max(0, self.included - self.questions_used)

    @property
    def utilization(self) -> float:
        """Fraction of the included quota consumed (can exceed 1.0)."""
        return (self.questions_used / self.included) if self.included else 0.0

    @property
    def gross_margin_usd(self) -> float:
        return self.total_billed_usd - self.cost_to_serve_usd

    @property
    def gross_margin_pct(self) -> float:
        if self.total_billed_usd <= 0:
            return 0.0
        return self.gross_margin_usd / self.total_billed_usd * 100.0


def usage_for(
    user_id: str, plan_id: str, *, since: str | None = None
) -> UsageSummary:
    """This period's usage, revenue, and measured cost to serve for one user.

    Cost comes from `telemetry.user_usage` — Groq's own token counts priced by
    `business.pricing` — not from the chars/4 estimator this module replaced as
    the source of cost truth (D32).
    """
    since = since or period_start()
    plan = get_plan(plan_id)

    rows = _query(
        "SELECT COUNT(*) FROM billing_events"
        " WHERE user_id = ? AND billable = 1 AND created_at >= ?",
        (user_id, since),
    )
    used = rows[0][0] if rows else 0

    from src import telemetry

    metered = telemetry.user_usage(user_id, since=since)
    overage_usd = plan.overage_cost(used)

    return UsageSummary(
        user_id=user_id,
        plan=plan,
        questions_used=used,
        included=plan.included_questions,
        overage_questions=max(0, used - plan.included_questions),
        overage_usd=overage_usd,
        subscription_usd=plan.monthly_price_usd,
        total_billed_usd=round(plan.monthly_price_usd + overage_usd, 2),
        cost_to_serve_usd=metered["cost_usd"],
    )


@dataclass
class QuotaVerdict:
    allowed: bool
    reason: str
    usage: UsageSummary
    will_incur_overage: bool = False


def check_quota(user_id: str, plan_id: str, *, since: str | None = None) -> QuotaVerdict:
    """Decide whether this user may ask another question right now.

    Free is a hard stop; paid tiers pass through into overage. The asymmetry is
    the whole point of the hybrid model — a paying customer is never blocked
    mid-recovery over a quota, and a free user is never charged.
    """
    usage = usage_for(user_id, plan_id, since=since)
    plan = usage.plan

    if usage.questions_used < plan.included_questions:
        return QuotaVerdict(True, "within quota", usage)

    if plan.is_free:
        return QuotaVerdict(
            False,
            f"Free plan includes {plan.included_questions} questions per month "
            f"and you have used {usage.questions_used}. Upgrade to Recovery "
            f"(${PLANS['recovery'].monthly_price_usd:.0f}/mo) to continue.",
            usage,
        )

    return QuotaVerdict(
        True,
        f"Over the included {plan.included_questions}; further questions bill "
        f"at ${plan.overage_per_question_usd:.2f} each.",
        usage,
        will_incur_overage=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Business reporting
# ─────────────────────────────────────────────────────────────────────────────


def revenue_report(since: str | None = None) -> dict:
    """MRR, ARR, ARPU, and tier mix across all accounts."""
    since = since or period_start()
    from src import auth

    users = auth.list_users()
    active = [u for u in users if u.is_active]

    by_plan: dict[str, int] = {}
    mrr = 0.0
    overage_total = 0.0

    for user in active:
        plan = get_plan(user.plan_id)
        by_plan[plan.plan_id] = by_plan.get(plan.plan_id, 0) + 1
        mrr += plan.monthly_price_usd
        usage = usage_for(user.user_id, user.plan_id, since=since)
        overage_total += usage.overage_usd

    paying = sum(1 for u in active if not get_plan(u.plan_id).is_free)
    total_revenue = mrr + overage_total

    return {
        "users_total": len(users),
        "users_active": len(active),
        "users_paying": paying,
        "users_free": len(active) - paying,
        "conversion_pct": (paying / len(active) * 100.0) if active else 0.0,
        "mrr_usd": round(mrr, 2),
        "arr_usd": round(mrr * 12, 2),
        "overage_usd": round(overage_total, 2),
        "total_revenue_usd": round(total_revenue, 2),
        "arpu_usd": round(total_revenue / len(active), 2) if active else 0.0,
        "arppu_usd": round(total_revenue / paying, 2) if paying else 0.0,
        "by_plan": by_plan,
        "overage_share_pct": (
            overage_total / total_revenue * 100.0 if total_revenue else 0.0
        ),
    }


def margin_report(since: str | None = None) -> dict:
    """Revenue against measured cost to serve, plus per-route cost-to-serve.

    This is the table that answers "does the price cover the cost", using
    Groq's reported token counts rather than an estimate.
    """
    since = since or period_start()
    from src import telemetry

    rev = revenue_report(since)
    metered = telemetry.summary()

    # Per-route cost: which routes are expensive to serve, measured.
    rows = _query(
        "SELECT COALESCE(route,'(unknown)'), COUNT(*), COALESCE(AVG(cost_usd),0),"
        " COALESCE(SUM(cost_usd),0)"
        " FROM billing_events WHERE created_at >= ? GROUP BY route"
        " ORDER BY SUM(cost_usd) DESC",
        (since,),
    )
    by_route = [
        {
            "route": r[0],
            "questions": r[1],
            "avg_cost_usd": float(r[2] or 0.0),
            "total_cost_usd": float(r[3] or 0.0),
        }
        for r in rows
    ]

    cost = float(metered.get("cost_usd") or 0.0)
    revenue = rev["total_revenue_usd"]

    return {
        "revenue_usd": revenue,
        "cost_to_serve_usd": round(cost, 6),
        "gross_margin_usd": round(revenue - cost, 2),
        "gross_margin_pct": ((revenue - cost) / revenue * 100.0) if revenue else 0.0,
        "by_route": by_route,
        "unpriced_calls": telemetry.unpriced_calls(),
        "rates_verified_on": pricing.RATES_VERIFIED_ON,
    }


def capacity_report() -> dict:
    """What the rate limit — not token cost — allows us to sell.

    Measured inputs (2026-08-08, src/telemetry.py):
        single-specialist question  11,564 tokens
        three-specialist TEAM       38,141 tokens, 204.8 s wall clock

    Groq's free tier allows 8,000 tokens/minute on gpt-oss-120b. Serving one
    TEAM question therefore occupies ~4.8 minutes of the entire account's
    budget, which is why the app appears to hang: the SDK backs off silently
    rather than erroring (hence telemetry's SLOW_CALL_MS rather than a 429
    count). This is the real ceiling on how many customers can be served.
    """
    from src import telemetry

    tpm = telemetry.TPM_LIMIT_120B
    single, team = 11_564, 38_141

    team_per_hour = (tpm * 60) / team
    single_per_hour = (tpm * 60) / single

    # If a Recovery subscriber uses their full 250 questions a month, spread
    # evenly, how many such subscribers fit under the ceiling?
    hours_per_month = 730
    team_capacity_month = team_per_hour * hours_per_month
    # Floored, not rounded: you cannot serve a fraction of a subscriber, and
    # the revenue ceiling below is derived from this same integer so the two
    # figures the dashboard shows side by side always agree. Deriving the
    # ceiling from the unfloored value reported "36 subscribers" next to
    # "$698/mo", which implies $19.39 each on a $19 plan.
    subs_supported = int(team_capacity_month // PLANS["recovery"].included_questions)

    return {
        "tpm_limit": tpm,
        "tokens_single_specialist": single,
        "tokens_team": team,
        "team_minutes_of_budget": round(team / tpm, 1),
        "team_questions_per_hour": round(team_per_hour, 1),
        "single_questions_per_hour": round(single_per_hour, 1),
        "team_questions_per_month": int(team_capacity_month),
        "recovery_subscribers_supported": subs_supported,
        "revenue_ceiling_usd_month": round(
            subs_supported * PLANS["recovery"].monthly_price_usd, 2
        ),
        "note": (
            "Throughput, not token cost, is the binding constraint. Lifting it "
            "is a Groq tier change, not an architecture change."
        ),
    }
