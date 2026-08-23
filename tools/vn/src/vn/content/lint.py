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
from . import migrations as mig

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
# Порог суммарного веса бинарных сырцов в git (ADR-0004): при превышении
# assets_src обязан переехать в хранилище (vn assets push), иначе история
# репозитория раздувается необратимо.
ADR0004_BINARY_LIMIT_MB = 50

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


def _lfs_tracked(root: Path, files: list[Path]) -> tuple[set[Path], bool]:
    """Какие из файлов реально покрыты LFS. Ответ даёт САМ git (check-attr): свои
    правила .gitattributes (`**`, порядок, отрицания) он трактует иначе, чем fnmatch,
    и расхождение здесь означало бы ложные ошибки в CI.

    Возвращает (множество, доступен_ли_git). Без git (синтетические корни, тесты)
    вторым элементом False — вызывающий не делает выводов о покрытии."""
    import subprocess

    if not files or not (root / ".git").exists():
        return set(), False
    try:
        payload = "\0".join(_rel(root, f) for f in files)
        out = subprocess.run(
            ["git", "check-attr", "--stdin", "-z", "filter"],
            cwd=root, input=payload, capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return set(), False
    except (OSError, subprocess.SubprocessError):
        return set(), False
    # Формат -z: path\0attr\0value\0 ...
    fields = out.stdout.split("\0")
    tracked: set[Path] = set()
    for i in range(0, len(fields) - 2, 3):
        if fields[i + 1] == "filter" and fields[i + 2] == "lfs":
            tracked.add(root / fields[i])
    return tracked, True


def _iter_declarations(root: Path):
    """Все декларативные документы, обязанные нести schema: (G16).
    REQUIRED_FILES идут первыми — их отсутствие само по себе ошибка."""
    for rel in REQUIRED_FILES:
        yield root / rel
    loc = root / "loc" / "loc.yaml"
    if loc.is_file():
        yield loc
    # Манифесты языковых пакетов (ADR-0005): наличие файла = язык существует,
    # поэтому битый манифест = сломанный язык — валидируем наравне с декларациями.
    po_dir = root / "loc" / "po"
    if po_dir.is_dir():
        yield from sorted(po_dir.glob("*/language.yaml"))
    for base in (root / "content", root / "packs"):
        if base.is_dir():
            yield from sorted(base.rglob("*.yaml"))
            yield from sorted(base.rglob("*.yml"))
    # Журнал номеров строк: битая или старая схема означает переиспользованный
    # номер (то есть перевод, переехавший на чужую реплику), а не косметику.
    ledger = root / "loc" / "ledger"
    if ledger.is_dir():
        yield from sorted(ledger.glob("ch*.json"))
    # Записи повтора (replay@1) — такие же входные данные с ожидаемым результатом,
    # что и фикстуры сейвов: битая запись должна краснеть на lint, а не на прогоне.
    replays = root / "ci" / "fixtures" / "replays"
    if replays.is_dir():
        yield from sorted(replays.glob("*.vnrec.json"))
    reg = root / "content" / "registry"
    if reg.is_dir():
        yield from sorted(reg.glob("*.json"))
    # Трассировка аудита (audit@1): статус «закрыто» обязан называть реализацию и
    # тест — это проверяет схема, поэтому сам трекер валидируется наравне с контентом.
    audit = root / "docs" / "audit"
    if audit.is_dir():
        yield from sorted(audit.glob("*.audit.yaml"))
    src = root / "assets_src"
    if src.is_dir():
        yield from sorted(src.rglob("*.manifest.json"))
        # ADR-0006: декларации рендеров, sidecar-опции видео, провенанс —
        # все несут schema: и валидируются наравне с контентом (G16).
        yield from sorted(src.rglob("*.yaml"))
        yield from sorted(src.rglob("*.provenance.json"))


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

    # ── 1a. Пакеты языков: code == имени каталога, каталоги без манифеста ────
    po_dir = root / "loc" / "po"
    if po_dir.is_dir():
        for d in sorted(p for p in po_dir.iterdir() if p.is_dir()):
            mf_rel = _rel(root, d / "language.yaml")
            if not (d / "language.yaml").is_file():
                rep.error(f"loc/po/{d.name}/: нет language.yaml — пакет языка не собран "
                          f"(vn loc add {d.name} --name <native>)")
                continue
            code = docs.get(mf_rel, {}).get("code")
            if mf_rel not in invalid and code != d.name:
                rep.error(f"{mf_rel}: code ({code}) != имени каталога ({d.name})")

    # ── 2. Структура глав: ядро + packs/*/chapters (C10) ────────────────────
    chapters: dict[str, dict] = {}   # ch_id -> {"scenes": set, "status": str}
    chapter_zones = [root / "content" / "chapters"]
    if (root / "packs").is_dir():
        chapter_zones += sorted((root / "packs").glob("*/chapters"))
    for chapters_dir in chapter_zones:
        if not chapters_dir.is_dir():
            continue
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
                        if sid in scenes:
                            rep.error(f"{_rel(root, f)}: дубликат id сцены {sid} в главе")
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
            # Столкновение номера главы между ядром и паком: раньше вторая запись
            # молча затирала первую, и по затёртой главе не выполнялись ни проверка
            # достижимости, ни сверка exits — то есть половина линта исчезала без
            # единого сообщения. Номер главы обязан быть уникальным на дерево: id
            # сцен (chNN_sNNN) плоские, и две главы chNN дали бы одинаковые id.
            if ch_id in chapters:
                rep.error(
                    f"{_rel(root, d)}: номер главы {ch_id} уже занят "
                    f"({chapters[ch_id]['dir']}) — id сцен плоские (chNN_sNNN), и две "
                    f"главы с одним номером дают одинаковые id: переименуйте одну")
                continue
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
    scene_exits: dict[str, list[str]] = {}    # ch_id_sNNN -> [полные id целей]
    for rel, data in docs.items():
        if rel in invalid or not rel.endswith(".scene.yaml") or data.get("schema") != "scene@1":
            continue
        parts = Path(rel).parts   # content/chapters/... или packs/<id>/chapters/...
        if "chapters" not in parts:
            continue
        ch_dir_idx = parts.index("chapters") + 1
        if len(parts) <= ch_dir_idx + 1:
            continue
        ch_id = parts[ch_dir_idx][:4]
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
                    full_target = f"{t_ch}_{t_s}"
                elif t not in chapters.get(ch_id, {}).get("scenes", set()):
                    complain(f"{rel}: exits.{exit_id} -> {t}: цель не существует в главе {ch_id}")
                    full_target = f"{ch_id}_{t}"
                else:
                    full_target = f"{ch_id}_{t}"
                scene_exits.setdefault(f"{ch_id}_{data['id']}", []).append(full_target)

    # ── 3a. Достижимость: обход графа сцен от entry_scene каждой главы ───────
    # Недостижимая сцена = написанный и переведённый контент, которого игрок
    # никогда не увидит; тупик = игра упирается в «конец контента» посреди главы.
    # Финальные сцены (exits: {}) — легитимные тупики, их не считаем.
    for ch_id, info in sorted(chapters.items()):
        ch_meta = None
        for rel, data in docs.items():
            if rel.endswith("/chapter.yaml") and data.get("id") == ch_id:
                ch_meta = data
                break
        entry = (ch_meta or {}).get("entry_scene")
        if not entry or entry not in info["scenes"]:
            continue    # об отсутствующем entry уже сообщила секция 2
        complain = rep.warn if info["status"] == "draft" else rep.error
        start = f"{ch_id}_{entry}"
        seen, queue = {start}, [start]
        while queue:
            cur = queue.pop()
            for nxt in scene_exits.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        for sid in sorted(info["scenes"]):
            full = f"{ch_id}_{sid}"
            if full not in seen:
                complain(
                    f"{ch_id}: сцена {sid} недостижима из entry_scene {entry} — "
                    f"на неё не ведёт ни один exit (мёртвый контент)"
                )
        # Тупики: сцена без exits, не являющаяся последней в scene_order.
        order = (ch_meta or {}).get("scene_order") or []
        last = order[-1] if order else None
        for sid in sorted(info["scenes"]):
            full = f"{ch_id}_{sid}"
            if full in seen and not scene_exits.get(full) and sid != last:
                rep.warn(
                    f"{ch_id}: сцена {sid} — тупик (нет exits, но не последняя "
                    f"в scene_order): игрок упрётся в «конец контента»"
                )

    # ── 4. Персонажи: id == имени папки ──────────────────────────────────────
    # Правило одно и живёт в characters.declaration_errors: те же слова говорит
    # `vn char validate`, иначе два места отвечали бы на один вопрос по-разному.
    from .characters import char_dirs, declaration_errors

    for d in char_dirs(root):
        if not CHAR_DIR_RE.match(d.name):
            rep.error(f"{_rel(root, d)}: ключ персонажа вне конвенции ^[a-z][a-z0-9_]{{1,23}}$")
            continue
        doc = docs.get(_rel(root, d / "character.yaml"), {})
        for e in declaration_errors(root, d, doc):
            rep.error(e)

    # ── 5. vars.yaml глав: store == id главы ─────────────────────────────────
    for rel, data in docs.items():
        if rel.startswith("content/chapters/") and rel.endswith("/vars.yaml"):
            ch_id = Path(rel).parts[2][:4]
            if data.get("store") and data["store"] != ch_id:
                rep.error(f"{rel}: store ({data['store']}) != id главы ({ch_id})")

    # ── 6. id_registry: выпущенные id не должны молча исчезать (G7) ─────────
    # Проверяются все четыре класса id. renames покрывает сцены и переменные;
    # главы и персонажи механизма переименования не имеют (не переименовываются).
    reg_rel = "content/registry/id_registry.json"
    id_reg = docs.get(reg_rel, {})
    renames = docs.get("content/renames.yaml", {})
    scene_moves = set(renames.get("scenes") or {}) | set(renames.get("deleted_scenes") or {})
    var_moves = set(renames.get("vars") or {})
    existing_full_ids = {
        f"{ch}_{s}" for ch, info in chapters.items() for s in info["scenes"]
    }
    existing_chapters = set(chapters)
    existing_chars: set[str] = set()
    char_zones = [root / "content" / "characters"]
    if (root / "packs").is_dir():
        char_zones += sorted((root / "packs").glob("*/characters"))
    for cz in char_zones:
        if cz.is_dir():
            existing_chars |= {d.name for d in cz.iterdir()
                               if d.is_dir() and CHAR_DIR_RE.match(d.name)}
    existing_vars: set[str] = set()
    for drel, data in docs.items():
        if not isinstance(data, dict) or data.get("schema") != "vars@1":
            continue
        store = data.get("store")
        if store and store != "persistent":
            for name in (data.get("vars") or {}):
                existing_vars.add(f"{store}.{name}")

    for released in id_reg.get("scenes", []):
        if released not in existing_full_ids and released not in scene_moves:
            rep.error(
                f"{reg_rel}: выпущенная сцена {released} исчезла без записи в renames.yaml "
                f"(id неизменяемы навсегда, G7)"
            )
    for released in id_reg.get("chapters", []):
        if released not in existing_chapters:
            rep.error(
                f"{reg_rel}: выпущенная глава {released} исчезла (главы не переименовываются, G7)"
            )
    for released in id_reg.get("characters", []):
        if released not in existing_chars:
            rep.error(
                f"{reg_rel}: выпущенный персонаж {released} исчез (id неизменяемы, G7)"
            )
    for released in id_reg.get("vars", []):
        if released not in existing_vars and released not in var_moves:
            rep.error(
                f"{reg_rel}: выпущенная переменная {released} исчезла без записи в "
                f"renames.vars (id неизменяемы, G7)"
            )
    # Ассеты: галерея открывает картинки по ИМЕНИ образа (persistent._seen_images),
    # поэтому переименование ассета после релиза стирает игроку открытый кадр.
    # Проверяем только при собранной зоне: без неё «исчез» означало бы «не собран».
    asset_moves = set(renames.get("assets") or {})
    released_assets = id_reg.get("assets", [])
    if released_assets and (root / "game" / "assets").is_dir():
        from ..release import built_asset_ids

        existing_assets = set(built_asset_ids(root))
        for released in released_assets:
            if released not in existing_assets and released not in asset_moves:
                rep.error(
                    f"{reg_rel}: выпущенный ассет {released} исчез без записи в "
                    f"renames.assets — у игроков он останется закрытым в галерее "
                    f"(ADR-0012)"
                )

    # ── 6a. Бинари в assets_src мимо LFS (ADR-0004 в редакции ADR-0012) ─────
    # Историю раздувают не бинари как таковые, а бинари, попавшие в git ОБЪЕКТАМИ:
    # git append-only и не дельта-сжимает уже сжатые форматы. LFS кладёт в историю
    # указатель на ~130 байт, поэтому мастер в LFS истории не вредит и под порог
    # не попадает. Считаем и ругаемся только на то, что идёт мимо LFS.
    src_dir = root / "assets_src"
    if src_dir.is_dir():
        text_ext = {".json", ".yaml", ".yml", ".md", ".txt", ".gitkeep"}
        binaries = [f for f in sorted(src_dir.rglob("*"))
                    if f.is_file() and f.suffix.lower() not in text_ext
                    and f.name != ".gitkeep"]
        lfs, known = _lfs_tracked(root, binaries)
        loose = [f for f in binaries if f not in lfs] if known else binaries
        if known:
            for f in loose:
                rep.error(
                    f"{_rel(root, f)}: бинарь в assets_src не покрыт Git LFS — "
                    f"он уедет в историю целиком и навсегда. Добавьте расширение в "
                    f".gitattributes (filter=lfs) или уберите файл из зоны мастеров"
                )
        total = sum(f.stat().st_size for f in loose)
        limit_mb = float(ADR0004_BINARY_LIMIT_MB)
        actual_mb = total / (1024 * 1024)
        if actual_mb > limit_mb:
            biggest = max(loose, key=lambda f: f.stat().st_size)
            rep.error(
                f"assets_src: бинарей мимо LFS на {actual_mb:.1f} МБ > порога "
                f"ADR-0004 ({limit_mb:.0f} МБ); крупнейший — {_rel(root, biggest)} "
                f"({biggest.stat().st_size / 1024 / 1024:.1f} МБ). Заведите их в LFS "
                f"(.gitattributes) либо в хранилище (vn assets lock + push)"
            )

    # ── 6b. Цепочка миграций сейвов (G5) ─────────────────────────────────────
    # Правила — те же, что у компилятора (content/migrations.py). Без этой секции
    # дыра в цепочке проходила бы lint и pre-push, а падала на vn build: инвариант
    # «lint зелёный => build не падает» (см. REQUIRED_FILES) был бы неверен.
    if "project.yaml" not in invalid:
        _save_schema = (docs.get("project.yaml") or {}).get("save_schema")
        if isinstance(_save_schema, int):
            _mig_errors = mig.collect(root / "content" / "migrations", _save_schema,
                                      lambda path: _rel(root, path))[1]
            for msg in _mig_errors:
                rep.error(msg)

    # ── 7. Layout (1.2) ──────────────────────────────────────────────────────
    if layout:
        for d in REQUIRED_DIRS:
            if not (root / d).is_dir():
                rep.error(f"layout: обязательный каталог отсутствует: {d}/")
        for p in FORBIDDEN_PATHS:
            if (root / p).exists():
                rep.error(f"layout: запрещённый путь существует: {p} (G2/1.2)")

    return rep
