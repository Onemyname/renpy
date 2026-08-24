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


def _load_gui_tokens(gui_rpy, ui_scale=1.0):
    """gui.rpy -> объект с атрибутами gui.*: экраны считают размеры от них,
    поэтому тест обязан читать те же числа, а не дублировать константы.

    ui_scale — множитель интерфейсных кеглей (20_ui/scale.rpy вычисляет его в
    рантайме из persistent/платформы; define в gui.rpy на него не eval'ится) —
    сеем до парса. База 1.0 = геометрия монитора; scale.rpy гарантирует >= 1.0,
    так что минимумы 2*Borders проверяются на ХУДШЕМ (наименьшем) случае."""
    gui = _Gui()
    gui.ui_scale = ui_scale
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


def _style_uses(rpy_files, repo_root):
    """Использования стилей ПО ИМЕНИ: ({имя: [место, ...]}, {место с вычисляемым именем}).

    Раньше здесь стоял регексп `\\bstyle\\s+"([a-z_][\\w]*)"` — только строковый литерал
    сразу после `style`. Форма `style (…)` для него невидима, а именно она стоит в шести
    местах боевой вёрстки: `style ("choice_button_chosen" if i.chosen else "choice_button")`,
    `style ("vn_btn_" + kind)` и т.п. Проверено движком: подмена такого имени на
    несуществующее оставляла ЗЕЛЁНЫМИ и этот тест, и `renpy lint`, и весь тур
    `vn test screens`, а движок падал `Exception: Style '…' does not exist` при первой
    отрисовке. Для `screen choice` (он в `ignore_defined` тура) другой сети нет вообще.

    Поэтому разбираем и скобочную форму: выражение может занимать несколько строк
    (choice.rpy), поэтому скан идёт по тексту файла с сопоставлением скобок, а не по
    строкам. Если внутри выражения есть склейка (`+`), имя стиля в исходнике как строка
    не существует — такое место уходит во ВТОРОЕ множество и проверяется матрицей
    (см. _COMPUTED_STYLE_SITES)."""
    used: dict[str, list[str]] = {}
    computed: set[str] = set()
    # `style` как ИСПОЛЬЗОВАНИЕ — дальше кавычка или скобка; `style vn_ach_card:` это
    # объявление, `style_prefix`/`text_style` — другие слова (\b между `_` и `s` нет).
    head = re.compile(r"\bstyle\b\s*(?=[(\"'])")
    for path in rpy_files:
        rel = path.relative_to(repo_root).as_posix()
        text = "\n".join(_strip_comment(ln)
                         for ln in path.read_text(encoding="utf-8").splitlines())
        for m in head.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            where = f"{rel}:{line}"
            pos = m.end()
            if text[pos] in "\"'":
                lit = re.match(r"([\"'])([a-z_][\w]*)\1", text[pos:])
                if lit:
                    used.setdefault(lit.group(2), []).append(where)
                continue
            expr = _balanced(text, pos)
            if expr is None:
                continue
            names, unknown = _expr_style_names(expr)
            if unknown:
                computed.add(f"{rel}: {expr[1:-1].strip()}")
            for name in names:
                used.setdefault(name, []).append(where)
    return used, computed


def _expr_style_names(expr):
    """({возможные имена стиля}, есть ли невыводимая ветвь) для выражения `style (…)`.

    Литералы берём НЕ регекспом, а разбором: в `("choice_guide_goal" if _note[0] == "goal"
    else "choice_guide_block")` регексп находит ещё и `"goal"` — операнд сравнения, который
    именем стиля не является, и гейт краснел бы на исправной вёрстке. Поэтому собираем
    только литералы в позиции ЗНАЧЕНИЯ выражения: у тернарника это body/orelse, у `or`/`and`
    — все операнды, у склейки со неконстантой имя в исходнике не существует вовсе."""
    import ast

    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return set(), True          # не разобрали — считаем невыводимым, а не «нет имён»

    def walk(node):
        if isinstance(node, ast.Constant):
            return ({node.value}, False) if isinstance(node.value, str) else (set(), True)
        if isinstance(node, ast.IfExp):          # A if C else B — значения только A и B
            a, ua = walk(node.body)
            b, ub = walk(node.orelse)
            return a | b, ua or ub
        if isinstance(node, ast.BoolOp):         # идиома `x or "fallback"`
            out, unk = set(), False
            for v in node.values:
                n, u = walk(v)
                out |= n
                unk = unk or u
            return out, unk
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, ua = walk(node.left)
            b, ub = walk(node.right)
            if ua or ub:                         # склейка с переменной: имени как строки нет
                return set(), True
            return {x + y for x in a for y in b}, False
        return set(), True                       # Name/Call/Attribute/Subscript — невыводимо

    return walk(tree)


