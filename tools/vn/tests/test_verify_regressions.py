"""Регрессии по находкам верификации фазы 0: устойчивость lint, --check, shim-размотка,
обязательные входы компилятора, переносимость самого набора между cwd."""

import ast
import json
import shutil
from pathlib import Path

import pytest

from conftest import BASE_OUTPUTS

from vn.content.compile import CompileError, compile_content
from vn.content.lint import lint

TESTS_DIR = Path(__file__).resolve().parent


def _copy_skeleton(repo_root, tmp_path):
    """Скелет без глав: lint-тесты создают свои главы, compile-тесты не требуют SDK."""
    from vn.content.lint import REQUIRED_DIRS

    for name in ("project.yaml", ".vnstorage.yaml"):
        shutil.copy(repo_root / name, tmp_path / name)
    shutil.copytree(repo_root / "tools" / "schemas", tmp_path / "tools" / "schemas",
                    dirs_exist_ok=True)
    shutil.copytree(repo_root / "content", tmp_path / "content")
    shutil.rmtree(tmp_path / "content" / "chapters")
    (tmp_path / "content" / "chapters").mkdir()
    # Локации требуют собранного game/assets — скелет без ассетов их не несёт
    if (tmp_path / "content" / "locations").is_dir():
        shutil.rmtree(tmp_path / "content" / "locations")
        (tmp_path / "content" / "locations").mkdir()
    for d in REQUIRED_DIRS:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_lint_survives_schema_invalid_exits(repo_root, tmp_path):
    """Схемно-невалидный exits не роняет lint трейсбеком (KeyError 'to')."""
    root = _copy_skeleton(repo_root, tmp_path)
    ch = root / "content" / "chapters" / "ch01_awakening"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: playtest\nentry_scene: s010\nscene_order: [s010]\n",
        encoding="utf-8",
    )
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nexits:\n  next:\n    - {when: 'g.flag'}\n",
        encoding="utf-8",
    )
    (ch / "scenes" / "s010_intro.scene.rpy").write_text(
        "label ch01_s010__body:\n    return 'next'\n", encoding="utf-8"
    )
    rep = lint(root)   # не должен бросить исключение
    # jsonschema для oneOf даёт «is not valid under any of the given schemas»
    assert any("exits/next" in e for e in rep.errors)


def test_lint_requires_compiler_inputs(repo_root, tmp_path):
    """Инвариант «lint зелёный => build не падает»: удалённый renames.yaml ловит lint."""
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "renames.yaml").unlink()
    rep = lint(root)
    assert any("renames.yaml: обязательный файл отсутствует" in e for e in rep.errors)


def test_compile_missing_input_is_compile_error(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "renames.yaml").unlink()
    with pytest.raises(CompileError, match="renames.yaml"):
        compile_content(root, out_dir=tmp_path / "gen")


def test_compile_invalid_project_is_compile_error(repo_root, tmp_path):
    """KeyError-трейсбек на project.yaml без version недопустим."""
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "project.yaml").write_text("schema: project@1\nsave_schema: 1\nmin_tools: \"0.1\"\n",
                                       encoding="utf-8")
    with pytest.raises(CompileError, match="project.yaml"):
        compile_content(root, out_dir=tmp_path / "gen")


