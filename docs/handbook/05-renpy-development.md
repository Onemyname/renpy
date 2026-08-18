# 05. Разработка на Ren'Py в этом проекте

> **Статус подсистемы:** IMPLEMENTED — рантайм-надстройка (22 рукописных `.rpy` в `game/framework/`) работает и покрыта обвязкой компилятора; но «но» большое: часть фасада `vn.*`, обещанная в `docs/ARCHITECTURE.md`, не существует (`register_system`, `safe_jump`, `scene_enter/leave`, `vn_pos_*`), а `vn.beat()` и `vn_qa.choice()` — мёртвые точки расширения.
> **Отвечает на вопрос:** «Я умею писать на Ren'Py — куда здесь класть код, что писать нельзя и почему моя правка исчезла после сборки?»

Этот файл — про Ren'Py **в этом репозитории**, а не про Ren'Py вообще. Движок — 8.5.3.26051504, SDK берётся только из `RENPY_SDK`. Игра состоит из двух половин: рукописной надстройки `game/framework/**` (в git, правится руками) и генерата `game/generated/**` + `game/assets/**` + `game/tl/**` (не в git, пишется `vn build`). Правило, которое ломает больше всего новичков: **сцены и персонажи — не код, а декларации в `content/`**; их Ren'Py-обвязку эмитит компилятор.

## Быстрый ответ

```bash
# Windows PowerShell (в bash-сессии агента RENPY_SDK не наследуется — экспортить руками)
vn doctor            # 8 проверок окружения: Python, git, git-lfs, корень репо, project.yaml,
                     #   реестр схем, шрифты UI (ловит LFS-указатели), Ren'Py SDK.
                     #   ffmpeg/GPU/ComfyUI здесь НЕТ — они в `vn pipeline doctor`
vn build             # lint -> ассеты -> компиляция content/ -> импорт переводов
vn play              # запуск игры через SDK (требует непустой game/generated/)
vn dev               # watch по content/ + assets_src/ и запущенная игра
```

| Хочу… | Файл, который надо открыть |
|---|---|
| поправить логику ядра / фасад `vn.*` | `../../game/framework/00_core/030_flow.rpy` |
| поправить экран, стиль, компонент | `../../game/framework/20_ui/` → см. [06-frontend.md](06-frontend.md) |
| написать реплики/выборы сцены | `content/chapters/chNN_*/scenes/sNNN_*.scene.rpy` → [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md) |
| добавить переход между сценами | `*.scene.yaml: exits:` — **не** `jump` в `.rpy` |
| добавить свою gameplay-механику | `game/framework/10_systems/<id>/` (каталог пуст, только README) |
| понять, почему правка `game/generated/**` пропала | она и должна была пропасть — это генерат |

---

## 1. Карта «где что лежит»

| Что | Где | Кто пишет | В git? |
|---|---|---|---|
| ядро, фасад `vn.*`, state, локализация, краш | `game/framework/00_core/` (13 файлов + `engine_compat/000_compat.rpy`) | человек | да |
| gameplay-системы (слой 1) | `game/framework/10_systems/` — **только `README.md`, кода нет** | человек | да |
| UI: компоненты, экраны, стили | `game/framework/20_ui/` (4 файла + 8 экранов в `screens/`) | человек | да |
| dev-инструменты | `game/framework/90_debug/` (3 файла) | человек | да |
| дизайн-токены | `game/gui.rpy` | человек | да |
| конфиг сборки, `build.classify` | `game/options.rpy` | человек | да |
| обвязка сцен `label chNN_sNNN:` | `game/generated/scenes/chNN/*.gen.rpy` | `vn build` | **нет** |
| `Character`, `image`, `layeredimage`, реестры | `game/generated/registry/*.gen.rpy` | `vn build` | **нет** |
| `default`-переменные, снапшот, миграции | `game/generated/state/*.gen.rpy` | `vn build` | **нет** |
| `config.version` | `game/generated/version.gen.rpy` (**не** в `options.rpy`) | `vn build` | **нет** |
| экран выбора глав | `game/generated/screens/chapter_select.gen.rpy` | `vn build` | **нет** |
| ассеты (webp/webm/ogg) | `game/assets/` | `vn assets build` | **нет** |
| переводы | `game/tl/{de,en,pseudo}/` | `vn loc import` | **нет** |

Единственный `image`-стейтмент, написанный руками, — `image vn_black = Solid("#000000")` в `game/framework/20_ui/images.rpy:5` (нейтральный фон сцены без локации). Всё остальное эмитит `registry/images.gen.rpy`. Автоопределение образов по каталогу выключено намеренно: `config.images_directory = None` (`00_core/001_boot.rpy:17`), а каталог `game/images` внесён в `FORBIDDEN_PATHS` линтера.

---

## 2. Слои и init-приоритеты

**Назначение.** Ren'Py склеивает все `.rpy` в один скрипт и исполняет `init`-блоки по приоритету; при равном приоритете порядок решает сортировка путей. Числовые префиксы каталогов (`00_core`, `20_ui`, `90_debug`) — **читаемость, а не порядок исполнения**. Порядок задаётся исключительно приоритетами.

**Реальная шкала** (проверено `grep -rn "^init \|init offset" game/`):

