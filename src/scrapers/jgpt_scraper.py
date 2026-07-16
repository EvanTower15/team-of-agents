import time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def _download_file(url: str, filepath: Path) -> None:
    """Helper to stream download a file with basic error handling."""
    try:
        print(f"[jgpt_scraper] Downloading: {url}")
        res = requests.get(url, headers=HEADERS, timeout=30, stream=True, allow_redirects=True)
        res.raise_for_status()
        
        with open(filepath, "wb") as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  -> Saved {filepath.name}")
    except Exception as e:
        print(f"[jgpt_scraper] Failed to download {url}: {e}")

def scrape_jgpt(output_dir: Path) -> None:
    """
    Downloads CPG PDFs from the Journal of Geriatric Physical Therapy.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # We will target a known open access CPG on their site or specific articles
    # Placeholder: Fall Risk CPG URL from APTA Geriatrics
    # Since we can't reliably scrape dynamic JS journals with requests easily if they use react/etc,
    # we target static known links or an index page.
    
    index_url = "https://aptageriatrics.org/clinical-practice-guidelines/"
    
    try:
        print(f"[jgpt_scraper] Fetching JGPT CPG index: {index_url}")
        res = requests.get(index_url, headers=HEADERS, timeout=15, allow_redirects=True)
        res.raise_for_status()
        
        soup = BeautifulSoup(res.content, "html.parser")
        
        # Find all PDF links
        pdf_links = soup.find_all("a", href=lambda href: href and href.lower().endswith(".pdf"))
        print(f"[jgpt_scraper] Found {len(pdf_links)} PDF links on page.")
        
        for link in pdf_links:
            pdf_url = urljoin(index_url, link.get("href"))
            filename = "JGPT_" + pdf_url.split("/")[-1].split("?")[0]
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            _download_file(pdf_url, output_dir / filename)
            time.sleep(2)
            
    except Exception as e:
        print(f"[jgpt_scraper] Error fetching JGPT CPG index: {e}")

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "structured"
    scrape_jgpt(out_path)
