"""vn — единая точка входа (G1). Домены (C13): bootstrap, doctor, dev, build, play,
package, assets, content, scene, chapter, char, loc, voice, save, test, release
(в т.ч. release android — мобильный канал), pack, pipeline.

Нереализованное — честные заглушки с номером фазы (раздел 8 ARCHITECTURE.md) и кодом
выхода 3, а не тихие no-op. Сейчас заглушка ровно одна: save migrate (фаза 3).
Источник истины по заглушкам — EXPECTED_STUBS в tests/test_cli.py (сверяется с деревом
команд тестом test_stub_inventory_matches_frozen_list, а не этой шапкой). Выведенное
из нормы не возвращается и сторожится отдельно, test_retired_commands_stay_retired:
домены validate|migrate|shell — ADR-0017, vn test perf — ADR-0019.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click

from . import __version__
from .repo import RepoError, find_root, write_text_lf

# Сколько примеров ОДНОГО класса предупреждений печатать, прежде чем свернуть
# остаток в «ещё N однотипных». Предупреждения вида «одно на главу» или «одно на
# CG» растут линейно с контентом: на корпусе 8 000 образов это 8 000 строк, в
# которых тонет всё остальное (измерено vn test corpus). Пять — чтобы по примерам
# был виден паттерн (какие именно главы и файлы), но класс занимал единицы строк.
# Сворачивается только ПЕЧАТЬ: в отчётах предупреждения остаются полными — их
# читают тесты, release-гейт и другие команды.
WARN_SAMPLES = 5

# Что в тексте предупреждения отличает один случай от другого (а не один класс
# проверок от другого): закавыченные значения, пути и любой токен с цифрой — id
# главы ch07, сцены s030, размеры, числа. Класс — текст с вымаранными значениями:
# «ch01: title_key … нет в strings.yaml» и то же про ch02 сворачиваются в один
# класс, а разные проверки не сливаются, потому что различаются словами.
_WARN_VALUE_RE = re.compile(r"""'[^']*'|"[^"]*"|\S*[\\/]\S*|\S*\d\S*""")


def _utf8_stdio() -> None:
    """Консоль/пайп Windows по умолчанию в locale-кодировке (cp1251): без этого
    русские сообщения — кракозябры, а '✓' в doctor — UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# Зовётся на импорте, а не только из callback группы: click печатает --help на
# этапе разбора аргументов, ДО вызова callback, поэтому справка (первое, что видит
# новый человек) выходила кракозябрами. Точка входа консольного скрипта —
# vn.cli:main, то есть импорт этого модуля гарантированно происходит раньше разбора.
_utf8_stdio()


def _fail(msg: str) -> "None":
    click.secho(f"ошибка: {msg}", fg="red", err=True)
    sys.exit(1)


def _warn_kind(text: str) -> str:
    return _WARN_VALUE_RE.sub("*", text)


def _echo_warnings(warnings, prefix: str = "warning") -> None:
    """Напечатать предупреждения, свернув однотипные (WARN_SAMPLES).

    Классы идут в порядке первого появления, внутри класса — в исходном порядке:
    пока однотипных мало, вывод совпадает с несгруппированным.
    """
    groups: dict[str, list[str]] = {}
    for w in warnings:
        groups.setdefault(_warn_kind(str(w)), []).append(str(w))
    for group in groups.values():
        for w in group[:WARN_SAMPLES]:
            click.secho(f"{prefix}: {w}", fg="yellow")
        if len(group) > WARN_SAMPLES:
            click.secho(f"{prefix}: ещё {len(group) - WARN_SAMPLES} однотипных "
                        f"(всего {len(group)})", fg="yellow")


def _root() -> Path:
    try:
        return find_root()
    except RepoError as e:
        _fail(str(e))


def _stub(phase: int):
    def cmd(*args, **kwargs):
        click.secho(f"эта команда появится в фазе {phase} (раздел 8 ARCHITECTURE.md)", fg="yellow")
        sys.exit(3)   # 3 = «не реализовано в этой фазе»; 2 занят click за usage error
    # Метка для сверки с докой: перечень заглушек называется в docs/handbook/25-custom-engine.md,
    # и без машинной сверки он расходится с кодом при первой же реализованной команде.
    cmd.vn_stub_phase = phase
    return cmd


@click.group()
@click.version_option(__version__, prog_name="vn")
def main():
    """Единственный CLI проекта (ARCHITECTURE.md, G1).

    Exit-коды: 0 — успех; 1 — ошибка проверки/сборки; 2 — usage error; 3 — команда
    ещё не реализована (номер фазы в сообщении).
    """
    # Повторно (кроме импорта модуля): поток мог быть подменён после импорта —
    # так работает CliRunner в тестах и вызов main() из чужого процесса.
    _utf8_stdio()


# ── Верхний уровень ───────────────────────────────────────────────────────────

@main.command()
def doctor():
    """Самодиагностика окружения."""
    from .doctor import run_doctor
    sys.exit(run_doctor())


def _assets_build(root, profile: str, only_transforms: set[str] | None = None):
    from .assets.pipeline import build_assets

    res = build_assets(root, profile=profile, only_transforms=only_transforms)
    _echo_warnings(res.warnings)
    # Пропущенный вариант — не ошибка (мастер мал), но и не мелочь: игрок на 4K
    # останется на растянутом 1080p. Молчать об этом нельзя.
    _echo_warnings(res.skipped_variants, prefix="вариант пропущен")
    if res.errors:
        for e in res.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"assets: {len(res.errors)} ошибок")
    click.echo(
        f"assets: {len(res.built)} собрано, {len(res.from_cache)} из кэша, "
        f"{len(res.fresh)} актуально, {len(res.deleted)} осиротевших удалено"
    )
    return res


@main.command()
@click.option("--check", is_flag=True, help="Проверить без записи: свеж ли генерат (CI-режим, G1).")
@click.option("--profile", type=click.Choice(["full", "draft"]), default="full",
              help="Профиль энкода ассетов (draft — быстрый, для локальной итерации).")
@click.option("--use-artifact", "artifact_ref", metavar="REF",
              help="АВАРИЙНЫЙ путь (G4): не собирать, а взять генерат из артефакта "
                   "зелёного прогона CI на этом коммите (ветка/тег/sha). Требует gh CLI.")
def build(check: bool, profile: str, artifact_ref: str | None = None):
    """Схемы -> lint -> сборка ассетов -> компиляция контента в game/generated/."""
    from .content.compile import CompileError, compile_content
    from .content.lint import lint

    root = _root()
    if artifact_ref:
        # Аварийный режим не собирает НИЧЕГО: он существует ровно для случая
        # «компилятор сломан, а играть и писать текст надо сейчас». Поэтому ни
        # lint, ни ассеты здесь не запускаются — иначе он падал бы на том же, из-за
        # чего его вызвали.
        if check:
            _fail("--use-artifact и --check несовместимы: первый ПИШЕТ генерат, "
                  "второй обязан ничего не писать (G1)")
        from .artifact import ArtifactError, head_mismatch, use_artifact

        try:
            info = use_artifact(root, artifact_ref)
        except ArtifactError as e:
            _fail(str(e))
        drift = head_mismatch(root, info.sha)
        if drift:
            click.secho(f"warning: {drift}", fg="yellow")
        click.secho(f"генерат из артефакта: {info.outputs} выходов, {info.rpyc} .rpyc "
                    f"(коммит {info.sha[:12]}, прогон {info.run_id}, собран vn "
                    f"{info.tool})", fg="green")
        click.secho("это ЧУЖОЙ генерат: vn build --check и vn content compile --check "
                    "будут красными до локальной сборки — так и задумано (G4)",
                    fg="yellow")
        return
    rep = lint(root)
    _echo_warnings(rep.warnings)
    if not rep.ok:
        for e in rep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"lint: {len(rep.errors)} ошибок — сборка остановлена")
    if check:
        from .assets.pipeline import build_assets

        ares = build_assets(root, check=True)
        if ares.errors:
            for e in ares.errors:
                click.secho(f"error: {e}", fg="red")
            _fail(f"assets: {len(ares.errors)} ошибок")
        if ares.stale:
            for rel in ares.stale:
                click.secho(f"устарело: assets/{rel}", fg="red")
            _fail("game/assets не свеж — выполните vn build")
    else:
        _assets_build(root, profile)
    try:
        res = compile_content(root, check=check)
    except CompileError as e:
        _fail(str(e))
    except Exception as e:
        # Контракт CLI: exit 1 всегда сопровождается сообщением, не голым трейсбеком.
        import traceback
        _fail(f"внутренняя ошибка компилятора: {type(e).__name__}: {e}\n"
              + traceback.format_exc(limit=3))
    _echo_warnings(res.warnings)
    if check:
        if res.stale:
            for rel in res.stale:
                click.secho(f"устарело: {rel}", fg="red")
            _fail("генерат не свеж — выполните vn build")
        # Разметка переводов (read-only): полный build упал бы на импорте tl —
        # check обязан ловить то же самое до мержа
        from .loc.po import LocError, validate_translations
        try:
            po_errors = validate_translations(root)
        except LocError as e:
            _fail(str(e))
        if po_errors:
            for e in po_errors:
                click.secho(f"error: {e}", fg="red")
            _fail(f"переводы: {len(po_errors)} ошибок разметки")
        _check_budgets(root)    # бюджеты G19 проверяются и в CI-режиме
        click.secho("check: генерат свеж", fg="green")
        return
    click.echo(
        f"generated: {len(res.written)} записано, {len(res.skipped)} без изменений, "
        f"{len(res.deleted)} осиротевших удалено"
    )
    # game/tl генерируется и НЕ в git: без импорта здесь релиз (vn package -> build)
    # уехал бы без переводов — сборка обязана оставлять tl свежим.
    _loc_import(root)
    _check_budgets(root)
    click.secho("build: OK", fg="green")


def _loc_import(root: Path):
    """Регенерация game/tl из loc/po (часть сборки: tl — производная зона)."""
    from .loc.po import LocError, import_translations

    try:
        lrep = import_translations(root)
    except LocError as e:
        _fail(str(e))
    if lrep.errors:
        for e in lrep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"loc import: {len(lrep.errors)} ошибок разметки переводов")
    if lrep.changed:
        click.echo(f"tl: {len(lrep.changed)} файлов обновлено")


def _check_budgets(root: Path):
    """Размер-бюджеты (G19) + бюджет памяти сцены (ADR-0012).

    Размерные бюджеты — предохранители от сломавшейся сборки. Реальный потолок
    производства — кэш образов: его переполнение не роняет игру, а превращает её
    в фризы, поэтому проверяется здесь же и так же жёстко."""
    from .assets.memory import analyze
    from .release import budget_failures

    failures = budget_failures(root)
    if failures:
        for f in failures:
            click.secho(f"бюджет: {f}", fg="red")
        _fail("бюджеты G19 превышены (project.yaml: budgets)")

    mem = analyze(root)
    _echo_warnings(mem.warnings)
    if mem.errors:
        for e in mem.errors:
            click.secho(f"память: {e}", fg="red")
        _fail("бюджет памяти сцены превышен (project.yaml: render.image_cache_mb)")
    if mem.worst:
        click.echo(
            f"память: худшая сцена {mem.worst.scene_id} — "
            f"{mem.worst.px / 1e6:.1f} Мпикс из {mem.budget_px / 1e6:.1f} "
            f"(масштаб @{mem.scale})")


@main.command()
def play():
    """Запуск игры через Ren'Py SDK (RENPY_SDK)."""
    from .doctor import sdk_path

    root = _root()
    sdk = sdk_path()
    if sdk is None:
        _fail("Ren'Py SDK не найден: скачайте с renpy.org и установите RENPY_SDK (vn doctor подскажет)")
    if not (root / "game" / "generated" / "manifest.json").is_file():
        _fail("game/generated/ пуст — сначала vn build")
    if sys.platform == "win32":
        exe = sdk / "renpy.exe"
        cmd = [str(exe), str(root)]
    else:
        cmd = [str(sdk / "renpy.sh"), str(root)]
    sys.exit(subprocess.run(cmd).returncode)


@main.command()
def bootstrap():
    """Подготовить чекаут к запуску: диагностика + сборка ассетов и генерата.

    Фаза 1: сборка локальная (источники в git). Скачивание из remote cache /
    CI-артефактов (G4) подключится вместе с командной инфраструктурой."""
    from .content.compile import CompileError, compile_content
    from .doctor import run_doctor

    root = _root()
    if run_doctor() != 0:
        _fail("bootstrap остановлен: почините окружение по рецептам vn doctor")
    _assets_build(root, "full")
    try:
        res = compile_content(root)
    except CompileError as e:
        _fail(str(e))
    _echo_warnings(res.warnings)
    _loc_import(root)    # game/tl не в git — чекаут без импорта был бы без переводов
    click.secho("bootstrap: OK — запускайте vn play", fg="green")


@main.command()
def dev():
    """Цикл разработчика: watch по content/ и assets_src/ + запущенная игра.

    Правки пересобираются автоматически; в игре — Shift+R для перезагрузки
    (замена пикселей подхватывается по месту, структурные правки могут сбросить позицию)."""
    import subprocess
    import threading

    from .content.compile import CompileError, compile_content
    from .devloop import watch
    from .doctor import sdk_path

    root = _root()
    sdk = sdk_path()
    if sdk is None:
        _fail("Ren'Py SDK не найден (RENPY_SDK) — vn doctor подскажет")

    def rebuild_assets():
        click.secho("assets_src изменился — пересборка (draft-профиль)…", fg="cyan")
        try:
            _assets_build(root, "draft")
            compile_content(root)   # реестр образов зависит от собранных ассетов
            click.secho("готово — Shift+R в игре", fg="green")
        except SystemExit:
            pass
        except CompileError as e:
            click.secho(f"компилятор: {e}", fg="red")

    def rebuild_content():
        click.secho("content изменился — компиляция…", fg="cyan")
        try:
            res = compile_content(root)
            _echo_warnings(res.warnings)
            click.secho("готово — Shift+R в игре", fg="green")
        except CompileError as e:
            click.secho(f"компилятор: {e}", fg="red")

    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    game = subprocess.Popen([str(exe), str(root)])
    click.secho("игра запущена; watch активен (Ctrl+C или закройте игру для выхода)", fg="green")
    watcher = threading.Thread(
        target=watch, args=(root, rebuild_assets, rebuild_content),
        kwargs={"stop_check": lambda: game.poll() is not None}, daemon=True,
    )
    watcher.start()
    try:
        game.wait()
    except KeyboardInterrupt:
        game.terminate()
    watcher.join(timeout=3)


