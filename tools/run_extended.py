"""
run.py  —  PEGA AI Companion CLI
Extended version of the original run.py adding:
  learn     — build knowledge base from analysed rules
  generate  — generate new PEGA rules using the knowledge base
  package   — re-package a previous generation result

Original commands (validate-config, graph, analyse, aggregate) are preserved.

Usage:
  python tools/run.py learn --analysis-dir ./workspaces/output
  python tools/run.py generate --type Flow --name KYC-AddressVerify --desc "Verify address via API"
  python tools/run.py package --input ./generated/result.json
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Auto-load .env file if present (keeps API key out of shell history)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # dotenv optional — can still set env var manually

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pega-ai-companion")


# ──────────────────────────────────────────────
# Subcommand handlers
# ──────────────────────────────────────────────

def cmd_parse(args):
    """Parse a PEGA JAR export into JSON rule files (Step 0 — before learn)."""
    from parser import PegaExportParser
    from parser.section_parser import SectionParser

    export_dir = Path(args.export_dir)
    if not export_dir.exists():
        logger.error(f"Export directory not found: {export_dir}")
        logger.info("Place your PEGA exported .jar files in this directory.")
        sys.exit(1)

    logger.info(f"Parsing PEGA export from: {export_dir}")
    parser_obj = PegaExportParser(
        export_dir=str(export_dir),
        output_dir=args.output_dir,
        work_dir=args.work_dir,
    )
    rules = parser_obj.parse(
        skip_existing=not args.force,
        force_extract=args.force,
    )

    # Enrich Section/Harness rules with UI metadata
    ui_rules = [r for r in rules if r.get("rule_type") in ("Section", "Harness")]
    if ui_rules:
        logger.info(f"Enriching {len(ui_rules)} Section/Harness rules with UI metadata...")
        section_parser = SectionParser()
        # Collect all string snippets from bin_data fields for context
        all_strings = []
        for r in rules:
            bin_data = r.get("bin_data_strings", [])
            all_strings.extend(bin_data if isinstance(bin_data, list) else [str(bin_data)])
        rules = section_parser.enrich_ui_rules(rules, all_strings)
        # Re-write enriched UI rules to JSON
        import json as _json
        from pathlib import Path as _Path
        out = _Path(args.output_dir)
        for rule in ui_rules:
            rt = rule.get("rule_type", "unknown").replace(" ", "_")
            pc = rule.get("pega_class", "").replace(" ", "_").replace("-", "_")
            rn = rule.get("rule_name", "unknown").replace(" ", "_").replace("-", "_")
            fpath = out / f"{rt}__{pc}__{rn}.json".lower()
            with open(fpath, "w", encoding="utf-8") as f:
                _json.dump(rule, f, indent=2, default=str)
        logger.info(f"UI metadata written for {len(ui_rules)} Section/Harness rules")

    parser_obj.print_summary(rules)
    logger.info(f"Done! {len(rules)} rules written to {args.output_dir}")
    logger.info(f"Next step: python tools/run_extended.py learn --analysis-dir {args.output_dir}")


def cmd_learn(args):
    """Index existing PEGA analysis output into the vector knowledge base."""
    from knowledge import KnowledgeBuilder

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.exists():
        logger.error(f"Analysis directory not found: {analysis_dir}")
        logger.info("Run 'python tools/run.py analyse' first to generate rule analysis output.")
        sys.exit(1)

    logger.info(f"Starting LEARN phase from: {analysis_dir}")
    builder = KnowledgeBuilder(
        analysis_output_dir=str(analysis_dir),
        knowledge_base_dir=args.kb_dir,
        skip_existing=not args.force,
    )
    builder.build(batch_size=args.batch_size)
    logger.info("✅ Learn phase complete. Knowledge base ready for generation.")


def cmd_generate(args):
    """Generate new PEGA rules using the knowledge base."""
    from generator import RuleGenerator, PackageBuilder

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    logger.info(f"Generating {args.type}: {args.name}")
    generator = RuleGenerator(knowledge_base_dir=args.kb_dir)

    result = generator.generate(
        request=args.desc,
        rule_type=args.type,
        rule_name=args.name,
        target_class=args.pega_class or "",
        n_similar=args.n_similar,
    )

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"GENERATION COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Summary: {result['summary']}")
    logger.info(f"Rules generated: {len(result['rules'])}")
    logger.info(f"Tokens used: {result['token_usage']}")

    if result.get("review_checklist"):
        logger.info("\n📋 Review Checklist:")
        for item in result["review_checklist"]:
            logger.info(f"  • {item}")

    # Save result JSON
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{args.name}_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    logger.info(f"\nResult saved to: {result_path}")

    # Auto-package if requested
    if args.package:
        builder = PackageBuilder(output_dir=str(output_dir))
        zip_path = builder.build(result, package_name=args.name)
        logger.info(f"📦 Package ready: {zip_path}")
    else:
        # Save individual XML files for review
        builder = PackageBuilder(output_dir=str(output_dir))
        saved = builder.save_xml_files(result)
        logger.info(f"XML files saved for review:")
        for p in saved:
            logger.info(f"  {p}")
        logger.info(f"\nTo package for PEGA import, run:")
        logger.info(f"  python tools/run.py package --input {result_path}")


def cmd_package(args):
    """Package a previous generation result JSON into a PEGA-importable .zip."""
    from generator import PackageBuilder

    result_path = Path(args.input)
    if not result_path.exists():
        logger.error(f"Result file not found: {result_path}")
        sys.exit(1)

    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    output_dir = Path(args.output_dir)
    builder = PackageBuilder(output_dir=str(output_dir))
    zip_path = builder.build(
        result,
        package_name=args.package_name or result_path.stem,
        ruleset_name=args.ruleset_name,
        ruleset_version=args.ruleset_version,
    )
    logger.info(f"✅ Package ready for PEGA import: {zip_path}")


def cmd_kb_status(args):
    """Show knowledge base statistics."""
    from knowledge import VectorStore

    store = VectorStore(persist_dir=args.kb_dir)
    count = store.count()
    rule_types = store.list_rule_types()
    logger.info(f"\n{'='*40}")
    logger.info(f"Knowledge Base Status")
    logger.info(f"{'='*40}")
    logger.info(f"Location : {args.kb_dir}")
    logger.info(f"Total rules: {count}")
    logger.info(f"Rule types : {', '.join(rule_types) if rule_types else 'none'}")


def cmd_recommend(args):
    """Recommend a Section/Harness pattern from the knowledge base."""
    import os
    from knowledge import VectorStore, EmbeddingEngine

    requirement = args.requirement
    rule_type_filter = None if args.rule_type == "any" else args.rule_type
    top_n = args.top

    logger.info(f"Searching knowledge base for: {requirement}")

    store = VectorStore(persist_dir=args.kb_dir)
    embedder = EmbeddingEngine(cache_dir=args.kb_dir)

    # Embed the requirement query
    query_vec = list(embedder.embed_batch([{"description": requirement,
                                            "rule_name": "query",
                                            "rule_type": rule_type_filter or "Section"}]))[0]

    # Search with optional type filter
    where = {"rule_type": rule_type_filter} if rule_type_filter else None
    results = store.query(query_vec, n_results=top_n * 3, rule_type_filter=rule_type_filter)

    # Filter to UI types only if no specific type given
    if not rule_type_filter:
        results = [r for r in results if r.get("metadata", {}).get("rule_type") in ("Section", "Harness")]

    results = results[:top_n]

    if not results:
        logger.info("No matching sections found. Run 'learn' with your sections export first.")
        return

    # Build recommendation prompt for Claude
    context_blocks = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        context_blocks.append(
            f"Match {i}: {r.get('rule_id', 'unknown')}\n"
            f"  Type: {meta.get('rule_type')} | Class: {meta.get('pega_class')}\n"
            f"  Template: {meta.get('template_type', 'unknown')} | "
            f"Layouts: {meta.get('layout_types', '[]')} | "
            f"Controls: {meta.get('controls_used', '[]')}\n"
            f"  Description: {r.get('document', '')[:200]}\n"
            f"  Use when: {meta.get('use_when', '')}"
        )

    context_text = "\n\n".join(context_blocks)

    client = __import__("anthropic").Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = f"""You are a PEGA UI architect. A developer has this requirement:

