"""Распаковка архивов с СОХРАНЕНИЕМ прав. Одно место на весь конвейер.

Почему отдельный модуль, а не хелпер внутри release.py: `zipfile` прав не
переносит ВООБЩЕ — CPython `ZipFile._extract_member` открывает цель обычным
`open(targetpath, "wb")` + `copyfileobj` и `external_attr` не читает, `chmod` не
зовёт. Значит каждый вызов `extractall` в проекте — это потенциальная потеря бита
исполняемости, и починка одного места ничего не говорит про остальные.

Так и вышло: FWA-003 закрыл mac-депот (`release._extract_archive`), а
`android.install_rapt` продолжал распаковывать тулчейн обычным `extractall` —
тот же дефект в другом месте и без гейта. На Windows он невидим полностью (бита x
там нет), а гейт, который единственный наблюдает x-бит, на машине владельца
скипается (`if os.name != "posix"`), так что второй экземпляр появился незаметно.

Штатный путь Ren'Py эту работу делает руками: лаунчер ставит RAPT своим
апдейтером, который несёт отдельный СПИСОК исполняемых файлов и восстанавливает
бит (SDK renpy/common/00updater.rpy: `if info.mode & 1: os.chmod(...)`).
"""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

# Файлы, которым бит x нужен по имени, даже если архив собран БЕЗ POSIX-атрибутов
# (например на Windows: тогда external_attr пуст и взять права неоткуда).
# Это ДОПОЛНЕНИЕ к чтению external_attr, а не замена: список отстанет, если
# апстрим переименует файл, поэтому основной механизм — атрибуты архива.
_EXECUTABLE_NAMES = ("gradlew", "renpy.sh", "adb", "aapt", "aapt2", "zipalign",
                     "apksigner", "java", "javac", "keytool")
_EXECUTABLE_SUFFIXES = (".sh",)


def _looks_executable(path: Path) -> bool:
    return path.name in _EXECUTABLE_NAMES or path.suffix in _EXECUTABLE_SUFFIXES


def extract_zip_preserving_modes(archive, dest: Path) -> list[Path]:
    """Распаковать zip в dest, восстановив права из `external_attr`.

    `archive` — путь или файловый объект (BytesIO для скачанного в память).
    Возвращает список распакованных файлов. Пути санирует сам `zf.extract`.
    """
    written: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = Path(zf.extract(info, dest))
            if info.is_dir():
                continue
            written.append(target)
            mode = (info.external_attr >> 16) & 0o777
            # mode == 0 у архивов без POSIX-атрибутов: выставлять нечего, и
            # придумывать права за архив нельзя.
            if mode:
                os.chmod(target, mode)
    if os.name == "posix":
        _ensure_executable_by_name(written)
    return written


def _ensure_executable_by_name(paths: list[Path]) -> None:
    """Дострахововка для архивов без POSIX-атрибутов: бит x по имени файла.

    Без неё установка тулчейна из архива, собранного на Windows, оставляла
    `rapt/prototype/gradlew` с режимом 0644, и следующий шаг сборки APK падал
    `Permission denied` посреди gradle — при том что диагностика (`rapt_status`)
    оставалась зелёной, потому что проверяет только НАЛИЧИЕ каталога и хеш.
    """
    for p in paths:
        if not _looks_executable(p):
            continue
        try:
            mode = p.stat().st_mode
            p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass                # права на чужой файл — не наша забота, не падаем
