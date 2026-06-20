"""
contents_parser.py
Parses PEGA's META-INF/contents.txt rule inventory manifest.

Format (tab or * delimited):
  Instance Key * RuleSet:Version * Rule Availability * Last Updated * Owning File

Instance Key format:
  RULE-TYPE CLASS-NAME RULE-NAME #TIMESTAMP
  e.g.: RULE-OBJ-ACTIVITY WKTAAPP-FW-REGTOOLS-WORK PROCESSINCOMINGEMAILS #20260616T003542.217 GMT
"""

from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DELIMITER = "*"
HEADER_LINE = "Instance Key"

# Maps PEGA rule type prefix to human-readable type
RULE_TYPE_MAP = {
    "RULE-OBJ-ACTIVITY": "Activity",
    "RULE-OBJ-FLOW": "Flow",
    "RULE-OBJ-FLOW-ACTION": "FlowAction",
    "RULE-HTML-PROPERTY": "Property",
    "RULE-HTML-SECTION": "Section",
    "RULE-HTML-HARNESS": "Harness",
    "RULE-DECLARE-PAGES": "DataPage",
    "RULE-DECLARE-TRIGGER": "Trigger",
    "RULE-DECLARE-INDEX": "Index",
    "RULE-OBJ-REPORT-DEFINITION": "ReportDefinition",
    "RULE-OBJ-REPORT-VIEW": "ReportView",
    "RULE-CONNECT-REST": "ConnectREST",
    "RULE-CONNECT-SOAP": "ConnectSOAP",
    "RULE-CONNECT-SAP": "ConnectSAP",
    "RULE-SERVICE-REST": "ServiceREST",
    "RULE-SERVICE-SOAP": "ServiceSOAP",
    "RULE-UTILITY-FUNCTION": "Function",
    "RULE-OBJ-VALIDATE": "Validate",
    "RULE-OBJ-EDIT-VALIDATE": "EditValidate",
    "RULE-RULESET-NAME": "RuleSet",
    "RULE-RULESET-VERSION": "RuleSetVersion",
    "RULE-ADMIN-PRODUCT": "Product",
    "DATA-ADMIN-DB-TABLE": "DatabaseTable",
    "DATA-ADMIN-PROPERTY": "Property",
    "DATA-ADMIN-OBJECT-TYPEDEF": "TypeDef",
    "DATA-ADMIN-OBJECT-REFERENCE": "Reference",
    "RULE-OBJ-CORRESPONDENCE": "Correspondence",
    "RULE-OBJ-WHEN": "When",
    "RULE-OBJ-DECISION-TABLE": "DecisionTable",
    "RULE-OBJ-DECISION-TREE": "DecisionTree",
    "RULE-OBJ-MAP-VALUE": "MapValue",
    "RULE-CASE-TYPE": "CaseType",
    "RULE-CASE-LIFECYCLE": "Lifecycle",
    "RULE-OBJ-PARAGRAPH": "Paragraph",
}


class ContentsParser:
    """
    Parses META-INF/contents.txt from a PEGA JAR export.
    Returns a list of structured rule metadata dicts.
    """

    def parse(self, contents_txt_path: str | Path) -> list[dict]:
        """
        Parse contents.txt and return a list of rule metadata dicts.

        Each dict has:
            rule_key        : full PEGA instance key
            rule_type_raw   : e.g. RULE-OBJ-ACTIVITY
            rule_type       : human-readable e.g. Activity
            pega_class      : PEGA class name
            rule_name       : rule name (lowercased PEGA name)
            ruleset         : ruleset name
            ruleset_version : ruleset version
            available       : True/False
            last_updated    : datetime string
            bin_file        : owning .bin filename
        """
        path = Path(contents_txt_path)
        if not path.exists():
            raise FileNotFoundError(f"contents.txt not found: {path}")

        rules = []
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith(HEADER_LINE):
                continue

            parts = [p.strip() for p in line.split(DELIMITER)]
            if len(parts) < 5:
                logger.debug(f"Skipping malformed line {line_num}: {line[:80]}")
                continue

            instance_key = parts[0]
            ruleset_full = parts[1]   # e.g. RegTools:02-08-94
            availability = parts[2]   # e.g. Yes / No / ""
            last_updated = parts[3]
            bin_file = parts[4]

            parsed_key = self._parse_instance_key(instance_key)
            if not parsed_key:
                continue

            ruleset_parts = ruleset_full.split(":")
            ruleset_name = ruleset_parts[0] if ruleset_parts else ""
            ruleset_version = ruleset_parts[1] if len(ruleset_parts) > 1 else ""

            rule = {
                "rule_key": instance_key,
                "rule_type_raw": parsed_key["rule_type_raw"],
                "rule_type": parsed_key["rule_type"],
                "pega_class": parsed_key["pega_class"],
                "rule_name": parsed_key["rule_name"],
                "ruleset": ruleset_name,
                "ruleset_version": ruleset_version,
                "available": availability.lower() == "yes",
                "last_updated": last_updated,
                "bin_file": bin_file,
            }
            rules.append(rule)

        logger.info(f"Parsed {len(rules)} rules from {path.name}")
        return rules

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_instance_key(self, key: str) -> dict | None:
        """
        Parse a PEGA instance key into its components.
        Format: RULE-TYPE CLASS-NAME RULE-NAME #TIMESTAMP
        """
        # Strip timestamp suffix  (#20260616T003542.217 GMT)
        key_clean = re.sub(r'\s*#\S+.*$', '', key).strip()
        parts = key_clean.split()

        if len(parts) < 3:
            # Some records like RULE-RULESET-NAME have only 2 parts
            if len(parts) == 2:
                return {
                    "rule_type_raw": parts[0],
                    "rule_type": RULE_TYPE_MAP.get(parts[0], parts[0]),
                    "pega_class": "",
                    "rule_name": parts[1],
                }
            return None

        rule_type_raw = parts[0]
        # Class is everything between rule_type and last token
        rule_name = parts[-1]
        pega_class = " ".join(parts[1:-1])

        return {
            "rule_type_raw": rule_type_raw,
            "rule_type": RULE_TYPE_MAP.get(rule_type_raw, rule_type_raw),
            "pega_class": pega_class,
            "rule_name": rule_name,
        }
