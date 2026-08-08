"""
src/conversation.py — turns a follow-up question into a standalone one.

The problem this solves: conversations persist and reopen, but every question
used to be answered from scratch. A follow-up like "what about my knee?" has
no meaning on its own -- the router can't classify it, and no specialist can
retrieve against it -- so it collapsed to CLARIFY or produced a generic answer
even though the user had explained their situation two turns earlier.

Approach: resolve the follow-up against prior turns ONCE, up front, then let
the existing pipeline run completely unchanged on the resolved question.

    "What about my knee?"  +  [earlier: "I had ACL reconstruction 6 weeks ago"]
        -> "What exercises are safe for my knee 6 weeks after ACL reconstruction?"

Note this deliberately also rewrites questions that *look* standalone, when
the conversation established a clinical context that bears on them. "Give me
a beginner strength program" from someone six weeks post-ACL must carry that
surgical context forward -- answering it as though they were uninjured would
route TRAINER_ONLY and produce advice that ignores their restrictions. In a
recovery product that is a safety property, not a nicety.

Why here rather than injecting chat history into every specialist's prompt:
* Specialists answer ONLY from their retrieved corpus (§7.1). Chat history is
  not retrieval evidence, and mixing it into their context would blur the
  grounding rule that is the anti-hallucination backbone of the product.
* RED_FLAG and the router both see a COMPLETE question, so routing accuracy
  and the deterministic safety gate keep working exactly as tuned. A bare
  "what about my knee?" would defeat both.
* One extra LLM call per turn instead of four.

Never raises: any failure returns the original question unchanged, so a
broken rewrite degrades to today's stateless behavior rather than breaking
the turn (same convention as consult() and describe_image()).
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag_core import get_llm  # noqa: E402

# How many prior turns to consider. Recovery conversations reference the
# injury/surgery mentioned early on, but sending the whole transcript every
# turn burns tokens fast on a free tier -- this is the practical middle.
MAX_HISTORY_TURNS = 6

_RESOLVE_PROMPT = ChatPromptTemplate.from_template(
    "You rewrite follow-up questions in an injury-recovery chat so they can "
    "stand alone.\n\n"
    "Conversation so far:\n{history}\n\n"
    "Latest user message: {question}\n\n"
    "Rewrite the latest message as a single self-contained question that "
    "carries forward the clinically relevant details the patient already "
    "stated -- the injury or surgery, how long ago it was, and any "
    "restrictions mentioned.\n"
    "This applies BOTH to messages that obviously depend on context "
    "(pronouns like 'it'/'that', or 'what about my knee?', 'is that safe?') "
    "AND to messages that read as standalone. A request like 'give me a "
    "beginner strength program' from someone six weeks post-surgery needs "
    "that surgical context attached -- answering it as though they were "
    "uninjured would be unsafe.\n"
    "If the conversation contains no injury, surgery, or restriction that "
    "bears on the latest message, return it UNCHANGED.\n"
    "Never answer the question. Never add facts the user did not state. "
    "Return ONLY the rewritten question, one line, no preamble or quotes."
)


def _format_history(history: list[dict], max_turns: int = MAX_HISTORY_TURNS) -> str:
    """Render recent turns as plain text for the rewrite prompt."""
    recent = [
        msg for msg in history
        if msg.get("role") in ("user", "assistant") and str(msg.get("content", "")).strip()
    ][-max_turns:]
    lines = []
    for msg in recent:
        speaker = "Patient" if msg["role"] == "user" else "Care team"
        content = str(msg["content"]).strip()
        # Assistant answers can be long; the rewrite only needs the gist, and
        # full answers would dominate the prompt.
        if speaker == "Care team" and len(content) > 400:
            content = content[:400] + "..."
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def resolve_followup(question: str, history: list[dict] | None) -> dict:
    """Rewrite `question` into a standalone question using `history`.

    Returns {"resolved": str, "rewritten": bool, "error": str | None}.
    Never raises -- on any failure `resolved` is the original question.
    """
    result = {"resolved": question, "rewritten": False, "error": None}

    if not question or not question.strip():
        return result
    if not history:
        return result

    formatted = _format_history(history)
    if not formatted:
        return result

    try:
        chain = _RESOLVE_PROMPT | get_llm() | StrOutputParser()
        resolved = chain.invoke({"history": formatted, "question": question}).strip()
        # Guard against a model that returns an empty string, wraps the answer
        # in quotes, or ignores the instruction and writes a paragraph.
        resolved = resolved.strip('"').strip("'").strip()
        if resolved and len(resolved) < 600:
            result["resolved"] = resolved
            result["rewritten"] = resolved.lower() != question.strip().lower()
    except Exception as exc:
        # Degrade to today's stateless behavior rather than failing the turn.
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    demo_history = [
        {"role": "user", "content": "I had ACL reconstruction on my right knee 6 weeks ago."},
        {"role": "assistant", "content": "Your surgeon advises staying within your weight-bearing clearance..."},
    ]
    for q in ("What about my knee?", "Give me a 3-day beginner strength program."):
        out = resolve_followup(q, demo_history)
        print(f"IN : {q}")
        print(f"OUT: {out['resolved']}  (rewritten={out['rewritten']})\n")


if __name__ == "__main__":
    main()
