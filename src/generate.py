"""Run the three-arm conformance experiment and log every model attempt."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.schema import RecordSchema, load_schema
from src.validator import (
    PARSE_FAILURE_ID,
    ParsedRecord,
    field_completeness,
    has_numeric_field,
    parse_record,
    render_record,
    validate_record,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
RESULTS_DIR = ROOT / "results"
DEFAULT_MODEL = "gpt-4o-2024-08-06"
DEFAULT_SEED = 7
DEFAULT_TEMPERATURE = 0.2
PARSE_FAILURE_MESSAGE = "输出无法解析为规定结构"


@dataclass(frozen=True)
class ModelResult:
    text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str
    system_fingerprint: str | None


@dataclass(frozen=True)
class RunConfig:
    model: str
    seed: int
    temperature: float
    input_cost_per_million: float
    output_cost_per_million: float


@dataclass(frozen=True)
class SourceRecord:
    record_id: str
    case_id: str
    department: str
    input_style: str
    schema: RecordSchema
    dictation: str
    omitted_required_fields: tuple[str, ...]
    omitted_field_rule_ids: dict[str, str]


def _rule_description(schema: RecordSchema) -> str:
    descriptions: list[str] = []
    for section in schema.sections:
        status = "必填" if section.required else "可选"
        descriptions.append(f"{section.label}为{status}项，位置顺序为{section.order}")
        for rule in section.rules:
            if rule.type != "required":
                descriptions.append(rule.message)
    descriptions.extend(rule.message for rule in schema.global_rules)
    return "；".join(descriptions) + "。"


def _json_shape(schema: RecordSchema) -> str:
    example = {section.id: "" for section in schema.sections}
    return json.dumps(example, ensure_ascii=False, indent=2)


def _structured_output_schema(schema: RecordSchema) -> dict[str, Any]:
    properties = {
        section.id: {
            "type": "string",
            "description": f"{section.label}；原始口述未提供时填写空字符串，禁止猜测",
        }
        for section in schema.sections
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"{schema.department}_record",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


def build_messages(
    arm: str,
    schema: RecordSchema,
    dictation: str,
    retry_messages: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build a fresh request; retries never include the previous generated record."""
    common = (
        "你负责把一段完全虚构的中文临床口述整理为病历。只能使用口述中明确出现的事实，"
        "不得补充、推断或编造患者信息。保持临床含义，不要评价诊疗质量。"
        "如果口述之后还有一条消息，其中每一行都是上次违反的规则消息；重新生成时修正能从口述中修正的项，"
        "但仍不得编造缺失事实。"
    )
    if arm == "A":
        instructions = (
            f"请用自然的临床病历自由文本作答，不要输出JSON。该科室文书标准用文字描述如下："
            f"{_rule_description(schema)}没有提供的事实不要生成对应内容。只输出病历正文。"
        )
    else:
        instructions = (
            f"请按{schema.display_name}科室字段整理为JSON。字段形状如下：\n{_json_shape(schema)}\n"
            "每个值必须是字符串；未在口述中提供的事实填空字符串，禁止用‘未提供’等占位词绕过必填检查。"
            f"合规要求：{_rule_description(schema)}只输出JSON对象。"
        )
    messages = [
        {"role": "developer", "content": common + instructions},
        {"role": "user", "content": f"原始虚构口述：\n{dictation}"},
    ]
    if retry_messages:
        messages.append({"role": "user", "content": "\n".join(retry_messages)})
    return messages


def call_model(
    client: OpenAI,
    config: RunConfig,
    messages: list[dict[str, str]],
    response_format: dict[str, Any] | None,
) -> ModelResult:
    request: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "seed": config.seed,
        "max_completion_tokens": 1800,
    }
    if response_format is not None:
        request["response_format"] = response_format
    started = time.perf_counter()
    response = client.chat.completions.create(**request)
    latency_ms = round((time.perf_counter() - started) * 1000)
    if not response.choices:
        text = ""
    else:
        text = response.choices[0].message.content or ""
    usage = response.usage
    return ModelResult(
        text=text,
        latency_ms=latency_ms,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        model=response.model,
        system_fingerprint=response.system_fingerprint,
    )


