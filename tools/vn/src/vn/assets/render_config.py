"""Render-профиль проекта (project.yaml: render) — единственный источник правды
о разрешениях, форматах, прозрачности и вариантах масштаба ассетов (ADR-0012).

Зачем отдельный слой. Раньше эти решения были рассыпаны константами по коду:
суффикс `@2` был вшит в имя выхода спрайта, качество WebP — в `_transform`,
формат источника — в `glob("*.png")`, а целевое разрешение не проверялось вообще.
Из-за этого «поднять качество до 4K» означало правку конвейера, а не конфига.

Модель. Ren'Py работает в ВИРТУАЛЬНОЙ сетке (`gui.init`, здесь `screen`) и сам
подбирает файл повышенного разрешения по имени `<base>@<N>.<ext>`, если физический
экран крупнее виртуального (renpy/display/im.py: `get_oversampled_image`,
`config.automatic_oversampling = 4`). Поиск срабатывает ТОЛЬКО если у имени нет
собственного `@N` — поэтому эталонный (референсный) файл каждого ассета всегда
безсуффиксный, а варианты живут рядом как `@2`, `@4`.

Практическое следствие: игрок на 1080p грузит маленький вариант, игрок на 4K —
крупный, и ни один из них не платит за чужой. Смена «шипим 1080p» → «шипим 4K» =
правка `variants` в project.yaml + пересборка, без единой правки сцен и контента.

Классы ассетов и их геометрия:
  layout: screen      — ассет занимает весь виртуальный экран (bg, cg).
                        Вариант s -> screen * s.
  layout: oversample  — ассет верстается в master_scale раз меньше мастера (spr).
                        Вариант s -> master * s / master_scale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Расширения, которые Pillow читает и которые имеют смысл как МАСТЕР.
# JPEG допущен там, где прозрачность запрещена (фоны/CG): запрет «просто потому
# что PNG лучше» — искусственный, мастер из фотореалистичного рендера часто
# приезжает именно JPEG. Там, где нужна альфа (спрайты), JPEG исключён физически.
KNOWN_SOURCE_EXTS = ("png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp")

# Форматы выхода, которые Ren'Py грузит без сюрпризов на всех платформах.
OUT_FORMATS = {"webp": ".webp", "png": ".png", "jpg": ".jpg"}

DEFAULTS: dict = {
    # Виртуальная координатная сетка Ren'Py. МЕНЯТЬ НЕЛЬЗЯ без пересчёта всего UI:
    # в game/framework/20_ui и gui.rpy координаты, кегли и отступы заданы в ней.
    # Качество картинки от неё не зависит — за него отвечают variants.
    "screen": [1920, 1080],
    # -> config.image_cache_size_mb. Ren'Py трактует его как ПИКСЕЛЬНЫЙ лимит:
    # cache_limit = image_cache_mb * 1024 * 1024 // 4 (renpy/display/im.py: Cache.init).
    "image_cache_mb": 400,
    # Сколько «поколений» сцен должно помещаться в кэш одновременно: текущая сцена
    # + предзагрузка следующей + запас на откат. Меньше 2 — гарантированный трэш.
    "cache_generations": 3,
    "thumb": {"max_side": 512, "quality": 80, "out_format": "webp"},
    "classes": {
        "bg": {
            "formats": ["png", "jpg", "jpeg", "webp", "tif", "tiff"],
            "alpha": "forbid",
            "layout": "screen",
            "variants": [1, 2],
            "aspect_tolerance": 0.01,
            "quality": {"full": 90, "draft": 50},
            "out_format": "webp",
            "thumb": True,
            "source_min": None,
        },
        "cg": {
            "formats": ["png", "jpg", "jpeg", "webp", "tif", "tiff"],
            "alpha": "forbid",
            "layout": "screen",
            "variants": [1, 2],
            "aspect_tolerance": 0.01,
            "quality": {"full": 90, "draft": 50},
            "out_format": "webp",
            "thumb": True,
            "source_min": None,
        },
        "spr": {
            # Альфа обязательна -> JPEG физически непригоден (нет альфа-канала).
            "formats": ["png", "webp", "tif", "tiff"],
            "alpha": "require",
            "layout": "oversample",
            "master_scale": 2,
            "variants": [1, 2],
            "quality": {"full": 95, "draft": 50},
            "out_format": "webp",
            "thumb": False,
            "source_min": None,
        },
        "mov": {
            # Видео Ren'Py тоже умеет оверсэмплить по имени
            # (renpy/display/video.py: find_oversampled_filename).
            "variants": [1],
            "heights": {"1": 1080, "2": 2160},
        },
    },
}


class RenderConfigError(RuntimeError):
    pass


def _merge(base: dict, over: dict | None) -> dict:
    """Рекурсивное слияние: пользователь переопределяет только то, что назвал."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class Variant:
    """Один отгружаемый масштаб ассета."""

    scale: int
    width: int
    height: int
    suffix: str          # "" для референсного варианта, "@2"/"@4" для остальных

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


