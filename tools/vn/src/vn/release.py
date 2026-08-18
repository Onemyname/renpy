"""vn release — манифест релиза, changelog, флейворы и релизный гейт (раздел 7/1.9,
ADR-0006): версии контента считаются по фактическому диффу реестров, а не по
ручным пометкам («их забывают»); флейворы (public/patron) описаны в project.yaml
и материализуются в game/build_id.json только на время distribute."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .content.compile import CHAPTER_DIR_RE, SCENE_YAML_RE
from .repo import git_sha, load_project, load_yaml

MANIFEST_REL = "ci/release-manifest.json"
BUILD_INFO_REL = "game/build_id.json"


class ReleaseError(RuntimeError):
    pass


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


def budget_failures(root: Path) -> list[str]:
    """Размер-бюджеты (G19; видео-бюджеты — ADR-0006). Пустой список = всё в рамках.
    Единая точка: и vn build, и vn release validate проверяют одно и то же."""
    budgets = load_project(root).get("budgets") or {}
    failures: list[str] = []
    assets = root / "game" / "assets"
    if "assets_total_mb" in budgets:
        actual = _dir_size(assets) / (1024 * 1024)
        if actual > budgets["assets_total_mb"]:
            failures.append(f"game/assets: {actual:.1f} МБ > бюджета {budgets['assets_total_mb']} МБ")
    if "generated_total_kb" in budgets:
        actual = _dir_size(root / "game" / "generated") / 1024
        if actual > budgets["generated_total_kb"]:
            failures.append(f"game/generated: {actual:.0f} КБ > бюджета {budgets['generated_total_kb']} КБ")
    mov = assets / "mov"
    if "video_total_mb" in budgets:
        actual = _dir_size(mov) / (1024 * 1024)
        if actual > budgets["video_total_mb"]:
            failures.append(f"game/assets/mov: {actual:.1f} МБ > бюджета {budgets['video_total_mb']} МБ")
    if "video_file_mb" in budgets and mov.is_dir():
        for f in sorted(mov.rglob("*.webm")):
            size_mb = f.stat().st_size / (1024 * 1024)
            if size_mb > budgets["video_file_mb"]:
                failures.append(f"{f.relative_to(root).as_posix()}: {size_mb:.1f} МБ > "
                                f"бюджета {budgets['video_file_mb']} МБ на файл")
    return failures


@dataclass
class ReleaseReport:
    added_chapters: list[str] = field(default_factory=list)
    added_scenes: list[str] = field(default_factory=list)
    removed_scenes: list[str] = field(default_factory=list)
    changed: bool = False
    stamped: int = 0            # сколько новых id занесено в id_registry (G7)


ID_REGISTRY_REL = "content/registry/id_registry.json"


def _released_ids(root: Path) -> dict:
    """Текущие id по классам для штампа реестра (G7). Персонажи/переменные штампуются
    только если есть хотя бы одна released-глава (иначе черновик не иммортализуем)."""
    chapters, scenes = [], []
    for ch_id, info in snapshot_content(root).items():
        if info.get("status") == "release":
            chapters.append(ch_id)
            scenes.extend(info["scenes"])
    if not scenes:
        return {"chapters": [], "scenes": [], "characters": [], "vars": [],
                "assets": []}
    chars = []
    cdir = root / "content" / "characters"
    if cdir.is_dir():
        chars = [d.name for d in sorted(cdir.iterdir())
                 if d.is_dir() and (d / "character.yaml").is_file()]
    variables = []
    var_files = []
    if (root / "content" / "variables").is_dir():
        var_files += sorted((root / "content" / "variables").glob("*.vars.yaml"))
    var_files += sorted((root / "content" / "chapters").glob("*/vars.yaml"))
    for vf in var_files:
        doc = load_yaml(vf)
        store = doc.get("store")
        if store and store != "persistent":
            for name in (doc.get("vars") or {}):
                variables.append(f"{store}.{name}")
    # Логические id собранных ассетов: галерея открывает картинки по ИМЕНИ образа
    # (persistent._seen_images), поэтому имя ассета — такой же выпущенный id, как
    # id сцены, и исчезать молча не должен (ADR-0012). Послойные шоты штампуются
    # своим составным id — см. built_asset_ids.
    return {"chapters": chapters, "scenes": scenes, "characters": chars,
            "vars": variables, "assets": built_asset_ids(root)}


# Файл слоя послойного шота: shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>]
# (ADR-0013). Группа 1 — составной id самого шота: каталог слоёв и есть шот, потому
# что имя каталога мастеров = его id, а собственного файла у шота нет.
SHOT_LAYER_RE = re.compile(
    r"^(shots/ch\d{2}/s\d{3}/[a-z][a-z0-9_]*)/[a-z][a-z0-9_]*(?:__[a-z][a-z0-9_]*)?$")


def built_asset_ids(root: Path) -> list[str]:
    """Логические id ассетов в game/assets: только референсные варианты, без
    производных (миниатюры, постеры, метаданные) — они не адресуются сценарием.

    Послойный шот попадает в список ДВАЖДЫ: своими слоями и СОСТАВНЫМ id
    (`shots/<chNN>/<sNNN>/<shot>`). Одних слоёв мало: галерея разблокирует шот по
    тегу образа плюс атрибуту ШОТА (`_seen_shot`, ADR-0013 в редакции 2026-08-18),
    поэтому переименование шота стирает игроку открытый кадр ровно так же, как
    переименование файла, — и обязано ловиться сетью G7 наравне с файловыми id.
    Источник один и тот же (собранное дерево), иначе штамп реестра и lint-проверка
    «выпущенный ассет исчез» разошлись бы и дали ложную красноту.
    """
    from .assets.pipeline import POSTER_SUFFIX, variant_scale

    assets = root / "game" / "assets"
    out: set[str] = set()
    for kind in ("bg", "cg", "spr", "shots", "mov"):
        base = assets / kind
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in (".webp", ".png", ".jpg", ".webm"):
                continue
            rel = f"{kind}/" + f.relative_to(base).as_posix()
            if rel.endswith(POSTER_SUFFIX) or f.stem.endswith(".thumb"):
                continue
            if variant_scale(f.stem) != 1:
                continue
            logical = rel.rsplit(".", 1)[0]
            out.add(logical)
            if kind == "shots" and (m := SHOT_LAYER_RE.match(logical)):
                out.add(m.group(1))
    return sorted(out)


def stamp_id_registry(root: Path) -> int:
    """Занести текущие выпущенные id в id_registry.json (append-only union, G7).
    Возвращает число впервые добавленных id. Так сеть безопасности «id не исчезают
    молча» наполняется автоматически при релизе, а не ведётся руками."""
    reg_path = root / ID_REGISTRY_REL
    if reg_path.is_file():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    else:
        reg = {"schema": "id_registry@1", "chapters": [], "scenes": [],
               "characters": [], "vars": [], "assets": []}
    added = 0
    current = _released_ids(root)
    for key, ids in current.items():
        have = set(reg.get(key) or [])
        merged = sorted(have | set(ids))
        added += len(merged) - len(have)
        reg[key] = merged
    reg.setdefault("schema", "id_registry@1")
    if added:
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=1,
                                       sort_keys=True) + "\n", encoding="utf-8")
    return added


# ── Steam-поставка (ADR-0014, ci/steam/README.md) ────────────────────────────

STEAM_PLATFORMS = ("windows", "linux", "mac")
# Форматы, которые launcher distribute реально выдаёт по платформам
# (SDK renpy/common/00build.rpy: package("win","zip") / ("linux","tar.bz2") /
# ("mac","app-zip app-dmg")). Порядок расширений = приоритет: .dmg игнорируем —
# распаковать его кроссплатформенно нельзя, а app-zip несёт то же содержимое.
_DIST_SUFFIX = {
    "windows": ("-win", (".zip",)),
    "linux": ("-linux", (".tar.bz2", ".zip")),
    "mac": ("-mac", (".zip",)),
}


def _find_dist_archive(dist: Path, suffix: str, exts: tuple[str, ...]) -> Path | None:
    for ext in exts:
        found = sorted(dist.glob(f"*{suffix}*{ext}"))
        if found:
            return found[-1]
    return None


def _extract_archive(archive: Path, dest: Path) -> None:
    """zip или tar.bz2 — распаковка по фактическому типу файла."""
    import tarfile
    import zipfile

    if archive.name.endswith(".tar.bz2"):
        with tarfile.open(archive, "r:bz2") as tf:
            tf.extractall(dest)
        return
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)


def _flatten_wrapper_dir(dest: Path) -> None:
    """Убрать каталог-обёртку распакованного артефакта: депот несёт игру В КОРНЕ.

    launcher distribute для zip/tar.bz2 добавляет верхний каталог с именем
    артефакта (SDK distribute.rpy: FORMATS[...] prepend=True -> vn-0.1.5-win/…),
    и без разворачивания путь запуска в Steamworks пришлось бы задавать через
    имя каталога, то есть править руками после каждого бампа версии.

    Разворачивается только однозначный случай: ровно один верхний каталог и
    ничего рядом. Mac-бандл (app-zip идёт БЕЗ обёртки, в корне лежит сам
    VN.app/) не трогаем — поднятие его Contents/ в корень сломало бы приложение.
    """
    entries = list(dest.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        return
    wrapper = entries[0]
    if wrapper.name.endswith(".app"):
        return
    for item in sorted(wrapper.iterdir()):
        target = dest / item.name
        if target.exists():
            raise ReleaseError(
                f"каталог-обёртка {wrapper.name} несёт {item.name} — имя занято, "
                f"содержимое депота не поднять в корень без потери файлов")
        item.rename(target)
    wrapper.rmdir()


def steam_config(project: dict) -> dict:
    """platform.steam из project.yaml; appid обязателен для поставки."""
    cfg = (project.get("platform") or {}).get("steam") or {}
    if not cfg.get("appid"):
        raise ReleaseError(
            "platform.steam.appid не задан в project.yaml — заполните App ID "
            "из Steamworks (публичный, не секрет)")
    return cfg


def steam_app_build(root: Path, flavor: str, branch: str = "") -> tuple[str, list[str]]:
    """Сгенерировать app_build VDF для steamcmd из шаблона ci/steam/.

    Возвращает (текст VDF, предупреждения). Контент депотов ожидается
    распакованным в build/steam/content/<flavor>/<platform>/ (наполняет
    vn release steam из зипов distribute). Credentials здесь не бывает."""
    project = load_project(root)
    cfg = steam_config(project)
    depots = cfg.get("depots") or {}
    if not depots:
        raise ReleaseError(
            "platform.steam.depots пуст — задайте номера депотов по платформам "
            "(project.yaml; номера выдаёт Steamworks)")
    warnings: list[str] = []
    tmpl_path = root / "ci" / "steam" / "app_build.vdf.tmpl"
    if not tmpl_path.is_file():
        raise ReleaseError("нет шаблона ci/steam/app_build.vdf.tmpl")
    depot_blocks: list[str] = []
    for platform in STEAM_PLATFORMS:
        depot_id = depots.get(platform)
        if not depot_id:
            warnings.append(f"депот для {platform} не задан — платформа не уедет")
            continue
        depot_blocks.append(
            '\t\t"%d"\n\t\t{\n\t\t\t"FileMapping"\n\t\t\t{\n'
            '\t\t\t\t"LocalPath" "content/%s/%s/*"\n'
            '\t\t\t\t"DepotPath" "."\n'
            '\t\t\t\t"recursive" "1"\n'
            "\t\t\t}\n\t\t}" % (depot_id, flavor, platform))
    if not depot_blocks:
        raise ReleaseError("ни одного депота с номером — генерировать нечего")
    vdf = tmpl_path.read_text(encoding="utf-8")
    vdf = (vdf.replace("{APPID}", str(cfg["appid"]))
              .replace("{DESC}", f"{project['version']} {flavor}")
              .replace("{BRANCH}", branch)
              .replace("{CONTENT_ROOT}", ".")
              .replace("{BUILD_OUTPUT}", "output")
              .replace("{DEPOTS}", "\n".join(depot_blocks)))
    return vdf, warnings


def steam_stage_content(root: Path, flavor: str, platforms: tuple[str, ...] | None = None
                        ) -> tuple[list[str], list[str]]:
    """Распаковать артефакты distribute в раскладку депотов build/steam/content/.

    Содержимое каждого депота кладётся в КОРЕНЬ своего каталога (каталог-обёртку
    артефакта разворачивает _flatten_wrapper_dir) — путь запуска в Steamworks
    задаётся от корня депота и не должен зависеть от имени артефакта.

    platforms — какие платформы ожидать (по умолчанию те, у которых объявлен
    депот): собирать под все три ради одного депота незачем, а «нет артефакта»
    для неотгружаемой платформы — не ошибка, а шум.
    Возвращает (распакованные платформы, ошибки)."""
    import shutil

    project = load_project(root)
    dist = root / "build" / "dist" / f"{project['version']}-{flavor}"
    staged: list[str] = []
    errors: list[str] = []
    if not dist.is_dir():
        return staged, [f"нет дистрибутива {dist.relative_to(root)} — "
                        f"сначала vn release build --flavor {flavor}"]
    if platforms is None:
        platforms = tuple((steam_config(project).get("depots") or {}).keys())
    for platform in platforms:
        suffix, exts = _DIST_SUFFIX[platform]
        archive = _find_dist_archive(dist, suffix, exts)
        if archive is None:
            errors.append(
                f"{platform}: в {dist.relative_to(root)} нет артефакта "
                f"*{suffix}*{'/'.join(exts)} (соберите vn release build "
                f"--package {suffix.lstrip('-')})")
            continue
        dest = root / "build" / "steam" / "content" / flavor / platform
        if dest.is_dir():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        _extract_archive(archive, dest)
        try:
            _flatten_wrapper_dir(dest)
        except ReleaseError as e:
            errors.append(f"{platform}: {e}")
            continue        # депот с чужой раскладкой хуже отсутствующего
        staged.append(platform)
    return staged, errors


def steam_libs_status(sdk: Path | None) -> list[str]:
    """Каких steam_api-библиотек не хватает в SDK (пустой список = все на месте).
    Без них дистрибутив соберётся, но будет standalone, а не Steam-сборкой."""
    if sdk is None:
        return ["RENPY_SDK не задан — наличие steam_api-библиотек не проверить"]
    need = {
        "py3-windows-x86_64": "steam_api64.dll",
        "py3-linux-x86_64": "libsteam_api.so",
        "py3-mac-universal": "libsteam_api.dylib",
    }
    missing = []
    for libdir, name in need.items():
        if not (sdk / "lib" / libdir / name).is_file():
            missing.append(f"{libdir}/{name}")
    return missing


_SAVE_DIR_RE = re.compile(
    r"""config\.save_directory\s*=\s*["'](?P<dir>[^"']+)["']""")


def steam_preflight(root: Path, flavor: str) -> list[tuple[str, str]]:
    """Готовность к Steam-поставке ДО получения App ID: [(PASS|WARN|FAIL|TODO, строка)].

    Зачем отдельно от steam_app_build. Та команда честно останавливается на пустом
    platform.steam.appid — и владелец не узнаёт, что ещё не готово, пока не завёл
    приложение у Valve. Preflight отвечает на обратный вопрос: «если App ID
    появится сейчас, что останется сделать?». Поэтому пустой appid здесь — не
    провал, а пункт TODO: команда обязана быть полезной именно в этом состоянии.

    Своих правил у preflight нет — он агрегирует существующие проверки конвейера
    (тот же принцип, что у validate_release), плюс печатает данные, которые
    человек переносит в партнёрку руками: имена ачивок и маски Auto-Cloud."""
    from .doctor import sdk_path

    project = load_project(root)
    steam = (project.get("platform") or {}).get("steam") or {}
    checks: list[tuple[str, str]] = []

    appid = steam.get("appid")
    checks.append(("PASS", f"App ID: {appid}") if appid else
                  ("TODO", "App ID: не задан (project.yaml: platform.steam.appid) — "
                           "остался этот шаг; всё остальное ниже проверено"))

    # Депоты: без них поставка не собирается, но до появления приложения их номеров
    # ещё нет — поэтому TODO, а не FAIL (иначе preflight бесполезен «до Valve»).
    depots = {k: v for k, v in (steam.get("depots") or {}).items() if v}
    if not depots:
        checks.append(("TODO", "депоты не заданы (platform.steam.depots) — номера "
                               "выдаёт Steamworks вместе с приложением"))
    elif len(set(depots.values())) != len(depots):
        checks.append(("FAIL", f"депоты повторяются: {depots} — один депот на платформу"))
    else:
        checks.append(("PASS", "депоты: " + ", ".join(f"{k}={v}" for k, v in sorted(depots.items()))))

    sdk = sdk_path()
    missing_libs = steam_libs_status(sdk)
    if sdk is None:
        checks.append(("WARN", "steam_api-библиотеки: RENPY_SDK не задан — проверить нечем"))
    elif missing_libs:
        checks.append(("WARN", f"нет steam_api-библиотек ({', '.join(missing_libs)}) — сборка "
                               f"будет standalone: лаунчер SDK, preferences -> Install Steam Support"))
    else:
        checks.append(("PASS", "steam_api-библиотеки Valve на месте"))

    # Артефакты дистрибутива для объявленных депотов: переиспользуем раскладку,
    # чтобы preflight и фактическая поставка не расходились в трактовке форматов.
    if depots:
        staged, errors = steam_stage_content(root, flavor, platforms=tuple(depots))
        checks.append(("PASS", f"артефакты distribute: {', '.join(staged)}") if not errors else
                      ("WARN", f"артефакты не готовы: {errors[0]} (vn release build)"))

    # Ачивки: API Name в Steamworks обязан совпадать с id ПОБУКВЕННО, маппинга
    # намеренно нет. Печатаем готовый список (с целью прогресса, если объявлена).
    ach_dir = root / "content" / "achievements"
    rows: list[str] = []
    for f in sorted(ach_dir.glob("*.yaml")) if ach_dir.is_dir() else []:
        for aid, spec in sorted((load_yaml(f).get("achievements") or {}).items()):
            goal = (spec or {}).get("goal") or {}
            rows.append(f"{aid} (прогресс до {goal['total']})" if goal.get("total") else aid)
    checks.append(("PASS", f"ачивки для партнёрки ({len(rows)}): {', '.join(rows)}") if rows else
                  ("WARN", "ачивок не объявлено — раздел Achievements в Steamworks не нужен"))

    # DLC: пак без steam_dlc_appid гейтится только установленностью (G9) — это
    # рабочее состояние для DRM-free поставки, но в Steam так пак не продать.
    packs_dir = root / "packs"
    with_dlc, without = [], []
    for d in sorted(p for p in packs_dir.iterdir() if p.is_dir()) if packs_dir.is_dir() else []:
        mf = d / "manifest.yaml"
        if not mf.is_file():
            continue
        (with_dlc if load_yaml(mf).get("steam_dlc_appid") else without).append(d.name)
    if with_dlc:
        checks.append(("PASS", f"паки с DLC App ID: {', '.join(with_dlc)}"))
    if without:
        checks.append(("TODO", f"паки без steam_dlc_appid: {', '.join(without)} — в Steam "
                               f"владение таким паком не проверить (гейт = установленность)"))

    # Auto-Cloud: кода в игре нет (ADR-0014), поэтому единственное, что может
    # проверить сборка, — что путь сейвов стабилен и объявлен явно.
    # Значение берём регексом по строковому литералу: строка в options.rpy несёт
    # хвостовой комментарий («не переименовывать»), и наивный split по = тащил бы
    # его в имя каталога, то есть в маску Auto-Cloud.
    options = root / "game" / "options.rpy"
    save_dir = ""
    if options.is_file():
        m = _SAVE_DIR_RE.search(options.read_text(encoding="utf-8"))
        save_dir = m.group("dir") if m else ""
    checks.append(("PASS", f"Auto-Cloud: корень сейвов {save_dir!r}, маски *.save и "
                           f"persistent (ci/steam/README.md)") if save_dir else
                  ("FAIL", "config.save_directory не задан явно — Auto-Cloud привязать не к чему"))
    return checks


def snapshot_content(root: Path) -> dict:
    chapters: dict[str, dict] = {}
    base = root / "content" / "chapters"
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        m = CHAPTER_DIR_RE.match(d.name)
        if not m:
            continue
        ch_id = f"ch{m.group(1)}"
        meta = load_yaml(d / "chapter.yaml") if (d / "chapter.yaml").is_file() else {}
        scenes = []
        for f in sorted((d / "scenes").glob("*.scene.yaml")) if (d / "scenes").is_dir() else []:
            sm = SCENE_YAML_RE.match(f.name)
            if sm:
                scenes.append(f"{ch_id}_s{sm.group(1)}")
        chapters[ch_id] = {"status": meta.get("status", "draft"), "scenes": scenes}
    return chapters


def update_changelog(root: Path) -> ReleaseReport:
    rep = ReleaseReport()
    project = load_project(root)
    manifest_path = root / MANIFEST_REL
    prev = {}
    if manifest_path.is_file():
        prev = json.loads(manifest_path.read_text(encoding="utf-8")).get("chapters", {})
    cur = snapshot_content(root)

    prev_scenes = {s for ch in prev.values() for s in ch["scenes"]}
    cur_scenes = {s for ch in cur.values() for s in ch["scenes"]}
    rep.added_chapters = sorted(set(cur) - set(prev))
    rep.added_scenes = sorted(cur_scenes - prev_scenes)
    rep.removed_scenes = sorted(prev_scenes - cur_scenes)
    rep.changed = bool(rep.added_chapters or rep.added_scenes or rep.removed_scenes)

    if rep.changed:
        lines = [f"## {project['version']}", ""]
        if rep.added_chapters:
            lines.append("Новые главы: " + ", ".join(rep.added_chapters))
        if rep.added_scenes:
            lines.append(f"Новые сцены ({len(rep.added_scenes)}): " + ", ".join(rep.added_scenes))
        if rep.removed_scenes:
            lines.append("Удалены сцены (см. renames.yaml): " + ", ".join(rep.removed_scenes))
        lines.append("")
        changelog = root / "docs" / "CHANGELOG.md"
        old = changelog.read_text(encoding="utf-8") if changelog.is_file() else "# Changelog\n\n"
        head, _, tail = old.partition("\n")
        changelog.write_text(head + "\n\n" + "\n".join(lines) + tail.lstrip("\n"),
                             encoding="utf-8")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(
        {"schema": "release_manifest@1", "version": project["version"], "chapters": cur},
        ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # Автоштамп реестра выпущенных id (G7): сеть безопасности наполняется сама.
    rep.stamped = stamp_id_registry(root)
    return rep


# ── Флейворы и build-info (ADR-0006) ──────────────────────────────────────────

def flavor_config(project: dict, name: str) -> dict:
    flavors = project.get("flavors") or {}
    if name not in flavors:
        raise ReleaseError(f"флейвор {name!r} не описан в project.yaml "
                           f"(есть: {', '.join(sorted(flavors)) or 'ни одного'})")
    return flavors[name]


# Строгость гейта по статусу главы (G15). draft ослабляет граф-проверки конвейера
# до warnings: ненаписанная ветка в такой главе легальна и у игрока станет «сцена
# недоступна» — публичной сборке это не подходит. playtest проходит ровно те же
# строгие проверки, что release, и отличается только подписью выпускающего.
_MATURITY_STATE = {"draft": "FAIL", "playtest": "WARN"}


def early_content_checks(root: Path, cfg: dict) -> list[tuple[str, str]]:
    """Зрелость контента для флейвора: [(PASS|WARN|FAIL, строка)] в форме гейта.

    early_content — не декоративная запись: скрипты глав уезжают в дистрибутив
    всегда (гейт логический, G9) и открываются из реестра, а тихо выкинуть главу
    из сборки нельзя — сейв игрока мог уже на неё сослаться. Поэтому «раннего
    контента в этом флейворе нет» проверяется здесь, до сборки, а не исполняется
    вырезанием контента. Незнакомый статус трактуется как draft (fail-closed)."""
    if cfg.get("early_content", False):
        return [("PASS", "early_content=true: незрелые главы для этого флейвора штатны")]
    by_status: dict[str, list[str]] = {}
    released = 0
    for ch_id, info in sorted(snapshot_content(root).items()):
        if info["status"] == "release":
            released += 1
        else:
            by_status.setdefault(info["status"], []).append(ch_id)
    if not by_status:
        return [("PASS", "зрелость контента: все главы сборки status=release")]
    # Пока в проекте нет НИ ОДНОЙ release-главы, требование «в публичном
    # флейворе только зрелые главы» невыполнимо: гейт запретил бы собрать
    # что угодно, включая демо. Невыполнимый гейт учит игнорировать гейты,
    # поэтому до первой зрелой главы это предупреждение, а не отказ. С момента
    # появления первой release-главы норма включается сама — специально
    # заводить флаг и помнить о нём не нужно.
    if not released:
        return [("WARN",
                 "зрелость контента: ни одна глава ещё не доведена до "
                 f"status=release ({', '.join(sorted(sum(by_status.values(), [])))}) — "
                 f"флейвор с early_content=false собирается, но гейт станет "
                 f"строгим с первой release-главой")]
    return [(_MATURITY_STATE.get(status, "FAIL"),
             f"early_content=false, а в сборке главы status={status}: "
             f"{', '.join(ids)} — доведите до release или собирайте флейвором "
             f"с early_content=true")
            for status, ids in sorted(by_status.items())]


def nsfw_exclude_globs(root: Path) -> list[str]:
    """Глобы classify для SFW-флейворов: конвенция — NSFW-ассеты живут в
    подпапке nsfw/ своей категории (assets/cg/nsfw/**, assets/mov/nsfw/** …).
    Глобы считаются от фактических каталогов, без опоры на поддержку ** движком
    в середине пути."""
    globs: list[str] = []
    assets = root / "game" / "assets"
    if assets.is_dir():
        for cat in sorted(p for p in assets.iterdir() if p.is_dir()):
            if (cat / "nsfw").is_dir():
                globs.append(f"game/assets/{cat.name}/nsfw/**")
    return globs


def patron_tag(token: str | None) -> str | None:
    """Короткая НЕвосстановимая метка patron-сборки: blake2s(токен), 8 hex.

    Сам токен в дистрибутив класть нельзя: game/build_id.json уезжает игроку
    целиком (build.classify его не исключает — он нужен игре в рантайме), а в CI
    в него подставляется секрет secrets.PATRON_TOKEN. До build_info@2 туда писался
    токен как есть — то есть секрет раздавался всем получателям сборки.

    Вотермарке нужна не подлинность токена, а различимость сборок. Метка
    детерминирована, поэтому владелец сопоставляет утёкшую сборку с получателем,
    пересчитав тег из своего токена:

        python -c "import hashlib,sys; print(hashlib.blake2s(sys.argv[1].encode(),
                   digest_size=4, person=b'vnpatron').hexdigest())" <токен>

    Ограничение: короткий низкоэнтропийный токен подбирается перебором по тегу.
    Токен-метку получателя генерируйте случайной (например secrets.token_hex(16)).
    """
    if not token:
        return None
    return hashlib.blake2s(token.encode("utf-8"), digest_size=4,
                           person=b"vnpatron").hexdigest()


def compute_build_info(root: Path, flavor: str, patron_token: str | None = None,
                       now: datetime | None = None) -> dict:
    """Документ build_info@2: идентичность сборки + список исключений distribute.
    Скрипты паков грузятся всегда (G9) — файлы сцен не исключаются, гейт
    логический (vn_build/pack_registry); исключаются только NSFW-ассеты.

    На вход берётся сам токен, наружу уходит только производная метка (patron_tag):
    документ целиком уезжает игроку внутри дистрибутива."""
    project = load_project(root)
    cfg = flavor_config(project, flavor)
    sha = git_sha(root)
    now = now or datetime.now(timezone.utc)
    return {
        "schema": "build_info@2",
        "flavor": flavor,
        "version": project["version"],
        "build_id": f"{project['version']}+{sha}.{flavor}.{now.strftime('%Y%m%d%H%M')}",
        "sha": sha,
        "built_at": now.isoformat(timespec="seconds"),
        "packs": sorted(cfg.get("packs") or []),
        "nsfw": bool(cfg.get("nsfw")),
        "early_content": bool(cfg.get("early_content", False)),
        "watermark": bool(cfg.get("watermark", False)),
        "patron_tag": patron_tag(patron_token),
        "exclude": [] if cfg.get("nsfw") else nsfw_exclude_globs(root),
    }


def write_build_info(root: Path, info: dict) -> Path:
    from .schemas import SchemaRegistry

    errors = SchemaRegistry(root / "tools" / "schemas").validate(info, BUILD_INFO_REL)
    if errors:
        raise ReleaseError("build-info не проходит схему:\n  " + "\n  ".join(errors))
    path = root / BUILD_INFO_REL
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def clear_build_info(root: Path) -> None:
    (root / BUILD_INFO_REL).unlink(missing_ok=True)


# ── Релизный гейт: vn release validate --flavor <id> ─────────────────────────

def validate_release(root: Path, flavor: str) -> tuple[list[tuple[str, str]], bool]:
    """Полная предрелизная проверка. Возвращает ([(PASS|WARN|FAIL, строка)], ok).
    Здесь агрегируются существующие проверки конвейера — своих правил у релиза
    нет, чтобы гейт не расходился с vn build."""
    checks: list[tuple[str, str]] = []
    ok = True

    def add(state: str, msg: str):
        nonlocal ok
        if state == "FAIL":
            ok = False
        checks.append((state, msg))

    from .schemas import SchemaRegistry

    project = load_project(root)
    registry = SchemaRegistry(root / "tools" / "schemas")
    p_errs = registry.validate(project, "project.yaml")
    add("FAIL" if p_errs else "PASS",
        "project.yaml: " + ("; ".join(p_errs) if p_errs else "схема валидна"))

    try:
        cfg = flavor_config(project, flavor)
        add("PASS", f"флейвор {flavor}: packs={cfg.get('packs') or []}, "
                    f"nsfw={cfg.get('nsfw')}, early={cfg.get('early_content', False)}")
    except ReleaseError as e:
        add("FAIL", str(e))
        return checks, False

    for pid in cfg.get("packs") or []:
        mf = root / "packs" / pid / "manifest.yaml"
        add("PASS" if mf.is_file() else "FAIL",
            f"пак {pid}: " + ("manifest.yaml на месте" if mf.is_file()
                              else f"нет packs/{pid}/manifest.yaml"))

    for state, msg in early_content_checks(root, cfg):
        add(state, msg)

    from .content.lint import lint

    rep = lint(root)
    add("FAIL" if rep.errors else "PASS",
        f"lint: {len(rep.errors)} ошибок, {len(rep.warnings)} предупреждений")

    # Шрифты — не производная зона: если чекаут пришёл без LFS-объектов, в
    # дистрибутив уедут указатели и игра упадёт FreetypeError на первом же
    # экране. Гейт обязан ловить это ЗДЕСЬ: конфигурация CI может разъехаться,
    # а артефакт обязан оставаться рабочим.
    from .doctor import _lfs_pointer_fonts

    bad_fonts, n_fonts = _lfs_pointer_fonts(root)
    if not n_fonts:
        add("WARN", "шрифты UI: game/fonts пуст — UI будет на системном шрифте")
    else:
        add("FAIL" if bad_fonts else "PASS",
            f"шрифты UI: {n_fonts - len(bad_fonts)}/{n_fonts} материализованы"
            + (f" — УКАЗАТЕЛИ LFS: {', '.join(bad_fonts)}; "
               f"checkout без lfs:true даст падающую сборку" if bad_fonts else ""))

    from .assets.pipeline import build_assets

    ares = build_assets(root, check=True)
    n_bad = len(ares.errors) + len(ares.stale)
    add("FAIL" if n_bad else "PASS",
        "ассеты: " + ("свежи" if not n_bad else
                      f"{len(ares.errors)} ошибок, {len(ares.stale)} несвежих (vn build)"))

    from .assets import video as videomod

    file_budget = (project.get("budgets") or {}).get("video_file_mb")
    v_errors, v_warnings = videomod.validate_all(root, file_budget_mb=file_budget)
    if v_errors:
        add("FAIL", f"видео: {len(v_errors)} ошибок — {v_errors[0]}")
    elif v_warnings:
        add("WARN", f"видео: {len(v_warnings)} предупреждений — {v_warnings[0]}")
    else:
        add("PASS", "видео: собранные лупы валидны")

    from .content.compile import CompileError, compile_content

    try:
        cres = compile_content(root, check=True)
        add("FAIL" if cres.stale else "PASS",
            "генерат: " + ("свеж" if not cres.stale
                           else f"{len(cres.stale)} несвежих (vn build)"))
    except CompileError as e:
        add("FAIL", f"генерат: {e}")

    b_failures = budget_failures(root)
    add("FAIL" if b_failures else "PASS",
        "бюджеты G19: " + ("в рамках" if not b_failures else "; ".join(b_failures)))

    from .assets.provenance import verify as prov_verify

    prep = prov_verify(root)
    if prep.errors:
        add("FAIL", f"провенанс: {len(prep.errors)} ошибок — {prep.errors[0]}")
    elif prep.warnings:
        add("WARN", f"провенанс: {len(prep.warnings)} предупреждений")
    else:
        add("PASS", f"провенанс: {len(prep.checked)} цепочек согласованы")

    from .assets.daz import validate_renders

    drep = validate_renders(root, write_provenance=False)
    if drep.errors:
        add("FAIL", f"DAZ-декларации: {len(drep.errors)} ошибок — {drep.errors[0]}")
    elif drep.warnings:
        add("WARN", f"DAZ-декларации: {len(drep.warnings)} предупреждений "
                    f"(неотрендеренные выходы)")
    else:
        add("PASS", f"DAZ-декларации: {len(drep.checked)} проверено")

    from .assets.vam import validate_scenes

    vrep = validate_scenes(root, write_provenance=False)
    if vrep.errors:
        add("FAIL", f"VaM-декларации: {len(vrep.errors)} ошибок — {vrep.errors[0]}")
    elif vrep.warnings:
        add("WARN", f"VaM-декларации: {len(vrep.warnings)} предупреждений "
                    f"(незахваченные выходы)")
    else:
        add("PASS", f"VaM-декларации: {len(vrep.checked)} проверено")

    from .assets import sims4 as sims4mod

    srep = sims4mod.validate_scenes(root, write_provenance=False)
    if srep.errors:
        add("FAIL", f"Sims4-декларации: {len(srep.errors)} ошибок — {srep.errors[0]}")
    elif srep.warnings:
        add("WARN", f"Sims4-декларации: {len(srep.warnings)} предупреждений "
                    f"(незахваченные выходы)")
    else:
        add("PASS", f"Sims4-декларации: {len(srep.checked)} проверено")

    # Покрытие переводов (loc.yaml: release_coverage_min): недопереведённый язык
    # молча откатывается на исходник — на витрине это «English»-билд наполовину
    # на русском. Порог был объявлен, но нигде не форсировался.
    from .loc.po import LocError, report as loc_report

    try:
        cov = loc_report(root).coverage
        threshold = float((load_yaml(root / "loc" / "loc.yaml") or {})
                          .get("release_coverage_min", 0) or 0)
    except (LocError, OSError):
        cov, threshold = {}, 0.0
    if cov and threshold:
        weak = []
        for lang, c in sorted(cov.items()):
            if (root / "game" / "tl" / lang / "language.json").is_file():
                import json as _json
                meta = _json.loads((root / "game" / "tl" / lang / "language.json")
                                   .read_text(encoding="utf-8"))
                if meta.get("synthetic"):
                    continue        # pseudo — QA-инструмент, в поставку не идёт
            pct = (c["translated"] / c["total"]) if c["total"] else 1.0
            if pct < threshold:
                weak.append(f"{lang} {pct:.0%}")
        add("FAIL" if weak else "PASS",
            "покрытие переводов: " + (
                f"ниже порога {threshold:.0%} — {', '.join(weak)}" if weak
                else f"все языки ≥ {threshold:.0%}"))

    # Озвучка (§4.9/C5): структурные поломки и дыры в озвученных главах = FAIL
    # (реплика без дубля посреди озвученной главы слышна игроку как обрыв),
    # драфты (TTS/черновые дубли) = WARN — играбельно, но не релизное качество.
    from .voice import validate as voice_validate

    vo = voice_validate(root)
    if vo.errors:
        add("FAIL", f"озвучка: {len(vo.errors)} ошибок — {vo.errors[0]}")
    elif vo.holes:
        add("FAIL", f"озвучка: {len(vo.holes)} непокрытых реплик в озвученных "
                    f"главах — {vo.holes[0]} (vn voice validate --report)")
    elif vo.drafts:
        add("WARN", f"озвучка: {len(vo.drafts)} черновых дублей (draft) — "
                    f"{vo.drafts[0]}")
    elif vo.coverage:
        add("PASS", f"озвучка: {len(vo.coverage)} шардов глава×язык покрыты полностью")

    from .assets.licenses import validate_licenses

    lrep = validate_licenses(root)
    if lrep.errors:
        add("FAIL", f"лицензии ассетов: {len(lrep.errors)} нарушений — {lrep.errors[0]}")
    elif lrep.warnings:
        add("WARN", f"лицензии ассетов: {lrep.warnings[0]}")
    elif lrep.declarations:
        add("PASS", f"лицензии ассетов: {lrep.declarations} деклараций покрыты "
                    f"реестром ({lrep.entries} записей)")

    from .assets.storage import StorageError, status

    try:
        srep = status(root)
        dirty = [r for r in srep.rows if "ИЗМЕНЁН локально" in r]
        if srep.errors:
            add("FAIL", f"хранилище сырцов: {srep.errors[0]}")
        elif dirty:
            add("FAIL", f"сырцы изменены, но не запушены ({len(dirty)}): {dirty[0]} — "
                        f"провенанс релиза обязан ссылаться на хранилище (G14)")
        else:
            add("PASS", "хранилище сырцов: локальные копии согласованы")
    except StorageError as e:
        add("WARN", f"хранилище сырцов недоступно: {e}")

    manifest_path = root / MANIFEST_REL
    if manifest_path.is_file():
        m_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
        add("PASS" if m_version == project["version"] else "WARN",
            f"release-manifest: версия {m_version} "
            + ("== project.yaml" if m_version == project["version"]
               else f"!= {project['version']} — прогоните vn release changelog"))
    else:
        add("WARN", "ci/release-manifest.json нет — прогоните vn release changelog")

    sha = git_sha(root)
    add("WARN" if sha == "nogit" else "PASS", f"git sha: {sha}")

    fixtures = list((root / "ci" / "fixtures" / "saves").glob("*.save"))
    add("PASS" if fixtures else "WARN",
        f"сейв-корпус: {len(fixtures)} фикстур" + ("" if fixtures else
        " — создайте (vn save corpus --add) до релиза, иначе совместимость "
        "сейвов не проверена"))

    return checks, ok
