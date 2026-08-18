# 39. Платформы: Steam, Steam Deck, Big Picture

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — архитектура слоя закрыта (**фасад — IMPLEMENTED**), приёмка на железе — нет. Платформенный слой замкнут одним файлом-фасадом ([ADR-0014](../adr/0014-platform-services.md)): Steam-ачивки и DLC-владение работают, controller-first UI сделан одной копией экранов, и его вёрстку теперь ночью снимает CI в двух геймпадных профилях ([42](42-big-picture.md) §5.10). Поставка стала полнее: раскладка депотов работает на всех трёх платформах, включая Linux (`tar.bz2`, §3.4), содержимое кладётся **в корень депота** без каталога-обёртки ([40](40-steamworks.md) §4.3.1), а аплоад автоматизирован ручным workflow `steam-upload`. **Но** `platform.steam.appid` в `project.yaml` сейчас `null` (все локальные сборки — standalone), ключа `depots` в файле нет вовсе — `vn release steam` честно падает на первом шаге; секретов `STEAM_USERNAME`/`STEAM_CONFIG_VDF` в репозитории нет, поэтому шаг выкладки — no-op. Мобильный канал перестал быть пустым местом: `vn release android status|preflight|build` вызывает штатный `launcher android_build` и проверяет предпосылки поставки (§2.1), но **ни одного APK/AAB не собрано** — RAPT в SDK не установлен, и CLI-пути его установки у Ren'Py нет. Ни одна платформа не проверена на живом железе, и ни один депот не проходил через реальный SteamPipe: подтверждено только то, что подтверждается кодом и эмуляцией вариантов (§2).
> **Отвечает на вопрос:** «Как игра узнаёт, что она запущена в Steam / на Deck / в Big Picture, что для этого надо положить на build-машину — и как добавить следующую платформу, не переписывая UI и контент».

Платформа в этом проекте — **не фундамент, а провайдер**. Ядро (`vn_ach`, `vn.pack_registry`) самодостаточно и работает без всякой платформы; `game/framework/00_core/035_platform.rpy` — единственное место, которое знает слово «Steam», и единственное, что меняется при добавлении витрины. Steam-специфика идёт через **штатный стек движка** (`00steam.rpy` + `00achievement.rpy` из `renpy/common/`): сторонних биндингов (SteamworksPy и т. п.) в проекте нет и по ADR-0014 быть не должно.

**Эта страница — хаб платформенного слоя.** Детали, которые выросли в отдельные документы: процесс в Steamworks (App ID, депоты, ачивки, ветки, Cloud) — [40-steamworks.md](40-steamworks.md); Deck (вёрстка, кегли, прогон) — [41-steam-deck.md](41-steam-deck.md); ТВ и safe-area — [42-big-picture.md](42-big-picture.md); QA-протокол под Steam — [43-steam-qa.md](43-steam-qa.md); «как мне…» одной строкой — [44-how-do-i.md](44-how-do-i.md). Релизный тракт (флейворы, гейт, дистрибутивы, сквозной маршрут релиза) — [29-build-and-release.md](29-build-and-release.md).

---

## Быстрый ответ

```bash
# 1. Включить Steam (данные, не код): App ID + номера депотов
#    project.yaml: platform.steam.appid: 480
#                  platform.steam.depots: {windows: 481, linux: 482, mac: 483}
#    откуда берутся эти номера — 40-steamworks.md
vn build                                  # -> game/generated/platform.gen.rpy (define config.steam_appid)

# 2. Один раз на build-машину: steam_api-редистрибутивы Valve
#    лаунчер Ren'Py -> preferences -> Install libraries -> Install Steam Support
#    (кладёт steam_api64.dll / libsteam_api.so / libsteam_api.dylib в $RENPY_SDK/lib/py3-*/)

# 3. Собрать и разложить под депоты
vn release build --flavor public --package win --package linux --package mac
vn release steam --flavor public [--branch beta]   # -> build/steam/app_build_public.vdf + content/
#    форматы distribute разные: win/mac — zip, linux — tar.bz2; раскладка знает оба (§3.4)
#    ожидаются только платформы с объявленным депотом в platform.steam.depots

# 4. Аплоад — вне репозитория
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit

# Проверка controller-first вёрстки без Deck:
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
```

Проверено на репозитории 2026-08-18: `platform.steam.appid: null` (`../../project.yaml:15`), поэтому `platform.gen.rpy` эмитит `define config.steam_appid = None`, движок молча не трогает Steam, а `vn release steam` честно падает: `ошибка: platform.steam.appid не задан в project.yaml`. **Это рабочее состояние, а не поломка** — игра полноценна как standalone.

**Включение Steam — два независимых редактирования `project.yaml`, а не одно.** `appid` объявлен схемой как `["integer", "null"]` и физически присутствует со значением `null`; ключа `depots` в файле **нет вообще**. Поэтому после заполнения одного `appid` придёт вторая ошибка — `platform.steam.depots пуст — задайте номера депотов по платформам` (`release.py:234-237`).

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

Ни один экран, ни одна сцена, ни один другой модуль ядра не имеют права обращаться к `_renpysteam` / `steamapi`. Проверка не на честном слове ревьюера, а тестом (`../../tools/vn/tests/test_platform.py:183-193`):

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
| `steam()` | `achievement.steam` или `None` | только внутри фасада (`:27` в `backend()`, `:46` в `overlay_enabled()`, `:63` в `_steam_owns_pack`) и `init 999` (`:74`) |
| `backend()` | `"steam"` \| `"standalone"` — идентичность платформы для логов | `describe()` |
| `is_steam_deck()` | `renpy.variant("steam_deck")` | `controller_first()`, косвенно `scale.rpy` |
| `is_big_picture()` | `renpy.variant("steam_big_picture")` | `../../game/framework/20_ui/scale.rpy:42` (`gui.overscan_pad`) |
| `has_touch()` | `renpy.variant("touch")` | `describe()` |
| `controller_first()` | `is_steam_deck() or is_big_picture()` | `scale.rpy`, `../../game/options.rpy:16` |
| `is_mobile()` | `renpy.variant("mobile")` — тач вместо мыши, нет окна и нет права выйти | `scale.rpy` (масштаб, safe-area, тач-зона), `describe()` |
| `is_android()` | `renpy.variant("android")` — именно Android (у iOS другие правила стора) | `describe()` |
| `is_phone()` | `renpy.variant("phone")` — мелкий экран; делит устройства **физическая диагональ**, а не разрешение | `scale.rpy` (`gui.touch_min`), `describe()` |
| `is_desktop()` | `renpy.variant("pc")` — есть окно, мышь и право закрыть приложение | задел под гейтинг «Выйти» и переключателя окно/фуллскрин (в экранах пока не применён) |
| `overlay_enabled()` | Steam-оверлей активен (в `try/except`, ошибка = `False`) | **никто** — задел (например «не показывать свой тост, когда открыт оверлей») |
| `describe()` | одна строка `backend deck=… bigpicture=… touch=… mobile=… android=… phone=…` | `035_platform.rpy` — уходит в `log.txt` при **каждом** старте |
| `_steam_owns_pack(pack_id)` | ownership-провайдер G9 (см. §5) | ставится на `init 999` |

