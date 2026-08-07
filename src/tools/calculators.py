"""
src/tools/calculators.py — deterministic math the specialists can call.

These exist because LLMs are unreliable at arithmetic, and several of the
numbers this system hands to patients are arithmetic: protein grams from
bodyweight, a training load from a 1RM percentage, which rehab phase a
"6 weeks post-op" patient is in.

Every function here is pure Python. Nothing calls an LLM, nothing fetches
anything, nothing touches the corpus. That matters for the §7.1 grounding
rule: these tools COMPUTE over numbers the patient supplied, they do not
introduce medical claims from outside the curated knowledge base. A
calculator can tell you 0.9 kg is 2.0 lb; it cannot tell you whether you
should be lifting.

All of them validate input and return a dict with an `error` key rather than
raising, so a malformed tool call from a model degrades to a message the
specialist can read instead of crashing the graph.
"""

from __future__ import annotations

# Rehab phases are broad, conventional bands used to frame guidance -- not a
# substitute for a surgeon's individual protocol, and the tool says so in its
# own output so a specialist quoting it carries the caveat forward.
_PHASES = [
    (0, 2, "acute / protection phase"),
    (2, 6, "early motion and protected weight-bearing phase"),
    (6, 12, "progressive strengthening phase"),
    (12, 24, "advanced strengthening and return-to-activity phase"),
    (24, 10_000, "return-to-sport / maintenance phase"),
]


def _num(value, name: str, low: float, high: float) -> float:
    """Coerce and range-check a numeric tool argument."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if not (low <= n <= high):
        raise ValueError(f"{name} must be between {low} and {high}, got {n}")
    return n


def convert_weight(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert between kg and lb."""
    try:
        n = _num(value, "value", 0, 2000)
        f, t = str(from_unit).lower().strip(), str(to_unit).lower().strip()
        if f not in ("kg", "lb") or t not in ("kg", "lb"):
            raise ValueError("units must be 'kg' or 'lb'")
        out = n if f == t else (n * 2.20462 if f == "kg" else n / 2.20462)
        return {"value": round(out, 2), "unit": t, "error": None}
    except ValueError as exc:
        return {"error": str(exc)}


def protein_target(bodyweight: float, unit: str = "kg", grams_per_kg: float = 1.6) -> dict:
    """Daily protein target in grams from bodyweight.

    `grams_per_kg` should come from the specialist's own retrieved corpus --
    this tool does the multiplication, it does not decide the guideline.
    """
    try:
        w = _num(bodyweight, "bodyweight", 20, 500)
        rate = _num(grams_per_kg, "grams_per_kg", 0.5, 3.0)
        kg = w if str(unit).lower().strip() == "kg" else w / 2.20462
        return {
            "grams_per_day": round(kg * rate, 1),
            "bodyweight_kg": round(kg, 1),
            "grams_per_kg_used": rate,
            "note": "Multiplication only; the g/kg figure must come from cited guidance.",
            "error": None,
        }
    except ValueError as exc:
        return {"error": str(exc)}


def training_load(one_rep_max: float, percent: float) -> dict:
    """Working weight at a percentage of a one-rep max."""
    try:
        orm = _num(one_rep_max, "one_rep_max", 1, 1500)
        pct = _num(percent, "percent", 1, 100)
        return {"weight": round(orm * pct / 100.0, 1), "percent_of_1rm": pct, "error": None}
    except ValueError as exc:
        return {"error": str(exc)}


def estimate_one_rep_max(weight: float, reps: float) -> dict:
    """Estimated 1RM via the Epley formula."""
    try:
        w = _num(weight, "weight", 1, 1500)
        r = _num(reps, "reps", 1, 20)
        return {
            "estimated_1rm": round(w * (1 + r / 30.0), 1),
            "formula": "Epley",
            "note": "An estimate; accuracy degrades above ~10 reps.",
            "error": None,
        }
    except ValueError as exc:
        return {"error": str(exc)}


def weeks_post_op_phase(weeks: float) -> dict:
    """Map weeks since surgery to a conventional rehab phase band."""
    try:
        w = _num(weeks, "weeks", 0, 520)
        phase = next(name for lo, hi, name in _PHASES if lo <= w < hi)
        return {
            "weeks_post_op": w,
            "phase": phase,
            "note": (
                "Conventional band only. The patient's own surgeon's protocol "
                "overrides this in every case."
            ),
            "error": None,
        }
    except (ValueError, StopIteration) as exc:
        return {"error": str(exc)}


# Tool schemas advertised to the model. Kept next to the implementations so a
# signature change can't silently drift from what the LLM is told.
CALCULATOR_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "convert_weight",
            "description": "Convert a weight between kilograms and pounds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string", "enum": ["kg", "lb"]},
                    "to_unit": {"type": "string", "enum": ["kg", "lb"]},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "protein_target",
            "description": (
                "Daily protein grams from bodyweight. Supply grams_per_kg from "
                "cited guidance; this only multiplies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bodyweight": {"type": "number"},
                    "unit": {"type": "string", "enum": ["kg", "lb"]},
                    "grams_per_kg": {"type": "number"},
                },
                "required": ["bodyweight"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "training_load",
            "description": "Working weight at a given percentage of a one-rep max.",
            "parameters": {
                "type": "object",
                "properties": {
                    "one_rep_max": {"type": "number"},
                    "percent": {"type": "number"},
                },
                "required": ["one_rep_max", "percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_one_rep_max",
            "description": "Estimate a one-rep max from a weight and rep count (Epley).",
            "parameters": {
                "type": "object",
                "properties": {"weight": {"type": "number"}, "reps": {"type": "number"}},
                "required": ["weight", "reps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weeks_post_op_phase",
            "description": (
                "Map weeks since surgery to a conventional rehab phase band. "
                "The patient's own surgical protocol always overrides this."
            ),
            "parameters": {
                "type": "object",
                "properties": {"weeks": {"type": "number"}},
                "required": ["weeks"],
            },
        },
    },
]

CALCULATOR_FUNCTIONS = {
    "convert_weight": convert_weight,
    "protein_target": protein_target,
    "training_load": training_load,
    "estimate_one_rep_max": estimate_one_rep_max,
    "weeks_post_op_phase": weeks_post_op_phase,
}
