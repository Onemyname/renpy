"""Генерация UI-панелей (ADR-0009): декларация -> 9-patch PNG -> Frame.

Ren'Py не умеет скруглённые углы, мягкие тени и обводки на Solid: всё это
требует картинки. Рисовать её руками в редакторе — значит держать бинарь в
git и перерисовывать на каждую правку палитры. Вместо этого панели
ОБЪЯВЛЯЮТСЯ (content/ui/panels.yaml) и РИСУЮТСЯ конвейером — как остальные
ассеты: источник истины текстовый, выход производный (game/assets/ui/, не в git).

Геометрия 9-patch: рисуется квадрат со стороной 2*(radius+inset)+STRETCH, где
центральная полоска шириной STRETCH тянется движком. Borders для Frame
эмитятся вместе с образом (registry/ui_frames.gen.rpy), поэтому вёрстка не
знает про пиксели — только про имя панели.
"""

from __future__ import annotations

import io
import json
import math

STRETCH = 4          # ширина тянущейся центральной полосы (чётная — без дрожания)
SHADOW_STEPS = 14    # число слоёв аппроксимации мягкой тени


def _hex_rgba(value: str) -> tuple[int, int, int, int]:
    """'#rrggbb' | '#rrggbbaa' | '#rgb' -> (r, g, b, a)."""
    s = value.lstrip("#")
    if len(s) in (3, 4):
        s = "".join(c * 2 for c in s)
    if len(s) == 6:
        s += "ff"
    if len(s) != 8:
        raise ValueError(f"цвет {value!r} вне формата #rgb/#rgba/#rrggbb/#rrggbbaa")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def panel_hash_source(spec: dict) -> bytes:
    """Каноническое представление параметров — ключ кэша трансформации.
    Правка радиуса/цвета инвалидирует ровно эту панель, а не всю ветку."""
    return json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")


def borders_of(spec: dict) -> tuple[int, int, int, int]:
    """Borders для Frame: радиус + запас на тень/обводку со всех сторон."""
    inset = _inset(spec)
    r = int(spec.get("radius", 0)) + inset
    return (r, r, r, r)


def _inset(spec: dict) -> int:
    """Поле вокруг скруглённого прямоугольника под тень и обводку."""
    shadow = spec.get("shadow") or {}
    blur = int(shadow.get("blur", 0))
    offset = abs(int(shadow.get("dy", 0)))
    border = int((spec.get("border") or {}).get("width", 0))
    return max(blur + offset, border, 0)


def render_panel(spec: dict) -> bytes:
    """PNG-байты 9-patch панели по декларации (ui_panels@1)."""
    from PIL import Image, ImageDraw, ImageFilter

    radius = int(spec.get("radius", 0))
    inset = _inset(spec)
    side = 2 * (radius + inset) + STRETCH
    box = (inset, inset, side - inset - 1, side - inset - 1)

    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))

    # ── Тень: рисуется отдельным слоем и размывается, чтобы край был мягким ──
    shadow = spec.get("shadow") or {}
    blur = int(shadow.get("blur", 0))
    if blur or shadow.get("color"):
        sh = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        dy = int(shadow.get("dy", 0))
        sd.rounded_rectangle(
            (box[0], box[1] + dy, box[2], box[3] + dy),
            radius=radius, fill=_hex_rgba(shadow.get("color", "#00000080")),
        )
        if blur:
            sh = sh.filter(ImageFilter.GaussianBlur(blur / 2.0))
        img = Image.alpha_composite(img, sh)

    # ── Заливка: сплошная или вертикальный градиент ──────────────────────────
    fill = spec.get("fill")
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if isinstance(fill, dict):                       # градиент {from, to}
        grad = Image.new("RGBA", (1, side))
        c1, c2 = _hex_rgba(fill["from"]), _hex_rgba(fill["to"])
        gp = grad.load()
        for y in range(side):
            t = y / max(side - 1, 1)
            gp[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
        grad = grad.resize((side, side))
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
        layer = Image.composite(grad, layer, mask)
    elif fill:
        draw.rounded_rectangle(box, radius=radius, fill=_hex_rgba(fill))
    img = Image.alpha_composite(img, layer)

    # ── Обводка поверх заливки ───────────────────────────────────────────────
    border = spec.get("border") or {}
    if border.get("color") and int(border.get("width", 0)) > 0:
        bd = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(bd).rounded_rectangle(
            box, radius=radius, outline=_hex_rgba(border["color"]),
            width=int(border["width"]),
        )
        img = Image.alpha_composite(img, bd)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def emit_frames(panels: dict, header: str) -> str:
    """registry/ui_frames.gen.rpy: Frame-образы по именам панелей.
    Вёрстка ссылается на vn_frame_<id>, не зная ни путей, ни пикселей."""
    out = [header, "init offset = 0\n"]
    if not panels:
        out.append("# UI-панели не объявлены (content/ui/panels.yaml).")
        return "\n".join(out) + "\n"
    out.append("# Скруглённые фоны/тени: Ren'Py не рисует их без картинки,")
    out.append("# поэтому панели генерируются конвейером из деклараций (ADR-0009).")
    out.append("# Минимальный размер = 2*Borders: элемент меньше — движок сожмёт фон.")
    for pid, spec in sorted(panels.items()):
        l, t, r, b = borders_of(spec)
        tile = "True" if spec.get("tile") else "False"
        out.append(
            f'define vn_frame_{pid} = Frame("assets/ui/{pid}.webp", '
            f'Borders({l}, {t}, {r}, {b}), tile={tile})'
            f'   # минимум {l + r}x{t + b} px'
        )
    return "\n".join(out) + "\n"