**Варианты вставляет движок, а не мы** (`$RENPY_SDK/renpy/main.py: choose_variants`, `:163-225`): Android → `android` + `mobile` + `touch` + (`tablet`+`medium` при физической диагонали ≥ 6″, иначе `phone`+`small`); iOS → `ios` + `mobile` + `touch` + то же деление; десктоп → `pc` + `large`. Две ветки, о которых легко забыть: **Android TV/OUYA** (`hasSystemFeature("android.hardware.type.television")`) вставляет `tv` + `small` и **выходит раньше** — то есть без `touch` и без `phone`/`tablet`, поэтому тач-токены там нулевые; Fire TV дополнительно даёт `firetv`, ChromeOS — `chromeos`. Наш фасад читает только `mobile`/`android`/`phone`/`pc`, так что TV-ветка деградирует в «мобильный без тача» — на телевизоре это и требуется.

**Честная оговорка:** `describe()`/`backend()` пишутся в `log.txt` одной строкой на старте (`vn_log("platform: …")`) — теперь всегда, а не только под Steam (иначе на Android лог о платформе молчал бы), — но в crash-отчёт `070_crash.rpy` **не попадают**: докстринг фасада («для логов/крэш-репортов») обещает больше, чем сегодня подключено. Это однострочное расширение, а не долг архитектуры.

### 1.3 Порядок инициализации

| Приоритет | Что происходит | Почему именно так |
|---|---|---|
| define-пасс | `define config.steam_appid = <appid>` из `platform.gen.rpy` | движок читает appid на `init -1499`, то есть **раньше любого пользовательского init**; поэтому appid обязан задаваться `define`-стейтментом, а не присваиванием в `init python` (`compile.py:136-140`) |
| `init -1499` (движок) | `steam_init()`: если рядом с исполняемым нет steam_api — **тихий no-op**; иначе вставляются варианты `steam_deck` / `steam_big_picture`, включается экранная клавиатура Deck для `input()`, регистрируется `SteamBackend` ачивок | без библиотеки standalone-сборка не должна ломаться |
| `init -960` | создаётся store `vn_platform` | до UI-токенов (`init -4`), которые его читают |
| `init -4 / -3` | `gui.vn_ui_scale()` и `define gui.ui_scale` / `gui.overscan_pad` | до `gui.rpy` (`init offset = -2`), который умножает кегли |
| `init 999` | подключение провайдеров: ownership, регистрация ачивок, `set_provider`, догон офлайн-выдач, `achievement.sync()` | реестры (`VN_ACHIEVEMENTS`, `VN_STEAM_DLC`) уже загружены, Steam уже инициализирован |

Уровень 999 — это ровно «DLC-слот» из нормы C8; до ADR-0014 он был занят только пересборкой реестра языков (`040_localization.rpy:131`). Сейчас на нём же живёт применение потолка качества текстур (`095_quality.rpy:12`) — три независимых блока, порядок между ними значения не имеет.

Допущения о штатном стеке движка не висят в воздухе: их стережёт контракт-тест `test_engine_compat::test_steam_engine_contract` (`../../tools/vn/tests/test_engine_compat.py:63-88`) — он читает `$RENPY_SDK/renpy/common/00steam.rpy` и падает, если исчезли тихий no-op без библиотеки, вставка вариантов `steam_deck`/`steam_big_picture`, регистрация `SteamBackend`, `dlc_installed` или `steam_init()` на `init -1499`. Без `RENPY_SDK` тест **skip** (его гоняет canary-джоба CI на свежем движке).

---

## 2. Platform Matrix

Только подтверждённые кодом значения. «Не проверялось» означает буквально это: соответствующего железа или прогона не было, и утверждать работоспособность нельзя.

| Platform | Status | Build | Controls | Steam | QA |
|---|---|---|---|---|---|
| **Windows** | IMPLEMENTED | `--package win` → **zip** (`00build.rpy:426`), `vn-<ver>-win.zip`. Дефолт `--package` в CLI (`cli.py:302`), собирается в CI (`release.yml:83`). **Не подписан** — `signtool` в репозитории отсутствует | Мышь/клавиатура штатно; дополнения пада из `input.rpy` активны на любой платформе | Да — при `steam_api64.dll` в `$RENPY_SDK/lib/py3-windows-x86_64/` (карта библиотек — `release.py:317-321`) | Ручной запуск артефакта. **Не проверялось**: автоматизации нет, эта машина — darwin arm64 |
| **macOS** | IMPLEMENTED (сборка) | `--package mac` → форматы `app-zip app-dmg` (`00build.rpy:425`), но **dmg пропускается**: `distribute.rpy:1537-1540` требует `build.mac_identity`, которого проект не задаёт → на выходе только `vn-<ver>-mac.zip`. DMG делает отдельная джоба `release.yml:95-115` через `hdiutil`. Не подписан и не нотаризован | То же | Да — при `libsteam_api.dylib` в `py3-mac-universal` | **Не проверялось**: mac-пакет на этой машине не собирался; `.app` без подписи упрётся в Gatekeeper |
| **Linux** | IMPLEMENTED (сборка) | `--package linux` → **`tar.bz2`, не zip** (`00build.rpy:424`), `vn-<ver>-linux.tar.bz2`. Собирается в CI; `release.yml:132-134` ищет артефакты по маске, включающей `*.tar.bz2` | То же | Да — при `libsteam_api.so` в `py3-linux-x86_64`; депот стейджится из `tar.bz2` (§3.4) | **Не проверялось**: Linux-машины нет |
| **Steam Deck** | PARTIALLY IMPLEMENTED (вёрстка и детект есть, на железе не проверено — [41](41-steam-deck.md)) | Отдельного пакета нет — едет Linux-пакет | `controller_first()` → `config.default_fullscreen = True` (`options.rpy:15-17`) и `gui.ui_scale = 1.4`; L3 = skip, R3 = auto-forward, LB/RB = листание вьюпортов (`input.rpy:19-29`); quick menu выведен из dpad-пути (`quick_menu.rpy:44-48`) | Вариант `steam_deck` вставляет **движок** при `steam_init()` (`00steam.rpy:1053-1059`: убирает `large`, добавляет `medium` и `touch`); экранную клавиатуру для `input()` тоже включает движок (`00steam.rpy:704`) | Эмуляция вёрстки — `RENPY_VARIANT="steam_deck medium touch" vn test smoke` (§7.1). **Живой Deck не проверялся** — устройства нет; прогон на нём объявлен обязательным в `../../ci/steam/README.md`. Протокол — [43-steam-qa.md](43-steam-qa.md) |
| **Big Picture** | PARTIALLY IMPLEMENTED (вёрстка и детект есть, вёрстку ночью снимает CI, оставшиеся открытые пункты — [42](42-big-picture.md)) | Тот же desktop-пакет | `controller_first()` (фуллскрин + масштаб 1.4) плюс `gui.overscan_pad = 48` (`scale.rpy:42`); потребители — `quick_menu.rpy:17,19`, `gallery.rpy:138`, `build_overlay.rpy:15-16`, `core_screens.rpy:91,122,126,511-512` (рельса меню и тост, [42](42-big-picture.md) §5.6) | Вариант `steam_big_picture` вставляет движок (`00steam.rpy:1050`) | Эмуляция — `RENPY_VARIANT="steam_big_picture" vn test smoke`. **На реальном ТВ не проверялось**. Подробно — [42-big-picture.md](42-big-picture.md) |
| **Android** | PARTIALLY IMPLEMENTED (канал сборки и предполётные проверки есть; ни одного APK не собрано — RAPT на машине не установлен) | Канал живёт в `vn release android {status,preflight,build}` (`cli.py`, модуль `tools/vn/src/vn/android.py`) и вызывает **штатную** команду лаунчера `renpy.sh <SDK>/launcher android_build <проект> --destination …` (`launcher/game/android.rpy:739`). `vn package` про Android не знает намеренно: там `launcher distribute`, а мобильный канал — другая команда лаунчера, свой тулчейн и свои потолки. Оверсэмпл-варианты `@N` в мобильный пакет не едут (`options.rpy:92`, §10.3) | Профиль тача — токены: `gui.touch_min` 120 px на телефоне / 72 px на планшете, `gui.ui_scale = 1.4`, `gui.overscan_pad = 48` (`scale.rpy:33-39,53-64,79-83`). Копий экранов под мобильный нет | Неприменимо | Вёрстка эмулируется вариантами: `RENPY_VARIANT="touch small phone android mobile" vn test smoke`; **на устройстве не проверялось** — RAPT/JDK/ключей на этой машине нет |

