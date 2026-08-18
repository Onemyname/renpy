# 15. Галерея и достижения

> **Статус подсистемы:** Галерея — **IMPLEMENTED** (декларации → компилятор → рантайм-стор → экран, ADR-0010), *но* `docs/ARCHITECTURE.md` до сих пор описывает заменённый дизайн на движковом классе `Gallery`. Достижения — **IMPLEMENTED (backend) / NO UI / UNDOCUMENTED**: выдаются и хранятся, но игроку их негде посмотреть.
> **Отвечает на вопрос:** «Как добавить CG/видео/бонус в галерею и как сделать, чтобы оно открывалось в нужный момент — без правки кода экранов?»

Галерея — data-driven подсистема: элемент = стабильный id + ссылка на **уже существующий** ассет + условие разблокировки. Декларация живёт в `content/gallery/*.yaml`, компилятор `_emit_gallery` превращает её в `game/generated/registry/gallery.gen.rpy`, рантайм-стор `vn_gal` (`game/framework/00_core/090_gallery.rpy`) отвечает на вопросы «видно?», «открыто?», «сколько из скольких», а экран `game/framework/20_ui/screens/gallery.rpy` только рисует то, что стор вернул. Достижения устроены зеркально: `content/achievements/*.yaml` → `achievements.gen.rpy` → стор `vn_ach` (`080_achievements.rpy`) — и на этом обрываются, потому что экрана достижений не существует.

## Быстрый ответ

Добавить материал в галерею — четыре шага, ни одной строки кода:

```bash
# 1. Ассет уже собран (иначе компилятор упадёт с «нет в game/assets»)
ls game/assets/cg/ch01/            # rooftop_day.webp + rooftop_day.thumb.webp

# 2. Запись в content/gallery/core.gallery.yaml (см. таблицу полей ниже)
# 3. Строки gal.<id>.title / .desc в content/ui/strings.yaml
vn build                            # схема + ассеты + якоря + сборка генерата
vn loc extract && vn loc import     # новые строки уехали в PO и вернулись в tl/

# 4. Проверка e2e
vn test smoke --picks 0,0
cat .vncache/smoke/gallery.json     # {"unlocked": N, "total": M, "ids": [...]}
```

Стор называется **`vn_gal`**, а не `vn_gallery`. `vn_gallery_unlocked` — это имя persistent-переменной (`persistent.vn_gallery_unlocked`), а не стора. Путать нельзя: `vn_gallery.check(...)` не существует.

## Модель: данные, а не код

`Asset ≠ Gallery entry ≠ Unlock state` (ADR-0010 §4) — три независимых слоя:

| Слой | Где живёт | Кто пишет |
|---|---|---|
| Ассет | `assets_src/png/cg/**` → `game/assets/cg/**` | конвейер (`vn assets build`), см. [16-assets.md](16-assets.md) |
| Запись галереи | `content/gallery/core.gallery.yaml` | человек |
| Состояние разблокировки | `persistent.vn_gallery_unlocked` + движковый `persistent._seen_images` | рантайм |

Следствия, которыми пользуются каждый день:

- **Копий файлов ради галереи не делают.** `asset:` — это логический id (`cg/ch01/rooftop_day`), а не путь; расширение подставляет компилятор: `mov/…` → `.webm`, остальное → `.webp` (`tools/vn/src/vn/content/compile.py:142-145`).
- **Один ассет может входить в несколько записей.** В боевой декларации `cg/ch01/rooftop_day` используется дважды (`cg_ch01_rooftop` и `cg_ch01_concept`), `cg/ch01/rooftop_sunset` — трижды.
- **Закрытость — это состояние, а не отсутствие записи.** Locked-элемент есть в реестре, но содержимого игроку не показывает (`gallery.rpy:83-86`). На этом построен тест `test_repo_compiles_gallery_registry` (`tools/vn/tests/test_gallery.py:160-175`).
- **Реестр — `define`, не `default`** (`gallery.gen.rpy:11-13`): он не попадает ни в сейв, ни в rollback-лог. Сейв-схема не зависит от количества элементов, миграции при добавлении материала не нужны (ADR-0010 §3).

## Полная таблица полей элемента (`gallery@1`)

Источник истины — `tools/schemas/gallery@1.schema.json`. Обязательны: `category`, `kind`, `asset`, `title_key`, `unlock`. `additionalProperties: false` — лишнее поле валит lint.

