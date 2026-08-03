"""
src/multimodal/clip_search.py — real CLIP embedding search over the visuals
folders for all 4 specialists (data/{surgeon,pt,trainer,nutrition}/visuals/).

Uses `sentence-transformers`' CLIP model (clip-ViT-B-32) to embed the actual
image pixels into a shared image/text vector space, then answers text queries
by cosine similarity against those image embeddings. This is the same
retrieval pattern rag_core.py already uses for text (embed once, similarity
search at query time), just with a multimodal model so a text query can match
image *content* rather than filenames.

This replaces an earlier filename-substring implementation that never opened
the images at all -- it could only find pictures whose filename happened to
contain the query words, so an image named `p27_img1.jpg` (most of this
corpus, since many were auto-extracted from PDF pages) was unfindable by any
query. Most of the ~290 images here have exactly that kind of opaque
auto-generated name, so filename matching was near-useless in practice.

The embedding index is computed once and cached to disk (clip_index.npz,
gitignored) keyed by a fingerprint of the image set, so startup is fast after
the first run and the index rebuilds automatically when images are added or
removed.

Falls back gracefully: if sentence-transformers/torch/Pillow aren't available
or a model download fails, `search_visuals()` returns [] rather than raising,
and `self.available` is False so callers can tell real "no matches" from
"search isn't working".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _REPO_ROOT / "data"
INDEX_PATH = _REPO_ROOT / "clip_index.npz"

CLIP_MODEL = "clip-ViT-B-32"

SPECIALIST_VISUAL_DIRS = {
    "surgeon": DATA_DIR / "surgeon" / "visuals",
    "pt": DATA_DIR / "pt" / "visuals",
    "trainer": DATA_DIR / "trainer" / "visuals",
    "nutrition": DATA_DIR / "nutrition" / "visuals",
}

# .jp2 is deliberately excluded: Pillow needs an extra codec for JPEG-2000 and
# several of the auto-extracted ones in this corpus fail to open.
_SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Below this cosine similarity a "match" is just noise. CLIP always returns a
# nearest neighbour for any query, so without a floor the UI would confidently
# show an unrelated anatomy diagram for a nutrition question.
_MIN_SIMILARITY = 0.20


class MultimodalVisualSearch:
    """CLIP-based semantic search over the specialists' educational diagrams."""

    def __init__(self) -> None:
        self.catalog: List[Dict[str, Any]] = []
        self.available = False
        self._model = None
        self._embeddings = None
        self._scan_catalog()
        self._load_or_build_index()

    def _scan_catalog(self) -> None:
        """Enumerate every supported image across all specialist visuals dirs."""
        self.catalog = []
        for agent, vdir in SPECIALIST_VISUAL_DIRS.items():
            if not vdir.exists():
                continue
            for img_path in sorted(vdir.glob("*")):
                if img_path.suffix.lower() not in _SUPPORTED_EXTS:
                    continue
                raw_name = img_path.stem.replace("_", " ")
                self.catalog.append(
                    {
                        "id": f"{agent}_{img_path.name}",
                        "title": raw_name.title(),
                        "agent": agent,
                        "file_path": str(img_path),
                    }
                )

    def _fingerprint(self) -> str:
        """Hash of the current image set, so a stale cache is never used."""
        joined = "|".join(item["file_path"] for item in self.catalog)
        return hashlib.md5(joined.encode("utf-8")).hexdigest()

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(CLIP_MODEL)
        return self._model

    def _load_or_build_index(self) -> None:
        """Load cached image embeddings, or compute and cache them."""
        if not self.catalog:
            return
        try:
            import numpy as np

            fingerprint = self._fingerprint()
            if INDEX_PATH.exists():
                cached = np.load(INDEX_PATH, allow_pickle=False)
                if str(cached["fingerprint"]) == fingerprint:
                    # Realign the catalog to exactly the images that were
                    # successfully embedded. _embed_images() drops unreadable
                    # files, so a cache-hit path that reused the full scanned
                    # catalog would pair embeddings with the WRONG image from
                    # the first skipped file onward -- silently returning
                    # mislabeled results (caught in live testing).
                    embedded_paths = [str(p) for p in cached["paths"]]
                    by_path = {item["file_path"]: item for item in self.catalog}
                    self.catalog = [by_path[p] for p in embedded_paths if p in by_path]
                    self._embeddings = cached["embeddings"]
                    self.available = len(self.catalog) == len(self._embeddings)
                    if self.available:
                        return

            self._embeddings = self._embed_images()
            if self._embeddings is not None and len(self._embeddings):
                np.savez(
                    INDEX_PATH,
                    embeddings=self._embeddings,
                    fingerprint=np.array(fingerprint),
                    paths=np.array([item["file_path"] for item in self.catalog]),
                )
                self.available = True
        except Exception as exc:
            print(f"[clip_search] Visual search unavailable ({exc}); returning no results.")
            self.available = False

    def _embed_images(self):
        """Embed every catalog image. Unreadable images are dropped from the
        catalog so embeddings and catalog stay index-aligned."""
        import numpy as np
        from PIL import Image

        model = self._get_model()
        vectors, kept = [], []
        print(f"[clip_search] Building CLIP index over {len(self.catalog)} image(s) (first run only)...")
        for item in self.catalog:
            try:
                with Image.open(item["file_path"]) as img:
                    vectors.append(model.encode(img.convert("RGB")))
                kept.append(item)
            except Exception as exc:
                print(f"[clip_search] Skipping unreadable image {item['file_path']}: {exc}")
        self.catalog = kept
        return np.array(vectors) if vectors else None

    @staticmethod
    def _filename_bonus(query: str, item: Dict[str, Any]) -> float:
        """Small score boost when the filename itself matches the query.

        CLIP handles photographs well but is weak on dense, text-heavy
        instructional diagrams (verified: a labeled "Squats for strengthening
        your leg muscles" infographic scored below rank 20 for "squat exercise
        form", while a plain photo of a squat ranked 1st). Those diagrams are
        also the ones most likely to have a descriptive human-given filename,
        so a light keyword signal recovers exactly the cases CLIP misses --
        without displacing genuine visual matches, since the bonus is capped
        well below the typical spread of CLIP scores.
        """
        words = {w for w in query.lower().split() if len(w) > 3}
        if not words:
            return 0.0
        name = Path(item["file_path"]).stem.lower()
        # Prefix match so "squat" hits "squatting", "exercise" hits "exercises".
        hits = sum(1 for w in words if w[:5] in name)
        return min(hits, 2) * 0.06

    def search_visuals(
        self, query: str, agent_filter: str | None = None, top_k: int = 2
    ) -> List[Dict[str, Any]]:
        """Return the top_k images best matching `query`.

        Hybrid score: CLIP image-embedding similarity (the primary signal,
        works on content regardless of filename) plus a small filename-keyword
        bonus (recovers text-heavy diagrams CLIP under-ranks). Returns []
        (never raises) when search is unavailable or nothing clears the floor.
        """
        if not self.available or self._embeddings is None or not query.strip():
            return []
        try:
            import numpy as np

            q_vec = self._get_model().encode(query)
            # Cosine similarity against every image embedding.
            sims = self._embeddings @ q_vec / (
                np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(q_vec) + 1e-10
            )

            scored = []
            for sim, item in zip(sims, self.catalog):
                if agent_filter is not None and item["agent"] != agent_filter:
                    continue
                combined = float(sim) + self._filename_bonus(query, item)
                if combined >= _MIN_SIMILARITY:
                    scored.append((combined, float(sim), item))

            scored.sort(key=lambda triple: triple[0], reverse=True)
            return [
                {**item, "similarity": round(combined, 3), "clip_similarity": round(sim, 3)}
                for combined, sim, item in scored[:top_k]
            ]
        except Exception as exc:
            print(f"[clip_search] Search failed ({exc}); returning no results.")
            return []


if __name__ == "__main__":
    searcher = MultimodalVisualSearch()
    print(f"Indexed {len(searcher.catalog)} image(s); available={searcher.available}")
    for q in ("knee anatomy diagram", "healthy eating plate", "squat exercise form"):
        hits = searcher.search_visuals(q, top_k=3)
        print(f"\nQuery: {q!r}")
        for h in hits:
            print(f"  [{h['similarity']}] ({h['agent']}) {h['title']} -> {h['file_path']}")
        if not hits:
            print("  (no matches above similarity floor)")