**Остальные каналы.** GOG / itch.io / Epic — NOT IMPLEMENTED как процесс, но технически им достаточно standalone-архивов, залитых загрузчиком витрины руками; ownership-API у GOG/itch нет, поэтому «владение = наличие пака» (поведение без провайдера) там уже корректно по ADR-0014. iOS/web — пакеты у движка есть (`00build.rpy:431-432`), у нас не заводились. Консоли — вне горизонта: Ren'Py консольных портов не даёт.

**Что общего у всех шести строк.** Копии UI под платформу не существует (§7-§8): различия делаются токенами `gui.*`, а не вариантами вёрстки. Поэтому «поддержать платформу» в этом проекте = детект + токены + канал поставки, а не порт интерфейса.

### 2.1 Android: что реализовано, что осталось

Часть работы была сделана побочно — release-рантайм чист для мобильных и консольных окружений (аудит 2026-08-18, зафиксирован в «Последствиях» ADR-0014):

| Уже готово | Где |
|---|---|
| Ноль сети в рантайме: ни `urllib`, ни `socket`, ни HTTP-клиентов в `game/` | grep по `game/framework/` |
| Ноль `subprocess` в релизной части (dev-инструменты `90_debug/` исключаются `build.classify`) | `../../game/options.rpy:41` |
| Файловый ввод только через `renpy.loader` — никаких абсолютных путей ФС | конвенция ядра |
| UI не требует мыши: dpad-навигация, фокус по умолчанию в модалках, скролл-пресет | §7 |
| Масштаб интерфейса — токен, а не вёрстка (мобильный экран = тот же рычаг, что Deck) | §8 |
| Детект мобильного окружения в фасаде: `is_mobile()`, `is_android()`, `is_phone()`, `is_desktop()`, `has_touch()`; строка `platform:` в лог пишется всегда, не только под Steam | `035_platform.rpy:36-84` |
| Минимальная тач-зона — токен `gui.touch_min` (120 px телефон / 72 px планшет; вывод от 48 dp Material расписан в комментарии), safe-area `gui.overscan_pad = 48` и на мобильном (движок safe-area не инсетит) | `20_ui/scale.rpy:33-39,57-64,79-83`; потребитель — `quick_menu.rpy` |
| Мобильный пакет без `@N`-вариантов: правило `build.classify("**@[2-9].*", "windows linux mac")` стоит **после** флейворных исключений (правило первого совпадения) | `../../game/options.rpy:72-92`, §10.3 |
| Канал сборки в CLI: `vn release android status` (готовность тулчейна), `preflight` (предпосылки проекта), `build` (штатный `launcher android_build`) | `tools/vn/src/vn/android.py`, `cli.py` |
| Предполётные проверки: потолок канала 2 ГБ (+80 % — предупреждение), пофайловый лимит 500 МБ для Play-бандла, мобильная модель памяти образов, утечка ключей подписи в git, отсутствие иконок/пресплэша | `android.py: preflight`, `keystore_leaks` |

| Осталось | Почему это работа, а не флаг |
|---|---|
| Сам APK/AAB ни разу не собран | RAPT в SDK не установлен, JDK 21 и ключей подписи на этой машине нет. **CLI-пути установки тулчейна у Ren'Py не существует** — RAPT ставит апдейтер лаунчера (`launcher/game/updater.rpy:41`), Android SDK — кнопка *Install SDK*, ключи — *Generate Keys*, конфиг — *Configure*. `vn release android status` называет каждый шаг и падает кодом 1, а не изображает установку |
| Мобильный лимит кэша образов не доезжает до движка | `render.mobile.image_cache_mb` (дефолт 200 МБ) читает только `preflight`; в `render.gen.rpy` эмитится один лимит — десктопный. Закрытие — вариант-условие `renpy.variant('mobile')` в эмиссии `config.image_cache_size_mb` |
| `*.keystore` не в `.gitignore` | ключи создаёт лаунчер в корне проекта; из дистрибутива они исключены (`options.rpy:31`), но от коммита сейчас не защищены. `vn release android preflight` назовёт это блокером, как только ключ появится |
| Размер-бюджеты по каналам в CI (AAB / universal APK) | `ARCHITECTURE.md:1189` требует реальную сборку `.aab` и сравнение с лимитами Play Asset Delivery — джобы нет; `preflight` считает оценку по `game/` + накладные ~150 МБ, а не по факту пакета |
| Провайдер владения для Google Play Billing | в `035_platform.rpy` нужна вторая ветка `init 999` (см. §9) |
| Тач-жесты и сплошной аудит hit-area | токен `gui.touch_min` применён в quick menu; остальные экраны на палец не проверялись, физические размеры (120/72 px) выведены из типовых dpi, а не измерены на устройстве |
| `is_desktop()` в фасаде есть, но **ни один экран им не гейтится** | на мобильном остаются бессмысленные «Выйти» (на iOS она запрещена правилами стора, на Android приложение снимает система) и группа настроек «Окно / Полный экран» — окна там нет. Штатный шаблон SDK гейтит и то, и другое как `renpy.variant("pc")`. Правка — обёртки `if vn_platform.is_desktop():` в `core_screens.rpy`; после скрытия группы «Экран» проверить, куда уедет `default_focus` |
| Тематические `.rpa` под каналы без пофайловых дельта-патчей | норма `ARCHITECTURE.md` §2.4: desktop едет россыпью ради Steam-дельта-патчей; mobile-`.rpa` — опция фазы 3, **только через ADR** |

#### 2.1.1 Мобильный канал: команды и что они проверяют

```bash
vn release android status      # RAPT, hash RAPT<->SDK, adb (Android SDK), JDK 21,
                               # android.keystore / bundle.keystore, android.json
                               # -> код 1 и перечень штатных шагов лаунчера, если чего-то нет
vn release android preflight [--bundle]
                               # размер: game/ минус @N-варианты + ~150 МБ накладных
                               # против потолка 2 ГБ; для --bundle ещё лимит 500 МБ
                               # на файл; мобильная модель памяти; ключи и оформление
vn release android build [--bundle] [--install] [--launch] [--timeout 3600]
                               # status -> vn build -> launcher android_build
                               # лог gradle/RAPT идёт живьём: молчащая сборка
                               # неотличима от зависшей
```

Фактический прогон на этой машине (2026-08-18, дословно): `status` печатает единственный пункт — «нет `<SDK>/rapt` — RAPT (тулчейн Android) не установлен: запустите лаунчер (`<SDK>/renpy.sh`), раздел Android — он предложит скачать RAPT» — и падает с «android: тулчейн не готов — перечисленное выше выполняется в лаунчере Ren'Py, CLI-пути установки у Ren'Py нет», код 1. `preflight --bundle` проходит: `game/: 2.8 МБ, из них @N-вариантов 0.3 МБ (в мобильный пакет не едут) -> 152 МБ с накладными`, `кэш образов мобильного профиля: 200 МБ`, три предупреждения — нет `android-icon_foreground.png`, `android-icon_background.png`, `android-presplash.jpg`. Порядок в `build` намеренный: тулчейн проверяется **до** `vn build`, потому что сборка ассетов и компиляция идут минутами, а проверка — миллисекунды.

