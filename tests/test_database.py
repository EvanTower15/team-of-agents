"""
tests/test_database.py — multi-session chat persistence (src/database.py).

Ported from opim-5517's HW8 persistence tests and extended for this project's
multi-agent transcript columns, titles, and session management.

Each test gets its own temp-file SQLite DB via the `temp_db_url` fixture, so they
are isolated, fast, and need no GROQ_API_KEY.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src import database as db


@pytest.fixture
def temp_db_url(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test_chat.db').as_posix()}"
    db.init_db(url)
    return url


def test_session_and_transcript_roundtrip(temp_db_url):
    sid = db.create_session({"client": "pytest"}, db_url=temp_db_url)
    row_id = db.save_transcript(
        sid,
        "How do I get back to lifting 8 weeks after meniscus surgery?",
        "Start with bodyweight movements, then...",
        "TEAM",
        route_confidence=0.91,
        agents_consulted=["orthopedic_surgeon", "physical_therapist", "gym_trainer"],
        sources={"physical_therapist": ["choose_pt_meniscus.md"]},
        constraints={
            "orthopedic_surgeon": [
                {"restriction": "No deep squatting", "body_part": "knee", "duration": "4 weeks"}
            ]
        },
        execution_trace=["router: TEAM (0.91)", "consult_surgeon: ok"],
        tokens={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        cost_usd=0.000075,
        db_url=temp_db_url,
    )
    assert row_id == 1

    rows = db.get_session_transcripts(sid, db_url=temp_db_url)
    assert len(rows) == 1
    t = rows[0]
    assert t.route_used == "TEAM"
    assert t.route_confidence == 0.91
    assert (t.input_tokens, t.output_tokens, t.total_tokens) == (100, 20, 120)
    assert t.user_query.startswith("How do I get back to lifting")

    # The JSON columns must come back as the structures the UI renders.
    meta = db.transcript_meta(t)
    assert meta["agents_consulted"] == [
        "orthopedic_surgeon",
        "physical_therapist",
        "gym_trainer",
    ]
    assert meta["sources"]["physical_therapist"] == ["choose_pt_meniscus.md"]
    assert meta["constraints"]["orthopedic_surgeon"][0]["body_part"] == "knee"
    assert len(meta["execution_trace"]) == 2
    assert meta["tokens"]["total_tokens"] == 120


def test_save_result_maps_orchestrator_dict(temp_db_url):
    """save_result() should unpack the §5.4 contract dict without the caller helping."""
    sid = db.create_session(db_url=temp_db_url)
    result = {
        "final_answer": "Ice it and see a clinician.",
        "route": "RED_FLAG",
        "route_confidence": 1.0,
        "agents_consulted": [],
        "sources": {},
        "constraints": {},
        "execution_trace": ["red_flag: matched 'numbness'"],
    }
    db.save_result(sid, "My foot is numb after surgery", result, db_url=temp_db_url)

    (t,) = db.get_session_transcripts(sid, db_url=temp_db_url)
    assert t.route_used == "RED_FLAG"
    assert t.agent_response == "Ice it and see a clinician."
    assert db.transcript_meta(t)["execution_trace"] == ["red_flag: matched 'numbness'"]


def test_transcript_meta_tolerates_missing_metadata(temp_db_url):
    """A turn saved with no metadata still renders: no None leaks to the UI."""
    sid = db.create_session(db_url=temp_db_url)
    db.save_transcript(sid, "q", "a", None, db_url=temp_db_url)

    (t,) = db.get_session_transcripts(sid, db_url=temp_db_url)
    meta = db.transcript_meta(t)
    assert meta["route"] == "?"
    assert meta["route_confidence"] == 0.0  # would break the `:.2f` route chip
    assert meta["agents_consulted"] == []
    assert meta["sources"] == {} and meta["constraints"] == {}


def test_foreign_key_rejects_orphan_transcript(temp_db_url):
    with pytest.raises(IntegrityError):
        db.save_transcript("no-such-session", "q", "a", "TEAM", db_url=temp_db_url)


def test_title_backfilled_from_first_question(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    assert db.get_session(sid, db_url=temp_db_url).title is None

    db.save_transcript(sid, "Rotator cuff rehab timeline?", "…", "PT_ONLY", db_url=temp_db_url)
    assert db.get_session(sid, db_url=temp_db_url).title == "Rotator cuff rehab timeline?"

    # A later turn must not overwrite the established title.
    db.save_transcript(sid, "And nutrition?", "…", "TEAM", db_url=temp_db_url)
    assert db.get_session(sid, db_url=temp_db_url).title == "Rotator cuff rehab timeline?"


def test_long_title_is_truncated(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    db.save_transcript(sid, "knee " * 100, "…", "TEAM", db_url=temp_db_url)
    title = db.get_session(sid, db_url=temp_db_url).title
    assert len(title) <= db.TITLE_MAX_CHARS
    assert title.endswith("…")


def test_saving_a_turn_bumps_updated_at(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    before = db.get_session(sid, db_url=temp_db_url).updated_at
    db.save_transcript(sid, "q", "a", "TEAM", db_url=temp_db_url)
    assert db.get_session(sid, db_url=temp_db_url).updated_at >= before


def test_list_sessions_orders_by_recent_activity(temp_db_url):
    """A revisited old chat outranks a newer idle one — sidebar ordering."""
    old = db.create_session(db_url=temp_db_url)
    new = db.create_session(db_url=temp_db_url)
    db.save_transcript(old, "revisited", "a", "TEAM", db_url=temp_db_url)

    ids = [s.session_id for s in db.list_sessions(db_url=temp_db_url)]
    assert {old, new} <= set(ids)
    assert ids.index(old) < ids.index(new)


def test_sessions_stay_isolated(temp_db_url):
    """Two concurrent chats must not see each other's turns."""
    a = db.create_session(db_url=temp_db_url)
    b = db.create_session(db_url=temp_db_url)
    db.save_transcript(a, "chat A", "a", "PT_ONLY", db_url=temp_db_url)
    db.save_transcript(b, "chat B", "b", "TRAINER_ONLY", db_url=temp_db_url)

    assert [t.user_query for t in db.get_session_transcripts(a, db_url=temp_db_url)] == ["chat A"]
    assert [t.user_query for t in db.get_session_transcripts(b, db_url=temp_db_url)] == ["chat B"]


