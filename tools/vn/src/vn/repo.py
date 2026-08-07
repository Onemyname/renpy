"""Поиск корня репозитория и загрузка project.yaml."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


class RepoError(RuntimeError):
    pass


def find_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / "project.yaml").is_file() and (cand / "tools" / "schemas").is_dir():
            return cand
    raise RepoError(
        "не найден корень репозитория: нужен project.yaml + tools/schemas/ "
        "в текущем каталоге или выше"
    )


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_project(root: Path) -> dict:
    return load_yaml(root / "project.yaml")


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "nogit"
    except Exception:
        return "nogit"
