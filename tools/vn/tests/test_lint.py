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
