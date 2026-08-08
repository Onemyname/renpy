"""vn — единая точка входа (G1). Домены: bootstrap|doctor|dev|build|play|package|migrate|shell,
assets, content, scene, chapter, char, loc, voice, save, test, release, pack.

Фаза 0: работают doctor, build, play, content lint|compile. Остальное — честные заглушки
с номером фазы (раздел 8 ARCHITECTURE.md), а не тихие no-op.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from . import __version__
from .repo import RepoError, find_root


def _fail(msg: str) -> "None":
    click.secho(f"ошибка: {msg}", fg="red", err=True)
    sys.exit(1)


def _root() -> Path:
    try:
        return find_root()
    except RepoError as e:
        _fail(str(e))


def _stub(phase: int):
    def cmd(*args, **kwargs):
        click.secho(f"эта команда появится в фазе {phase} (раздел 8 ARCHITECTURE.md)", fg="yellow")
        sys.exit(3)   # 3 = «не реализовано в этой фазе»; 2 занят click за usage error
    return cmd


@click.group()
@click.version_option(__version__, prog_name="vn")
def main():
    """Единственный CLI проекта (ARCHITECTURE.md, G1).

    Exit-коды: 0 — успех; 1 — ошибка проверки/сборки; 2 — usage error; 3 — команда
    ещё не реализована (номер фазы в сообщении).
    """
    # Windows-консоль/пайп по умолчанию в locale-кодировке (cp1251): без этого
    # русские сообщения в CI — кракозябры, а '✓' в doctor — UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# ── Верхний уровень ───────────────────────────────────────────────────────────

@main.command()
def doctor():
    """Самодиагностика окружения."""
    from .doctor import run_doctor
    sys.exit(run_doctor())


def _assets_build(root, profile: str, only_transforms: set[str] | None = None):
    from .assets.pipeline import build_assets

    res = build_assets(root, profile=profile, only_transforms=only_transforms)
    for w in res.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
def build(check: bool, profile: str):
    """Схемы -> lint -> сборка ассетов -> компиляция контента в game/generated/."""
    from .content.compile import CompileError, compile_content
    from .content.lint import lint

    root = _root()
    rep = lint(root)
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
    for w in res.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
    """Размер-бюджеты (G19): превышение = красная сборка, а не сюрприз в релизе."""
    from .release import budget_failures

    failures = budget_failures(root)
    if failures:
        for f in failures:
            click.secho(f"бюджет: {f}", fg="red")
        _fail("бюджеты G19 превышены (project.yaml: budgets)")


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
    for w in res.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
            for w in res.warnings:
                click.secho(f"warning: {w}", fg="yellow")
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
    def _semver_key(p: Path):
        try:
            return tuple(int(x) for x in p.name.split("."))
        except ValueError:
            return (0,)

    cache_root = root / "build" / "rpyc-cache"
    caches = sorted((p for p in cache_root.iterdir() if p.is_dir()),
                    key=_semver_key) if cache_root.is_dir() else []
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

    # 5) Кэш .rpyc этого релиза — для переноса имён в следующем (G6): весь game/
    save_dir = cache_root / version
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
    click.echo(f"rpyc-кэш релиза: {n} файлов -> build/rpyc-cache/{version}/")
    click.secho(f"package: OK — {', '.join(artifacts)}", fg="green")
main.command(name="migrate", help="Миграции схем деклараций (фаза 2).")(_stub(2))
main.command(name="shell", help="Docker-репро CI-окружения (фаза 2).")(_stub(2))


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
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
    for w in res.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
        Path(out).write_text(text, encoding="utf-8")
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
    for w in ares.warnings:
        click.secho(f"warning: {w}", fg="yellow")
    if ares.errors:
        for e in ares.errors:
            click.secho(f"error: {e}", fg="red")
        _fail(f"assets: {len(ares.errors)} ошибок в сырцах")
    for rel in ares.stale:
        click.secho(f"warning: несвежий выход: assets/{rel} (vn assets build)", fg="yellow")
    # 2) Уровень контента: реестр образов + music-треки (check ничего не пишет).
    try:
        res = compile_content(root, check=True)
    except CompileError as e:
        _fail(str(e))
    for w in res.warnings:
        click.secho(f"warning: {w}", fg="yellow")
    n_warn = len(ares.warnings) + len(ares.stale) + len(res.warnings)
    click.secho(f"assets validate: OK ({n_warn} предупреждений)", fg="green")


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
        for w in warnings:
            click.secho(f"warning: {w}", fg="yellow")
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
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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


@assets_provenance.command("verify")
@click.option("--scope", default=None, help="Подпуть в assets_src.")
def assets_provenance_verify(scope: str | None):
    """Сверка всех провенанс-цепочек: схема, хэш артефакта, хэши источников
    (локально или по манифестам хранилища)."""
    from .assets.provenance import verify

    rep = verify(_root(), scope=scope)
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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

_stub_group("char", "Персонажи: new, validate, sheet (раздел 4).", {"new": 1, "validate": 1, "sheet": 2})
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
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
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
_stub_group("voice", "Озвучка (C5).", {"manifest": 2, "import": 2, "tts": 2, "validate": 2})
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


_AUTOPILOT_RPY = (
    "# AUTO-GENERATED by vn (test smoke / save corpus) — временный файл, удаляется после.\n"
    "# Всё гейтится на VN_AUTOPILOT: даже осиротевший .rpyc без env-переменной мёртв.\n"
    "label main_menu:\n"
    "    if not vn_qa.autopilot_active():\n"
    "        $ renpy.quit(save=False)   # осиротевший прогон-файл вне smoke: не играем сами с собой\n"
    "    # Одно выражение, без runtime-import: rollback-лог записал бы модуль в сейв.\n"
    "    $ vn_qa.autopilot_boot()\n"
    "    return\n\n"
    "init python:\n"
    "    if vn_qa.autopilot_active():\n"
    '        config.overlay_screens.append("vn_autopilot")\n\n'
    "screen vn_autopilot():\n"
    "    timer 0.6 action Function(vn_qa.autopilot_tick) repeat True\n"
)


def _autopilot_run(root: Path, shots: Path, extra_env: dict, timeout_s: int,
                   savedir: Path | None = None) -> tuple[int, bool]:
    """Прогон игры автопилотом ВНУТРИ её процесса. Возвращает (returncode, timed_out).
    Никакого синтетического ввода на рабочий стол — только in-process автоматизация."""
    import shutil
    import subprocess

    from .doctor import sdk_path

    sdk = sdk_path()
    if sdk is None:
        _fail("Ren'Py SDK не найден (RENPY_SDK) — vn doctor подскажет")
    if not (root / "game" / "generated" / "manifest.json").is_file():
        _fail("game/generated/ пуст — сначала vn build")

    if shots.exists():
        shutil.rmtree(shots)
    shots.mkdir(parents=True)

    # Пречистка qa/: осиротевший autopilot.rpyc от жёстко убитого прошлого прогона
    # превратил бы обычный vn play в самопроигрывающуюся игру.
    qa_dir = root / "game" / "generated" / "qa"
    if qa_dir.exists():
        shutil.rmtree(qa_dir)
    qa_dir.mkdir(parents=True)
    autopilot = qa_dir / "autopilot.gen.rpy"
    autopilot.write_text(_AUTOPILOT_RPY, encoding="utf-8")

    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    env = dict(os.environ, VN_AUTOPILOT="1", VN_AUTOPILOT_DIR=str(shots), **extra_env)
    cmd = [str(exe), str(root)]
    if savedir is not None:
        cmd += ["--savedir", str(savedir)]
    tb = root / "traceback.txt"
    if tb.is_file():
        tb.unlink()
    timed_out = False
    popen = subprocess.Popen(cmd, env=env, start_new_session=(sys.platform != "win32"))
    try:
        returncode = popen.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = -1
        # renpy.exe — лаунчер: убивать нужно ВСЁ дерево, иначе игра остаётся жить.
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(popen.pid)],
                           capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(popen.pid), signal.SIGKILL)
        popen.wait(timeout=10)
    finally:
        for p in (autopilot, autopilot.with_suffix(".rpyc")):
            if p.is_file():
                p.unlink()
        try:
            qa_dir.rmdir()
        except OSError:
            pass
    return returncode, timed_out


@test.command("smoke")
@click.option("--picks", default="", help="Индексы выборов в меню через запятую (например 0,1).")
@click.option("--lang", default="", help="Язык прогона (код пакета loc/po/<code>/, включая pseudo).")
@click.option("--timeout", "timeout_s", default=180, help="Лимит прогона, сек.")
def test_smoke(picks: str, lang: str, timeout_s: int):
    """Автопрохождение игры автопилотом: авто-advance, авто-выбор, скриншоты движка."""
    root = _root()
    if lang:
        from .loc.po import LocError, source_language

        try:
            src_code = source_language(root).code
        except LocError:
            src_code = None
        if lang == src_code:
            # Исходный язык: tl/<code>/ не существует по определению — прогон
            # с явным сбросом на language=None (маркер @source в автопилоте)
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
    startup_file = shots / "startup.txt"
    if startup_file.is_file():
        from .repo import load_project

        cold = float(startup_file.read_text().strip())
        click.echo(f"cold start (init -> первая интеракция): {cold:.2f} c")
        budget = (load_project(root).get("budgets") or {}).get("cold_start_s")
        if budget and cold > budget:
            _fail(f"cold start {cold:.2f} c > бюджета {budget} c (G19)")
    if picks_log.is_file():
        for line in picks_log.read_text(encoding="utf-8").splitlines():
            click.echo(f"путь: {line}")
    if tb.is_file():
        click.secho(tb.read_text(encoding="utf-8", errors="replace")[-1500:], fg="red")
        _fail("smoke: игра упала с traceback")
    if returncode != 0 or not verdict.startswith("OK"):
        _fail(f"smoke: {verdict} (exit {returncode})")
    click.secho(f"smoke: {verdict} ({n_shots} скриншотов)", fg="green")


for _cmd, _phase in {"replay": 2, "screens": 3, "paths": 2}.items():
    test.command(name=_cmd, help=f"Появится в фазе {_phase} (раздел 8).")(_stub(_phase))

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
    if comfy is None:
        click.secho("ComfyUI не найден — статусы условны (tools/setup-comfyui.ps1)", fg="yellow")
    click.echo("загрузка: vn pipeline models --pull  (ручные шаги будут перечислены)")


# ── vn release ────────────────────────────────────────────────────────────────

@main.group()
def release():
    """Релизы: changelog из фактического диффа контента, Steam-аплоад."""


@release.command("changelog")
def release_changelog():
    """Обновить docs/CHANGELOG.md и ci/release-manifest.json по диффу реестров."""
    from .release import update_changelog

    rep = update_changelog(_root())
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
    click.echo(f"build-id: {info['build_id']}"
               + (f" (исключено: {', '.join(info['exclude'])})" if info["exclude"] else ""))
    ctx = click.get_current_context()
    try:
        ctx.invoke(package, packages=packages, timeout_s=timeout_s,
                   dest_suffix=f"-{flavor}")
        dist = root / "build" / "dist" / f"{info['version']}-{flavor}"
        (dist / "build-info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
    finally:
        clear_build_info(root)   # dev-чекаут не должен носить чужой флейвор
    click.secho(f"release build: OK — {info['build_id']} -> "
                f"build/dist/{info['version']}-{flavor}/", fg="green")


release.command("steam", help="Steam-аплоад депотов (фаза 3: нужен аккаунт партнёра).")(_stub(3))
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
    out = root / "build" / "packs" / f"{pack_id}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(manifest, f"packs/{pack_id}/manifest.yaml")
        n += 1
        for ch in chapters:
            for f in sorted((gen / "scenes" / ch).glob("*")) if (gen / "scenes" / ch).is_dir() else []:
                z.write(f, f"game/generated/scenes/{ch}/{f.name}")
                n += 1
    if not n:
        _fail(f"pack build: у пака {pack_id!r} нет скомпилированных сцен — сначала vn build")
    click.secho(f"pack build: OK — {out.relative_to(root).as_posix()} ({n} файлов, "
                f"главы: {', '.join(chapters)})", fg="green")


if __name__ == "__main__":
    main()
