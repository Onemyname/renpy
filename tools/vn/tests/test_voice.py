"""Голосовая подсистема (§4.9/C5): манифесты, валидация, импорт, инжекция
voice-операторов и транскод мастеров."""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import pytest

from helpers import mk_root, write_project
from vn import voice
from vn.voice import (
    ImportReport,
    Tts,
    VoiceError,
    import_takes,
    load_manifests,
    manifest_rows,
    master_path,
    resolve_tts,
    synth_drafts,
    tts_text,
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
    (root / "loc" / "loc.yaml").write_text(
        "schema: loc@2\nsource:\n  code: ru\n  name: \u0420\u0443\u0441\u0441\u043a\u0438\u0439\n",
        encoding="utf-8")
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


def test_import_final_replaces_draft_master_in_other_format(tmp_path, repo_root):
    """Финал в другом формате обязан вытеснить черновой мастер: master_path берёт
    первое расширение из MASTER_EXTS, и оставленный .wav звучал бы вместо .opus."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "draft"})
    old_draft = _master(root, "ru", "ch01_s010_0001", ext=".wav")
    takes = tmp_path / "takes"
    takes.mkdir()
    (takes / "ch01_s010_0001.opus").write_bytes(b"OggS-final")

    rep = import_takes(root, takes, "ru")
    assert not rep.errors
    assert not old_draft.exists()
    assert master_path(root, "ru", "ch01_s010_0001").suffix == ".opus"
    assert validate(root).ok, validate(root).errors


def test_import_rejects_two_versions_of_one_take(tmp_path, repo_root):
    """Две версии одного дубля в пачке легли бы двумя мастерами одного line_id;
    какая нужна — знает студия, поэтому отказ и ничего не разложено."""
    root = _mk_voice_root(tmp_path, repo_root)
    takes = tmp_path / "takes"
    takes.mkdir()
    (takes / "ch01_s010_0001.wav").write_bytes(b"riff")
    (takes / "ch01_s010_0001.opus").write_bytes(b"OggS")

    rep = import_takes(root, takes, "ru")
    assert any("две версии дубля" in e for e in rep.errors)
    assert not (root / "assets_src" / "voice").exists()


def test_validate_two_masters_for_one_line_is_error(tmp_path, repo_root):
    """Дубль, положенный руками рядом с прежним: сиротой он не считается (stem
    объявлен), а конвейер споткнулся бы об него много позже — нужна адресная
    ошибка здесь, с указанием, что удалить."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final"})
    _master(root, "ru", "ch01_s010_0001", ext=".wav")
    _master(root, "ru", "ch01_s010_0001", ext=".opus")

    errs = [e for e in validate(root).errors if "ch01_s010_0001" in e]
    assert len(errs) == 1 and "несколько мастеров" in errs[0]
    assert ".opus" in errs[0] and ".wav" in errs[0]


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


# ── TTS-черновики (§4.9) ──────────────────────────────────────────────────────

def _tools(monkeypatch, **installed):
    """Подменить обнаружение бинарей: _tools(mp, piper='/f/piper') = «стоит piper»."""
    from vn import pipeline

    monkeypatch.setattr(pipeline, "find_tool",
                        lambda name, env_var: installed.get(name))


def _fake_backend(monkeypatch) -> list[tuple[str, str]]:
    """Синтезатор-заглушка: пишет валидный WAV и запоминает (line_id, текст).
    Так проверяется ПОТОК (что синтезируем, что кладём, что пишем в манифест) без
    зависимости от установленных в системе бэкендов; сами бэкенды — тестами ниже."""
    calls: list[tuple[str, str]] = []

    def synth(tts, text, out_wav):
        calls.append((out_wav.stem, text))
        _wav(out_wav)

    monkeypatch.setattr(voice, "_synth_wav", synth)
    monkeypatch.setattr(voice, "resolve_tts", lambda *a, **k: Tts(
        backend="fake", voice="test-voice", rate=1.0, argv=lambda out_wav: []))
    # Транскод — забота encode_opus (проверен отдельно, ему нужен ffmpeg);
    # здесь важно лишь, что мастер кладётся в .opus.
    monkeypatch.setattr(voice, "encode_opus", lambda src, tmp_dir: b"OggS-fake")
    return calls