**Мобильный профиль памяти — отдельное число, и сегодня его видит только `preflight`.** `render.mobile.image_cache_mb` (`tools/schemas/project@1.schema.json`, дефолт `200`; в `project.yaml` не переопределён — десктопный `image_cache_mb: 1024`) применяется методом `RenderConfig.for_mobile()` (`assets/render_config.py`), и `preflight` считает на нём **ту же** модель памяти, что `vn assets memory`, но на масштабе `@1`: `@N`-варианты в мобильный пакет не едут, поэтому считать worst-case на `@2` было бы враньём в свою пользу. Отдельная проверка — «мобильный лимит ≥ десктопного» (предупреждение: почти всегда это забытая правка, а не решение). В **движок** этот лимит не эмитится: `render.gen.rpy` содержит один `define config.image_cache_size_mb` (см. таблицу «Осталось»), то есть на телефоне игра пока живёт с десктопным потолком кэша.

**В CI мобильный канал проверяется на каждый пуш** — `ci.yml`: `vn release android preflight --bundle` **после** `vn build` (на пустом `game/` и потолок канала, и модель памяти зелены всегда → гейт был бы ложно-зелёным), плюс шаг `must_fail`, который требует, чтобы `vn release android status` и `vn release android build --timeout 1` возвращали НЕнулевой код **и называли** отсутствующий RAPT. Секунды против часа gradle, который упал бы на том же самом.

**Что осталось непроверенным честно:** ни одной сборки APK/AAB не запускалось; `--install`/`--launch` (adb) не проверялись — устройства нет; оценка накладных расходов пакета (150 МБ) — оценка сверху, а не измерение, и уточняется по первому реальному APK; раскладка Android SDK внутри `rapt/` определяется по `rapt/sdk.txt` и `platform-tools/adb*` — если RAPT её сменит, диагностика даст ложное «нет adb» (сборку это не ломает).

---

## 3. Как включается Steam

Steam включается **двумя независимыми вещами**, и обе обязательны:

1. **Данные в репозитории** — `platform.steam.appid` в `../../project.yaml:13-15`. `null` = Steam выключен во всех сборках (движок сам удалит `steam_appid.txt`, чтобы игра не подцепила чужой App ID).
2. **Библиотека на build-машине** — редистрибутив Valve `steam_api`, которого в git нет и не будет.

Отсюда главное свойство поставки: **тот же самый дистрибутив** без библиотеки — обычный standalone. Отдельной «Steam-сборки» в конвейере не существует.

| Артефакт | Где живёт | В git? |
|---|---|---|
| App ID, номера депотов | `project.yaml: platform.steam` (схема — `../../tools/schemas/project@1.schema.json:11-38`; `depots` допускает **ровно** `windows`/`linux`/`mac` при `additionalProperties: false`, `:23-32`) | **да** — публичные, не секреты. Но сегодня в файле есть только `appid: null`, ключа `depots` нет |
| `pack_id → DLC App ID` | `packs/<id>/manifest.yaml: steam_dlc_appid` (`../../tools/schemas/pack_manifest@1.schema.json:32-35`) | да |
| `define config.steam_appid`, `VN_STEAM_DLC` | генерат `game/generated/platform.gen.rpy` | нет (генерат) |
| `steam_api64.dll` / `libsteam_api.so` / `libsteam_api.dylib` | `$RENPY_SDK/lib/py3-{windows-x86_64,linux-x86_64,mac-universal}/` | **нет — лицензия Valve** |
| VDF для `steamcmd` | `build/steam/app_build_<flavor>.vdf` (генерат `vn release steam`) | нет |
| Логин/Steam Guard `steamcmd` | CI-секреты или интерактивный вход | **никогда** |

### 3.1 Как положить steam_api

Steam-поддержка Ren'Py **не входит в SDK** и ставится лаунчером: `preferences` → `Install libraries` → `Install Steam Support`. Скачивание гейтится приёмом в Steam partner program, Ren'Py 8.5 требует Steamworks SDK 1.62 — это нельзя «добавить в последний момент». Файлы можно и разложить руками из `redistributable_bin/` Steamworks SDK по тем же трём каталогам.

Проверка наличия — в самой команде поставки (`../../tools/vn/src/vn/release.py:312-326`): чего не хватает, печатается **предупреждением**, а не ошибкой:

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

`../../tools/vn/src/vn/cli.py:1819-1852` + `release.py:150-326`. Пять шагов, все локальные:

| Шаг | Функция | Поведение при проблеме |
|---|---|---|
| Прочитать `platform.steam` | `steam_config` (`release.py:215-222`) | нет `appid` → **exit 1** с указанием, что заполнить |
| Отрендерить VDF из `ci/steam/app_build.vdf.tmpl` | `steam_app_build` (`:197-235`) | пустые `depots` → exit 1; депот отдельной платформы не задан → `warning` и платформа не уезжает |
| Проверить steam_api в SDK | `steam_libs_status` (`:275-289`) | `warning` (сборка остаётся валидной, просто standalone) |
| Распаковать архивы distribute в `build/steam/content/<flavor>/<platform>/` | `steam_stage_content` (`:238-272`) | нет `build/dist/<version>-<flavor>/` → `error` + exit 1; нет артефакта у платформы **с объявленным депотом** → `error` + exit 1 (у платформы без депота артефакт и не требуется) |
| Записать `build/steam/app_build_<flavor>.vdf` | `cli.py:1847-1849`, сообщение — `:1850-1852` | — |

`--branch beta` подставляется в `"SetLive"` шаблона (`ci/steam/app_build.vdf.tmpl:7`): выкладка уходит в бета-ветку, а release-ветку переключают руками в Steamworks — **после прогона на самом Deck** (`../../ci/steam/README.md`; этот прогон в проекте ещё не выполнялся). Важная деталь процесса: ветку `beta` нужно **сначала создать в Steamworks**, иначе `SetLive` в несуществующую ветку ничего не публикует — как это делается, см. [40-steamworks.md](40-steamworks.md).

Пути в VDF **относительные**: `steam_app_build` подставляет `ContentRoot "."` и `BuildOutput "output"` (`release.py:257-262`), то есть SteamPipe создаст `build/steam/output/` и будет искать `content/<flavor>/<platform>/*` относительно самого VDF, а не относительно текущего каталога.

Чего команда не делает: не логинится, не звонит в сеть, не хранит credentials и **не запускает `steamcmd`**. Аплоад — отдельная ручная команда. Каналов `dev`/`beta`/`release` как сущностей конвейера тоже нет: `--branch` — это строка в VDF, а не канал сборки (и теги `vX.Y.Z-rcN` по-прежнему невозможны — `project@1` требует `^\d+\.\d+\.\d+$`).

### 3.4 Форматы архивов distribute: раскладка знает, что Linux — не zip

**STATUS: IMPLEMENTED.** Формат пакета движок выбирает **по платформе**, а не единый для всех:
`package("win","zip")`, `package("linux","tar.bz2")`, `package("mac","app-zip app-dmg")`
(`00build.rpy:421-432`). `_DIST_SUFFIX` (`release.py:158-162`) хранит для каждой платформы суффикс
имени и кортеж расширений по приоритету — linux `(-linux, .tar.bz2, .zip)`, windows/mac `.zip`, —
а `_extract_archive` (`:174-184`) распаковывает zip или tar.bz2 **по фактическому типу файла**.
`.dmg` в карте нет намеренно: кроссплатформенно его не распаковать, а `app-zip` несёт то же.

