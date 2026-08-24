"""Сейв-инфраструктура (G5): валидация цепочки миграций, эмиттеры snapshot/migrations,
решения рантайм-стора vn_state (снапшот и прогон цепочки)."""

import sys
import textwrap
import types

import pytest

from vn.content.compile import (CompileError, _collect_migrations, _emit_migrations,
                                _emit_snapshot, compile_content)


def _src_factory(root, errors):
    inputs = {}

    def src(path):
        rel = path.relative_to(root).as_posix()
        inputs[rel] = "0" * 16
        return rel, inputs[rel]

    return src


def _mk_migrations(tmp_path, files: dict, reserved: str):
    root = tmp_path / "repo"
    mig = root / "content" / "migrations"
    mig.mkdir(parents=True)
    (mig / "registry.yaml").write_text(reserved, encoding="utf-8")
    for name, body in files.items():
        (mig / name).write_text(body, encoding="utf-8")
    return root

MIG_OK = "def migrate(state):\n    return state\n"


def test_chain_validation_gap(tmp_path):
    root = _mk_migrations(
        tmp_path,
        {"0002_alpha.py": MIG_OK, "0004_beta.py": MIG_OK},
        "schema: migrations_registry@1\nreserved:\n"
        "  - {number: 2, slug: alpha, by: x}\n  - {number: 4, slug: beta, by: x}\n",
    )
    errors = []
    _collect_migrations(root, _src_factory(root, errors), {"save_schema": 4}, errors)
    assert any("цепочка [2, 4]" in e for e in errors)


def test_unreserved_number(tmp_path):
    root = _mk_migrations(
        tmp_path, {"0002_alpha.py": MIG_OK},
        "schema: migrations_registry@1\nreserved: []\n",
    )
    errors = []
    _collect_migrations(root, _src_factory(root, errors), {"save_schema": 2}, errors)
    assert any("не зарезервирован" in e for e in errors)


def test_schema_mismatch(tmp_path):
    root = _mk_migrations(
        tmp_path, {"0002_alpha.py": MIG_OK},
        "schema: migrations_registry@1\nreserved:\n  - {number: 2, slug: alpha, by: x}\n",
    )
    errors = []
    _collect_migrations(root, _src_factory(root, errors), {"save_schema": 3}, errors)
    assert any("!= ожидаемой [2, 3]" in e for e in errors)


def test_emit_migrations_embeds_source():
    out = _emit_migrations([(2, "0002_alpha.py", MIG_OK)], [("project.yaml", "0" * 16)])
    assert "_vn_load_migration(2," in out
    assert "def migrate(state):" in out          # исходник встроен
    assert "MIGRATIONS.sort" in out
    empty = _emit_migrations([], [("project.yaml", "0" * 16)])
    assert "миграций нет" in empty


def test_emit_snapshot_pairs():
    var_docs = [
        ("core.vars.yaml", {"store": "g", "vars": {"route": {}}}),
        ("ch01/vars.yaml", {"store": "ch01", "vars": {"met_mira": {}}}),
        ("meta.vars.yaml", {"store": "persistent", "vars": {"vn_seen": {}}}),
    ]
    out = _emit_snapshot(var_docs, [("project.yaml", "0" * 16)])
    assert "('ch01', 'met_mira')" in out
    assert "('g', 'route')" in out
    assert "persistent" not in out               # persistent живёт своим механизмом


def test_migration_chain_executes_like_runtime():
    """Тот же контракт, что и в игре: json-раундтрип -> цепочка -> результат."""
    import json

    src = ("def migrate(state):\n"
           "    if state.get('g.route') == 'common':\n"
           "        state['g.route'] = 'prologue'\n"
           "    return state\n")
    ns = {}
    exec(compile(src, "0002_x.py", "exec"), ns)
    state = json.loads(json.dumps({"g.route": "common", "vn_save_schema": 1}))
    state = ns["migrate"](state)
    assert state["g.route"] == "prologue"


