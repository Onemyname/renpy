"""Правила цепочки миграций сейвов (G5) — одно место для компилятора и линтера.

Компилятор роняет сборку на дыре в цепочке, но линтер об этих правилах не знал:
`vn content lint` (то есть и pre-push hook) оставался зелёным, а падало на
`vn build`. Инвариант «lint зелёный => build не падает» (см. шапку REQUIRED_FILES
в lint.py) держится только если правило физически одно, а не переписано дважды.

Рантайм полагается на тот же инвариант: `vn_state.run_migrations` обрывает цепочку
на первой дыре (миграция N ждёт состояние после N−1), поэтому дыра, дошедшая до
игры, означала бы «сейв не мигрирован» — ловить её обязана сборка.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..repo import load_yaml

# Номер = целевая save_schema, фиксированная ширина: сортировка по имени совпадает
# с сортировкой по номеру (грабля FreshWomen с `int(unlock_str[2:3])` — раздел 8
# конкурентного аудита).
MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([a-z][a-z0-9_]+)\.py$")


def collect(mig_dir: Path, save_schema: int,
            rel) -> tuple[list[tuple[int, Path]], list[str]]:
    """Найденные миграции (номер, путь) по возрастанию + ошибки цепочки.

    `rel(path) -> str` даёт путь для сообщений; компилятор попутно регистрирует
    файл как вход сборки, поэтому колбэк зовётся ровно для тех файлов, чьё имя
    прошло конвенцию.
    """
    errors: list[str] = []
    reserved: dict[int, str] = {}          # номер -> slug из брони
    reg_path = mig_dir / "registry.yaml"
    if reg_path.is_file():
        # Читаем ЗАЩИТНО: этот же документ проверяет схема migrations_registry@1,
        # и её ошибку читатель уже получил. Свалиться здесь трейсбеком значило бы
        # спрятать внятное сообщение за стеком (линтер обязан доложить, а не упасть).
        try:
            rows = load_yaml(reg_path).get("reserved") or []
        except Exception as e:
            errors.append(f"content/migrations/registry.yaml: не парсится: {e}")
            rows = []
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and isinstance(r.get("number"), int):
                reserved[r["number"]] = str(r.get("slug") or "")

    found: list[tuple[int, Path]] = []
    for f in sorted(mig_dir.glob("*.py")) if mig_dir.is_dir() else []:
        m = MIGRATION_FILE_RE.match(f.name)
        if not m:
            errors.append(f"content/migrations/{f.name}: имя вне конвенции NNNN_slug.py")
            continue
        number = int(m.group(1))
        path_for_msg = rel(f)
        if number not in reserved:
            errors.append(
                f"{path_for_msg}: номер {number} не зарезервирован в "
                f"content/migrations/registry.yaml "
                f"(параллельные ветки получат конфликт номеров, G5)"
            )
        elif reserved[number] and reserved[number] != m.group(2):
            # Иначе бронь превращается в формальность: номер занят, а под ним в
            # реестре записана другая миграция — при разборе истории сейвов по
            # реестру это уводит по ложному следу.
            errors.append(
                f"{path_for_msg}: slug не совпадает с бронью номера {number} "
                f"(в registry.yaml — {reserved[number]!r})"
            )
        found.append((number, f))

    found.sort(key=lambda row: row[0])
    numbers = [n for n, _f in found]
    expected = list(range(2, save_schema + 1))
    if numbers != expected:
        errors.append(
            f"content/migrations: цепочка {numbers} != ожидаемой {expected} "
            f"(номер миграции = целевая save_schema; дыры и лишние номера запрещены)"
        )
    return found, errors
