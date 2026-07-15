"""
src/agents/constraints.py — structured constraint extraction for agent-to-agent
handoff (extends decision D4).

Free-text peer_context works, but it makes a downstream specialist's LLM parse
restrictions out of prose and hope it caught them all. This module pulls a
short structured list out of a specialist's draft so restrictions can be
rendered unambiguously (and later surfaced to the UI), while the raw draft
still rides along in peer_context as before.

Never raises: extraction failure (bad JSON, LLM error) degrades to an empty
list, same "never crash the graph" convention as SpecialistAgent.consult().
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import get_llm  # noqa: E402

_EXTRACT_PROMPT = ChatPromptTemplate.from_template(
    "Extract any binding physical restrictions or precautions from the "
    "specialist note below that another specialist MUST follow when building "
    "a plan (e.g. weight-bearing limits, range-of-motion limits, activities to "
    "avoid, timelines). Return ONLY a JSON array, no prose, no markdown fences. "
    'Each item: {{"body_part": string, "restriction": string, "duration": '
    "string or null}}. If there are no binding restrictions, return [].\n\n"
    "Specialist note:\n{answer}\n\nJSON array:"
)

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def extract_constraints(answer: str) -> list[dict]:
    """Pull structured restrictions out of a specialist's draft answer.

    Returns a list of {"body_part", "restriction", "duration"} dicts, or []
    if there are none or extraction fails for any reason.
    """
    if not answer or not answer.strip():
        return []
    try:
        chain = _EXTRACT_PROMPT | get_llm() | StrOutputParser()
        raw = chain.invoke({"answer": answer})
    except Exception:
        return []

    match = _ARRAY_RE.search(raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("restriction"):
            continue
        duration = item.get("duration")
        out.append(
            {
                "body_part": str(item.get("body_part") or "").strip(),
                "restriction": str(item["restriction"]).strip(),
                "duration": str(duration).strip() if duration else None,
            }
        )
    return out


def format_constraints_block(constraints: list[dict], label: str) -> str:
    """Render constraints as a labeled bullet block for peer_context, or ""
    if there are none."""
    if not constraints:
        return ""
    lines = [f"BINDING RESTRICTIONS FROM {label} (follow exactly):"]
    for c in constraints:
        part = f" ({c['body_part']})" if c["body_part"] else ""
        dur = f" for {c['duration']}" if c["duration"] else ""
        lines.append(f"- {c['restriction']}{part}{dur}")
    return "\n".join(lines) + "\n\n"
