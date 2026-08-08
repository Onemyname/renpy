"""VaM-декларации захватов (ADR-0006): assets_src/vam/**/<name>.render.yaml.

Virt-a-Mate — опциональный ТРЕТИЙ источник конвейера рядом с DAZ: сцену собирают
и захватывают (скриншот/секвенция) вручную в приложении, но контракт тот же —
захват ОБЪЯВЛЕН (schema vam_render@1: сцена, разрешение, режим, камера, плагины)
и попадает в provenance-цепочку. Дальше — общий трек: png/cg или video_src ->
vn assets build/video -> game/assets, ровно как у DAZ.

Сцены VaM (.json/.vac/.vap) — бинарные/тяжёлые сырцы: в хранилище через
vn assets push, в git — только манифесты (G2/G21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry
from . import provenance as prov

RENDER_SUFFIX = ".render.yaml"


@dataclass
class VamReport:
    checked: list[str] = field(default_factory=list)
    provenance_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_scenes(root: Path, scope: str | None = None,
                    write_provenance: bool = True) -> VamReport:
    """Все декларации захватов VaM: схема, наличие сцены (файл или манифест),
    наличие выхода. Для готовых выходов — запись/обновление провенанса."""
    rep = VamReport()
    registry = SchemaRegistry(root / "tools" / "schemas")
    base = root / "assets_src"
    vam_dir = base / "vam"
    if not vam_dir.is_dir():
        return rep
    seen_outputs: dict[str, str] = {}
    for decl_path in sorted(vam_dir.rglob(f"*{RENDER_SUFFIX}")):
        rel = decl_path.relative_to(root).as_posix()
        if scope and not decl_path.relative_to(vam_dir).as_posix().startswith(scope.rstrip("/")):
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
                f"(vn assets push после сохранения сцены VaM)")

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
                p = prov.record_vam(root, decl_path.relative_to(base).as_posix(),
                                    decl, output)
                rep.provenance_written.append(p.relative_to(root).as_posix())
            except prov.ProvenanceError as e:
                rep.errors.append(f"{rel}: {e}")
    return rep
