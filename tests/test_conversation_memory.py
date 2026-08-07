"""
tests/test_conversation_memory.py — follow-up resolution and the bounded
agent-to-agent peer-consult back-channel.

These cover the two structural properties that matter and can be asserted
without burning a live LLM call on every run:
  * history is optional and non-destructive (no history -> question untouched)
  * peer consult is genuinely bounded (cannot loop, cannot self-consult)
"""

import pytest

from src.agents.peer_consult import (
    CONSULTABLE,
    MAX_CONSULT_ROUNDS,
    format_peer_exchange,
)
from src.conversation import _format_history, resolve_followup


def test_no_history_leaves_question_untouched():
    """Backward compatibility: every pre-existing caller passes no history."""
    q = "What about my knee?"
    for history in (None, []):
        out = resolve_followup(q, history)
        assert out["resolved"] == q
        assert out["rewritten"] is False
        assert out["error"] is None


def test_empty_question_is_safe():
    out = resolve_followup("", [{"role": "user", "content": "hi"}])
    assert out["resolved"] == ""
    assert out["rewritten"] is False


def test_history_formatting_labels_speakers_and_truncates():
    history = [
        {"role": "user", "content": "I had ACL reconstruction 6 weeks ago."},
        {"role": "assistant", "content": "x" * 900},
        {"role": "system", "content": "ignored"},
    ]
    out = _format_history(history)
    assert "Patient: I had ACL reconstruction 6 weeks ago." in out
    assert "Care team:" in out
    assert "ignored" not in out  # non user/assistant roles are dropped
    # Long assistant answers are truncated so they can't dominate the prompt.
    assert len(out) < 900


def test_history_window_is_bounded():
    """Long conversations must not send the whole transcript every turn."""
    history = [{"role": "user", "content": f"turn {i}"} for i in range(50)]
    out = _format_history(history, max_turns=6)
    assert out.count("Patient:") == 6
    assert "turn 49" in out and "turn 0" not in out


def test_peer_consult_is_bounded_to_one_round():
    """The graph is a DAG that 'cannot loop' -- this cap is what preserves
    that property now that agents can consult each other."""
    assert MAX_CONSULT_ROUNDS == 1


def test_consultable_roster_matches_the_four_specialists():
    assert set(CONSULTABLE) == {"surgeon", "pt", "trainer", "nutrition"}


def test_format_peer_exchange_is_readable_and_attributed():
    block = format_peer_exchange(
        {"from": "trainer", "to": "surgeon", "question": "Is deep flexion permitted?"},
        "Avoid flexion past 90 degrees for now.",
    )
    assert "Gym Trainer asked the Orthopedic Surgeon" in block
    assert "Is deep flexion permitted?" in block
    assert "Avoid flexion past 90 degrees" in block


@pytest.mark.parametrize(
    "raw",
    [
        "NONE",
        "",
        "ASK | trainer | trainer | self-consult should be rejected",
        "ASK | trainer | dentist | not a real specialist",
        "ASK | trainer",  # malformed, too few fields
    ],
)
def test_detect_peer_question_rejects_bad_output(raw, monkeypatch):
    """A malformed or self-directed consult must resolve to 'no consult'
    rather than routing to a nonexistent agent."""
    import src.agents.peer_consult as pc

    monkeypatch.setattr(pc, "get_llm", lambda: None)
    monkeypatch.setattr(
        pc, "_DETECT_PROMPT", type("P", (), {"__or__": lambda self, o: _Chain(raw)})()
    )
    assert pc.detect_peer_question("q", {"trainer": "a", "surgeon": "b"}) is None


def test_detect_peer_question_needs_two_drafts():
    """One specialist alone has no peer to ask."""
    import src.agents.peer_consult as pc

    assert pc.detect_peer_question("q", {"trainer": "only one draft"}) is None


class _Chain:
    """Minimal stand-in for a LangChain runnable chain."""

    def __init__(self, out):
        self._out = out

    def __or__(self, other):
        return self

    def invoke(self, _payload):
        return self._out
