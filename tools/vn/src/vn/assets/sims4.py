"""Sims4-декларации захватов (ADR-0007): assets_src/sims4/**/<name>.render.yaml.

The Sims 4 — опциональный ЧЕТВЁРТЫЙ источник конвейера: контракт тот же, что у
DAZ/VaM — захват ОБЪЯВЛЕН (schema sims4_render@1) и попадает в provenance-цепочку,
дальше общий трек art/** | video_src/** -> vn assets build -> game/assets.

Исходник сцены — zip-бандл Tray-файлов (лот+семья), сейв или .package: бинарные
сырцы живут в хранилище через vn assets push, в git — манифесты (G2/G21).
capture.game_version обязателен схемой: патчи EA меняют картинку и ломают моды —
кадр без зафиксированной версии игры невоспроизводим.

Проверки общие для всех источников — assets/sources.py."""

from __future__ import annotations

from pathlib import Path

from . import sources

RENDER_SUFFIX = sources.RENDER_SUFFIX
Sims4Report = sources.SourceReport


def validate_scenes(root: Path, scope: str | None = None,
                    write_provenance: bool = True) -> sources.SourceReport:
    return sources.validate(root, sources.SIMS4, scope, write_provenance)
