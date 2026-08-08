"""vn content lint: чистый репозиторий фазы 0 линтуется без ошибок; поломки ловятся."""

import shutil

from vn.content.lint import lint


def test_lint_clean_repo(repo_root):
    rep = lint(repo_root)
    assert rep.errors == []


def _copy_skeleton(repo_root, tmp_path):
    """Копия скелета репозитория без тяжёлых зон и без глав (тесты создают свои)."""
    from vn.content.lint import REQUIRED_DIRS

    for name in ("project.yaml", ".vnstorage.yaml"):
        shutil.copy(repo_root / name, tmp_path / name)
    shutil.copytree(repo_root / "tools" / "schemas", tmp_path / "tools" / "schemas",
                    dirs_exist_ok=True)
    shutil.copytree(repo_root / "content", tmp_path / "content")
    shutil.rmtree(tmp_path / "content" / "chapters")
    (tmp_path / "content" / "chapters").mkdir()
    for d in REQUIRED_DIRS:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_lint_catches_broken_language_packages(repo_root, tmp_path):
    """Инвариант «lint зелёный => build не падает»: битые пакеты языков
    (ADR-0005) обязаны краснить lint ДО того, как build упадёт LocError."""
    root = _copy_skeleton(repo_root, tmp_path)

    (root / "loc").mkdir(exist_ok=True)
    (root / "loc" / "loc.yaml").write_text(
        "schema: loc@2\nsource:\n  code: ru\n  name: Русский\n", encoding="utf-8"
    )
    # Каталог без манифеста
    (root / "loc" / "po" / "xx").mkdir(parents=True)
    # code != имени каталога (схемно-валидный манифест)
    (root / "loc" / "po" / "de").mkdir(parents=True)
    (root / "loc" / "po" / "de" / "language.yaml").write_text(
        "schema: language@1\ncode: fr\nname: Deutsch\n", encoding="utf-8"
    )

    rep = lint(root)
    assert any("loc/po/xx" in e and "language.yaml" in e for e in rep.errors)
    assert any("loc/po/de/language.yaml" in e and "fr" in e for e in rep.errors)


def test_lint_catches_bad_chapter_and_orphan_pair(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)

    ch = root / "content" / "chapters" / "ch01_awakening"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: playtest\nentry_scene: s010\nscene_order: [s010, s020]\n",
        encoding="utf-8",
    )
    # s010: только yaml без парного rpy; s020 вообще нет; exits в никуда
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nexits:\n  done: s099\n", encoding="utf-8"
    )

    rep = lint(root)
    text = "\n".join(rep.errors)
    assert "нет парного .scene.rpy" in text
    assert "scene_order ссылается на несуществующую сцену s020" in text
    assert "s099: цель не существует" in text


def test_draft_downgrades_graph_errors_to_warnings(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    ch = root / "content" / "chapters" / "ch02_undertow"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch02\ntitle_key: meta.chapters.ch02.title\n"
        "status: draft\nentry_scene: s010\nscene_order: [s010]\n",
        encoding="utf-8",
    )
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\nexits:\n  done: s050\n", encoding="utf-8"
    )
    (ch / "scenes" / "s010_intro.scene.rpy").write_text(
        "label ch02_s010__body:\n    return 'done'\n", encoding="utf-8"
    )

    rep = lint(root)
    assert rep.errors == []
    assert any("s050: цель не существует" in w for w in rep.warnings)


def test_released_id_cannot_vanish(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    reg = root / "content" / "registry" / "id_registry.json"
    reg.write_text(
        '{"schema": "id_registry@1", "chapters": ["ch01"], "scenes": ["ch01_s010"],'
        ' "characters": [], "vars": []}\n',
        encoding="utf-8",
    )
    rep = lint(root)
    assert any("исчезла без записи в renames.yaml" in e for e in rep.errors)


def test_released_id_check_covers_all_four_classes(repo_root, tmp_path):
    """G7-проверка исчезновения — не только сцены: главы/персонажи/переменные тоже."""
    root = _copy_skeleton(repo_root, tmp_path)
    reg = root / "content" / "registry" / "id_registry.json"
    # Персонаж mira и var g.route в скелете есть; фантомные — нет.
    reg.write_text(
        '{"schema": "id_registry@1", "chapters": ["ch77"], "scenes": [],'
        ' "characters": ["ghost"], "vars": ["g.gone"]}\n',
        encoding="utf-8",
    )
    rep = lint(root)
    text = "\n".join(rep.errors)
    assert "выпущенная глава ch77 исчезла" in text
    assert "выпущенный персонаж ghost исчез" in text
    assert "выпущенная переменная g.gone исчезла" in text


def test_released_var_exempt_by_renames(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "registry" / "id_registry.json").write_text(
        '{"schema": "id_registry@1", "chapters": [], "scenes": [],'
        ' "characters": [], "vars": ["g.old_route"]}\n', encoding="utf-8")
    (root / "content" / "renames.yaml").write_text(
        "schema: renames@1\nscenes: {}\ndeleted_scenes: {}\nlabels: {}\n"
        "vars:\n  g.old_route: g.route\n", encoding="utf-8")
    rep = lint(root)
    assert not any("g.old_route" in e for e in rep.errors)


def test_stamp_id_registry_unions_released_ids(repo_root, tmp_path):
    """vn release changelog штампует выпущенные id всех классов (append-only)."""
    from vn.release import stamp_id_registry
    import json

    root = _copy_skeleton(repo_root, tmp_path)
    ch = root / "content" / "chapters" / "ch01_awakening"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: release\nentry_scene: s010\nscene_order: [s010]\n", encoding="utf-8")
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\n", encoding="utf-8")
    (ch / "vars.yaml").write_text(
        "schema: vars@1\nstore: ch01\nvars:\n  met:\n    type: bool\n    default: false\n"
        "    since: 1\n", encoding="utf-8")

    added = stamp_id_registry(root)
    assert added > 0
    reg = json.loads((root / "content" / "registry" / "id_registry.json").read_text(encoding="utf-8"))
    assert "ch01" in reg["chapters"]
    assert "ch01_s010" in reg["scenes"]
    assert "mira" in reg["characters"]          # из скопированного content/characters
    assert "ch01.met" in reg["vars"] and "g.route" in reg["vars"]

    # Повторный штамп идемпотентен (append-only union)
    assert stamp_id_registry(root) == 0


def test_stamp_skips_draft_only(repo_root, tmp_path):
    """Черновики не иммортализуются: нет released-глав -> штамп ничего не заносит."""
    from vn.release import stamp_id_registry

    root = _copy_skeleton(repo_root, tmp_path)
    ch = root / "content" / "chapters" / "ch01_awakening"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: draft\nentry_scene: s010\nscene_order: [s010]\n", encoding="utf-8")
    (ch / "scenes" / "s010_intro.scene.yaml").write_text(
        "schema: scene@1\nid: s010\n", encoding="utf-8")
    assert stamp_id_registry(root) == 0
