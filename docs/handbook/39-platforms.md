# 39. Платформы: Steam, Steam Deck, Big Picture

> **Статус подсистемы:** IMPLEMENTED — платформенный слой замкнут одним файлом-фасадом ([ADR-0014](../adr/0014-platform-services.md)): Steam-ачивки, DLC-владение, controller-first UI и генерация Steam-депотов работают; **но** сам аплоад — ручной `steamcmd` (credentials вне репозитория), `platform.steam.appid` в `project.yaml` сейчас `null` (то есть все локальные сборки — standalone), а Android — NOT IMPLEMENTED.
> **Отвечает на вопрос:** «Как игра узнаёт, что она запущена в Steam / на Deck / в Big Picture, что для этого надо положить на build-машину — и как добавить следующую платформу, не переписывая UI и контент».

Платформа в этом проекте — **не фундамент, а провайдер**. Ядро (`vn_ach`, `vn.pack_registry`) самодостаточно и работает без всякой платформы; `game/framework/00_core/035_platform.rpy` — единственное место, которое знает слово «Steam», и единственное, что меняется при добавлении витрины. Steam-специфика идёт через **штатный стек движка** (`00steam.rpy` + `00achievement.rpy` из `renpy/common/`): сторонних биндингов (SteamworksPy и т. п.) в проекте нет и по ADR-0014 быть не должно.

---

## Быстрый ответ

```bash
# 1. Включить Steam (данные, не код): App ID + номера депотов
#    project.yaml: platform.steam.appid: 480, platform.steam.depots: {windows: 481, ...}
vn build                                  # -> game/generated/platform.gen.rpy (define config.steam_appid)

# 2. Один раз на build-машину: steam_api-редистрибутивы Valve
#    лаунчер Ren'Py -> preferences -> Install libraries -> Install Steam Support
#    (кладёт steam_api64.dll / libsteam_api.so / libsteam_api.dylib в $RENPY_SDK/lib/py3-*/)

# 3. Собрать и разложить под депоты
vn release build --flavor public --package win --package linux --package mac
vn release steam --flavor public [--branch beta]   # -> build/steam/app_build_public.vdf + content/

# 4. Аплоад — вне репозитория
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit

# Проверка controller-first вёрстки без Deck:
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
```

Проверено на репозитории 2026-08-18: `platform.steam.appid: null` (`../../project.yaml:15`), поэтому `platform.gen.rpy` эмитит `define config.steam_appid = None`, движок молча не трогает Steam, а `vn release steam` честно падает: `platform.steam.appid не задан в project.yaml`. **Это рабочее состояние, а не поломка** — игра полноценна как standalone.

---

## 1. Архитектура: три этажа и одна точка касания

```
Game Core (контент, генерат сцен, экраны)
        │  зовёт ТОЛЬКО фасады ядра и capability-запросы
        ▼
Фасады ядра                       Capability-запросы
  vn_ach.grant / has / all_ids      vn_platform.is_steam_deck()
  vn.pack_registry.owned()          vn_platform.is_big_picture()
  gui.* (ui_scale, overscan_pad)    vn_platform.controller_first()
        ▲                                   ▲
        │  set_provider / set_ownership_provider
        ▼                                   │
game/framework/00_core/035_platform.rpy  ◄───┘   ← ЕДИНСТВЕННАЯ точка касания
        ▼
Штатный стек движка: renpy/common/00steam.rpy + 00achievement.rpy
        ▼
steam_api (редистрибутив Valve, НЕ в git) — есть? Steam. Нет? standalone.
```

| Шов | Где объявлен | Кто подключает | Статус |
|---|---|---|---|
| `vn_ach.set_provider(fn)` | `../../game/framework/00_core/080_achievements.rpy:17-21` | `035_platform.rpy:82` (только при живом Steam) | IMPLEMENTED |
| `vn.pack_registry.set_ownership_provider(fn)` | `../../game/framework/00_core/030_flow.rpy:73-74` | `035_platform.rpy:75` | IMPLEMENTED |
| `vn_platform.*` capability-запросы | `../../game/framework/00_core/035_platform.rpy:19-53` | UI и `options.rpy` читают напрямую | IMPLEMENTED |
| `config.steam_appid`, `VN_STEAM_DLC` | генерат `game/generated/platform.gen.rpy` (`../../tools/vn/src/vn/content/compile.py:133-152`) | `vn build` | IMPLEMENTED |

### 1.1 Правило «слово Steam живёт только в одном файле» — под гард-тестом

Ни один экран, ни одна сцена, ни один другой модуль ядра не имеют права обращаться к `_renpysteam` / `steamapi`. Проверка не на честном слове ревьюера, а тестом (`../../tools/vn/tests/test_platform.py:107-117`):

```python
def test_platform_facade_is_single_steam_touchpoint(repo_root):
    for f in (repo_root / "game").rglob("*.rpy"):
        if "_renpysteam" in text or "steamapi" in text:
            if f.name != "035_platform.rpy":
                offenders.append(...)
    assert offenders == []
```

