"""
src/scrapers/clinical_downloader.py — Clinical Data Downloader
"""
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
        print(f"[clinical_downloader] Downloading: {url}")
        res = requests.get(url, headers=HEADERS, timeout=30, stream=True)
        res.raise_for_status()
        
        with open(filepath, "wb") as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  -> Saved {filepath.name}")
    except Exception as e:
        print(f"[clinical_downloader] Failed to download {url}: {e}")

def download_clinical_data(output_dir: Path) -> None:
    """
    Downloads CPG PDFs from the APTA Orthopedics index and the Evidence-Based
    Massage Therapy OER textbook directly into the output directory.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Evidence-Based Massage Therapy OER (Direct PDF)
    oer_url = "https://openlibrary-repo.ecampusontario.ca/jspui/bitstream/123456789/641/3/Evidence-Based-Massage-Therapy-1592410109._print.pdf"
    oer_filename = "Evidence-Based-Massage-Therapy.pdf"
    _download_file(oer_url, output_dir / oer_filename)
    
    # Ethical delay
    time.sleep(2)
    
    # 2. APTA Orthopedics CPGs
    cpg_index_url = "https://www.orthopt.org/content/practice/clinical-practice-guidelines"
    try:
        print(f"[clinical_downloader] Fetching CPG index: {cpg_index_url}")
        res = requests.get(cpg_index_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        
        soup = BeautifulSoup(res.content, "html.parser")
        # Find all PDF links
        pdf_links = soup.find_all("a", href=lambda href: href and href.lower().endswith(".pdf"))
        print(f"[clinical_downloader] Found {len(pdf_links)} PDF links on CPG page.")
        
        for link in pdf_links:
            pdf_url = urljoin(cpg_index_url, link.get("href"))
            filename = pdf_url.split("/")[-1]
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            _download_file(pdf_url, output_dir / filename)
            # Ethical delay
            time.sleep(2)
            
    except Exception as e:
        print(f"[clinical_downloader] Error fetching CPG index: {e}")

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "structured"
    download_clinical_data(out_path)
