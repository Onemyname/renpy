"""Достижения (achievements@1): эмиссия реестра, валидация якорей и контракт
экрана достижений с реестром.
Ачивки привязаны к стабильным якорям (scene/beat/var), поэтому добавляются
без правки уже написанных и переведённых сцен."""

import ast
import re

import polib
import pytest

from vn.content.compile import _emit_achievements

SCREEN = "game/framework/20_ui/screens/achievements.rpy"
NAV = "game/framework/20_ui/screens/core_screens.rpy"

# Обращения экрана к записи реестра: spec["<поле>"].
_SPEC_FIELD_RE = re.compile(r'spec\["([a-z_]+)"\]')
# Ключи строк, которые экран берёт из content/ui/strings.yaml.
_LOC_KEY_RE = re.compile(r'vn_loc\.t\("([a-z0-9_.]+)"\)')


def _doc(**achievements):
    return [("content/achievements/core.achievements.yaml",
             {"schema": "achievements@1", "achievements": achievements})]


def _screen_src(repo_root):
    return (repo_root / SCREEN).read_text(encoding="utf-8")


def _statements(src):
    """Инструкции вёрстки: строки-комментарии выброшены, перенос по незакрытой
    скобке склеен. Проверять гейт по ФИЗИЧЕСКИМ строкам нельзя — перевод
    выражения на вторую строку выглядел бы как обход гейта."""
    out, buf, depth = [], "", 0
    for line in src.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        buf = line if not buf else buf + " " + line.strip()
        depth = sum(buf.count(o) - buf.count(c) for o, c in ("()", "[]", "{}"))
        if depth <= 0:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _repo_registry(repo_root):
    """Реестр так, как его увидит рантайм: эмиттер на боевых декларациях."""
    from vn.repo import load_yaml

    path = repo_root / "content" / "achievements" / "core.achievements.yaml"
    if not path.is_file():
        pytest.skip("деклараций достижений нет")
    doc = load_yaml(path)
    text = _emit_achievements([(path.name, doc)], [("src", "0")])
    body = text.split("define VN_ACHIEVEMENTS = ", 1)[1].strip()
    return doc, ast.literal_eval(body)


def test_emit_registry_with_defaults():
    docs = _doc(
        met={"name_key": "ach.met.name", "trigger": {"var": "ch01.met_mira"}},
        roof={"name_key": "ach.roof.name", "desc_key": "ach.roof.desc",
              "hidden": True, "nsfw": True, "pack": "nsfw",
              "trigger": {"scene": "ch01_s030"}},
    )
    text = _emit_achievements(docs, [("src", "deadbeef")])
    assert "define VN_ACHIEVEMENTS = " in text
    # var-триггер без equals получает дефолт True (иначе рантайму пришлось бы гадать)
    assert "'equals': True" in text
    assert "'pack': 'core'" in text          # дефолт пака
    assert "'nsfw': True" in text and "'hidden': True" in text


def test_emit_empty_is_valid():
    text = _emit_achievements([], [("project.yaml", "0")])
    assert "define VN_ACHIEVEMENTS = {}" in text


def test_schema_rejects_multiple_triggers(repo_root):
    """oneOf: ровно один якорь — иначе неоднозначно, когда выдавать."""
    from vn.schemas import SchemaRegistry

    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    bad = {"schema": "achievements@1", "achievements": {
        "roof_reached": {"name_key": "a.b",
                         "trigger": {"scene": "ch01_s010", "beat": "kiss"}}}}
    assert reg.validate(bad, "test") != []

    good = {"schema": "achievements@1", "achievements": {
        "roof_reached": {"name_key": "a.b", "trigger": {"scene": "ch01_s010"}}}}
    assert reg.validate(good, "test") == []


def test_repo_achievements_are_valid(repo_root):
    """Боевые декларации проходят схему и ссылаются на существующие якоря."""
    from vn.repo import load_yaml
    from vn.schemas import SchemaRegistry

    path = repo_root / "content" / "achievements" / "core.achievements.yaml"
    if not path.is_file():
        pytest.skip("деклараций достижений нет")
    doc = load_yaml(path)
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    assert reg.validate(doc, path.name) == []

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    for aid, spec in doc["achievements"].items():
        assert spec["name_key"] in strings, f"{aid}: name_key вне strings.yaml"
        if spec.get("desc_key"):
            assert spec["desc_key"] in strings, f"{aid}: desc_key вне strings.yaml"


# ── Экран достижений (20_ui/screens/achievements.rpy) ─────────────────────────
# Проверяется то, что проверяемо статически: экран существует, достижим из
# навигации, не держит у себя ни одного достижения и читает у реестра ровно те
# поля, которые реестр эмитит. Рантайм-часть (persistent, выдача) — e2e в
# vn test smoke, вёрстка — скриншотами VN_AUTOPILOT_SCREENS=achievements.


