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


def test_var_write_not_in_registry_is_error():
    """Запись атрибута управляемого стора вне реестра — молчаливый фантом (G5)."""
    rep = sc.SceneCompileReport()
    a = _analysis(var_writes=["ch01.met_mirs"], var_reads=[])   # опечатка в имени
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      var_registry={"ch01.met_mira", "g.route"})
    assert any("ch01.met_mirs" in e and "Variable Registry" in e for e in rep.errors)


def test_var_read_ok_when_declared():
    rep = sc.SceneCompileReport()
    a = _analysis(var_reads=["ch01.met_mira"], var_writes=[])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      var_registry={"ch01.met_mira"})
    assert rep.errors == []


def test_var_draft_downgrades_to_warning():
    rep = sc.SceneCompileReport()
    a = _analysis(var_writes=["g.phantom"])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "draft", rep, var_registry=set())
    assert rep.errors == []
    assert any("g.phantom" in w for w in rep.warnings)


def test_var_manifest_mismatch_warns_only_when_declared():
    # автор объявил writes, но фактически пишет другое -> предупреждение
    rep = sc.SceneCompileReport()
    a = _analysis(var_writes=["ch01.met_mira"])
    sc.validate_scene(_unit(meta={"vars": {"writes": ["ch01.other"]}}, analysis=a),
                      {"ch01_s010"}, "release", rep,
                      var_registry={"ch01.met_mira", "ch01.other"})
    assert any("не указан в vars.writes" in w for w in rep.warnings)
    assert any("vars.writes.ch01.other объявлен" in w for w in rep.warnings)
    # без var_registry (старый вызов) — проверок переменных нет вовсе
    rep2 = sc.SceneCompileReport()
    sc.validate_scene(_unit(analysis=_analysis(var_writes=["x.y"])), {"ch01_s010"},
                      "release", rep2)
    assert rep2.errors == []


def _index(exact=(), tags=(), layered=None, available=True):
    from vn.content.images import ImageIndex

    return ImageIndex(exact={tuple(e) for e in exact}, tags=set(tags),
                      layered={k: set(v) for k, v in (layered or {}).items()},
                      available=available)


def test_show_unknown_image_is_error():
    """Опечатка в `show` — исключение движка у игрока; ловить обязан билд."""
    rep = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 4, "kind": "scene",
                               "name": ["bg", "gate", "nite"], "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      image_index=_index(exact=[("bg", "gate", "day")], tags=["bg"]))
    assert any("bg gate nite" in e and "нет в собранных ассетах" in e for e in rep.errors)


def test_show_unknown_tag_gets_hint():
    rep = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 2, "kind": "show",
                               "name": ["mirra", "happy"], "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      image_index=_index(tags=["mira"], layered={"mira": ["happy"]}))
    assert any("тега 'mirra' нет вовсе" in e for e in rep.errors)


def test_layeredimage_attribute_validated():
    rep = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 3, "kind": "show",
                               "name": ["mira", "hapy"], "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      image_index=_index(tags=["mira"],
                                         layered={"mira": ["stand", "happy", "sad"]}))
    assert any("нет атрибут(ов) hapy" in e for e in rep.errors)

    ok = sc.SceneCompileReport()
    a2 = _analysis(image_refs=[{"line": 3, "kind": "show",
                                "name": ["mira", "stand", "happy"], "expression": False}])
    sc.validate_scene(_unit(analysis=a2), {"ch01_s010"}, "release", ok,
                      image_index=_index(tags=["mira"],
                                         layered={"mira": ["stand", "happy"]}))
    assert ok.errors == []


def test_hide_validates_tag_only():
    """hide адресует тег: атрибуты движок игнорирует, и валидатор тоже."""
    ok = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 9, "kind": "hide",
                               "name": ["mira", "whatever"], "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", ok,
                      image_index=_index(tags=["mira"], layered={"mira": ["stand"]}))
    assert ok.errors == []

    bad = sc.SceneCompileReport()
    a2 = _analysis(image_refs=[{"line": 9, "kind": "hide",
                                "name": ["ghost"], "expression": False}])
    sc.validate_scene(_unit(analysis=a2), {"ch01_s010"}, "release", bad,
                      image_index=_index(tags=["mira"]))
    assert any("hide ghost" in e for e in bad.errors)


def test_show_expression_forbidden():
    rep = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 5, "kind": "show", "name": None, "expression": True}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      image_index=_index(tags=["mira"]))
    assert any("show expression" in e for e in rep.errors)


def test_image_refs_skipped_when_assets_not_built():
    """Без собранной game/assets индекс пуст — сверка молчит, иначе на свежем
    клоне падала бы каждая ссылка."""
    rep = sc.SceneCompileReport()
    a = _analysis(image_refs=[{"line": 4, "kind": "show",
                               "name": ["anything", "at", "all"], "expression": False}])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      image_index=_index(available=False))
    assert rep.errors == []


