"""Работа с растром: проба мастера, энкод варианта, модель памяти Ren'Py (ADR-0012).

Модель памяти здесь — не оценка «на глаз», а ПОВТОРЕНИЕ формул движка
(renpy/display/im.py, Ren'Py 8.5.3):

  Cache.init():        cache_limit = config.image_cache_size_mb * 1024 * 1024 // 4
                       -> лимит измеряется в ПИКСЕЛЯХ, не в байтах;
  Cache.get():         bounds = surf.get_bounding_rect()
                       bounds = expand_bounds(bounds, size, config.expand_texture_bounds)
                       -> при optimize_texture_bounds (дефолт True) движок обрезает
                          текстуру по непрозрачному bbox, и полностью прозрачные поля
                          холста НЕ стоят памяти;
  CacheEntry.size():   bounds_w * bounds_h * 1.34   (1 текстура + 0.34 мипмапы)

Поэтому спрайт-слой «лицо на полном холсте 1200x2200» стоит не 2.6 Мпикс, а
площадь своего bbox плюс 8 px запаса — в разы меньше. Любая наша прикидка, не
учитывающая обрезку, завышала бы стоимость сцены и заставляла раздувать кэш зря.
"""

from __future__ import annotations

import io
from pathlib import Path

# renpy/config.py: expand_texture_bounds = 8, optimize_texture_bounds = True
EXPAND_TEXTURE_BOUNDS = 8
# renpy/display/im.py: CacheEntry.size(), cache_surfaces=False (дефолт)
TEXTURE_MULTIPLIER = 1.34


class ImagingError(RuntimeError):
    pass


def _open(path: Path):
    from PIL import Image

    try:
        return Image.open(path)
    except Exception as e:                    # битый/недописанный/не-растр
        raise ImagingError(f"не читается как изображение: {e}") from e


def probe(path: Path) -> dict:
    """Свойства мастера: размер, формат, наличие ЗНАЧИМОЙ прозрачности, bbox.

    «Значимая» = альфа-канал есть И в нём реально встречаются прозрачные пиксели.
    RGBA-файл с полностью непрозрачной альфой считается непрозрачным: именно так
    выглядит скриншот, у которого фон не вырезали, и именно это надо ловить."""
    with _open(path) as im:
        fmt = (im.format or "").lower()
        size = im.size
        has_alpha_channel = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        alpha_min = 255
        bbox = (0, 0, size[0], size[1])
        if has_alpha_channel:
            rgba = im.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_min = alpha.getextrema()[0]
            if alpha_min < 255:
                bb = alpha.getbbox()          # прямоугольник непрозрачного
                bbox = (bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]) if bb else (0, 0, 0, 0)
    return {
        "format": fmt,
        "size": size,
        "width": size[0],
        "height": size[1],
        "has_alpha": has_alpha_channel and alpha_min < 255,
        "alpha_min": alpha_min,
        "bbox": bbox,
    }


def expand_bounds(bounds, size, amount: int = EXPAND_TEXTURE_BOUNDS):
    """Дословный порт renpy.display.im.expand_bounds."""
    x, y, w, h = bounds
    sx, sy = size
    x0 = max(0, x - amount)
    y0 = max(0, y - amount)
    x1 = min(sx, x + w + amount)
    y1 = min(sy, y + h + amount)
    return (x0, y0, x1 - x0, y1 - y0)


def decoded_cost_px(data: bytes) -> int:
    """Во сколько пикселей кэша Ren'Py обойдётся ЭТОТ собранный файл.

    Считаем ровно как движок: bbox непрозрачного + expand_texture_bounds,
    умноженные на TEXTURE_MULTIPLIER. Для непрозрачных ассетов bbox = весь кадр."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        size = im.size
        bounds = (0, 0, size[0], size[1])
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            alpha = im.convert("RGBA").getchannel("A")
            if alpha.getextrema()[0] < 255:
                bb = alpha.getbbox()
                bounds = (bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]) if bb else (0, 0, 0, 0)
    bounds = expand_bounds(bounds, size)
    return int(bounds[2] * bounds[3] * TEXTURE_MULTIPLIER)


def encode(src: Path, target: tuple[int, int] | None, quality: int,
           out_format: str = "webp", keep_alpha: bool = True,
           max_side: int | None = None) -> bytes:
    """Мастер -> байты варианта.

    target=None — размер мастера как есть. Уменьшение — LANCZOS (единственный
    фильтр Pillow, не мылящий даунскейл 2:1 фотореалистичного рендера).
    keep_alpha=False -> RGB: у непрозрачных классов альфа-канал это ~20 % веса
    файла ни за что, а bbox-оптимизация движка на нём всё равно не срабатывает."""
    from PIL import Image

    with _open(src) as im:
        im = im.convert("RGBA" if keep_alpha else "RGB")
        if target and im.size != tuple(target):
            if target[0] > im.size[0] or target[1] > im.size[1]:
                raise ImagingError(
                    f"апскейл {im.size} -> {tuple(target)} запрещён: качества "
                    f"не бывает из ничего, отдайте мастер крупнее")
            im = im.resize(tuple(target), Image.LANCZOS)
        if max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = out_format.lower()
        if fmt == "webp":
            im.save(buf, format="WEBP", quality=quality, method=4)
        elif fmt == "png":
            im.save(buf, format="PNG", optimize=True)
        elif fmt == "jpg":
            im.convert("RGB").save(buf, format="JPEG", quality=quality,
                                   optimize=True, progressive=True, subsampling=0)
        else:
            raise ImagingError(f"неизвестный формат выхода {out_format!r}")
        return buf.getvalue()


def aspect_mismatch(size: tuple[int, int], target: tuple[int, int]) -> float:
    """Относительное расхождение пропорций (0 = совпадают)."""
    a = size[0] / size[1]
    b = target[0] / target[1]
    return abs(a - b) / b