Второе: ожидаются **не все три платформы, а только объявленные** в `platform.steam.depots`
(`release.py:287-288`). Собирать все три ради одного депота незачем; «нет артефакта» для платформы,
которую вы не отгружаете, — не ошибка. Для платформы **с** депотом, но без артефакта, ошибка
остаётся честной и валит команду до записи VDF (`cli.py:1843-1846`): частично рабочего результата
не бывает — либо все объявленные депоты, либо ничего.

Урок, который стоит унести в любую следующую витрину: **сверяйтесь с фактическим форматом пакета
движка** (`00build.rpy:421-432`), а не с предположением «всё zip». Разбор по коду, тесты на реальные
архивы и оставшийся открытый вопрос про каталог-обёртку в депоте —
[40-steamworks.md](40-steamworks.md) §4.3.

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

**Экран достижений в игре появился** (`20_ui/screens/achievements.rpy`, пункт рельсы рядом с «Галереей»), поэтому в standalone игрок видит прогресс, а под Steam — ещё и в оверлее с профилем. Экран читает те же `visible()`/`has()`, поэтому ачивка невидимая для игрока не попадает ни на экран, ни в знаменатель счётчика, ни в Steam. Что у него всё ещё отсутствует — прогресс отдельной ачивки и уведомление о выдаче ([15-gallery.md](15-gallery.md)).

**Что мы у движка не используем.** `achievement.register(_vn_aid)` вызывается без ключевых аргументов, хотя движок документирует три (`00achievement.rpy:160-184`): `steam` (другое имя на стороне Steam), `stat_max` (значение стата, на котором ачивка открывается) и `stat_modulo` (частота показа прогресса). Ровно поэтому «API Name = наш id» — не ограничение движка, а **наше** решение (маппинг был бы вторым источником истины). Прогресс-ачивок («прочитано 100 реплик») у нас быть не может без правки фасада: `vn_ach` знает только `grant` / `has` / `all_ids`. Позиция тоста тоже не задаётся — движок ставит `POSITION_TOP_RIGHT` при инициализации (`00steam.rpy:1047`), а `achievement.steam_position` мы не трогаем. Полный перечень неиспользуемого — §10; как заводить ачивку в самом Steamworks — [40-steamworks.md](40-steamworks.md).

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

**Чего поверх ownership-гейта не хватает.** При `owned() == False` карточка главы просто исчезает — предложения купить нет, хотя движок даёт прямой путь: `activate_overlay_to_store(appid, flag)` (`00steam.rpy:375`) открывает страницу товара в оверлее. Экран `vn_content_unavailable` о DLC не знает. И отдельный разрыв в данных: App ID DLC положить есть куда (`pack_manifest@1: steam_dlc_appid`), а **номер депота DLC — некуда**: `project@1` разрешает в `platform.steam.depots` только `windows`/`linux`/`mac` при `additionalProperties: false`. То есть «пак как товар» упирается не в код, а в схему — [30-packs-and-dlc.md](30-packs-and-dlc.md) §7.3 и [40-steamworks.md](40-steamworks.md).

---

## 6. Steam Cloud — кода нет, и это решение

Синхронизация сейвов делается **Auto-Cloud** в настройках Steamworks: корень — каталог сохранений Ren'Py (`%APPDATA%/RenPy/<save_directory>` на Windows — **Roaming**, а не Local, `$RENPY_SDK/renpy.py:194-197`; `~/Library/RenPy/<save_directory>` на macOS; `~/.renpy/<save_directory>` на Linux; у нас `config.save_directory = "vn-1755000000"`, `../../game/options.rpy:7`), маска `*.save` + `persistent`.

**Готовая конфигурация — в нормативе.** `../../ci/steam/README.md`, раздел «Steam Cloud»: шесть строк `Root / Path / Pattern` (`WinAppDataRoaming`, `MacHome`, `LinuxHome` × `*.save`, `persistent`) плюс явное «что не синхронизировать». **Recursive держим выключенным** — иначе под маску попадёт подкаталог `crash/` с нашими крэш-отчётами (`070_crash.rpy:27-34`): это диагностика конкретной машины, в облаке она бесполезна и жжёт квоту. Маска `persistent` задана точным именем: `persistent*` затянул бы `.tmp`-мусор атомарной записи.

**Риск, о котором надо знать заранее: подпись сейвов.** Ключ подписи генерируется **на устройстве** и живёт в `<корень>/tokens/security_keys.txt`, то есть **вне** синхронизируемого каталога (`$RENPY_SDK/renpy/savetoken.py:290-306`). Поэтому сейв, приехавший из облака с другого устройства, движок встретит вопросом «This save was created on a different device…» (`renpy/common/00gui.rpy:459-460`, логика — `savetoken.py:141-185`): игрок один раз подтверждает доверие. Обойти это подстановкой общего ключа нельзя — `config.save_token_keys` принимает только verifying-ключи и явно отвергает signing (`savetoken.py:316-337`). Это штатное поведение Cloud-переноса, не дефект; но в приёмке его надо ожидать ([43-steam-qa.md](43-steam-qa.md)).

**Не проверяемое без партнёрского аккаунта** (так и записано в нормативе): имена root'ов из выпадающего списка Steamworks, трансляция путей для Windows-депота под Proton, срок жизни сентри `config.vdf`.

**`config.save_directory` не переименовывать.** `vn-1755000000` — штатное имя от лаунчера (`<simple_name>-<unixtime создания проекта>`, `$RENPY_SDK/launcher/game/gui7/parameters.py:113`), литерал, а не вычисление. Переименование = смена каталога сейвов: у игроков «пропадает» весь прогресс и `persistent`, а Auto-Cloud начинает синхронизировать пустой каталог, продолжая держать старый в облаке. Понадобится — это миграция при первом запуске, а не правка `options.rpy` (предохранитель — inline-комментарий на `../../game/options.rpy:7`).

Почему в игре нет ни строки кода про Cloud:

- локальная система сейвов самодостаточна: `vn_save_schema` + цепочка миграций (G5) уже решает «сейв из другой версии» — а это единственная реальная опасность синхронизации;
- конфликты «две машины» разруливает Steam-клиент своим UI, писать свой мердж сейвов VN — работа без выгоды;
- Cloud API в коде означал бы вторую точку касания платформы, то есть прямое нарушение ADR-0014.

Нормативная запись — `../../ci/steam/README.md` (раздел «Steam Cloud»); учтите, что там windows-путь назван `%LOCALAPPDATA%` — это ошибка норматива, по коду SDK путь `%APPDATA%` ([40-steamworks.md](40-steamworks.md) §7.1). Что именно вводится в форму Auto-Cloud (root-переменные, подпуть с `config.save_directory`, отдельное правило для файла `persistent` без расширения, квоты) — [40-steamworks.md](40-steamworks.md).

---

## 7. Controller-first UX

Норма ADR-0014 §6: **отдельной копии UI под геймпад не существует**. Всё сделано пятью приёмами в общей вёрстке.

