"""Compute conformance metrics from an existing attempt log."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


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
            rows.append(row)
    if not rows:
        raise ValueError(f"empty run log: {path}")
    return rows


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])


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
    return grouped


def _slice_metrics(record_groups: list[list[dict[str, Any]]], arm: str) -> dict[str, Any]:
    first_rows = [attempts[0] for attempts in record_groups]
    final_rows = [attempts[-1] for attempts in record_groups]
    record_latency = [sum(row["latency_ms"] for row in attempts) for attempts in record_groups]
    record_cost = [sum(float(row.get("estimated_cost_usd", 0.0)) for row in attempts) for attempts in record_groups]
    first_failures = Counter(rule_id for row in first_rows for rule_id in row["violated_rule_ids"])
    first_pass_rate = fmean(not row["violated_rule_ids"] for row in first_rows)
    pass_rate_after_budget = fmean(not row["violated_rule_ids"] for row in final_rows)
    metrics: dict[str, Any] = {
        "records": len(record_groups),
        "field_completeness": fmean(float(row["field_completeness"]) for row in final_rows),
        "first_pass_rate": first_pass_rate,
        "final_pass_rate": pass_rate_after_budget if arm == "C" else None,
        "pass_rate_after_budget": pass_rate_after_budget,
        "mean_latency_ms": fmean(record_latency),
        "p95_latency_ms": percentile_95(record_latency),
        "total_cost_usd": sum(record_cost),
        "mean_cost_usd": fmean(record_cost),
        "per_rule_failures": dict(first_failures.most_common()),
        "retry_distribution": None,
        "unrecoverable": [],
    }
    if arm == "C":
        metrics["retry_distribution"] = dict(sorted(Counter(len(attempts) for attempts in record_groups).items()))
        metrics["unrecoverable"] = [
            {"record_id": attempts[-1]["record_id"], "violated_rule_ids": attempts[-1]["violated_rule_ids"]}
            for attempts in record_groups
            if len(attempts) == 3 and attempts[-1]["violated_rule_ids"]
        ]
    return metrics


def evaluate_log(path: str | Path) -> dict[str, Any]:
    log_path = Path(path)
    rows = read_log(log_path)
    grouped = _group_records(rows)
    arms = sorted({key[0] for key in grouped})
    departments = sorted({key[1] for key in grouped})
    overall: dict[str, Any] = {}
    breakdown: dict[str, dict[str, Any]] = {}
    for arm in arms:
        arm_groups = [attempts for (row_arm, _, _), attempts in grouped.items() if row_arm == arm]
        overall[arm] = _slice_metrics(arm_groups, arm)
        breakdown[arm] = {}
        for department in departments:
            department_groups = [
                attempts
                for (row_arm, row_department, _), attempts in grouped.items()
                if row_arm == arm and row_department == department
            ]
            if department_groups:
                breakdown[arm][department] = _slice_metrics(department_groups, arm)
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
