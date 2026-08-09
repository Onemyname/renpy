"""DAZ-декларации рендеров (ADR-0006): assets_src/daz/**/<name>.render.yaml.

Рендер в DAZ Studio — ручной GUI-шаг; контракт конвейера в том, что каждый
рендер ОБЪЯВЛЕН (schema daz_render@1: сцена, камера, свет, разрешение, пресеты
персонажей) и его выход попадает в provenance-цепочку. Тогда любой стилл/клип
в игре можно проследить до .duf и настроек — и воспроизвести.

Дальше выход идёт общим треком: art/** или video_src/** -> vn assets build ->
game/assets. AI-полировка (ComfyUI/Wan) добавляется шагом провенанса поверх
рендера — отдельной ветки конвейера у неё нет и не требуется.

Сцены .duf — бинарные сырцы: живут в хранилище через vn assets push (в git —
только манифесты, G2/G21).

Проверки общие для всех источников — assets/sources.py."""

from __future__ import annotations

from pathlib import Path

from . import sources

RENDER_SUFFIX = sources.RENDER_SUFFIX
DazReport = sources.SourceReport


def validate_renders(root: Path, scope: str | None = None,
                     write_provenance: bool = True) -> sources.SourceReport:
    """Все декларации рендеров: схема, наличие сцены, соответствие id и выхода,
    объявленное разрешение против фактического, провенанс."""
    return sources.validate(root, sources.DAZ, scope, write_provenance)
