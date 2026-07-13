"""
src/router.py — route classifier for the recovery team (Phase 4).

Decides which specialist(s) a question goes to:

    PT_ONLY       -> physical therapist (pain, rehab, mobility, post-op progression)
    TRAINER_ONLY  -> gym trainer (programming, form, getting active)
    TEAM          -> PT first, then trainer with the PT draft as binding context
    RED_FLAG      -> deterministic safety response, NO LLM ever (decision D5)
    CLARIFY       -> too vague to route safely; ask one follow-up

Strategy (ported from the opim-5517 reference router):
    1. RED_FLAG regexes are checked FIRST and always win — health safety must
       not depend on LLM behavior.
    2. A weighted keyword scorer handles the clear cases with a confidence
       derived from how strong and one-sided the cues are.
    3. Below RULES_CONFIDENCE_THRESHOLD the Groq/Llama classifier decides;
       if even the LLM is unsure, the route collapses to CLARIFY.

Most questions never touch the LLM, and the deterministic path is fully
inspectable via ``RouteDecision.scores``.

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
# Phase B adds: SURGEON = "SURGEON"

VALID_LABELS = (PT_ONLY, TRAINER_ONLY, TEAM, CLARIFY, RED_FLAG)

RULES_CONFIDENCE_THRESHOLD = 0.62  # below this, consult the LLM
CLARIFY_THRESHOLD = 0.50           # LLM confidence below this collapses to CLARIFY

MODEL = "llama-3.3-70b-versatile"


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
# Specialist cues — weighted; stronger, less ambiguous signals weigh more
# ─────────────────────────────────────────────────────────────────────────────

_PT_CUES = [
    (_c(r"\bpain(?:ful)?\b"), 2),
    (_c(r"\baches?\b|\baching\b|\bhurts?\b|\bhurting\b"), 2),
    (_c(r"\bsore(?:ness)?\b"), 2),
    (_c(r"\bsprain\w*\b|\bstrain\w*\b"), 2),
    (_c(r"\binjur\w+\b"), 2),
    (_c(r"\brehab\w*\b"), 2),
    (_c(r"\brecover\w*\b"), 1),
    (_c(r"\bphysical therap\w+\b|\bphysio\w*\b"), 3),
    (_c(r"\bpost-?op\w*\b|\bpost-?surg\w*\b|\bsurgery\b|\boperation\b"), 2),
    (_c(r"\brange of motion\b|\brom\b"), 3),
    (_c(r"\bstretch\w*\b"), 1),
    (_c(r"\bswell\w*\b|\bswollen\b|\bstiff\w*\b"), 1),
    (_c(r"\bmobility\b|\bflexib\w+\b"), 1),
    (_c(r"\btendon\b|\bligament\b|\bmeniscus\b|\brotator cuff\b|\bacl\b|\bmcl\b"), 2),
    (_c(r"\bcrutch\w*\b|\bbrace\b|\bcast\b"), 2),
]

_TRAINER_CUES = [
    (_c(r"\bworkouts?\b|\bworking out\b"), 2),
    (_c(r"\bgym\b"), 2),
    (_c(r"\bprogram\w*\b|\broutine\b|\bregimen\b|\btraining plan\b"), 2),
    (_c(r"\bsets?\b|\breps?\b|\brepetitions?\b"), 2),
    (_c(r"\bprogressive overload\b"), 3),
    (_c(r"\bstrength\b|\bstrength training\b"), 1),
    (_c(r"\bcardio\b|\baerobic\b|\bendurance\b"), 2),
    (_c(r"\bdumbbells?\b|\bbarbells?\b|\bkettlebells?\b|\bmachines?\b|\bresistance bands?\b"), 2),
    (_c(r"\bform\b|\btechnique\b"), 1),
    (_c(r"\bwarm-? ?ups?\b"), 1),
    (_c(r"\bbeginner\b|\bnovice\b"), 2),
    (_c(r"\blift(?:s|ing)?\b|\bweights?\b"), 2),
    (_c(r"\bget(?:ting)? (?:active|in shape|fit|started)\b|\bwhere do i start\b"), 2),
    (_c(r"\bexercis\w+\b"), 1),
    (_c(r"\bprotein\b|\bsupplements?\b|\bnutrition\b|\bdiet\b"), 2),
    (_c(r"\bbuild(?:ing)? muscle\b|\bmuscle growth\b"), 2),
]

# Subjective / contentless markers: only force CLARIFY when the domain signal
# is weak, so "best exercises for a sprained knee" still routes normally.
_VAGUE_CUES = _c(
    r"\b(?:best|better|good|great|worst|favou?rite|help|anything|something|stuff|tell me)\b"
)


def _score_rules(question: str) -> tuple[int, int]:
    p = sum(w for rx, w in _PT_CUES if rx.search(question))
    t = sum(w for rx, w in _TRAINER_CUES if rx.search(question))
    return p, t


def _decide_from_scores(question: str, p: int, t: int) -> RouteDecision | None:
    """Turn cue scores into a RouteDecision, or None to defer to the LLM."""
    n_tokens = len(re.findall(r"\w+", question))
    total = p + t
    scores = {"pt": p, "trainer": t}

    # No or weak domain signal + short/subjective phrasing -> ask, don't guess.
    if n_tokens <= 2 or (total <= 2 and _VAGUE_CUES.search(question)):
        return RouteDecision(
            CLARIFY, 0.70,
            "Too short or subjective with little domain signal.",
            "rules", scores,
        )
    if total == 0:
        return None  # has content but nothing we recognise -> LLM decides

    # Both specialists signalled and neither dominates -> the TEAM route
    # (PT consults first; trainer builds around the PT's constraints — D4).
    if p > 0 and t > 0:
        dominance = max(p, t) / total
        if dominance <= 0.70:
            conf = 0.55 + 0.35 * min(1.0, total / 4.0)
            return RouteDecision(
                TEAM, round(conf, 2),
                f"Both rehab ({p}) and training ({t}) cues present.",
                "rules", scores,
            )
        label = PT_ONLY if p > t else TRAINER_ONLY
        strength = min(1.0, max(p, t) / 3.0)
        conf = 0.50 + 0.40 * strength * dominance
        side = "rehab" if p > t else "training"
        return RouteDecision(
            label, round(conf, 2),
            f"Mixed cues but the {side} signal dominates ({p} vs {t}).",
            "rules", scores,
        )

    # Pure single-specialist case.
    label = PT_ONLY if p > t else TRAINER_ONLY
    strength = min(1.0, max(p, t) / 3.0)
    conf = 0.55 + 0.40 * strength
    why = "rehab/pain cues" if p > t else "training/fitness cues"
    return RouteDecision(label, round(conf, 2), f"Clear {why}.", "rules", scores)


# ─────────────────────────────────────────────────────────────────────────────
# LLM classifier (fallback for low-confidence cases only)
# ─────────────────────────────────────────────────────────────────────────────

_ROUTER_PROMPT = ChatPromptTemplate.from_template(
    "You are a routing classifier for an injury-recovery support team with two "
    "specialists: a physical therapist and a gym trainer.\n"
    "Choose exactly ONE category for the question:\n\n"
    "- PT_ONLY: pain, injuries, rehab progression, soreness-vs-injury, range of "
    "motion, mobility, or post-surgery recovery questions.\n"
    "- TRAINER_ONLY: workout programming, exercise form, strength/cardio "
    "guidelines, or getting active as a beginner or older adult.\n"
    "- TEAM: genuinely needs BOTH — e.g. returning to training while recovering "
    "from an injury or surgery.\n"
    "- RED_FLAG: urgent medical warning signs (severe pain, numbness, joint "
    "giving way, fever, a hot swollen calf, chest pain, wound problems).\n"
    "- CLARIFY: too vague or underspecified to route safely.\n\n"
    "Question: {question}\n\n"
    "Respond with EXACTLY one line, no extra text:\n"
    "LABEL | confidence | one short reason\n"
    "where LABEL is one of PT_ONLY, TRAINER_ONLY, TEAM, RED_FLAG, CLARIFY and "
    "confidence is a decimal between 0 and 1."
)


def _parse_llm_response(raw: str) -> RouteDecision:
    """Parse 'LABEL | confidence | reason' robustly (tolerates messy output)."""
    first_line = next((ln for ln in raw.strip().splitlines() if ln.strip()), raw.strip())

    label, pos = CLARIFY, None
    for cand in VALID_LABELS:
        m = re.search(rf"\b{cand}\b", raw)
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

    parts = [x.strip() for x in first_line.split("|")]
    reason = parts[-1] if len(parts) >= 2 else first_line
    reason = re.sub(r"\s+", " ", reason).strip()[:200]

    return RouteDecision(
        label, round(max(0.0, min(1.0, conf)), 2), reason or "LLM classification.", "llm"
    )


def _classify_with_llm(question: str) -> RouteDecision:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set; cannot run the LLM router fallback.")
    # Lazy import: high-confidence rule decisions never construct the client.
    from langchain_groq import ChatGroq

    llm = ChatGroq(model=MODEL, temperature=0, groq_api_key=api_key)
    raw = (_ROUTER_PROMPT | llm | StrOutputParser()).invoke({"question": question})
    return _parse_llm_response(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (contract §5.3)
# ─────────────────────────────────────────────────────────────────────────────


def classify(question: str) -> RouteDecision:
    """Classify a question into one of the five routes.

    RED_FLAG first (deterministic, always wins). Then the cue scorer; the LLM
    is consulted only when the rules are not confident, and low LLM confidence
    collapses to CLARIFY rather than guessing.
    """
    q = (question or "").strip()
    if not q:
        return RouteDecision(CLARIFY, 0.90, "Empty question.", "rules", {"pt": 0, "trainer": 0})

    for rx in _RED_FLAG_CUES:
        m = rx.search(q)
        if m:
            return RouteDecision(
                RED_FLAG, 0.97,
                f"Urgent-care cue matched: '{m.group(0)}'.",
                "rules", {"red_flag": m.group(0)},
            )

    p, t = _score_rules(q)
    decision = _decide_from_scores(q, p, t)

    if decision is not None and decision.confidence >= RULES_CONFIDENCE_THRESHOLD:
        return decision

    try:
        llm_decision = _classify_with_llm(q)
    except Exception as exc:
        if decision is not None:
            decision.reasoning += " (LLM fallback unavailable.)"
            return decision
        return RouteDecision(
            CLARIFY, 0.50,
            f"Could not classify confidently and the LLM was unavailable: {exc}",
            "rules", {"pt": p, "trainer": t},
        )

    if llm_decision.confidence < CLARIFY_THRESHOLD and llm_decision.label != CLARIFY:
        llm_decision.reasoning = (
            f"Low confidence ({llm_decision.confidence:.2f}) - {llm_decision.reasoning}"
        )
        llm_decision.label = CLARIFY
    return llm_decision


def main() -> None:
    question = " ".join(sys.argv[1:]) or "Can I do cardio while rehabbing an ankle sprain?"
    print(f"Question: {question}")
    print(classify(question))


if __name__ == "__main__":
    main()
