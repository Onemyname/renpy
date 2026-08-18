"""Аварийный путь G4: генерат из артефакта CI (`vn build --use-artifact`).

Сеть здесь не нужна и не используется: `gh` подменяется скриптом в PATH, который
отдаёт заранее заготовленный JSON и «распаковывает» подготовленный каталог. Приём —
тот же, что у фейкового `javac` в test_android.py: проверяется НАША логика (поиск
зелёного прогона, верификация, пометка генерата чужим), а не поведение gh.
"""

from __future__ import annotations

import json
import sys

import pytest

from helpers import mk_root
from vn import artifact
from vn.artifact import ArtifactError, find_run, install, resolve_sha, verify
from vn.content import compile as cc

no_windows = pytest.mark.skipif(sys.platform == "win32", reason="фейковый gh — sh-скрипт")

SHA = "a" * 40


def _with_fake_gh(monkeypatch, bin_dir):
    """Подставной gh ПЕРЕД системным PATH, а не вместо него: скрипту нужны cat и sh."""
    import os

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _root_with_schemas(tmp_path):
    """Корень проекта со РЕАЛЬНЫМИ схемами: верификация артефакта проверяет манифест
    реестром, поэтому синтетический корень без tools/schemas ей не годится."""
    import shutil

    from conftest import REPO_ROOT

    root = mk_root(tmp_path)
    (root / "tools").mkdir(exist_ok=True)
    if not (root / "tools" / "schemas").exists():
        shutil.copytree(REPO_ROOT / "tools" / "schemas", root / "tools" / "schemas")
    return root


