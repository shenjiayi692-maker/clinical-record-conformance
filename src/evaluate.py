"""Compute conformance, grounding, recovery, and latency metrics from an attempt log."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any

from src.schema import load_schema
from src.validator import PARSE_FAILURE_ID, has_numeric_field


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def read_log(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number} of {path}") from exc
            required = {"record_id", "arm", "department", "attempt", "violated_rule_ids", "field_completeness", "latency_ms"}
            missing = required - row.keys()
            if missing:
                raise ValueError(f"line {line_number} missing fields: {sorted(missing)}")
            row.setdefault("case_id", row["record_id"])
            row.setdefault("input_style", "unknown")
            row.setdefault("structured_record", {})
            row.setdefault("omitted_required_fields", [])
            row.setdefault("omitted_field_rule_ids", {})
            rows.append(row)
    if not rows:
        raise ValueError(f"empty run log: {path}")
    return rows


def _rule_types() -> dict[str, str]:
    result = {PARSE_FAILURE_ID: "parse"}
    for filename in ("internal_medicine.json", "emergency.json"):
        schema = load_schema(SCHEMA_DIR / filename)
        result.update({rule_id: rule.type for rule_id, rule in schema.rule_by_id.items()})
    return result


def _group_records(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["arm"], row["department"], row["record_id"])
        grouped[key].append(row)
    for attempts in grouped.values():
        attempts.sort(key=lambda row: row["attempt"])
        expected = list(range(1, len(attempts) + 1))
        actual = [row["attempt"] for row in attempts]
        if actual != expected:
            raise ValueError(f"non-contiguous attempts: {actual}")
        arm = attempts[0]["arm"]
        if arm != "C" and len(attempts) != 1:
            raise ValueError(f"arm {arm} must contain one attempt per record")
        if len(attempts) > 3:
            raise ValueError("attempt budget exceeded")
        stable_fields = ("case_id", "input_style", "omitted_required_fields", "omitted_field_rule_ids")
        if any(attempt.get(key) != attempts[0].get(key) for attempt in attempts[1:] for key in stable_fields):
            raise ValueError(f"source metadata changed across attempts for {attempts[0]['record_id']}")
    return grouped


def _omitted_field_is_populated(row: dict[str, Any], field_path: str) -> bool:
    record = row.get("structured_record")
    if not isinstance(record, dict):
        return False
    section_id, separator, subfield = field_path.partition(".")
    content = record.get(section_id, "")
    if not isinstance(content, str):
        return bool(content)
    if separator:
        return has_numeric_field(content, subfield)
    return bool(content.strip())


def _grounding_metrics(record_groups: list[list[dict[str, Any]]]) -> dict[str, int | float]:
    opportunities = 0
    unsupported_fills = 0
    records_with_unsupported_fills = 0
    surfaced = 0
    for attempts in record_groups:
        final = attempts[-1]
        omissions = final.get("omitted_required_fields", [])
        rule_ids = final.get("omitted_field_rule_ids", {})
        record_has_unsupported_fill = False
        for field_path in omissions:
            opportunities += 1
            populated = _omitted_field_is_populated(final, field_path)
            unsupported_fills += populated
            record_has_unsupported_fill = record_has_unsupported_fill or populated
            rule_id = rule_ids.get(field_path)
            surfaced += bool(rule_id and rule_id in final["violated_rule_ids"])
        records_with_unsupported_fills += record_has_unsupported_fill
    return {
        "omitted_field_opportunities": opportunities,
        "unsupported_fills": unsupported_fills,
        "records_with_unsupported_fills": records_with_unsupported_fills,
        "source_grounded_records": len(record_groups) - records_with_unsupported_fills,
        "source_grounded_record_rate": (len(record_groups) - records_with_unsupported_fills) / len(record_groups),
        "left_unpopulated": opportunities - unsupported_fills,
        "surfaced_as_violations": surfaced,
    }


def _failure_class(rule_type: str) -> str:
    if rule_type == "required":
        return "required"
    if rule_type == "parse":
        return "parse_structure"
    return "format_terminology_order"


def _recovery_metrics(
    record_groups: list[list[dict[str, Any]]], rule_types: dict[str, str]
) -> tuple[dict[str, dict[str, int | float | None]], dict[str, dict[str, int | float | None]], dict[str, dict[str, int | float | None]]]:
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_class: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_root: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for attempts in record_groups:
        first = attempts[0]
        final_failures = set(attempts[-1]["violated_rule_ids"])
        source_absence_rules = set(first.get("omitted_field_rule_ids", {}).values())
        for rule_id in first["violated_rule_ids"]:
            recovered = rule_id not in final_failures
            rule_type = rule_types.get(rule_id, "unknown")
            rule_class = _failure_class(rule_type)
            root = "source_information_absent" if rule_id in source_absence_rules else "model_or_format_repairable"
            for bucket, key in ((by_type, rule_type), (by_class, rule_class), (by_root, root)):
                bucket[key][0] += 1
                bucket[key][1] += recovered

    def finish(raw: dict[str, list[int]]) -> dict[str, dict[str, int | float | None]]:
        result: dict[str, dict[str, int | float | None]] = {}
        for key, (initial, recovered) in sorted(raw.items()):
            result[key] = {
                "initial_failures": initial,
                "recovered": recovered,
                "remaining": initial - recovered,
                "recovery_rate": recovered / initial if initial else None,
            }
        return result

    return finish(by_type), finish(by_class), finish(by_root)


def _slice_metrics(
    record_groups: list[list[dict[str, Any]]], arm: str, rule_types: dict[str, str]
) -> dict[str, Any]:
    first_rows = [attempts[0] for attempts in record_groups]
    final_rows = [attempts[-1] for attempts in record_groups]
    record_latency = [sum(row["latency_ms"] for row in attempts) for attempts in record_groups]
    record_cost = [sum(float(row.get("estimated_cost_usd", 0.0)) for row in attempts) for attempts in record_groups]
    first_failures = Counter(rule_id for row in first_rows for rule_id in row["violated_rule_ids"])
    first_failure_types = Counter(rule_types.get(rule_id, "unknown") for rule_id in first_failures.elements())
    first_pass_rate = fmean(not row["violated_rule_ids"] for row in first_rows)
    pass_rate_after_budget = fmean(not row["violated_rule_ids"] for row in final_rows)
    max_index = max(range(len(record_groups)), key=record_latency.__getitem__)
    max_group = record_groups[max_index]
    metrics: dict[str, Any] = {
        "records": len(record_groups),
        "field_completeness": fmean(float(row["field_completeness"]) for row in final_rows),
        "first_pass_rate": first_pass_rate,
        "final_pass_rate": pass_rate_after_budget if arm == "C" else None,
        "pass_rate_after_budget": pass_rate_after_budget,
        "median_latency_ms": float(median(record_latency)),
        "max_latency_ms": float(record_latency[max_index]),
        "max_latency_record_id": max_group[0]["record_id"],
        "max_latency_attempts": len(max_group),
        "total_cost_usd": sum(record_cost),
        "mean_cost_usd": fmean(record_cost),
        "per_rule_failures": dict(first_failures.most_common()),
        "per_rule_type_failures": dict(first_failure_types.most_common()),
        "grounding": _grounding_metrics(record_groups),
        "retry_distribution": None,
        "unrecoverable": [],
        "recovery_by_rule_type": {},
        "recovery_by_failure_class": {},
        "recovery_by_root_cause": {},
    }
    if arm == "C":
        metrics["retry_distribution"] = dict(sorted(Counter(len(attempts) for attempts in record_groups).items()))
        metrics["unrecoverable"] = [
            {
                "record_id": attempts[-1]["record_id"],
                "input_style": attempts[-1]["input_style"],
                "attempts": len(attempts),
                "violated_rule_ids": attempts[-1]["violated_rule_ids"],
                "human_review_rule_ids": attempts[-1].get("human_review_rule_ids", []),
                "source_absence_rule_ids": sorted(
                    set(attempts[-1]["violated_rule_ids"])
                    & set(attempts[-1].get("omitted_field_rule_ids", {}).values())
                ),
            }
            for attempts in record_groups
            if attempts[-1]["violated_rule_ids"]
        ]
        by_type, by_class, by_root = _recovery_metrics(record_groups, rule_types)
        metrics["recovery_by_rule_type"] = by_type
        metrics["recovery_by_failure_class"] = by_class
        metrics["recovery_by_root_cause"] = by_root
    return metrics


def _bc_first_attempt_pairing(grouped: dict[tuple[str, str, str], list[dict[str, Any]]]) -> dict[str, int | float]:
    by_record: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (arm, _, record_id), attempts in grouped.items():
        if arm in {"B", "C"}:
            by_record[record_id][arm] = attempts[0]
    pairs = [pair for pair in by_record.values() if set(pair) == {"B", "C"}]
    same_failures = sum(pair["B"]["violated_rule_ids"] == pair["C"]["violated_rule_ids"] for pair in pairs)
    same_outputs = sum(pair["B"].get("structured_record") == pair["C"].get("structured_record") for pair in pairs)
    b_aggregate = Counter(rule_id for pair in pairs for rule_id in pair["B"]["violated_rule_ids"])
    c_aggregate = Counter(rule_id for pair in pairs for rule_id in pair["C"]["violated_rule_ids"])
    return {
        "records": len(pairs),
        "same_failure_sets": same_failures,
        "same_structured_outputs": same_outputs,
        "aggregate_rule_failure_counts_match": b_aggregate == c_aggregate,
        "same_failure_set_rate": same_failures / len(pairs) if pairs else 0.0,
        "same_structured_output_rate": same_outputs / len(pairs) if pairs else 0.0,
    }


def evaluate_log(path: str | Path) -> dict[str, Any]:
    log_path = Path(path)
    rows = read_log(log_path)
    grouped = _group_records(rows)
    rule_types = _rule_types()
    arms = sorted({key[0] for key in grouped})
    departments = sorted({key[1] for key in grouped})
    overall: dict[str, Any] = {}
    breakdown: dict[str, dict[str, Any]] = {}
    by_style: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in arms:
        arm_groups = [attempts for (row_arm, _, _), attempts in grouped.items() if row_arm == arm]
        overall[arm] = _slice_metrics(arm_groups, arm, rule_types)
        breakdown[arm] = {}
        by_style[arm] = {}
        for department in departments:
            department_groups = [
                attempts
                for (row_arm, row_department, _), attempts in grouped.items()
                if row_arm == arm and row_department == department
            ]
            if not department_groups:
                continue
            breakdown[arm][department] = _slice_metrics(department_groups, arm, rule_types)
            by_style[arm][department] = {}
            styles = sorted({attempts[0]["input_style"] for attempts in department_groups})
            for style in styles:
                style_groups = [attempts for attempts in department_groups if attempts[0]["input_style"] == style]
                by_style[arm][department][style] = _slice_metrics(style_groups, arm, rule_types)

    emergency_case_sets: dict[str, set[str]] = defaultdict(set)
    complete_emergency_case_sets: dict[str, set[str]] = defaultdict(set)
    for (_, department, _), attempts in grouped.items():
        if department == "emergency":
            emergency_case_sets[attempts[0]["input_style"]].add(attempts[0]["case_id"])
            if not attempts[0]["omitted_required_fields"]:
                complete_emergency_case_sets[attempts[0]["input_style"]].add(attempts[0]["case_id"])
    paired_emergency_cases = len(emergency_case_sets.get("narrative", set()) & emergency_case_sets.get("fragmented", set()))
    emergency_pairs_complete = emergency_case_sets.get("narrative", set()) == emergency_case_sets.get("fragmented", set())
    complete_source_pairs = len(
        complete_emergency_case_sets.get("narrative", set())
        & complete_emergency_case_sets.get("fragmented", set())
    )
    complete_source_by_style: dict[str, dict[str, Any]] = {}
    for arm in arms:
        complete_source_by_style[arm] = {}
        for style in ("narrative", "fragmented"):
            style_groups = [
                attempts
                for (row_arm, department, _), attempts in grouped.items()
                if row_arm == arm
                and department == "emergency"
                and attempts[0]["input_style"] == style
                and not attempts[0]["omitted_required_fields"]
            ]
            if style_groups:
                complete_source_by_style[arm][style] = _slice_metrics(style_groups, arm, rule_types)

    try:
        source_log = str(log_path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        source_log = str(log_path)
    return {
        "source_log": source_log,
        "arms": arms,
        "departments": departments,
        "overall": overall,
        "by_arm_and_department": breakdown,
        "by_arm_department_and_input_style": by_style,
        "emergency_complete_source_by_arm_and_input_style": complete_source_by_style,
        "bc_first_attempt_pairing": _bc_first_attempt_pairing(grouped),
        "emergency_paired_design": {
            "paired_cases": paired_emergency_cases,
            "complete_source_paired_cases": complete_source_pairs,
            "case_sets_identical": emergency_pairs_complete,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate an existing generation JSONL log")
    parser.add_argument("log", type=Path)
    parser.add_argument("--json", action="store_true", help="print machine-readable metrics")
    parser.add_argument("--report", type=Path, help="also write a Markdown report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = evaluate_log(args.log)
    if args.report:
        from src.report import write_report

        write_report(metrics, args.report)
    if args.json or not args.report:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