@main.command()
@click.option("--package", "packages", multiple=True, default=("win",),
              help="Целевые пакеты launcher distribute (win/linux/mac/market).")
@click.option("--timeout", "timeout_s", default=900)
@click.option("--dest-suffix", "dest_suffix", default="", hidden=True,
              help="Суффикс каталога dist (vn release build добавляет -<flavor>).")
def package(packages: tuple, timeout_s: int, dest_suffix: str = ""):
    """Дистрибутивы через launcher distribute + перенос .rpyc между релизами (G6)."""
    import shutil

    from .doctor import sdk_path
    from .release import rpyc_cache_lane, rpyc_lane_frozen
    from .repo import load_project

    root = _root()
    sdk = sdk_path()
    if sdk is None:
        _fail("Ren'Py SDK не найден (RENPY_SDK)")
    project = load_project(root)
    version = project["version"]

    # 1) Полная сборка: генерат (.rpy) должен существовать ДО восстановления .rpyc
    ctx = click.get_current_context()
    ctx.invoke(build, check=False, profile="full")

    # 2) Перенос .rpyc прошлого релиза (G6): кэш релиза — КАНОНИЧЕСКИЙ носитель
    # statement-имён, локальные .rpyc таковым не являются -> восстановление
    # С ПЕРЕЗАПИСЬЮ; движок при перекомпиляции изменённых .rpy перенесёт имена.
    # Кэш покрывает весь game/ (framework-метки тоже попадают в сейвы/rollback).
    lane, caches, legacy = rpyc_cache_lane(root, dest_suffix)
    if legacy:
        click.secho(f"rpyc-перенос: линии {lane.name} нет, взята старая раскладка "
                    f"ci/rpyc-cache/{caches[-1].name} (до разделения по флейворам) — "
                    f"эта сборка запишет линию", fg="yellow")
    if caches:
        latest = caches[-1]
        restored = 0
        for rpyc in latest.rglob("*.rpyc"):
            rel = rpyc.relative_to(latest)
            target = root / "game" / rel
            if not target.with_suffix(".rpy").is_file():
                # legacy-раскладка кэша (относительно game/generated/)
                target = root / "game" / "generated" / rel
            if target.with_suffix(".rpy").is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(rpyc, target)
                restored += 1
        if restored == 0:
            _fail(f"rpyc-перенос: кэш {latest.name} есть, но не восстановлено ни одного "
                  f".rpyc — save-совместимость под угрозой (G6), сборка остановлена")
        click.echo(f"rpyc-перенос: {restored} файлов из релиза {latest.name} (G6, с перезаписью)")
    else:
        click.echo("rpyc-перенос: кэша прошлых релизов нет (первый релиз)")

    # 3) Компиляция движком (обновляет .rpyc с переносом statement-имён)
    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    proc = subprocess.run([str(exe), str(root), "compile"], capture_output=True,
                          text=True, timeout=timeout_s)
    if proc.returncode != 0:
        _fail(f"renpy compile упал:\n{proc.stdout[-1500:]}\n{proc.stderr[-800:]}")

    # 4) Дистрибутивы: dest чистится — старые архивы не должны вкладываться в новые
    dest = root / "build" / "dist" / (version + dest_suffix)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), str(sdk / "launcher"), "distribute", "--dest", str(dest)]
    for p in packages:
        cmd += ["--package", p]
    cmd.append(str(root))
    click.echo(f"distribute {', '.join(packages)} -> {dest.relative_to(root).as_posix()} …")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        _fail(f"distribute упал:\n{proc.stdout[-2000:]}\n{proc.stderr[-800:]}")

    # 5) Кэш .rpyc этого релиза — для переноса имён в следующем (G6): весь game/,
    # в линию своего флейвора (см. пункт 2).
    save_dir = lane / version
    # Линия УЖЕ ВЫПУЩЕННОЙ версии неприкосновенна (release.py: rpyc_lane_frozen).
    frozen = rpyc_lane_frozen(root, lane, version)
    if frozen:
        _fail(frozen)
    if save_dir.exists():
        shutil.rmtree(save_dir)
    n = 0
    for rpyc in (root / "game").rglob("*.rpyc"):
        rel = rpyc.relative_to(root / "game")
        target = save_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(rpyc, target)
        n += 1
    artifacts = [p.name for p in dest.iterdir()]
    click.echo(f"rpyc-кэш релиза: {n} файлов -> "
               f"{save_dir.relative_to(root).as_posix()}/")
    click.secho(f"package: OK — {', '.join(artifacts)}", fg="green")


# ── vn content ────────────────────────────────────────────────────────────────

@main.group()
def content():
    """Контент: lint, compile, graph."""


@content.command("lint")
@click.option("--layout/--no-layout", default=True, help="Сверка структуры каталогов с нормативной (1.2).")
def content_lint(layout: bool):
    """Схемы, naming-конвенции, структура глав, битые exits."""
    from .content.lint import lint

    root = _root()
    rep = lint(root, layout=layout)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if not rep.ok:
        _fail(f"lint: {len(rep.errors)} ошибок")
    click.secho(f"lint: OK ({len(rep.warnings)} предупреждений)", fg="green")


@content.command("compile")
@click.option("--check", is_flag=True, help="Проверить без записи: свеж ли генерат (CI-режим, G1).")
def content_compile(check: bool):
    """Компиляция деклараций в game/generated/ (без lint — используйте vn build)."""
    from .content.compile import CompileError, compile_content

    root = _root()
    try:
        res = compile_content(root, check=check)
    except CompileError as e:
        _fail(str(e))
    _echo_warnings(res.warnings)
    if check:
        if res.stale:
            for rel in res.stale:
                click.secho(f"устарело: {rel}", fg="red")
            _fail("генерат не свеж — выполните vn build")
        click.secho("check: генерат свеж", fg="green")
        return
    click.echo(
        f"generated: {len(res.written)} записано, {len(res.skipped)} без изменений, "
        f"{len(res.deleted)} осиротевших удалено"
    )


@content.command("graph")
@click.option("--out", type=click.Path(), default=None, help="Файл (по умолчанию stdout).")
def content_graph(out):
    """Граф сцен в Mermaid: сцены, exits с условиями, тупики."""
    from .content.graph import build_graph

    root = _root()
    text = build_graph(root)
    if out:
        write_text_lf(Path(out), text)
        click.secho(f"граф записан: {out}", fg="green")
    else:
        click.echo(text)


# ── vn chapter / vn scene ─────────────────────────────────────────────────────

@main.group()
def chapter():
    """Главы: new."""


@chapter.command("new")
@click.argument("slug")
def chapter_new(slug: str):
    """Создать главу: папка chNN_<slug> со скелетом (chapter.yaml, vars.yaml, s010)."""
    from .content.scaffold import ScaffoldError, new_chapter

    root = _root()
    try:
        ch_dir = new_chapter(root, slug)
    except ScaffoldError as e:
        _fail(str(e))
    click.secho(f"создана глава: {ch_dir.relative_to(root).as_posix()}/", fg="green")
    click.echo("не забудьте: владельца главы в CODEOWNERS; vn build для регистрации в меню")


@main.group()
def scene():
    """Сцены: new, stub."""


@scene.command("new")
@click.argument("chapter")
@click.argument("slug")
def scene_new(chapter: str, slug: str):
    """Создать сцену в главе: пара sNNN_<slug>.scene.{yaml,rpy} (следующий номер, шаг 10)."""
    from .content.scaffold import ScaffoldError, new_scene

    root = _root()
    try:
        yaml_path = new_scene(root, chapter, slug)
    except ScaffoldError as e:
        _fail(str(e))
    rel = yaml_path.relative_to(root).as_posix()
    click.secho(f"создана сцена: {rel} (+ парный .rpy)", fg="green")
    click.echo("не забудьте: добавить сцену в scene_order главы и связать exits")


@scene.command("stub")
@click.argument("chapter")
@click.argument("scene_id")
def scene_stub(chapter: str, scene_id: str):
    """Placeholder-сцена для объявленной, но не написанной цели перехода (G15)."""
    from .content.scaffold import ScaffoldError, new_stub

    root = _root()
    try:
        yaml_path = new_stub(root, chapter, scene_id)
    except ScaffoldError as e:
        _fail(str(e))
    click.secho(f"создана заглушка: {yaml_path.relative_to(root).as_posix()}", fg="green")


# ── Остальные домены (заглушки с номером фазы) ────────────────────────────────

def _stub_group(name: str, help_text: str, commands: dict[str, int]):
    grp = click.Group(name=name, help=help_text)
    for cmd_name, phase in commands.items():
        grp.command(name=cmd_name, help=f"Появится в фазе {phase} (раздел 8 ARCHITECTURE.md).")(_stub(phase))
    main.add_command(grp)


# ── vn assets ─────────────────────────────────────────────────────────────────

@main.group()
def assets():
    """Конвейер ассетов (раздел 2): assets_src -> game/assets."""


@assets.command("build")
@click.option("--profile", type=click.Choice(["full", "draft"]), default="full")
def assets_build(profile: str):
    """Сборка game/assets из assets_src (PNG-слои и PSD -> WebP @2, аудио)."""
    _assets_build(_root(), profile)


@assets.command("validate")
def assets_validate():
    """Сырцы (discovery + свежесть) и ссылки контента: matrix, фоны локаций, треки."""
    from .assets.pipeline import build_assets
    from .content.compile import CompileError, compile_content

    root = _root()
    # 1) Уровень сырцов: конвенции имён, обязательные base.png, свежесть выходов.
    ares = build_assets(root, check=True)
    _echo_warnings(ares.warnings)
    if ares.errors:
        for e in ares.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"assets: {len(ares.errors)} ошибок в сырцах")
    _echo_warnings([f"несвежий выход: assets/{rel} (vn assets build)"
                    for rel in ares.stale])
    # 2) Уровень контента: реестр образов + music-треки (check ничего не пишет).
    try:
        res = compile_content(root, check=True)
    except CompileError as e:
        _fail(str(e))
    _echo_warnings(res.warnings)
    n_warn = len(ares.warnings) + len(ares.stale) + len(res.warnings)
    click.secho(f"assets validate: OK ({n_warn} предупреждений)", fg="green")


@assets.command("memory")
@click.option("--scale", type=int, default=None,
              help="Масштаб оверсэмпла (по умолчанию — крупнейший отгружаемый).")
@click.option("--top", default=10, help="Сколько самых тяжёлых сцен показать.")
def assets_memory(scale: int | None, top: int):
    """Модель памяти образов: во что обходится худшая сцена и влезает ли она в кэш."""
    from .assets.memory import analyze, recommended_cache_mb
    from .assets.render_config import load_render_config

    root = _root()
    cfg = load_render_config(root)
    rep = analyze(root, cfg, scale=scale)
    _echo_warnings(rep.warnings)
    click.echo(
        f"кэш образов: {cfg.image_cache_mb} МБ -> {rep.limit_px / 1e6:.0f} Мпикс; "
        f"бюджет сцены {rep.budget_px / 1e6:.1f} Мпикс "
        f"({cfg.cache_generations} поколения), масштаб @{rep.scale}")
    for sc in sorted(rep.scenes, key=lambda s: -s.px)[:top]:
        share = sc.px / rep.budget_px if rep.budget_px else 0
        colour = "red" if share > 1 else ("yellow" if share > 0.8 else "green")
        click.secho(f"  {sc.scene_id:16s} {sc.px / 1e6:7.1f} Мпикс  {share:5.0%}", fg=colour)
        for label, px in sc.parts:
            click.echo(f"      {label:28s} {px / 1e6:7.2f}")
    if rep.scenes:
        click.echo(f"рекомендуемый render.image_cache_mb: "
                   f"{recommended_cache_mb(rep, cfg.cache_generations)}")
    if rep.errors:
        for e in rep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail("бюджет памяти сцены превышен")
    click.secho("память: OK", fg="green")


@assets.command("watch")
@click.option("--profile", type=click.Choice(["full", "draft"]), default="draft")
def assets_watch(profile: str):
    """Вотчер assets_src: бросил PNG/PSD в папку -> пересборка (Ctrl+C для выхода)."""
    from .devloop import watch

    root = _root()
    click.secho("watch активен: assets_src/ (Ctrl+C для выхода)", fg="green")

    def on_assets():
        try:
            _assets_build(root, profile)
        except SystemExit:
            pass

    try:
        watch(root, on_assets, lambda: None)
    except KeyboardInterrupt:
        pass


# ── vn assets video (ADR-0006) ────────────────────────────────────────────────

@assets.group("video")
def assets_video():
    """Видео-трек: video_src -> VP9/WebM-лупы в game/assets/mov (ADR-0006)."""


@assets_video.command("build")
@click.option("--profile", type=click.Choice(["full", "draft"]), default="full",
              help="draft — быстрый низкокачественный энкод для итераций.")
def assets_video_build(profile: str):
    """Собрать только видео-ветку (инкрементально, с loop-валидацией и meta.json)."""
    _assets_build(_root(), profile, only_transforms={"video2webm"})