def test_tts_text_strips_renpy_markup():
    """Синтезатор произнёс бы разметку буквально — теги и интерполяции снимаются."""
    assert tts_text("{i}Привет,{/i} [player_name]! {w=0.5}Идём?") == "Привет, ! Идём?"
    assert tts_text("Скобки {{ и [[ внутри") == "Скобки и внутри"
    assert tts_text("{w}{nw}") == ""


def test_tts_generates_only_holes_and_never_touches_final(tmp_path, repo_root,
                                                        monkeypatch):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final", "ch01_s010_0002": "draft"})
    final_master = _master(root, "ru", "ch01_s010_0001")
    draft_master = _master(root, "ru", "ch01_s010_0002")
    calls = _fake_backend(monkeypatch)
    rep = synth_drafts(root, "ch01")

    assert rep.generated == ["ch01_s020_0001"]          # только дыра покрытия
    assert calls == [("ch01_s020_0001", "Третья")]
    assert any("final" in s for s in rep.skipped)
    assert any("черновик уже есть" in s for s in rep.skipped)
    assert final_master.read_bytes() == b"fake-audio"    # записанный дубль не тронут
    assert draft_master.read_bytes() == b"fake-audio"
    mf = (root / "content" / "chapters" / "ch01_test" / "voice" / "ru.voice.yaml") \
        .read_text(encoding="utf-8")
    assert "ch01_s020_0001: {status: draft}" in mf       # черновик — только draft
    assert "ch01_s010_0001: {status: final}" in mf
    assert master_path(root, "ru", "ch01_s020_0001").suffix == ".opus"
    assert validate(root).ok, validate(root).errors


