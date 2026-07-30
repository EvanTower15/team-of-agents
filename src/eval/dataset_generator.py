"""
src/eval/dataset_generator.py — Synthetic evaluation dataset generation.

Generates synthetic test benchmark datasets for evaluating multi-agent routing,
specialist grounding, and constraint enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path

_EVAL_DATASET = [
    {
        "id": "eval_01",
        "question": "What protein intake should I target post ACL surgery to prevent muscle atrophy?",
        "expected_route": "NUTRITION_ONLY",
        "expected_specialists": ["nutritionist"],
        "category": "nutrition",
    },
    {
        "id": "eval_02",
        "question": "I am 10 weeks post rotator cuff repair, can I start doing light dumbbell presses and what should I eat?",
        "expected_route": "TEAM",
        "expected_specialists": ["surgeon", "pt", "trainer", "nutritionist"],
        "category": "multi_agent_team",
    },
    {
        "id": "eval_03",
        "question": "My calf is extremely hot, red, and swollen after ankle surgery.",
        "expected_route": "RED_FLAG",
        "expected_specialists": [],
        "category": "safety_red_flag",
    },
    {
        "id": "eval_04",
        "question": "I have lateral knee pain when running past 3 miles. What rehab exercises help?",
        "expected_route": "PT_ONLY",
        "expected_specialists": ["physical_therapist"],
        "category": "rehab_pt",
    },
    {
        "id": "eval_05",
        "question": "How do I structure a 3-day full body workout routine for a beginner?",
        "expected_route": "TRAINER_ONLY",
        "expected_specialists": ["gym_trainer"],
        "category": "strength_trainer",
    },
]


def save_synthetic_dataset(output_path: str = "src/eval/synthetic_dataset.json") -> str:
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(_EVAL_DATASET, f, indent=2)
    print(f"[eval] Saved synthetic dataset with {len(_EVAL_DATASET)} rows to {p}.")
    push_to_langsmith_dataset()
    return str(p)


def push_to_langsmith_dataset(dataset_name: str = "recovery-team-eval-dataset") -> None:
    """Push evaluation dataset directly to LangSmith Cloud dataset registry."""
    import os
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("[langsmith] API key not set; local synthetic dataset saved.")
        return
    try:
        from langsmith import Client
        client = Client()
        if not client.has_dataset(dataset_name=dataset_name):
            ds = client.create_dataset(dataset_name=dataset_name, description="Recovery Team MAS evaluation benchmark")
            inputs = [{"question": item["question"]} for item in _EVAL_DATASET]
            outputs = [
                {
                    "expected_route": item["expected_route"],
                    "expected_specialists": item["expected_specialists"],
                }
                for item in _EVAL_DATASET
            ]
            client.create_examples(inputs=inputs, outputs=outputs, dataset_id=ds.id)
            print(f"[langsmith] Successfully pushed dataset '{dataset_name}' to LangSmith Cloud.")
    except Exception as e:
        print(f"[langsmith] LangSmith dataset upload note: {e}")


if __name__ == "__main__":
    save_synthetic_dataset()