def _balanced(text, start):
    """Подстрока от '(' в text[start] до парной ')' включительно, либо None.
    Кавычки учитываются: скобка внутри строкового литерала не считается."""
    if start >= len(text) or text[start] != "(":
        return None
    depth, quote = 0, None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


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
    # Референсный вариант — без суффикса (иначе движок не включит автоподбор),
    # крупный — рядом с @2 (ADR-0012).
    assert sorted(res.built) == ["ui/a.webp", "ui/a@2.webp",
                                 "ui/b.webp", "ui/b@2.webp"]
    assert (root / "game/assets/ui/a.webp").is_file()

    # Правка ОДНОЙ панели не должна перерисовывать соседнюю (хэш по параметрам)
    decl.write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n"
        "  b:\n    radius: 4\n    fill: \"#333333ff\"\n", encoding="utf-8")
    res2 = build_assets(root)
    assert res2.built == ["ui/b.webp", "ui/b@2.webp"]
    assert {"ui/a.webp", "ui/a@2.webp"} <= set(res2.fresh)

    # Удаление панели чистит ВСЕ её варианты (orphan-очистка по манифесту)
    decl.write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n", encoding="utf-8")
    res3 = build_assets(root)
    assert res3.deleted == ["ui/b.webp", "ui/b@2.webp"]


def test_every_declared_panel_ships_reference_and_oversampled(tmp_path, repo_root):
    """Боевая декларация целиком: у каждой панели обязаны быть и референсный
    (безсуффиксный) выход, и крупный вариант ровно вдвое. Сборка гоняется в
    копии — трогать game/assets боевого репозитория тест не имеет права.

    Размер здесь проверяется на ФАЙЛАХ, а не на рисовалке: если бы масштаб не
    входил в ключ кэша (panel_hash_source), @2 приехал бы байт-в-байт из блоба
    1x — файл был бы, а картинка в нём была бы мелкой."""
    import shutil

    from vn.repo import load_yaml

    root = tmp_path / "repo"
    (root / "content" / "ui").mkdir(parents=True)
    src = repo_root / "content" / "ui" / "panels.yaml"
    shutil.copyfile(src, root / "content" / "ui" / "panels.yaml")

    res = build_assets(root)
    assert res.errors == []
    out = root / "game" / "assets" / "ui"
    for pid in load_yaml(src)["panels"]:
        ref, big = out / f"{pid}.webp", out / f"{pid}@2.webp"
        assert ref.is_file() and big.is_file(), f"панель {pid}: собран не весь набор"
        with Image.open(ref) as a, Image.open(big) as b:
            assert b.size == tuple(2 * v for v in a.size), f"панель {pid}: @2 не вдвое"


@pytest.mark.parametrize("scale", [1, 2])
def test_panel_variant_geometry_scales_exactly(repo_root, scale):
    """Вариант @N — та же панель, НАРИСОВАННАЯ в N раз крупнее: сторона и
    Borders умножаются ровно на N, поэтому 1px-обводка на 4K остаётся обводкой,
    а не мыльным градиентом.

    И на каждом масштабе обязано выполняться условие движка: сумма Borders
    меньше стороны (imagelike.py, Frame.render: xborder = min(bw, sw - 2, dw)) —
    иначе Ren'Py сам урежет поля, и скругление съедет."""
    from vn.repo import load_yaml

    panels = load_yaml(repo_root / "content" / "ui" / "panels.yaml")["panels"]
    for pid, spec in sorted(panels.items()):
        left, top, right, bottom = uimod.borders_of(spec, scale)
        assert (left, top, right, bottom) == tuple(
            v * scale for v in uimod.borders_of(spec)), \
            f"панель {pid}: Borders не в масштабе"
        with Image.open(io.BytesIO(uimod.render_panel(spec, scale))) as im, \
                Image.open(io.BytesIO(uimod.render_panel(spec))) as ref:
            assert im.size == (2 * left + uimod.STRETCH * scale,) * 2
            assert im.size == tuple(v * scale for v in ref.size), \
                f"панель {pid}: сторона @{scale} не в масштабе"
            assert left + right <= im.size[0] - 2, f"панель {pid}: Borders шире картинки"
            assert top + bottom <= im.size[1] - 2, f"панель {pid}: Borders выше картинки"