@assets_video.command("seq")
@click.argument("frames_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("dest", type=click.Path(path_type=Path))
@click.option("--fps", default=24.0, help="Частота кадров секвенции.")
@click.option("--crf", default=12, help="CRF мастера (низкий = ближе к исходнику).")
def assets_video_seq(frames_dir: Path, dest: Path, fps: float, crf: int):
    """PNG-секвенция -> видео-мастер в assets_src/video_src/<group>/<name>.mp4.

    Захват из DAZ/Wan/Sims4 приходит кадрами; до этой команды склейку делали
    руками вне репозитория, и её параметры нигде не фиксировались."""
    from .assets.video import VideoError, assemble_sequence

    root = _root()
    dest = dest if dest.is_absolute() else root / dest
    try:
        rel = dest.resolve().relative_to((root / "assets_src" / "video_src").resolve())
    except ValueError:
        _fail("мастер обязан лечь в assets_src/video_src/<group>/<name>.<ext> (G2)")
    if len(rel.parts) < 2:
        _fail("видео кладутся в группу: assets_src/video_src/<group>/<name>.<ext>")
    try:
        info = assemble_sequence(frames_dir, dest, fps=fps, crf=crf)
    except VideoError as e:
        _fail(str(e))
    click.secho(
        f"секвенция: {info['frames']} кадров -> {dest.relative_to(root).as_posix()} "
        f"({info['width']}x{info['height']}, {info['duration_s']:.2f} c, "
        f"{info['size_bytes'] / 1048576:.1f} МБ)", fg="green")
    # Склейка — нетривиальный шаг обработки: без записи в провенанс мастер выглядел
    # бы «взявшимся ниоткуда», а декларация источника при следующем прогоне встала
    # бы в начало цепочки поверх пустоты.
    from .assets.provenance import ProvenanceError, record

    try:
        record(root, dest, note=(
            f"PNG-секвенция: {info['frames']} кадров @ {fps} fps, "
            f"{info['width']}x{info['height']}, libx264 crf {crf} "
            f"(vn assets video seq)"))
    except ProvenanceError as e:
        click.secho(f"warning: провенанс не записан: {e}", fg="yellow")
    click.echo("дальше: vn assets video build (энкод в отгружаемый VP9)")


@assets_video.command("validate")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
def assets_video_validate(paths: tuple):
    """Строгая проверка .webm: кодек/пиксели/размеры/fps/луп/бюджет.

    Без аргументов проверяются все собранные game/assets/mov/**."""
    from .assets import video as videomod
    from .repo import load_project

    root = _root()
    if paths:
        targets = [Path(p).resolve() for p in paths]
    else:
        mov = root / "game" / "assets" / "mov"
        targets = sorted(mov.rglob("*.webm")) if mov.is_dir() else []
    if not targets:
        click.echo("видео нет: положите сырцы в assets_src/video_src/<group>/ и "
                   "выполните vn assets video build")
        return
    file_budget = (load_project(root).get("budgets") or {}).get("video_file_mb")
    workdir = root / ".vncache" / "video-tmp"
    n_err = 0
    for p in targets:
        opts = videomod.opts_from_meta(p)
        try:
            errors, warnings, s = videomod.validate_output(p, opts, workdir,
                                                           file_budget_mb=file_budget)
        except videomod.VideoError as e:
            _fail(str(e))
        _echo_warnings(warnings)
        for e in errors:
            click.secho(f"error: {e}", fg="red")
        n_err += len(errors)
        if not errors:
            seam = f", стык {s['loop_seam']}" if s.get("loop_seam") is not None else ""
            click.secho(f" ✓ {p.name}: {s['width']}x{s['height']} {s['fps']}fps "
                        f"{s['duration_s']}c, {s['size_bytes'] / 1024 / 1024:.1f} МБ{seam}",
                        fg="green")
    if n_err:
        _fail(f"video validate: {n_err} ошибок")
    click.secho(f"video validate: OK ({len(targets)} файлов)", fg="green")


@assets_video.command("inspect")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def assets_video_inspect(path: Path):
    """Свойства видео + метаданные конвейера + провенанс (если есть)."""
    from .assets import video as videomod

    try:
        s = videomod.summarize(Path(path))
    except videomod.VideoError as e:
        _fail(str(e))
    for k, v in s.items():
        click.echo(f"{k:>12}: {v}")
    for suffix, label in ((videomod.META_SUFFIX, "meta"),
                          (".provenance.json", "provenance")):
        side = Path(path).with_name(Path(path).name + suffix)
        if side.is_file():
            click.secho(f"--- {label}: {side.name} ---", fg="cyan")
            click.echo(side.read_text(encoding="utf-8").strip())


# ── vn assets daz / provenance (ADR-0006) ─────────────────────────────────────

@assets.group("daz")
def assets_daz():
    """Декларации DAZ-рендеров: assets_src/daz/**/<name>.render.yaml."""


@assets_daz.command("validate")
@click.option("--scope", default=None, help="Подпуть в assets_src/daz (например ch01).")
@click.option("--no-provenance", is_flag=True, help="Только проверить, провенанс не писать.")
def assets_daz_validate(scope: str | None, no_provenance: bool):
    """Схема деклараций, наличие сцен (.duf или манифест), наличие выходов;
    для готовых рендеров пишется/обновляется провенанс."""
    from .assets.daz import validate_renders

    rep = validate_renders(_root(), scope=scope, write_provenance=not no_provenance)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    for p in rep.provenance_written:
        click.echo(f"провенанс: {p}")
    if rep.errors:
        _fail(f"daz validate: {len(rep.errors)} ошибок")
    if not rep.checked:
        click.echo("деклараций нет (assets_src/daz/**/<name>.render.yaml) — "
                   "см. docs/adr/0006 и docs/pipeline/phase-0.md")
        return
    click.secho(f"daz validate: OK ({len(rep.checked)} деклараций, "
                f"{len(rep.warnings)} предупреждений)", fg="green")


@assets.group("vam")
def assets_vam():
    """Декларации захватов Virt-a-Mate: assets_src/vam/**/<name>.render.yaml (опц. источник)."""


@assets_vam.command("validate")
@click.option("--scope", default=None, help="Подпуть в assets_src/vam (например ch01).")
@click.option("--no-provenance", is_flag=True, help="Только проверить, провенанс не писать.")
def assets_vam_validate(scope: str | None, no_provenance: bool):
    """Схема деклараций VaM, наличие сцен (.json/.vac/.vap или манифест), наличие
    выходов; для готовых захватов пишется/обновляется провенанс."""
    from .assets.vam import validate_scenes

    rep = validate_scenes(_root(), scope=scope, write_provenance=not no_provenance)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    for p in rep.provenance_written:
        click.echo(f"провенанс: {p}")
    if rep.errors:
        _fail(f"vam validate: {len(rep.errors)} ошибок")
    if not rep.checked:
        click.echo("деклараций нет (assets_src/vam/**/<name>.render.yaml) — "
                   "VaM опционален, см. docs/pipeline/phase-0.md (раздел VaM)")
        return
    click.secho(f"vam validate: OK ({len(rep.checked)} деклараций, "
                f"{len(rep.warnings)} предупреждений)", fg="green")


@assets.group("sims4")
def assets_sims4():
    """Декларации захватов The Sims 4: assets_src/sims4/**/<name>.render.yaml
    (опциональный источник-задел, ADR-0007)."""


@assets_sims4.command("validate")
@click.option("--scope", default=None, help="Подпуть в assets_src/sims4 (например ch01).")
@click.option("--no-provenance", is_flag=True, help="Только проверить, провенанс не писать.")
def assets_sims4_validate(scope: str | None, no_provenance: bool):
    """Схема деклараций Sims 4, наличие сцен (zip/save/package или манифест),
    наличие выходов; для готовых захватов пишется/обновляется провенанс."""
    from .assets.sims4 import validate_scenes

    rep = validate_scenes(_root(), scope=scope, write_provenance=not no_provenance)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    for p in rep.provenance_written:
        click.echo(f"провенанс: {p}")
    if rep.errors:
        _fail(f"sims4 validate: {len(rep.errors)} ошибок")
    if not rep.checked:
        click.echo("деклараций нет (assets_src/sims4/**/<name>.render.yaml) — "
                   "источник опционален (задел), см. ADR-0007 и "
                   "docs/pipeline/phase-0.md (раздел Sims 4)")
        return
    click.secho(f"sims4 validate: OK ({len(rep.checked)} деклараций, "
                f"{len(rep.warnings)} предупреждений)", fg="green")


@assets.command("new")
@click.argument("source", type=click.Choice(["daz", "vam", "sims4"]))
@click.argument("logical_id")
@click.option("--scene", required=True,
              help="Исходник сцены относительно assets_src/ (daz/…/x.duf, vam/…, sims4/…).")
@click.option("--resolution", default=None,
              help="ШxВ мастера; по умолчанию — source_min класса из project.yaml.")
@click.option("--ext", default="png", help="Расширение мастера (png/jpg/webp/tif).")
@click.option("--video", is_flag=True, help="Выход — видео-мастер в video_src/.")
def assets_new(source: str, logical_id: str, scene: str, resolution: str | None,
               ext: str, video: bool):
    """Заготовка декларации рендера/захвата: vn assets new daz cg/ch01/kiss --scene …

    Писать YAML руками против схемы с additionalProperties: false — самый частый
    способ потерять полчаса на опечатке."""
    from .assets import sources
    from .assets.render_config import load_render_config

    root = _root()
    kind = {"daz": sources.DAZ, "vam": sources.VAM, "sims4": sources.SIMS4}[source]
    cfg = load_render_config(root)
    if resolution:
        try:
            w, h = (int(x) for x in resolution.lower().replace("х", "x").split("x"))
        except ValueError:
            _fail("--resolution задаётся как ШxВ, например 3840x2160")
    else:
        cls_name = logical_id.split("/", 1)[0]
        cls = cfg.classes.get(cls_name if cls_name in cfg.classes else "cg")
        w, h = cls.source_min or (cfg.screen[0] * max(cls.scales), cfg.screen[1] * max(cls.scales))
    try:
        dest = sources.scaffold(root, kind, logical_id, scene, (w, h), ext=ext, video=video)
    except FileExistsError as e:
        _fail(f"декларация уже существует: {Path(str(e)).relative_to(root).as_posix()}")
    click.secho(f"создано: {dest.relative_to(root).as_posix()}", fg="green")
    click.echo(f"выход: assets_src/{sources.output_for_id(logical_id, video, ext)} "
               f"({w}x{h})")
    click.echo(f"дальше: отрендерить -> vn assets {source} validate -> vn build")


@assets.command("cache")
@click.option("--gc", "do_gc", is_flag=True, help="Удалить блобы, которых нет в текущем манифесте.")
@click.option("--dry-run", is_flag=True, help="Показать, что будет удалено.")
def assets_cache(do_gc: bool, dry_run: bool):
    """Кэш трансформаций (.vncache/assets): размер и сборка мусора.

    Кэш контентно-адресуемый и растёт неограниченно: каждая правка сырца
    оставляет прошлый блоб. GC — mark & sweep от манифеста сборки."""
    from .assets.pipeline import cache_gc

    root = _root()
    cache_dir = root / ".vncache" / "assets"
    total = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file()) \
        if cache_dir.is_dir() else 0
    click.echo(f"кэш: {total / 1024 / 1024:.1f} МБ ({cache_dir})")
    if not (do_gc or dry_run):
        click.echo("сборка мусора: vn assets cache --gc (или --dry-run)")
        return
    removed, freed = cache_gc(root, dry_run=dry_run)
    verb = "будет удалено" if dry_run else "удалено"
    click.secho(f"{verb}: {removed} блобов, {freed / 1024 / 1024:.1f} МБ", fg="green")


@assets.command("licenses")
def assets_licenses():
    """Сверка деклараций рендеров с реестром лицензий (content/licenses.yaml).

    Проверяет: ссылки существуют, ассет разрешён в коммерческой игре (game_use),
    а для выходов в nsfw/** — разрешён во взрослом контенте (nsfw_allowed)."""
    from .assets.licenses import REGISTRY_REL, validate_licenses

    rep = validate_licenses(_root())
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if rep.errors:
        _fail(f"licenses: {len(rep.errors)} нарушений")
    if not rep.declarations:
        click.echo(f"деклараций рендеров нет; в реестре {rep.entries} записей "
                   f"({REGISTRY_REL})")
        return
    click.secho(f"licenses: OK ({rep.declarations} деклараций, {rep.entries} записей "
                f"в реестре, {len(rep.unlicensed)} без license)", fg="green")


@assets.group("provenance")
def assets_provenance():
    """Провенанс сырцов: хэш исходника -> параметры обработки -> хэш артефакта."""


@assets_provenance.command("record")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option("--source", type=click.Path(exists=True, path_type=Path), default=None,
              help="Исходник шага; его провенанс-цепочка станет префиксом.")
@click.option("--workflow", "workflow_file", type=click.Path(exists=True, path_type=Path),
              default=None, help="API-граф ComfyUI (json), если артефакт не PNG с метаданными.")
@click.option("--note", default=None, help="Ручной шаг (Photoshop и т.п.): описание.")
@click.option("--model", default=None, help="Переопределить имя модели.")
@click.option("--seed", type=int, default=None, help="Переопределить seed.")
def assets_provenance_record(artifact: Path, source: Path | None, workflow_file: Path | None,
                             note: str | None, model: str | None, seed: int | None):
    """Записать провенанс артефакта. PNG из ComfyUI разбирается автоматически
    (workflow, seed, модель, LoRA, промпты из tEXt-чанков)."""
    from .assets.provenance import ProvenanceError, record

    try:
        path, doc = record(_root(), Path(artifact), source=source,
                           workflow_file=workflow_file, note=note,
                           overrides={"model": model, "seed": seed})
    except ProvenanceError as e:
        _fail(str(e))
    last = doc["chain"][-1]
    click.echo(f"шагов в цепочке: {len(doc['chain'])}; последний: {last['kind']}"
               + (f", seed {last.get('seed')}, модель {last.get('model')}"
                  if last["kind"] == "comfyui" else ""))
    click.secho(f"провенанс записан: {path.relative_to(_root()).as_posix()}", fg="green")


