import ast
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _app_source():
    return (ROOT / "api" / "app.py").read_text(encoding="utf-8")


def test_public_endpoints_are_declared():
    source = _app_source()
    assert '"/v1/chat/completions"' in source
    assert '"/health"' in source
    assert '"/v1/models"' in source


def test_message_contract_is_restricted_to_supported_roles():
    tree = ast.parse(_app_source())
    message_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Message"
    )
    role_annotation = next(
        node for node in message_class.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", "") == "role"
    )
    assert isinstance(role_annotation.annotation, ast.Subscript)
    assert {element.value for element in role_annotation.annotation.slice.elts} == {
        "system", "user", "assistant"
    }


def test_showcase_examples_use_the_public_chat_endpoint():
    showcase = (ROOT / "docs" / "SHOWCASE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert showcase.count("/v1/chat/completions") >= 1
    assert "/v1/chat/completions" in readme


def test_seed_records_have_categories_and_tags_for_filtering():
    for path in sorted(ROOT.glob("qa_*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        assert all(record.get("category") and record.get("tags") for record in records), path.name
