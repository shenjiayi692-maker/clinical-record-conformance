"""Render evaluation metrics as plain Markdown tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEPARTMENT_NAMES = {"internal_medicine": "Internal medicine", "emergency": "Emergency"}
STYLE_NAMES = {"narrative": "Narrative", "fragmented": "Fragmented", "unknown": "Unknown"}
ARM_NAMES = {
    "A": "A — prompt only",
    "B": "B — template constrained",
    "C": "C — template + validator loop",
}
RULE_TYPE_NAMES = {
    "required": "Required",
    "max_length": "Maximum length",
    "min_length": "Minimum length",
    "must_match": "Required pattern",
    "must_not_match": "Forbidden pattern",
    "numeric_fields": "Numeric fields",
    "section_order": "Section order",
    "timestamp_format": "Timestamp format",
    "parse": "Parse/structure",
    "unknown": "Unknown",
}
FAILURE_CLASS_NAMES = {
    "required": "Required information",
    "format_terminology_order": "Format / terminology / order",
    "parse_structure": "Parse / structure",
}
ROOT_CAUSE_NAMES = {
    "source_information_absent": "Source information absent",
    "model_or_format_repairable": "Model extraction or formatting",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _money(value: float) -> str:
    return f"${value:.4f}"


def _max_latency(item: dict[str, Any]) -> str:
    calls = item.get("max_latency_attempts", 1)
    record_id = item.get("max_latency_record_id", "unknown")
    return f"{item['max_latency_ms']:.0f} ms (`{record_id}`, {calls} call{'s' if calls != 1 else ''})"


def _recovery_rows(lines: list[str], title: str, values: dict[str, dict[str, Any]], names: dict[str, str]) -> None:
    lines.extend(
        [
            f"### {title}",
            "",
            "| Failure group | Initial instances | Recovered | Remaining | Recovery rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    if not values:
        lines.append("| — | 0 | 0 | 0 | — |")
    else:
        for key, item in values.items():
            lines.append(
                f"| {names.get(key, key)} | {item['initial_failures']} | {item['recovered']} | "
                f"{item['remaining']} | {_pct(item['recovery_rate'])} |"
            )
    lines.append("")


def render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Clinical record conformance evaluation",
        "",
        f"Source log: `{metrics['source_log']}`",
        "",
        "## Three-arm result",
        "",
        "| Arm | Records | Source-grounded records | Field completeness | Pass rate after arm budget | Median record latency | Observed maximum | Unsupported fills | Total estimated cost |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for arm in metrics["arms"]:
        item = metrics["overall"][arm]
        grounding = item["grounding"]
        lines.append(
            f"| {ARM_NAMES.get(arm, arm)} | {item['records']} | {_pct(grounding['source_grounded_record_rate'])} | "
            f"{_pct(item['field_completeness'])} | {_pct(item['pass_rate_after_budget'])} | "
            f"{item['median_latency_ms']:.0f} ms | {_max_latency(item)} | {grounding['unsupported_fills']} | "
            f"{_money(item['total_cost_usd'])} |"
        )

    lines.extend(
        [
            "",
            "Field completeness is measured on final outputs and is not a grounding metric. Latency is end-to-end per record; Arm C includes all validator retries. The observed maximum identifies the record and API-call count so a single API tail is not presented as a population percentile.",
            "",
            "## Ground-truth omission check",
            "",
            "The corpus manifest records every intentionally absent required field or required subfield. Populating one of those fields is mechanically counted as an unsupported fill, regardless of whether the prose sounds plausible.",
            "",
            "| Arm | Absent-source opportunities | Populated despite absence | Records with unsupported fills | Source-grounded record rate | Left unpopulated | Surfaced as violations |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in metrics["arms"]:
        item = metrics["overall"][arm]["grounding"]
        lines.append(
            f"| {ARM_NAMES.get(arm, arm)} | {item['omitted_field_opportunities']} | {item['unsupported_fills']} | "
            f"{item['records_with_unsupported_fills']} | {_pct(item['source_grounded_record_rate'])} | "
            f"{item['left_unpopulated']} | {item['surfaced_as_violations']} |"
        )
    if "A" in metrics["overall"] and "C" in metrics["overall"]:
        arm_a = metrics["overall"]["A"]["grounding"]
        arm_c = metrics["overall"]["C"]["grounding"]
        lines.extend(
            [
                "",
                f"Arm A produced content for **{arm_a['unsupported_fills']} of {arm_a['omitted_field_opportunities']}** required fields or subfields that were absent from the source dictation. Arm C left **{arm_c['left_unpopulated']} of {arm_c['omitted_field_opportunities']}** unpopulated and surfaced **{arm_c['surfaced_as_violations']}** as rule violations.",
            ]
        )

    emergency_styles = metrics.get("by_arm_department_and_input_style", {})
    paired = metrics.get("emergency_paired_design", {})
    if paired.get("paired_cases"):
        lines.extend(
            [
                "",
                "## Paired emergency input-shape control",
                "",
                f"The same {paired['paired_cases']} synthetic emergency cases were rendered twice from identical source-fact fingerprints. The emergency schema and generation settings stayed fixed; only dictation shape changed.",
                "",
                "| Arm | Narrative conformance | Fragmented conformance | Fragmented minus narrative | Narrative source-grounded | Fragmented source-grounded |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for arm in metrics["arms"]:
            styles = emergency_styles.get(arm, {}).get("emergency", {})
            narrative = styles.get("narrative")
            fragmented = styles.get("fragmented")
            if not narrative or not fragmented:
                continue
            delta = fragmented["pass_rate_after_budget"] - narrative["pass_rate_after_budget"]
            lines.append(
                f"| {ARM_NAMES.get(arm, arm)} | {_pct(narrative['pass_rate_after_budget'])} | "
                f"{_pct(fragmented['pass_rate_after_budget'])} | {delta * 100:+.1f} pp | "
                f"{_pct(narrative['grounding']['source_grounded_record_rate'])} | "
                f"{_pct(fragmented['grounding']['source_grounded_record_rate'])} |"
            )
        lines.extend(
            [
                "",
                "Holding the record standard constant, this table isolates the effect of narrative versus fragmented dictation instead of conflating input shape with department schema size.",
            ]
        )
        complete_pairs = paired.get("complete_source_paired_cases", 0)
        complete_styles = metrics.get("emergency_complete_source_by_arm_and_input_style", {})
        if complete_pairs:
            lines.extend(
                [
                    "",
                    f"The following sensitivity check excludes the six emergency cases with intentional source omissions, leaving {complete_pairs} complete-source pairs:",
                    "",
                    "| Arm | Complete-source narrative | Complete-source fragmented | Fragmented minus narrative |",
                    "|---|---:|---:|---:|",
                ]
            )
            for arm in metrics["arms"]:
                narrative = complete_styles.get(arm, {}).get("narrative")
                fragmented = complete_styles.get(arm, {}).get("fragmented")
                if not narrative or not fragmented:
                    continue
                delta = fragmented["pass_rate_after_budget"] - narrative["pass_rate_after_budget"]
                lines.append(
                    f"| {ARM_NAMES.get(arm, arm)} | {_pct(narrative['pass_rate_after_budget'])} | "
                    f"{_pct(fragmented['pass_rate_after_budget'])} | {delta * 100:+.1f} pp |"
                )

    pairing = metrics.get("bc_first_attempt_pairing", {})
    if pairing.get("records"):
        lines.extend(
            [
                "",
                "## First-attempt pairing check",
                "",
                f"Arms B and C use the same first-attempt prompt, model snapshot, seed, and temperature. Their aggregate per-rule failure counts {'matched exactly' if pairing.get('aggregate_rule_failure_counts_match') else 'did not match'}, while record-level failure sets matched for **{pairing['same_failure_sets']} of {pairing['records']}** records and structured outputs matched for **{pairing['same_structured_outputs']} of {pairing['records']}** records. Seeded API output is best-effort rather than bitwise deterministic, so retry benefit is measured within Arm C from its own first attempt to its final attempt.",
            ]
        )

    arm_c = metrics.get("overall", {}).get("C")
    if arm_c:
        lines.extend(["", "## Arm C failure diagnosis", ""])
        _recovery_rows(lines, "By operational failure class", arm_c["recovery_by_failure_class"], FAILURE_CLASS_NAMES)
        _recovery_rows(lines, "By rule type", arm_c["recovery_by_rule_type"], RULE_TYPE_NAMES)
        _recovery_rows(lines, "By source-aware root cause", arm_c["recovery_by_root_cause"], ROOT_CAUSE_NAMES)
        lines.extend(
            [
                "A rule's syntax does not by itself determine recoverability. For example, a `numeric_fields` failure caused by a source dictation that omits `SpO2` is a source-information absence, not a broken feedback loop. The appropriate action is to surface the gap for human completion, not regenerate until a value appears.",
                "",
            ]
        )

    lines.extend(
        [
            "## Department breakdown",
            "",
            "| Arm | Department | Records | Field completeness | First-pass rate | Pass rate after arm budget | Median latency | Observed maximum |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for arm in metrics["arms"]:
        for department in metrics["departments"]:
            item = metrics["by_arm_and_department"].get(arm, {}).get(department)
            if not item:
                continue
            lines.append(
                f"| {ARM_NAMES.get(arm, arm)} | {DEPARTMENT_NAMES.get(department, department)} | {item['records']} | "
                f"{_pct(item['field_completeness'])} | {_pct(item['first_pass_rate'])} | "
                f"{_pct(item['pass_rate_after_budget'])} | {item['median_latency_ms']:.0f} ms | {_max_latency(item)} |"
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

    lines.extend(
        [
            "## Arm C retry distribution",
            "",
            "| Department | Input style | 1 attempt | 2 attempts | 3 attempts |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for department in metrics["departments"]:
        styles = emergency_styles.get("C", {}).get(department, {})
        for style, item in styles.items():
            distribution = item["retry_distribution"] or {}
            lines.append(
                f"| {DEPARTMENT_NAMES.get(department, department)} | {STYLE_NAMES.get(style, style)} | "
                f"{distribution.get(1, distribution.get('1', 0))} | {distribution.get(2, distribution.get('2', 0))} | "
                f"{distribution.get(3, distribution.get('3', 0))} |"
            )

    lines.extend(
        [
            "",
            "## Unresolved after retry policy",
            "",
            "| Department | Input style | Record | Attempts | Remaining rule IDs | Next action |",
            "|---|---|---|---:|---|---|",
        ]
    )
    unrecoverable_count = 0
    for department in metrics["departments"]:
        item = metrics["by_arm_and_department"].get("C", {}).get(department)
        if not item:
            continue
        for case in item["unrecoverable"]:
            unrecoverable_count += 1
            rules = ", ".join(f"`{rule_id}`" for rule_id in case["violated_rule_ids"])
            next_action = "Human completion required" if case.get("human_review_rule_ids") else "Model/format not recovered"
            lines.append(
                f"| {DEPARTMENT_NAMES.get(department, department)} | "
                f"{STYLE_NAMES.get(case.get('input_style', 'unknown'), case.get('input_style', 'unknown'))} | "
                f"`{case['record_id']}` | {case.get('attempts', 1)} | {rules} | {next_action} |"
            )
    if not unrecoverable_count:
        lines.append("| — | — | — | — | None | — |")
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
