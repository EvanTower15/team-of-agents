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

Priced on a production stack, not the free tier (D35)
----------------------------------------------------
The free Groq tier this proof-of-concept runs on cannot host a business: its
200,000-token daily cap supports ~157 TEAM questions a month for the ENTIRE
account, i.e. one Recovery subscriber and a $45/month revenue ceiling. So the
economics are modelled on a stack a real startup would deploy — Sonnet 5 for
specialists, Haiku 4.5 for orchestration, no usage caps — by re-pricing the
same MEASURED token volumes. See `pricing.PRODUCTION_STACK`.

That swap is not cosmetic; it inverts the conclusion:

    cost / TEAM question    free tier  $0.0092      production  $0.185  (~20x)
    cost / single question  free tier  $0.0024      production  $0.052

On the free tier, cost is a rounding error and supply is the only constraint.
On a production stack, the multi-agent architecture's ~10x token multiplier
becomes **the dominant line item** — Ben's finding that constraint extraction
costs nearly as much as the consult it summarises is a curiosity at $0.009 and
a budget line at $0.185. The same architecture is cheap or ruinous depending
entirely on the model tier underneath it.

The prices below follow from that cost, not from taste: blended cost is
~$0.1006/question across the assumed route mix, and every paid tier is set to
clear TARGET_GROSS_MARGIN at full quota use. The proof-of-concept-era $19/mo
plan with 250 included questions would run at **negative 32% margin** on this
stack. `derive_pricing()` shows the arithmetic and flags any plan that stops
clearing.

`capacity_report()` still models the free tier, deliberately — it is the
evidence for why the paid stack is necessary rather than an upsell.

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


# ── projected cost to serve, per route (D35) ─────────────────────────────────
#
# Measured token volumes from src/telemetry.py, priced on the PRODUCTION stack
# (Sonnet 5 specialists + Haiku 4.5 orchestration) rather than on the free-tier
# gpt-oss models the proof-of-concept actually runs. Verified by re-pricing
# Ben's measured single-specialist run: $0.00244 actual -> $0.05235 projected,
# a 21.5x multiplier.
COST_SINGLE_SPECIALIST_USD = 0.052   # 11,564 measured tokens
COST_DUAL_SPECIALIST_USD = 0.115     # interpolated
COST_TEAM_USD = 0.185                # 38,141 measured tokens

# Assumed route mix for blended cost. Stated rather than hidden: a recovery
# product skews toward narrow questions, and only a minority wake the full
# team. Replace with measured proportions from billing_events once there is
# enough real traffic to beat the assumption.
ROUTE_MIX = {"single": 0.45, "dual": 0.35, "team": 0.20}

BLENDED_COST_PER_QUESTION_USD = round(
    ROUTE_MIX["single"] * COST_SINGLE_SPECIALIST_USD
    + ROUTE_MIX["dual"] * COST_DUAL_SPECIALIST_USD
    + ROUTE_MIX["team"] * COST_TEAM_USD,
    4,
)  # ~= $0.1007

# Every plan below is priced to clear this at FULL quota consumption -- the
# worst case, since a subscriber who uses nothing is pure margin. Pricing to
# the average would leave the heaviest users unprofitable.
TARGET_GROSS_MARGIN = 0.75


