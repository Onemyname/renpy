"""Модель памяти образов и бюджет сцены (ADR-0012).

Ценность этих тестов — в верности формулам ДВИЖКА, а не нашим представлениям:
если Ren'Py считает лимит в пикселях, а мы в байтах, «зелёный бюджет» ничего не
гарантирует. Поэтому здесь дословно проверяются три вещи из renpy/display/im.py:
лимит = mb * 1024 * 1024 // 4, стоимость = bbox * 1.34, bbox обрезается по альфе.
"""

import shutil

from helpers import img, mk_root, write_project

from vn.assets import imaging
from vn.assets.memory import (_character_index, analyze, load_costs,
                              recommended_cache_mb)
from vn.assets.pipeline import build_assets
from vn.assets.render_config import load_render_config

# Манифест-образец для предындексации персонажей. Числа подобраны так, чтобы каждая
# ветка формулы ADR-0012 читалась в ответе: у mira дороже поза b (но только на @2),
# у наряда два варианта разной цены, у nika крупного варианта нет вовсе — движок
# откатится на референсный. Фон в наборе есть намеренно: он не персонаж.
CHAR_COSTS = {
    "spr/mira/a/base.webp": 10,
    "spr/mira/a/base@2.webp": 40,
    "spr/mira/a/outfits/school.webp": 3,
    "spr/mira/a/outfits/school@2.webp": 12,
    "spr/mira/a/outfits/casual@2.webp": 20,
    "spr/mira/a/faces/smile@2.webp": 5,
    "spr/mira/b/base@2.webp": 100,
    "spr/nika/c/base.webp": 7,
    "spr/nika/c/faces/sad.webp": 2,
    "bg/roof/day@2.webp": 999,
}


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


def test_character_index_keeps_worst_case_formula():
    """Предындексация обязана давать РОВНО те числа, что расчёт по одному персонажу:
    base + самый тяжёлый наряд + самая тяжёлая эмоция на том масштабе, который
    реально грузится, с откатом на референсный вариант. Формула здесь записана
    числами, а не кодом: оптимизация не должна тихо менять вердикт бюджета.
    """
    # @2: у mira поза b (100) дороже позы a (40 + max(12, 20) + 5 = 65);
    # у nika крупных вариантов нет — откат на референсные (7 + 2).
    assert _character_index(CHAR_COSTS, 2) == {"mira": (100, "b"), "nika": (9, "c")}
    # @1: позы b на референсном масштабе не существует, остаётся a (10 + 3 + 0).
    assert _character_index(CHAR_COSTS, 1) == {"mira": (13, "a"), "nika": (9, "c")}
    # Персонаж без спрайтов в индекс не попадает — сцена считает его нулём
    assert "bg" not in _character_index(CHAR_COSTS, 2)


def test_character_index_ignores_manifest_order():
    """Индекс строится одним проходом по манифесту, поэтому его результат не имеет
    права зависеть от порядка ключей: порядок задаёт обход assets_src на сборке
    (файловая система), а бюджет сцены — величина проекта, не машины сборки."""
    reversed_costs = dict(reversed(list(CHAR_COSTS.items())))
    shuffled = dict(sorted(CHAR_COSTS.items(), key=lambda kv: kv[1]))
    for scale in (1, 2):
        assert _character_index(reversed_costs, scale) == _character_index(CHAR_COSTS, scale)
        assert _character_index(shuffled, scale) == _character_index(CHAR_COSTS, scale)


def test_character_costs_indexed_once_for_all_scenes(tmp_path, repo_root, monkeypatch):
    """Стоимость персонажа считается ОДИН раз на отчёт, а не на каждую сцену.

    Расчёт по требованию перебирал весь манифест заново для каждого участника
    каждой сцены, и стадия «модель памяти» росла как произведение «сцены × выходы»:
    на корпусе 2000 сцен это измеримо (7.6 ARCHITECTURE.md), на порядок больше —
    уже минуты. Число проходов и есть предмет проверки: оно обязано остаться
    единицей при любом количестве сцен, иначе произведение вернётся незаметно.
    """
    from vn.assets import memory

    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    ch = root / "assets_src" / "art" / "characters" / "mira" / "a"
    img(ch / "base.png", (128, 96), "RGBA", "PNG", color=(1, 2, 3, 255))
    img(ch / "outfits" / "school.png", (128, 96), "RGBA", "PNG", color=(4, 5, 6, 255))
    assert build_assets(root).errors == []

    # Один и тот же участник в трёх сценах двух глав: если бы индекс строился в
    # цикле, порядок обхода сцен мог бы влиять на числа — а он не влияет.
    for ch_dir, scene_ids in (("ch01_demo", ("s010", "s020")), ("ch02_demo", ("s010",))):
        scenes = root / "content" / "chapters" / ch_dir / "scenes"
        scenes.mkdir(parents=True)
        for sid in scene_ids:
            (scenes / f"{sid}_x.scene.yaml").write_text(
                f"schema: scene@1\nid: {sid}\nparticipants: [mira]\n", encoding="utf-8")

    calls = []
    real_index = memory._character_index

    def counting_index(costs, scale):
        calls.append(scale)
        return real_index(costs, scale)

    monkeypatch.setattr(memory, "_character_index", counting_index)
    rep = memory.analyze(root)

    assert len(rep.scenes) == 3
    assert calls == [rep.scale], f"индекс построен {len(calls)} раз(а) на 3 сцены"
    per_scene = {sc.scene_id: dict((label, px) for label, px in sc.parts) for sc in rep.scenes}
    costs = load_costs(root)
    expected = costs["spr/mira/a/base@2.webp"] + costs["spr/mira/a/outfits/school@2.webp"]
    assert {s: parts["mira (a)"] for s, parts in per_scene.items()} == {
        "ch01_s010": expected, "ch01_s020": expected, "ch02_s010": expected}
