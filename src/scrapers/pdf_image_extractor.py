"""
src/scrapers/pdf_image_extractor.py — Extracts embedded figures & exercise diagrams from project PDFs.

Iterates over all PDF documents in data/pt/, data/trainer/, data/surgeon/, data/nutrition/
and extracts embedded exercise illustrations, form guides, and medical charts directly into data/{agent}/visuals/.
"""

from __future__ import annotations

import os
from pathlib import Path
import pypdf

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _REPO_ROOT / "data"


def extract_images_from_pdfs() -> dict[str, int]:
    """Extract embedded images from all PDF files in data/ subdirectories."""
    extracted_counts = {}

    for agent_dir in DATA_DIR.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("chroma_db", ".git"):
            continue

        agent_name = agent_dir.name
        visuals_dir = agent_dir / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        count = 0

        print(f"[pdf_extractor] Checking PDFs for agent '{agent_name}'...")
        for pdf_path in agent_dir.rglob("*.pdf"):
            try:
                reader = pypdf.PdfReader(str(pdf_path))
                pdf_stem = pdf_path.stem[:30]

                for page_idx, page in enumerate(reader.pages):
                    try:
                        for img_idx, img in enumerate(page.images):
                            # Filter out tiny logos/icons < 3000 bytes
                            if len(img.data) < 3000:
                                continue

                            ext = Path(img.name).suffix.lower() or ".png"
                            out_name = f"pdf_{pdf_stem}_p{page_idx+1}_img{img_idx+1}{ext}"
                            out_path = visuals_dir / out_name

                            if out_path.exists():
                                continue

                            out_path.write_bytes(img.data)
                            count += 1
                            print(f"  [Extracted] {out_name} ({len(img.data)//1024} KB) from {pdf_path.name}")
                    except Exception as e:
                        continue
            except Exception as exc:
                print(f"  [Warning] Could not read PDF {pdf_path.name}: {exc}")

        extracted_counts[agent_name] = count
        print(f"[pdf_extractor] Agent '{agent_name}': {count} new image(s) extracted.\n")

    return extracted_counts


if __name__ == "__main__":
    extract_images_from_pdfs()
