"""
package_builder.py
Packages generated PEGA rule XML files into a review bundle (.zip).

NOTE: PEGA's Application Import Wizard only accepts its own binary export
format (Java-serialized .bin files in a JAR). Direct XML import is NOT
supported via the Import Wizard. Instead, use the generated HTML guide
to manually create the rule in PEGA Designer Studio.

Package contents:
  - <RuleName>.xml          -- clipboard-ready rule XML (blueprint)
  - <RuleName>_guide.html   -- step-by-step creation guide in PEGA
  - README.txt              -- import instructions
"""

from __future__ import annotations
import logging
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RULE_TYPE_TO_PEGA_MENU = {
    "Activity": "Technical > Activity",
    "Flow": "Process > Flow",
    "DataPage": "Data Model > Data Page",
    "Harness": "User Interface > Harness",
}

README_TEMPLATE = """PEGA AI Companion -- Generated Rule Package
===========================================
Generated: {timestamp}
Package:   {package_name}
Rules:     {rule_count}

HOW TO USE THIS PACKAGE
------------------------
PEGA's Application Import Wizard requires binary .jar archives with Java-
serialized rule data. This package cannot be imported via the wizard.

RECOMMENDED: Open {guide_file} in a browser for a step-by-step guide.

METHOD 1 -- Manual creation in Designer Studio (recommended):
  1. Open PEGA Designer Studio
  2. Click [Create] -> {menu_path}
  3. Use the XML file and HTML guide as your blueprint
  4. Fill in each field, then Save and Check In

METHOD 2 -- Clipboard XML paste (advanced, PEGA 8+):
  1. Create the rule shell manually (name + class only)
  2. In Designer Studio: Help > Clipboard Viewer (F11)
  3. Navigate to the rule page in the tree
  4. Use "Import from XML" to paste properties from the XML file

FILES IN THIS PACKAGE
---------------------
{file_list}

REVIEW CHECKLIST
----------------
{checklist}
"""