Практическое следствие: **запрос «покажи бейдж только в Steam-версии» решается не через `if steam:` в экране**, а через новый capability-метод в фасаде. Легальный способ узнать про Steam ровно один — `vn_platform.steam()` (`035_platform.rpy:19-23`), и он возвращает `achievement.steam` (то есть `_renpysteam` или `None`), а не импортирует модуль сам.

### 1.2 Полный состав фасада `vn_platform`

Store `vn_platform`, `init -960` (`035_platform.rpy:16`).

| Функция | Что возвращает | Потребители в `game/` |
|---|---|---|
| `steam()` | `achievement.steam` или `None` | только внутри фасада (`:27`, `:66`) |
| `backend()` | `"steam"` \| `"standalone"` — идентичность платформы для логов | `describe()` |
| `is_steam_deck()` | `renpy.variant("steam_deck")` | `controller_first()`, косвенно `scale.rpy` |
| `is_big_picture()` | `renpy.variant("steam_big_picture")` | `../../game/framework/20_ui/scale.rpy:42` (`gui.overscan_pad`) |
| `has_touch()` | `renpy.variant("touch")` | `describe()` |
| `controller_first()` | `is_steam_deck() or is_big_picture()` | `scale.rpy:32`, `../../game/options.rpy:16` |
| `overlay_enabled()` | Steam-оверлей активен (в `try/except`, ошибка = `False`) | **никто** — задел (например «не показывать свой тост, когда открыт оверлей») |
| `describe()` | одна строка `backend deck=… bigpicture=… touch=…` | `035_platform.rpy:89` — уходит в `log.txt` при старте под Steam |
| `_steam_owns_pack(pack_id)` | ownership-провайдер G9 (см. §5) | ставится в `:75` |

**Честная оговорка:** `describe()`/`backend()` пишутся в `log.txt` одной строкой на старте (`vn_log("platform: …")`), но в crash-отчёт `070_crash.rpy` **не попадают** — докстринг фасада («для логов/крэш-репортов») обещает больше, чем сегодня подключено. Это однострочное расширение, а не долг архитектуры.

### 1.3 Порядок инициализации

| Приоритет | Что происходит | Почему именно так |
|---|---|---|
| define-пасс | `define config.steam_appid = <appid>` из `platform.gen.rpy` | движок читает appid на `init -1499`, то есть **раньше любого пользовательского init**; поэтому appid обязан задаваться `define`-стейтментом, а не присваиванием в `init python` (`compile.py:136-140`) |
| `init -1499` (движок) | `steam_init()`: если рядом с исполняемым нет steam_api — **тихий no-op**; иначе вставляются варианты `steam_deck` / `steam_big_picture`, включается экранная клавиатура Deck для `input()`, регистрируется `SteamBackend` ачивок | без библиотеки standalone-сборка не должна ломаться |
| `init -960` | создаётся store `vn_platform` | до UI-токенов (`init -4`), которые его читают |
| `init -4 / -3` | `gui.vn_ui_scale()` и `define gui.ui_scale` / `gui.overscan_pad` | до `gui.rpy` (`init offset = -2`), который умножает кегли |
| `init 999` | подключение провайдеров: ownership, регистрация ачивок, `set_provider`, догон офлайн-выдач, `achievement.sync()` | реестры (`VN_ACHIEVEMENTS`, `VN_STEAM_DLC`) уже загружены, Steam уже инициализирован |

Уровень 999 — это ровно «DLC-слот» из нормы C8; до ADR-0014 он был занят только пересборкой реестра языков.

Допущения о штатном стеке движка не висят в воздухе: их стережёт контракт-тест `test_engine_compat::test_steam_engine_contract` (`../../tools/vn/tests/test_engine_compat.py:63-88`) — он читает `$RENPY_SDK/renpy/common/00steam.rpy` и падает, если исчезли тихий no-op без библиотеки, вставка вариантов `steam_deck`/`steam_big_picture`, регистрация `SteamBackend`, `dlc_installed` или `steam_init()` на `init -1499`. Без `RENPY_SDK` тест **skip** (его гоняет canary-джоба CI на свежем движке).

---

## 2. Поддерживаемые платформы и их статус

| Платформа | Статус | Что именно работает / чего нет |
|---|---|---|
| **Windows / Linux / macOS standalone** | **IMPLEMENTED** | Основной режим. `vn release build --package win\|linux\|mac` → зипы через launcher distribute. Steam не требуется ни для чего: ачивки локальные (`persistent.vn_achievements`), владение паками = установленность |
| **Steam** | **IMPLEMENTED** | Штатный стек движка; ачивки синхронизируются, DLC-владение проверяется, оверлей работает движком. Поставка: `vn release steam` генерирует VDF и раскладывает депоты; **аплоад ручной** (`steamcmd`) |
| **Steam Deck** | **IMPLEMENTED** | Вариант `steam_deck` вставляет движок; `controller_first()` → фуллскрин по умолчанию + авто-масштаб интерфейса 1.4; вёрстка одна и та же (копии экранов под Deck не существует) |
| **Big Picture** | **IMPLEMENTED** | Вариант `steam_big_picture`; плюс `gui.overscan_pad = 48` — прижатые к кромке оверлеи (quick menu, контролы просмотрщика, вотермарка) уезжают из зоны overscan ТВ |
| **Android / APK / AAB** | **NOT IMPLEMENTED** | Ни сборки, ни конфига, ни провайдера, ни CI-джобы. См. §2.1 |
| **GOG, itch.io, Epic** | **NOT IMPLEMENTED** | Достаточно standalone-зипов (загрузчиком витрины руками). Ownership-API у GOG/itch нет — по ADR-0014 владение там = наличие пака, то есть текущее поведение без провайдера уже корректно |
| **Консоли** | **NOT IMPLEMENTED / вне горизонта** | Ren'Py консольных портов не даёт |

