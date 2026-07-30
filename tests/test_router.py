"""
tests/test_router.py — Unit tests for router classification taxonomy and red flag detection.
"""

import pytest
from src.router import classify, RED_FLAG, NUTRITION_ONLY, PT_ONLY, TRAINER_ONLY, SURGEON, TEAM


def test_red_flag_detection():
    decision = classify("I have severe, unbearable chest pain and a hot swollen calf")
    assert decision.label == RED_FLAG
    assert decision.method == "rules"
    assert decision.confidence >= 0.95


def test_empty_question():
    decision = classify("")
    assert decision.label in ("CLARIFY", "RED_FLAG")


def test_nutrition_routing_parse():
    from src.router import _parse_llm_response
    raw = "THOUGHT: Diet advice.\nDECISION: NUTRITION_ONLY | 0.95 | nutrition | Diet post surgery."
    dec = _parse_llm_response(raw)
    assert dec.label == NUTRITION_ONLY
    assert dec.scores.get("nutrition") == 1
