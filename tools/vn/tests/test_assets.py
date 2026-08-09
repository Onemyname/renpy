"""Ассет-конвейер (раздел 2, G13, ADR-0012): трансформации, кэш, orphan-очистка,
конвенции имён, форматы мастеров, оверсэмпл-варианты, прозрачность."""

import json

from helpers import img, mk_root, write_project

from vn.assets.pipeline import build_assets, sprite_tree


def _png(path, size=(64, 48), color=(200, 100, 50, 255)):
    return img(path, size, "RGBA", "PNG", color)


def _opaque(path, size=(64, 48), fmt="PNG", color=(200, 100, 50)):
    return img(path, size, "RGB", fmt, color)


def _char(root, key="mira", pose="a"):
    return root / "assets_src" / "art" / "characters" / key / pose


# ── Базовый конвейер ─────────────────────────────────────────────────────────

def test_build_transforms_and_caches(tmp_path):
    root = mk_root(tmp_path)
    ch = _char(root)
    # Цвета разные: одинаковые байты конвейер дедуплицирует через кэш (from_cache)
    _png(ch / "base.png", (128, 96), color=(10, 20, 30, 255))
    _png(ch / "outfits" / "school.png", (128, 96), color=(40, 50, 60, 255))
    _png(ch / "faces" / "smile.png", (128, 96), color=(70, 80, 90, 255))
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))

    res = build_assets(root)
    assert res.errors == []
    # Референсный вариант — БЕЗ суффикса (иначе Ren'Py не включит автоподбор),
    # крупный — рядом с @2. Плюс миниатюра фона для сетки галереи.
    assert sorted(res.built + res.from_cache) == [
        "bg/gate/day.thumb.webp",
        "bg/gate/day.webp",
        "bg/gate/day@2.webp",
        "spr/mira/a/base.webp",
        "spr/mira/a/base@2.webp",
        "spr/mira/a/faces/smile.webp",
        "spr/mira/a/faces/smile@2.webp",
        "spr/mira/a/outfits/school.webp",
        "spr/mira/a/outfits/school@2.webp",
    ]

    # Повторная сборка: всё актуально, трансформации не гоняются
    res2 = build_assets(root)
    assert res2.built == [] and res2.from_cache == []
    assert len(res2.fresh) == 9

    # Удалили выход руками -> восстановление ИЗ КЭША без энкода
    (root / "game/assets/bg/gate/day.webp").unlink()
    res3 = build_assets(root)
    assert res3.from_cache == ["bg/gate/day.webp"]
    assert res3.built == []


def test_variant_sizes_and_reference_name(tmp_path):
    """Референс = вёрстка, @2 = мастер. Это и есть контракт оверсэмпла."""
    from PIL import Image

    root = mk_root(tmp_path)
    _png(_char(root) / "base.png", (128, 96))
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))
    assert build_assets(root).errors == []

    assets = root / "game/assets"
    assert Image.open(assets / "spr/mira/a/base.webp").size == (64, 48)
    assert Image.open(assets / "spr/mira/a/base@2.webp").size == (128, 96)
    assert Image.open(assets / "bg/gate/day.webp").size == (64, 48)
    assert Image.open(assets / "bg/gate/day@2.webp").size == (128, 96)


def test_small_master_skips_large_variant(tmp_path):
    """Мастер ровно под 1x: @2 не собирается, но и не молчит."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (64, 48))
    res = build_assets(root)
    assert res.errors == []
    assert not (root / "game/assets/bg/gate/day@2.webp").exists()
    assert any("@2" in s for s in res.skipped_variants)


def test_master_below_shipping_size_is_error(tmp_path):
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (32, 24))
    res = build_assets(root)
    assert any("меньше отгружаемого" in e for e in res.errors)


def test_source_min_enforced(tmp_path):
    """source_min ставится по БУДУЩЕМУ качеству: мастер 1x проходит сборку,
    но нарушает объявленный минимум и обязан краснеть."""
    root = mk_root(tmp_path, render_extra={"classes": {"bg": {"source_min": [128, 96]}}})
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (64, 48))
    res = build_assets(root)
    assert any("меньше требуемого минимума" in e for e in res.errors)


# ── Форматы мастеров ─────────────────────────────────────────────────────────

def test_opaque_classes_accept_jpeg_and_webp(tmp_path):
    """JPEG/WebP-мастер для непрозрачных классов — легальны (ADR-0012)."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.jpg", (128, 96), "JPEG")
    _opaque(root / "assets_src/art/cg/ch01/kiss.webp", (128, 96), "WEBP")
    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/bg/gate/day.webp").is_file()
    assert (root / "game/assets/cg/ch01/kiss@2.webp").is_file()


