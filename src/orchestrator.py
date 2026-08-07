"""
src/orchestrator.py — the LangGraph team workflow.

    START -> route_question ─┬─ RED_FLAG -> safety_response  -> END
                             ├─ CLARIFY  -> ask_clarification -> END
                             └─ else     -> plan_consultation
                                                 │
                                    ┌────────────▼─────────────┐
                                    │  consult_next  (loops)   │  <- one node per
                                    │  through plan[] in order │     planned agent
                                    └────────────┬─────────────┘
                                                 ▼
                            peer_consult -> synthesize_team_answer -> END
                       (agent error / no usable draft) -> fallback_handler -> END

Design notes:
* **A small LM chooses which specialists run and in what order** (D28,
  src/planner.py), replacing the fixed surgeon->PT->trainer->nutrition edge
  chain. `plan` and `plan_index` in state drive a single generic
  ``consult_next`` node; the sequence is data, not graph topology.
* **The graph has exactly one cycle**, consult_next -> consult_next, bounded
  by len(plan). planner.py caps and de-duplicates the plan at the size of the
  specialist roster, so it iterates at most once per specialist.
* **This trades away a safety guarantee, deliberately.** Fixed ordering (D4)
  used to guarantee by construction that a restrictive specialist's
  constraints reached everyone downstream as binding ``peer_context``. With
  LM-chosen order, a plan like ["trainer", "surgeon"] writes the training
  plan before the surgeon's restrictions exist. Three things contain that:
  RED_FLAG still runs on regex before planning (D5); the planner prompt
  states most-restrictive-first as a justified default and inversions are
  logged to the trace; and ``compliance_check`` re-verifies the finished
  answer against every extracted constraint regardless of run order
  (src/agents/compliance.py) — after the fact rather than by construction.
* ``answer_question(question, history=None)`` resolves a follow-up against
  prior turns BEFORE routing (src/conversation.py). Without it "what about my
  knee?" reaches the router with no referent and collapses to CLARIFY.
  History is deliberately NOT injected into specialist prompts: they answer
  only from retrieved corpus evidence (§7.1), and the router and RED_FLAG gate
  both need a complete standalone question.
* ``peer_consult`` is the agent-to-agent back-channel: one specialist may put
  a direct question to another after the chain and before synthesis. Capped at
  MAX_CONSULT_ROUNDS=1, straight-through rather than cyclic.
* Specialists can call tools (D29, src/tools/) — deterministic calculators, a
  re-query against their OWN collection, and PubMed gated to the case where
  their own retrieval came back empty. See agents/base.py.
* Every node captures its own errors into state instead of raising; one
  failing agent never crashes the graph.
* RED_FLAG never touches an LLM: canned response, appended in code (D5, §7.3).
* Every question is scanned for prompt injection / SQL injection / PII before
  it reaches the router, and every answer once more before return
  (src/security/guardrails.py).
* The standing disclaimer (§7.2) is a code constant appended by the terminal
  nodes — never left to the LLM.

Run standalone:
    python -m src.orchestrator "I'm 8 weeks post-meniscus surgery - how do I get back into lifting safely?"
"""

from __future__ import annotations

import operator
import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.router import (  # noqa: E402
    classify,
    PT_ONLY,
    TRAINER_ONLY,
    SURGEON,
    NUTRITION_ONLY,
    TEAM,
    CLARIFY,
    RED_FLAG,
)
from src.rag_core import get_llm  # noqa: E402
from src.agents.physical_therapist import PhysicalTherapistAgent  # noqa: E402
from src.agents.gym_trainer import GymTrainerAgent  # noqa: E402
from src.agents.orthopedic_surgeon import OrthopedicSurgeonAgent  # noqa: E402
from src.agents.nutritionist import NutritionistAgent  # noqa: E402
from src.agents.constraints import extract_constraints, format_constraints_block  # noqa: E402
from src.agents.peer_consult import (  # noqa: E402
    MAX_CONSULT_ROUNDS,
    detect_peer_question,
    format_peer_exchange,
)
from src.agents.compliance import COMPLIANCE_WARNING, check_compliance  # noqa: E402
from src.conversation import resolve_followup  # noqa: E402
from src.planner import plan_consultation, violates_restrictiveness  # noqa: E402
from src.security.guardrails import scan_input, scan_output  # noqa: E402
from src.eval.tracing import init_langsmith_tracing  # noqa: E402

