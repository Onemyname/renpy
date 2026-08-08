"""Достижения (achievements@1): эмиссия реестра и валидация якорей.
Ачивки привязаны к стабильным якорям (scene/beat/var), поэтому добавляются
без правки уже написанных и переведённых сцен."""

import pytest

from vn.content.compile import _emit_achievements


def _doc(**achievements):
    return [("content/achievements/core.achievements.yaml",
             {"schema": "achievements@1", "achievements": achievements})]


def test_emit_registry_with_defaults():
    docs = _doc(
        met={"name_key": "ach.met.name", "trigger": {"var": "ch01.met_mira"}},
        roof={"name_key": "ach.roof.name", "desc_key": "ach.roof.desc",
              "hidden": True, "nsfw": True, "pack": "nsfw",
              "trigger": {"scene": "ch01_s030"}},
    )
    text = _emit_achievements(docs, [("src", "deadbeef")])
    assert "define VN_ACHIEVEMENTS = " in text
    # var-триггер без equals получает дефолт True (иначе рантайму пришлось бы гадать)
    assert "'equals': True" in text
    assert "'pack': 'core'" in text          # дефолт пака
    assert "'nsfw': True" in text and "'hidden': True" in text


def test_emit_empty_is_valid():
    text = _emit_achievements([], [("project.yaml", "0")])
    assert "define VN_ACHIEVEMENTS = {}" in text


def test_schema_rejects_multiple_triggers(repo_root):
    """oneOf: ровно один якорь — иначе неоднозначно, когда выдавать."""
    from vn.schemas import SchemaRegistry

    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    bad = {"schema": "achievements@1", "achievements": {
        "roof_reached": {"name_key": "a.b",
                         "trigger": {"scene": "ch01_s010", "beat": "kiss"}}}}
    assert reg.validate(bad, "test") != []

    good = {"schema": "achievements@1", "achievements": {
        "roof_reached": {"name_key": "a.b", "trigger": {"scene": "ch01_s010"}}}}
    assert reg.validate(good, "test") == []


def test_repo_achievements_are_valid(repo_root):
    """Боевые декларации проходят схему и ссылаются на существующие якоря."""
    from vn.repo import load_yaml
    from vn.schemas import SchemaRegistry

    path = repo_root / "content" / "achievements" / "core.achievements.yaml"
    if not path.is_file():
        pytest.skip("деклараций достижений нет")
    doc = load_yaml(path)
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, path.name) == []

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    for aid, spec in doc["achievements"].items():
        assert spec["name_key"] in strings, f"{aid}: name_key вне strings.yaml"
        if spec.get("desc_key"):
            assert spec["desc_key"] in strings, f"{aid}: desc_key вне strings.yaml"
