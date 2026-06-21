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

            rule_id = "{}_{}_{}_{}".format(
                raw.get('rule_type', 'unknown'),
                raw.get('pega_class', ''),
                raw.get('ruleset', ''),
                raw.get('rule_name') or rule_file.stem
            )
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
        to a raw PEGA rule dict. UI rules (Section/Harness) get a richer prompt.
        """
        rule_name = raw.get("rule_name", "Unknown")
        rule_type = raw.get("rule_type", "Unknown")
        pega_class = raw.get("pega_class", "")
        xml_snippet = raw.get("xml", "")[:1500]

        if rule_type in ("Section", "Harness"):
            prompt = self._ui_enrichment_prompt(raw)
        else:
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
            response_text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            enrichment = json.loads(response_text)
        except Exception as e:
            logger.warning(f"Enrichment failed for {rule_name}: {e}")
            enrichment = {"description": f"{rule_type}: {rule_name}", "business_context": ""}

        return {**raw, **enrichment}

    def _ui_enrichment_prompt(self, raw: dict) -> str:
        """Richer enrichment prompt for Section/Harness rules."""
        rule_name = raw.get("rule_name", "Unknown")
        rule_type = raw.get("rule_type", "Section")
        pega_class = raw.get("pega_class", "")
        ui = raw.get("ui_metadata", {})

        ui_summary = []
        if ui.get("template_type"):
            ui_summary.append(f"Template type: {ui['template_type']}")
        if ui.get("layout_types"):
            ui_summary.append(f"Layouts: {', '.join(ui['layout_types'])}")
        if ui.get("controls_used"):
            ui_summary.append(f"Controls: {', '.join(ui['controls_used'])}")
        if ui.get("data_sources"):
            ui_summary.append(f"Data sources: {', '.join(ui['data_sources'][:5])}")
        if ui.get("has_repeating"):
            ui_summary.append("Has repeating/list layout")
        if ui.get("has_actions"):
            ui_summary.append("Has action buttons")
        if ui.get("is_modal"):
            ui_summary.append("Rendered as modal/dialog")

        ui_text = "\n".join(ui_summary) if ui_summary else "(no UI metadata available)"

        return f"""You are a PEGA UI expert. Given this PEGA {rule_type} rule metadata, write:
1. A description (2-3 sentences) of what this UI rule displays and when a developer would use it
2. A business context sentence (what user role / process step uses this screen)
3. A "use_when" sentence — what requirement should trigger a developer to reuse or copy this pattern
4. A "layout_summary" — 1 sentence describing the visual layout pattern

Rule name: {rule_name}
Rule type: {rule_type}
PEGA class: {pega_class}
UI analysis:
{ui_text}

Respond in JSON only:
{{
  "description": "...",
  "business_context": "...",
  "use_when": "...",
  "layout_summary": "..."
}}"""

    def _embed_and_store(self, rules: list[dict]):
        """Embed a batch of enriched rules and upsert into vector store."""
        # Deduplicate within batch by ID
        seen_ids = set()
        deduped_rules = []
        for rule in rules:
            rid = "{}_{}_{}_{}".format(
                rule.get('rule_type', 'unknown'),
                rule.get('pega_class', ''),
                rule.get('ruleset', ''),
                rule.get('rule_name') or rule.get('id', 'unknown')
            )[:200]
            if rid not in seen_ids:
                seen_ids.add(rid)
                deduped_rules.append(rule)
        rules = deduped_rules
        embeddings = self.embedder.embed_batch(rules)
        records = []
        for rule, embedding in zip(rules, embeddings):
            rule_id = "{}_{}_{}_{}".format(
                rule.get('rule_type', 'unknown'),
                rule.get('pega_class', ''),
                rule.get('ruleset', ''),
                rule.get('rule_name') or rule.get('id', 'unknown')
            )
            rule_id = rule_id[:200]
            rule_type = rule.get("rule_type", "unknown")
            ui = rule.get("ui_metadata", {})

            metadata = {
                "rule_type":      rule_type,
                "pega_class":     rule.get("pega_class", ""),
                "app":            rule.get("app", ""),
                "dependencies":   json.dumps(rule.get("dependencies", [])),
                "properties":     json.dumps(rule.get("properties", [])[:20]),
            }

            # UI-specific metadata (searchable fields)
            if rule_type in ("Section", "Harness"):
                metadata["template_type"]  = ui.get("template_type", "")
                metadata["layout_types"]   = json.dumps(ui.get("layout_types", []))
                metadata["controls_used"]  = json.dumps(ui.get("controls_used", []))
                metadata["has_repeating"]  = str(ui.get("has_repeating", False))
                metadata["has_actions"]    = str(ui.get("has_actions", False))
                metadata["is_modal"]       = str(ui.get("is_modal", False))
                metadata["use_when"]       = rule.get("use_when", "")
                metadata["layout_summary"] = rule.get("layout_summary", "")

            # Document = the searchable text for semantic similarity
            doc_parts = [
                rule.get("description", ""),
                rule.get("business_context", ""),
            ]
            if rule_type in ("Section", "Harness"):
                doc_parts += [
                    rule.get("use_when", ""),
                    rule.get("layout_summary", ""),
                    f"layout: {' '.join(ui.get('layout_types', []))}",
                    f"controls: {' '.join(ui.get('controls_used', []))}",
                    f"template: {ui.get('template_type', '')}",
                ]
            document = " | ".join(p for p in doc_parts if p)

            records.append({
                "rule_id":   rule_id,
                "embedding": embedding,
                "metadata":  metadata,
                "document":  document,
            })
        self.store.upsert_batch(records)
        logger.info(f"Stored {len(records)} rules in knowledge base")
