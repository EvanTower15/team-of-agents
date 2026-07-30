"""
src/scrapers/nutrition_media_scraper.py — Scrapes open-access Nutrition & Healthy Food Plate diagrams.

Scrapes public domain / CC-licensed dietary diagrams (USDA MyPlate, food pyramid, dietary protein sources,
vitamin & mineral food charts) from Wikimedia Commons into data/nutrition/visuals/.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NUTRITION_VISUALS_DIR = _REPO_ROOT / "data" / "nutrition" / "visuals"

HEADERS = {"User-Agent": "RecoveryTeamEducationalBot/1.0 (educational support project)"}

SEARCH_QUERIES = [
    "MyPlate",
    "Food pyramid",
    "Nutrition guide",
    "Dietary protein",
    "Vitamin C foods",
    "Calcium food",
    "Healthy eating plate",
]


def scrape_nutrition_images(target_dir: Path = NUTRITION_VISUALS_DIR) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    print(f"[nutrition_media_scraper] Scraping open nutrition & food plate diagrams into {target_dir}...")

    for query in SEARCH_QUERIES:
        url = (
            "https://commons.wikimedia.org/w/api.php?"
            "action=query&format=json&generator=search&gsrnamespace=6&"
            f"gsrsearch={requests.utils.quote(query)}&prop=imageinfo&iiprop=url|mime&gsrlimit=10"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            downloaded = 0
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                img_url = info.get("url")
                mime = info.get("mime", "")
                if not img_url or not mime.startswith("image/"):
                    continue

                ext = ".jpg" if "jpeg" in mime or "jpg" in mime else (".png" if "png" in mime else ".webp")
                raw_title = page.get("title", "img").replace("File:", "").strip()
                clean_name = re.sub(r"[^\w\-_]", "_", raw_title)[:45]
                out_path = target_dir / f"nutrition_{clean_name}{ext}"

                if out_path.exists():
                    continue

                img_resp = requests.get(img_url, headers=HEADERS, timeout=15)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    out_path.write_bytes(img_resp.content)
                    print(f"  [Downloaded] {out_path.name} ({len(img_resp.content)//1024} KB)")
                    count += 1
                    downloaded += 1
                    if downloaded >= 4:
                        break
        except Exception as exc:
            print(f"  [Error] {query}: {exc}")

        time.sleep(0.5)

    print(f"[nutrition_media_scraper] Complete. Downloaded {count} nutrition diagram(s).\n")
    return count


if __name__ == "__main__":
    scrape_nutrition_images()