### 2.1 Android: что уже готово, а что потребуется

Полезно знать заранее, потому что часть работы **уже сделана побочно** — release-рантайм чист для мобильных и консольных окружений (аудит 2026-08-18, зафиксирован в «Последствиях» ADR-0014):

| Уже готово | Где |
|---|---|
| Ноль сети в рантайме: ни `urllib`, ни `socket`, ни HTTP-клиентов в `game/` | grep по `game/framework/` |
| Ноль `subprocess` в релизной части (dev-инструменты `90_debug/` исключаются `build.classify`) | `../../game/options.rpy:31` |
| Файловый ввод только через `renpy.loader` — никаких абсолютных путей ФС | конвенция ядра |
| UI не требует мыши: dpad-навигация, фокус по умолчанию в модалках, скролл-пресет | §7 |
| Масштаб интерфейса — токен, а не вёрстка (мобильный экран = тот же рычаг, что Deck) | §8 |
| Вариант `touch` уже опрашивается фасадом (`has_touch()`) | `035_platform.rpy:36-37` |

| Потребуется | Почему это работа, а не флаг |
|---|---|
| RAPT/SDK Android + подпись, канал сборки | у `vn package`/`vn release build` нет `--package android`; в `cli.py` ветки нет вовсе |
| Размер-бюджеты по каналам (AAB / universal APK < 2 ГБ) | `ARCHITECTURE.md:1189` требует реальную сборку `.aab` и сравнение с лимитами Play Asset Delivery — джобы нет |
| Провайдер владения для Google Play Billing | в `035_platform.rpy` нужна вторая ветка `init 999` (см. §9) |
| Тач-жесты и hit-area | «≥ 48 px» соблюдается только у quick menu (`quick_menu.rpy:4,49`), сплошного аудита не было |
| Тематические `.rpa` под каналы без пофайловых дельта-патчей | норма `ARCHITECTURE.md` §2.4: desktop едет россыпью ради Steam-дельта-патчей; mobile-`.rpa` — опция фазы 3, **только через ADR** |

---

## 3. Как включается Steam

Steam включается **двумя независимыми вещами**, и обе обязательны:

1. **Данные в репозитории** — `platform.steam.appid` в `../../project.yaml:13-15`. `null` = Steam выключен во всех сборках (движок сам удалит `steam_appid.txt`, чтобы игра не подцепила чужой App ID).
2. **Библиотека на build-машине** — редистрибутив Valve `steam_api`, которого в git нет и не будет.

Отсюда главное свойство поставки: **тот же самый дистрибутив** без библиотеки — обычный standalone. Отдельной «Steam-сборки» в конвейере не существует.

| Артефакт | Где живёт | В git? |
|---|---|---|
| App ID, номера депотов | `project.yaml: platform.steam` (схема — `../../tools/schemas/project@1.schema.json:11-33`) | **да** — публичные, не секреты |
| `pack_id → DLC App ID` | `packs/<id>/manifest.yaml: steam_dlc_appid` (`../../tools/schemas/pack_manifest@1.schema.json:32-35`) | да |
| `define config.steam_appid`, `VN_STEAM_DLC` | генерат `game/generated/platform.gen.rpy` | нет (генерат) |
| `steam_api64.dll` / `libsteam_api.so` / `libsteam_api.dylib` | `$RENPY_SDK/lib/py3-{windows-x86_64,linux-x86_64,mac-universal}/` | **нет — лицензия Valve** |
| VDF для `steamcmd` | `build/steam/app_build_<flavor>.vdf` (генерат `vn release steam`) | нет |
| Логин/Steam Guard `steamcmd` | CI-секреты или интерактивный вход | **никогда** |

### 3.1 Как положить steam_api

Steam-поддержка Ren'Py **не входит в SDK** и ставится лаунчером: `preferences` → `Install libraries` → `Install Steam Support`. Скачивание гейтится приёмом в Steam partner program, Ren'Py 8.5 требует Steamworks SDK 1.62 — это нельзя «добавить в последний момент». Файлы можно и разложить руками из `redistributable_bin/` Steamworks SDK по тем же трём каталогам.

Проверка наличия — в самой команде поставки (`../../tools/vn/src/vn/release.py:238-252`): чего не хватает, печатается **предупреждением**, а не ошибкой:

```
warning: в SDK нет py3-mac-universal/libsteam_api.dylib — дистрибутив будет
standalone, не Steam-сборкой (ci/steam/README.md)
```

### 3.2 Что эмитит компилятор

`_emit_platform` (`../../tools/vn/src/vn/content/compile.py:133-152`, регистрация выхода — `:1136`) кладёт в `game/generated/platform.gen.rpy` ровно два `define`:

