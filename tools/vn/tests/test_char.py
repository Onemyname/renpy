"""vn char new | validate | sheet — скаффолд, проверка матрицы, лист арт-ревью.

Главное свойство, которое здесь стережётся: `char validate` — не вторая реализация
проверок, а второй ВЫЗОВ тех же функций, что у сборки (`images.check_matrix`,
`pipeline.character_jobs`). Поэтому часть тестов сверяет формулировки между путями:
разойдутся — значит появилась копия, и «зелёный validate при красном build» станет
возможен.
"""

from __future__ import annotations

import json

import pytest

from helpers import img, mk_root, mk_root_with_schemas
from vn.content.characters import CharError, char_dirs, declaration_errors, sheet, validate
from vn.content.scaffold import ScaffoldError, new_character


def _declare(root, char_id="mira", *, canvas=None, poses=("a",), outfits=("casual",),
             emotions=("neutral",), required=True, forbidden=None):
    doc = {
        "schema": "character@1",
        "id": char_id,
        "name": char_id.capitalize(),
        "color": "#c94f7c",
        "matrix": {"poses": list(poses), "outfits": list(outfits),
                   "emotions": list(emotions)},
    }
    if canvas:
        doc["canvas"] = list(canvas)
    if required:
        doc["matrix"]["required"] = [
            {"pose": poses[0], "outfits": [outfits[0]], "emotions": [emotions[0]]}]
    if forbidden:
        doc["matrix"]["forbidden"] = forbidden
    path = root / "content" / "characters" / char_id / "character.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _build_layers(root, char_id="mira", pose="a", outfits=("casual",),
                  emotions=("neutral",), size=(60, 110)):
    """Собранные слои в game/assets (то, что видит sprite_tree)."""
    base = root / "game" / "assets" / "spr" / char_id / pose
    img(base / "base.webp", size)
    for o in outfits:
        img(base / "outfits" / f"{o}.webp", size)
    for e in emotions:
        img(base / "faces" / f"{e}.webp", size)
    return base


def _master(root, char_id="mira", pose="a", size=(120, 220)):
    """Мастер позы в зоне сырцов (то, что видит character_jobs)."""
    d = root / "assets_src" / "art" / "characters" / char_id / pose
    img(d / "base.png", size, fmt="PNG")
    return d


# ── char new: скаффолд, который не оставляет дерево красным ───────────────────

def test_new_character_creates_valid_declaration(tmp_path, repo_root):
    """Заготовка обязана проходить character@1 сразу: иначе первый же vn build
    после скаффолда красный, и человек чинит не свою ошибку."""
    import shutil

    from vn.repo import load_yaml
    from vn.schemas import SchemaRegistry

    root = mk_root(tmp_path)
    created = new_character(root, "kira", name="Кира")
    decl = root / "content" / "characters" / "kira" / "character.yaml"
    assert decl in created and decl.is_file()
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    errors = SchemaRegistry(root / "tools" / "schemas").validate(
        load_yaml(decl), "character.yaml")
    assert errors == []


def test_new_character_does_not_create_pose_dir(tmp_path):
    """Папка позы без base.* мгновенно валит vn assets build — скаффолд не имеет
    права оставлять дерево в красном состоянии."""
    root = mk_root(tmp_path)
    new_character(root, "kira")
    masters = root / "assets_src" / "art" / "characters" / "kira"
    assert masters.is_dir()
    assert [p.name for p in masters.iterdir()] == [".gitkeep"]


def test_new_character_never_overwrites(tmp_path):
    root = mk_root(tmp_path)
    new_character(root, "kira")
    with pytest.raises(ScaffoldError, match="уже есть"):
        new_character(root, "kira")


def test_new_character_color_is_stable_and_distinct(tmp_path):
    """Цвет из id: стабильный между машинами (иначе дифф на пустом месте) и разный
    у разных персонажей (иначе первые пять получат один дефолт из примера)."""
    from vn.content.scaffold import _character_color

    assert _character_color("kira") == _character_color("kira")
    assert _character_color("kira") != _character_color("mira")
    assert _character_color("kira").startswith("#") and len(_character_color("kira")) == 7


@pytest.mark.parametrize("kwargs, match", [
    ({"char_id": "K"}, "вне конвенции"),
    ({"char_id": "kira", "color": "красный"}, "RRGGBB"),
    ({"char_id": "kira", "pose": "A"}, "вне конвенции"),
    ({"char_id": "kira", "pose": "x", "outfit": "x"}, "различаться"),
])
def test_new_character_rejects_bad_input(tmp_path, kwargs, match):
    with pytest.raises(ScaffoldError, match=match):
        new_character(mk_root(tmp_path), **kwargs)


# ── char validate: те же проверки, что у сборки, но без сборки ────────────────

def test_validate_reports_matrix_and_layers(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220))
    _master(root)
    _build_layers(root)
    rep = validate(root, only="mira")
    assert rep.ok, rep.errors
    assert rep.rows and "поз 1" in rep.rows[0] and "собрано слоёв 3" in rep.rows[0]


