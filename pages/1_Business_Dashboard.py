"""
pages/1_Business_Dashboard.py — the business-facing console (admin only, D34).

Deliberately separate from the Observability tab in app.py. That one is
engineering-facing and answers *where do the tokens and the latency go*; this
one is business-facing and answers *does the price cover the cost, and what
caps growth*. They read the same metered rows, so the two can never disagree
about what a question cost.

Access control: Streamlit's `pages/` directory puts a link in the sidebar for
anyone. Hiding a link is not access control, so this page re-checks the
signed-in user's role against the database on every run and `st.stop()`s
otherwise. Navigating here by URL as a non-admin gets the same refusal.

Every figure is computed from real rows:

    revenue / users     src/auth.py  (users table)
    questions / quota   src/business/plans.py  (billing_events)
    cost to serve       src/telemetry.py  (llm_calls, Groq's own token counts)
                        priced by src/business/pricing.py

Nothing is charged, and no figure here is a placeholder. Invoices carry
status='simulated' so a demo row could never be mistaken for a real payment.
"""

from __future__ import annotations

import streamlit as st

from src import auth, telemetry
from src.business import plans, pricing

st.set_page_config(page_title="Business · Recovery Team", page_icon="📈", layout="wide")


# ─────────────────────────────────────────────────────────────────────────────
# Access control
# ─────────────────────────────────────────────────────────────────────────────

_uid = st.session_state.get("user_id")
_user = auth.get_user(_uid) if _uid else None

if _user is None:
    st.title("📈 Business console")
    st.warning("Sign in on the main page to continue.")
    st.stop()

# Re-read from the database rather than trusting a role cached in session_state,
# so a revoked admin loses access on their next interaction rather than at their
# next login.
if not _user.is_admin:
    st.title("📈 Business console")
    st.error("This page is restricted to administrator accounts.")
    st.caption(
        f"Signed in as {_user.email} (role: {_user.role}). "
        "Try the admin demo account listed on the sign-in screen."
    )
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────

period = plans.period_start()
revenue = plans.revenue_report(period)
margin = plans.margin_report(period)
capacity = plans.capacity_report()
metered = telemetry.summary()

st.title("📈 Business console")
st.caption(
    f"Billing period beginning {period[:10]} · cost measured from Groq's own "
    f"token counts · rates verified {pricing.RATES_VERIFIED_ON}"
)

st.info(
    "**Coursework — nothing is charged.** Accounts, quota, overage, invoices, "
    "and cost-to-serve are all real and computed from live data. The only "
    "missing piece is a payment processor; invoices are written with "
    "`status='simulated'`.",
    icon="🎓",
)

# ── headline numbers ─────────────────────────────────────────────────────────
# Stat tiles, not charts: these are single values, and a chart of one number is
# strictly worse than the number.

st.subheader("Revenue")
c1, c2, c3, c4 = st.columns(4)
c1.metric("MRR", f"${revenue['mrr_usd']:,.0f}")
c2.metric("ARR", f"${revenue['arr_usd']:,.0f}")
c3.metric("ARPU", f"${revenue['arpu_usd']:,.2f}",
          help="Total revenue this period divided by all active accounts.")
c4.metric(
    "Paid conversion", f"{revenue['conversion_pct']:.0f}%",
    help=f"{revenue['users_paying']} paying of {revenue['users_active']} active.",
)

c5, c6, c7, c8 = st.columns(4)
c5.metric("Users", f"{revenue['users_total']:,}")
c6.metric("Paying", f"{revenue['users_paying']:,}")
c7.metric("Usage revenue", f"${revenue['overage_usd']:,.2f}",
          help="Overage beyond included quota — the metered half of the model.")
c8.metric("Usage share", f"{revenue['overage_share_pct']:.1f}%",
          help="Overage as a share of total revenue.")

# ── margin ───────────────────────────────────────────────────────────────────

st.subheader("Gross margin")
st.caption(
    "Cost to serve is metered, not estimated: Groq's reported token counts for "
    "every call in the pipeline, priced per model."
)