# ── Рантайм-стор vn_state: снапшот и прогон цепочки ──────────────────────────
# Блок `python in vn_state` — обычный Python, а его внешний мир это renpy.store,
# vn_log и vn_compat. Подставляем ровно их и проверяем РЕШЕНИЯ (что попало в
# снапшот, что записалось обратно в сторы), а не наличие строк. Тот же приём, что
# в test_gallery.py; отличие одно: код исполняется в __dict__ настоящего модуля,
# потому что тесту надо подменять глобалы стора (MIGRATIONS, SNAPSHOT_*), которые
# в игре наполняет генерат.

STATE_REL = "game/framework/00_core/020_state.rpy"


# Ren'Py подменяет в КАЖДОМ сторе имена list/dict/set на Revertable-аналоги
# (SDK renpy/minstore.py:41-53), а значения в сторах — соответственно Revertable.
# Без этой подмены тест врёт: `isinstance(x, dict)` внутри блока значит совсем не
# то, что в обычном питоне, и ошибку такого рода поймал бы только живой движок
# (так и случилось однажды с проверкой «миграция вернула dict»).

class _RevList(list):
    pass


class _RevDict(dict):
    pass


class _RevSet(set):
    pass


def _revertable(value):
    if isinstance(value, dict):
        return _RevDict((k, _revertable(v)) for k, v in value.items())
    if isinstance(value, list):
        return _RevList(_revertable(v) for v in value)
    if isinstance(value, set):
        return _RevSet(_revertable(v) for v in value)
    return value


def _state_module(repo_root, stores: dict, monkeypatch, save_schema: int = 1,
                  declared: dict | None = None):
    """Стор vn_state без движка. stores: {имя стора: {переменная: значение}} —
    так их наполняют generated/state/defaults.gen.rpy и snapshot.gen.rpy.

    `declared` разводит две разные вещи, которые раньше совпадали: что ЛЕЖИТ в
    сторе и что ОБЪЯВЛЕНО декларациями (SNAPSHOT_VARS). В игре они не совпадают
    никогда — create_store копирует в каждый стор содержимое renpy.minstore,
    поэтому в сторе всегда есть имена, которых никто не объявлял. По умолчанию
    объявленным считается всё (так проще большинству тестов), но тест про имена
    движка обязан задать это явно, иначе он проверяет не то, что думает.
    Значения кладутся в стор Revertable-обёртками, а имена list/dict/set в блоке
    подменяются, как это делает движок (см. комментарий выше).

    Подставной `store` живёт в sys.modules весь тест (monkeypatch), а не только на
    время exec: apply_snapshot берёт vn_compat ленивым импортом в момент вызова —
    в игре стор vn_compat создаётся позже этого блока (C8)."""
    tail = (repo_root / STATE_REL).read_text(encoding="utf-8") \
        .partition("python in vn_state:")[2]
    assert tail, f"{STATE_REL}: блок `python in vn_state:` не найден"
    body = []
    for line in tail.splitlines():
        if line.strip() and not line.startswith("    "):
            break                     # блок кончился (label after_load и т. п.)
        body.append(line)

    modules = {name: types.SimpleNamespace(**{k: _revertable(v) for k, v in values.items()})
               for name, values in stores.items()}
    renpy_store = types.SimpleNamespace(vn_save_schema=save_schema, **modules)
    log: list[str] = []
    fake_store = types.ModuleType("store")
    fake_store.renpy = types.SimpleNamespace(store=renpy_store)
    fake_store.vn_log = log.append
    # Revertable-конвертация движка: тесту важно, ЧТО записано в стор, а не в какой
    # обёртке движка это лежит.
    # engine_store_names: в игре это имена, которые create_store копирует в
    # каждый стор из renpy.minstore. Тест подставляет их явно — снапшот обязан
    # вычитать их по СПИСКУ, а не угадывать по признакам.
    fake_store.vn_compat = types.SimpleNamespace(
        revertable=lambda v: v,
        engine_store_names=lambda: frozenset({"PY2", "renpy_version"}))

    mod = types.ModuleType("vn_state")
    # Ровно как движок: имена типов в сторе — Revertable-аналоги.
    mod.__dict__.update(list=_RevList, dict=_RevDict, set=_RevSet)
    monkeypatch.setitem(sys.modules, "store", fake_store)
    exec(compile(textwrap.dedent("\n".join(body)), STATE_REL, "exec"), mod.__dict__)
    mod.SNAPSHOT_STORES = tuple(stores)
    decl = stores if declared is None else declared
    mod.SNAPSHOT_VARS = tuple((s, v) for s, values in decl.items() for v in values)
    mod.stores = modules
    mod.log = log
    return mod


