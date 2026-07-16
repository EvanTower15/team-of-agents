import time
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import urllib.parse

def scrape_jospt(output_dir: Path) -> None:
    """
    Downloads CPG PDFs from JOSPT using Playwright to bypass their 403 WAF.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # We will target a known open access CPG as an example (Neck Pain Revision)
    # and a general search page if possible. For robustness, we will fetch a direct article.
    targets = [
        "https://www.jospt.org/doi/10.2519/jospt.2017.0302" # Neck pain CPG
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        for url in targets:
            try:
                print(f"[jospt_scraper] Fetching JOSPT article: {url}")
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                
                # Wait for any potential Cloudflare challenge to pass
                try:
                    page.wait_for_selector(".article-content, .pdf-link, h1", timeout=15000)
                except Exception:
                    pass
                    
                html_content = page.content()
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Try to find a PDF download link
                pdf_link = None
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "pdf" in href.lower() or "download" in href.lower():
                        pdf_link = urllib.parse.urljoin(url, href)
                        break
                        
                if pdf_link:
                    print(f"[jospt_scraper] Found PDF link: {pdf_link}")
                    # Downloading the PDF through playwright to keep the session/cookies
                    try:
                        with page.expect_download(timeout=30000) as download_info:
                            page.goto(pdf_link)
                        download = download_info.value
                        
                        filename = "JOSPT_" + url.split("/")[-1] + ".pdf"
                        filepath = output_dir / filename
                        download.save_as(filepath)
                        print(f"  -> Saved {filename}")
                    except Exception as download_err:
                        # Fallback: Maybe it's a direct link that renders in browser
                        print(f"[jospt_scraper] Standard download failed ({download_err}). Trying to extract text directly from HTML...")
                        content_div = soup.find("div", class_="article-content") or soup.find("main") or soup
                        text_blocks = [elem.get_text(separator=" ", strip=True) for elem in content_div.find_all(["h1", "h2", "h3", "p"]) if elem.get_text(strip=True)]
                        if text_blocks:
                            filename = "JOSPT_" + url.split("/")[-1] + ".txt"
                            filepath = output_dir.parent.parent / "unstructured" / filename
                            filepath.parent.mkdir(parents=True, exist_ok=True)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write("\n\n".join(text_blocks))
                            print(f"  -> Saved {filename} as text fallback.")
                else:
                    # If no PDF link, just scrape the HTML text
                    print(f"[jospt_scraper] No PDF link found. Extracting HTML text instead.")
                    content_div = soup.find("div", class_="article-content") or soup.find("main") or soup
                    text_blocks = [elem.get_text(separator=" ", strip=True) for elem in content_div.find_all(["h1", "h2", "h3", "p"]) if elem.get_text(strip=True)]
                    if text_blocks:
                        filename = "JOSPT_" + url.split("/")[-1] + ".txt"
                        filepath = output_dir.parent.parent / "unstructured" / filename
                        filepath.parent.mkdir(parents=True, exist_ok=True)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write("\n\n".join(text_blocks))
                        print(f"  -> Saved {filename} as text fallback.")
            
            except Exception as e:
                print(f"[jospt_scraper] Error processing {url}: {e}")
                
            time.sleep(3)
            
        browser.close()

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "structured"
    scrape_jospt(out_path)
