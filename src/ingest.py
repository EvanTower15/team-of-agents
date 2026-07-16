"""
src/ingest.py — CLI to build one agent's knowledge base from its data folder.

    python -m src.ingest --agent pt              # data/pt/      → pt_docs
    python -m src.ingest --agent trainer         # data/trainer/ → trainer_docs
    python -m src.ingest --agent pt --fresh      # clear pt_docs first, then build

Each agent's collection is independent (PROJECT_PLAN.md decision D3): rebuilding
the PT knowledge base never touches the trainer's, and vice versa.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `from src.X import ...` work whether run as `python -m src.ingest`
# or as a plain script (same shim as the opim-5517 reference project).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag_core import clear_collection, ingest_folder  # noqa: E402
from src.scrapers.physiopedia_scraper import scrape_physiopedia  # noqa: E402
from src.scrapers.clinical_downloader import download_clinical_data  # noqa: E402
from src.scrapers.jospt_scraper import scrape_jospt  # noqa: E402
from src.scrapers.jgpt_scraper import scrape_jgpt  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent

# agent flag → (corpus folder, Chroma collection). Phase B adds "surgeon" here.
AGENT_CORPORA = {
    "pt": (_REPO_ROOT / "data" / "pt", "pt_docs"),
    "trainer": (_REPO_ROOT / "data" / "trainer", "trainer_docs"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a specialist agent's vector-store knowledge base."
    )
    parser.add_argument(
        "--agent",
        required=True,
        choices=sorted(AGENT_CORPORA),
        help="which agent's corpus to ingest",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="clear the agent's existing collection before ingesting",
    )
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="run data collection scrapers before ingesting",
    )
    args = parser.parse_args()

    folder, collection = AGENT_CORPORA[args.agent]
    
    if args.scrape and args.agent == "pt":
        print(f"[ingest] Running scrapers for PT agent... Outputting to {folder}")
        scrape_physiopedia(folder / "unstructured")
        download_clinical_data(folder / "structured")
        scrape_jospt(folder / "structured")
        scrape_jgpt(folder / "structured")

    if args.fresh:
        clear_collection(collection)

    added = ingest_folder(str(folder), collection)
    print(f"[ingest] Done: {added} chunk(s) added to '{collection}' from {folder}")


if __name__ == "__main__":
    main()
