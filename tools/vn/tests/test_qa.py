"""vn test screens | paths | replay — машинерия прогонов и разбор их артефактов.

Движок здесь не запускается: артефакты прогона выкладываются на диск руками, а
проверяется наша логика — парсер трассы, сборка вердикта, покрытие, сверка повтора.
Прогон под движком покрыт контракт-тестами (`test_engine_compat.py`) и живыми
командами; дублировать его в юнитах значило бы гонять минуты вместо миллисекунд.
"""

from __future__ import annotations

import json

import pytest

from helpers import mk_root, mk_root_with_schemas
from vn import qa
from vn.qa import (
    QaError,
    parse_picks_log,
    read_run,
    replay_diff,
    replay_records,
    run_failures,
    tour_screens,
    write_record,
)


def _artifacts(root, *, result="OK: vn_end_of_content", picks="menu 0 -> pick 1 (ch01_s010_m001)",
               state=None, gallery=None, screens=None, perf=None, shots=3,
               name="run"):
    d = root / ".vncache" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    for i in range(shots):
        (d / f"shot{i:03d}.png").write_bytes(b"\x89PNG")
    (d / "startup.txt").write_text("1.42\n", encoding="utf-8")
    if picks is not None:
        (d / "picks.log").write_text(picks + "\n", encoding="utf-8")
    for fname, doc in (("state.json", state), ("gallery.json", gallery),
                       ("screens.json", screens), ("perf.json", perf)):
        if doc is not None:
            (d / fname).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d


# ── Трасса выборов: единственный парсер этого формата ─────────────────────────

def test_parse_picks_log_reads_menu_and_scene():
    picks = parse_picks_log("menu 0 -> pick 1 (ch01_s010_m001)\n"
                            "menu 1 -> pick 0 (ch01_s020_m001)\n")
    assert [(p.menu_index, p.idx, p.menu_id) for p in picks] == [
        (0, 1, "ch01_s010_m001"), (1, 0, "ch01_s020_m001")]
    assert picks[0].scene_id == "ch01_s010", "сцена берётся срезом id меню"


def test_parse_picks_log_ignores_foreign_lines():
    """В логе могут оказаться чужие строки (движок пишет туда же) — парсер обязан
    брать только свой формат, а не падать и не выдумывать записи."""
    assert parse_picks_log("мусор\nmenu 2 -> pick 0 (ch01_s030_m001)\n") != []
    assert len(parse_picks_log("мусор\n")) == 0


def test_pick_without_menu_convention_has_no_scene():
    picks = parse_picks_log("menu 0 -> pick 0 (какое-то_меню)\n")
    assert picks[0].scene_id is None


# ── Чтение прогона и вердикт ──────────────────────────────────────────────────

def test_read_run_collects_every_artifact(tmp_path):
    root = mk_root(tmp_path)
    d = _artifacts(root, state={"g.route": "prologue"}, gallery={"ids": ["cg_a"]},
                   screens={"shown": ["main_menu"]}, perf={"baseline_rss_mb": 420.5})
    art = read_run(root, d)
    assert art.ok and art.shots == 3 and art.cold_start_s == 1.42
    assert art.state == {"g.route": "prologue"} and art.gallery["ids"] == ["cg_a"]
    assert art.perf["baseline_rss_mb"] == 420.5 and art.picks[0].idx == 1


def test_read_run_survives_missing_and_broken_files(tmp_path):
    """Отсутствие артефакта — тоже факт, и он не должен ломать чтение: иначе
    упавший прогон нельзя было бы даже разобрать."""
    root = mk_root(tmp_path)
    d = root / ".vncache" / "empty"
    d.mkdir(parents=True)
    (d / "state.json").write_text("{битый", encoding="utf-8")
    (d / "startup.txt").write_text("не число", encoding="utf-8")
    art = read_run(root, d)
    assert not art.ok and art.result == "нет RESULT.txt"
    assert art.state == {} and art.cold_start_s is None


def test_run_failures_names_traceback_first(tmp_path):
    """Порядок причин — от самой информативной: traceback объясняет остальные."""
    root = mk_root(tmp_path)
    d = _artifacts(root, result="FAIL: сцена не найдена")
    (root / "traceback.txt").write_text("Traceback…", encoding="utf-8")
    fails = run_failures(read_run(root, d), 1, False, 180)
    assert "traceback" in fails[0] and any("FAIL" in f for f in fails)