def _parse_structured(text: str, schema: RecordSchema) -> tuple[dict[str, Any], ParsedRecord | None, list[str]]:
    try:
        decoded = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}, None, [PARSE_FAILURE_ID]
    if not isinstance(decoded, dict):
        return {}, None, [PARSE_FAILURE_ID]
    failures = validate_record(decoded, schema)
    return decoded, None, failures


def _feedback_messages(violations: list[str], schema: RecordSchema) -> list[str]:
    rule_by_id = schema.rule_by_id
    messages: list[str] = []
    for rule_id in violations:
        if rule_id == PARSE_FAILURE_ID:
            messages.append(PARSE_FAILURE_MESSAGE)
        elif rule_id in rule_by_id:
            messages.append(rule_by_id[rule_id].message)
    return messages


def _partition_retry_rules(
    violations: list[str],
    schema: RecordSchema,
    dictation: str,
) -> tuple[list[str], list[str]]:
    """Separate model-repairable rules from gaps that require human input."""
    retryable: list[str] = []
    human_review: list[str] = []
    for rule_id in violations:
        if rule_id == PARSE_FAILURE_ID:
            retryable.append(rule_id)
            continue
        rule = schema.rule_by_id[rule_id]
        if rule.type == "required":
            human_review.append(rule_id)
        elif rule.type == "numeric_fields" and any(
            not has_numeric_field(dictation, field_name) for field_name in rule.value
        ):
            human_review.append(rule_id)
        else:
            retryable.append(rule_id)
    return retryable, human_review


def _cost_usd(result: ModelResult, config: RunConfig) -> float:
    return round(
        result.input_tokens * config.input_cost_per_million / 1_000_000
        + result.output_tokens * config.output_cost_per_million / 1_000_000,
        8,
    )


def _log_attempt(handle, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def run_record(
    client: OpenAI,
    config: RunConfig,
    record_id: str,
    arm: str,
    schema: RecordSchema,
    dictation: str,
    log_handle,
    start_attempt: int = 1,
    retry_messages: list[str] | None = None,
    case_id: str | None = None,
    input_style: str = "unknown",
    omitted_required_fields: tuple[str, ...] = (),
    omitted_field_rule_ids: dict[str, str] | None = None,
) -> None:
    max_attempts = 3 if arm == "C" else 1
    feedback = list(retry_messages or [])
    response_format = None if arm == "A" else _structured_output_schema(schema)

    for attempt in range(start_attempt, max_attempts + 1):
        messages = build_messages(arm, schema, dictation, feedback or None)
        result = call_model(client, config, messages, response_format)
        if arm == "A":
            parsed = parse_record(result.text, schema)
            structured_record: dict[str, Any] = parsed.sections
            violations = validate_record(parsed, schema)
            rendered = result.text
            completeness = field_completeness(parsed, schema)
        else:
            structured_record, _, violations = _parse_structured(result.text, schema)
            rendered = render_record(structured_record, schema) if structured_record else ""
            completeness = field_completeness(structured_record, schema) if structured_record else 0.0
        retryable_rule_ids, human_review_rule_ids = _partition_retry_rules(violations, schema, dictation)

        _log_attempt(
            log_handle,
            {
                "record_id": record_id,
                "case_id": case_id or record_id,
                "arm": arm,
                "department": schema.department,
                "input_style": input_style,
                "attempt": attempt,
                "violated_rule_ids": violations,
                "retryable_rule_ids": retryable_rule_ids,
                "human_review_rule_ids": human_review_rule_ids,
                "feedback_messages": list(feedback),
                "omitted_required_fields": list(omitted_required_fields),
                "omitted_field_rule_ids": dict(omitted_field_rule_ids or {}),
                "structured_record": structured_record,
                "field_completeness": round(completeness, 6),
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated_cost_usd": _cost_usd(result, config),
                "input_cost_per_million_usd": config.input_cost_per_million,
                "output_cost_per_million_usd": config.output_cost_per_million,
                "requested_model": config.model,
                "model": result.model,
                "system_fingerprint": result.system_fingerprint,
                "seed": config.seed,
                "temperature": config.temperature,
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "output_text": result.text,
                "rendered_record": rendered,
            },
        )
        if not violations or arm != "C" or not retryable_rule_ids:
            return
        feedback = _feedback_messages(retryable_rule_ids, schema)


def _load_resume_rows(path: Path, config: RunConfig) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if not path.stat().st_size:
        return grouped
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"cannot resume: invalid JSON on line {line_number}") from exc
            expected_config = {
                "requested_model": config.model,
                "seed": config.seed,
                "temperature": config.temperature,
                "input_cost_per_million_usd": config.input_cost_per_million,
                "output_cost_per_million_usd": config.output_cost_per_million,
            }
            for key, expected in expected_config.items():
                if row.get(key) != expected:
                    raise ValueError(f"cannot resume: {key} differs on line {line_number}")
            grouped[(row["record_id"], row["arm"])].append(row)

    for key, attempts in grouped.items():
        attempts.sort(key=lambda row: row["attempt"])
        actual = [row["attempt"] for row in attempts]
        if actual != list(range(1, len(attempts) + 1)):
            raise ValueError(f"cannot resume: non-contiguous attempts for {key}: {actual}")
        arm = key[1]
        if arm != "C" and len(attempts) != 1:
            raise ValueError(f"cannot resume: arm {arm} has multiple attempts for {key[0]}")
        if len(attempts) > 3:
            raise ValueError(f"cannot resume: attempt budget exceeded for {key}")
    return grouped