@assets_provenance.command("workflow")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), default=None,
              help="Куда сохранить граф (по умолчанию — stdout).")
def assets_provenance_workflow(artifact: Path, out: Path | None):
    """Восстановить workflow-граф ComfyUI артефакта: из хранилища по
    workflow_hash (или из инлайн-fallback'а сайдкара). Выход пригоден для
    загрузки в ComfyUI (регенерация с теми же параметрами)."""
    from .assets.provenance import load, load_workflow

    doc = load(Path(artifact))
    if doc is None:
        _fail(f"{artifact}: провенанс-сайдкара нет")
    steps = [s for s in doc["chain"] if s.get("kind") == "comfyui"]
    if not steps:
        _fail(f"{artifact}: в цепочке нет comfyui-шагов")
    step = steps[-1]
    graph = step.get("workflow")
    if graph is None and step.get("workflow_hash"):
        blob = load_workflow(_root(), step["workflow_hash"])
        if blob is not None:
            graph = blob.get("prompt")
    if graph is None:
        _fail("workflow-граф не найден ни в сайдкаре, ни в хранилище — "
              "перезапишите провенанс из исходного PNG")
    payload = json.dumps(graph, ensure_ascii=False, indent=1, sort_keys=True)
    if out:
        write_text_lf(Path(out), payload + "\n")
        click.secho(f"граф сохранён: {out} (seed {step.get('seed')}, "
                    f"модель {step.get('model')})", fg="green")
    else:
        click.echo(payload)


@assets_provenance.command("verify")
@click.option("--scope", default=None, help="Подпуть в assets_src.")
def assets_provenance_verify(scope: str | None):
    """Сверка всех провенанс-цепочек: схема, хэш артефакта, хэши источников
    (локально или по манифестам хранилища)."""
    from .assets.provenance import verify

    rep = verify(_root(), scope=scope)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if rep.errors:
        _fail(f"provenance verify: {len(rep.errors)} ошибок")
    if not rep.checked:
        click.echo("провенанс-сайдкаров нет (assets_src/**/*.provenance.json)")
        return
    click.secho(f"provenance verify: OK ({len(rep.checked)} цепочек, "
                f"{len(rep.warnings)} предупреждений)", fg="green")


def _sync_report(rep, ok_label: str):
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    for r in rep.pushed:
        click.echo(f"залит: {r}")
    for r in rep.pulled:
        click.echo(f"получен: {r}")
    for r in rep.locked:
        click.secho(f"лок взят: {r}", fg="cyan")
    for r in rep.rows:
        click.echo(f" {r}")
    if rep.errors:
        _fail(f"{ok_label}: {len(rep.errors)} ошибок")
    click.secho(f"{ok_label}: OK", fg="green")


@assets.command("push")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--storage", default="default", help="Логическое хранилище для новых файлов.")
def assets_push(paths: tuple, storage: str):
    """Залить сырцы в хранилище (ТРЕБУЕТ лока, G14) и обновить манифесты."""
    from .assets.storage import StorageError, push

    root = _root()
    try:
        rep = push(root, list(paths), storage=storage)
    except StorageError as e:
        _fail(str(e))
    for r in rep.fresh:
        click.echo(f"актуален: {r}")
    _sync_report(rep, "assets push")


@assets.command("pull")
@click.option("--scope", default=None, help="Подпуть в assets_src (например psd/characters/mira).")
@click.option("--edit", is_flag=True, help="Заодно взять лок на полученные файлы.")
def assets_pull(scope: str | None, edit: bool):
    """Восстановить бинари сырцов по манифестам из хранилища."""
    from .assets.storage import StorageError, pull

    root = _root()
    try:
        rep = pull(root, scope=scope, edit=edit)
    except StorageError as e:
        _fail(str(e))
    click.echo(f"актуально: {len(rep.fresh)}")
    _sync_report(rep, "assets pull")


@assets.command("lock")
@click.argument("rel_path")
@click.option("--release", is_flag=True, help="Снять свой лок.")
@click.option("--force", is_flag=True, help="Снять ЧУЖОЙ лок (эскалация на лида, G14).")
def assets_lock(rel_path: str, release: bool, force: bool):
    """Взять/снять лок на сырец (путь относительно assets_src/)."""
    from .assets.storage import StorageError, lock

    root = _root()
    try:
        rep = lock(root, rel_path.replace("\\", "/"), release=release, force=force)
    except StorageError as e:
        _fail(str(e))
    _sync_report(rep, "assets lock")


@assets.command("status")
def assets_status():
    """Сводка сырцов: версии, локальное состояние, держатели локов."""
    from .assets.storage import StorageError, status

    root = _root()
    try:
        rep = status(root)
    except StorageError as e:
        _fail(str(e))
    if not rep.rows and not rep.errors:
        click.echo("манифестов нет — сырцы ещё не пушились (vn assets lock + push)")
        return
    _sync_report(rep, "assets status")

# ── vn char ───────────────────────────────────────────────────────────────────

@main.group()
def char():
    """Персонажи: скаффолд декларации, проверка матрицы, лист арт-ревью (раздел 4)."""


@char.command("new")
@click.argument("char_id")
@click.option("--name", default="", help="Имя в текстбоксе (исходный язык); по умолчанию — Id.")
@click.option("--color", default="", help="Цвет имени #RRGGBB; по умолчанию — стабильный из id.")
@click.option("--pose", default="a", show_default=True, help="Первая поза матрицы.")
@click.option("--outfit", default="casual", show_default=True, help="Первый наряд.")
@click.option("--emotion", default="neutral", show_default=True, help="Первая эмоция.")
def char_new(char_id: str, name: str, color: str, pose: str, outfit: str, emotion: str):
    """Завести персонажа: декларация + каталог мастеров."""
    from .assets.sources import output_for_id
    from .content.scaffold import ScaffoldError, new_character

    root = _root()
    try:
        created = new_character(root, char_id, name=name, color=color, pose=pose,
                                outfit=outfit, emotion=emotion)
    except ScaffoldError as e:
        _fail(str(e))
    for path in created:
        click.secho(f"создано: {path.relative_to(root).as_posix()}", fg="green")
    master = output_for_id(f"spr/{char_id}/{pose}/base")
    click.echo("дальше:")
    click.echo(f"  1) положите мастер позы: assets_src/{master} (плюс "
               f"outfits/{outfit}, faces/{emotion} рядом)")
    click.echo("  2) vn assets build && vn char validate " + char_id
               + "   # впишет фактический холст в canvas")
    click.echo("  3) vn build                                 # layeredimage в генерат")
    if not name:
        click.secho("warning: имя не задано (--name) — в текстбоксе будет "
                    f"{char_id.capitalize()!r}; после правки прогоните vn loc extract",
                    fg="yellow")


@char.command("validate")
@click.argument("char_id", required=False)
@click.option("--all", "all_chars", is_flag=True, help="Проверить всех персонажей.")
def char_validate(char_id: str | None, all_chars: bool):
    """Декларация, геометрия мастеров и полнота матрицы — БЕЗ сборки ассетов.

    Проверки те же, что в `vn build` (одна функция контракта на два потребителя),
    но без перекодирования дерева и без Ren'Py SDK: цикл «поправил слой -> узнал,
    что не так» измеряется секундами."""
    from .content.characters import CharError, validate

    if not char_id and not all_chars:
        raise click.UsageError("укажите персонажа или --all")
    root = _root()
    try:
        rep = validate(root, only=None if all_chars else char_id)
    except CharError as e:
        _fail(str(e))
    for row in rep.rows:
        click.echo(row)
    _echo_warnings(rep.warnings)
    if rep.errors:
        for e in rep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"char validate: {len(rep.errors)} ошибок")
    click.secho(f"char validate: OK ({len(rep.rows)} персонажей)", fg="green")


@char.command("sheet")
@click.argument("char_id", required=False)
@click.option("--all", "all_chars", is_flag=True, help="Листы всех персонажей + индекс.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path),
              help="Куда писать (по умолчанию build/review/<id>/).")
@click.option("--max-side", type=int, help="Сторона ячейки, px (по умолчанию render.thumb).")
def char_sheet(char_id: str | None, all_chars: bool, out_dir: Path | None,
               max_side: int | None):
    """Лист арт-ревью: все допустимые комбинации поза+наряд+эмоция одной страницей.

    Ячейки склеиваются в том же z-порядке, что эмитирует layeredimage, — ревьюер
    смотрит на то, что увидит игрок."""
    from .content.characters import CharError, char_dirs, sheet, sheet_index

    if not char_id and not all_chars:
        raise click.UsageError("укажите персонажа или --all")
    root = _root()
    ids = [d.name for d in char_dirs(root)] if all_chars else [char_id]
    pages: dict[str, Path] = {}
    try:
        for cid in ids:
            pages[cid] = sheet(root, cid, out_dir=out_dir, max_side=max_side)
            click.secho(f"лист: {pages[cid].relative_to(root).as_posix()}", fg="green")
        if all_chars and pages:
            index = sheet_index(root, pages)
            click.secho(f"индекс: {index.relative_to(root).as_posix()}", fg="green")
    except CharError as e:
        _fail(str(e))
# ── vn loc ────────────────────────────────────────────────────────────────────

@main.group()
def loc():
    """Локализация (раздел 5, G8)."""


@loc.command("keys")
@click.option("--check", is_flag=True, help="Только проверить (CI): все ли say/menu имеют id.")
def loc_keys(check: bool):
    """Дописать say-id и маркеры меню в авторские scene.rpy (парсером Ren'Py, G24)."""
    from .loc.keys import KeysError, assign_ids

    root = _root()
    try:
        rep = assign_ids(root, check=check)
    except KeysError as e:
        _fail(str(e))
    _echo_warnings(rep.warnings)
    if rep.errors:
        for e in rep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"loc keys: {len(rep.errors)} ошибок")
    if check:
        if rep.missing:
            for m in rep.missing:
                click.secho(f"расхождение: {m}", fg="red")
            _fail("loc keys --check: есть строки без id или устаревший ledger — "
                  "выполните vn loc keys")
        click.secho("loc keys --check: все строки с id, ledger свеж", fg="green")
        return
    for c in rep.changed:
        click.echo(f"обновлён: {c}")
    for l in rep.ledgers:
        click.echo(f"ledger: {l}")
    click.secho(f"loc keys: OK ({len(rep.changed)} файлов изменено)", fg="green")


@loc.command("add")
@click.argument("code")
@click.option("--name", default="", help="Native-название (Deutsch, 日本語); "
                                         "для известных кодов подставится само.")
def loc_add(code: str, name: str):
    """Создать пакет языка loc/po/<code>/ (ADR-0005) и заполнить PO-заготовки."""
    from .loc.po import LocError, extract, scaffold_language

    root = _root()
    try:
        mf = scaffold_language(root, code, name)
        click.echo(f"создан: {mf.relative_to(root).as_posix()}")
        rep = extract(root)
    except LocError as e:
        _fail(str(e))
    _echo_warnings(rep.warnings)
    for c in rep.changed:
        click.echo(f"обновлён: {c}")
    click.secho(f"loc add: OK — пакет {code} готов; переводите loc/po/{code}/*.po "
                f"и выполните vn loc import", fg="green")


@loc.command("extract")
def loc_extract():
    """Обновить PO всех языков из ledger/strings/персонажей (переводы сохраняются)."""
    from .loc.po import LocError, extract

    try:
        rep = extract(_root())
    except LocError as e:
        _fail(str(e))
    _echo_warnings(rep.warnings)
    for c in rep.changed:
        click.echo(f"обновлён: {c}")
    click.secho(f"loc extract: OK ({len(rep.changed)} PO-файлов)", fg="green")


@loc.command("import")
def loc_import():
    """PO -> game/tl/<lang>/: translate-блоки, данные меню/строк, манифест языка
    (ручные правки tl запрещены)."""
    from .loc.po import LocError, import_translations

    try:
        rep = import_translations(_root())
    except LocError as e:
        _fail(str(e))
    if rep.errors:
        for e in rep.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"loc import: {len(rep.errors)} ошибок разметки переводов")
    for c in rep.changed:
        click.echo(f"{c}")
    click.secho(f"loc import: OK ({len(rep.changed)} файлов)", fg="green")


@loc.command("pseudo")
def loc_pseudo():
    """Псевдолокализация (synthetic-пакет pseudo): QA переполнений UI до реальных переводов."""
    from .loc.po import LocError, import_translations, pseudo

    root = _root()
    try:
        rep = pseudo(root)
        imp = import_translations(root)
    except LocError as e:
        _fail(str(e))
    if imp.errors:
        for e in imp.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"loc pseudo: {len(imp.errors)} ошибок разметки при импорте")
    click.secho(f"loc pseudo: OK ({len(rep.changed)} PO-файлов; язык 'pseudo' готов)", fg="green")


@loc.command("report")
def loc_report():
    """Покрытие перевода по языкам."""
    from .loc.po import LocError, report

    try:
        rep = report(_root())
    except LocError as e:
        _fail(str(e))
    if not rep.coverage:
        click.echo("пакетов языков нет (loc/po/*/language.yaml) — vn loc add <code>")
        return
    for lang, cov in sorted(rep.coverage.items()):
        pct = (cov["translated"] / cov["total"] * 100) if cov["total"] else 100.0
        click.echo(f"{lang}: {cov['translated']}/{cov['total']} ({pct:.0f}%), fuzzy: {cov['fuzzy']}")
# ── vn voice (C5/§4.9) ────────────────────────────────────────────────────────

@main.group()
def voice():
    """Озвучка: покрытие по манифестам, импорт дублей, валидация (C5/§4.9)."""


