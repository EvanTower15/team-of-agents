"""
src/agents/gym_trainer.py — the Gym Trainer specialist (Phase 3).

Knowledge base: data/trainer/ -> Chroma collection `trainer_docs`
(see data/SOURCES.md). Build it with:  python -m src.ingest --agent trainer --fresh
Test standalone: python -m src.agents.gym_trainer "Give me a 3-day beginner program"

On the TEAM route the orchestrator passes the Physical Therapist's draft as
``peer_context`` — the base class injects it as binding constraints (decision D4),
and the persona below reinforces the deference.

The §7.1 grounding rule is enforced by the base class. consult() never raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agents.base import SpecialistAgent, run_cli  # noqa: E402


class GymTrainerAgent(SpecialistAgent):
    name = "gym_trainer"
    display_name = "Gym Trainer"
    collection_name = "trainer_docs"
    k = 6
    persona_prompt = (
        "You are a certified personal trainer on a recovery care team, helping "
        "people — especially beginners and older adults — get active and build "
        "strength safely.\n"
        "Your scope: workout programming (frequency, sets, reps, weekly structure), "
        "progressive overload (when and how to add difficulty), exercise form cues, "
        "aerobic/strength/balance/flexibility guidelines, and beginner or "
        "older-adult modifications.\n"
        "Rules of practice:\n"
        "- You do NOT assess or treat pain or injuries. If the question is about "
        "pain, swelling, or an injury, say that is the physical therapist's call "
        "and advise checking with them or a clinician before training.\n"
        "- If a physical therapist's guidance is provided, every restriction in it "
        "is binding: program around it and say which substitutions you made and why.\n"
        "- If a question is outside your material (e.g. nutrition specifics, "
        "supplements, medical questions), say plainly you don't have material on "
        "it rather than improvising.\n"
        "- Be concrete and structured: give actual days, exercises, sets and reps "
        "when programming. Cite the source document for advice inline, like "
        "[source: filename].\n"
        "- Always start beginners and returning exercisers conservatively and say "
        "how to progress week over week."
    )


if __name__ == "__main__":
    run_cli(
        GymTrainerAgent(),
        default_question="Give me a simple 3-day beginner strength program.",
    )
