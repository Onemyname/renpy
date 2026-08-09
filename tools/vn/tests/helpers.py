"""Общие помощники тестов: синтетический корень с маленьким render-профилем.

Мастера боевого профиля — 4K, и гонять их в юнит-тестах бессмысленно дорого.
Вместо ослабления проверок тесты объявляют СВОЙ render-профиль с крошечным
экраном: та же кодовая ветка, те же валидации, картинки 64x48. Заодно это
проверяет, что профиль действительно data-driven, а не зашит в конвейер.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TINY_SCREEN = (64, 48)


def write_project(root: Path, screen=TINY_SCREEN, render_extra: dict | None = None,
                  budgets: dict | None = None) -> Path:
    """Минимальный project.yaml с маленьким render-профилем."""
    doc = {
        "schema": "project@1",
        "version": "0.0.1",
        "save_schema": 1,
        "min_tools": "0.1",
        "render": {
            "screen": list(screen),
            "image_cache_mb": 64,
            "cache_generations": 3,
            "classes": {
                "bg": {"variants": [1, 2]},
                "cg": {"variants": [1, 2]},
                "spr": {"master_scale": 2, "variants": [1, 2]},
            },
        },
    }
    if render_extra:
        _merge(doc["render"], render_extra)
    if budgets:
        doc["budgets"] = budgets
    root.mkdir(parents=True, exist_ok=True)
    path = root / "project.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def mk_root(tmp_path: Path, **kwargs) -> Path:
    """Корень с зоной мастеров и render-профилем."""
    root = tmp_path / "repo"
    (root / "assets_src" / "art").mkdir(parents=True)
    write_project(root, **kwargs)
    return root


def img(path: Path, size, mode="RGBA", fmt=None, color=(200, 100, 50, 255),
        transparent_border: bool = True):
    """Мастер заданного размера/формата. У RGBA по умолчанию делаем реальную
    прозрачную рамку: без неё «альфа есть, но всё непрозрачно» — а это ровно то
    состояние, которое конвейер обязан считать ошибкой для спрайтов."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new(mode, size, color[: 4 if mode == "RGBA" else 3])
    if mode == "RGBA" and transparent_border:
        px = im.load()
        edge = max(1, size[1] // 16)
        for x in range(size[0]):
            for y in range(edge):
                px[x, y] = (0, 0, 0, 0)
    im.save(path, format=fmt)
    return path
