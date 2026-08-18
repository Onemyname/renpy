"""Реестр JSON Schema (G16): tools/schemas/<name>@<int>.schema.json —
единственный источник версий схем. Каждый YAML/JSON-документ проекта обязан
нести поле schema: <name>@<int>."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

_FILENAME_RE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)@(?P<ver>\d+)\.schema\.json$")


class SchemaRegistry:
    def __init__(self, schemas_dir: Path):
        self.dir = Path(schemas_dir)
        self.schemas: dict[str, dict] = {}
        # Старшая зарегистрированная версия каждой схемы: по ней ловится документ,
        # оставшийся на предыдущей (см. validate).
        self.newest: dict[str, int] = {}
        # Валидатор на schema-id строится один раз: пересборка на каждый документ
        # заметна на больших сборках и в релизном гейте.
        self._validators: dict[str, jsonschema.Draft202012Validator] = {}
        for f in sorted(self.dir.glob("*.schema.json")):
            m = _FILENAME_RE.match(f.name)
            if not m:
                raise ValueError(f"имя файла схемы вне конвенции <name>@<int>.schema.json: {f.name}")
            sid = f"{m['name']}@{m['ver']}"
            schema = json.loads(f.read_text(encoding="utf-8"))
            const = schema.get("properties", {}).get("schema", {}).get("const")
            if const != sid:
                raise ValueError(f"{f.name}: const поля schema ({const!r}) != имени файла ({sid!r})")
            self.schemas[sid] = schema
            ver = int(m["ver"])
            if ver > self.newest.get(m["name"], 0):
                self.newest[m["name"]] = ver

    def validate(self, data, path: str = "<data>", *,
                 allow_older: bool = False) -> list[str]:
        """Валидация одного документа. Возвращает список ошибок (пустой = ок).

        `allow_older` снимает гейт устаревшей версии — он нужен там, где документ
        не авторский, а ИСТОРИЧЕСКИЙ: манифест внутри артефакта CI собран прошлой
        версией тулинга, и требовать от него сегодняшнюю схему бессмысленно. Для
        всего, что живёт в репозитории, гейт обязателен."""
        if not isinstance(data, dict) or "schema" not in data:
            return [f"{path}: отсутствует обязательное поле schema (правило G16)"]
        sid = data["schema"]
        schema = self.schemas.get(sid)
        if schema is None:
            known = ", ".join(sorted(self.schemas))
            return [f"{path}: неизвестная схема {sid!r}; зарегистрированы: {known}"]
        # Документ на УСТАРЕВШЕЙ версии — ошибка, а не мелочь. Реестр держит версии
        # рядом (@1 и @2 обе валидны сами по себе), поэтому забытый документ прошёл
        # бы валидацию молча, а код, написанный под @2, читал бы у него поля @1 —
        # тихо и не в свою пользу. Гейт превращает это в красную сборку, и он же
        # заменяет отдельную команду миграции: бамп схемы и перевод документов
        # обязаны приехать одним PR (G16).
        name, _, ver = sid.partition("@")
        newest = self.newest.get(name, 0)
        if not allow_older and ver.isdigit() and int(ver) < newest:
            return [f"{path}: документ на устаревшей схеме {sid}; актуальная — "
                    f"{name}@{newest}. Переведите документ (поле schema и структуру) "
                    f"в том же PR, что и бамп схемы: версии живут рядом, поэтому "
                    f"молча разойтись с кодом может только документ"]
        validator = self._validators.get(sid)
        if validator is None:
            validator = jsonschema.Draft202012Validator(schema)
            self._validators[sid] = validator
        errors = []
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            loc = "/".join(str(x) for x in err.absolute_path) or "<root>"
            errors.append(f"{path}: {loc}: {err.message}")
        return errors
