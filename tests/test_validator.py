from pathlib import Path

import pytest

from src.schema import RecordSchema, Rule, Section, load_schema
from src.validator import PARSE_FAILURE_ID, field_completeness, render_record, validate_record


ROOT = Path(__file__).resolve().parents[1]
IM_SCHEMA = load_schema(ROOT / "schemas" / "internal_medicine.json")
EM_SCHEMA = load_schema(ROOT / "schemas" / "emergency.json")


def single_rule_schema(rule_type, value=None, required=False):
    rule = Rule(id="TEST-001", type=rule_type, value=value, message="test")
    return RecordSchema(
        department="test",
        display_name="测试",
        sections=(Section(id="field", label="字段", required=required, order=1, rules=(rule,)),),
        global_rules=(),
        todo_verify="TODO-VERIFY",
    )


@pytest.mark.parametrize(
    ("rule_type", "value", "passing", "failing"),
    [
        ("required", None, "内容", "   "),
        ("max_length", 3, "三字", "超过三字"),
        ("min_length", 3, "三个字", "短"),
        ("must_match", r"天|日", "咳嗽3天", "咳嗽数周"),
        ("must_not_match", r"患者说", "诉咳嗽", "患者说咳嗽"),
        ("numeric_fields", ["T", "P"], "T 36.5 P:80", "T 36.5"),
        ("timestamp_format", None, "2026-09-03 14:05", "2026/09/03 14:05"),
    ],
)
def test_each_section_rule_passes_and_fails(rule_type, value, passing, failing):
    schema = single_rule_schema(rule_type, value)
    assert validate_record({"field": passing}, schema) == []
    assert validate_record({"field": failing}, schema) == ["TEST-001"]


@pytest.mark.parametrize("empty", ["", " ", "\n\t"])
def test_required_rejects_empty_and_whitespace(empty):
    schema = single_rule_schema("required", required=True)
    assert validate_record({"field": empty}, schema) == ["TEST-001"]


def test_non_required_rules_are_skipped_for_an_empty_optional_section():
    schema = single_rule_schema("must_match", r"x")
    assert validate_record({}, schema) == []


def test_fully_conforming_internal_medicine_record_returns_no_failures():
    record = {
        "chief_complaint": "咳嗽伴发热3天",
        "history_present_illness": "3天前受凉后出现咳嗽、发热，最高38.5℃，无明显胸痛及呼吸困难。",
        "past_history": "既往体健，无高血压及糖尿病史。",
        "allergy_history": "否认药物及食物过敏史。",
        "physical_exam": "T 38.2℃，P 92次/分，R 20次/分，BP 128/78 mmHg，双肺呼吸音粗。",
        "ancillary_exam": "血常规白细胞轻度升高。",
        "initial_diagnosis": "急性上呼吸道感染",
        "plan": "完善检查，予对症治疗并观察体温变化。",
    }
    assert validate_record(record, IM_SCHEMA) == []
    assert validate_record(render_record(record, IM_SCHEMA), IM_SCHEMA) == []
    assert field_completeness(record, IM_SCHEMA) == 1.0


def test_common_markdown_heading_styles_are_parseable():
    text = "\n".join(
        [
            "## **主诉**：咳嗽3天",
            "- **现病史**：3天前受凉后出现咳嗽咳痰，症状逐渐加重，无呼吸困难。",
            "3. 既往史：既往体健",
            "4、过敏史：否认药物过敏",
            "5) 体格检查：T 37.2 P 82 R 18 BP 120/76",
            "6. 初步诊断：上呼吸道感染",
            "7. 处理意见：对症治疗并随诊",
        ]
    )
    assert validate_record(text, IM_SCHEMA) == []


def test_multiple_rule_violations_are_all_returned():
    record = {
        "chief_complaint": "患者说最近一直非常不舒服而且具体持续时间完全不清楚",
        "history_present_illness": "太短",
        "past_history": "",
        "allergy_history": "否认过敏史",
        "physical_exam": "T 36.8℃",
        "initial_diagnosis": "待查",
        "plan": "观察",
    }
    failures = validate_record(record, IM_SCHEMA)
    assert failures == ["IM-LEN-002", "IM-FMT-003", "IM-TERM-004", "IM-LEN-102", "IM-REQ-201", "IM-FMT-402"]


def test_section_order_violation():
    record = {
        "history_present_illness": "症状发生于三天前，目前仍有咳嗽咳痰，病程经过记录完整。",
        "chief_complaint": "咳嗽3天",
        "past_history": "既往体健",
        "allergy_history": "无",
        "physical_exam": "T 37 P 80 R 18 BP 120/80",
        "initial_diagnosis": "上呼吸道感染",
        "plan": "对症治疗",
    }
    assert "IM-ORD-900" in validate_record(record, IM_SCHEMA)


def test_unknown_mapping_section_is_parse_failure():
    assert validate_record({"unknown": "x"}, IM_SCHEMA)[0] == PARSE_FAILURE_ID


def test_unknown_text_heading_is_parse_failure():
    text = "主诉：咳嗽3天\n神秘章节：内容"
    assert PARSE_FAILURE_ID in validate_record(text, IM_SCHEMA)


@pytest.mark.parametrize("value", ["回家", "住院", "拒绝治疗后离院"])
def test_closed_set_disposition_rejects_out_of_vocabulary_value(value):
    valid = {
        "visit_time": "2026-09-03 14:05",
        "chief_complaint": "胸痛30分钟",
        "history_present_illness": "30分钟前突发胸痛，持续不缓解，伴大汗及恶心。",
        "allergy_history": "否认药物过敏史",
        "vital_signs": "T 36.6 P 96 R 22 BP 148/92 SpO2 96",
        "physical_exam": "神清，心律齐，双肺呼吸音清。",
        "initial_diagnosis": "胸痛待查",
        "emergency_treatment": "2026-09-03 14:12 完成心电图检查。",
        "disposition": value,
    }
    assert "EM-FMT-802" in validate_record(valid, EM_SCHEMA)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-02-30 10:00", "2026-09-03 4:05", "2026-09-03 14:05:00", "2026/09/03 14:05"],
)
def test_timestamp_requires_real_date_at_minute_resolution(timestamp):
    schema = single_rule_schema("timestamp_format")
    assert validate_record({"field": timestamp}, schema) == ["TEST-001"]


def test_schema_files_have_todo_marker_and_unique_rules():
    for schema in (IM_SCHEMA, EM_SCHEMA):
        assert "TODO-VERIFY" in schema.todo_verify
        assert len(schema.rule_by_id) == sum(len(section.rules) for section in schema.sections) + len(schema.global_rules)
