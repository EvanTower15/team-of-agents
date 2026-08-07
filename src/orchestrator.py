"""
src/orchestrator.py — the LangGraph team workflow (Phase 4, extended Phase 4b,
now a 4-specialist chain).

    START -> route_question ─┬─ PT_ONLY        -> consult_pt ──────────────────────┐
                             ├─ TRAINER_ONLY   -> consult_trainer ──────────────────┤
                             ├─ SURGEON        -> consult_surgeon ──────────────────┤
                             ├─ NUTRITION_ONLY -> consult_nutritionist ─────────────┤
                             ├─ TEAM  -> [surgeon] -> [pt] -> [trainer] -> [nutritionist] ┤
                             │           (whichever cues fired, most-restrictive first)   │
                             ├─ RED_FLAG       -> safety_response -> END            │
                             └─ CLARIFY        -> ask_clarification -> END          v
                                                          synthesize_team_answer -> END
                       (agent error / no usable draft) -> fallback_handler -> END

Design notes (mirrors the opim-5517 reference workflow):
* The graph is a DAG — no cycles, cannot loop.
* Every node captures its own errors into state instead of raising; one failing
  agent never crashes the graph — conditional edges route to fallback_handler.
* On the TEAM route, specialists chain most-restrictive-first — surgeon, then
  PT, then trainer, then nutritionist — but only the ones whose buckets actually
  fired in ``route_scores`` are consulted (D4, generalized to four agents). Each
  downstream specialist receives the upstream drafts, plus their *structured*
  constraints (src/agents/constraints.py), as ``peer_context``; the nutritionist
  sits last precisely because it must respect every clinical restriction above it.
* RED_FLAG never touches an LLM: canned response, appended in code (D5, §7.3).
* Every question is scanned for prompt injection / SQL injection / PII before
  it reaches the router, and every answer is scanned once more before it's
  returned (src/security/guardrails.py) — a violation short-circuits the
  whole graph, same posture as RED_FLAG.
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


def consult_surgeon(state: TeamState) -> dict:
    # Most-restrictive voice goes first on TEAM (D4, generalized): no upstream
    # peer_context to receive, but its own constraints get extracted for the
    # specialists that follow.
    result = _SURGEON.consult(state["question"])
    constraints = extract_constraints(result["answer"]) if _ok(result) else []
    note = result["error"] or (
        f"{len(result['sources'])} source(s), {len(constraints)} constraint(s) extracted"
    )
    return {
        "surgeon_result": result,
        "surgeon_constraints": constraints,
        "execution_trace": [f"consult_surgeon: {note}"],
    }


def consult_pt(state: TeamState) -> dict:
    # Agent-to-agent handoff: on TEAM, if the surgeon already weighed in, its
    # structured constraints + draft ride along as peer_context (D4).
    peer = None
    surgeon = state.get("surgeon_result")
    if state.get("route") == TEAM and _ok(surgeon):
        peer = (
            format_constraints_block(state.get("surgeon_constraints") or [], "SURGEON")
            + surgeon["answer"]
        )
    result = _PT.consult(state["question"], peer_context=peer)
    constraints = extract_constraints(result["answer"]) if _ok(result) else []
    note = result["error"] or (
        f"{len(result['sources'])} source(s)"
        + (", with surgeon draft as peer_context" if peer else "")
    )
    return {
        "pt_result": result,
        "pt_constraints": constraints,
        "execution_trace": [f"consult_pt: {note}"],
    }


def consult_trainer(state: TeamState) -> dict:
    blocks = []
    surgeon, pt = state.get("surgeon_result"), state.get("pt_result")
    if state.get("route") == TEAM and _ok(surgeon):
        blocks.append(
            format_constraints_block(state.get("surgeon_constraints") or [], "SURGEON")
            + surgeon["answer"]
        )
    if state.get("route") == TEAM and _ok(pt):
        blocks.append(
            format_constraints_block(state.get("pt_constraints") or [], "PT")
            + pt["answer"]
        )
    peer = "\n\n".join(blocks) or None
    result = _TRAINER.consult(state["question"], peer_context=peer)
    note = result["error"] or (
        f"{len(result['sources'])} source(s)"
        + (f", with {len(blocks)} upstream draft(s) as peer_context" if blocks else "")
    )
    return {
        "trainer_result": result,
        "execution_trace": [f"consult_trainer: {note}"],
    }


def consult_nutritionist(state: TeamState) -> dict:
    blocks = []
    surgeon, pt, tr = state.get("surgeon_result"), state.get("pt_result"), state.get("trainer_result")
    if state.get("route") == TEAM and _ok(surgeon):
        blocks.append(
            format_constraints_block(state.get("surgeon_constraints") or [], "SURGEON")
            + surgeon["answer"]
        )
    if state.get("route") == TEAM and _ok(pt):
        blocks.append(
            format_constraints_block(state.get("pt_constraints") or [], "PT")
            + pt["answer"]
        )
    if state.get("route") == TEAM and _ok(tr):
        blocks.append(
            "GYM TRAINER RECOMMENDATIONS:\n" + tr["answer"]
        )
    peer = "\n\n".join(blocks) or None
    result = _NUTRITIONIST.consult(state["question"], peer_context=peer)
    constraints = extract_constraints(result["answer"]) if _ok(result) else []
    note = result["error"] or (
        f"{len(result['sources'])} source(s)"
        + (f", with {len(blocks)} upstream draft(s) as peer_context" if blocks else "")
    )
    return {
        "nutrition_result": result,
        "nutrition_constraints": constraints,
        "execution_trace": [f"consult_nutritionist: {note}"],
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

    try:
        graph_chain = _get_clinical_graph().query_multihop_chain(state["question"])
        # matched_entity is None when the question doesn't genuinely name one
        # of the 4 curated surgeries -- see kuzu_graph.py's docstring for why
        # that guard matters (it used to default to "ACL Reconstruction" and
        # inject irrelevant contraindications into every question).
        if graph_chain.get("matched_entity"):
            graph_summary = (
                f"CLINICAL GRAPH RAG MULTI-HOP PATHWAYS ({graph_chain['matched_entity']}):\n"
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

    return {
        "final_answer": answer + DISCLAIMER,
        "sources": sources,
        "execution_trace": [trace],
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
    # Every specialist that can run must be listed here, or its failure reason is
    # silently dropped and the user gets "no usable evidence" instead of the real
    # cause (which is often an unbuilt knowledge base, with the fix in the text).
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
    route = state["route"]
    if route == TEAM:
        scores = state.get("route_scores") or {}
        if scores.get("surgeon", 0) > 0:
            return "consult_surgeon"
        if scores.get("pt", 0) > 0:
            return "consult_pt"
        if scores.get("trainer", 0) > 0:
            return "consult_trainer"
        if scores.get("nutrition", 0) > 0:
            return "consult_nutritionist"
        return "consult_trainer"
    return {
        PT_ONLY: "consult_pt",
        TRAINER_ONLY: "consult_trainer",
        SURGEON: "consult_surgeon",
        NUTRITION_ONLY: "consult_nutritionist",
        RED_FLAG: "safety_response",
        CLARIFY: "ask_clarification",
    }[route]


def _after_surgeon(state: TeamState) -> str:
    if state.get("route") == TEAM:
        scores = state.get("route_scores") or {}
        if scores.get("pt", 0) > 0:
            return "consult_pt"
        if scores.get("trainer", 0) > 0:
            return "consult_trainer"
        if scores.get("nutrition", 0) > 0:
            return "consult_nutritionist"
    return "synthesize" if _ok(state.get("surgeon_result")) else "fallback"


def _after_pt(state: TeamState) -> str:
    if state.get("route") == TEAM:
        scores = state.get("route_scores") or {}
        if scores.get("trainer", 0) > 0:
            return "consult_trainer"
        if scores.get("nutrition", 0) > 0:
            return "consult_nutritionist"
        ok = _ok(state.get("pt_result")) or _ok(state.get("surgeon_result"))
        return "synthesize" if ok else "fallback"
    return "synthesize" if _ok(state.get("pt_result")) else "fallback"


def _after_trainer(state: TeamState) -> str:
    if state.get("route") == TEAM:
        scores = state.get("route_scores") or {}
        if scores.get("nutrition", 0) > 0:
            return "consult_nutritionist"
    if (
        _ok(state.get("trainer_result"))
        or _ok(state.get("pt_result"))
        or _ok(state.get("surgeon_result"))
    ):
        return "synthesize"
    return "fallback"


def _after_nutritionist(state: TeamState) -> str:
    if (
        _ok(state.get("nutrition_result"))
        or _ok(state.get("trainer_result"))
        or _ok(state.get("pt_result"))
        or _ok(state.get("surgeon_result"))
    ):
        return "synthesize"
    return "fallback"


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
    g.add_node("consult_surgeon", consult_surgeon)
    g.add_node("consult_pt", consult_pt)
    g.add_node("consult_trainer", consult_trainer)
    g.add_node("consult_nutritionist", consult_nutritionist)
    g.add_node("synthesize_team_answer", synthesize_team_answer)
    g.add_node("safety_response", safety_response)
    g.add_node("ask_clarification", ask_clarification)
    g.add_node("fallback_handler", fallback_handler)

    g.add_edge(START, "route_question")
    g.add_conditional_edges(
        "route_question",
        _route_selector,
        {
            "consult_pt": "consult_pt",
            "consult_trainer": "consult_trainer",
            "consult_surgeon": "consult_surgeon",
            "consult_nutritionist": "consult_nutritionist",
            "safety_response": "safety_response",
            "ask_clarification": "ask_clarification",
        },
    )
    g.add_conditional_edges(
        "consult_surgeon",
        _after_surgeon,
        {
            "consult_pt": "consult_pt",
            "consult_trainer": "consult_trainer",
            "consult_nutritionist": "consult_nutritionist",
            "synthesize": "synthesize_team_answer",
            "fallback": "fallback_handler",
        },
    )
    g.add_conditional_edges(
        "consult_pt",
        _after_pt,
        {
            "consult_trainer": "consult_trainer",
            "consult_nutritionist": "consult_nutritionist",
            "synthesize": "synthesize_team_answer",
            "fallback": "fallback_handler",
        },
    )
    g.add_conditional_edges(
        "consult_trainer",
        _after_trainer,
        {
            "consult_nutritionist": "consult_nutritionist",
            "synthesize": "synthesize_team_answer",
            "fallback": "fallback_handler",
        },
    )
    g.add_conditional_edges(
        "consult_nutritionist",
        _after_nutritionist,
        {"synthesize": "synthesize_team_answer", "fallback": "fallback_handler"},
    )
    g.add_edge("synthesize_team_answer", END)
    g.add_edge("safety_response", END)
    g.add_edge("ask_clarification", END)
    g.add_edge("fallback_handler", END)
    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (contract §5.4) — the ONLY thing app.py may call
# ─────────────────────────────────────────────────────────────────────────────


def answer_question(question: str) -> dict:
    """Run the team graph on one question and return the §5.4 result dict.

    Input is scanned for prompt injection / SQL injection / PII before it
    ever reaches the router or a specialist (src/security/guardrails.py);
    a violation short-circuits the whole graph, same posture as RED_FLAG.
    The sanitized (PII-redacted) question is what actually gets processed.
    Output is scanned once more before being returned to the caller.
    """
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

    state = _get_graph().invoke({"question": sanitized_question, "execution_trace": []})

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
