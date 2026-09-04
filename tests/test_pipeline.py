import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evaluate import evaluate_log
from src.generate import ModelResult, RunConfig, build_messages, run_experiment, run_record
from src.report import render_report
from src.schema import load_schema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_schema(ROOT / "schemas" / "internal_medicine.json")
EM_SCHEMA = load_schema(ROOT / "schemas" / "emergency.json")
CONFIG = RunConfig(
    model="test-model",
    seed=7,
    temperature=0.2,
    input_cost_per_million=1.0,
    output_cost_per_million=2.0,
)
CONFORMING = {
    "chief_complaint": "咳嗽3天",
    "history_present_illness": "3天前受凉后出现咳嗽咳痰，症状逐渐加重，无呼吸困难。",
    "past_history": "既往体健",
    "allergy_history": "否认药物过敏",
    "physical_exam": "T 37.2 P 82 R 18 BP 120/76",
    "ancillary_exam": "",
    "initial_diagnosis": "上呼吸道感染",
    "plan": "对症治疗并随诊",
}
EM_CONFORMING = {
    "visit_time": "2026-09-03 14:05",
    "chief_complaint": "胸痛30分钟",
    "history_present_illness": "30分钟前突发胸痛，持续不缓解，伴出汗和恶心。",
    "allergy_history": "否认药物过敏",
    "vital_signs": "T 36.6 P 96 R 22 BP 148/92 SpO2 96",
    "physical_exam": "神清，心律齐，双肺呼吸音清",
    "ancillary_exam": "心电图已完成",
    "initial_diagnosis": "胸痛待查",
    "emergency_treatment": "2026-09-03 14:12 完成心电监护",
    "disposition": "留观",
}


def model_result(payload):
    return ModelResult(
        text=json.dumps(payload, ensure_ascii=False),
        latency_ms=10,
        input_tokens=100,
        output_tokens=50,
        model="test-model-snapshot",
        system_fingerprint="fp_test",
    )


def test_retry_uses_only_rule_messages_and_not_previous_output(monkeypatch):
    outputs = [model_result({"chief_complaint": "咳嗽"}), model_result(CONFORMING)]
    calls = []

    def fake_call(client, config, messages, response_format):
        calls.append(messages)
        return outputs.pop(0)

    monkeypatch.setattr("src.generate.call_model", fake_call)
    handle = io.StringIO()
    run_record(object(), CONFIG, "im_01", "C", SCHEMA, "虚构口述", handle)
    rows = [json.loads(line) for line in handle.getvalue().splitlines()]
    assert len(rows) == 2
    assert rows[0]["violated_rule_ids"]
    assert rows[1]["violated_rule_ids"] == []
    assert all(rows[0]["output_text"] not in message["content"] for message in calls[1])
    assert "主诉须包含主要症状（或体征）的持续时间" in calls[1][-1]["content"]
    assert all(
        line in {rule.message for rule in SCHEMA.rule_by_id.values()}
        for line in calls[1][-1]["content"].splitlines()
    )
    assert rows[0]["seed"] == 7
    assert rows[0]["estimated_cost_usd"] == pytest.approx(0.0002)
    assert rows[1]["feedback_messages"] == calls[1][-1]["content"].splitlines()


def test_malformed_json_is_parse_failure_and_counts_as_attempt(monkeypatch):
    outputs = [
        ModelResult("not json", 5, 10, 4, "test", None),
        model_result(CONFORMING),
    ]
    monkeypatch.setattr("src.generate.call_model", lambda *args, **kwargs: outputs.pop(0))
    handle = io.StringIO()
    run_record(object(), CONFIG, "im_01", "C", SCHEMA, "虚构口述", handle)
    rows = [json.loads(line) for line in handle.getvalue().splitlines()]
    assert rows[0]["violated_rule_ids"] == ["PARSE-000"]
    assert rows[0]["field_completeness"] == 0.0
    assert rows[1]["attempt"] == 2


def test_arm_a_prompt_is_free_text_and_has_no_json_shape():
    messages = build_messages("A", SCHEMA, "口述")
    assert "不要输出JSON" in messages[0]["content"]
    assert '"chief_complaint"' not in messages[0]["content"]


