"""
src/scrapers/jgpt_scraper.py — JGPT / Geriatrics Document Ingester
"""
import shutil
import time
from pathlib import Path

def scrape_jgpt(output_dir: Path) -> None:
    """
    Ingests curated Geriatrics CPGs and Assessment PDFs.
    Note: aptageriatrics.org is heavily protected by Sucuri Cloudproxy and returns 404s. 
    Instead, we copy the curated Geriatric PT PDFs (like CDC STEADI falls guidelines) 
    from the main data folder into the structured ingestion folder so they are properly 
    processed by the pipeline without firewall failures.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Path to the curated data folder
    curated_dir = Path(__file__).resolve().parent.parent.parent / "data" / "pt"
    
    # List of known curated geriatrics PDFs
    geriatrics_files = [
        "cdc_steadi_chair_rise_exercise.pdf",
        "cdc_steadi_stay_independent.pdf",
        "cdc_steadi_what_you_can_do.pdf",
        "nia_exercise_and_older_adults.pdf"
    ]
    
    print(f"[jgpt_scraper] Ingesting {len(geriatrics_files)} curated Geriatric PT PDFs...")
    
    for filename in geriatrics_files:
        src_path = curated_dir / filename
        dest_path = output_dir / f"Geriatrics_{filename}"
        
        if src_path.exists():
            print(f"[jgpt_scraper] Copying: {filename}")
            try:
                shutil.copy2(src_path, dest_path)
                print(f"  -> Saved {dest_path.name}")
            except Exception as e:
                print(f"  -> Failed to copy {filename}: {e}")
        else:
            print(f"[jgpt_scraper] File not found in curated data: {src_path}")
            
        time.sleep(0.5)

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "structured"
    scrape_jgpt(out_path)