| Поле | Тип / шаблон | Обяз. | Что делает | Значение по умолчанию в генерате |
|---|---|---|---|---|
| `category` | `^[a-z][a-z0-9_]{1,23}$` | да | Вкладка галереи. Должна быть объявлена в `categories:` того же или соседнего файла, иначе ошибка компиляции (`compile.py:189-191`) | — |
| `kind` | `image` \| `movie` | да | Ветвление UI: `movie` рисует бейдж-ромб на превью и `Movie(...)` в просмотрщике | — |
| `asset` | `^(cg\|bg\|mov)/[a-z0-9_/]+$` | да | Логический id существующего ассета. Проверяется на диске, если `game/assets` собран (`compile.py:197-199`) | превращается в `assets/<id>.webp\|webm` |
| `variants` | список `asset_ref` | нет | Варианты одной CG (свет/одежда/поза). Листаются **внутри** элемента кнопкой «Вариант», отдельными записями не считаются и в прогресс не входят | `[]` |
| `thumb` | `asset_ref` \| `null` | нет | Явное превью. Для `kind: image` не нужен — берётся `<asset>.thumb.webp` из конвейера. Для `kind: movie` **обязателен по смыслу**: у видео своего превью нет, без него warning и пустая заглушка в сетке (`compile.py:224-227`) | вычисленный путь превью |
| `title_key` | `^[a-z0-9_.]+$` | да | Ключ строки в `content/ui/strings.yaml`. Отсутствие ключа — только warning; в игре покажется сырой ключ (`compile.py:244-248`, `040_localization.rpy:151-157`) | — |
| `desc_key` | `^[a-z0-9_.]+$` | нет | Подпись в просмотрщике под заголовком | `None` |
| `chapter` | `^ch\d{2}$` | нет | Глава-владелец: второй ключ сортировки в сетке | `None` |
| `characters` | список slug'ов | нет | Кто на кадре. **Сейчас ничем не читается** — задел под фильтр по персонажу (NOT IMPLEMENTED) | `[]` |
| `order` | integer | нет | Порядок внутри категории; меньше — раньше | `100` |
| `nsfw` | boolean | нет | 18+: в SFW-флейворе элемент не виден и не разблокируется | `False` |
| `pack` | `^[a-z][a-z0-9_]{1,31}$` | нет | Пак-владелец, гейтится владением (G9). **Существование пака не проверяется** — см. «Чего НЕ делать» | `"core"` |
| `unlock` | объект, ровно один якорь | да | `seen_image` \| `scene` \| `beat` \| `var`(+`equals`) \| `chapter_done` \| `always` | — |

Поля категории (`categories.<id>`): `title_key` (обяз.), `order` (по умолчанию 100), `nsfw` (скрывает всю категорию целиком, `090_gallery.rpy:42`).

## Пять элементов `core.gallery.yaml` — по одному на каждый тип unlock

Боевая декларация — `content/gallery/core.gallery.yaml`, три категории (`cg` / `videos` / `extras`) и ровно пять элементов, подобранных так, чтобы каждый демонстрировал свой якорь.

| id | kind | unlock | Как открывается на практике |
|---|---|---|---|
| `cg_ch01_rooftop` | image | `{seen_image: true}` | В `s030_rooftop.scene.rpy:13` есть `scene cg ch01 rooftop_day with dissolve`. Движок сам пишет показ в `persistent._seen_images`; `is_unlocked` спрашивает `renpy.seen_image("cg ch01 rooftop_day")`. Единственный элемент с `variants: [cg/ch01/rooftop_sunset]` — в просмотрщике доступна кнопка «Вариант» |
| `mov_ch01_ambient` | movie | `{scene: ch01_s030}` | `vn.checkpoint("ch01_s030")` из обвязки сцены → `vn_gal.check(scene_id="ch01_s030")` → запись в `persistent.vn_gallery_unlocked`. `_seen_images` про видео не знает вообще, поэтому якорь-сцена. Явный `thumb: cg/ch01/rooftop_sunset` — постер-кадр |
| `cg_ch01_finale` | image | `{chapter_done: ch01}` | Терминальная сцена главы (без `exits`) получает `$ vn.chapter_done("ch01")` от компилятора → `vn_gal.check(chapter_done="ch01")`. Награда за прохождение, а не за показ кадра |
| `cg_ch01_concept` | image | `{always: true}` | `is_unlocked` возвращает True сразу (`090_gallery.rpy:53-54`), состояние нигде не хранится. Концепт-арт/обои. Единственный элемент без `desc_key` |
| `cg_ch01_route_mira` | image | `{var: g.route, equals: mira}` | `_var_value("g.route")` сравнивается с `"mira"` на каждом якоре. В демо-сборке `g.route` стартует как `'prologue'` и роут не проходится — элемент **намеренно остаётся locked**, чтобы в игре и на скриншотах CI была видна закрытая ячейка |

Фактический результат прогона (`.vncache/smoke/gallery.json`, `vn test smoke --picks 0,0`): `unlocked: 4, total: 5`, закрыт `cg_ch01_route_mira`. Это и есть регрессионный якорь подсистемы.