```renpy
define config.steam_appid = None            # или число из project.yaml
define VN_STEAM_DLC = {}                    # или {'ep_beach': 481, ...}
```

Паки без `steam_dlc_appid` в карту **не попадают** — это тестируется (`test_platform.py:31-36`).

### 3.3 `vn release steam` — что делает и чего не делает

`../../tools/vn/src/vn/cli.py:1819-1852` + `release.py:151-252`. Пять шагов, все локальные:

| Шаг | Функция | Поведение при проблеме |
|---|---|---|
| Прочитать `platform.steam` | `steam_config` (`release.py:158-165`) | нет `appid` → **exit 1** с указанием, что заполнить |
| Отрендерить VDF из `ci/steam/app_build.vdf.tmpl` | `steam_app_build` (`:168-206`) | пустые `depots` → exit 1; депот отдельной платформы не задан → `warning` и платформа не уезжает |
| Проверить steam_api в SDK | `steam_libs_status` (`:238-252`) | `warning` (сборка остаётся валидной, просто standalone) |
| Распаковать зипы distribute в `build/steam/content/<flavor>/<platform>/` | `steam_stage_content` (`:209-235`) | нет `build/dist/<version>-<flavor>/` или нет зипа платформы → `error` + exit 1 |
| Записать `build/steam/app_build_<flavor>.vdf` | `cli.py:1847-1849` | — |

`--branch beta` подставляется в `"SetLive"`: выкладка уходит в бета-ветку, а release-ветку переключают руками в Steamworks — **после прогона на самом Deck** (`../../ci/steam/README.md`).

Чего команда не делает: не логинится, не звонит в сеть, не хранит credentials и **не запускает `steamcmd`**. Аплоад — отдельная ручная команда. Каналов `dev`/`beta`/`release` как сущностей конвейера тоже нет: `--branch` — это строка в VDF, а не канал сборки (и теги `vX.Y.Z-rcN` по-прежнему невозможны — `project@1` требует `^\d+\.\d+\.\d+$`).

---

## 4. Ачивки под Steam

Локальная система (`vn_ach`, `../../game/framework/00_core/080_achievements.rpy`) остаётся **источником истины**: выдача по стабильным якорям из реестра, хранение в `persistent.vn_achievements`. Платформа — только зеркало. Подробности самой подсистемы — [15-gallery.md](15-gallery.md).

Что делает фасад при живом Steam (`035_platform.rpy:80-88`):

```renpy
for _vn_aid in vn_ach.all_ids():
    achievement.register(_vn_aid)          # те же стабильные id
vn_ach.set_provider(achievement.grant)     # дальнейшие выдачи уходят и в Steam
for _vn_aid in vn_ach.all_ids():           # ДОГОН офлайн-выдач:
    if vn_ach.has(_vn_aid):
        achievement.grant(_vn_aid)         # grant идемпотентен
achievement.sync()                         # батч StoreStats
```

| Правило | Почему так |
|---|---|
| **API Name ачивки в Steamworks обязан ПОБУКВЕННО совпадать с id из `content/achievements/*.yaml`** | маппингов нет намеренно: любая таблица соответствий — второй источник истины, который расходится молча |
| Прогресс, выданный офлайн или до покупки Steam-версии, доезжает при первом запуске под Steam | догон в `init 999`; `grant` идемпотентен, `sync()` сводит бэкенды |
| Ошибка провайдера не роняет игру | `vn_ach.grant` оборачивает вызов провайдера в `try/except` и логирует (`080_achievements.rpy:58-62`) |
| Скрытые/NSFW/пак-ачивки фильтруются **до** провайдера | `visible()` (`080_achievements.rpy:31-41`) — в Steam не уедет то, что игроку не показано |

**Оговорка, которая никуда не делась:** UI достижений в игре по-прежнему нет. Под Steam игрок увидит их в оверлее и в профиле, в standalone — нигде.

---

## 5. Владение DLC (G9)

Ownership-провайдер — `_steam_owns_pack` (`035_platform.rpy:55-68`), ставится в `vn.pack_registry` на `init 999`. Логика в три строки и три решения:

| Случай | Результат | Обоснование |
|---|---|---|
| у пака есть `steam_dlc_appid` | `steam().dlc_installed(<appid>)` | Steam скачивает депот DLC только купившим — установленность DLC и есть владение |
| у пака нет маппинга | `True` | гейтится только установленностью, как в DRM-free поставке |
| API упал / бросил исключение | **`True` (fail-open)** + строка в `log.txt` | «ошибка API не должна отбирать купленный контент»: гейт **логический** и не претендует на защиту |

Гейт остаётся логическим по причинам движка, а не проекта (скрипты всех установленных паков грузятся всегда, `.rpa` ничем не защищён) — разбор в [30-packs-and-dlc.md](30-packs-and-dlc.md) §4. Что меняется с ADR-0014: `owned()` **перестал быть тождественно `True`** — под Steam у пака с `steam_dlc_appid` он честно вернёт `False`, и тогда пропадут карточка главы в `chapter_select`, элементы галереи с этим паком и его ачивки.

