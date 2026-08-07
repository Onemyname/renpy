"""Регрессии по находкам верификации фазы 0: устойчивость lint, --check, shim-размотка,
обязательные входы компилятора."""

import json
import shutil

import pytest

from vn.content.compile import CompileError, compile_content
from vn.content.lint import lint


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
    assert len(res.stale) == 11                          # всё «устарело» (генерата нет)

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
