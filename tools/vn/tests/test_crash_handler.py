"""Регрессия «мёртвый обработчик»: config.exception_handler — одно поле движка,
и побеждает последнее присваивание. Раньше их было два (001_boot.rpy на init -999
и 070_crash.rpy на init -950), боотовый молча затирался, а его строка
«unhandled exception» никогда не доезжала до log.txt. Тест статический: рантайм
Ren'Py в pytest недоступен, но пара «одно присваивание + оно в 070_crash.rpy»
проверяется по исходникам так же надёжно.

Вторая половина файла — инварианты САМОГО экрана краха (crash_screen.rpy): он
последний эшелон, и проверять его прогоном нельзя (для этого игра должна
упасть), поэтому контракт зафиксирован статически."""

import re

HANDLER_FILE = "070_crash.rpy"
SCREEN_FILE = "game/framework/20_ui/screens/crash_screen.rpy"

# Порог читаемости интерфейса на Deck/ТВ = нижний кегль «крупного» профиля
# (round(13 * 1.4), 20_ui/scale.rpy). Экран краха масштаб не читает (gui.* ему
# запрещён), поэтому его литералы обязаны быть не мельче порога сами.
MIN_TEXT_SIZE = 18


def _framework_rpy(repo_root):
    # game/generated — производная зона (её пишет сборка), обработчиков там быть не может
    return sorted((repo_root / "game" / "framework").rglob("*.rpy"))


def test_single_exception_handler_assignment(repo_root):
    """Второе присваивание = мёртвый код: чей-то обработчик перестанет вызываться."""
    hits = []
    for path in _framework_rpy(repo_root):
        for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*config\.exception_handler\s*=", line):
                hits.append("%s:%d" % (path.name, num))

    assert len(hits) == 1, (
        "config.exception_handler присваивается %d раз (%s) — выживет только "
        "последний по init-порядку, остальные мёртвы" % (len(hits), ", ".join(hits))
    )
    assert hits[0].startswith(HANDLER_FILE), (
        "обработчик краха должен жить в %s (breadcrumbs и запись отчёта — там же), "
        "а присваивание найдено в %s" % (HANDLER_FILE, hits[0])
    )


def test_crash_handler_logs_and_declines(repo_root):
    """Контракт обработчика: строка в log.txt + возврат False (экран рисует движок,
    подхватывая наш брендированный screen _exception)."""
    src = (repo_root / "game" / "framework" / "00_core" / HANDLER_FILE).read_text(
        encoding="utf-8"
    )
    body = src.split("def vn_crash_write_report", 1)[1]

    assert 'vn_log("unhandled exception:' in body, (
        "потеряна строка «[vn] unhandled exception: …» в log.txt — с неё начинается "
        "разбор падения (grep по log.txt), отчёта в savedir может не быть"
    )
    assert re.search(r"^\s+return False\b", body, re.M), (
        "обработчик обязан вернуть False (=не обработано): иначе движок не покажет "
        "screen _exception и игрок останется без экрана краха"
    )


def _screen_code(repo_root):
    """Код экрана краха без комментариев. Комментарии в этом файле — только
    целыми строками, поэтому разбор кавычек не нужен: рубить '#' по месту нельзя
    (цвета "#rrggbb" — литералы), а '#' первым непробельным символом однозначен."""
    src = (repo_root / SCREEN_FILE).read_text(encoding="utf-8")
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))


def _buttons(code):
    """Куски «textbutton … со своими свойствами»: от строки textbutton до первой
    строки с отступом не глубже его. Границу держит именно отступ — иначе в кусок
    попадёт соседний `if ignore_action:`, и по нему нельзя судить о кнопке."""
    lines = code.splitlines()
    blocks = []
    for num, line in enumerate(lines):
        if not line.lstrip().startswith("textbutton"):
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for tail in lines[num + 1:]:
            if tail.strip() and (len(tail) - len(tail.lstrip())) <= indent:
                break
            block.append(tail)
        blocks.append("\n".join(block))
    return blocks


