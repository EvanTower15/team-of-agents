"""
tests/test_monetization.py — pricing, metered attribution, accounts, and billing.

Covers the layer added in D32/D34. Each test gets its own temp-file SQLite DB
(matching tests/test_database.py's convention), and the two modules that use
plain sqlite3 against a module-level path — src/telemetry.py and
src/business/plans.py — are pointed at that same file via monkeypatch.

The assertions worth understanding rather than skimming:

* An unmeasured call must price as NULL, never 0.0. A zero would silently drag
  every average in the dashboard toward optimism, which is the same failure
  mode as the eval harness that once scored 5/5 on exception (D13).
* Attribution must be per-thread. The whole reason attribution moved off a
  module global is that Streamlit serves concurrent users on separate threads,
  and a raced global would invoice the wrong customer.
* A free user is blocked at quota; a paid user is not. Charging someone who
  never entered a card, or cutting off a paying patient mid-recovery, are both
  wrong -- in opposite directions.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from src import auth, telemetry
from src.business import plans, pricing
from src.business.unit_economics import GROQ_PRICING_PER_1M_TOKENS


@pytest.fixture
def temp_db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'test_money.db').as_posix()}"


@pytest.fixture
def wired_db(tmp_path, temp_db_url, monkeypatch):
    """Point telemetry + plans at the same temp file the ORM layer uses.

    Both write via plain sqlite3 to a module-level path, and both cache an
    "already initialised" flag, so the flag has to be reset too or a test
    inherits the previous test's schema state.
    """
    db_file = tmp_path / "test_money.db"
    monkeypatch.setattr(telemetry, "DB_PATH", db_file)
    monkeypatch.setattr(telemetry, "_initialised", False)
    monkeypatch.setattr(plans, "DB_PATH", db_file)
    monkeypatch.setattr(plans, "_initialised", False)
    monkeypatch.setattr(auth, "DEFAULT_DB_URL", temp_db_url)
    auth.init_auth(temp_db_url)
    return temp_db_url


# ─────────────────────────────────────────────────────────────────────────────
# Pricing
# ─────────────────────────────────────────────────────────────────────────────


def test_pricing_matches_published_groq_rates():
    """The rates that every dollar figure in the app depends on."""
    assert pricing.MODEL_PRICING_PER_1M["openai/gpt-oss-120b"] == {
        "input": 0.15,
        "output": 0.60,
    }
    assert pricing.MODEL_PRICING_PER_1M["openai/gpt-oss-20b"] == {
        "input": 0.075,
        "output": 0.30,
    }


def test_retired_llama_pricing_is_gone():
    """Regression guard for the bug that motivated this whole layer.

    unit_economics billed $0.59/$0.79 -- llama-3.3-70b-versatile's rates -- for
    a year after D27 moved the project to gpt-oss. It must now derive from the
    pricing table rather than hold its own copy.
    """
    assert GROQ_PRICING_PER_1M_TOKENS["input"] != 0.59
    assert GROQ_PRICING_PER_1M_TOKENS["output"] != 0.79
    assert GROQ_PRICING_PER_1M_TOKENS == pricing.MODEL_PRICING_PER_1M[
        "openai/gpt-oss-120b"
    ]


def test_price_call_arithmetic():
    # 1M input + 1M output on the big model = 0.15 + 0.60
    assert pricing.price_call("openai/gpt-oss-120b", 1_000_000, 1_000_000) == pytest.approx(0.75)
    # the small model is exactly half price on both sides
    assert pricing.price_call("openai/gpt-oss-20b", 1_000_000, 1_000_000) == pytest.approx(0.375)


def test_unmeasured_call_prices_as_none_not_zero():
    """None and 0.0 mean different things and must not be conflated."""
    assert pricing.price_call("openai/gpt-oss-120b", None, None) is None
    assert pricing.price_call("openai/gpt-oss-120b", 0, 0) == 0.0


def test_unknown_model_prices_at_the_dearest_known_rate():
    """An unpriced model must never make the margin look better than it is."""
    unknown = pricing.price_call("someone/new-model", 1_000_000, 1_000_000)
    dearest = pricing.price_call("openai/gpt-oss-120b", 1_000_000, 1_000_000)
    assert unknown == pytest.approx(dearest)
    assert not pricing.is_priced("someone/new-model")


def test_cost_bounds_do_not_assume_a_split():
    lo, hi = pricing.cost_bounds("openai/gpt-oss-120b", 38_141)
    assert lo == pytest.approx(38_141 / 1e6 * 0.15)
    assert hi == pytest.approx(38_141 / 1e6 * 0.60)
    assert lo < hi


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry: cost, attribution, migration
# ─────────────────────────────────────────────────────────────────────────────


def test_records_cost_and_attribution(wired_db):
    telemetry.record_call(
        node="consult:pt", model="openai/gpt-oss-120b",
        input_tokens=2914, output_tokens=729, latency_ms=3655, ok=True,
        user_id="u1", session_id="s1",
    )
    usage = telemetry.user_usage("u1")
    assert usage["calls"] == 1
    assert usage["tokens"] == 2914 + 729
    assert usage["cost_usd"] == pytest.approx(
        2914 / 1e6 * 0.15 + 729 / 1e6 * 0.60
    )
    assert telemetry.session_cost("s1")["cost_usd"] == pytest.approx(usage["cost_usd"])


def test_missing_usage_records_null_cost_not_zero(wired_db):
    """A call we could not measure must stay distinguishable from a free one."""
    telemetry.record_call(
        node="route", model="openai/gpt-oss-20b", input_tokens=None,
        output_tokens=None, latency_ms=90, ok=True, user_id="u1",
    )
    conn = sqlite3.connect(telemetry.DB_PATH)
    (cost,) = conn.execute("SELECT cost_usd FROM llm_calls").fetchone()
    conn.close()
    assert cost is None
    assert telemetry.unpriced_calls() == 1


def test_migrates_a_preexisting_table(tmp_path, monkeypatch):
    """An llm_calls written before the money columns existed must migrate.

    The failure this guards against is silent: CREATE INDEX on a not-yet-added
    column raises inside _connect, record_call swallows it, and the table stays
    un-migrated forever while every insert fails invisibly.
    """
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(
        "CREATE TABLE llm_calls ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
        " node TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,"
        " total_tokens INTEGER, latency_ms INTEGER, ok INTEGER NOT NULL,"
        " error_type TEXT, is_rate_limit INTEGER NOT NULL DEFAULT 0);"
    )
    conn.execute(
        "INSERT INTO llm_calls (created_at, node, model, input_tokens,"
        " output_tokens, total_tokens, ok) VALUES"
        " ('2026-08-08T00:00:00','route','openai/gpt-oss-20b',900,88,988,1)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(telemetry, "DB_PATH", db_file)
    monkeypatch.setattr(telemetry, "_initialised", False)

    telemetry.record_call(
        node="consult:pt", model="openai/gpt-oss-120b", input_tokens=100,
        output_tokens=10, latency_ms=50, ok=True, user_id="u1", session_id="s1",
    )

    conn = sqlite3.connect(db_file)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    assert {"cost_usd", "user_id", "session_id"} <= cols
    # The legacy row must NOT be back-filled at today's rates.
    (legacy,) = conn.execute(
        "SELECT cost_usd FROM llm_calls WHERE input_tokens = 900"
    ).fetchone()
    conn.close()
    assert legacy is None
    assert telemetry.user_usage("u1")["calls"] == 1


def test_attribution_is_per_thread(wired_db):
    """Two concurrent requests must not bill each other.

    This is the property the ContextVar switch bought. With the previous module
    global, whichever thread called set_user last would own both rows.
    """
    started = threading.Barrier(2)

    def request(user_id: str, tokens: int):
        with telemetry.attributed_to(user_id, f"sess_{user_id}"):
            started.wait(timeout=5)  # force genuine interleaving
            telemetry.record_call(
                node="consult:pt", model="openai/gpt-oss-120b",
                input_tokens=tokens, output_tokens=0, latency_ms=10, ok=True,
                user_id=telemetry._current_user.get(),
                session_id=telemetry._current_session.get(),
            )

    threads = [
        threading.Thread(target=request, args=("alice", 1000)),
        threading.Thread(target=request, args=("bob", 2000)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert telemetry.user_usage("alice")["tokens"] == 1000
    assert telemetry.user_usage("bob")["tokens"] == 2000


def test_attributed_to_restores_previous_owner(wired_db):
    with telemetry.attributed_to("outer", "s_outer"):
        with telemetry.attributed_to("inner", "s_inner"):
            assert telemetry._current_user.get() == "inner"
        assert telemetry._current_user.get() == "outer"
    assert telemetry._current_user.get() is None


def test_unattributed_rows_still_reconcile(wired_db):
    telemetry.record_call(node="route", model="openai/gpt-oss-20b",
                          input_tokens=500, output_tokens=50, latency_ms=10,
                          ok=True, user_id="u1", session_id="s1")
    telemetry.record_call(node="route", model="openai/gpt-oss-20b",
                          input_tokens=500, output_tokens=50, latency_ms=10,
                          ok=True)  # CLI-style, no owner

    rows = telemetry.cost_by_user()
    assert {r["user_id"] for r in rows} == {"u1", "(unattributed)"}
    assert sum(r["cost_usd"] for r in rows) == pytest.approx(
        telemetry.summary()["cost_usd"]
    )


def test_telemetry_never_raises_on_a_bad_write(tmp_path, monkeypatch):
    """A telemetry failure must not surface to the user mid-consult."""
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "nope" / "x" / "y.db")
    monkeypatch.setattr(telemetry, "_initialised", False)
    monkeypatch.setattr(
        telemetry, "_connect", lambda: (_ for _ in ()).throw(sqlite3.Error("boom"))
    )
    telemetry.record_call(node="n", model="m", input_tokens=1, output_tokens=1,
                          latency_ms=1, ok=True)  # must not raise
    assert telemetry.summary()["calls"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Accounts
# ─────────────────────────────────────────────────────────────────────────────


def test_password_round_trip():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert "correct horse battery" not in stored  # never stored in the clear
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("wrong", stored)


def test_two_hashes_of_one_password_differ():
    """Distinct salts, so identical passwords are not identifiable in the table."""
    assert auth.hash_password("same") != auth.hash_password("same")


@pytest.mark.parametrize("bad", ["", None, "not-a-hash", "scrypt$x$y$z", "a$b$c$d$e$f"])
def test_verify_password_rejects_garbage_without_raising(bad):
    assert auth.verify_password("anything", bad) is False


def test_verify_rejects_empty_password():
    assert auth.verify_password("", auth.hash_password("x" * 8)) is False


def test_create_and_authenticate(wired_db):
    user = auth.create_user("Evan@Example.COM ", "hunter2hunter2",
                            display_name="Evan", db_url=wired_db)
    assert user.email == "evan@example.com"  # normalised
    assert user.role == "user" and user.plan_id == "free"

    assert auth.authenticate("evan@example.com", "hunter2hunter2", db_url=wired_db)
    # normalisation applies on the way in too
    assert auth.authenticate(" EVAN@EXAMPLE.com ", "hunter2hunter2", db_url=wired_db)
    assert auth.authenticate("evan@example.com", "wrong", db_url=wired_db) is None
    assert auth.authenticate("ghost@example.com", "whatever", db_url=wired_db) is None


@pytest.mark.parametrize(
    "email,password",
    [("not-an-email", "longenough1"), ("a@b.co", "short")],
)
def test_create_user_rejects_bad_input(wired_db, email, password):
    with pytest.raises(ValueError):
        auth.create_user(email, password, db_url=wired_db)


def test_duplicate_email_rejected(wired_db):
    auth.create_user("dup@example.com", "password123", db_url=wired_db)
    with pytest.raises(ValueError):
        auth.create_user("DUP@example.com", "password123", db_url=wired_db)


def test_roles_and_plans(wired_db):
    u = auth.create_user("a@b.com", "password123", db_url=wired_db)
    assert not u.is_admin
    assert auth.set_role(u.user_id, "admin", db_url=wired_db)
    assert auth.get_user(u.user_id, db_url=wired_db).is_admin
    assert auth.set_plan(u.user_id, "clinic", db_url=wired_db)
    assert auth.get_user(u.user_id, db_url=wired_db).plan_id == "clinic"
    with pytest.raises(ValueError):
        auth.set_role(u.user_id, "superuser", db_url=wired_db)


def test_seed_demo_users_is_idempotent(wired_db):
    first = auth.seed_demo_users(db_url=wired_db)
    assert len(first) == len(auth.DEMO_ACCOUNTS)
    assert auth.seed_demo_users(db_url=wired_db) == []  # second run creates nothing


# ─────────────────────────────────────────────────────────────────────────────
# Conversation ownership
# ─────────────────────────────────────────────────────────────────────────────


def test_sessions_are_scoped_to_their_owner(wired_db):
    from src import database as db

    mine = db.create_session(user_id="u1", db_url=wired_db)
    theirs = db.create_session(user_id="u2", db_url=wired_db)
    orphan = db.create_session(db_url=wired_db)  # pre-accounts row

    ids = {s.session_id for s in db.list_sessions(user_id="u1", db_url=wired_db)}
    assert ids == {mine}
    assert theirs not in ids and orphan not in ids

    assert db.owns_session("u1", mine, db_url=wired_db)
    assert not db.owns_session("u1", theirs, db_url=wired_db)
    assert not db.owns_session("u1", orphan, db_url=wired_db)
    assert not db.owns_session(None, orphan, db_url=wired_db)


# ─────────────────────────────────────────────────────────────────────────────
# Plans, quota, billing
# ─────────────────────────────────────────────────────────────────────────────


def test_unknown_plan_falls_back_to_least_privileged():
    """A typo in stored data must not hand someone the Clinic tier."""
    assert plans.get_plan("enterprise-gold").plan_id == "free"
    assert plans.get_plan(None).plan_id == "free"


def test_overage_only_applies_beyond_the_included_quota():
    recovery = plans.PLANS["recovery"]
    assert recovery.overage_cost(250) == 0.0
    assert recovery.overage_cost(260) == pytest.approx(10 * 0.12)
    assert plans.PLANS["free"].overage_cost(1000) == 0.0  # free never bills


def test_free_user_blocked_at_quota(wired_db):
    u = auth.create_user("free@x.com", "password123", db_url=wired_db)
    for _ in range(plans.PLANS["free"].included_questions):
        plans.record_question(u.user_id, plan_id="free", route="PT_ONLY", cost_usd=0.002)

    verdict = plans.check_quota(u.user_id, "free")
    assert verdict.allowed is False
    assert "Upgrade" in verdict.reason
    assert verdict.usage.overage_usd == 0.0  # blocked, never billed


def test_paid_user_passes_into_overage(wired_db):
    u = auth.create_user("paid@x.com", "password123", plan_id="recovery",
                         db_url=wired_db)
    for _ in range(260):
        plans.record_question(u.user_id, plan_id="recovery", route="TEAM",
                              cost_usd=0.009)

    verdict = plans.check_quota(u.user_id, "recovery")
    assert verdict.allowed is True
    assert verdict.will_incur_overage is True
    assert verdict.usage.overage_questions == 10
    assert verdict.usage.overage_usd == pytest.approx(1.20)
    assert verdict.usage.total_billed_usd == pytest.approx(20.20)


def test_red_flag_does_not_consume_quota(wired_db):
    """Billing someone for being told to seek emergency care is indefensible."""
    u = auth.create_user("rf@x.com", "password123", db_url=wired_db)
    plans.record_question(u.user_id, plan_id="free", route="PT_ONLY", cost_usd=0.002)
    plans.record_question(u.user_id, plan_id="free", route="RED_FLAG",
                          cost_usd=0.0, billable=False)

    assert plans.usage_for(u.user_id, "free").questions_used == 1


def test_usage_uses_metered_cost_not_an_estimate(wired_db):
    u = auth.create_user("m@x.com", "password123", plan_id="recovery",
                         db_url=wired_db)
    telemetry.record_call(node="consult:pt", model="openai/gpt-oss-120b",
                          input_tokens=30_000, output_tokens=8_000,
                          latency_ms=2000, ok=True, user_id=u.user_id,
                          session_id="s1")
    usage = plans.usage_for(u.user_id, "recovery")
    assert usage.cost_to_serve_usd == pytest.approx(
        30_000 / 1e6 * 0.15 + 8_000 / 1e6 * 0.60
    )
    assert usage.gross_margin_pct > 99  # $19 subscription vs sub-cent cost


def test_revenue_and_margin_reports(wired_db):
    auth.create_user("f@x.com", "password123", db_url=wired_db)
    auth.create_user("r@x.com", "password123", plan_id="recovery", db_url=wired_db)
    auth.create_user("c@x.com", "password123", plan_id="clinic", db_url=wired_db)

    rev = plans.revenue_report()
    assert rev["users_active"] == 3
    assert rev["users_paying"] == 2
    assert rev["mrr_usd"] == pytest.approx(19.0 + 99.0)
    assert rev["arr_usd"] == pytest.approx((19.0 + 99.0) * 12)
    assert rev["by_plan"] == {"free": 1, "recovery": 1, "clinic": 1}

    margin = plans.margin_report()
    assert margin["revenue_usd"] == pytest.approx(118.0)
    assert margin["gross_margin_pct"] > 99  # no usage recorded yet


def test_capacity_report_reflects_the_measured_ceiling():
    """The binding constraint is throughput, and the numbers must say so."""
    cap = plans.capacity_report()
    assert cap["tpm_limit"] == telemetry.TPM_LIMIT_120B
    # One TEAM question exceeds a full minute of the account's entire budget.
    assert cap["team_minutes_of_budget"] > 1.0
    assert cap["team_questions_per_hour"] < cap["single_questions_per_hour"]
    assert cap["recovery_subscribers_supported"] > 0
    assert cap["revenue_ceiling_usd_month"] == pytest.approx(
        cap["recovery_subscribers_supported"] * 19.0, rel=0.01
    )


def test_invoices_are_marked_simulated(wired_db):
    """A demo row must never be mistakable for a real payment."""
    u = auth.create_user("inv@x.com", "password123", plan_id="recovery",
                         db_url=wired_db)
    assert plans.record_payment(u.user_id, plan_id="recovery",
                                subscription_usd=19.0, overage_usd=1.2) > 0

    conn = sqlite3.connect(plans.DB_PATH)
    status, total = conn.execute(
        "SELECT status, total_usd FROM invoices WHERE user_id = ?", (u.user_id,)
    ).fetchone()
    conn.close()
    assert status == "simulated"
    assert total == pytest.approx(20.2)
