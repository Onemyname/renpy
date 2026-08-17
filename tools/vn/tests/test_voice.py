"""Голосовая подсистема (§4.9/C5): манифесты, валидация, импорт, инжекция
voice-операторов и транскод мастеров."""

from __future__ import annotations

import json
import shutil
import wave

import pytest

from helpers import mk_root, write_project
from vn.voice import (
    ImportReport,
    VoiceError,
    import_takes,
    load_manifests,
    manifest_rows,
    validate,
    write_manifest_csv,
)


def _mk_voice_root(tmp_path, repo_root):
    """Корень с главой, ledger'ом на три реплики и реестром схем."""
    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    (root / "content" / "chapters" / "ch01_test").mkdir(parents=True)
    ledger = {
        "schema": "ledger@1",
        "chapter": "ch01",
        "menus": {},
        "says": {
            "ch01_s010_0001": {"text": "Первая", "who": None},
            "ch01_s010_0002": {"text": "Вторая", "who": "mira"},
            "ch01_s020_0001": {"text": "Третья", "who": "mira"},
        },
    }
    (root / "loc" / "ledger").mkdir(parents=True)
    (root / "loc" / "ledger" / "ch01.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return root


def _manifest(root, lines: dict, lang="ru", chapter_dir="ch01_test", chapter="ch01"):
    vdir = root / "content" / "chapters" / chapter_dir / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"  {lid}: {{status: {status}}}" for lid, status in lines.items())
    (vdir / f"{lang}.voice.yaml").write_text(
        f"schema: voice@1\nchapter: {chapter}\nlang: {lang}\n"
        + (f"lines:\n{rows}\n" if lines else "lines: {}\n"),
        encoding="utf-8")


def _master(root, lang, line_id, ext=".ogg"):
    p = root / "assets_src" / "voice" / lang / line_id[:4] / (line_id + ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"fake-audio")
    return p


