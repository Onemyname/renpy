"""VaM-декларации захватов (ADR-0006): assets_src/vam/**/<name>.render.yaml.

Virt-a-Mate — опциональный ТРЕТИЙ источник конвейера рядом с DAZ: сцену собирают
и захватывают вручную в приложении, но контракт тот же — захват ОБЪЯВЛЕН
(schema vam_render@1) и попадает в provenance-цепочку. Дальше — общий трек.

Сцены VaM (.json/.vac/.vap) — бинарные/тяжёлые сырцы: в хранилище через
vn assets push, в git — только манифесты (G2/G21).

Проверки общие для всех источников — assets/sources.py."""

from __future__ import annotations

from pathlib import Path

from . import sources

RENDER_SUFFIX = sources.RENDER_SUFFIX
VamReport = sources.SourceReport


def validate_scenes(root: Path, scope: str | None = None,
                    write_provenance: bool = True) -> sources.SourceReport:
    return sources.validate(root, sources.VAM, scope, write_provenance)
