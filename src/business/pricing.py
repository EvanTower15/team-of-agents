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


# ─────────────────────────────────────────────────────────────────────────────
# Production scenario (D35) — what this would cost as a real product
# ─────────────────────────────────────────────────────────────────────────────
#
# The free Groq tier this runs on is a proof-of-concept choice: it is free, and
# it is capped at 200,000 tokens/day, which cannot host a paying customer. The
# business case therefore has to be argued against a stack a real startup would
# actually deploy — capable models with no usage ceiling.
#
# This is a TIER-FOR-TIER swap of the split the architecture already has, keyed
# by the model each call actually used rather than by node name. That mapping is
# exact: `get_llm()` (120b) serves specialists, synthesis, peer consult, and
# constraint extraction; `get_small_llm()` (20b) serves routing, planning, and
# the compliance check. Swapping each tier for its production equivalent is a
# like-for-like substitution, not a flat repricing — and it preserves the real
# architectural cost lever (cheap models do the cheap work).
#
# Rates verified 2026-08-08 against anthropic.com. Sonnet 5's INTRODUCTORY rate
# is $2/$10 through 2026-08-31; the standard $3/$15 is used deliberately, since
# a business model that only works on introductory pricing is not a business
# model, and the intro rate expires three weeks after this project is presented.


class ModelRate:
    """A named model and its published per-1M-token rates."""

    __slots__ = ("model", "input", "output", "role")

    def __init__(self, model: str, inp: float, out: float, role: str):
        self.model, self.input, self.output, self.role = model, inp, out, role

    def price(self, input_tokens: int | None, output_tokens: int | None) -> float:
        return (
            ((input_tokens or 0) / 1_000_000.0) * self.input
            + ((output_tokens or 0) / 1_000_000.0) * self.output
        )


PRODUCTION_STACK: dict[str, ModelRate] = {
    # Specialists, synthesis, peer consult, constraint extraction, follow-up
    # resolution -- the clinical reasoning. Near-frontier.
    "openai/gpt-oss-120b": ModelRate("claude-sonnet-5", 3.00, 15.00, "specialist"),
    # Routing, planning, compliance check -- classification and selection.
    "openai/gpt-oss-20b": ModelRate("claude-haiku-4-5", 1.00, 5.00, "orchestration"),
}

# An unmapped model projects at the specialist (dearest) tier, same reasoning as
# _FALLBACK below: an unknown model must never flatter the projection.
_PRODUCTION_FALLBACK = PRODUCTION_STACK["openai/gpt-oss-120b"]

PRODUCTION_STACK_NAME = "Sonnet 5 specialists + Haiku 4.5 orchestration"
PRODUCTION_RATES_VERIFIED_ON = "2026-08-08"

# Surfaced verbatim in the UI. The project's standing convention is that an
# estimate is labelled where it is displayed (D13, D23, D26, D30), and every
# projected figure in this app rests on the assumption named first here.
PROJECTION_ASSUMPTIONS = (
    "Projected costs apply production model rates to token volumes MEASURED on "
    "Groq's gpt-oss models. Token counts are not model-invariant, so these are "
    "modelled figures, not metered ones. Three known sources of error: "
    "different tokenizers produce different counts for identical text "
    "(typically 10-20%); models differ in how many reasoning tokens they spend "
    "before answering, which is billed at the output rate; and answer length "
    "varies by model. Treat the projection as accurate to roughly +/-20-30%. "
    "Actual spend on the current free tier is $0.00."
)

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


def project_call(
    measured_model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Cost of one call had it run on the PRODUCTION stack instead (D35).

    `measured_model` is the model that actually served the call; the tier it
    belongs to selects the production model it maps to. Returns None for an
    unmeasured call, exactly like `price_call` — a projection of nothing is not
    zero.

    Deliberately NOT stored on the row. `cost_usd` is a historical fact and is
    written at insert so a Groq price change cannot rewrite last month's
    reported margin; a projection is a model output and must re-derive whenever
    the scenario changes, so it is computed at read time.
    """
    if input_tokens is None and output_tokens is None:
        return None
    rate = PRODUCTION_STACK.get(measured_model or "", _PRODUCTION_FALLBACK)
    return rate.price(input_tokens, output_tokens)


def production_rate_for(measured_model: str | None) -> ModelRate:
    """The production model a measured model's tier maps to."""
    return PRODUCTION_STACK.get(measured_model or "", _PRODUCTION_FALLBACK)


def projection_multiplier(
    measured_model: str, input_tokens: int, output_tokens: int
) -> float:
    """How many times dearer the production stack is for this call shape.

    Used in the dashboard to state the headline "~20x" honestly rather than
    quoting a number derived from one hand-picked example.
    """
    actual = price_call(measured_model, input_tokens, output_tokens)
    projected = project_call(measured_model, input_tokens, output_tokens)
    if not actual or projected is None:
        return 0.0
    return projected / actual


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
