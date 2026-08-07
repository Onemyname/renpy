# Онбординг: tools-инженер

Карта внутренностей тулинга (G20: этот документ — обязательный артефакт фазы 1; сейчас — фаза 0).

## Что где лежит

| Модуль | Назначение |
|---|---|
| `tools/vn/src/vn/cli.py` | Единая точка входа; заглушки честно называют фазу |
| `tools/vn/src/vn/repo.py` | Поиск корня, project.yaml, git sha |
| `tools/vn/src/vn/schemas.py` | Реестр JSON Schema (G16): `<name>@<int>.schema.json`, const == имени файла |
| `tools/vn/src/vn/content/lint.py` | Схемы, naming, структура глав, exits, id_registry, layout |
| `tools/vn/src/vn/content/compile.py` | Генерат фазы 0 + манифест, инкрементальность, точечная очистка (G6) |
| `tools/vn/src/vn/doctor.py` | Самодиагностика окружения |
| `tools/vn/src/vn/pipeline.py` | Окружение production-конвейера (ADR-0006): doctor, манифест моделей |
| `tools/vn/src/vn/assets/video.py` | Видео-трек: VP9-энкод, loop-валидация, mov_meta, movie_tree |
| `tools/vn/src/vn/assets/provenance.py` | Цепочки происхождения: extract ComfyUI, record/verify |
| `tools/vn/src/vn/assets/daz.py` | Декларации DAZ-рендеров (daz_render@1) |
| `tools/vn/src/vn/release.py` | Changelog, бюджеты G19, флейворы/build-info, релизный гейт |
| `tools/vn/tests/` | pytest; test_compile — регрессионная сетка идемпотентности/очистки |

## Незыблемые контракты (не ломать молча)

- Разбор `scene.rpy` в фазе 1 — ТОЛЬКО парсером Ren'Py из пиннованного SDK; регексы запрещены (G24).
- Архитектура компилятора: frontend (парсинг+валидация) / IR / backends; новая функциональность —
  только как плагин стадии.
- Неизменённые файлы генерата не перезаписываются байтово; очистка — по диффу манифестов;
  `.rpyc` — релизный артефакт (G6).
- Недокументированные API Ren'Py — только в `game/framework/00_core/engine_compat/`
  с контракт-тестом на каждое допущение (G18).
- На `/tools/` — минимум два владельца (CODEOWNERS); бамп зависимостей — через `tools/vn.lock`
  отдельным PR.