def test_snapshot_skips_value_that_breaks_json_roundtrip(repo_root, monkeypatch):
    """set внутри объявленного списка не должен доезжать до json.dumps в
    run_migrations: там он падает уже ВНУТРИ label after_load, то есть загрузка
    старого сейва превращается в крэш-скрин вместо игры. Проверка типа по верхнему
    уровню (list — простой тип) такое пропускала."""
    st = _state_module(repo_root, {"g": {"route": "common", "tags": [{"a", "b"}]}},
                       monkeypatch)
    snap = st.snapshot()
    assert snap["g.route"] == "common"
    assert "g.tags" not in snap
    assert any("g.tags" in line for line in st.log)


def test_migrations_write_back_only_what_changed(repo_root, monkeypatch):
    """json-раундтрип нужен миграциям, но он же теряет форму (ключи dict ->
    строки). Переменная, которой миграция не касалась, обязана остаться как была:
    иначе {1: ...} молча становится {"1": ...} у всех игроков, и следующий d[1]
    промахивается."""
    st = _state_module(repo_root, {"g": {"route": "common", "day_log": {1: "a"}}},
                       monkeypatch)

    def to_prologue(state):
        state["g.route"] = "prologue"
        return state

    st.MIGRATIONS = [(2, to_prologue)]
    assert st.run_migrations(1) == 2
    assert st.stores["g"].route == "prologue"      # миграция применена
    assert st.stores["g"].day_log == {1: "a"}      # чужая переменная не тронута


def test_migration_chain_gap_breaks_the_chain(repo_root, monkeypatch):
    """Миграция N ждёт состояние ПОСЛЕ N−1: исполнять её поверх непройденной
    предыдущей нельзя. Цепочка обрывается на дыре, и сейв не помечается
    актуальным (after_load ставит схему по фактически применённой) — иначе
    повторная загрузка уже ничего не починит."""
    calls = []

    def mig(number):
        def _m(state):
            calls.append(number)
            state["g.route"] = "after%d" % number
            return state
        return _m

    st = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)
    st.MIGRATIONS = [(3, mig(3))]
    assert st.run_migrations(1) == 1               # схема не поднялась
    assert calls == []                             # дыра 1 -> 3: ничего не исполнено
    assert st.stores["g"].route == "common"

    st2 = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)
    st2.MIGRATIONS = [(2, mig(2)), (4, mig(4))]
    assert st2.run_migrations(1) == 2              # 2 применена, на 4 обрыв
    assert calls == [2]
    assert st2.stores["g"].route == "after2"


def test_full_chain_applies_every_step(repo_root, monkeypatch):
    """Регрессия к обрыву на дыре: непрерывная цепочка обязана проходить целиком."""
    seen = []

    def step(number):
        def _m(state):
            seen.append(number)
            return state
        return _m

    st = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)
    st.MIGRATIONS = [(2, step(2)), (3, step(3))]
    assert st.run_migrations(1) == 3
    assert seen == [2, 3]


def test_migration_that_forgot_return_breaks_the_chain(repo_root, monkeypatch):
    """Забытый return — типичная описка автора миграции. Дальше идти нельзя
    (следующая получила бы None), падать трейсбеком у игрока — тем более:
    поведение то же, что на дыре, схема остаётся прежней."""
    st = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)
    st.MIGRATIONS = [(2, lambda state: None), (3, lambda state: state)]
    assert st.run_migrations(1) == 1
    assert st.stores["g"].route == "common"
    assert any("вместо dict" in line for line in st.log)


def test_migration_result_that_is_not_json_is_written_and_logged(repo_root, monkeypatch):
    """Миграция нарушила свой контракт и положила не-json значение. Терять её
    результат молча нельзя, падать на сравнении «до/после» — тоже: значение
    записывается, а факт нарушения уходит в лог."""
    st = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)

    def bad(state):
        state["g.route"] = {"a", "b"}      # set — не сериализуется
        return state

    st.MIGRATIONS = [(2, bad)]
    assert st.run_migrations(1) == 2
    assert st.stores["g"].route == {"a", "b"}
    assert any("не сериализуется" in line for line in st.log)


