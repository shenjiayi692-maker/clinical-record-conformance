"""Deterministic clinical-record validation. No model calls live here."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from src.schema import RecordSchema, Rule, Section


PARSE_FAILURE_ID = "PARSE-000"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class ParsedRecord:
    sections: dict[str, str]
    order: tuple[str, ...]
    parse_failed: bool = False


def _clean_heading(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^(?:[-*+]\s+|\d+[.、)]\s*)", "", cleaned)
    return cleaned.replace("**", "").replace("__", "").replace("`", "").strip()


def parse_record(text: str, schema: RecordSchema) -> ParsedRecord:
    """Split free text on known section labels and flag unknown explicit headings."""
    by_label = schema.section_by_label
    sections: dict[str, str] = {}
    order: list[str] = []
    chunks: dict[str, list[str]] = {}
    current_id: str | None = None
    parse_failed = False

    for raw_line in text.splitlines():
        line = _clean_heading(raw_line)
        if not line:
            continue

        matched = False
        for label, section in by_label.items():
            heading_match = re.fullmatch(rf"{re.escape(label)}\s*[：:]?\s*(.*)", line)
            if heading_match:
                current_id = section.id
                if current_id in sections or current_id in chunks:
                    parse_failed = True
                else:
                    order.append(current_id)
                    chunks[current_id] = []
                inline = heading_match.group(1).strip()
                if inline:
                    chunks.setdefault(current_id, []).append(inline)
                matched = True
                break
        if matched:
            continue

        looks_like_heading = bool(re.fullmatch(r"[^，。；、]{1,12}[：:].*", line))
        if looks_like_heading:
            prefix = re.split(r"[：:]", line, maxsplit=1)[0].strip()
            if prefix not in by_label and not re.fullmatch(r"(?:T|P|R|BP|SpO2)", prefix, re.IGNORECASE):
                parse_failed = True
        if current_id is None:
            parse_failed = True
        else:
            chunks[current_id].append(line)

    for section_id, lines in chunks.items():
        # Sentence punctuation belongs to the free-text container, not a closed-set field value.
        sections[section_id] = "\n".join(lines).strip().rstrip("。；;")
    if not sections:
        parse_failed = True
    return ParsedRecord(sections=sections, order=tuple(order), parse_failed=parse_failed)


def _normalize_mapping(record: Mapping[str, object], schema: RecordSchema) -> ParsedRecord:
    by_id = schema.section_by_id
    by_label = schema.section_by_label
    sections: dict[str, str] = {}
    order: list[str] = []
    parse_failed = False

    for key, raw_value in record.items():
        if key in by_id:
            section_id = key
        elif key in by_label:
            section_id = by_label[key].id
        else:
            parse_failed = True
            continue
        if section_id in sections:
            parse_failed = True
            continue
        if raw_value is None:
            value = ""
        elif isinstance(raw_value, str):
            value = raw_value.strip()
        else:
            parse_failed = True
            value = str(raw_value).strip()
        sections[section_id] = value
        order.append(section_id)
    return ParsedRecord(sections=sections, order=tuple(order), parse_failed=parse_failed)


def has_numeric_field(content: str, key: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(key)}\s*(?:[:：=]?\s*)-?\d+(?:\.\d+)?"
    return re.search(pattern, content, flags=re.IGNORECASE) is not None


def _timestamp_is_valid(content: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", content):
        return False
    try:
        datetime.strptime(content, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def _violates(rule: Rule, content: str) -> bool:
    if rule.type == "required":
        return not content.strip()
    if rule.type == "max_length":
        return len(content) > rule.value
    if rule.type == "min_length":
        return len(content) < rule.value
    if rule.type == "must_match":
        return re.search(rule.value, content) is None
    if rule.type == "must_not_match":
        return re.search(rule.value, content) is not None
    if rule.type == "numeric_fields":
        return any(not has_numeric_field(content, key) for key in rule.value)
    if rule.type == "timestamp_format":
        return not _timestamp_is_valid(content)
    raise ValueError(f"unsupported section rule: {rule.type}")


def validate_record(record: str | Mapping[str, object] | ParsedRecord, schema: RecordSchema) -> list[str]:
    """Return every violated rule ID in stable schema order."""
    if isinstance(record, ParsedRecord):
        parsed = record
    elif isinstance(record, str):
        parsed = parse_record(record, schema)
    elif isinstance(record, Mapping):
        parsed = _normalize_mapping(record, schema)
    else:
        raise TypeError("record must be text, a mapping, or ParsedRecord")

    failures: list[str] = []
    if parsed.parse_failed:
        failures.append(PARSE_FAILURE_ID)

    for section in schema.sections:
        content = parsed.sections.get(section.id, "").strip()
        for rule in section.rules:
            if rule.type != "required" and not content:
                continue
            if _violates(rule, content):
                failures.append(rule.id)

    for rule in schema.global_rules:
        if rule.type == "section_order":
            expected = [section.id for section in sorted(schema.sections, key=lambda item: item.order)]
            expected_position = {section_id: index for index, section_id in enumerate(expected)}
            positions = [expected_position[section_id] for section_id in parsed.order if section_id in expected_position]
            if positions != sorted(positions):
                failures.append(rule.id)

    return failures


def field_completeness(record: str | Mapping[str, object] | ParsedRecord, schema: RecordSchema) -> float:
    """Fraction of required sections that are present and non-empty."""
    if isinstance(record, ParsedRecord):
        parsed = record
    elif isinstance(record, str):
        parsed = parse_record(record, schema)
    else:
        parsed = _normalize_mapping(record, schema)
    required = schema.required_sections
    if not required:
        return 1.0
    present = sum(bool(parsed.sections.get(section.id, "").strip()) for section in required)
    return present / len(required)


def render_record(record: Mapping[str, object], schema: RecordSchema) -> str:
    """Render known mapping fields in their supplied order for later validation."""
    by_id = schema.section_by_id
    by_label = schema.section_by_label
    lines: list[str] = []
    for key, raw_value in record.items():
        section: Section | None = by_id.get(key) or by_label.get(key)
        label = section.label if section else str(key)
        value = "" if raw_value is None else str(raw_value).strip()
        lines.append(f"{label}：{value}")
    return "\n".join(lines)
