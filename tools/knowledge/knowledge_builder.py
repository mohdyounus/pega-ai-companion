"""
knowledge_builder.py
Orchestrates the LEARN phase:
  1. Reads parsed PEGA rules from the existing recursive_analyser output
  2. Enriches each rule with LLM-generated description & business context (cheap Haiku model)
  3. Embeds each rule via EmbeddingEngine
  4. Stores in VectorStore (ChromaDB)

Run via:  python tools/run.py learn --export-dir ./pega-export
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Iterator

import anthropic

from .embeddings import EmbeddingEngine
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

# Use cheaper model for learn phase — reduces cost by ~12x vs Sonnet
LEARN_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 512  # short summaries only


class KnowledgeBuilder:
    """
    Builds the local knowledge base from existing PEGA analysis output.

    Input:  Directory of JSON rule files produced by recursive_analyser.py
    Output: Populated ChromaDB vector store ready for semantic search
    """

    def __init__(
        self,
        analysis_output_dir: str,
        knowledge_base_dir: str = "./knowledge_base",
        skip_existing: bool = True,
    ):
        self.analysis_dir = Path(analysis_output_dir)
        self.store = VectorStore(persist_dir=knowledge_base_dir)
        self.embedder = EmbeddingEngine(cache_dir=knowledge_base_dir)
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.skip_existing = skip_existing

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build(self, batch_size: int = 20):
        """
        Full learn pipeline. Processes all rule JSON files in analysis_output_dir.
        Resumes safely — skips rules already in the knowledge base if skip_existing=True.
        """
        rule_files = list(self.analysis_dir.glob("**/*.json"))
        logger.info(f"Found {len(rule_files)} rule files in {self.analysis_dir}")

        if not rule_files:
            logger.warning(
                "No JSON rule files found. Run 'python tools/run.py analyse' first."
            )
            return

        new_rules = []
        skipped = 0

        for rule_file in rule_files:
            raw = self._load_rule_file(rule_file)
            if raw is None:
                continue

            rule_id = raw.get("rule_name") or rule_file.stem
            if self.skip_existing and self.store.get_by_id(rule_id):
                skipped += 1
                continue

            enriched = self._enrich_rule(raw)
            new_rules.append(enriched)

            # Process in batches to avoid memory spikes
            if len(new_rules) >= batch_size:
                self._embed_and_store(new_rules)
                new_rules = []

        # Flush remainder
        if new_rules:
            self._embed_and_store(new_rules)

        logger.info(
            f"Learn phase complete — {len(rule_files) - skipped} new rules indexed, "
            f"{skipped} skipped (already in KB). Total KB size: {self.store.count()}"
        )

    def build_from_dict(self, rules: list[dict]):
        """
        Alternative entry: build directly from a list of rule dicts
        (useful when calling from recursive_analyser.py during analyse phase).
        """
        enriched = [self._enrich_rule(r) for r in rules]
        self._embed_and_store(enriched)

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _load_rule_file(self, path: Path) -> dict | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")
            return None

    def _enrich_rule(self, raw: dict) -> dict:
        """
        Use Claude Haiku to add a plain-English description and business context
        to a raw PEGA rule dict. This makes the embeddings semantically rich.
        """
        rule_name = raw.get("rule_name", "Unknown")
        rule_type = raw.get("rule_type", "Unknown")
        pega_class = raw.get("pega_class", "")
        xml_snippet = raw.get("xml", "")[:1500]  # cap XML to keep tokens low

        prompt = f"""You are a PEGA expert. Given this PEGA rule, write:
1. A 1-sentence plain-English description of what this rule does
2. A 1-sentence business context (why it exists / what business process it supports)

Rule name: {rule_name}
Rule type: {rule_type}
PEGA class: {pega_class}
XML snippet:
{xml_snippet}

Respond in JSON only:
{{"description": "...", "business_context": "..."}}"""

        try:
            response = self.client.messages.create(
                model=LEARN_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            enrichment = json.loads(response.content[0].text)
        except Exception as e:
            logger.warning(f"Enrichment failed for {rule_name}: {e}")
            enrichment = {"description": rule_name, "business_context": ""}

        return {**raw, **enrichment}

    def _embed_and_store(self, rules: list[dict]):
        """Embed a batch of enriched rules and upsert into vector store."""
        embeddings = self.embedder.embed_batch(rules)
        records = []
        for rule, embedding in zip(rules, embeddings):
            rule_id = rule.get("rule_name") or rule.get("id", "unknown")
            metadata = {
                "rule_type": rule.get("rule_type", "unknown"),
                "pega_class": rule.get("pega_class", ""),
                "app": rule.get("app", ""),
                "dependencies": json.dumps(rule.get("dependencies", [])),
                "properties": json.dumps(rule.get("properties", [])[:20]),
            }
            document = (
                f"{rule.get('description', '')} | {rule.get('business_context', '')}"
            )
            records.append(
                {
                    "rule_id": rule_id,
                    "embedding": embedding,
                    "metadata": metadata,
                    "document": document,
                }
            )
        self.store.upsert_batch(records)
        logger.info(f"Stored {len(records)} rules in knowledge base")