| Приоритет | Что инициализируется | Файл |
|---|---|---|
| `-999` | конфиг движка, слой `sprites`, `vn_log`, save-JSON-хедер | `00_core/001_boot.rpy:5` |
| `-999` | store `vn_registry` | `00_core/010_registry.rpy:4` |
| `-999` | store `vn_state` (`MIGRATIONS`, `SNAPSHOT_*`, `snapshot/apply/run_migrations`) | `00_core/020_state.rpy:12` |
| `-999` | store `vn` (фасад) и store `vn_qa` (автопилот) | `00_core/030_flow.rpy:4,91` |
| `-995` | store `vn_lang` (реестр языков), store `vn_loc` (lookup строк) | `00_core/040_localization.rpy:15,137` |
| `-985` | store `vn_build` (флейвор, nsfw, watermark) | `00_core/060_build_info.rpy:10` |
| `-980` | store `vn_ach`, store `vn_gal` | `00_core/080_achievements.rpy:12`, `090_gallery.rpy:20` |
| `-980` | **генерат:** именованные stores `ch01`, `g` + все `default` | `generated/state/defaults.gen.rpy:10,13` |
| `-970` | **генерат:** `SNAPSHOT_VARS` / `SNAPSHOT_STORES` | `generated/state/snapshot.gen.rpy:8` |
| `-960` | **генерат:** `MIGRATIONS` (исходники миграций инлайном) | `generated/state/migrations.gen.rpy:7` |
| `-950` | breadcrumbs + crash-репортер, **единственный** `config.exception_handler` | `00_core/070_crash.rpy:10,82` |
| `-950` | store `vn_compat` (engine_compat) | `00_core/engine_compat/000_compat.rpy:5` |
| `-900` | **генерат:** `define config.version` | `generated/version.gen.rpy:6` |
| `-100` | **генерат:** `VN_CHAPTERS/VN_SCENES/VN_MENUS/VN_STRINGS/VN_GALLERY/VN_ACHIEVEMENTS`, `config.label_overrides` | `generated/registry/*.gen.rpy` |
| `-2` | все токены `gui.*`, `gui.init(1920, 1080)` | `game/gui.rpy:6` |
| `0` | `images.gen`, `ui_frames.gen`, весь `20_ui/**`, build-bridge, `90_debug/**` | `init offset = 0` / голый `init python` |
| `500` | **генерат:** `Character(...)`, audio-каналы | `generated/registry/{characters,audio}.gen.rpy` |
| `999` | `vn_lang.refresh()` — скан языков | `00_core/040_localization.rpy:131` |

**Почему порядок важен — три конкретных случая:**

1. `030_flow.rpy:6-7` прямо запрещает не-ленивый доступ к `vn_compat`: `vn` создаётся на `-999`, `vn_compat` — на `-950`. Поэтому `check_scene_stack()` берёт `renpy.store.vn_compat` **внутри тела функции**, а не на уровне модуля. Скопируете этот импорт наверх — сломаете инициализацию.
2. `gui.rpy` на `-2` обязан отработать раньше стилей `20_ui` на `0`: стили читают `gui.*` в момент объявления.
3. `vn_lang.refresh()` на `999` — потому что только к этому моменту зарегистрированы все `translate`-блоки, включая приехавшие внутри `.rpa` DLC-пака.

**ADR-0003: почему шкала начинается с −999, а не −1000.** Первый прогон настоящего `renpy lint` на скелете фазы 0 выдал `The init priority (-1000) is not in the -999 to 999 range` — движок резервирует всё за пределами `−999..999` за собой (`../adr/0003-init-scale-engine-limit.md:9-17`). Верхняя граница 999 занята DLC-слотами впритык: **новые уровни выше DLC не заводить**.

*Расхождение, которое не надо «чинить»:* ADR-0003:16 называет для `build_info` приоритет −900, а `060_build_info.rpy:10` использует −985 — потому что −900 занял `version.gen.rpy`. Код прав, ADR устарел.

**Как менять.** Меняете приоритет — проверьте, что ниже по шкале никто не читает ваш store на своём init. **Не** пишите `init offset` в `00_core/**` (там явные `init <N> python in <store>`), и **не** убирайте `init offset = 0` из `20_ui/**`.

---

## 3. Фасад `vn.*` — единственный API между генератом и движком

**Где лежит:** `game/framework/00_core/030_flow.rpy`, `API_LEVEL = 1` (`:9`) — это значение проверяют манифесты DLC-паков (`packs/*/manifest.yaml: api_level`).