Шестой тип якоря — `beat` — схемой разрешён, но **фактически недостижим**: `vn.beat()` компилятором никогда не эмитится и ни в одной сцене вручную не вызывается. Чтобы `unlock: {beat: x}` заработал, автор обязан сам поставить `$ vn.beat("x")` в теле `*.scene.rpy` (`030_flow.rpy:19-24`). Статус: **PARTIALLY IMPLEMENTED** — рантайм готов, точек вызова нет.

## Два источника разблокировки — и почему их два

Это самое важное место подсистемы. ADR-0010 §2 фиксирует таблицу:

| Что | Источник состояния | Почему так |
|---|---|---|
| `kind: image` + `unlock: {seen_image: true}` | штатный `persistent._seen_images` движка | Обещание «ручного кода разблокировки нет» сохранено: показал кадр в сцене — он в галерее. Работает на старых сейвах и при перепрохождении без миграций |
| всё остальное: `scene` / `beat` / `var` / `chapter_done` + **любое видео** | `persistent.vn_gallery_unlocked = {id: True}` | Движок про эти события ничего не знает |

**Почему `_seen_images` не годится для видео.** `persistent._seen_images` заполняется движком при показе *образа* (`image`-стейтмента). Видео у нас объявлено как `image mov demo ambient = Movie(play="assets/mov/demo/ambient.webm", loop=True)` (`game/generated/registry/images.gen.rpy:15`), но в галерее видео проигрывается через `Movie(...)` прямо в просмотрщике, а в сценах ролик может вообще не показываться как образ. Полагаться на это нельзя — поэтому компилятор жёстко запрещает `seen_image` для `kind: movie` (`compile.py:230-232`, тест `test_seen_image_only_for_images`).

**Где вызывается `check`.** Ровно три точки, все в `game/framework/00_core/030_flow.rpy` — те же, что у достижений:

```renpy
def checkpoint(scene_id):                      # :12  — эмитится компилятором в каждую сцену
    renpy.store.vn_scene = scene_id
    renpy.store.vn_ach.check(scene_id=scene_id)
    _gallery_notify(renpy.store.vn_gal.check(scene_id=scene_id))

def beat(beat_id=None):                        # :19  — только вручную из тела сцены
    if beat_id is not None:
        renpy.store.vn_ach.check(beat_id=beat_id)
        _gallery_notify(renpy.store.vn_gal.check(beat_id=beat_id))

def chapter_done(chapter_id):                  # :26  — эмитится в терминальную сцену главы
    renpy.store.vn_ach.check(beat_id="chapter_done:%s" % chapter_id)
    _gallery_notify(renpy.store.vn_gal.check(chapter_done=chapter_id))
```

`_gallery_notify` (`030_flow.rpy:32-42`) берёт список только что открытых id и шлёт `renpy.notify` со строкой `ui.gallery.unlocked_one` / `ui.gallery.unlocked_many` (в `_many` подставляется `[n]` через `str.replace`).

**Важное следствие про `var`-якоря.** В `check()` (`090_gallery.rpy:96-104`) стоит цепочка `if/elif`, и ветка `elif "var" in u` достигается при **любом** вызове — с `scene_id`, с `beat_id`, с `chapter_done`. То есть `var`-условие переоценивается на каждой границе сцены. Но не в момент присваивания: если сцена ставит `g.route = "mira"` в середине, элемент откроется только на **следующем** `checkpoint`/`chapter_done`, а не сразу. Это же верно для достижений (`080_achievements.rpy:79-84`).

## Runtime API стора `vn_gal` (`090_gallery.rpy`) — IMPLEMENTED

`init -980 python in vn_gal` (:20). Экраны обязаны ходить только сюда: списка элементов и правил разблокировки в UI нет.

| Функция | Строка | Что делает |
|---|---|---|
| `visible(item_id)` | :34 | Показывать ли вообще. `False`, если элемента нет в реестре; если `spec.nsfw` **или** `category.nsfw` при `vn_build.nsfw == False`; если пак не «во владении» (`vn.pack_registry.owned`) |
| `is_unlocked(item_id)` | :46 | `False`, если невидим. `always` → True. `seen_image` → `renpy.seen_image(spec["image_name"])`. Иначе — `persistent.vn_gallery_unlocked.get(id)` |
| `unlock(item_id, silent=False)` | :61 | Явная разблокировка, идемпотентная. Неизвестный id → `vn_log`, не краш. Возвращает `True` **только при смене состояния** — на этом стоит уведомление. При `silent=False` кладёт id в `_pending` |
| `take_pending()` | :77 | Забрать и очистить очередь открытых. **Zero call sites** — `_gallery_notify` использует возврат `check()`. Список `_pending` (:75) растёт до конца процесса. Статус: IMPLEMENTED / UNUSED |
| `check(scene_id=None, beat_id=None, chapter_done=None)` | :88 | Прогон всех якорей, возвращает список новых id. Дёшево: линейный проход по десяткам записей |
| `categories()` | :111 | `[(id, spec)]` в объявленном порядке, **только непустые** (категория без видимых элементов исчезает) |
| `items(category=None)` | :120 | `[(id, spec)]` только видимые, сортировка `(order, chapter, id)` |
| `progress(category=None)` | :128 | `(открыто, всего)` — считается динамически, никаких сохранённых счётчиков |
| `unlocked_ids(category=None)` | :134 | Список открытых id; используется просмотрщиком для листания prev/next и автопилотом для `gallery.json` |

