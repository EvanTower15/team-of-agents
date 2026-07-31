"""
tests/test_nutrition.py — Unit tests for the Nutritionist agent and data ingestion.
"""

import pytest
from src.agents.nutritionist import NutritionistAgent


def test_nutritionist_agent_instantiation():
    agent = NutritionistAgent()
    assert agent.name == "nutritionist"
    assert agent.collection_name == "nutrition_kb"


def test_nutritionist_consult_fallback():
    agent = NutritionistAgent()
    # Test consult never raises even with arbitrary query
    res = agent.consult("What is the recommended protein intake for post-op recovery?")
    assert "agent" in res
    assert res["agent"] == "nutritionist"
    assert "answer" in res
    assert "error" in res
