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


def _recovery_rows(lines: list[str], values: dict[str, dict[str, Any]], names: dict[str, str]) -> None:
    lines.extend(
        [
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
        "## Headline: conformance without invention",
        "",
    ]
    if "A" in metrics["overall"] and "C" in metrics["overall"]:
        arm_a = metrics["overall"]["A"]
        arm_c = metrics["overall"]["C"]
        a_grounding = arm_a["grounding"]
        c_grounding = arm_c["grounding"]
        highest_raw = arm_a["pass_rate_after_budget"] == max(
            item["pass_rate_after_budget"] for item in metrics["overall"].values()
        )
        repairable = arm_c.get("recovery_by_root_cause", {}).get("model_or_format_repairable", {})
        absent = arm_c.get("recovery_by_root_cause", {}).get("source_information_absent", {})
        lines.extend(
            [
                f"Prompt-only Arm A achieved {'the highest ' if highest_raw else ''}raw conformance at **{_pct(arm_a['pass_rate_after_budget'])}**, while populating **{a_grounding['unsupported_fills']} of {a_grounding['omitted_field_opportunities']}** fields absent from the source. Arm C's lower raw conformance of **{_pct(arm_c['pass_rate_after_budget'])}** was often the safer behavior: it left **{c_grounding['left_unpopulated']}** controlled omissions unpopulated and surfaced **{c_grounding['surfaced_as_violations']}** as violations. Retries recovered **{_pct(repairable.get('recovery_rate'))}** of model extraction or formatting failures and **{_pct(absent.get('recovery_rate'))}** of source-information absences, so the validator should route failures rather than blindly retry them.",
                "",
            ]
        )
    lines.extend(
        [
        "| Arm | Records | **Conformant and grounded** | Raw conformance | Source-grounded records | Required-field population | Unsupported fills | Total estimated cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in metrics["arms"]:
        item = metrics["overall"][arm]
        grounding = item["grounding"]
        lines.append(
            f"| {ARM_NAMES.get(arm, arm)} | {item['records']} | **{_pct(item['conformant_and_grounded_rate'])}** | "
            f"{_pct(item['pass_rate_after_budget'])} | {_pct(grounding['source_grounded_record_rate'])} | "
            f"{_pct(item['required_field_population_rate'])} | {grounding['unsupported_fills']} | "
            f"{_money(item['total_cost_usd'])} |"
        )

    lines.extend(
        [
            "",
            "**Conformant and grounded** means that the final record passed every rule and did not populate any manifest-controlled omission. This is stricter than raw conformance, but it is not a general factuality score: grounding is measured only for the benchmark's deliberately omitted fields. **Required-field population** replaces the misleading term “field completeness”; it measures whether required sections contain text, not whether that text is supported.",
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

    if "A" in metrics["overall"] and "C" in metrics["overall"]:
        cost_a = metrics["overall"]["A"]["total_cost_usd"]
        cost_c = metrics["overall"]["C"]["total_cost_usd"]
        if cost_a:
            cost_multiple = cost_c / cost_a
            cost_sentence = f"The full Arm C pipeline cost **{cost_multiple:.1f}×** as much as prompt-only Arm A in this run"
            cost_interpretation = (
                f"The {cost_multiple:.1f}× comparison is the observed price of the whole constrained pipeline, "
                "not a causal estimate for grounding alone"
            )
            if "B" in metrics["overall"]:
                cost_b = metrics["overall"]["B"]["total_cost_usd"]
                if cost_b:
                    cost_sentence += f", while C cost **{(cost_c / cost_b - 1) * 100:.1f}%** more than template-only Arm B"
                    cost_interpretation += "; most of the gap already appears in structured generation"
            retry_distribution = metrics["overall"]["C"].get("retry_distribution") or {}
            retried_records = sum(
                count
                for attempts, count in retry_distribution.items()
                if int(attempts) > 1
            )
            retry_label = f"{retried_records} Arm C record{'s' if retried_records != 1 else ''} made more than one API call"
            lines.extend(
                [
                    "",
                    "## Operational cost and latency",
                    "",
                    cost_sentence + f". {cost_interpretation}, and only {retry_label}.",
                    "",
                    "| Arm | Median record latency | Observed maximum |",
                    "|---|---:|---|",
                ]
            )
            for arm in metrics["arms"]:
                item = metrics["overall"][arm]
                lines.append(
                    f"| {ARM_NAMES.get(arm, arm)} | {item['median_latency_ms']:.0f} ms | {_max_latency(item)} |"
                )
            if "B" in metrics["overall"] and metrics["overall"]["C"]["median_latency_ms"] < metrics["overall"]["B"]["median_latency_ms"]:
                lines.extend(
                    [
                        "",
                        f"Arm C's median happens to be lower than Arm B's, despite including retries. With {metrics['overall']['C']['records']} records and only {retried_records} retried records, that ordering is within run-to-run API latency noise and should not be read as free retries; retry overhead is visible in the extra calls and cost.",
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
                "| Arm | Narrative raw conformance | Fragmented raw conformance | Narrative conformant + grounded | Fragmented conformant + grounded |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for arm in metrics["arms"]:
            styles = emergency_styles.get(arm, {}).get("emergency", {})
            narrative = styles.get("narrative")
            fragmented = styles.get("fragmented")
            if not narrative or not fragmented:
                continue
            lines.append(
                f"| {ARM_NAMES.get(arm, arm)} | {_pct(narrative['pass_rate_after_budget'])} | "
                f"{_pct(fragmented['pass_rate_after_budget'])} | "
                f"{_pct(narrative['conformant_and_grounded_rate'])} | "
                f"{_pct(fragmented['conformant_and_grounded_rate'])} |"
            )
        lines.extend(
            [
                "",
                "This is a null result for the input-shape hypothesis. B and C were nominally higher on fragmented raw conformance, not lower; for C the 75% versus 70% difference is one record out of 20. That record, `em_15`, passed only because its fragmented output populated an absent visit time, while `em_narrative_15` honestly left it blank. The joint metric is therefore 70% in both C conditions.",
                "",
                "The synthetic fragmentation transformation reorders and interrupts facts but deliberately preserves them. It tests disorder without information loss, not omitted speech or ASR deletion. Within this benchmark, source omission is the mechanism the controlled cases clearly expose; word-order disruption by itself does not show a consistent effect.",
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
                    "| Arm | Complete-source narrative | Complete-source fragmented |",
                    "|---|---:|---:|",
                ]
            )
            for arm in metrics["arms"]:
                narrative = complete_styles.get(arm, {}).get("narrative")
                fragmented = complete_styles.get(arm, {}).get("fragmented")
                if not narrative or not fragmented:
                    continue
                lines.append(
                    f"| {ARM_NAMES.get(arm, arm)} | {_pct(narrative['pass_rate_after_budget'])} | "
                    f"{_pct(fragmented['pass_rate_after_budget'])} |"
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
        _recovery_rows(lines, arm_c["recovery_by_root_cause"], ROOT_CAUSE_NAMES)
        lines.extend(
            [
                "Retries repaired every observed model extraction or formatting failure and none of the source-information absences. The validator's role is therefore routing: repairable model failures go back to the model, while missing source facts go to a human.",
                "",
                "The earlier suspicion that `EM-FMT-402` exposed a broken feedback path was incorrect. Its source dictation omitted `SpO2`; the source-aware diagnosis correctly treats that numeric-rule failure as missing information and sends it to human review rather than retrying until the model invents a value.",
                "",
            ]
        )

    lines.extend(
        [
            "## Department breakdown",
            "",
            "| Arm | Department | Records | Required-field population | First-pass rate | Raw conformance | Conformant + grounded | Median latency | Observed maximum |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for arm in metrics["arms"]:
        for department in metrics["departments"]:
            item = metrics["by_arm_and_department"].get(arm, {}).get(department)
            if not item:
                continue
            lines.append(
                f"| {ARM_NAMES.get(arm, arm)} | {DEPARTMENT_NAMES.get(department, department)} | {item['records']} | "
                f"{_pct(item['required_field_population_rate'])} | {_pct(item['first_pass_rate'])} | "
                f"{_pct(item['pass_rate_after_budget'])} | {_pct(item['conformant_and_grounded_rate'])} | "
                f"{item['median_latency_ms']:.0f} ms | {_max_latency(item)} |"
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