def test_docs_do_not_claim_that_underscore_vars_skip_the_save(repo_root):
    """Правила «Ren'Py не кладёт в сейв переменные с `_`» НЕ существует.

    rollback.get_roots() перебирает ever_been_changed всех store_dict'ов без
    какой-либо фильтрации по имени; единственный фильтр по «_» в SDK —
    loadsave.py, и он про имена СЛОТОВ. Проверяется это прямо здесь, на
    фактическом сейве проекта: в корнях лежат store._vn_ap_shot и соседи.

    Почему это важнее опечатки в документе: правило было НОРМАТИВНЫМ и повторено
    в семи местах, то есть оно разрешало считать `_`-имена свободной scratch-зоной.
    Обратная сторона («ничего сюжетного и никаких объектов в `_` лежать не
    может») движком не обеспечена, а линтер её не проверяет — значит объект,
    положенный в `_`-переменную, уедет в каждый сейв и сделает сейвы игроков
    нечитаемыми при первом же переименовании класса."""
    import io
    import pickletools
    import zipfile

    fixture = repo_root / "ci" / "fixtures" / "saves" / "schema2-demo.save"
    if not fixture.is_file():
        pytest.skip("фикстуры сейв-корпуса нет")
    with zipfile.ZipFile(fixture) as z:
        ops = list(pickletools.genops(io.BytesIO(z.read("log"))))
    roots = {a for _op, a, _pos in ops if isinstance(a, str) and a.startswith("store._")}
    assert roots, ("в сейве нет ни одной `_`-переменной — либо фикстура сменилась, "
                   "либо движок начал их фильтровать; проверьте утверждение заново")

    # Ищем именно утверждение про «_»-префикс: «define не попадает в сейв» —
    # правда и к делу не относится.
    import re as _re

    claim = _re.compile(
        r'(?:`_`|"_"|underscore)[^\n]{0,120}'
        r"(?:не кладёт в сейв|не попадают в сейв|не сохраняются в сейв|"
        r"не пишется в сейв|не попадает в сейв)")
    docs = [repo_root / "docs" / "ARCHITECTURE.md",
            *sorted((repo_root / "docs" / "handbook").glob("*.md")),
            *sorted((repo_root / "docs" / "conventions").glob("*.md"))]
    guilty = [d.relative_to(repo_root).as_posix() for d in docs
              if claim.search(d.read_text(encoding="utf-8"))]
    assert not guilty, (
        f"документы снова обещают несуществующее поведение движка: {guilty}. "
        f"Факт: в сейве лежат {sorted(roots)[:3]}")


