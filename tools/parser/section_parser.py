"""
section_parser.py
Specialist parser for PEGA UI rules: Rule-HTML-Section and Rule-HTML-Harness.

Extracts richer metadata than the generic bin_parser:
  - Layout type (table, repeating, free-form, grid, tree, dynamic)
  - Template type (create, review, perform, confirm, list, search, detail)
  - Controls used (text box, dropdown, button, grid, table, dynamic layout)
  - Data source (class name, data page, report definition)
  - Visible-when conditions (display logic)
  - Repeating structure (page list vs page group vs single page)

These become the "fingerprint" of each section, used for RAG-based
UI pattern recommendation.
"""

from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Layout type signals ──────────────────────────────────────────────────────
LAYOUT_SIGNALS = {
    "repeating":      ["repeating", "repeatlayout", "repeatrow", "pagelist", "pagegroup",
                       "for-each", "foreach", "gridlayout"],
    "table":          ["table", "tablelayout", "columnheader", "tablerow", "<tr", "<td",
                       "gridtable", "datatable"],
    "flow":           ["flowlayout", "flow-layout", "inline", "horizontal"],
    "stacked":        ["stackedlayout", "stacked", "vertical", "column"],
    "dynamic":        ["dynamiclayout", "dynamic layout", "auto-layout", "accordion",
                       "tabbed", "tabs"],
    "tree":           ["tree", "treetable", "treeview", "hierarchical"],
    "modal":          ["modal", "dialog", "overlay", "popup"],
    "panel":          ["panel", "panelgroup", "sidepanel"],
}

# ── Template / purpose signals ───────────────────────────────────────────────
TEMPLATE_SIGNALS = {
    "create":         ["create", "new", "submit", "pycreatework", "creatework",
                       "pycreatecase", "newcase"],
    "review":         ["review", "summary", "pyreview", "confirm", "reviewharness"],
    "perform":        ["perform", "assignment", "pyperform", "action", "task"],
    "list":           ["list", "search result", "browse", "grid", "pysearchresult",
                       "listview", "worklist", "workbasket"],
    "search":         ["search", "filter", "query", "criteria", "pysearch", "findwork"],
    "detail":         ["detail", "profile", "view", "readonly", "readonlyfield"],
    "dashboard":      ["dashboard", "home", "landing", "overview", "portal"],
    "navigation":     ["navigation", "nav", "menu", "breadcrumb", "sidebar"],
    "attachment":     ["attachment", "file", "upload", "download", "pyattachment"],
    "audit":          ["audit", "history", "changelog", "log", "trail"],
}

# ── Control type signals ─────────────────────────────────────────────────────
CONTROL_SIGNALS = {
    "text_input":     ["textinput", "text-input", "pxinputtext", "inputtext", "<input"],
    "dropdown":       ["dropdown", "select", "combobox", "pxdropdown", "pyselectoption"],
    "button":         ["button", "pxbutton", "submit-button", "actionbutton"],
    "grid":           ["grid", "datagrid", "pxgrid", "repeatinggrid"],
    "autocomplete":   ["autocomplete", "typeahead", "suggest", "pxautocomplete"],
    "date_picker":    ["datepicker", "date-picker", "pxdatepicker", "calendar"],
    "rich_text":      ["richtext", "rich-text", "pxrichtext", "wysiwyg"],
    "file_upload":    ["fileupload", "file-upload", "pxfileupload", "attachment"],
    "checkbox":       ["checkbox", "check-box", "pxcheckbox", "boolean"],
    "radio":          ["radio", "radiobutton", "radio-button"],
    "table":          ["tablelayout", "table-layout", "repeatingtable"],
    "chart":          ["chart", "pxchart", "graph", "visualization"],
    "map":            ["map", "geolocation", "pxmap"],
    "signature":      ["signature", "pxsignature"],
}

# ── Data source signals ──────────────────────────────────────────────────────
DATA_SOURCE_RE = [
    re.compile(r'D_([A-Za-z0-9_\-]+)', re.IGNORECASE),   # Data pages D_XXX
    re.compile(r'datapage[:\s"=]+([A-Za-z0-9_\-]+)', re.IGNORECASE),
    re.compile(r'reportdefinition[:\s"=]+([A-Za-z0-9_\-]+)', re.IGNORECASE),
    re.compile(r'sourcepage[:\s"=]+([A-Za-z0-9_\-]+)', re.IGNORECASE),
]

# ── Visible-when signals ─────────────────────────────────────────────────────
VISIBLE_WHEN_RE = re.compile(
    r'(visiblewhen|showwhen|hidewhen|displaywhen)[:\s"=]+([A-Za-z0-9_\-\.]+)',
    re.IGNORECASE
)

# ── PEGA class name pattern ──────────────────────────────────────────────────
PEGA_CLASS_RE = re.compile(
    r'\b([A-Z][A-Z0-9]+-[A-Z][A-Z0-9\-]+)\b'
)


