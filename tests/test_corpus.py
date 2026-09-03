from pathlib import Path

from scripts.make_dictations import EMERGENCY_CASES, INTERNAL_CASES


ROOT = Path(__file__).resolve().parents[1]
DICTATIONS = ROOT / "data" / "dictations"


def test_fixed_corpus_has_twenty_records_per_department():
    assert len(INTERNAL_CASES) == 20
    assert len(EMERGENCY_CASES) == 20
    assert len(list(DICTATIONS.glob("im_*.txt"))) == 20
    assert len(list(DICTATIONS.glob("em_*.txt"))) == 20
    assert all(path.read_text(encoding="utf-8").strip() for path in DICTATIONS.glob("*.txt"))


def test_styles_are_deliberately_different():
    internal = "\n".join(path.read_text(encoding="utf-8") for path in DICTATIONS.glob("im_*.txt"))
    emergency = "\n".join(path.read_text(encoding="utf-8") for path in DICTATIONS.glob("em_*.txt"))
    assert "电话响了" not in internal
    assert "刚复测生命体征" not in internal
    assert "刚复测生命体征" in emergency
    assert "有人打断了" in emergency


def test_about_one_third_of_emergency_cases_omit_required_source_information():
    required_source_keys = {"time", "complaint", "history", "allergy", "v1", "exam", "diagnosis", "treatment", "disposition"}
    incomplete = sum(not required_source_keys.issubset(case) or "SpO2" not in case["v1"] for case in EMERGENCY_CASES)
    assert incomplete == 6
