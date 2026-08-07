"""Вызов build-bridge: разбор авторских scene.rpy парсером Ren'Py из пиннованного SDK (G24).

Мост — команда vn_analyze, зарегистрированная в game/framework/00_core/050_build_bridge.rpy.
Результат кэшируется в .vncache/ по blake3 набора (путь, хэш) входных файлов:
неизменённые сцены не требуют перезапуска движка.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import blake3


class AnalyzeError(RuntimeError):
    pass


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
    out = cache_dir / "analyze-last.json"
    cmd = [str(exe), str(root), "vn_analyze", str(out)] + [str(f) for f in files]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not out.is_file():
        raise AnalyzeError(
            "build-bridge (renpy vn_analyze) упал: код %s\nstdout: %s\nstderr: %s"
            % (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:])
        )
    data = json.loads(out.read_text(encoding="utf-8"))
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out.unlink()
    return data["files"]