| Символ | Строка | Семантика | Статус | Эмитит ли компилятор |
|---|---|---|---|---|
| `vn.API_LEVEL` | `:9` | `int = 1` | IMPLEMENTED | — |
| `vn.checkpoint(scene_id)` | `:12` | `store.vn_scene = scene_id`; прогон `vn_ach.check(scene_id=)` и `vn_gal.check(scene_id=)`, уведомление о разблокировках | IMPLEMENTED | **да**, первой строкой обвязки (`scenes.py:201`) |
| `vn.beat(beat_id=None)` | `:19` | мелкий якорь внутри сцены; при `beat_id is None` — no-op | **IMPLEMENTED / UNUSED** | **нет.** Ни компилятор не эмитит, ни один файл в `content/` не зовёт. Тип якоря `beat:` в схемах `achievements@1`/`gallery@1` сегодня недостижим |
| `vn.chapter_done(chapter_id)` | `:26` | `vn_ach.check(beat_id="chapter_done:<id>")` + `vn_gal.check(chapter_done=)` | IMPLEMENTED | **да**, только у терминальной сцены (без `exits`) — `scenes.py:394-397` |
| `vn._gallery_notify(opened)` | `:32` | приватный; `renpy.notify` с ключом `ui.gallery.unlocked_one`/`_many`, `[n]` подставляется `str.replace` | IMPLEMENTED | — |
| `vn.check_scene_stack()` | `:44` | инвариант G7: глубина call-стека на границе сцены = 0. **Только логирует**, не чинит и не прерывает | IMPLEMENTED | **да** (`scenes.py:245`) |
| `vn.unwind_call_stack()` | `:50` | `renpy.pop_call()` пока глубина > 0. Куда идти дальше — решает вызывающий | IMPLEMENTED | **да** |
| `vn.eval_when(expr)` | `:57` | `renpy.python.py_eval(expr)` для условных exits | IMPLEMENTED / НЕ ОБКАТАН | **да**, но только когда у exit объявлен `when:`; ни одна сцена в `content/` этого не делает |
| `vn.pack_registry` | `:88` | экземпляр `_PackRegistry` (`:63`) | IMPLEMENTED | используется в `generated/screens/chapter_select.gen.rpy`, `080_achievements.rpy:41`, `090_gallery.rpy:44` |
| `…set_ownership_provider(fn)` | `:73` | внедрение платформенной проверки владения | IMPLEMENTED | вызывающий один: `00_core/035_platform.rpy:75` (`init 999`, только при живом Steam) — [ADR-0014](../adr/0014-platform-services.md), [39-platforms.md](39-platforms.md) |
| `…installed(pack_id)` | `:76` | `pack_id == "core"` или в `VN_PACKS` | IMPLEMENTED | — |
| `…owned(pack_id)` | `:79` | `core`→True; не установлен→False; провайдер, если задан; **иначе True** (DRM-free по умолчанию) | IMPLEMENTED | — |

**Store `vn_qa`** (тот же файл, `init -999 python in vn_qa`, `:91`) — только для QA:

| Символ | Строка | Статус |
|---|---|---|
| `vn_qa.choice(scene_id, menu_id, idx)` | `:98` | **NOT IMPLEMENTED — тело `pass`.** `docs/ARCHITECTURE.md:544-551` и норма C1 требуют, чтобы компилятор эмитил его первым стейтментом каждой ветки меню. `emit_scene` копирует авторский `.rpy` дословно (`scenes.py:270-271`) и menu-блоки не переписывает |
| `autopilot_active()` | `:106` | IMPLEMENTED — гейт по env `VN_AUTOPILOT` |
| `autopilot_tick()` | `:109` | IMPLEMENTED — скриншот + `renpy.queue_event("dismiss")`; на тике 0 пишет `startup.txt` (cold start) |
| `autopilot_choose(items)` | `:130` | IMPLEMENTED — выбор пункта меню по `VN_AUTOPILOT_PICKS` |
| `autopilot_boot()` | `:152` | IMPLEMENTED — смена языка (`@source` = сброс) и `renpy.load(slot)` |
| `autopilot_screens()` | `:166` | IMPLEMENTED / UNDOCUMENTED — `VN_AUTOPILOT_SCREENS=gallery,preferences`; **ни один флаг CLI эту переменную не выставляет** |
| `autopilot_finish(reason)` | `:186` | IMPLEMENTED — `RESULT.txt`, `state.json`, `gallery.json`, `renpy.quit(save=False)` |

**Store `vn_registry`** (`010_registry.rpy`): `chapters()` `:7`, `menus()` `:12`, `scene_label(full_id)` `:16` (функция-тождество — метка сцены равна её id).

**NOT IMPLEMENTED, но заявлено в `docs/ARCHITECTURE.md`** — не пишите этот код, его нет:
`vn.register_system(...)` (`ARCHITECTURE.md:717`, а также `10_systems/README.md:3`), `vn.safe_jump()` (`:1733`), `vn.scene_enter()` / `vn.scene_leave()` (`:1555,1562`), сохраняемые `vn_pos_scene` / `vn_pos_beat` (`:3136-3151`), вызов `renpy.block_rollback()` внутри `checkpoint()` на границе главы (`:3151`). В коде существует ровно одна позиционная переменная — `vn_scene` (`020_state.rpy:10`).

**Метки-точки входа** (там же, `030_flow.rpy`): `label start:` `:217` (пустой реестр глав → две локализованные реплики и `return`, игра не падает), `label vn_scene_unavailable:` `:227`, `label vn_end_of_content:` `:235`. `label after_load:` живёт отдельно — `020_state.rpy:83`.

**Частые ошибки.** (1) Звать `vn.beat("x")` и ждать, что якорь `beat:` в галерее сработает — сработает, но эмитить вызов должен **автор вручную**, компилятор его не подставит. (2) Полагаться на `check_scene_stack()` как на защиту — он только пишет строку в `log.txt`. (3) Добавлять функции в `vn` без обновления `API_LEVEL` — манифесты паков сверяются именно с ним.

---

## 4. Контракт меток и переходов

**Назначение.** Разделить «что пишет автор» и «что эмитит компилятор», чтобы переименование сцены не ломало сейвы и переводы.