@voice.command("manifest")
@click.argument("chapter")
@click.option("--lang", required=True, help="Язык дублей (код языка, включая исходный).")
@click.option("--char", default=None, help="Только реплики этого персонажа.")
@click.option("-o", "--out", "out_path", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Куда писать CSV-лист для актёра/студии.")
def voice_manifest(chapter: str, lang: str, char: str | None, out_path: Path):
    """Лист записи: реплики главы (id, кто, текст, контекст, статус покрытия)."""
    from .voice import VoiceError, manifest_rows, write_manifest_csv

    root = _root()
    try:
        rows = manifest_rows(root, chapter, lang, char=char)
    except VoiceError as e:
        _fail(str(e))
    write_manifest_csv(rows, out_path)
    covered = sum(1 for r in rows if r["status"])
    click.secho(f"voice manifest: {len(rows)} реплик -> {out_path} "
                f"(уже покрыто: {covered})", fg="green")


@voice.command("import")
@click.argument("src_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--lang", required=True, help="Язык импортируемых дублей.")
@click.option("--draft", is_flag=True,
              help="Пометить дубли как draft (черновые/TTS): warning в релизном гейте.")
def voice_import(src_dir: Path, lang: str, draft: bool):
    """Разложить дубли <line_id>.<ext> по assets_src/voice/ и обновить манифесты.

    Импорт атомарен: любая ошибка валидации имён/ledger — и ни один файл
    не скопирован (половинчатый импорт хуже отказа). Транскод в Opus — vn assets build."""
    from .voice import import_takes

    root = _root()
    rep = import_takes(root, src_dir, lang, status="draft" if draft else "final")
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if rep.errors:
        _fail(f"voice import: {len(rep.errors)} ошибок — ничего не импортировано")
    click.secho(f"voice import: {len(rep.imported)} дублей "
                f"({', '.join(rep.updated_manifests)}); транскод — vn assets build",
                fg="green")


@voice.command("tts")
@click.argument("chapter")
@click.option("--lang", default=None,
              help="Язык дублей (по умолчанию — исходный язык проекта из loc.yaml).")
@click.option("--char", default=None, help="Только реплики этого персонажа.")
@click.option("--backend", default=None,
              help="Чем синтезировать: piper (основной) | say (дев-фолбэк, macOS). "
                   "По умолчанию — первый доступный.")
@click.option("--voice", "voice_name", default=None,
              help="Голос: имя модели piper (ru_RU-irina-medium) или путь к .onnx; "
                   "для say — имя системного голоса (say -v '?').")
@click.option("--rate", type=float, default=None,
              help="Множитель темпа речи (по умолчанию 1.0 — нормальный темп голоса).")
@click.option("--only-missing/--regenerate-drafts", default=True, show_default=True,
              help="Только непокрытые реплики либо ещё и перезапись существующих "
                   "черновиков. Реплики status: final не трогаются никогда.")
@click.option("--allow-download", is_flag=True,
              help="Разрешить скачать модель голоса piper в .vncache/piper-voices.")
def voice_tts(chapter: str, lang: str | None, char: str | None, backend: str | None,
              voice_name: str | None, rate: float | None, only_missing: bool,
              allow_download: bool):
    """TTS-черновики непокрытых реплик главы: озвученный играбельный билд до записи актёров.

    Дубли помечаются status: draft (WARN релизного гейта) и лежат в общей мастер-зоне;
    боевые дубли заменяют их через vn voice import. Транскод в game/assets — vn assets build."""
    from .loc.po import LocError
    from .voice import TTS_DEFAULT_RATE, VoiceError, synth_drafts

    root = _root()
    try:
        rep = synth_drafts(root, chapter, lang=lang, char=char, backend=backend,
                           voice=voice_name,
                           rate=TTS_DEFAULT_RATE if rate is None else rate,
                           only_missing=only_missing, allow_download=allow_download)
    except (VoiceError, LocError) as e:
        _fail(str(e))
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if rep.errors:
        _fail(f"voice tts: {len(rep.errors)} ошибок — ничего не импортировано")
    if not rep.generated:
        click.secho(f"voice tts: озвучивать нечего (пропущено: {len(rep.skipped)})",
                    fg="green")
        return
    click.secho(f"voice tts: {len(rep.generated)} черновиков [{rep.backend}/{rep.voice}] "
                f"({', '.join(rep.updated_manifests)}); транскод — vn assets build",
                fg="green")


@voice.command("validate")
@click.option("--report", "show_report", is_flag=True,
              help="Сводка покрытия по главам и языкам.")
def voice_validate(show_report: bool):
    """Манифесты <-> ledger <-> мастера: сироты в обе стороны, драфты, дыры покрытия.

    Ошибки валят команду; драфты и дыры здесь информационные — жёсткими они
    становятся в релизном гейте (vn release validate: драфты = WARN, дыры = FAIL)."""
    from .voice import validate as voice_validate_fn

    root = _root()
    rep = voice_validate_fn(root)
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if show_report:
        if not rep.coverage:
            click.echo("озвучиваемых глав нет (content/chapters/*/voice/)")
        for (ch, lang), (covered, total) in sorted(rep.coverage.items()):
            pct = covered / total * 100 if total else 100.0
            click.echo(f"{ch} [{lang}]: покрыто {covered}/{total} ({pct:.0f}%)")
        for h in rep.holes:
            click.echo(f"  непокрыто {h}")
    if not rep.ok:
        _fail(f"voice: {len(rep.errors)} ошибок")
    accepted = f", принятых драфтов: {len(rep.accepted)}" if rep.accepted else ""
    click.secho(f"voice: OK (драфтов: {len(rep.drafts)}{accepted}, "
                f"непокрыто: {len(rep.holes)})", fg="green")
# ── vn save ───────────────────────────────────────────────────────────────────

FIXTURES_DIR = "ci/fixtures/saves"


@main.group()
def save():
    """Сейвы: check, corpus (раздел 6, G5/G6). Миграции исполняются автоматически
    при загрузке (label after_load); корпусный прогон и есть их проверка."""


@save.command("check")
def save_check():
    """Оффлайн-проверка фикстур: структура слота, JSON-метаданные, версия схемы."""
    import zipfile

    root = _root()
    fixtures = sorted((root / FIXTURES_DIR).glob("*.save"))
    if not fixtures:
        click.echo(f"фикстур нет ({FIXTURES_DIR}/) — создайте: vn save corpus --add")
        return
    failed = 0
    for f in fixtures:
        try:
            with zipfile.ZipFile(f) as z:
                meta = json.loads(z.read("json"))
            schema = meta.get("vn_save_schema")
            if not isinstance(schema, int):
                raise ValueError("в JSON-заголовке нет vn_save_schema (int)")
            click.echo(f" ✓ {f.name}: schema {schema}, версия {meta.get('vn_version', '?')}, "
                       f"сцена {meta.get('vn_scene', '?')}")
        except Exception as e:
            click.secho(f" ✗ {f.name}: {e}", fg="red")
            failed += 1
    if failed:
        _fail(f"save check: {failed} битых фикстур")
    click.secho(f"save check: OK ({len(fixtures)} фикстур)", fg="green")


RPYC_LINE_DIR = "ci/fixtures/rpyc-line"


def _rpyc_line_restore(root: Path) -> int:
    """Линия statement-имён (G6): фикстуры сейвов валидны ТОЛЬКО против .rpyc,
    с которыми создавались. Канонический носитель линии — ci/fixtures/rpyc-line/
    в git: восстановление с перезаписью перед прогоном корпуса делает корпус
    детерминированным на любой машине (движок перенесёт имена при перекомпиляции)."""
    import shutil

    line = root / RPYC_LINE_DIR
    if not line.is_dir():
        return 0
    n = 0
    for rpyc in line.rglob("*.rpyc"):
        rel = rpyc.relative_to(line)
        target = root / "game" / rel
        if target.with_suffix(".rpy").is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(rpyc, target)
            n += 1
    return n


def _rpyc_line_snapshot(root: Path) -> int:
    import shutil

    line = root / RPYC_LINE_DIR
    if line.exists():
        shutil.rmtree(line)
    n = 0
    for rpyc in (root / "game").rglob("*.rpyc"):
        rel = rpyc.relative_to(root / "game")
        target = line / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(rpyc, target)
        n += 1
    return n


@save.command("corpus")
@click.option("--add", "add_name", default=None,
              help="Создать фикстуру: прогон с сохранением на тике N, копия в ci/fixtures/saves/.")
@click.option("--timeout", "timeout_s", default=180)
def save_corpus(add_name: str | None, timeout_s: int):
    """Корпус сейвов: каждая фикстура ЗАГРУЖАЕТСЯ в реальной игре (--savedir),
    миграции прогоняются в after_load, автопилот доигрывает до конца.
    Линия .rpyc фикстур живёт в git (ci/fixtures/rpyc-line/) — корпус работает
    одинаково на любой машине и в CI (G6)."""
    import shutil

    from .repo import load_project

    root = _root()
    project = load_project(root)
    fixtures_dir = root / FIXTURES_DIR
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    if add_name is not None:
        savedir = root / ".vncache" / "corpus-savedir"
        if savedir.exists():
            shutil.rmtree(savedir)
        shots = root / ".vncache" / "corpus"
        rc, timed_out = _autopilot_run(
            root, shots, {"VN_AUTOPILOT_SAVE_AT": "4", "VN_AUTOPILOT_PICKS": "0,1"},
            timeout_s, savedir=savedir,
        )
        # Ren'Py 8.5 добавляет к имени слота токен локации: 1-1-LT1.save
        slots = sorted(savedir.glob("1-1*.save"))
        if timed_out or not slots:
            _fail("corpus --add: прогон не создал сейв (см. traceback.txt / RESULT.txt)")
        slot = slots[0]
        name = add_name if add_name.endswith(".save") else f"{add_name}.save"
        dest = fixtures_dir / name
        shutil.copy(slot, dest)
        others = [f for f in fixtures_dir.glob("*.save") if f != dest]
        if others:
            click.secho(
                f"ВНИМАНИЕ: линия .rpyc перезаписывается — старые фикстуры "
                f"({', '.join(f.name for f in others)}) могли быть созданы на другой линии",
                fg="yellow",
            )
        n = _rpyc_line_snapshot(root)
        click.secho(f"фикстура создана: {dest.relative_to(root).as_posix()} "
                    f"(schema {project['save_schema']}); линия имён: {n} .rpyc -> "
                    f"{RPYC_LINE_DIR}/", fg="green")
        return

    restored = _rpyc_line_restore(root)
    if restored:
        click.echo(f"линия имён: {restored} .rpyc восстановлено из {RPYC_LINE_DIR}/ (G6)")

    fixtures = sorted(fixtures_dir.glob("*.save"))
    if not fixtures:
        _fail(f"фикстур нет ({FIXTURES_DIR}/) — создайте: vn save corpus --add <имя>")
    failed = 0
    for fixture in fixtures:
        savedir = root / ".vncache" / "corpus-savedir"
        if savedir.exists():
            shutil.rmtree(savedir)
        savedir.mkdir(parents=True)
        # Имя слота с токеном локации зависит от версии SDK — кладём оба варианта,
        # движок подхватит известный ему (renpy.load("1-1"))
        shutil.copy(fixture, savedir / "1-1-LT1.save")
        shutil.copy(fixture, savedir / "1-1.save")
        shots = root / ".vncache" / "corpus"
        rc, timed_out = _autopilot_run(
            root, shots, {"VN_AUTOPILOT_LOAD": "1-1"}, timeout_s, savedir=savedir,
        )
        result_file = shots / "RESULT.txt"
        verdict = (result_file.read_text(encoding="utf-8").strip()
                   if result_file.is_file() else "нет RESULT.txt")
        state_file = shots / "state.json"
        schema_after = None
        if state_file.is_file():
            schema_after = json.loads(state_file.read_text(encoding="utf-8")).get("vn_save_schema")
        ok = (not timed_out and verdict.startswith("OK")
              and schema_after == project["save_schema"])
        mark = "✓" if ok else "✗"
        line = (f" {mark} {fixture.name}: {verdict}; schema после загрузки: {schema_after} "
                f"(цель {project['save_schema']})")
        click.secho(line, fg=("green" if ok else "red"))
        if not ok:
            failed += 1
            tb = root / "traceback.txt"
            if tb.is_file():
                click.secho(tb.read_text(encoding="utf-8", errors="replace")[-1200:], fg="red")
    if failed:
        _fail(f"save corpus: {failed} фикстур не прошли")
    click.secho(f"save corpus: OK ({len(fixtures)} фикстур загружены и мигрированы)", fg="green")


save.command("migrate", help="Оффлайн-миграция файла сейва — при необходимости (фаза 3); "
                             "в игре миграции идут автоматически в after_load.")(_stub(3))
# ── vn test ───────────────────────────────────────────────────────────────────

@main.group()
def test():
    """QA-прогоны (7.4): smoke, replay, screens, paths."""


def _autopilot_run(root: Path, shots: Path, extra_env: dict, timeout_s: int,
                   savedir: Path | None = None) -> tuple[int, bool]:
    """Тонкая обёртка над qa.autopilot_run: CLI переводит отказ модуля в exit 1."""
    from .qa import QaError, autopilot_run

    try:
        return autopilot_run(root, shots, extra_env, timeout_s, savedir=savedir)
    except QaError as e:
        _fail(str(e))


@test.command("smoke")
@click.option("--picks", default="", help="Индексы выборов в меню через запятую (например 0,1).")
@click.option("--lang", default="", help="Язык прогона (код пакета loc/po/<code>/, включая pseudo).")
@click.option("--timeout", "timeout_s", default=180, help="Лимит прогона, сек.")
@click.option("--record", "record_name", default="",
              help="Записать этот прогон как фикстуру повтора (vn test replay).")
@click.option("--why", "record_why", default="",
              help="Зачем запись нужна: какой путь или баг она держит (обязательно с --record).")
def test_smoke(picks: str, lang: str, timeout_s: int, record_name: str = "",
               record_why: str = ""):
    """Автопрохождение игры автопилотом: авто-advance, авто-выбор, скриншоты движка."""
    root = _root()
    if lang:
        from .loc.po import LocError, source_language

        try:
            src_code = source_language(root).code
        except LocError:
            src_code = None
        if lang in (src_code, "@source"):
            # Исходный язык: tl/<code>/ не существует по определению — прогон
            # с явным сбросом на language=None (маркер @source в автопилоте).
            # Сам маркер тоже принимаем: он документирован в рантайме
            # (030_flow.rpy: autopilot_boot), и отвергать его — ловушка.
            lang = "@source"
        elif not (root / "game" / "tl" / lang).is_dir():
            _fail(f"языка {lang!r} нет в game/tl/ — выполните vn loc import "
                  f"(change_language молча показал бы исходный язык — ложно-зелёный прогон)")
    shots = root / ".vncache" / "smoke"
    returncode, timed_out = _autopilot_run(
        root, shots, {"VN_AUTOPILOT_PICKS": picks, "VN_AUTOPILOT_LANG": lang}, timeout_s
    )
    tb = root / "traceback.txt"
    if timed_out:
        if tb.is_file():
            click.secho(tb.read_text(encoding="utf-8", errors="replace")[-1500:], fg="red")
            _fail("smoke: игра упала с traceback (и висела до таймаута)")
        _fail(f"smoke: игра не завершилась за {timeout_s} c — прогон снят (дерево процессов убито)")

    result_file = shots / "RESULT.txt"
    verdict = result_file.read_text(encoding="utf-8").strip() if result_file.is_file() else "нет RESULT.txt"
    n_shots = len(list(shots.glob("shot*.png")))
    picks_log = shots / "picks.log"
    click.echo(f"скриншоты: {n_shots} -> {shots}")
    from .qa import read_run
    from .release import runtime_budget_failures

    art = read_run(root, shots)
    if art.cold_start_s is not None:
        click.echo(f"cold start (init -> первая интеракция): {art.cold_start_s:.2f} c")
    rss = art.perf.get("baseline_rss_mb")
    if rss is not None:
        click.echo(f"пик RSS игры: {rss:.0f} МБ")
    over = runtime_budget_failures(root, cold_start_s=art.cold_start_s,
                                   baseline_rss_mb=rss)
    if over:
        for line in over:
            click.secho(f"error: {line} (G19)", fg="red")
        _fail("рантайм-бюджеты превышены")
    if picks_log.is_file():
        for line in picks_log.read_text(encoding="utf-8").splitlines():
            click.echo(f"путь: {line}")
    if tb.is_file():
        click.secho(tb.read_text(encoding="utf-8", errors="replace")[-1500:], fg="red")
        _fail("smoke: игра упала с traceback")
    if returncode != 0 or not verdict.startswith("OK"):
        _fail(f"smoke: {verdict} (exit {returncode})")
    if record_name:
        import time as _time

        from .qa import QaError, read_run, write_record

        if not record_why:
            raise click.UsageError("--record требует --why: запись без причины через "
                                   "полгода никто не решится ни починить, ни удалить")
        try:
            path = write_record(
                root, record_name, record_why, read_run(root, shots), picks=picks,
                lang=lang, variant=os.environ.get("RENPY_VARIANT", ""),
                content_version=_content_version(root),
                recorded_at=_time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()))
        except QaError as e:
            _fail(str(e))
        click.secho(f"запись повтора: {path.relative_to(root).as_posix()}", fg="green")
    click.secho(f"smoke: {verdict} ({n_shots} скриншотов)", fg="green")


