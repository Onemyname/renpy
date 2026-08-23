"""Фаза 1: компиляция сцен. Юнит-тесты валидатора/эмиттера — на фабрикованном анализе
(SDK не нужен); e2e через build-bridge — skipif без RENPY_SDK.

Здесь же — два свойства масштаба конвейера сцен: список файлов уезжает в мост
файлом, а не argv (иначе ARG_MAX кладёт компиляцию на тысячах сцен), и вывод
однотипных предупреждений компилятора сворачивается (иначе один warning на главу
превращается в тысячи строк)."""

import json
import os
import subprocess
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

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
                      audio_tracks={"calm_theme": {"kind": "bgm"},
                                    "door_slam": {"kind": "sfx"}})
    assert any("play music clam_theme" in e for e in rep.errors)
    assert not any("door_slam" in e for e in rep.errors)


def test_audio_kind_channel_mismatch_is_error():
    """sfx на канале music занял бы канал и оборвал музыку — kind обязан
    соответствовать каналу play-оператора (C18 + канал ambient)."""
    rep = sc.SceneCompileReport()
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": "door_slam", "channel": None},
        {"line": 5, "stmt": "play ambient", "file": "rain", "channel": None},
        {"line": 6, "stmt": "play sound", "file": "door_slam", "channel": None},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep,
                      audio_tracks={"door_slam": {"kind": "sfx"},
                                    "rain": {"kind": "amb"}})
    assert any("play music door_slam" in e and "sfx" in e for e in rep.errors)
    assert len(rep.errors) == 1


def test_audio_raw_path_is_c18_violation():
    """Сырой путь в play — нарушение C18: физические пути живут только в
    декларациях content/audio/*.yaml, иначе трек выпадает из проверок и
    молча замолкает при переименовании ассета."""
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": '"assets/audio/bgm/x.ogg"', "channel": None},
        {"line": 5, "stmt": "queue sound", "file": "'sfx/door.ogg'", "channel": None},
    ])
    rep = sc.SceneCompileReport()
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep, audio_tracks={})
    assert len(rep.errors) == 2
    assert any("C18" in e and "assets/audio/bgm/x.ogg" in e for e in rep.errors)

    # Строгость — общая для ссылочных проверок (G15): draft ругается warning'ом.
    draft = sc.SceneCompileReport()
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "draft", draft, audio_tracks={})
    assert draft.errors == []
    assert len(draft.warnings) == 2


def test_audio_engine_spec_is_not_a_raw_path():
    """`<silence 3.0>` и родня — спецификация движка, а не путь: файла за ней
    может не быть вовсе, а объявить её в content/audio/*.yaml нечем. Под запрет
    сырых путей (C18) она не попадает, иначе штатная пауза стала бы ошибкой."""
    rep = sc.SceneCompileReport()
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": '"<silence 3.0>"', "channel": None},
        {"line": 5, "stmt": "queue music", "file": "'<from 2 to 5>bgm_calm'", "channel": None},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep, audio_tracks={})
    assert rep.errors == [] and rep.warnings == []


def test_audio_expression_skipped():
    """Сложное выражение статически не разрешается — молчим: иначе легальные
    формы вроде vn.voice_path(...) и выбора трека по индексу стали бы ошибкой."""
    rep = sc.SceneCompileReport()
    a = _analysis(audio_refs=[
        {"line": 4, "stmt": "play music", "file": "tracks[i]", "channel": None},
        {"line": 5, "stmt": "play voice", "file": 'vn.voice_path("ch01_s010_001")',
         "channel": None},
        {"line": 6, "stmt": "play sound", "file": '"a" + suffix', "channel": None},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep, audio_tracks={})
    assert rep.errors == [] and rep.warnings == []


def test_refs_draft_downgrades_to_warning():
    rep = sc.SceneCompileReport()
    a = _analysis(
        image_refs=[{"line": 4, "kind": "show", "name": ["ghost"], "expression": False}],
        audio_refs=[{"line": 5, "stmt": "play music", "file": "nope", "channel": None}],
    )
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "draft", rep,
                      image_index=_index(tags=["mira"]), audio_tracks={})
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


