"""
src/agents/peer_consult.py — the back-channel that lets one specialist ask
another a direct question mid-run.

What existed before this: agent-to-agent communication was strictly
one-directional. On a TEAM route the chain ran Surgeon -> PT -> Trainer ->
Nutritionist, each receiving upstream drafts and their structured constraints
as ``peer_context``. Real handoff, but no way back -- if the trainer needed to
know whether loaded knee flexion past 90 degrees was permitted, it could only
hedge ("check with your PT"), because nothing could route that question back.

What this adds: after the chain runs, the drafts are inspected for exactly
that situation. If one specialist genuinely needs something only another
specialist can answer, that question is put to the named specialist and the
reply is added to the evidence the synthesizer sees.

**Bounded by construction.** The orchestrator graph is a DAG and deliberately
"cannot loop" -- that is a documented safety property, not an accident. So
this is implemented as a single node that makes at most ``MAX_CONSULT_ROUNDS``
(1) round-trip, rather than as a cyclic graph edge. One extra detection call
plus at most one extra ``consult()``; it cannot ping-pong, and it cannot run
away with the token budget (a real constraint -- the free-tier daily cap has
been hit during testing more than once).

Never raises: any failure returns "no consult needed" and the pipeline
proceeds to synthesis exactly as before.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import get_llm  # noqa: E402

MAX_CONSULT_ROUNDS = 1

# Canonical agent keys -> how they're described to the detection prompt.
CONSULTABLE = {
    "surgeon": "orthopedic surgeon (post-op protocols, weight-bearing status, hardware, wound care, surgical timelines)",
    "pt": "physical therapist (pain vs soreness, rehab progression, range of motion, when to regress an exercise)",
    "trainer": "gym trainer (programming, sets/reps, progressive overload, exercise form, modifications)",
    "nutrition": "sports nutritionist (protein targets, healing micronutrients, post-op diet, hydration)",
}

_DETECT_PROMPT = ChatPromptTemplate.from_template(
    "You are reviewing drafts from an injury-recovery care team to see if one "
    "specialist needs a direct answer from another before the team responds.\n\n"
    "Available specialists:\n{roster}\n\n"
    "Patient question: {question}\n\n"
    "Specialist drafts:\n{drafts}\n\n"
    "Look for a specialist who deferred, hedged, or flagged that they needed "
    "information outside their own scope -- something a DIFFERENT specialist "
    "above could answer directly (e.g. a trainer unsure whether a movement is "
    "within post-op restrictions, or a nutritionist unsure of a surgical "
    "timeline).\n"
    "Only flag this when answering it would MATERIALLY change the team's "
    "advice. Routine 'talk to your doctor' disclaimers do NOT count.\n\n"
    "If no such need exists, respond with exactly: NONE\n"
    "Otherwise respond with exactly one line:\n"
    "ASK | <from_key> | <to_key> | <the specific question>\n"
    "where from_key and to_key are one of: surgeon, pt, trainer, nutrition "
    "(and must differ)."
)

_AGENT_LABELS = {
    "surgeon": "orthopedic_surgeon",
    "pt": "physical_therapist",
    "trainer": "gym_trainer",
    "nutrition": "nutritionist",
}


def detect_peer_question(question: str, drafts: dict[str, str]) -> dict | None:
    """Decide whether one specialist needs to ask another something.

    `drafts` maps agent key ("surgeon"/"pt"/"trainer"/"nutrition") to that
    specialist's draft text. Returns {"from", "to", "question"} or None.
    Never raises.
    """
    if len(drafts) < 2:
        # Nothing to ask across -- a single specialist has no peer here.
        return None
    try:
        roster = "\n".join(f"- {k}: {v}" for k, v in CONSULTABLE.items())
        rendered = "\n\n".join(
            f"{_AGENT_LABELS.get(k, k).upper()} ({k}) DRAFT:\n{v}" for k, v in drafts.items()
        )
        chain = _DETECT_PROMPT | get_llm() | StrOutputParser()
        raw = chain.invoke(
            {"roster": roster, "question": question, "drafts": rendered}
        ).strip()

        if not raw or raw.upper().startswith("NONE") or "ASK" not in raw.upper():
            return None

        line = next((ln for ln in raw.splitlines() if "|" in ln), "")
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            return None

        frm, to, ask = parts[1].lower(), parts[2].lower(), parts[3].strip()
        if frm not in CONSULTABLE or to not in CONSULTABLE or frm == to or not ask:
            return None
        # Strip any stray label the model prepended to the question text.
        ask = re.sub(r"^(question|ask)\s*[:\-]\s*", "", ask, flags=re.I).strip()
        return {"from": frm, "to": to, "question": ask}
    except Exception:
        # A failed detection means "no consult needed" -- synthesis proceeds
        # on the drafts it already has, exactly as before this feature.
        return None


def format_peer_exchange(peer_q: dict, answer: str) -> str:
    """Render the exchange as a labeled block for the synthesis evidence."""
    frm = _AGENT_LABELS.get(peer_q["from"], peer_q["from"]).replace("_", " ").title()
    to = _AGENT_LABELS.get(peer_q["to"], peer_q["to"]).replace("_", " ").title()
    return (
        f"PEER CONSULT — {frm} asked the {to}:\n"
        f"Q: {peer_q['question']}\n"
        f"A: {answer}"
    )