def test_run_failures_empty_on_green_run(tmp_path):
    root = mk_root(tmp_path)
    art = read_run(root, _artifacts(root))
    assert run_failures(art, 0, False, 180) == []


def test_run_failures_distinguishes_timeout_from_exit_code(tmp_path):
    root = mk_root(tmp_path)
    art = read_run(root, _artifacts(root))
    assert any("не завершилась" in f for f in run_failures(art, -1, True, 30))
    assert any("вернул 3" in f for f in run_failures(art, 3, False, 30))


# ── Декларация тура по экранам ────────────────────────────────────────────────

def test_tour_screens_reads_declaration(tmp_path):
    root = mk_root(tmp_path)
    (root / "content" / "ui").mkdir(parents=True)
    (root / "content" / "ui" / "screens.yaml").write_text(
        "schema: qa_screens@1\nscreens:\n  - name: main_menu\n    why: точка входа\n"
        "  - name: gallery\n    why: сетка\n    kwargs: {page: 1}\n", encoding="utf-8")
    tour = tour_screens(root)
    assert [e["name"] for e in tour] == ["main_menu", "gallery"]
    assert tour[1]["kwargs"] == {"page": 1}


def test_tour_screens_without_declaration_is_empty(tmp_path):
    assert tour_screens(mk_root(tmp_path)) == []


def test_repo_tour_covers_every_project_screen(repo_root):
    """Гейт «экран есть в игре, но его никто не проверяет» держится на декларации:
    если экран не в туре и не в ignore_defined, `vn test screens` краснеет. Здесь то
    же самое проверяется статически — по объявлениям `screen <имя>` в исходниках,
    чтобы забытый экран ловился без прогона движка."""
    import re

    declared = set()
    for rpy in sorted((repo_root / "game" / "framework").rglob("*.rpy")):
        declared |= set(re.findall(r"^screen ([a-z_][a-z0-9_]*)", rpy.read_text(encoding="utf-8"),
                                   re.M))
    doc = json.loads(json.dumps(  # через json, чтобы не тянуть yaml в тест
        {"screens": [e for e in tour_screens(repo_root)]}))
    from vn.repo import load_yaml

    decl = load_yaml(repo_root / "content" / "ui" / "screens.yaml")
    covered = {e["name"] for e in doc["screens"]} | set(decl.get("ignore_defined") or [])
    uncovered = sorted(n for n in declared - covered if not n.startswith("_"))
    assert uncovered == [], (
        f"экраны без покрытия туром: {uncovered} — добавьте в content/ui/screens.yaml "
        f"или в ignore_defined с причиной")


# ── Записи повтора ────────────────────────────────────────────────────────────

def test_write_record_from_artifacts(tmp_path):
    root = mk_root(tmp_path)
    art = read_run(root, _artifacts(root, state={"g.route": "mira"},
                                    gallery={"ids": ["cg_b", "cg_a"]}))
    path = write_record(root, "route-mira", "держит ветку с CG", art, picks="0,1",
                        lang="", variant="", content_version="0.1.5",
                        recorded_at="2026-08-18T00:00:00Z")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "replay@1" and doc["input"]["picks"] == [0, 1]
    assert doc["expect"]["gallery_ids"] == ["cg_a", "cg_b"], "ids сортируются"
    assert doc["expect"]["picks"] == ["ch01_s010_m001#1"]


def test_write_record_refuses_red_run(tmp_path):
    """Запись фиксирует ОЖИДАЕМЫЙ результат. Записать красный прогон значит
    закрепить поломку как норму."""
    root = mk_root(tmp_path)
    art = read_run(root, _artifacts(root, result="FAIL: нет сцены"))
    with pytest.raises(QaError, match="не зелёный"):
        write_record(root, "bad", "почему", art, picks="0", lang="", variant="",
                     content_version="0.1.5", recorded_at="сейчас")


def test_written_record_passes_its_schema(tmp_path, repo_root):
    from vn.schemas import SchemaRegistry

    root = mk_root_with_schemas(tmp_path, repo_root)
    art = read_run(root, _artifacts(root, state={"g.route": "x"}, gallery={"ids": []}))
    path = write_record(root, "route-x", "зачем", art, picks="0", lang="ru",
                        variant="steam_deck", content_version="0.1.5",
                        recorded_at="2026-08-18T00:00:00Z")
    errors = SchemaRegistry(root / "tools" / "schemas").validate(
        json.loads(path.read_text(encoding="utf-8")), path.name)
    assert errors == []


