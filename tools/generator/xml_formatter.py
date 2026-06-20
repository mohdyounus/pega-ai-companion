"""
xml_formatter.py
Renders Jinja2 XML templates into valid PEGA rule XML
and validates the output structure.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from lxml import etree

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

RULE_TYPE_TO_TEMPLATE = {
    "Flow": "flow_template.xml",
    "DataPage": "datapage_template.xml",
    "Activity": "activity_template.xml",
    "Harness": "harness_template.xml",
}


class XMLFormatter:
    """
    Takes a rule dict (from rule_generator.py) and produces
    well-formed PEGA XML using Jinja2 templates.
    """

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, rule_type: str, context: dict) -> str:
        """
        Render a PEGA rule to XML string.

        Args:
            rule_type: One of Flow, DataPage, Activity, Harness
            context:   Template variables dict

        Returns:
            Well-formed XML string
        """
        template_file = RULE_TYPE_TO_TEMPLATE.get(rule_type)
        if not template_file:
            raise ValueError(
                f"Unknown rule type: {rule_type}. "
                f"Supported: {list(RULE_TYPE_TO_TEMPLATE.keys())}"
            )

        template = self.env.get_template(template_file)
        xml_str = template.render(**context)
        return self._validate_and_format(xml_str, rule_type)

    def render_from_llm_output(self, llm_json: dict) -> list[dict]:
        """
        Process the JSON output from Agent 10.
        Returns list of dicts with: rule_name, rule_type, xml, notes.

        If the LLM produced raw XML directly (not via template),
        it still validates it. Falls back to template rendering
        if the LLM output can be mapped to a template.
        """
        results = []
        for rule in llm_json.get("rules", []):
            raw_xml = rule.get("xml", "")
            rule_type = rule.get("rule_type", "")

            if raw_xml:
                # LLM produced raw XML — validate it
                try:
                    formatted_xml = self._validate_and_format(raw_xml, rule_type)
                    rule["xml"] = formatted_xml
                    rule["xml_valid"] = True
                except Exception as e:
                    logger.warning(f"XML validation failed for {rule.get('rule_name')}: {e}")
                    rule["xml_valid"] = False
                    rule["xml_error"] = str(e)
            else:
                # No XML from LLM — try template rendering
                try:
                    rule["xml"] = self.render(rule_type, rule)
                    rule["xml_valid"] = True
                except Exception as e:
                    logger.warning(f"Template rendering failed for {rule.get('rule_name')}: {e}")
                    rule["xml_valid"] = False
                    rule["xml_error"] = str(e)

            results.append(rule)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_and_format(self, xml_str: str, rule_type: str) -> str:
        """Parse and re-serialise XML to ensure well-formedness and consistent formatting."""
        try:
            root = etree.fromstring(xml_str.encode("utf-8"))
        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML for {rule_type}: {e}") from e

        # Pretty-print with 2-space indentation
        etree.indent(root, space="  ")
        return etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        ).decode("utf-8")

    def extract_json_from_llm_response(self, raw_text: str) -> dict:
        """
        Safely extract JSON from Claude's response.
        Handles cases where the model wraps JSON in markdown code blocks.
        """
        text = raw_text.strip()
        # Strip ```json ... ``` wrapper if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse LLM JSON output: {e}\nRaw: {raw_text[:500]}") from e
