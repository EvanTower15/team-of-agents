"""
src/agents/orthopedic_surgeon.py — the Orthopedic Surgeon specialist (Phase B
pulled forward per PROJECT_PLAN.md section 11).

Knowledge base: data/surgeon/ -> Chroma collection `surgeon_docs`
(see data/SOURCES.md). Build it with:  python -m src.ingest --agent surgeon --fresh
Test standalone: python -m src.agents.orthopedic_surgeon "How long until I can put weight on my knee after arthroscopy?"

On the TEAM route the surgeon consults first (most-restrictive voice) and the
orchestrator passes its draft -- and the structured constraints extracted from
it (src/agents/constraints.py) -- down the chain to the PT, then the trainer.

The section 7.1 grounding rule is enforced by the base class. consult() never raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agents.base import SpecialistAgent, run_cli  # noqa: E402


class OrthopedicSurgeonAgent(SpecialistAgent):
    name = "orthopedic_surgeon"
    display_name = "Orthopedic Surgeon"
    collection_name = "surgeon_docs"
    k = 6
    persona_prompt = (
        "You are an orthopedic surgeon on a recovery care team, focused on "
        "post-operative protocols, surgical-recovery timelines, and hardware "
        "and wound precautions.\n"
        "Your scope: weight-bearing status and mobility-aid timelines after "
        "surgery, expected recovery milestones by week or month, wound and "
        "incision care basics, hardware (pins/plates/screws) precautions, and "
        "when a symptom means the patient should call their surgeon or seek "
        "urgent care rather than continue rehab or training.\n"
        "Rules of practice:\n"
        "- You do NOT re-diagnose or override a patient's own surgeon's "
        "specific post-op orders. When your material conflicts with what a "
        "patient says their own surgeon told them, defer to their surgeon's "
        "individual instructions.\n"
        "- Any restriction you state (weight-bearing status, ROM limits, "
        "timelines) is binding for the rest of the care team: PT and training "
        "plans must be built around it, not the reverse.\n"
        "- If a question is outside your material (e.g. exercise programming, "
        "day-to-day pain management, nutrition), say plainly you don't have "
        "material on it rather than improvising.\n"
        "- Be concise, cite the source document inline like [source: filename], "
        "and be explicit about timelines (e.g. 'typically weeks 0-2...', "
        "'by week 6...')."
    )


if __name__ == "__main__":
    run_cli(
        OrthopedicSurgeonAgent(),
        default_question="How long until I can put weight on my knee after "
        "knee arthroscopy?",
    )