def test_check_mode_writes_nothing_and_detects_stale(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    gen = tmp_path / "generated"
    res = compile_content(root, out_dir=gen, check=True)
    assert not gen.exists() or not any(gen.iterdir())   # ничего не записано
    assert len(res.stale) == len(BASE_OUTPUTS)           # всё «устарело» (генерата нет)

    compile_content(root, out_dir=gen)
    res2 = compile_content(root, out_dir=gen, check=True)
    assert res2.stale == []                             # после сборки — свежо

    (gen / "version.gen.rpy").write_text("# испорчено руками\n", encoding="utf-8")
    res3 = compile_content(root, out_dir=gen, check=True)
    assert res3.stale == ["version.gen.rpy"]


def test_shims_unwind_call_stack(repo_root, tmp_path):
    """Shim-метки обязаны разматывать стек перед jump (G7)."""
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "renames.yaml").write_text(
        "schema: renames@1\n"
        "scenes:\n  ch02_s090: ch02_s100\n"
        "deleted_scenes:\n  ch03_s010: {fallback: ch03_s020, since: 1.2.0}\n"
        "labels: {}\nvars: {}\n",
        encoding="utf-8",
    )
    gen = tmp_path / "gen"
    compile_content(root, out_dir=gen)
    text = (gen / "registry" / "overrides.gen.rpy").read_text(encoding="utf-8")
    assert "config.label_overrides.update({'ch02_s090': 'ch02_s100', 'ch03_s010': 'ch03_s020'})" in text
    assert "label ch02_s090:\n    $ vn.unwind_call_stack()\n    jump ch02_s100" in text
    assert "label ch03_s010:\n    $ vn.unwind_call_stack()\n    jump ch03_s020" in text


def test_registry_scenes_missing_from_build_get_shims(repo_root, tmp_path):
    """Выпущенный id вне сборки (неустановленный пак/эпизод) обязан получить
    shim на «контент недоступен» — иначе сейв игрока падает ScriptError в
    crash-экран (раздел 3.8 ARCHITECTURE.md; закрыто по FW-аудиту)."""
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "registry" / "id_registry.json").write_text(
        json.dumps({"schema": "id_registry@1", "chapters": ["ch77"],
                    "scenes": ["ch77_s010"], "characters": [], "vars": [],
                    "assets": []}),
        encoding="utf-8",
    )
    gen = tmp_path / "gen"
    compile_content(root, out_dir=gen)
    text = (gen / "registry" / "overrides.gen.rpy").read_text(encoding="utf-8")
    assert ("label ch77_s010:\n    $ vn.unwind_call_stack()\n"
            '    $ vn_unavailable_reason = "missing_content"\n'
            "    jump vn_scene_unavailable") in text