| # | Приём | Где | Что решает |
|---|---|---|---|
| 1 | **Скролл-пресет `vn_scroll_props`** — колёсико, драг, `pagekeys`, единый скроллбар | `../../game/framework/20_ui/components.rpy:104-113`; потребители: `history.rpy:31`, `gallery.rpy:56`, `core_screens.rpy:437` | вместо копий настроек viewport в каждом экране |
| 2 | **`vn_ui.reveal(...)`** — hovered-колбэк ячейки докручивает viewport так, чтобы ряд был виден целиком **плюс `peek` соседа** | `components.rpy:118-140` (store `vn_ui`, `init -990` — `:100`) | движок не докручивает viewport к клавиатурному фокусу, а кнопка за границей клипа выпадает из фокус-листа (нет фокус-ректа) — dpad упирался в край видимой области |
| 3 | **`vn_modal_dialog(cancel_action)`** — затемнение + `key "game_menu"` на безопасное действие + рамка | `components.rpy:171-176`; потребители: `core_screens.rpy:486`, `unavailable.rpy:23` | modal-экран **глотает** `game_menu`, поэтому без своего `key` B/Esc в модалке были мертвы. `modal`/`zorder` при `use` не наследуются — их объявляет потребитель |
| 4 | **`focus_default` у `vn_button`** → `default_focus` | `components.rpy:198-206`; ставится на **безопасную** кнопку: `core_screens.rpy:494` («Нет»), `unavailable.rpy:31` («В главное меню»), `gallery.rpy:160` («Назад») | первое нажатие A уходит в кнопку, а не «в пустоту» |
| 5 | **`quick_menu` уходит из dpad-пути**: `keyboard_focus False` | `../../game/framework/20_ui/screens/quick_menu.rpy:44-48` | во время say это были ЕДИНСТВЕННЫЕ фокусируемые элементы — первый dpad «залипал» на кнопке, и A жал её вместо продвижения текста. Мышь и тач работают как раньше |

Плюс раскладка пада — **одно место**, `../../game/framework/20_ui/input.rpy:19-29`:

| Событие | Действие | Почему именно оно |
|---|---|---|
| `pad_leftstick_press` (L3) | `toggle_skip` | вместе с п. 5 закрывает фокус-ловушку: функции quick menu получили прямые кнопки пада. L3/R3 — единственные незанятые кнопки |
| `pad_rightstick_press` (R3) | `toggle_afm` | обработчики движковые (`_default_keymap`), в меню-контекстах сами no-op'ятся |
| `pad_{left,right}shoulder_press` (+`repeat_*`) | **дополняется** `viewport_pageup` / `viewport_pagedown` | у движка нет пад-биндинга листания (только PageUp/Down клавиатуры) — длинные списки (история, галерея, языки) на паде было не пролистать |

**Дефолтная раскладка движка (`00keymap.rpy`) не переопределяется.** A/B/X/Y, LB/LT=rollback, RB=rollforward, RT=подтверждение, Start/Guide=game_menu сохраняют штатные роли — фасад только дополняет свободное. В игровом контексте добавленные `viewport_page*` безвредны: rollback/rollforward перехватываются раньше (underlay), а вьюпортов с pagekeys там нет.

Точечные закрытые ловушки:

- **Первый фокус: контент, а не рельса.** Два токена приоритета (`../../game/gui.rpy:104-105`) — `gui.focus_content` (2) у контента экранов меню и экрана выбора, `gui.focus_rail` (1) у рельсы, и рельса берёт его только на пункт **текущего** экрана. Слепой A больше не уводит из «Загрузки» в «Сохранение» и не жмёт `Start()` на экране выбора глав; разбор — [42](42-big-picture.md) §5.1, §5.2.

- **Страница квиксейвов.** `QuickSave()` пишет на страницу `"quick"`, и без пункта в пейджере её нельзя было загрузить вовсе — теперь есть `FilePage("quick")` (`../../game/framework/20_ui/screens/core_screens.rpy:268`).
- **Листание в просмотрщике галереи с пада.** dpad шлёт `focus_*`, а не keysym, поэтому «стрелки» листать не могли; LB/RB — единственный пад-способ листать, не гоняя фокус по чипам (`../../game/framework/20_ui/screens/gallery.rpy:159-169`).
- **Фуллскрин на первом запуске.** Игрок без мыши не должен искать переключатель: `config.default_fullscreen = True`, но **только** при `controller_first()` (`../../game/options.rpy:12-17`). На десктопе дефолт движка (оконный, выбор сохраняется) не трогается.

### 7.1 Как это проверять без Deck

```bash
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
```

`vn test smoke` наследует окружение процесса (`../../tools/vn/src/vn/cli.py:1538`: `env = dict(os.environ, VN_AUTOPILOT="1", …)`), поэтому `RENPY_VARIANT` доезжает до движка и он ведёт себя как на Deck: варианты, авто-масштаб 1.4, фуллскрин. Скриншоты — в `.vncache/smoke/`, смотреть **глазами**: движковый lint не ловит ни сплющенный 9-patch, ни обрезанный текст. То же с `RENPY_VARIANT="steam_big_picture"` — проверять, что оверлеи ушли от кромки на `gui.overscan_pad`.

**Тонкость, из-за которой эмуляция не равна Deck.** `RENPY_VARIANT` **заменяет** список вариантов целиком: `renpy/main.py:158-159` делает `config.variants = list(os.environ["RENPY_VARIANT"].split()) + [None]`. То есть штатных `pc`/`desktop`/`large` в прогоне не окажется вовсе — вы проверяете набор вариантов, а не устройство. Именно поэтому строку принято писать полностью — `"steam_deck medium touch"`: ровно те варианты, которые вставляет сам движок при `steam_init()` (`00steam.rpy:1053-1059`).

**Этот прогон теперь есть и в CI.** Ночная джоба `controller-first` (`.github/workflows/nightly.yml:85-152`) гоняет матрицу из двух профилей — `steam_deck medium touch` и `steam_big_picture` — с `VN_AUTOPILOT_SCREENS=main_menu,preferences,gallery,chapter_select` и кладёт шоты в артефакт `controller-shots-<profile>-<run_id>`. Гейта у неё нет намеренно: поломка вёрстки видна на картинке, а не в коде выхода. В `ci.yml` `RENPY_VARIANT` не задаётся и задаваться не должен — MR-пайплайн держим под 10 минут (G15), и это проверяет `test_ci_config.py`.

Чего этот прогон **не** проверяет: реального пада (событий `pad_*` в автопилоте нет), Steam-инициализации, оверлея, `dlc_installed`, экранной клавиатуры Deck. Пад и Steam проверяются только на живой машине — и прогон на самом Deck перед `setlive default` обязателен (`ci/steam/README.md`) и **в проекте ещё не выполнялся**. Полный QA-протокол — [43-steam-qa.md](43-steam-qa.md), специфика Deck — [41-steam-deck.md](41-steam-deck.md).

**Аварийный рычаг отладки, о котором легко не узнать.** `steam_init()` выходит без инициализации, если `config.enable_steam` ложно **или** в окружении есть `RENPY_NO_STEAM` (`00steam.rpy:1022-1026`; порядок проверок: сначала наличие библиотеки, `:1019-1020`, потом эти две). Это единственный способ прогнать сборку, у которой библиотека лежит рядом, как standalone — например чтобы сравнить ветки ownership-гейта.

---

## 8. Масштаб и типографика

Правило одно: **UI читает только `gui.*`, копий экранов не существует.** Один display-профиль вместо вариантов вёрстки.

| Токен | Значение | Где считается |
|---|---|---|
| `gui.ui_scale` | `1.0` или `VN_UI_SCALE_LARGE = 1.4` | `../../game/framework/20_ui/scale.rpy:23` (константа), `:41-55` (расчёт), `:70` (`define`) |
| `gui.overscan_pad` | `VN_SAFE_AREA_PAD = 48` в Big Picture **и на мобильном**, иначе `0` | `scale.rpy:36-39,79-80` |
| `gui.touch_min` | `120` (телефон) / `72` (планшет) / `0` (десктоп) — **пол** тач-зоны, не размер | `scale.rpy:25-34,57-65,83` |
| `persistent.vn_ui_scale` | `null` = авто, `"normal"`, `"large"` | `../../content/variables/settings.vars.yaml:11-15` |

