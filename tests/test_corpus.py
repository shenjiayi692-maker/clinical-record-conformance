import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.make_dictations import EMERGENCY_CASES, INTERNAL_CASES


ROOT = Path(__file__).resolve().parents[1]
DICTATIONS = ROOT / "data" / "dictations"
MANIFEST = ROOT / "data" / "manifest.json"


def manifest_records():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]


def test_fixed_corpus_has_twenty_records_per_control_group():
    assert len(INTERNAL_CASES) == 20
    assert len(EMERGENCY_CASES) == 20
    assert len(list(DICTATIONS.glob("im_*.txt"))) == 20
    assert len(list(DICTATIONS.glob("em_*.txt"))) == 20
    assert len(list((DICTATIONS / "emergency_narrative").glob("em_narrative_*.txt"))) == 20
    assert len(manifest_records()) == 60
    groups = Counter((row["department"], row["input_style"]) for row in manifest_records())
    assert groups == {
        ("internal_medicine", "narrative"): 20,
        ("emergency", "fragmented"): 20,
        ("emergency", "narrative"): 20,
    }


def test_emergency_versions_share_case_facts_but_not_input_shape():
    by_case = defaultdict(list)
    for row in manifest_records():
        if row["department"] == "emergency":
            by_case[row["case_id"]].append(row)
    assert len(by_case) == 20
    for pair in by_case.values():
        assert {row["input_style"] for row in pair} == {"narrative", "fragmented"}
        assert len({row["source_fact_sha256"] for row in pair}) == 1
        assert len({tuple(row["omitted_required_fields"]) for row in pair}) == 1

    fragmented = "\n".join(path.read_text(encoding="utf-8") for path in DICTATIONS.glob("em_*.txt"))
    narrative = "\n".join(
        path.read_text(encoding="utf-8") for path in (DICTATIONS / "emergency_narrative").glob("*.txt")
    )
    assert "电话响了" in fragmented
    assert "有人打断了" in fragmented
    assert "电话响了" not in narrative
    assert "急诊连续口述" in narrative


def test_manifest_marks_six_incomplete_emergency_cases_in_each_style():
    by_style = defaultdict(list)
    for row in manifest_records():
        if row["department"] == "emergency" and row["omitted_required_fields"]:
            by_style[row["input_style"]].append(row)
            assert set(row["omitted_required_fields"]) == set(row["omitted_field_rule_ids"])
    assert len(by_style["fragmented"]) == 6
    assert len(by_style["narrative"]) == 6
    assert sum(len(row["omitted_required_fields"]) for row in by_style["fragmented"]) == 6


def test_every_manifest_path_exists_and_contains_only_fictional_corpus_text():
    for row in manifest_records():
        path = ROOT / row["dictation_path"]
        assert path.is_file()
        assert path.read_text(encoding="utf-8").strip()