def test_evaluator_uses_first_failures_and_end_to_end_retry_latency(tmp_path):
    log_path = tmp_path / "run.jsonl"
    rows = [
        {"record_id": "im_01", "arm": "A", "department": "internal_medicine", "attempt": 1, "violated_rule_ids": ["IM-REQ-001"], "field_completeness": 0.5, "latency_ms": 100, "estimated_cost_usd": 0.01},
        {"record_id": "im_01", "arm": "C", "department": "internal_medicine", "attempt": 1, "violated_rule_ids": ["IM-REQ-001"], "field_completeness": 0.5, "latency_ms": 100, "estimated_cost_usd": 0.01},
        {"record_id": "im_01", "arm": "C", "department": "internal_medicine", "attempt": 2, "violated_rule_ids": [], "field_completeness": 1.0, "latency_ms": 150, "estimated_cost_usd": 0.02},
    ]
    log_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    metrics = evaluate_log(log_path)
    arm_c = metrics["overall"]["C"]
    assert arm_c["first_pass_rate"] == 0.0
    assert arm_c["final_pass_rate"] == 1.0
    assert arm_c["pass_rate_after_budget"] == 1.0
    assert arm_c["field_completeness"] == 1.0
    assert arm_c["median_latency_ms"] == 250
    assert arm_c["max_latency_ms"] == 250
    assert arm_c["max_latency_attempts"] == 2
    assert arm_c["retry_distribution"] == {2: 1}
    assert arm_c["per_rule_failures"] == {"IM-REQ-001": 1}
    report = render_report(metrics)
    assert "Three-arm result" in report
    assert "Median record latency" in report
    assert "p95" not in report
    assert "First-attempt failures by rule" in report
    assert "Unresolved after retry policy" in report


def test_fake_client_runs_all_three_arms_end_to_end(monkeypatch, tmp_path):
    from src import generate

    def fake_call(client, config, messages, response_format):
        emergency = "急诊" in messages[0]["content"]
        payload = EM_CONFORMING if emergency else CONFORMING
        if response_format is None:
            schema = load_schema(ROOT / "schemas" / ("emergency.json" if emergency else "internal_medicine.json"))
            text = "\n".join(f"{section.label}：{payload[section.id]}" for section in schema.sections)
            return ModelResult(text, 8, 80, 40, "test-model", "fp_test")
        return model_result(payload)

    monkeypatch.setattr(generate, "call_model", fake_call)
    monkeypatch.setattr(generate, "RESULTS_DIR", tmp_path)
    log_path = tmp_path / "run_test.jsonl"
    run_experiment(object(), CONFIG, limit=1, log_path=log_path)
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 9
    assert all(row["violated_rule_ids"] == [] for row in rows)
    assert (tmp_path / "final_run.jsonl").is_file()
    assert "Three-arm result" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_resume_skips_finished_paths_and_continues_c_attempt_number(monkeypatch, tmp_path):
    from src import generate

    prior_rows = [
        {
            "record_id": "im_01",
            "case_id": "im_01",
            "arm": "A",
            "department": "internal_medicine",
            "input_style": "narrative",
            "attempt": 1,
            "omitted_required_fields": [],
            "omitted_field_rule_ids": {},
            "violated_rule_ids": [],
            "field_completeness": 1.0,
            "latency_ms": 10,
            "estimated_cost_usd": 0.0001,
            "requested_model": CONFIG.model,
            "model": CONFIG.model,
            "seed": CONFIG.seed,
            "temperature": CONFIG.temperature,
            "input_cost_per_million_usd": CONFIG.input_cost_per_million,
            "output_cost_per_million_usd": CONFIG.output_cost_per_million,
        },
        {
            "record_id": "im_01",
            "case_id": "im_01",
            "arm": "C",
            "department": "internal_medicine",
            "input_style": "narrative",
            "attempt": 1,
            "omitted_required_fields": [],
            "omitted_field_rule_ids": {},
            "violated_rule_ids": ["IM-FMT-003"],
            "field_completeness": 1.0,
            "latency_ms": 10,
            "estimated_cost_usd": 0.0001,
            "requested_model": CONFIG.model,
            "model": CONFIG.model,
            "seed": CONFIG.seed,
            "temperature": CONFIG.temperature,
            "input_cost_per_million_usd": CONFIG.input_cost_per_million,
            "output_cost_per_million_usd": CONFIG.output_cost_per_million,
        },
    ]
    log_path = tmp_path / "partial.jsonl"
    log_path.write_text("".join(json.dumps(row) + "\n" for row in prior_rows), encoding="utf-8")
    calls = []

    def fake_call(client, config, messages, response_format):
        calls.append(messages)
        return model_result(CONFORMING)

    monkeypatch.setattr(generate, "call_model", fake_call)
    monkeypatch.setattr(generate, "RESULTS_DIR", tmp_path)
    run_experiment(
        object(),
        CONFIG,
        departments={"internal_medicine"},
        limit=1,
        log_path=log_path,
        resume=True,
    )
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert [(row["arm"], row["attempt"]) for row in rows[-2:]] == [("B", 1), ("C", 2)]
    assert "主诉须包含主要症状（或体征）的持续时间" in calls[-1][-1]["content"]