def test_validate_ok_and_coverage(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final", "ch01_s010_0002": "draft"})
    _master(root, "ru", "ch01_s010_0001")
    _master(root, "ru", "ch01_s010_0002")
    rep = validate(root)
    assert rep.ok, rep.errors
    assert rep.coverage[("ch01", "ru")] == (2, 3)
    assert rep.drafts == ["ru: ch01_s010_0002"]
    assert rep.holes == ["ru: ch01_s020_0001"]


def test_validate_unknown_line_id_is_error(tmp_path, repo_root):
    """Опечатка в line_id = файл дубля осиротеет молча — обязана быть ошибкой."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_9999": "final"})
    rep = validate(root)
    assert any("ch01_s010_9999" in e and "нет в ledger" in e for e in rep.errors)


def test_validate_missing_master_is_error(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final"})
    rep = validate(root)
    assert any("мастера нет" in e for e in rep.errors)


def test_validate_orphan_master_is_error(tmp_path, repo_root):
    """Мастер без строки манифеста доехал бы до дистрибутива мёртвым грузом."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {})
    _master(root, "ru", "ch01_s010_0001")
    rep = validate(root)
    assert any("без строки" in e for e in rep.errors)


def test_validate_foreign_chapter_line_is_error(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch02_s010_0001": "final"})
    errors: list[str] = []
    load_manifests(root, errors)
    assert any("чужой главы" in e for e in errors)


def test_manifest_rows_and_csv(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final"})
    rows = manifest_rows(root, "ch01", "ru")
    assert [r["line_id"] for r in rows] == [
        "ch01_s010_0001", "ch01_s010_0002", "ch01_s020_0001"]
    assert rows[0]["status"] == "final" and rows[1]["status"] == ""
    assert rows[1]["prev"] == "Первая" and rows[0]["next"] == "Вторая"
    only_mira = manifest_rows(root, "ch01", "ru", char="mira")
    assert [r["line_id"] for r in only_mira] == ["ch01_s010_0002", "ch01_s020_0001"]
    out = tmp_path / "sheet.csv"
    write_manifest_csv(rows, out)
    assert "ch01_s010_0001" in out.read_text(encoding="utf-8")


def test_manifest_rows_without_ledger_fails(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    with pytest.raises(VoiceError):
        manifest_rows(root, "ch02", "ru")


def test_import_takes_places_masters_and_updates_manifest(tmp_path, repo_root):
    root = _mk_voice_root(tmp_path, repo_root)
    takes = tmp_path / "takes"
    takes.mkdir()
    (takes / "ch01_s010_0001.wav").write_bytes(b"riff")
    (takes / "ch01_s010_0002.ogg").write_bytes(b"oggs")
    rep = import_takes(root, takes, "ru")
    assert not rep.errors
    assert (root / "assets_src" / "voice" / "ru" / "ch01" / "ch01_s010_0001.wav").is_file()
    mf = (root / "content" / "chapters" / "ch01_test" / "voice" / "ru.voice.yaml") \
        .read_text(encoding="utf-8")
    assert "ch01_s010_0001: {status: final}" in mf
    assert "ch01_s010_0002: {status: final}" in mf
    # Манифест обязан остаться валидным по схеме и пройти validate целиком
    vrep = validate(root)
    assert not [e for e in vrep.errors if "манифест" in e], vrep.errors


def test_import_is_atomic_on_bad_take(tmp_path, repo_root):
    """Один битый файл в пачке — не импортируется ничего (половинчатый импорт
    хуже отказа: студия исправляет пачку и повторяет)."""
    root = _mk_voice_root(tmp_path, repo_root)
    takes = tmp_path / "takes"
    takes.mkdir()
    (takes / "ch01_s010_0001.wav").write_bytes(b"riff")
    (takes / "ch01_s010_typo.wav").write_bytes(b"riff")
    rep: ImportReport = import_takes(root, takes, "ru")
    assert rep.errors
    assert not (root / "assets_src" / "voice").exists()


def test_release_gate_maps_holes_to_fail(tmp_path, repo_root):
    """Дыры в озвученной главе = FAIL релизного гейта (§4.9), драфты = WARN."""
    from vn.release import validate_release

    root = _mk_voice_root(tmp_path, repo_root)
    proj = root / "project.yaml"
    proj.write_text(proj.read_text(encoding="utf-8") +
                    "\nflavors:\n  test:\n    packs: []\n    nsfw: false\n",
                    encoding="utf-8")
    _manifest(root, {"ch01_s010_0001": "final"})
    _master(root, "ru", "ch01_s010_0001")
    checks, _ok = validate_release(root, flavor="test")
    voice_lines = [(lvl, msg) for lvl, msg in checks if msg.startswith("озвучка")]
    assert voice_lines and voice_lines[0][0] == "FAIL"
    assert "непокрытых" in voice_lines[0][1]


def _wav(path, seconds=0.2, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x40" * int(rate * seconds))
    return path


def test_pipeline_transcodes_voice_master_to_opus(tmp_path, repo_root):
    """Мастер дубля -> game/assets/voice/<lang>/<chNN>/<line_id>.opus."""
    from vn.pipeline import find_ffmpeg
    if find_ffmpeg() is None:
        pytest.skip("нужен ffmpeg (vn pipeline doctor)")
    from vn.assets.pipeline import build_assets

    root = mk_root(tmp_path)
    _wav(root / "assets_src" / "voice" / "ru" / "ch01" / "ch01_s010_0001.wav")
    rep = build_assets(root)
    assert not rep.errors, rep.errors
    out = root / "game" / "assets" / "voice" / "ru" / "ch01" / "ch01_s010_0001.opus"
    assert out.is_file() and out.stat().st_size > 0


def test_pipeline_rejects_bad_voice_layout(tmp_path):
    from vn.assets.pipeline import build_assets

    root = mk_root(tmp_path)
    p = root / "assets_src" / "voice" / "ru" / "ch01_s010_0001.ogg"   # нет <chNN>/
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    rep = build_assets(root)
    assert any("вне конвенции" in e for e in rep.errors)


def test_emit_scene_injects_voice_statements():
    """voice vn.voice_path(...) вставляется перед озвученной репликой с её отступом."""
    from vn.content import scenes as sc

    rpy = "\n".join([
        "label ch01_s010__body:",
        '    "Первая" id ch01_s010_0001',
        "    menu:",
        '        "Пункт":',
        '            "Вторая" id ch01_s010_0002',
        '    "Без озвучки" id ch01_s010_0003',
        '    return "gate"',
    ])
    unit = sc.SceneUnit(
        full_id="ch01_s010", chapter_id="ch01", short_id="s010",
        yaml_rel="y", rpy_rel="r", meta={"exits": {"gate": "s020"}},
        rpy_text=rpy,
        analysis={
            "labels": [{"name": "ch01_s010__body", "line": 1}],
            "jumps": [], "calls": [],
            "returns": [{"expr": '"gate"', "line": 7}],
            "menus": [],
            "say_list": [
                {"line": 2, "who": None, "what": "Первая", "id": "ch01_s010_0001"},
                {"line": 5, "who": None, "what": "Вторая", "id": "ch01_s010_0002"},
                {"line": 6, "who": None, "what": "Без озвучки", "id": "ch01_s010_0003"},
            ],
        },
    )
    rep = sc.SceneCompileReport()
    dispatch = {"gate": [{"to_label": "ch01_s020", "when": None}]}
    text = sc.emit_scene(unit, dispatch, {}, {}, rep, "# hdr\n",
                         voiced={"ch01_s010_0001", "ch01_s010_0002"})
    lines = text.split("\n")
    i1 = lines.index('    voice vn.voice_path("ch01_s010_0001")')
    assert lines[i1 + 1] == '    "Первая" id ch01_s010_0001'
    i2 = lines.index('            voice vn.voice_path("ch01_s010_0002")')
    assert lines[i2 + 1] == '            "Вторая" id ch01_s010_0002'
    assert 'voice vn.voice_path("ch01_s010_0003")' not in text
