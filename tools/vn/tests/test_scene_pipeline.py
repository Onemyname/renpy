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


@pytest.mark.skipif(not (os.environ.get("RENPY_SDK")
                         and (Path(os.environ["RENPY_SDK"]) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_unshipped_pack_vars_are_split_out_of_the_shipped_generat(repo_root, tmp_path):
    """Переменные пака ВНЕ всех флейворов не смешиваются с переменными игры.

    Мотив — не чистота, а сейв игрока: генерат один на все флейворы (иначе рвётся
    линия .rpyc, G6), поэтому `default ch70.path = 'none'` исполнялся бы в
    релизной сборке, а Ren'Py кладёт в сейв любую изменённую переменную стора.
    Разделение позволяет исключить ровно один файл глобом (release.py:
    unshipped_exclude_globs) и не заводить второй генерат.

    Проверяются три места, и промах в любом тихий: объявления не должны утечь в
    `defaults.gen.rpy`, снапшот миграций (G5) не должен знать про тестовые сторы,
    а отдельный файл обязан быть самодостаточным — создавать сторы, иначе в
    dev-чекауте тестовые главы упадут NameError.
    """
    import yaml

    from vn.content.compile import compile_content
    from vn.repo import chapter_zones, load_project

    project = load_project(repo_root)
    shipped = {"core"}
    for cfg in (project.get("flavors") or {}).values():
        shipped.update((cfg or {}).get("packs") or [])
    unshipped_stores = set()
    for pack_id, zone in chapter_zones(repo_root):
        if pack_id in shipped:
            continue
        for f in sorted(zone.glob("*/vars.yaml")):
            unshipped_stores.add(yaml.safe_load(f.read_text(encoding="utf-8"))["store"])
    if not unshipped_stores:
        pytest.skip("в дереве нет паков вне флейворов — разделять нечего")

    gen = tmp_path / "generated"
    compile_content(repo_root, out_dir=gen)
    shipped_defaults = (gen / "state/defaults.gen.rpy").read_text(encoding="utf-8")
    snapshot = (gen / "state/snapshot.gen.rpy").read_text(encoding="utf-8")
    split = (gen / "state/defaults_unshipped.gen.rpy").read_text(encoding="utf-8")

    for store in sorted(unshipped_stores):
        assert f"default {store}." not in shipped_defaults, (
            f"{store}: объявления тестового пака в поставляемом генерате — "
            f"они уедут в сейв игрока (RTL-046)")
        assert f"'{store}'" not in snapshot, (
            f"{store}: тестовый стор в снапшоте миграций (G5)")
        assert f"init -980 python in {store}:" in split
        assert f"default {store}." in split

    # Файл поставляемых переменных при этом не опустел: разделение не должно
    # унести с собой переменные игры.
    assert "default g." in shipped_defaults and "vn_save_schema" in shipped_defaults
    # А отдельный файл не должен объявлять схему сейва: она одна на игру.
    assert "vn_save_schema" not in split


def test_say_menuitem_is_a_contract_violation():
    """Реплика-заголовок внутри `menu:` — ошибка сборки, как и условный пункт.

    Форму Ren'Py разрешает, и finish_say разбирает у неё клаузу `id` — значит
    `vn loc keys` выдаст ей say-id, она уедет в леджер и в voice-манифест
    наравне с обычными, а компилятор вставит `voice ...` выше неё ПО НОМЕРУ
    СТРОКИ, то есть внутрь блока menu:, где движок разбирает только пункты.
    Без запрета: компиляция зелёная, файл записан, падает загрузка игры на
    сгенерированном файле, которого никто не писал."""
    rep = sc.SceneCompileReport()
    a = _analysis(say_list=[
        {"line": 4, "who": "mira", "what": "Что скажешь?",
         "id": "ch01_s010_0001", "interact": False},
        {"line": 2, "who": None, "what": "Обычная реплика",
         "id": "ch01_s010_0002", "interact": True},
    ])
    sc.validate_scene(_unit(analysis=a), {"ch01_s010"}, "release", rep)
    hits = [e for e in rep.errors if "say menuitem" in e]
    assert len(hits) == 1, rep.errors
    assert ":4:" in hits[0], "ошибка обязана указывать на строку реплики"


def test_voice_is_never_injected_into_a_menu_block():
    """Вторая линия к запрету выше: даже если контракт когда-нибудь ослабят,
    инжектор не имеет права писать voice внутрь блока menu: — это неразбираемый
    генерат, а не деградация."""
    text = ('label ch01_s010__body:\n'
            '    $ vn_menu = "ch01_s010_m001"\n'
            '    menu:\n'
            '        mira "Что скажешь?" id ch01_s010_0001\n'
            '        "Соврать":\n'
            '            return "a"\n')
    says = [{"line": 4, "who": "mira", "what": "Что скажешь?",
             "id": "ch01_s010_0001", "interact": False}]
    out = sc._inject_voice(text, says, {"ch01_s010_0001"})
    assert out == text, "voice уехал внутрь menu: — генерат не разберётся"

    # Контрольная половина: обычная реплика озвучивается как и раньше, иначе
    # проверка выше «проходила» бы и при полностью выключенном инжекторе.
    plain = 'label ch01_s010__body:\n    "Реплика" id ch01_s010_0002\n'
    says2 = [{"line": 2, "who": None, "what": "Реплика",
              "id": "ch01_s010_0002", "interact": True}]
    assert 'voice vn.voice_path("ch01_s010_0002")' in sc._inject_voice(
        plain, says2, {"ch01_s010_0002"})


@pytest.mark.skipif(not (os.environ.get("RENPY_SDK")
                         and (Path(os.environ["RENPY_SDK"]) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_bridge_marks_the_menu_caption_say_as_non_interactive(repo_root, tmp_path):
    """Признак, на котором держится запрет выше, выставляет ПАРСЕР ДВИЖКА, а не мы.

    parse_menu зовёт finish_say(..., interact=False) и кладёт получившийся Say
    отдельным узлом ПЕРЕД Menu (renpy/parser.py) — по соседству Say и Menu не
    различить, обычная реплика перед меню в AST выглядит так же. Различает
    только interact. Проверять это на фабрикованном анализе бессмысленно: там
    проверялась бы фабрикация, поэтому разбор идёт настоящим мостом."""
    from vn.content.analyze import analyze_scene_files

    scene = tmp_path / "s010_probe.scene.rpy"
    scene.write_text(
        'label ch01_s010__body:\n'
        '    "Обычная реплика перед меню"\n'
        '    $ vn_menu = "ch01_s010_m001"\n'
        '    menu:\n'
        '        mira "Реплика-заголовок"\n'
        '        "Соврать":\n'
        '            return "a"\n'
        '        "Правду":\n'
        '            return "b"\n', encoding="utf-8")

    a = analyze_scene_files(repo_root, [scene])[str(scene)]
    assert not a.get("errors"), a["errors"]
    by_line = {s["line"]: s for s in a["say_list"]}
    assert by_line[2]["interact"] is True, "обычная реплика помечена как заголовок"
    assert by_line[5]["interact"] is False, (
        "мост не отличает реплику-заголовок меню — запрет в validate_scene "
        "держится ни на чём")


def _when_errors(when, registry={"ch01.met_mira", "g.route"}, status="release"):
    rep = sc.SceneCompileReport()
    unit = _unit(meta={"exits": {"next": [{"when": when, "to": "s020"},
                                          {"to": "s030"}]}},
                 analysis=_analysis(returns=[{"expr": "'next'", "line": 5}]))
    sc.validate_scene(unit, {"ch01_s010", "ch01_s020", "ch01_s030"}, status, rep,
                      var_registry=registry)
    return [e for e in rep.errors if "when" in e], [w for w in rep.warnings if "when" in w]


def test_when_condition_is_validated_against_the_variable_registry():
    """`when` не проверял НИКТО: схема описывает его строкой, линтер поле не
    читает, компилятор вклеивает как есть, а flow.parse_condition на незнакомом
    имени просто объявляет ребро непрозрачным. Опечатка проходила весь набор
    гейтов и превращалась в NameError у ИГРОКА — в точке перехода между сценами,
    то есть там, где сейв остался в предыдущей сцене и продолжить нельзя."""
    errors, _ = _when_errors("ch01.met_mirra")
    assert len(errors) == 1 and "ch01.met_mirra" in errors[0], errors

    # Свободное имя: в py_eval оно не разрешится ничем.
    errors, _ = _when_errors("route == 'a'")
    assert errors and "route" in errors[0]

    # Не выражение вовсе.
    errors, _ = _when_errors("ch01.met_mira and")
    assert errors and "не разбирается" in errors[0]


def test_when_validation_checks_names_not_shape():
    """Форму проверять нельзя: подмножество, которое понимает parse_condition,
    уже, чем множество легальных выражений, и её ветка «непрозрачное условие»
    пропускает остальные НАМЕРЕННО (ADR-0021 §2). Поэтому опечатка — ошибка, а
    непонятая, но корректная форма — не ошибка."""
    for expr in ("ch01.met_mira", "not ch01.met_mira", "g.route == 'a'",
                 "ch01.met_mira and g.route != 'b'",
                 "len(g.route) > 0",                     # вызов: непрозрачно, но легально
                 "g.route in ('a', 'b')"):               # in: вне подмножества графа
        errors, _ = _when_errors(expr)
        assert errors == [], f"{expr}: ложная ошибка {errors}"


def test_when_typo_is_only_a_warning_in_a_draft_chapter():
    """Та же градация, что у остальных проверок переменных (G15): в черновике
    автор ещё ходит по дереву, и красная сборка мешала бы больше, чем помогала."""
    errors, warnings = _when_errors("ch01.met_mirra", status="draft")
    assert errors == [] and warnings and "ch01.met_mirra" in warnings[0]


def test_label_that_can_fall_through_is_an_error():
    """Метка, из которой можно ВЫПАСТЬ, — тихая подмена ветки.

    Авторский .rpy вклеивается в генерат целиком, а Ren'Py сшивает операторы
    файла подряд (renpy/script.py: chain_block -> ast.Label.chain). Значит
    выпадение из блока метки продолжает исполнение со СЛЕДУЮЩЕЙ метки файла:
    игрок, выбравший «остаться», оказывается в ветке «ушёл», причём флаг
    «остался» уже выставлен — состояние и путь разъезжаются. Если следующей
    метки нет, цепочка упирается в None и игра тихо выходит из прохождения.

    Заметить это нечем: G7-страж стоит ПОСЛЕ call ...__body, соседняя ветка
    делает свой return, глубина стека корректна — и обвязка исполняет чужой exit
    как свой. renpy lint тоже молчит: метка достижима, jump валиден."""
    rep = sc.SceneCompileReport()
    a = _analysis(labels=[{"name": "ch01_s010__body", "line": 1, "terminal": False},
                          {"name": "ch01_s010__leave", "line": 9, "terminal": True}],
                  returns=[{"expr": "'corridor'", "line": 10}])
    sc.validate_scene(_unit(meta={"exits": {"corridor": "s020"}},
                            analysis=a), {"ch01_s010", "ch01_s020"}, "release", rep)
    hits = [e for e in rep.errors if "завершается не по всем путям" in e]
    assert len(hits) == 1 and "ch01_s010__body" in hits[0], rep.errors


@pytest.mark.skipif(not (os.environ.get("RENPY_SDK")
                         and (Path(os.environ["RENPY_SDK"]) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_bridge_reports_terminality_per_label(repo_root, tmp_path):
    """Признак терминальности считает ПАРСЕР ДВИЖКА, а не регексп по тексту:
    завершённость определяется по всем ветвям if и по всем пунктам menu, и
    воспроизводить эту логику вторым разборщиком запрещено (G24).

    Четыре формы, и три из них — типовые ошибки автора."""
    from vn.content.analyze import analyze_scene_files

    scene = tmp_path / "s010_probe.scene.rpy"
    scene.write_text(
        'label ch01_s010__body:\n'
        '    return "a"\n'
        '\n'
        'label ch01_s010__falls:\n'
        '    "просто реплика"\n'
        '\n'
        'label ch01_s010__if_full:\n'
        '    if ch01.met_mira:\n'
        '        return "a"\n'
        '    else:\n'
        '        jump ch01_s010__body\n'
        '\n'
        'label ch01_s010__if_no_else:\n'
        '    if ch01.met_mira:\n'
        '        return "a"\n'
        '\n'
        'label ch01_s010__menu_partial:\n'
        '    menu:\n'
        '        "Уйти":\n'
        '            return "a"\n'
        '        "Остаться":\n'
        '            "остался"\n', encoding="utf-8")

    a = analyze_scene_files(repo_root, [scene])[str(scene)]
    assert not a.get("errors"), a["errors"]
    terminal = {lb["name"]: lb["terminal"] for lb in a["labels"]}
    assert terminal["ch01_s010__body"] is True
    assert terminal["ch01_s010__falls"] is False
    assert terminal["ch01_s010__if_full"] is True
    assert terminal["ch01_s010__if_no_else"] is False, "путь мимо if не учтён"
    assert terminal["ch01_s010__menu_partial"] is False, "незакрытый пункт меню не учтён"


def test_voice_ducking_is_actually_enabled(repo_root):
    """Трёх config.emphasize_audio_* мало: механизм гейтится ИГРОВОЙ настройкой.

    renpy/audio/audio.py: `if not renpy.game.preferences.emphasize_audio:
    emphasized = False`, а значение по умолчанию у неё False
    (renpy/preferences.py: Preference("emphasize_audio", False)). Без
    config.default_emphasize_audio дакинг был выключен ВСЕГДА, а заметить это
    можно только на слух и только с озвучкой поверх музыки — то есть на контенте,
    которого в репозитории ещё нет. Справочник при этом называл подсистему
    работающей."""
    audio = (repo_root / "game" / "framework" / "00_core"
             / "045_audio.rpy").read_text(encoding="utf-8")
    assert 'config.emphasize_audio_channels = ["voice"]' in audio
    assert "config.default_emphasize_audio = True" in audio, \
        "дакинг сконфигурирован, но не включён — настройка по умолчанию False"

    # И тумблер: механизм и так гейтится настройкой, значит игрок обязан иметь
    # к ней доступ, иначе выключить приглушение нечем.
    prefs = (repo_root / "game" / "framework" / "20_ui" / "screens"
             / "core_screens.rpy").read_text(encoding="utf-8")
    assert 'Preference("emphasize audio", "toggle")' in prefs


def test_play_operator_does_not_restart_the_same_track():
    """Обвязка КАЖДОЙ сцены исполняет play при входе. Без if_changed один и тот
    же трек в соседних сценах перезапускался бы с начала — да ещё с fadeout и
    fadein, то есть слышимым провалом на каждом переходе.

    Клауза штатная (common/000statements.rpy) и означает «если на канале уже
    играет этот файл — не трогать». Громкость она сохраняет прежнюю, и это
    безопасно ровно потому, что volume объявлен у ТРЕКА, а не у сцены."""
    rep = sc.SceneCompileReport()
    lines = []
    tracks = {"calm_theme": {"kind": "bgm"}, "rain": {"kind": "amb", "volume": 0.5}}
    sc._emit_track(lines, _unit(), "bgm/calm_theme", tracks, rep, "music")
    sc._emit_track(lines, _unit(), "amb/rain", tracks, rep, "ambient")
    assert rep.errors == []
    assert lines[0] == "    play music calm_theme if_changed fadeout 1.0 fadein 1.0"
    # Громкость трека по-прежнему уходит в оператор — клауза её не отменяет.
    assert lines[1] == "    play ambient rain if_changed fadeout 1.0 fadein 1.0 volume 0.5"


def test_chapter_map_zoom_does_not_steal_the_viewport_page_keys(repo_root):
    """Оба вьюпорта карты идут с пресетом, где pagekeys включён, а движковый
    keymap связывает viewport_pageup/pagedown ровно с PageUp/PageDown
    (common/00keymap.rpy). Viewport обрабатывает их без проверки фокуса, поэтому
    зум на тех же клавишах дрался с постраничной прокруткой полотна — а граф
    шире экрана уже на пяти узлах, и прокрутка нужнее второго способа менять
    масштаб (кнопка масштаба есть в шапке)."""
    src = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "story_flow.rpy").read_text(encoding="utf-8")
    keys = [ln.strip() for ln in src.splitlines() if ln.strip().startswith('key "')]
    bound = {ln.split('"')[1] for ln in keys}
    assert not bound & {"K_PAGEUP", "K_PAGEDOWN"}, \
        f"зум снова перехватывает клавиши прокрутки вьюпорта: {sorted(bound)}"
    assert {"K_MINUS", "K_EQUALS"} <= bound, f"зум не привязан ни к чему: {sorted(bound)}"


def test_when_rejects_a_bare_builtin_name():
    """Обход стража FWA-006: голое ВСТРОЕННОЕ имя в `when`.

    Валидатор требовал, чтобы свободных имён не было, и тут же вычитал из них
    весь dir(builtins) — ~160 имён (next, id, max, min, all, any, len, set, list,
    dict, object, type, round, input, format, credits, quit…). Все они в py_eval
    разрешаются и все TRUTHY, поэтому забытый префикс стора у переменной с таким
    именем давал ВСЕГДА-ИСТИННОЕ условие: игрок молча уезжал не в ту сцену при
    зелёных lint/compile/renpy lint и зелёном smoke. Числовое сравнение с тем же
    именем вместо тихой подмены давало TypeError ровно в точке перехода между
    сценами, где сейв остался в предыдущей.

    Схема vars@1 объявить переменную с любым таким именем разрешает
    (propertyNames: ^[a-z][a-z0-9_]*$), так что вход достижим. ARCHITECTURE §3.11
    голое `Name` в подмножестве условий не разрешает вовсе.

    Прежний страж на свободное имя проверял РОВНО ОДИН кейс — `route == 'a'`, —
    а `route` в dir(builtins) не входит."""
    for expr in ("credits", "next", "not all", "round >= 3", "quit"):
        errors, _ = _when_errors(expr)
        assert errors, f"{expr!r} прошло валидацию: условие станет константой у игрока"

    # Вызов встроенной функции остаётся легальным: `len/min/int` в сторе есть
    # всегда, и это условие просто непрозрачно для графа (норма, не дефект).
    errors, _ = _when_errors("len(g.route) > 0")
    assert not errors, errors


def test_unconditional_exit_entry_must_be_last():
    """Список условных целей — «первый подошедший выигрывает».

    Компилятор эмитит НЕЗАВИСИМЫЕ `if _return == "<exit>"` в порядке YAML, и
    каждая ветка делает jump. Запись без `when:` эмитится безусловным if и
    перехватывает управление — всё, что объявлено ниже, в генерате мёртво.

    Самая вероятная авторская правка это как раз «дописать новую условную цель в
    конец списка, где уже лежит fallback»: новая ветка не срабатывает никогда,
    игрок молча идёт по старому пути, а YAML корректен и все гейты зелёные.
    Схема порядок не ограничивает и не может — она не знает про семантику
    первого совпадения."""
    rep = sc.SceneCompileReport()
    unit = _unit(meta={"exits": {"next": [{"to": "s020"},
                                          {"when": "ch01.met_mira", "to": "s030"}]}},
                 analysis=_analysis(returns=[{"expr": "'next'", "line": 5}]))
    sc.validate_scene(unit, {"ch01_s010", "ch01_s020", "ch01_s030"}, "release", rep,
                      var_registry={"ch01.met_mira"})
    assert any("не последней" in e for e in rep.errors), rep.errors

    # Правильный порядок — молчание.
    rep2 = sc.SceneCompileReport()
    unit2 = _unit(meta={"exits": {"next": [{"when": "ch01.met_mira", "to": "s030"},
                                           {"to": "s020"}]}},
                  analysis=_analysis(returns=[{"expr": "'next'", "line": 5}]))
    sc.validate_scene(unit2, {"ch01_s010", "ch01_s020", "ch01_s030"}, "release", rep2,
                      var_registry={"ch01.met_mira"})
    assert not [e for e in rep2.errors if "не последней" in e], rep2.errors


def test_marker_ownership_is_exclusive_and_nearest_wins():
    """Обход стража FWA-033: один маркер на ДВА меню, и «первый» вместо ближайшего.

    (1) Вложенная развилка (легальный `menu` внутри ветки другого `menu`) даёт два
    оператора в окне ОДНОГО маркера. Маркер достаётся обоим: `vn loc keys` считает,
    что у внутреннего меню маркер уже есть, своего id ему не вставляет, в ledger
    оно не попадает, а в рантайме на нём остаётся vn_menu ВНЕШНЕГО меню — игрок в
    переведённой сборке видит подписи другого меню по индексу. В исходном языке
    дефект невидим.

    (2) Два маркера в окне (например остался маркер удалённого меню): «первый»
    выигрывал у компилятора, а движок исполняет ВСЕ присваивания подряд, то есть
    побеждает последний. Проверено picks.log живого прогона — граф знал m001,
    рантайм писал m002.

    Прежний страж проверял ровно «одно меню + один маркер»."""
    m1 = {"line": 10, "source": 'vn_menu = "ch01_s010_m001"'}
    m2 = {"line": 11, "source": 'vn_menu = "ch01_s010_m002"'}

    # Два маркера в окне -> ближайший, как и движок.
    owner = sc.menu_markers_map([{"line": 12}], [m1, m2])
    assert owner[12] is m2, "компилятор берёт не ближайший маркер — разойдётся с рантаймом"

    # Одно маркер, два меню в его окне -> достаётся ОДНОМУ, второе без id.
    owner = sc.menu_markers_map([{"line": 11}, {"line": 12}], [m1])
    assert len(owner) == 1, f"маркер достался двум меню: {owner}"
    assert owner.get(11) is m1, "маркер обязан достаться БЛИЖАЙШЕМУ меню"
    assert 12 not in owner, "второе меню обязано остаться без id, чтобы его заметили"
