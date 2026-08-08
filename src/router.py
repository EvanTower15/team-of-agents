"""
src/router.py — route classifier for the recovery team (Phase 4, redesigned Phase 4c).

Decides which specialist(s) a question goes to — one label out of seven:

    PT_ONLY         -> physical therapist (pain, rehab, mobility)
    TRAINER_ONLY    -> gym trainer (programming, form, getting active)
    SURGEON         -> orthopedic surgeon (post-op protocols, timelines, hardware)
    NUTRITION_ONLY  -> recovery nutritionist (protein targets, healing nutrients,
                       anti-inflammatory diet, post-op GI support)
    TEAM            -> more than one specialist, chained most-restrictive-first
    RED_FLAG        -> deterministic safety response, NO LLM ever (decision D5)
    CLARIFY         -> too vague to route safely; ask one follow-up

Alongside the label, every decision carries ``scores`` — a
``{"pt", "trainer", "surgeon", "nutrition"}`` dict of 0/1 flags naming which
specialists apply. That is what the orchestrator's TEAM chain reads to decide
who to consult, so adding the nutritionist needed no orchestrator API change.

Strategy (Phase 4c, D11 — supersedes the Phase 4/4b weighted-regex scorer):
    1. RED_FLAG regexes are checked FIRST and always win — health safety must
       not depend on LLM behavior. This is the one place regex stays load-bearing.
    2. Everything else goes to the Groq/Llama classifier, which returns both the
       label and the specialist flags in one call.
    3. If the LLM's own confidence is below CLARIFY_THRESHOLD, or the LLM is
       unavailable (no key, network error), routing drops to
       ``keyword_route_fallback()`` — a deterministic keyword pass over
       HIGH_RISK_PATTERNS then SPECIALIST_KEYWORDS (two or more specialists
       matched => TEAM), reported as method "rules" at confidence 0.85. A
       *confident* CLARIFY is left alone (D15): the classifier read the whole
       question and judged it too vague, so one loose keyword match must not
       overturn it.
    4. Only if that finds nothing does the route collapse to CLARIFY. Never
       crashes, per the codebase's "never raise" convention.

Step 3 was added after Phase 4c: the LLM-only design collapsed explicit
questions to CLARIFY too eagerly (and, with no key set, collapsed *every*
non-RED_FLAG question), so a small keyword net now sits under the classifier
rather than in front of it. It over-corrected at first — firing even on a
confident CLARIFY, which re-broke "What's the best gym?" — hence the D15
narrowing described above. Note what this means operationally: without
GROQ_API_KEY the router still routes, deterministically, instead of asking
everyone to rephrase.

Trade-off, on purpose: every non-RED_FLAG question now costs one Groq call
instead of being resolved for free by keyword weights. Hand-tuned regex cue
lists were proving brittle (subtle misses like "stitches come out" not
matching "stitches out") and needed constant patching as the specialist roster
grew; a classifier generalizes without new patterns per phrasing — the keyword
list survives only as a safety net, not as the primary decision-maker.

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

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.rag_core import GROQ_SMALL_MODEL, get_small_llm  # noqa: E402

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
NUTRITION_ONLY = "NUTRITION_ONLY"

VALID_LABELS = (PT_ONLY, TRAINER_ONLY, SURGEON, NUTRITION_ONLY, TEAM, CLARIFY, RED_FLAG)
# Labels the LLM may assign -- RED_FLAG is regex-only and never reaches it.
_LLM_LABELS = (PT_ONLY, TRAINER_ONLY, SURGEON, NUTRITION_ONLY, TEAM, CLARIFY)

CLARIFY_THRESHOLD = 0.50  # LLM confidence below this collapses to CLARIFY

# Routing is classification, so it runs on the SMALL model (D27/D28) -- see
# rag_core.GROQ_SMALL_MODEL. Kept as a module constant for test visibility.
MODEL = GROQ_SMALL_MODEL

_EMPTY_SCORES = {"pt": 0, "trainer": 0, "surgeon": 0, "nutrition": 0}


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
    "four specialists: an orthopedic surgeon, a physical therapist, a "
    "gym trainer, and a sports recovery nutritionist.\n"
    "Read the question and decide two things:\n"
    "1. Which specialist(s) are relevant to answering it: any combination of "
    "'pt', 'trainer', 'surgeon', 'nutrition'.\n"
    "2. A single overall LABEL summarizing that:\n"
    "   - PT_ONLY: only the physical therapist is relevant (pain, injuries, "
    "rehab progression, soreness-vs-injury, range of motion, mobility).\n"
    "   - TRAINER_ONLY: only the gym trainer is relevant (workout programming, "
    "exercise form, strength/cardio guidelines, getting active as a beginner "
    "or older adult).\n"
    "   - SURGEON: only the orthopedic surgeon is relevant (post-operative "
    "protocols, weight-bearing status, surgical hardware, wound/incision "
    "care, recovery timelines tied to a specific surgery).\n"
    "   - NUTRITION_ONLY: only the recovery nutritionist is relevant (post-op "
    "diet, collagen/protein targets, anti-inflammatory foods, supplements, hydration).\n"
    "   - TEAM: more than one specialist is relevant -- e.g. returning to "
    "training while recovering from an injury/surgery with dietary support.\n"
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
    "Q: \"What should I eat to heal faster after ACL surgery?\"\n"
    "THOUGHT: The user is asking specifically about dietary recovery and anti-inflammatory nutrition post-surgery.\n"
    "DECISION: NUTRITION_ONLY | 0.95 | nutrition | Anti-inflammatory nutrition and protein intake for surgical healing.\n\n"
    "Q: \"My surgeon cleared me for lifting after ACL reconstruction. What exercises and diet should I follow?\"\n"
    "THOUGHT: The user is transitioning back to training post-surgery and needs surgical protocols, rehab exercises, training guidance, and nutrition.\n"
    "DECISION: TEAM | 0.95 | pt,trainer,surgeon,nutrition | Post-op return to lifting with dietary protocol requires full team alignment.\n\n"
    "Q: \"My surgeon cleared me for full weight-bearing 6 weeks after knee surgery -- how do I get back into leg training?\"\n"
    "THOUGHT: The clearance already happened, but the surgeon's weight-bearing timeline still bounds what the PT and trainer can safely plan, so all three apply.\n"
    "DECISION: TEAM | 0.95 | pt,trainer,surgeon | Post-op weight-bearing status still constrains PT/trainer planning even though clearance was already given.\n\n"
    "Q: \"My knee hurts when I squat\"\n"
    "THOUGHT: The user is experiencing pain during a specific movement, which requires a physical therapist to diagnose or provide rehab exercises.\n"
    "DECISION: PT_ONLY | 0.9 | pt | Pain during movement requires PT assessment.\n\n"
    "Question: {question}\n\n"
    "Respond using EXACTLY the following two-line format:\n"
    "THOUGHT: <Brief 1-2 sentence analysis of the user's intent and required expertise>\n"
    "DECISION: LABEL | confidence | specialists | one short reason\n"
    "where LABEL is one of PT_ONLY, TRAINER_ONLY, SURGEON, NUTRITION_ONLY, TEAM, CLARIFY; "
    "confidence is a decimal between 0 and 1; specialists is a comma-separated "
    "subset of pt,trainer,surgeon,nutrition (empty if CLARIFY)."
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
        scores = {"pt": 1, "trainer": 0, "surgeon": 0, "nutrition": 0}
    elif label == TRAINER_ONLY:
        scores = {"pt": 0, "trainer": 1, "surgeon": 0, "nutrition": 0}
    elif label == SURGEON:
        scores = {"pt": 0, "trainer": 0, "surgeon": 1, "nutrition": 0}
    elif label == NUTRITION_ONLY:
        scores = {"pt": 0, "trainer": 0, "surgeon": 0, "nutrition": 1}
    elif label == TEAM:
        named_field = parts[2] if len(parts) >= 4 else ""
        named = {tok.strip().lower() for tok in named_field.split(",") if tok.strip()}
        scores = {name: (1 if name in named else 0) for name in ("pt", "trainer", "surgeon", "nutrition")}
        # A model that says TEAM but names <2 specialists is being inconsistent;
        # default to all four rather than silently under-chaining.
        if sum(scores.values()) < 2:
            scores = {"pt": 1, "trainer": 1, "surgeon": 1, "nutrition": 1}
    else:
        scores = dict(_EMPTY_SCORES)

    reason = parts[-1] if len(parts) >= 2 else decision_line
    reason = re.sub(r"\s+", " ", reason).strip()[:200]

    return RouteDecision(
        label, round(max(0.0, min(1.0, conf)), 2), reason or "LLM classification.", "llm", scores
    )


def _classify_with_llm(question: str) -> RouteDecision:
    if not os.getenv("GROQ_API_KEY"):
        raise EnvironmentError("GROQ_API_KEY not set; cannot run the LLM router.")
    raw = (_ROUTER_PROMPT | get_small_llm() | StrOutputParser()).invoke({"question": question})
    return _parse_llm_response(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (contract §5.3)
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic Keyword Fallback — prevents CLARIFY on explicit prompts
# ─────────────────────────────────────────────────────────────────────────────

SPECIALIST_KEYWORDS = {
    SURGEON: [
        "acl", "anterior cruciate ligament", "reconstruction", "graft", "arthroscopic", "surgery", "surgical", "ortho", "orthopedic"
    ],
    PT_ONLY: [
        "quad set", "quadriceps set", "physical therapy", "physiotherapy", "rom", "range of motion",
        "rehab", "knee surgery", "after knee surgery", "post-op", "heavy squats", "heavy squatting", "forcing"
    ],
    NUTRITION_ONLY: [
        "protein", "tendon", "tendon healing", "vitamin", "diet", "nutrition", "starvation", "calorie",
        "nutrient", "dietary", "eating"
    ],
    TRAINER_ONLY: [
        "workout", "gym", "cardio", "lifting", "strength training", "exercise form"
    ]
}

HIGH_RISK_PATTERNS = [
    ("extreme starvation", NUTRITION_ONLY),
    ("starvation diet", NUTRITION_ONLY),
    ("heavy squatting", PT_ONLY),
    ("premature heavy squatting", PT_ONLY),
    ("forcing range of motion", PT_ONLY),
    ("skipping pt", PT_ONLY),
    ("infection", RED_FLAG),
    ("coughing up blood", RED_FLAG),
]


def keyword_route_fallback(user_prompt: str) -> RouteDecision | None:
    """Return a deterministic RouteDecision based on keywords when LLM is unsure or unavailable."""
    prompt = user_prompt.lower()

    # 1. Check high-risk explicit patterns
    for pat, route in HIGH_RISK_PATTERNS:
        if pat in prompt:
            scores = dict(_EMPTY_SCORES)
            if route == PT_ONLY:
                scores["pt"] = 1
            elif route == NUTRITION_ONLY:
                scores["nutrition"] = 1
            elif route == SURGEON:
                scores["surgeon"] = 1
            elif route == TRAINER_ONLY:
                scores["trainer"] = 1
            return RouteDecision(route, 0.85, f"Keyword fallback matched pattern '{pat}'.", "rules", scores)

    # 2. Multi-specialist keywords match -> TEAM
    matched_specs = set()
    if any(k in prompt for k in SPECIALIST_KEYWORDS[SURGEON]):
        matched_specs.add("surgeon")
    if any(k in prompt for k in SPECIALIST_KEYWORDS[PT_ONLY]):
        matched_specs.add("pt")
    if any(k in prompt for k in SPECIALIST_KEYWORDS[NUTRITION_ONLY]):
        matched_specs.add("nutrition")
    if any(k in prompt for k in SPECIALIST_KEYWORDS[TRAINER_ONLY]):
        matched_specs.add("trainer")

    if len(matched_specs) >= 2:
        scores = {name: (1 if name in matched_specs else 0) for name in ("pt", "trainer", "surgeon", "nutrition")}
        return RouteDecision(TEAM, 0.85, f"Keyword fallback matched multiple specialists: {', '.join(matched_specs)}.", "rules", scores)

    # 3. Single-specialist keyword match
    for route, keywords in SPECIALIST_KEYWORDS.items():
        for kw in keywords:
            if kw in prompt:
                scores = dict(_EMPTY_SCORES)
                if route == PT_ONLY:
                    scores["pt"] = 1
                elif route == NUTRITION_ONLY:
                    scores["nutrition"] = 1
                elif route == SURGEON:
                    scores["surgeon"] = 1
                elif route == TRAINER_ONLY:
                    scores["trainer"] = 1
                return RouteDecision(route, 0.85, f"Keyword fallback matched keyword '{kw}'.", "rules", scores)

    return None


def classify(question: str) -> RouteDecision:
    """Classify a question into one of six routes.

    RED_FLAG first (deterministic regex, always wins, D5). Everything else
    goes straight to the LLM classifier (D11): low LLM confidence, or the LLM
    being unavailable, falls back to deterministic keyword routing before CLARIFY.
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
        fallback = keyword_route_fallback(q)
        if fallback:
            return fallback
        return RouteDecision(
            CLARIFY, 0.50,
            f"Could not classify: LLM unavailable ({exc}).",
            "rules", dict(_EMPTY_SCORES),
        )

    # Keyword fallback only gets a say when the LLM itself was genuinely
    # unsure (confidence < threshold) -- including when its low-confidence
    # answer happened to be CLARIFY. It does NOT get a say when the LLM
    # *confidently* returned CLARIFY: that means the LLM judged the whole
    # question too vague/subjective on its own reasoning, and second-guessing
    # that with a single loose keyword match (e.g. "gym" matching in "What's
    # the best gym?") was silently overriding a correct CLARIFY with a wrong
    # single-specialist guess. Regression caught by re-running the router
    # battery after this fallback was added -- see PROJECT_PLAN.md decision log.
    if decision.confidence < CLARIFY_THRESHOLD:
        fallback = keyword_route_fallback(q)
        if fallback:
            return fallback
        if decision.label != CLARIFY:
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
