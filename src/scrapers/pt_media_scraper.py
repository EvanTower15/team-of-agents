"""
src/scrapers/pt_media_scraper.py — Scrapes open-access Physical Therapy & Rehab exercise motion diagrams.

Scrapes public domain / CC-licensed rehab motion diagrams (quad sets, straight leg raises, gait mechanics, shoulder pendulums)
into data/pt/visuals/.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PT_VISUALS_DIR = _REPO_ROOT / "data" / "pt" / "visuals"

HEADERS = {"User-Agent": "RecoveryTeamEducationalBot/1.0 (educational support project)"}

SEARCH_QUERIES = [
    "Knee exercise",
    "Physical therapy exercise",
    "Stretching exercise",
    "Shoulder rehab",
]


def scrape_pt_images(target_dir: Path = PT_VISUALS_DIR) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    print(f"[pt_media_scraper] Scraping open physical therapy rehab diagrams into {target_dir}...")

    for query in SEARCH_QUERIES:
        url = (
            "https://commons.wikimedia.org/w/api.php?"
            "action=query&format=json&generator=search&gsrnamespace=6&"
            f"gsrsearch={requests.utils.quote(query)}&prop=imageinfo&iiprop=url|mime"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                img_url = info.get("url")
                mime = info.get("mime", "")
                if not img_url or not mime.startswith("image/"):
                    continue

                ext = ".jpg" if "jpeg" in mime or "jpg" in mime else (".png" if "png" in mime else ".webp")
                safe_title = "".join(c for c in page.get("title", "img") if c.isalnum() or c in (" ", "_")).strip()
                safe_title = safe_title.replace("File", "").replace(" ", "_")[:50]
                out_path = target_dir / f"{safe_title}{ext}"

                if out_path.exists():
                    continue

                img_resp = requests.get(img_url, headers=HEADERS, timeout=15)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    out_path.write_bytes(img_resp.content)
                    print(f"  [Downloaded] {out_path.name} ({len(img_resp.content)//1024} KB)")
                    count += 1
                    if count >= 3:
                        break
        except Exception as exc:
            print(f"  [Error] {query}: {exc}")

        time.sleep(1.0)

    print(f"[pt_media_scraper] Complete. Downloaded {count} PT rehab diagram(s).\n")
    return count


if __name__ == "__main__":
    scrape_pt_images()