def test_validate_suggests_canvas_when_missing(tmp_path, repo_root):
    """Холст мастеров не объявлен — validate обязан назвать ФАКТИЧЕСКИЙ размер
    готовой к вставке строкой, а не просто сказать «не хватает поля»."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root)
    _master(root, size=(120, 220))
    _build_layers(root)
    rep = validate(root, only="mira")
    assert any("canvas: [120, 220]" in w for w in rep.warnings), rep.warnings


def test_validate_catches_canvas_mismatch(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(999, 999))
    _master(root, size=(120, 220))
    _build_layers(root)
    rep = validate(root, only="mira")
    assert any("!= фактического холста" in e for e in rep.errors), rep.errors


def test_validate_reports_missing_required_layer(tmp_path, repo_root):
    """Та же формулировка, что у сборки: контракт один (images.check_matrix)."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, outfits=("casual", "school"),
             required=False)
    path = root / "content" / "characters" / "mira" / "character.yaml"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["matrix"]["required"] = [{"pose": "a", "outfits": ["school"], "emotions": []}]
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _master(root)
    _build_layers(root, outfits=("casual",))
    rep = validate(root, only="mira")
    assert any("нет слоя outfits/school" in e for e in rep.errors), rep.errors


def test_validate_warns_about_masters_without_declaration(tmp_path, repo_root):
    """Мастера без декларации — художник рисует в пустоту: компилятор их не увидит."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _master(root, char_id="ghost")
    rep = validate(root)
    assert any("декларации" in w and "ghost" in w for w in rep.warnings), rep.warnings


def test_validate_unknown_character_points_at_scaffold(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    with pytest.raises(CharError, match="vn char new"):
        validate(root, only="нет-такого")


def test_validate_does_not_touch_the_tree(tmp_path, repo_root):
    """Ни одного записанного байта: команда — проверка, а не сборка."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220))
    _master(root)
    _build_layers(root)
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    validate(root, only="mira")
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_declaration_errors_match_lint_rule(repo_root):
    """Правило «id == имени папки» цитируется и линтом, и валидатором — оно обязано
    физически жить в одном месте, иначе два ответа на один вопрос."""
    src = (repo_root / "tools" / "vn" / "src" / "vn" / "content" / "lint.py").read_text(
        encoding="utf-8")
    assert "from .characters import char_dirs, declaration_errors" in src
    assert "declaration_errors(root, d, doc)" in src


def test_declaration_errors_on_missing_file(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    d = root / "content" / "characters" / "mira"
    d.mkdir(parents=True)
    assert declaration_errors(root, d, None) == ["content/characters/mira: нет character.yaml"]
    assert [p.name for p in char_dirs(root)] == ["mira"]


# ── char sheet: ячейки в z-порядке эмиттера ───────────────────────────────────

def test_sheet_builds_all_allowed_combinations(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220), outfits=("casual", "school"),
             emotions=("neutral", "smile"))
    _master(root)
    _build_layers(root, outfits=("casual", "school"), emotions=("neutral", "smile"))
    index = sheet(root, "mira")
    cells = sorted(p.name for p in (index.parent / "cells").iterdir())
    assert len(cells) == 4, cells
    assert "a__school__smile.webp" in cells
    html = index.read_text(encoding="utf-8")
    assert "ячеек: 4" in html and "base → outfits → faces → overlays" in html


def test_sheet_skips_forbidden_combinations(tmp_path, repo_root):
    """forbidden в декларации — это запрет показывать, а не только собирать: ячейка
    запрещённой пары в листе означала бы ревью того, чего в игре не будет."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220), outfits=("casual", "school"),
             forbidden=[{"pose": "a", "outfits": ["school"]}])
    _master(root)
    _build_layers(root, outfits=("casual",))
    index = sheet(root, "mira")
    cells = [p.name for p in (index.parent / "cells").iterdir()]
    assert cells == ["a__casual__neutral.webp"], cells


def test_sheet_is_idempotent(tmp_path, repo_root):
    """Второй прогон не должен копить ячейки прошлой матрицы: устаревшая ячейка в
    листе ревью — прямая дезинформация."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220), outfits=("casual", "school"))
    _master(root)
    _build_layers(root, outfits=("casual", "school"))
    index = sheet(root, "mira")
    stale = index.parent / "cells" / "старая.webp"
    stale.write_bytes(b"x")
    sheet(root, "mira")
    assert not stale.exists()


def test_sheet_cell_has_opaque_background(tmp_path, repo_root):
    """Слои спрайта — вырезы с альфой; без подложки лист показывал бы силуэты."""
    from PIL import Image

    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220))
    _master(root)
    _build_layers(root)
    index = sheet(root, "mira")
    cell = next((index.parent / "cells").iterdir())
    with Image.open(cell) as im:
        assert im.mode == "RGB"
        corner = im.convert("RGB").getpixel((1, 1))
    # Допуск: ячейка сохранена в webp с потерями, и точных 128 в углу не будет.
    # Проверяется не число, а факт — угол СЕРЫЙ, а не чёрный (иначе подложки нет).
    assert all(abs(c - 128) <= 8 for c in corner), corner


def test_sheet_without_built_assets_says_what_to_do(tmp_path, repo_root):
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220))
    _master(root)
    with pytest.raises(CharError, match="vn assets build"):
        sheet(root, "mira")


def test_sheet_without_any_combination_explains_why(tmp_path, repo_root):
    """Слои собраны, но ни одна комбинация матрицы не сходится — это отдельная
    ситуация, и путать её с «нет ассетов» нельзя."""
    root = mk_root_with_schemas(tmp_path, repo_root)
    _declare(root, canvas=(120, 220), emotions=("smile",), required=False)
    _master(root)
    _build_layers(root, emotions=("neutral",))     # эмоции не той, что в matrix
    with pytest.raises(CharError, match="ни одной допустимой комбинации"):
        sheet(root, "mira")