def _content_version(root: Path) -> str:
    """Версия контента прогона — из генерата, а не из project.yaml: сверять надо то,
    на чём игра фактически шла."""
    from .qa import _current_version

    return _current_version(root) or "?"


@test.command("oversample")
@click.option("--scale", default=2.0, help="Во сколько раз физический экран крупнее виртуального.")
@click.option("--timeout", "timeout_s", default=180)
def test_oversample(scale: float, timeout_s: int):
    """Проверить движком, что 4K-варианты реально подхватываются (ADR-0012).

    Единственный способ убедиться в этом честно: решение принимает Ren'Py, а не
    наш конвейер. Команда vn_oversample (framework/90_debug) зовёт настоящий
    Image.get_oversampled_image() на настоящем дереве game/assets."""
    from .doctor import sdk_path

    root = _root()
    sdk = sdk_path()
    if sdk is None:
        _fail("Ren'Py SDK не найден (RENPY_SDK)")
    if not (root / "game" / "generated" / "manifest.json").is_file():
        _fail("game/generated/ пуст — сначала vn build")
    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    proc = subprocess.run([str(exe), str(root), "vn_oversample", "--scale", str(scale)],
                          capture_output=True, text=True, timeout=timeout_s)
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if line.startswith("FAIL"):
            click.secho(line, fg="red")
        elif line.startswith("oversample"):
            click.secho(line, fg="green" if "OK" in line else None)
    if "oversample: OK" not in out:
        _fail("оверсэмпл не подтверждён движком:\n" + out.strip()[-1200:])


@test.command("deck-kit")
@click.option("--timeout", "timeout_s", default=180, show_default=True,
              help="Лимит одного автопилотного прогона, сек.")
def test_deck_kit(timeout_s: int):
    """Комплект приёмки для ЖИВОГО устройства (Steam Deck / ТВ).

    Всё, что можно проверить на build-машине, уже автоматизировано; на железе
    остаётся то, что видно только там — читаемость, Steam Input, сон/пробуждение,
    оверлей, загрузка с eMMC. Команда собирает build/deck-kit/: скриншоты обоих
    окружений, машинную сводку (в т.ч. кегли в ФИЗИЧЕСКИХ пикселях Deck) и
    чек-лист, построенный из docs/handbook/43-steam-qa.md."""
    from .deckkit import KIT_REL, QA_DOC_REL, build_summary, parse_checklist, write_kit

    root = _root()
    if not (root / "game" / "generated" / "manifest.json").is_file():
        _fail("генерат не собран — сначала vn build")
    doc = root / QA_DOC_REL
    if not doc.is_file():
        _fail(f"нет документа приёмки {QA_DOC_REL} — из него строится чек-лист")

    # Экраны меню прохождением не открываются, поэтому снимаем их явно. Набор — из
    # той же декларации, что у vn test screens (content/ui/screens.yaml): хардкод
    # здесь означал бы, что новый экран попадает в один тур и не попадает в другой.
    from .qa import tour_screens

    screens = ",".join(e["name"] for e in tour_screens(root))
    if not screens:
        _fail("content/ui/screens.yaml пуст — комплекту приёмки нечего снимать")
    shots: dict[str, list[Path]] = {}
    for variant, env_variant in (("deck", "steam_deck medium touch"),
                                 ("big_picture", "steam_big_picture")):
        out = root / ".vncache" / f"deck-kit-{variant}"
        rc, timed_out = _autopilot_run(
            root, out,
            {"VN_AUTOPILOT_PICKS": "0", "VN_AUTOPILOT_SCREENS": screens,
             "VN_AUTOPILOT_LANG": "@source", "RENPY_VARIANT": env_variant},
            timeout_s)
        if timed_out or rc != 0:
            _fail(f"прогон в варианте {env_variant!r} не завершился (код {rc})")
        shots[variant] = sorted(out.glob("*.png"))
        if not shots[variant]:
            _fail(f"прогон {variant} не дал ни одного скриншота")

    summary, warnings = build_summary(root)
    for w in warnings:
        click.secho(f"warning: {w}", fg="yellow")

    # Факты автоматики собираем ПРОГОНАМИ, а не декларацией: комплект не должен
    # утверждать «сейвы мигрируют», если корпус сейчас красный.
    automated: list[tuple[str, str]] = []
    from .loc.po import report as loc_report
    from .release import validate_release

    cov = loc_report(root).coverage
    if cov:
        worst = min((c["translated"] / c["total"]) if c["total"] else 1.0
                    for c in cov.values())
        automated.append(("покрытие переводов", f"минимум {worst:.0%} по языкам"))
    checks, ok = validate_release(root, "public")
    fails = [m for st, m in checks if st == "FAIL"]
    automated.append(("релизный гейт (public)",
                      "OK" if ok else f"{len(fails)} FAIL — {fails[0]}"))
    for variant, files in sorted(shots.items()):
        automated.append((f"прогон автопилота [{variant}]",
                          f"{len(files)} скриншотов, вердикт OK"))

    written = write_kit(root, parse_checklist(doc), summary, shots, automated)
    items = parse_checklist(doc)
    click.secho(f"deck-kit: {KIT_REL} готов — {len(written)} файлов, "
                f"{len(items)} пунктов приёмки "
                f"(скриншоты: {', '.join(sorted(shots))})", fg="green")


@test.command("corpus")
@click.option("--scenes", default=100, help="Сколько сцен сгенерировать (главы набираются по 50).")
@click.option("--images", default=100, help="Сколько мастеров образов (bg/spr/shot/cg по долям).")
@click.option("--videos", default=0, help="Видео-мастеров (энкод дорог — по умолчанию без видео).")
@click.option("--lines", default=8, help="Реплик (say) на сцену.")
@click.option("--vars", "variables", default=50, help="Объявленных сохраняемых переменных всего.")
@click.option("--profile", type=click.Choice(["full", "draft"]), default="full",
              help="Профиль энкода ассетов в измеряемой сборке.")
@click.option("--dest", type=click.Path(path_type=Path), default=None,
              help="Каталог корпуса (по умолчанию .vncache/test-corpus — вне git).")
@click.option("--keep", is_flag=True, help="Не удалять корпус после прогона (для разбора генерата).")
def test_corpus(scenes: int, images: int, videos: int, lines: int, variables: int,
                profile: str, dest: Path | None, keep: bool):
    """Синтетический корпус масштаба + измерительный прогон конвейера.

    Строит настоящий проект заданного размера ВНЕ репозитория и гоняет по нему
    assets build -> lint -> compile -> модель памяти, печатая время, память и объём
    генерата. Утверждения о масштабе проверяются числами, а не рассуждением."""
    from .corpus import CorpusError, CorpusSpec, default_dest, format_table, run

    root = _root()
    target = Path(dest) if dest else default_dest(root)
    try:
        rep = run(target, CorpusSpec(scenes=scenes, images=images, videos=videos,
                                     lines=lines, variables=variables),
                  root, profile=profile, keep=keep)
    except CorpusError as e:
        _fail(str(e))
    click.echo(format_table([rep]))
    if keep:
        click.echo(f"корпус оставлен: {target}")
    if not rep.ok:
        _fail("прогон не зелёный: корпус этого масштаба не выдержали конвейер "
              "или бюджеты G19 (строки выше)")
    click.secho("test corpus: OK", fg="green")


@test.command("screens")
@click.option("--timeout", "timeout_s", default=180, help="Лимит прогона, сек.")
@click.option("--variant", default="", help="RENPY_VARIANT прогона (steam_deck, touch small phone…).")
def test_screens(timeout_s: int, variant: str):
    """Тур по экранам из content/ui/screens.yaml: открыть каждый и снять кадр.

    Гейт структурный, а не пиксельный: провал — экран из декларации не открылся или
    отсутствует в игре, либо в игре есть экран, которого нет ни в туре, ни в списке
    исключений. Пиксельных эталонов здесь нет намеренно: они привязаны к окружению,
    в котором сняты, и до устоявшегося UI сопровождать их дороже, чем ловить
    поломки этим гейтом (ADR-0019)."""
    import json as _json

    from .qa import read_run, run_failures, tour_screens

    root = _root()
    tour = tour_screens(root)
    if not tour:
        _fail("content/ui/screens.yaml пуст или отсутствует — туру нечего открывать")
    shots = root / ".vncache" / "screens"
    tour_file = root / ".vncache" / "screens-tour.json"
    tour_file.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(tour_file, _json.dumps(tour, ensure_ascii=False))
    env = {"VN_AUTOPILOT_SCREENS_FILE": str(tour_file)}
    if variant:
        env["RENPY_VARIANT"] = variant
    rc, timed_out = _autopilot_run(root, shots, env, timeout_s)
    art = read_run(root, shots)
    fails = run_failures(art, rc, timed_out, timeout_s)

    declared = {e["name"] for e in tour}
    optional = {e["name"] for e in tour if e.get("optional")}
    ignored = set(tour_screens_ignored(root))
    shown = set(art.screens.get("shown") or [])
    failed = art.screens.get("failed") or {}
    missing = set(art.screens.get("missing") or []) - optional
    defined = set(art.screens.get("defined") or [])

    for name in sorted(shown):
        if not (shots / f"screen_{name}.png").is_file():
            fails.append(f"{name}: экран показан, но кадра screen_{name}.png нет")
    for name, why in sorted(failed.items()):
        fails.append(f"{name}: экран не открылся — {why}")
    for name in sorted(missing):
        fails.append(f"{name}: экран объявлен в туре, но в игре его нет "
                     f"(renpy.has_screen == False)")
    # Экран есть в игре и не покрыт ни туром, ни списком исключений: это и есть
    # «добавили экран, забыли проверять». Движковые (_-префикс) не считаем.
    if defined:
        uncovered = sorted(n for n in defined - declared - ignored
                           if not n.startswith("_"))
        for name in uncovered:
            fails.append(f"{name}: экран есть в игре, но не назван ни в screens, ни в "
                         f"ignore_defined — добавьте его в тур или объясните исключение")

    click.echo(f"экраны: показано {len(shown)} из {len(declared)}; "
               f"кадры -> {shots.relative_to(root).as_posix()}")
    if art.traceback:
        click.secho(art.traceback[-1500:], fg="red")
    if fails:
        for f in fails:
            click.secho(f"error: {f}", fg="red")
        _fail(f"test screens: {len(fails)} проблем")
    click.secho(f"test screens: OK ({len(shown)} экранов, {art.result})", fg="green")


