"""Ассет-конвейер (раздел 2, G13): трансформации, кэш, orphan-очистка, конвенции."""

import json

from PIL import Image

from vn.assets.pipeline import build_assets, sprite_tree


def _png(path, size=(64, 64), color=(200, 100, 50, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, "PNG")


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "assets_src" / "png").mkdir(parents=True)
    return root


def test_build_transforms_and_caches(tmp_path):
    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    # Цвета разные: одинаковые байты конвейер дедуплицирует через кэш (from_cache)
    _png(ch / "base.png", color=(10, 20, 30, 255))
    _png(ch / "outfits" / "school.png", color=(40, 50, 60, 255))
    _png(ch / "faces" / "smile.png", color=(70, 80, 90, 255))
    _png(root / "assets_src" / "png" / "backgrounds" / "gate" / "day.png", (128, 72))

    res = build_assets(root)
    assert res.errors == []
    assert sorted(res.built) == [
        "bg/gate/day.webp",
        "spr/mira/a/base@2.webp",
        "spr/mira/a/faces/smile@2.webp",
        "spr/mira/a/outfits/school@2.webp",
    ]
    assert (root / "game/assets/spr/mira/a/outfits/school@2.webp").is_file()

    # Повторная сборка: всё актуально, трансформации не гоняются
    res2 = build_assets(root)
    assert res2.built == [] and res2.from_cache == []
    assert len(res2.fresh) == 4

    # Удалили выход руками -> восстановление ИЗ КЭША без энкода
    (root / "game/assets/bg/gate/day.webp").unlink()
    res3 = build_assets(root)
    assert res3.from_cache == ["bg/gate/day.webp"]
    assert res3.built == []


def test_audio_stems_branch_copies_ogg(tmp_path):
    """Зона звука — assets_src/audio_stems/ (ARCHITECTURE.md:393, folder-layout.md:29):
    конвейер обязан смотреть именно туда, иначе ветка copy_audio мертва и звук
    не попадает в игру никаким путём."""
    root = _mk_root(tmp_path)
    src = root / "assets_src" / "audio_stems" / "bgm" / "market_theme.ogg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"OggS-not-really-but-copy_audio-is-bytewise")

    res = build_assets(root)
    assert res.errors == []
    assert res.built == ["audio/bgm/market_theme.ogg"]
    out = root / "game/assets/audio/bgm/market_theme.ogg"
    assert out.is_file()
    assert out.read_bytes() == src.read_bytes()   # copy_audio копирует байт в байт


def test_manifest_matches_registered_schema(tmp_path, repo_root):
    """G16: манифест объявляет assets_manifest@1 — документ обязан проходить схему
    из реестра (иначе объявление — пустая строка, а читатели манифеста слепы)."""
    from vn.schemas import SchemaRegistry

    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "base.png", color=(11, 22, 33, 255))
    (root / "assets_src" / "audio_stems" / "sfx").mkdir(parents=True)
    (root / "assets_src" / "audio_stems" / "sfx" / "door.ogg").write_bytes(b"sfx-bytes")
    assert build_assets(root).errors == []

    doc = json.loads((root / ".vncache" / "assets-manifest.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "assets_manifest@1"
    assert "audio/sfx/door.ogg" in doc["outputs"]
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, "assets-manifest.json") == []


def test_orphan_output_cleanup(tmp_path):
    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "base.png", color=(10, 20, 30, 255))
    _png(ch / "faces" / "smile.png", color=(70, 80, 90, 255))
    build_assets(root)

    (ch / "faces" / "smile.png").unlink()   # источник удалён
    res = build_assets(root)
    assert res.deleted == ["spr/mira/a/faces/smile@2.webp"]
    assert not (root / "game/assets/spr/mira/a/faces/smile@2.webp").exists()


def test_naming_violation_and_missing_base(tmp_path):
    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "outfits" / "School.png")     # не-slug имя; base.png нет вовсе
    res = build_assets(root)
    text = "\n".join(res.errors)
    assert "вне конвенции" in text
    assert "нет обязательного base.png" in text


def test_sprite_tree_scan(tmp_path):
    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "base.png")
    _png(ch / "outfits" / "school.png")
    build_assets(root)
    tree = sprite_tree(root)
    assert tree == {"mira": {"a": {"base": ["base"], "outfits": ["school"],
                                   "faces": [], "overlays": []}}}


def test_images_emitter_validates_matrix(tmp_path):
    """required-комбинация без файла -> ошибка; слой вне matrix -> предупреждение."""
    from vn.content.images import ImagesReport, emit_images

    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "base.png")
    _png(ch / "outfits" / "school.png")
    _png(ch / "outfits" / "party.png")      # вне matrix
    build_assets(root)

    doc = {
        "schema": "character@1", "id": "mira", "name": "Мира", "color": "#c94f7c",
        "matrix": {
            "poses": ["a"], "outfits": ["school", "casual"], "emotions": ["neutral"],
            "required": [{"pose": "a", "outfits": ["school", "casual"]}],
        },
    }
    rep = ImagesReport()
    text = emit_images(root, {}, [("mira/character.yaml", doc)], rep, "# h\n")
    assert any("нет слоя outfits/casual" in e for e in rep.errors)
    assert any("outfits/party" in w for w in rep.warnings)
    assert 'attribute school default "assets/spr/mira/a/outfits/school@2.webp" if_any ["a"]' in text
    assert 'define config.tag_layer = {"mira": "sprites"}' in text


def test_images_emitter_forbidden_and_disjoint(tmp_path):
    """forbidden-комбинация с собранным слоем -> ошибка; пересечение имён групп -> ошибка."""
    from vn.content.images import ImagesReport, emit_images

    root = _mk_root(tmp_path)
    ch = root / "assets_src" / "png" / "characters" / "mira" / "a"
    _png(ch / "base.png", color=(1, 2, 3, 255))
    _png(ch / "faces" / "blush.png", color=(4, 5, 6, 255))
    build_assets(root)

    doc = {
        "schema": "character@1", "id": "mira", "name": "Мира", "color": "#c94f7c",
        "matrix": {
            "poses": ["a"], "outfits": ["a"],            # 'a' в двух группах — коллизия
            "emotions": ["blush"],
            "forbidden": [{"pose": "a", "emotions": ["blush"]}],
        },
    }
    rep = ImagesReport()
    emit_images(root, {}, [("mira/character.yaml", doc)], rep, "# h\n")
    text = "\n".join(rep.errors)
    assert "faces/blush для позы 'a' собран, но комбинация запрещена" in text
    assert "используется в двух группах matrix" in text


def test_graph_export(repo_root):
    from vn.content.graph import build_graph

    text = build_graph(repo_root)
    assert "ch01_s010" in text
    assert '-->|"gate"| ch01_s020' in text
    assert "vn_end" in text                 # финальная сцена без exits
