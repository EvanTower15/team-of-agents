"""
src/tools/research.py — the two retrieval tools a specialist can call:
re-querying its OWN corpus, and (gated) searching PubMed.

`search_my_corpus` is uncontroversial: it re-runs vector search against the
specialist's own Chroma collection with better search terms. Knowledge
siloing (D3) is preserved exactly -- a specialist still cannot reach another's
corpus -- it just gets a second attempt when the first retrieval was weak.

`search_pubmed` is the one that changes this system's character, and the
tradeoff is stated here rather than buried:

    The product thesis has been that specialists answer ONLY from a curated,
    licensed, provenance-tracked corpus (§7.1 grounding rule). PubMed is
    primary research -- individual trials, small-n studies, animal models,
    conflicting findings -- not the clinically vetted patient-education
    material in data/. A single abstract is not equivalent authority to an
    NIH consensus guideline, but dropped into a synthesized answer it reads
    identically to a patient.

So it is deliberately constrained (D29):

* **Miss-path only.** Callable only when the specialist's own corpus turned up
  nothing usable. It supplements honest ignorance; it does not replace it.
* **Labeled differently.** Results carry `[research: PMID ...]`, never
  `[source: filename]`. A patient and a grader can both tell at a glance which
  claims rest on vetted guidance and which on a study abstract.
* **Never overrides a restriction.** Enforced in the synthesis prompt and
  re-checked by src/agents/compliance.py.
* **Metadata only.** Title, journal, year, PMID, and abstract from NCBI
  E-utilities -- no full text, which sidesteps the licensing problem that this
  project has already had to clean up once in data/.

Never raises: failures return an empty result list with an `error` field, so a
dead network degrades the answer to "no material found" rather than the turn.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.rag_core import retrieve  # noqa: E402

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI asks unauthenticated clients to stay at/below 3 requests/second and to
# identify themselves. One call per specialist per question stays well inside
# that; the tool loop cap in agents/base.py is what keeps it there.
_HEADERS = {"User-Agent": "RecoveryTeamEducationalProject/1.0 (course project)"}

MAX_PUBMED_RESULTS = 3
_TIMEOUT = 20


def search_my_corpus(query: str, collection_name: str, k: int = 4) -> dict:
    """Re-search the calling specialist's own collection with new terms.

    `collection_name` is injected by the agent, NOT chosen by the model, so a
    specialist cannot use this to read another specialist's corpus (D3).
    """
    try:
        docs = retrieve(query, collection_name, k=k)
        passages = []
        for doc in docs:
            p = Path(doc.metadata.get("source", "unknown"))
            passages.append(
                {
                    "source": f"{p.parent.name}/{p.name}",
                    "text": doc.page_content[:1200],
                }
            )
        return {"passages": passages, "count": len(passages), "error": None}
    except Exception as exc:
        return {"passages": [], "count": 0, "error": f"{type(exc).__name__}: {exc}"}


def search_pubmed(query: str, max_results: int = MAX_PUBMED_RESULTS) -> dict:
    """Search PubMed for study abstracts. Miss-path fallback only.

    Returns {"studies": [{pmid, title, journal, year, abstract}], "error"}.
    """
    try:
        import requests

        max_results = max(1, min(int(max_results), MAX_PUBMED_RESULTS))
        search = requests.get(
            f"{EUTILS}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return {"studies": [], "error": None}

        fetch = requests.get(
            f"{EUTILS}/efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        fetch.raise_for_status()

        studies = []
        for art in ET.fromstring(fetch.content).findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            title = art.findtext(".//ArticleTitle") or "(no title)"
            journal = art.findtext(".//Journal/Title") or ""
            year = art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or ""
            abstract = " ".join(
                (seg.text or "") for seg in art.findall(".//AbstractText")
            ).strip()
            studies.append(
                {
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "year": year,
                    "abstract": abstract[:900],
                    "citation": f"[research: PMID {pmid}]",
                }
            )
        return {"studies": studies, "error": None}
    except Exception as exc:
        return {"studies": [], "error": f"{type(exc).__name__}: {exc}"}


CORPUS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_my_corpus",
        "description": (
            "Re-search YOUR OWN knowledge base with different or more specific "
            "terms. Use this first when your initial context was thin or off-topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Reworded search terms, e.g. clinical synonyms.",
                }
            },
            "required": ["query"],
        },
    },
}

PUBMED_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_pubmed",
        "description": (
            "Search published research abstracts. ONLY use this after "
            "search_my_corpus found nothing usable. Results are individual "
            "studies, NOT vetted patient guidance -- present them as published "
            "research, cite them as [research: PMID ...], and never let them "
            "override a restriction from the patient's own care team."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}
