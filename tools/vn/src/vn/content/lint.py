"""vn content lint — схемы, naming-конвенции, структура глав, layout (разделы 1.4, 3.12).

Строгость привязана к статусу главы (G15): для status: draft граф-проверки — warnings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry

CHAPTER_DIR_RE = re.compile(r"^ch(\d{2})_([a-z][a-z0-9_]{2,30})$")
SCENE_FILE_RE = re.compile(r"^s(\d{3})_([a-z][a-z0-9_]{2,40})\.scene\.(yaml|rpy)$")
CHAR_DIR_RE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")

# Каталоги, обязанные существовать (нормативное дерево 1.2 / C17)
REQUIRED_DIRS = [
    "game/framework/00_core",
    "game/framework/00_core/engine_compat",
    "game/framework/10_systems",
    "game/framework/20_ui",
    "game/framework/90_debug",
    "content/chapters",
    "content/characters",
    "content/registry",
    "tools/schemas",
    "docs",
]
# Файлы-скелет, обязанные существовать: безусловные входы компилятора и реестры G7.
# Инвариант «lint зелёный => build не падает» держится на этом списке.
REQUIRED_FILES = [
    "project.yaml",
    ".vnstorage.yaml",
    "content/renames.yaml",
    "content/registry/id_registry.json",
    "content/flags.yaml",
    "content/anchors.yaml",
    "content/migrations/registry.yaml",
]
# Каталоги/файлы, которых существовать НЕ должно
FORBIDDEN_PATHS = [
    "game/content",          # content/ строго вне game/ (G2)
    "game/images",           # автоопределение образов не используется (1.2)
]


@dataclass
class LintReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_declarations(root: Path):
    """Все декларативные документы, обязанные нести schema: (G16).
    REQUIRED_FILES идут первыми — их отсутствие само по себе ошибка."""
    for rel in REQUIRED_FILES:
        yield root / rel
    loc = root / "loc" / "loc.yaml"
    if loc.is_file():
        yield loc
    for base in (root / "content", root / "packs"):
        if base.is_dir():
            yield from sorted(base.rglob("*.yaml"))
            yield from sorted(base.rglob("*.yml"))
    reg = root / "content" / "registry"
    if reg.is_dir():
        yield from sorted(reg.glob("*.json"))
    src = root / "assets_src"
    if src.is_dir():
        yield from sorted(src.rglob("*.manifest.json"))


def _load_doc(path: Path):
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return load_yaml(path)


def lint(root: Path, layout: bool = True) -> LintReport:
    rep = LintReport()
    try:
        registry = SchemaRegistry(root / "tools" / "schemas")
    except ValueError as e:
        rep.error(f"tools/schemas: {e}")
        return rep

    # ── 1. Схема-валидация всех деклараций ───────────────────────────────────
    docs: dict[str, dict] = {}
    invalid: set[str] = set()   # схемно-невалидные: граф-проверки их пропускают
    seen: set[str] = set()
    for path in _iter_declarations(root):
        rel = _rel(root, path)
        if rel in seen:
            continue
        seen.add(rel)
        if not path.is_file():
            rep.error(f"{rel}: обязательный файл отсутствует")
            continue
        try:
            data = _load_doc(path)
        except Exception as e:
            rep.error(f"{rel}: не парсится: {e}")
            invalid.add(rel)
            continue
        errs = registry.validate(data, rel)
        for err in errs:
            rep.error(err)
        if errs:
            invalid.add(rel)
        docs[rel] = data if isinstance(data, dict) else {}

    # ── 2. Структура глав ────────────────────────────────────────────────────
    chapters: dict[str, dict] = {}   # ch_id -> {"scenes": set, "status": str}
    chapters_dir = root / "content" / "chapters"
    if chapters_dir.is_dir():
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
            m = CHAPTER_DIR_RE.match(d.name)
            if not m:
                rep.error(f"{_rel(root, d)}: имя папки главы вне конвенции ch<NN>_<slug> (1.4)")
                continue
            ch_id = f"ch{m.group(1)}"
            ch_yaml = d / "chapter.yaml"
            meta = docs.get(_rel(root, ch_yaml), {})
            if not ch_yaml.is_file():
                rep.error(f"{_rel(root, d)}: нет chapter.yaml")
                continue
            if meta.get("id") and meta["id"] != ch_id:
                rep.error(f"{_rel(root, ch_yaml)}: id ({meta['id']}) != префиксу папки ({ch_id})")
            status = meta.get("status", "draft")
            scenes: set[str] = set()
            scenes_dir = d / "scenes"
            if scenes_dir.is_dir():
                for f in sorted(scenes_dir.iterdir()):
                    if f.name == ".gitkeep" or f.is_dir():
                        continue
                    sm = SCENE_FILE_RE.match(f.name)
                    if not sm:
                        rep.error(f"{_rel(root, f)}: имя файла сцены вне конвенции s<NNN>_<slug>.scene.(yaml|rpy)")
                        continue
                    sid = f"s{sm.group(1)}"
                    if f.suffix == ".yaml":
                        scenes.add(sid)
                        pair = f.parent / (f.name[: -len(".yaml")] + ".rpy")
                        if not pair.is_file():
                            rep.error(f"{_rel(root, f)}: нет парного .scene.rpy (сцена = ПАРА файлов, G3)")
                        smeta = docs.get(_rel(root, f), {})
                        if smeta.get("id") and smeta["id"] != sid:
                            rep.error(f"{_rel(root, f)}: id ({smeta['id']}) != номеру файла ({sid})")
                    else:
                        pair = f.parent / (f.name[: -len(".rpy")] + ".yaml")
                        if not pair.is_file():
                            rep.error(f"{_rel(root, f)}: нет парного .scene.yaml (сцена = ПАРА файлов, G3)")
            chapters[ch_id] = {"scenes": scenes, "status": status, "dir": d.name}

            # порядок и вход
            order = meta.get("scene_order", [])
            entry = meta.get("entry_scene")
            complain = rep.warn if status == "draft" else rep.error
            for s in order:
                if s not in scenes:
                    complain(f"{_rel(root, ch_yaml)}: scene_order ссылается на несуществующую сцену {s}")
            if entry and entry not in scenes:
                complain(f"{_rel(root, ch_yaml)}: entry_scene {entry} не существует")

    # ── 3. Exits: битые цели переходов ──────────────────────────────────────
    # Схемно-невалидные документы пропускаются: их структура непредсказуема,
    # а ошибка по ним уже выдана в секции 1 (не роняем весь lint трейсбеком).
    for rel, data in docs.items():
        if rel in invalid or not rel.endswith(".scene.yaml") or data.get("schema") != "scene@1":
            continue
        parts = Path(rel).parts   # content/chapters/<chdir>/scenes/<file>
        if len(parts) < 4 or parts[1] != "chapters":
            continue
        ch_id = parts[2][:4]
        status = chapters.get(ch_id, {}).get("status", "draft")
        complain = rep.warn if status == "draft" else rep.error
        exits = data.get("exits") or {}
        for exit_id, target in exits.items():
            if isinstance(target, str):
                targets = [target]
            elif isinstance(target, dict):
                targets = [target.get("to")]
            elif isinstance(target, list):
                targets = [t.get("to") for t in target if isinstance(t, dict)]
            else:
                targets = []
            for t in targets:
                if not isinstance(t, str):
                    continue
                if "/" in t:
                    t_ch, t_s = t.split("/", 1)
                    if t_s not in chapters.get(t_ch, {}).get("scenes", set()):
                        complain(f"{rel}: exits.{exit_id} -> {t}: цель не существует")
                elif t not in chapters.get(ch_id, {}).get("scenes", set()):
                    complain(f"{rel}: exits.{exit_id} -> {t}: цель не существует в главе {ch_id}")

    # ── 4. Персонажи: id == имени папки ──────────────────────────────────────
    chars_dir = root / "content" / "characters"
    if chars_dir.is_dir():
        for d in sorted(p for p in chars_dir.iterdir() if p.is_dir()):
            if not CHAR_DIR_RE.match(d.name):
                rep.error(f"{_rel(root, d)}: ключ персонажа вне конвенции ^[a-z][a-z0-9_]{{1,23}}$")
                continue
            c_yaml = d / "character.yaml"
            if not c_yaml.is_file():
                rep.error(f"{_rel(root, d)}: нет character.yaml")
                continue
            cmeta = docs.get(_rel(root, c_yaml), {})
            if cmeta.get("id") and cmeta["id"] != d.name:
                rep.error(f"{_rel(root, c_yaml)}: id ({cmeta['id']}) != имени папки ({d.name})")

    # ── 5. vars.yaml глав: store == id главы ─────────────────────────────────
    for rel, data in docs.items():
        if rel.startswith("content/chapters/") and rel.endswith("/vars.yaml"):
            ch_id = Path(rel).parts[2][:4]
            if data.get("store") and data["store"] != ch_id:
                rep.error(f"{rel}: store ({data['store']}) != id главы ({ch_id})")

    # ── 6. id_registry: выпущенные id не должны молча исчезать (G7) ─────────
    reg_rel = "content/registry/id_registry.json"
    id_reg = docs.get(reg_rel, {})
    renames = docs.get("content/renames.yaml", {})
    known_scene_moves = set(renames.get("scenes") or {}) | set(renames.get("deleted_scenes") or {})
    existing_full_ids = {
        f"{ch}_{s}" for ch, info in chapters.items() for s in info["scenes"]
    }
    for released in id_reg.get("scenes", []):
        if released not in existing_full_ids and released not in known_scene_moves:
            rep.error(
                f"{reg_rel}: выпущенная сцена {released} исчезла без записи в renames.yaml "
                f"(id неизменяемы навсегда, G7)"
            )

    # ── 7. Layout (1.2) ──────────────────────────────────────────────────────
    if layout:
        for d in REQUIRED_DIRS:
            if not (root / d).is_dir():
                rep.error(f"layout: обязательный каталог отсутствует: {d}/")
        for p in FORBIDDEN_PATHS:
            if (root / p).exists():
                rep.error(f"layout: запрещённый путь существует: {p} (G2/1.2)")

    return rep
