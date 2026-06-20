"""
vector_store.py
ChromaDB wrapper for storing and querying PEGA rule embeddings.
"""

import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

COLLECTION_NAME = "pega_rules"


class VectorStore:
    """
    Persistent local ChromaDB vector store for PEGA rule knowledge.
    Stores rule embeddings and metadata for semantic similarity search.
    """

    def __init__(self, persist_dir: str = "./knowledge_base"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"VectorStore initialised at {self.persist_dir} — {self.count()} rules loaded")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, rule_id: str, embedding: list[float], metadata: dict, document: str):
        """
        Insert or update a rule in the vector store.

        Args:
            rule_id:   Unique rule identifier (e.g. 'KYC-IdentityCheck')
            embedding: Float vector produced by embeddings.py
            metadata:  Dict of rule attributes (type, class, app, etc.)
            document:  Plain-text description/summary of the rule (stored for retrieval display)
        """
        self.collection.upsert(
            ids=[rule_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    def upsert_batch(self, rules: list[dict]):
        """
        Batch upsert for efficiency during the learn phase.

        Each dict must have keys: rule_id, embedding, metadata, document
        """
        if not rules:
            return
        self.collection.upsert(
            ids=[r["rule_id"] for r in rules],
            embeddings=[r["embedding"] for r in rules],
            metadatas=[r["metadata"] for r in rules],
            documents=[r["document"] for r in rules],
        )
        logger.info(f"Upserted batch of {len(rules)} rules")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        rule_type_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Find the most similar rules to a query embedding.

        Returns a list of dicts with keys:
            rule_id, document, metadata, distance
        """
        where = {"rule_type": rule_type_filter} if rule_type_filter else None
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        output = []
        for i, rule_id in enumerate(results["ids"][0]):
            output.append(
                {
                    "rule_id": rule_id,
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                }
            )
        return output

    def get_by_id(self, rule_id: str) -> Optional[dict]:
        """Retrieve a single rule by its ID."""
        result = self.collection.get(ids=[rule_id], include=["documents", "metadatas"])
        if not result["ids"]:
            return None
        return {
            "rule_id": result["ids"][0],
            "document": result["documents"][0],
            "metadata": result["metadatas"][0],
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self.collection.count()

    def list_rule_types(self) -> list[str]:
        """Return distinct rule types stored in the knowledge base."""
        results = self.collection.get(include=["metadatas"])
        types = {m.get("rule_type", "unknown") for m in results["metadatas"]}
        return sorted(types)

    def delete(self, rule_id: str):
        self.collection.delete(ids=[rule_id])

    def clear(self):
        """Wipe the entire knowledge base (use with caution)."""
        self.client.delete_collection(COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.warning("Knowledge base cleared")
