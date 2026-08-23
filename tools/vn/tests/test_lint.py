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
    # Реестр выпущенных id — вместе с главами: скелет «без глав» с боевым
    # реестром давал бы G7-ошибки «выпущенная сцена исчезла» в каждом тесте
    # (реестр репозитория непуст с 1.0.0). Тесты реестра пишут своё содержимое.
    (tmp_path / "content" / "registry" / "id_registry.json").write_text(
        '{"schema": "id_registry@1", "chapters": [], "scenes": [], '
        '"characters": [], "vars": [], "assets": []}\n', encoding="utf-8")
    for d in REQUIRED_DIRS:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_lint_catches_migration_chain_gap(repo_root, tmp_path):
    """Тот же инвариант «lint зелёный => build не падает»: дыру в цепочке миграций
    (G5) компилятор ронял всегда, а lint — то есть и pre-push hook — не знал о ней
    вовсе. Правило одно на обоих (content/migrations.py)."""
    root = _copy_skeleton(repo_root, tmp_path)
    mig = root / "content" / "migrations"
    (mig / "0003_gap.py").write_text("def migrate(state):\n    return state\n",
                                     encoding="utf-8")
    reg = mig / "registry.yaml"
    reg.write_text(reg.read_text(encoding="utf-8")
                   + "  - {number: 3, slug: gap, by: test}\n", encoding="utf-8")

    rep = lint(root)
    # save_schema в project.yaml = 2, номер 3 лишний: цепочка != ожидаемой
    assert any("content/migrations: цепочка" in e for e in rep.errors), rep.errors


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


