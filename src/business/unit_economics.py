"""
src/business/unit_economics.py — human-care ROI comparison and budget guards.

**This module no longer produces the cost figures the app displays.** It was
the project's only source of cost until 2026-08-08, and it was wrong twice
over: `estimate_tokens` is a chars/4 heuristic applied to the visible question
and answer — roughly one of the 6–14 model calls a question actually makes —
and it priced them at `llama-3.3-70b-versatile`'s rates, which D27 migrated off
on 2026-08-07. Measured, a single-specialist question is 11,564 tokens, not the
~2,000 the estimator reported: understated ~5.7×, then over-priced ~3.9× on
input. Two errors pointing opposite ways.

What replaced it (D32):

    src/telemetry.py         captures Groq's own per-call token counts
    src/business/pricing.py  owns the per-model rates
    src/business/plans.py    turns those into quota, overage, and margin

What still lives here and is still used:

    VerticalStrategyMetrics  the human-care cost comparison, which is a
                             business argument rather than a token measurement
    BudgetOverrunGuard       an in-process spend ceiling

`CostCalculator` is kept for the CLI's offline path and for tests, but now
prices through `business.pricing` instead of holding its own table, so there is
exactly one place where a Groq price lives. Treat any number it returns as an
estimate; anything user-facing should read telemetry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Any

from src.business.pricing import MODEL_PRICING_PER_1M

# Kept as a module constant because tests and the CLI import it. Now DERIVED
# from the pricing table for the model this project actually runs on, rather
# than being a second, independently-drifting copy of Groq's price list.
GROQ_PRICING_PER_1M_TOKENS = dict(MODEL_PRICING_PER_1M["openai/gpt-oss-120b"])

HUMAN_CONSULT_HOURLY_RATES = {
    "orthopedic_surgeon": 350.0,
    "physical_therapist": 150.0,
    "gym_trainer": 80.0,
    "nutritionist": 100.0,
}


@dataclass
class QueryCostMetrics:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    groq_cost_usd: float
    local_embedding_cost_usd: float
    budget_overrun: bool


class CostCalculator:
    """Calculates Groq token costs, local compute savings, and budget metrics."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count based on word & character heuristics (~4 chars/token)."""
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 4.0))

    @classmethod
    def calculate_query_cost(
        self,
        question: str,
        answer: str,
        budget_limit_usd: float = 0.05,
    ) -> QueryCostMetrics:
        input_tokens = self.estimate_tokens(question)
        output_tokens = self.estimate_tokens(answer)
        total_tokens = input_tokens + output_tokens

        groq_cost = (
            (input_tokens / 1_000_000.0) * GROQ_PRICING_PER_1M_TOKENS["input"]
            + (output_tokens / 1_000_000.0) * GROQ_PRICING_PER_1M_TOKENS["output"]
        )

        is_overrun = groq_cost > budget_limit_usd

        return QueryCostMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            groq_cost_usd=round(groq_cost, 6),
            local_embedding_cost_usd=0.0,  # 100% free local sentence-transformers
            budget_overrun=is_overrun,
        )


class BudgetOverrunGuard:
    """Enforces financial budget limits and detects runaway token loops."""

    def __init__(
        self,
        max_cost_per_query: float = 0.05,
        max_session_budget: float = 1.00,
    ) -> None:
        self.max_cost_per_query = max_cost_per_query
        self.max_session_budget = max_session_budget
        self.accumulated_session_cost = 0.0
        self.query_count = 0

    def check_and_update(self, query_cost_usd: float) -> Dict[str, Any]:
        """Check if current query or session violates financial budget limits."""
        self.query_count += 1
        self.accumulated_session_cost += query_cost_usd

        query_overrun = query_cost_usd > self.max_cost_per_query
        session_overrun = self.accumulated_session_cost > self.max_session_budget

        status = "HEALTHY"
        if query_overrun or session_overrun:
            status = "BUDGET_EXCEEDED"

        return {
            "status": status,
            "query_count": self.query_count,
            "accumulated_session_cost_usd": round(self.accumulated_session_cost, 6),
            "max_session_budget_usd": self.max_session_budget,
            "query_overrun": query_overrun,
            "session_overrun": session_overrun,
        }


class VerticalStrategyMetrics:
    """Calculates Vertical AI Strategy ROI vs Human Clinical Consultation Costs."""

    @staticmethod
    def calculate_roi_versus_human_care(
        query_cost_usd: float, consultation_duration_minutes: float = 15.0
    ) -> Dict[str, Any]:
        """Compare AI Recovery Team query cost against average human care costs."""
        # Average weighted hourly rate across 4 specialists (~$170/hr = ~$2.83/min)
        avg_min_rate = sum(HUMAN_CONSULT_HOURLY_RATES.values()) / 4.0 / 60.0
        human_cost = round(avg_min_rate * consultation_duration_minutes, 2)
        multiplier = round(human_cost / query_cost_usd, 0) if query_cost_usd > 0 else 0.0

        return {
            "human_care_equivalent_usd": human_cost,
            "ai_query_cost_usd": query_cost_usd,
            "cost_reduction_multiplier": f"{int(multiplier)}x cheaper",
            "vertical_moat_advantages": [
                "Groq gpt-oss-120b Primary Inference Engine",
                "Domain-Siloed RAG (Zero Cross-Specialist Hallucinations)",
                "Clinician-Grounded Binding Constraints & Safety Guardrails",
                "Deterministic Red-Flag Medical Emergency Interception",
                "Multi-Hop GraphRAG Recovery Pathways",
            ],
        }