def _resume_point(
    prior: list[dict[str, Any]], arm: str, schema: RecordSchema
) -> tuple[bool, int, list[str] | None]:
    if not prior:
        return False, 1, None
    retryable = prior[-1].get("retryable_rule_ids", prior[-1]["violated_rule_ids"])
    if arm != "C" or not prior[-1]["violated_rule_ids"] or not retryable or len(prior) == 3:
        return True, len(prior) + 1, None
    return False, len(prior) + 1, _feedback_messages(retryable, schema)


def discover_records(
    departments: set[str],
    limit: int | None = None,
    input_styles: set[str] | None = None,
) -> list[SourceRecord]:
    schemas = {
        "internal_medicine": load_schema(SCHEMA_DIR / "internal_medicine.json"),
        "emergency": load_schema(SCHEMA_DIR / "emergency.json"),
    }
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    raw_records = manifest.get("records") if isinstance(manifest, dict) else None
    if not isinstance(raw_records, list):
        raise ValueError("data/manifest.json must contain a records list")

    records: list[SourceRecord] = []
    per_group_count: dict[tuple[str, str], int] = defaultdict(int)
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            raise ValueError(f"manifest record {index} must be an object")
        record_id = raw.get("record_id")
        case_id = raw.get("case_id")
        department = raw.get("department")
        input_style = raw.get("input_style")
        relative_path = raw.get("dictation_path")
        omitted = raw.get("omitted_required_fields")
        omission_rules = raw.get("omitted_field_rule_ids")
        if not all(isinstance(value, str) and value for value in (record_id, case_id, department, input_style, relative_path)):
            raise ValueError(f"manifest record {index} has invalid identity fields")
        if record_id in seen_ids:
            raise ValueError(f"duplicate manifest record_id: {record_id}")
        seen_ids.add(record_id)
        if department not in schemas:
            raise ValueError(f"manifest record {record_id} has unknown department {department}")
        if not isinstance(omitted, list) or not all(isinstance(field, str) and field for field in omitted):
            raise ValueError(f"manifest record {record_id} has invalid omitted_required_fields")
        if not isinstance(omission_rules, dict) or set(omission_rules) != set(omitted):
            raise ValueError(f"manifest record {record_id} must map every omitted field to a rule ID")
        if not all(isinstance(rule_id, str) and rule_id for rule_id in omission_rules.values()):
            raise ValueError(f"manifest record {record_id} has an invalid omission rule ID")
        if department not in departments or (input_styles is not None and input_style not in input_styles):
            continue
        group = (department, input_style)
        if limit is not None and per_group_count[group] >= limit:
            continue
        per_group_count[group] += 1
        path = (ROOT / relative_path).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
            raise ValueError(f"manifest record {record_id} has invalid dictation_path")
        records.append(
            SourceRecord(
                record_id=record_id,
                case_id=case_id,
                department=department,
                input_style=input_style,
                schema=schemas[department],
                dictation=path.read_text(encoding="utf-8").strip(),
                omitted_required_fields=tuple(omitted),
                omitted_field_rule_ids=dict(omission_rules),
            )
        )
    return records


