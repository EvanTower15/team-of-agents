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
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import get_llm, retrieve  # noqa: E402

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

_CONSULT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{persona}\n\n{grounding_rule}"),
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
                src = Path(doc.metadata.get("source", "unknown")).name
                if src not in sources:
                    sources.append(src)

            context = "\n\n".join(
                f"[source: {Path(doc.metadata.get('source', 'unknown')).name}]\n"
                f"{doc.page_content}"
                for doc in docs
            )

            chain = _CONSULT_PROMPT | get_llm() | StrOutputParser()
            answer = chain.invoke(
                {
                    "persona": self.persona_prompt,
                    "grounding_rule": GROUNDING_RULE,
                    "peer_block": (
                        _PEER_BLOCK.format(peer_context=peer_context)
                        if peer_context
                        else ""
                    ),
                    "context": context,
                    "question": question,
                }
            )

            result["answer"] = answer.strip()
            result["sources"] = sources
        except Exception as exc:  # never raise — the graph reads `error` instead
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result


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