def test_screen_exists_and_is_reachable_from_navigation(repo_root):
    """Пробел, который экран закрывает: бэкенд ачивок был полон, а показать их
    игроку было нечем. Пункт рельсы гейтится ДАННЫМИ (visible_ids), иначе в
    сборке без ачивок он вёл бы в пустой экран."""
    src = _screen_src(repo_root)
    assert "screen achievements():" in src
    assert 'use vn_game_menu(vn_loc.t("ui.nav.achievements")):' in src

    nav = (repo_root / NAV).read_text(encoding="utf-8")
    assert 'ShowMenu("achievements")' in nav
    assert "if vn_ach.visible_ids():" in nav


def test_screen_holds_no_achievement_data(repo_root):
    """«Только данные»: ни id, ни ключей, ни текстов ачивок в вёрстке — иначе
    новая ачивка требовала бы правки экрана (и разъезжалась бы с реестром)."""
    from vn.repo import load_yaml

    src = _screen_src(repo_root)
    doc, _rows = _repo_registry(repo_root)
    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    for aid, spec in doc["achievements"].items():
        assert aid not in src, f"{aid}: id достижения захардкожен в экране"
        for key in (spec["name_key"], spec.get("desc_key")):
            if not key:
                continue
            assert key not in src, f"{key}: ключ строки захардкожен в экране"
            assert strings[key] not in src, f"{key}: текст скопирован в экран"


def test_registry_emits_every_field_the_screen_reads(repo_root):
    """Дрейф «экран читает spec[...] — эмиттер поле не пишет» = KeyError в
    рантайме на живом экране. Поля берём из самого экрана, не из списка."""
    used = set(_SPEC_FIELD_RE.findall(_screen_src(repo_root)))
    # Парсер молча «починился бы», сломавшись: экран обязан что-то читать.
    assert "name_key" in used and "hidden" in used, used

    _doc_, rows = _repo_registry(repo_root)
    assert rows, "боевой реестр пуст — проверять нечего"
    for aid, spec in rows.items():
        missing = used - set(spec)
        assert not missing, f"{aid}: реестр не эмитит поля {sorted(missing)}"


def test_hidden_achievement_is_never_spoiled_by_layout(repo_root):
    """Скрытая ачивка до получения не раскрывается ничем: и название, и описание
    проходят через ОДИН спойлер-гейт, поэтому настоящий текст не попадает в
    дерево отображения даже под другим стилем."""
    stmts = _statements(_screen_src(repo_root))

    gate = [s for s in stmts if "_spoiler =" in s]
    assert len(gate) == 1, "спойлер-гейт должен быть ровно один"
    assert '"hidden"' in gate[0] and "_got" in gate[0], (
        "гейт обязан учитывать и флаг hidden, и факт получения")
    got = [s for s in stmts if "_got =" in s]
    assert got and "vn_ach.has(" in got[0], "получение спрашивается у vn_ach"

    for stmt in stmts:
        if "name_key" in stmt or "desc_key" in stmt:
            assert "_spoiler" in stmt, f"текст ачивки вне гейта: {stmt.strip()}"


def test_screen_string_keys_are_declared(repo_root):
    """Незадекларированный ключ vn_loc.t не падает, а рисует сам ключ — такую
    опечатку видно только глазами на живом экране, поэтому её ловит тест."""
    from vn.repo import load_yaml

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    keys = set(_LOC_KEY_RE.findall(_screen_src(repo_root)))
    assert "ui.nav.achievements" in keys, keys
    for key in sorted(keys):
        assert key in strings, f"{key}: нет в content/ui/strings.yaml"


def test_progress_counter_interpolates_screen_locals(repo_root):
    """Счётчик «получено N из M» собирается интерполяцией строки, то есть имена
    экранных локалей — часть контракта с переводом. Разъедутся — игрок увидит
    сами скобки, и ни lint, ни компиляция об этом не скажут."""
    from vn.repo import load_yaml

    src = _screen_src(repo_root)
    template = load_yaml(
        repo_root / "content" / "ui" / "strings.yaml")["strings"]["ui.ach.progress"]
    names = set(re.findall(r"\[([a-z_]+)\]", template))
    assert names, "в ui.ach.progress нет подстановок — счётчик не соберётся"
    for name in sorted(names):
        assert re.search(r"^\s*\$ .*\b%s\b.*=" % name, src, re.M), (
            f"[{name}] в ui.ach.progress: экран такой локали не объявляет")
    assert "vn_ach.progress()" in src, "счётчик обязан считаться из реестра"

    # Перевод, потерявший подстановку, ломает счётчик тише всего — на языке,
    # который разработчик не открывает.
    for po_path in sorted((repo_root / "loc" / "po").glob("*/common.po")):
        entry = polib.pofile(str(po_path)).find(
            "string:ui.ach.progress", by="msgctxt")
        if entry is None or not entry.msgstr:
            continue
        for name in sorted(names):
            assert f"[{name}]" in entry.msgstr, (
                f"{po_path.parent.name}: перевод счётчика потерял [{name}]")