def test_panel_variants_follow_render_profile(tmp_path, monkeypatch):
    """Набор масштабов панелей — ДАННЫЕ render-профиля (класс ui, ADR-0012), а не
    константа конвейера: «поднять UI до 4K» обязано быть правкой профиля, а не
    кода. Профиль подменяется в дефолтах — синтетический корень своего не имеет."""
    from vn.assets import render_config

    monkeypatch.setitem(render_config.DEFAULTS["classes"]["ui"], "variants", [1, 2, 4])
    root = tmp_path / "repo"
    (root / "content" / "ui").mkdir(parents=True)
    (root / "content" / "ui" / "panels.yaml").write_text(
        "schema: ui_panels@1\npanels:\n"
        "  a:\n    radius: 8\n    fill: \"#111111ff\"\n", encoding="utf-8")

    res = build_assets(root)
    assert res.errors == []
    assert sorted(res.built) == ["ui/a.webp", "ui/a@2.webp", "ui/a@4.webp"]


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


@pytest.mark.parametrize("ui_scale", [1.0, 1.4])
def test_every_frame_consumer_is_not_smaller_than_2x_borders(repo_root, ui_scale):
    """Главная ловушка ADR-0009 со стороны ПОТРЕБИТЕЛЯ: элемент меньше 2*Borders
    заставляет движок сжать 9-patch, и кнопка превращается в тонкую пилюлю.
    Декларацию проверяет тест выше, но сплющивает вёрстку не она, а пара
    «стиль + панель». Здесь разбираются стили экранов и для каждого
    `background vn_frame_<id>` сверяется реальный размер элемента с минимумом.

    Высота текста берётся по метрикам шрифта из репозитория — это оценка того,
    что посчитает Ren'Py, а не сам движок. Ось, которую задаёт содержимое
    (текст без xsize/xfill), не проверяется: её ширину знает только рантайм.

    Прогон при ui_scale 1.4 («крупный», scale.rpy) ловит регресс связки
    «кегль x масштаб vs Borders» — токены растут, минимумы должны выполняться
    и в крупном профиле."""
    from vn.repo import load_yaml

    panels = load_yaml(repo_root / "content" / "ui" / "panels.yaml")["panels"]
    gui = _load_gui_tokens(repo_root / "game" / "gui.rpy", ui_scale=ui_scale)
    styles = _load_styles(sorted((repo_root / "game").rglob("*.rpy")))

    consumers = _frame_consumers(styles)
    # Парсер молча «починился бы», сломавшись: убеждаемся, что он что-то видит.
    # vn_toast в списке ещё и потому, что тост уже жил с литеральным Solid при
    # объявленной и собранной панели toast: возврат к литералу — регресс.
    assert {c[0] for c in consumers} >= {
        "choice_button", "vn_gal_cell", "vn_gal_tab", "vn_gal_ctl_button",
        "vn_toast"}

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