@dataclass
class AssetClass:
    name: str
    spec: dict
    screen: tuple[int, int]

    @property
    def formats(self) -> tuple[str, ...]:
        return tuple(str(f).lower().lstrip(".") for f in self.spec.get("formats", ()))

    @property
    def alpha(self) -> str:
        return self.spec.get("alpha", "any")

    @property
    def layout(self) -> str:
        return self.spec.get("layout", "screen")

    @property
    def master_scale(self) -> int:
        return int(self.spec.get("master_scale", 1))

    @property
    def scales(self) -> list[int]:
        return sorted({int(s) for s in self.spec.get("variants", [1])})

    @property
    def out_ext(self) -> str:
        return OUT_FORMATS[self.spec.get("out_format", "webp")]

    @property
    def wants_thumb(self) -> bool:
        return bool(self.spec.get("thumb", False))

    @property
    def source_min(self) -> tuple[int, int] | None:
        sm = self.spec.get("source_min")
        return (int(sm[0]), int(sm[1])) if sm else None

    @property
    def aspect_tolerance(self) -> float:
        return float(self.spec.get("aspect_tolerance", 0.0))

    def quality(self, profile: str) -> int:
        q = self.spec.get("quality", {})
        return int(q.get(profile, q.get("full", 90)))

    def suffix_for(self, scale: int) -> str:
        """Референсный (наименьший) вариант — БЕЗ суффикса: только у безсуффиксного
        имени Ren'Py включает автоподбор `@N` под физический экран."""
        return "" if scale == self.scales[0] else f"@{scale}"

    def variants_for(self, master: tuple[int, int]) -> tuple[list[Variant], list[int]]:
        """Какие варианты можно собрать из мастера такого размера.
        Возвращает (собираемые, пропущенные_масштабы)."""
        mw, mh = master
        built: list[Variant] = []
        skipped: list[int] = []
        for scale in self.scales:
            if self.layout == "screen":
                w, h = self.screen[0] * scale, self.screen[1] * scale
            else:
                # Мастер отдан в master_scale раз крупнее вёрстки.
                w = round(mw * scale / self.master_scale)
                h = round(mh * scale / self.master_scale)
            if w > mw or h > mh:
                skipped.append(scale)      # апскейл запрещён: качества не создать
                continue
            built.append(Variant(scale, w, h, self.suffix_for(scale)))
        return built, skipped


@dataclass
class RenderConfig:
    screen: tuple[int, int]
    image_cache_mb: int
    cache_generations: int
    thumb: dict
    classes: dict[str, AssetClass] = field(default_factory=dict)

    # ── Пиксельная модель кэша Ren'Py ────────────────────────────────────────
    @property
    def cache_limit_px(self) -> int:
        """Ren'Py: cache_limit = image_cache_size_mb * 1024 * 1024 // 4 — это ПИКСЕЛИ,
        а не байты (renpy/display/im.py: Cache.init). Повторяем формулу дословно."""
        return int(self.image_cache_mb * 1024 * 1024 // 4)

    @property
    def scene_budget_px(self) -> int:
        """Сколько пикселей может стоить одна сцена, чтобы в кэш влезло
        cache_generations сцен подряд (текущая + предзагрузка следующей + запас)."""
        return self.cache_limit_px // max(1, self.cache_generations)

    def cls(self, name: str) -> AssetClass:
        if name not in self.classes:
            raise RenderConfigError(f"класс ассетов {name!r} не описан в render.classes")
        return self.classes[name]

    def params_digest(self, cls_name: str, extra: dict) -> bytes:
        """Слепок параметров трансформации — участвует в хеше источника, поэтому
        правка конфига инвалидирует ровно свою ветку кэша (G13). Отдельного поля
        в манифесте не заводим: у видео и ui_panel ровно тот же приём."""
        payload = {"class": cls_name, "screen": list(self.screen), **extra}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def load_render_config(root: Path | None = None, project: dict | None = None) -> RenderConfig:
    """Профиль из project.yaml поверх дефолтов. Отсутствие project.yaml —
    не ошибка: синтетические корни (тесты, скаффолд) собираются на дефолтах."""
    if project is None:
        project = {}
        if root is not None:
            path = root / "project.yaml"
            if path.is_file():
                from ..repo import load_yaml

                try:
                    project = load_yaml(path) or {}
                except Exception:
                    project = {}
    merged = _merge(DEFAULTS, project.get("render") or {})
    screen = (int(merged["screen"][0]), int(merged["screen"][1]))
    classes = {
        name: AssetClass(name=name, spec=spec, screen=screen)
        for name, spec in merged["classes"].items()
    }
    return RenderConfig(
        screen=screen,
        image_cache_mb=int(merged["image_cache_mb"]),
        cache_generations=int(merged["cache_generations"]),
        thumb=dict(merged["thumb"]),
        classes=classes,
    )
