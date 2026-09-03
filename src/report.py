"""Render evaluation metrics as plain Markdown tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEPARTMENT_NAMES = {"internal_medicine": "Internal medicine", "emergency": "Emergency"}
ARM_NAMES = {
    "A": "A — prompt only",
    "B": "B — template constrained",
    "C": "C — template + validator loop",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _money(value: float) -> str:
    return f"${value:.4f}"


def render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Clinical record conformance evaluation",
        "",
        f"Source log: `{metrics['source_log']}`",
        "",
        "## Three-arm result",
        "",
        "| Arm | Records | Field completeness | First-pass rate | Pass rate after arm budget | Mean record latency | p95 record latency | Total estimated cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in metrics["arms"]:
        item = metrics["overall"][arm]
        lines.append(
            f"| {ARM_NAMES.get(arm, arm)} | {item['records']} | {_pct(item['field_completeness'])} | "
            f"{_pct(item['first_pass_rate'])} | {_pct(item['pass_rate_after_budget'])} | "
            f"{item['mean_latency_ms']:.0f} ms | {item['p95_latency_ms']:.0f} ms | {_money(item['total_cost_usd'])} |"
        )

    lines.extend(
        [
            "",
            "Field completeness is measured on each arm's final output. Latency is end-to-end per record: for arm C it includes every retry. Cost is estimated from the token rates recorded with each attempt.",
            "",
            "## Department breakdown",
            "",
            "| Arm | Department | Records | Field completeness | First-pass rate | Pass rate after arm budget | Mean record latency | p95 record latency |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in metrics["arms"]:
        for department in metrics["departments"]:
            item = metrics["by_arm_and_department"].get(arm, {}).get(department)
            if not item:
                continue
            lines.append(
                f"| {ARM_NAMES.get(arm, arm)} | {DEPARTMENT_NAMES.get(department, department)} | {item['records']} | "
                f"{_pct(item['field_completeness'])} | {_pct(item['first_pass_rate'])} | {_pct(item['pass_rate_after_budget'])} | "
                f"{item['mean_latency_ms']:.0f} ms | {item['p95_latency_ms']:.0f} ms |"
            )

    lines.extend(["", "## First-attempt failures by rule", ""])
    for arm in metrics["arms"]:
        for department in metrics["departments"]:
            item = metrics["by_arm_and_department"].get(arm, {}).get(department)
            if not item:
                continue
            lines.extend(
                [
                    f"### {ARM_NAMES.get(arm, arm)} · {DEPARTMENT_NAMES.get(department, department)}",
                    "",
                    "| Rule ID | First-attempt failures |",
                    "|---|---:|",
                ]
            )
            failures = item["per_rule_failures"]
            if failures:
                lines.extend(f"| `{rule_id}` | {count} |" for rule_id, count in failures.items())
            else:
                lines.append("| — | 0 |")
            lines.append("")

    lines.extend(["## Arm C retry distribution", "", "| Department | 1 attempt | 2 attempts | 3 attempts |", "|---|---:|---:|---:|"])
    for department in metrics["departments"]:
        item = metrics["by_arm_and_department"].get("C", {}).get(department)
        if not item:
            continue
        distribution = item["retry_distribution"] or {}
        lines.append(
            f"| {DEPARTMENT_NAMES.get(department, department)} | {distribution.get(1, distribution.get('1', 0))} | "
            f"{distribution.get(2, distribution.get('2', 0))} | {distribution.get(3, distribution.get('3', 0))} |"
        )

    lines.extend(["", "## Unrecoverable after three attempts", "", "| Department | Record | Remaining rule IDs |", "|---|---|---|"])
    unrecoverable_count = 0
    for department in metrics["departments"]:
        item = metrics["by_arm_and_department"].get("C", {}).get(department)
        if not item:
            continue
        for case in item["unrecoverable"]:
            unrecoverable_count += 1
            rules = ", ".join(f"`{rule_id}`" for rule_id in case["violated_rule_ids"])
            lines.append(f"| {DEPARTMENT_NAMES.get(department, department)} | `{case['record_id']}` | {rules} |")
    if not unrecoverable_count:
        lines.append("| — | — | None |")
    lines.append("")
    return "\n".join(lines)


def write_report(metrics: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(metrics), encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render metrics JSON as Markdown")
    parser.add_argument("metrics", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.metrics.open(encoding="utf-8") as handle:
        metrics = json.load(handle)
    print(write_report(metrics, args.output))


if __name__ == "__main__":
    main()