"{requirement}"

Based on these matching sections from their existing codebase:

{context_text}

Provide:
1. Which existing section best matches their requirement (and why)
2. What configuration/layout pattern to use (table/repeating/flow/modal etc.)
3. What controls they will need
4. Whether to reuse an existing section or create a new one based on a pattern
5. Key things to configure (data source, visible-when, repeating group etc.)

Be specific and practical. Reference the actual rule names from their codebase."""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    recommendation = response.content[0].text

    logger.info(f"\n{'='*60}")
    logger.info(f"SECTION RECOMMENDATION")
    logger.info(f"{'='*60}")
    logger.info(f"Requirement: {requirement}")
    logger.info(f"\nTop {len(results)} matches from your codebase:")
    for r in results:
        meta = r.get("metadata", {})
        rid = r.get("rule_id", "unknown")
        rule_name = rid.split("_")[-1] if "_" in rid else rid
        logger.info(f"  - {rule_name} ({meta.get('rule_type')} | "
                    f"template: {meta.get('template_type', '?')} | "
                    f"class: {meta.get('pega_class', '?')})")
    logger.info(f"\nRecommendation:\n{recommendation}")
    logger.info(f"{'='*60}")


# ──────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pega-ai-companion",
        description="PEGA AI Companion — Learn from existing PEGA apps and generate new rules",
    )

    # Global option
    parser.add_argument(
        "--kb-dir",
        default="./knowledge_base",
        help="Path to knowledge base directory (default: ./knowledge_base)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── parse ──
    parse_p = subparsers.add_parser(
        "parse",
        help="Parse a PEGA JAR export into JSON rule files (run this before 'learn')",
    )
    parse_p.add_argument(
        "--export-dir",
        required=True,
        help="Directory containing your PEGA exported .jar files",
    )
    parse_p.add_argument(
        "--output-dir",
        default="./workspaces/output",
        help="Where to write JSON rule files (default: ./workspaces/output)",
    )
    parse_p.add_argument(
        "--work-dir",
        default="./pega_work",
        help="Temp directory for JAR extraction (default: ./pega_work)",
    )
    parse_p.add_argument(
        "--force", action="store_true", help="Re-extract and re-parse even if already done"
    )
    parse_p.set_defaults(func=cmd_parse)

    # ── learn ──
    learn_p = subparsers.add_parser(
        "learn",
        help="Index PEGA analysis output into the vector knowledge base",
    )
    learn_p.add_argument(
        "--analysis-dir",
        default="./workspaces/output",
        help="Directory containing JSON rule files from 'analyse' phase",
    )
    learn_p.add_argument(
        "--batch-size", type=int, default=20, help="Embedding batch size (default: 20)"
    )
    learn_p.add_argument(
        "--force", action="store_true", help="Re-index rules even if already in KB"
    )
    learn_p.set_defaults(func=cmd_learn)

    # ── generate ──
    gen_p = subparsers.add_parser(
        "generate",
        help="Generate new PEGA rules using the knowledge base",
    )
    gen_p.add_argument(
        "--type",
        required=True,
        choices=["Flow", "DataPage", "Activity", "Harness"],
        help="PEGA rule type to generate",
    )
    gen_p.add_argument("--name", required=True, help="Rule name, e.g. KYC-AddressVerify")
    gen_p.add_argument(
        "--desc", required=True, help="Natural language description of what the rule should do"
    )
    gen_p.add_argument(
        "--pega-class", default="", help="Target PEGA class (auto-inferred if not provided)"
    )
    gen_p.add_argument(
        "--n-similar", type=int, default=5, help="Number of similar rules to retrieve (default: 5)"
    )
    gen_p.add_argument(
        "--output-dir", default="./generated", help="Output directory (default: ./generated)"
    )
    gen_p.add_argument(
        "--package",
        action="store_true",
        help="Automatically package as PEGA .zip archive after generation",
    )
    gen_p.set_defaults(func=cmd_generate)

    # ── package ──
    pkg_p = subparsers.add_parser(
        "package",
        help="Package a generation result JSON into a PEGA-importable .zip",
    )
    pkg_p.add_argument("--input", required=True, help="Path to generation result JSON file")
    pkg_p.add_argument(
        "--output-dir", default="./generated", help="Output directory (default: ./generated)"
    )
    pkg_p.add_argument("--package-name", default="", help="Base name for the .zip file")
    pkg_p.add_argument(
        "--ruleset-name", default="AI-Generated", help="PEGA ruleset name (default: AI-Generated)"
    )
    pkg_p.add_argument(
        "--ruleset-version", default="01-01-01", help="Ruleset version (default: 01-01-01)"
    )
    pkg_p.set_defaults(func=cmd_package)

    # ── kb-status ──
    kb_p = subparsers.add_parser("kb-status", help="Show knowledge base statistics")
    kb_p.set_defaults(func=cmd_kb_status)

    # ── recommend ──
    rec_p = subparsers.add_parser(
        "recommend",
        help="Recommend a Section/Harness pattern from your knowledge base for a given requirement",
    )
    rec_p.add_argument(
        "--requirement", "-r", required=True,
        help='Natural language requirement, e.g. "display a list of work items with filters and pagination"',
    )
    rec_p.add_argument(
        "--rule-type", default="Section",
        choices=["Section", "Harness", "any"],
        help="Rule type to search (default: Section)",
    )
    rec_p.add_argument(
        "--top", type=int, default=3,
        help="Number of top matches to show (default: 3)",
    )
    rec_p.add_argument(
        "--kb-dir", default="./knowledge_base",
        help="Knowledge base directory (default: ./knowledge_base)",
    )
    rec_p.set_defaults(func=cmd_recommend)

    return parser


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure tools/ is on the path for relative imports
    sys.path.insert(0, str(Path(__file__).parent))

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