def _focus_priority(button):
    match = re.search(r"\bdefault_focus\s+(\d+)", button)
    return int(match.group(1)) if match else 0


def test_crash_screen_first_focus_is_the_safe_action(repo_root):
    """Первый A с пада на экране краха уходит «в пустоту», если default focus не
    объявлен, и уносит сессию, если он на «выйти». Приоритет — число (движок
    берёт наибольший), лестница: откат > продолжить > выход/Reload."""
    buttons = _buttons(_screen_code(repo_root))
    assert buttons, "в экране краха не найдено ни одного textbutton"

    top = max(buttons, key=_focus_priority)
    assert _focus_priority(top) > 0, (
        "ни одна кнопка экрана краха не объявляет default_focus — с геймпада "
        "первое нажатие A не делает ничего, экран становится тупиком"
    )
    assert "rollback_action" in top, (
        "наибольший default_focus должен стоять на откате: это единственное "
        "действие, оставляющее игру в согласованном состоянии"
    )
    ignore = [b for b in buttons if "ignore_action" in b]
    assert ignore and 0 < _focus_priority(ignore[0]) < _focus_priority(top), (
        "«продолжить» обязано иметь НЕнулевой, но меньший приоритет: движок не "
        "всегда передаёт rollback_action, и тогда фокус должен достаться ему"
    )
    for button in buttons:
        if "Quit(" in button or "reload_action" in button:
            assert _focus_priority(button) == 0, (
                "выход и dev-only Reload не имеют права получать первый фокус: "
                "нажатие наугад теряло бы сессию"
            )


def test_crash_screen_traceback_scrolls_without_mouse(repo_root):
    """Трейсбек (dev-режим) длиннее вьюпорта всегда. Без arrowkeys/pagekeys
    viewport даже не фокусируемый — с dpad его не прокрутить ни на строку."""
    code = _screen_code(repo_root)
    parts = code.split("viewport:", 1)
    assert len(parts) == 2, "в экране краха потерялся viewport трейсбека"
    viewport = parts[1].split("hbox:", 1)[0]

    for prop in ("arrowkeys", "pagekeys"):
        assert re.search(r"^\s+%s\s+True\b" % prop, viewport, re.M), (
            "viewport трейсбека без %s: dpad/стрелки и LB/RB его не прокручивают"
            % prop
        )


def test_crash_screen_does_not_read_gui_tokens(repo_root):
    """Инвариант выживания: токены gui.* объявляются на init -3/-2, и падение
    любого более раннего init'а оставит их неполными — обращение к gui.* из
    последнего эшелона уронило бы сам экран краха. Литералы здесь легальны."""
    for num, line in enumerate(_screen_code(repo_root).splitlines(), 1):
        assert "gui." not in line, (
            "%s:%d читает gui.* — экран краха обязан быть самодостаточным "
            "(пояснения про токены выносите в комментарий целой строкой)"
            % (SCREEN_FILE, num)
        )


def test_crash_screen_text_is_readable_from_a_couch(repo_root):
    """Кегли экрана краха — литералы, и их некому масштабировать: gui.ui_scale
    ему запрещён. Значит нижняя граница проверяется здесь, иначе экран снова
    станет нечитаемым на Deck/ТВ (было 12-17px)."""
    sizes = [(int(m.group(1)), m.group(0))
             for m in re.finditer(r"\b(?:text_)?size\s+(\d+)",
                                  _screen_code(repo_root))]
    assert sizes, "в экране краха не найдено ни одного кегля"
    too_small = ["%s (%d)" % (raw, value) for value, raw in sizes
                 if value < MIN_TEXT_SIZE]
    assert not too_small, (
        "кегли меньше %d px: %s — порог читаемости интерфейса на Deck/ТВ"
        % (MIN_TEXT_SIZE, ", ".join(too_small))
    )