def _mk_chapter(root, ch_id="ch03", status="playtest", scenes=None, order=None, entry="s010"):
    """Глава со сценами: scenes = {sid: exits-dict}."""
    ch = root / "content" / "chapters" / f"{ch_id}_test"
    (ch / "scenes").mkdir(parents=True, exist_ok=True)
    order = order or sorted(scenes)
    (ch / "chapter.yaml").write_text(
        f"schema: chapter@1\nid: {ch_id}\ntitle_key: meta.chapters.{ch_id}.title\n"
        f"status: {status}\nentry_scene: {entry}\nscene_order: [{', '.join(order)}]\n",
        encoding="utf-8")
    import yaml as _yaml
    for sid, exits in scenes.items():
        doc = {"schema": "scene@1", "id": sid}
        if exits:
            doc["exits"] = exits
        (ch / "scenes" / f"{sid}_test.scene.yaml").write_text(
            _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        (ch / "scenes" / f"{sid}_test.scene.rpy").write_text(
            f"label {ch_id}_{sid}__body:\n    return\n", encoding="utf-8")
    return ch


def test_unreachable_scene_detected(repo_root, tmp_path):
    """Сцена, на которую не ведёт ни один exit — мёртвый контент."""
    root = _copy_skeleton(repo_root, tmp_path)
    _mk_chapter(root, scenes={"s010": {"go": "s020"}, "s020": {}, "s030": {}},
                order=["s010", "s020", "s030"])
    rep = lint(root)
    assert any("сцена s030 недостижима" in e for e in rep.errors)
    assert not any("сцена s020 недостижима" in e for e in rep.errors)


def test_dead_end_scene_warns(repo_root, tmp_path):
    """Сцена без exits в середине главы — тупик (warning, не ошибка)."""
    root = _copy_skeleton(repo_root, tmp_path)
    _mk_chapter(root, scenes={"s010": {"go": "s020"}, "s020": {}, "s030": {}},
                order=["s010", "s020", "s030"])
    rep = lint(root)
    assert any("сцена s020 — тупик" in w for w in rep.warnings)


def test_reachability_draft_downgrades(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    _mk_chapter(root, ch_id="ch04", status="draft",
                scenes={"s010": {}, "s020": {}}, order=["s010", "s020"])
    rep = lint(root)
    assert rep.errors == []
    assert any("сцена s020 недостижима" in w for w in rep.warnings)


def test_full_linear_chapter_is_clean(repo_root, tmp_path):
    root = _copy_skeleton(repo_root, tmp_path)
    _mk_chapter(root, ch_id="ch05", scenes={"s010": {"go": "s020"},
                                            "s020": {"go": "s030"}, "s030": {}},
                order=["s010", "s020", "s030"])
    rep = lint(root)
    assert not any("недостижима" in e or "тупик" in e for e in rep.errors)
    assert not any("тупик" in w for w in rep.warnings)


def test_assets_src_binary_budget_guard(repo_root, tmp_path):
    """ADR-0004: порог бинарей в git — проверяемый, а не устный (история append-only)."""
    from vn.content import lint as lintmod

    root = _copy_skeleton(repo_root, tmp_path)
    src = root / "assets_src" / "png"
    src.mkdir(parents=True)
    limit = lintmod.ADR0004_BINARY_LIMIT_MB
    (src / "huge.png").write_bytes(b"\0" * int((limit + 1) * 1024 * 1024))
    rep = lint(root)
    assert any("порога ADR-0004" in e and "huge.png" in e for e in rep.errors)

    # Манифесты/декларации не считаются бинарями — они и должны жить в git
    (src / "huge.png").unlink()
    (src / "big.png.manifest.json").write_bytes(b"x" * 1024)
    assert not any("ADR-0004" in e for e in lint(root).errors)


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


def test_released_asset_disappearance_is_error(repo_root, tmp_path):
    """Ассет — такой же выпущенный id, как сцена: галерея открывает картинки по
    имени образа, и молчаливое исчезновение стирает игроку прогресс (ADR-0012)."""
    import json

    root = _copy_skeleton(repo_root, tmp_path)
    (root / "game" / "assets" / "cg" / "ch01").mkdir(parents=True)
    (root / "game" / "assets" / "cg" / "ch01" / "kept.webp").write_bytes(b"x")
    reg = root / "content" / "registry" / "id_registry.json"
    doc = json.loads(reg.read_text(encoding="utf-8"))
    doc["assets"] = ["cg/ch01/kept", "cg/ch01/gone"]
    reg.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    rep = lint(root)
    assert any("cg/ch01/gone" in e and "renames.assets" in e for e in rep.errors)
    assert not any("cg/ch01/kept" in e for e in rep.errors)

    # Запись в renames.assets снимает ошибку — это и есть штатный путь переименования
    (root / "content" / "renames.yaml").write_text(
        "schema: renames@1\nscenes: {}\ndeleted_scenes: {}\nlabels: {}\nvars: {}\n"
        "assets: {cg/ch01/gone: cg/ch01/kept}\n", encoding="utf-8")
    rep2 = lint(root)
    assert not any("cg/ch01/gone" in e for e in rep2.errors)


def test_non_lfs_binary_in_assets_src_is_error(repo_root, tmp_path):
    """История git append-only: бинарь мимо LFS оседает в ней целиком и навсегда.
    Покрытие определяет сам git (check-attr) — в корне без .git проверка молчит."""
    import subprocess

    root = _copy_skeleton(repo_root, tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    (root / ".gitattributes").write_text(
        "assets_src/**/*.png filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    src = root / "assets_src" / "art" / "cg"
    src.mkdir(parents=True)
    (src / "covered.png").write_bytes(b"\x89PNG covered")
    (src / "loose.tga").write_bytes(b"raw-bytes-outside-lfs")

    rep = lint(root)
    assert any("loose.tga" in e and "LFS" in e for e in rep.errors)
    assert not any("covered.png" in e for e in rep.errors)

def test_lint_catches_chapter_number_collision(repo_root, tmp_path):
    """Одинаковый номер главы в ядре и в паке раньше молча затирал запись: по
    затёртой главе не выполнялись ни достижимость, ни сверка exits. id сцен плоские
    (chNN_sNNN), так что коллизия номера — это коллизия идентификаторов."""
    from vn.content.lint import lint

    root = _copy_skeleton(repo_root, tmp_path)

    def _chapter(base):
        base.mkdir(parents=True, exist_ok=True)
        (base.parent / "chapter.yaml").write_text(
            "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
            "status: draft\nentry_scene: s010\nscene_order: [s010]\n", encoding="utf-8")
        (base / "s010_x.scene.yaml").write_text("schema: scene@1\nid: s010\nexits: {}\n",
                                                encoding="utf-8")
        (base / "s010_x.scene.rpy").write_text(
            'label ch01_s010__body:\n    "…"\n    return\n', encoding="utf-8")

    _chapter(root / "content" / "chapters" / "ch01_core" / "scenes")
    pack = root / "packs" / "ep_beach" / "chapters" / "ch01_clash" / "scenes"
    pack.mkdir(parents=True, exist_ok=True)
    (pack.parent / "chapter.yaml").write_text(
        "schema: chapter@1\nid: ch01\ntitle_key: meta.chapters.ch01.title\n"
        "status: draft\nentry_scene: s010\nscene_order: [s010]\n", encoding="utf-8")
    (pack / "s010_clash.scene.yaml").write_text("schema: scene@1\nid: s010\nexits: {}\n",
                                                encoding="utf-8")
    (pack / "s010_clash.scene.rpy").write_text(
        'label ch01_s010__body:\n    "…"\n    return\n', encoding="utf-8")

    rep = lint(root)
    assert any("номер главы ch01 уже занят" in e for e in rep.errors), rep.errors


def test_lint_reports_broken_migration_registry_instead_of_crashing(repo_root, tmp_path):
    """Линтер обязан ДОЛОЖИТЬ, а не упасть: битый registry.yaml уже получил
    внятную ошибку от схемы, и трейсбек из секции миграций спрятал бы её за стеком."""
    root = _copy_skeleton(repo_root, tmp_path)
    (root / "content" / "migrations" / "registry.yaml").write_text(
        "schema: migrations_registry@1\nreserved:\n  - not-a-mapping\n",
        encoding="utf-8")

    rep = lint(root)                       # падения быть не должно
    assert rep.errors, "битый реестр брони обязан краснить lint"


def test_lint_catches_migration_slug_not_matching_reservation(repo_root, tmp_path):
    """Бронь номера без сверки слага — формальность: под номером в реестре может
    стоять совсем другая миграция, и разбор истории сейвов уйдёт по ложному следу."""
    root = _copy_skeleton(repo_root, tmp_path)
    mig = root / "content" / "migrations"
    (mig / "0002_route_prologue.py").rename(mig / "0002_something_else.py")

    rep = lint(root)
    assert any("slug не совпадает с бронью" in e for e in rep.errors), rep.errors
