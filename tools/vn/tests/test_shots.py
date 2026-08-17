"""Послойные полнокадровые шоты (shots@1, ADR-0013): конвейер, эмиссия, модель."""

from __future__ import annotations

import shutil

from helpers import img, mk_root

from vn.assets.pipeline import build_assets, shot_tree
from vn.content.images import ImagesReport, _emit_shots, _shot_attrs, build_image_index, shot_tag

# Холст шота в tiny-профиле (экран 64x48, вариант @2 => мастер 128x96).
CANVAS = (128, 96)


def _shot_masters(root, ch="ch01", sid="s030", shot="sunset",
                  layers=("mira__school", "mira__casual")):
    base = root / "assets_src" / "art" / "shots" / ch / sid / shot
    img(base / "env.jpg", CANVAS, mode="RGB", fmt="JPEG")
    for name in layers:
        img(base / f"{name}.png", CANVAS)
    return base


DOC = {
    "schema": "shots@1",
    "scene": "s030",
    "shots": {
        "sunset": {
            "layers": {
                "env": {},
                "mira": {"variants": ["school", "casual"], "var": "g.mira_outfit"},
            },
            "order": ["env", "mira"],
        }
    },
}


def test_pipeline_builds_shot_layers_with_variants(tmp_path):
    root = mk_root(tmp_path)
    _shot_masters(root)
    rep = build_assets(root)
    assert not rep.errors, rep.errors
    out = root / "game" / "assets" / "shots" / "ch01" / "s030" / "sunset"
    for name in ("env.webp", "env@2.webp", "mira__school.webp", "mira__school@2.webp"):
        assert (out / name).is_file(), name
    tree = shot_tree(root)
    assert tree["ch01"]["s030"]["sunset"] == {"env": [""], "mira": ["casual", "school"]}


def test_pipeline_requires_env_layer(tmp_path):
    root = mk_root(tmp_path)
    base = root / "assets_src" / "art" / "shots" / "ch01" / "s030" / "sunset"
    img(base / "mira__school.png", CANVAS)
    rep = build_assets(root)
    assert any("env" in e and "подложка" in e for e in rep.errors)


def test_pipeline_requires_alpha_on_layers(tmp_path):
    """Слой без альфы ляжет в кадр прямоугольником — ошибка конвейера."""
    root = mk_root(tmp_path)
    base = root / "assets_src" / "art" / "shots" / "ch01" / "s030" / "sunset"
    img(base / "env.jpg", CANVAS, mode="RGB", fmt="JPEG")
    img(base / "mira.jpg", CANVAS, mode="RGB", fmt="JPEG")
    rep = build_assets(root)
    assert any("mira" in e and "прозрачн" in e for e in rep.errors)


def test_pipeline_requires_single_canvas(tmp_path):
    root = mk_root(tmp_path)
    base = root / "assets_src" / "art" / "shots" / "ch01" / "s030" / "sunset"
    img(base / "env.jpg", CANVAS, mode="RGB", fmt="JPEG")
    img(base / "mira.png", (CANVAS[0] * 2, CANVAS[1] * 2))
    rep = build_assets(root)
    assert any("ОДНОМ холсте" in e for e in rep.errors)


def test_pipeline_rejects_bad_shot_path(tmp_path):
    root = mk_root(tmp_path)
    img(root / "assets_src" / "art" / "shots" / "loose" / "s030" / "x" / "env.jpg",
        CANVAS, mode="RGB", fmt="JPEG")
    rep = build_assets(root)
    assert any("вне конвенции shots/" in e for e in rep.errors)


def test_emit_shots_layeredimage(tmp_path):
    root = mk_root(tmp_path)
    _shot_masters(root)
    assert not build_assets(root).errors
    rep = ImagesReport()
    out = "\n".join(_emit_shots(root, [("ch01", "shots/s030.shots.yaml", DOC)], rep))
    assert rep.errors == []
    assert "layeredimage shot_ch01_s030:" in out
    assert "attribute sunset default Null()" in out
    assert 'always "assets/shots/ch01/s030/sunset/env.webp" if_any ["sunset"]' in out
    # env идёт ПЕРЕД группой mira — z-порядок из декларации
    assert out.index("env.webp") < out.index("group mira:")
    assert "attribute mira_auto default ConditionSwitch(" in out
    assert "g.mira_outfit == 'casual'" in out and "predict_all=True" in out
    assert 'attribute mira_school "assets/shots/ch01/s030/sunset/mira__school.webp"' in out


def test_emit_shots_missing_variant_is_error(tmp_path):
    root = mk_root(tmp_path)
    _shot_masters(root, layers=("mira__school",))       # casual не собран
    assert not build_assets(root).errors
    rep = ImagesReport()
    out = _emit_shots(root, [("ch01", "shots/s030.shots.yaml", DOC)], rep)
    assert any("не собраны варианты casual" in e for e in rep.errors)
    assert out == []    # битый layeredimage не эмитится


def test_emit_shots_orphan_layer_is_warning(tmp_path):
    root = mk_root(tmp_path)
    _shot_masters(root, layers=("mira__school", "mira__casual", "ghost"))
    assert not build_assets(root).errors
    rep = ImagesReport()
    _emit_shots(root, [("ch01", "shots/s030.shots.yaml", DOC)], rep)
    assert any("ghost" in w and "не объявлен" in w for w in rep.warnings)


def test_image_index_knows_shot_attributes(tmp_path):
    root = mk_root(tmp_path)
    (root / "game" / "assets").mkdir(parents=True)      # зона «собрана»
    idx = build_image_index(root, {}, [], [("ch01", "rel", DOC)])
    tag = shot_tag("ch01", "s030")
    assert tag == "shot_ch01_s030"
    assert idx.layered[tag] == {"sunset", "mira_auto", "mira_school", "mira_casual"}
    assert _shot_attrs(DOC) == idx.layered[tag]


def test_memory_counts_worst_shot(tmp_path):
    from vn.assets.memory import _shot_cost

    costs = {
        "shots/ch01/s030/sunset/env.webp": 100,
        "shots/ch01/s030/sunset/mira__school.webp": 10,
        "shots/ch01/s030/sunset/mira__casual.webp": 30,
    }
    px, shot_id = _shot_cost(costs, "ch01", "s030", DOC, scale=1)
    assert (px, shot_id) == (130, "sunset")    # env + самый тяжёлый вариант слоя


def test_compile_rejects_bad_shot_declarations(tmp_path, repo_root):
    """order обязан перечислить все слои; у env вариантов не бывает."""
    from vn.content.compile import _collect_shots_dir
    from vn.schemas import SchemaRegistry

    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    d = root / "content" / "chapters" / "ch01_test"
    (d / "shots").mkdir(parents=True)
    (d / "shots" / "s030.shots.yaml").write_text(
        "schema: shots@1\nscene: s030\nshots:\n"
        "  bad:\n"
        "    layers:\n"
        "      env: {variants: [day, night]}\n"
        "      mira: {}\n"
        "    order: [env]\n",
        encoding="utf-8")
    registry = SchemaRegistry(root / "tools" / "schemas")
    errors: list[str] = []
    docs: list = []
    _collect_shots_dir(root, lambda p: (str(p), ""), registry, errors, docs, d)
    assert any("env вариантов не бывает" in e for e in errors)
    assert any("z-порядок" in e for e in errors)
    assert docs == []