def test_replay_records_unknown_name_points_at_recording(tmp_path):
    root = mk_root(tmp_path)
    with pytest.raises(QaError, match="vn test smoke --record"):
        replay_records(root, "нет-такой")


def test_replay_records_reads_all(tmp_path):
    root = mk_root(tmp_path)
    base = root / "ci" / "fixtures" / "replays"
    base.mkdir(parents=True)
    for name in ("a", "b"):
        (base / f"{name}.vnrec.json").write_text(
            json.dumps({"schema": "replay@1", "name": name}), encoding="utf-8")
    assert [r["name"] for _p, r in replay_records(root)] == ["a", "b"]


# ── Сверка повтора ────────────────────────────────────────────────────────────

def _record(**over):
    rec = {
        "schema": "replay@1", "name": "r", "why": "w",
        "recorded_at": "2026-08-18T00:00:00Z", "content_version": "0.1.5",
        "input": {"picks": [0, 1]},
        "expect": {"result": "OK: vn_end_of_content",
                   "picks": ["ch01_s010_m001#1"],
                   "state": {"g.route": "prologue"},
                   "gallery_ids": ["cg_a"]},
    }
    rec.update(over)
    return rec


def _with_version(root, version="0.1.5"):
    gen = root / "game" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "version.gen.rpy").write_text(
        f'define config.version = "{version}+abc1234"\n\n'
        f'define build.version = "{version}"\n', encoding="utf-8")


def test_replay_diff_empty_when_reproduced(tmp_path):
    root = mk_root(tmp_path)
    _with_version(root)
    art = read_run(root, _artifacts(root, state={"g.route": "prologue"},
                                    gallery={"ids": ["cg_a"]}))
    assert replay_diff(root, _record(), art) == []


def test_replay_diff_names_the_changed_variable(tmp_path):
    """Расхождение состояния обязано называть КОНКРЕТНУЮ переменную: «состояние не
    совпало» на снапшоте из десятков ключей бесполезно."""
    root = mk_root(tmp_path)
    _with_version(root)
    art = read_run(root, _artifacts(root, state={"g.route": "mira"},
                                    gallery={"ids": ["cg_a"]}))
    diffs = replay_diff(root, _record(), art)
    assert any("состояние g.route" in d and "mira" in d for d in diffs)


def test_replay_diff_catches_changed_trace(tmp_path):
    root = mk_root(tmp_path)
    _with_version(root)
    art = read_run(root, _artifacts(root, picks="menu 0 -> pick 0 (ch01_s010_m001)",
                                    state={"g.route": "prologue"},
                                    gallery={"ids": ["cg_a"]}))
    assert any("трасса выборов" in d for d in replay_diff(root, _record(), art))


def test_replay_diff_catches_gallery_drift(tmp_path):
    root = mk_root(tmp_path)
    _with_version(root)
    art = read_run(root, _artifacts(root, state={"g.route": "prologue"},
                                    gallery={"ids": []}))
    assert any("галерея" in d for d in replay_diff(root, _record(), art))


def test_replay_survives_a_commit(tmp_path):
    """Запись обязана переживать коммит: `config.version` несёт git-sha и меняется
    на каждом, а сверка идёт по ПОСТАВОЧНОЙ версии (`build.version`) — иначе все
    записи обнулялись бы после любой правки, и ночная джоба была бы вечно красной."""
    root = mk_root(tmp_path)
    gen = root / "game" / "generated"
    gen.mkdir(parents=True)
    (gen / "version.gen.rpy").write_text(
        'define config.version = "0.1.5+ffffff9"\n\ndefine build.version = "0.1.5"\n',
        encoding="utf-8")
    art = read_run(root, _artifacts(root, state={"g.route": "prologue"},
                                    gallery={"ids": ["cg_a"]}))
    assert replay_diff(root, _record(content_version="0.1.5"), art) == []


def test_replay_diff_stops_on_version_drift(tmp_path):
    """На другом контенте расхождение состояния ничего не доказывает — сверять его
    молча значит выдавать ложную панику вместо «перезапишите запись»."""
    root = mk_root(tmp_path)
    _with_version(root, "0.2.0")
    art = read_run(root, _artifacts(root, state={"g.route": "что угодно"}))
    diffs = replay_diff(root, _record(), art)
    assert len(diffs) == 1 and "перезапишите" in diffs[0]