def test_persistent_vars_require_vn_prefix(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "variables" / "meta.vars.yaml").write_text(
        "schema: vars@1\nstore: persistent\nvars:\n  seen_intro: {type: bool, default: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(CompileError, match="vn_"):
        compile_content(root, out_dir=tmp_path / "gen")


def test_gen_manifest_matches_schema(repo_root, tmp_path):
    from vn.schemas import SchemaRegistry

    root = _copy_skeleton(repo_root, tmp_path)
    gen = tmp_path / "generated"
    compile_content(root, out_dir=gen)
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    manifest = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    assert reg.validate(manifest, "manifest.json") == []


def test_doctor_detects_lfs_pointer_fonts(tmp_path):
    """Чекаут без git-lfs кладёт указатель вместо шрифта — игра упала бы
    в рантайме невнятной ошибкой; doctor обязан ловить это до запуска."""
    from vn.doctor import _lfs_pointer_fonts

    fonts = tmp_path / "game" / "fonts"
    fonts.mkdir(parents=True)
    # настоящий TTF (сигнатура sfnt 1.0)
    (fonts / "Real.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 60)
    # указатель LFS
    (fonts / "Pointer.ttf").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:dead\nsize 1\n")
    # мусор (обрезанная загрузка)
    (fonts / "Broken.ttf").write_bytes(b"<!DOCTYPE html>")

    bad, total = _lfs_pointer_fonts(tmp_path)
    assert total == 3
    assert sorted(bad) == ["Broken.ttf", "Pointer.ttf"]

    # Здоровое дерево — пусто
    (fonts / "Pointer.ttf").unlink()
    (fonts / "Broken.ttf").unlink()
    assert _lfs_pointer_fonts(tmp_path) == ([], 1)


def test_doctor_font_check_noop_without_fonts_dir(tmp_path):
    """Нет game/fonts — проверка молчит (не все чекауты её имеют)."""
    from vn.doctor import _lfs_pointer_fonts

    assert _lfs_pointer_fonts(tmp_path) == ([], 0)


def test_suite_never_imports_itself_as_package():
    """Набор обязан импортироваться при ЛЮБОМ cwd: `python -m pytest tools/vn/tests`
    из корня репозитория так же зелен, как прогон из tools/vn.

    Ломала это ровно одна форма — `from tests.test_compile import BASE_OUTPUTS`:
    пакета `tests` не существует (в каталоге нет __init__.py), он «появляется»
    только когда на sys.path есть tools/vn, то есть когда pytest запущен ИЗ
    tools/vn. Из корня тот же набор давал один красный тест, невоспроизводимый
    локально ничем, — то есть поломку видел только CI. Импорт по имени модуля
    (`from test_compile import ...`) и `from conftest import ...` работают всегда:
    каталог самого теста pytest кладёт на sys.path сам.

    Разбор — AST, а не поиск подстроки: те же строки цитируются в докстрингах
    (test_ci_config), и текстовая проверка ловила бы объяснение вместо импорта.
    """
    bad: list[str] = []
    for f in sorted(TESTS_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"), filename=f.name)):
            if isinstance(node, ast.ImportFrom):
                if node.level:          # from . import x — тоже требует пакета
                    bad.append(f"{f.name}:{node.lineno}: относительный импорт")
                elif (node.module or "").split(".")[0] == "tests":
                    bad.append(f"{f.name}:{node.lineno}: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                bad += [f"{f.name}:{node.lineno}: import {a.name}" for a in node.names
                        if a.name.split(".")[0] == "tests"]
    assert not bad, ("набор импортирует себя как пакет — прогон из корня репозитория "
                     f"упадёт ModuleNotFoundError: {bad}")


def test_lint_catches_renamed_layered_shot(repo_root, tmp_path):
    """Сеть G7 обязана ловить переименование ШОТА, а не только его слоёв.

    Разблокировка галереи у `kind: shot` идёт по тегу образа плюс атрибуту шота
    (`_seen_shot`, ADR-0013 в редакции 2026-08-18), поэтому переименованный шот
    остаётся у игроков закрытым — молча, как и переименованный CG. До штампа
    составного id (`shots/<chNN>/<sNNN>/<shot>`) реестр этого не видел: обход
    ассетов перечислял файлы, а своего файла у шота нет.
    """
    root = _copy_skeleton(repo_root, tmp_path)
    shot = root / "game" / "assets" / "shots" / "ch01" / "s030" / "sunset"
    shot.mkdir(parents=True)
    (shot / "env.webp").write_bytes(b"x")
    reg = root / "content" / "registry" / "id_registry.json"
    doc = json.loads(reg.read_text(encoding="utf-8"))
    doc["assets"] = ["shots/ch01/s030/sunset", "shots/ch01/s030/sunset/env"]
    reg.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    assert not any("shots/ch01/s030/sunset" in e for e in lint(root).errors)

    shot.rename(shot.with_name("dusk"))          # шот переименован целиком
    errors = lint(root).errors
    assert any("shots/ch01/s030/sunset исчез" in e and "renames.assets" in e
               for e in errors), errors

    # Запись о переименовании — единственный законный способ: она же учитывается
    # рантаймом галереи, поэтому открытый кадр у игрока остаётся открытым.
    (root / "content" / "renames.yaml").write_text(
        "schema: renames@1\nscenes: {}\ndeleted_scenes: {}\nlabels: {}\nvars: {}\n"
        "assets:\n"
        "  shots/ch01/s030/sunset: shots/ch01/s030/dusk\n"
        "  shots/ch01/s030/sunset/env: shots/ch01/s030/dusk/env\n",
        encoding="utf-8")
    assert not any("shots/ch01/s030/sunset" in e for e in lint(root).errors)