| Метка | Кто пишет | Паттерн |
|---|---|---|
| `chNN_sNNN` (обвязка) | **компилятор** | `^ch\d{2}_s\d{3}$` |
| `chNN_sNNN__body` | **автор**, обязательна | — |
| `chNN_sNNN__<branch>` | автор, сколько угодно | `^ch\d{2}_s\d{3}__[a-z0-9_]+$` (`scenes.py:18`) |

Правила, которые проверяются машиной (`tools/vn/src/vn/content/scenes.py:81-137`, статус IMPLEMENTED):

- любая метка верхнего уровня в авторском `.rpy` обязана матчиться `LABEL_RE` **и** относиться к своей сцене — иначе ошибка компиляции;
- `<full_id>__body` обязателен (`:89-90`);
- `jump`/`call` разрешены **только** на метки своей же сцены (префикс `<full_id>__`), `:100-104`;
- `jump expression` / `call expression` запрещены — они ломают статический анализ и prediction (`:94-98`);
- `return` обязан вернуть **строковый литерал**, объявленный в `exits:` соответствующего `scene.yaml`, либо ничего (`:118-137`);
- условные пункты `menu:` запрещены (`:108-114`) — движок фильтрует их до `screen choice`, и перевод по runtime-индексу съехал бы на соседние пункты;
- чтение/запись атрибута управляемого store, не объявленного в Variable Registry, — ошибка (в главе со `status: draft` — предупреждение), `:148-159`.

**Переход между сценами — только `return "<exit_id>"`.** Цель прописывается в `scene.yaml`:

```yaml
exits:
  roof: s030                                  # короткая ссылка внутри главы
  alt:
    - {when: "g.route == 'mira'", to: s040}   # условный переход -> vn.eval_when
    - {to: ch02/s010}                         # межглавная ссылка
```

**Грабля, которая всех ловит первой:** `vn content lint` **не проверяет контракт меток**. Линтер смотрит только, что рядом с `*.scene.yaml` лежит `*.scene.rpy` (`tools/vn/src/vn/content/lint.py:194-201`). Кривую метку, лишний `jump` или неописанный `return` ловит `vn content compile` (то есть `vn build`), потому что разбор `.rpy` идёт через build-bridge. Прогон только линтера — не проверка.

---

## 5. Разбор реального генерата: `ch01_s020.gen.rpy`

Файл `../../game/generated/scenes/ch01/ch01_s020.gen.rpy` (эмиттер — `scenes.py:197-273`):

```renpy
label ch01_s020:                                       # (1)
    $ vn.checkpoint("ch01_s020")                       # (2)
    $ renpy.scene("sprites")                           # (3)
    scene bg school_gate day with dissolve             # (4)
    call ch01_s020__body from _call_ch01_s020__body    # (5)
    $ vn.check_scene_stack()                           # (6)
    if _return == "roof":                              # (7)
        jump ch01_s030
    # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)
    $ vn.unwind_call_stack()                           # (8)
    jump vn_scene_unavailable
```

1. Имя метки = `full_id`, собранный из **имён файлов**: `CHAPTER_DIR_RE` над каталогом главы + `SCENE_YAML_RE` над именем `.scene.yaml` (`compile.py:31-32,571-575`). Поле `id:` внутри `scene.yaml` компилятор **не читает** — его сверяет только линтер. Слуг (`school_gate`) в имя метки не входит: слуг можно переименовать, id — никогда.
2. Единственный якорь позиции сейва + прогон триггеров ачивок/галереи.
3. Явная чистка слоя `sprites` — см. §6.
4. Фон из `scene.yaml: location: school_gate/day`. Локация и вариант валидируются против `content/locations/**` (`scenes.py:206-229`); нет локации или она не прошла проверку → `scene vn_black with dissolve`. Если объявлен `music:`, следом идёт `play music <id> fadein 1.0` (`:234-242`).
5. `call … from …` с явным именем точки возврата — так имя statement'а стабильно между перекомпиляциями, и старые сейвы продолжают находить точку возврата (норма G6, линия `.rpyc` в `ci/fixtures/rpyc-line/`).
6. Проверка инварианта глубины стека (только лог).
7. Диспетчер по `_return`: по одному `if` на каждую запись `exits`, **в порядке объявления в YAML**. При `when:` условие становится `_return == "roof" and vn.eval_when('...')` (`scenes.py:249-251`).
8. Фолбэк: `_return` не совпал ни с чем → размотать стек и уйти на `vn_scene_unavailable`.

Ниже в том же файле — **дословная копия авторского `.rpy`** после маркера `# ══ Авторский источник (копия)`. Именно поэтому редактировать генерат бессмысленно: следующая сборка перезапишет обе половины.

**Терминальная сцена главы** выглядит иначе (`ch01_s030.gen.rpy:14-16`) — вместо диспетчера:

```renpy
    $ vn.chapter_done("ch01")
    if _return is None:
        jump vn_end_of_content
```

**Черновая (`status: draft`) сцена с ненаписанной целью** получает живой плейсхолдер вместо `jump` (`scenes.py:253-257`): комментарий `# TODO(draft): цель <label> ещё не написана`, `$ vn.unwind_call_stack()`, `jump vn_scene_unavailable`.

---

## 6. Слой `sprites`, `renpy.scene()` и `config.tag_layer`

