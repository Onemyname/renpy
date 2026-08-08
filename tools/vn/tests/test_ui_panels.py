"""UI-панели (ADR-0009): генерация 9-patch из деклараций, геометрия Borders,
эмиссия Frame, инкрементальность по параметрам отдельной панели."""

import io
import re

import pytest
from PIL import Image, ImageFont

from vn.assets import ui as uimod
from vn.assets.pipeline import build_assets

# Свойства стиля, через которые в вёрстку попадает Frame-панель.
_BG_PROPS = ("background", "hover_background", "selected_background",
             "insensitive_background", "selected_hover_background")
_FRAME_RE = re.compile(r"\bvn_frame_([a-z][a-z0-9_]*)")
_STYLE_RE = re.compile(r"^style\s+([A-Za-z_][\w]*)\s*(?:is\s+([A-Za-z_][\w]*)\s*)?:?\s*$")
_DEFINE_RE = re.compile(r"^define\s+gui\.([a-z0-9_]+)\s*=\s*(.+)$")


def _strip_comment(src: str) -> str:
    """Обрезать '# …', не разрубив цвет "#rrggbb" внутри строкового литерала."""
    quote = None
    for i, ch in enumerate(src):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return src[:i]
    return src


class _Gui:
    """Пространство имён для eval выражений вида 'gui.sp_l - 6'."""


def _load_gui_tokens(gui_rpy):
    """gui.rpy -> объект с атрибутами gui.*: экраны считают размеры от них,
    поэтому тест обязан читать те же числа, а не дублировать константы."""
    gui = _Gui()
    for line in gui_rpy.read_text(encoding="utf-8").splitlines():
        m = _DEFINE_RE.match(line.strip())
        if not m:
            continue
        try:
            setattr(gui, m.group(1), eval(_strip_comment(m.group(2)), {"gui": gui}))
        except Exception:
            pass            # define на Solid()/Frame() и прочий рантайм — не нужен
    return gui


def _load_styles(rpy_files):
    """{имя стиля: {"parent": ..., "props": {ключ: выражение}}} по .rpy экранов."""
    styles = {}
    cur = None
    for path in rpy_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            body = _strip_comment(line).rstrip()
            if not body.strip():
                continue
            if not body.startswith((" ", "\t")):
                m = _STYLE_RE.match(body.strip())
                cur = styles.setdefault(
                    m.group(1), {"parent": None, "props": {}}) if m else None
                if m and m.group(2):
                    cur["parent"] = m.group(2)
                continue
            if cur is None:
                continue
            key, _, value = body.strip().partition(" ")
            cur["props"].setdefault(key, value.strip())
    return styles


def _prop(styles, name, key):
    """Значение свойства с учётом цепочки 'style X is Y' (наследование стилей)."""
    seen = set()
    while name and name in styles and name not in seen:
        seen.add(name)
        if key in styles[name]["props"]:
            return styles[name]["props"][key]
        name = styles[name]["parent"]
    return None


def _text_style(styles, name):
    """Спутник <style>_text: Ren'Py наследует его вместе с самим стилем."""
    seen = set()
    while name and name not in seen:
        seen.add(name)
        if name + "_text" in styles:
            return name + "_text"
        name = styles.get(name, {}).get("parent")
    return None


def _line_height(repo_root, font_rel, size):
    """Высота строки = ascent + descent шрифта: столько займёт текст внутри
    padding. Шрифты лежат в репозитории, поэтому число детерминировано."""
    font = ImageFont.truetype(str(repo_root / "game" / font_rel), size)
    return sum(font.getmetrics())


def _element_size(repo_root, styles, gui, name):
    """(ширина, высота) элемента в px; None по оси, которую задаёт содержимое."""
    ev = lambda expr: eval(expr, {"gui": gui})     # noqa: E731

    xysize = _prop(styles, name, "xysize")
    if xysize:
        return ev(xysize)

    width = ev(_prop(styles, name, "xsize")) if _prop(styles, name, "xsize") else None
    ysize = _prop(styles, name, "ysize")
    if ysize:
        return width, ev(ysize)

    # Высота = padding сверху/снизу + строка текста в стиле-спутнике
    padding = _prop(styles, name, "padding")
    tstyle = _text_style(styles, name)
    if not padding or not tstyle:
        return width, None
    pad = ev(padding)
    pad_top, pad_bottom = (pad[1], pad[1]) if len(pad) == 2 else (pad[1], pad[3])
    font = _prop(styles, tstyle, "font")
    size = _prop(styles, tstyle, "size")
    if not font or not size:
        return width, None
    return width, pad_top + pad_bottom + _line_height(repo_root, ev(font), ev(size))


