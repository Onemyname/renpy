"""Локализация (G8): PO round-trip, tl-генерация, fuzzy при смене исходника, pseudo."""

import json

import polib

from vn.loc.po import extract, import_translations, pseudo, report


def _mk_loc_root(tmp_path):
    root = tmp_path / "repo"
    (root / "loc" / "ledger").mkdir(parents=True)
    (root / "content" / "ui").mkdir(parents=True)
    (root / "content" / "characters" / "mira").mkdir(parents=True)
    (root / "loc" / "loc.yaml").write_text(
        "schema: loc@1\nsource_lang: ru\nlanguages: [en]\n", encoding="utf-8"
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
    po = polib.pofile(str(root / "loc" / "po" / "pseudo" / "ch01.po"))
    e = {x.msgctxt: x for x in po}["ch01_s010_0001"]
    assert e.msgstr.startswith("[") and e.msgstr.endswith("]")
    assert len(e.msgstr) > len(e.msgid)          # удлинение для QA переполнений
    import_translations(root)                     # pseudo не в languages -> не поставляется
    pseudo_cov = report(root).coverage["pseudo"]
    assert pseudo_cov["translated"] == pseudo_cov["total"]


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


def test_pseudo_delivered_to_game_tl(tmp_path):
    """Псевдолокализация обязана доезжать до game/tl (иначе QA-прогон ложно-зелёный)."""
    root = _mk_loc_root(tmp_path)
    pseudo(root)
    import_translations(root)
    assert (root / "game" / "tl" / "pseudo" / "dialogue_ch01.rpy").is_file()


def test_pseudo_preserves_interpolations(tmp_path):
    from vn.loc.po import _pseudoize

    assert "[name]" in _pseudoize("Привет, [name]! {b}Да{/b}")
    assert "{b}" in _pseudoize("Привет, [name]! {b}Да{/b}")