def test_ui_scale_grows_interface_tokens_only(repo_root):
    """Масштаб интерфейса (20_ui/scale.rpy): интерфейсные кегли gui.rpy обязаны
    сидеть на множителе gui.ui_scale (иначе профиль «крупный» молча перестанет
    работать), диалоговые — НЕ масштабироваться (они проходят пороги Deck/ТВ),
    и ни один токен не имеет права УМЕНЬШИТЬСЯ (минимумы 2*Borders панелей)."""
    base = _load_gui_tokens(repo_root / "game" / "gui.rpy", ui_scale=1.0)
    big = _load_gui_tokens(repo_root / "game" / "gui.rpy", ui_scale=1.4)

    scaled = ("interface_text_size", "button_text_size", "small_text_size",
              "tiny_text_size", "choice_text_size", "group_text_size")
    for name in scaled:
        assert getattr(big, name) > getattr(base, name), (
            f"gui.{name}: не растёт с gui.ui_scale — кегль выпал из множителя")

    for name in ("text_size", "name_text_size", "label_text_size",
                 "title_text_size"):
        assert getattr(big, name) == getattr(base, name), (
            f"gui.{name}: диалоговый кегль не должен зависеть от ui_scale")

    for name, value in vars(base).items():
        if isinstance(value, (int, float)) and not name.startswith("_"):
            assert getattr(big, name, value) >= value, (
                f"gui.{name}: уменьшился при ui_scale>1 — сплющит 9-patch")


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


def test_every_style_used_by_name_is_declared(repo_root):
    """Стиль, названный в вёрстке строкой, обязан существовать — иначе игра падает
    исключением на показе экрана, а не «уезжает на дефолтный шрифт».

    Ren'Py выводит родителя по подчёркиванию (vn_modal -> modal), но ТОЛЬКО если
    родитель существует: style.pyx get_style рекурсивно требует его и при
    отсутствии бросает `Exception: Style '<имя>' does not exist` уже из
    build_style, то есть в момент первой отрисовки. Проверено живым прогоном
    движка на минимальном проекте: `renpy lint` при этом ЗЕЛЁНЫЙ.

    Так пришёл P0: screen story_node_menu был написан на vn_modal /
    vn_modal_title / vn_modal_text, которых в проекте не объявлено ни одного, и
    клик по любому узлу карты главы ронял игру. Тур автопилота его не снимал
    (модалка), а движковый lint такого класса не видит — этот тест и есть
    единственная сеть."""
    project = sorted((repo_root / "game").rglob("*.rpy"))
    declared = set(_load_styles(project))

    # Стили движка (default, frame, vbox, text, button, bar…) объявлены в
    # renpy/common/*.rpy, и там они ВНУТРИ init-блоков — то есть с отступом,
    # поэтому _load_styles их не видит (он считает отступ свойством стиля).
    # Отдельный скан по этой причине, а не по невнимательности.
    import os
    from pathlib import Path

    sdk = os.environ.get("RENPY_SDK")
    if not sdk:
        pytest.skip("RENPY_SDK не задан — набор стилей движка неизвестен")
    common = sorted((Path(sdk) / "renpy" / "common").glob("*.rpy"))
    if not common:
        pytest.skip("renpy/common в SDK не найден")
    engine = set()
    for path in common:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*style\s+([A-Za-z_][\w]*)\s*(?:is\s+[\w]+\s*)?:?\s*$",
                         _strip_comment(line))
            if m:
                engine.add(m.group(1))
    assert {"default", "frame", "vbox", "text", "button"} <= engine,         "скан стилей движка выродился — базовых стилей не нашлось"
    declared |= engine

    used, computed = _style_uses(project, repo_root)

    # Гейт не должен выродиться: вёрстка обязана ссылаться на стили по имени.
    assert len(used) > 20, f"использований стилей подозрительно мало: {len(used)}"
    missing = {k: v for k, v in used.items() if k not in declared}
    assert not missing, "стили используются, но не объявлены: " + "; ".join(
        f"{k} <- {v[0]}" for k, v in sorted(missing.items()))

    # Вычисляемое имя стиля литеральным сканом не проверить в принципе, поэтому
    # набор таких мест ЗАМОРОЖЕН: новое место обязано приехать вместе со своей
    # матричной проверкой (ниже — test_computed_style_names_cover_every_kind).
    assert computed == _COMPUTED_STYLE_SITES, (
        "изменился набор мест с вычисляемым именем стиля.\n"
        f"  сейчас:  {sorted(computed)}\n"
        f"  заморожено: {sorted(_COMPUTED_STYLE_SITES)}\n"
        "Литеральный скан такое имя не видит: добавьте место в _COMPUTED_STYLE_SITES "
        "и матричную проверку всех значений, из которых имя собирается.")