Ограничение по построению: маппинг живёт в манифесте пака, поэтому **один пак — один DLC App ID**. Бандлы («три эпизода одним товаром») решаются на стороне Steamworks, а не в манифесте.

---

## 6. Steam Cloud — кода нет, и это решение

Синхронизация сейвов делается **Auto-Cloud** в настройках Steamworks: корень — каталог сохранений Ren'Py (`%LOCALAPPDATA%/RenPy/<save_directory>` / `~/.renpy/<save_directory>`, у нас `config.save_directory = "vn-1755000000"`, `../../game/options.rpy:7`), маска `*.save` + `persistent`.

Почему в игре нет ни строки кода про Cloud:

- локальная система сейвов самодостаточна: `vn_save_schema` + цепочка миграций (G5) уже решает «сейв из другой версии» — а это единственная реальная опасность синхронизации;
- конфликты «две машины» разруливает Steam-клиент своим UI, писать свой мердж сейвов VN — работа без выгоды;
- Cloud API в коде означал бы вторую точку касания платформы, то есть прямое нарушение ADR-0014.

Нормативная запись — `../../ci/steam/README.md` (раздел «Steam Cloud»).

---

## 7. Controller-first UX

Норма ADR-0014 §6: **отдельной копии UI под геймпад не существует**. Всё сделано пятью приёмами в общей вёрстке.

| # | Приём | Где | Что решает |
|---|---|---|---|
| 1 | **Скролл-пресет `vn_scroll_props`** — колёсико, драг, `pagekeys`, единый скроллбар | `../../game/framework/20_ui/components.rpy:89-98`; потребители: `history.rpy:29`, `gallery.rpy:56`, `core_screens.rpy:397` | вместо копий настроек viewport в каждом экране |
| 2 | **`vn_ui.reveal(...)`** — hovered-колбэк ячейки докручивает viewport так, чтобы ряд был виден целиком **плюс `peek` соседа** | `components.rpy:100-125` | движок не докручивает viewport к клавиатурному фокусу, а кнопка за границей клипа выпадает из фокус-листа (нет фокус-ректа) — dpad упирался в край видимой области |
| 3 | **`vn_modal_dialog(cancel_action)`** — затемнение + `key "game_menu"` на безопасное действие + рамка | `components.rpy:134-139`; потребители: `core_screens.rpy:446`, `unavailable.rpy:23` | modal-экран **глотает** `game_menu`, поэтому без своего `key` B/Esc в модалке были мертвы. `modal`/`zorder` при `use` не наследуются — их объявляет потребитель |
| 4 | **`focus_default` у `vn_button`** → `default_focus` | `components.rpy:161-169`; ставится на **безопасную** кнопку: `core_screens.rpy:454` («Нет»), `unavailable.rpy:31` («В главное меню»), `gallery.rpy:150` («Назад») | первое нажатие A уходит в кнопку, а не «в пустоту» |
| 5 | **`quick_menu` уходит из dpad-пути**: `keyboard_focus False` | `../../game/framework/20_ui/screens/quick_menu.rpy:43-48` | во время say это были ЕДИНСТВЕННЫЕ фокусируемые элементы — первый dpad «залипал» на кнопке, и A жал её вместо продвижения текста. Мышь и тач работают как раньше |

Плюс раскладка пада — **одно место**, `../../game/framework/20_ui/input.rpy:19-29`:

| Событие | Действие | Почему именно оно |
|---|---|---|
| `pad_leftstick_press` (L3) | `toggle_skip` | вместе с п. 5 закрывает фокус-ловушку: функции quick menu получили прямые кнопки пада. L3/R3 — единственные незанятые кнопки |
| `pad_rightstick_press` (R3) | `toggle_afm` | обработчики движковые (`_default_keymap`), в меню-контекстах сами no-op'ятся |
| `pad_{left,right}shoulder_press` (+`repeat_*`) | **дополняется** `viewport_pageup` / `viewport_pagedown` | у движка нет пад-биндинга листания (только PageUp/Down клавиатуры) — длинные списки (история, галерея, языки) на паде было не пролистать |

**Дефолтная раскладка движка (`00keymap.rpy`) не переопределяется.** A/B/X/Y, LB/LT=rollback, RB=rollforward, RT=подтверждение, Start/Guide=game_menu сохраняют штатные роли — фасад только дополняет свободное. В игровом контексте добавленные `viewport_page*` безвредны: rollback/rollforward перехватываются раньше (underlay), а вьюпортов с pagekeys там нет.

Точечные закрытые ловушки:

- **Страница квиксейвов.** `QuickSave()` пишет на страницу `"quick"`, и без пункта в пейджере её нельзя было загрузить вовсе — теперь есть `FilePage("quick")` (`../../game/framework/20_ui/screens/core_screens.rpy:245`).
- **Листание в просмотрщике галереи с пада.** dpad шлёт `focus_*`, а не keysym, поэтому «стрелки» листать не могли; LB/RB — единственный пад-способ листать, не гоняя фокус по чипам (`../../game/framework/20_ui/screens/gallery.rpy:155-159`).
- **Фуллскрин на первом запуске.** Игрок без мыши не должен искать переключатель: `config.default_fullscreen = True`, но **только** при `controller_first()` (`../../game/options.rpy:12-17`). На десктопе дефолт движка (оконный, выбор сохраняется) не трогается.