def _fake_gh(tmp_path, *, runs=None, download_from=None, fail=None):
    """gh-заглушка в своём каталоге; возвращает путь, который надо добавить в PATH.

    `runs` — что отдаёт `gh run list --json …`; `download_from` — каталог, содержимое
    которого «скачивается» в `--dir`; `fail` — код выхода, если gh обязан упасть.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    runs_json = json.dumps(runs if runs is not None else [])
    script = ["#!/bin/sh", "set -e"]
    if fail is not None:
        script += [f'echo "gh: подставная ошибка" 1>&2', f"exit {fail}"]
    else:
        script += [
            'if [ "$2" = "list" ]; then',
            f"  cat <<'JSON'\n{runs_json}\nJSON",
            "  exit 0",
            "fi",
            'if [ "$2" = "download" ]; then',
            '  dir=""; prev=""',
            '  for a in "$@"; do [ "$prev" = "--dir" ] && dir="$a"; prev="$a"; done',
            '  mkdir -p "$dir"',
            f'  [ -n "{download_from or ""}" ] && cp -R "{download_from or ""}/." "$dir/"',
            "  exit 0",
            "fi",
            "exit 9",
        ]
    exe = bin_dir / "gh"
    exe.write_text("\n".join(script) + "\n", encoding="utf-8")
    exe.chmod(0o755)
    return bin_dir


def _fake_generated(tmp_path, *, extra_rpyc=True, corrupt=False, schema=None,
                    outputs_override=None):
    """Каталог «как артефакт CI»: выходы + манифест с их настоящими хешами."""
    src = tmp_path / "artifact-src"
    (src / "registry").mkdir(parents=True, exist_ok=True)
    files = {
        "version.gen.rpy": 'define config.version = "0.9.9+deadbee"\n',
        "registry/scenes.gen.rpy": "# сцены\n",
    }
    outputs = {}
    for rel, text in files.items():
        path = src / rel
        path.write_text(text, encoding="utf-8")
        outputs[rel] = cc._b3(text.encode("utf-8"))
    if corrupt:
        (src / "version.gen.rpy").write_text("подменено\n", encoding="utf-8")
    if extra_rpyc:
        # .rpyc в артефакте есть законно (upload идёт после renpy lint и pytest),
        # и в outputs их нет — «лишних файлов не должно быть» проверять нельзя.
        (src / "version.gen.rpyc").write_bytes(b"\x00rpyc")
    manifest = {
        "schema": schema or cc.MANIFEST_SCHEMA,
        "tool": "0.1.0",
        "inputs": {"project.yaml": "0123456789abcdef"},
        "outputs": outputs_override if outputs_override is not None else outputs,
    }
    if manifest["schema"] == cc.MANIFEST_SCHEMA:
        manifest["source"] = {"kind": "local"}
    (src / cc.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return src


# ── Поиск прогона: красный не берём, истёкший объясняем ───────────────────────

@no_windows
def test_find_run_picks_newest_green(tmp_path, monkeypatch):
    """На коммите бывает несколько прогонов (повторы, dispatch) — нужен новейший
    ЗЕЛЁНЫЙ: артефакт красной сборки не прошёл ни lint, ни тесты."""
    root = mk_root(tmp_path)
    _with_fake_gh(monkeypatch, _fake_gh(tmp_path, runs=[
        {"databaseId": 11, "conclusion": "success", "status": "completed",
         "createdAt": "2026-08-01T10:00:00Z"},
        {"databaseId": 22, "conclusion": "failure", "status": "completed",
         "createdAt": "2026-08-03T10:00:00Z"},
        {"databaseId": 33, "conclusion": "success", "status": "completed",
         "createdAt": "2026-08-02T10:00:00Z"},
    ]))
    run_id, created = find_run(root, SHA)
    assert run_id == 33 and created == "2026-08-02T10:00:00Z"


@no_windows
def test_find_run_without_green_names_the_states(tmp_path, monkeypatch):
    root = mk_root(tmp_path)
    _with_fake_gh(monkeypatch, _fake_gh(tmp_path, runs=[
        {"databaseId": 5, "conclusion": "failure", "status": "completed",
         "createdAt": "2026-08-01T10:00:00Z"}]))
    with pytest.raises(ArtifactError, match="нет зелёных прогонов"):
        find_run(root, SHA)


@no_windows
def test_find_run_without_runs_at_all(tmp_path, monkeypatch):
    root = mk_root(tmp_path)
    _with_fake_gh(monkeypatch, _fake_gh(tmp_path, runs=[]))
    with pytest.raises(ArtifactError, match="нет прогонов"):
        find_run(root, SHA)


@no_windows
def test_gh_failure_is_reported_with_its_output(tmp_path, monkeypatch):
    root = mk_root(tmp_path)
    _with_fake_gh(monkeypatch, _fake_gh(tmp_path, fail=4))
    with pytest.raises(ArtifactError, match="вернул 4"):
        find_run(root, SHA)


def test_missing_gh_explains_the_manual_path(tmp_path, monkeypatch):
    """Без gh команда обязана назвать ручной путь: он остаётся рабочим и в аварии
    важнее, чем сообщение «поставьте инструмент»."""
    root = mk_root(tmp_path)
    monkeypatch.setattr(artifact, "gh_path", lambda: None)
    with pytest.raises(ArtifactError, match="Ручной путь"):
        find_run(root, SHA)


def test_resolve_sha_passes_full_sha_through(tmp_path):
    assert resolve_sha(mk_root(tmp_path), SHA) == SHA


def test_resolve_sha_rejects_unknown_ref(tmp_path):
    """Несуществующая ссылка обязана отбиваться до всякого обращения к сети."""
    with pytest.raises(ArtifactError, match="не коммит"):
        resolve_sha(mk_root(tmp_path), "нет-такой-ветки")


# ── Верификация: наш ли это генерат ──────────────────────────────────────────

def test_verify_accepts_our_generated_tree(tmp_path):
    root = _root_with_schemas(tmp_path)
    manifest = verify(root, _fake_generated(tmp_path))
    assert manifest["outputs"] and manifest["tool"] == "0.1.0"


def test_verify_rejects_tree_without_manifest(tmp_path):
    root = _root_with_schemas(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ArtifactError, match="не генерат"):
        verify(root, empty)


def test_verify_rejects_corrupted_bytes(tmp_path):
    """Подменённый файл ловится пересчётом хешей теми же функциями, которыми их
    считал компилятор."""
    root = _root_with_schemas(tmp_path)
    with pytest.raises(ArtifactError, match="хеш не совпал"):
        verify(root, _fake_generated(tmp_path, corrupt=True))


def test_verify_rejects_paths_outside_generated(tmp_path):
    """`outputs` из чужого архива используется как список путей ЗАПИСИ в game/ —
    zip-slip обязан отбиваться до копирования."""
    root = _root_with_schemas(tmp_path)
    src = _fake_generated(tmp_path, outputs_override={"../../etc/passwd": "ab" * 8})
    with pytest.raises(ArtifactError, match="вне генерата"):
        verify(root, src)


def test_verify_accepts_historical_manifest_schema(tmp_path):
    """Артефакт 30-дневной давности несёт gen_manifest@1. Гейт устаревших схем
    существует для авторских документов репозитория, а не для истории."""
    root = _root_with_schemas(tmp_path)
    manifest = verify(root, _fake_generated(tmp_path, schema="gen_manifest@1"))
    assert manifest["schema"] == "gen_manifest@1"


def test_verify_rejects_unknown_manifest_schema(tmp_path):
    """Артефакт, собранный БОЛЕЕ НОВЫМ тулингом, брать нельзя: его манифест мы
    прочитать не умеем, а значит и проверить не можем."""
    root = _root_with_schemas(tmp_path)
    with pytest.raises(ArtifactError, match="не проходит схему"):
        verify(root, _fake_generated(tmp_path, schema="gen_manifest@99"))


# ── Установка: замена, а не наложение; генерат помечен чужим ──────────────────

def test_install_replaces_generated_and_marks_it_foreign(tmp_path):
    root = _root_with_schemas(tmp_path)
    gen = root / "game" / "generated"
    gen.mkdir(parents=True)
    (gen / "мой-локальный.gen.rpy").write_text("# локальный\n", encoding="utf-8")

    info = install(root, _fake_generated(tmp_path), SHA, 42, "2026-08-02T10:00:00Z")

    assert not (gen / "мой-локальный.gen.rpy").exists(), \
        "смешанный генерат — худшее состояние: манифест врал бы про свои же байты"
    manifest = cc.load_manifest(gen)
    assert manifest["schema"] == cc.MANIFEST_SCHEMA
    assert cc.manifest_source(manifest) == {
        "kind": "artifact", "sha": SHA, "run_id": 42, "workflow": "ci.yml",
        "downloaded_at": "2026-08-02T10:00:00Z", "installed_by": manifest["source"]["installed_by"],
    }
    assert manifest["tool"] == "0.1.0", "поле tool остаётся ЧУЖИМ — его писал CI"
    assert (info.outputs, info.rpyc) == (2, 1)


def test_installed_manifest_passes_the_schema(tmp_path):
    """Пометка «чужой» — данные, значит она обязана проходить свою схему (G16)."""
    from vn.schemas import SchemaRegistry

    root = _root_with_schemas(tmp_path)
    install(root, _fake_generated(tmp_path), SHA, 7, "2026-08-02T10:00:00Z")
    manifest = cc.load_manifest(root / "game" / "generated")
    from conftest import REPO_ROOT

    errors = SchemaRegistry(REPO_ROOT / "tools" / "schemas").validate(
        manifest, "game/generated/manifest.json")
    assert errors == []


def test_artifact_constants_match_the_workflow():
    """Имя артефакта, workflow и срок хранения заданы в ci.yml. Разъедутся —
    команда будет искать артефакт, которого нет, и объяснять это «истёк»."""
    from conftest import REPO_ROOT

    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "name: generated-${{ github.sha }}" in ci
    assert artifact.ARTIFACT_NAME == "generated-{sha}"
    assert artifact.WORKFLOW == "ci.yml" and (REPO_ROOT / ".github" / "workflows"
                                              / artifact.WORKFLOW).is_file()
    assert f"retention-days: {artifact.RETENTION_DAYS}" in ci

# ── Рассинхрон коммита и снятие пометки ──────────────────────────────────────

def test_head_mismatch_warns_about_api_level(tmp_path):
    """Артефакт чужого коммита — законный случай (в аварии берут последний зелёный),
    но генерат и рукописный framework связаны контрактом API_LEVEL: об этом надо
    сказать до того, как человек решит, что сломался и артефакт."""
    from conftest import REPO_ROOT

    warn = artifact.head_mismatch(REPO_ROOT, SHA)
    assert warn and "API_LEVEL" in warn


def test_head_match_is_silent():
    """На своём коммите предупреждения быть не должно — иначе оно превратится в шум."""
    import subprocess

    from conftest import REPO_ROOT

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    assert artifact.head_mismatch(REPO_ROOT, head) is None


def test_local_build_clears_the_foreign_mark(tmp_path):
    """Снять пометку «чужой» может только успешная локальная компиляция — тем же
    действием, которое делает генерат своим. Отдельной команды для этого нет."""
    root = _root_with_schemas(tmp_path)
    install(root, _fake_generated(tmp_path), SHA, 7, "2026-08-02T10:00:00Z")
    gen = root / "game" / "generated"
    assert cc.manifest_source(cc.load_manifest(gen))["kind"] == "artifact"

    # Компилятор пишет манифест сам; здесь проверяется контракт записи, а не сборка.
    manifest = cc.load_manifest(gen)
    manifest["source"] = {"kind": "local"}
    (gen / cc.MANIFEST_NAME).write_text(__import__("json").dumps(manifest), encoding="utf-8")
    assert cc.manifest_source(cc.load_manifest(gen)) == {"kind": "local"}


def test_unknown_source_is_not_local(tmp_path):
    """Манифест gen_manifest@1 не имеет права выглядеть локальным: такой приезжает
    только из артефакта, собранного до появления поля."""
    assert cc.manifest_source({"schema": "gen_manifest@1"}) == {"kind": "unknown"}
    assert cc.manifest_source(None) == {"kind": "unknown"}