**Назначение.** Отделить персонажей от фона, чтобы (а) `scene` не сносил их случайно и (б) тонировка локации применялась ко всем персонажам разом.

**Как работает.**

- Слой создаётся в `00_core/001_boot.rpy:22`: `renpy.add_layer("sprites", above="master")`. Без него `show mira …` упадёт в рантайме.
- Каждый персонажный тег привязан к слою генератом: последняя строка `generated/registry/images.gen.rpy` — `define config.tag_layer = {"mira": "sprites"}` (эмиттер `tools/vn/src/vn/content/images.py:239-244`).
- Стейтмент `scene` чистит **только свой слой** (`master`). Персонажи живут в `sprites` и пережили бы смену сцены. Поэтому обвязка ставит явный `$ renpy.scene("sprites")` перед фоном — комментарий эмиттера прямо это фиксирует (`scenes.py:202-203`).

**Как менять / расширять.** Новый персонаж попадает в `config.tag_layer` автоматически при `vn build` — руками ничего не добавляется. Захотите ещё один слой (например `fx` над `sprites`) — добавляйте `renpy.add_layer` в `001_boot.rpy` **и** учтите, что обвязка сцены его чистить не будет: строку чистки эмитит `scenes.py`, а это правка тулинга, а не игры.

**Частые ошибки.** (1) `config.tag_layer` со слоем, которого нет, — падение при первом `show`. (2) Ручной `image mira …` рядом с генератом: `image`-стейтменты имеют базовый приоритет 500, ваш и сгенерированный столкнутся, победит порядок сортировки путей. (3) Ожидание, что `scene bg …` уберёт спрайты — нет, см. выше.

---

## 7. `engine_compat` — единственная дверь к недокументированному API

**Назначение (норма G18).** `game/framework/00_core/engine_compat/000_compat.rpy` — **единственный** модуль, которому разрешено трогать недокументированные/полудокументированные API движка. Всё остальное обязано звать `vn_compat.*`. Каждое допущение обязано быть покрыто контракт-тестом.

| Функция | Строка | Что прячет | Контракт-тест |
|---|---|---|---|
| `call_stack_depth()` | `:8` | `renpy.call_stack_depth()`, fallback на `len(renpy.get_return_stack())` при `AttributeError` | `test_engine_compat::test_call_stack_depth` |
| `revertable(value)` | `:17` | рекурсивная конвертация `dict/list/set` в `RevertableDict/List/Set` из `renpy.revertable` | `test_engine_compat::test_revertable_types` |

`revertable()` нужен потому, что значения, созданные вне renpy-python (миграции сейвов, `json.loads`), **не участвуют в rollback**, пока не завёрнуты. `020_state.rpy:58` прогоняет через него каждое значение при `apply_snapshot`.

**Как расширять.** Понадобился ещё один недокументированный вызов — добавляйте функцию **сюда**, с docstring вида «КОНТРАКТ-ТЕСТ: …», и заводите тест в `tools/vn/tests/test_engine_compat.py`. Canary-джоба CI гоняет тесты на свежем Ren'Py и первой ловит поломку допущения.

---

## 8. Куда класть свой Ren'Py-код

**Правило 1.8: `00_core` не знает ни об одной главе, системе или персонаже** — ни одного `chNN`-идентификатора (комментарий-норма в `001_boot.rpy:1-3`). Проверка `vn content lint --arch` заявлена, но **NOT IMPLEMENTED** (у линтера есть только `--layout/--no-layout`), так что норма держится на ревью.

| Что вы пишете | Куда | Статус |
|---|---|---|
| инфраструктура ядра (state, флоу, локализация, краш) | `00_core/` — существующие файлы, новый файл только с новым номером-префиксом | IMPLEMENTED |
| gameplay-механика (отношения, телефон, миниигра) | `game/framework/10_systems/<mechanic_id>/` | **NOT IMPLEMENTED** — каталог содержит только `README.md`; `vn.register_system(...)` из `README.md:3` в коде отсутствует |
| экран, стиль, компонент | `20_ui/` — см. [06-frontend.md](06-frontend.md) | IMPLEMENTED |
| dev-инструмент | `90_debug/` (вырезается из релиза) | IMPLEMENTED |
| логика сцены | `content/**/*.scene.rpy` — см. [12-scenes.md](12-scenes.md) | IMPLEMENTED |

**Практически сегодня:** пока `register_system` не существует, механику придётся положить как обычный файл в `10_systems/<id>/` со своим `init`-приоритетом и своим named store вида `mech_<id>` (это имя разрешено регексом управляемых stores в `050_build_bridge.rpy:13` и схемой `vars@1`). Тогда её переменные попадут в снапшот и миграции. Store с любым другим именем — молчаливый фантом вне сейва.

**Категорически не класть** новые `.rpy` в `game/generated/**` — орфан-чистка компилятора удалит и `.rpy`, и `.rpyc` при следующей сборке (`compile.py:892-897`).

---

## 9. Debug: консоль, Shift+J, исключение из релиза

| Инструмент | Файл | Как включается |
|---|---|---|
| консоль разработчика (Shift+O) | `90_debug/010_dev.rpy:7-8` | `config.console = True` — **безусловно** |
| jump-меню по сценам (**Shift+J**) | `90_debug/020_jump_menu.rpy:5-11` | `if config.developer: config.overlay_screens.append("vn_debug_hotkeys")`; экран `vn_debug_jump` рисует `vpgrid cols 4` по `VN_SCENES` и прыгает через `Function(renpy.jump_out_of_context, sc["label"])` (`:29-31`) |

