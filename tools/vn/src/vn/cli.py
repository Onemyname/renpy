"""vn — единая точка входа (G1). Домены: bootstrap|doctor|dev|build|play|package|migrate|shell,
assets, content, scene, chapter, char, loc, voice, save, test, release, pack.

Фаза 0: работают doctor, build, play, content lint|compile. Остальное — честные заглушки
с номером фазы (раздел 8 ARCHITECTURE.md), а не тихие no-op.
"""

from __future__ import annotations

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


@main.command()
@click.option("--check", is_flag=True, help="Проверить без записи: свеж ли генерат (CI-режим, G1).")
def build(check: bool):
    """Схемы -> lint -> компиляция контента в game/generated/."""
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
    click.secho("build: OK", fg="green")


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


main.command(name="bootstrap", help="Скачивание собранных зон из remote cache (фаза 1).")(_stub(1))
main.command(name="dev", help="Комбинированный цикл разработчика: watch + игра (фаза 1).")(_stub(1))
main.command(name="package", help="Сборка дистрибутивов (фаза 2).")(_stub(2))
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


content.command("graph", help="Экспорт графа сцен в DOT/Mermaid (фаза 1).")(_stub(1))


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


scene.command("stub", help="Placeholder-сцена для объявленной цели перехода (фаза 1).")(_stub(1))


# ── Остальные домены (заглушки с номером фазы) ────────────────────────────────

def _stub_group(name: str, help_text: str, commands: dict[str, int]):
    grp = click.Group(name=name, help=help_text)
    for cmd_name, phase in commands.items():
        grp.command(name=cmd_name, help=f"Появится в фазе {phase} (раздел 8 ARCHITECTURE.md).")(_stub(phase))
    main.add_command(grp)


# Номера фаз — по разделу 8 ARCHITECTURE.md (сверено верификацией фазы 0).
_stub_group("assets", "Конвейер ассетов (раздел 2).", {
    "build": 1, "validate": 1, "watch": 1, "pull": 1, "push": 1, "lock": 1, "status": 1,
})
_stub_group("char", "Персонажи: new, validate, sheet (раздел 4).", {"new": 1, "validate": 1, "sheet": 2})
_stub_group("loc", "Локализация (раздел 5).", {"extract": 2, "import": 2, "report": 2, "pseudo": 2, "keys": 2})
_stub_group("voice", "Озвучка (C5).", {"manifest": 2, "import": 2, "tts": 2, "validate": 2})
_stub_group("save", "Сейвы: check, migrate, corpus (раздел 6).", {"check": 2, "migrate": 2, "corpus": 2})
_stub_group("test", "QA-прогоны (7.4): smoke, replay, screens, paths.", {"smoke": 1, "replay": 2, "screens": 3, "paths": 2})
_stub_group("release", "Релизы: changelog, Steam-аплоад (раздел 7).", {"changelog": 2, "steam": 2})
_stub_group("pack", "Сборка DLC/voice-паков (раздел 6).", {"build": 3, "validate": 3})


if __name__ == "__main__":
    main()
