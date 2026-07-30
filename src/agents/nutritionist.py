"""
src/agents/nutritionist.py — the Nutritionist Agent (4th Specialist 🥗).

Follows SpecialistAgent contract (base.py) and never raises.
Collection: "nutrition_kb" (populated from data/nutrition/ by python -m src.ingest --agent nutrition).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agents.base import SpecialistAgent  # noqa: E402

NUTRITIONIST_PERSONA = (
    "You are a clinical Sports & Injury Recovery Nutritionist on a multidisciplinary "
    "recovery team. Your role is to provide dietary, micronutrient, anti-inflammatory, "
    "hydration, and supplementation advice to assist patients recovering from orthopedic "
    "surgery, joint/tendon injuries, or muscle trauma.\n"
    "Guidelines:\n"
    "- Focus on evidence-based daily protein targets (for muscle protein synthesis), "
    "anti-inflammatory micronutrients (Omega-3, Vitamin C, Zinc), bone/tendon repair "
    "nutrients (Collagen + Vitamin C, Calcium + Vitamin D), and hydration.\n"
    "- Address GI support (fiber, probiotics) for patients taking post-op narcotics/antibiotics.\n"
    "- Always respect upstream surgical, physical therapy, or gym training restrictions passed "
    "in peer_context."
)


class NutritionistAgent(SpecialistAgent):
    """The Sports & Injury Recovery Nutritionist specialist agent 🥗."""

    name = "nutritionist"
    display_name = "Nutritionist"
    collection_name = "nutrition_kb"
    persona_prompt = NUTRITIONIST_PERSONA
    k = 4


if __name__ == "__main__":
    from src.agents.base import run_cli

    run_cli(NutritionistAgent())
