"""
bin_parser.py
Parses PEGA's Java-serialized .bin files to extract rule implementation details.

PEGA .bin files (instances_NNNNN.bin) are Java serialized objects of type:
  com.pega.pegarules.deploy.internal.inventory.ParInventory

Strategy:
  1. Primary: Use javaobj-py3 to fully deserialize the Java object tree
  2. Fallback: String extraction from binary for key PEGA property names

The output enriches the rule metadata from contents_parser.py with
details like: labels, descriptions, step lists, property references.
"""

from __future__ import annotations
import logging
import re
import struct
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Known PEGA property field names embedded in the binary
PEGA_STRING_FIELDS = [
    "mInsNameq", "mRuleNameq", "mClassNameq", "mPyLabelq",
    "mPyRuleNameq", "mRuleSetq", "mRuleSetNameq", "mTableNameq",
    "mUpdateOperatorq", "mSaveDateTimeq", "mEmbeddedJarNameq",
    "mPxRuleObjClassq", "mPxRuleClassNameq", "mPxRuleSetq",
    "mPxReferencingDescriptionq",
]


class BinParser:
    """
    Parses PEGA .bin files and enriches rule metadata.
    Attempts full Java deserialization first, falls back to string extraction.
    """

    def __init__(self):
        self._javaobj_available = self._check_javaobj()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, bin_path: str | Path) -> list[dict]:
        """
        Parse a .bin file and return a list of rule detail dicts.
        Each dict maps rule_key → extracted properties.
        """
        path = Path(bin_path)
        if not path.exists():
            raise FileNotFoundError(f".bin file not found: {path}")

        logger.info(f"Parsing .bin: {path.name} ({path.stat().st_size:,} bytes)")

        if self._javaobj_available:
            try:
                return self._parse_with_javaobj(path)
            except Exception as e:
                logger.warning(f"javaobj deserialization failed ({e}), falling back to string extraction")

        return self._parse_with_string_extraction(path)

    def enrich_rules(self, rules: list[dict], bin_path: str | Path) -> list[dict]:
        """
        Enrich a list of rule metadata dicts (from contents_parser)
        with additional data extracted from the .bin file.
        """
        bin_data = self.parse(bin_path)

        # Build lookup by rule name (case-insensitive)
        bin_lookup: dict[str, dict] = {}
        for entry in bin_data:
            key = entry.get("rule_name", "").upper()
            if key:
                bin_lookup[key] = entry

        enriched = []
        for rule in rules:
            rule_name_upper = rule.get("rule_name", "").upper()
            extra = bin_lookup.get(rule_name_upper, {})
            enriched.append({**rule, **extra})

        return enriched

    # ------------------------------------------------------------------
    # Strategy 1: javaobj-py3
    # ------------------------------------------------------------------

    def _parse_with_javaobj(self, path: Path) -> list[dict]:
        import javaobj.v2 as javaobj

        with open(path, "rb") as f:
            obj = javaobj.load(f)

        rules = []
        inventory = self._unwrap_java_object(obj)
        instance_set = self._get_field(inventory, "mInstanceSet") or []

        for item in self._iter_collection(instance_set):
            rule = self._extract_instance_info(item)
            if rule:
                rules.append(rule)

        logger.info(f"javaobj parsed {len(rules)} rule instances from {path.name}")
        return rules

    def _extract_instance_info(self, obj: Any) -> dict | None:
        """Extract rule metadata from a Java InstanceInfo object."""
        try:
            rule_name = self._get_string_field(obj, "mRuleNameq") or self._get_string_field(obj, "mInsNameq")
            pega_class = self._get_string_field(obj, "mClassNameq")
            label = self._get_string_field(obj, "mPyLabelq")
            ruleset = self._get_string_field(obj, "mRuleSetq") or self._get_string_field(obj, "mPxRuleSetq")
            rule_obj_class = self._get_string_field(obj, "mPxRuleObjClassq")
            description = self._get_string_field(obj, "mPxReferencingDescriptionq")

            if not rule_name:
                return None

            return {
                "rule_name": rule_name,
                "pega_class": pega_class or "",
                "label": label or rule_name,
                "ruleset": ruleset or "",
                "rule_obj_class": rule_obj_class or "",
                "description": description or "",
            }
        except Exception as e:
            logger.debug(f"Could not extract instance info: {e}")
            return None

    def _unwrap_java_object(self, obj: Any) -> Any:
        if hasattr(obj, "classdesc"):
            return obj
        return obj

    def _get_field(self, obj: Any, field_name: str) -> Any:
        try:
            return getattr(obj, field_name, None)
        except Exception:
            return None

    def _get_string_field(self, obj: Any, field_name: str) -> str | None:
        val = self._get_field(obj, field_name)
        if val is None:
            return None
        if hasattr(val, "value"):
            return str(val.value)
        return str(val) if val else None

    def _iter_collection(self, collection: Any):
        if collection is None:
            return []
        if hasattr(collection, "__iter__"):
            try:
                return list(collection)
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------
    # Strategy 2: String extraction fallback
    # ------------------------------------------------------------------

    def _parse_with_string_extraction(self, path: Path) -> list[dict]:
        """
        Fallback: extract readable strings from binary to build partial rule info.
        Less structured but works without javaobj.
        """
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")

        # Extract all readable ASCII strings >= 4 chars
        strings = re.findall(r'[A-Za-z0-9\-_\.@ ]{4,}', text)

        rules = []
        # Look for PEGA rule class patterns
        rule_class_pattern = re.compile(
            r'(RULE-OBJ-ACTIVITY|RULE-OBJ-FLOW|RULE-HTML-HARNESS|RULE-DECLARE-PAGES|'
            r'RULE-OBJ-REPORT-DEFINITION|RULE-CONNECT-REST|RULE-OBJ-VALIDATE)'
        )
        pega_class_pattern = re.compile(r'[A-Z][A-Z0-9\-]{3,}(?:-[A-Z][A-Z0-9]+)+')

        found_types = rule_class_pattern.findall(text)
        found_classes = pega_class_pattern.findall(text)

        # Deduplicate
        found_classes = list(dict.fromkeys(
            c for c in found_classes
            if not c.startswith("RULE-") and not c.startswith("DATA-")
            and len(c) > 5
        ))

        summary = {
            "rule_types_found": list(set(found_types)),
            "pega_classes_found": found_classes[:20],
            "total_strings": len(strings),
            "parse_method": "string_extraction_fallback",
        }

        logger.info(
            f"String extraction: found {len(found_types)} rule type refs, "
            f"{len(found_classes)} class refs in {path.name}"
        )
        logger.info(
            "Install javaobj-py3 for full .bin parsing: pip install javaobj-py3"
        )

        return [summary]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _check_javaobj() -> bool:
        try:
            import javaobj.v2
            return True
        except ImportError:
            logger.info(
                "javaobj-py3 not installed — using string extraction fallback. "
                "Run: pip install javaobj-py3 for full .bin parsing."
            )
            return False