# ── Рантайм-бюджеты вместо команды vn test perf ───────────────────────────────

def test_runtime_budgets_check_three_numbers(tmp_path):
    """G19 требует cold start, пик RSS и вес .rpyc. Отдельной команды нет (ADR-0019):
    числа снимает прогон, который и так делается."""
    from vn.release import runtime_budget_failures

    root = mk_root(tmp_path, budgets={"cold_start_s": 5, "baseline_rss_mb": 500,
                                      "rpyc_total_kb": 1})
    (root / "game").mkdir(exist_ok=True)
    (root / "game" / "big.rpyc").write_bytes(b"\0" * 4096)
    fails = runtime_budget_failures(root, cold_start_s=7.5, baseline_rss_mb=800)
    assert any("cold start" in f for f in fails)
    assert any("RSS" in f for f in fails)
    assert any(".rpyc" in f for f in fails)


def test_runtime_budgets_silent_without_declarations(tmp_path):
    """Бюджет не объявлен — проверять нечего; выдумывать потолок инструмент не имеет
    права (числа задаёт проект, ADR-0012)."""
    from vn.release import runtime_budget_failures

    root = mk_root(tmp_path)
    assert runtime_budget_failures(root, cold_start_s=999, baseline_rss_mb=99999) == []


def test_perf_command_does_not_exist():
    """`vn test perf` не создаётся намеренно (ADR-0019): референсного слабого железа
    и Android-эмулятора нет, а команда, которая не может сделать свою работу, — это
    заглушка, которых норма не допускает."""
    from vn import cli

    assert "perf" not in cli.test.commands


def test_autopilot_template_is_gated_on_env():
    """Осиротевший autopilot.rpyc без переменной окружения обязан быть мёртвым:
    иначе обычный `vn play` превращается в самопроигрывающуюся игру."""
    assert "if not vn_qa.autopilot_active()" in qa.AUTOPILOT_RPY
    assert "renpy.quit(save=False)" in qa.AUTOPILOT_RPY


def test_screens_gate_fails_when_the_tour_did_not_report(repo_root):
    """Гейт тура не имеет права зеленеть на отсутствующем отчёте.

    Весь он стоит на содержимом screens.json: без файла все множества пусты,
    проверка «экран не покрыт туром» отключается своим `if defined:` — и команда
    печатала зелёное «показано 0 из N». То есть ОТСУТСТВИЕ отчёта трактовалось
    как «всё хорошо», а записи может не быть при любом исключении в дампе
    рантайма (прогон при этом завершается нормально, код возврата нулевой).

    Второй инвариант рядом: объявленный экран обязан попасть РОВНО в один из
    трёх исходов. Раньше гейт верил, что рантайм честно разложил все имена, и
    экран, потерявшийся между списками, исчезал из проверки молча."""
    src = (repo_root / "tools" / "vn" / "src" / "vn" / "cli.py").read_text(
        encoding="utf-8")
    body = src.split('@test.command("screens")', 1)[1].split("\n@test.command", 1)[0]

    assert "if not art.screens:" in body, \
        "пустой отчёт тура не считается провалом"
    assert "declared - optional - shown - set(failed) - missing" in body, \
        "экран без отчёта ни в одном из трёх списков проходит гейт молча"


