"""Content Compiler: генерат, идемпотентность, точечная очистка (G6).
Тесты пустого контента гоняются на скелете БЕЗ глав (не требуют Ren'Py SDK)."""

import json
import shutil

import pytest

from vn.content.compile import CompileError, compile_content

BASE_OUTPUTS = {
    "version.gen.rpy",
    "state/defaults.gen.rpy",
    "state/snapshot.gen.rpy",
    "state/migrations.gen.rpy",
    "registry/achievements.gen.rpy",
    "registry/audio.gen.rpy",
    "registry/chapters.gen.rpy",
    "registry/scenes.gen.rpy",
    "registry/characters.gen.rpy",
    "registry/images.gen.rpy",
    "registry/menus.gen.rpy",
    "registry/overrides.gen.rpy",
    "registry/ui_frames.gen.rpy",     # ADR-0009: Frame'ы генерируемых панелей
    "registry/gallery.gen.rpy",       # ADR-0010: реестр галереи
}


def skeleton_no_chapters(repo_root, tmp_path):
    """Скелет репозитория без глав: компиляция не требует SDK (фаза-0 путь)."""
    from vn.content.lint import REQUIRED_DIRS

    root = tmp_path / "repo"
    root.mkdir()
    for name in ("project.yaml", ".vnstorage.yaml"):
        shutil.copy(repo_root / name, root / name)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    shutil.copytree(repo_root / "content", root / "content")
    shutil.rmtree(root / "content" / "chapters")
    (root / "content" / "chapters").mkdir()
    # Локации требуют собранного game/assets — скелет без ассетов их не несёт
    if (root / "content" / "locations").is_dir():
        shutil.rmtree(root / "content" / "locations")
        (root / "content" / "locations").mkdir()
    for d in REQUIRED_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def test_compile_empty_project(repo_root, tmp_path):
    root = skeleton_no_chapters(repo_root, tmp_path)
    gen = tmp_path / "generated"
    res = compile_content(root, out_dir=gen)

    assert set(res.written) == BASE_OUTPUTS
    for rel in BASE_OUTPUTS:
        text = (gen / rel).read_text(encoding="utf-8")
        assert "AUTO-GENERATED" in text

    from vn.repo import load_project
    schema_n = load_project(root)["save_schema"]
    defaults = (gen / "state/defaults.gen.rpy").read_text(encoding="utf-8")
    assert f"default vn_save_schema = {schema_n}" in defaults
    assert f"define vn_build_save_schema = {schema_n}" in defaults
    assert "init -980 python in g:" in defaults
    assert "default g.route = " in defaults

    snapshot = (gen / "state/snapshot.gen.rpy").read_text(encoding="utf-8")
    assert "('g', 'route')" in snapshot
    migrations = (gen / "state/migrations.gen.rpy").read_text(encoding="utf-8")
    assert "_vn_load_migration(" in migrations or "миграций нет" in migrations

    chars = (gen / "registry/characters.gen.rpy").read_text(encoding="utf-8")
    assert "define mira = Character(_('Мира')" in chars

    manifest = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "gen_manifest@1"
    assert "project.yaml" in manifest["inputs"]


def test_compile_is_idempotent(repo_root, tmp_path):
    root = skeleton_no_chapters(repo_root, tmp_path)
    gen = tmp_path / "generated"
    compile_content(root, out_dir=gen)
    res2 = compile_content(root, out_dir=gen)
    assert res2.written == []
    assert len(res2.skipped) == len(BASE_OUTPUTS)
    assert res2.deleted == []


def test_orphan_cleanup_removes_rpy_and_rpyc(repo_root, tmp_path):
    root = skeleton_no_chapters(repo_root, tmp_path)
    gen = tmp_path / "generated"
    compile_content(root, out_dir=gen)

    manifest_path = gen / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    orphan_rpy = gen / "scenes" / "ch99" / "ch99_s010.gen.rpy"
    orphan_rpy.parent.mkdir(parents=True)
    orphan_rpy.write_text("# stale\n", encoding="utf-8")
    orphan_rpy.with_suffix(".rpyc").write_bytes(b"stale")
    manifest["outputs"]["scenes/ch99/ch99_s010.gen.rpy"] = "deadbeef"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    res = compile_content(root, out_dir=gen)
    assert not orphan_rpy.exists()
    assert not orphan_rpy.with_suffix(".rpyc").exists()
    assert "scenes/ch99/ch99_s010.gen.rpy" in res.deleted


def test_chapters_require_sdk(repo_root, tmp_path, monkeypatch):
    """Главы без RENPY_SDK -> внятный CompileError, не трейсбек (G24)."""
    root = skeleton_no_chapters(repo_root, tmp_path)
    ch = root / "content" / "chapters" / "ch01_demo"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: draft\nentry_scene: s010\nscene_order: [s010]\n",
        encoding="utf-8",
    )
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nexits: {}\n", encoding="utf-8"
    )
    (ch / "scenes" / "s010_intro.scene.rpy").write_text(
        "label ch01_s010__body:\n    \"…\"\n    return\n", encoding="utf-8"
    )
    monkeypatch.delenv("RENPY_SDK", raising=False)
    with pytest.raises(CompileError, match="RENPY_SDK"):
        compile_content(root, out_dir=tmp_path / "gen")
