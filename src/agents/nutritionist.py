"""
src/agents/nutritionist.py — the Sports Nutritionist specialist (4th agent 🥗).

Knowledge base: data/nutrition/ -> Chroma collection `nutrition_kb` (NIH Office of
Dietary Supplements + MedlinePlus fact sheets; see data/SOURCES.md).
Build it with:  python -m src.ingest --agent nutrition --fresh
Test standalone: python -m src.agents.nutritionist "How much protein after ACL surgery?"

On the TEAM route the nutritionist consults **last** — after the surgeon, PT, and
trainer — so every clinical restriction upstream reaches it as ``peer_context``
(decision D4). Nothing is chained downstream of it; its draft goes straight to
synthesis.

Follows the SpecialistAgent contract (base.py §5.2): the §7.1 grounding rule is
enforced by the base class, and consult() never raises.
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
    "Rules of practice:\n"
    "- Focus on evidence-based daily protein targets (for muscle protein synthesis), "
    "anti-inflammatory micronutrients (Omega-3, Vitamin C, Zinc), bone/tendon repair "
    "nutrients (Collagen + Vitamin C, Calcium + Vitamin D), and hydration.\n"
    "- Address GI support (fiber, probiotics) for patients taking post-op narcotics/antibiotics.\n"
    "- You do NOT diagnose conditions, prescribe exercises, or clear someone for activity -- "
    "if the question is really about pain, an injury, surgical precautions, or a training "
    "program, say plainly that is the surgeon's/physical therapist's/trainer's call, not yours.\n"
    "- Always respect upstream surgical, physical therapy, or gym training restrictions passed "
    "in peer_context -- they are binding on your recommendations, not the reverse.\n"
    "- If a question is outside your material (e.g. specific dosing for a medical condition, "
    "drug interactions), say plainly you don't have material on it rather than improvising.\n"
    "- Cite the source document for advice inline, like [source: filename]."
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