# Места, где имя стиля СОБИРАЕТСЯ в рантайме, а не написано литералом. Каждое
# перечислено здесь по одной причине: скан по литералам его не видит, а движок при
# отсутствии стиля бросает исключение на первой отрисовке. Значения, из которых
# имя собирается, проверяет матричный тест ниже.
_COMPUTED_STYLE_SITES = {
    'game/framework/20_ui/components.rpy: "vn_btn_" + kind',
    'game/framework/20_ui/components.rpy: "vn_btn_" + kind + "_text"',
}


def test_computed_style_names_cover_every_kind(repo_root):
    """У vn_button имя стиля собирается из kind — значит проверять надо МАТРИЦУ.

    `style ("vn_btn_" + kind)` (components.rpy) литеральным сканом невидимо и
    останется невидимым: имени как строки в исходнике нет. Единственная честная
    проверка — взять ВСЕ значения kind, с которыми экран реально зовут (плюс
    дефолт из его сигнатуры), и потребовать, чтобы для каждого существовали и
    `vn_btn_<kind>`, и `vn_btn_<kind>_text`. Иначе `use vn_button(..., kind="warning")`
    роняет экран исключением `Style 'vn_btn_warning' does not exist` при первой
    отрисовке, а renpy lint такого класса не видит (он стили не проверяет)."""
    project = sorted((repo_root / "game").rglob("*.rpy"))
    declared = set(_load_styles(project))

    kinds: dict[str, str] = {}
    for path in project:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            body = _strip_comment(line)
            # Дефолт из сигнатуры screen vn_button(... kind="primary" ...)
            for m in re.finditer(r'screen\s+vn_button\s*\([^)]*?kind\s*=\s*"([a-z_]\w*)"',
                                 body):
                kinds[m.group(1)] = f"{path.relative_to(repo_root).as_posix()}:{i}"
            # Значения из вызовов: use vn_button(..., kind="secondary")
            if "vn_button" in body:
                for m in re.finditer(r'kind\s*=\s*"([a-z_]\w*)"', body):
                    kinds[m.group(1)] = f"{path.relative_to(repo_root).as_posix()}:{i}"

    # Гейт не должен выродиться: kind у компонента есть, и значений у него больше одного.
    assert len(kinds) >= 2, f"значения kind не нашлись — скан выродился: {kinds}"

    missing = [f"vn_btn_{k}{suffix} <- {where}"
               for k, where in sorted(kinds.items())
               for suffix in ("", "_text")
               if f"vn_btn_{k}{suffix}" not in declared]
    assert not missing, ("vn_button зовут с kind, для которого стиль не объявлен "
                         "(движок упадёт при отрисовке): " + "; ".join(missing))


def test_chapter_map_never_prints_titles_of_unseen_scenes(repo_root):
    """Туман войны — правило одного места, а не привычка автора экрана.

    Целью walkthrough можно отметить ЛЮБОЙ узел, включая непройденный. Правило
    «непройденное — это ???» соблюдалось только на карточке узла, а план
    прохождений, список конфликтующих целей и подсказки гайда печатали настоящий
    заголовок закрытой сцены — то есть выдавали ровно то, что карта прячет.

    Инвариант: UI зовёт только vn_story.display_title(); vn_story.title() —
    внутренняя функция стора."""
    ui = sorted((repo_root / "game" / "framework" / "20_ui").rglob("*.rpy"))
    leaks = [f"{f.relative_to(repo_root).as_posix()}:{i}"
             for f in ui
             for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
             if "vn_story.title(" in _strip_comment(ln)]
    assert not leaks, f"заголовок берётся мимо тумана войны: {leaks}"

    store = (repo_root / "game" / "framework" / "00_core"
             / "100_story_graph.rpy").read_text(encoding="utf-8")
    assert "def display_title(" in store
    guide = store.split("def guide_note(", 1)[1].split("\n    def ", 1)[0]
    assert "display_title(" in guide and "join(title(" not in guide, \
        "подсказка гайда печатает заголовок непройденной цели"


