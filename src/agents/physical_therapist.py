"""
src/agents/physical_therapist.py — the Physical Therapist specialist (Phase 2).

Knowledge base: data/pt/ -> Chroma collection `pt_docs` (see data/SOURCES.md).
Build it with:  python -m src.ingest --agent pt --fresh
Test standalone: python -m src.agents.physical_therapist "My knee aches after squats"

The §7.1 grounding rule is enforced by the base class — the persona below only
defines voice and scope. consult() never raises (see base.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agents.base import SpecialistAgent, run_cli  # noqa: E402


class PhysicalTherapistAgent(SpecialistAgent):
    name = "physical_therapist"
    display_name = "Physical Therapist"
    collection_name = "pt_docs"
    # Larger corpus than the smoke tests -> a couple more passages of context.
    k = 6
    persona_prompt = (
        "You are a licensed physical therapist (DPT) on a recovery care team, "
        "helping people rehabilitate injuries and safely return to activity.\n"
        "Your scope: rehabilitation progressions, the difference between normal "
        "post-exercise soreness and pain that signals a problem, range-of-motion "
        "and mobility work, and when to regress or pause an exercise.\n"
        "Rules of practice:\n"
        "- You do NOT diagnose. If the question asks what condition someone has, "
        "explain what the context says about such symptoms and advise them to see "
        "a clinician for diagnosis.\n"
        "- If a question is outside physical-therapy scope (nutrition, supplements, "
        "medications, surgical decisions), say plainly that it is not your area "
        "rather than improvising.\n"
        "- Be concise and practical. Cite the source document for advice inline, "
        "like [source: filename].\n"
        "- When advice depends on injury stage or severity, say so explicitly "
        "(e.g. 'in the first 72 hours...' vs 'once swelling has settled...')."
    )


if __name__ == "__main__":
    run_cli(
        PhysicalTherapistAgent(),
        default_question="My knee aches when I go down stairs since I sprained it. "
        "Which exercises could help?",
    )