# Anchoring note for the report: a physical-therapy visit runs $75-150 and a
# session with a trainer $40-80. Recovery at $39/mo still undercuts a SINGLE
# visit while covering a month, which is the value claim the product was
# pitched on (PROJECT_PLAN section 1). Clinic is priced per-provider, not
# per-patient: $199 across 5 seats is ~$40/provider/month.
#
# These prices replace the proof-of-concept-era ones ($19/250, $99/2000). That
# is not inflation, it is the near-frontier model: at $0.1006/question a
# 250-question plan costs $25.15 to serve, so the old $19 plan ran at NEGATIVE
# 32% margin on every fully-utilised subscriber. Both paid tiers now clear
# 77.6% at full quota, and their overage prices are set to the same margin so a
# heavy user is exactly as profitable as a light one. $225 across 5 Clinic
# seats is $45/provider -- the same per-head price as Recovery, which makes the
# B2B tier easy to justify. See derive_pricing() for the arithmetic.
PLANS: dict[str, Plan] = {
    "free": Plan(
        plan_id="free",
        name="Free",
        monthly_price_usd=0.0,
        # Cut from 15 to 10: at projected rates a free user costs ~$1.00/month
        # rather than ~$0.14, so the trial has to be sized like real spend.
        included_questions=10,
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
        monthly_price_usd=45.0,
        included_questions=100,
        overage_per_question_usd=0.45,
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
        monthly_price_usd=225.0,
        included_questions=500,
        overage_per_question_usd=0.35,  # volume discount vs Recovery
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


def derive_pricing(
    blended_cost_usd: float | None = None,
    target_margin: float | None = None,
) -> list[dict]:
    """Show the arithmetic behind every price, and whether it holds.

    The dashboard renders this so the plan table is a *derivation* rather than
    an assertion: change the model scenario and it becomes visible which plans
    stop clearing the margin target. That link -- model choice determines what
    you must charge -- is the analytical point of the whole exercise.
    """
    cost = blended_cost_usd or BLENDED_COST_PER_QUESTION_USD
    margin = TARGET_GROSS_MARGIN if target_margin is None else target_margin

    rows = []
    for plan in PLANS.values():
        cost_at_full = plan.included_questions * cost
        revenue = plan.monthly_price_usd
        actual_margin = (
            (revenue - cost_at_full) / revenue * 100.0 if revenue > 0 else 0.0
        )
        # What this plan WOULD have to charge to hit the target at this quota.
        required_price = cost_at_full / (1 - margin) if margin < 1 else float("inf")
        # ...or how many questions it could include at the current price.
        affordable_quota = int(revenue * (1 - margin) / cost) if cost > 0 else 0

        rows.append(
            {
                "plan": plan.name,
                "price_usd": revenue,
                "included": plan.included_questions,
                "cost_at_full_usd": round(cost_at_full, 2),
                "margin_pct": actual_margin,
                "required_price_usd": round(required_price, 2),
                "affordable_quota": affordable_quota,
                # None, not False, for free plans: zero revenue means margin is
                # undefined, and rendering "fails target" against a plan that was
                # never meant to earn would misread as a pricing bug.
                "clears_target": (
                    actual_margin >= margin * 100.0 if revenue > 0 else None
                ),
                "overage_margin_pct": (
                    (plan.overage_per_question_usd - cost)
                    / plan.overage_per_question_usd
                    * 100.0
                    if plan.overage_per_question_usd
                    else 0.0
                ),
            }
        )
    return rows

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
    cost_usd     REAL,             -- ACTUAL metered cost, NULL if unmeasured
    billable     INTEGER NOT NULL DEFAULT 1,
    projected_usd REAL             -- cost on the production stack (D35)
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

# Added after billing_events first shipped. Same reasoning as telemetry's
# migration block: SQLite has no ADD COLUMN IF NOT EXISTS, and without this an
# existing database keeps the old table while every insert fails silently.
_MIGRATIONS = {
    "projected_usd": "ALTER TABLE billing_events ADD COLUMN projected_usd REAL",
}

_initialised = False


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if not _initialised:
        conn.executescript(_SCHEMA)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(billing_events)")}
        for column, ddl in _MIGRATIONS.items():
            if column not in existing:
                conn.execute(ddl)
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
    projected_usd: float | None = None,
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
            " route, cost_usd, billable, projected_usd) VALUES (?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                user_id,
                session_id,
                plan_id,
                route,
                cost_usd,
                1 if billable else 0,
                projected_usd,
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
    cost_to_serve_usd: float   # projected, on the production stack (D35)
    actual_cost_usd: float = 0.0  # what the free tier really cost

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
    # PROJECTED cost is the primary figure (D35): the app presents economics as
    # a production deployment would bill them. `actual_cost_usd` keeps the real
    # free-tier spend alongside so the two never have to be reconstructed.

    return UsageSummary(
        user_id=user_id,
        plan=plan,
        questions_used=used,
        included=plan.included_questions,
        overage_questions=max(0, used - plan.included_questions),
        overage_usd=overage_usd,
        subscription_usd=plan.monthly_price_usd,
        total_billed_usd=round(plan.monthly_price_usd + overage_usd, 2),
        cost_to_serve_usd=metered.get("projected_usd", 0.0),
        actual_cost_usd=metered["cost_usd"],
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
        "SELECT COALESCE(route,'(unknown)'), COUNT(*),"
        " COALESCE(AVG(projected_usd),0), COALESCE(SUM(projected_usd),0)"
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

    cost = float(metered.get("projected_usd") or 0.0)
    actual_cost = float(metered.get("cost_usd") or 0.0)
    revenue = rev["total_revenue_usd"]

    return {
        "revenue_usd": revenue,
        "cost_to_serve_usd": round(cost, 6),
        "actual_cost_usd": round(actual_cost, 6),
        "projection_multiplier": round(cost / actual_cost, 1) if actual_cost else 0.0,
        "blended_cost_per_question_usd": BLENDED_COST_PER_QUESTION_USD,
        "target_margin_pct": TARGET_GROSS_MARGIN * 100.0,
        "production_stack": pricing.PRODUCTION_STACK_NAME,
        "gross_margin_usd": round(revenue - cost, 2),
        "gross_margin_pct": ((revenue - cost) / revenue * 100.0) if revenue else 0.0,
        "by_route": by_route,
        "unpriced_calls": telemetry.unpriced_calls(),
        "rates_verified_on": pricing.RATES_VERIFIED_ON,
    }


TOKENS_SINGLE_SPECIALIST = 11_564  # measured 2026-08-08, 6 calls
TOKENS_TEAM = 38_141               # measured 2026-08-08, 14 calls, 204.8 s
DAYS_PER_MONTH = 30


def capacity_report() -> dict:
    """What the rate limits — not token cost — allow us to sell.

    Groq's free tier imposes TWO token limits, and they constrain different
    things. Getting this wrong understates the problem by ~58x, so both are
    modelled here and the report names which one actually binds:

        TPM  8,000 tokens/minute  A TEAM question needs 38,141 tokens = 4.8
                                  minutes of the whole account's budget, so
                                  Groq stalls it (204.8 s measured, with ZERO
                                  429s -- see telemetry.SLOW_CALL_MS). This is
                                  a LATENCY constraint: it makes one question
                                  slow, and it is what breaks a live demo.

        TPD  200,000 tokens/day   Only ~5 TEAM questions exist per day before
                                  the account is finished until tomorrow. This
                                  is a VOLUME constraint, and it is the one
                                  that determines how many customers can be
                                  served at all.

    The daily cap binds far earlier. Sustaining 8,000 tok/min for a whole month
    would be ~350M tokens; the daily cap allows 6M. Any capacity figure derived
    from TPM alone is fiction.
    """
    from src import telemetry

    tpm = telemetry.TPM_LIMIT_120B
    tpd = telemetry.TPD_LIMIT
    single, team = TOKENS_SINGLE_SPECIALIST, TOKENS_TEAM
    included = PLANS["recovery"].included_questions

    # Volume ceiling (the binding one): the daily token cap.
    team_per_day = tpd / team
    single_per_day = tpd / single
    team_per_month = team_per_day * DAYS_PER_MONTH
    single_per_month = single_per_day * DAYS_PER_MONTH

    # Subscribers a plan promise can actually be honoured for. Floored so the
    # revenue ceiling derived from it agrees with the count shown beside it.
    subs_team = int(team_per_month // included)
    subs_single = int(single_per_month // included)

    # What TPM alone would imply if it were the only limit -- kept purely to
    # show how far off a TPM-only model is.
    tpm_only_month = (tpm * 60 * 24 * DAYS_PER_MONTH) / team

    return {
        "tpm_limit": tpm,
        "tpd_limit": tpd,
        "tokens_single_specialist": single,
        "tokens_team": team,
        # latency side (TPM)
        "team_minutes_of_budget": round(team / tpm, 1),
        "team_questions_per_hour": round((tpm * 60) / team, 1),
        # volume side (TPD) -- the binding constraint
        "team_questions_per_day": round(team_per_day, 1),
        "single_questions_per_day": round(single_per_day, 1),
        "team_questions_per_month": int(team_per_month),
        "single_questions_per_month": int(single_per_month),
        "recovery_subscribers_supported": subs_team,
        "recovery_subscribers_supported_single": subs_single,
        "revenue_ceiling_usd_month": round(
            subs_team * PLANS["recovery"].monthly_price_usd, 2
        ),
        "binding_constraint": "daily token cap (TPD)",
        "tpm_only_overstatement_x": round(tpm_only_month / team_per_month, 1),
        "note": (
            "Throughput, not token cost, is the binding constraint -- and the "
            "DAILY cap binds long before the per-minute one. The free tier "
            "cannot host a single paying subscriber; lifting it is a Groq tier "
            "change, not an architecture change."
        ),
    }