def test_session_stats_aggregates_tokens_and_cost(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    for _ in range(3):
        db.save_transcript(
            sid,
            "q",
            "a",
            "TEAM",
            tokens={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            cost_usd=0.0001,
            db_url=temp_db_url,
        )
    stats = db.session_stats(sid, db_url=temp_db_url)
    assert stats["turns"] == 3
    assert stats["total_tokens"] == 45
    assert stats["cost_usd"] == pytest.approx(0.0003)


def test_session_stats_on_empty_session(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    assert db.session_stats(sid, db_url=temp_db_url) == {
        "turns": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def test_rename_session(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    assert db.rename_session(sid, "ACL recovery plan", db_url=temp_db_url) is True
    assert db.get_session(sid, db_url=temp_db_url).title == "ACL recovery plan"
    assert db.rename_session("nope", "x", db_url=temp_db_url) is False


def test_delete_session_removes_its_transcripts(temp_db_url):
    sid = db.create_session(db_url=temp_db_url)
    db.save_transcript(sid, "q", "a", "TEAM", db_url=temp_db_url)
    keep = db.create_session(db_url=temp_db_url)
    db.save_transcript(keep, "keep me", "a", "TEAM", db_url=temp_db_url)

    assert db.delete_session(sid, db_url=temp_db_url) is True
    assert db.get_session(sid, db_url=temp_db_url) is None
    assert db.get_session_transcripts(sid, db_url=temp_db_url) == []
    assert db.delete_session(sid, db_url=temp_db_url) is False

    # The other conversation is untouched.
    assert len(db.get_session_transcripts(keep, db_url=temp_db_url)) == 1


def test_wal_mode_enabled(temp_db_url):
    engine = db.init_db(temp_db_url)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
