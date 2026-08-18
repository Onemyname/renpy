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


def chapter_zones(root: Path, packs=None) -> list[tuple[str, Path]]:
    """[(pack_id, каталог глав)]: ядро (`content/chapters`) плюс главы паков
    (`packs/<id>/chapters`). Принадлежность паку — по РАСПОЛОЖЕНИЮ (C10): поля
    `pack:` в `chapter.yaml` не существует.

    `packs` — валидированные id из манифестов; так зоны собирает компилятор, для
    которого пак без манифеста не существует. Инструменты, которые дерево только
    читают (граф сцен, снимок реестра, модель памяти), вызывают без аргумента и
    получают все каталоги `packs/*`: глава, забытая в манифесте, должна быть видна
    человеку в графе, а не исчезать из него молча.

    Хелпер общий, потому что раньше эта раскладка была скопирована в четыре места
    и в двух из них отставала — граф и changelog не видели глав паков вовсе.
    """
    zones = [("core", root / "content" / "chapters")]
    if packs is None:
        pack_dir = root / "packs"
        ids = sorted(p.name for p in pack_dir.iterdir()
                     if p.is_dir() and (p / "chapters").is_dir()) \
            if pack_dir.is_dir() else []
    else:
        ids = sorted(packs)
    zones += [(pid, root / "packs" / pid / "chapters") for pid in ids]
    return [(pid, d) for pid, d in zones if d.is_dir()]


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