def test_undeclared_audio_is_error():
    rep = sc.SceneCompileReport()
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": "clam_theme", "channel": None},
        {"line": 5, "stmt": "play sound", "file": "door_slam", "channel": None},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      audio_ids={"calm_theme", "door_slam"})
    assert any("play music clam_theme" in e for e in rep.errors)
    assert not any("door_slam" in e for e in rep.errors)


def test_audio_literal_and_expression_skipped():
    """Строковый литерал и сложное выражение статически не разрешаются — не ругаемся."""
    rep = sc.SceneCompileReport()
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": '"assets/audio/bgm/x.ogg"', "channel": None},
        {"line": 5, "stmt": "play music", "file": "tracks[i]", "channel": None},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep, audio_ids=set())
    assert rep.errors == []


def test_refs_draft_downgrades_to_warning():
    rep = sc.SceneCompileReport()
    a = _analysis(
        image_refs=[{"line": 4, "kind": "show", "name": ["ghost"], "expression": False}],
        audio_refs=[{"line": 5, "stmt": "play music", "file": "nope", "channel": None}],
    )
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "draft", rep,
                      image_index=_index(tags=["mira"]), audio_ids=set())
    assert rep.errors == []
    assert len(rep.warnings) == 2


def test_build_image_index_sources(tmp_path):
    """Индекс собирается из тех же источников, что и emit_images."""
    from vn.content.images import build_image_index

    root = tmp_path / "repo"
    (root / "game" / "assets" / "cg" / "ep1").mkdir(parents=True)
    (root / "game" / "assets" / "cg" / "ep1" / "kiss.webp").write_bytes(b"x")
    (root / "game" / "assets" / "cg" / "ep1" / "kiss@2.webp").write_bytes(b"x")
    (root / "game" / "assets" / "cg" / "ep1" / "kiss.thumb.webp").write_bytes(b"x")
    spr = root / "game" / "assets" / "spr" / "mira"
    (spr / "stand" / "outfits").mkdir(parents=True)
    (spr / "stand" / "faces").mkdir(parents=True)
    (spr / "stand" / "base.webp").write_bytes(b"x")
    (spr / "stand" / "outfits" / "school.webp").write_bytes(b"x")
    (spr / "stand" / "faces" / "happy.webp").write_bytes(b"x")
    (spr / "side").mkdir(parents=True)
    (spr / "side" / "base.webp").write_bytes(b"x")

    locations = {"gate": {"id": "gate", "backgrounds": {"day": "assets/bg/gate/day.webp"}}}
    chars = [("content/characters/mira/character.yaml", {
        "id": "mira",
        "matrix": {"poses": ["stand"], "outfits": ["school"], "emotions": ["happy"]},
    })]
    idx = build_image_index(root, locations, chars)

    assert idx.available
    assert ("bg", "gate", "day") in idx.exact
    assert ("cg", "ep1", "kiss") in idx.exact
    assert ("cg", "ep1", "kiss@2") not in idx.exact      # вариант, не отдельный образ
    assert ("cg", "ep1", "kiss.thumb") not in idx.exact  # миниатюра галереи
    assert ("side", "mira") in idx.exact
    assert idx.layered["mira"] == {"stand", "school", "happy"}
    assert ("vn_black",) in idx.exact                    # служебный образ framework


def test_emit_scene_wrapper():
    rep = sc.SceneCompileReport()
    unit = _unit(meta={"exits": {"done": "s020"}})
    dispatch = {"done": [{"to_label": "ch01_s020", "when": None}]}
    text = sc.emit_scene(unit, dispatch, set(), {}, rep, "# header\n")
    assert 'label ch01_s010:' in text
    assert '$ vn.checkpoint("ch01_s010")' in text
    # scene чистит только master — слой sprites обвязка чистит явно (иначе утечка спрайтов)
    assert '$ renpy.scene("sprites")' in text
    assert "scene vn_black with dissolve" in text       # без локации — нейтральный фон
    assert 'call ch01_s010__body from _call_ch01_s010__body' in text
    assert 'if _return == "done":\n        jump ch01_s020' in text
    assert 'jump vn_scene_unavailable' in text
    assert unit.rpy_text.strip() in text                # авторский источник скопирован


def test_emit_scene_location():
    locations = {"gate": {"id": "gate", "backgrounds": {"day": "assets/bg/gate/day.webp"}}}
    rep = sc.SceneCompileReport()
    text = sc.emit_scene(_unit(meta={"location": "gate/day"}), {}, set(), locations, rep, "# h\n")
    assert "scene bg gate day with dissolve" in text
    assert rep.errors == []

    rep2 = sc.SceneCompileReport()
    text2 = sc.emit_scene(_unit(meta={"location": "gate/night"}), {}, set(), locations, rep2, "# h\n")
    assert any("нет варианта 'night'" in e for e in rep2.errors)
    assert "scene vn_black" in text2                    # fallback при невалидной локации

    rep3 = sc.SceneCompileReport()
    sc.emit_scene(_unit(meta={"location": "gate"}), {}, set(), locations, rep3, "# h\n")
    assert any("без варианта" in e for e in rep3.errors)


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