def test_missing_spo2_is_routed_to_human_review_without_retry(monkeypatch):
    missing_spo2 = {**EM_CONFORMING, "vital_signs": "T 36.6 P 96 R 22 BP 148/92"}
    outputs = [model_result(missing_spo2)]
    calls = []

    def fake_call(client, config, messages, response_format):
        calls.append(messages)
        return outputs.pop(0)

    monkeypatch.setattr("src.generate.call_model", fake_call)
    handle = io.StringIO()
    run_record(
        object(),
        CONFIG,
        "em_09",
        "C",
        EM_SCHEMA,
        "虚构口述中没有SpO2",
        handle,
        case_id="em_case_09",
        input_style="fragmented",
        omitted_required_fields=("vital_signs.SpO2",),
        omitted_field_rule_ids={"vital_signs.SpO2": "EM-FMT-402"},
    )
    rows = [json.loads(line) for line in handle.getvalue().splitlines()]
    assert len(rows) == 1
    assert len(calls) == 1
    assert rows[0]["violated_rule_ids"] == ["EM-FMT-402"]
    assert rows[0]["retryable_rule_ids"] == []
    assert rows[0]["human_review_rule_ids"] == ["EM-FMT-402"]
    assert "SpO2" not in rows[-1]["structured_record"]["vital_signs"]


def test_present_spo2_allows_format_feedback_and_retry(monkeypatch):
    missing_from_output = {**EM_CONFORMING, "vital_signs": "T 36.6 P 96 R 22 BP 148/92"}
    outputs = [model_result(missing_from_output), model_result(EM_CONFORMING)]
    calls = []

    def fake_call(client, config, messages, response_format):
        calls.append(messages)
        return outputs.pop(0)

    monkeypatch.setattr("src.generate.call_model", fake_call)
    handle = io.StringIO()
    run_record(
        object(),
        CONFIG,
        "em_complete_source",
        "C",
        EM_SCHEMA,
        "生命体征 T 36.6 P 96 R 22 BP 148/92 SpO2 96",
        handle,
    )
    rows = [json.loads(line) for line in handle.getvalue().splitlines()]
    feedback = EM_SCHEMA.rule_by_id["EM-FMT-402"].message
    assert len(rows) == 2
    assert rows[0]["retryable_rule_ids"] == ["EM-FMT-402"]
    assert rows[0]["human_review_rule_ids"] == []
    assert calls[1][-1]["content"] == feedback
    assert rows[1]["feedback_messages"] == [feedback]
    assert rows[1]["violated_rule_ids"] == []


def test_grounding_recovery_types_and_bc_pairing_are_mechanical(tmp_path):
    shared_gap = {
        "case_id": "case_gap",
        "department": "emergency",
        "input_style": "fragmented",
        "omitted_required_fields": ["disposition"],
        "omitted_field_rule_ids": {"disposition": "EM-REQ-801"},
        "field_completeness": 0.9,
        "latency_ms": 10,
        "estimated_cost_usd": 0.01,
    }
    shared_format = {
        "case_id": "case_format",
        "department": "emergency",
        "input_style": "fragmented",
        "omitted_required_fields": [],
        "omitted_field_rule_ids": {},
        "field_completeness": 1.0,
        "latency_ms": 10,
        "estimated_cost_usd": 0.01,
    }
    rows = [
        {**shared_gap, "record_id": "gap", "arm": "A", "attempt": 1, "violated_rule_ids": [], "structured_record": {"disposition": "离院"}},
        {**shared_gap, "record_id": "gap", "arm": "B", "attempt": 1, "violated_rule_ids": ["EM-REQ-801"], "structured_record": {"disposition": ""}},
        {**shared_gap, "record_id": "gap", "arm": "C", "attempt": 1, "violated_rule_ids": ["EM-REQ-801"], "structured_record": {"disposition": ""}},
        {**shared_format, "record_id": "format", "arm": "B", "attempt": 1, "violated_rule_ids": ["EM-FMT-802"], "structured_record": {"disposition": "拟留观"}},
        {**shared_format, "record_id": "format", "arm": "C", "attempt": 1, "violated_rule_ids": ["EM-FMT-802"], "structured_record": {"disposition": "拟留观"}},
        {**shared_format, "record_id": "format", "arm": "C", "attempt": 2, "violated_rule_ids": [], "structured_record": {"disposition": "留观"}},
    ]
    path = tmp_path / "grounding.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    metrics = evaluate_log(path)

    assert metrics["overall"]["A"]["grounding"]["unsupported_fills"] == 1
    assert metrics["overall"]["C"]["grounding"] == {
        "omitted_field_opportunities": 1,
        "unsupported_fills": 0,
        "records_with_unsupported_fills": 0,
        "source_grounded_records": 2,
        "source_grounded_record_rate": 1.0,
        "left_unpopulated": 1,
        "surfaced_as_violations": 1,
    }
    assert metrics["overall"]["C"]["recovery_by_failure_class"]["required"]["recovery_rate"] == 0.0
    assert metrics["overall"]["C"]["recovery_by_failure_class"]["format_terminology_order"]["recovery_rate"] == 1.0
    assert metrics["overall"]["C"]["recovery_by_root_cause"]["source_information_absent"]["remaining"] == 1
    assert metrics["overall"]["C"]["recovery_by_root_cause"]["model_or_format_repairable"]["recovered"] == 1
    assert metrics["bc_first_attempt_pairing"]["same_structured_outputs"] == 2
    report = render_report(metrics)
    assert "Arm A produced content for **1 of 1**" in report
    assert "Source information absent" in report
