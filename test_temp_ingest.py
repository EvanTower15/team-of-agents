import sys
import shutil
import traceback
from pathlib import Path

# Add project root to path
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from src.scrapers.physiopedia_scraper import scrape_physiopedia
from src.scrapers.clinical_downloader import download_clinical_data
from src.scrapers.jospt_scraper import scrape_jospt
from src.scrapers.jgpt_scraper import scrape_jgpt
from src.rag_core import load_folder_documents, split_documents

def run_test():
    test_dir = _REPO_ROOT / "data" / "test_tmp_pt"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    
    test_dir.mkdir(parents=True, exist_ok=True)
    unstructured = test_dir / "unstructured"
    structured = test_dir / "structured"
    
    unstructured.mkdir(exist_ok=True)
    structured.mkdir(exist_ok=True)
    
    try:
        print("--- 1. Testing Scrapers ---")
        print("Running physiopedia scraper...")
        scrape_physiopedia(unstructured)
        
        print("\nRunning clinical downloader...")
        download_clinical_data(structured)
        
        print("\nRunning JOSPT scraper...")
        scrape_jospt(structured)
        
        print("\nRunning JGPT scraper...")
        scrape_jgpt(structured)
        
        print("\n--- 2. Testing Ingestion Parsing (Docling & TextLoader) ---")
        print(f"Loading documents from {test_dir}...")
        docs = load_folder_documents(str(test_dir))
        print(f"Loaded {len(docs)} document objects.")
        
        if docs:
            print("\n--- 3. Testing Chunking ---")
            chunks = split_documents(docs)
            print(f"Successfully produced {len(chunks)} chunks.")
            print("\nTest passed successfully!")
        else:
            print("\nWarning: No documents were parsed!")
            
    except Exception as e:
        print(f"\nTEST FAILED WITH ERROR: {e}")
        traceback.print_exc()
    finally:
        print("\n--- 4. Cleaning up ---")
        if test_dir.exists():
            shutil.rmtree(test_dir)
        print("Temporary files removed.")

if __name__ == "__main__":
    run_test()
