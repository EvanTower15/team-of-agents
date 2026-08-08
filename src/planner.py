"""
src/planner.py — the small-LM orchestrator that decides WHICH specialists run
and IN WHAT ORDER.

Before this, agent selection came from the router's `scores` dict and the
*order* was hardcoded in the graph's conditional edges: surgeon -> PT ->
trainer -> nutritionist, always. That fixed order was decision D4 -- the
most-restrictive voice goes first so its constraints bound everyone
downstream via `peer_context`.

This module hands both decisions to a model (D28). That is a deliberate
architectural shift and it has a real cost, stated plainly because the
project's own docs used to claim the opposite:

    The system no longer guarantees by construction that a specialist's
    constraints reach the specialists who need them. A plan of
    ["trainer", "surgeon"] will produce a training plan written before the
    surgeon's post-op restrictions exist.

Three things keep that from becoming a safety hole:

1. RED_FLAG still runs on regex BEFORE this planner is ever called (D5).
   An emergency must never depend on a planning decision.
2. The prompt states most-restrictive-first as a strong, justified default,
   so the model has to actively decide otherwise rather than stumble into it.
3. `src/agents/compliance.py` re-checks the finished answer against every
   extracted constraint regardless of what order the plan ran in. That
   recovers most of what D4's fixed ordering guaranteed, after the fact
   instead of by construction.

Runs on the SMALL model (gpt-oss-20b, reasoning_effort=low): this is a
classification/selection task, and it is called once per question.

Never raises. On any failure it falls back to the router's own `scores`,
ordered most-restrictive-first -- i.e. exactly the pre-D28 behavior.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag_core import get_small_llm  # noqa: E402

VALID_AGENTS = ("surgeon", "pt", "trainer", "nutrition")

# Most-restrictive-first. Used to order the fallback plan, and as the tie-break
# the prompt is told to default to.
RESTRICTIVENESS_ORDER = {"surgeon": 0, "pt": 1, "trainer": 2, "nutrition": 3}

# A plan longer than the roster is nonsense, and repeated agents would just
# burn tokens re-asking the same specialist.
MAX_PLAN_LENGTH = len(VALID_AGENTS)

_PLANNER_PROMPT = ChatPromptTemplate.from_template(
    "You are the care coordinator for an injury-recovery team. Decide which "
    "specialists should answer this patient's question, and in what order.\n\n"
    "Specialists:\n"
    "- surgeon: post-operative protocols, weight-bearing status, surgical "
    "hardware, wound care, recovery timelines tied to a specific surgery\n"
    "- pt: pain vs soreness, rehab progression, range of motion, when to "
    "regress an exercise\n"
    "- trainer: workout programming, sets/reps, progressive overload, form, "
    "beginner and older-adult modifications\n"
    "- nutrition: protein targets, healing micronutrients, post-op diet, "
    "hydration\n\n"
    "ORDERING RULE — this matters for patient safety: each specialist you list "
    "receives the drafts of everyone before them as BINDING restrictions. So "
    "the most restrictive voice must come FIRST, or its limits arrive too late "
    "to constrain the plan. Default order is surgeon, then pt, then trainer, "
    "then nutrition. Only deviate if the question makes another order clearly "
    "better, and never place a training or nutrition specialist ahead of a "
    "surgeon or physical therapist whose restrictions would bound their advice.\n\n"
    "Include only specialists who genuinely add something. One is fine.\n\n"
    "Patient question: {question}\n\n"
    "Respond with ONLY a JSON object, no prose. Example of the SHAPE (write "
    "your own values, do not copy these):\n"
    '{{"agents": ["surgeon", "pt"], "reasoning": "Post-op restrictions must '
    'bound the rehab progression."}}'
)


def _fallback_plan(scores: dict | None) -> list[str]:
    """Pre-D28 behavior: whoever the router scored, most-restrictive-first."""
    scores = scores or {}
    chosen = [a for a in VALID_AGENTS if scores.get(a, 0) > 0]
    return sorted(chosen, key=lambda a: RESTRICTIVENESS_ORDER[a])


def _sanitize(agents: list, scores: dict | None) -> list[str]:
    """Drop unknown/duplicate agents, cap length, and never return empty."""
    seen, clean = set(), []
    for a in agents:
        key = str(a).strip().lower()
        if key in VALID_AGENTS and key not in seen:
            seen.add(key)
            clean.append(key)
        if len(clean) >= MAX_PLAN_LENGTH:
            break
    return clean or _fallback_plan(scores)


def plan_consultation(question: str, scores: dict | None = None) -> dict:
    """Decide which specialists to consult, in order.

    Returns {"agents": [...], "reasoning": str, "method": "llm"|"rules"}.
    Never raises -- falls back to the router's scores ordered
    most-restrictive-first.
    """
    fallback = {
        "agents": _fallback_plan(scores),
        "reasoning": "Router scores, most-restrictive-first.",
        "method": "rules",
    }
    if not question or not question.strip():
        return fallback

    try:
        raw = (_PLANNER_PROMPT | get_small_llm() | StrOutputParser()).invoke(
            {"question": question}
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return fallback
        data = json.loads(match.group(0))
        agents = data.get("agents")
        if not isinstance(agents, list):
            return fallback
        return {
            "agents": _sanitize(agents, scores),
            "reasoning": str(data.get("reasoning", ""))[:200] or "LLM plan.",
            "method": "llm",
        }
    except Exception:
        # A planner failure must never fail the turn -- degrade to the
        # deterministic ordering the system used before D28.
        return fallback


def violates_restrictiveness(agents: list[str]) -> list[str]:
    """Report ordering inversions, e.g. trainer placed before surgeon.

    Not enforced here -- the LM owns ordering by design (D28) -- but surfaced
    so the trace and the compliance check can see that constraints may have
    arrived too late to bind someone.
    """
    problems = []
    for i, later in enumerate(agents):
        for earlier in agents[:i]:
            if RESTRICTIVENESS_ORDER[later] < RESTRICTIVENESS_ORDER[earlier]:
                problems.append(f"{earlier} ran before {later}")
    return problems


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for q in (
        "I'm 6 weeks post ACL reconstruction - what squat depth is safe?",
        "Give me a 3-day beginner strength program.",
        "What should I eat to heal faster after surgery?",
    ):
        p = plan_consultation(q)
        print(f"Q: {q}\n   plan={p['agents']} ({p['method']}) - {p['reasoning']}\n")


if __name__ == "__main__":
    main()