def test_sprite_rejects_jpeg_master(tmp_path):
    """У JPEG нет альфа-канала — для спрайта это не вкусовщина, а невозможность."""
    root = mk_root(tmp_path)
    _opaque(_char(root) / "base.jpg", (128, 96), "JPEG")
    res = build_assets(root)
    assert any("нет обязательного base" in e for e in res.errors)


def test_bg_output_is_rgb_without_alpha(tmp_path):
    """alpha: forbid -> альфа отбрасывается: ~20 % веса файла ни за что."""
    from PIL import Image

    root = mk_root(tmp_path)
    _png(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))
    res = build_assets(root)
    assert res.errors == []
    assert any("прозрачность не используется" in w for w in res.warnings)
    assert Image.open(root / "game/assets/bg/gate/day.webp").mode == "RGB"


# ── Прозрачность спрайтов ────────────────────────────────────────────────────

def test_sprite_without_alpha_is_error(tmp_path):
    """Скриншот с невырезанным фоном лёг бы в игре прямоугольником поверх фона."""
    root = mk_root(tmp_path)
    img(_char(root) / "base.png", (128, 96), "RGBA", "PNG", transparent_border=False)
    res = build_assets(root)
    assert any("требует прозрачности" in e for e in res.errors)


def test_layer_canvas_mismatch_is_error(tmp_path):
    """Слои позы обязаны лежать на одном холсте: layeredimage кладёт их в (0,0)."""
    root = mk_root(tmp_path)
    _png(_char(root) / "base.png", (128, 96))
    _png(_char(root) / "faces" / "smile.png", (100, 96))
    res = build_assets(root)
    assert any("на ОДНОМ холсте" in e for e in res.errors)


def test_declared_canvas_is_enforced(tmp_path):
    """character.yaml: canvas перестал быть мёртвой поверхностью схемы."""
    root = mk_root(tmp_path)
    _png(_char(root) / "base.png", (128, 96))
    decl = root / "content" / "characters" / "mira" / "character.yaml"
    decl.parent.mkdir(parents=True)
    decl.write_text(
        "schema: character@1\nid: mira\nname: M\ncolor: \"#ffffff\"\n"
        "canvas: [200, 300]\n", encoding="utf-8")
    res = build_assets(root)
    assert any("холст 128x96 != 200x300" in e for e in res.errors)


# ── Никаких тихих потерь ─────────────────────────────────────────────────────

def test_unconsumed_master_is_error(tmp_path):
    """Файл в зоне мастеров, который не взяла ни одна ветка, обязан краснеть.
    Раньше он просто исчезал и всплывал чёрным экраном в игре."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))
    _opaque(root / "assets_src/art/sketches/idea.png", (128, 96))   # чужая папка
    res = build_assets(root)
    assert any("не подобран ни одной веткой" in e for e in res.errors)


def test_unsupported_format_in_known_zone_is_error(tmp_path):
    """В опознанной зоне неподходящий формат называет себя точнее — форматом."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))
    (root / "assets_src/art/backgrounds/gate/wip.psd").write_bytes(b"not-a-master")
    res = build_assets(root)
    assert any("формат .psd не разрешён" in e for e in res.errors)


def test_nested_backgrounds_are_built(tmp_path):
    """Вложенность каталогов фонов — организационная и больше не теряется молча."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/apartment/living_room/day.png", (128, 96))
    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/bg/apartment/living_room/day.webp").is_file()
    assert (root / "game/assets/bg/apartment/living_room/day@2.webp").is_file()


def test_legacy_png_zone_still_works(tmp_path):
    """assets_src/png/ — исторический алиас: работа художника не ломается."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/png/backgrounds/gate/day.png", (128, 96))
    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/bg/gate/day.webp").is_file()


# ── Инфраструктура ───────────────────────────────────────────────────────────

def test_audio_stems_branch_copies_ogg(tmp_path):
    """Зона звука — assets_src/audio_stems/ (folder-layout.md): конвейер обязан
    смотреть именно туда, иначе ветка copy_audio мертва."""
    root = mk_root(tmp_path)
    src = root / "assets_src" / "audio_stems" / "bgm" / "market_theme.ogg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"OggS-not-really-but-copy_audio-is-bytewise")

    res = build_assets(root)
    assert res.errors == []
    assert res.built == ["audio/bgm/market_theme.ogg"]
    out = root / "game/assets/audio/bgm/market_theme.ogg"
    assert out.read_bytes() == src.read_bytes()   # copy_audio копирует байт в байт


