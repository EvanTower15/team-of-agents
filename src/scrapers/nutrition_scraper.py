"""
src/scrapers/nutrition_scraper.py — Automated scraper for authentic NIH & MedlinePlus nutrition documents.

Fetches public-domain health professional fact sheets and clinical nutrition guides from:
- NIH Office of Dietary Supplements (ods.od.nih.gov)
- MedlinePlus Medical Encyclopedia (medlineplus.gov)

Saves authentic extracted text and markdown documents directly into data/nutrition/.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NUTRITION_DIR = _REPO_ROOT / "data" / "nutrition"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

TARGET_SOURCES = [
    {
        "filename": "nih_ods_exercise_and_athletic_performance.md",
        "url": "https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-Consumer/",
        "title": "NIH ODS - Dietary Supplements for Exercise and Athletic Performance",
    },
    {
        "filename": "nih_ods_vitamin_c.md",
        "url": "https://ods.od.nih.gov/factsheets/VitaminC-Consumer/",
        "title": "NIH ODS - Vitamin C Fact Sheet",
    },
    {
        "filename": "nih_ods_vitamin_d.md",
        "url": "https://ods.od.nih.gov/factsheets/VitaminD-Consumer/",
        "title": "NIH ODS - Vitamin D Fact Sheet",
    },
    {
        "filename": "nih_ods_zinc.md",
        "url": "https://ods.od.nih.gov/factsheets/Zinc-Consumer/",
        "title": "NIH ODS - Zinc Fact Sheet",
    },
    {
        "filename": "nih_ods_omega3.md",
        "url": "https://ods.od.nih.gov/factsheets/Omega3FattyAcids-Consumer/",
        "title": "NIH ODS - Omega-3 Fatty Acids Fact Sheet",
    },
    {
        "filename": "nih_ods_calcium.md",
        "url": "https://ods.od.nih.gov/factsheets/Calcium-Consumer/",
        "title": "NIH ODS - Calcium Fact Sheet",
    },
    {
        "filename": "medlineplus_diet_and_wound_healing.md",
        "url": "https://medlineplus.gov/ency/article/002458.htm",
        "title": "MedlinePlus - Diet for Wound Healing and Surgical Recovery",
    },
    {
        "filename": "medlineplus_protein_in_diet.md",
        "url": "https://medlineplus.gov/ency/article/002470.htm",
        "title": "MedlinePlus - Protein in Diet",
    },
    {
        "filename": "medlineplus_vitamins.md",
        "url": "https://medlineplus.gov/ency/article/002404.htm",
        "title": "MedlinePlus - Vitamins Overview",
    },
    {
        "filename": "medlineplus_minerals.md",
        "url": "https://medlineplus.gov/ency/article/002467.htm",
        "title": "MedlinePlus - Minerals Overview",
    },
]


def clean_scraped_text(soup: BeautifulSoup) -> str:
    """Extract clean text content from NIH / MedlinePlus body tags."""
    lines = []
    for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = elem.get_text(separator=" ", strip=True)
        if not text or len(text) < 15:
            continue
        if any(skip in text.lower() for skip in ["enable javascript", "privacy policy", "terms of use"]):
            continue
        tag = elem.name
        if tag == "h1":
            lines.append(f"\n# {text}\n")
        elif tag == "h2":
            lines.append(f"\n## {text}\n")
        elif tag == "h3":
            lines.append(f"\n### {text}\n")
        elif tag == "li":
            lines.append(f"- {text}")
        else:
            lines.append(f"\n{text}")

    content = "\n".join(lines)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def scrape_nutrition_docs(target_dir: Path = NUTRITION_DIR) -> Dict[str, bool]:
    """Scrape authentic public domain nutrition documents into target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    print(f"[nutrition_scraper] Scraping {len(TARGET_SOURCES)} official NIH & MedlinePlus sources into {target_dir}...\n")

    for src in TARGET_SOURCES:
        url = src["url"]
        filename = src["filename"]
        out_path = target_dir / filename

        print(f"-> Scraping '{src['title']}' from {url}...")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"   [Error] HTTP {resp.status_code} for {url}")
                results[filename] = False
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            body_text = clean_scraped_text(soup)

            if len(body_text) < 200:
                print(f"   [Warning] Extracted text too short ({len(body_text)} chars) for {filename}")
                results[filename] = False
                continue

            # Add source metadata header
            header = (
                f"<!-- Source: {url} -->\n"
                f"<!-- Title: {src['title']} -->\n"
                f"<!-- Scraped At: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
            )
            out_path.write_text(header + body_text, encoding="utf-8")
            print(f"   [Success] Saved {len(body_text)} chars to {filename}")
            results[filename] = True

        except Exception as exc:
            print(f"   [Exception] Failed to scrape {url}: {exc}")
            results[filename] = False

        time.sleep(1.0)  # Respectful crawling delay

    successes = sum(1 for v in results.values() if v)
    print(f"\n[nutrition_scraper] Finished: {successes}/{len(TARGET_SOURCES)} documents scraped successfully.")
    return results


if __name__ == "__main__":
    scrape_nutrition_docs()
