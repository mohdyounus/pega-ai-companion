"""
wiki_agent.py
Core orchestration agent for PEGA LSA wiki documentation.

Flow:
  1. Parse instruction → extract doc_type, feature name, keywords
  2. Search existing wiki pages for related content + links
  3. Query RAG knowledge base for PEGA rule context
  4. Fill document template with Claude (structured, Mermaid diagrams)
  5. Inject cross-links to related wiki pages
  6. Return preview markdown (caller decides whether to push)
"""
from __future__ import annotations
import os
import re
import logging
from pathlib import Path

import anthropic

from wiki.wiki_reader import WikiReader
from wiki.templates import get_template

logger = logging.getLogger("wiki-agent")

# Keywords that signal each doc section to look for in existing wiki pages
SECTION_KEYWORDS = {
    "integration": ["API", "integration", "connect", "REST", "service"],
    "data_model": ["data model", "properties", "class", "schema"],
    "case": ["case design", "case type", "lifecycle", "flow"],
    "security": ["security", "access", "role", "IAM"],
}

DOC_TYPE_HINTS = {
    "hld": ["high level", "hld", "architecture", "design document"],
    "tdd": ["technical design", "tdd", "detailed design", "technical spec"],
    "adr": ["decision", "adr", "architectural decision"],
}


class WikiAgent:
    def __init__(
        self,
        org: str,
        project: str,
        wiki_id: str,
        pat: str,
        api_key: str,
        kb_dir: str | None = None,
    ):
        self.reader = WikiReader(org, project, wiki_id, pat)
        self.api_key = api_key
        self.kb_dir = kb_dir
        self._store = None
        self._embedder = None

    # ── RAG helpers ───────────────────────────────────────────────────────────
    def _get_rag_context(self, query: str) -> str:
        if not self.kb_dir:
            return ""
        try:
            if self._store is None:
                from knowledge.vector_store import VectorStore
                from knowledge.embeddings import EmbeddingEngine
                self._store = VectorStore(persist_dir=self.kb_dir)
                self._embedder = EmbeddingEngine(cache_dir=self.kb_dir)
            vec = list(self._embedder.embed_batch([{"description": query, "rule_name": "q", "rule_type": ""}]))[0]
            results = self._store.query(vec, n_results=5)
            if not results:
                return ""
            lines = ["**Relevant PEGA rules from your codebase:**"]
            for r in results:
                meta = r.get("metadata", {})
                rid = r.get("rule_id", "")
                name = rid.split("_")[-1] if "_" in rid else rid
                lines.append(f"- `{name}` ({meta.get('rule_type','?')} on {meta.get('pega_class','?')}): "
                              f"{r.get('document','')[:150]}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"RAG lookup failed: {e}")
            return ""

    # ── Doc type detection ────────────────────────────────────────────────────
    def _detect_doc_type(self, instruction: str) -> str:
        lower = instruction.lower()
        for doc_type, hints in DOC_TYPE_HINTS.items():
            if any(h in lower for h in hints):
                return doc_type
        return "hld"

    # ── Wiki cross-link builder ───────────────────────────────────────────────
    def _find_related_pages(self, instruction: str) -> list[dict]:
        words = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b', instruction)
        words += re.findall(r'\b(?:PEGA|API|DLR|SCT|HVP|RMS|MVR)\b', instruction)
        keywords = list(set(words))[:6]
        related = self.reader.get_related_pages(keywords)
        # deduplicate by path
        seen = set()
        unique = []
        for r in related:
            if r["path"] not in seen:
                seen.add(r["path"])
                unique.append(r)
        return unique[:5]

    def _build_links_section(self, related: list[dict]) -> str:
        if not related:
            return ""
        lines = []
        for r in related:
            name = r["path"].split("/")[-1]
            lines.append(f"- [{name}]({r['link']})")
        return "\n".join(lines)

    # ── Main generation ───────────────────────────────────────────────────────
    def generate(self, instruction: str, page_path: str | None = None, author: str = "PEGA LSA") -> dict:
        """
        Generate wiki document markdown from a natural language instruction.

        Returns:
            {
              "markdown": str,        # Full generated markdown
              "page_path": str,       # Suggested wiki page path
              "doc_type": str,        # hld / tdd / adr
              "related_pages": list,  # Related wiki pages found
            }
        """
        doc_type = self._detect_doc_type(instruction)

        # Extract feature name from instruction
        feature_name = self._extract_feature_name(instruction)

        # Suggest page path if not provided
        if not page_path:
            safe = re.sub(r'[^\w\s-]', '', feature_name).strip().replace(" ", "-")
            page_path = f"/Home - Waka Kotahi wiki/{safe}/{safe}-{doc_type.upper()}"

        # Get template scaffold
        template = get_template(doc_type, feature_name, author)

        # Find related wiki pages for cross-links
        related = self._find_related_pages(instruction)
        links_md = self._build_links_section(related)

        # Get RAG context from PEGA knowledge base
        rag_context = self._get_rag_context(instruction)

        # Build Claude prompt
        system = f"""You are a PEGA Lead System Architect (LSA) documentation expert.
You write professional, complete Azure DevOps Wiki pages in markdown.

Rules:
- Use Mermaid diagrams for architecture, sequence, ER, and state diagrams
- Reference actual PEGA rule names (Activities, Data Pages, Sections, Flows) from the codebase context provided
- Use PEGA terminology: Case Type, Stage, Step, Data Page, Activity, Section, Harness, Correspondence
- Every section must have real content — no placeholder text left empty
- Tables must be fully filled in
- Link to related documents using the links provided
- Output ONLY the final markdown document — no explanations before or after

Document type: {doc_type.upper()}
Feature: {feature_name}
Author: {author}
"""

        user_msg = f"""Instruction from LSA: {instruction}

Template to fill in (expand every section with real, specific content):
{template}

Cross-links to related documents (use these in Section 9 - Related Documents):
{links_md if links_md else "No related pages found yet."}

{rag_context}

Generate the complete, fully-filled {doc_type.upper()} document now. 
Every section must have real content. Include at least 2 Mermaid diagrams.
Replace ALL placeholder text with actual specific content based on the feature described.
"""

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        markdown = response.content[0].text

        # Inject related links into Related Documents section if not already there
        if links_md and "Related Documents" in markdown and links_md[:30] not in markdown:
            markdown = markdown.replace(
                "## 9. Related Documents\n",
                f"## 9. Related Documents\n\n{links_md}\n"
            )

        return {
            "markdown": markdown,
            "page_path": page_path,
            "doc_type": doc_type,
            "related_pages": related,
        }

    def _extract_feature_name(self, instruction: str) -> str:
        """Extract a clean feature name from the instruction."""
        # Remove common instruction words
        cleaned = re.sub(
            r'^(create|generate|write|make|build|update|draft)\s+(a|an|the)?\s*'
            r'(hld|high level design|tdd|technical design|adr|design document|wiki page|document|doc)\s+(for|of|on|about)?\s*',
            '', instruction, flags=re.IGNORECASE
        ).strip()
        # Title case, max 60 chars
        return cleaned[:60].title() if cleaned else "New Feature"