def test_every_screen_string_key_is_declared(repo_root):
    """Каждый ключ `vn_loc.t("…")` во ВСЕЙ вёрстке объявлен в strings.yaml.

    Незадекларированный ключ не падает — движок рисует сам ключ, то есть игрок
    видит на кнопке «ui.chart.continues». Такое ловится только глазами на живом
    экране, поэтому проверка была написана ещё для экрана достижений
    (test_achievements.py::test_screen_string_keys_are_declared) — но ровно для
    него одного, а ключи есть в каждом экране. Здесь тот же вопрос ко всей
    вёрстке: гейт на класс, а не на файл."""
    from vn.repo import load_yaml

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    key_re = re.compile(r'vn_loc\.t\("([a-z0-9_.]+)"\)')
    missing = {}
    seen = 0
    for path in sorted((repo_root / "game").rglob("*.rpy")):
        src = path.read_text(encoding="utf-8")
        for key in key_re.findall(src):
            seen += 1
            if key not in strings:
                missing.setdefault(path.name, set()).add(key)
    assert seen > 50, f"ключи в вёрстке не найдены вовсе ({seen}) — регексп съехал"
    assert missing == {}, f"ключи вне content/ui/strings.yaml: {missing}"


def test_navigation_rail_gates_are_cheap_predicates(repo_root):
    """Рельсу рисует каркас vn_game_menu, то есть КАЖДЫЙ экран игрового меню —
    и предикция ShowMenu тоже. Гейты её пунктов обязаны отвечать «да/нет», а не
    строить и сортировать реестры.

    Раньше пункт «Галерея» гейтился через categories(), который на каждую
    категорию звал items(), а тот фильтровал и сортировал ВЕСЬ реестр: O(C·N log N)
    на показ рельсы. Ачивки и карта — тем же способом."""
    nav = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "core_screens.rpy").read_text(encoding="utf-8")
    # Гейты продублированы в главном меню (тот же вопрос — «есть ли что
    # показывать» — и тот же аргумент про цену), поэтому проверяются оба экрана.
    # Только код: комментарии рядом называют функции по именам.
    rail = "\n".join(_strip_comment(ln) for ln in nav.splitlines())
    for cheap in ("vn_gal.has_visible()", "vn_ach.has_visible()",
                  "vn_story.has_chapters()"):
        assert cheap in rail, f"гейт рельсы не переведён на дешёвый предикат: {cheap}"
    for costly in ("vn_gal.categories()", "vn_ach.visible_ids()",
                   "vn_story.chapter_list()"):
        assert costly not in rail, f"рельса снова строит список: {costly}"


