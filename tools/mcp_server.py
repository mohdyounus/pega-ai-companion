"""
mcp_server.py - PEGA Developer Copilot MCP Server
Exposes wiki agent and PEGA knowledge base as MCP tools for VS Code Copilot Chat.

Configure in VS Code user mcp.json - see HANDOVER.md.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ADO_ORG     = os.environ.get("AZURE_DEVOPS_ORG_URL", "https://dev.azure.com/nztasd")
ADO_PROJECT = os.environ.get("AZURE_DEVOPS_PROJECT", "SharedDelivery")
ADO_WIKI_ID = os.environ.get("AZURE_DEVOPS_WIKI_ID", "SharedDelivery.wiki")
ADO_PAT     = os.environ.get("AZURE_DEVOPS_PAT", "")
KB_DIR      = str(Path(__file__).parent.parent / "knowledge_base")

mcp = FastMCP("pega-copilot")


@mcp.tool()
def generate_wiki_doc(
    instruction: str,
    doc_type: str = "hld",
    page_path: str = "",
    push_to_wiki: bool = False,
    author: str = "PEGA LSA",
) -> str:
    """
    Generate a professional PEGA LSA design document (HLD, TDD, or ADR)
    with Mermaid diagrams, case design, data model, integration sequences,
    and cross-links to related Azure DevOps wiki pages.

    Args:
        instruction: What to document. E.g. 'Create a HLD for SCT DL9 integration with DLR API'
        doc_type: hld, tdd, or adr
        page_path: Wiki page path (auto-generated if blank)
        push_to_wiki: Set True to publish directly to Azure DevOps Wiki
        author: Author name for document header
    """
    if not ANTHROPIC_API_KEY:
        return "ERROR: ANTHROPIC_API_KEY not set in .env"
    if not ADO_PAT:
        return "ERROR: AZURE_DEVOPS_PAT not set in .env"

    from wiki.wiki_agent import WikiAgent
    from wiki.wiki_writer import WikiWriter

    agent = WikiAgent(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT, ANTHROPIC_API_KEY, KB_DIR)
    result = agent.generate(instruction, page_path or None, author)

    markdown  = result["markdown"]
    final_path = result["page_path"]
    related   = result["related_pages"]

    output = f"## Generated {result['doc_type'].upper()}\n"
    output += f"**Suggested wiki path:** `{final_path}`\n\n"

    if related:
        names = ", ".join(p["path"].split("/")[-1] for p in related)
        output += f"**Related pages linked:** {names}\n\n"

    if push_to_wiki:
        writer = WikiWriter(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT)
        writer.create_or_update(final_path, markdown)
        output += f"**Published to Wiki:** {final_path}\n\n"
    else:
        output += "_Not pushed yet. Set push_to_wiki=True to publish, or open http://localhost:8000 > Wiki Agent tab._\n\n"

    return output + "---\n\n" + markdown


@mcp.tool()
def recommend_pega_section(requirement: str, rule_type: str = "Section") -> str:
    """
    Search the RMS PEGA knowledge base (669 indexed rules) to find existing
    sections, harnesses, or UI patterns that best match a requirement.

    Args:
        requirement: UI/UX requirement. E.g. 'list of occurrences with search filters'
        rule_type: Section, Harness, or Any
    """
    if not ANTHROPIC_API_KEY:
        return "ERROR: ANTHROPIC_API_KEY not set"

    from knowledge.vector_store import VectorStore
    from knowledge.embeddings import EmbeddingEngine
    import anthropic

    store    = VectorStore(persist_dir=KB_DIR)
    embedder = EmbeddingEngine(cache_dir=KB_DIR)
    vec      = list(embedder.embed_batch([{"description": requirement, "rule_name": "q", "rule_type": ""}]))[0]
    rt_filter = None if rule_type == "Any" else rule_type
    results  = store.query(vec, n_results=5, rule_type_filter=rt_filter)

    if not results:
        return "No matching rules found in knowledge base."

    lines = []
    for r in results:
        meta  = r.get("metadata", {})
        rid   = r.get("rule_id", "")
        name  = rid.split("_")[-1] if "_" in rid else rid
        lines.append(f"- `{name}` ({meta.get('rule_type','?')} on {meta.get('pega_class','?')}): {r.get('document','')[:200]}")

    rag_context = "\n".join(lines)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        system="You are a PEGA UI architect. Recommend which existing section/harness to reuse or base a new one on. Reference actual rule names. Include layout type, controls, and data source.",
        messages=[{"role": "user", "content": f"Requirement: {requirement}\n\nMatching rules:\n{rag_context}"}]
    )
    return resp.content[0].text


@mcp.tool()
def ask_pega_copilot(
    question: str,
    rule_name: str = "",
    rule_class: str = "",
    rule_set: str = "",
) -> str:
    """
    Ask the PEGA Developer Copilot anything about PEGA development.
    Uses RAG over 669 RMS rules. Supports generating rule specs, debugging,
    reviewing best practices, writing test cases, and mentoring.

    Args:
        question: Your question or instruction. E.g. 'generate an Activity to validate participant licence'
        rule_name: Current rule name (optional context)
        rule_class: Current rule class (optional context)
        rule_set: Current ruleset (optional context)
    """
    if not ANTHROPIC_API_KEY:
        return "ERROR: ANTHROPIC_API_KEY not set"

    rag_context = ""
    try:
        from knowledge.vector_store import VectorStore
        from knowledge.embeddings import EmbeddingEngine
        store    = VectorStore(persist_dir=KB_DIR)
        embedder = EmbeddingEngine(cache_dir=KB_DIR)
        vec      = list(embedder.embed_batch([{"description": question, "rule_name": "q", "rule_type": ""}]))[0]
        results  = store.query(vec, n_results=4)
        if results:
            lines = ["**Relevant rules from RMS codebase:**"]
            for r in results:
                meta  = r.get("metadata", {})
                rid   = r.get("rule_id", "")
                rname = rid.split("_")[-1] if "_" in rid else rid
                lines.append(f"- `{rname}` ({meta.get('rule_type','?')} on {meta.get('pega_class','?')}): {r.get('document','')[:150]}")
            rag_context = "\n".join(lines)
    except Exception:
        pass

    ctx_parts = []
    if rule_name:  ctx_parts.append(f"Rule: {rule_name}")
    if rule_class: ctx_parts.append(f"Class: {rule_class}")
    if rule_set:   ctx_parts.append(f"RuleSet: {rule_set}")
    context_str = " | ".join(ctx_parts) if ctx_parts else "No specific rule context"

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        system=f"You are a PEGA Developer Copilot — expert in PEGA 8.x (Activities, Flows, Sections, Data Pages, Correspondence). Current context: {context_str}",
        messages=[{"role": "user", "content": f"{question}\n\n{rag_context}"}]
    )
    return resp.content[0].text


@mcp.tool()
def list_wiki_pages(filter: str = "") -> str:
    """
    List all pages in the Azure DevOps Wiki (SharedDelivery.wiki).
    Use to find page paths before reading or updating.

    Args:
        filter: Optional keyword to filter pages (e.g. 'PEGA', 'Railway', 'SCT')
    """
    if not ADO_PAT:
        return "ERROR: AZURE_DEVOPS_PAT not set"

    from wiki.wiki_reader import WikiReader
    reader = WikiReader(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT)
    pages  = reader.list_pages()
    if filter:
        pages = [p for p in pages if filter.lower() in p.lower()]

    return f"**{len(pages)} pages** in SharedDelivery.wiki:\n\n" + "\n".join(pages)


if __name__ == "__main__":
    mcp.run(transport="stdio")