Как считается масштаб (`scale.rpy:41-55`): выбор игрока сильнее платформы; при `null` (авто) — `1.4`, если `vn_platform.controller_first()` **или** `vn_platform.is_mobile()` (мелкий физический экран — те же 21 вирт. px на пятидюймовой стороне нечитаемы), иначе `1.0`.

Проверено прогоном движка (`renpy.sh . quit --json-dump` + лог), значения из строки `display:`: десктоп `ui_scale=1.00 overscan=0 touch_min=0`; телефон `1.40 / 48 / 120`; планшет `1.40 / 48 / 72`; Steam Deck `1.40 / 0 / 0` — регрессии Deck мобильная ветка не дала. Множитель применяется **в самих `define` в `gui.rpy`** (`../../game/gui.rpy:52-55` — комментарий-норма, `:58-64` — сами `round(N * gui.ui_scale)`): `interface 21 → 29`, `button 17 → 24`, `tiny 13 → 18` — интерфейс проходит порог читаемости Deck (~26–28 вирт. px строчных) и «10-foot» ТВ. Экраны при этом не трогаются **по построению**.

Переключение на лету — `vn.set_ui_scale(mode)` (`scale.rpy:52-57`): пишет `persistent` и зовёт `gui.rebuild()`, который перезапускает все `define gui.*` в исходном порядке и перестраивает стили; завершается `restart_interaction`, поэтому экран настроек переоценивает себя сам, без перезапуска игры. UI настройки — сегмент из трёх кнопок «авто / крупный / обычный» (`core_screens.rpy:326-349`).

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

**5. Поставка.** По образцу `release.py:150-326`: функция «сгенерировать манифест витрины из шаблона в `ci/<platform>/`» + функция «разложить артефакты `build/dist/` под её раскладку» + функция «чего не хватает на build-машине» (предупреждение, не ошибка). Команда в `cli.py` печатает путь к артефакту, аплоад не выполняет. Учтите урок §3.4: **сверяйтесь с фактическим форматом пакета движка** (`00build.rpy:421-432`), а не с предположением «всё zip», и тестируйте раскладку на настоящем архиве этого формата, а не на синтетическом zip.

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

## 10. Что штатный стек движка умеет, а мы не используем

Все строки ниже — **optional / future**, ничего из этого сегодня в проекте не подключено. Список нужен затем, чтобы не писать своё поверх того, что движок уже даёт (норма ADR-0014), и чтобы видеть дешёвые улучшения.

| Возможность движка | Где в SDK | Что даст у нас | Статус |
|---|---|---|---|
| **Steam Timeline** — фазы игры и режим в оверлее/клипах | `config.automatic_steam_timeline = True` по умолчанию (`00steam.rpy:28`); движок сам ставит game mode и читает `store.save_name` (`00steam.rpy:707-724`) | уже **включено движком**, но `save_name` в проекте не присваивается нигде (`grep save_name game/ tools/vn/src/` — ноль), поэтому в таймлайне видно только menu/playing. Присвоение имени главы — однострочное улучшение | NOT IMPLEMENTED (данные не поставляются) |
| **Прогресс-ачивки и статы** | `achievement.register` документирует `steam`, `stat_max`, `stat_modulo` (`00achievement.rpy:160-184`), плюс `progress` (`:248`), `grant_progress` (`:276`), `get_progress` (`:233`); у Steam-слоя — `indicate_achievement_progress` (`00steam.rpy:125`), `get/set_int_stat` (`:166`, `:183`), `retrieve_stats` / `store_stats` (`:43`, `:57`) | ачивки вида «прочитано N реплик»; сейчас `vn_ach` умеет только бинарные `grant`/`has` (§4) | NOT IMPLEMENTED |
| **Оверлей: магазин и веб-страница** | `activate_overlay_to_store(appid, flag)` (`00steam.rpy:375`), `activate_overlay_to_web_page` (`:366`) | предложение купить DLC вместо исчезнувшей карточки главы (§5) | NOT IMPLEMENTED |
| **Позиция тостов ачивок** | `achievement.steam_position` (движок по умолчанию ставит `POSITION_TOP_RIGHT`, `00steam.rpy:1047`) | сдвинуть тост, если он спорит с нашим UI на ТВ | не задаётся (дефолт движка) |
| **Имя текущей беты** | `achievement.steam.get_current_beta_name()` (`00steam.rpy:227`) | показать канал в crash-отчёте/дебаг-строке: «игрок на beta» | NOT IMPLEMENTED |
| **Steam Workshop** | `get_subscribed_items()`, `get_subscribed_item_path()` (`00steam.rpy:483-533`) | перечисление подписанных модов; стыкуется с `kind: mod` из `pack_manifest@1` | NOT IMPLEMENTED (моды — фаза 3, [30-packs-and-dlc.md](30-packs-and-dlc.md) §10) |
| **`overlay_enabled()`** | у нас **есть** в фасаде (`035_platform.rpy:43-48`) | «не показывать свой тост, когда открыт оверлей» | объявлено, потребителей ноль |

Правило подключения любой строки не меняется: код живёт только в `035_platform.rpy`, наружу выходит capability-метод, а недокументированные допущения закрываются контракт-тестом в `test_engine_compat.py` (G18).

---

## Как изменить / Как расширить

| Задача | Что править | Обязательно после |
|---|---|---|
| Включить Steam в этом репозитории | `project.yaml: platform.steam.appid` **и** отдельно `depots` (ключа в файле нет) | `vn build` (перегенерит `platform.gen.rpy`), `vn release steam --flavor public`, прогон на Deck. Номера берутся в Steamworks — [40-steamworks.md](40-steamworks.md) |
| Добавить формат архива или платформу в раскладку депотов (§3.4) | `_DIST_SUFFIX` (`release.py:158-162`) — суффикс + кортеж расширений по приоритету; `_extract_archive` (`:174-184`), если формат не zip и не tar.bz2 | кейс в `test_platform.py` с **реальным** архивом формата (как `test_steam_stage_content_unpacks_dist`, `:78-102`), формат сверять по `00build.rpy:421-432` |
| Отгружать в Steam не все три платформы | `project.yaml: platform.steam.depots` — оставить нужные номера; раскладка ожидает ровно объявленные (`release.py:287-288`) | `vn release steam --flavor <f>`: платформа без депота не должна давать `error` |
| Предлагать покупку DLC вместо пустоты при `owned() == False` | новый capability-метод в `035_platform.rpy` поверх `activate_overlay_to_store` (`00steam.rpy:375`) + кнопка в `screens/unavailable.rpy` | гард-тест единственной точки касания; проверять и standalone-ветку (метод обязан быть no-op) |
| Кормить Steam Timeline именами глав | движок делает это сам при `config.automatic_steam_timeline` (по умолчанию `True`, `00steam.rpy:28`), но читает `store.save_name` (`00steam.rpy:717-724`), которому в проекте нигде не присваивают | присваивать `save_name` там, где ставится `vn.checkpoint`; проверять в оверлее Steam |
| Привязать пак к DLC | `packs/<id>/manifest.yaml: steam_dlc_appid` | `vn pack validate`, `vn build`; проверить, что `owned()` даёт `False` без DLC |
| Добавить capability-запрос («открыт ли оверлей», «есть ли клавиатура») | только `035_platform.rpy` | потребитель в UI читает фасад, не движок; гард-тест `test_platform.py:183` должен остаться зелёным |
| Изменить крупный масштаб (1.4) | `../../game/framework/20_ui/scale.rpy:19` (`VN_UI_SCALE_LARGE`) | проверить 9-patch панели (минимум `2*Borders`) и `RENPY_VARIANT="steam_deck …" vn test smoke` |
| Поменять safe-area ТВ | `scale.rpy:42` | все три потребителя `gui.overscan_pad`: `quick_menu.rpy:17,19`, `gallery.rpy:143`, `build_overlay.rpy:15-16` |
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
- **Не ждать `vn release validate` проверки платформы** — в гейте из **20** проверок Steam-проверок нет ни одной; всё платформенное валидируется в `vn release steam` и тестах ([29-build-and-release.md](29-build-and-release.md) §5).
- **Не считать `vn release steam` проходящей целиком** — раскладка депотов работает (§3.4), но приложения в Steamworks нет: `appid: null` и ключа `depots` в `project.yaml` нет, поэтому команда честно падает exit 1 на первом же шаге. Аплоад делает человек через `steamcmd`, на живом Steam не проверялось ничего.
- **Не утверждать, что платформа «работает», на основании эмуляции вариантов** — `RENPY_VARIANT` заменяет список вариантов и не запускает ни Steam, ни пад (§7.1). Живого прогона на Windows, mac, Linux и Deck в проекте не было.