def _margin_label(pct: float, cost: float) -> str:
    """Never print a flat 100% while we are actually paying something.

    At these volumes margin rounds to 100.0% long before it is 100%, and a
    dashboard claiming a perfect margin reads as a bug or an overclaim. Same
    convention as compliance_check distinguishing "clean" from "could not
    check" -- say the true thing, not the flattering rounding.
    """
    if cost > 0 and pct > 99.9:
        return ">99.9%"
    return f"{pct:.1f}%"


m1, m2, m3, m4 = st.columns(4)
m1.metric("Revenue", f"${margin['revenue_usd']:,.2f}")
m2.metric("Cost to serve", f"${margin['cost_to_serve_usd']:,.4f}")
m3.metric("Gross margin", f"${margin['gross_margin_usd']:,.2f}")
m4.metric(
    "Margin %",
    _margin_label(margin["gross_margin_pct"], margin["cost_to_serve_usd"]),
    help="Revenue minus measured cost to serve, over revenue.",
)

if margin["unpriced_calls"]:
    st.warning(
        f"{margin['unpriced_calls']} recorded call(s) carry no cost — the "
        "provider returned no usage metadata for them. They are excluded from "
        "cost to serve, so the true figure is slightly higher than shown.",
        icon="⚠️",
    )

if margin["by_route"]:
    import pandas as pd

    st.markdown("**Cost to serve by route** — what the planner's choice costs us")
    df = pd.DataFrame(margin["by_route"])
    df["price_charged_usd"] = plans.PLANS["recovery"].overage_per_question_usd
    df["margin_pct"] = (
        (df["price_charged_usd"] - df["avg_cost_usd"])
        / df["price_charged_usd"]
        * 100.0
    )
    st.dataframe(
        df.rename(
            columns={
                "route": "Route",
                "questions": "Questions",
                "avg_cost_usd": "Avg cost $",
                "total_cost_usd": "Total cost $",
                "price_charged_usd": "Price $",
                "margin_pct": "Margin %",
            }
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Avg cost $": st.column_config.NumberColumn(format="$%.5f"),
            "Total cost $": st.column_config.NumberColumn(format="$%.4f"),
            "Price $": st.column_config.NumberColumn(format="$%.2f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "A TEAM question costs roughly 3.3x a single-specialist one, and the "
        "*planner* picks the route, not the patient (D28) — which is why "
        "billing is per question, not per token. We absorb the variance; this "
        "table is the evidence that doing so is safe."
    )

# ── the constraint that actually binds ───────────────────────────────────────

st.subheader("Capacity — the real constraint")
st.caption(
    "Token cost is not what limits this business; Groq's rate limits are. The "
    "free tier imposes two token caps that constrain different things, and the "
    "**daily** one binds far earlier than the per-minute one."
)

lat, vol = st.columns(2)
with lat:
    st.markdown(
        f"**Per-minute — {capacity['tpm_limit']:,} tok/min** · a *latency* limit"
    )
    st.caption(
        f"One TEAM question is {capacity['tokens_team']:,} tokens = "
        f"**{capacity['team_minutes_of_budget']} minutes** of the whole "
        f"account's budget, so Groq stalls it (204.8 s measured, zero 429s). "
        f"This is what breaks a live demo — it does not cap the business."
    )
    st.metric("TEAM questions / hour", f"{capacity['team_questions_per_hour']:.1f}")

with vol:
    st.markdown(
        f"**Per-day — {capacity['tpd_limit']:,} tok/day** · a *volume* limit "
        "⟵ **binding**"
    )
    st.caption(
        f"Only **{capacity['team_questions_per_day']:.1f} TEAM questions per "
        f"day** exist before the account is finished until tomorrow "
        f"({capacity['single_questions_per_day']:.1f} single-specialist). This "
        f"is what caps how many customers can be served at all."
    )
    st.metric("TEAM questions / month", f"{capacity['team_questions_per_month']:,}")

k1, k2, k3 = st.columns(3)
k1.metric(
    "Subscribers supported (TEAM)",
    f"{capacity['recovery_subscribers_supported']:,}",
    help=f"Recovery subscribers whose full {plans.PLANS['recovery'].included_questions} "
         "questions/month could actually be honoured, if every question were a "
         "TEAM question.",
)
k2.metric(
    "Subscribers (single-specialist)",
    f"{capacity['recovery_subscribers_supported_single']:,}",
    help="The same figure if every question woke exactly one specialist — the "
         "cheapest possible mix.",
)
k3.metric("Revenue ceiling", f"${capacity['revenue_ceiling_usd_month']:,.0f}/mo")

st.error(
    f"**The free tier cannot host a single paying subscriber.** At "
    f"{capacity['tpd_limit']:,} tokens/day the whole account supports "
    f"**{capacity['team_questions_per_month']:,} TEAM questions a month** — and "
    f"one Recovery subscriber is promised "
    f"{plans.PLANS['recovery'].included_questions}. Gross margin is >99%; it is "
    f"irrelevant. **The constraint is supply, not price, and the fix is a Groq "
    f"tier upgrade — a purchase order, not a rewrite.**",
    icon="🚧",
)
st.caption(
    f"Modelling this from the per-minute limit alone would have claimed "
    f"~{capacity['tpm_only_overstatement_x']}× more capacity than exists — "
    f"sustaining {capacity['tpm_limit']:,} tok/min for a month is ~350M tokens, "
    f"while the daily cap allows 6M. Both limits are real; only the tighter one "
    f"is the ceiling."
)

if metered.get("throttled"):
    st.caption(
        f"Observed: {metered['throttled']} call(s) slower than "
        f"{telemetry.SLOW_CALL_MS // 1000}s — the signature of throttling. Groq "
        "stalls excess rather than rejecting it, so 429 counts stay at zero "
        "while the system visibly hangs."
    )

# ── tier mix ─────────────────────────────────────────────────────────────────

st.subheader("Plan mix")
mix_cols = st.columns(len(plans.PLANS))
for col, (pid, plan) in zip(mix_cols, plans.PLANS.items()):
    count = revenue["by_plan"].get(pid, 0)
    with col:
        st.metric(
            plan.name,
            f"{count} user{'' if count == 1 else 's'}",
            help=" · ".join(plan.features),
        )
        st.caption(
            f"${plan.monthly_price_usd:.0f}/mo · "
            f"{plan.included_questions:,} questions"
            + (
                f", then ${plan.overage_per_question_usd:.2f} each"
                if plan.overage_per_question_usd
                else " (hard cap)"
            )
        )

# ── per-user economics ───────────────────────────────────────────────────────

st.subheader("Accounts")
users = auth.list_users()
rows = []
for u in users:
    usage = plans.usage_for(u.user_id, u.plan_id, since=period)
    rows.append(
        {
            "Email": u.email,
            "Role": u.role,
            "Plan": usage.plan.name,
            "Questions": usage.questions_used,
            "Quota": usage.included,
            "Utilization %": usage.utilization * 100.0,
            "Billed $": usage.total_billed_usd,
            "Cost $": usage.cost_to_serve_usd,
            "Margin %": usage.gross_margin_pct,
        }
    )

if rows:
    import pandas as pd

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Utilization %": st.column_config.ProgressColumn(
                format="%.0f%%", min_value=0, max_value=100
            ),
            "Billed $": st.column_config.NumberColumn(format="$%.2f"),
            "Cost $": st.column_config.NumberColumn(format="$%.5f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "Users near 100% utilization are the upsell list; users far past it on "
        "a paid tier are the ones overage revenue comes from."
    )

# ── unattributed spend ───────────────────────────────────────────────────────

unattributed = [r for r in telemetry.cost_by_user(period) if r["user_id"] == "(unattributed)"]
if unattributed:
    row = unattributed[0]
    with st.expander("Unattributed spend"):
        st.caption(
            f"{row['calls']} call(s), {row['tokens']:,} tokens, "
            f"${row['cost_usd']:.5f} — model calls made outside a signed-in "
            "request: CLI runs, the test suite, and anything recorded before "
            "accounts shipped. Reported rather than dropped so per-user totals "
            "always reconcile with the metered total."
        )

st.divider()
st.caption(
    "Sources: `users` (accounts), `billing_events` (quota/usage), `invoices` "
    "(simulated payments), `llm_calls` (metered tokens). "
    f"Prices from `src/business/pricing.py`, verified {pricing.RATES_VERIFIED_ON} "
    f"against {pricing.RATES_SOURCE}."
)