def tour_screens_ignored(root: Path) -> list[str]:
    """Список намеренно не покрытых туром экранов (qa_screens@1: ignore_defined)."""
    from .qa import SCREENS_DECL_REL
    from .repo import load_yaml

    doc = load_yaml(root / SCREENS_DECL_REL) if (root / SCREENS_DECL_REL).is_file() else None
    return list((doc or {}).get("ignore_defined") or [])


@test.command("paths")
@click.option("--picks", "picks_list", multiple=True,
              help="Трасса выборов прогона (можно повторять: --picks 0,0 --picks 1).")
@click.option("--timeout", "timeout_s", default=180, help="Лимит одного прогона, сек.")
@click.option("--strict", is_flag=True,
              help="Непокрытая ветка — ошибка для ЛЮБОГО статуса главы (по умолчанию "
                   "draft даёт предупреждение, G15).")
def test_paths(picks_list: tuple, timeout_s: int, strict: bool):
    """Покрытие ветвления: какие сцены и выборы прогоны реально прошли.

    Полный набор развилок берётся из деклараций — сцены из `exits` (content/chapters)
    и пункты меню из шардированного леджера (`loc/ledger/*.json`), а не из генерата:
    парсить .rpy запрещено (G24). Фактическое покрытие — из артефактов прогона:
    посещённые сцены пишет `vn.checkpoint` в `g.scenes_seen`, взятые выборы —
    `picks.log`."""
    import json as _json

    from .content.graph import build_edges
    from .qa import read_run, run_failures
    from .repo import load_yaml

    root = _root()
    traces = list(picks_list) or [""]
    declared_scenes, _edges = build_edges(root)
    # Рёбра выбора: <menu_id>#<индекс пункта> для каждого пункта каждого меню.
    declared_choices: list[str] = []
    chapter_status: dict[str, str] = {}
    for shard in sorted((root / "loc" / "ledger").glob("*.json")):
        doc = load_yaml(shard) or {}
        for menu_id, menu in sorted((doc.get("menus") or {}).items()):
            for idx in range(len(menu.get("items") or [])):
                declared_choices.append(f"{menu_id}#{idx}")
    for pack_id, chapters_dir in __import__("vn.repo", fromlist=["chapter_zones"]).chapter_zones(root):
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
            meta = load_yaml(d / "chapter.yaml") if (d / "chapter.yaml").is_file() else {}
            chapter_status[d.name[:4]] = str((meta or {}).get("status") or "draft")

    visited: set[str] = set()
    taken: set[str] = set()
    for i, picks in enumerate(traces):
        shots = root / ".vncache" / "paths" / f"run{i}"
        rc, timed_out = _autopilot_run(root, shots, {"VN_AUTOPILOT_PICKS": picks},
                                       timeout_s)
        art = read_run(root, shots)
        fails = run_failures(art, rc, timed_out, timeout_s)
        if fails:
            if art.traceback:
                click.secho(art.traceback[-1200:], fg="red")
            _fail(f"прогон --picks {picks!r}: " + "; ".join(fails))
        # Снапшот плоский: ключи вида "<store>.<имя>" (020_state.rpy: snapshot).
        visited |= {str(s) for s in (art.state.get("g.scenes_seen") or [])}
        taken |= {f"{p.menu_id}#{p.idx}" for p in art.picks}
        click.echo(f"прогон {i + 1}/{len(traces)} (--picks {picks or '—'}): "
                   f"сцен {len(visited)}, выборов {len(taken)}")

    missing_scenes = sorted(set(declared_scenes) - visited)
    missing_choices = sorted(set(declared_choices) - taken)
    out = root / ".vncache" / "paths" / "coverage.json"
    write_text_lf(out, _json.dumps({
        "schema": "qa_coverage@1",
        "runs": len(traces),
        "scenes": {"declared": sorted(declared_scenes), "visited": sorted(visited),
                   "missing": missing_scenes},
        "choices": {"declared": sorted(declared_choices), "taken": sorted(taken),
                    "missing": missing_choices},
    }, ensure_ascii=False, indent=1) + "\n")
    click.echo(f"покрытие: сцены {len(visited)}/{len(declared_scenes)}, выборы "
               f"{len(taken)}/{len(declared_choices)} -> "
               f"{out.relative_to(root).as_posix()}")

    def _severity(item: str) -> str:
        """draft-глава даёт предупреждение, playtest/release — ошибку (G15)."""
        status = chapter_status.get(item[:4], "draft")
        return "error" if (strict or status in ("playtest", "release")) else "warning"

    errors = [m for m in missing_scenes + missing_choices if _severity(m) == "error"]
    warnings = [m for m in missing_scenes + missing_choices if _severity(m) == "warning"]
    _echo_warnings([f"не пройдено: {w} (глава draft — не блокирует)" for w in warnings])
    if errors:
        for e in errors:
            click.secho(f"error: не пройдено: {e}", fg="red")
        _fail(f"test paths: {len(errors)} непройденных ветвей в playtest/release-главах")
    click.secho(f"test paths: OK ({len(traces)} прогонов)", fg="green")


@test.command("replay")
@click.argument("name", required=False)
@click.option("--all", "all_records", is_flag=True, help="Повторить все записи.")
@click.option("--timeout", "timeout_s", default=180, help="Лимит одного прогона, сек.")
def test_replay(name: str | None, all_records: bool, timeout_s: int):
    """Повторить записанный прогон и сверить результат с записью.

    Детерминизм в этом движке складывается из индексов выборов, языка и варианта
    окружения: источника случайности в игре нет (`random` в `game/` не вызывается),
    свободного текстового ввода нет (ADR-0016) — поэтому ни seed, ни лог ввода в
    записи не нужны. Записи делает `vn test smoke --record <имя>`."""
    from .qa import read_run, replay_diff, replay_records, run_failures

    root = _root()
    records = replay_records(root, None if all_records else name)
    if not records:
        _fail("записей нет — создайте: vn test smoke --picks 0,0 --record <имя>")
    failed = 0
    for path, rec in records:
        env = {"VN_AUTOPILOT_PICKS": ",".join(str(i) for i in rec["input"]["picks"])}
        if rec["input"].get("lang"):
            env["VN_AUTOPILOT_LANG"] = rec["input"]["lang"]
        if rec["input"].get("variant"):
            env["RENPY_VARIANT"] = rec["input"]["variant"]
        shots = root / ".vncache" / "replay" / rec["name"]
        rc, timed_out = _autopilot_run(root, shots, env, timeout_s)
        art = read_run(root, shots)
        diffs = run_failures(art, rc, timed_out, timeout_s) + replay_diff(root, rec, art)
        mark = "✓" if not diffs else "✗"
        click.secho(f" {mark} {rec['name']}: {art.result}",
                    fg=("green" if not diffs else "red"))
        for d in diffs:
            click.secho(f"    {d}", fg="red")
        failed += bool(diffs)
    if failed:
        _fail(f"test replay: {failed} из {len(records)} записей не воспроизвелись")
    click.secho(f"test replay: OK ({len(records)} записей)", fg="green")

# ── vn pipeline ───────────────────────────────────────────────────────────────

@main.group()
def pipeline():
    """Окружение production-конвейера DAZ/ComfyUI/ffmpeg (ADR-0006, phase-0.md)."""


@pipeline.command("doctor")
@click.option("--comfyui", "comfy_opt", default=None,
              help="Корень ComfyUI (по умолчанию VN_COMFYUI, затем D:/ и C:/ComfyUI).")
def pipeline_doctor(comfy_opt: str | None):
    """PASS/WARN/FAIL-сводка: Python, ffmpeg/VP9, GPU, CUDA/PyTorch, ComfyUI,
    модели, DAZ, диски, SDK."""
    from .pipeline import run_pipeline_doctor

    sys.exit(run_pipeline_doctor(_root(), comfy_opt))


@pipeline.command("models")
@click.option("--pull", is_flag=True, help="Скачать недостающие модели (auth: none, с докачкой).")
@click.option("--all", "include_optional", is_flag=True,
              help="С --pull: включая опциональные (required: false).")
@click.option("--only", default=None, help="Только перечисленные id (через запятую).")
@click.option("--comfyui", "comfy_opt", default=None, help="Корень ComfyUI.")
def pipeline_models(pull: bool, include_optional: bool, only: str | None, comfy_opt: str | None):
    """Статус моделей по манифесту tools/comfyui-models.yaml; --pull — загрузка.

    Модели с auth: manual (Civitai и т.п.) не качаются автоматически: команда
    печатает точную инструкцию и целевой путь."""
    from .pipeline import PipelineError, comfyui_root, models_table, pull_models

    root = _root()
    comfy = comfyui_root(comfy_opt)
    only_set = {s.strip() for s in only.split(",")} if only else None
    try:
        if pull or only_set:
            sys.exit(pull_models(root, comfy, only=only_set, include_optional=include_optional))
        statuses, _lock = models_table(root, comfy)
    except PipelineError as e:
        _fail(str(e))
    marks = {"ok": ("✓", "green"), "missing": ("✗", "red"),
             "undersized": ("!", "yellow"), "no_root": ("?", "yellow")}
    for st in statuses:
        mark, color = marks[st.state]
        e = st.entry
        size = f"{st.actual_mb:.0f} МБ" if st.actual_mb else (
            f"~{e['size_mb']:.0f} МБ" if e.get("size_mb") else "?")
        note = {"none": "", "civitai_key": " [нужен CIVITAI_API_KEY]",
                "manual": " [ручная установка]"}.get(e["auth"], "")
        req = "" if e["required"] else " (опц.)"
        click.secho(f" {mark} {e['id']:<22} {size:>10}  models/{e['dest']}{req}{note}",
                    fg=color)
        # Правовой статус — второй строкой, а не в общей: ADR-0008 обещает, что он
        # «виден и проверяем этой командой», а до сих пор команда печатала только
        # факт наличия файла. Красным — то, что нельзя использовать коммерчески:
        # решение о таком контенте принимается ДО рендера, а не после.
        legal = f"{e.get('license') or 'лицензия не указана'} / коммерческое: " \
                f"{e.get('commercial_use') or 'не указано'}"
        click.secho(f"     {legal}",
                    fg=(None if e.get("commercial_use") == "allowed" else "red"))
    if comfy is None:
        click.secho("ComfyUI не найден — статусы условны (tools/setup-comfyui.ps1)", fg="yellow")
    click.echo("загрузка: vn pipeline models --pull  (ручные шаги будут перечислены)")


# ── vn release ────────────────────────────────────────────────────────────────

@main.group()
def release():
    """Релизы: changelog из фактического диффа контента, Steam-аплоад."""


@release.command("changelog")
@click.option("--force", is_flag=True,
              help="Писать раздел даже на уже выпущенную версию (перезапись после "
                   "ручной правки CHANGELOG; дифф при этом СЪЕДАЕТСЯ).")
def release_changelog(force: bool):
    """Обновить docs/CHANGELOG.md и ci/release-manifest.json по диффу реестров.

    Порядок обязателен: сначала бамп `project.yaml: version`, потом эта команда.
    Прогон на уже выпущенной версии съедает дифф — добавленные после релиза сцены
    в блок следующей версии не попадут, потому что манифест их уже помнит."""
    from .release import ReleaseError, update_changelog

    try:
        rep = update_changelog(_root(), force=force)
    except ReleaseError as e:
        _fail(str(e))
    if rep.stamped:
        click.echo(f"id_registry: занесено {rep.stamped} выпущенных id (G7)")
    if not rep.changed:
        click.echo("контент не менялся с прошлого манифеста")
        return
    if rep.added_chapters:
        click.echo(f"новые главы: {', '.join(rep.added_chapters)}")
    if rep.added_scenes:
        click.echo(f"новые сцены: {len(rep.added_scenes)}")
    if rep.removed_scenes:
        click.secho(f"удалены сцены: {', '.join(rep.removed_scenes)} — проверьте renames.yaml!",
                    fg="yellow")
    click.secho("changelog обновлён", fg="green")


@release.command("validate")
@click.option("--flavor", required=True, help="Флейвор из project.yaml (public/patron/…).")
def release_validate(flavor: str):
    """Предрелизный гейт: схема, lint, свежесть ассетов/генерата, видео, бюджеты,
    провенанс, DAZ-декларации, хранилище, версии, сейв-корпус."""
    from .release import validate_release

    checks, ok = validate_release(_root(), flavor)
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for state, msg in checks:
        click.secho(f" {state:<4}  {msg}", fg=colors[state])
    if not ok:
        _fail(f"release validate --flavor {flavor}: есть FAIL")
    click.secho(f"release validate: OK (флейвор {flavor})", fg="green")


@release.command("build")
@click.option("--flavor", required=True, help="Флейвор из project.yaml (public/patron/…).")
@click.option("--patron-token", default=None,
              help="Опциональная метка получателя сборки (трассировка утечек).")
@click.option("--package", "packages", multiple=True, default=("win",),
              help="Целевые пакеты launcher distribute.")
