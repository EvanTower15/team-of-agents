"""
src/scrapers/physiopedia_scraper.py — Physiopedia Therapeutic Exercise Scraper
"""
import time
from pathlib import Path
from bs4 import BeautifulSoup
import cloudscraper

def scrape_physiopedia(output_dir: Path) -> None:
    """
    Target the Physiopedia Therapeutic Exercise article, extract internal links,
    and save clean text (h1, h2, p) to the output directory using cloudscraper
    to bypass Cloudflare.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = "https://www.physio-pedia.com"
    start_url = f"{base_url}/Therapeutic_Exercise"
    
    scraper = cloudscraper.create_scraper()
    
    print(f"[physiopedia_scraper] Fetching start page: {start_url}")
    try:
        res = scraper.get(start_url, timeout=15)
        if res.status_code != 200:
            print(f"[physiopedia_scraper] Failed to fetch. Status code: {res.status_code}")
            return
    except Exception as e:
        print(f"[physiopedia_scraper] Error fetching start page: {e}")
        return
        
    soup = BeautifulSoup(res.text, "html.parser")
    content_div = soup.find("div", id="mw-content-text")
    if not content_div:
        print("[physiopedia_scraper] Could not find #mw-content-text.")
        return
        
    # Extract internal article links
    links = content_div.find_all("a")
    article_urls = []
    for link in links:
        href = link.get("href")
        if href and href.startswith("/") and ":" not in href and "index.php" not in href:
            full_url = f"{base_url}{href}"
            if full_url not in article_urls:
                article_urls.append(full_url)
                
    # Also include the start page itself
    if start_url not in article_urls:
        article_urls.insert(0, start_url)
        
    # Limit to top 10 articles to avoid excessive scraping
    article_urls = article_urls[:10]
    print(f"[physiopedia_scraper] Found {len(article_urls)} articles to scrape.")

    for i, url in enumerate(article_urls):
        try:
            print(f"[physiopedia_scraper] ({i+1}/{len(article_urls)}) Scraping {url}...")
            res = scraper.get(url, timeout=15)
            if res.status_code != 200:
                print(f"  -> Failed with status {res.status_code}")
                continue
                
            article_soup = BeautifulSoup(res.text, "html.parser")
            article_content = article_soup.find("div", id="mw-content-text") or article_soup
            
            # Extract only h1, h2, p tags
            elements = article_content.find_all(["h1", "h2", "p"])
            text_blocks = [elem.get_text(separator=" ", strip=True) for elem in elements if elem.get_text(strip=True)]
            
            if text_blocks:
                filename = url.split("/")[-1].replace("%", "_") + ".txt"
                filepath = output_dir / filename
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("\n\n".join(text_blocks))
                print(f"  -> Saved {filename}")
            else:
                print("  -> No relevant content found.")
                
        except Exception as e:
            print(f"[physiopedia_scraper] Failed to scrape {url}: {e}")
            
        # Ethical delay
        time.sleep(2)

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "unstructured"
    scrape_physiopedia(out_path)