def test_emit_chapter_select_scrolls_with_pad():
    """chapter_select (C14): сетка обязана жить в vpgrid со скролл-пресетом
    vn_scroll_props и reveal-координатами карточек — прежний hbox box_wrap
    молча прятал главы за низом экрана при росте корпуса, и они были
    недостижимы ЛЮБЫМ вводом (аудит controller-first, P1 №9)."""
    text = sc.emit_chapter_select("# h\n")
    assert 'vpgrid id "vp_chapters"' in text
    assert "properties vn_scroll_props" in text
    assert "ysize gui.scroll_height" in text
    # Карточка получает row/rows — без них vn_ui.reveal не докрутит сетку к фокусу,
    # и focus_default на первой — без него default focus достаётся левой рельсе,
    # где слепой A = Start() (42-big-picture.md §5.1)
    assert "use vn_chapter_card(ch, _i // 3, _rows, focus_default=(_i == 0))" in text
    assert "box_wrap" not in text


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


def _fake_scenes(root: Path, count: int) -> list[Path]:
    scenes_dir = root / "content" / "chapters" / "ch01_scale" / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(count):
        p = scenes_dir / f"s{i:04d}_gen.scene.rpy"
        p.write_text(f"label ch01_s{i:04d}__body:\n    return\n", encoding="utf-8")
        out.append(p)
    return out