`010_dev.rpy:4-6` объясняет, почему там честное `True`, а не `config.console = config.developer`: **в init-фазе `config.developer` ещё равен строке `"auto"`**, то есть truthy, и такая запись включила бы консоль и в релизе.

**Исключение из релиза** — `game/options.rpy:24-26`:

```python
build.classify("game/framework/90_debug/**", None)
build.classify("game/generated/qa/**", None)
build.classify("game/generated/manifest.json", None)
```

Риск, который надо помнить: у консоли **нет рантайм-гейта**. Безопасность держится целиком на этой строке `build.classify`. Регрессия в упаковке = консоль в релизной сборке. Оба файла `90_debug/**` пользуются голыми литералами `_("…")` (`020_jump_menu.rpy:21,22,32`) — это единственные литералы в UI-слое, и они допустимы ровно потому, что файл в релиз не едет.

`vn_debug_jump` честно предупреждает на экране: **состояние глав не выставляется**, переменные останутся текущими (`:22`). Прыжок в сцену — не то же самое, что её прохождение.

**Обработчик исключений в проекте один.** `config.exception_handler` — одно поле движка, побеждает последнее по init-порядку присваивание; раньше их было два (мёртвый блок в `001_boot.rpy` на `-999` и живой крэш-репортер в `070_crash.rpy` на `-950`). Мёртвое присваивание удалено, на его месте в `001_boot.rpy:38-49` стоит комментарий-указатель. Единственный обработчик — `vn_crash_write_report` (`070_crash.rpy:36-82`); он пишет в `log.txt` строку `[vn] unhandled exception: <Тип: сообщение>`, кладёт отчёт в `<savedir>/crash/` и возвращает `False`, чтобы экран рисовал движок. Инвариант «присваивание ровно одно и именно в `070_crash.rpy`» стережёт `tools/vn/tests/test_crash_handler.py` (2 теста). Статус: **IMPLEMENTED**.

Подробности отладки — [28-debugging.md](28-debugging.md); краш-репорты и `screen _exception` — там же и в [07-backend.md](07-backend.md).

---

## 10. Грабли Ren'Py 8.5, проверенные на этом проекте

| Грабля | Почему так | Что делать |
|---|---|---|
| `config.change_language_callbacks` **мёртв** в 8.5 («Removed.» в `config.py`) | движок его больше не зовёт | подписываться через `config.language_callbacks[lang]` — так и сделано в `040_localization.rpy:47-51`, `_hook()` регистрируется на `None` и на каждый найденный код |
| `viewport` со `scrollbars "vertical"` не рисует полосу | у полосы нет дефолтного изображения | задавать `vscrollbar_base_bar` / `vscrollbar_thumb` / `vscrollbar_xsize` — образец: `20_ui/screens/gallery.rpy:58-61`, `core_screens.rpy:367-370`, `history.rpy:36-39` |
| `viewport` без `xsize/ysize` съедает всё доступное место | у viewport нет естественного размера | фиксировать размер явно (`gallery.rpy` — `ysize 800`; `history.rpy` — `1100×830`) |
| в контексте `label main_menu` overlay-экраны и таймеры не тикают | контекст главного меню отличается от игрового | автопилот поэтому и устроен так: `label main_menu` из `_AUTOPILOT_RPY` (`cli.py:1271-1276`) делает **один** вызов `vn_qa.autopilot_boot()` и сразу `return` — управление уходит в `label start`, и только там начинает тикать overlay-таймер `vn_autopilot` (`cli.py:1280-1281`) |
| голый `[` в тексте = интерполяция | синтаксис подстановки Ren'Py | экранировать `[[`; псевдолокаль это делает автоматически (`tools/vn/src/vn/loc/po.py:539-542`), а проверка парности скобок снимает эскейпы до анализа (`po.py:308-317`) |
| `autopilot_choose` обязан `return renpy.run(action)` | интеракция меню завершается только non-None результатом action | `030_flow.rpy:148-150` — комментарий стоит там же; иначе вечное перевыбирание |
| выбор пункта меню нельзя делать выражением в `screen` | экран переоценивается предикцией и каждым тиком оверлея, счётчик picks дрейфует | только `timer … action Function(...)` — `choice.rpy:53-54` |
| парсер добавляет неявный `Return` в конец файла | особенность `renpy.parser.parse` | build-bridge отрезает его сам (`050_build_bridge.rpy:124-125`); при своём разборе `.rpy` — учитывать |
| Ren'Py 8.5 добавляет к имени слота токен: `1-1-LT1.save` | подпись сейва | корпус кладёт **оба** имени (`1-1-LT1.save` и `1-1.save`) в временный `--savedir`, движок подхватит известный ему (`cli.py:1194` и ниже). Сейв, принесённый с чужой машины, движок встретит модальным подтверждением — для CI это решается собственным `--savedir`, а не переносом файлов в профиль игрока |
| `image`-стейтменты имеют базовый приоритет 500 | движок | `images.gen.rpy` намеренно ставит `init offset = 0` (`images.py:286-288`), не 500 — не «поправляйте» это |
| синтетический ввод (SendKeys) на рабочий стол | ломает чужие окна, недетерминирован, запрещён нормой G23 | только in-process автопилот `vn test smoke` — см. [27-testing.md](27-testing.md) |
| `errors.txt` / `traceback.txt` в корне | движок пишет их сам | в git не хранятся и вырезаны из дистрибутива (`options.rpy:17-22`); лежащий в корне `errors.txt` может быть **устаревшим** — сверяйтесь с датой |