# ── Прогрессивные достижения (goal) ──────────────────────────────────────────

def test_emit_progressive_achievement_carries_goal_without_equals():
    """Прогресс = накопление, поэтому equals прогрессивной ачивке не подставляется:
    иначе в реестре осталось бы мёртвое поле, а рантайму пришлось бы решать, что
    из двух правил главнее."""
    docs = _doc(explorer={"name_key": "ach.explorer.name",
                          "trigger": {"var": "g.scenes_seen"},
                          "goal": {"total": 3}})
    text = _emit_achievements(docs, [("src", "deadbeef")])
    assert "'goal': {'total': 3, 'step': 1}" in text     # step по умолчанию 1
    assert "'equals'" not in text


def test_schema_accepts_goal_and_rejects_broken_goal(repo_root):
    from vn.schemas import SchemaRegistry

    reg = SchemaRegistry(repo_root / "tools" / "schemas")

    def doc(goal):
        return {"schema": "achievements@1", "achievements": {
            "explorer": {"name_key": "a.b", "trigger": {"var": "g.scenes_seen"},
                         "goal": goal}}}

    assert reg.validate(doc({"total": 3}), "t") == []
    assert reg.validate(doc({"total": 3, "step": 2}), "t") == []
    assert reg.validate(doc({"total": 1}), "t") != []          # цель из одного шага — это бинарная ачивка
    assert reg.validate(doc({"step": 2}), "t") != []           # без total прогресс не определён
    assert reg.validate(doc({"total": 3, "x": 1}), "t") != []  # additionalProperties: false


def test_compiler_rejects_goal_without_counter(repo_root, tmp_path):
    """goal на scene/beat-триггере или вместе с equals — ачивка выдалась бы разом,
    и игрок не увидел бы ни одного шага прогресса. Ловит компилятор, не рантайм."""
    import shutil

    from vn.content.compile import CompileError, compile_content
    from vn.content.lint import REQUIRED_DIRS

    root = tmp_path / "repo"
    root.mkdir()
    for name in ("project.yaml", ".vnstorage.yaml"):
        shutil.copy(repo_root / name, root / name)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    shutil.copytree(repo_root / "content", root / "content")
    shutil.rmtree(root / "content" / "chapters")
    (root / "content" / "chapters").mkdir()
    shutil.rmtree(root / "content" / "locations")
    (root / "content" / "locations").mkdir()
    for d in REQUIRED_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    ach = root / "content" / "achievements" / "core.achievements.yaml"
    base = ach.read_text(encoding="utf-8")

    ach.write_text(base + "\n  bad_scene_goal:\n    name_key: ach.met_mira.name\n"
                          "    trigger: {scene: ch01_s010}\n    goal: {total: 3}\n",
                   encoding="utf-8")
    with pytest.raises(CompileError, match="goal требует trigger.var"):
        compile_content(root, out_dir=tmp_path / "gen")

    ach.write_text(base + "\n  bad_equals_goal:\n    name_key: ach.met_mira.name\n"
                          "    trigger: {var: g.scenes_seen, equals: 3}\n"
                          "    goal: {total: 3}\n",
                   encoding="utf-8")
    with pytest.raises(CompileError, match="взаимоисключают"):
        compile_content(root, out_dir=tmp_path / "gen")


def test_runtime_progress_contract(repo_root):
    """Рантайм-контракт прогресса (проверяем исходник ядра, как и остальные тесты
    этого набора): счётчик читает переменную триггера, длину списка считает
    прогрессом, значение ограничено целью, а сообщённый прогресс живёт в
    отдельном persistent — старый persistent обязан читаться как пустой."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "080_achievements.rpy").read_text(encoding="utf-8")
    assert "def counter(" in src and "def goal_of(" in src
    assert "len(value)" in src, "длина списка не считается прогрессом"
    assert "min(int(value), int(goal[\"total\"]))" in src, "прогресс не ограничен целью"
    assert "default persistent.vn_ach_progress = {}" in src
    assert "def set_progress_provider(" in src
    # Порог уведомления считается по уже сообщённому значению, иначе попап
    # дёргался бы на каждой смене состояния.
    assert "(value // step) > (reported // step)" in src


def test_steam_registers_goal_with_stat_max(repo_root):
    """Прогрессивную ачивку движок умеет показывать сам («N из M»), но только
    если при регистрации знает цель и шаг."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "035_platform.rpy").read_text(encoding="utf-8")
    assert "stat_max=" in src and "stat_modulo=" in src
    assert "vn_ach.set_progress_provider(achievement.progress)" in src


def test_progress_is_not_shown_for_hidden_achievement(repo_root):
    """Прогресс скрытой ачивки — тот же спойлер, что описание: он выдал бы, ЧТО
    именно надо собрать."""
    src = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "achievements.rpy").read_text(encoding="utf-8")
    card = src.split("screen vn_ach_card(", 1)[1]
    assert "None if _spoiler else vn_ach.goal_of(ach_id)" in card
