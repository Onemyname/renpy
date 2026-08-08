"""Реестр лицензий сторонних ассетов (content/licenses.yaml, license_registry@1).

Для коммерческой 18+ игры на покупных 3D-ассетах правовой статус каждого
использованного продукта — не бумажка, а часть конвейера: декларации рендеров
ссылаются на записи реестра полем license, релизный гейт отказывается собирать
билд с ассетом, который нельзя использовать в игре (game_use: false) или во
взрослом контенте (nsfw_allowed: false для выходов в nsfw/**).

Восстановить учёт задним числом дорого — придётся вручную пробивать SKU каждого
продукта по сотням деклараций. Поэтому запись в реестр идёт ДО первого рендера.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry

REGISTRY_REL = "content/licenses.yaml"
# Декларации источников и путь к их «выходу» внутри документа
DECL_SOURCES = (
    ("daz", "daz_render@1"),
    ("vam", "vam_render@1"),
    ("sims4", "sims4_render@1"),
)


@dataclass
class LicenseReport:
    entries: int = 0
    declarations: int = 0
    unlicensed: list[str] = field(default_factory=list)   # декларации без license
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_registry(root: Path) -> dict:
    """Записи реестра {id: entry}; пустой словарь, если реестра нет."""
    path = root / REGISTRY_REL
    if not path.is_file():
        return {}
    doc = load_yaml(path) or {}
    return dict(doc.get("assets") or {})


def _is_nsfw_output(output: str) -> bool:
    """Конвенция ADR-0006: NSFW-контент живёт в подпапке nsfw/ своей категории."""
    return "/nsfw/" in f"/{output}"


def validate_licenses(root: Path) -> LicenseReport:
    """Сверка деклараций рендеров с реестром лицензий.

    Ошибки (блокируют релиз): ссылка на несуществующую запись; ассет с
    game_use: false; nsfw-выход из ассета с nsfw_allowed: false.
    Предупреждения: декларация без license (учёт не ведётся) и битый реестр.
    """
    rep = LicenseReport()
    registry_path = root / REGISTRY_REL
    if registry_path.is_file():
        doc = load_yaml(registry_path) or {}
        errs = SchemaRegistry(root / "tools" / "schemas").validate(doc, REGISTRY_REL)
        if errs:
            rep.errors.extend(errs)
            return rep
    entries = load_registry(root)
    rep.entries = len(entries)

    base = root / "assets_src"
    for subdir, schema_id in DECL_SOURCES:
        src_dir = base / subdir
        if not src_dir.is_dir():
            continue
        for decl_path in sorted(src_dir.rglob("*.render.yaml")):
            decl = load_yaml(decl_path) or {}
            if decl.get("schema") != schema_id:
                continue
            rel = decl_path.relative_to(root).as_posix()
            rep.declarations += 1
            refs = decl.get("license") or []
            if not refs:
                rep.unlicensed.append(rel)
                continue
            output = str(decl.get("output") or "")
            for ref in refs:
                entry = entries.get(ref)
                if entry is None:
                    rep.errors.append(
                        f"{rel}: license {ref!r} не найден в {REGISTRY_REL} — "
                        f"занесите продукт в реестр (SKU, тип лицензии, инвойс)")
                    continue
                if not entry.get("game_use", False):
                    rep.errors.append(
                        f"{rel}: ассет {ref!r} ({entry.get('title')}) помечен "
                        f"game_use: false — использование в коммерческой игре "
                        f"не разрешено лицензией")
                if _is_nsfw_output(output) and not entry.get("nsfw_allowed", False):
                    rep.errors.append(
                        f"{rel}: ассет {ref!r} ({entry.get('title')}) помечен "
                        f"nsfw_allowed: false, но выход {output} идёт в nsfw-зону — "
                        f"лицензия запрещает взрослое использование этого ассета")
    if rep.unlicensed:
        rep.warnings.append(
            f"{len(rep.unlicensed)} деклараций без поля license "
            f"(первая: {rep.unlicensed[0]}) — учёт лицензий не ведётся; "
            f"заполняйте с первого ассета, ретрофит дорог")
    return rep
