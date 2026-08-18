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

# ── Версии схем: документ не имеет права отстать от реестра ───────────────────

def _mk_registry(tmp_path, *versions):
    """Реестр из синтетических схем demo@N (каждая — пустой объект с полем schema)."""
    d = tmp_path / "schemas"
    d.mkdir(exist_ok=True)
    for name, ver in versions:
        sid = f"{name}@{ver}"
        (d / f"{sid}.schema.json").write_text(json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"vn:schemas/{sid}",
            "title": sid,
            "type": "object",
            "properties": {"schema": {"const": sid}},
            "required": ["schema"],
            "additionalProperties": False,
        }), encoding="utf-8")
    return SchemaRegistry(d)


def test_registry_tracks_newest_version(tmp_path):
    reg = _mk_registry(tmp_path, ("demo", 1), ("demo", 2), ("solo", 1))
    assert reg.newest == {"demo": 2, "solo": 1}


def test_document_on_outdated_schema_is_an_error(tmp_path):
    """Реестр держит версии рядом, поэтому документ на @1 валиден сам по себе —
    и молча разойдётся с кодом, написанным под @2. Гейт делает это красным."""
    reg = _mk_registry(tmp_path, ("demo", 1), ("demo", 2))
    errors = reg.validate({"schema": "demo@1"}, "content/demo.yaml")
    assert len(errors) == 1
    assert "устаревшей схеме demo@1" in errors[0] and "demo@2" in errors[0]


def test_newest_version_document_passes(tmp_path):
    reg = _mk_registry(tmp_path, ("demo", 1), ("demo", 2))
    assert reg.validate({"schema": "demo@2"}, "content/demo.yaml") == []


def test_single_version_schema_is_never_stale(tmp_path):
    """Схема без более новой версии не должна порождать ложную ошибку — иначе
    гейт краснел бы на всём проекте."""
    reg = _mk_registry(tmp_path, ("solo", 1))
    assert reg.validate({"schema": "solo@1"}, "content/solo.yaml") == []


def test_repo_has_no_documents_left_on_old_schemas(repo_root):
    """Гейт полезен, только если репозиторий ему соответствует: ни одна авторская
    декларация не осталась на предыдущей версии схемы."""
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    stale = []
    for path in _iter_declarations(repo_root):
        if not path.is_file():
            continue
        sid = (_load_doc(path) or {}).get("schema")
        if not isinstance(sid, str):
            continue
        name, _, ver = sid.partition("@")
        if ver.isdigit() and int(ver) < reg.newest.get(name, 0):
            stale.append(f"{path.relative_to(repo_root).as_posix()}: {sid}")
    assert stale == [], "документы на устаревших схемах: " + ", ".join(stale)
