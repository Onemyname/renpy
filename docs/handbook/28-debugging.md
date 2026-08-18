# 28. Отладка: логи, дев-инструменты, крах, автопилот

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — диагностический инструментарий богатый и рабочий (`vn doctor`, `vn pipeline doctor`, 10+ проверяющих команд, in-process автопилот со скриншотами, crash-репорты с breadcrumbs), но всё это **pull-модель**: телеметрии, сбора логов у игроков и агрегации падений нет и не планируется.
> **Отвечает на вопрос:** «Что-то не работает — куда смотреть и какой командой сузить проблему до одного файла?»

Этот файл — про **инструменты диагностики**: где что логируется, чем прогнать игру без рук, как читать генерат и как локализовать поломку. Каталог «симптом → лечение» живёт отдельно: [36-troubleshooting.md](36-troubleshooting.md). Внутреннее устройство подсистем не пересказывается — ссылки на [05-renpy-development.md](05-renpy-development.md), [06-frontend.md](06-frontend.md), [07-backend.md](07-backend.md), [08-content-pipeline.md](08-content-pipeline.md).

## Быстрый ответ

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"   # в bash-сессии агента не наследуется

vn doctor                        # окружение: Python, git, git-lfs, корень, схемы, шрифты, SDK
vn content lint                  # декларации: схемы, имена, структура глав, битые exits
vn build --check                 # ничего не пишет: свеж ли генерат + разметка PO + бюджеты
vn test smoke --picks 0,0        # прогнать игру автопилотом; скриншоты в .vncache/smoke/
grep "\[vn\]" log.txt            # наши строки рантайма (снапшот, миграции, автопилот, стек)
cat errors.txt                   # ошибки парсинга скрипта (может быть УСТАРЕВШИМ — смотри дату)
```

| Симптом | Первая команда / первый файл |
|---|---|
| игра не запускается вообще | `vn doctor`, затем `errors.txt` |
| «сцена недоступна» / вылет в главное меню | `log.txt` → `[vn] scene stack invariant violated`, метка `vn_scene_unavailable` |
| правка в `game/generated/**` пропала | так и задумано — правьте `content/`, см. §6 |
| картинка не показывается | `game/generated/registry/images.gen.rpy` → `game/assets/…` → `assets_src/…` (§7) |
| на экране торчит `ui.gallery.locked` | строки нет в `content/ui/strings.yaml` или не прогнан `vn loc import` (§8) |
| сейв не грузится | `vn save check`, затем `vn save corpus` (§9) |
| CI красный, локально зелено | §10.1 |
| игра упала у игрока | `<savedir>/crash/crash-*.txt` (§3) |

---

## 1. Где что логируется

| Файл | Кто пишет | Режим | В git? | Что там |
|---|---|---|---|---|
| `log.txt` (корень проекта) | движок + наш `vn_log` | **перезаписывается при каждом запуске** (`renpy/display/__init__.py:61` — `open("log", developer=False, append=False)`) | нет (`.gitignore:15`) | тайминги старта, инфо о GPU/дисплее, строки `[vn] …` |
| `errors.txt` | движок | перезапись при ошибке парсинга | нет (`.gitignore:16`) | ошибки разбора `.rpy` — игра до рантайма не доходит |
| `traceback.txt` | движок | перезапись при необработанном исключении | нет (`.gitignore:17`) | последний трейсбек; `vn test smoke` удаляет файл ДО прогона (`cli.py:1318-1320`), поэтому его появление = сигнал падения |
| `<savedir>/crash/crash-*.txt` | наш `070_crash.rpy` | новый файл на каждое исключение, хранятся 10 последних | нет (вне репозитория) | build id, флейвор, версия, **breadcrumbs меток** + трейсбек |
| `.vncache/smoke/**` | `vn test smoke` | каталог полностью пересоздаётся | нет (`.gitignore:21`) | скриншоты, `RESULT.txt`, `picks.log`, `state.json`, `gallery.json`, `startup.txt` |
| `.vncache/analyze-*.json` | build-bridge | контентно-адресуемый кэш | нет | результат разбора авторских `.rpy` парсером Ren'Py |

Каталог сейвов на машине владельца — `C:\Users\Vadim\AppData\Roaming\RenPy\vn-1755000000` (из `define config.save_directory = "vn-1755000000"`, `../../game/options.rpy:7`).

### 1.1. Строки `[vn]` — наш единственный канал логов

`vn_log(msg)` (`../../game/framework/00_core/001_boot.rpy:25-27`) — обёртка над `renpy.write_log("[vn] %s", msg)`. Поэтому диагностика рантайма всегда начинается с `grep "\[vn\]" log.txt`. Реальные строки из живого `log.txt`:

```
[vn] language -> ru
[vn] snapshot: ch01.division пропущен (не-простой тип _Feature)
[vn] snapshot: g.basestring пропущен (не-простой тип tuple)
```

Кто пишет `[vn]`-строки — **исчерпывающий** список (`grep -rn vn_log game/framework/`):

| Строка | Источник | Что означает |
|---|---|---|
| `language -> <code>` | `040_localization.rpy:123` (из `_notify`, вызывается хуком `config.language_callbacks[lang]`) | язык переключился; отсутствие строки при клике = хук не зарегистрирован |
| `snapshot: <store>.<var> пропущен (не-простой тип …)` | `020_state.rpy:43-44` | переменная не попадёт в сейв-снапшот. **12 таких строк на каждый снапшот — это норма** (`__future__._Feature` и `basestring` внутри named stores), не баг вашей переменной |
| `migration NNNN` / `migration chain gap: A -> B` / `migrations incomplete: …` | `020_state.rpy:72-73,105-106` | ход миграций при загрузке сейва |
| `scene stack invariant violated: depth=N` | `030_flow.rpy:48` | на границе сцены call-стек не пуст. **Только логируется, не чинится** |
| `achievement unknown: <id>` / `achievement provider failed for <id>: …` | `080_achievements.rpy:51,62` | `grant()` с незарегистрированным достижением или падение внешнего провайдера — логируется, игра не падает |
| `autopilot screenshot failed` / `autopilot: fixture save at tick N` / `autopilot screen X failed` / `autopilot state dump failed` / `autopilot gallery dump failed` | `030_flow.rpy:123,127,184,200,210` | ход и проблемы прогона `vn test smoke` |
| `vn_lang: битый манифест …` / `vn_lang: сохранённый язык … исчез — сброс на исходный` / `vn_lang: подписчик … упал` | `040_localization.rpy:44,74,128` | проблемы языкового пакета `game/tl/<code>/language.json` и подписчиков смены языка |

### 1.2. Стартовый лог: чем мерить холодный старт

Первые строки `log.txt` — самодиагностика движка (реальный прогон):

```
2026-08-08 12:47:16 UTC
Windows-11-10.0.26200-SP0
Ren'Py 8.5.3.26051504

Early init took 22 ms
Loading script took 67 ms
Running init code took 21 ms
Creating interface object took 112 ms
[vn] language -> ru
Interface start took 91 ms
```

Как этим пользоваться:

- **`Loading script`** растёт от количества `.rpy`/`.rpyc` — сюда бьют новые главы и генерат.
- **`Running init code`** — суммарное время всех `init`-блоков; сюда бьют тяжёлые вычисления в `init python`.
- **`Creating interface object`** — инициализация окна/рендерера, от кода проекта почти не зависит.
- Эти тайминги — **не** бюджет `cold_start_s`. Бюджет считает автопилот: от инициализации store `vn_qa` (`_T0`, `030_flow.rpy:96`) до первого тика, и пишет секунды в `.vncache/smoke/startup.txt` (`030_flow.rpy:115-118`). Гейт — в `cli.py:1384-1392` против `project.yaml: budgets.cold_start_s` (сейчас `30`; на RTX 5080 реальное значение **1.13 c**, комментарий в `project.yaml:9` даёт референс CI-раннера ~14 c).

### 1.3. Дополнительные логи движка (не включены)

Ren'Py умеет писать ещё несколько файлов, ни один из них проектом не включён — **это приёмы, а не механизмы проекта**:

| Файл | Как включить | Зачем |
|---|---|---|
| `text_overflow.txt` | `config.debug_text_overflow = True` (`renpy/text/text.py:1139-1148`) | строка не влезла в отведённую область: файл, строка, `Available` vs `Laid-out`. Идеальная пара к прогону `--lang pseudo` (§5.4) |
| `image_cache.txt` | `config.debug_image_cache = True` | промахи кэша образов |
| `profile_screen.txt` | `config.profile_screen` / `renpy.profile_screen` | время предсказания и отрисовки экранов |
| `trace.txt` | `renpy.exe . --trace 1` (или `2`) | пооператорная/построчная трассировка |

> **Грабля.** Все они пишутся **в корень репозитория и НЕ покрыты `.gitignore`** (там перечислены только `log.txt`, `errors.txt`, `traceback.txt` — `.gitignore:15-17`). Включили — удалите файл перед коммитом. Из дистрибутива их вырезает сам Ren'Py (`base_patterns` лаунчера), но не из git.

---

## 2. Дев-инструменты внутри игры — **IMPLEMENTED**

### 2.1. Что доступно и по каким клавишам

Всё ниже проверено по пиннованному SDK 8.5.3 (`renpy/common/00keymap.rpy`) и по коду проекта.

| Клавиша | Что | Гейт | Источник |
|---|---|---|---|
| **Shift+O** | консоль Ren'Py (eval/exec в контексте игры) | `config.console or config.developer` (`00console.rpy:427`) | `../../game/framework/90_debug/010_dev.rpy:7-8` — `config.console = True` **безусловно** |
| **Shift+D** | Developer Menu | `config.developer` | движок, `renpy/common/_developer/developer.rpym:27` |
| **Shift+J** | наше QA-меню прыжка по сценам | `config.developer` | `../../game/framework/90_debug/020_jump_menu.rpy:5-11` |
| **Shift+R** | перезагрузка скрипта на месте | `config.developer` | движок; в `vn dev` это основной цикл (`cli.py:229-230`) |
| **Shift+I** / **Alt+Shift+I** | инспектор displayable / полный инспектор | `config.developer` | `00keymap.rpy:48-49` |
| **F4** | Image Load Log | `config.developer` | `00keymap.rpy:156` |
| **Shift+E** | открыть текущую строку в редакторе | `config.developer` | `00keymap.rpy:45` |

Пункты Developer Menu (Shift+D) — прямо из SDK: Interactive Director, Reload Game, Console, **Variable Viewer**, **Persistent Viewer**, Image Location Picker, Filename List, Show Image Load Log, **Image Attributes**, Show Translation Info, Speech Bubble Editor. Для этого проекта самые полезные — Variable Viewer (видно `ch01.*`, `g.*`, `vn_scene`, `vn_menu`) и Persistent Viewer (`persistent.vn_gallery_unlocked`, `persistent.vn_achievements`).

### 2.2. Shift+J — что именно показывает

`screen vn_debug_jump` (`020_jump_menu.rpy:14-32`) рисует `vpgrid cols 4` по реестру `VN_SCENES` и прыгает через `Function(renpy.jump_out_of_context, sc["label"])`. Реестр сейчас — 4 сцены, **включая главу из пака**:

```renpy
define VN_SCENES = ({'id': 'ch01_s010', 'label': 'ch01_s010', 'chapter': 'ch01'}, …,
                    {'id': 'ch90_s010', 'label': 'ch90_s010', 'chapter': 'ch90'})
```
(`game/generated/registry/scenes.gen.rpy:9`)

Экран честно предупреждает: `Состояние глав НЕ выставляется — переменные останутся текущими` (`:22`). То есть прыжок в `ch01_s030` не выставит `ch01.met_mira` — сцена с условным текстом покажет не ту ветку. Для проверки ветвления нужен не Shift+J, а `--picks` (§5).

### 2.3. Почему этого нет в релизе

Два независимых механизма:

1. **`config.developer` вычисляется движком.** Значение по умолчанию — `"auto"`; движок разрешает его в `renpy/common/00library.rpy:353-360`: `config.developer = True`, если `config.script_version` пуст (запуск исходников через SDK), и `False` в собранном дистрибутиве. Проект `config.developer` нигде не присваивает — только читает (`crash_screen.rpy:48,64`, `040_localization.rpy:82`, `020_jump_menu.rpy:6`).
2. **Файлы вырезаются из сборки** (`../../game/options.rpy:24-26`):
   ```renpy
   build.classify("game/framework/90_debug/**", None)
   build.classify("game/generated/qa/**", None)
   build.classify("game/generated/manifest.json", None)
   ```

**Дефект (PARTIAL).** `config.console = True` в `010_dev.rpy:8` — безусловное, рантайм-гейта нет. Единственная защита — `build.classify`. Регрессия в упаковке (например, кто-то удалил строку `:24`) откроет игроку консоль в релизе. Комментарий `010_dev.rpy:4-6` объясняет, почему нельзя написать `config.console = config.developer`: в init-фазе `developer` ещё строка `"auto"`, то есть truthy. Правильное исправление — не в init-фазе, а поздним `init 999`-гейтом; сейчас **NOT IMPLEMENTED**.

Проверить, что dev-инструменты не уехали в релиз, можно по распакованному дистрибутиву:

```bash
vn release build --flavor public --package win
ls build/dist/0.1.4-public/            # ни framework/90_debug/, ни generated/qa/
```

---

## 3. Обработка краха — **IMPLEMENTED**

Цепочка (детали устройства — [07-backend.md](07-backend.md) §крах, экран — [06-frontend.md](06-frontend.md)):

1. **Breadcrumbs.** `config.label_callbacks.append(_vn_crash_breadcrumb)` (`../../game/framework/00_core/070_crash.rpy:25`) кладёт `(HH:MM:SS, метка)` в `deque(maxlen=40)`, служебные метки движка (`_*`) отфильтрованы (`:22`).
2. **Строка в `log.txt`.** `vn_crash_write_report(te)` первым делом пишет `[vn] unhandled exception: <Тип: сообщение>` (`:41-52`) — отдельным `try`, до записи отчёта, чтобы недоступный `savedir` не украл ещё и эту строку.
3. **Отчёт.** Дальше (`:53-79`) пишется `<savedir>/crash/crash-YYYYmmdd-HHMMSS.txt`, путь кладётся в `_vn_last_crash_report`, каталог подрезается до 10 последних. Возвращает `False` (`:80`) → показ экрана остаётся движку.
4. **Экран.** Движок подхватывает наш `screen _exception` (`../../game/framework/20_ui/screens/crash_screen.rpy:37`). Игрок видит: заголовок, «Прогресс до последнего сохранения не пострадал», **путь к отчёту**, кнопки «Откатиться назад» / «Попробовать продолжить» / «Закрыть игру». Сырой трейсбек и кнопка Reload — **только при `config.developer`** (`:66-90,115`).

**Экран доступен с геймпада (новое).** Первый фокус — на «Откатиться назад» (`default_focus 2`), «Попробовать продолжить» — `1`, «Закрыть игру» и dev-only Reload — без свойства: слепой A уходит в самое безопасное действие, а не в потерю сессии. Трейсбек листается dpad'ом (`arrowkeys True`) и плечами (`pagekeys True`). Кегли поднялись до верхнего профиля масштаба (40/24/21/20, кнопки 29) — экран читается с дивана. Всё это на **числовых литералах**, и это единственное такое место в `20_ui`: токены `gui.*` объявляются на `init -3/-2`, а экран краха обязан выжить при падении более раннего init'а. Инвариант «ноль обращений к `gui.*`» и нижняя граница кеглей ≥ 18 проверяются `tools/vn/tests/test_crash_handler.py` (6 тестов). Разбор — [42-big-picture.md](42-big-picture.md) §5.3.

**B/Esc экран не закрывают, и это не дефект вёрстки:** движок показывает `_exception` через `renpy.ui.interact(..., suppress_underlay=True)` (`$RENPY_SDK/renpy/display/error.py:45`), то есть keymap-underlay в этой интеракции отсутствует и `game_menu` обработать некому. Выход с пада существует: dpad до «Закрыть игру», затем A.

**Латентный дефект, исправленный по ходу: трейсбек в dev-режиме не рисовался вообще.** Причина — `scrollbars "vertical"` без явных визуалов полосы. Картинок скроллбара в проекте нет (ADR-0009: фоны генерируются), а пресет `vn_scroll_props` считает свои `Solid` от `gui.*`, которые этому экрану запрещены; движковый дефолт полосы пуст, и side-раскладка отдавала вьюпорту **нулевую площадь**. Теперь визуалы полосы заданы литералами (`crash_screen.rpy:85-89`). Общее правило для любой скролл-зоны: `viewport`/`vpgrid` со `scrollbars`, но без `vscrollbar_base_bar`/`thumb`, рисуется **пустым** — берите `properties vn_scroll_props` ([06-frontend.md](06-frontend.md)).

**Контракта `vn_qa` в экране краха нет намеренно.** `vn_qa` объявляется на `init -999` в `030_flow.rpy`; обращение к нему из последнего эшелона нарушило бы инвариант выживания. Последствие: падение под автопилотом висит до таймаута — и `vn test smoke` это ловит, печатает `traceback.txt` и валит прогон.

Реальный отчёт из `C:\Users\Vadim\AppData\Roaming\RenPy\vn-1755000000\crash\` (сокращён):

```
build: 0.1.1+99e50a9.public.202608081032
flavor: public
version: 0.1.1+99e50a9
renpy: Ren'Py 8.5.3.26051504
time: 2026-08-08 13:35:36

Последние метки (breadcrumbs):
  13:35:36  main_menu_screen

Traceback (most recent call last):
  File "renpy/common/_layout/screen_main_menu.rpym", line 28, in script
  …
```

Что это даёт при разборе жалобы игрока: строка `build:` однозначно привязывает падение к сборке и флейвору (формат `<version>+<sha>.<flavor>.<YYYYmmddHHMM>`, `release.py:278`), breadcrumbs дают путь по меткам, которого в голом трейсбеке нет.

**Что просить у игрока:** файл из `crash/` — этого достаточно; `log.txt` бесполезен, если игра уже перезапускалась (перезаписывается).

**Строку `[vn] unhandled exception: …` в `log.txt` искать можно** — она пишется (`070_crash.rpy:50`). Раньше не писалась: `001_boot.rpy` ставил свой обработчик со старой трёхаргументной сигнатурой на `init -999`, а `070_crash.rpy` на `init -950` переприсваивал `config.exception_handler` — поле одно, побеждало второе, боотовый блок был мёртвым кодом. Теперь обработчик один, логирование живёт в нём, а в `001_boot.rpy:38-49` остался комментарий-указатель. Регрессия закрыта тестом: `tools/vn/tests/test_crash_handler.py` (**6 тестов**) статически проверяет по `game/framework/**/*.rpy`, что присваивание `config.exception_handler` ровно одно и именно в `070_crash.rpy`, что обработчик пишет строку в лог и возвращает `False`, а также лестницу default-фокуса экрана, наличие `arrowkeys`/`pagekeys` у вьюпорта трейсбека, отсутствие обращений к `gui.*` и нижнюю границу кеглей. Помните ограничение: `log.txt` перезаписывается на каждом старте, поэтому если игра уже перезапускалась — единственный источник это отчёт из `crash/`.

---

## 4. Диагностика сборки: какая команда на какой вопрос отвечает

Все команды — из единственного CLI (`../../tools/vn/src/vn/cli.py`), exit-коды: `0` ок / `1` ошибка проверки / `2` usage / `3` «не реализовано в этой фазе».

| Команда | Отвечает на вопрос | Что делает и где | Статус |
|---|---|---|---|
| `vn doctor` | «у меня вообще правильно настроена машина?» | 8 проверок: Python ≥ 3.10, git, git-lfs, корень репозитория, `project.yaml/min_tools`, реестр схем, шрифты UI (детект LFS-указателей по магическим байтам), SDK + сверка с пином `renpy_sdk`. Девятая строка (`!`, warning) появляется, только если существует `.vnstorage.local.yaml` (`doctor.py:104-106`). Каждая неудача печатает рецепт `→ …` (`doctor.py:69-153`) | IMPLEMENTED |
| `vn pipeline doctor` | «почему не рендерится / не кодируется?» | PASS/WARN/FAIL по ffmpeg+VP9, GPU/VRAM, CUDA/PyTorch, ComfyUI и моделям, DAZ, дискам, SDK (`pipeline.py`) | IMPLEMENTED |
| `vn content lint` | «декларации валидны?» | схемы, конвенции имён, структура глав, битые `exits`, бюджет бинарей `assets_src/` (ADR-0004). `--layout` (по умолчанию вкл.) сверяет структуру каталогов (`tools/vn/src/vn/content/lint.py`) | IMPLEMENTED |
| `vn build --check` | «мой генерат отстал от `content/`?» | lint → `build_assets(check=True)` → `compile_content(check=True)` → разметка PO → бюджеты G19. **Ничего не пишет.** Печатает `устарело: <файл>` по каждому расхождению (`cli.py:101-144`) | IMPLEMENTED |
| `vn content compile --check` | то же, но **без lint и без ассетов** | быстрее, ловит контракт авторских `.rpy` (метки, `return`↔`exits`) (`cli.py:399-422`) | IMPLEMENTED |
| `vn content graph` | «куда вообще ведут переходы?» | Mermaid-граф сцен с условиями и тупиками. **Читает только `content/chapters/`** — главы паков в граф не попадают (`tools/vn/src/vn/content/graph.py:15`) | PARTIAL |
| `vn assets validate` | «почему картинка/трек не подхватились?» | два уровня: сырцы (конвенции, обязательные `base.png`, свежесть выходов) + контент (реестр образов, треки). Несвежесть выхода — **warning**, не ошибка (`cli.py:522-547`) | IMPLEMENTED |
| `vn assets video inspect <файл>` | «что за видео у меня собралось?» | контейнер/кодек/pix_fmt/размер/fps/длительность/размер + дамп сайдкаров `*.meta.json` и `*.provenance.json` (`cli.py:630-647`) | IMPLEMENTED / UNDOCUMENTED в `docs/` |
| `vn assets video validate [пути]` | «луп рвётся / бюджет превышен?» | строгая проверка кодека, пикселей, fps, шва лупа, бюджета `video_file_mb` (`cli.py:586-627`) | IMPLEMENTED |
| `vn assets cache --dry-run --gc` | «почему `.vncache` распух?» | размер `.vncache/assets` + mark&sweep от манифеста сборки; `--dry-run` только показывает (`cli.py:744-764`) | IMPLEMENTED |
| `vn loc keys --check` | «текст поменяли, а id не выдали?» | все ли say/menu имеют id и свеж ли ledger; печатает `расхождение: …` (`cli.py:966-993`). Это гейт CI (`ci.yml:70`) | IMPLEMENTED |
| `vn loc report` | «перевод отстал?» | покрытие и fuzzy по языкам. Флагов `--gate/--format` нет — гейтинг живёт только в релизном гейте (`release.py:475-501`) | PARTIAL |
| `vn save check` | «фикстуры сейвов целы?» | оффлайн, без unpickle: zip → член `json` → `vn_save_schema`/`vn_version`/`vn_scene` (`cli.py:1099-1124`) | IMPLEMENTED |
| `"$RENPY_SDK/renpy.exe" . lint` | «движок ругается на скрипт/стили?» | родной lint Ren'Py по `game/**` (framework + генерат). В CI — `ci.yml:73` | IMPLEMENTED (движок) |

Реальные выводы (прогон 2026-08-08):

```
$ vn save check
 ✓ schema1-demo.save: schema 1, версия 0.1.4+dd1cb3e, сцена ch01_s010
 ✓ schema2-demo.save: schema 2, версия 0.1.0+48d19a3, сцена ch01_s020
save check: OK (2 фикстур)

$ vn assets cache
кэш: 0.1 МБ (C:\Users\Vadim\IdeaProjects\renpy\.vncache\assets)

$ vn loc report
de: 136/136 (100%), fuzzy: 0
en: 136/136 (100%), fuzzy: 0
pseudo: 136/136 (100%), fuzzy: 0

$ vn assets status
манифестов нет — сырцы ещё не пушились (vn assets lock + push)
```

**Чего НЕТ** (в `docs/ARCHITECTURE.md` упоминается, кода нет): `vn build --use-artifact <sha>` (14 упоминаний в ARCHITECTURE.md — **NOT IMPLEMENTED**), группы `vn validate` вообще нет, `vn content lint --strict/--arch/--schemas` нет (только `--layout/--no-layout`), `vn test perf` нет.

---

## 5. Автопилот как отладчик — **IMPLEMENTED**

`vn test smoke` — единственный поддерживаемый способ прогнать игру автоматически (норма G23: синтетический ввод на рабочий стол запрещён). Механика прогона и покрытие — в [27-testing.md](27-testing.md); здесь — **как этим отлаживать**.

### 5.1. Запуск и что появляется

```bash
vn test smoke --picks 0,0                 # первая опция в каждом меню
vn test smoke --picks 0,1 --lang en       # другая ветка + другой язык
vn test smoke --picks 1 --timeout 300     # длинный прогон
```

Флаги ровно три: `--picks`, `--lang`, `--timeout` (по умолчанию 180 с) — `cli.py:1347-1350`. После прогона `.vncache/smoke/` содержит (реальный прогон):

| Артефакт | Содержимое живого прогона | Как читать |
|---|---|---|
| `RESULT.txt` | `OK: vn_end_of_content` | вердикт. `FAIL: vn_scene_unavailable` = переход упёрся в несуществующий exit |
| `picks.log` | `menu 0 -> pick 0 (ch01_s010_m001)`<br>`menu 1 -> pick 1 (ch01_s020_m001)` | **фактический** путь: номер меню, выбранный индекс, id меню. Если строк меньше, чем ожидали, — часть меню не показалась |
| `startup.txt` | `1.13` | cold start в секундах, гейтится против `budgets.cold_start_s` |
| `state.json` | `{"ch01.met_mira": true, "g.route": "prologue", "vn_save_schema": 2, …}` | снимок состояния на выходе — чем проверять, что флаг реально выставился |
| `gallery.json` | `{"unlocked": 4, "total": 5, "ids": [...]}` | доехали ли разблокировки до `persistent` |
| `shot000.png … shot020.png` | 21 кадр | покадровая лента прохождения |
| `screen_gallery.png` | есть | снимок экрана `gallery` — см. 5.3 |

### 5.2. Семантика `--picks` и `--lang`

- `--picks` — **по одному индексу на меню, в порядке появления** (`030_flow.rpy:137-141`). Кончились — дальше берётся `0`. Индекс клампится `min(idx, len(items)-1)`; если выбранный пункт недоступен, берётся первый доступный.
- `--lang` требует существующего `game/tl/<code>/`, иначе команда падает с явным сообщением — «`change_language` молча показал бы исходный язык — ложно-зелёный прогон» (`cli.py:1365-1367`).
- Исходный язык (`ru`) переписывается в сентинел `@source` (`cli.py:1361-1364`), который в рантайме означает `renpy.change_language(None)` (`030_flow.rpy:156-159`) — явный сброс языка, оставшегося от прошлых прогонов в `persistent`. Сентинел **нигде в `docs/` не документирован**.

### 5.3. Скриншоты экранов меню — IMPLEMENTED / UNDOCUMENTED

`vn_qa.autopilot_screens()` (`030_flow.rpy:166-184`) показывает перечисленные в `VN_AUTOPILOT_SCREENS` экраны, снимает `screen_<name>.png` и прячет их. Вызывается из `label vn_end_of_content` перед завершением, то есть **после** всех разблокировок. **Ни один флаг CLI эту переменную не выставляет** — она только наследуется из окружения:

```bash
VN_AUTOPILOT_SCREENS=gallery,achievements,preferences vn test smoke --picks 0,0
```

Наличие `.vncache/smoke/screen_gallery.png` доказывает, что приём использовался. Это единственный способ увидеть вёрстку меню/галереи в автоматическом прогоне: сцены эти экраны не открывают, а `renpy lint` визуальные поломки не видит.

### 5.4. Ловля переполнений UI псевдолокалью

```bash
vn loc pseudo                              # пересобрать synthetic-пакет
vn test smoke --picks 0,0 --lang pseudo    # прогон на удлинённых строках
```

Дальше глазами по `.vncache/smoke/shot*.png`. Псевдолокаль — dev-only (`vn_lang.available()` по умолчанию гейтится на `config.developer`, `040_localization.rpy:78-82`) и вырезается из дистрибутива по манифесту `language.json: synthetic` (`options.rpy:29-40`). Пара к этому приёму — `config.debug_text_overflow` (§1.3), который даст файл и строку вместо «кажется, вылезло».

### 5.5. Ловля регрессий ветвления

Матрица из nightly (`.github/workflows/nightly.yml:55-60`) — готовый локальный чеклист:

```bash
vn test smoke --picks 0,0
vn test smoke --picks 0,1 --lang en
vn test smoke --picks 1
vn test smoke --picks 0,0 --lang pseudo
```

Сравнивайте `picks.log` и `state.json` между прогонами: разошёлся набор ключей в `state.json` — поехали переменные; в `picks.log` меньше строк — меню перестало показываться; `RESULT.txt` = `FAIL: vn_scene_unavailable` — сцена вернула exit, которого нет в `scene.yaml`.

### 5.6. Грабли автопилота

- Прогон **пишет** `game/generated/qa/autopilot.gen.rpy` и удаляет его в `finally` (`cli.py:1336-1343`). Осиротевший `.rpyc` от жёстко убитого прогона обезврежен двумя слоями: пречистка каталога и гейт `VN_AUTOPILOT` внутри самого файла.
- Не запускайте `vn test smoke` параллельно со своей игрой: по таймауту убивается **всё дерево процессов** (`taskkill /T /F` на Windows, `killpg` на POSIX — `cli.py:1328-1334`).
- Автопилот кликает меню **таймером**, а не выражением экрана (`choice.rpy:53-54`), и `autopilot_choose` обязан вернуть `renpy.run(action)` — иначе интеракция меню не завершается и прогон висит до таймаута (`030_flow.rpy:148-150`). Не «оптимизируйте» этот блок.
- Автопилот подменяет `label main_menu` (`cli.py:1268-1282`): движок вызывает `main_menu` в **отдельном контексте**, и `return` из него означает «стартуем игру» (`renpy/common/00start.rpy:294-306,336-337`). Поэтому оверлей-таймер автопилота живёт уже в игровом контексте, а не в меню.

---

## 6. Отладка генерата

### 6.1. Как читать шапку

Каждый файл в `game/generated/**` начинается блоком (реальный `version.gen.rpy`):

```
# ══════════════════════════════════════════════════════════════
# AUTO-GENERATED by vn content compile (vn 0.1.0)
# source: project.yaml  blake3:ea0d07e22f349b8c
# НЕ РЕДАКТИРОВАТЬ. Правки перезапишутся. Меняйте источник.
# ══════════════════════════════════════════════════════════════
```

`source:` — **список файлов-источников этого конкретного выхода** с первыми 16 hex blake3 (`tools/vn/src/vn/content/compile.py:56-62`). Это первый ответ на вопрос «откуда взялась эта строчка»: сверху написано, какой YAML править. У `images.gen.rpy` источник — `content/characters/mira/character.yaml`, у `chapters.gen.rpy` — `project.yaml`, и так далее.

### 6.2. Как понять «генерат устарел»

Свежесть определяется **побайтовым сравнением выходов**, а не датами и не хэшами входов:

```bash
vn build --check
# устарело: registry/images.gen.rpy
# ошибка: генерат не свеж — выполните vn build
```

Механика (`tools/vn/src/vn/content/compile.py:1168-1178`): выходы считаются в память и сравниваются с диском; сироты прошлого манифеста помечаются `(осиротел)`. `game/generated/manifest.json` (`schema: gen_manifest@1`, 36 входов / 21 выход) хранит blake3 и входов, и выходов, но **`inputs` никогда не читается обратно** — это документация, а не механизм инвалидации.

Важная деталь: `version.gen.rpy` содержит `define config.version = "0.1.4+<sha>"` — git-sha **внутри генерата**. На свежесть он не влияет: при сравнении sha нормализуется (`_stale_key` в `tools/vn/src/vn/content/compile.py`), потому что это метаданные сборки, а не контент. Поэтому красный `--check` теперь означает ровно одно — генерат отстал от источников; коммит сам по себе его не красит. Бамп semver в `project.yaml` без пересборки при этом ловится.

### 6.3. Кэш разбора авторских `.rpy`

`.rpy` разбираются только парсером Ren'Py через build-bridge (норма G24). Результат кэшируется в `.vncache/analyze-<24hex>.json`; ключ = версия тулинга + байты `050_build_bridge.rpy` + пути и байты всех разбираемых файлов (`tools/vn/src/vn/content/analyze.py:42-56`). Следствия:

- Правка авторского `.rpy` инвалидирует кэш автоматически — «залипшего» анализа не бывает.
- Если подозреваете именно мост: удалите `.vncache/analyze-*.json` и пересоберите; падение моста печатается как `build-bridge (renpy vn_analyze) упал: код N` с хвостами stdout/stderr (`analyze.py:62-66`).
- Тёплый кэш **маскирует отсутствие SDK** — поэтому `vn doctor` делает пропажу SDK жёсткой ошибкой, если в `content/chapters/` есть главы (`doctor.py:119-142`).

### 6.4. Почему нельзя править генерат

`game/generated/`, `game/assets/`, `game/tl/` не в git (`.gitignore:2-4`) и перезаписываются сборкой; сироты **удаляются** вместе с `.rpyc` (`tools/vn/src/vn/content/compile.py:892-897`). Правка живёт до ближайшего `vn build`, а на чужой машине её не существует вовсе. Правильный маршрут — [08-content-pipeline.md](08-content-pipeline.md).

Отладочный приём, который **можно**: посмотреть в генерат, чтобы понять, что именно исполняется. Эталон обвязки сцены — `game/generated/scenes/ch01/ch01_s020.gen.rpy:8-18`: `vn.checkpoint` → `renpy.scene("sprites")` → `scene bg … with dissolve` → `call …__body` → `vn.check_scene_stack()` → диспетчер `_return` → `vn.unwind_call_stack(); jump vn_scene_unavailable`.

---

## 7. Отладка ассетов: «картинка не показалась»

Проверяйте строго по цепочке, сверху вниз — первая же дырка и есть причина.

```bash
# 1. Есть ли image-стейтмент вообще?
grep -n "rooftop" game/generated/registry/images.gen.rpy
#    image bg rooftop day = "assets/bg/rooftop/day.webp"

# 2. Есть ли файл в собранной зоне?
ls game/assets/bg/rooftop/

# 3. Есть ли сырец и валиден ли он?
ls assets_src/          # зоны сырцов
vn assets validate      # конвенции имён + свежесть выходов + реестр образов

# 4. Пересобрать и посмотреть счётчики
vn assets build         # assets: N собрано, N из кэша, N актуально, N осиротевших удалено
vn build
```

Что означает каждая ступень:

| Ступень | Пусто → причина |
|---|---|
| нет строки в `images.gen.rpy` | декларация не дошла до компилятора: локация/персонаж не объявлены, либо файл не подходит под конвенцию имён. Автоопределение образов **выключено** (`config.images_directory = None`, `001_boot.rpy:17`) — движок не подхватит «просто положенный» файл |
| строка есть, файла в `game/assets/` нет | ассеты не собраны или удалены как сироты; `vn assets build` |
| файла нет и в `assets_src/` | сырца просто нет. Локально это не видно, потому что бинари живут во внешнем хранилище: `vn assets status` (сейчас — «манифестов нет — сырцы ещё не пушились») |
| всё есть, но кадр пустой | смотрите имя образа: `image bg rooftop day` = три слова, `scene bg rooftop day`. Спрайты — `layeredimage` с оверсэмплингом `@2` |

Дополнительно: `.vncache/assets-manifest.json` — манифест собранных выходов; удаление орфанов из `game/assets` целиком построено на диффе с ним, и **потеря манифеста навсегда отключает удаление** (`tools/vn/src/vn/assets/pipeline.py:393-433`). При записи манифест с 2026-08-08 проверяется схемой `assets_manifest@1` из реестра (`pipeline.py:441-454`), а вот на **чтении** исключения по-прежнему глотаются — битый файл выглядит как «нечего удалять». Кэш блобов чистится `vn assets cache --gc`. Подробности зон и именования — [16-assets.md](16-assets.md).

---

## 8. Отладка локализации

**Симптом: на экране написано `ui.gallery.locked` вместо текста.** Это не баг движка, а штатный fallback: `vn_loc.t(key)` возвращает **сам ключ**, если его нет ни в переводе, ни в исходнике (`040_localization.rpy:151-157`). Причины ровно две:

1. Ключа нет в `content/ui/strings.yaml` → добавить и `vn build`.
2. Ключ есть, но `game/tl/` не пересобран → `vn loc import` (или просто `vn build` — он вызывает импорт сам, `cli.py:151`).

**Симптом: выбор не переводится.** Проверьте, что экран зовёт `vn_loc.choice_text(vn_menu, idx, i.caption)`, а не `i.caption` (`choice.rpy:47`). Fallback здесь — авторский caption, то есть исходный язык: поломка выглядит как «частично перевелось».

**Подмена языка в рантайме.** Быстрее всего — через консоль (Shift+O):

```python
renpy.change_language("de")     # переключить
renpy.change_language(None)     # вернуться на исходный (ru)
vn_lang.current()               # что сейчас
vn_lang.available()             # список пакетов (pseudo виден только в dev)
```

Смена языка обязана оставить строку `[vn] language -> <code>` в `log.txt` — нет строки, значит не сработал хук `config.language_callbacks[lang]` (`040_localization.rpy:47`). **`config.change_language_callbacks` в Ren'Py 8.5 мёртв** — если кто-то «починил» подписку через него, она не вызывается никогда.

Покрытие и fuzzy — `vn loc report`; свежесть id и ledger — `vn loc keys --check`. Устройство round-trip — [14-localization.md](14-localization.md).

---

## 9. Отладка сейвов

**Шаг 1 — оффлайн, без движка:**

```bash
vn save check
#  ✓ schema2-demo.save: schema 2, версия 0.1.0+48d19a3, сцена ch01_s020
```

Команда открывает `.save` как zip и читает член `json` — **без unpickle** (`cli.py:1099-1124`). Ключи туда кладёт `config.save_json_callbacks` (`001_boot.rpy:31-36`): `vn_save_schema`, `vn_version`, `vn_scene`. Тот же трюк работает руками для любого слота игрока:

```bash
python -c "import zipfile,json,sys; print(json.loads(zipfile.ZipFile(sys.argv[1]).read('json')))" \
  "$APPDATA/RenPy/vn-1755000000/1-1-LT1.save"
```

**Шаг 2 — реальная загрузка и миграции:**

```bash
vn save corpus
#  линия имён: 52 .rpyc восстановлено из ci/fixtures/rpyc-line/ (G6)
#  ✓ schema1-demo.save: OK: vn_end_of_content; schema после загрузки: 2 (цель 2)
#  ✓ schema2-demo.save: OK: vn_end_of_content; schema после загрузки: 2 (цель 2)
```

Каждая фикстура кладётся во временный `--savedir`, загружается настоящей игрой, миграции идут в `label after_load` (`020_state.rpy:83-107`), автопилот доигрывает до конца. Критерий прохода (`cli.py:1243-1244`): не таймаут **и** `RESULT.txt` начинается с `OK` **и** `state.json["vn_save_schema"] == project.yaml: save_schema`.

**Что здесь важно знать при отладке:**

- Фикстура валидна только против той «линии statement-имён», с которой создана. Носитель линии — `ci/fixtures/rpyc-line/` (52 `.rpyc`, **единственные `.rpyc` в git**, негативное правило `.gitignore:14`). `vn save corpus` восстанавливает линию перед прогоном, `--add` её пересоздаёт. Линия пересобрана 2026-08-08 (было 34 файла): старая снималась до галереи, ачивок и UI-панелей.
- Фикстур **две**, и `schema1-demo.save` — на **старой** схеме 1. На ней ветка «загружаем старый сейв и мигрируем» (`020_state.rpy:95-106`) исполняется по-настоящему: в `log.txt` появляется `[vn] migration 0002`, а прогон печатает `schema после загрузки: 2 (цель 2)`. Если отлаживаете миграцию — смотрите именно эту фикстуру; `schema2-demo.save` ветку миграции не трогает.
- Фикстуру на старой схеме можно снять **только до** бампа `save_schema` (`vn save corpus --add` пишет сейв текущей игрой). Для будущих переходов схемы её опять придётся заводить заранее — см. [27-testing.md §9.8](27-testing.md).
- `vn save migrate` — заглушка фазы 3 (`cli.py:1259-1260`, exit 3).
- Сейв из **будущей** схемы не мигрируется вниз: `after_load` делает `block_rollback()` до `say`, показывает `ui.flow.save_from_newer` и `full_restart()` (`020_state.rpy:87-94`). Именно так выглядит «игра выкидывает меня в меню при загрузке чужого сейва».
- Ren'Py 8 подписывает сейвы per-machine токеном — чужой `.save` при загрузке даёт модальный confirm движка. Это не поломка проекта.

---

## 10. Приёмы

### 10.1. Воспроизвести CI локально

Порядок шагов CI (`.github/workflows/ci.yml`) один в один:

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"
vn content lint                                  # job lint (:32)
vn build                                         # job build-test (:67)
vn loc keys --check                              # (:70)
"$RENPY_SDK/renpy.exe" . lint                    # (:73) — в CI это renpy.sh под xvfb
vn content compile --check                       # (:76)
python -m pytest tools/vn/tests -q               # (:79) — 373 теста
```

Если локально зелено, а CI красный — проверьте по порядку:

1. **Незакоммиченные файлы «чинят» сборку.** `git stash -u && vn content lint && git stash pop` — рецепт из `docs/runbooks/pipeline-broken-at-night.md`.
2. **LFS.** CI берёт чекаут с `lfs: true`; локально шрифты могут быть материализованы, а у соседа — указателями. Ловится `vn doctor` (проверка шрифтов по магическим байтам).
3. **Версия SDK.** В CI `RENPY_VERSION: "8.5.3"` (`ci.yml:13`), локально — что стоит; сверка с пином `project.yaml: renpy_sdk` — в `vn doctor`.
4. **Nightly шире, чем PR-пайплайн:** smoke-матрица, `vn save check`, `vn save corpus` и dry-run релиза обоих флейворов гоняются только ночью (`nightly.yml:55-74`). Красный nightly при зелёном PR — норма жанра, воспроизводите его командами из §5.5 и §9.

Артефакт `generated-<sha>` из job `build-test` (`ci.yml:81-86`, хранится 30 дней) — последний зелёный генерат: распаковали в `game/generated/`, игра запускается без локальной компиляции. Автоматизация этого (`vn build --use-artifact <sha>`) в runbook обещана, но **NOT IMPLEMENTED**.

### 10.2. Сузить проблему до одной сцены

```bash
vn content graph                       # где сцена в графе, какие у неё exits
vn scene stub ch01 s040                # заглушка вместо подозрительной сцены
vn build && vn test smoke --picks 0,0  # прогон без неё
```

`vn scene stub` создаёт пару `s040_stub.scene.{yaml,rpy}` с пустыми `exits` и телом из одной реплики (`tools/vn/src/vn/content/scaffold.py:98-117`) — этого достаточно, чтобы прогон draft-главы не падал на ненаписанной цели перехода (G15). Обратный приём: оставить подозрительную сцену и заглушить соседей, тогда `picks.log` покажет, доходит ли автопилот до неё.

Точечно попасть в конкретную строку умеет сам движок — но **только по генерату**, не по авторскому `.rpy`:

```bash
"$RENPY_SDK/renpy.exe" . run --warp "generated/scenes/ch01/ch01_s020.gen.rpy:23"
# строка 23 файла game/generated/scenes/ch01/ch01_s020.gen.rpy =
#   mira "Ты опять проспал?" id ch01_s020_0001
```

(`--warp file:line`, `renpy/arguments.py:162-167` пиннованного SDK; состояние переменных при этом **не** выставляется — ровно как у Shift+J.)

**Грабля.** Путь в `--warp` резолвится **относительно `game/`**: `warp.py:59-60` пиннованного SDK делает `if not filename.startswith("game/"): filename = "game/" + filename`, а дальше ищет узел с ровно таким `filename` и падает `Exception: Could not find a statement to warp to. (...)` (`warp.py:135-137`), если такого нет. Авторские `.rpy` лежат в `content/` — вне `game/` (каталог `game/content` даже занесён в `FORBIDDEN_PATHS` линтера, `tools/vn/src/vn/content/lint.py:50-53`), движок их никогда не парсит, поэтому `--warp "content/chapters/.../s020_school_gate.scene.rpy:12"` падает всегда. Соответствие «авторская строка → строка генерата» ищите по копии источника в самом `.gen.rpy` (блок `label <scene>__body`).

Изолировать прогон от своих сейвов:

```bash
"$RENPY_SDK/renpy.exe" . --savedir "$TEMP/vn-debug-saves"
```

### 10.3. Временно отключить пак

Принадлежность главы паку определяется **расположением** (`tools/vn/src/vn/content/compile.py:506-508`), а `id` в манифесте обязан совпадать с именем каталога (`compile.py:454-456`). Поэтому переименование `packs/ep_beach` не отключает пак, а ломает сборку. Рабочий способ — **вынести каталог за пределы `packs/`**:

```bash
mv packs/ep_beach /tmp/ep_beach     # каталог целиком, вместе с manifest.yaml
vn build                            # ch90 исчезает из VN_CHAPTERS/VN_SCENES
# …проверили…
mv /tmp/ep_beach packs/ep_beach && vn build
```

Помните: `VN_PACKS` перечисляет **все** установленные паки независимо от флейвора (`packs:` в `project.yaml` как гейт — NOT IMPLEMENTED), а `vn.pack_registry.owned()` вне Steam всегда `True` (провайдер подключается в `00_core/035_platform.rpy:75` только при живом Steam — [39-platforms.md](39-platforms.md)). То есть «пак не виден в игре» не воспроизводится подменой флейвора — только физическим отсутствием каталога или запуском под Steam без купленного DLC. Подробности — [30-packs-and-dlc.md](30-packs-and-dlc.md).

### 10.4. Понять, в каком режиме идёт игра

В чекауте `game/build_id.json` отсутствует (пишется только на время `distribute`), поэтому игра всегда стартует как `flavor="dev"`, `nsfw=True`, `watermark=False`, `patron_tag=None`, весь контент виден (`060_build_info.rpy:14-40`). В консоли:

```python
vn_build.flavor        # 'dev' в чекауте; 'public'/'patron' в дистрибутиве
vn_build.patron_tag    # None в чекауте; 8 hex в patron-сборке с --patron-token
vn_build.label()       # то, что рисует вотермарка: build_id [+ ' · ' + patron_tag]
vn_scene, vn_menu      # где мы и какое меню последним показывалось
```

`patron_tag` — это **не** токен: с ADR-0011 в документ пишется `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex (`release.py:455-476`), потому что `build_id.json` целиком уезжает игроку внутри дистрибутива. Восстановить токен из метки нельзя; сопоставить утёкшую сборку с получателем — можно, пересчитав метку из своего токена (рецепт в докстринге `release.patron_tag`). Читая старый `build-info.json` из `build/dist/` сборки до 0.1.5, вы увидите там поле `patron_token` со схемой `build_info@1` — это тот самый дефект, а не альтернативный формат.

Если нужно воспроизвести поведение релизного флейвора — собирайте релиз (`vn release build --flavor public`), подмена `build_id.json` руками противоречит контракту (файл в `.gitignore:8` и удаляется в `finally`).

---

## Как изменить / Как расширить

Приоритетные, дешёвые и полезные доработки — по возрастанию стоимости:

1. **Рантайм-гейт консоли.** В `../../game/framework/90_debug/010_dev.rpy` перенести включение в `init 999` и написать `config.console = bool(config.developer)` — к этому моменту `developer` уже разрешён движком из `"auto"`. Снимает зависимость безопасности релиза от одной строки `build.classify`.
2. **Флаг `--screens` у `vn test smoke`.** Пробросить `VN_AUTOPILOT_SCREENS` из CLI (`cli.py:1347-1371`) — механика в рантайме уже есть и работает (`030_flow.rpy:166-184`), не хватает только флага и строки в nightly.
3. **Убрать шум снапшота.** В `020_state.rpy:39-45` отфильтровать `__future__._Feature` и `basestring` до `vn_log` — 12 строк мусора на каждый снапшот прячут настоящие сообщения.
4. **`vn build --use-artifact <sha>`.** Аварийный режим из runbook: скачать артефакт `generated-<sha>` и распаковать в `game/generated/`. Сейчас делается руками.

Чего **не** делать в рамках «улучшения отладки»: вводить сетевую телеметрию и автоотправку crash-репортов — это оффлайн-игра, и модель «игрок прислал файл из `crash/`» осознанная.

---

## Чего НЕ делать

- **Не искать в `log.txt` историю прошлых запусков** — файл открывается в режиме `w` и обнуляется на каждом старте. Нужен архив — копируйте после прогона.
- **Не верить `errors.txt` в корне без проверки даты.** Лежащий сейчас файл — от `Sat Aug 8 12:59:41 2026` про `ypadding` у `hbox` в `history.rpy:44`; проблема давно исправлена (там теперь `spacing`).
- **Не заводить второй `config.exception_handler`** — поле одно, побеждает последнее присваивание по init-порядку, и чужой обработчик молча умрёт. Единственный — в `070_crash.rpy` (§3); попытку завести второй завалит `tools/vn/tests/test_crash_handler.py`.
- **Не считать 12 строк `[vn] snapshot: … пропущен` симптомом** — это штатный шум named stores.
- **Не отправлять синтетический ввод (SendKeys и подобное) в окно игры** — норма G23, единственный автоматический прогон это `vn test smoke`.
- **Не править производные зоны** — `game/generated/`, `game/assets/`, `game/tl/`: перезапишет сборка, а сироты будут удалены вместе с `.rpyc`.
- **Не удалять и не «чинить» блок автопилота** в `choice.rpy:53-54` и `core_screens.rpy:408-410` — прогон повиснет на меню до таймаута.
- **Не запускать `vn test smoke` при открытой игре** — по таймауту убивается всё дерево процессов.
- **Не коммитить включённые движковые логи** (`text_overflow.txt`, `image_cache.txt`, `profile_screen.txt`, `trace.txt`) — они не в `.gitignore`.
- **Не полагаться на `vn content graph` для DLC** — он читает только `content/chapters/`, главы паков в графе не видны.
- **Не считать `.vncache/langqa/` воспроизводимым артефактом** — этот каталог никем в репозитории не создаётся (`grep -rn langqa tools/ game/ docs/ .github/` → 0 совпадений), это ручной осадок.

---

## Проверка

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"

vn doctor                              # 8 PASS, 0 FAIL — эталон на машине владельца
vn content lint                        # lint: OK (N предупреждений)
vn build                               # build: OK
vn build --check                       # check: генерат свеж
"$RENPY_SDK/renpy.exe" . lint          # родной lint движка по game/**
vn test smoke --picks 0,0              # smoke: OK: vn_end_of_content (21 скриншот)
vn save check && vn save corpus        # 2 фикстуры: целы, грузятся, миграция 0002 исполняется
python -m pytest tools/vn/tests -q     # 400 passed
```

После правок в `game/framework/90_debug/**` или `game/options.rpy` дополнительно:

```bash
vn release validate --flavor public    # 21 проверка релизного гейта (сейчас 0 FAIL, 2 WARN, exit 0)
vn release build --flavor public --package win
# и глазами: в build/dist/0.1.4-public/ нет framework/90_debug/ и generated/qa/
```

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `game/framework/00_core/070_crash.rpy` (breadcrumbs + репорт), `game/framework/00_core/001_boot.rpy` (`vn_log`, `save_json_callbacks`), `game/framework/20_ui/screens/crash_screen.rpy`, `game/framework/90_debug/010_dev.rpy` и `020_jump_menu.rpy`, `game/options.rpy:17-26` (`build.classify`), `game/framework/00_core/030_flow.rpy:91-211` (`vn_qa`), `tools/vn/src/vn/cli.py:1268-1401` (`_autopilot_run`, `test smoke`), `tools/vn/src/vn/doctor.py`, `tools/vn/src/vn/content/analyze.py` |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**` (генерат — перезапишется), `*.rpyc`, `log.txt` / `errors.txt` / `traceback.txt` (пишет движок), `.vncache/**` (кэш и артефакты прогонов), `ci/fixtures/rpyc-line/**` (линия statement-имён; меняется только через `vn save corpus --add`), `ci/fixtures/saves/*.save` |
| **Зависимости** | Удаление строки `build.classify("game/framework/90_debug/**", None)` (`options.rpy:24`) → консоль и Shift+J уезжают игроку (рантайм-гейта у консоли нет). Правка `030_flow.rpy:91-211` или блока автопилота в `choice.rpy:53-54` → виснет `vn test smoke` и, следом, `vn save corpus` и вся ночная матрица. Правка `050_build_bridge.rpy` → инвалидируется весь кэш `.vncache/analyze-*.json` (мост входит в ключ). Правка `001_boot.rpy:31-36` → меняется JSON-заголовок слота, ломается `vn save check` |
| **Валидация** | `vn doctor && vn build && vn build --check && vn test smoke --picks 0,0 && vn save check && python -m pytest tools/vn/tests -q`; для UI дополнительно `vn test smoke --lang pseudo` и просмотр `.vncache/smoke/shot*.png` |
| **Частые ошибки** | 1) Искать несуществующие команды из `docs/ARCHITECTURE.md`: `vn build --use-artifact`, `vn validate`, `vn test perf`, `vn content lint --strict` — их **нет**. 2) Считать `log.txt` накопительным журналом — он обнуляется при каждом старте. 3) Диагностировать по `errors.txt` в корне, не глядя на дату — файл устаревший. 4) Заводить свой `config.exception_handler` вторым присваиванием — переживёт только последнее по init-порядку. 5) Отключать пак переименованием каталога — сборка упадёт на сверке `id` с именем папки, каталог надо выносить из `packs/`. 6) Править генерат «на минутку» — исчезнет на ближайшем `vn build`. 7) Ставить `config.console = config.developer` в init-фазе — там `developer` ещё строка `"auto"` (truthy). |

**Смежные файлы хендбука:** [03-getting-started.md](03-getting-started.md) (окружение и `RENPY_SDK`), [04-development-workflow.md](04-development-workflow.md) (CI-пайплайны), [05-renpy-development.md](05-renpy-development.md) (рантайм и dev-инструменты), [06-frontend.md](06-frontend.md) (экраны, экран краха), [07-backend.md](07-backend.md) (state, сейвы, миграции, crash-репортер), [08-content-pipeline.md](08-content-pipeline.md) (компилятор и генерат), [14-localization.md](14-localization.md), [16-assets.md](16-assets.md), [25-custom-engine.md](25-custom-engine.md) (`vn` CLI), [27-testing.md](27-testing.md) (тесты и автопилот как QA), [29-build-and-release.md](29-build-and-release.md), [30-packs-and-dlc.md](30-packs-and-dlc.md), [36-troubleshooting.md](36-troubleshooting.md) (каталог симптомов).
