"""Локализация (G8, ADR-0005): пакеты языков, PO round-trip, tl-генерация,
fuzzy при смене исходника, pseudo, манифесты рантайма, свежесть ledger."""

import json
import os
from pathlib import Path

import polib
import pytest

from vn.loc.po import (LocError, discover_languages, extract, import_translations,
                       pseudo, report, scaffold_language, source_language)


def _mk_loc_root(tmp_path):
    root = tmp_path / "repo"
    (root / "loc" / "ledger").mkdir(parents=True)
    (root / "content" / "ui").mkdir(parents=True)
    (root / "content" / "characters" / "mira").mkdir(parents=True)
    (root / "loc" / "loc.yaml").write_text(
        "schema: loc@2\nsource:\n  code: ru\n  name: Русский\n", encoding="utf-8"
    )
    (root / "loc" / "po" / "en").mkdir(parents=True)
    (root / "loc" / "po" / "en" / "language.yaml").write_text(
        "schema: language@1\ncode: en\nname: English\n", encoding="utf-8"
    )
    (root / "loc" / "ledger" / "ch01.json").write_text(json.dumps({
        "schema": "ledger@1", "chapter": "ch01",
        "says": {"ch01_s010_0001": {"who": "mira", "text": "Привет"},
                 "ch01_s010_0002": {"who": None, "text": "Тишина."}},
        "menus": {"ch01_s010_m001": {"items": ["Да", "Нет"]}},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "content" / "ui" / "strings.yaml").write_text(
        'schema: strings@1\nstrings:\n  meta.chapters.ch01.title: "Глава 1"\n',
        encoding="utf-8",
    )
    (root / "content" / "characters" / "mira" / "character.yaml").write_text(
        'schema: character@1\nid: mira\nname: "Мира"\ncolor: "#c94f7c"\n', encoding="utf-8"
    )
    return root


def test_discovery_scans_packages(tmp_path):
    """Язык = каталог с language.yaml; списка языков нет нигде (ADR-0005)."""
    root = _mk_loc_root(tmp_path)
    langs = discover_languages(root)
    assert [l.code for l in langs] == ["en"]
    assert langs[0].name == "English" and not langs[0].synthetic

    # Добавление языка = добавление пакета, никакой регистрации
    (root / "loc" / "po" / "de").mkdir()
    (root / "loc" / "po" / "de" / "language.yaml").write_text(
        "schema: language@1\ncode: de\nname: Deutsch\n", encoding="utf-8"
    )
    assert [l.code for l in discover_languages(root)] == ["de", "en"]

    src = source_language(root)
    assert (src.code, src.name) == ("ru", "Русский")


def test_discovery_rejects_package_without_manifest(tmp_path):
    """Каталог без language.yaml — громкая ошибка, не тихо пропущенный язык."""
    root = _mk_loc_root(tmp_path)
    (root / "loc" / "po" / "fr").mkdir()
    (root / "loc" / "po" / "fr" / "common.po").write_text("", encoding="utf-8")
    with pytest.raises(LocError, match="fr"):
        discover_languages(root)


def test_discovery_rejects_code_dir_mismatch(tmp_path):
    root = _mk_loc_root(tmp_path)
    (root / "loc" / "po" / "de").mkdir()
    (root / "loc" / "po" / "de" / "language.yaml").write_text(
        "schema: language@1\ncode: fr\nname: Deutsch\n", encoding="utf-8"
    )
    with pytest.raises(LocError, match="code"):
        discover_languages(root)


def test_scaffold_language(tmp_path):
    root = _mk_loc_root(tmp_path)
    mf = scaffold_language(root, "de")            # native-название из справочника
    assert mf.is_file()
    assert [l.name for l in discover_languages(root) if l.code == "de"] == ["Deutsch"]
    with pytest.raises(LocError, match="уже существует"):
        scaffold_language(root, "de")
    with pytest.raises(LocError, match="native"):
        scaffold_language(root, "tlh")            # неизвестный код без --name
    mf2 = scaffold_language(root, "tlh", name="tlhIngan Hol")
    assert "tlhIngan Hol" in mf2.read_text(encoding="utf-8")


def test_extract_import_roundtrip(tmp_path):
    root = _mk_loc_root(tmp_path)
    rep = extract(root)
    assert "loc/po/en/ch01.po" in rep.changed
    assert "loc/po/en/common.po" in rep.changed

    po = polib.pofile(str(root / "loc" / "po" / "en" / "ch01.po"))
    by_ctx = {e.msgctxt: e for e in po}
    assert by_ctx["ch01_s010_0001"].msgid == "Привет"
    by_ctx["ch01_s010_0001"].msgstr = "Hi"
    by_ctx["ch01_s010_m001[0]"].msgstr = "Yes"
    by_ctx["ch01_s010_m001[1]"].msgstr = "No"
    po.save()
    common = polib.pofile(str(root / "loc" / "po" / "en" / "common.po"))
    for e in common:
        if e.msgctxt == "char:mira":
            e.msgstr = "Mira"
        if e.msgctxt == "string:meta.chapters.ch01.title":
            e.msgstr = "Chapter 1"
    common.save()

    import_translations(root)
    dlg = (root / "game" / "tl" / "en" / "dialogue_ch01.rpy").read_text(encoding="utf-8")
    assert 'translate en ch01_s010_0001:\n    mira "Hi"' in dlg
    assert "ch01_s010_0002" not in dlg          # непереведённая реплика не поставляется
    cmn = (root / "game" / "tl" / "en" / "common.rpy").read_text(encoding="utf-8")
    assert 'old "Мира"' in cmn and 'new "Mira"' in cmn
    assert "'ch01_s010_m001': ['Yes', 'No']" in cmn
    assert "'meta.chapters.ch01.title': 'Chapter 1'" in cmn

    cov = report(root).coverage["en"]
    assert cov == {"total": 6, "translated": 5, "fuzzy": 0}


def test_import_emits_runtime_manifest_and_registration(tmp_path):
    """Каждый язык обязан получить language.json (Language Registry) и хотя бы
    один translate-стейтмент: renpy.known_languages() видит только языки
    с translate-блоками — язык с одним переведённым UI иначе бы «исчез»."""
    root = _mk_loc_root(tmp_path)
    extract(root)
    import_translations(root)

    mf = json.loads((root / "game" / "tl" / "en" / "language.json").read_text(encoding="utf-8"))
    assert mf == {"code": "en", "name": "English", "font": None, "synthetic": False,
                  "generator": "vn loc import"}

    cmn = (root / "game" / "tl" / "en" / "common.rpy").read_text(encoding="utf-8")
    assert "translate en python:" in cmn


def _mk_font(root, name):
    """Файл-заглушка шрифта в game/fonts/: импорт эмитит переопределение роли
    только для реально существующего файла."""
    fdir = root / "game" / "fonts"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / name).write_bytes(b"stub")


def test_import_applies_package_font(tmp_path):
    """Плоский font — исторический алиас fonts.text: старые пакеты обязаны
    работать без правок манифеста."""
    root = _mk_loc_root(tmp_path)
    (root / "loc" / "po" / "ja").mkdir(parents=True)
    (root / "loc" / "po" / "ja" / "language.yaml").write_text(
        "schema: language@1\ncode: ja\nname: 日本語\nfont: fonts/NotoSansJP.ttf\n",
        encoding="utf-8",
    )
    _mk_font(root, "NotoSansJP.ttf")
    extract(root)
    rep = import_translations(root)
    assert rep.warnings == []
    cmn = (root / "game" / "tl" / "ja" / "common.rpy").read_text(encoding="utf-8")
    assert "translate ja python:" in cmn
    assert "gui.text_font = 'fonts/NotoSansJP.ttf'" in cmn
    mf = json.loads((root / "game" / "tl" / "ja" / "language.json").read_text(encoding="utf-8"))
    assert mf["font"] == "fonts/NotoSansJP.ttf" and mf["name"] == "日本語"


def test_import_applies_role_fonts(tmp_path):
    """fonts.<роль> переопределяет соответствующую gui-переменную: CJK-языку
    одного gui.text_font мало — имя персонажа осталось бы тофу."""
    root = _mk_loc_root(tmp_path)
    (root / "loc" / "po" / "ja").mkdir(parents=True)
    (root / "loc" / "po" / "ja" / "language.yaml").write_text(
        "schema: language@1\ncode: ja\nname: 日本語\n"
        "fonts:\n  text: fonts/NotoSansJP.ttf\n  name: fonts/NotoSansJP-Bold.ttf\n",
        encoding="utf-8",
    )
    _mk_font(root, "NotoSansJP.ttf")
    _mk_font(root, "NotoSansJP-Bold.ttf")
    extract(root)
    rep = import_translations(root)
    assert rep.warnings == []
    cmn = (root / "game" / "tl" / "ja" / "common.rpy").read_text(encoding="utf-8")
    assert "gui.text_font = 'fonts/NotoSansJP.ttf'" in cmn
    assert "gui.name_text_font = 'fonts/NotoSansJP-Bold.ttf'" in cmn
    # Незаданные роли не трогаем: рантайм остаётся на базовых из gui.rpy
    assert "gui.interface_text_font" not in cmn
    # fonts.text — это и шрифт native-названия в списке языков (манифест)
    mf = json.loads((root / "game" / "tl" / "ja" / "language.json").read_text(encoding="utf-8"))
    assert mf["font"] == "fonts/NotoSansJP.ttf"


def test_import_skips_missing_font_file(tmp_path):
    """Отсутствующий файл шрифта — warning, переопределение НЕ эмитится:
    рантайм остаётся на читаемом базовом шрифте, а не падает на битом пути."""
    root = _mk_loc_root(tmp_path)
    (root / "loc" / "po" / "ja").mkdir(parents=True)
    (root / "loc" / "po" / "ja" / "language.yaml").write_text(
        "schema: language@1\ncode: ja\nname: 日本語\n"
        "fonts:\n  interface: fonts/Missing.ttf\n",
        encoding="utf-8",
    )
    extract(root)
    rep = import_translations(root)
    assert any("fonts.interface" in w and "Missing.ttf" in w for w in rep.warnings)
    cmn = (root / "game" / "tl" / "ja" / "common.rpy").read_text(encoding="utf-8")
    assert "gui.interface_text_font" not in cmn
    # Регистрационный блок обязан остаться валидным и пустым
    assert "translate ja python:\n    pass" in cmn


def test_removed_language_cleans_tl(tmp_path):
    """Удаление пакета = удаление языка: tl-каталог вычищается целиком
    (включая language.json — иначе Language Registry показал бы «пустой» язык)."""
    root = _mk_loc_root(tmp_path)
    extract(root)
    import_translations(root)
    en_dir = root / "game" / "tl" / "en"
    assert en_dir.is_dir()

    import shutil
    shutil.rmtree(root / "loc" / "po" / "en")
    import_translations(root)
    assert not (en_dir / "language.json").exists()
    assert not list(en_dir.glob("*.rpy")) if en_dir.exists() else True
    assert not en_dir.exists()                   # пустой каталог не оставляем


def test_source_change_marks_fuzzy_and_blocks_delivery(tmp_path):
    root = _mk_loc_root(tmp_path)
    extract(root)
    po_path = root / "loc" / "po" / "en" / "ch01.po"
    po = polib.pofile(str(po_path))
    for e in po:
        if e.msgctxt == "ch01_s010_0001":
            e.msgstr = "Hi"
    po.save()

    # Исходник изменился (правка реплики) — перевод остаётся, но становится fuzzy
    ledger_path = root / "loc" / "ledger" / "ch01.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["says"]["ch01_s010_0001"]["text"] = "Привет!!!"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    extract(root)

    po = polib.pofile(str(po_path))
    e = {x.msgctxt: x for x in po}["ch01_s010_0001"]
    assert "fuzzy" in e.flags and e.msgstr == "Hi" and e.msgid == "Привет!!!"

    import_translations(root)
    dlg = root / "game" / "tl" / "en" / "dialogue_ch01.rpy"
    assert not dlg.is_file() or "ch01_s010_0001" not in dlg.read_text(encoding="utf-8")
    assert report(root).coverage["en"]["fuzzy"] == 1


def test_pseudo_generates_expanded_strings(tmp_path):
    root = _mk_loc_root(tmp_path)
    pseudo(root)
    # pseudo — обычный synthetic-пакет: манифест создан, дискавери его видит
    langs = {l.code: l for l in discover_languages(root)}
    assert langs["pseudo"].synthetic

    po = polib.pofile(str(root / "loc" / "po" / "pseudo" / "ch01.po"))
    e = {x.msgctxt: x for x in po}["ch01_s010_0001"]
    assert e.msgstr.startswith("[") and e.msgstr.endswith("]")
    assert len(e.msgstr) > len(e.msgid)          # удлинение для QA переполнений
    pseudo_cov = report(root).coverage["pseudo"]
    assert pseudo_cov["translated"] == pseudo_cov["total"]


def test_extract_regenerates_stale_pseudo(tmp_path):
    """extract держит pseudo свежим: правка исходника без ручного vn loc pseudo
    не должна оставлять псевдолокализацию устаревшей (QA гонял бы старый текст)."""
    root = _mk_loc_root(tmp_path)
    pseudo(root)
    ledger_path = root / "loc" / "ledger" / "ch01.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["says"]["ch01_s010_0001"]["text"] = "Совсем новый текст"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    extract(root)
    po = polib.pofile(str(root / "loc" / "po" / "pseudo" / "ch01.po"))
    e = {x.msgctxt: x for x in po}["ch01_s010_0001"]
    assert e.msgid == "Совсем новый текст" and "ǫвсę" in e.msgstr


def test_tl_cleanup_spares_foreign_files(tmp_path):
    """Очистка tl трогает только свой генерат (маркеры GEN_HEADER/generator):
    модовый перевод или ручной font-оверрайд, брошенный в game/tl, — не наш."""
    root = _mk_loc_root(tmp_path)
    extract(root)
    import_translations(root)

    mod_dir = root / "game" / "tl" / "es"
    mod_dir.mkdir(parents=True)
    (mod_dir / "dialogue.rpy").write_text("# мой модовый перевод\n", encoding="utf-8")
    (mod_dir / "language.json").write_text('{"code": "es", "name": "Español"}', encoding="utf-8")
    override = root / "game" / "tl" / "en" / "style_override.rpy"
    override.write_text("# ручной оверрайд\n", encoding="utf-8")

    import_translations(root)
    assert (mod_dir / "dialogue.rpy").is_file()
    assert (mod_dir / "language.json").is_file()
    assert override.is_file()


def test_obsolete_entry_resurrects(tmp_path):
    """Вернувшаяся строка переоткрывается (polib: obsolete — атрибут, не флаг)."""
    root = _mk_loc_root(tmp_path)
    extract(root)
    ledger_path = root / "loc" / "ledger" / "ch01.json"
    original = ledger_path.read_text(encoding="utf-8")
    ledger = json.loads(original)
    del ledger["says"]["ch01_s010_0002"]
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    extract(root)
    po = polib.pofile(str(root / "loc" / "po" / "en" / "ch01.po"))
    assert {e.msgctxt: e.obsolete for e in po}["ch01_s010_0002"]

    ledger_path.write_text(original, encoding="utf-8")   # строка вернулась
    extract(root)
    po = polib.pofile(str(root / "loc" / "po" / "en" / "ch01.po"))
    assert not {e.msgctxt: e.obsolete for e in po}["ch01_s010_0002"]
    rep = extract(root)                                   # и extract снова идемпотентен
    assert rep.changed == []


def test_import_validates_markup_and_escapes(tmp_path):
    root = _mk_loc_root(tmp_path)
    extract(root)
    po_path = root / "loc" / "po" / "en" / "ch01.po"
    po = polib.pofile(str(po_path))
    for e in po:
        if e.msgctxt == "ch01_s010_0001":
            e.msgstr = 'He said "stop"\nnow {b}bold'      # кавычки + \n + битый тег
    po.save()
    rep = import_translations(root)
    assert any("незакрытые теги" in x for x in rep.errors)

    po = polib.pofile(str(po_path))
    for e in po:
        if e.msgctxt == "ch01_s010_0001":
            e.msgstr = 'He said "stop"\nnow {b}bold{/b}'
    po.save()
    rep = import_translations(root)
    assert rep.errors == []
    dlg = (root / "game" / "tl" / "en" / "dialogue_ch01.rpy").read_text(encoding="utf-8")
    assert 'mira "He said \\"stop\\"\\nnow {b}bold{/b}"' in dlg


def test_markup_validator_accepts_context_tags(tmp_path):
    """{#file_time}-подобные контекст-теги — самозакрытые: перевод формата
    даты не должен падать «незакрытым тегом» (ui.file.time_format)."""
    from vn.loc.po import _validate_markup

    assert _validate_markup("{#file_time}%d.%m.%Y %H:%M", "{#file_time}%m/%d/%Y %H:%M") is None


def test_markup_validator_accepts_renpy_escapes(tmp_path):
    """Эскейпы Ren'Py {{ и [[ — литеральные скобки: перевод с ними легитимен."""
    from vn.loc.po import _validate_markup

    assert _validate_markup("Скобка [[x]", "Bracket [[y]") is None
    assert _validate_markup("Фигурная {{скобка}", "Curly {{brace}") is None
    # А непарные скобки по-прежнему бракуются
    assert _validate_markup("текст", "битый [тег") is not None


def test_discover_rejects_broken_manifest_yaml(tmp_path):
    """Пустой/битый language.yaml — это LocError с путём, не голый трейсбек
    (контракт CLI: exit 1 всегда сопровождается сообщением)."""
    root = _mk_loc_root(tmp_path)
    mf = root / "loc" / "po" / "en" / "language.yaml"

    mf.write_text("", encoding="utf-8")                       # пустой -> None
    with pytest.raises(LocError, match="language.yaml"):
        discover_languages(root)

    mf.write_text("<<<<<<< HEAD\ncode: en\n", encoding="utf-8")   # merge-конфликт
    with pytest.raises(LocError, match="language.yaml"):
        discover_languages(root)

    mf.write_text("schema: language@1\ncode: en\nname: 123\n", encoding="utf-8")
    with pytest.raises(LocError, match="строкой"):           # name не строка
        discover_languages(root)


def test_scaffold_escapes_hostile_name(tmp_path):
    """--name с двоеточием/решёткой не должен порождать битый YAML-манифест."""
    root = _mk_loc_root(tmp_path)
    scaffold_language(root, "pt_br", name="Português: Brasil # nota")
    langs = {l.code: l for l in discover_languages(root)}
    assert langs["pt_br"].name == "Português: Brasil # nota"
    with pytest.raises(LocError, match="pseudo"):
        scaffold_language(root, "pseudo", name="X")           # pseudo — vn loc pseudo


def test_extract_pseudo_idempotent(tmp_path):
    """Повторный extract без изменений исходников не рапортует pseudo «обновлён»."""
    root = _mk_loc_root(tmp_path)
    pseudo(root)
    extract(root)
    rep = extract(root)
    assert rep.changed == []


def test_pseudo_delivered_to_game_tl(tmp_path):
    """Псевдолокализация обязана доезжать до game/tl (иначе QA-прогон ложно-зелёный)."""
    root = _mk_loc_root(tmp_path)
    pseudo(root)
    import_translations(root)
    assert (root / "game" / "tl" / "pseudo" / "dialogue_ch01.rpy").is_file()
    mf = json.loads((root / "game" / "tl" / "pseudo" / "language.json").read_text(encoding="utf-8"))
    assert mf["synthetic"] is True


def test_pseudo_preserves_interpolations(tmp_path):
    from vn.loc.po import _pseudoize

    assert "[name]" in _pseudoize("Привет, [name]! {b}Да{/b}")
    assert "{b}" in _pseudoize("Привет, [name]! {b}Да{/b}")


def test_keys_reconciles_orphan_ledger_without_scenes(tmp_path):
    """Осиротевшие шарды ledger ловятся (--check) и чистятся даже при нуле сцен:
    ранний выход assign_ids не должен оставлять «переводы исчезнувших глав»."""
    from vn.loc.keys import assign_ids

    root = tmp_path / "repo"
    (root / "loc" / "ledger").mkdir(parents=True)
    (root / "content" / "chapters").mkdir(parents=True)
    (root / "loc" / "ledger" / "ch99.json").write_text("{}", encoding="utf-8")

    rep = assign_ids(root, check=True)
    assert any("ch99" in m for m in rep.missing)
    assert (root / "loc" / "ledger" / "ch99.json").is_file()   # --check не пишет

    rep2 = assign_ids(root, check=False)
    assert not (root / "loc" / "ledger" / "ch99.json").exists()
    assert any("ch99" in l for l in rep2.ledgers)


_SDK = os.environ.get("RENPY_SDK")


@pytest.mark.skipif(not (_SDK and (Path(_SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_e2e_keys_check_detects_stale_ledger(repo_root):
    """CI-гейт свежести (G8): правка ТЕКСТА реплики при существующем id не меняет
    scene.rpy — но keys --check обязан увидеть расхождение ledger со сценой."""
    from vn.loc.keys import assign_ids

    rep = assign_ids(repo_root, check=True)
    assert rep.missing == []                                  # чистый репозиторий свеж

    ledger_path = repo_root / "loc" / "ledger" / "ch01.json"
    # Байты, не текст: тест мутирует БОЕВОЙ файл репозитория, и восстановление
    # через write_text на Windows возвращало его с CRLF — фантомный дифф после
    # каждого прогона набора (аудит 2026-08-21, п.3).
    original = ledger_path.read_bytes()
    try:
        data = json.loads(original.decode("utf-8"))
        sid = sorted(data["says"])[0]
        data["says"][sid]["text"] += " (устарело)"
        ledger_path.write_bytes(
            (json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            .encode("utf-8"))
        rep2 = assign_ids(repo_root, check=True)
        assert any("ch01.json устарел" in m for m in rep2.missing)
    finally:
        ledger_path.write_bytes(original)

# ── High-watermark say-id: номер не переиспользуется (P1-8) ───────────────────

def _journal_root(tmp_path, *, retired=None, says=None, menus=None, schema="ledger@2"):
    root = tmp_path / "repo"
    (root / "loc" / "ledger").mkdir(parents=True)
    (root / "content" / "chapters" / "ch01_intro" / "scenes").mkdir(parents=True)
    doc = {"schema": schema, "chapter": "ch01",
           "says": says if says is not None else {},
           "menus": menus if menus is not None else {}}
    if schema == "ledger@2":
        doc["retired"] = {i: {"state": "retired"} for i in (retired or ())}
    (root / "loc" / "ledger" / "ch01.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root


def test_journal_seeds_counter_from_retired(tmp_path):
    """Номер удалённой реплики остаётся ЗАНЯТЫМ: иначе новая реплика получит его id,
    а вместе с ним — перевод удалённой (msgctxt в PO совпадёт)."""
    from vn.loc.keys import KeysReport, _journal

    root = _journal_root(tmp_path, retired=["ch01_s010_0002"],
                         says={"ch01_s010_0001": {"who": None, "text": "Живая"}})
    rep = KeysReport()
    known, prior = _journal(root, {"ch01"}, rep)
    assert known["ch01"] == {"ch01_s010_0001", "ch01_s010_0002"}
    assert prior["ch01"] == {"ch01_s010_0002"} and rep.errors == []


def test_journal_migration_seeds_from_obsolete_po(tmp_path):
    """Шард на ledger@1: журнала ещё нет, и единственный след удалённых id —
    obsolete-записи в PO. Без засева миграция сбросила бы метку аллокации."""
    from vn.loc.keys import KeysReport, _journal

    root = _journal_root(tmp_path, schema="ledger@1",
                         says={"ch01_s010_0003": {"who": None, "text": "Живая"}})
    po_dir = root / "loc" / "po" / "en"
    po_dir.mkdir(parents=True)
    (po_dir / "ch01.po").write_text(
        'msgid ""\nmsgstr ""\n\n'
        '#~ msgctxt "ch01_s010_0001"\n#~ msgid "Удалённая"\n#~ msgstr "Deleted"\n\n'
        'msgctxt "ch01_s010_m001[0]"\nmsgid "Да"\nmsgstr "Yes"\n',
        encoding="utf-8")
    known, _prior = _journal(root, {"ch01"}, KeysReport())
    assert "ch01_s010_0001" in known["ch01"], "obsolete-id обязан занимать номер"
    assert "ch01_s010_m001" in known["ch01"], "суффикс индекса пункта срезается"
    assert not any("[" in i for i in known["ch01"]), \
        "ключ с [0] не прошёл бы propertyNames схемы ledger@2"


def test_journal_broken_shard_is_an_error_not_a_reset(tmp_path):
    """Битый шард нельзя трактовать как «журнала нет»: это тихий сброс метки, то
    есть повторная выдача уже использованных номеров."""
    from vn.loc.keys import KeysReport, _journal

    root = _journal_root(tmp_path)
    (root / "loc" / "ledger" / "ch01.json").write_text("{битый", encoding="utf-8")
    rep = KeysReport()
    known, _prior = _journal(root, {"ch01"}, rep)
    assert "ch01" not in known
    assert any("восстановите файл из git" in e for e in rep.errors)


def test_ledger2_schema_rejects_menu_context_suffix(repo_root):
    """Схема журнала обязана отвергать ключ с индексом пункта: если бы засев из PO
    его пропустил, шард не прошёл бы собственную валидацию."""
    from vn.schemas import SchemaRegistry

    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    bad = {"schema": "ledger@2", "chapter": "ch01", "says": {}, "menus": {},
           "retired": {"ch01_s010_m001[0]": {"state": "retired"}}}
    assert reg.validate(bad, "ch01.json") != []
    good = dict(bad, retired={"ch01_s010_m001": {"state": "retired"}})
    assert reg.validate(good, "ch01.json") == []


def test_repo_ledgers_are_on_journal_schema(repo_root):
    """Миграция прошла и не откатывается: шард на ledger@1 означает, что номера
    снова переиспользуются."""
    shards = sorted((repo_root / "loc" / "ledger").glob("ch*.json"))
    assert shards, "шардов журнала нет — проверка выродилась"
    for shard in shards:
        doc = json.loads(shard.read_text(encoding="utf-8"))
        assert doc["schema"] == "ledger@2", shard.name
        assert "retired" in doc, shard.name


@pytest.mark.skipif(not (_SDK and (Path(_SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_e2e_deleted_line_number_is_not_reused(repo_root, tmp_path):
    """САМ ДЕФЕКТ, из-за которого нужен журнал: удалить реплику, добавить новую —
    новая обязана получить СЛЕДУЮЩИЙ номер, а не номер удалённой (иначе к ней
    приедет перевод удалённой).

    Прогон идёт на копии репозитория: команда физически правит авторские .rpy."""
    import shutil

    from vn.loc.keys import assign_ids

    root = tmp_path / "copy"
    for rel in ("project.yaml", "tools/schemas", "content", "loc", "game/framework"):
        src = repo_root / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)

    scene = next((root / "content" / "chapters").rglob("s010_*.scene.rpy"))
    text = scene.read_text(encoding="utf-8")
    ledger_path = root / "loc" / "ledger" / "ch01.json"
    before = json.loads(ledger_path.read_text(encoding="utf-8"))
    ids = sorted(i for i in before["says"] if i.startswith("ch01_s010_"))
    victim = ids[-1]                      # последняя реплика сцены: её номер и есть метка
    victim_line = next(l for l in text.splitlines() if f"id {victim}" in l)

    # 1) удалить реплику с самым большим номером
    scene.write_text(text.replace(victim_line + "\n", ""), encoding="utf-8")
    rep = assign_ids(root, check=False)
    assert rep.errors == [], rep.errors
    mid = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert victim not in mid["says"], "реплики больше нет"
    assert victim in mid["retired"], "её номер обязан остаться занятым"

    # 2) добавить новую реплику на её место
    lines = scene.read_text(encoding="utf-8").splitlines()
    # Вставляем сразу после ПЕРВОЙ реплики с id: её отступ гарантированно корректен
    # для тела сцены (вставка после пункта меню сломала бы блок choice).
    anchor = next(i for i, l in enumerate(lines) if " id ch01_s010_" in l)
    indent = lines[anchor][: len(lines[anchor]) - len(lines[anchor].lstrip())]
    lines.insert(anchor + 1, f'{indent}"Новая реплика после удаления."')
    scene.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep2 = assign_ids(root, check=False)
    assert rep2.errors == [], rep2.errors

    after = json.loads(ledger_path.read_text(encoding="utf-8"))
    fresh = sorted(set(after["says"]) - set(mid["says"]))
    assert len(fresh) == 1, fresh
    assert fresh[0] != victim, (
        f"номер {victim} переиспользован — новая реплика унаследует перевод удалённой")
    assert int(fresh[0].rsplit("_", 1)[1]) > int(victim.rsplit("_", 1)[1])
    assert victim in after["retired"], "журнал не должен терять отставленный номер"


def test_menu_marker_rule_lives_in_one_place():
    """Правило близости маркера `$ vn_menu` к оператору `menu` — одно на проект.

    content/scenes.py объявляет себя единственным местом этого правила
    (MENU_MARKER_LOOKBACK + menu_marker + MENU_ID_IN_SOURCE_RE), но из двух
    названных потребителей мигрировал только графовый компилятор: аллокатор id
    держал свою копию регекспа и литерал «3» в двух местах. Расхождение значений
    разъехало бы их молча — маркер, который видит один, второй считал бы
    отсутствующим, и меню получило бы второй id, то есть новую строку в ledger
    вместо перевода к существующей.

    Проверяется поведением: константа подменяется, и оба потребителя обязаны
    увидеть одно и то же."""
    from vn.content import scenes as sc
    from vn.loc import keys as lk

    assert lk.MENU_ID_RE is sc.MENU_ID_IN_SOURCE_RE, "регексп маркера продублирован"

    markers = [{"line": 10, "source": 'vn_menu = "ch01_s010_m001"'}]
    near, far = {"line": 12}, {"line": 40}
    assert sc.menu_marker(near, markers) is markers[0]
    assert sc.menu_marker(far, markers) is None

    # Сузим окно — и «близкий» маркер обязан перестать считаться близким СРАЗУ у
    # обоих: у keys.py своего литерала больше нет.
    saved = sc.MENU_MARKER_LOOKBACK
    try:
        sc.MENU_MARKER_LOOKBACK = 1
        assert sc.menu_marker(near, markers) is None
    finally:
        sc.MENU_MARKER_LOOKBACK = saved

    src = (Path(lk.__file__)).read_text(encoding="utf-8")
    assert '- 3 <=' not in src, "в аллокаторе id снова литерал окна маркера"


def test_source_language_cannot_get_a_translation_package(tmp_path):
    """Пакет перевода с кодом ИСХОДНОГО языка завести нельзя.

    В Ren'Py исходный язык — это language=None, отдельного пакета у него нет.
    Пакет с тем же кодом даёт в рантайм-реестре второй пункт с тем же native-
    названием, который никуда не переключает: игрок видит два «Русских», и выбор
    второго не меняет ничего. Про коллизию знал ровно один потребитель
    (`vn play --lang` схлопывает её в "@source"), а конвейер PO — нет.

    Проверяются оба входа: явная команда и автодискавери, потому что каталог,
    созданный руками мимо `vn loc add`, доезжал до game/tl/ молча."""
    from vn.loc.po import LocError, discover_languages, scaffold_language

    root = tmp_path / "repo"
    (root / "loc").mkdir(parents=True)
    (root / "loc" / "loc.yaml").write_text(
        "schema: loc@2\nsource: {code: ru, name: Русский}\n", encoding="utf-8")

    with pytest.raises(LocError, match="исходный язык"):
        scaffold_language(root, "ru", name="Русский")

    # Тот же пакет, созданный руками: автодискавери обязано его отбить.
    d = root / "loc" / "po" / "ru"
    d.mkdir(parents=True)
    (d / "language.yaml").write_text(
        'schema: language@1\ncode: ru\nname: "Русский"\n', encoding="utf-8")
    with pytest.raises(LocError, match="исходный язык"):
        discover_languages(root)

    # Контраст: обычный язык заводится как и раньше.
    import shutil
    shutil.rmtree(d)
    scaffold_language(root, "fr", name="Français")
    assert [lang.code for lang in discover_languages(root)] == ["fr"]


def test_markup_validator_rejects_an_unknown_text_tag():
    """Парность тега ничего не говорит о его СУЩЕСТВОВАНИИ.

    Валидатор следил только за стеком, а движок при отрисовке не прощает:
    renpy/text/text.py бросает `Exception: Unknown text tag`, и config.safe_text по
    умолчанию False (проект его не переопределяет). Типовая ошибка переводчика —
    `{bold}` вместо `{b}`: тег парен, гейты зелёные, и у игрока с этим языком НЕ
    РИСУЕТСЯ главное меню и экран выбора глав; та же ошибка в подписи выбора
    роняет игру посреди первой сцены.

    renpy lint этого не видит по построению: UI-строки и подписи выборов
    поставляются как repr-словари данных (VN_STRINGS_TL / VN_MENUS_TL), для
    линтера это литерал dict. Прежний страж проверял только НЕЗАКРЫТЫЙ тег."""
    from vn.loc.po import _validate_markup

    err = _validate_markup("Chapters", "{bold}Chapters{/bold}")
    assert err and "не знает" in err, err

    # Известные теги и самозакрывающиеся — проходят.
    assert _validate_markup("x", "{b}x{/b}") is None
    assert _validate_markup("x", "{i}{color=#fff}x{/color}{/i}") is None
    assert _validate_markup("x", "x{w}{nw}") is None
    assert _validate_markup("x", "{#context}x") is None


def test_known_text_tags_match_the_pinned_sdk():
    """Копия таблицы тегов обязана совпадать с SDK — иначе гейт врёт при апгрейде.

    Правильное место проверки — внутри движка, через build-bridge (у движка есть
    renpy.text.extras.check_text_tags, и она учитывает ещё custom_text_tags).
    Пока проверка живёт копией, расхождение с пиннованным SDK должно КРАСНЕТЬ, а
    не протекать молча: иначе новый тег Ren'Py начнёт браковаться как неизвестный,
    а удалённый — проходить."""
    import os
    import re
    from pathlib import Path

    from vn.loc.po import _KNOWN_TAGS

    sdk = os.environ.get("RENPY_SDK")
    if not sdk:
        pytest.skip("RENPY_SDK не задан — таблицу тегов сверять не с чем")
    src = (Path(sdk) / "renpy" / "text" / "extras.py").read_text(
        encoding="utf-8", errors="replace")
    body = src.split("text_tags = dict(", 1)[1].split(")", 1)[0]
    sdk_tags = set(re.findall(r"(\w+)=(?:True|False)", body))
    sdk_tags.add("")            # extras.py: text_tags[""] = True
    assert sdk_tags, "разбор таблицы тегов SDK выродился"
    assert set(_KNOWN_TAGS) == sdk_tags, (
        "копия таблицы тегов разошлась с SDK:\n"
        f"  нет у нас: {sorted(sdk_tags - set(_KNOWN_TAGS))}\n"
        f"  лишние у нас: {sorted(set(_KNOWN_TAGS) - sdk_tags)}")


def test_markup_validator_rejects_a_bracket_that_is_not_a_substitution():
    """Литеральной квадратной скобкой считается ТОЛЬКО эскейп `[[`.

    Раньше хватало «скобка закрыта»: _BRACKET_RE съедала любую [...], а набор
    подстановок собирал _INTERP_RE, требующий начала с латинской буквы. Поэтому
    `[1/3]`, `[1:2]`, `[смеётся]` не попадали ни в набор, ни в остаток — перевод
    признавался чистым. Движок же вычисляет содержимое как выражение Python
    (substitutions.py: py_eval при config.interpolate_exprs=True) и трактует `:`
    как format-spec: «Chapter 1 [1/3]» игрок видел как
    «Chapter 1 0.3333333333333333», а `[1/0]` в UI-строке не давало открыться ни
    главному меню, ни галерее, ни истории, ни загрузке."""
    from vn.loc.po import _validate_markup

    for bad in ("Chapter 1 [1/3]. Awakening", "Back [1:2]", "Gallery [1/0]",
                "Он [смеётся] и уходит"):
        err = _validate_markup("x", bad)
        assert err and "не подстановка" in err, f"{bad!r} прошло: {err}"

    # Легитимные формы обязаны проходить, иначе гейт покраснеет на живых PO.
    # msgid == msgstr: правило «набор подстановок совпадает с исходником» здесь
    # не проверяется, нас интересует только валидность самой скобки.
    for ok in ("Стоит [cost] монет", "Осталось [n!q]", "Цена [cost:>6.2f]",
               "Имя [obj.field]", "Слот [slots[0]]", "Литеральная [[скобка]",
               "Одинокая ] закрывающая"):
        assert _validate_markup(ok, ok) is None, ok


def test_dialogue_literal_uses_the_renpy_escape_table_for_tabs():
    """`_rpy_str` обслуживал ДВЕ грамматики, и эскейп таба был верен только для одной.

    Текст реплики читает лексер Ren'Py, у которого своя таблица эскейпов
    (renpy/lexer.py: dequote понимает фигурную и квадратную скобку, процент, `n` и
    `uXXXX`, а всё остальное отдаёт как есть). Ветки для `t` там нет, поэтому
    эскейп таба превращался в букву «t» посреди фразы: переводчик ставил в msgstr
    табуляцию (штатный эскейп PO, который принимают все gettext-инструменты), а
    игрок на этом языке видел лишний символ. Ошибка тихая — файл валиден, теги и
    скобки не при чём, никто не краснеет.

    Клаузы old/new у translate strings читает ПИТОН, там эскейп таба верен —
    поэтому формы разведены на две функции."""
    from vn.loc.po import _py_str, _rpy_str

    bs = chr(92)                      # без литеральных бэкслешей: их легко потерять
    out = _rpy_str("a" + chr(9) + "b")
    assert bs + "t" not in out, f"лексер этот эскейп не знает, он даст букву t: {out}"
    assert bs + "u0009" in out, out

    # Грамматика питона: эскейп таба на месте.
    assert bs + "t" in _py_str("a" + chr(9) + "b")

    # Остальные эскейпы совпадают в обеих грамматиках.
    for fn in (_rpy_str, _py_str):
        assert fn('a"b') == '"a' + bs + '"b"'
        assert fn("a" + chr(10) + "b") == '"a' + bs + 'nb"'
        assert fn("a" + bs + "b") == '"a' + bs + bs + 'b"'