load_dotenv()
init_langsmith_tracing()

_SURGEON = OrthopedicSurgeonAgent()
_PT = PhysicalTherapistAgent()
_TRAINER = GymTrainerAgent()
_NUTRITIONIST = NutritionistAgent()

# ─────────────────────────────────────────────────────────────────────────────
# Fixed texts (§7.2 / §7.3 — code constants, never LLM-generated)
# ─────────────────────────────────────────────────────────────────────────────

DISCLAIMER = (
    "\n\n---\n"
    "This is educational support from an AI recovery team, not a substitute "
    "for advice from a licensed clinician who can examine you."
)

RED_FLAG_RESPONSE = (
    "Your question describes a possible urgent medical warning sign, so I'm "
    "not going to give training or rehab advice for it.\n\n"
    "Please stop the activity now and get evaluated promptly: contact your "
    "surgeon or doctor, or go to urgent care. If you have chest pain, trouble "
    "breathing, or a hot, swollen calf, treat it as an emergency and call "
    "emergency services.\n\n"
    "Once a clinician has cleared you, come back and the team can help you "
    "rebuild safely."
)

FALLBACK_APOLOGY = (
    "Sorry - the team could not produce a grounded answer for that question."
)

BLOCKED_RESPONSE = (
    "That question couldn't be processed for security reasons. Please rephrase "
    "and ask again without special instructions, code, or account/system details."
)

_SYNTH_PROMPT = ChatPromptTemplate.from_template(
    "You are the care coordinator for an injury-recovery support team. Merge "
    "the specialist drafts below into ONE coherent answer to the user's "
    "question.\n"
    "Rules:\n"
    "- Use ONLY the drafts as material. Add no new exercises, facts, or "
    "medical claims of your own.\n"
    "- Attribute advice to its specialist: 'Your surgeon advises...', 'Your "
    "physical therapist advises...', 'Your trainer suggests...', 'Your nutritionist recommends...'.\n"
    "- Attribute ONLY to specialists whose draft appears below. If a block is "
    "labeled general reference data rather than a specialist draft, never "
    "introduce it as coming from a specialist -- a patient must not be told "
    "their nutritionist said something when no nutritionist was consulted. "
    "State such content plainly ('general guidance suggests...') with NO "
    "[source: ...] marker at all; never invent a placeholder citation.\n"
    "- If the drafts conflict, say so explicitly. On post-op precautions, "
    "hardware, or weight-bearing status, follow the surgeon. On anything "
    "else involving pain, safety, or rehab restrictions, follow the physical "
    "therapist.\n"
    "- Keep the inline [source: filename] citations exactly as they appear "
    "in the drafts.\n"
    "- Keep the response CRISP, CONCISE, and DIRECT. Eliminate repetitive phrases, "
    "redundant restatements, or wordy preamble.\n"
    "- Do not add any disclaimer; that is appended separately.\n\n"
    "Question: {question}\n\n"
    "Specialist drafts:\n{drafts}\n\n"
    "Coordinated answer:"
)

_CLARIFY_PROMPT = ChatPromptTemplate.from_template(
    "A user asked the recovery-team assistant the question below, but it is "
    "too vague or underspecified to route to the right specialist. Ask ONE "
    "short, focused follow-up question that would let the team help (e.g. "
    "which body part, whether they are recovering from an injury, or what "
    "their training goal is). Do NOT answer the question itself.\n\n"
    "User question: {question}\n\n"
    "Your single clarifying question:"
)

