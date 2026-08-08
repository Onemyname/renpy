"""Галерея (gallery@1, ADR-0010): валидация деклараций и состав реестра.

Рантайм-часть (persistent, seen_images) проверяется e2e в vn test smoke —
он пишет .vncache/smoke/gallery.json с фактическими разблокировками.
"""

import shutil

import pytest

from vn.content.compile import CompileError, _emit_gallery, compile_content
from vn.repo import load_yaml
from vn.schemas import SchemaRegistry

from conftest import REPO_ROOT


class _Rep:
    """Заглушка CompileResult: нужны только warnings."""

    def __init__(self):
        self.warnings = []


def _mk_assets(root, *rel_paths):
    for rel in rel_paths:
        p = root / "game" / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def _doc(items, categories=None):
    return [("content/gallery/t.gallery.yaml", {
        "schema": "gallery@1",
        "categories": categories or {"cg": {"title_key": "ui.gallery.cat.cg"}},
        "items": items,
    })]


def test_registry_shape_and_thumb_resolution(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/a.thumb.webp", "cg/ch01/b.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(root, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "variants": ["cg/ch01/b"], "title_key": "gal.a.title",
                 "unlock": {"seen_image": True}},
    }), {"ch01_s010"}, {"ch01"}, {"g.route"}, {}, rep, errors, [("t", "d")])
    assert errors == []
    assert "define VN_GALLERY_CATEGORIES" in text
    # превью взято из конвейера, а не полноразмерный кадр
    assert "'thumb': 'assets/cg/ch01/a.thumb.webp'" in text
    assert "'image_name': 'cg ch01 a'" in text          # для renpy.seen_image
    assert "'variants': ['assets/cg/ch01/b.webp']" in text


def test_missing_asset_is_error(tmp_path):
    # Строгая проверка включается только при собранной зоне ассетов
    (tmp_path / "game" / "assets").mkdir(parents=True)
    rep, errors = _Rep(), []
    _emit_gallery(tmp_path, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/ghost",
                 "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("нет в game/assets" in e for e in errors)


def test_unknown_category_and_bad_kind(tmp_path):
    root = tmp_path
    _mk_assets(root, "mov/demo/x.webm", "cg/ch01/a.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "bad_cat": {"category": "nope", "kind": "image", "asset": "cg/ch01/a",
                    "title_key": "t", "unlock": {"always": True}},
        "bad_kind": {"category": "cg", "kind": "image", "asset": "mov/demo/x",
                     "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    text = "\n".join(errors)
    assert "категория 'nope' не объявлена" in text
    assert "kind: image, но ассет mov/demo/x — видео" in text


def test_unlock_anchor_must_exist(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "s": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"scene": "ch09_s999"}},
        "c": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"chapter_done": "ch77"}},
        "v": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"var": "g.ghost"}},
    }), {"ch01_s010"}, {"ch01"}, {"g.route"}, {}, rep, errors, [("t", "d")])
    text = "\n".join(errors)
    assert "unlock.scene ch09_s999" in text
    assert "unlock.chapter_done ch77" in text
    assert "unlock.var g.ghost" in text


def test_seen_image_only_for_images(tmp_path):
    root = tmp_path
    _mk_assets(root, "mov/demo/x.webm", "cg/ch01/p.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "m": {"category": "cg", "kind": "movie", "asset": "mov/demo/x",
              "thumb": "cg/ch01/p", "title_key": "t",
              "unlock": {"seen_image": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("seen_image работает только" in e for e in errors)


def test_warnings_for_missing_thumb_and_orphan_cg(tmp_path):
    root = tmp_path
    # CG без thumb-варианта + осиротевший CG, не объявленный в галерее
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/orphan.webp", "mov/demo/x.webm")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "title_key": "t", "unlock": {"always": True}},
        "mov_x": {"category": "cg", "kind": "movie", "asset": "mov/demo/x",
                  "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert errors == []
    text = "\n".join(rep.warnings)
    assert "нет превью" in text                     # картинка без thumb
    assert "kind: movie без thumb" in text           # видео без постера
    assert "cg/ch01/orphan" in text and "не объявлен в галерее" in text


def test_duplicate_ids_across_files_are_error(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp")
    docs = _doc({"dup": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                         "title_key": "t", "unlock": {"always": True}}})
    docs.append(("content/gallery/other.gallery.yaml", {
        "schema": "gallery@1", "categories": {},
        "items": {"dup": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                          "title_key": "t", "unlock": {"always": True}}}}))
    rep, errors = _Rep(), []
    _emit_gallery(root, docs, set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("объявлен дважды" in e for e in errors)


def test_repo_gallery_declaration_is_schema_valid(repo_root):
    """Боевая декларация проекта валидна и все её строки объявлены."""
    doc = load_yaml(repo_root / "content" / "gallery" / "core.gallery.yaml")
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, "content/gallery/core.gallery.yaml") == []

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    for cid, cspec in doc["categories"].items():
        assert cspec["title_key"] in strings, f"категория {cid}: нет строки"
    for gid, spec in doc["items"].items():
        assert spec["title_key"] in strings, f"{gid}: нет title_key"
        if spec.get("desc_key"):
            assert spec["desc_key"] in strings, f"{gid}: нет desc_key"


def test_repo_compiles_gallery_registry(repo_root, tmp_path):
    """Сквозная компиляция реального проекта эмитит реестр галереи."""
    import os

    sdk = os.environ.get("RENPY_SDK")
    if not (sdk and (REPO_ROOT / "game").is_dir()):
        pytest.skip("нужен RENPY_SDK для компиляции сцен")
    gen = tmp_path / "generated"
    compile_content(repo_root, out_dir=gen)
    text = (gen / "registry" / "gallery.gen.rpy").read_text(encoding="utf-8")
    assert "define VN_GALLERY = {" in text
    assert "cg_ch01_rooftop" in text
    # locked-элемент тоже в реестре: закрытость — состояние, а не отсутствие записи
    assert "cg_ch01_route_mira" in text


def test_unbuilt_assets_zone_warns_not_errors(tmp_path):
    """vn content compile без предшествующей сборки — легитимное состояние:
    ссылки не проверяются, но об этом честно предупреждают (зона G4 производная)."""
    rep, errors = _Rep(), []
    _emit_gallery(tmp_path, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/ghost",
                 "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert errors == []
    assert any("game/assets не собран" in w for w in rep.warnings)
