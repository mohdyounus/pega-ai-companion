"""
embeddings.py
Converts PEGA rule descriptions and XML into vector embeddings.
Uses sentence-transformers (local, no API cost) for the learn phase.
Optionally falls back to Anthropic embeddings for generation queries.
"""

from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lightweight model — fast, free, runs locally
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"  # lightweight, fast, works on Windows
EMBEDDING_DIM = 384

# Cache file to avoid re-embedding unchanged rules
CACHE_FILE = ".embedding_cache.json"


class EmbeddingEngine:
    """
    Produces vector embeddings for PEGA rules.
    Uses sentence-transformers locally (zero API cost for learn phase).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str = "./knowledge_base"):
        self.model_name = model_name
        self.cache_path = Path(cache_dir) / CACHE_FILE
        self._model = None  # lazy-loaded
        self._cache: dict[str, list[float]] = self._load_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_rule(self, rule: dict) -> list[float]:
        """
        Produce an embedding for a PEGA rule dict.
        The rule dict should have at minimum: rule_name, rule_type, description.
        Caches result by content hash to avoid redundant computation.
        """
        text = self._rule_to_text(rule)
        return self._embed_with_cache(text)

    def embed_text(self, text: str) -> list[float]:
        """Produce an embedding for arbitrary text (used in generate phase queries)."""
        return self._embed_with_cache(text)

    def embed_batch(self, rules: list[dict]) -> list[list[float]]:
        """
        Batch embed a list of rule dicts. Only computes new embeddings
        for rules not already in cache — significantly reduces learn time.
        """
        texts = [self._rule_to_text(r) for r in rules]
        hashes = [self._hash(t) for t in texts]
        results: list[Optional[list[float]]] = [None] * len(texts)

        # Identify which need computing
        to_compute_indices = [i for i, h in enumerate(hashes) if h not in self._cache]
        to_compute_texts = [texts[i] for i in to_compute_indices]

        if to_compute_texts:
            logger.info(f"Computing embeddings for {len(to_compute_texts)} rules (cache miss)")
            model = self._get_model()
            import numpy as np
            vectors = [np.array(v).tolist() for v in model.embed(to_compute_texts)]
            for i, vec in zip(to_compute_indices, vectors):
                self._cache[hashes[i]] = vec
            self._save_cache()

        for i, h in enumerate(hashes):
            results[i] = self._cache[h]

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rule_to_text(self, rule: dict) -> str:
        """
        Serialise a rule dict to a rich text string for embedding.
        More detail = better semantic search quality.
        """
        parts = []
        if rule.get("rule_name"):
            parts.append(f"Rule: {rule['rule_name']}")
        if rule.get("rule_type"):
            parts.append(f"Type: {rule['rule_type']}")
        if rule.get("pega_class"):
            parts.append(f"Class: {rule['pega_class']}")
        if rule.get("description"):
            parts.append(f"Description: {rule['description']}")
        if rule.get("business_context"):
            parts.append(f"Business context: {rule['business_context']}")
        if rule.get("dependencies"):
            deps = rule["dependencies"]
            if isinstance(deps, list):
                parts.append(f"Depends on: {', '.join(deps)}")
        if rule.get("properties"):
            props = rule["properties"]
            if isinstance(props, list):
                parts.append(f"Properties: {', '.join(props[:10])}")  # cap at 10
        return " | ".join(parts)

    def _embed_with_cache(self, text: str) -> list[float]:
        h = self._hash(text)
        if h in self._cache:
            return self._cache[h]
        model = self._get_model()
        import numpy as np
        vec = list(model.embed([text]))[0]
        self._cache[h] = np.array(vec).tolist() if hasattr(vec, '__len__') else vec
        self._save_cache()
        return vec

    def _get_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(f"Loading embedding model: {self.model_name}")
                self._model = TextEmbedding(model_name=self.model_name)
            except Exception as e:
                logger.warning(f"fastembed model load failed ({e}), using built-in hash embeddings")
                self._model = _HashEmbedder()
        return self._model

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            with open(self.cache_path, "r") as f:
                return json.load(f)
        return {}

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f)


class _HashEmbedder:
    """
    Zero-dependency fallback embedder using deterministic hash-based vectors.
    No model download needed. Works offline. Good enough for small rule sets.
    """

    DIM = 384

    def embed(self, texts):
        for text in texts:
            yield self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        import math
        vec = [0.0] * self.DIM
        words = text.lower().split()
        for i, word in enumerate(words):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % self.DIM
            vec[idx] += 1.0
        # Also use character trigrams for better semantic coverage
        for j in range(len(text) - 2):
            trigram = text[j:j+3].lower()
            h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
            idx = h % self.DIM
            vec[idx] += 0.3
        # L2 normalise
        magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / magnitude for v in vec]
