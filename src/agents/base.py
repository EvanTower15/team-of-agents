"""
src/agents/base.py — SpecialistAgent, the base class every specialist extends.

Contract frozen in PROJECT_PLAN.md §5.2. Concrete agents (physical_therapist.py,
gym_trainer.py, later orthopedic_surgeon.py) only supply identity fields and a
persona prompt, plus a two-line ``__main__`` CLI via run_cli().

Safety design (PROJECT_PLAN.md §7):
  * The grounding rule (§7.1) is enforced HERE, in the base prompt template —
    a subclass persona cannot accidentally omit it.
  * consult() NEVER raises. Errors land in the returned ``error`` field so one
    failing agent can never crash the orchestrator graph (opim-5517 convention).
  * ``peer_context`` is the agent-to-agent handoff (decision D4): on the TEAM
    route the trainer receives the PT's draft and must respect its constraints.

Tool calling (D29). Specialists can now call tools rather than answering from
a single prompt in one shot:
  * Deterministic calculators (src/tools/calculators.py) — protein targets,
    training loads, post-op phase bands. Pure arithmetic on numbers the patient
    supplied, so the grounding rule is untouched: they compute, they do not
    introduce outside medical claims.
  * ``search_my_corpus`` — a second retrieval attempt against THIS specialist's
    own collection. The collection name is injected by the agent, never chosen
    by the model, so knowledge siloing (D3) still holds.
  * ``search_pubmed`` — only offered when the agent's own retrieval came back
    empty, and its results must be cited as ``[research: PMID ...]`` rather
    than ``[source: filename]`` so vetted guidance stays distinguishable from
    a single study abstract.

The loop is capped at MAX_TOOL_ROUNDS. Unbounded tool loops are the standard
way an agent burns a token budget, and this project's free tier has a daily
cap it has hit more than once.
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import get_llm, retrieve  # noqa: E402
from src.tools.calculators import CALCULATOR_FUNCTIONS, CALCULATOR_SCHEMAS  # noqa: E402
from src.tools.research import (  # noqa: E402
    CORPUS_TOOL_SCHEMA,
    PUBMED_TOOL_SCHEMA,
    search_my_corpus,
    search_pubmed,
)

# Each round is one extra LLM call plus whatever the tools cost. Two is enough
# for the realistic pattern (retrieval was thin -> re-query -> answer, or
# re-query found nothing -> pubmed -> answer) without letting a confused model
# loop indefinitely against a metered API.
MAX_TOOL_ROUNDS = 2

# §7.1 — the anti-hallucination backbone. Baked into every consult() call.
GROUNDING_RULE = (
    "Use ONLY the provided context to answer. If the context does not cover "
    "the question, say you don't have material on it in your knowledge base "
    "and do not improvise an answer from general knowledge."
)

_PEER_BLOCK = (
    "A teammate specialist has already weighed in. Treat any restrictions or "
    "safety constraints in their draft as binding — build on them, never "
    "contradict them:\n---\n{peer_context}\n---\n\n"
)

_TOOL_RULE = (
    "You have tools available. Use them when they genuinely help:\n"
    "- Do arithmetic with the calculator tools rather than in your head. Any "
    "protein target, training load, unit conversion, or post-op phase you "
    "state should come from a tool call -- these are numbers a patient may act "
    "on, and quiet arithmetic slips are exactly what the tools exist to "
    "prevent. Take the underlying guideline (e.g. g/kg) from your retrieved "
    "context and pass it in; the tool multiplies, it does not decide clinical "
    "guidance.\n"
    "- If your retrieved context is thin or off-topic, call search_my_corpus "
    "with better terms before concluding you have no material.\n"
    "- If search_pubmed is offered, your own knowledge base returned nothing. "
    "Say so plainly first, then present any study as published research -- "
    "cite it as [research: PMID ...], never as [source: filename], and never "
    "let it override a restriction from the patient's care team."
)

_CONSULT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{persona}\n\n{grounding_rule}\n\n" + _TOOL_RULE),
        (
            "human",
            "{peer_block}"
            "Context from your knowledge base:\n{context}\n\n"
            "Question: {question}\n\n"
            "Your specialist answer:",
        ),
    ]
)


class SpecialistAgent:
    """One specialist on the recovery team: a persona bound to a knowledge base."""

    name: str = "specialist"
    display_name: str = "Specialist"
    collection_name: str = ""
    persona_prompt: str = "You are a helpful specialist."
    k: int = 4

    def consult(self, question: str, peer_context: str | None = None) -> dict:
        """Retrieve from own collection, answer in persona from ONLY that context.

        Returns {"agent", "answer", "sources", "error"} and never raises.
        """
        result = {"agent": self.name, "answer": "", "sources": [], "error": None}
        try:
            docs = retrieve(question, self.collection_name, k=self.k)

            # De-duped source filenames, in retrieval order → citation list.
            sources = []
            for doc in docs:
                p = Path(doc.metadata.get("source", "unknown"))
                src = f"{p.parent.name}/{p.name}" if p.name != "unknown" else "unknown"
                if src not in sources:
                    sources.append(src)

            context = "\n\n".join(
                f"[source: {Path(doc.metadata.get('source', 'unknown')).parent.name}/{Path(doc.metadata.get('source', 'unknown')).name}]\n"
                f"{doc.page_content}"
                for doc in docs
            )

            messages = _CONSULT_PROMPT.format_messages(
                persona=self.persona_prompt,
                grounding_rule=GROUNDING_RULE,
                peer_block=(
                    _PEER_BLOCK.format(peer_context=peer_context) if peer_context else ""
                ),
                context=context or "(no matching passages found in your knowledge base)",
                question=question,
            )
            answer, used, extra_sources = self._run_with_tools(
                messages, corpus_was_empty=not docs
            )
            result["answer"] = answer.strip()
            result["tools_used"] = used
            for s in extra_sources:
                if s not in sources:
                    sources.append(s)
            result["sources"] = sources
        except Exception as exc:  # never raise — the graph reads `error` instead
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _available_tools(self, corpus_was_empty: bool) -> list[dict]:
        """Tool schemas offered to this specialist for this question.

        PubMed is withheld unless the agent's own retrieval came back empty —
        that gate is what keeps external research a fallback for honest
        ignorance rather than a routine substitute for the curated corpus
        (D29). It is enforced here in code, not by asking the model nicely.
        """
        tools = list(CALCULATOR_SCHEMAS) + [CORPUS_TOOL_SCHEMA]
        if corpus_was_empty:
            tools.append(PUBMED_TOOL_SCHEMA)
        return tools

    def _dispatch_tool(self, name: str, args: dict) -> tuple[dict, list[str]]:
        """Execute one tool call. Returns (payload, new_source_labels)."""
        if name in CALCULATOR_FUNCTIONS:
            return CALCULATOR_FUNCTIONS[name](**args), []

        if name == "search_my_corpus":
            # collection_name is injected, never model-supplied: a specialist
            # cannot use this to read another specialist's corpus (D3).
            out = search_my_corpus(
                args.get("query", ""), self.collection_name, k=self.k
            )
            return out, [p["source"] for p in out.get("passages", [])]

        if name == "search_pubmed":
            out = search_pubmed(args.get("query", ""))
            return out, [s["citation"] for s in out.get("studies", [])]

        return {"error": f"unknown tool '{name}'"}, []

    def _run_with_tools(
        self, messages: list, corpus_was_empty: bool
    ) -> tuple[str, list[str], list[str]]:
        """Run the consult conversation, servicing tool calls up to
        MAX_TOOL_ROUNDS. Returns (answer_text, tools_used, extra_sources)."""
        import json

        llm = get_llm().bind_tools(self._available_tools(corpus_was_empty))
        used: list[str] = []
        extra_sources: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            reply = llm.invoke(messages)
            calls = getattr(reply, "tool_calls", None)
            if not calls:
                return (reply.content or "").strip(), used, extra_sources

            messages.append(reply)
            for call in calls:
                name = call.get("name", "")
                args = call.get("args", {}) or {}
                try:
                    payload, new_sources = self._dispatch_tool(name, args)
                except Exception as exc:
                    # A bad tool call is the model's problem to recover from,
                    # not a reason to fail the consult -- hand back the error
                    # so it can try again or answer without the tool.
                    payload, new_sources = {"error": f"{type(exc).__name__}: {exc}"}, []
                used.append(name)
                extra_sources.extend(s for s in new_sources if s not in extra_sources)
                messages.append(
                    ToolMessage(
                        content=json.dumps(payload)[:4000],
                        tool_call_id=call.get("id", name),
                    )
                )

        # Budget exhausted while the model was still calling tools: ask once
        # more with tools withheld so it must produce prose.
        final = get_llm().invoke(
            messages
            + [
                HumanMessage(
                    content=(
                        "Answer now using what you have. Do not request more tools."
                    )
                )
            ]
        )
        return (final.content or "").strip(), used, extra_sources


def run_cli(agent: SpecialistAgent, default_question: str) -> None:
    """Shared ``__main__`` body so every concrete agent is testable standalone:

        python -m src.agents.physical_therapist "My knee aches after squats"
    """
    question = " ".join(sys.argv[1:]).strip() or default_question
    print(f"[{agent.name}] Question: {question}\n")
    result = agent.consult(question)
    if result["error"]:
        print(f"ERROR: {result['error']}")
        return
    print(result["answer"])
    print(f"\nSources: {', '.join(result['sources']) or '(none)'}")
