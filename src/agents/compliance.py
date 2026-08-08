"""
src/agents/compliance.py — verifies the final answer against every restriction
any specialist stated, regardless of what order they ran in.

Why this exists: the team's ordering used to be fixed (surgeon -> PT ->
trainer -> nutrition, decision D4), which guaranteed *by construction* that a
restrictive specialist's constraints reached everyone downstream as binding
`peer_context`. Since D28 a small LM chooses the order, so that guarantee is
gone -- a plan of ["trainer", "surgeon"] produces a training plan written
before the surgeon's restrictions existed.

This recovers most of it after the fact: collect every constraint extracted
from every specialist that ran, then check the synthesized answer against
them. A violation is surfaced to the user rather than silently shipped,
because in a post-op context "your plan contradicts your surgeon's
restriction" is the single most consequential thing this system can get wrong.

Deliberately conservative: it only flags a violation when the answer
affirmatively recommends something a constraint forbids. Merely *mentioning* a
restricted movement (e.g. "avoid deep squatting") is not a violation -- that
is the system working.

Never raises. If the check itself fails, the answer passes through unchanged
with the failure noted in the trace, rather than blocking a legitimate answer
on a broken checker.
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import get_small_llm  # noqa: E402

COMPLIANCE_WARNING = (
    "\n\n> ⚠️ **Check with your care team before acting on this.** Part of this "
    "answer may not line up with a restriction one of your specialists gave: "
    "{details}"
)

_CHECK_PROMPT = ChatPromptTemplate.from_template(
    "You are auditing an injury-recovery answer for contradictions against the "
    "patient's stated restrictions.\n\n"
    "RESTRICTIONS (from the patient's own specialists — these are binding):\n"
    "{constraints}\n\n"
    "ANSWER GIVEN TO THE PATIENT:\n{answer}\n\n"
    "Does the answer AFFIRMATIVELY RECOMMEND doing something a restriction "
    "forbids?\n"
    "- Telling the patient to AVOID a restricted thing is NOT a violation.\n"
    "- Merely mentioning a restricted movement is NOT a violation.\n"
    "- Only recommending, permitting, or programming a forbidden thing counts.\n\n"
    "If there is no violation, respond with exactly: OK\n"
    "Otherwise respond with exactly one line:\n"
    "VIOLATION | <short description of what conflicts with which restriction>"
)


def _format_constraints(constraints_by_agent: dict[str, list[dict]]) -> str:
    lines = []
    for agent, items in (constraints_by_agent or {}).items():
        label = agent.replace("_", " ").title()
        for c in items or []:
            part = f" ({c['body_part']})" if c.get("body_part") else ""
            dur = f" for {c['duration']}" if c.get("duration") else ""
            lines.append(f"- [{label}] {c.get('restriction', '')}{part}{dur}")
    return "\n".join(lines)


def check_compliance(answer: str, constraints_by_agent: dict[str, list[dict]]) -> dict:
    """Check `answer` against all extracted constraints.

    Returns {"compliant": bool, "details": str, "checked": bool}.
    `checked` is False when there was nothing to check or the check failed —
    which is different from "checked and found compliant", and the caller
    should not report a clean bill of health it never actually established.
    """
    result = {"compliant": True, "details": "", "checked": False}

    formatted = _format_constraints(constraints_by_agent)
    if not formatted.strip() or not (answer or "").strip():
        return result

    try:
        raw = (_CHECK_PROMPT | get_small_llm() | StrOutputParser()).invoke(
            {"constraints": formatted, "answer": answer}
        ).strip()
        result["checked"] = True
        if raw.upper().startswith("VIOLATION"):
            parts = [p.strip() for p in raw.split("|", 1)]
            result["compliant"] = False
            result["details"] = parts[1] if len(parts) > 1 else "unspecified conflict"
    except Exception as exc:
        # A broken checker must not block a legitimate answer, but it also must
        # not be reported as a pass -- `checked` stays False.
        result["details"] = f"compliance check failed: {type(exc).__name__}: {exc}"
    return result