`default persistent.vn_gallery_unlocked = {}` (:138). Имя с префиксом `vn_` — норма C9; плоская persistent-переменная, а не dict-корень (Ren'Py мержит persistent пофилдово).

## Превью

Для `kind: image` превью **не объявляют** — его делает конвейер ассетов. Каждый PNG из `assets_src/png/cg/**` даёт две работы (`tools/vn/src/vn/assets/pipeline.py:156-157`):

| Трансформация | Выход | Параметры |
|---|---|---|
| `png2webp_cg` | `cg/<путь>.webp` | WebP q90 (`full`) / q50 (`draft`) |
| `png2webp_cg_thumb` | `cg/<путь>.thumb.webp` | WebP q80, длинная сторона 512 px (`pipeline.py:228-231`) |

Логика выбора превью в компиляторе (`compile.py:204-227`):

1. Есть `thumb:` в декларации → берётся `<thumb>.thumb.webp`, если он существует, иначе полноразмерный `<thumb>`. То есть даже явный постер ужимается до миниатюры, если конвейер её сделал.
2. Нет `thumb:`, `kind: image` → `<asset>.thumb.webp`. Если файла нет — warning «нет превью… ожидается `png2webp_cg_thumb`» и в сетку идёт полноразмерный кадр.
3. Нет `thumb:`, `kind: movie` → warning «kind: movie без thumb», `thumb: None`, и экран падает на `spec["asset"]` (`gallery.rpy:76`) — то есть в ячейку попадёт `.webm`. **У видео своего превью нет: указывайте `thumb:` всегда.**

## Экран галереи (`20_ui/screens/gallery.rpy`) — IMPLEMENTED

Рукописный файл, **не генерат** (вопреки `ARCHITECTURE.md:337,1369`, где обещан `game/generated/screens/gallery.gen.rpy` — такого файла не существует). Добавление элемента, категории или языка правок этого файла не требует.

| Часть | Строки | Устройство |
|---|---|---|
| `screen gallery()` | :21 | `tag menu`, поверх `use vn_game_menu(vn_loc.t("ui.nav.gallery"))` — тот же каркас, что у save/load/preferences |
| Прогресс | :37 | `text "[_done] / [_total]"` из `vn_gal.progress()` |
| Вкладки | :40-45 | `textbutton "<title>  <done>/<total>"` на категорию, `action SetVariable("vn_gal_category", _cid)`, `selected (_cid == _cur)` |
| Пустое состояние | :47-48 | `ui.gallery.empty`, если `categories()` пуст |
| Сетка | :50-63 | `vpgrid cols 3`, `ysize 800`, `scrollbars "vertical"` — с обязательными `vscrollbar_base_bar` / `vscrollbar_thumb` (без них Ren'Py полосу не рисует) |
| `screen vn_gal_cell` | :68 | Ячейка `472×266`. Открытая: `add (spec["thumb"] or spec["asset"]) fit "cover"` + плашка `#0a0a0cd9` под подпись + бейдж `vn_gal_play` для `kind == "movie"`. Закрытая: `Solid(gui.panel_bg_deep)` + «?» + `ui.gallery.locked`, **контент не показывается никогда** |
| `screen gallery_viewer(item_id)` | :91 | `modal True`, `zorder 60`, `default variant = 0` |
| Видео в просмотрщике | :107 | `add Movie(play=_spec["asset"], loop=True) fit "contain"` — displayable существует ровно пока показан экран; `Hide` останавливает воспроизведение и освобождает ресурс |
| Картинка / зум | :111 | `fit ("cover" if vn_gal_zoom else "contain")` — `contain` не растягивает при любых пропорциях |
| Управление | :124-141 | prev / вариант / зум / next / назад. prev-next ходят только по **открытым** элементам той же категории (`unlocked_ids`) |
| Клавиатура | :144-148 | `K_LEFT` / `K_RIGHT` листают, `K_ESCAPE` и `game_menu` закрывают |
| Бейдж видео | :152 | `image vn_gal_play = Transform(Solid(gui.text_color), xysize=(26,26), rotate=45, alpha=0.85)` — без бинарных ассетов |

Пункт навигации условный: `if vn_gal.categories(): textbutton ui.nav.gallery` (`20_ui/screens/core_screens.rpy:97-98`) — гейт живёт в сторе, не в вёрстке. Галерея доступна и из главного меню, и из игрового.

**Мелкие кнопки галереи стоят на чипах (`2*Borders`, ADR-0009) — дефект закрыт, IMPLEMENTED.** Вкладка и кнопка просмотрщика — это 29-31 px высоты, а панели `choice*` требуют 54-60 px: раньше обе брали их и получали сплющенный фон. Теперь в `content/ui/panels.yaml` объявлена своя пара рамок `chip` / `chip_active` (`radius: 8`, `Borders(11)`, минимум 22×22) — панелей в декларации стало **8** (было 6), нарушений `2*Borders` в вёрстке не осталось:

| Стиль | Строки | Фактическая высота | Рамка (минимум) |
|---|---|---|---|
| `vn_gal_tab` | :161-168 | padding (16, 6) + строка 19 px = **31 px** | `hover_background vn_frame_chip`, `selected_background vn_frame_chip_active` → **22 px** |
| `vn_gal_ctl_button` | :221-225 | padding (16, 6) + строка 17 px = **29 px** | `background vn_frame_chip`, `hover_background vn_frame_chip_active` → **22 px** |

Ячейка сетки (`vn_gal_cell`, :182-186) фиксирована `xysize (472, 266)` — ей `slot` и `choice_hover` подходят без оговорок.

Минимумы печатает эмиттер в комментариях `game/generated/registry/ui_frames.gen.rpy:12-19`. Регресс стерегут два теста в `tools/vn/tests/test_ui_panels.py`: `test_every_frame_consumer_is_not_smaller_than_2x_borders` (`:244`) разбирает все `style`-блоки `game/**/*.rpy` и сверяет высоту с `2*Borders`, так что новая мелкая кнопка на `choice*` уронит прогон; `test_gallery_chips_fit_their_small_buttons` (`:284`) отдельно следит, чтобы чипы не растолстели, а вкладка и кнопка просмотрщика не вернулись на `choice*`. Заводя ещё один компактный элемент, берите `chip`/`chip_active`. Подробности — [06-frontend.md](06-frontend.md).

## NSFW-гейт и паки

Два независимых механизма, и путать их дорого:

1. **Скрытие записи в UI** — `vn_gal.visible()` (`090_gallery.rpy:42`): при `spec["nsfw"]` или `category["nsfw"]` и `vn_build.nsfw == False` элемент не виден, не считается в прогрессе и **не разблокируется** (`unlock` и `is_unlocked` начинаются с проверки `visible`).
2. **Исключение файлов из дистрибутива** — `nsfw_exclude_globs` (`tools/vn/src/vn/release.py:192-203`): глобы строятся от **фактических каталогов** `game/assets/<категория>/nsfw/**`. Флаг `nsfw: true` в YAML на это никак не влияет.

Значит: NSFW-кадр обязан лежать в `assets_src/png/cg/nsfw/**` → `game/assets/cg/nsfw/**`, иначе в `public`-сборке запись спрячется, а сам файл уедет в дистрибутив. Сейчас каталогов `nsfw/` в проекте нет, поэтому оба выпущенных `build/dist/0.1.0-*/build-info.json` несут `"exclude": []`.

`vn_build.nsfw` берётся из `game/build_id.json`, который пишется только на время `distribute`. В чекауте файла нет → `flavor=dev`, `nsfw=True` → **в разработке видно всё**. Проверять гейт нужно на собранном флейворе, см. [29-build-and-release.md](29-build-and-release.md).

Пак-гейт: `visible()` спрашивает `vn.pack_registry.owned(spec.get("pack", "core"))`. Без провайдера владения установленный пак считается купленным (`030_flow.rpy:79-86`), а не установленный — нет. Деклараций галереи внутри `packs/<id>/` компилятор **не читает** (сканируется только `content/gallery/`, `compile.py:640-652`) — элементы DLC объявляют в общем файле с полем `pack:`. См. [30-packs-and-dlc.md](30-packs-and-dlc.md).

## Валидация: что ловится до запуска игры

Схема (`gallery@1`) проверяется дважды — в `vn content lint` (все YAML под `content/` идут через `SchemaRegistry`, `tools/vn/src/vn/content/lint.py:89-92`) и в компиляторе перед эмиссией (`compile.py:647-650`). Семантика — только в компиляторе, `_emit_gallery`:

| Проверка | Уровень | Строки |
|---|---|---|
| `game/assets` не собран | warning (проверки ассетов отключаются целиком) | :161-164 |
| Категория не объявлена | **error** | :189-191 |
| Ассета/варианта нет в `game/assets` | **error** | :197-199 |
| `kind: movie`, а ассет не из `mov/` (и наоборот) | **error** | :200-203 |
| Явного `thumb` нет в `game/assets` | **error** | :209-210 |
| `unlock.seen_image` при `kind: movie` | **error** | :230-232 |
| `unlock.scene` — такой сцены нет | **error** | :233-234 |
| `unlock.chapter_done` — такой главы нет | **error** | :235-238 |
| `unlock.var` нет в Variable Registry | **error** | :239-242 |
| Дубликат id или категории между файлами | **error** | :172-183 |
| Нет `<asset>.thumb.webp` | warning | :219-221 |
| `kind: movie` без `thumb` | warning | :224-227 |
| `title_key`/`desc_key` нет в `strings.yaml` | warning | :244-248 |
| CG собран, но в галерее не объявлен («осиротевший CG») | warning | :268-279 |

Ошибки поднимают `CompileError` до записи генерата (`compile.py:846-848`) — битая запись физически не может доехать до игры. Проверки существования `pack:` у элемента галереи **нет** (у достижений есть, `compile.py:814-817`).

Юнит-тесты подсистемы: `tools/vn/tests/test_gallery.py` (10 тестов), включая проверку боевой декларации на схему и наличие всех её `title_key`/`desc_key` в `strings.yaml` (:145-157).

## Достижения (`achievements@1`) — IMPLEMENTED (backend) / NO UI / UNDOCUMENTED

Декларация: `content/achievements/core.achievements.yaml`, схема `tools/schemas/achievements@1.schema.json`. Поля элемента: `name_key` (обяз.), `desc_key`, `hidden`, `nsfw`, `pack`, `trigger` (обяз., ровно один из `scene` / `beat` / `var`+`equals`).

Сейчас объявлены две ачивки:

```yaml
met_mira:        trigger: {var: ch01.met_mira, equals: true}
reached_rooftop: trigger: {scene: ch01_s030}
```

Стор `vn_ach` (`080_achievements.rpy`): `set_provider(fn)` :17 (Steam-подобный бэкенд — **вызывающих нет**), `visible(id)` :31 (NSFW + пак), `has(id)` :43, `grant(id)` :46 (идемпотентно; неизвестный id → `vn_log`, не краш; исключение провайдера ловится и логируется), `check(scene_id=None, beat_id=None)` :70, `all_ids()` :89. Хранилище — `persistent.vn_achievements = {id: True}` (:92).

Что честно **отсутствует**:

- **Экрана достижений нет.** Ни один файл в `game/framework/20_ui/screens/` не упоминает достижения. Строки `ach.met_mira.name` / `.desc` и `ach.reached_rooftop.*` лежат в `content/ui/strings.yaml:15-18`, переводятся, но потребителя не имеют. Ачивки выдаются и хранятся — игрок их не видит.
- **Steam-синхронизации нет.** `set_provider` ждёт вызова, которого никто не делает.
- **Поле `hidden` не читается** ничем (задел под спойлерные ачивки).
- **Документации нет.** В `docs/ARCHITECTURE.md` слово `achievements.yaml` встречается ровно один раз (строка 2720) и только как источник для loc-экстракции; ни раздела, ни ADR. Итоговый статус подсистемы: **IMPLEMENTED / UNDOCUMENTED**.

В отличие от галереи, якоря достижений проверяются на существование в основном теле компилятора (`compile.py:786-823`), включая пак-владельца, и различают «сцены нет вовсе» (error) и «главы нет в этой сборке» (warning — частичная/пак-сборка).

## ADR-0010: что решили и где расходится с ARCHITECTURE.md

`docs/adr/0010-gallery-extras.md` (принят 2026-08-08) заменяет решение раздела 6 ARCHITECTURE.md. Кратко: галерея делается зеркально достижениям — декларация → эмиттер → рантайм-стор → persistent; своего механизма событий не вводится, используются те же якоря и те же точки вызова.

**Конфликт документов, который надо знать наизусть.** `docs/ARCHITECTURE.md` в строках 151, 201, 1226, 1634-1653, 2978, 3935 всё ещё требует: галерея = движковый класс `Gallery` + `unlock_image` + только `persistent._seen_images`, «свой dict не ведётся», «`persistent.gallery_unlocked` не существует», экран генерируется в `game/generated/screens/gallery.gen.rpy`. **Ничего из этого не соответствует коду.** Канон — ADR-0010 и код; ARCHITECTURE.md после принятия ADR не обновлялся. Файла `game/generated/screens/gallery.gen.rpy` не существует (в `game/generated/screens/` лежит только `chapter_select.gen.rpy`).

Принятые цены решения (ADR-0010 «Последствия»):

- Два источника состояния вместо одного — сложнее рассуждать; правило зафиксировано таблицей и тестами.
- `_seen_images` привязан к **имени образа**: переименование CG-ассета молча «забудет» разблокировку. Кода-защиты нет. Для важных кадров используйте явный якорь (`scene`/`beat`), а имена ассетов не переименовывайте (дух G7).

## Как добавить элемент галереи — пошагово

1. **Положите сырец** в `assets_src/png/cg/ch01/<slug>.png` (каждый сегмент пути — slug: `^[a-z][a-z0-9_]*$`). Видео — `assets_src/video_src/<group>/<name>.<ext>`, см. [21-video-generation.md](21-video-generation.md).
2. **Соберите ассеты:** `vn assets build` (или сразу `vn build`). Убедитесь, что появились оба файла:
   ```bash
   ls game/assets/cg/ch01/<slug>.webp game/assets/cg/ch01/<slug>.thumb.webp
   ```
3. **Добавьте запись** в `content/gallery/core.gallery.yaml`. Id — стабильный, `^[a-z][a-z0-9_]{2,63}$`, менять нельзя никогда (он и есть ключ в `persistent.vn_gallery_unlocked`):
   ```yaml
     cg_ch02_kiss:
       category: cg
       kind: image
       asset: cg/ch02/kiss
       title_key: gal.cg_ch02_kiss.title
       desc_key: gal.cg_ch02_kiss.desc
       chapter: ch02
       characters: [mira]
       order: 30
       unlock: {seen_image: true}
   ```
4. **Добавьте строки** в `content/ui/strings.yaml` (блок «Названия материалов галереи», ~строка 42):
   ```yaml
     gal.cg_ch02_kiss.title: "Поцелуй"
     gal.cg_ch02_kiss.desc: "Финал второй главы"
   ```
5. **Соберите:** `vn build`. Компилятор проверит ассет, категорию, якорь и ключи строк.
6. **Локализация:** `vn loc extract` → `vn loc import`. Ключи UI-строк уезжают в домен `common` с `msgctxt string:<key>` (`tools/vn/src/vn/loc/po.py:178,210`). Подробности — [14-localization.md](14-localization.md).
7. **Проверьте e2e:**
   ```bash
   vn test smoke --picks 0,0
   cat .vncache/smoke/gallery.json
   ```
   Число `total` должно вырасти; если элемент должен открываться в этом прогоне — его id обязан появиться в `ids`.

Никакой экран, стиль или `.rpy` при этом не трогают. Скаффолда для галереи нет (`vn scene new`-подобной команды для `*.gallery.yaml` не существует, `scaffold.py` её не знает) — YAML правится руками.

## Как расширить

| Задача | Что делать |
|---|---|
| Новая категория | Блок в `categories:` + `title_key` в `strings.yaml`. UI не трогать: вкладки рисуются циклом по `vn_gal.categories()` |
| Новый тип контента (`kind`) | Расширить `enum` в `tools/schemas/gallery@1.schema.json:39-42`, добавить ветку в `_gallery_asset_paths` (расширение) и ветвление в `gallery.rpy:80,105,136`. Экран ветвится по `kind`, а не переписывается |
| Разблокировка «за просмотр момента» | `unlock: {beat: <name>}` **плюс** руками `$ vn.beat("<name>")` в теле сцены — иначе якорь мёртв |
| Фильтр по персонажу | Данные уже есть (`characters`), потребителя нет — писать новый (`items()` + вкладку/выпадашку) |
| Экран достижений | Всё готово со стороны данных: `vn_ach.all_ids()`, `visible()`, `has()`, `VN_ACHIEVEMENTS[id]["name_key"/"desc_key"/"hidden"]`. Нужен файл в `game/framework/20_ui/screens/`, пункт навигации рядом с галереей (`core_screens.rpy:97-98`) и `Frame`-фон из `ui_frames.gen.rpy` — соблюдая `2*Borders` |
| Steam-ачивки | `vn_ach.set_provider(fn)` из `label splashscreen` после инициализации Steam. Контент-код не трогается (ADR-0010 §Последствия) |

## Чего НЕ делать

- **Не править `game/generated/registry/gallery.gen.rpy` и `achievements.gen.rpy`** — это генерат, `vn build` перезапишет. Источник — `content/gallery/`, `content/achievements/`.
- **Не переименовывать id элемента и не переименовывать CG-ассет с `unlock: {seen_image: true}`.** Id — ключ в `persistent`, имя ассета — ключ в `_seen_images`. Переименование = тихая потеря разблокировки у всех игроков, без единого сообщения.
- **Не писать `vn_gallery.check(...)`.** Стор — `vn_gal`. `vn_gallery_unlocked` — persistent-переменная.
- **Не рассчитывать, что `var`-якорь сработает в момент присваивания.** Он проверяется только на `checkpoint` / `beat` / `chapter_done`.
- **Не ставить `unlock: {beat: ...}`, не добавив `$ vn.beat("...")` в сцену.** Компилятор `beat`-якоря не эмитит и на их недостижимость не ругается — получится мёртвый контент.
- **Не полагаться на `nsfw: true` для исключения файла из `public`-сборки.** Флаг прячет запись; файл исключает только физическое размещение в `game/assets/<категория>/nsfw/**`.
- **Не ошибаться в `pack:`.** Существование пака у элемента галереи не проверяется: опечатка → `owned()` вернёт False → элемент навсегда невидим без единой ошибки сборки.
- **Не класть в сетку полноразмерные кадры.** Если `.thumb.webp` не собрался, компилятор только предупредит, а игра начнёт декодировать полные CG в сетке 3 колонки.
- **Не добавлять `thumb` видео как `.webm`.** Постер — картинка (`cg/...`), иначе в ячейке окажется видеофайл.
- **Не проверять NSFW-гейт в dev-чекауте** — `game/build_id.json` отсутствует, `vn_build.nsfw == True`, видно всё.

## Проверка

```bash
vn content lint                 # схема gallery@1 / achievements@1
vn build                        # семантика: ассеты, превью, категории, якоря, ключи строк
python -m pytest tools/vn/tests/test_gallery.py -q     # 10 тестов подсистемы
python -m pytest tools/vn/tests -q                     # весь набор: 253 теста

vn test smoke --picks 0,0
cat .vncache/smoke/gallery.json                        # {"unlocked":4,"total":5,"ids":[...]}
```

Скриншот самого экрана галереи снимается только при заданной переменной окружения — **`vn test smoke` её не выставляет** (передаются лишь `VN_AUTOPILOT_PICKS` и `VN_AUTOPILOT_LANG`, `tools/vn/src/vn/cli.py:1370`). Чтобы получить `.vncache/smoke/screen_gallery.png`, переменную задают вручную перед прогоном:

```bash
VN_AUTOPILOT_SCREENS=gallery vn test smoke --picks 0,0     # bash
$env:VN_AUTOPILOT_SCREENS="gallery"; vn test smoke --picks 0,0   # PowerShell
```

Обработчик — `vn_qa.autopilot_screens()` (`030_flow.rpy:166-184`), вызывается из `label vn_end_of_content` **до** выхода, когда разблокировки уже произошли. В `.github/workflows/nightly.yml:57-60` четыре прогона smoke, но `VN_AUTOPILOT_SCREENS` не выставлен ни в одном — статус проверки вёрстки галереи в CI: **NOT IMPLEMENTED** (артефакт `gallery.json` при этом пишется всегда, `030_flow.rpy:201-210`). См. [27-testing.md](27-testing.md).

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `content/gallery/core.gallery.yaml`, `tools/schemas/gallery@1.schema.json`, `docs/adr/0010-gallery-extras.md`, `game/framework/00_core/090_gallery.rpy`, `tools/vn/src/vn/content/compile.py:139-290` |
| **Не трогать** | `game/generated/registry/gallery.gen.rpy`, `game/generated/registry/achievements.gen.rpy`, `game/assets/**`, `.vncache/**` — производные зоны, перезапишет `vn build` |
| **Зависимости** | Запись галереи требует собранного ассета (`vn assets build`), существующего якоря (сцена/глава/переменная), объявленной категории и ключей в `content/ui/strings.yaml`. Ниже по течению: `vn loc extract/import` (новые строки), `vn test smoke` (`gallery.json`), релизный гейт `vn release validate` (покрытие переводов) |
| **Валидация** | `vn content lint` → `vn build` → `python -m pytest tools/vn/tests/test_gallery.py -q` → `vn test smoke --picks 0,0` + `.vncache/smoke/gallery.json` |
| **Частые ошибки** | 1) Стор называется `vn_gal`, не `vn_gallery`. 2) `docs/ARCHITECTURE.md` описывает **заменённый** дизайн на движковом `Gallery` + `_seen_images`; канон — ADR-0010 и код, `game/generated/screens/gallery.gen.rpy` не существует. 3) `unlock: {beat: ...}` бесполезен без ручного `$ vn.beat(...)` в сцене — компилятор его не эмитит. 4) `seen_image` запрещён для `kind: movie` (ошибка компиляции) и ломается при переименовании ассета (тихо). 5) `nsfw: true` прячет запись, но не исключает файл из дистрибутива. 6) Опечатка в `pack:` у элемента галереи не диагностируется — элемент просто исчезает |