---

## Проверка

```bash
# Тулинг: эмиттер, VDF, раскладка депотов, статус библиотек, гард-тест фасада
python -m pytest tools/vn/tests/test_platform.py -q                 # 10 passed
python -m pytest tools/vn/tests -q                                  # 400 passed

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
vn release build --flavor public --package win --package linux --package mac
vn release steam --flavor public
ls build/steam/                                    # app_build_public.vdf + content/
#   в этом чекауте не проверить: appid=null и ключа depots нет -> exit 1 на первом шаге
#   (собирать все три платформы нужно только если все три депота объявлены — §3.4)

# Релизный гейт (платформенных проверок в нём нет — но он не должен покраснеть)
vn release validate --flavor public
```

Эталон на 2026-08-18: `platform.steam.appid: null`, `platform.gen.rpy` выключает Steam, `vn release steam --flavor public` завершается `ошибка: platform.steam.appid не задан в project.yaml …` (exit 1) — ожидаемое поведение репозитория без Steamworks-приложения. `test_platform.py` — 10 тестов, из них ни один не требует SDK; `test_steam_engine_contract` — skip без `RENPY_SDK`. Прогонов на живом Windows, mac, Linux и Steam Deck **не было** — их отсутствие и есть текущий статус QA (§2).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | [`../adr/0014-platform-services.md`](../adr/0014-platform-services.md) (**норматив**, читать целиком), `../../game/framework/00_core/035_platform.rpy` (весь файл — 89 строк), `../../game/framework/20_ui/{scale.rpy,input.rpy}`, `../../game/framework/20_ui/components.rpy:91-197`, `../../tools/vn/src/vn/release.py:150-326`, `../../tools/vn/src/vn/cli.py:1819-1852`, `../../tools/vn/src/vn/content/compile.py:133-152`, `../../ci/steam/README.md`, `../../project.yaml:13-15`, `$RENPY_SDK/renpy/common/00steam.rpy` (источник истины про штатный стек) и `$RENPY_SDK/renpy/common/00build.rpy:421-432` (форматы пакетов) |
| **Не трогать** | `game/generated/platform.gen.rpy` — генерат (`.gitignore`); `build/steam/**` — артефакт `vn release steam`; steam_api-библиотеки — их в репозитории нет и добавлять нельзя; дефолтные пад-биндинги движка (`00keymap.rpy` в SDK) |
| **Зависимости (что ломается ниже по течению)** | Правка `035_platform.rpy` → ачивки, ownership-гейт (`chapter_select`, галерея, ачивки), `controller_first()` → `gui.ui_scale` и `config.default_fullscreen`. Правка `scale.rpy` → **все** кегли `gui.*` и минимумы `2*Borders` панелей ADR-0009. Правка `input.rpy` → раскладка пада во всех контекстах. Правка `_emit_platform` → свежесть генерата (`vn build --check`) и `test_platform.py`. Добавление `steam_dlc_appid` → `VN_STEAM_DLC` и поведение `owned()` |
| **Валидация** | `python -m pytest tools/vn/tests/test_platform.py -q` → 13 passed → `python -m pytest tools/vn/tests -q` → 400 passed (без `RENPY_SDK` — 271 passed + 7 skipped) → `test_engine_compat::test_steam_engine_contract` (с `RENPY_SDK`) → `RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0` + просмотр `.vncache/smoke/` глазами → `vn release steam --flavor public` (при заполненном appid) → `vn release validate --flavor patron` (у `public` штатный FAIL по зрелости контента) |
| **Частые ошибки** | 1) Добавлять платформенное ветвление в экран или сцену — точка касания ровно одна, и это под тестом (`test_platform.py:183-193`). 2) Считать, что `owned()` по-прежнему всегда `True` — с ADR-0014 под Steam у пака с `steam_dlc_appid` он честно даёт `False`; описание «провайдера никто не подключает» в старых текстах устарело. 3) Читать `vn release steam` как аплоад — она только готовит VDF и раскладку депотов. 4) Ожидать Steam в локальной сборке: без steam_api в `$RENPY_SDK/lib/py3-*/` и с `appid: null` любая сборка — standalone, это норма. 5) Уменьшать `gui.ui_scale` (< 1.0) — ADR-0009 запрещает, сплющит панели. 6) Верить `../ARCHITECTURE.md` §6.7 про `steam_appid` в манифесте пака — поле называется `steam_dlc_appid`, а `steam_appid` схемой запрещён. 7) Искать Steam-проверку в релизном гейте — её там нет (и проверок в нём **20**, не 19). 8) Считать Steam Cloud недоделкой: кода нет осознанно (§6). 9) Утверждать, что `vn release steam` отработает целиком — раскладка депотов работает (§3.4), но `appid`/`depots` в `project.yaml` не заполнены, аплоад ручной, живого прогона не было. 10) Писать «Steam Deck поддержан и проверен» — проверена только вёрстка через `RENPY_VARIANT`; живого устройства не было, и это надо называть прямо |

---

**Смежные страницы:** [40-steamworks.md](40-steamworks.md) (процесс в Steamworks: App ID, депоты, ачивки, ветки, Cloud) · [41-steam-deck.md](41-steam-deck.md) (Deck: вёрстка, кегли, прогон) · [42-big-picture.md](42-big-picture.md) (ТВ, safe-area, «10-foot») · [43-steam-qa.md](43-steam-qa.md) (QA-протокол под Steam) · [44-how-do-i.md](44-how-do-i.md) («как мне…» одной строкой) · [29-build-and-release.md](29-build-and-release.md) (флейворы, гейт из 21 проверки, дистрибутивы, сквозной маршрут релиза) · [30-packs-and-dlc.md](30-packs-and-dlc.md) (формат пака, логический гейт G9) · [06-frontend.md](06-frontend.md) (токены `gui.*`, компоненты, панели ADR-0009) · [15-gallery.md](15-gallery.md) (подсистема достижений) · [27-testing.md](27-testing.md) (smoke-автопилот) · [33-security-and-legal.md](33-security-and-legal.md) (организационные сроки Steamworks, правовая рамка 18+)
