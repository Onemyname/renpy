"""Ссылки документации на код: адресуем СИМВОЛОМ, а не номером строки.

Класс поломок, ради которого файл существует (трекер: RTL-029). Ссылка вида
`video.py:200-249` верна ровно до первой вставки выше неё. Модуль вырос с 326 до
470 строк — и половина ссылок handbook 21/22 стала указывать в чужие функции,
причём в документации это выглядит так же убедительно, как раньше. Никакой
прогон vn такую ошибку не видит: код зелёный, врёт текст.

Лечение — не перенумерация (она отстанет снова), а адресация по имени:
`video.py: validate_output`. Такую ссылку можно ПРОВЕРИТЬ, чем и занят этот файл.

Два гейта:

* `test_symbol_references_resolve` — каждая ссылка `<файл>.py: <символ>` из
  docs/ обязана указывать на существующий модульный символ. Переименовали
  функцию — красный тест, а не тихо устаревшая дока.
* `test_cleaned_docs_have_no_line_references` — в вычищенных файлах номера строк
  не отрастают обратно. Список ЗАМОРОЖЕН и растёт по мере чистки: полная зачистка
  ~2000 ссылок во всех доках — отдельная работа, а откат уже сделанной — нет.
"""

import ast
import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT

DOCS = REPO_ROOT / "docs"

# Файлы, где номера строк уже вычищены и не должны появляться снова.
LINE_REF_FREE = (
    "handbook/21-video-generation.md",
    "handbook/22-rendering.md",
)

# `path/to/file.py: symbol` или `file.py: symbol` — второй вариант резолвится по
# имени файла среди модулей tools/vn (в доке так пишут короткую форму).
SYMBOL_REF_RE = re.compile(
    r"(?P<path>[A-Za-z_0-9/]*\b[a-z_0-9]+\.py):\s*(?P<symbol>[A-Za-z_][A-Za-z_0-9]*)")

# Числовая ссылка на .py: `video.py:200-249`, `pipeline.py:38-46,82-91`.
LINE_REF_RE = re.compile(r"[A-Za-z_0-9/]*\.py:[0-9][0-9,\-]*")

# Символы, которые в доке пишут как «файл.py: имя», но имя — не объект модуля:
# это подпись параметра или ключ, и проверять его нечем. Список закрытый,
# добавление в него — сознательное исключение, а не способ погасить красный тест.
NOT_A_SYMBOL = {
    ("video.py", "opts"),
}


def _md_files():
    return sorted(DOCS.rglob("*.md"))


def _module_symbols(path: Path) -> set[str]:
    """Модульные символы файла: функции, классы, константы, поля dataclass."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
            # Методы класса тоже адресуются в доке (`Класс.метод`), поэтому имена
            # методов кладём наравне: ссылка на метод не должна требовать точки.
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.add(sub.name)
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    out.add(sub.target.id)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


@pytest.fixture(scope="module")
def py_modules():
    """{имя файла: [пути]} по всему дереву инструментов."""
    index: dict[str, list[Path]] = {}
    for p in sorted((REPO_ROOT / "tools").rglob("*.py")):
        index.setdefault(p.name, []).append(p)
    return index


def test_symbol_references_resolve(py_modules):
    """Ссылка `файл.py: символ` обязана резолвиться.

    Неоднозначное имя файла (одинаковые basename в разных пакетах — `pipeline.py`
    лежит и в `assets/`, и в корне `vn/`) считается разрешённой, если символ есть
    ХОТЬ В ОДНОМ из них: дока пишет короткую форму осознанно, а требовать полный
    путь значило бы переписать половину ссылок ради теста.
    """
    broken = []
    for md in _md_files():
        text = md.read_text(encoding="utf-8")
        for m in SYMBOL_REF_RE.finditer(text):
            name = Path(m.group("path")).name
            symbol = m.group("symbol")
            if (name, symbol) in NOT_A_SYMBOL:
                continue
            candidates = py_modules.get(name)
            if not candidates:
                continue        # файл вне tools/ — не наша зона ответственности
            if not any(symbol in _module_symbols(p) for p in candidates):
                broken.append(f"{md.relative_to(DOCS)}: {name}: {symbol}")
    assert not broken, (
        "ссылки на несуществующие символы (переименовали код — поправьте доку):\n  "
        + "\n  ".join(broken))


@pytest.mark.parametrize("rel", LINE_REF_FREE)
def test_cleaned_docs_have_no_line_references(rel):
    """В вычищенных файлах номера строк не возвращаются.

    Правило простое: место в коде адресуется именем. Если имени нет (константа
    внутри функции, ветка условия), назовите объемлющую функцию — она есть всегда.
    """
    text = (DOCS / rel).read_text(encoding="utf-8")
    hits = sorted(set(LINE_REF_RE.findall(text)))
    assert not hits, (
        f"{rel}: вернулись ссылки на номера строк {hits} — они переживают ровно до "
        f"первой вставки выше (RTL-029). Адресуйте символом: `файл.py: имя`")


def test_the_guard_is_not_vacuous():
    """Гейт бессмыслен, если в вычищенных файлах не осталось ссылок вовсе."""
    total = 0
    for rel in LINE_REF_FREE:
        text = (DOCS / rel).read_text(encoding="utf-8")
        total += len(SYMBOL_REF_RE.findall(text))
    assert total > 50, f"символьных ссылок всего {total} — проверять почти нечего"


def test_audit_trackers_reference_real_files_and_tests(repo_root):
    """Поля implementation/tests у CLOSED — это и есть сеть «закрыто ⇔ проверяемо».

    Схема audit@1 требует их наличия, но резолвимость не проверяет никто, и в
    трекере уже жили две висячие ссылки на переименованные тесты. Ирония в том,
    что этот самый файл заведён ровно ради такой проверки — только для
    документации. Ссылка, которая никуда не ведёт, хуже отсутствующей: она
    создаёт видимость покрытия."""
    import re

    import yaml

    dangling = []
    for tracker in sorted((repo_root / "docs" / "audit").glob("*.audit.yaml")):
        doc = yaml.safe_load(tracker.read_text(encoding="utf-8"))
        where = tracker.relative_to(repo_root).as_posix()
        for item_id, item in (doc.get("items") or {}).items():
            for rel in item.get("implementation") or []:
                if not (repo_root / rel).exists():
                    dangling.append(f"{where}:{item_id} implementation -> {rel}")
            for ref in item.get("tests") or []:
                # Движковые гейты («vn test oversample», шаг ci.yml) — законная
                # форма записи: это не pytest, и файла у них нет. Проверяем
                # только то, что записано как путь к .py.
                if ".py" not in ref:
                    continue
                path, _, name = ref.partition("::")
                f = repo_root / path
                if not f.is_file():
                    dangling.append(f"{where}:{item_id} tests -> {path}")
                elif name and not re.search(rf"^\s*def {re.escape(name)}\b",
                                            f.read_text(encoding="utf-8"), re.M):
                    dangling.append(f"{where}:{item_id} tests -> {ref}")
    assert not dangling, "висячие ссылки в трекерах аудита:\n  " + "\n  ".join(dangling)
