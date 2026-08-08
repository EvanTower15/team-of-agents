"""
tests/test_planner_and_tools.py — the LM planner, the specialist tools, and
the compliance check that backstops LM-chosen ordering.

Focused on the properties that must hold regardless of what any model decides:
bounds are enforced, the PubMed gate is code-enforced rather than
prompt-requested, knowledge siloing survives tool access, and calculators
return errors instead of raising on junk input.
"""

import pytest

from src.agents.compliance import _format_constraints, check_compliance
from src.planner import (
    MAX_PLAN_LENGTH,
    RESTRICTIVENESS_ORDER,
    VALID_AGENTS,
    _fallback_plan,
    _sanitize,
    violates_restrictiveness,
)
from src.tools.calculators import (
    CALCULATOR_FUNCTIONS,
    CALCULATOR_SCHEMAS,
    convert_weight,
    estimate_one_rep_max,
    protein_target,
    training_load,
    weeks_post_op_phase,
)


# ── planner ──────────────────────────────────────────────────────────────────

def test_fallback_plan_is_most_restrictive_first():
    """When planning fails we must land on the pre-D28 ordering, not any order."""
    plan = _fallback_plan({"trainer": 1, "surgeon": 1, "nutrition": 1, "pt": 1})
    assert plan == ["surgeon", "pt", "trainer", "nutrition"]


def test_fallback_plan_only_includes_scored_agents():
    assert _fallback_plan({"trainer": 1, "surgeon": 0}) == ["trainer"]
    assert _fallback_plan({}) == []
    assert _fallback_plan(None) == []


def test_sanitize_drops_unknown_and_duplicate_agents():
    """A hallucinated agent name must not reach the graph as a node key."""
    assert _sanitize(["surgeon", "dentist", "surgeon", "pt"], None) == ["surgeon", "pt"]


def test_sanitize_caps_plan_length():
    """Bounds the one cycle in the graph -- at most one turn per specialist."""
    plan = _sanitize(["surgeon", "pt", "trainer", "nutrition"] * 3, None)
    assert len(plan) <= MAX_PLAN_LENGTH


def test_sanitize_never_returns_empty_when_scores_exist():
    """Garbage from the model degrades to the router's scores, not to nothing."""
    assert _sanitize(["bogus"], {"pt": 1}) == ["pt"]


def test_violates_restrictiveness_detects_inversions():
    """This is what surfaces 'constraints arrived too late' to the trace."""
    assert violates_restrictiveness(["trainer", "surgeon"]) == ["trainer ran before surgeon"]
    assert violates_restrictiveness(["surgeon", "pt", "trainer"]) == []


def test_restrictiveness_order_covers_every_agent():
    assert set(RESTRICTIVENESS_ORDER) == set(VALID_AGENTS)


# ── calculators ──────────────────────────────────────────────────────────────

def test_protein_target_math():
    out = protein_target(80, "kg", 1.6)
    assert out["error"] is None
    assert out["grams_per_day"] == pytest.approx(128.0)


def test_protein_target_converts_pounds():
    out = protein_target(180, "lb", 1.6)
    assert out["bodyweight_kg"] == pytest.approx(81.6, abs=0.2)


def test_weight_conversion_roundtrips():
    kg = convert_weight(100, "lb", "kg")["value"]
    assert convert_weight(kg, "kg", "lb")["value"] == pytest.approx(100, abs=0.1)


def test_training_load_and_one_rep_max():
    assert training_load(300, 70)["weight"] == pytest.approx(210.0)
    assert estimate_one_rep_max(225, 5)["estimated_1rm"] == pytest.approx(262.5, abs=0.1)


@pytest.mark.parametrize("weeks,expected", [(1, "acute"), (6, "progressive"), (30, "return-to-sport")])
def test_weeks_post_op_phase_bands(weeks, expected):
    assert expected in weeks_post_op_phase(weeks)["phase"]


def test_post_op_phase_defers_to_the_surgeon():
    """The band is conventional; a patient's own protocol always wins, and the
    tool has to say so or a specialist could quote it as authoritative."""
    assert "surgeon" in weeks_post_op_phase(6)["note"].lower()


@pytest.mark.parametrize(
    "call",
    [
        lambda: protein_target("abc"),
        lambda: protein_target(-5),
        lambda: training_load(300, 500),          # 500% of 1RM
        lambda: convert_weight(10, "kg", "stone"),
        lambda: estimate_one_rep_max(225, 99),     # rep count out of range
    ],
)
def test_calculators_return_errors_instead_of_raising(call):
    """A malformed tool call from a model must degrade to a readable error,
    never an exception that would crash the consult."""
    assert call().get("error")


def test_every_calculator_schema_has_an_implementation():
    """Schema drift would advertise a tool the dispatcher cannot run."""
    advertised = {s["function"]["name"] for s in CALCULATOR_SCHEMAS}
    assert advertised == set(CALCULATOR_FUNCTIONS)


# ── tool gating / siloing ────────────────────────────────────────────────────

def test_pubmed_is_withheld_unless_corpus_came_back_empty():
    """The miss-path gate is enforced in code, not requested in a prompt."""
    from src.agents.nutritionist import NutritionistAgent

    agent = NutritionistAgent()
    with_corpus = {t["function"]["name"] for t in agent._available_tools(False)}
    without = {t["function"]["name"] for t in agent._available_tools(True)}
    assert "search_pubmed" not in with_corpus
    assert "search_pubmed" in without
    # The own-corpus re-query is always available -- it is never the risky one.
    assert "search_my_corpus" in with_corpus


def test_corpus_search_cannot_be_pointed_at_another_specialist(monkeypatch):
    """Knowledge siloing (D3) must survive tool access: the collection name is
    injected by the agent, never taken from model-supplied arguments."""
    from src.agents.gym_trainer import GymTrainerAgent
    import src.agents.base as base

    seen = {}

    def fake_search(query, collection_name, k=4):
        seen["collection"] = collection_name
        return {"passages": [], "count": 0, "error": None}

    monkeypatch.setattr(base, "search_my_corpus", fake_search)
    agent = GymTrainerAgent()
    # A model trying to read the surgeon's corpus supplies it as an argument.
    agent._dispatch_tool("search_my_corpus", {"query": "x", "collection_name": "surgeon_docs"})
    assert seen["collection"] == agent.collection_name != "surgeon_docs"


def test_unknown_tool_name_is_reported_not_raised():
    from src.agents.gym_trainer import GymTrainerAgent

    payload, sources = GymTrainerAgent()._dispatch_tool("definitely_not_a_tool", {})
    assert "unknown tool" in payload["error"]
    assert sources == []


# ── compliance ───────────────────────────────────────────────────────────────

def test_compliance_skips_cleanly_with_nothing_to_check():
    """`checked` False must be distinguishable from 'checked and compliant' --
    otherwise the trace would report a clean bill of health never established."""
    out = check_compliance("some answer", {})
    assert out["checked"] is False
    assert out["compliant"] is True


def test_compliance_skips_on_empty_answer():
    out = check_compliance("", {"physical_therapist": [{"restriction": "no deep squats"}]})
    assert out["checked"] is False


def test_constraint_formatting_labels_the_source_specialist():
    text = _format_constraints(
        {"orthopedic_surgeon": [
            {"restriction": "no flexion past 90 degrees", "body_part": "knee", "duration": "6 weeks"}
        ]}
    )
    assert "Orthopedic Surgeon" in text
    assert "no flexion past 90 degrees" in text
    assert "knee" in text and "6 weeks" in text
