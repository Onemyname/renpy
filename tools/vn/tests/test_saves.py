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


def _state_module(repo_root, stores: dict, monkeypatch, save_schema: int = 1):
    """Стор vn_state без движка. stores: {имя стора: {переменная: значение}} —
    так их наполняют generated/state/defaults.gen.rpy и snapshot.gen.rpy.
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
    fake_store.vn_compat = types.SimpleNamespace(revertable=lambda v: v)

    mod = types.ModuleType("vn_state")
    # Ровно как движок: имена типов в сторе — Revertable-аналоги.
    mod.__dict__.update(list=_RevList, dict=_RevDict, set=_RevSet)
    monkeypatch.setitem(sys.modules, "store", fake_store)
    exec(compile(textwrap.dedent("\n".join(body)), STATE_REL, "exec"), mod.__dict__)
    mod.SNAPSHOT_STORES = tuple(stores)
    mod.SNAPSHOT_VARS = tuple((s, v) for s, values in stores.items() for v in values)
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