def run_experiment(
    client: OpenAI,
    config: RunConfig,
    arms: tuple[str, ...] = ("A", "B", "C"),
    departments: set[str] | None = None,
    input_styles: set[str] | None = None,
    limit: int | None = None,
    log_path: Path | None = None,
    write_report: bool = True,
    resume: bool = False,
) -> Path:
    departments = departments or {"internal_medicine", "emergency"}
    records = discover_records(departments, limit, input_styles)
    if not records:
        raise RuntimeError("no dictation records found")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if log_path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        log_path = RESULTS_DIR / f"run_{stamp}.jsonl"
    if resume and not log_path.exists():
        raise FileNotFoundError(f"resume log does not exist: {log_path}")
    if not resume and log_path.exists():
        raise FileExistsError(f"refusing to overwrite existing log: {log_path}")
    existing = _load_resume_rows(log_path, config) if resume else {}
    expected_keys = {(record.record_id, arm) for record in records for arm in arms}
    unexpected = set(existing) - expected_keys
    if unexpected:
        raise ValueError(f"cannot resume: log contains records outside this run: {sorted(unexpected)}")

    total = len(records) * len(arms)
    completed = 0
    mode = "a" if resume else "x"
    with log_path.open(mode, encoding="utf-8") as handle:
        for record in records:
            for arm in arms:
                completed += 1
                done, start_attempt, retry_messages = _resume_point(
                    existing.get((record.record_id, arm), []), arm, record.schema
                )
                if done:
                    continue
                print(f"[{completed}/{total}] {record.record_id} arm {arm}", flush=True)
                run_record(
                    client,
                    config,
                    record.record_id,
                    arm,
                    record.schema,
                    record.dictation,
                    handle,
                    start_attempt=start_attempt,
                    retry_messages=retry_messages,
                    case_id=record.case_id,
                    input_style=record.input_style,
                    omitted_required_fields=record.omitted_required_fields,
                    omitted_field_rule_ids=record.omitted_field_rule_ids,
                )

    if write_report:
        from src.evaluate import evaluate_log
        from src.report import write_report as render_report

        shutil.copyfile(log_path, RESULTS_DIR / "final_run.jsonl")
        metrics = evaluate_log(RESULTS_DIR / "final_run.jsonl")
        render_report(metrics, RESULTS_DIR / "report.md")
    return log_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all clinical-record conformance eval arms")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--input-cost", type=float, default=float(os.getenv("OPENAI_INPUT_COST_PER_MILLION", "2.50")))
    parser.add_argument("--output-cost", type=float, default=float(os.getenv("OPENAI_OUTPUT_COST_PER_MILLION", "10.00")))
    parser.add_argument("--arms", nargs="+", choices=("A", "B", "C"), default=("A", "B", "C"))
    parser.add_argument(
        "--departments",
        nargs="+",
        choices=("internal_medicine", "emergency"),
        default=("internal_medicine", "emergency"),
    )
    parser.add_argument("--input-styles", nargs="+", choices=("narrative", "fragmented"))
    parser.add_argument("--limit", type=int, help="records per department and input style; useful for a smoke run")
    parser.add_argument("--resume-log", type=Path, help="append to a compatible partial JSONL run")
    parser.add_argument("--no-report", action="store_true", help="skip report and final-run copy")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL"),
        help="OpenAI-compatible endpoint to call instead of the OpenAI API, e.g. http://localhost:8080/v1",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set; copy .env.example to .env and add a key")
    config = RunConfig(
        model=args.model,
        seed=args.seed,
        temperature=args.temperature,
        input_cost_per_million=args.input_cost,
        output_cost_per_million=args.output_cost,
    )
    path = run_experiment(
        OpenAI(max_retries=5, base_url=args.base_url),
        config,
        arms=tuple(args.arms),
        departments=set(args.departments),
        input_styles=set(args.input_styles) if args.input_styles else None,
        limit=args.limit,
        log_path=args.resume_log,
        write_report=not args.no_report,
        resume=args.resume_log is not None,
    )
    print(f"Run log: {path}")
    if not args.no_report:
        print(f"Report: {RESULTS_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
