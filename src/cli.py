"""
src/cli.py — Programmatic CLI & E2E Pipeline Runner.

Allows running end-to-end queries through the Recovery Team MAS pipeline
(Security -> Router -> Specialist RAG -> GraphRAG -> Multimodal -> Synthesis -> Unit Economics)
directly from the terminal or test scripts without opening Streamlit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.orchestrator import answer_question
from src.security.guardrails import scan_input, scan_output
from src.multimodal.clip_search import MultimodalVisualSearch
from src.business.unit_economics import CostCalculator, BudgetOverrunGuard


def run_e2e_pipeline(question: str, budget_guard: BudgetOverrunGuard | None = None) -> dict:
    """Run a complete end-to-end query through all pipeline components."""
    # 1. Security Input Scan
    is_safe, sanitized_prompt, reason = scan_input(question)
    if not is_safe:
        return {
            "status": "BLOCKED_BY_GUARDRAILS",
            "reason": reason,
            "final_answer": "Request blocked by security guardrails.",
        }

    # 2. LangGraph MAS Orchestrator Execution
    result = answer_question(sanitized_prompt)

    # 3. Security Output Scan
    out_safe, final_text = scan_output(result["final_answer"])

    # 4. Multimodal Visual Search
    visual_search = MultimodalVisualSearch()
    matched_visuals = visual_search.search_visuals(question, top_k=2)

    # 5. Unit Economics & Cost Tracking
    cost_metrics = CostCalculator.calculate_query_cost(question, final_text)
    budget_status = {}
    if budget_guard:
        budget_status = budget_guard.check_and_update(cost_metrics.groq_cost_usd)

    return {
        "status": "SUCCESS",
        "question": question,
        "final_answer": final_text,
        "route": result.get("route"),
        "route_confidence": result.get("route_confidence"),
        "agents_consulted": result.get("agents_consulted", []),
        "sources": result.get("sources", {}),
        "constraints": result.get("constraints", {}),
        "matched_visuals": [v["title"] for v in matched_visuals],
        "cost_metrics": {
            "total_tokens": cost_metrics.total_tokens,
            "groq_cost_usd": cost_metrics.groq_cost_usd,
        },
        "budget_status": budget_status,
        "execution_trace": result.get("execution_trace", []),
    }


def main():
    parser = argparse.ArgumentParser(description="Recovery Team E2E Pipeline CLI")
    parser.add_argument("question", nargs="?", help="Question to submit to the Recovery Team")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    args = parser.parse_args()

    question = args.question or "How do I safely recover from an ACL reconstruction knee surgery?"
    print(f"\n[CLI E2E Pipeline] Submitting question: '{question}'...\n")

    res = run_e2e_pipeline(question)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"=== ROUTE: {res.get('route')} (Confidence: {res.get('route_confidence', 0):.2f}) ===")
        print(f"AGENTS CONSULTED: {', '.join(res.get('agents_consulted', []))}")
        print(f"MATCHED VISUALS: {', '.join(res.get('matched_visuals', []))}")
        print(f"TOKENS / COST: {res['cost_metrics']['total_tokens']} tokens (${res['cost_metrics']['groq_cost_usd']:.6f})")
        print("\n--- FINAL ANSWER ---")
        print(res["final_answer"])


if __name__ == "__main__":
    main()
