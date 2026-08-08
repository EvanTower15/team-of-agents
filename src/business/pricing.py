"""
src/business/pricing.py — the single source of truth for what a token costs.

Before this module there were two cost stories and both were wrong:

* `unit_economics.GROQ_PRICING_PER_1M_TOKENS` billed at $0.59/$0.79 per 1M —
  `llama-3.3-70b-versatile`'s rates, left behind when D27 migrated the project
  to gpt-oss. Every dollar figure the app displayed between 2026-08-07 and this
  change was computed at a retired model's prices.
* `telemetry.py` (2026-08-08) captures Groq's real token counts but never
  converts them to money at all.

So one place now owns pricing, and both callers read from it. Keeping it in
`business/` rather than in `telemetry.py` is deliberate: telemetry answers
"what happened", pricing answers "what it cost", and only the latter changes
when Groq reprices or the project switches models.

Rates verified against console.groq.com/docs/model/openai/gpt-oss-{120b,20b}
on 2026-08-08. `RATES_VERIFIED_ON` is displayed in the dashboard so a stale
table is visible rather than silently trusted.

Public API:
    price_call(model, input_tokens, output_tokens) -> float | None
    price_tokens(model, total_tokens)              -> float   (blended estimate)
    is_priced(model)                               -> bool
"""

from __future__ import annotations

# Groq list prices, USD per 1,000,000 tokens.
#
# Keyed by the exact model id string ChatGroq reports back in
# `llm_output["model_name"]`, so a future model swap that forgets this file
# shows up as an unpriced model in the dashboard instead of silently billing
# at the wrong model's rate.
MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    # Specialists, synthesis, peer consult, constraint extraction (D27).
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
    # Routing, planning, compliance check (D27).
    "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
}

RATES_VERIFIED_ON = "2026-08-08"
RATES_SOURCE = "https://console.groq.com/docs/model/openai/gpt-oss-120b"

# What an unknown model is charged. Set to the DEAREST known model rather than
# an average or zero: an unpriced model must never make the margin look better
# than it is. The dashboard flags these rows separately so the estimate is
# visible as an estimate.
_FALLBACK = {"input": 0.15, "output": 0.60}

# Local MiniLM embeddings (D2) and the CLIP index run on the host CPU and cost
# nothing per call. Stated explicitly because "retrieval is free" is a real
# part of the margin story, not an oversight in the pricing table.
EMBEDDING_COST_PER_CALL_USD = 0.0


def is_priced(model: str | None) -> bool:
    """True when we hold a real published rate for this model."""
    return bool(model) and model in MODEL_PRICING_PER_1M


def price_call(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """USD for one completion, or None when the provider reported no usage.

    Returning None rather than 0.0 for missing usage is deliberate and matches
    the convention `compliance_check` set: a row that could not be measured
    must be distinguishable from one that genuinely cost nothing. A zero here
    would quietly drag every average in the dashboard toward optimism.
    """
    if input_tokens is None and output_tokens is None:
        return None

    rates = MODEL_PRICING_PER_1M.get(model or "", _FALLBACK)
    return (
        ((input_tokens or 0) / 1_000_000.0) * rates["input"]
        + ((output_tokens or 0) / 1_000_000.0) * rates["output"]
    )


def price_tokens(model: str | None, total_tokens: int | None) -> float:
    """Cost of a token count whose input/output split is unknown.

    Used only for back-filling historical `llm_calls` rows written before the
    cost column existed. Assumes the RAG-shaped 80/20 input/output split this
    pipeline actually exhibits (large retrieved-context prompts, short
    answers). Prefer `price_call` anywhere the split is known.
    """
    if not total_tokens:
        return 0.0
    return price_call(model, int(total_tokens * 0.8), int(total_tokens * 0.2)) or 0.0


def cost_bounds(model: str | None, total_tokens: int | None) -> tuple[float, float]:
    """(min, max) USD for a token count, assuming all-input vs all-output.

    Honest bounds for reporting a figure whose split we do not have — the
    dashboard uses this rather than presenting an assumed split as fact.
    """
    if not total_tokens:
        return (0.0, 0.0)
    rates = MODEL_PRICING_PER_1M.get(model or "", _FALLBACK)
    lo = (total_tokens / 1_000_000.0) * min(rates["input"], rates["output"])
    hi = (total_tokens / 1_000_000.0) * max(rates["input"], rates["output"])
    return (lo, hi)
