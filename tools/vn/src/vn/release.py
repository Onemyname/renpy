"""vn release — манифест релиза, changelog, флейворы и релизный гейт (раздел 7/1.9,
ADR-0006): версии контента считаются по фактическому диффу реестров, а не по
ручным пометкам («их забывают»); флейворы (public/patron) описаны в project.yaml
и материализуются в game/build_id.json только на время distribute."""

from __future__ import annotations

import json
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
        return {"chapters": [], "scenes": [], "characters": [], "vars": []}
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
    return {"chapters": chapters, "scenes": scenes,
            "characters": chars, "vars": variables}


def stamp_id_registry(root: Path) -> int:
    """Занести текущие выпущенные id в id_registry.json (append-only union, G7).
    Возвращает число впервые добавленных id. Так сеть безопасности «id не исчезают
    молча» наполняется автоматически при релизе, а не ведётся руками."""
    reg_path = root / ID_REGISTRY_REL
    if reg_path.is_file():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    else:
        reg = {"schema": "id_registry@1", "chapters": [], "scenes": [],
               "characters": [], "vars": []}
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


def compute_build_info(root: Path, flavor: str, patron_token: str | None = None,
                       now: datetime | None = None) -> dict:
    """Документ build_info@1: идентичность сборки + список исключений distribute.
    Скрипты паков грузятся всегда (G9) — файлы сцен не исключаются, гейт
    логический (vn_build/pack_registry); исключаются только NSFW-ассеты."""
    project = load_project(root)
    cfg = flavor_config(project, flavor)
    sha = git_sha(root)
    now = now or datetime.now(timezone.utc)
    return {
        "schema": "build_info@1",
        "flavor": flavor,
        "version": project["version"],
        "build_id": f"{project['version']}+{sha}.{flavor}.{now.strftime('%Y%m%d%H%M')}",
        "sha": sha,
        "built_at": now.isoformat(timespec="seconds"),
        "packs": sorted(cfg.get("packs") or []),
        "nsfw": bool(cfg.get("nsfw")),
        "early_content": bool(cfg.get("early_content", False)),
        "watermark": bool(cfg.get("watermark", False)),
        "patron_token": patron_token,
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
    elif vrep.checked:
        add("PASS", f"VaM-декларации: {len(vrep.checked)} проверено")

    from .assets import sims4 as sims4mod

    srep = sims4mod.validate_scenes(root, write_provenance=False)
    if srep.errors:
        add("FAIL", f"Sims4-декларации: {len(srep.errors)} ошибок — {srep.errors[0]}")
    elif srep.warnings:
        add("WARN", f"Sims4-декларации: {len(srep.warnings)} предупреждений "
                    f"(незахваченные выходы)")
    elif srep.checked:
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
