"""Load and validate the small JSON rule-schema format used by the project."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RULE_TYPES = {
    "required",
    "max_length",
    "min_length",
    "must_match",
    "must_not_match",
    "numeric_fields",
    "section_order",
    "timestamp_format",
}
SYNTHETIC_TEMPLATE_SOURCE = "illustrative departmental template (synthetic)"
NATIONAL_STANDARD_PREFIX = "《病历书写基本规范》第"


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    source: str
    message: str
    value: Any = None


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    required: bool
    order: int
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class RecordSchema:
    department: str
    display_name: str
    sections: tuple[Section, ...]
    global_rules: tuple[Rule, ...]
    provenance: dict[str, Any]

    @property
    def section_by_id(self) -> dict[str, Section]:
        return {section.id: section for section in self.sections}

    @property
    def section_by_label(self) -> dict[str, Section]:
        return {section.label: section for section in self.sections}

    @property
    def rule_by_id(self) -> dict[str, Rule]:
        rules = [rule for section in self.sections for rule in section.rules]
        return {rule.id: rule for rule in [*rules, *self.global_rules]}

    @property
    def required_sections(self) -> tuple[Section, ...]:
        return tuple(section for section in self.sections if section.required)


def _require(mapping: dict[str, Any], key: str, expected_type: type, context: str) -> Any:
    if key not in mapping or not isinstance(mapping[key], expected_type):
        raise ValueError(f"{context}.{key} must be {expected_type.__name__}")
    return mapping[key]


def _load_rule(raw: dict[str, Any], context: str) -> Rule:
    rule_id = _require(raw, "id", str, context)
    rule_type = _require(raw, "type", str, context)
    source = _require(raw, "source", str, context)
    message = _require(raw, "message", str, context)
    if not source.strip():
        raise ValueError(f"{context}.source must not be empty")
    if source != SYNTHETIC_TEMPLATE_SOURCE and not source.startswith(NATIONAL_STANDARD_PREFIX):
        raise ValueError(f"{context}.source must identify the public standard or synthetic template")
    if rule_type not in RULE_TYPES:
        raise ValueError(f"{context}.type has unsupported value {rule_type!r}")
    if rule_type in {"max_length", "min_length"}:
        value = raw.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{context}.value must be a non-negative integer")
    elif rule_type in {"must_match", "must_not_match"}:
        value = raw.get("value")
        if not isinstance(value, str):
            raise ValueError(f"{context}.value must be a regex string")
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"{context}.value is not a valid regex") from exc
    elif rule_type == "numeric_fields":
        value = raw.get("value")
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
            raise ValueError(f"{context}.value must be a non-empty list of field names")
    else:
        value = raw.get("value")
    return Rule(id=rule_id, type=rule_type, source=source, message=message, value=value)


def load_schema(path: str | Path) -> RecordSchema:
    """Load a schema and reject structural errors before validation begins."""
    schema_path = Path(path)
    with schema_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("schema root must be an object")

    department = _require(raw, "department", str, "schema")
    display_name = _require(raw, "display_name", str, "schema")
    provenance = _require(raw, "provenance", dict, "schema")
    national = _require(provenance, "national_standard", dict, "schema.provenance")
    departmental = _require(provenance, "departmental_template", dict, "schema.provenance")
    for key in ("title", "document_number", "official_url", "scope"):
        _require(national, key, str, "schema.provenance.national_standard")
    departmental_source = _require(departmental, "source", str, "schema.provenance.departmental_template")
    if departmental_source != SYNTHETIC_TEMPLATE_SOURCE:
        raise ValueError("schema departmental source must identify the template as synthetic")

    raw_sections = _require(raw, "sections", list, "schema")
    sections: list[Section] = []
    for index, raw_section in enumerate(raw_sections):
        context = f"schema.sections[{index}]"
        if not isinstance(raw_section, dict):
            raise ValueError(f"{context} must be an object")
        raw_rules = _require(raw_section, "rules", list, context)
        rules = tuple(
            _load_rule(rule, f"{context}.rules[{rule_index}]")
            for rule_index, rule in enumerate(raw_rules)
            if isinstance(rule, dict)
        )
        if len(rules) != len(raw_rules):
            raise ValueError(f"{context}.rules entries must be objects")
        sections.append(
            Section(
                id=_require(raw_section, "id", str, context),
                label=_require(raw_section, "label", str, context),
                required=_require(raw_section, "required", bool, context),
                order=_require(raw_section, "order", int, context),
                rules=rules,
            )
        )

    raw_global = _require(raw, "global_rules", list, "schema")
    global_rules = tuple(
        _load_rule(rule, f"schema.global_rules[{index}]")
        for index, rule in enumerate(raw_global)
        if isinstance(rule, dict)
    )
    if len(global_rules) != len(raw_global):
        raise ValueError("schema.global_rules entries must be objects")

    section_ids = [section.id for section in sections]
    labels = [section.label for section in sections]
    orders = [section.order for section in sections]
    rule_ids = [rule.id for section in sections for rule in section.rules]
    rule_ids.extend(rule.id for rule in global_rules)
    for name, values in (("section id", section_ids), ("section label", labels), ("section order", orders), ("rule id", rule_ids)):
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {name} in {schema_path}")
    if any(isinstance(order, bool) or order < 1 for order in orders):
        raise ValueError("section order must be a positive integer")
    if any(rule.type != "section_order" for rule in global_rules):
        raise ValueError("only section_order rules may be global")

    return RecordSchema(
        department=department,
        display_name=display_name,
        sections=tuple(sections),
        global_rules=global_rules,
        provenance=provenance,
    )