def test_manifest_matches_registered_schema(tmp_path, repo_root):
    """G16: манифест объявляет assets_manifest@1 — документ обязан проходить схему
    из реестра (иначе объявление — пустая строка, а читатели манифеста слепы)."""
    import shutil

    from vn.schemas import SchemaRegistry

    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    _png(_char(root) / "base.png", (128, 96), color=(11, 22, 33, 255))
    (root / "assets_src" / "audio_stems" / "sfx").mkdir(parents=True)
    (root / "assets_src" / "audio_stems" / "sfx" / "door.ogg").write_bytes(b"sfx-bytes")
    assert build_assets(root).errors == []

    doc = json.loads((root / ".vncache" / "assets-manifest.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "assets_manifest@1"
    assert "audio/sfx/door.ogg" in doc["outputs"]
    # Стоимость декодирования пишется на сборке: модель памяти не декодирует заново
    assert doc["outputs"]["spr/mira/a/base.webp"]["cost_px"] > 0
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, "assets-manifest.json") == []


def test_orphan_output_cleanup(tmp_path):
    root = mk_root(tmp_path)
    ch = _char(root)
    _png(ch / "base.png", (128, 96), color=(10, 20, 30, 255))
    _png(ch / "faces" / "smile.png", (128, 96), color=(70, 80, 90, 255))
    build_assets(root)

    (ch / "faces" / "smile.png").unlink()   # мастер удалён
    res = build_assets(root)
    assert sorted(res.deleted) == ["spr/mira/a/faces/smile.webp",
                                   "spr/mira/a/faces/smile@2.webp"]
    assert not (root / "game/assets/spr/mira/a/faces/smile.webp").exists()


def test_naming_violation_and_missing_base(tmp_path):
    root = mk_root(tmp_path)
    _png(_char(root) / "outfits" / "School.png", (128, 96))   # не-slug; base.png нет
    res = build_assets(root)
    text = "\n".join(res.errors)
    assert "вне конвенции" in text
    assert "нет обязательного base" in text


def test_render_profile_change_invalidates_cache(tmp_path):
    """Правка качества в project.yaml обязана пересобрать ветку: параметры
    трансформации входят в хеш источника (G13)."""
    root = mk_root(tmp_path)
    _opaque(root / "assets_src/art/backgrounds/gate/day.png", (128, 96))
    assert build_assets(root).errors == []
    assert build_assets(root).built == []

    write_project(root, render_extra={"classes": {"bg": {"quality": {"full": 40}}}})
    res = build_assets(root)
    assert "bg/gate/day.webp" in res.built


def test_sprite_tree_scan(tmp_path):
    root = mk_root(tmp_path)
    ch = _char(root)
    _png(ch / "base.png", (128, 96))
    _png(ch / "outfits" / "school.png", (128, 96))
    build_assets(root)
    # Дерево отдаёт РЕФЕРЕНСНЫЕ имена: @2 — вариант того же слоя, а не второй слой
    tree = sprite_tree(root)
    assert tree == {"mira": {"a": {"base": ["base"], "outfits": ["school"],
                                   "faces": [], "overlays": []}}}


# ── Эмиттер образов ──────────────────────────────────────────────────────────

def test_images_emitter_validates_matrix(tmp_path):
    """required-комбинация без файла -> ошибка; слой вне matrix -> предупреждение."""
    from vn.content.images import ImagesReport, emit_images

    root = mk_root(tmp_path)
    ch = _char(root)
    _png(ch / "base.png", (128, 96))
    _png(ch / "outfits" / "school.png", (128, 96))
    _png(ch / "outfits" / "party.png", (128, 96))      # вне matrix
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
    # Ссылка — на референсный вариант: @2 подставит движок сам
    assert 'attribute school default "assets/spr/mira/a/outfits/school.webp" if_any ["a"]' in text
    assert "@2" not in text
    assert 'define config.tag_layer = {"mira": "sprites"}' in text


def test_images_emitter_forbidden_and_disjoint(tmp_path):
    """forbidden-комбинация с собранным слоем -> ошибка; пересечение имён групп -> ошибка."""
    from vn.content.images import ImagesReport, emit_images

    root = mk_root(tmp_path)
    ch = _char(root)
    _png(ch / "base.png", (128, 96), color=(1, 2, 3, 255))
    _png(ch / "faces" / "blush.png", (128, 96), color=(4, 5, 6, 255))
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