def test_every_autopilot_run_pins_the_language(repo_root):
    """Язык автопилотного прогона обязан быть ДЕТЕРМИНИРОВАННЫМ.

    Без переменной VN_AUTOPILOT_LANG движок язык не трогает (030_flow.rpy), то есть
    берёт persistent-язык, оставшийся от ПРЕДЫДУЩЕГО прогона, а `--savedir`
    persistent не изолирует (savelocation поднимает и config.savedir, и
    <gamedir>/saves).

    В nightly шаги идут в одном job последовательно, и последний smoke матрицы
    ставит pseudo — после чего тур экранов, покрытие ветвления, пересмотр сцен и
    проверка сейв-корпуса шли по ПСЕВДОЛОКАЛИЗАЦИИ. То есть `vn test screens`
    никогда не проверял то, для чего заведён. Локально гейт давал разный ответ на
    одном коммите в зависимости от истории машины.

    Пин стоит в ОДНОМ месте — обёртке `_autopilot_run`, — а не у каждого вызова:
    правило, которое обязан помнить автор новой команды, рано или поздно забудут
    (так и вышло: deck-kit пиннил, остальные пять команд — нет)."""
    src = (repo_root / "tools" / "vn" / "src" / "vn" / "cli.py").read_text(
        encoding="utf-8")
    body = src.split("def _autopilot_run(", 1)[1].split("\n@", 1)[0]
    assert "VN_AUTOPILOT_LANG" in body, \
        "обёртка автопилота не пиннит язык — прогон возьмёт язык прошлого прогона"
    assert '"@source"' in body, \
        "дефолт пина не @source: прогон не сбрасывает persistent-язык явно"
    # И ни один вызов не имеет права остаться без пина по недосмотру: обёртка
    # обязана быть единственной точкой запуска.
    assert "autopilot_run(root, shots" not in src.split(
        "def _autopilot_run(", 1)[0], \
        "есть вызов qa.autopilot_run мимо обёртки — язык там не пиннится"


def test_screens_tour_recovers_the_ui_stack_and_names_the_root_cause(repo_root):
    """Одна поломка экрана не должна выдаваться за семь.

    Исключение при отрисовке оставляет непустой widget/layer-стек, и каждый
    следующий экран тура падал с «ui.interact called with non-empty widget/layer
    stack. Did you forget a ui.close() somewhere?» — сообщением, не имеющим
    отношения к причине. Release-инженер видел «7 проблем» и шесть одинаковых
    дампов стека, а корень был один и первый в списке.

    Стек возвращается в валидное состояние ШТАТНЫМ ui.reset() (он ставит
    [Layer("transient")], а не пустой список): ручное опустошение делает хуже —
    следующие экраны падают уже «Can't add displayable during init phase»."""
    flow = (repo_root / "game" / "framework" / "00_core"
            / "030_flow.rpy").read_text(encoding="utf-8")
    tour = flow.split("def autopilot_screens(", 1)[1].split("\n    def ", 1)[0]
    assert "reset()" in tour, \
        "тур не восстанавливает стек UI — одна поломка даст каскад ложных диагнозов"
    assert "cascade_after" in tour, \
        "тур не сообщает, после какого экрана он восстанавливался"

    cli = (repo_root / "tools" / "vn" / "src" / "vn" / "cli.py").read_text(
        encoding="utf-8")
    assert "cascade_after" in cli and "КОРЕНЬ" in cli, \
        "гейт не отделяет корень от каскада — вердикт называет не ту причину"


def test_orphan_rpyc_backup_never_ships(repo_root):
    """Осиротевший .rpyc движок ПЕРЕИМЕНОВЫВАЕТ в .bak, и он уезжал игроку.

    `renpy compile` (третий шаг `vn package`) чистит осиротевшие .rpyc не
    удалением, а os.rename(name, name + ".bak") — renpy/script.py:
    clean_script_files. Шаблона *.bak нет ни в early_base_patterns, ни в
    late_base_patterns движка, а последний паттерн там всеядный ("**", "all"):
    скомпилированный скрипт УДАЛЁННОГО контента попадал в каждый пакет и в каждый
    следующий релиз, потому что удалять .bak нечему — и линия .rpyc (G6), и бюджет
    rpyc_total_kb ходят по glob("*.rpyc").

    Для 18+ проекта это выдача дата-майнеру вырезанного контента (unrpyc —
    публичный инструмент), то есть ровно то, от чего защищается запрет зон в
    options.rpy. Риск повышен тем, что релизы собираются вручную на долгоживущем
    рабочем дереве, а не в свежем чекауте CI, где сирот не бывает."""
    options = (repo_root / "game" / "options.rpy").read_text(encoding="utf-8")
    assert 'build.classify("**.bak", None)' in options, \
        "*.bak не исключён из дистрибутива — уедет скомпилированный удалённый контент"

    cli = (repo_root / "tools" / "vn" / "src" / "vn" / "cli.py").read_text(
        encoding="utf-8")
    pkg = cli.split("def package", 1)[1].split("\n@", 1)[0]
    assert '"*.bak"' in pkg or "'*.bak'" in pkg, \
        "релизный путь не убирает .bak из рабочего дерева"