---

## 11. Как не сломать сейвы правкой кода

Коротко (подробно — [07-backend.md](07-backend.md)):

- **Не переименовывайте label'ы вручную.** Метка сцены = её id; переименование сцены = новый id + запись в `content/renames.yaml`, из которой компилятор делает `config.label_overrides.update({…})` и shim-метки (`generated/registry/overrides.gen.rpy:7-9`, сейчас карта пуста).
- **Не трогайте `call … from …`.** Явное имя точки возврата — то, чем старый сейв находит место возврата (G6). Линия `.rpyc` фикстур лежит в `ci/fixtures/rpyc-line/` (52 файла — пересобрана после появления галереи, ачивок и UI-панелей) и восстанавливается перед `vn save corpus`.
- **Переменные, которые должны сохраняться, не начинаются с `_`** — Ren'Py не кладёт их в сейв. Ровно поэтому `vn_menu` и `vn_scene` объявлены без префикса (`020_state.rpy:5-10`).
- **Новая сохраняемая переменная объявляется в `content/**/*.vars.yaml`**, а не `default` в `.rpy`. Иначе она не попадёт в `SNAPSHOT_VARS` и будет невидима миграциям.
- **`persistent`-имена обязаны начинаться с `vn_`** (норма C9, проверяется компилятором: `compile.py:100-104`).
- Изменили форму сохраняемых данных — поднимайте `save_schema` в `project.yaml` и пишите миграцию `content/migrations/NNNN_*.py` с зарезервированным номером в `content/migrations/registry.yaml`. Прогоняются миграции **только в игре**, в `label after_load` (`020_state.rpy:83-107`); `vn save migrate` — заглушка фазы 3.

---

## Как изменить / Как расширить

**Добавить функцию в фасад `vn.*`:**
1. дописать в `game/framework/00_core/030_flow.rpy` внутрь `init -999 python in vn:`; доступ к `vn_compat` — **только внутри тела функции**;
2. если её должен эмитить компилятор — правка `tools/vn/src/vn/content/scenes.py:emit_scene` (это уже изменение тулинга, см. [25-custom-engine.md](25-custom-engine.md));
3. поменяли контракт — поднимите `API_LEVEL` (`030_flow.rpy:9`) и проверьте `api_level` в `packs/*/manifest.yaml`;
4. `vn build && python -m pytest tools/vn/tests -q && vn test smoke`.

**Добавить сцену:** `vn scene new ch01 rooftop` → пара `content/chapters/ch01_awakening/scenes/s040_rooftop.scene.{yaml,rpy}`. Скаффолд **не трогает `chapter.yaml`** — `scene_order` и `exits` дописываются руками (`cli.py` печатает напоминание). Обвязку и экран выбора не пишите: их эмитит компилятор.

**Добавить свой экран:** файл в `game/framework/20_ui/screens/`, первой строкой `init offset = 0`, строки — только через `vn_loc.t(key)` из `content/ui/strings.yaml`. Подробности — [06-frontend.md](06-frontend.md).

**Подключить платформенный бэкенд:** точки внедрения — `vn.pack_registry.set_ownership_provider(fn)` (`030_flow.rpy:73`) и `vn_ach.set_provider(fn)` (`080_achievements.rpy:17`), и **они уже подключены** для Steam в `00_core/035_platform.rpy` (`init 999`) по [ADR-0014](../adr/0014-platform-services.md). Правило жёсткое: **любая платформенная специфика идёт только в `035_platform.rpy`** — прямые обращения к `_renpysteam`/`steamapi` из других файлов `game/` роняют гард-тест `test_platform::test_platform_facade_is_single_steam_touchpoint`. Как добавить свою платформу — [39-platforms.md](39-platforms.md) §9.

---

## Чего НЕ делать

- **Не редактировать `game/generated/**`, `game/assets/**`, `game/tl/**`.** Первое перезапишет `vn build` (и удалит осиротевшие файлы вместе с `.rpyc`), второе — `vn assets build`, третье — `vn loc import`.
- **Не задавать `config.version` в `game/options.rpy`** — его эмитит `generated/version.gen.rpy` из `project.yaml` + git sha. Сам sha на свежесть генерата больше не влияет: `--check` сравнивает `version.gen.rpy` с нормализованным sha (`_stale_key`, `compile.py`), поэтому коммит без правок `content/` генерат устаревшим не делает. Бамп semver в `project.yaml` при этом ловится по-прежнему.
- **Не писать `jump` из сцены в сцену.** Компилятор это ловит; переход — `return "<exit_id>"` + `exits:` в `scene.yaml`.
- **Не делать условные пункты `menu:`** (`menu: "Вариант" if cond:`) — запрещено компилятором, ломает перевод по индексу.
- **Не писать `config.console = config.developer`** в init-фазе — `developer` там строка `"auto"`.
- **Не заводить `image`/`Character` руками** — их эмитит компилятор из `content/`. Исключение — служебный `vn_black`.
- **Не трогать undocumented API движка вне `engine_compat/`** (G18).
- **Не заводить второе присваивание `config.exception_handler`.** Поле одно, выживет последнее по init-порядку; единственный обработчик живёт в `070_crash.rpy:82`, и `tools/vn/tests/test_crash_handler.py` это стережёт.
- **Не полагаться на `docs/ARCHITECTURE.md` как на описание кода** — это целевой документ. `vn.safe_jump`, `vn.register_system`, `vn.scene_enter/leave`, `vn_pos_*`, `vn_qa.choice` в ветках меню там описаны, а в коде их нет (`.rpa`-архивы — наоборот: их отсутствие в desktop-дистрибутиве теперь и есть норма §2.4).
- **Не заводить init-приоритеты за пределами `−999…999`** (ADR-0003) и не занимать уровни выше DLC-слотов (999).

