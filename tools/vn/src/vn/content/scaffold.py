"""vn chapter new / vn scene new / vn char new — скаффолдинг по конвенциям (раздел 1.4)."""

from __future__ import annotations

import re
from pathlib import Path

CHAPTER_DIR_RE = re.compile(r"^ch(\d{2})_")
# id персонажа: та же форма, что в character@1 (tools/schemas/character@1.schema.json).
CHAR_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
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


def _find_chapter(root: Path, chapter: str) -> tuple[Path, str]:
    chapters = root / "content" / "chapters"
    if not chapters.is_dir():
        raise ScaffoldError("каталог content/chapters/ не существует")
    matches = [d for d in chapters.iterdir()
               if d.is_dir() and (d.name == chapter or d.name.startswith(chapter + "_"))]
    if len(matches) != 1:
        raise ScaffoldError(
            f"глава {chapter!r} не найдена (или неоднозначна): "
            f"{[d.name for d in matches] or 'нет совпадений'}"
        )
    m = re.match(r"^(ch\d{2})_", matches[0].name)
    if not m:
        raise ScaffoldError(f"папка {matches[0].name!r} вне конвенции ch<NN>_<slug>")
    return matches[0], m.group(1)


def new_stub(root: Path, chapter: str, short_id: str) -> Path:
    """Placeholder-сцена для объявленной, но не написанной цели перехода (G15):
    smoke-прогон draft-главы не падает, игрок видит заглушку."""
    if not re.match(r"^s\d{3}$", short_id):
        raise ScaffoldError(f"id сцены {short_id!r} вне конвенции ^s\\d{{3}}$")
    ch_dir, ch_id = _find_chapter(root, chapter)
    scenes = ch_dir / "scenes"
    scenes.mkdir(exist_ok=True)
    if list(scenes.glob(f"{short_id}_*.scene.yaml")):
        raise ScaffoldError(f"сцена {short_id} уже существует в {ch_dir.name}")
    full_id = f"{ch_id}_{short_id}"
    yaml_path = scenes / f"{short_id}_stub.scene.yaml"
    yaml_path.write_text(f"schema: scene@1\nid: {short_id}\nexits: {{}}\n", encoding="utf-8")
    (scenes / f"{short_id}_stub.scene.rpy").write_text(
        f"label {full_id}__body:\n"
        "    \"Заглушка: сцена в разработке.\"\n"
        "    return\n",
        encoding="utf-8",
    )
    return yaml_path


def new_scene(root: Path, chapter: str, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ScaffoldError(f"слуг {slug!r} вне конвенции ^[a-z][a-z0-9_]{{2,30}}$")
    ch_dir, ch_id = _find_chapter(root, chapter)
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


def _character_color(char_id: str) -> str:
    """Цвет реплик по id — детерминированно и различимо.

    Зачем вообще: `color` в character@1 обязателен, а «выберите сами» на скаффолде
    означает, что первые пять персонажей получат один и тот же дефолт из примера.
    Тон берётся из хеша id (стабильно между машинами), насыщенность и яркость
    фиксированы — цвет обязан читаться на тёмном текстбоксе, а не быть случайным.
    """
    import colorsys

    from blake3 import blake3

    hue = int.from_bytes(blake3(char_id.encode("utf-8")).digest()[:2], "big") % 360
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, 0.45, 0.85)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _character_yaml(char_id: str, name: str, color: str, pose: str, outfit: str,
                    emotion: str) -> str:
    import json

    return (
        "schema: character@1\n"
        f"id: {char_id}\n"
        f"name: {json.dumps(name, ensure_ascii=False)}"
        "        # исходный язык; перевод — vn loc extract\n"
        f'color: "{color}"'
        "                    # цвет имени в текстбоксе\n"
        f"voice_tag: {char_id}\n"
        "# canvas: [1200, 2200]                # ХОЛСТ МАСТЕРОВ (ADR-0012): все слои\n"
        "#                                     # позы обязаны лежать на одном холсте.\n"
        "#                                     # Фактический размер назовёт\n"
        "#                                     # vn char validate — впишите его сюда.\n"
        "matrix:\n"
        f"  poses: [{pose}]\n"
        f"  outfits: [{outfit}]\n"
        f"  emotions: [{emotion}]\n"
        "  required:\n"
        f"    - {{pose: {pose}, outfits: [{outfit}], emotions: [{emotion}]}}\n"
    )


def new_character(root: Path, char_id: str, name: str = "", color: str = "",
                  pose: str = "a", outfit: str = "casual",
                  emotion: str = "neutral") -> list[Path]:
    """content/characters/<id>/character.yaml + каталог мастеров. Возвращает пути.

    Каталог позы НЕ создаётся намеренно: папка позы без `base.*` мгновенно валит
    `vn assets build` («поза не собрана»), то есть скаффолд оставлял бы дерево в
    красном состоянии. Художник создаёт папку позы вместе с первым файлом.
    """
    if not CHAR_ID_RE.match(char_id):
        raise ScaffoldError(f"id персонажа {char_id!r} вне конвенции {CHAR_ID_RE.pattern} "
                            f"(character@1: 2-24 символа, латиница со строчных)")
    for label, token in (("поза", pose), ("наряд", outfit), ("эмоция", emotion)):
        if not TOKEN_RE.match(token):
            raise ScaffoldError(f"{label} {token!r} вне конвенции {TOKEN_RE.pattern}")
    if color and not COLOR_RE.match(color):
        raise ScaffoldError(f"цвет {color!r} — ожидается #RRGGBB")
    if len({pose, outfit, emotion}) != 3:
        raise ScaffoldError("имена позы, наряда и эмоции обязаны различаться: атрибуты "
                            "layeredimage уникальны между группами")

    decl = root / "content" / "characters" / char_id / "character.yaml"
    if decl.is_file():
        raise ScaffoldError(f"{decl.relative_to(root).as_posix()} уже есть — скаффолд "
                            f"никогда не перезаписывает декларацию")
    decl.parent.mkdir(parents=True, exist_ok=True)
    decl.write_text(_character_yaml(char_id, name or char_id.capitalize(),
                                    color or _character_color(char_id),
                                    pose, outfit, emotion), encoding="utf-8")
    created = [decl]
    masters = root / "assets_src" / "art" / "characters" / char_id
    if not masters.is_dir():
        masters.mkdir(parents=True, exist_ok=True)
        keep = masters / ".gitkeep"
        keep.write_text("", encoding="utf-8")
        created.append(keep)
    return created
