"""Sims4-декларации захватов (ADR-0007): assets_src/sims4/**/<name>.render.yaml.

The Sims 4 — опциональный ЧЕТВЁРТЫЙ источник конвейера, задел рядом с DAZ/VaM:
контракт тот же — захват (скриншот/секвенция) ОБЪЯВЛЕН (schema sims4_render@1)
и попадает в provenance-цепочку, дальше общий трек png/cg | video_src ->
vn assets build/video -> game/assets. Продакшен-трек проекта — DAZ; этот модуль
держит движок источника готовым на случай, если трек решат задействовать.

Исходник сцены — zip-бандл Tray-файлов (лот+семья), сейв или .package: бинарные
сырцы живут в хранилище через vn assets push, в git — манифесты (G2/G21).
capture.game_version обязателен схемой: патчи EA меняют картинку и ломают моды —
кадр без зафиксированной версии игры невоспроизводим."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry
from . import provenance as prov

RENDER_SUFFIX = ".render.yaml"


@dataclass
class Sims4Report:
    checked: list[str] = field(default_factory=list)
    provenance_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_scenes(root: Path, scope: str | None = None,
                    write_provenance: bool = True) -> Sims4Report:
    """Все декларации захватов Sims 4: схема, наличие сцены (файл или манифест),
    наличие выхода. Для готовых выходов — запись/обновление провенанса."""
    rep = Sims4Report()
    registry = SchemaRegistry(root / "tools" / "schemas")
    base = root / "assets_src"
    sims_dir = base / "sims4"
    if not sims_dir.is_dir():
        return rep
    seen_outputs: dict[str, str] = {}
    for decl_path in sorted(sims_dir.rglob(f"*{RENDER_SUFFIX}")):
        rel = decl_path.relative_to(root).as_posix()
        if scope and not decl_path.relative_to(sims_dir).as_posix().startswith(scope.rstrip("/")):
            continue
        decl = load_yaml(decl_path)
        errs = registry.validate(decl, rel)
        if errs:
            rep.errors.extend(errs)
            continue
        rep.checked.append(rel)

        src = base / decl["scene"]
        src_manifest = base / (decl["scene"] + ".manifest.json")
        if not src.is_file() and not src_manifest.is_file():
            rep.errors.append(
                f"{rel}: сцены {decl['scene']} нет ни локально, ни в манифестах "
                f"(vn assets push после экспорта Tray-бандла/сейва)")

        if decl["output"] in seen_outputs:
            rep.errors.append(f"{rel}: выход {decl['output']} уже объявлен "
                              f"в {seen_outputs[decl['output']]}")
            continue
        seen_outputs[decl["output"]] = rel

        output = base / decl["output"]
        if not output.is_file():
            rep.warnings.append(f"{rel}: выход {decl['output']} ещё не захвачен")
            continue
        if write_provenance:
            try:
                p = prov.record_sims4(root, decl_path.relative_to(base).as_posix(),
                                      decl, output)
                rep.provenance_written.append(p.relative_to(root).as_posix())
            except prov.ProvenanceError as e:
                rep.errors.append(f"{rel}: {e}")
    return rep
