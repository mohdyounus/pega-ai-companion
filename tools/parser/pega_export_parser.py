"""
pega_export_parser.py
Orchestrates the full PEGA JAR export → JSON rule files pipeline.

Flow:
  1. JarExtractor  → extracts .jar files to work directory
  2. ContentsParser → reads META-INF/contents.txt rule inventory
  3. BinParser     → enriches rules with data from .bin files
  4. Writes one JSON file per rule to output_dir (ready for learn phase)

Usage:
  python tools/run_extended.py parse --export-dir ./pega-export --output-dir ./workspaces/output
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from .jar_extractor import JarExtractor
from .contents_parser import ContentsParser
from .bin_parser import BinParser

logger = logging.getLogger(__name__)

# Rule types to skip (metadata-only, not useful for code generation)
SKIP_RULE_TYPES = {"RuleSet", "RuleSetVersion", "Product"}


class PegaExportParser:
    """
    Full pipeline: PEGA JAR export → structured JSON rule files.
    """

    def __init__(
        self,
        export_dir: str,
        output_dir: str = "./workspaces/output",
        work_dir: str = "./pega_work",
    ):
        self.export_dir = Path(export_dir)
        self.output_dir = Path(output_dir)
        self.work_dir = Path(work_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.extractor = JarExtractor(export_dir=str(export_dir), work_dir=str(work_dir))
        self.contents_parser = ContentsParser()
        self.bin_parser = BinParser()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self, skip_existing: bool = True, force_extract: bool = False) -> list[dict]:
        """
        Full parse pipeline. Returns list of all parsed rule dicts.

        Args:
            skip_existing:  Skip rules already saved as JSON in output_dir
            force_extract:  Re-extract JARs even if already extracted
        """
        # Step 1: Extract JARs
        logger.info(f"Step 1/3 — Extracting JARs from {self.export_dir}")
        extractions = self.extractor.extract_all(force=force_extract)

        if not extractions:
            raise RuntimeError(f"No JAR files found in {self.export_dir}")

        all_rules = []

        for extraction in extractions:
            jar_name = extraction["jar_path"].name
            manifest = extraction["manifest"]
            app_name = manifest.get("ArtifactName", jar_name)
            app_version = manifest.get("ArtifactVersion", "")

            logger.info(f"Processing: {jar_name} ({app_name} {app_version})")

            # Step 2: Parse contents.txt
            if not extraction["contents_txt"]:
                logger.warning(f"No contents.txt in {jar_name} — skipping")
                continue

            logger.info(f"Step 2/3 — Parsing rule inventory from {jar_name}")
            rules = self.contents_parser.parse(extraction["contents_txt"])

            # Filter out metadata-only rule types
            rules = [r for r in rules if r.get("rule_type") not in SKIP_RULE_TYPES]
            logger.info(f"Found {len(rules)} actionable rules in {jar_name}")

            # Step 3: Enrich from .bin files
            for bin_file in extraction["bin_files"]:
                if "Templates" in bin_file.name:
                    continue  # skip template .bin files
                logger.info(f"Step 3/3 — Enriching from {bin_file.name}")
                try:
                    rules = self.bin_parser.enrich_rules(rules, bin_file)
                except Exception as e:
                    logger.warning(f"Bin enrichment failed for {bin_file.name}: {e}")

            # Add app context
            for rule in rules:
                rule["app"] = app_name
                rule["app_version"] = app_version
                rule["source_jar"] = jar_name

            all_rules.extend(rules)

        # Step 4: Write JSON output files
        written = 0
        skipped = 0
        for rule in all_rules:
            out_path = self._rule_json_path(rule)
            if skip_existing and out_path.exists():
                skipped += 1
                continue
            self._write_rule_json(rule, out_path)
            written += 1

        logger.info(
            f"\n{'='*50}\n"
            f"Parse complete\n"
            f"  Total rules : {len(all_rules)}\n"
            f"  Written     : {written}\n"
            f"  Skipped     : {skipped} (already exist)\n"
            f"  Output dir  : {self.output_dir}\n"
            f"{'='*50}\n"
            f"Next step: python tools/run_extended.py learn --analysis-dir {self.output_dir}"
        )

        return all_rules

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rule_json_path(self, rule: dict) -> Path:
        """Generate a safe output filename for a rule JSON."""
        rule_type = rule.get("rule_type", "unknown").replace(" ", "_")
        pega_class = rule.get("pega_class", "").replace(" ", "_").replace("-", "_")
        rule_name = rule.get("rule_name", "unknown").replace(" ", "_").replace("-", "_")
        filename = f"{rule_type}__{pega_class}__{rule_name}.json".lower()
        return self.output_dir / filename

    def _write_rule_json(self, rule: dict, out_path: Path):
        """Write a rule dict to a JSON file."""
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rule, f, indent=2, default=str)

    def print_summary(self, rules: list[dict]):
        """Print a summary of parsed rules grouped by type."""
        from collections import Counter
        type_counts = Counter(r.get("rule_type", "unknown") for r in rules)
        print("\n=== Parsed Rule Summary ===")
        print(f"{'Rule Type':<30} {'Count':>6}")
        print("-" * 38)
        for rule_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"{rule_type:<30} {count:>6}")
        print(f"{'TOTAL':<30} {len(rules):>6}")
