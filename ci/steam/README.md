# Steam-поставка (ADR-0014)

Steam — одна из платформ распространения, не фундамент: тот же дистрибутив,
собранный `vn release build`, становится Steam-сборкой только за счёт
steam_api-библиотеки рядом с исполняемым файлом. Без неё (или при
`platform.steam.appid: null` в project.yaml) игра — обычный standalone.

## Что где живёт

| Артефакт | Место | В git? |
|---|---|---|
| App ID, номера депотов | `project.yaml: platform.steam` | да (публичные) |
| VDF для steamcmd | генерируются: `vn release steam --flavor <f>` → `build/steam/` | нет (генерат) |
| steam_api редистрибутивы Valve | `$RENPY_SDK/lib/py3-<platform>/` (кладутся один раз на build-машину из Steamworks SDK: `redistributable_bin/`) | **нет — лицензия Valve** |
| Логин/credentials steamcmd | CI-секреты / интерактивный вход | **никогда** |

## Процесс релиза

```bash
# 1. Обычная сборка (гейт vn release validate внутри):
vn release build --flavor public --package win --package linux --package mac

# 2. Генерация VDF + распаковка контента под депоты + префлайт:
vn release steam --flavor public [--branch beta]

# 3. Аплоад (credentials вне репозитория):
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit
```

`--branch beta` выставляет `setlive beta`: выкладка уходит в бета-ветку,
release-ветку переключают руками в Steamworks после проверки (в т.ч. на
Steam Deck — обязательный прогон перед setlive default).

## Steam Cloud

Синхронизация сейвов — Auto-Cloud в настройках Steamworks (кода в игре нет):
корень — каталог сохранений Ren'Py (`%LOCALAPPDATA%/RenPy/<save_directory>` /
`~/.renpy/<save_directory>`), маска `*.save` + `persistent`. Cloud — только
синхронизация: локальная система сейвов самодостаточна, конфликты разруливает
Steam-клиент, несовместимость версий ловит save_schema + миграции (G5).

## Ачивки

API Name каждой ачивки в Steamworks обязан ПОБУКВЕННО совпадать с id из
`content/achievements/*.yaml`: рантайм регистрирует те же id
(`framework/00_core/035_platform.rpy`), маппингов нет намеренно.