def _frame_consumers(styles):
    """[(стиль, свойство, id панели)] — все места, где вёрстка ставит vn_frame_*."""
    out = []
    for name, style in sorted(styles.items()):
        for key in _BG_PROPS:
            m = _FRAME_RE.search(style["props"].get(key, ""))
            if m:
                out.append((name, key, m.group(1)))
    return out


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


def test_every_frame_consumer_is_not_smaller_than_2x_borders(repo_root):
    """Главная ловушка ADR-0009 со стороны ПОТРЕБИТЕЛЯ: элемент меньше 2*Borders
    заставляет движок сжать 9-patch, и кнопка превращается в тонкую пилюлю.
    Декларацию проверяет тест выше, но сплющивает вёрстку не она, а пара
    «стиль + панель». Здесь разбираются стили экранов и для каждого
    `background vn_frame_<id>` сверяется реальный размер элемента с минимумом.

    Высота текста берётся по метрикам шрифта из репозитория — это оценка того,
    что посчитает Ren'Py, а не сам движок. Ось, которую задаёт содержимое
    (текст без xsize/xfill), не проверяется: её ширину знает только рантайм."""
    from vn.repo import load_yaml

    panels = load_yaml(repo_root / "content" / "ui" / "panels.yaml")["panels"]
    gui = _load_gui_tokens(repo_root / "game" / "gui.rpy")
    styles = _load_styles(sorted((repo_root / "game").rglob("*.rpy")))

    consumers = _frame_consumers(styles)
    # Парсер молча «починился бы», сломавшись: убеждаемся, что он что-то видит.
    assert {c[0] for c in consumers} >= {
        "choice_button", "vn_gal_cell", "vn_gal_tab", "vn_gal_ctl_button"}

    unchecked = []
    for name, key, pid in consumers:
        assert pid in panels, f"{name}.{key}: панель {pid} не объявлена в panels.yaml"
        left, top, right, bottom = uimod.borders_of(panels[pid])
        width, height = _element_size(repo_root, styles, gui, name)
        if height is None:
            unchecked.append(f"{name}.{key}")
        else:
            assert height >= top + bottom, (
                f"{name}.{key}: высота {height}px < минимума {top + bottom}px "
                f"панели {pid} — движок сожмёт фон (ADR-0009)")
        if width is not None:
            assert width >= left + right, (
                f"{name}.{key}: ширина {width}px < минимума {left + right}px "
                f"панели {pid} — движок сожмёт фон (ADR-0009)")

    assert not unchecked, f"высота не выводится, посчитайте вручную: {unchecked}"


def test_gallery_chips_fit_their_small_buttons(repo_root):
    """Регресс именно того дефекта, ради которого заведены чипы: вкладка и
    кнопка просмотрщика галереи ниже 40px, и вернуть им панель choice*
    (минимум 54-60px) — значит снова сплющить фон."""
    from vn.repo import load_yaml

    panels = load_yaml(repo_root / "content" / "ui" / "panels.yaml")["panels"]
    gui = _load_gui_tokens(repo_root / "game" / "gui.rpy")
    styles = _load_styles(sorted((repo_root / "game").rglob("*.rpy")))

    for pid in ("chip", "chip_active"):
        _, top, _, bottom = uimod.borders_of(panels[pid])
        assert top + bottom <= 24, f"чип {pid} растолстел до {top + bottom}px"

    for name in ("vn_gal_tab", "vn_gal_ctl_button"):
        _, height = _element_size(repo_root, styles, gui, name)
        assert height < 40, f"{name}: {height}px — это уже не чип, пересмотрите фон"
        for key in _BG_PROPS:
            frame = _FRAME_RE.search(styles[name]["props"].get(key, ""))
            assert not frame or frame.group(1).startswith("chip"), (
                f"{name}.{key}: панель {frame.group(1)} рассчитана на кнопку выше")