### 7.1 Как это проверять без Deck

```bash
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
```

`vn test smoke` наследует окружение процесса (`../../tools/vn/src/vn/cli.py:1538`: `env = dict(os.environ, VN_AUTOPILOT="1", …)`), поэтому `RENPY_VARIANT` доезжает до движка и он ведёт себя как на Deck: варианты, авто-масштаб 1.4, фуллскрин. Скриншоты — в `.vncache/smoke/`, смотреть **глазами**: движковый lint не ловит ни сплющенный 9-patch, ни обрезанный текст. То же с `RENPY_VARIANT="steam_big_picture"` — проверять, что оверлеи ушли от кромки на `gui.overscan_pad`.

Чего этот прогон **не** проверяет: реального пада (событий `pad_*` в автопилоте нет), Steam-инициализации, оверлея, `dlc_installed`. Пад и Steam проверяются только на живой машине — и прогон на самом Deck перед `setlive default` обязателен (`ci/steam/README.md`).

---

## 8. Масштаб и типографика

Правило одно: **UI читает только `gui.*`, копий экранов не существует.** Один display-профиль вместо вариантов вёрстки.

| Токен | Значение | Где считается |
|---|---|---|
| `gui.ui_scale` | `1.0` или `VN_UI_SCALE_LARGE = 1.4` | `../../game/framework/20_ui/scale.rpy:18,21-32,37` |
| `gui.overscan_pad` | `48` в Big Picture, иначе `0` | `scale.rpy:42` |
| `persistent.vn_ui_scale` | `null` = авто, `"normal"`, `"large"` | `../../content/variables/settings.vars.yaml:11-15` |

Как считается масштаб (`scale.rpy:21-32`): выбор игрока сильнее платформы; при `null` (авто) — `1.4`, если `vn_platform.controller_first()`, иначе `1.0`. Множитель применяется **в самих `define` в `gui.rpy`** (`../../game/gui.rpy:52,58-64`): `interface 21 → 29`, `button 17 → 24`, `tiny 13 → 18` — интерфейс проходит порог читаемости Deck (~26–28 вирт. px строчных) и «10-foot» ТВ. Экраны при этом не трогаются **по построению**.

Переключение на лету — `vn.set_ui_scale(mode)` (`scale.rpy:52-57`): пишет `persistent` и зовёт `gui.rebuild()`, который перезапускает все `define gui.*` в исходном порядке и перестраивает стили; завершается `restart_interaction`, поэтому экран настроек переоценивает себя сам, без перезапуска игры. UI настройки — сегмент из трёх кнопок «авто / крупный / обычный» (`core_screens.rpy:320-343`).

**ВАЖНО: только увеличение (`>= 1.0`).** Генерируемые 9-patch панели (ADR-0009) считают минимумы `2*Borders` от **базовых** кеглей; уменьшение сплющило бы фоны `choice`/`chip`. Рост безопасен — кнопки авто-высотные. Подробнее про панели и токены — [06-frontend.md](06-frontend.md).

Порядок init здесь критичен и задан явно: хелпер `-4` → токены этого файла `-3` → `gui.rpy` `-2` → стили и экраны.

---

## 9. Как добавить новую платформу (например Android)

Пошагово, ровно в этом порядке. Ядро, контент и UI не трогаются — это и есть проверка, что вы делаете правильно.

**1. Конфиг — данные, не код.** Новый блок в `project.yaml: platform.<name>` + расширение `../../tools/schemas/project@1.schema.json` (`additionalProperties: false` — без правки схемы `vn build` покраснеет). Публичные идентификаторы (App ID, package name) в git можно; секретов витрин в репозитории не бывает.

**2. Генерат.** Если платформе нужны движковые `define` до init (как `config.steam_appid`) — добавьте их в `_emit_platform` (`compile.py:133-152`). Это тот же файл `platform.gen.rpy`, отдельного выхода заводить не нужно.

**3. Новый провайдер/ветка в `035_platform.rpy`.** Три части:

- capability-запросы (`is_<platform>()`, при необходимости расширить `controller_first()` / `has_touch()`);
- функция-провайдер владения по образцу `_steam_owns_pack` — **обязательно fail-open** на исключениях;
- ветка в `init 999` рядом с существующей: `if <platform> доступна: set_ownership_provider(...)`, `vn_ach.set_provider(...)`.

Ветки взаимоисключающие по факту окружения; ядро о них не знает.

**4. UI — только capability-запросы.** Нужна другая типографика? Это `gui.ui_scale` (уже есть). Другая safe-area? `gui.overscan_pad` (уже есть). Новый токен заводится в `scale.rpy` и читается экранами — но **не** `if <platform>` в экране.

**5. Поставка.** По образцу `release.py:151-252`: функция «сгенерировать манифест витрины из шаблона в `ci/<platform>/`» + функция «разложить артефакты `build/dist/` под её раскладку» + функция «чего не хватает на build-машине» (предупреждение, не ошибка). Команда в `cli.py` печатает путь к артефакту, аплоад не выполняет.

