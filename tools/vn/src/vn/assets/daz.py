"""DAZ-декларации рендеров (ADR-0006): assets_src/daz/**/<name>.render.yaml.

Рендер в DAZ Studio — ручной GUI-шаг; контракт конвейера в том, что каждый
рендер ОБЪЯВЛЕН (schema daz_render@1: сцена, камера, свет, разрешение, пресеты
персонажей) и его выход попадает в provenance-цепочку. Тогда любой стилл/клип
в игре можно проследить до .duf и настроек — и воспроизвести.

Сцены .duf — бинарные сырцы: живут в хранилище через vn assets push (в git —
только манифесты, G2/G21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry
from . import provenance as prov

RENDER_SUFFIX = ".render.yaml"


@dataclass
class DazReport:
    checked: list[str] = field(default_factory=list)
    provenance_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_renders(root: Path, scope: str | None = None,
                     write_provenance: bool = True) -> DazReport:
    """Все декларации рендеров: схема, наличие сцены (файл или манифест),
    наличие выхода. Для готовых выходов — запись/обновление провенанса."""
    rep = DazReport()
    registry = SchemaRegistry(root / "tools" / "schemas")
    base = root / "assets_src"
    daz_dir = base / "daz"
    if not daz_dir.is_dir():
        return rep
    seen_outputs: dict[str, str] = {}
    for decl_path in sorted(daz_dir.rglob(f"*{RENDER_SUFFIX}")):
        rel = decl_path.relative_to(root).as_posix()
        if scope and not decl_path.relative_to(daz_dir).as_posix().startswith(scope.rstrip("/")):
            continue
        decl = load_yaml(decl_path)
        errs = registry.validate(decl, rel)
        if errs:
            rep.errors.extend(errs)
            continue
        rep.checked.append(rel)

        src = base / decl["source"]
        src_manifest = base / (decl["source"] + ".manifest.json")
        if not src.is_file() and not src_manifest.is_file():
            rep.errors.append(
                f"{rel}: сцены {decl['source']} нет ни локально, ни в манифестах "
                f"(vn assets push после сохранения .duf)")

        if decl["output"] in seen_outputs:
            rep.errors.append(f"{rel}: выход {decl['output']} уже объявлен "
                              f"в {seen_outputs[decl['output']]}")
            continue
        seen_outputs[decl["output"]] = rel

        output = base / decl["output"]
        if not output.is_file():
            rep.warnings.append(f"{rel}: выход {decl['output']} ещё не отрендерен")
            continue
        if write_provenance:
            try:
                p = prov.record_daz(root, decl_path.relative_to(base).as_posix(),
                                    decl, output)
                rep.provenance_written.append(p.relative_to(root).as_posix())
            except prov.ProvenanceError as e:
                rep.errors.append(f"{rel}: {e}")
    return rep