def test_conflict_lookup_and_plan_are_not_recomputed_per_frame(repo_root):
    """compatible() зовут пачками: карточка КАЖДОГО узла спрашивает conflicts()
    по всем целям, план — по каждой паре целей, подсказка гайда — на КАЖДЫЙ
    пункт меню в точке выбора. Линейный скан списка конфликтов (до 4096 пар)
    платился в каждом кадре.

    Кэш плана обязан сбрасываться по смене целей: молчаливо устаревшая карта
    хуже медленной."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "100_story_graph.rpy").read_text(encoding="utf-8")

    comp = src.split("def compatible(", 1)[1].split("\n    def ", 1)[0]
    assert "_conflicts_set()" in comp, "матрица конфликтов снова сканируется списком"
    assert "for x, y in" not in comp

    plan = src.split("def plan(", 1)[1].split("\n    def ", 1)[0]
    # Кэш живёт атрибутом объекта, созданного на init, а не именем стора: имя,
    # переприсвоенное в рантайме, становится корнем сейва навсегда, и загруженный
    # сейв всю сессию подсовывал старую матрицу конфликтов — см.
    # test_saves::test_no_store_name_is_reassigned_at_runtime.
    assert "_cache.plan" in plan, "план пересчитывается на каждый вызов"
    for mutator in ("def toggle_target(", "def clear_targets("):
        body = src.split(mutator, 1)[1].split("\n    def ", 1)[0]
        assert "_drop_plan_cache()" in body, f"{mutator} не сбрасывает кэш плана"


# ── Навигация: один список пунктов и рабочий выход ───────────────────────────

NAV_REL = "game/framework/20_ui/screens/core_screens.rpy"
FRAME_REL = "game/framework/20_ui/components.rpy"

# Ключи пунктов навигации. Каждый обязан упоминаться в вёрстке РОВНО ОДИН раз:
# два перечня и были причиной «шафла» — порядок в них разошёлся, и при переходе
# из главного меню в подэкран «Настройки» прыгали с седьмой позиции на четвёртую.
_NAV_KEYS = (
    "ui.nav.start", "ui.nav.chapters", "ui.nav.save", "ui.nav.load",
    "ui.nav.gallery", "ui.nav.achievements", "ui.chart.open", "ui.nav.history",
    "ui.nav.prefs", "ui.nav.continue", "ui.nav.return", "ui.nav.main_menu",
    "ui.nav.quit",
)


def _ui_sources(repo_root):
    return sorted((repo_root / "game" / "framework" / "20_ui").rglob("*.rpy"))


def test_every_navigation_item_is_declared_once(repo_root):
    """Пункт навигации объявлен в вёрстке ровно один раз.

    Списка было два — рельса `navigation` и колонна `main_menu` держали свои
    литеральные перечни, и синхронизировал их никто. Порядок пунктов в SL2 равен
    порядку строк в файле, поэтому расхождение перечней игрок видит как
    «странный шафл»: «Настройки» напечатаны в главном меню ПОСЛЕ галереи и
    достижений, а в рельсе — ДО них. Оттуда же и «Карта главы появляется только
    после захода в главы»: пункта в колонне не было вовсе, хотя его гейт
    `vn_story.has_chapters()` в главном меню истинен.

    Так же устроен штатный шаблон движка: `screen main_menu` делает
    `use navigation` с комментарием «The actual contents of the main menu are in
    the navigation screen» (SDK gui/game/screens.rpy)."""
    hits = {}
    for path in _ui_sources(repo_root):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            # Только ПУНКТЫ: тот же ключ законно называет и раздел в заголовке
            # экрана (use vn_game_menu(vn_loc.t("ui.nav.gallery"))) — это не
            # второй список, а подпись того же самого.
            # «Продолжить» — не textbutton, а карточка со временем сейва:
            # у неё подпись лежит вложенным text со своим стилем.
            if "textbutton" not in code and "vn_main_continue_text" not in code:
                continue
            for key in _NAV_KEYS:
                if f'vn_loc.t("{key}")' in code:
                    hits.setdefault(key, []).append(
                        f"{path.relative_to(repo_root).as_posix()}:{i}")
    doubled = {k: v for k, v in hits.items() if len(v) > 1}
    assert doubled == {}, (
        f"пункт навигации объявлен дважды — списки разъедутся и игрок увидит "
        f"перестановку: {doubled}")
    missing = [k for k in _NAV_KEYS if k not in hits]
    assert missing == [], f"пункты навигации исчезли из вёрстки: {missing}"


def test_both_menu_contexts_share_one_item_list(repo_root):
    """Колонна главного меню и рельса рисуют ОДИН список.

    Гейт на способ, а не только на следствие: пока каждый экран строит перечень
    сам, синхронность держится дисциплиной, а её хватило ровно до первой
    правки."""
    src = (repo_root / NAV_REL).read_text(encoding="utf-8")
    assert "screen vn_nav_items(" in src, "общий список пунктов исчез"
    for user in ("screen navigation():", "screen main_menu():"):
        assert user in src, user
    body = src.split("screen main_menu():", 1)[1]
    assert "use vn_nav_items(" in body, (
        "главное меню снова строит свой список пунктов вместо общего")
    assert "use vn_nav_tail(" in body, "главное меню не берёт общий хвост навигации"


def test_a_screen_opened_from_the_main_menu_has_a_way_back(repo_root):
    """Возврат доступен в ОБОИХ контекстах.

    Гейт `if not main_menu:` был надет на пару «Вернуться + Главное меню», а
    нужен он только второму: `MainMenu()` в главном меню действительно
    insensitive (`get_sensitive: return not renpy.context()._main_menu`,
    SDK 00action_menu.rpy), а `Return()` там как раз РАБОТАЕТ — движок знает
    этот случай сам (`if self.value is None: if main_menu: ShowMenu("main_menu")()`,
    00action_control.rpy). Пряталась ровно та кнопка, которая работает, и
    галерея, открытая из главного меню, оставалась без единого выхода."""
    src = (repo_root / NAV_REL).read_text(encoding="utf-8")
    tail = src.split("screen vn_nav_tail(", 1)[1].split("\nscreen ", 1)[0]
    lines = [l for l in tail.splitlines() if l.split("#", 1)[0].strip()]

    ret = next(i for i, l in enumerate(lines) if 'vn_loc.t("ui.nav.return")' in l)
    guards = [l.strip() for l in lines[:ret]
              if l.split("#", 1)[0].strip().startswith(("if ", "elif "))]
    assert not any("not main_menu" in g for g in guards), (
        f"«Вернуться» снова спрятан за `not main_menu` — из галереи, открытой из "
        f"главного меню, выхода не будет: {guards}")
    assert "action Return()" in tail, "«Вернуться» перестал звать Return()"

    mm = next(i for i, l in enumerate(lines) if 'vn_loc.t("ui.nav.main_menu")' in l)
    assert any("not main_menu" in l for l in lines[:mm]), (
        "«Главное меню» показывается в контексте главного меню, где MainMenu() "
        "insensitive — пункт будет мёртвым")


def test_escape_returns_to_the_main_menu_from_a_submenu(repo_root):
    """Esc/B возвращает в главное меню из подэкрана.

    Движковый keysym `game_menu` в этом контексте намеренный no-op:
    `_invoke_game_menu` начинается с `if renpy.context()._menu: if main_menu:
    return` (SDK 00gamemenu.rpy). В игре это верно, но подэкран, открытый из
    главного меню, оставался вообще без клавиши выхода — только Alt+F4. Штатный
    шаблон компенсирует это тем же способом."""
    # Комментарии вычищаются ПЕРЕД проверкой: в этом самом каркасе процитирована
    # строка штатного шаблона, и без вычистки гард засчитывал цитату за код —
    # проверено мутацией, удаление настоящей строки его не роняло.
    src = "\n".join(_strip_comment(l) for l in
                    (repo_root / FRAME_REL).read_text(encoding="utf-8").splitlines())
    frame = src.split("screen vn_game_menu(", 1)[1].split("\nscreen ", 1)[0]
    assert 'key "game_menu"' in frame, (
        "каркас подэкранов не перехватывает Esc/B — в главном меню клавиша выхода "
        "мертва по устройству движка")
    assert 'ShowMenu("main_menu")' in frame, "перехват есть, но ведёт не в главное меню"


def test_the_screens_tour_covers_both_menu_contexts(repo_root):
    """Тур открывает экраны и в игре, и в ГЛАВНОМ МЕНЮ.

    Он звался только из vn_end_of_content, то есть всегда при main_menu ==
    False, и целый класс «экран, открытый из главного меню, ведёт себя иначе» не
    проверялся ничем. Именно этот класс и сработал: рельса там рисует другую
    ветку, где не было ни одного пункта назад."""
    flow = (repo_root / "game" / "framework" / "00_core" / "030_flow.rpy").read_text(
        encoding="utf-8")
    assert "VN_AUTOPILOT_SCREENS_MAIN" in flow, (
        "рантайм не умеет прогонять тур в контексте главного меню")
    boot = flow.split("def autopilot_boot(", 1)[1].split("\n    def ", 1)[0]
    assert 'autopilot_screens("main_menu")' in boot, (
        "проход по экранам главного меню не вызывается из autopilot_boot — "
        "то есть до входа в игру, пока main_menu ещё True")

    cli = (repo_root / "tools" / "vn" / "src" / "vn" / "cli.py").read_text(
        encoding="utf-8")
    assert '"VN_AUTOPILOT_SCREENS_MAIN": "1"' in cli, "vn test screens не просит второй контекст"
    assert 'read_run(root, shots / "main_menu")' in cli, (
        "гейт не читает отчёт контекста главного меню — молчание одного контекста "
        "засчиталось бы за проверку второго")