**6. Тесты.** В `../../tools/vn/tests/test_platform.py`: эмиттер (включён/выключен), генерация манифеста (успех, обязательные поля, предупреждения), раскладка контента (есть/нет дистрибутива), статус библиотек. Плюс расширить гард-тест единственной точки касания на новые запретные символы. Если опираетесь на недокументированный API движка — контракт-тест в `test_engine_compat.py` (G18).

**7. ADR.** Новая платформа меняет последствия ADR-0014 (и, вероятно, G9) — нужна запись в `../adr/` с планом отступления.

**Чего НЕ делать при добавлении платформы:**

| Нельзя | Почему |
|---|---|
| `if renpy.variant("android")` в экране или сцене | точка касания одна; иначе следующая платформа = рефакторинг всего UI |
| вторая копия экрана/вёрстки под платформу | ADR-0014 §6: один display-профиль, токены `gui.*` |
| сторонние Python-биндинги витрины, если движок умеет сам | чужой цикл релизов + лицензионные риски; штатный стек стережёт canary-CI |
| коммитить SDK/редистрибутивы витрины | лицензии; место — build-машина |
| DRM-жёсткий гейт владения (fail-closed) | G9: гейт логический; отобрать купленный контент из-за сбоя API хуже, чем пропустить |
| ownership-провайдер, который блокирует старт | всё в `init 999` обязано быть валидным при любом составе платформ |

---

## Как изменить / Как расширить

| Задача | Что править | Обязательно после |
|---|---|---|
| Включить Steam в этом репозитории | `project.yaml: platform.steam.appid` (+ `depots`) | `vn build` (перегенерит `platform.gen.rpy`), `vn release steam --flavor public`, прогон на Deck |
| Привязать пак к DLC | `packs/<id>/manifest.yaml: steam_dlc_appid` | `vn pack validate`, `vn build`; проверить, что `owned()` даёт `False` без DLC |
| Добавить capability-запрос («открыт ли оверлей», «есть ли клавиатура») | только `035_platform.rpy` | потребитель в UI читает фасад, не движок; гард-тест `test_platform.py:107` должен остаться зелёным |
| Изменить крупный масштаб (1.4) | `../../game/framework/20_ui/scale.rpy:18` | проверить 9-patch панели (минимум `2*Borders`) и `RENPY_VARIANT="steam_deck …" vn test smoke` |
| Поменять safe-area ТВ | `scale.rpy:42` | все три потребителя `gui.overscan_pad`: `quick_menu.rpy:17,19`, `gallery.rpy:134`, `build_overlay.rpy:15-16` |
| Добавить кнопку пада | `../../game/framework/20_ui/input.rpy` — **только там** | не переопределять занятые движком кнопки; проверить, что событие безвредно в игровом контексте |
| Довести `describe()` до crash-отчёта | `070_crash.rpy` — дописать строку `vn_platform.describe()` в отчёт | `tools/vn/tests/test_crash_handler.py` |
| Каналы `dev`/`beta`/`release` как сущности | `release.py` + `project@1` (сейчас `^\d+\.\d+\.\d+$` запрещает теги `-rcN`) | ADR: это меняет схему версий и релизный гейт |
| Steam Cloud через API вместо Auto-Cloud | **не делать без ADR** — вторая точка касания платформы (§6) | — |

---

## Чего НЕ делать

- **Не писать `if steam:` / `_renpysteam` / `steamapi` нигде, кроме `035_platform.rpy`** — гард-тест `test_platform::test_platform_facade_is_single_steam_touchpoint` покраснеет, и это правильно.
- **Не коммитить steam_api-библиотеки** (`steam_api64.dll`, `libsteam_api.so`, `libsteam_api.dylib`) — редистрибутив Valve, лицензия. Место — `$RENPY_SDK/lib/py3-*/` на build-машине.
- **Не заводить таблицу «наш id ачивки → API Name Steamworks»**. Совпадение побуквенное, маппингов нет намеренно.
- **Не задавать `config.steam_appid` присваиванием в `init python`** — движок читает его на `init -1499`, раньше любого пользовательского кода. Только `define` из генерата.
- **Не делать ownership-гейт fail-closed.** Ошибка `dlc_installed` = `True` + строка в лог. Гейт логический (G9), не DRM.
- **Не считать `appid: null` поломкой** — это штатное «Steam выключен», и половина тестов проекта опирается на такое поведение.
- **Не уменьшать `gui.ui_scale` ниже 1.0** — сплющит генерируемые 9-patch панели (ADR-0009).
- **Не делать копию экрана под Deck/ТВ/мобилку.** Один display-профиль, различия — через токены `gui.*`.
- **Не переопределять дефолтные пад-биндинги движка** (A/B/X/Y, LB/LT, RB, RT, Start/Guide) — только дополнять свободное.
- **Не считать `vn release steam` аплоадом.** Она готовит VDF и раскладку; `steamcmd` запускает человек или CI с секретами вне репозитория.
- **Не выкладывать в release-ветку, не прогнав на живом Steam Deck** — smoke под `RENPY_VARIANT` проверяет вёрстку, но не пад, не оверлей и не Steam API.
- **Не ждать `vn release validate` проверки платформы** — в гейте из 19 проверок Steam-проверок нет ни одной; всё платформенное валидируется в `vn release steam` и тестах.

