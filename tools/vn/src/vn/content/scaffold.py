"""vn chapter new / vn scene new — скаффолдинг контента по конвенциям (раздел 1.4)."""

from __future__ import annotations

import re
from pathlib import Path

CHAPTER_DIR_RE = re.compile(r"^ch(\d{2})_")
SCENE_FILE_RE = re.compile(r"^s(\d{3})_")
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


class ScaffoldError(RuntimeError):
    pass


def _chapter_yaml(ch_id: str, slug: str) -> str:
    return (
        "schema: chapter@1\n"
        f"id: {ch_id}                             # слуг {slug} — только в имени папки\n"
        f"title_key: meta.chapters.{ch_id}.title\n"
        "status: draft                        # draft | playtest | release (G15)\n"
        "entry_scene: s010\n"
        "scene_order: [s010]\n"
    )


def _scene_yaml(short_id: str) -> str:
    return (
        "schema: scene@1\n"
        f"id: {short_id}\n"
        "exits: {}\n"
        "# exits:\n"
        "#   done: s020                        # короткая ссылка внутри главы\n"
        "#   alt:\n"
        "#     - {when: \"g.route == 'mira'\", to: s030}\n"
        "#     - {to: ch02/s010}              # межглавная ссылка\n"
    )


def _scene_rpy(full_id: str) -> str:
    return (
        f"# Метки — только {full_id}__body и {full_id}__<branch> (C2, naming.md).\n"
        f"# Переходы между сценами — return \"<exit_id>\"; цели в exits: scene.yaml.\n\n"
        f"label {full_id}__body:\n"
        "    \"…\"\n"
        "    return\n"
    )


def _vars_yaml(ch_id: str) -> str:
    return (
        "schema: vars@1\n"
        f"store: {ch_id}\n"
        "vars: {}\n"
    )


def new_chapter(root: Path, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ScaffoldError(f"слуг {slug!r} вне конвенции ^[a-z][a-z0-9_]{{2,30}}$")
    chapters = root / "content" / "chapters"
    used = set()
    for d in chapters.iterdir() if chapters.is_dir() else []:
        m = CHAPTER_DIR_RE.match(d.name)
        if m:
            used.add(int(m.group(1)))
    num = max(used, default=0) + 1
    ch_id = f"ch{num:02d}"
    ch_dir = chapters / f"{ch_id}_{slug}"
    scenes = ch_dir / "scenes"
    scenes.mkdir(parents=True)
    (ch_dir / "chapter.yaml").write_text(_chapter_yaml(ch_id, slug), encoding="utf-8")
    (ch_dir / "vars.yaml").write_text(_vars_yaml(ch_id), encoding="utf-8")
    full_id = f"{ch_id}_s010"
    (scenes / "s010_intro.scene.yaml").write_text(_scene_yaml("s010"), encoding="utf-8")
    (scenes / "s010_intro.scene.rpy").write_text(_scene_rpy(full_id), encoding="utf-8")
    return ch_dir


def new_scene(root: Path, chapter: str, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ScaffoldError(f"слуг {slug!r} вне конвенции ^[a-z][a-z0-9_]{{2,30}}$")
    chapters = root / "content" / "chapters"
    matches = [d for d in chapters.iterdir()
               if d.is_dir() and (d.name == chapter or d.name.startswith(chapter + "_"))]
    if len(matches) != 1:
        raise ScaffoldError(
            f"глава {chapter!r} не найдена (или неоднозначна): "
            f"{[d.name for d in matches] or 'нет совпадений'}"
        )
    ch_dir = matches[0]
    ch_id = ch_dir.name[:4]
    scenes = ch_dir / "scenes"
    scenes.mkdir(exist_ok=True)
    used = set()
    for f in scenes.glob("s*_*.scene.yaml"):
        m = SCENE_FILE_RE.match(f.name)
        if m:
            used.add(int(m.group(1)))
    num = (max(used, default=0) // 10) * 10 + 10   # шаг 10 (1.4)
    short_id = f"s{num:03d}"
    full_id = f"{ch_id}_{short_id}"
    yaml_path = scenes / f"{short_id}_{slug}.scene.yaml"
    yaml_path.write_text(_scene_yaml(short_id), encoding="utf-8")
    (scenes / f"{short_id}_{slug}.scene.rpy").write_text(_scene_rpy(full_id), encoding="utf-8")
    return yaml_path