def test_tts_repeat_is_noop_and_needs_no_backend(tmp_path, repo_root, monkeypatch):
    """Повторный прогон полностью покрытой главы обязан быть успешным даже там,
    где TTS не установлен вообще — иначе команду нельзя держать в скриптах."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "draft", "ch01_s010_0002": "draft",
                     "ch01_s020_0001": "draft"})
    for lid in ("ch01_s010_0001", "ch01_s010_0002", "ch01_s020_0001"):
        _master(root, "ru", lid)
    _tools(monkeypatch)      # ни piper, ни say
    rep = synth_drafts(root, "ch01")
    assert rep.generated == [] and rep.backend == ""
    assert len(rep.skipped) == 3 and rep.updated_manifests == []


def test_tts_regenerate_drafts_replaces_master_and_format(tmp_path, repo_root,
                                                         monkeypatch):
    """Перегенерация обязана убрать прежний мастер: master_path берёт первое
    расширение из MASTER_EXTS, и оставленный .wav заглушал бы новый .opus."""
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0001": "final", "ch01_s010_0002": "draft"})
    _master(root, "ru", "ch01_s010_0001", ext=".wav")
    old_draft = _master(root, "ru", "ch01_s010_0002", ext=".wav")
    _fake_backend(monkeypatch)
    rep = synth_drafts(root, "ch01", only_missing=False)

    assert rep.generated == ["ch01_s010_0002", "ch01_s020_0001"]
    assert not old_draft.exists()
    assert master_path(root, "ru", "ch01_s010_0002").suffix == ".opus"
    assert master_path(root, "ru", "ch01_s010_0001").suffix == ".wav"   # final как был
    assert validate(root).ok, validate(root).errors


def test_tts_char_filter_limits_lines(tmp_path, repo_root, monkeypatch):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {})
    calls = _fake_backend(monkeypatch)
    rep = synth_drafts(root, "ch01", char="mira")
    assert rep.generated == ["ch01_s010_0002", "ch01_s020_0001"]
    assert [lid for lid, _text in calls] == rep.generated


def test_tts_dub_language_speaks_translation(tmp_path, repo_root, monkeypatch):
    """Дубляж обязан говорить своим текстом: ledger хранит только исходный.
    Реплика без перевода — предупреждение, а не молчаливый русский в en-паке."""
    root = _mk_voice_root(tmp_path, repo_root)
    po = root / "loc" / "po" / "en"
    po.mkdir(parents=True)
    (po / "ch01.po").write_text(
        'msgid ""\nmsgstr "Content-Type: text/plain; charset=utf-8\\nLanguage: en\\n"\n\n'
        'msgctxt "ch01_s010_0002"\nmsgid "Вторая"\nmsgstr "{i}The second{/i}"\n',
        encoding="utf-8")
    calls = _fake_backend(monkeypatch)
    rep = synth_drafts(root, "ch01", lang="en")

    assert rep.generated == ["ch01_s010_0002"]
    assert calls == [("ch01_s010_0002", "The second")]
    assert len(rep.warnings) == 2 and all("нет перевода на en" in w for w in rep.warnings)
    assert (root / "assets_src" / "voice" / "en" / "ch01" /
            "ch01_s010_0002.opus").is_file()


def test_tts_manifest_header_comment_survives(tmp_path, repo_root, monkeypatch):
    """Шапку манифеста пишет человек — автоматика не имеет права её стереть."""
    root = _mk_voice_root(tmp_path, repo_root)
    mf = root / "content" / "chapters" / "ch01_test" / "voice" / "ru.voice.yaml"
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text("schema: voice@1\nchapter: ch01\nlang: ru\n"
                  "# Актёр в декрете — глава живёт на черновиках.\nlines: {}\n",
                  encoding="utf-8")
    _fake_backend(monkeypatch)
    synth_drafts(root, "ch01")
    assert "# Актёр в декрете — глава живёт на черновиках." in \
        mf.read_text(encoding="utf-8")


def test_tts_backend_autoselect_prefers_piper(tmp_path, repo_root, monkeypatch):
    """Выбор — по доступности, приоритет у кроссплатформенного piper: say звучит
    как системный диктор и есть только на macOS."""
    root = _mk_voice_root(tmp_path, repo_root)
    voices = tmp_path / "piper-voices"
    voices.mkdir()
    model = voices / "ru_RU-irina-medium.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv(voice.PIPER_VOICES_ENV, str(voices))
    monkeypatch.setattr(voice, "_piper_help", lambda tool: "--output-file FILE")
    _tools(monkeypatch, piper=Path("/fake/piper"), say=Path("/fake/say"))

    tts = resolve_tts(root, "ru")
    assert tts.backend == "piper" and tts.voice == str(model)
    # Пути — через str(Path(...)): на Windows argv несёт обратные слеши,
    # и литерал "/fake/piper" сравнивался бы с "\\fake\\piper".
    assert tts.argv(Path("/tmp/o.wav")) == [
        str(Path("/fake/piper")), "--model", str(model),
        "--output-file", str(Path("/tmp/o.wav")), "--length-scale", "1.000"]


def test_tts_piper_flag_dialect_is_probed(tmp_path, repo_root, monkeypatch):
    """У piper1-gpl флаги через дефис, у старого piper (rhasspy) — через
    подчёркивание; версия спрашивается у самого бинаря, а не угадывается."""
    root = _mk_voice_root(tmp_path, repo_root)
    model = tmp_path / "ru_RU-irina-medium.onnx"     # явный путь к модели — как из --voice
    model.write_bytes(b"onnx")
    monkeypatch.setattr(voice, "_piper_help", lambda tool: "usage: piper --output_file")
    _tools(monkeypatch, piper=Path("/fake/piper"))

    argv = resolve_tts(root, "ru", voice=str(model)).argv(Path("/tmp/o.wav"))
    assert "--output_file" in argv and "--length_scale" in argv
    # Темп — множитель ДЛИТЕЛЬНОСТИ: быстрее речь = меньше length_scale
    fast = resolve_tts(root, "ru", voice=str(model), rate=2.0)
    assert fast.argv(Path("/tmp/o.wav"))[-1] == "0.500"
    with pytest.raises(VoiceError, match="файла модели нет"):
        resolve_tts(root, "ru", voice=str(tmp_path / "no-such-voice.onnx"))


def test_tts_say_voice_follows_language(tmp_path, repo_root, monkeypatch):
    """Голос say выбирается по языку: черновик с чужим акцентом бесполезен."""
    root = _mk_voice_root(tmp_path, repo_root)
    monkeypatch.setattr(voice, "_say_voices",
                        lambda tool: {"Samantha": "en_US", "Yuri": "ru_RU"})
    _tools(monkeypatch, say=Path("/fake/say"))

    assert resolve_tts(root, "ru").voice == "Yuri"      # предпочтения нет — берём по локали
    assert resolve_tts(root, "en").voice == "Samantha"
    with pytest.raises(VoiceError, match="ни одного голоса для языка ja"):
        resolve_tts(root, "ja")
    with pytest.raises(VoiceError, match="say такого голоса не знает"):
        resolve_tts(root, "ru", voice="Milena")


def test_tts_without_backend_is_actionable_error(tmp_path, repo_root, monkeypatch):
    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {})
    _tools(monkeypatch)
    with pytest.raises(VoiceError) as e:
        resolve_tts(root, "ru")
    assert "piper" in str(e.value) and "say" in str(e.value)
    assert "pipx install piper-tts" in str(e.value)     # рецепт установки, а не факт
    # то же самое видно через основной поток — черновики просто нечем собрать
    with pytest.raises(VoiceError):
        synth_drafts(root, "ch01")


def test_tts_piper_model_is_never_downloaded_silently(tmp_path, repo_root, monkeypatch):
    """Загрузка модели — только по явному флагу: тихие сотни мегабайт из vn voice
    tts недопустимы. В ошибке — прямая ссылка и путь, куда положить файл."""
    root = _mk_voice_root(tmp_path, repo_root)
    monkeypatch.delenv(voice.PIPER_VOICES_ENV, raising=False)
    monkeypatch.setattr(voice, "_piper_help", lambda tool: "--output-file")
    _tools(monkeypatch, piper=Path("/fake/piper"))
    with pytest.raises(VoiceError) as e:
        resolve_tts(root, "ru")
    assert "--allow-download" in str(e.value)
    assert voice._piper_voice_url("ru_RU-irina-medium", ".onnx") == (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx")
    with pytest.raises(VoiceError, match="дефолтного голоса для языка ja"):
        resolve_tts(root, "ja")


def test_tts_rate_out_of_range_is_error(tmp_path, repo_root, monkeypatch):
    root = _mk_voice_root(tmp_path, repo_root)
    _tools(monkeypatch, say=Path("/fake/say"))
    with pytest.raises(VoiceError, match="вне диапазона"):
        resolve_tts(root, "ru", rate=5.0)


def test_tts_say_end_to_end(tmp_path, repo_root):
    """Полный путь на реальном бэкенде: say -> WAV -> encode_opus -> мастер.
    Скипается там, где say или ffmpeg нет (Linux/CI) — проверять там нечего."""
    from vn.pipeline import find_ffmpeg
    from vn.voice import _say_voices

    say = Path("/usr/bin/say")
    if not say.is_file():
        pytest.skip("нужен macOS say")
    if find_ffmpeg() is None:
        pytest.skip("нужен ffmpeg (vn pipeline doctor)")
    if not any(loc.startswith("ru") for loc in _say_voices(say).values()):
        pytest.skip("в системе нет русского голоса say")

    root = _mk_voice_root(tmp_path, repo_root)
    _manifest(root, {"ch01_s010_0002": "final"})
    _master(root, "ru", "ch01_s010_0002")
    rep = synth_drafts(root, "ch01", char="mira", backend="say")

    assert rep.errors == [] and rep.warnings == []
    assert rep.generated == ["ch01_s020_0001"] and rep.backend == "say"
    master = master_path(root, "ru", "ch01_s020_0001")
    assert master.suffix == ".opus" and master.read_bytes()[:4] == b"OggS"
    assert validate(root).ok, validate(root).errors
    # стейджинг за собой убран: незамеченные wav-полуфабрикаты в .vncache — мусор,
    # который на следующем прогоне попал бы в импорт
    assert not list((root / voice.TTS_STAGE_REL).rglob("*"))


def test_import_draft_never_destroys_a_recorded_final_take(tmp_path, repo_root):
    """Раскладка вытесняет мастер прежнего формата, поэтому черновик поверх
    записанного финала уничтожил бы дубль актёра на диске — а шапка модуля
    обещает, что final автоматика не перезаписывает никогда. Отказ, а не догадка."""
    root = _mk_voice_root(tmp_path, repo_root)
    final = tmp_path / "takes_final"
    final.mkdir()
    (final / "ch01_s010_0001.wav").write_bytes(b"final-take")
    assert voice.import_takes(root, final, "ru").errors == []
    master = root / "assets_src" / "voice" / "ru" / "ch01" / "ch01_s010_0001.wav"
    assert master.is_file()

    draft = tmp_path / "takes_draft"
    draft.mkdir()
    (draft / "ch01_s010_0001.opus").write_bytes(b"tts-draft")
    rep = voice.import_takes(root, draft, "ru", status=voice.STATUS_DRAFT)
    assert any("уже есть записанный дубль" in e for e in rep.errors), rep.errors
    assert master.read_bytes() == b"final-take", "дубль актёра затёрт черновиком"
    assert not (master.with_suffix(".opus")).exists()


def test_missing_ledger_is_an_error_not_a_warning(tmp_path, repo_root):
    """Без ledger покрытие озвучки не посчитать — значит проверка НЕ выполнена.

    Раньше это было предупреждением, и последствие было тихим: `if says` внутри
    validate выключает сразу три проверки (сверка «реплика есть в главе»,
    покрытие, поиск дыр), а релизный гейт разбирает отчёт по
    errors/holes/drafts/coverage и поле warnings не читает вовсе. В сумме у
    озвученной главы без шарда ledger не было НИ FAIL, НИ WARN, НИ PASS — строка
    про озвучку просто исчезала из чек-листа релиза, и «дыра посреди озвученной
    главы», которую гейт обещает ловить, проходила незамеченной."""
    import shutil

    from vn.voice import validate as voice_validate

    root = tmp_path / "repo"
    (root / "content" / "chapters" / "ch01_demo").mkdir(parents=True)
    src_voice = repo_root / "content" / "chapters" / "ch01_awakening" / "voice"
    if not src_voice.is_dir():
        pytest.skip("в дереве нет voice-манифестов")
    shutil.copytree(src_voice, root / "content" / "chapters" / "ch01_demo" / "voice")
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    (root / "loc" / "ledger").mkdir(parents=True)     # шарда главы НЕТ

    rep = voice_validate(root)
    assert any("ledger" in e for e in rep.errors), (
        f"несобранный ledger не стал ошибкой: errors={rep.errors[:2]} "
        f"warnings={rep.warnings[:2]}")
    assert rep.ok is False


def test_release_gate_never_drops_the_voice_line(repo_root):
    """У релизного гейта не может быть состояния «строки про озвучку нет».

    Отчёт разбирается по errors/holes/drafts/coverage; если все четыре пусты, а
    предупреждения есть — это «проверить не удалось», и сказать об этом обязан
    сам чек-лист, а не читатель кода."""
    src = (repo_root / "tools" / "vn" / "src" / "vn" / "release.py").read_text(
        encoding="utf-8")
    branch = src.split("vo = voice_validate(root)", 1)[1].split("\n    from ", 1)[0]
    assert "vo.warnings" in branch, "предупреждения отчёта озвучки не доходят до гейта"
