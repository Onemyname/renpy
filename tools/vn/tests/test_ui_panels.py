"""UI-панели (ADR-0009): генерация 9-patch из деклараций, геометрия Borders,
эмиссия Frame, инкрементальность по параметрам отдельной панели."""

import io

import pytest
from PIL import Image

from vn.assets import ui as uimod
from vn.assets.pipeline import build_assets


def test_hex_rgba_forms():
    assert uimod._hex_rgba("#fff") == (255, 255, 255, 255)
    assert uimod._hex_rgba("#000000") == (0, 0, 0, 255)
    assert uimod._hex_rgba("#ff000080") == (255, 0, 0, 128)
    with pytest.raises(ValueError):
        uimod._hex_rgba("#12345")


def test_borders_cover_radius_and_shadow():
    """Borders обязаны накрывать и скругление, и разлёт тени — иначе движок
    растянет угол/тень и панель поедет."""
    spec = {"radius": 14, "shadow": {"color": "#000", "blur": 10, "dy": 3}}
    assert uimod.borders_of(spec) == (27, 27, 27, 27)      # 14 + (10+3)
    # Без тени Borders = радиус (+ обводка, если она толще)
    assert uimod.borders_of({"radius": 8}) == (8, 8, 8, 8)
    assert uimod.borders_of({"radius": 4, "border": {"color": "#fff", "width": 3}}) \
        == (7, 7, 7, 7)


def test_render_panel_geometry_and_alpha():
    spec = {"radius": 12, "fill": "#202024ff",
            "border": {"color": "#ffffff20", "width": 1}}
    png = uimod.render_panel(spec)
    with Image.open(io.BytesIO(png)) as im:
        assert im.mode == "RGBA"
        # side = 2*(radius+inset) + STRETCH; inset здесь = border width = 1
        assert im.size == (2 * (12 + 1) + uimod.STRETCH,) * 2
        # Угол прозрачный (скругление), центр залит
        assert im.getpixel((0, 0))[3] == 0
        assert im.getpixel((im.size[0] // 2, im.size[1] // 2))[3] > 200


def test_render_panel_gradient_differs_top_from_bottom():
    spec = {"radius": 6, "fill": {"from": "#ffffffff", "to": "#000000ff"}}
    with Image.open(io.BytesIO(uimod.render_panel(spec))) as im:
        cx = im.size[0] // 2
        top = im.getpixel((cx, im.size[1] // 4))
        bottom = im.getpixel((cx, im.size[1] * 3 // 4))
        assert top[0] > bottom[0] + 60          # сверху светлее


def test_emit_frames_declares_named_frames_and_minimum():
    text = uimod.emit_frames(
        {"choice": {"radius": 14, "shadow": {"color": "#000", "blur": 10, "dy": 3}}},
        "# h\n")
    assert 'define vn_frame_choice = Frame("assets/ui/choice.webp", ' \
           'Borders(27, 27, 27, 27), tile=False)' in text
    assert "минимум 54x54" in text              # ловушка видна дизайнеру
    assert "не объявлены" in uimod.emit_frames({}, "# h\n")


def test_pipeline_builds_panels_and_reacts_only_to_own_change(tmp_path):
    root = tmp_path / "repo"
    (root / "content" / "ui").mkdir(parents=True)
    decl = root / "content" / "ui" / "panels.yaml"
    decl.write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n"
        "  b:\n    radius: 4\n    fill: \"#222222ff\"\n", encoding="utf-8")

    res = build_assets(root)
    assert res.errors == []
    assert sorted(res.built) == ["ui/a.webp", "ui/b.webp"]
    assert (root / "game/assets/ui/a.webp").is_file()

    # Правка ОДНОЙ панели не должна перерисовывать соседнюю (хэш по параметрам)
    decl.write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n"
        "  b:\n    radius: 4\n    fill: \"#333333ff\"\n", encoding="utf-8")
    res2 = build_assets(root)
    assert res2.built == ["ui/b.webp"]
    assert "ui/a.webp" in res2.fresh

    # Удаление панели чистит выход (orphan-очистка по манифесту)
    decl.write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n", encoding="utf-8")
    res3 = build_assets(root)
    assert res3.deleted == ["ui/b.webp"]


def test_repo_panels_declaration_is_valid(repo_root):
    """Боевая декларация проекта проходит схему, и все кнопочные панели
    достаточно компактны, чтобы не сплющить кнопку (минимум <= 60px)."""
    import json

    from vn.repo import load_yaml
    from vn.schemas import SchemaRegistry

    doc = load_yaml(repo_root / "content" / "ui" / "panels.yaml")
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, "content/ui/panels.yaml") == []
    for pid, spec in doc["panels"].items():
        if not pid.startswith("choice"):
            continue
        l, t, r, b = uimod.borders_of(spec)
        assert t + b <= 60, f"панель {pid}: минимум {t + b}px выше кнопки — сплющит фон"