class SectionParser:
    """
    Enriches Section and Harness rule metadata by analysing extracted
    string content from .bin files.
    """

    UI_RULE_TYPES = {"Section", "Harness"}

    def enrich_ui_rules(self, rules: list[dict], raw_strings: list[str]) -> list[dict]:
        """
        Enrich Section/Harness rules with UI metadata.
        Derives metadata from rule name (primary) + any raw strings (secondary).
        """
        combined = " ".join(raw_strings).lower() if raw_strings else ""
        ui_rules = [r for r in rules if r.get("rule_type") in self.UI_RULE_TYPES]
        logger.info(f"Enriching {len(ui_rules)} UI rules (Section/Harness)")

        for rule in ui_rules:
            rule_name = rule.get("rule_name", "").lower()
            pega_class = rule.get("pega_class", "").lower()

            # Build context from rule name + class — these are very descriptive in PEGA
            name_context = rule_name + " " + pega_class + " " + rule_name.replace("_", " ")

            # Also use any available raw strings scoped to this rule
            relevant_strings = [s for s in raw_strings
                                 if rule_name in s.lower() and len(s) > 5]
            string_context = " ".join(relevant_strings[:200]).lower()

            context = name_context + " " + string_context

            rule["ui_metadata"] = {
                "layout_types":       self._detect(context, LAYOUT_SIGNALS),
                "template_type":      self._top_match(context, TEMPLATE_SIGNALS),
                "controls_used":      self._detect(context, CONTROL_SIGNALS),
                "data_sources":       self._extract_data_sources(context),
                "visible_when":       self._extract_visible_when(context),
                "referenced_classes": self._extract_classes(pega_class.upper()),
                "has_repeating":      any(kw in context for kw in
                                          ["list", "worklist", "table", "grid",
                                           "repeating", "pagelist", "results"]),
                "has_actions":        any(kw in context for kw in
                                          ["action", "button", "submit", "create",
                                           "perform", "save", "confirm"]),
                "is_modal":           any(kw in context for kw in
                                          ["modal", "dialog", "overlay", "popup",
                                           "confirm", "prompt"]),
            }

        return rules

    def generate_ui_description(self, rule: dict) -> str:
        """
        Generate a human-readable description of a UI rule for the knowledge base.
        This becomes the text that gets embedded and searched.
        """
        ui = rule.get("ui_metadata", {})
        rule_type = rule.get("rule_type", "Section")
        rule_name = rule.get("rule_name", "")
        pega_class = rule.get("pega_class", "")
        ruleset = rule.get("ruleset", "")

        parts = [
            f"{rule_type} '{rule_name}' on class {pega_class} in ruleset {ruleset}.",
        ]

        tmpl = ui.get("template_type")
        if tmpl:
            parts.append(f"Purpose: {tmpl} template.")

        layouts = ui.get("layout_types", [])
        if layouts:
            parts.append(f"Layout: {', '.join(layouts)}.")

        controls = ui.get("controls_used", [])
        if controls:
            parts.append(f"Controls: {', '.join(controls)}.")

        sources = ui.get("data_sources", [])
        if sources:
            parts.append(f"Data sources: {', '.join(sources[:5])}.")

        if ui.get("has_repeating"):
            parts.append("Contains repeating/list layout.")
        if ui.get("has_actions"):
            parts.append("Contains action buttons / flow triggers.")
        if ui.get("is_modal"):
            parts.append("Rendered as modal/dialog.")

        classes = ui.get("referenced_classes", [])
        if classes:
            parts.append(f"Referenced classes: {', '.join(classes[:5])}.")

        return " ".join(parts)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _detect(self, text: str, signal_map: dict) -> list[str]:
        """Return all signal categories that have at least one keyword match."""
        found = []
        for category, keywords in signal_map.items():
            if any(kw in text for kw in keywords):
                found.append(category)
        return found

    def _top_match(self, text: str, signal_map: dict) -> str:
        """Return the category with the most keyword hits."""
        scores = {}
        for category, keywords in signal_map.items():
            scores[category] = sum(1 for kw in keywords if kw in text)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=lambda k: scores[k])

    def _extract_data_sources(self, text: str) -> list[str]:
        sources = set()
        for pattern in DATA_SOURCE_RE:
            for m in pattern.finditer(text):
                val = m.group(1).strip().upper()
                if len(val) > 2:
                    sources.add(val)
        return list(sources)[:10]

    def _extract_visible_when(self, text: str) -> list[str]:
        conditions = []
        for m in VISIBLE_WHEN_RE.finditer(text):
            conditions.append(m.group(2))
        return list(set(conditions))[:10]

    def _extract_classes(self, text: str) -> list[str]:
        classes = set()
        for m in PEGA_CLASS_RE.finditer(text.upper()):
            cls = m.group(1)
            if len(cls) > 5 and "-" in cls:
                classes.add(cls)
        return list(classes)[:10]
