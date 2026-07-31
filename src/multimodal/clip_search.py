"""
src/multimodal/clip_search.py — Multimodal Visual Search Engine.

Scans, indexes, and retrieves scraped educational diagrams across all 4 specialists:
- Surgeon (data/surgeon/visuals/)
- Physical Therapist (data/pt/visuals/)
- Gym Trainer (data/trainer/visuals/)
- Nutritionist (data/nutrition/visuals/)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Dict, Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _REPO_ROOT / "data"

SPECIALIST_VISUAL_DIRS = {
    "surgeon": DATA_DIR / "surgeon" / "visuals",
    "pt": DATA_DIR / "pt" / "visuals",
    "trainer": DATA_DIR / "trainer" / "visuals",
    "nutrition": DATA_DIR / "nutrition" / "visuals",
}


class MultimodalVisualSearch:
    """Multimodal search engine over scraped educational diagrams."""

    def __init__(self) -> None:
        self.catalog = []
        self._scan_and_index()

    def _scan_and_index(self) -> None:
        """Scan all specialist visuals directories and build visual catalog."""
        self.catalog = []
        for agent, vdir in SPECIALIST_VISUAL_DIRS.items():
            if not vdir.exists():
                vdir.mkdir(parents=True, exist_ok=True)
                continue

            for img_path in vdir.glob("*"):
                if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue

                raw_name = img_path.stem.replace("_", " ")
                tags = [t.lower() for t in re.findall(r"\w+", raw_name)] + [agent]
                self.catalog.append(
                    {
                        "id": f"{agent}_{img_path.name}",
                        "title": raw_name.title(),
                        "agent": agent,
                        "file_path": str(img_path),
                        "tags": tags,
                    }
                )

    def search_visuals(self, query: str, agent_filter: str | None = None, top_k: int = 2) -> List[Dict[str, Any]]:
        """Search visual assets matching query terms."""
        query_words = set(query.lower().split())
        results = []
        for item in self.catalog:
            if agent_filter and item["agent"] != agent_filter:
                continue

            score = sum(1 for tag in item["tags"] if any(w in tag for w in query_words))
            if score > 0 or not query_words:
                results.append((score, item))

        results.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in results[:top_k]]


if __name__ == "__main__":
    searcher = MultimodalVisualSearch()
    print(f"Total indexed images across all specialists: {len(searcher.catalog)}")
    for item in searcher.catalog:
        print(f" - [{item['agent'].upper()}] {item['title']} -> {item['file_path']}")