@click.option("--timeout", "timeout_s", default=900)
def release_build(flavor: str, patron_token: str | None, packages: tuple, timeout_s: int):
    """Релизная сборка флейвора: гейт -> game/build_id.json -> vn package
    (classify исключает NSFW-ассеты для SFW-флейворов) -> build-info в dist.

    build_id.json живёт только на время сборки: dev-запуски остаются флейвором
    dev, а вотермарка не течёт в рабочие прогоны."""
    from .release import (ReleaseError, clear_build_info, compute_build_info,
                          validate_release, write_build_info)

    root = _root()
    ctx = click.get_current_context()
    # Сборка ДО гейта: в свежем чекауте (CI) генерата нет вовсе, и проверка
    # «генерат свеж» валила бы каждый релиз. Плюс так гейт проверяет ровно то
    # состояние, которое уедет в дистрибутив, а не предыдущее.
    click.secho(f"сборка перед гейтом (флейвор {flavor})…", fg="cyan")
    ctx.invoke(build, check=False, profile="full")

    checks, ok = validate_release(root, flavor)
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for state, msg in checks:
        click.secho(f" {state:<4}  {msg}", fg=colors[state])
    if not ok:
        _fail(f"release build --flavor {flavor}: гейт не пройден")

    try:
        info = compute_build_info(root, flavor, patron_token=patron_token)
        write_build_info(root, info)
    except ReleaseError as e:
        _fail(str(e))
    # Уведомления о сторонних лицензиях обязаны ехать с игрой (BSD/Apache/OFL).
    notices = root / "docs" / "licenses" / "THIRD-PARTY-NOTICES.md"
    if notices.is_file():
        import shutil as _shutil
        _shutil.copy(notices, root / "game" / "THIRD-PARTY-NOTICES.md")
    click.echo(f"build-id: {info['build_id']}"
               + (f" (исключено: {', '.join(info['exclude'])})" if info["exclude"] else ""))
    try:
        ctx.invoke(package, packages=packages, timeout_s=timeout_s,
                   dest_suffix=f"-{flavor}")
        dist = root / "build" / "dist" / f"{info['version']}-{flavor}"
        write_text_lf((dist / "build-info.json"),
            json.dumps(info, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    finally:
        clear_build_info(root)   # dev-чекаут не должен носить чужой флейвор
        (root / "game" / "THIRD-PARTY-NOTICES.md").unlink(missing_ok=True)
    click.secho(f"release build: OK — {info['build_id']} -> "
                f"build/dist/{info['version']}-{flavor}/", fg="green")


@release.command("preflight")
@click.option("--flavor", default="public", show_default=True,
              help="Флейвор, чьи артефакты проверять.")
def release_preflight(flavor: str):
    """Готовность к Steam-поставке ДО получения App ID.

    Отвечает на вопрос «если App ID появится сейчас, что останется сделать»:
    депоты, библиотеки Valve, артефакты сборки, готовый список ачивок для
    партнёрки, DLC-маппинг паков и корень Auto-Cloud. Пустой App ID — пункт
    TODO, а не провал: команда полезна именно в этом состоянии (exit 0, пока
    нет настоящих ошибок)."""
    from .release import steam_preflight

    root = _root()
    color = {"PASS": "green", "TODO": "cyan", "WARN": "yellow", "FAIL": "red"}
    checks = steam_preflight(root, flavor)
    for state, msg in checks:
        click.secho(f" {state:4} {msg}", fg=color.get(state))
    failures = [m for st, m in checks if st == "FAIL"]
    if failures:
        _fail(f"steam preflight: {len(failures)} ошибок")
    todo = sum(1 for st, _ in checks if st == "TODO")
    click.secho(f"steam preflight: OK ({todo} шагов за владельцем аккаунта)", fg="green")


@release.command("steam")
@click.option("--flavor", required=True, help="Флейвор собранного дистрибутива.")
@click.option("--branch", default="", help="SetLive-ветка steamcmd (например beta); пусто = не публиковать.")
def release_steam(flavor: str, branch: str):
    """Подготовка Steam-выкладки: раскладка депотов + VDF для steamcmd.

    Генерирует build/steam/app_build_<flavor>.vdf и распаковывает зипы
    distribute в build/steam/content/. Сам аплоад — steamcmd с credentials
    ВНЕ репозитория (ci/steam/README.md)."""
    from .doctor import sdk_path
    from .release import (ReleaseError, steam_app_build, steam_libs_status,
                          steam_stage_content)

    root = _root()
    try:
        vdf, warnings = steam_app_build(root, flavor, branch=branch)
    except ReleaseError as e:
        _fail(str(e))
    _echo_warnings(warnings)
    for lib in steam_libs_status(sdk_path()):
        click.secho(f"warning: в SDK нет {lib} — дистрибутив будет standalone, "
                    f"не Steam-сборкой (ci/steam/README.md)", fg="yellow")
    staged, errors = steam_stage_content(root, flavor)
    for e in errors:
        click.secho(f"error: {e}", fg="red")
    if errors:
        _fail("steam: контент депотов не собран")
    out = root / "build" / "steam" / f"app_build_{flavor}.vdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(out, vdf)
    click.secho(f"steam: {out.relative_to(root)} готов; платформы: "
                f"{', '.join(staged)}; аплоад: steamcmd +run_app_build (README)",
                fg="green")


# ── vn release android (мобильный канал) ──────────────────────────────────────
# Домена android в C13 нет и не вводится: Android — ещё один КАНАЛ поставки, как
# Steam, поэтому его команды живут рядом с vn release steam. В vn package их место
# было бы неверным: package — это launcher distribute (win/linux/mac/market), а у
# Android другая команда лаунчера (android_build), свой тулчейн и свои потолки.

@release.group("android")
def release_android():
    """Мобильный канал: готовность тулчейна, предпосылки поставки, сборка APK/AAB."""


@release_android.command("setup")
@click.argument("step", type=click.Choice(["sdk", "keys", "config"]))
@click.option("--download-rapt", is_flag=True,
              help="Перед шагом sdk скачать RAPT с renpy.org (в архив SDK он не входит).")
def release_android_setup(step: str, download_rapt: bool):
    """Довести проект до готовности собирать Android-пакет: STEP = sdk | keys | config.

    \b
    sdk     — RAPT + Android SDK/NDK в пиннованный SDK (нужен интернет)
    keys    — android.keystore и bundle.keystore в корне проекта
    config  — android.json: имя пакета, ориентация, магазин, permissions

    Шаги ИНТЕРАКТИВНЫЕ и вызывают те же функции RAPT, что и лаунчер: sdk просит
    принять Android SDK Terms and Conditions, keys — подтвердить, что вы сделаете
    копию ключа. Ключ подписи не заменяем и не восстанавливаем: его потеря =
    невозможность обновить опубликованное приложение. Отвечайте в приглашениях сами."""
    from .android import AndroidError, install_rapt, setup_step
    from .doctor import sdk_path
    from .repo import load_project

    root = _root()
    sdk = sdk_path()
    if sdk is None:
        _fail("RENPY_SDK не задан — тулчейн живёт внутри пиннованного SDK (vn doctor)")
    try:
        if download_rapt:
            for msg in install_rapt(sdk, load_project(root)["renpy_sdk"]):
                click.secho(msg, fg="green")
        rc = setup_step(root, sdk, step)
    except AndroidError as e:
        _fail(str(e))
    if rc != 0:
        _fail(f"шаг {step} вернул {rc} — см. вывод выше")
    click.secho(f"android setup {step}: OK (что осталось — vn release android status)",
                fg="green")


@release_android.command("status")
def release_android_status():
    """Чего не хватает для сборки: RAPT, Android SDK, JDK, ключи подписи, конфиг.

    Установку CLI не делает и не изображает: у Ren'Py её вне лаунчера нет, поэтому
    каждый пункт называет свой штатный шаг лаунчера."""
    from .android import rapt_status
    from .doctor import sdk_path

    gaps = rapt_status(sdk_path(), _root())
    for gap in gaps:
        click.secho(f" - {gap}", fg="yellow")
    if gaps:
        _fail("android: тулчейн не готов — закройте пункты выше (подготовка: "
              "vn release android setup sdk|keys|config) и повторите")
    click.secho("android status: OK — тулчейн готов", fg="green")


@release_android.command("preflight")
@click.option("--bundle", is_flag=True,
              help="Правила Play-бандла (.aab): +пофайловый лимит 500 МБ к потолку канала.")
def release_android_preflight(bundle: bool):
    """Предпосылки проекта: размер против потолка канала, пофайловый лимит бандла,
    мобильный бюджет памяти образов, утечка ключей подписи, оформление приложения.

    Секунды проверок против часа gradle-сборки, которая упадёт на том же самом."""
    from .android import preflight

    rep = preflight(_root(), bundle=bundle)
    click.echo(f"game/: {rep.game_mb:.1f} МБ, из них @N-вариантов {rep.oversample_mb:.1f} МБ "
               f"(в мобильный пакет не едут) -> {rep.mobile_mb:.0f} МБ с накладными")
    click.echo(f"кэш образов мобильного профиля: {rep.mobile_cache_mb} МБ")
    _echo_warnings(rep.warnings)
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if not rep.ok:
        _fail("android preflight: есть блокеры — мобильная сборка не запускается")
    click.secho("android preflight: OK", fg="green")


@release_android.command("build")
@click.option("--bundle", is_flag=True, help="Play-бандл (.aab) для стора вместо universal APK.")
@click.option("--install", is_flag=True, help="Поставить на подключённое устройство (adb).")
@click.option("--launch", is_flag=True, help="Запустить после установки (подразумевает --install).")
@click.option("--timeout", "timeout_s", default=3600,
              help="Лимит сборки, сек: первая тянет gradle и зависимости — она самая долгая.")
def release_android_build(bundle: bool, install: bool, launch: bool, timeout_s: int):
    """Сборка мобильного пакета: vn build -> предполётные проверки -> android_build.

    Лог RAPT/gradle не перехватывается: сборка идёт минутами, и молчащий процесс
    не отличить от зависшего."""
    from .android import AndroidError, build_apk
    from .doctor import sdk_path

    root = _root()
    ctx = click.get_current_context()
    # Тулчейн — ПЕРВЫМ, до полной сборки: без RAPT/JDK/ключей сборка всё равно не
    # состоится, и узнать это после assets build + compile обиднее, чем сразу.
    # Вызовом команды, а не копией проверки: build_apk сверит тулчейн ещё раз сам
    # (он публичная точка входа), но формулировки пунктов живут в одном месте.
    ctx.invoke(release_android_status)
    ctx.invoke(build, check=False, profile="full")
    try:
        res = build_apk(root, sdk_path(), bundle=bundle, install=install,
                        launch=launch, timeout_s=timeout_s)
    except AndroidError as e:
        _fail(str(e))
    click.echo("команда: " + " ".join(res.command))
    for line in res.facts:
        click.echo(line)
    for w in res.warnings:
        click.secho("warning: " + w, fg="yellow")
    if res.errors:
        # Артефакт на диске остаётся намеренно: понять, чем пакет раздут, можно
        # только по нему. Но зелёным такой прогон называть нельзя.
        for e in res.errors:
            click.secho("ошибка: " + e, fg="red")
        _fail("пакет собран, но не проходит потолки канала — "
              + ", ".join(p.relative_to(root).as_posix() for p in res.artifacts))
    click.secho("android build: OK — " + ", ".join(
        p.relative_to(root).as_posix() for p in res.artifacts), fg="green")
# ── vn pack ───────────────────────────────────────────────────────────────────

@main.group()
def pack():
    """DLC/voice-паки (раздел 6, G9/G10)."""


@pack.command("validate")
def pack_validate():
    """Манифесты паков: схема, api_level против фасада vn.*, структура."""
    from .content.compile import VN_API_LEVEL, _collect_packs
    from .schemas import SchemaRegistry

    root = _root()
    registry = SchemaRegistry(root / "tools" / "schemas")
    errors: list[str] = []
    inputs = {}

    def src(p):
        rel = p.relative_to(root).as_posix()
        inputs[rel] = "-"
        return rel, "-"

    packs = _collect_packs(root, src, registry, errors)
    for e in errors:
        click.secho(f"error: {e}", fg="red")
    if errors:
        _fail(f"pack validate: {len(errors)} ошибок")
    for pid, m in sorted(packs.items()):
        click.echo(f" ✓ {pid}: {m['kind']} v{m['version']}, api_level "
                   f"[{m['api_level']['min']}, {m['api_level']['below']}) (фасад {VN_API_LEVEL})")
    click.secho(f"pack validate: OK ({len(packs)} паков)", fg="green")


@pack.command("build")
@click.argument("pack_id")
def pack_build(pack_id: str):
    """Содержимое Steam-депота пака: генерат его глав + манифест -> build/packs/<id>.zip.
    Скрипты пака грузятся всегда (управлять загрузкой нельзя, G9) — гейт логический."""
    import zipfile

    root = _root()
    manifest = root / "packs" / pack_id / "manifest.yaml"
    if not manifest.is_file():
        _fail(f"пака {pack_id!r} нет (packs/{pack_id}/manifest.yaml)")
    from .repo import load_yaml
    chapters = [d.name[:4] for d in sorted((root / "packs" / pack_id / "chapters").glob("ch*"))
                if d.is_dir()]
    gen = root / "game" / "generated"
    # Список сцен собираем ДО открытия архива: иначе «нет генерата» обнаруживается,
    # когда неполный zip уже лежит в build/packs/ и может уехать в депот.
    scenes = [(f, f"game/generated/scenes/{ch}/{f.name}")
              for ch in chapters
              for f in sorted((gen / "scenes" / ch).glob("*")) if f.is_file()]
    # Счёт сцен отдельно от манифеста: манифест есть всегда, и общий счётчик делал
    # охранник недостижимым. Ноль сцен сам по себе не ошибка — пак-контейнер (nsfw)
    # везёт только ассеты и глав не объявляет. Ошибка — когда главы объявлены, а
    # генерата для них нет: типовая причина — забыли vn build.
    if chapters and not scenes:
        _fail(f"pack build: у пака {pack_id!r} объявлены главы ({', '.join(chapters)}), но в "
              f"game/generated/scenes/ нет ни одной их скомпилированной сцены — сначала vn build")
    out = root / "build" / "packs" / f"{pack_id}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(manifest, f"packs/{pack_id}/manifest.yaml")
        for f, arcname in scenes:
            z.write(f, arcname)
    # Без этой строки архив из одного манифеста выглядит поломкой сборки, а не
    # нормой пака-контейнера — пусть решает человек, а не молчание команды.
    if not chapters:
        click.secho(f"warning: пак {pack_id!r} не объявляет глав (packs/{pack_id}/chapters/ пуст) "
                    f"— в архиве только манифест", fg="yellow")
    click.secho(f"pack build: OK — {out.relative_to(root).as_posix()} ({1 + len(scenes)} файлов, "
                f"главы: {', '.join(chapters) or '—'})", fg="green")


if __name__ == "__main__":
    main()
