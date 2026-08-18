"""Комплект приёмки для живого устройства (vn test deck-kit).

Главное свойство под тестом: чек-лист СТРОИТСЯ из docs/handbook/43-steam-qa.md,
а не хранит копию. Копия разъехалась бы с документом на первой правке приёмки,
и человек с Deck в руках проверял бы прошлогодний список."""

from __future__ import annotations

from vn.deckkit import (
    DECK_PHYSICAL,
    LEVELS,
    ChecklistItem,
    deck_scale,
    font_sizes,
    parse_checklist,
    render_checklist,
    write_kit,
)


def test_checklist_follows_the_document(repo_root):
    """Пункты берутся из документа: добавили раздел — он появился в комплекте."""
    items = parse_checklist(repo_root / "docs" / "handbook" / "43-steam-qa.md")
    assert items, "чек-лист пуст — парсер разошёлся с форматом документа"
    levels = {i.level for i in items}
    assert levels <= set(LEVELS)
    # Все три уровня приёмки в документе описаны разными способами (подразделы
    # и таблица), и комплект обязан видеть каждый.
    assert levels == set(LEVELS), f"уровни потеряны: {sorted(set(LEVELS) - levels)}"
    assert any(i.number.startswith("1.") for i in items)


def test_checklist_stops_at_next_section(tmp_path):
    """Уровень заканчивается следующим «## », а не концом файла: иначе соседние
    таблицы документа (что автоматизировано, BLOCKED) попадали бы в приёмку."""
    doc = tmp_path / "qa.md"
    doc.write_text(
        "# QA\n\n## 1. MUST PASS\n\n### 1.1 Запуск\ntext\n\n"
        "## 2. SHOULD PASS\n\n### 2.1 Оверлей\ntext\n\n"
        "## 3. NICE TO HAVE\n\n| Пункт | Как | Статус |\n|---|---|---|\n"
        "| **Таймлайн** | смотреть | нет |\n\n"
        "## 4. Что автоматизировано\n\n| Проверка | Команда |\n|---|---|\n"
        "| Тесты | pytest |\n", encoding="utf-8")
    items = parse_checklist(doc)
    titles = [i.title for i in items]
    assert titles == ["Запуск", "Оверлей", "Таймлайн"], titles
    assert not any("Тесты" in t for t in titles), "раздел за уровнями попал в приёмку"


def test_deck_scale_matches_letterbox_geometry():
    """Виртуальная сетка вписывается в окно Deck с сохранением пропорций —
    отсюда и мягкость текста, и полосы сверху/снизу (ADR-0015)."""
    scale = deck_scale((1920, 1080))
    assert round(scale, 4) == round(DECK_PHYSICAL[0] / 1920, 4)      # ширина упирается первой
    letterbox = (DECK_PHYSICAL[1] - 1080 * scale) / 2
    assert round(letterbox) == 40


def test_font_sizes_read_both_declaration_forms(tmp_path):
    """Кегли объявлены двумя формами: голое число (диалоги) и round(N*ui_scale)
    (интерфейс, крупнее в controller-first). Комплект обязан видеть обе."""
    gui = tmp_path / "gui.rpy"
    gui.write_text(
        "define gui.text_size           = 34\n"
        "define gui.interface_text_size = round(21 * gui.ui_scale)\n",
        encoding="utf-8")
    sizes = font_sizes(gui, ui_scale=1.4)
    assert sizes["text_size"] == {"virtual": 34, "scales_on_deck": False}
    assert sizes["interface_text_size"] == {"virtual": 29, "scales_on_deck": True}


def test_automated_facts_are_separate_from_device_checks(tmp_path):
    """Закрытое машиной идёт отдельным блоком с фактом прогона, а пункты
    устройства остаются пустыми: ложная галочка в приёмке дороже неудобства."""
    items = [ChecklistItem(level="MUST PASS", number="1.1", title="Запуск из Steam")]
    summary = {"version": "0.1.5", "git_sha": "abc1234", "save_schema": 2}
    text = render_checklist(items, summary, automated=[("релизный гейт", "OK")])
    assert "- [x] релизный гейт — OK" in text
    assert "- [ ] 1.1 Запуск из Steam" in text


def test_write_kit_is_idempotent(tmp_path):
    """Перезапуск перезаписывает комплект, а не копит мусор рядом."""
    root = tmp_path
    shot = tmp_path / "shot000.png"
    shot.write_bytes(b"png")
    items = [ChecklistItem(level="MUST PASS", number="1.1", title="Запуск")]
    summary = {"version": "0.1.5", "git_sha": "abc", "save_schema": 2}
    for _ in range(2):
        written = write_kit(root, items, summary, {"deck": [shot]})
    kit = root / "build" / "deck-kit"
    assert (kit / "summary.json").is_file() and (kit / "checklist.md").is_file()
    assert (kit / "screens" / "deck" / "shot000.png").is_file()
    assert sorted(written) == ["checklist.md", "screens/deck/shot000.png", "summary.json"]
    assert len(list((kit / "screens" / "deck").iterdir())) == 1
