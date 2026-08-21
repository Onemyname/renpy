"""Вызов build-bridge: разбор авторских scene.rpy парсером Ren'Py из пиннованного SDK (G24).

Мост — команда vn_analyze, зарегистрированная в game/framework/00_core/050_build_bridge.rpy.
Результат кэшируется в .vncache/ по blake3 набора (путь, хэш) входных файлов:
неизменённые сцены не требуют перезапуска движка.

Список сцен уезжает в мост ФАЙЛОМ (--files-from), а не аргументами командной
строки. Аргументами он не влезает: argv ограничен ARG_MAX (macOS 25.5: 1 048 576 Б
на argv+env, под сами аргументы остаётся ~950 КБ), а путь сцены — 100–180 Б.
Измерено на этой машине прямой пробой execve: путь 101 Б (боевое дерево) — 9 468
аргументов, 177 Б (корпус в /private/tmp) — 5 599. То есть argv давал потолок
~6–9 тыс. сцен при заявленных десятках тысяч, и на корпусе 8 000 сцен компиляция
падала сырым OSError [Errno 7] Argument list too long — без диагностики и без
обхода: кэш анализа заполняется только после успешного прогона, поэтому падал и
повторный запуск.

Батчинг (нарезать файлы чанками под ARG_MAX) отвергнут осознанно: каждый запуск
моста — это init ВСЕГО проекта, а он растёт вместе с контентом, потому что Ren'Py
читает game/**.rpy, включая game/generated. Измерено (одна сцена на входе, тёплые
.rpyc): демо-глава — 0.27 c, корпус 8 000 сцен — 4.2 c, корпус 20 000 сцен —
12.5 c. Один запуск со всем списком: 8.0 c и 23.0 c соответственно. Чанки по
5 000 сцен дали бы на 20 000 четыре запуска — ~60 c вместо 23 c, и цена росла бы
квадратично по контенту. Файл-список стоит один write и снимает потолок целиком.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import blake3
from ..repo import write_text_lf


class AnalyzeError(RuntimeError):
    pass


# Имена рабочих файлов в .vncache: список входов для моста и его выход. Оба
# перезаписываются каждым прогоном и остаются на диске только после падения —
# чтобы упавший вызов можно было повторить руками теми же входами.
FILES_FROM_NAME = "analyze-files.txt"
OUT_NAME = "analyze-last.json"


def sdk_renpy_exe() -> Path:
    env = os.environ.get("RENPY_SDK")
    if not env:
        raise AnalyzeError(
            "RENPY_SDK не установлен, а в content/ есть главы: компиляция сцен требует "
            "парсер Ren'Py из пиннованного SDK (G24). vn doctor подскажет установку."
        )
    sdk = Path(env)
    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    if not exe.is_file():
        raise AnalyzeError(f"RENPY_SDK указывает на {sdk}, но {exe.name} там нет")
    return exe


def write_files_listing(path: Path, files: list[Path]) -> Path:
    """Файл-список для моста: по пути на строку, UTF-8, перевод строки — всегда \\n.

    Формат тот же, что у `xargs -a` и `gcc @file`: он читается человеком и его
    можно скормить мосту руками. Перевод строки внутри пути сделал бы список
    неоднозначным, поэтому это ошибка, а не повод молча потерять сцену.
    """
    bad = [f for f in files if "\n" in str(f) or "\r" in str(f)]
    if bad:
        raise AnalyzeError(
            "перевод строки в пути сцены — такой путь нельзя передать мосту "
            "списком: %s" % ", ".join(repr(str(f)) for f in bad[:3])
        )
    path.write_text("".join(f"{f}\n" for f in files), encoding="utf-8", newline="\n")
    return path


def analyze_scene_files(root: Path, files: list[Path]) -> dict:
    """{абсолютный путь -> {labels, jumps, calls, returns, menus, says, errors}}."""
    if not files:
        return {}

    cache_key = blake3.blake3()
    # Версия моста и тулинга — часть ключа: изменение анализатора инвалидирует кэш.
    from .. import __version__
    cache_key.update(__version__.encode("utf-8"))
    bridge = root / "game" / "framework" / "00_core" / "050_build_bridge.rpy"
    if bridge.is_file():
        cache_key.update(bridge.read_bytes())
    for f in sorted(files):
        cache_key.update(str(f).encode("utf-8"))
        cache_key.update(f.read_bytes())
    cache_dir = root / ".vncache"
    cache_file = cache_dir / f"analyze-{cache_key.hexdigest()[:24]}.json"
    if cache_file.is_file():
        return json.loads(cache_file.read_text(encoding="utf-8"))["files"]

    exe = sdk_renpy_exe()
    cache_dir.mkdir(exist_ok=True)
    out = cache_dir / OUT_NAME
    listing = write_files_listing(cache_dir / FILES_FROM_NAME, files)
    cmd = [str(exe), str(root), "vn_analyze", str(out), "--files-from", str(listing)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except OSError as e:
        # Голый OSError от execve («Argument list too long», «Exec format error»)
        # ничего не говорит о том, что именно делал компилятор — контракт CLI
        # требует сообщения, а не трейсбека из недр subprocess.
        raise AnalyzeError(
            f"не запустить build-bridge ({exe}) на {len(files)} сценах: {e}") from e
    if proc.returncode != 0 or not out.is_file():
        raise AnalyzeError(
            "build-bridge (renpy vn_analyze) упал: код %s\nсписок входов: %s\n"
            "stdout: %s\nstderr: %s"
            % (proc.returncode, listing, proc.stdout[-2000:], proc.stderr[-2000:])
        )
    data = json.loads(out.read_text(encoding="utf-8"))
    write_text_lf(cache_file, json.dumps(data, ensure_ascii=False))
    out.unlink()
    listing.unlink()
    return data["files"]
