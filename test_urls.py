import requests

urls = [
    "https://www.jospt.org/page/cpg",
    "https://www.jospt.org/topic/cpg",
    "https://aptageriatrics.org/clinical-practice-guidelines/",
]

for url in urls:
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        print(f"{url}: {res.status_code}")
    except Exception as e:
        print(f"{url}: Error {e}")
