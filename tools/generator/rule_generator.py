"""
rule_generator.py
Core GENERATE phase engine.

1. Embeds the user's request
2. Retrieves the most similar existing rules from the knowledge base (RAG)
3. Builds Agent 10 prompt with retrieved context + learned conventions
4. Calls Claude Sonnet to generate new PEGA rule XML
5. Returns structured output for package_builder.py
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path

import anthropic

from ..knowledge.embeddings import EmbeddingEngine
from ..knowledge.vector_store import VectorStore
from .xml_formatter import XMLFormatter

logger = logging.getLogger(__name__)

GENERATE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4000
AGENT10_PROMPT_PATH = Path(__file__).parent.parent.parent / "agents" / "10_generator" / "system-prompt.md"

RULE_TYPES = ["Flow", "DataPage", "Activity", "Harness"]


class RuleGenerator:
    """
    Generates new PEGA rules grounded in the existing codebase knowledge base.
    """

    def __init__(self, knowledge_base_dir: str = "./knowledge_base"):
        self.store = VectorStore(persist_dir=knowledge_base_dir)
        self.embedder = EmbeddingEngine(cache_dir=knowledge_base_dir)
        self.formatter = XMLFormatter()
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.system_prompt_template = self._load_agent10_prompt()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        request: str,
        rule_type: str,
        rule_name: str,
        target_class: str = "",
        n_similar: int = 5,
    ) -> dict:
        """
        Generate a new PEGA rule from a natural language request.

        Args:
            request:      Natural language description, e.g. "Verify customer address using API"
            rule_type:    One of Flow, DataPage, Activity, Harness
            rule_name:    Desired PEGA rule name, e.g. KYC-AddressVerify
            target_class: PEGA class name, e.g. Work-KYC (auto-inferred if empty)
            n_similar:    Number of similar existing rules to retrieve for context

        Returns:
            Dict with keys: rules (list), summary, review_checklist, token_usage
        """
        if rule_type not in RULE_TYPES:
            raise ValueError(f"rule_type must be one of {RULE_TYPES}")

        if self.store.count() == 0:
            raise RuntimeError(
                "Knowledge base is empty. Run 'python tools/run.py learn' first."
            )

        logger.info(f"Generating {rule_type}: {rule_name}")

        # Step 1: Semantic search for similar rules
        query_text = f"{rule_type} {rule_name} {request}"
        query_embedding = self.embedder.embed_text(query_text)
        similar_rules = self.store.query(
            query_embedding, n_results=n_similar, rule_type_filter=rule_type
        )

        # Fallback: if no rules of same type, query without type filter
        if not similar_rules:
            similar_rules = self.store.query(query_embedding, n_results=n_similar)

        logger.info(f"Retrieved {len(similar_rules)} similar rules from knowledge base")

        # Step 2: Infer target_class from similar rules if not provided
        if not target_class and similar_rules:
            target_class = similar_rules[0]["metadata"].get("pega_class", "")

        # Step 3: Build context strings for Agent 10
        similar_rules_context = self._format_similar_rules(similar_rules)
        learned_conventions = self._extract_conventions(similar_rules)

        # Step 4: Build system prompt
        system_prompt = self.system_prompt_template.format(
            similar_rules_context=similar_rules_context,
            learned_conventions=learned_conventions,
            user_request=request,
            rule_type=rule_type,
            target_class=target_class,
        )

        # Step 5: Call Claude Sonnet
        response = self.client.messages.create(
            model=GENERATE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate a PEGA {rule_type} rule named '{rule_name}' "
                        f"for class '{target_class}' that: {request}"
                    ),
                }
            ],
            system=system_prompt,
        )

        raw_text = response.content[0].text
        token_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        # Step 6: Parse and validate XML
        llm_json = self.formatter.extract_json_from_llm_response(raw_text)
        validated_rules = self.formatter.render_from_llm_output(llm_json)

        return {
            "rules": validated_rules,
            "summary": llm_json.get("summary", ""),
            "review_checklist": llm_json.get("review_checklist", []),
            "similar_rules_used": [r["rule_id"] for r in similar_rules],
            "token_usage": token_usage,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_similar_rules(self, similar_rules: list[dict]) -> str:
        """Format retrieved rules as rich context for the Agent 10 prompt."""
        if not similar_rules:
            return "No similar rules found in knowledge base."

        lines = []
        for i, rule in enumerate(similar_rules, 1):
            meta = rule["metadata"]
            lines.append(f"--- Similar Rule {i} ---")
            lines.append(f"Rule ID: {rule['rule_id']}")
            lines.append(f"Type: {meta.get('rule_type', 'unknown')}")
            lines.append(f"Class: {meta.get('pega_class', '')}")
            lines.append(f"App: {meta.get('app', '')}")
            lines.append(f"Description: {rule['document']}")
            deps = json.loads(meta.get("dependencies", "[]"))
            if deps:
                lines.append(f"Dependencies: {', '.join(deps)}")
            props = json.loads(meta.get("properties", "[]"))
            if props:
                lines.append(f"Key Properties: {', '.join(props[:8])}")
            lines.append(f"Similarity score: {1 - rule['distance']:.2f}")
            lines.append("")
        return "\n".join(lines)

    def _extract_conventions(self, similar_rules: list[dict]) -> str:
        """
        Derive naming conventions and patterns from the retrieved similar rules.
        This helps the AI generate code that fits the team's style.
        """
        if not similar_rules:
            return "No conventions available — knowledge base may be empty."

        classes = [r["metadata"].get("pega_class", "") for r in similar_rules if r["metadata"].get("pega_class")]
        apps = [r["metadata"].get("app", "") for r in similar_rules if r["metadata"].get("app")]
        rule_ids = [r["rule_id"] for r in similar_rules]

        # Infer naming prefix from existing rule names
        prefixes = set()
        for rid in rule_ids:
            parts = rid.split("-")
            if parts:
                prefixes.add(parts[0])

        lines = [
            f"Observed naming prefixes: {', '.join(sorted(prefixes))}",
            f"Primary PEGA classes: {', '.join(set(classes))}",
            f"Applications: {', '.join(set(apps))}",
            "Convention: Follow the same prefix and class structure as the rules above.",
            "Convention: Reuse existing data pages and activities — don't create new ones unless essential.",
        ]
        return "\n".join(lines)

    def _load_agent10_prompt(self) -> str:
        if AGENT10_PROMPT_PATH.exists():
            return AGENT10_PROMPT_PATH.read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"Agent 10 prompt not found at {AGENT10_PROMPT_PATH}. "
            "Ensure the agents/10_generator/system-prompt.md file exists."
        )
