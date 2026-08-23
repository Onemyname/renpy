"""Поиск корня репозитория и загрузка project.yaml."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


class RepoError(RuntimeError):
    pass


def write_text_lf(path: Path, text: str) -> None:
    """Единственный способ писать текст в репозиторий: UTF-8 + LF на любой ОС.

    Голый `Path.write_text` на Windows транслирует `\\n` в CRLF, а `.gitattributes`
    требует LF — каждый прогон тулинга оставлял бы фантомные диффы, в которых
    тонет настоящий (ловилось на loc/ledger). Все записи текста идут сюда."""
    path.write_text(text, encoding="utf-8", newline="\n")


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


def unshipped_chapters(root: Path) -> set[str]:
    """Главы, которые не уезжают НИ ОДНОМУ игроку: их пак не перечислен ни в одном
    `flavors.*.packs` (ADR-0021).

    Такой контент не участвует в гейтах, которые говорят про ИГРОКА: покрытие
    переводов (иначе QA-топологии графа топили бы порог 98%, ничего не давая
    игроку) и покрытие ветвления (`vn test paths` требовал бы прохождения
    тестовых развилок в ночной джобе). Из PO главы не исключаются — в dev-сборке
    они играбельны и должны переводиться псевдолокалью, — но помечаются
    комментарием для переводчика.

    Хелпер живёт здесь, а не у первого потребителя: «уезжает ли контент игроку» —
    свойство раскладки репозитория, и второй ответ на этот вопрос разъехался бы
    с первым.
    """
    try:
        project = load_project(root)
    except Exception:
        return set()
    shipped = {"core"}
    for cfg in (project.get("flavors") or {}).values():
        shipped.update((cfg or {}).get("packs") or [])
    out: set[str] = set()
    for pack_id, chapters_dir in chapter_zones(root):
        if pack_id in shipped or not chapters_dir.is_dir():
            continue
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
            m = re.match(r"^ch(\d{2})_", d.name)
            if m:
                out.add(f"ch{m.group(1)}")
    return out


def git_tag_exists(root: Path, tag: str) -> bool:
    """Есть ли такой git-тег. Недоступный git (архив без истории, чужая песочница)
    трактуется как «тега нет»: проверка, которая падает без git, заблокировала бы
    работу там, где git и не нужен."""
    try:
        out = subprocess.run(
            ["git", "tag", "-l", tag],
            cwd=root, capture_output=True, text=True, check=True,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "nogit"
    except Exception:
        return "nogit"