CLARIFY_CANNED = (
    "Could you tell me a bit more - is this about pain or an injury you're "
    "recovering from, or about training and getting active (and for which "
    "body part or goal)?"
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared graph state (§6.3)
# ─────────────────────────────────────────────────────────────────────────────


class TeamState(TypedDict, total=False):
    question: str

    route: str
    route_confidence: float
    route_reasoning: str
    route_method: str
    route_scores: dict     # {"pt": int, "trainer": int, "surgeon": int, "nutrition": int}

    surgeon_result: dict   # SpecialistAgent.consult() output
    pt_result: dict
    trainer_result: dict
    nutrition_result: dict

    surgeon_constraints: list  # extract_constraints() output, chained forward
    pt_constraints: list
    nutrition_constraints: list

    # Bounded agent-to-agent back-channel (src/agents/peer_consult.py): one
    # specialist may ask another a direct question after the chain runs.
    plan: list             # LM-chosen agent order (D28), e.g. ["surgeon","pt"]
    plan_index: int        # how far through `plan` execution has got
    compliance: dict       # check_compliance() verdict on the final answer

    peer_question: dict    # {"from", "to", "question"}
    peer_answer: dict      # SpecialistAgent.consult() output from the asked agent
    consult_rounds: int    # capped at MAX_CONSULT_ROUNDS -- the graph cannot loop

    final_answer: str
    sources: dict         # agent name -> [source filenames]

    needs_clarification: bool
    clarification_question: str
    fallback_reason: str

    execution_trace: Annotated[list, operator.add]


def _ok(result: dict | None) -> bool:
    """A specialist draft is usable iff it exists, has no error, and has text."""
    return bool(result) and not result.get("error") and bool(result.get("answer"))


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────


def route_question(state: TeamState) -> dict:
    decision = classify(state["question"])
    return {
        "route": decision.label,
        "route_confidence": decision.confidence,
        "route_reasoning": decision.reasoning,
        "route_method": decision.method,
        "route_scores": decision.scores,
        "execution_trace": [
            f"route_question: {decision.label} "
            f"({decision.confidence:.2f}, {decision.method}) - {decision.reasoning}"
        ],
    }


_AGENT_BY_KEY = {
    "surgeon": ("surgeon_result", lambda: _SURGEON),
    "pt": ("pt_result", lambda: _PT),
    "trainer": ("trainer_result", lambda: _TRAINER),
    "nutrition": ("nutrition_result", lambda: _NUTRITIONIST),
}

# key -> (constraints state field, label used in the peer_context block)
_CONSTRAINT_FIELD = {
    "surgeon": ("surgeon_constraints", "SURGEON"),
    "pt": ("pt_constraints", "PHYSICAL THERAPIST"),
    "trainer": (None, "GYM TRAINER"),
    "nutrition": ("nutrition_constraints", "NUTRITIONIST"),
}


def plan_consultation_node(state: TeamState) -> dict:
    """Ask the small LM which specialists to consult, and in what order (D28).

    Replaces the fixed surgeon->PT->trainer->nutrition edge chain. Falls back
    to the router's own scores, ordered most-restrictive-first, if planning
    fails — i.e. exactly the pre-D28 behavior.
    """
    plan = plan_consultation(state["question"], state.get("route_scores"))
    agents = plan["agents"]
    trace = [f"plan_consultation: {' -> '.join(agents) or '(none)'} ({plan['method']}) - {plan['reasoning']}"]

    # The LM owns ordering now, so an inversion is legal — but it means a
    # restrictive specialist's limits arrived too late to bind someone
    # downstream. Surface it; compliance_check is what actually catches the
    # consequences (see planner.py's module docstring).
    inversions = violates_restrictiveness(agents)
    if inversions:
        trace.append(
            "plan_consultation: WARNING ordering inversion — "
            + "; ".join(inversions)
            + " (constraints may not have bound downstream advice; compliance_check will verify)"
        )
    return {"plan": agents, "plan_index": 0, "execution_trace": trace}


def consult_next(state: TeamState) -> dict:
    """Consult the next specialist in the plan.

    One generic node replaces the four hardcoded consult_* nodes, because the
    sequence is now data (state["plan"]) rather than graph topology. Every
    specialist still receives all prior drafts plus their extracted
    constraints as binding peer_context.
    """
    plan = state.get("plan") or []
    idx = state.get("plan_index", 0)
    if idx >= len(plan):
        return {}

    key = plan[idx]
    field, agent_getter = _AGENT_BY_KEY[key]

    # Accumulate every upstream draft, constraints first so restrictions lead.
    blocks = []
    for prior in plan[:idx]:
        prior_field, _ = _AGENT_BY_KEY[prior]
        prior_result = state.get(prior_field)
        if not _ok(prior_result):
            continue
        cfield, label = _CONSTRAINT_FIELD[prior]
        block = format_constraints_block(state.get(cfield) or [], label) if cfield else ""
        blocks.append(block + prior_result["answer"])
    peer = "\n\n".join(blocks) or None

    result = agent_getter().consult(state["question"], peer_context=peer)
    constraints = extract_constraints(result["answer"]) if _ok(result) else []

    tools = result.get("tools_used") or []
    note = result["error"] or (
        f"{len(result['sources'])} source(s)"
        + (f", {len(blocks)} upstream draft(s) as peer_context" if blocks else "")
        + (f", tools={tools}" if tools else "")
    )

    update = {
        field: result,
        "plan_index": idx + 1,
        "execution_trace": [f"consult_{key}: {note}"],
    }
    cfield, _ = _CONSTRAINT_FIELD[key]
    if cfield:
        update[cfield] = constraints
    return update


def peer_consult(state: TeamState) -> dict:
    """Bounded agent-to-agent back-channel.

    Before synthesis, check whether one specialist needs something only
    another specialist can answer (e.g. the trainer unsure whether a movement
    is within post-op restrictions). If so, put that question to the named
    specialist and add the reply to the evidence synthesis sees.

    Hard-capped at MAX_CONSULT_ROUNDS round-trips so the DAG's "cannot loop"
    safety property still holds and the token budget stays bounded.
    """
    if state.get("consult_rounds", 0) >= MAX_CONSULT_ROUNDS:
        return {}

    drafts = {
        key: state[field]["answer"]
        for key, (field, _) in _AGENT_BY_KEY.items()
        if _ok(state.get(field))
    }
    if len(drafts) < 2:
        return {}  # need at least two specialists for one to ask another

    peer_q = detect_peer_question(state["question"], drafts)
    if not peer_q:
        return {"consult_rounds": state.get("consult_rounds", 0) + 1}

    field, agent_getter = _AGENT_BY_KEY[peer_q["to"]]
    asked = agent_getter().consult(peer_q["question"])
    note = asked["error"] or f"{len(asked['sources'])} source(s)"
    return {
        "peer_question": peer_q,
        "peer_answer": asked,
        "consult_rounds": state.get("consult_rounds", 0) + 1,
        "execution_trace": [
            f"peer_consult: {peer_q['from']} -> {peer_q['to']}: "
            f"\"{peer_q['question']}\" ({note})"
        ],
    }


def synthesize_team_answer(state: TeamState) -> dict:
    drafts, sources = [], {}
    surgeon = state.get("surgeon_result")
    pt, tr = state.get("pt_result"), state.get("trainer_result")
    nut = state.get("nutrition_result")
    if _ok(surgeon):
        drafts.append(f"ORTHOPEDIC SURGEON DRAFT:\n{surgeon['answer']}")
        sources["orthopedic_surgeon"] = surgeon["sources"]
    if _ok(pt):
        drafts.append(f"PHYSICAL THERAPIST DRAFT:\n{pt['answer']}")
        sources["physical_therapist"] = pt["sources"]
    if _ok(tr):
        drafts.append(f"GYM TRAINER DRAFT:\n{tr['answer']}")
        sources["gym_trainer"] = tr["sources"]
    if _ok(nut):
        drafts.append(f"SPORTS NUTRITIONIST DRAFT:\n{nut['answer']}")
        sources["nutritionist"] = nut["sources"]

    # A specialist's direct answer to another specialist's question carries
    # the same weight as a draft -- it IS grounded specialist output, and the
    # asked agent's sources belong in the citation list.
    peer_q, peer_a = state.get("peer_question"), state.get("peer_answer")
    if peer_q and _ok(peer_a):
        drafts.append(format_peer_exchange(peer_q, peer_a["answer"]))
        agent_name = {
            "surgeon": "orthopedic_surgeon",
            "pt": "physical_therapist",
            "trainer": "gym_trainer",
            "nutrition": "nutritionist",
        }[peer_q["to"]]
        existing = sources.get(agent_name, [])
        sources[agent_name] = existing + [s for s in peer_a["sources"] if s not in existing]

    try:
        graph_chain = _get_clinical_graph().query_multihop_chain(state["question"])
        # matched_entity is None when the question doesn't genuinely name one
        # of the 4 curated surgeries -- see kuzu_graph.py's docstring for why
        # that guard matters (it used to default to "ACL Reconstruction" and
        # inject irrelevant contraindications into every question).
        if graph_chain.get("matched_entity"):
            graph_summary = (
                f"GENERAL REFERENCE DATA — NOT A SPECIALIST DRAFT "
                f"({graph_chain['matched_entity']}). Do not attribute any of this "
                f"to a specialist; state it as general guidance or omit it:\n"
                f"- Contraindicated Movements: {', '.join(graph_chain['contraindicated_movements'])}\n"
                f"- Recommended Rehab Exercises: {', '.join(graph_chain['rehab_exercises'])}\n"
                f"- Healing Nutrients & Synergies: {', '.join([n['nutrient'] for n in graph_chain['multihop_nutrient_pathways']])}"
            )
            drafts.append(graph_summary)
    except Exception as exc:
        # Never let a decorative enrichment feature take down the real
        # synthesis path -- but log it instead of silently swallowing it,
        # per this codebase's "errors are visible, never faked" convention.
        print(f"[orchestrator] graph_rag lookup failed (non-fatal): {exc}")

    if not drafts:  # conditional edges should prevent this; guard anyway
        return {
            "fallback_reason": "synthesize reached with no usable drafts",
            "final_answer": FALLBACK_APOLOGY + DISCLAIMER,
            "sources": {},
            "execution_trace": ["synthesize_team_answer: no usable drafts"],
        }

    try:
        chain = _SYNTH_PROMPT | get_llm() | StrOutputParser()
        answer = chain.invoke(
            {"question": state["question"], "drafts": "\n\n".join(drafts)}
        ).strip()
        trace = f"synthesize_team_answer: merged {len(drafts)} draft(s)"
    except Exception as exc:
        # Degrade gracefully: hand back the raw drafts with attribution headers
        # rather than losing the specialists' work to a synthesis failure.
        answer = "\n\n".join(drafts)
        trace = f"synthesize_team_answer: LLM failed ({exc}); returning raw drafts"

    traces = [trace]

    # Since D28 the LM chooses run order, so a restrictive specialist's limits
    # may have arrived after the specialist they should have bound. Re-check
    # the finished answer against EVERY constraint anyone stated, whatever the
    # order was. This is the after-the-fact replacement for what D4's fixed
    # ordering used to guarantee by construction.
    all_constraints = {
        name: state[field]
        for name, field in (
            ("orthopedic_surgeon", "surgeon_constraints"),
            ("physical_therapist", "pt_constraints"),
            ("nutritionist", "nutrition_constraints"),
        )
        if state.get(field)
    }
    verdict = check_compliance(answer, all_constraints)
    if verdict["checked"] and not verdict["compliant"]:
        answer += COMPLIANCE_WARNING.format(details=verdict["details"])
        traces.append(f"compliance_check: VIOLATION - {verdict['details']}")
    elif verdict["checked"]:
        traces.append("compliance_check: no constraint conflicts found")
    elif verdict["details"]:
        traces.append(f"compliance_check: not run ({verdict['details']})")

    return {
        "final_answer": answer + DISCLAIMER,
        "sources": sources,
        "compliance": verdict,
        "execution_trace": traces,
    }


def safety_response(state: TeamState) -> dict:
    # Deterministic by design (D5): no retrieval, no LLM, no exceptions possible.
    return {
        "final_answer": RED_FLAG_RESPONSE + DISCLAIMER,
        "sources": {},
        "execution_trace": ["safety_response: canned red-flag answer (no LLM)"],
    }


def ask_clarification(state: TeamState) -> dict:
    try:
        chain = _CLARIFY_PROMPT | get_llm() | StrOutputParser()
        question = chain.invoke({"question": state["question"]}).strip()
        trace = "ask_clarification: LLM follow-up"
    except Exception:
        question = CLARIFY_CANNED
        trace = "ask_clarification: LLM unavailable; canned follow-up"
    return {
        "needs_clarification": True,
        "clarification_question": question,
        "final_answer": question + DISCLAIMER,
        "sources": {},
        "execution_trace": [trace],
    }


def fallback_handler(state: TeamState) -> dict:
    reasons = [
        r["error"]
        for r in (
            state.get("surgeon_result"),
            state.get("pt_result"),
            state.get("trainer_result"),
            state.get("nutrition_result"),
        )
        if r and r.get("error")
    ]
    reason = "; ".join(reasons) or state.get("fallback_reason", "no usable evidence")
    answer = (
        f"{FALLBACK_APOLOGY}\n\nWhat went wrong: {reason}\n\n"
        "If the knowledge bases have not been built yet, run:\n"
        "  python -m src.ingest --agent pt\n"
        "  python -m src.ingest --agent trainer\n"
        "  python -m src.ingest --agent surgeon\n"
        "  python -m src.ingest --agent nutrition\n"
        "Otherwise, try rephrasing the question."
    )
    return {
        "fallback_reason": reason,
        "final_answer": answer + DISCLAIMER,
        "sources": {},
        "execution_trace": [f"fallback_handler: {reason}"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Edges
# ─────────────────────────────────────────────────────────────────────────────


def _route_selector(state: TeamState) -> str:
    """RED_FLAG and CLARIFY terminate before planning; everything else plans."""
    route = state["route"]
    if route == RED_FLAG:
        return "safety_response"
    if route == CLARIFY:
        return "ask_clarification"
    return "plan_consultation"


def _after_plan(state: TeamState) -> str:
    """An empty plan means nobody to ask -- go straight to fallback rather
    than synthesizing from nothing."""
    return "consult_next" if state.get("plan") else "fallback"


def _after_consult(state: TeamState) -> str:
    """Continue through the plan, then hand off to the peer-consult pass.

    Terminates on plan_index reaching len(plan); planner.py caps and
    de-duplicates the plan, so this cycle runs at most once per specialist.
    """
    plan = state.get("plan") or []
    if state.get("plan_index", 0) < len(plan):
        return "consult_next"

    any_usable = any(
        _ok(state.get(_AGENT_BY_KEY[key][0])) for key in plan if key in _AGENT_BY_KEY
    )
    return "peer_consult" if any_usable else "fallback"


@lru_cache(maxsize=1)
def _get_clinical_graph():
    """Cached singleton -- avoid rebuilding the in-memory clinical lookup
    (and retrying the kuzu import) on every single synthesis call."""
    from src.graph_rag.kuzu_graph import ClinicalGraphRAG

    return ClinicalGraphRAG()


@lru_cache(maxsize=1)
def _get_graph():
    g = StateGraph(TeamState)
    g.add_node("route_question", route_question)
    g.add_node("plan_consultation", plan_consultation_node)
    g.add_node("consult_next", consult_next)
    g.add_node("peer_consult", peer_consult)
    g.add_node("synthesize_team_answer", synthesize_team_answer)
    g.add_node("safety_response", safety_response)
    g.add_node("ask_clarification", ask_clarification)
    g.add_node("fallback_handler", fallback_handler)

    g.add_edge(START, "route_question")
    # RED_FLAG and CLARIFY still short-circuit BEFORE any planning happens:
    # an emergency must never depend on an LM's planning decision (D5).
    g.add_conditional_edges(
        "route_question",
        _route_selector,
        {
            "plan_consultation": "plan_consultation",
            "safety_response": "safety_response",
            "ask_clarification": "ask_clarification",
        },
    )
    g.add_conditional_edges(
        "plan_consultation",
        _after_plan,
        {"consult_next": "consult_next", "fallback": "fallback_handler"},
    )
    # The one cycle in the graph. Bounded by len(plan), which planner.py caps
    # at MAX_PLAN_LENGTH (the size of the specialist roster) and de-duplicates,
    # so it can iterate at most once per specialist.
    g.add_conditional_edges(
        "consult_next",
        _after_consult,
        {
            "consult_next": "consult_next",
            "peer_consult": "peer_consult",
            "fallback": "fallback_handler",
        },
    )
    g.add_edge("peer_consult", "synthesize_team_answer")
    g.add_edge("synthesize_team_answer", END)
    g.add_edge("safety_response", END)
    g.add_edge("ask_clarification", END)
    g.add_edge("fallback_handler", END)
    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (contract §5.4) — the ONLY thing app.py may call
# ─────────────────────────────────────────────────────────────────────────────


def answer_question(question: str, history: list[dict] | None = None) -> dict:
    """Run the team graph on one question and return the §5.4 result dict.

    `history` is the prior conversation as a list of
    ``{"role": "user"|"assistant", "content": str}`` dicts. It is OPTIONAL and
    defaults to None, so every existing caller keeps working unchanged. When
    provided, a follow-up like "what about my knee?" is first resolved into a
    standalone question against those turns (src/conversation.py) -- otherwise
    the router and every specialist would see a question with no referent and
    collapse to CLARIFY. The resolved question is what flows through the rest
    of the pipeline; routing, retrieval, and synthesis are untouched by this.

    Input is scanned for prompt injection / SQL injection / PII before it
    ever reaches the router or a specialist (src/security/guardrails.py);
    a violation short-circuits the whole graph, same posture as RED_FLAG.
    The sanitized (PII-redacted) question is what actually gets processed.
    Output is scanned once more before being returned to the caller.
    """
    # Scan the raw user input FIRST -- before it is combined with history --
    # so an injection attempt can never reach the rewrite call either.
    safe, sanitized_question, violation = scan_input(question)
    if not safe:
        return {
            "final_answer": BLOCKED_RESPONSE + DISCLAIMER,
            "route": "BLOCKED",
            "route_confidence": 1.0,
            "agents_consulted": [],
            "sources": {},
            "constraints": {},
            "execution_trace": [f"security_guardrail: input blocked - {violation}"],
        }

    followup_trace = []
    effective_question = sanitized_question
    if history:
        resolved = resolve_followup(sanitized_question, history)
        if resolved["error"]:
            followup_trace = [f"resolve_followup: failed ({resolved['error']}); using question as-is"]
        elif resolved["rewritten"]:
            effective_question = resolved["resolved"]
            followup_trace = [f"resolve_followup: rewritten using history -> \"{effective_question}\""]

    state = _get_graph().invoke({"question": effective_question, "execution_trace": followup_trace})

    agents_consulted = [
        name
        for name, result in (
            ("orthopedic_surgeon", state.get("surgeon_result")),
            ("physical_therapist", state.get("pt_result")),
            ("gym_trainer", state.get("trainer_result")),
            ("nutritionist", state.get("nutrition_result")),
        )
        if _ok(result)
    ]
    constraints = {
        name: state[field]
        for name, field in (
            ("orthopedic_surgeon", "surgeon_constraints"),
            ("physical_therapist", "pt_constraints"),
            ("nutritionist", "nutrition_constraints"),
        )
        if state.get(field)
    }
    final_answer = state.get("final_answer", FALLBACK_APOLOGY + DISCLAIMER)
    trace = state.get("execution_trace", [])
    output_safe, checked_answer = scan_output(final_answer)
    if not output_safe:
        final_answer = BLOCKED_RESPONSE + DISCLAIMER
        trace = trace + ["security_guardrail: output blocked"]

    return {
        "final_answer": final_answer,
        "route": state.get("route", CLARIFY),
        "route_confidence": state.get("route_confidence", 0.0),
        "agents_consulted": agents_consulted,
        "sources": state.get("sources", {}),
        "constraints": constraints,
        "execution_trace": trace,
    }


def main() -> None:
    # Windows terminals default to cp1252; LLM output may contain non-ASCII.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    question = (
        " ".join(sys.argv[1:]).strip()
        or "I'm 8 weeks post-meniscus surgery - how do I get back into lifting safely?"
    )
    print(f"Question: {question}\n")
    result = answer_question(question)
    print(f"Route: {result['route']} (confidence {result['route_confidence']:.2f})")
    print("Trace:")
    for line in result["execution_trace"]:
        print(f"  - {line}")
    print(f"\n{result['final_answer']}")
    if result["sources"]:
        print("\nSources by specialist:")
        for agent, files in result["sources"].items():
            print(f"  {agent}: {', '.join(files)}")


if __name__ == "__main__":
    main()
