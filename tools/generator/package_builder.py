"""
package_builder.py
Packages generated PEGA rule XML files into a .zip Rule Archive
that can be imported via PEGA's Deployment Manager or App Studio.

PEGA Rule Archive format:
  - Root: importzip.xml  (manifest listing all rules)
  - Each rule: data/rule-<ruleclass>-<rulename>.xml
"""

from __future__ import annotations
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

IMPORTZIP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<import version="1.0" generatedBy="PEGA-AI-Companion" generatedAt="{timestamp}">
  <rulesets>
    <ruleset name="{ruleset_name}" version="{ruleset_version}">
      {rule_entries}
    </ruleset>
  </rulesets>
</import>
"""

RULE_ENTRY_TEMPLATE = (
    '      <rule class="{rule_class}" name="{rule_name}" type="{rule_type}" '
    'file="{filename}" />'
)


class PackageBuilder:
    """
    Assembles generated PEGA XML rules into an importable .zip archive.
    """

    def __init__(self, output_dir: str = "./generated"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        generation_result: dict,
        package_name: str = "pega-ai-generated",
        ruleset_name: str = "AI-Generated",
        ruleset_version: str = "01-01-01",
    ) -> Path:
        """
        Build a .zip Rule Archive from a generation result dict
        (as returned by rule_generator.RuleGenerator.generate()).

        Args:
            generation_result: Output from RuleGenerator.generate()
            package_name:      Base name for the .zip file
            ruleset_name:      PEGA ruleset to assign imported rules to
            ruleset_version:   Ruleset version string (PEGA format: MM-mm-pp)

        Returns:
            Path to the created .zip file
        """
        rules = [r for r in generation_result.get("rules", []) if r.get("xml_valid", False)]

        if not rules:
            raise ValueError(
                "No valid XML rules to package. Check xml_valid flags in generation output."
            )

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_filename = self.output_dir / f"{package_name}_{timestamp}.zip"

        rule_entries = []
        file_contents: list[tuple[str, str]] = []  # (filename, xml_content)

        for rule in rules:
            rule_name = rule.get("rule_name", "Unknown")
            rule_type = rule.get("rule_type", "Unknown")
            pega_class = rule.get("pega_class", "")
            xml = rule.get("xml", "")

            # PEGA archive file naming convention
            type_prefix = self._rule_type_to_prefix(rule_type)
            safe_name = rule_name.replace(" ", "-").lower()
            safe_class = pega_class.replace(" ", "-").lower()
            filename = f"data/{type_prefix}-{safe_class}-{safe_name}.xml"

            rule_entries.append(
                RULE_ENTRY_TEMPLATE.format(
                    rule_class=pega_class,
                    rule_name=rule_name,
                    rule_type=rule_type,
                    filename=filename,
                )
            )
            file_contents.append((filename, xml))
            logger.info(f"Packaging rule: {rule_name} ({rule_type}) → {filename}")

        # Build importzip.xml manifest
        importzip_xml = IMPORTZIP_TEMPLATE.format(
            timestamp=datetime.utcnow().isoformat(),
            ruleset_name=ruleset_name,
            ruleset_version=ruleset_version,
            rule_entries="\n".join(rule_entries),
        )

        # Write zip
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("importzip.xml", importzip_xml)
            for filename, xml_content in file_contents:
                zf.writestr(filename, xml_content)

        logger.info(f"Package created: {zip_filename} ({len(rules)} rules)")
        self._write_summary(zip_filename, generation_result, rules)
        return zip_filename

    def save_xml_files(self, generation_result: dict) -> list[Path]:
        """
        Alternative to zip packaging — save each rule as a standalone XML file.
        Useful for manual review before packaging.
        """
        rules = generation_result.get("rules", [])
        saved = []
        for rule in rules:
            rule_name = rule.get("rule_name", "unknown")
            xml = rule.get("xml", "")
            if not xml:
                continue
            out_path = self.output_dir / f"{rule_name}.xml"
            out_path.write_text(xml, encoding="utf-8")
            saved.append(out_path)
            logger.info(f"Saved: {out_path}")
        return saved

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_type_to_prefix(rule_type: str) -> str:
        mapping = {
            "Flow": "rule-obj-flow",
            "DataPage": "rule-declare-pages",
            "Activity": "rule-obj-activity",
            "Harness": "rule-html-harness",
        }
        return mapping.get(rule_type, "rule-unknown")

    def _write_summary(self, zip_path: Path, generation_result: dict, rules: list[dict]):
        """Write a human-readable summary file alongside the zip."""
        summary_path = zip_path.with_suffix(".md")
        lines = [
            f"# PEGA AI Companion — Generation Summary",
            f"",
            f"**Generated**: {datetime.utcnow().isoformat()} UTC",
            f"**Package**: {zip_path.name}",
            f"**Rules**: {len(rules)}",
            f"",
            f"## Summary",
            generation_result.get("summary", ""),
            f"",
            f"## Generated Rules",
        ]
        for rule in rules:
            lines.append(f"- **{rule.get('rule_name')}** ({rule.get('rule_type')}) — {rule.get('description', '')}")
            if rule.get("notes"):
                lines.append(f"  - ⚠️ Notes: {rule['notes']}")

        checklist = generation_result.get("review_checklist", [])
        if checklist:
            lines += ["", "## Review Checklist", "Before importing into PEGA, verify:"]
            for item in checklist:
                lines.append(f"- [ ] {item}")

        token_usage = generation_result.get("token_usage", {})
        if token_usage:
            lines += [
                "",
                "## Token Usage",
                f"- Input: {token_usage.get('input_tokens', 0):,}",
                f"- Output: {token_usage.get('output_tokens', 0):,}",
            ]

        lines += [
            "",
            "## Similar Rules Used as Context",
        ]
        for rid in generation_result.get("similar_rules_used", []):
            lines.append(f"- {rid}")

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Summary written: {summary_path}")
