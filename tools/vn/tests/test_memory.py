"""Модель памяти образов и бюджет сцены (ADR-0012).

Ценность этих тестов — в верности формулам ДВИЖКА, а не нашим представлениям:
если Ren'Py считает лимит в пикселях, а мы в байтах, «зелёный бюджет» ничего не
гарантирует. Поэтому здесь дословно проверяются три вещи из renpy/display/im.py:
лимит = mb * 1024 * 1024 // 4, стоимость = bbox * 1.34, bbox обрезается по альфе.
"""

import shutil

from helpers import img, mk_root, write_project

from vn.assets import imaging
from vn.assets.memory import analyze, load_costs, recommended_cache_mb
from vn.assets.pipeline import build_assets
from vn.assets.render_config import load_render_config


def test_cache_limit_matches_engine_formula():
    """renpy/display/im.py: cache_limit = image_cache_size_mb * 1024 * 1024 // 4."""
    cfg = load_render_config(project={"render": {"image_cache_mb": 400}})
    assert cfg.cache_limit_px == 400 * 1024 * 1024 // 4 == 104857600
    assert cfg.scene_budget_px == cfg.cache_limit_px // 3


def test_decoded_cost_uses_alpha_bbox_not_canvas(tmp_path):
    """optimize_texture_bounds (дефолт True) обрезает текстуру по непрозрачному
    bbox: прозрачные поля холста памяти НЕ стоят. Модель обязана это учитывать,
    иначе спрайты выглядят вчетверо дороже, чем есть, и кэш раздувают зря."""
    from PIL import Image

    opaque = tmp_path / "opaque.webp"
    Image.new("RGBA", (200, 200), (10, 20, 30, 255)).save(opaque, "WEBP", lossless=True)

    padded = tmp_path / "padded.webp"
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (50, 50), (10, 20, 30, 255)), (75, 75))
    im.save(padded, "WEBP", lossless=True)

    full = imaging.decoded_cost_px(opaque.read_bytes())
    small = imaging.decoded_cost_px(padded.read_bytes())
    assert full == int(200 * 200 * imaging.TEXTURE_MULTIPLIER)
    # 50x50 + expand_texture_bounds(8) с каждой стороны -> 66x66
    assert small == int(66 * 66 * imaging.TEXTURE_MULTIPLIER)
    assert small < full / 8


def test_costs_recorded_and_scene_worst_case(tmp_path, repo_root):
    """Сцена = фон + участники (base + тяжелейший наряд + тяжелейшая эмоция) + UI."""
    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    art = root / "assets_src" / "art"
    img(art / "backgrounds" / "gate" / "day.png", (128, 96), "RGB", "PNG")
    ch = art / "characters" / "mira" / "a"
    img(ch / "base.png", (128, 96), "RGBA", "PNG", color=(1, 2, 3, 255))
    img(ch / "outfits" / "school.png", (128, 96), "RGBA", "PNG", color=(4, 5, 6, 255))
    img(ch / "faces" / "smile.png", (128, 96), "RGBA", "PNG", color=(7, 8, 9, 255))
    assert build_assets(root).errors == []

    costs = load_costs(root)
    assert costs["bg/gate/day.webp"] > 0
    assert costs["spr/mira/a/base@2.webp"] > costs["spr/mira/a/base.webp"]

    (root / "content" / "locations" / "gate").mkdir(parents=True)
    (root / "content" / "locations" / "gate" / "location.yaml").write_text(
        "schema: location@1\nid: gate\nbackgrounds:\n  day: assets/bg/gate/day.webp\n",
        encoding="utf-8")
    scenes = root / "content" / "chapters" / "ch01_demo" / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "s010_meet.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nlocation: gate/day\nparticipants: [mira]\n",
        encoding="utf-8")

    rep = analyze(root)
    assert rep.scale == 2                      # худший случай — крупнейший вариант
    worst = rep.worst
    assert worst is not None and worst.scene_id == "ch01_s010"
    labels = {label for label, _ in worst.parts}
    assert "bg gate/day" in labels
    assert any(label.startswith("mira") for label in labels)
    # Персонаж считается по САМОЙ дорогой комбинации, а не по сумме всех слоёв
    char_px = next(px for label, px in worst.parts if label.startswith("mira"))
    assert char_px == (costs["spr/mira/a/base@2.webp"]
                       + costs["spr/mira/a/outfits/school@2.webp"]
                       + costs["spr/mira/a/faces/smile@2.webp"])
    assert rep.errors == []


def test_scene_over_budget_is_error(tmp_path, repo_root):
    """Переполнение кэша Ren'Py не роняет — оно молча превращает игру в фризы.
    Поэтому это ошибка сборки, а не наблюдение."""
    root = mk_root(tmp_path, screen=(512, 384),
                   render_extra={"image_cache_mb": 1})    # 262 Кпикс на весь кэш
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    img(root / "assets_src/art/backgrounds/gate/day.png", (1024, 768), "RGB", "PNG")
    assert build_assets(root).errors == []

    (root / "content" / "locations" / "gate").mkdir(parents=True)
    (root / "content" / "locations" / "gate" / "location.yaml").write_text(
        "schema: location@1\nid: gate\nbackgrounds:\n  day: assets/bg/gate/day.webp\n",
        encoding="utf-8")
    scenes = root / "content" / "chapters" / "ch01_demo" / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "s010_meet.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nlocation: gate/day\n", encoding="utf-8")

    rep = analyze(root)
    assert any("кэша при бюджете" in e for e in rep.errors)
    assert recommended_cache_mb(rep, 3) > 1


def test_emitted_render_config_matches_project(tmp_path, repo_root):
    """config.image_cache_size_mb больше не «дефолт SDK, о котором никто не знал»:
    он выводится из project.yaml и попадает в генерат."""
    from test_compile import skeleton_no_chapters

    from vn.content.compile import compile_content

    root = skeleton_no_chapters(repo_root, tmp_path)
    gen = tmp_path / "generated"
    compile_content(root, out_dir=gen)
    text = (gen / "render.gen.rpy").read_text(encoding="utf-8")
    cfg = load_render_config(root)
    assert f"define config.image_cache_size_mb = {cfg.image_cache_mb}" in text
    assert "define config.automatic_oversampling = 4" in text
    assert "init offset = -950" in text
