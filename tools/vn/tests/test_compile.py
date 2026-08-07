"""Content Compiler фазы 0: генерат, идемпотентность, точечная очистка (G6)."""

import json

import pytest

from vn.content.compile import CompileError, compile_content


def test_compile_empty_project(repo_root, tmp_path):
    gen = tmp_path / "generated"
    res = compile_content(repo_root, out_dir=gen)

    expected = {
        "version.gen.rpy",
        "state/defaults.gen.rpy",
        "registry/audio.gen.rpy",
        "registry/chapters.gen.rpy",
        "registry/menus.gen.rpy",
        "registry/overrides.gen.rpy",
    }
    assert set(res.written) == expected
    for rel in expected:
        text = (gen / rel).read_text(encoding="utf-8")
        assert "AUTO-GENERATED" in text

    defaults = (gen / "state/defaults.gen.rpy").read_text(encoding="utf-8")
    assert "default vn_save_schema = 1" in defaults
    assert "define vn_build_save_schema = 1" in defaults
    assert "init -980 python in g:" in defaults
    assert "default g.route = 'common'" in defaults

    manifest = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "gen_manifest@1"
    assert "project.yaml" in manifest["inputs"]


def test_compile_is_idempotent(repo_root, tmp_path):
    gen = tmp_path / "generated"
    compile_content(repo_root, out_dir=gen)
    res2 = compile_content(repo_root, out_dir=gen)
    assert res2.written == []
    assert len(res2.skipped) == 6
    assert res2.deleted == []


def test_orphan_cleanup_removes_rpy_and_rpyc(repo_root, tmp_path):
    gen = tmp_path / "generated"
    compile_content(repo_root, out_dir=gen)

    # Подделываем прошлый манифест: якобы существовал лишний выход
    manifest_path = gen / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    orphan_rpy = gen / "scenes" / "ch99" / "ch99_s010.gen.rpy"
    orphan_rpy.parent.mkdir(parents=True)
    orphan_rpy.write_text("# stale\n", encoding="utf-8")
    orphan_rpy.with_suffix(".rpyc").write_bytes(b"stale")
    manifest["outputs"]["scenes/ch99/ch99_s010.gen.rpy"] = "deadbeef"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    res = compile_content(repo_root, out_dir=gen)
    assert not orphan_rpy.exists()
    assert not orphan_rpy.with_suffix(".rpyc").exists()
    assert "scenes/ch99/ch99_s010.gen.rpy" in res.deleted


def test_chapters_refuse_until_phase1(repo_root, tmp_path):
    """Фаза 0 честно отказывается компилировать главы, а не молчит."""
    import shutil

    root = tmp_path / "repo"
    root.mkdir()
    for name in ("project.yaml", ".vnstorage.yaml"):
        shutil.copy(repo_root / name, root / name)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    shutil.copytree(repo_root / "content", root / "content")
    (root / "content" / "chapters" / "ch01_x").mkdir(parents=True)

    with pytest.raises(CompileError, match="фаза 1"):
        compile_content(root, out_dir=tmp_path / "gen")
