"""Реестр схем: имена файлов соответствуют const, стартовые декларации валидны."""

import json

from vn.content.lint import _iter_declarations, _load_doc
from vn.schemas import SchemaRegistry


def test_registry_loads(repo_root):
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert len(reg.schemas) >= 15
    for sid, schema in reg.schemas.items():
        assert schema["properties"]["schema"]["const"] == sid
        assert schema.get("additionalProperties") is False, f"{sid}: additionalProperties должен быть false"


def test_all_starter_declarations_valid(repo_root):
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    errors = []
    seen = 0
    for path in _iter_declarations(repo_root):
        if not path.is_file():
            continue
        seen += 1
        data = _load_doc(path)
        errors += reg.validate(data, path.relative_to(repo_root).as_posix())
    assert seen >= 10, "стартовые декларации не найдены — сломан _iter_declarations?"
    assert errors == []


def test_unknown_schema_and_missing_field(repo_root):
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert any("неизвестная схема" in e for e in reg.validate({"schema": "nope@9"}, "x"))
    assert any("отсутствует обязательное поле schema" in e for e in reg.validate({}, "x"))
