"""vn doctor — самодиагностика окружения с человекочитаемыми рецептами починки (G22)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .repo import RepoError, find_root, load_project
from .schemas import SchemaRegistry


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return None


def sdk_path() -> Path | None:
    env = os.environ.get("RENPY_SDK")
    if env:
        p = Path(env)
        if (p / "renpy.py").is_file():
            return p
    return None


def sdk_version(sdk: Path) -> str | None:
    """Фактическая версия SDK из renpy/vc_version.py (например '8.5.3.26051504')."""
    vc = sdk / "renpy" / "vc_version.py"
    if not vc.is_file():
        return None
    for line in vc.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version ") or line.startswith("version="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def run_doctor() -> int:
    checks: list[tuple[bool | None, str, str]] = []   # (ok | None=warn, заголовок, рецепт починки)

    py_ok = sys.version_info >= (3, 10)
    checks.append((py_ok, f"Python {sys.version.split()[0]}", "" if py_ok else "нужен Python >= 3.10"))

    checks.append((shutil.which("git") is not None, "git", "установите git и добавьте в PATH"))
    lfs = _run(["git", "lfs", "version"])
    checks.append((lfs is not None, f"git-lfs ({lfs or 'нет'})", "установите git-lfs: https://git-lfs.com"))

    root = None
    try:
        root = find_root()
        checks.append((True, f"корень репозитория: {root}", ""))
    except RepoError as e:
        checks.append((False, "корень репозитория", str(e)))

    if root is not None:
        try:
            project = load_project(root)
            min_tools = str(project.get("min_tools", "0"))
            have = tuple(int(x) for x in __version__.split(".")[:2])
            need = tuple(int(x) for x in min_tools.split(".")[:2])
            ok = have >= need
            checks.append((ok, f"project.yaml (min_tools {min_tools}, vn {__version__})",
                           "" if ok else "обновите vn: pip install -e tools/vn"))
        except Exception as e:
            checks.append((False, "project.yaml", f"не читается: {e}"))

        try:
            reg = SchemaRegistry(root / "tools" / "schemas")
            checks.append((True, f"реестр схем: {len(reg.schemas)} схем", ""))
        except Exception as e:
            checks.append((False, "реестр схем tools/schemas/", str(e)))

        local_storage = root / ".vnstorage.local.yaml"
        if local_storage.is_file():
            checks.append((None, "локальное переопределение .vnstorage.local.yaml активно", ""))

    sdk = sdk_path()
    if sdk:
        actual = sdk_version(sdk) or "?"
        pinned = None
        if root is not None:
            try:
                pinned = load_project(root).get("renpy_sdk")
            except Exception:
                pass
        if pinned and not actual.startswith(pinned):
            checks.append((False, f"Ren'Py SDK {actual} != пину {pinned} (project.yaml)",
                           "поставьте пиннованную версию SDK или обновите пин отдельным PR (G18)"))
        else:
            checks.append((True, f"Ren'Py SDK {actual}: {sdk}", ""))
    else:
        checks.append((None, "Ren'Py SDK не найден",
                       "скачайте SDK с renpy.org и укажите путь: setx RENPY_SDK <путь>; "
                       "нужен для vn play (сборка vn build работает без SDK)"))

    hard_fail = False
    for ok, title, hint in checks:
        mark = "✓" if ok else ("!" if ok is None else "✗")
        line = f" {mark} {title}"
        if hint and ok is not True:
            line += f"\n     → {hint}"
        print(line)
        if ok is False:
            hard_fail = True
    return 1 if hard_fail else 0