def _run_analyze(monkeypatch, root: Path, files: list[Path]) -> list[str]:
    """Прогнать analyze_scene_files с фальшивым мостом; вернуть argv вызова."""
    from vn.content import analyze as an

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        idx = cmd.index("--files-from")
        captured["listed"] = Path(cmd[idx + 1]).read_bytes()
        Path(cmd[3]).write_text(
            json.dumps({"renpy": "test", "files": {str(f): {"says": 0} for f in files}}),
            encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(an, "sdk_renpy_exe", lambda: root / "renpy.sh")
    monkeypatch.setattr(an.subprocess, "run", fake_run)
    result = an.analyze_scene_files(root, files)
    assert len(result) == len(files)
    captured["result"] = result
    return captured


def test_analyze_sends_file_list_through_file_not_argv(tmp_path, monkeypatch):
    """Регрессия масштаба: пути сцен НЕ едут в argv.

    Аргументами список ограничен ARG_MAX (~950 КБ под аргументы), то есть 6–9 тыс.
    сцен, и на 8 000 компиляция падала сырым OSError [Errno 7]. Свойство, которое
    охраняет тест: argv вызова моста не растёт вместе с корпусом (при росте числа
    сцен в 100 раз он БАЙТ-В-БАЙТ тот же), а сами пути приезжают файлом-списком.
    """
    root = tmp_path / "proj"
    small = _fake_scenes(root, 30)
    small_call = _run_analyze(monkeypatch, root, small)
    big = _fake_scenes(root, 3000)
    big_call = _run_analyze(monkeypatch, root, big)

    assert small_call["cmd"] == big_call["cmd"]          # argv не зависит от масштаба
    assert "--files-from" in big_call["cmd"]
    assert [a for a in big_call["cmd"] if a.endswith(".scene.rpy")] == []
    # Файл-список: по пути на строку, ровно \n (иначе на Windows приехал бы CRLF).
    assert big_call["listed"] == "".join(f"{f}\n" for f in big).encode("utf-8")
    # Рабочий файл убран за собой: на диске остаётся только кэш анализа.
    assert not (root / ".vncache" / "analyze-files.txt").exists()


def test_analyze_refuses_newline_in_path(tmp_path):
    """Перевод строки в пути сделал бы файл-список неоднозначным: это ошибка с
    сообщением, а не молча потерянная сцена."""
    from vn.content.analyze import AnalyzeError, write_files_listing

    with pytest.raises(AnalyzeError):
        write_files_listing(tmp_path / "files.txt", [Path("scenes/пло\nхой.scene.rpy")])


# Предупреждения, которых по одному на главу и по одному на CG: именно они растут
# линейно с контентом (на корпусе 8 000 образов — 8 000 строк вывода).
def _chapter_warnings(count: int) -> list[str]:
    return [f"ch{i:02d}: title_key 'meta.chapters.ch{i:02d}.title' нет в "
            f"content/ui/strings.yaml — в меню глав отобразится сырой ключ"
            for i in range(1, count + 1)]


def _cg_warnings(count: int) -> list[str]:
    return [f"cg/ch01/set01_{i:03d}: CG собран, но не объявлен в галерее "
            f"(content/gallery/*.gallery.yaml) — игрок его не увидит в галерее"
            for i in range(count)]


def _echo(warnings: list[str]) -> str:
    from vn import cli

    @click.command()
    def cmd():
        cli._echo_warnings(warnings)

    res = CliRunner().invoke(cmd, catch_exceptions=False)
    assert res.exit_code == 0
    return res.output


def test_cli_folds_same_kind_warnings():
    """Однотипные предупреждения печатаются примерами, а не целиком.

    Класс определяется текстом с вымаранными значениями, поэтому главы ch01…ch40
    — один класс, CG — другой, а одиночная проверка не сворачивается вовсе.
    """
    from vn import cli

    warnings = _chapter_warnings(40) + _cg_warnings(30) + [
        "audio/music/calm.ogg: трек объявлен, файла нет"]
    lines = _echo(warnings).splitlines()

    assert sum(1 for line in lines if "title_key" in line) == cli.WARN_SAMPLES
    assert sum(1 for line in lines if "CG собран" in line) == cli.WARN_SAMPLES
    assert f"warning: ещё {40 - cli.WARN_SAMPLES} однотипных (всего 40)" in lines
    assert f"warning: ещё {30 - cli.WARN_SAMPLES} однотипных (всего 30)" in lines
    # Единственное в своём классе печатается целиком: сворачивать нечего.
    assert "warning: audio/music/calm.ogg: трек объявлен, файла нет" in lines
    assert len(lines) == cli.WARN_SAMPLES * 2 + 2 + 1
    # Сворачивается только ПЕЧАТЬ: сам отчёт остаётся полным (его читают тесты,
    # release-гейт и другие команды).
    assert len(warnings) == 71


def test_cli_keeps_short_warning_lists_verbatim():
    """Пока однотипных мало, вывод совпадает с несгруппированным: агрегация не
    должна менять поведение на обычном проекте."""
    from vn import cli

    warnings = _chapter_warnings(cli.WARN_SAMPLES) + _cg_warnings(1)
    assert _echo(warnings).splitlines() == [f"warning: {w}" for w in warnings]


SDK = os.environ.get("RENPY_SDK")


@pytest.mark.skipif(not (SDK and (Path(SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_bridge_reads_files_from_and_direct_args(repo_root, tmp_path):
    """Мост понимает оба входа: компилятор зовёт его файлом-списком, человек при
    отладке одной сцены — путями аргументами. Результат обязан быть одинаковым,
    иначе отладочный вызов проверял бы не то, что собирает CI."""
    from vn.content.analyze import sdk_renpy_exe, write_files_listing

    exe = str(sdk_renpy_exe())
    scene = repo_root / "content/chapters/ch01_awakening/scenes/s010_intro.scene.rpy"
    listing = write_files_listing(tmp_path / "files.txt", [scene])

    def analyze(out: Path, *args: str):
        proc = subprocess.run([exe, str(repo_root), "vn_analyze", str(out), *args],
                              capture_output=True, text=True, timeout=300)
        return proc, (json.loads(out.read_text(encoding="utf-8"))["files"]
                      if out.is_file() else None)

    _proc, via_list = analyze(tmp_path / "list.json", "--files-from", str(listing))
    _proc, via_argv = analyze(tmp_path / "argv.json", str(scene))
    assert via_list == via_argv
    assert list(via_list) == [str(scene)]
    assert via_list[str(scene)]["says"] > 0

    # Ни одного входа — внятная ошибка и непустой код, а не отчёт про пустоту.
    proc, data = analyze(tmp_path / "none.json")
    assert proc.returncode != 0 and data is None
    assert "--files-from" in proc.stderr


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
