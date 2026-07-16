"""
src/scrapers/physiopedia_scraper.py — Physiopedia Therapeutic Exercise Scraper
"""
import time
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def scrape_physiopedia(output_dir: Path) -> None:
    """
    Target the Physiopedia Therapeutic Exercise category page, extract article links,
    and save clean text (h1, h2, p) to the output directory using Playwright to bypass JS challenges.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = "https://www.physio-pedia.com"
    category_url = f"{base_url}/Category:Therapeutic_Exercise"
    
    with sync_playwright() as p:
        # Launch headless browser
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            print(f"[physiopedia_scraper] Fetching category index: {category_url}")
            page.goto(category_url, timeout=45000)
            
            # Wait for the actual content to render, bypassing any Cloudflare loading screen
            try:
                page.wait_for_selector(".mw-category", timeout=15000)
            except Exception:
                pass
                
            html_content = page.content()
        except Exception as e:
            print(f"[physiopedia_scraper] Failed to fetch category index: {e}")
            browser.close()
            return
            
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Locate the articles in the category
        mw_category = soup.find("div", class_="mw-category")
        if not mw_category:
            print("[physiopedia_scraper] Could not find the mw-category div. Ensure the page structure hasn't changed.")
            browser.close()
            return
            
        links = mw_category.find_all("a")
        article_urls = [f"{base_url}{link.get('href')}" for link in links if link.get("href")]
        print(f"[physiopedia_scraper] Found {len(article_urls)} articles.")

        for i, url in enumerate(article_urls):
            try:
                print(f"[physiopedia_scraper] ({i+1}/{len(article_urls)}) Scraping {url}...")
                page.goto(url, timeout=45000)
                
                try:
                    page.wait_for_selector("#mw-content-text, h1", timeout=15000)
                except Exception:
                    pass
                    
                article_html = page.content()
                
                article_soup = BeautifulSoup(article_html, "html.parser")
                
                # Target main content area if possible, else fallback to full page
                content_div = article_soup.find("div", id="mw-content-text") or article_soup
                
                # Extract only h1, h2, p tags, explicitly skipping menus/sidebars
                elements = content_div.find_all(["h1", "h2", "p"])
                text_blocks = [elem.get_text(separator=" ", strip=True) for elem in elements if elem.get_text(strip=True)]
                
                if text_blocks:
                    filename = url.split("/")[-1].replace(":", "_").replace("%", "_") + ".txt"
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
            
        browser.close()

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "pt" / "unstructured"
    scrape_physiopedia(out_path)
