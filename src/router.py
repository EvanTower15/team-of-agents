"""
src/router.py — route classifier for the recovery team (Phase 4, redesigned Phase 4c).

Decides which specialist(s) a question goes to:

    PT_ONLY       -> physical therapist (pain, rehab, mobility)
    TRAINER_ONLY  -> gym trainer (programming, form, getting active)
    SURGEON       -> orthopedic surgeon (post-op protocols, timelines, hardware)
    TEAM          -> more than one specialist, chained most-restrictive-first
    RED_FLAG      -> deterministic safety response, NO LLM ever (decision D5)
    CLARIFY       -> too vague to route safely; ask one follow-up

Strategy (Phase 4c, D11 — supersedes the Phase 4/4b weighted-regex scorer):
    1. RED_FLAG regexes are checked FIRST and always win — health safety must
       not depend on LLM behavior. This is the one place regex stays load-bearing.
    2. Everything else goes straight to the Groq/Llama classifier, which also
       names which specialist(s) apply (so the orchestrator's TEAM chain still
       knows who to consult, same as the old ``RouteDecision.scores``).
    3. If the LLM is unsure (confidence below CLARIFY_THRESHOLD) or unavailable
       (no key, network error), the route collapses to CLARIFY rather than
       guessing — never crashes, per the codebase's "never raise" convention.

Trade-off, on purpose: every non-RED_FLAG question now costs one Groq call
instead of being resolved for free by keyword weights. Hand-tuned regex cue
lists were proving brittle (subtle misses like "stitches come out" not
matching "stitches out") and needed constant patching as the specialist roster
grew; a classifier generalizes without new patterns per phrasing.

Run standalone:
    python -m src.router "Can I do cardio while rehabbing an ankle sprain?"
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Route labels (contract §5.3) and thresholds
# ─────────────────────────────────────────────────────────────────────────────

PT_ONLY = "PT_ONLY"
TRAINER_ONLY = "TRAINER_ONLY"
TEAM = "TEAM"
CLARIFY = "CLARIFY"
RED_FLAG = "RED_FLAG"
SURGEON = "SURGEON"

VALID_LABELS = (PT_ONLY, TRAINER_ONLY, SURGEON, TEAM, CLARIFY, RED_FLAG)
# Labels the LLM may assign -- RED_FLAG is regex-only and never reaches it.
_LLM_LABELS = (PT_ONLY, TRAINER_ONLY, SURGEON, TEAM, CLARIFY)

CLARIFY_THRESHOLD = 0.50  # LLM confidence below this collapses to CLARIFY

MODEL = "llama-3.3-70b-versatile"

_EMPTY_SCORES = {"pt": 0, "trainer": 0, "surgeon": 0}


@dataclass
class RouteDecision:
    """Structured routing result that flows into the LangGraph state."""

    label: str
    confidence: float
    reasoning: str
    method: str  # "rules" | "llm"
    scores: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.label} (confidence={self.confidence:.2f}, via {self.method}) "
            f"- {self.reasoning}"
        )


def _c(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# RED_FLAG cues — checked first, deterministic, always win (§6.2, D5)
# ─────────────────────────────────────────────────────────────────────────────

_RED_FLAG_CUES = [
    _c(r"\b(?:severe|sharp|unbearable|excruciating|intense) pain\b"),
    _c(r"\bnumb(?:ness)?\b|\btingling\b"),
    _c(r"\bcan(?:'?t|not) (?:bear|put) (?:any )?weight\b"),
    _c(r"\bdeform(?:ed|ity)\b"),
    _c(r"\bfever\b|\bchills\b"),
    _c(r"\bchest pain\b|\bshort(?:ness)? of breath\b"),
    _c(r"\bcalf\b.{0,40}\b(?:swollen|swelling|hot)\b|\b(?:swollen|hot)\b.{0,40}\bcalf\b"),
    _c(r"\b(?:felt|heard) (?:a |something )?pop\b"),
    _c(r"\bbuckl\w+\b|\bgives? (?:way|out)\b|\bgave (?:way|out)\b"),
    _c(r"\bincision\b|\bsurgical wound\b|\bstitches?\b.{0,30}\b(?:open|red|ooz|leak)\w*"),
]

# Canned response lives in orchestrator.py (§7.3); the router only labels.


# ─────────────────────────────────────────────────────────────────────────────
# LLM classifier — the primary decision path for everything but RED_FLAG
# ─────────────────────────────────────────────────────────────────────────────

_ROUTER_PROMPT = ChatPromptTemplate.from_template(
    "You are a routing classifier for an injury-recovery support team with "
    "three specialists: an orthopedic surgeon, a physical therapist, and a "
    "gym trainer.\n"
    "Read the question and decide two things:\n"
    "1. Which specialist(s) are relevant to answering it: any combination of "
    "'pt', 'trainer', 'surgeon'.\n"
    "2. A single overall LABEL summarizing that:\n"
    "   - PT_ONLY: only the physical therapist is relevant (pain, injuries, "
    "rehab progression, soreness-vs-injury, range of motion, mobility).\n"
    "   - TRAINER_ONLY: only the gym trainer is relevant (workout programming, "
    "exercise form, strength/cardio guidelines, getting active as a beginner "
    "or older adult).\n"
    "   - SURGEON: only the orthopedic surgeon is relevant (post-operative "
    "protocols, weight-bearing status, surgical hardware, wound/incision "
    "care, recovery timelines tied to a specific surgery).\n"
    "   - TEAM: more than one specialist is relevant -- e.g. returning to "
    "training while recovering from an injury or surgery.\n"
    "   - CLARIFY: too vague or underspecified to route safely -- no "
    "specialist applies yet.\n"
    "Do NOT use RED_FLAG -- urgent medical warning signs are handled "
    "separately, before you ever see the question.\n\n"
    "IMPORTANT: if the question mentions a specific surgery, a surgeon's "
    "clearance/instructions, surgical hardware, or a post-op timeline or "
    "milestone -- even if that surgeon involvement already happened (e.g. "
    "\"my surgeon already cleared me\") -- always include 'surgeon' in "
    "specialists. The surgeon's post-op protocol still constrains what the "
    "other specialists can safely recommend; it does not stop applying just "
    "because the clearance was already given.\n\n"
    "EXAMPLES:\n"
    "Q: \"What's the best gym?\"\n"
    "THOUGHT: The user is asking a broad question lacking any context about their physical condition, goals, or injury status.\n"
    "DECISION: CLARIFY | 0.9 | | Need more context about goals or injuries.\n\n"
    "Q: \"My surgeon cleared me for lifting after ACL reconstruction\"\n"
    "THOUGHT: The user is transitioning back to training post-surgery. This requires the surgeon's post-op protocol, the PT for rehab, and the trainer for lifting.\n"
    "DECISION: TEAM | 0.95 | pt,trainer,surgeon | Transition to lifting post-op requires full team alignment.\n\n"
    "Q: \"My surgeon cleared me for full weight-bearing 6 weeks after knee surgery -- how do I get back into leg training?\"\n"
    "THOUGHT: The clearance already happened, but the surgeon's weight-bearing timeline still bounds what the PT and trainer can safely plan, so all three specialists apply.\n"
    "DECISION: TEAM | 0.95 | pt,trainer,surgeon | Post-op weight-bearing status still constrains PT/trainer planning even though clearance was already given.\n\n"
    "Q: \"My knee hurts when I squat\"\n"
    "THOUGHT: The user is experiencing pain during a specific movement, which requires a physical therapist to diagnose or provide rehab exercises.\n"
    "DECISION: PT_ONLY | 0.9 | pt | Pain during movement requires PT assessment.\n\n"
    "Question: {question}\n\n"
    "Respond using EXACTLY the following two-line format:\n"
    "THOUGHT: <Brief 1-2 sentence analysis of the user's intent and required expertise>\n"
    "DECISION: LABEL | confidence | specialists | one short reason\n"
    "where LABEL is one of PT_ONLY, TRAINER_ONLY, SURGEON, TEAM, CLARIFY; "
    "confidence is a decimal between 0 and 1; specialists is a comma-separated "
    "subset of pt,trainer,surgeon (empty if CLARIFY)."
)


def _parse_llm_response(raw: str) -> RouteDecision:
    """Parse 'LABEL | confidence | specialists | reason' robustly (tolerates
    messy output -- scans the whole response rather than trusting exact
    formatting, same defensive posture as the rest of this codebase)."""

    # Extract the decision line for specialists and reason parsing
    decision_line = next((ln for ln in raw.strip().splitlines() if ln.strip().startswith("DECISION:")), raw.strip())
    if decision_line.startswith("DECISION:"):
        decision_line = decision_line[len("DECISION:"):].strip()

    label, pos = CLARIFY, None
    for cand in _LLM_LABELS:
        m = re.search(rf"\b{cand}\b", decision_line)
        if m and (pos is None or m.start() < pos):
            label, pos = cand, m.start()

    conf = 0.5
    for token in re.findall(r"\d*\.\d+|\b[01]\b", raw):
        try:
            val = float(token)
        except ValueError:
            continue
        if 0.0 <= val <= 1.0:
            conf = val
            break

    parts = [x.strip() for x in decision_line.split("|")]

    # Single-label routes always imply exactly that one specialist, regardless
    # of what the model put in the specialists field -- keeps `scores` honest
    # even if the model's list was empty or malformed.
    if label == PT_ONLY:
        scores = {"pt": 1, "trainer": 0, "surgeon": 0}
    elif label == TRAINER_ONLY:
        scores = {"pt": 0, "trainer": 1, "surgeon": 0}
    elif label == SURGEON:
        scores = {"pt": 0, "trainer": 0, "surgeon": 1}
    elif label == TEAM:
        named_field = parts[2] if len(parts) >= 4 else ""
        named = {tok.strip().lower() for tok in named_field.split(",") if tok.strip()}
        scores = {name: (1 if name in named else 0) for name in ("pt", "trainer", "surgeon")}
        # A model that says TEAM but names <2 specialists is being inconsistent;
        # default to all three rather than silently under-chaining.
        if sum(scores.values()) < 2:
            scores = {"pt": 1, "trainer": 1, "surgeon": 1}
    else:
        scores = dict(_EMPTY_SCORES)

    reason = parts[-1] if len(parts) >= 2 else decision_line
    reason = re.sub(r"\s+", " ", reason).strip()[:200]

    return RouteDecision(
        label, round(max(0.0, min(1.0, conf)), 2), reason or "LLM classification.", "llm", scores
    )


def _classify_with_llm(question: str) -> RouteDecision:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set; cannot run the LLM router.")
    from langchain_groq import ChatGroq

    llm = ChatGroq(model=MODEL, temperature=0, groq_api_key=api_key)
    raw = (_ROUTER_PROMPT | llm | StrOutputParser()).invoke({"question": question})
    return _parse_llm_response(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (contract §5.3)
# ─────────────────────────────────────────────────────────────────────────────


def classify(question: str) -> RouteDecision:
    """Classify a question into one of six routes.

    RED_FLAG first (deterministic regex, always wins, D5). Everything else
    goes straight to the LLM classifier (D11): low LLM confidence, or the LLM
    being unavailable, collapses to CLARIFY rather than guessing.
    """
    q = (question or "").strip()
    if not q:
        return RouteDecision(CLARIFY, 0.90, "Empty question.", "rules", dict(_EMPTY_SCORES))

    for rx in _RED_FLAG_CUES:
        m = rx.search(q)
        if m:
            return RouteDecision(
                RED_FLAG, 0.97,
                f"Urgent-care cue matched: '{m.group(0)}'.",
                "rules", {"red_flag": m.group(0)},
            )

    try:
        decision = _classify_with_llm(q)
    except Exception as exc:
        return RouteDecision(
            CLARIFY, 0.50,
            f"Could not classify: LLM unavailable ({exc}).",
            "rules", dict(_EMPTY_SCORES),
        )

    if decision.confidence < CLARIFY_THRESHOLD and decision.label != CLARIFY:
        decision.reasoning = f"Low confidence ({decision.confidence:.2f}) - {decision.reasoning}"
        decision.label = CLARIFY
        decision.scores = dict(_EMPTY_SCORES)
    return decision


def main() -> None:
    question = " ".join(sys.argv[1:]) or "Can I do cardio while rehabbing an ankle sprain?"
    print(f"Question: {question}")
    print(classify(question))


if __name__ == "__main__":
    main()
