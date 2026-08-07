"""Фаза 1: компиляция сцен. Юнит-тесты валидатора/эмиттера — на фабрикованном анализе
(SDK не нужен); e2e через build-bridge — skipif без RENPY_SDK."""

import os
from pathlib import Path

import pytest

from vn.content import scenes as sc


def _unit(meta=None, analysis=None, full_id="ch01_s010"):
    return sc.SceneUnit(
        full_id=full_id,
        chapter_id=full_id[:4],
        short_id=full_id[5:],
        yaml_rel=f"content/chapters/ch01_x/scenes/{full_id[5:]}_t.scene.yaml",
        rpy_rel=f"content/chapters/ch01_x/scenes/{full_id[5:]}_t.scene.rpy",
        meta=meta or {},
        rpy_text="label ch01_s010__body:\n    return\n",
        analysis=analysis or {},
    )


def _analysis(**kw):
    base = {"labels": [{"name": "ch01_s010__body", "line": 1}],
            "jumps": [], "calls": [], "returns": [], "menus": [], "says": 0, "errors": []}
    base.update(kw)
    return base


def test_label_contract_violations():
    rep = sc.SceneCompileReport()
    a = _analysis(labels=[{"name": "my_label", "line": 3},
                          {"name": "ch01_s010__body", "line": 1}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep)
    assert any("вне контракта" in e for e in rep.errors)


def test_missing_body_label():
    rep = sc.SceneCompileReport()
    a = _analysis(labels=[{"name": "ch01_s010__alt", "line": 1}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep)
    assert any("__body" in e for e in rep.errors)


def test_cross_scene_jump_forbidden():
    rep = sc.SceneCompileReport()
    a = _analysis(jumps=[{"target": "ch01_s020", "line": 5, "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010", "ch01_s020"}, "release", rep)
    assert any("вне своей сцены" in e for e in rep.errors)


def test_return_must_match_exits():
    rep = sc.SceneCompileReport()
    a = _analysis(returns=[{"expr": '"gone"', "line": 7}])
    sc.validate_scene(_unit(meta={"exits": {"done": "s020"}}, analysis=a),
                      {"ch01_s010", "ch01_s020"}, "release", rep)
    assert any("'gone' не объявлен в exits" in e for e in rep.errors)
    assert any("exits.done не достигается" in w for w in rep.warnings)


def test_draft_missing_target_becomes_fallback():
    rep = sc.SceneCompileReport()
    a = _analysis(returns=[{"expr": '"done"', "line": 7}])
    dispatch = sc.validate_scene(_unit(meta={"exits": {"done": "s099"}}, analysis=a),
                                 {"ch01_s010"}, "draft", rep)
    assert rep.errors == []
    assert dispatch["done"][0]["to_label"] is None      # draft: уйдёт на «сцена недоступна»
    assert any("не существует" in w for w in rep.warnings)


def test_emit_scene_wrapper():
    rep = sc.SceneCompileReport()
    unit = _unit(meta={"exits": {"done": "s020"}})
    dispatch = {"done": [{"to_label": "ch01_s020", "when": None}]}
    text = sc.emit_scene(unit, dispatch, set(), rep, "# header\n")
    assert 'label ch01_s010:' in text
    assert '$ vn.checkpoint("ch01_s010")' in text
    assert 'call ch01_s010__body from _call_ch01_s010__body' in text
    assert 'if _return == "done":\n        jump ch01_s020' in text
    assert 'jump vn_scene_unavailable' in text
    assert unit.rpy_text.strip() in text                # авторский источник скопирован


SDK = os.environ.get("RENPY_SDK")


@pytest.mark.skipif(not (SDK and (Path(SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_e2e_demo_chapter_compiles(repo_root, tmp_path):
    """Сквозная компиляция реальной демо-главы через build-bridge."""
    from vn.content.compile import compile_content

    gen = tmp_path / "generated"
    res = compile_content(repo_root, out_dir=gen)
    s010 = (gen / "scenes/ch01/ch01_s010.gen.rpy").read_text(encoding="utf-8")
    assert 'if _return == "gate":\n        jump ch01_s020' in s010
    assert 'if _return == "roof":\n        jump ch01_s030' in s010
    chapters = (gen / "registry/chapters.gen.rpy").read_text(encoding="utf-8")
    assert "'entry_label': 'ch01_s010'" in chapters
    assert (gen / "screens/chapter_select.gen.rpy").is_file()

    res2 = compile_content(repo_root, out_dir=gen)      # анализ из кэша, байт-в-байт
    assert res2.written == []
