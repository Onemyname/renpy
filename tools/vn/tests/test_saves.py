"""Сейв-инфраструктура (G5): валидация цепочки миграций, эмиттеры snapshot/migrations."""

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
