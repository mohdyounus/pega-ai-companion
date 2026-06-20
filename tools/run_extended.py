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
    parser_obj.print_summary(rules)
    logger.info(f"\n✅ Done! {len(rules)} rules written to {args.output_dir}")
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
