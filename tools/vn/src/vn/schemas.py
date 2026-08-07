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

    def validate(self, data, path: str = "<data>") -> list[str]:
        """Валидация одного документа. Возвращает список ошибок (пустой = ок)."""
        if not isinstance(data, dict) or "schema" not in data:
            return [f"{path}: отсутствует обязательное поле schema (правило G16)"]
        sid = data["schema"]
        schema = self.schemas.get(sid)
        if schema is None:
            known = ", ".join(sorted(self.schemas))
            return [f"{path}: неизвестная схема {sid!r}; зарегистрированы: {known}"]
        validator = jsonschema.Draft202012Validator(schema)
        errors = []
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            loc = "/".join(str(x) for x in err.absolute_path) or "<root>"
            errors.append(f"{path}: {loc}: {err.message}")
        return errors