class PackageBuilder:
    """Assembles generated PEGA rules into a review bundle (.zip)."""

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
        rules = [r for r in generation_result.get("rules", []) if r.get("xml_valid", False)]
        if not rules:
            raise ValueError(
                "No valid XML rules to package. Check xml_valid flags in generation output."
            )

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_filename = self.output_dir / f"{package_name}_{timestamp}.zip"

        all_files: list[tuple[str, str]] = []
        file_list_lines: list[str] = []

        for rule in rules:
            rule_name = rule.get("rule_name", "Unknown")
            rule_type = rule.get("rule_type", "Unknown")
            xml = rule.get("xml", "")

            xml_filename = f"{rule_name}.xml"
            guide_filename = f"{rule_name}_guide.html"

            all_files.append((xml_filename, xml))
            all_files.append((guide_filename, self._build_guide(rule, ruleset_name, ruleset_version, generation_result)))

            file_list_lines.append(f"  {xml_filename}  -- rule XML blueprint")
            file_list_lines.append(f"  {guide_filename} -- step-by-step guide (open in browser)")
            logger.info(f"Packaging rule: {rule_name} ({rule_type}) -> {xml_filename}")

        first_rule = rules[0]
        menu_path = RULE_TYPE_TO_PEGA_MENU.get(first_rule.get("rule_type", ""), "Technical > Activity")
        checklist = generation_result.get("review_checklist", [])
        checklist_text = "\n".join(f"  - {item}" for item in checklist) if checklist else "  (none)"
        guide_file = f"{first_rule.get('rule_name', 'rule')}_guide.html"

        readme = README_TEMPLATE.format(
            timestamp=datetime.utcnow().isoformat(),
            package_name=zip_filename.name,
            rule_count=len(rules),
            menu_path=menu_path,
            guide_file=guide_file,
            file_list="\n".join(file_list_lines),
            checklist=checklist_text,
        )
        all_files.append(("README.txt", readme))

        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in all_files:
                zf.writestr(filename, content)

        logger.info(f"Package created: {zip_filename} ({len(rules)} rules)")
        self._write_summary(zip_filename, generation_result, rules)
        return zip_filename

    def save_xml_files(self, generation_result: dict) -> list[Path]:
        """Save each rule as a standalone XML file for manual review."""
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

    def _build_guide(self, rule: dict, ruleset_name: str, ruleset_version: str, result: dict) -> str:
        rule_name = rule.get("rule_name", "")
        rule_type = rule.get("rule_type", "Activity")
        pega_class = rule.get("pega_class", "")
        description = rule.get("description", "")
        menu_path = RULE_TYPE_TO_PEGA_MENU.get(rule_type, "Technical > Activity")
        summary = result.get("summary", "")
        checklist = result.get("review_checklist", [])
        checklist_html = "".join(f"<li>{item}</li>" for item in checklist)

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>PEGA Creation Guide -- {rule_name}</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px}}
  h1{{color:#003366}}h2{{color:#0066cc;border-bottom:1px solid #ccc}}
  .step{{background:#f5f9ff;border-left:4px solid #0066cc;padding:12px 16px;margin:10px 0}}
  .field{{display:flex;gap:16px;margin:6px 0}}
  .label{{font-weight:bold;min-width:180px;color:#444}}
  .value{{font-family:monospace;background:#eee;padding:2px 6px;border-radius:3px}}
  .warn{{background:#fff8e1;border-left:4px solid #ffc107;padding:12px;margin:12px 0}}
  ol li{{margin:8px 0}}
</style>
</head><body>
<h1>PEGA Rule Creation Guide: {rule_name}</h1>
<div class="warn">
  <strong>AI-Generated Rule</strong> -- Review all details before saving to PEGA.
  The Application Import Wizard cannot import this file (it needs binary .jar format).
  Follow the steps below to create the rule manually.
</div>

<h2>Rule Details</h2>
<div class="field"><span class="label">Rule Type:</span><span class="value">{rule_type}</span></div>
<div class="field"><span class="label">Rule Name:</span><span class="value">{rule_name}</span></div>
<div class="field"><span class="label">Apply to Class:</span><span class="value">{pega_class}</span></div>
<div class="field"><span class="label">RuleSet:</span><span class="value">{ruleset_name} {ruleset_version}</span></div>
<div class="field"><span class="label">Description:</span><span class="value">{description[:120]}</span></div>

<h2>Steps to Create in PEGA Designer Studio</h2>
<ol>
  <li class="step">Open <strong>PEGA Designer Studio</strong></li>
  <li class="step">Click <strong>+ Create</strong> &rarr; <strong>{menu_path}</strong></li>
  <li class="step">Fill in the New Rule form:
    <br>&bull; <strong>Label:</strong> {description[:80]}
    <br>&bull; <strong>Apply to (Class):</strong> <code>{pega_class}</code>
    <br>&bull; <strong>Add to ruleset:</strong> <code>{ruleset_name}</code> version <code>{ruleset_version}</code>
    <br>&bull; Click <strong>[Create and Open]</strong>
  </li>
  <li class="step">Open <code>{rule_name}.xml</code> from this package as your blueprint -- add each step/property to the rule form</li>
  <li class="step">Click <strong>[Save]</strong> then <strong>[Check In]</strong></li>
  <li class="step">Go through the Review Checklist below before activating</li>
</ol>

<h2>What the AI Generated</h2>
<p>{summary}</p>

<h2>Review Checklist</h2>
<ul>{checklist_html}</ul>

<h2>Reference XML</h2>
<p>See <code>{rule_name}.xml</code> in this package for the full rule XML.</p>
<hr><p style="color:#999;font-size:12px">Generated by PEGA AI Companion -- {datetime.utcnow().isoformat()} UTC</p>
</body></html>"""

    def _write_summary(self, zip_path: Path, generation_result: dict, rules: list[dict]):
        summary_path = zip_path.with_suffix(".md")
        lines = [
            "# PEGA AI Companion -- Generation Summary",
            "",
            f"**Generated**: {datetime.utcnow().isoformat()} UTC",
            f"**Package**: {zip_path.name}",
            f"**Rules**: {len(rules)}",
            "",
            "> **Import note**: PEGA Import Wizard needs binary .jar format.",
            "> Open the HTML guide inside the .zip for manual creation steps.",
            "",
            "## Summary",
            generation_result.get("summary", ""),
            "",
            "## Generated Rules",
        ]
        for rule in rules:
            lines.append(f"- **{rule.get('rule_name')}** ({rule.get('rule_type')}) -- {rule.get('description', '')}")

        checklist = generation_result.get("review_checklist", [])
        if checklist:
            lines += ["", "## Review Checklist"]
            for item in checklist:
                lines.append(f"- [ ] {item}")

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Summary written: {summary_path}")