---

## Проверка

```bash
# Тулинг: эмиттер, VDF, раскладка депотов, статус библиотек, гард-тест фасада
python -m pytest tools/vn/tests/test_platform.py -q                 # 9 passed
python -m pytest tools/vn/tests -q                                  # 253 passed

# Контракт со штатным стеком движка (нужен RENPY_SDK, иначе skip)
python -m pytest tools/vn/tests/test_engine_compat.py::test_steam_engine_contract -q

# Генерат платформы
vn build && cat game/generated/platform.gen.rpy
#   define config.steam_appid = None      <- appid: null в project.yaml
#   define VN_STEAM_DLC = {}

# Controller-first вёрстка без Deck (скриншоты смотреть глазами)
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0
ls .vncache/smoke/

# Поставка (при заполненных appid/depots и собранном дистрибутиве)
vn release build --flavor public --package win
vn release steam --flavor public
ls build/steam/                                    # app_build_public.vdf + content/

# Релизный гейт (платформенных проверок в нём нет — но он не должен покраснеть)
vn release validate --flavor public
```

Эталон на 2026-08-18: `platform.steam.appid: null`, `platform.gen.rpy` выключает Steam, `vn release steam --flavor public` завершается `ошибка: platform.steam.appid не задан в project.yaml …` (exit 1) — ожидаемое поведение репозитория без Steamworks-приложения. `test_platform.py` — 9 тестов, из них ни один не требует SDK; `test_steam_engine_contract` — skip без `RENPY_SDK`.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | [`../adr/0014-platform-services.md`](../adr/0014-platform-services.md) (**норматив**, читать целиком), `../../game/framework/00_core/035_platform.rpy` (весь файл — 89 строк), `../../game/framework/20_ui/{scale.rpy,input.rpy}`, `../../game/framework/20_ui/components.rpy:76-169`, `../../tools/vn/src/vn/release.py:151-252`, `../../tools/vn/src/vn/cli.py:1819-1852`, `../../tools/vn/src/vn/content/compile.py:133-152`, `../../ci/steam/README.md`, `../../project.yaml:13-15` |
| **Не трогать** | `game/generated/platform.gen.rpy` — генерат (`.gitignore`); `build/steam/**` — артефакт `vn release steam`; steam_api-библиотеки — их в репозитории нет и добавлять нельзя; дефолтные пад-биндинги движка (`00keymap.rpy` в SDK) |
| **Зависимости (что ломается ниже по течению)** | Правка `035_platform.rpy` → ачивки, ownership-гейт (`chapter_select`, галерея, ачивки), `controller_first()` → `gui.ui_scale` и `config.default_fullscreen`. Правка `scale.rpy` → **все** кегли `gui.*` и минимумы `2*Borders` панелей ADR-0009. Правка `input.rpy` → раскладка пада во всех контекстах. Правка `_emit_platform` → свежесть генерата (`vn build --check`) и `test_platform.py`. Добавление `steam_dlc_appid` → `VN_STEAM_DLC` и поведение `owned()` |
| **Валидация** | `python -m pytest tools/vn/tests/test_platform.py -q` → 9 passed → `python -m pytest tools/vn/tests -q` → 253 passed → `test_engine_compat::test_steam_engine_contract` (с `RENPY_SDK`) → `RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0` + просмотр `.vncache/smoke/` глазами → `vn release steam --flavor public` (при заполненном appid) → `vn release validate --flavor public` |
| **Частые ошибки** | 1) Добавлять платформенное ветвление в экран или сцену — точка касания ровно одна, и это под тестом (`test_platform.py:107-117`). 2) Считать, что `owned()` по-прежнему всегда `True` — с ADR-0014 под Steam у пака с `steam_dlc_appid` он честно даёт `False`; описание «провайдера никто не подключает» в старых текстах устарело. 3) Читать `vn release steam` как аплоад — она только готовит VDF и раскладку депотов. 4) Ожидать Steam в локальной сборке: без steam_api в `$RENPY_SDK/lib/py3-*/` и с `appid: null` любая сборка — standalone, это норма. 5) Уменьшать `gui.ui_scale` (< 1.0) — ADR-0009 запрещает, сплющит панели. 6) Верить `../ARCHITECTURE.md` §6.7 про `steam_appid` в манифесте пака — поле называется `steam_dlc_appid`, а `steam_appid` схемой запрещён. 7) Искать Steam-проверку в релизном гейте — её там нет. 8) Считать Steam Cloud недоделкой: кода нет осознанно (§6) |

---

**Смежные страницы:** [29-build-and-release.md](29-build-and-release.md) (флейворы, гейт, дистрибутивы) · [30-packs-and-dlc.md](30-packs-and-dlc.md) (формат пака, логический гейт G9) · [06-frontend.md](06-frontend.md) (токены `gui.*`, компоненты, панели ADR-0009) · [15-gallery.md](15-gallery.md) (подсистема достижений) · [27-testing.md](27-testing.md) (smoke-автопилот) · [33-security-and-legal.md](33-security-and-legal.md) (организационные сроки Steamworks, правовая рамка 18+)