---

## Проверка

```bash
vn doctor                              # окружение: SDK, схемы, шрифты (LFS-указатели ловятся по magic bytes); ffmpeg — не здесь
vn content lint                        # декларации, граф, layout — НЕ контракт меток
vn content compile --check             # генерат актуален? (тут ловится контракт .rpy)
vn build                               # полный проход: lint -> assets -> compile -> loc import
vn build --check                       # ничего не пишет; падает, если генерат отстал
python -m pytest tools/vn/tests -q     # 278 тестов, в т.ч. контракт-тесты engine_compat
vn play                                # запуск руками
vn test smoke                          # in-process автопилот: прогон сцен + бюджет cold start
vn save corpus                         # 2 фикстуры сейвов загружаются и мигрируют
                                       #   (schema1-demo реально гоняет миграцию 0002)
vn release validate --flavor public    # релизный гейт, 21 проверка
```

Правили `00_core/**` или `20_ui/**` — минимум: `vn build && vn test smoke`. Правили что-то, связанное со стеком вызовов, сейвами или миграциями — плюс `python -m pytest tools/vn/tests -q && vn save corpus`.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `game/framework/00_core/030_flow.rpy` (фасад + автопилот), `game/framework/00_core/001_boot.rpy` (конфиг движка, слой `sprites`), `game/framework/00_core/020_state.rpy` (снапшот, `after_load`), `game/framework/00_core/engine_compat/000_compat.rpy`, `tools/vn/src/vn/content/scenes.py` (эмиттер обвязки и весь контракт `.rpy`), `game/generated/scenes/ch01/ch01_s020.gen.rpy` (эталон генерата), `docs/adr/0003-init-scale-engine-limit.md` |
| **Не трогать** | `game/generated/**` (генерат `vn build`, орфаны удаляются), `game/assets/**` (генерат `vn assets build`), `game/tl/**` (генерат `vn loc import`), `*.rpyc`, `errors.txt` / `traceback.txt` / `log.txt` (пишет движок), `ci/fixtures/rpyc-line/**` (линия имён statement'ов для сейв-корпуса, 52 `.rpyc` — правится только через `vn save corpus --add`) |
| **Зависимости** | Правка `030_flow.rpy` → ломается обвязка **всех** сцен (компилятор эмитит вызовы `vn.*` без проверки их существования) и автопилот `vn test smoke`. Правка init-приоритета → падает инициализация зависимого store. Правка `scenes.py` → перегенерируются все `scenes/**/*.gen.rpy`, старые сейвы могут потерять точку возврата. Правка `options.rpy: build.classify` → dev-инструменты или QA-файлы могут уехать в релиз. Правка `gui.rpy` → пересчитываются все стили `20_ui`. |
| **Валидация** | `vn build && python -m pytest tools/vn/tests -q && vn test smoke`; при работе с сейвами/миграциями дополнительно `vn save check && vn save corpus` |
| **Частые ошибки** | 1) Считать `docs/ARCHITECTURE.md` описанием кода — `vn.safe_jump`, `vn.register_system`, `vn.scene_enter/leave`, `vn_pos_*`, `vn_qa.choice` в ветках меню **не реализованы** (а `.rpa`-архивов нет по норме §2.4 — россыпь ради Steam-дельта-патчей). 2) Проверять контракт меток через `vn content lint` — он его не проверяет, нужен `vn content compile`. 3) Писать `jump` между сценами вместо `return "<exit_id>"`. 4) Обращаться к `vn_compat` на уровне модуля в store с приоритетом −999 (он создаётся на −950). 5) Класть новые `.rpy` в `game/generated/**` — их удалит орфан-чистка. 6) Забыть, что `game/build_id.json` в чекауте отсутствует, поэтому игра всегда идёт как `flavor=dev` с `nsfw=True` и всем видимым контентом (`060_build_info.rpy:14-23`). 7) Завести второй `config.exception_handler` — поле одно, выживет последнее присваивание; тест `test_crash_handler.py` уронит прогон. |

**Смежные файлы хендбука:** [02-architecture.md](02-architecture.md) (зоны и нормы G/C), [06-frontend.md](06-frontend.md) (UI-слой), [07-backend.md](07-backend.md) (state, сейвы, миграции), [08-content-pipeline.md](08-content-pipeline.md) (`content/` → `game/generated/`), [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md), [25-custom-engine.md](25-custom-engine.md) (`vn` CLI и компилятор), [27-testing.md](27-testing.md), [28-debugging.md](28-debugging.md).
