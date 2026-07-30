"""
tests/test_unit_economics.py — Test Suite for Business Unit Economics & AI Budget Overrun Controls.

Tests token estimation, Groq model cost calculation, budget limit enforcement, and Vertical AI ROI metrics.
"""

import pytest
from src.business.unit_economics import (
    CostCalculator,
    BudgetOverrunGuard,
    VerticalStrategyMetrics,
)


def test_token_estimation():
    """Test character-to-token heuristic estimation."""
    assert CostCalculator.estimate_tokens("") == 0
    assert CostCalculator.estimate_tokens("Hello world") == 3
    assert CostCalculator.estimate_tokens("A" * 400) == 100


def test_calculate_query_cost():
    """Test token inference cost calculation on Groq engine."""
    q = "How do I recover from an ACL tear?"
    a = "Focus on early quad activation with isometric quad sets and straight leg raises."
    metrics = CostCalculator.calculate_query_cost(q, a)

    assert metrics.input_tokens > 0
    assert metrics.output_tokens > 0
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens
    assert metrics.groq_cost_usd > 0.0
    assert metrics.local_embedding_cost_usd == 0.0
    assert metrics.budget_overrun is False


def test_budget_overrun_guard():
    """Test financial budget overrun detection and session accumulation."""
    guard = BudgetOverrunGuard(max_cost_per_query=0.01, max_session_budget=0.03)

    # First query within budget
    res1 = guard.check_and_update(0.005)
    assert res1["status"] == "HEALTHY"
    assert res1["query_count"] == 1
    assert res1["accumulated_session_cost_usd"] == 0.005

    # Second query triggers session overrun
    res2 = guard.check_and_update(0.03)
    assert res2["status"] == "BUDGET_EXCEEDED"
    assert res2["session_overrun"] is True


def test_vertical_strategy_roi():
    """Test Vertical AI vs Human Care ROI calculation."""
    roi = VerticalStrategyMetrics.calculate_roi_versus_human_care(
        query_cost_usd=0.001, consultation_duration_minutes=15.0
    )
    assert roi["human_care_equivalent_usd"] > 30.0
    assert "cheaper" in roi["cost_reduction_multiplier"]
    assert len(roi["vertical_moat_advantages"]) >= 4
