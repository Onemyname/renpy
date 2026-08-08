"""Регрессия «мёртвый обработчик»: config.exception_handler — одно поле движка,
и побеждает последнее присваивание. Раньше их было два (001_boot.rpy на init -999
и 070_crash.rpy на init -950), боотовый молча затирался, а его строка
«unhandled exception» никогда не доезжала до log.txt. Тест статический: рантайм
Ren'Py в pytest недоступен, но пара «одно присваивание + оно в 070_crash.rpy»
проверяется по исходникам так же надёжно."""

import re

HANDLER_FILE = "070_crash.rpy"


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
