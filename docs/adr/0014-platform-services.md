# ADR-0014: Platform Services — Steam как одна из платформ, не фундамент

- **Статус**: принято
- **Дата**: 2026-08-18
- **Затрагивает нормы**: G9 (ownership-гейт получает провайдера), C13 (`vn release steam`
  легализована), дополняет раздел 6/7 ARCHITECTURE.md платформенным слоем

## Контекст

Игре нужны Steam, Steam Deck и Big Picture, а в будущем — другие витрины и
Android. Риск: интеграция врастает в игровой код (`if steam:` по экранам и
сценам), после чего каждая новая платформа = рефакторинг ядра. При этом ядро
уже имело правильные швы: `vn_ach.set_provider(fn)` и
`vn.pack_registry.set_ownership_provider(fn)` — но их никто не подключал, а
Steam-специфики не существовало вовсе.

Выбор способа интеграции Steamworks: (1) штатный стек Ren'Py
(`00steam.rpy` + ctypes-биндинг `steamapi`, поставляется движком), (2) внешние
Python-биндинги (SteamworksPy и т.п.), (3) собственная обёртка над C-API.
Штатный стек выигрывает по всем осям: сопровождается вместе с движком (наш
canary-CI его уже стережёт), покрывает ачивки/DLC/оверлей/Deck/Big Picture,
не добавляет зависимостей и лицензионных рисков. Внешние биндинги — чужой
цикл релизов и дублирование того, что движок делает сам.

## Решение

1. **Одна точка касания платформы** — `game/framework/00_core/035_platform.rpy`
   (store `vn_platform`). Игровой код зовёт фасады ядра (`vn_ach.grant`,
   `pack_registry.owned`) и capability-запросы (`is_steam_deck`,
   `is_big_picture`, `controller_first`); слово «Steam» за пределами этого
   файла в game/ запрещено ревью и **гард-тестом**
   (`test_platform::test_platform_facade_is_single_steam_touchpoint`).
2. **Конфигурация — данные**: `project.yaml: platform.steam.{appid, depots}`
   → генерат `platform.gen.rpy` (`define config.steam_appid`, карта
   `VN_STEAM_DLC`). `appid: null` = Steam выключен во всех сборках. App ID и
   номера депотов публичны; секретов Steamworks в репозитории не существует.
3. **Активация — наличием библиотеки**: steam_api (редистрибутив Valve, НЕ в
   git) кладётся в `$RENPY_SDK/lib/py3-*/` на build-машине; без неё тот же
   дистрибутив — standalone: движок молча пропускает инициализацию
   (контракт-тест `test_engine_compat::test_steam_engine_contract`).
4. **Ачивки**: `vn_ach` остаётся источником истины (persistent, триггеры по
   якорям); при живом Steam фасад регистрирует те же стабильные id в движковом
   achievement-модуле, ставит провайдер и догоняет офлайн-выдачи
   (`achievement.sync`). API Name в Steamworks = id из `achievements.yaml`.
5. **Владение паками**: провайдер G9 — `dlc_installed(steam_dlc_appid)` из
   манифеста пака (`pack_manifest@1`); пак без маппинга гейтится
   установленностью. Ошибка API — fail-open: гейт логический, не DRM.
6. **Deck/Big Picture — варианты движка** (`steam_deck`, `steam_big_picture`,
   вставляются при init): UI подстраивает типографику и safe-area токенами
   gui.*, полноэкранный дефолт — от `controller_first()`. Отдельной копии UI
   не существует.
7. **Сейвы**: локальная система самодостаточна (schema+миграции, G5);
   Steam Cloud — только Auto-Cloud синхронизация в Steamworks-настройках,
   кода в игре нет (`ci/steam/README.md`).
8. **Поставка**: `vn release steam --flavor <f>` генерирует VDF из
   `ci/steam/app_build.vdf.tmpl` и раскладывает депоты из артефактов distribute (zip и tar.bz2 — форматы различаются по платформам);
   аплоад — steamcmd с credentials вне репозитория.

## Последствия

- Новая платформа (Android, GOG, itch) = новый провайдер в 035_platform.rpy
  (или его аналог) + конфиг; ядро, контент и UI не трогаются. Отсутствующая
  возможность платформы — безопасный no-op по построению фасадов.
- Release-рантайм остаётся чистым для консольных/мобильных окружений: ноль
  сети, ноль subprocess, файловый ввод через loader (аудит 2026-08-18).
- Ограничение: маппинг «пак → DLC» живёт в манифесте пака, поэтому один пак —
  один DLC-appid; бандлы решаются на стороне Steamworks.
- План отступления: удалить 035_platform.rpy и platform-блок project.yaml —
  игра возвращается к чисто локальным ачивкам и установленность-гейту, ничего
  больше не меняется.
