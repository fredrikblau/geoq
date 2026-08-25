from api.text import normalize_farsi
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_normalize_farsi_unifies_arabic_characters_and_spacing():
    assert normalize_farsi("  كي‌ک  ") == "کی ک"


def test_normalize_farsi_removes_directional_marks_without_changing_words():
    assert normalize_farsi("قشم\u200e، هرمز\u200f") == "قشم، هرمز"


def test_normalize_farsi_is_safe_for_empty_text():
    assert normalize_farsi("") == ""


def test_project_name_is_geoq():
    assert 'name = "geoq"' in (ROOT / "pyproject.toml").read_text()


def test_tourism_knowledge_files_have_a_consistent_schema():
    for path in sorted(ROOT.glob("qa_*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        assert records, path.name
        assert all({"id", "question", "answer"} <= set(record) for record in records)
        assert all(record["question"].strip() and record["answer"].strip() for record in records)


def test_tourism_knowledge_ids_are_unique_within_each_file():
    for path in sorted(ROOT.glob("qa_*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        ids = [record["id"] for record in records]
        assert len(ids) == len(set(ids)), path.name