def test_start_label_does_not_bake_the_registry_into_every_save(repo_root):
    """label start не имеет права заводить store-переменную под копию реестра.

    Любое рантайм-присваивание в дефолтный стор делает переменную корнем сейва
    НАВСЕГДА (python.py: get_changes -> ever_been_changed), а `$ _chapters =
    vn_registry.chapters()` клал туда список словарей всех глав. Проверено на
    фактическом сейве до правки: корень `store._chapters` со всем содержимым
    VN_CHAPTERS; после правки в свежем сейве остаётся только `store._entry` —
    строка. Разница не косметическая: реестр растёт с каждой главой и с каждым
    паком, и растёт он в КАЖДОМ файле сохранения игрока.

    Старые сейвы `_chapters` продолжат нести: переменная восстановится из файла
    и останется в ever_been_changed. Вычистить её можно только миграцией, и она
    того не стоит — значение безвредно, просто лишнее."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "030_flow.rpy").read_text(encoding="utf-8")
    start = src.split("\nlabel start:", 1)[1].split("\nlabel ", 1)[0]

    assert "vn_registry.chapters()" not in start, \
        "точка входа снова кладёт реестр в переменную стора"
    assert "vn.first_entry_label()" in start
    # Обе ветки обязаны сохраниться: пустой проект должен запускаться и честно
    # говорить, что контента нет.
    assert "ui.flow.no_content" in start and "renpy.jump(" in start

    facade = src.split("def first_entry_label(", 1)[1].split("\n    def ", 1)[0]
    assert 'rows[0]["entry_label"] if rows else None' in facade, \
        "фасад возвращает не строку — в сейв снова уедет структура"


def test_snapshot_excludes_engine_names(repo_root, monkeypatch):
    """Имена движка не должны доезжать до состояния миграций.

    renpy/python.py: create_store() копирует в каждый named store всё содержимое
    renpy.minstore. Фильтр «не `_`, не callable, не модуль» отсеивал оттуда почти
    всё — но не `PY2 = False`: обычный bool без подчёркивания, json-safe. В
    state.json боевого прогона лежали `ch01.PY2` и `g.PY2`, то есть автор
    миграции видел в плоском состоянии переменные, которых никто не объявлял и
    которые могут появиться или исчезнуть с версией движка.

    Вычитание идёт по СПИСКУ имён (vn_compat.engine_store_names), а не по новым
    признакам: признаковый фильтр уже один раз промахнулся."""
    st = _state_module(repo_root,
                       {"g": {"route": "common", "PY2": False, "renpy_version": "8.5"}},
                       monkeypatch,
                       # Объявлена только route: PY2/renpy_version в сторе есть, но
                       # их туда положил движок, а не декларация. Раньше харнесс
                       # объявлял ВСЁ, что лежит в сторе, и тест проверял не то.
                       declared={"g": ["route"]})
    snap = st.snapshot()
    assert snap["g.route"] == "common"
    assert "g.PY2" not in snap and "g.renpy_version" not in snap, snap
    # Пропуск обязан быть виден в логе: две другие ветки отбраковки логируют имя,
    # а эта молчала — и «снапшот показывает ВСЁ» расходилось с фактом без следа.
    assert any("PY2" in line for line in st.log), st.log


def test_non_string_dict_keys_are_refused_by_the_compiler():
    """dict с не-строковыми ключами в default — ошибка сборки.

    Состояние проходит json-раундтрип в цепочке миграций, а json приводит ключи
    к строкам: {1: x} возвращается в стор как {"1": x}, и следующий d[1]
    промахивается У ВСЕХ ИГРОКОВ, молча. Защита «не трогали — не пишем»
    закрывает только половину механизма: переменную, которую миграция ТРОНУЛА,
    мы записываем уже нормализованной. Дешевле сделать её невозможной на входе."""
    from vn.content.compile import _py_literal

    assert _py_literal({"a": 1}) == repr({"a": 1})
    with pytest.raises(CompileError, match="не-строковыми ключами"):
        _py_literal({1: "x"})
    with pytest.raises(CompileError, match="не-строковыми ключами"):
        _py_literal({"ok": 1, (2, 3): "x"})


def test_migration_warns_when_it_normalises_dict_keys(repo_root, monkeypatch):
    """Вторая половина той же защиты — в рантайме.

    Переменную мог наполнить не только default, но и код сцены. Если миграция
    ТРОНУЛА такой dict, в стор уедет результат раундтрипа — уже со строковыми
    ключами. Молча этого происходить не должно: в логе обязан остаться след с
    именем переменной."""
    st = _state_module(repo_root, {"g": {"tally": {1: "a", 2: "b"}}}, monkeypatch)
    st.MIGRATIONS = [(2, lambda state: dict(state, **{"g.tally": {"1": "a", "2": "b",
                                                                  "3": "c"}}))]
    applied = st.run_migrations(1)
    assert applied == 2
    assert any("ключи dict нормализованы" in m and "g.tally" in m for m in st.log), st.log


def test_snapshot_keeps_a_declared_name_that_collides_with_an_engine_name(
        repo_root, monkeypatch):
    """Объявленная переменная обязана быть в снапшоте, даже если имя есть в minstore.

    Фикс FWA-024 вычитал из снапшота ВСЕ имена renpy.minstore. Их там 70, и 39
    подходят под шаблон имени контентной переменной (C21): round, position, input,
    open, set, range, sorted… Объявленная `g.round` (счётчик раунда мини-игры —
    C21 прямо предусматривает сторы mech_* для механик) МОЛЧА выпадала из
    снапшота, и migrate(state) её не видел: миграция, переносящая переменную в
    новый формат, ничего не делала, сейв игрока оставался в старом формате, а
    новый код читал его с новой семантикой.

    Проверено прогоном движка: g.round и g.position отсутствовали в state.json при
    исправной контрольной переменной рядом. Поэтому вычитается РАЗНИЦА: объявленное
    имя — наше по определению."""
    st = _state_module(
        repo_root,
        {"g": {"round": 3, "position": "left", "plain": 1, "PY2": False}},
        monkeypatch,
        # round/position объявлены декларацией, PY2 — нет: его положил движок.
        declared={"g": ["round", "position", "plain"]})
    snap = st.snapshot()
    assert snap["g.round"] == 3, snap
    assert snap["g.position"] == "left", snap
    assert snap["g.plain"] == 1, snap
    assert "g.PY2" not in snap, snap


def test_migration_that_raises_breaks_the_chain_instead_of_crashing(
        repo_root, monkeypatch):
    """Исключение из тела миграции — третий способ сломать цепочку.

    Забытый return и дыра в нумерации давали мягкий обрыв, а исключение (KeyError
    по переменной, которой в старом сейве нет; TypeError на None; опечатка) не
    перехватывалось вовсе: оно вылетало из run_migrations, из блока python: в
    label after_load и попадало в движковый обработчик — крэш-скрин вместо игры.
    Хуже побочный эффект: apply_snapshot стоит ПОСЛЕ цикла, поэтому результат
    успешно прошедших миграций терялся ЦЕЛИКОМ, а vn_save_schema оставался старым,
    и каждая следующая загрузка того же слота падала снова.

    Инвариант: обрыв как на дыре — applied на последней успешной, её результат
    записан, факт в логе."""
    st = _state_module(repo_root, {"g": {"route": "common"}}, monkeypatch)

    def boom(state):
        return state["g.legacy_route"]          # KeyError: в старом сейве нет

    st.MIGRATIONS = [(2, lambda state: dict(state, **{"g.route": "prologue"})),
                     (3, boom),
                     (4, lambda state: dict(state, **{"g.route": "never"}))]
    applied = st.run_migrations(1)

    assert applied == 2, "цепочка обязана остаться на последней УСПЕШНОЙ миграции"
    assert st.stores["g"].route == "prologue", \
        "результат успешной миграции 2 потерян — apply_snapshot не отработал"
    assert any("упала" in m and "KeyError" in m for m in st.log), st.log


def test_migration_warns_about_nested_non_string_keys(repo_root, monkeypatch):
    """Обход гарда FWA-025: не-строковый ключ ВЛОЖЕННОГО dict.

    Обе половины защиты смотрели ровно на один уровень: компилятор проверял свои
    ключи и не спускался в значения, а детектор в run_migrations делал
    `any(not isinstance(kk, str) for kk in old_value)`. Механизм же (json-раундтрип)
    работает на ЛЮБОЙ глубине: `{counters: {1: 0}}` возвращается в стор как
    `{counters: {"1": 0}}`, и следующее d["counters"][1] промахивается у КАЖДОГО
    игрока, загрузившего старый сейв, — без единой строки в логе.

    В сообщении обязан быть путь до ключа, а не только имя переменной: иначе по
    логу непонятно, что чинить."""
    st = _state_module(repo_root, {"g": {"tally": {"counters": {1: 0, 2: 0}}}},
                       monkeypatch)
    st.MIGRATIONS = [(2, lambda state: dict(
        state, **{"g.tally": {"counters": {"1": 0, "2": 0, "3": 0}}}))]
    assert st.run_migrations(1) == 2
    hit = [m for m in st.log if "ключи dict нормализованы" in m]
    assert hit, st.log
    assert "g.tally" in hit[0] and "counters" in hit[0], \
        f"в логе нет пути до вложенного ключа: {hit[0]}"


# Рантайм-присваивания имён стора, которые РАЗРЕШЕНЫ. Каждое здесь потому, что
# зовётся только с init, а не из рантайма: присваивание в init корнем сейва не
# становится (тот же аргумент, что у vn_platform._beta). Список заморожен —
# новый `global` в сторе обязан приехать вместе с обоснованием.
_ALLOWED_STORE_GLOBALS = {
    # set_provider / set_progress_provider зовёт только 035_platform.rpy на init 999.
    "game/framework/00_core/080_achievements.rpy: _provider",
    "game/framework/00_core/080_achievements.rpy: _progress_provider",
}


def test_no_store_name_is_reassigned_at_runtime(repo_root):
    """Мемоизация не имеет права жить именем стора — она уедет в КАЖДЫЙ сейв.

    Рантайм-присваивание имени в named store движок считает изменением и делает
    имя КОРНЕМ СЕЙВА навсегда (renpy/python.py: get_changes -> ever_been_changed;
    фильтра ни по «_», ни по «это named store» там нет), а на загрузке корень
    пишется обратно в стор безусловно (renpy/rollback.py: unfreeze_core).

    Так в сейвы уехали три кэша. store.vn_story._conflict_index — без
    инвалидатора вовсе: после патча контента загруженный сейв всю сессию
    подсовывал СТАРУЮ матрицу конфликтов, и карта главы рисовала конфликт,
    которого в новой сборке нет. store.vn_gal._seen_index_cache/_seen_index_len —
    индекс увиденных кадров, чья единственная проверка валидности это равенство
    длин, то есть чужой сейв мог подсунуть чужой индекс; плюс каждая перестройка
    кладёт полную копию в rollback-лог, а он весь пишется в файл.

    Проверено дампом get_roots() и сканом реальных автосейвов репозитория.

    Правильный приём — атрибуты объекта, созданного на init: имя объекта в
    рантайме не переприсваивается, поэтому в корни не попадает (образец —
    vn.pack_registry._owned_cache). Существующий гейт этого класса
    (test_start_label_does_not_bake_the_registry_into_every_save) смотрел только
    тело label start и `global` внутри `python in <store>` не видел."""
    import re

    found = set()
    for path in sorted((repo_root / "game" / "framework").rglob("*.rpy")):
        rel = path.relative_to(repo_root).as_posix()
        for m in re.finditer(r"^\s*global\s+([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)",
                             path.read_text(encoding="utf-8"), re.M):
            for name in m.group(1).split(","):
                found.add(f"{rel}: {name.strip()}")

    extra = found - _ALLOWED_STORE_GLOBALS
    assert not extra, (
        "рантайм-присваивание имени стора делает его корнем сейва навсегда:\n  "
        + "\n  ".join(sorted(extra))
        + "\nДержите мемоизацию атрибутами объекта, созданного на init (образец — "
          "vn.pack_registry._owned_cache), либо добавьте место в "
          "_ALLOWED_STORE_GLOBALS с обоснованием «зовётся только с init».")
    # Гейт не должен выродиться: список разрешённых обязан оставаться актуальным.
    stale = _ALLOWED_STORE_GLOBALS - found
    assert not stale, f"в _ALLOWED_STORE_GLOBALS остались мёртвые записи: {stale}"


def test_nested_non_string_dict_keys_are_refused_by_the_compiler():
    """Обход гарда FWA-025 в КОМПИЛЯТОРЕ: вложенный не-строковый ключ.

    Проверка смотрела ровно один уровень (свои ключи, без спуска в значения), а
    механизм рекурсивен: json приводит ключи к строкам на ЛЮБОЙ глубине. Поэтому
    `default: {counters: {1: 0}}` компилятор пропускал, а после любой миграции,
    ТРОНУВШЕЙ переменную, в стор возвращалось `{counters: {"1": 0}}` — и следующее
    d["counters"][1] промахивалось у КАЖДОГО игрока, загрузившего старый сейв.

    Схема vars@1 тут не помогает: у default нет ни propertyNames, ни ограничения
    глубины. В сообщении обязан быть ПУТЬ до ключа — иначе в большом словаре
    непонятно, что чинить."""
    from vn.content.compile import _py_literal

    for bad in ({"a": {1: "x"}}, [{2: "y"}], {"a": {"b": {None: 1}}},
                {"a": [{"b": {3.5: 1}}]}):
        with pytest.raises(CompileError, match="не-строковыми ключами"):
            _py_literal(bad)

    # В тексте — путь, а не только факт.
    try:
        _py_literal({"a": {"b": {7: 1}}})
    except CompileError as e:
        assert "'a'" in str(e) and "'b'" in str(e) and "7" in str(e), str(e)

    # Легальное вложенное значение проходит без изменений.
    assert _py_literal({"a": {"b": [1, 2]}}) == repr({"a": {"b": [1, 2]}})
