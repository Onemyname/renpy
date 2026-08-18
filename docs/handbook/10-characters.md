# 10. Персонажи

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — декларация → layeredimage работает сквозным конвейером (`character.yaml` → `vn assets build` → `vn build` → `game/generated/registry/{characters,images}.gen.rpy`), **но** всё заведение персонажа делается руками: `vn char new` / `vn char validate` / `vn char sheet` — заглушки (exit 3). Поле `animated` есть в схеме и не читается ни одной строкой кода. **Обновлено ADR-0012:** `canvas` стал контрактом (холст мастеров проверяется сборкой), `overlays` эмитятся независимыми атрибутами, ветка `side/` реализована (портреты say-окна).
> **Отвечает на вопрос:** «Как завести нового персонажа, чтобы он показался в сцене и не сломал сборку».

Персонаж живёт в трёх зонах одновременно: декларация `content/characters/<id>/character.yaml` (git, человек), сырцы слоёв `assets_src/png/characters/<id>/<pose>/**` (git, ADR-0004), собранные слои `game/assets/spr/<id>/<pose>/**` (не в git, пишет `vn assets build`). Кодоген связывает их в `define <id> = Character(...)` и `layeredimage <id>`. Сегодня в репозитории **один** персонаж — `mira`, одна поза `a`, 2 наряда, 3 эмоции, 6 файлов слоёв.

---

## Быстрый ответ

Завести персонажа `lena` целиком руками (CLI-скаффолда нет):

```bash
mkdir -p content/characters/lena
mkdir -p assets_src/png/characters/lena/a/{outfits,faces}
# положить base.png, outfits/<o>.png, faces/<e>.png
# написать content/characters/lena/character.yaml (шаблон ниже)
vn content lint          # id == имени папки, конвенции имён
vn assets build          # PNG -> game/assets/spr/lena/a/**@2.webp
vn build                 # lint -> assets -> компиляция; здесь валидируется matrix
vn play                  # проверить show lena a school neutral
```

Показать в сцене (файл `content/chapters/chNN_*/scenes/sNNN_*.scene.rpy`):

```renpy
show lena a school neutral at center with dissolve
show lena smile      # достаточно частичного набора атрибутов
```

---

## 1. Зоны и что где лежит

| Зона | Путь | В git? | Кто пишет | Статус |
|---|---|---|---|---|
| Декларация | `content/characters/<id>/character.yaml` | да | человек | IMPLEMENTED |
| Сырцы слоёв (PNG) | `assets_src/png/characters/<id>/<pose>/{base.png,outfits/*.png,faces/*.png,overlays/*.png}` | да (ADR-0004, бюджет 30/50 МБ) | человек / рендер | IMPLEMENTED |
| Сырцы слоёв (PSD) | `assets_src/psd/characters/<id>/<id>_<pose>.psd` | да | художник | IMPLEMENTED / UNEXERCISED — ни одного `.psd` в репозитории |
| Staging нарезки PSD | `.vncache/psd_png/characters/<id>/<pose>/**` | нет | `vn assets build` | IMPLEMENTED / UNEXERCISED |
| Собранные слои | `game/assets/spr/<id>/<pose>/**@2.webp` | **нет** | `vn assets build` | IMPLEMENTED |
| Кодоген | `game/generated/registry/characters.gen.rpy`, `.../images.gen.rpy` | **нет** | `vn build` | IMPLEMENTED |
| Имя персонажа для переводчика | `loc/po/<lang>/common.po`, `msgctxt "char:<id>"` | да | `vn loc extract` + переводчик | IMPLEMENTED |
| Переводы имени | `game/tl/<lang>/common.rpy` (`translate <lang> strings`) | **нет** | `vn loc import` | IMPLEMENTED |

Правки в `game/assets/`, `game/generated/`, `game/tl/` бесполезны — их перезапишет ближайшая сборка. Подробности зон — [16-assets.md](16-assets.md), [08-content-pipeline.md](08-content-pipeline.md).

---

## 2. `character.yaml` — полная таблица полей

Реальный файл `content/characters/mira/character.yaml` целиком:

```yaml
schema: character@1
id: mira
name: "Мира"
color: "#c94f7c"
voice_tag: mira
canvas: [1200, 2200]
matrix:
  poses: [a]
  outfits: [school, casual]
  emotions: [neutral, smile, angry]
  required:
    - {pose: a, outfits: [school, casual], emotions: [neutral, smile, angry]}
```

Схема: `tools/schemas/character@1.schema.json`, `additionalProperties: false`, обязательны только `schema, id, name, color` (`character@1.schema.json:69`).

| Поле | Обяз. | Паттерн / тип | Кто читает | Статус |
|---|---|---|---|---|
| `schema` | да | `const character@1` | `registry.validate` в `compile.py:668` | IMPLEMENTED |
| `id` | да | `^[a-z][a-z0-9_]{1,23}$`, **обязан равняться имени папки** | линтер `lint.py:309`, эмиттеры | IMPLEMENTED |
| `name` | да | непустая строка, исходный язык | `emit_characters` → `Character(_('Мира'), …)` (`scenes.py:315`) | IMPLEMENTED |
| `color` | да | `^#[0-9a-fA-F]{6}$` | `Character(color=…)` — цвет имени в say-окне | IMPLEMENTED |
| `voice_tag` | нет | `^[a-z][a-z0-9_]*$` | `Character(voice_tag=…)` | IMPLEMENTED — тег даёт per-character mute в настройках; сама озвучка привязана не к тегу, а к say-id через манифесты `voice@1` (см. [23-audio.md](23-audio.md) §8; заглушкой осталась только `vn voice tts`) |
| `canvas` | нет | `[int,int]`, обе ≥1 | `assets/pipeline.py` — холст всех мастеров персонажа | IMPLEMENTED (ADR-0012): расхождение = ошибка сборки |
| `matrix` | нет | объект, ниже | `emit_images` (`images.py:357-510`) | IMPLEMENTED |
| `animated` | нет | `{backend: live2d\|spine, source, map}` | **никто** — 0 совпадений `animated`/`live2d`/`spine` в коде тулинга | NOT IMPLEMENTED (G12, ARCHITECTURE.md:75) |

Практические следствия:

- `matrix` **необязателен**. Персонаж без `matrix` компилируется в `Character(...)` и годится как «голос за кадром»/озвучка без спрайта. Если при этом в `game/assets/spr/<id>/` что-то есть — будет warning «спрайты собраны, но в character.yaml нет блока matrix» (`images.py:110-113`).
- `canvas` — контракт (ADR-0012): все мастера персонажа обязаны лежать на этом холсте, иначе layeredimage смещает наряд и эмоцию относительно тела. Проверяет `vn assets build`.
- `image='<id>'` в `Character(...)` подставляется всегда (`scenes.py:315`) — то есть Ren'Py ждёт образ с тегом, совпадающим с id. Если `matrix` нет и `layeredimage` не сгенерился, `show <id>` упадёт в рантайме; `say` при этом работает.

---

## 3. `matrix` — что это и как валидируется

`matrix` описывает **состав** спрайта, а не комбинации файлов. Файлы слоёв лежат внутри позы, поэтому арт-стоимость аддитивна: `файлов = poses × (1 + outfits + emotions)`. Для `mira` это `1 × (1 + 2 + 3) = 6` — ровно столько PNG на диске.

| Ключ | Обяз. | Смысл |
|---|---|---|
| `poses` | да | Токены поз. Одна поза = один каталог `assets_src/png/characters/<id>/<pose>/` и один `base.png`. Порядок важен: первая поза получает `default` в группе `pose`. |
| `outfits` | да | Токены нарядов. Файл — `<pose>/outfits/<outfit>.png`. |
| `emotions` | да | Токены эмоций (лиц). Файл — `<pose>/faces/<emotion>.png`. |
| `required` | нет | Список `{pose, outfits: [...], emotions: [...]}` — комбинации, которые **обязаны** быть собраны. Отсутствие слоя = ошибка компиляции. |
| `forbidden` | нет | Тот же формат — комбинации, которых **не должно** быть в собранной зоне. Наличие слоя = ошибка компиляции. |

Все токены — `^[a-z][a-z0-9_]*$` (схема). `required`/`forbidden` требуют ключ `pose`; `outfits`/`emotions` внутри них опциональны.

Валидации в `emit_images` (`tools/vn/src/vn/content/images.py`), все выполняются **против собранной зоны** `game/assets/spr/` (скан `sprite_tree`, `pipeline.py:481-499`), а не против `assets_src/`. Поэтому порядок всегда `vn assets build` → `vn build`; `vn build` делает это сам (`cli.py:114-116`).

| Проверка | Где | Уровень | Сообщение (сокращённо) |
|---|---|---|---|
| Дизъюнктность имён между группами | `images.py:380-386` | error | «имя `x` используется в двух группах matrix» |
| `required`: есть `base` у позы | `images.py:389-393` | error | «matrix.required: нет base для позы `p`» |
| `required`: есть слой `outfits/<o>` | `images.py:395-399` | error | «нет слоя outfits/o для позы p» |
| `required`: есть слой `faces/<e>` | `images.py:400-404` | error | «нет слоя faces/e для позы p» |
| `forbidden`: слой отсутствует | `images.py:407-421` | error | «собран, но комбинация запрещена — удалите арт или декларацию» |
| Собранная поза вне `matrix.poses` | `images.py:424-426` | warning | «поза `p` есть в assets, но не в matrix» |
| Собранный `outfits/*`/`faces/*` вне matrix | `images.py:428-433` | warning | «outfits/o (p) вне matrix» |
| Собраны `overlays/*` | `images.py:434-436` | warning | «эмиссия overlay-группы появится позже — сейчас мёртвый груз» |
| Поза из matrix без собранного `base` | `images.py:440-444` | error | «у позы `p` нет base@2.webp — поза не собрана» |
| Ни одна поза не собрана | `images.py:446-448` | error | «ни одна поза из matrix не собрана в assets» |
| Первый объявленный `outfit`/`emotion` не собран | `images.py:482-487` | warning | «default достался следующему собранному имени» |

Любая error здесь = `CompileError` и exit 1 у `vn build` (`compile.py:835-838`).

**Ключевая асимметрия, о которой легко забыть:** `matrix` объявляет вселенную имён, `required` — минимум, который обязан быть, `forbidden` — то, чего быть не должно. Слои, которые есть в `matrix`, но не в `required` и физически не собраны, — не ошибка: они просто не попадут в `layeredimage`. Это законный способ вести персонажа поэтапно.

---

## 4. Каталоги: сырец → игровой ассет

Конвенция источников зашита в `_discover` (`tools/vn/src/vn/assets/pipeline.py:110-135`) и продублирована в докстринге `pipeline.py:8-22`.

```
assets_src/png/characters/<id>/<pose>/base.png              -> game/assets/spr/<id>/<pose>/base@2.webp
assets_src/png/characters/<id>/<pose>/outfits/<outfit>.png  -> game/assets/spr/<id>/<pose>/outfits/<outfit>@2.webp
assets_src/png/characters/<id>/<pose>/faces/<emotion>.png   -> game/assets/spr/<id>/<pose>/faces/<emotion>@2.webp
assets_src/png/characters/<id>/<pose>/overlays/<name>.png   -> game/assets/spr/<id>/<pose>/overlays/<name>@2.webp   (собирается, НЕ эмитится)
```

Реально на диске сегодня:

```
assets_src/png/characters/mira/a/base.png
assets_src/png/characters/mira/a/outfits/{school,casual}.png
assets_src/png/characters/mira/a/faces/{neutral,smile,angry}.png
game/assets/spr/mira/a/base@2.webp
game/assets/spr/mira/a/outfits/{school,casual}@2.webp
game/assets/spr/mira/a/faces/{neutral,smile,angry}@2.webp
```

Жёсткие правила:

- **`base.png` обязателен для каждой позы.** Нет — `vn assets build` даёт ошибку «нет обязательного base.png» (`pipeline.py:124`).
- Каждый сегмент пути — слуг `^[a-z][a-z0-9_]*$`, иначе ошибка «вне конвенции … (naming.md)» (`pipeline.py:94-99`).
- Два источника на один выход (например ручной PNG и нарезка того же PSD) — ошибка «два источника претендуют на один выход» (`pipeline.py:288`).

### Почему WebP и что значит `@2`

- **WebP** — единственный выходной формат статики: трансформация `img_sprite` (имя после ADR-0012; `png2webp_sprite` в коде больше нет), `quality=95` в профиле `full`, `quality=50` в `draft`, RGBA (`alpha: require`), масштабы по `render.classes.spr.variants` (`render_config.py:81-92`, применение — `pipeline.py:625-630`, ядро энкода — `assets/imaging.py:104-136`). Профиль `draft` (`vn build --profile draft`, `vn assets build --profile draft`) существует ради скорости локальной итерации, в релиз идёт только `full`.
- **`@2`** — суффикс oversampling Ren'Py: движок читает его из **имени файла** и считает изображение вдвое плотнее виртуального разрешения. В нашем конвейере это **чистая конвенция имени**: масштабирующего кода нет, PNG кодируется 1:1 (`pipeline.py:221` не передаёт `max_side`). То есть художник обязан отдавать сырец в 2× от расчётного экранного размера — иначе персонаж будет вдвое мельче задуманного.
- `@2` есть **только у спрайтов**. Выходы `bg/`, `cg/`, `ui/` идут без суффикса.

Трансформация версионирована: `TRANSFORMS["img_sprite"] = "2"` (`pipeline.py:54-65`). Бамп версии инвалидирует только спрайтовую ветку кэша `.vncache/assets/`. Подробности кэша, GC и orphan-удаления — [16-assets.md](16-assets.md).

### PSD-путь (IMPLEMENTED / UNEXERCISED)

`assets_src/psd/characters/<id>/<id>_<pose>.psd` (`PSD_NAME_RE`, `psd.py:25`) режется в `.vncache/psd_png/characters/<id>/<pose>/` по конвенции слоёв: пиксельный слой `base`, группы `outfits`, `faces`, `overlays`. Экспортируются **все** слои конвенционных групп независимо от флага видимости (`psd.py:29-34`). Далее — те же трансформации. В `assets_src/` нарезка никогда не пишется. Сегодня `.psd` в репозитории нет, тестов на `psd.py` нет — путь не обкатан.

---

## 5. Кодоген: что именно получается

Два выхода, разные `init offset` — это не случайность.

### `game/generated/registry/characters.gen.rpy` (`init offset = 500`)

```renpy
init offset = 500

define mira = Character(_('Мира'), color='#c94f7c', image='mira', voice_tag='mira')

# layeredimage появятся вместе с ассет-пайплайном (раздел 2/4, G11).
```

Эмиттер — `emit_characters` (`tools/vn/src/vn/content/scenes.py:310-322`). Последняя строка — **устаревший комментарий**: layeredimage уже эмитятся, но в другом файле. Не верьте ему.

### `game/generated/registry/images.gen.rpy` (`init offset = 0`)

`init offset = 0` выбран сознательно: стейтменты `image`/`layeredimage` имеют **собственный** базовый приоритет 500, оффсет 500 дал бы суммарные 1000 — вне допустимого диапазона движка (ADR-0003, комментарий `images.py:52-55`).

Реальный фрагмент (`game/generated/registry/images.gen.rpy:17-33`):

```renpy
layeredimage mira:
    group pose:
        attribute a default Null()

    always "assets/spr/mira/a/base@2.webp" if_any ["a"]

    group outfit:
        attribute school default "assets/spr/mira/a/outfits/school@2.webp" if_any ["a"]
        attribute casual "assets/spr/mira/a/outfits/casual@2.webp" if_any ["a"]

    group face:
        attribute neutral default "assets/spr/mira/a/faces/neutral@2.webp" if_any ["a"]
        attribute smile "assets/spr/mira/a/faces/smile@2.webp" if_any ["a"]
        attribute angry "assets/spr/mira/a/faces/angry@2.webp" if_any ["a"]

# Тонировка: matrixcolor-профиль локации применяется camera sprites (раздел 4)
define config.tag_layer = {"mira": "sprites"}
```

Правила эмиттера (канон G11, `images.py:357-510`) — их нужно знать, чтобы понимать ошибки:

1. **Группа `pose` — селекторная.** Каждый атрибут — `Null()`, то есть ничего не рисует; поза только «включает» слои через `if_any`. Литерала `null` в layeredimage не существует, `Null()` — выражение-displayable.
2. **`base` — не атрибут, а `always`-слой** с гейтом `if_any ["<pose>"]`. По одному `always` на позу.
3. **Группы `outfit` и `face` строятся перебором `имя × поза`**: если два наряда с именем `school` есть у поз `a` и `b`, эмитятся две строки `attribute school … if_any ["a"]` и `attribute school … if_any ["b"]`. Имена атрибутов повторяются — это штатная идиома Ren'Py, гейтинг разводит их по позам.
4. **`default` достаётся первому реально собранному имени**, а не первому объявленному (`images.py:471-487`); расхождение = warning.
5. **Пустая группа не эмитится** — строки откатываются (`images.py:488-495`).
6. **Каждый attribute — с явным displayable.** Без него layeredimage искал бы файл по авто-паттерну.
7. **`config.tag_layer`** привязывает тег персонажа к слою `sprites` — иначе `camera sprites` с matrixcolor-профилем локации не тонировала бы персонажа. Слой `sprites` создаётся в `game/framework/00_core/001_boot.rpy:22` (`renpy.add_layer("sprites", above="master")`).

В тот же файл попадают фоны локаций ([11-locations.md](11-locations.md)), CG-стиллы и видео-лупы — заголовок `# source:` при этом перечисляет **только** `character.yaml`, хотя реальных источников больше (`compile.py:833`). Известное расхождение, не баг компиляции.

---

## 6. Как показывать персонажа в сцене

Реальный код `content/chapters/ch01_awakening/scenes/s020_school_gate.scene.rpy`:

```renpy
label ch01_s020__body:
    show mira a school neutral at center with dissolve
    mira "Ты опять проспал?" id ch01_s020_0001
    ...
            show mira angry
```

Разбор `show mira a school neutral at center with dissolve`:

| Токен | Что это | Откуда |
|---|---|---|
| `mira` | тег образа = `id` персонажа | `layeredimage mira` |
| `a` | атрибут группы `pose` | `matrix.poses` |
| `school` | атрибут группы `outfit` | `matrix.outfits` |
| `neutral` | атрибут группы `face` | `matrix.emotions` |
| `at center` | встроенный transform Ren'Py | движок |
| `with dissolve` | встроенный transition | движок |

**Почему `show mira smile` работает.** Ren'Py при повторном `show` уже показанного тега применяет только переданные атрибуты, остальные группы сохраняют текущее значение. Меняете эмоцию — пишете один атрибут. Полный набор нужен только при первом показе в сцене (и то не обязательно: незаданные группы возьмут свой `default`).

**Каждая сцена начинается с чистого слоя `sprites`.** Сгенерированная обвязка выполняет `$ renpy.scene("sprites")` перед фоном (`game/generated/scenes/ch01/ch01_s020.gen.rpy`), поэтому персонажа надо показывать заново в каждой сцене — состояние показа между сценами не переносится. Механика обвязки — [12-scenes.md](12-scenes.md).

**`participants` в `scene.yaml`.** Поле проверяется односторонне: каждый указанный id обязан существовать в `content/characters/`, иначе ошибка компиляции «участник … не объявлен … (say упадёт NameError в рантайме)» (`compile.py:755-760`). Обратной проверки нет: сцена может показывать персонажа, не указанного в `participants`, — компилятор промолчит. Заполняйте честно, это единственная машиночитаемая связка «сцена ↔ персонаж».

---

## 7. Честные ограничения

| Механизм | Статус | Детали |
|---|---|---|
| `vn char new` | NOT IMPLEMENTED (фаза 1) | `_stub_group("char", …, {"new": 1, …})` — `cli.py:958`; печатает «эта команда появится в фазе 1» и выходит с кодом 3 (`cli.py:34-38`) |
| `vn char validate` | NOT IMPLEMENTED (фаза 1) | там же. Валидация фактически живёт в `vn content lint` + `vn build` |
| `vn char sheet` (лист персонажа) | NOT IMPLEMENTED (фаза 2) | там же |
| Группа `overlays` | PARTIAL | сканируется (`pipeline.py:493`), собирается в `game/assets/spr/<id>/<pose>/overlays/*@2.webp`, но `emit_images` её **не эмитит** — только warning (`images.py:178-182`). Собранные overlay-слои = мёртвый вес в дистрибутиве |
| `side/<emotion>@2.webp` (side images для say-окна) | NOT IMPLEMENTED | нормативно в `docs/conventions/naming.md:18` и `docs/ARCHITECTURE.md:144,454,922`; в `tools/vn/src/vn/` — ноль совпадений `side/` |
| `canvas` | IMPLEMENTED (ADR-0012) | контракт холста мастеров |
| `animated` (Live2D/Spine, G12) | NOT IMPLEMENTED | схема есть, потребителей нет; `assets_src/{live2d,spine_export}/characters/` содержат только `.gitkeep` |
| Персонажи в паках | NOT IMPLEMENTED | компилятор берёт **только** `content/characters/*/character.yaml` (`compile.py:878`); `packs/<id>/characters/` сканирует лишь G7-проверка линтера (`lint.py:366-373`). Персонаж, объявленный в паке, не попадёт ни в `characters.gen.rpy`, ни в `images.gen.rpy` |
| Переименование персонажа | NOT IMPLEMENTED (by design) | `renames@1` имеет секции `scenes`, `deleted_scenes`, `labels`, `vars` — секции `characters` **нет**. Комментарий линтера прямо говорит: «главы и персонажи механизма переименования не имеют» (`lint.py:320-321`) |
| `vn voice tts` (TTS-черновики; остальной `vn voice` и озвучка по say-id — работают, [23-audio.md](23-audio.md) §8) | NOT IMPLEMENTED (фаза 2) | `cli.py:1278-1281` |
| Автоматизация рендера DAZ/VaM/Sims4 | NOT IMPLEMENTED | есть только валидаторы деклараций и запись провенанса; headless-вызова нет |

---

## 8. Полный конвейер персонажа: от идеи до билда

Шаги 1–8 (внешние инструменты) подробно расписаны в отдельных файлах — здесь только точки стыковки с репозиторием.

| # | Шаг | Каталог / артефакт | Команда | Статус | Подробно |
|---|---|---|---|---|---|
| 1 | Concept | вне репозитория (мудборд, описание) | — | процесс, не код | [01-project-overview.md](01-project-overview.md) |
| 2 | Reference-лист | `assets_src/daz/**` (сцена) или сторонний источник | — | — | [17-daz-studio.md](17-daz-studio.md) |
| 3 | Подготовка модели (DAZ / VaM / Sims 4) | `assets_src/daz/**/*.duf`, `assets_src/vam/**`, `assets_src/sims4/**` | `vn assets daz validate`, `vn assets vam validate`, `vn assets sims4 validate` | IMPLEMENTED (валидаторы деклараций); **ноль деклараций в репозитории сегодня** | [17-daz-studio.md](17-daz-studio.md), [18-vam.md](18-vam.md), [19-sims4.md](19-sims4.md) |
| 4 | Материалы, поза, эмоция | там же; декларация `<name>.render.yaml` (`daz_render@1`: `id ^(bg\|cg\|spr\|mov)/…`, `source ^daz/.+\.duf$`, `output ^(png\|video_src)/.+`, `render.{resolution,renderer,camera}`) | `vn assets daz validate --scope <подпуть>` | IMPLEMENTED / UNEXERCISED | [22-rendering.md](22-rendering.md) |
| 5 | Рендер | выход по `output:` — для персонажа это `png/characters/<id>/<pose>/…` относительно `assets_src/` | вручную в DAZ/VaM; headless-автоматизации нет | NOT IMPLEMENTED (автоматизация) | [22-rendering.md](22-rendering.md) |
| 6 | AI-обработка / консистентность лица | ComfyUI, PNG с tEXt-метаданными | `vn assets provenance record <файл> [--source …]` | IMPLEMENTED / UNEXERCISED (ноль `*.provenance.json` в репозитории) | [20-image-generation.md](20-image-generation.md) |
| 7 | Постобработка, нарезка слоёв | `assets_src/psd/characters/<id>/<id>_<pose>.psd` **или** сразу PNG | `vn assets build` (PSD режется автоматически) | IMPLEMENTED / UNEXERCISED (PSD) | [24-post-processing.md](24-post-processing.md) |
| 8 | Импорт слоёв | `assets_src/art/characters/<id>/<pose>/{base,outfits/*,faces/*}.png` | `git add` (ADR-0012: мастера живут в git **через LFS**; ошибка линта на бинарь мимо LFS и на 50 МБ таких файлов суммарно) | IMPLEMENTED | [16-assets.md](16-assets.md), [31-storage-and-backup.md](31-storage-and-backup.md) |
| 9 | Декларация | `content/characters/<id>/character.yaml` | `vn content lint` | IMPLEMENTED (руками) | этот файл, §2 |
| 10 | Сборка ассетов | → `game/assets/spr/<id>/**@2.webp` | `vn assets build [--profile draft]` | IMPLEMENTED | §4 |
| 11 | Валидация matrix + ссылок | — | `vn assets validate` | IMPLEMENTED | §3 |
| 12 | Кодоген | → `characters.gen.rpy`, `images.gen.rpy` | `vn build` | IMPLEMENTED | §5 |
| 13 | Локализация имени | `loc/po/<lang>/common.po`, `msgctxt "char:<id>"` (`po.py:208`) | `vn loc extract` → перевод → `vn loc import` | IMPLEMENTED | [14-localization.md](14-localization.md) |
| 14 | Сцены | `content/chapters/**/scenes/*.scene.{yaml,rpy}`: `participants: [<id>]` + `show <id> …` | `vn loc keys`, `vn build` | IMPLEMENTED | [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md) |
| 15 | Галерея | `content/gallery/*.yaml`, поле `characters: [<id>]` у CG-записей | `vn build` | IMPLEMENTED (поле доезжает в `VN_GALLERY` как метаданные записи; фильтра по персонажу в UI сегодня нет) | [15-gallery.md](15-gallery.md) |
| 16 | Билд / релиз | `build/dist/<версия>-<flavor>/` | `vn package`, `vn release validate --flavor public`, `vn release build` | IMPLEMENTED | [29-build-and-release.md](29-build-and-release.md) |

---

## 9. Как завести персонажа руками (подробный рецепт)

`vn char new` не существует — делаем по шагам. Пример: `lena`.

**1. Проверить id.** `^[a-z][a-z0-9_]{1,23}$` (`lint.py:18`, `naming.md:16`). Id **неизменяем навсегда** и механизма переименования у персонажей нет (см. §7). Выбирайте на 5 лет вперёд: не `lena_v2`, не `heroine`, не `girl1`.

**2. Каталоги:**

```bash
mkdir -p content/characters/lena
mkdir -p assets_src/png/characters/lena/a/outfits
mkdir -p assets_src/png/characters/lena/a/faces
```

**3. Слои.** Положить `assets_src/png/characters/lena/a/base.png` (обязателен!), затем `outfits/<наряд>.png` и `faces/<эмоция>.png`. Имена файлов — слуги. Сырец — в 2× от целевого экранного размера (см. §4 про `@2`).

**4. `content/characters/lena/character.yaml`** — шаблон, копируйте и правьте:

```yaml
schema: character@1
id: lena
name: "Лена"
color: "#4f8fc9"
voice_tag: lena
canvas: [1200, 2200]
matrix:
  poses: [a]
  outfits: [school]
  emotions: [neutral, smile]
  required:
    - {pose: a, outfits: [school], emotions: [neutral, smile]}
```

`id` обязан совпасть с именем папки. `color` — цвет имени в say-окне, берите различимый на фоне панели диалога ([06-frontend.md](06-frontend.md)).

**5. Сборка и проверки:**

```bash
vn content lint          # id == папка, конвенции, бюджет assets_src
vn assets build          # PNG -> WebP@2
vn assets validate       # matrix против собранной зоны, без записи
vn build                 # полный проход: lint -> assets -> компиляция
```

**6. Убедиться в кодогене:**

```bash
grep -n "define lena" game/generated/registry/characters.gen.rpy
grep -n "layeredimage lena" -A 12 game/generated/registry/images.gen.rpy
```

**7. Локализация имени:**

```bash
vn loc extract           # msgctxt "char:lena" появится в loc/po/<lang>/common.po
# переводчик заполняет msgstr
vn loc import            # -> game/tl/<lang>/common.rpy, блок translate <lang> strings
vn loc report            # покрытие по языкам
```

**8. Первый показ в сцене** — добавить `lena` в `participants:` нужной `*.scene.yaml` и `show lena a school neutral at center with dissolve` в парный `*.scene.rpy`. Затем `vn build && vn play`.

---

## 10. Масштабирование на десятки персонажей

Целевой масштаб из `docs/ARCHITECTURE.md:7` — 150+ персонажей. Что работает и что нет уже сегодня.

**Работает по построению:**

- «Папка = персонаж» в трёх зонах сразу (`content/characters/<id>/`, `assets_src/png/characters/<id>/`, `game/assets/spr/<id>/`). Конфликтов между персонажами не бывает — все ключи уникальны по имени папки.
- Скан персонажей — `sorted(glob("*/character.yaml"))` (`compile.py:878`): добавление персонажа не трогает чужие файлы, значит не создаёт merge-конфликтов и не инвалидирует чужой кэш ассетов (ключ кэша — `blake3(сырец) + трансформация + версия + профиль`).
- Кодоген детерминирован и идемпотентен: неизменившиеся выходы не переписываются, `.rpyc` не пересобираются массово.

**Арифметика.** Слоёв на персонажа: `poses × (1 + outfits + emotions)`. Игровых комбинаций: `poses × outfits × emotions` — но **новых файлов они не требуют**, комбинации собирает движок. Взрывается не количество комбинаций, а количество поз: каждая новая поза — это полный повторный набор всех нарядов и всех лиц, потому что `outfits/` и `faces/` физически лежат **внутри** позы.

| Профиль персонажа | poses | outfits | emotions | Файлов |
|---|---|---|---|---|
| `mira` сегодня | 1 | 2 | 3 | 6 |
| Второстепенный | 1 | 2 | 4 | 7 |
| Основной | 3 | 4 | 8 | 39 |
| «Всё для всех» | 5 | 8 | 12 | 105 |

Сдерживать так:

1. **Позы — самый дорогой ресурс.** Не заводите позу ради лёгкого разворота корпуса. Реалистично: 1 поза у эпизодических, 2–3 у основных.
2. **`required` — только на то, что реально нужно сценарию.** Всё остальное объявляйте в `matrix.poses/outfits/emotions` и досыпайте арт по мере надобности: недостающий слой не ошибка, если он не в `required`.
3. **`forbidden` — для комбинаций, которые сценарно невозможны** (школьная форма на пляже). Это защита от того, что художник сдал арт «на всякий случай», а он молча уехал в билд.
4. **Бюджеты.** `assets_src/` — error на любой нетекстовый файл мимо LFS и на 50 МБ таких файлов суммарно (`lint.py:422-452`, ADR-0004 в редакции ADR-0012; warn-порога нет). `game/assets` целиком — `assets_total_mb: 20000` (`project.yaml:61`). При десятках персонажей PNG в git перестанет помещаться: миграция на внешнее хранилище — `vn assets push/pull/lock` c `.vnstorage.yaml` (`type: file` работает, `type: s3` — честный `StorageError`, [31-storage-and-backup.md](31-storage-and-backup.md)).

**Чего матрица сегодня НЕ умеет** (не выдумывайте обходные пути — их нет):

| Хотелось бы | Реальность | Что делать сейчас |
|---|---|---|
| Группа `hair` (причёски) | Групп ровно три: `pose`/`outfit`/`face`. Имена групп зашиты в `images.py:455,464` | Кодировать причёску в токен наряда (`school_ponytail`, `school_loose`) — умножает число файлов нарядов, зато честно валидируется |
| Аксессуары поверх наряда | Группа `overlays` собирается, но не эмитится (§7) | То же: токен наряда. Не складывать в `overlays/` — получите мёртвый вес и warning |
| Варианты тела / возраст / «до и после» | Отдельного измерения нет | Отдельная **поза** (полный набор слоёв) или отдельный персонаж с новым id (см. §11) |
| Side-image в say-окне | `side/` NOT IMPLEMENTED | Ничего; не создавайте каталог `side/` — `_discover` его не знает, файлы просто не соберутся |
| Персонаж, приходящий с DLC | Компилятор не видит `packs/*/characters/` | Объявлять персонажа в `content/characters/`, а гейтить контентом главы пака |
| Автоматический лист персонажа (контактный лист поз/эмоций) | `vn char sheet` — заглушка фазы 2 | Смотреть глазами в `vn play` или собрать контактный лист вручную |

Подробнее про бюджеты и рост — [32-performance-and-scalability.md](32-performance-and-scalability.md).

---

## 11. Версии персонажа: как ввести «v2 внешности»

**Базовый факт:** `id` персонажа неизменяем, и — в отличие от сцен, меток и переменных — **механизма переименования для персонажей не существует**. `content/renames.yaml` (`schema: renames@1`) имеет только секции `scenes`, `deleted_scenes`, `labels`, `vars`; ключа `characters` в схеме нет (`tools/schemas/renames@1.schema.json`). Линтер это фиксирует прямым текстом (`lint.py:320-321`) и стережёт исчезновение выпущенного персонажа: `content/registry/id_registry.json:characters` → ошибка «выпущенный персонаж … исчез (id неизменяемы, G7)» (`lint.py:359-363`). Сегодня массив пуст, потому что `ch01` в статусе `draft` и `stamp_id_registry` ещё ничего не записал — но после первого релиза защита включится.

Три рабочих сценария:

**A. Перерисовали того же персонажа (ретекстур, апскейл, новый рендер).** Ничего не меняется в декларации. Заменяете PNG в `assets_src/png/characters/<id>/<pose>/`, `vn build`. Кэш инвалидируется по хэшу сырца, `layeredimage` тот же. Сейвы не ломаются.

**B. Новый облик как новое состояние (взросление, смена гардероба на всю вторую половину игры).** Заводите **новую позу**:

```yaml
matrix:
  poses: [a, b]              # a — старый облик, b — новый
  outfits: [school, casual, uniform]
  emotions: [neutral, smile, angry]
  required:
    - {pose: a, outfits: [school, casual], emotions: [neutral, smile, angry]}
    - {pose: b, outfits: [uniform],        emotions: [neutral, smile]}
```

Слои `b` кладутся в `assets_src/png/characters/<id>/b/**`. Старые сцены продолжают писать `show mira a …` и работают как прежде; новые — `show mira b …`. Токены поз — тоже id: `a` нельзя переименовать в `young`, не сломав старые сцены.

**C. Формально другой персонаж (клон, двойник, «она же в другом сеттинге»).** Новый id, новая папка, новый `Character(...)`. Старого **не удалять** — после релиза это ошибка G7 без пути отхода. Если персонаж больше не появляется, просто перестаньте на него ссылаться: неиспользуемый `Character` стоит околонуля, а его слои можно вычистить из `matrix.required`, оставив декларацию.

Чего делать **нельзя**: переименовывать папку `content/characters/<id>/`, менять `id:` внутри YAML после релиза, переиспользовать освободившийся id для другого персонажа.

---

## NEW CHARACTER CHECKLIST

```
[ ] id выбран: ^[a-z][a-z0-9_]{1,23}$, навсегда, без версий и порядковых номеров
[ ] content/characters/<id>/ создан, имя папки == id
[ ] assets_src/png/characters/<id>/<pose>/base.png существует для КАЖДОЙ позы
[ ] слои разложены: outfits/<o>.png, faces/<e>.png; все имена — слуги
[ ] сырцы в 2× от экранного размера (суффикс @2 не масштабирует)
[ ] character.yaml: schema/id/name/color заполнены; color различим на панели диалога
[ ] matrix: poses/outfits/emotions перечислены; имена НЕ пересекаются между группами
[ ] matrix.required перечисляет то, что реально собрано (иначе ошибка компиляции)
[ ] matrix.forbidden закрывает сценарно невозможные комбинации (если такие есть)
[ ] overlays/ НЕ используется (собирается, но не эмитится — мёртвый вес)
[ ] side/ НЕ создаётся (ветка не реализована)
[ ] vn content lint            -> 0 errors
[ ] vn assets build            -> слои в game/assets/spr/<id>/
[ ] vn assets validate         -> 0 errors
[ ] vn build                   -> build: OK
[ ] grep "define <id> = Character" game/generated/registry/characters.gen.rpy  -> есть
[ ] grep "layeredimage <id>" game/generated/registry/images.gen.rpy            -> есть
[ ] vn loc extract             -> msgctxt "char:<id>" в loc/po/*/common.po
[ ] перевод имени заполнен -> vn loc import -> vn loc report (100%)
[ ] participants: [<id>] проставлен в scene.yaml сцен, где он появляется
[ ] vn play: show <id> <pose> <outfit> <emotion> рисуется, смена эмоции работает
[ ] бюджеты не пробиты: vn build не ругается на assets_total_mb / assets_src
```

---

## Как изменить / Как расширить

**Добавить эмоцию персонажу:**
1. `assets_src/png/characters/<id>/<pose>/faces/<новая>.png`;
2. дописать токен в `matrix.emotions` (и, если нужно гарантировать наличие, в `required`);
3. `vn build`;
4. использовать `show <id> <новая>` в сценах.
Пропустите шаг 2 — получите warning «faces/x (pose) вне matrix» и слой в `layeredimage` **не попадёт**.

**Добавить наряд:** то же самое через `outfits/` и `matrix.outfits`.

**Добавить позу:** новый каталог `<pose>/` с обязательным `base.png` + свои `outfits/`/`faces/`, токен в `matrix.poses`, запись в `required`. Помните: поза — самый дорогой юнит (§10).

**Сменить цвет имени:** `color:` в `character.yaml` → `vn build`. Затрагивает только `characters.gen.rpy`.

**Убрать персонажа из сборки:** удалите ссылки на него из сцен и `participants`, декларацию оставьте (G7). Слои можно вынести из `assets_src/` — orphan-очистка `game/assets` пройдёт по диффу манифеста (`.vncache/assets-manifest.json`; потеряете манифест — удаление перестанет работать, см. [16-assets.md](16-assets.md)).

**Ускорить итерацию:** `vn assets build --profile draft` (quality 50) или `vn dev` — вотчер `assets_src/` + `content/`. Осторожно: `vn assets watch` события `content/` молча выбрасывает (`cli.py:566` — `watch(root, on_assets, lambda: None)`).

---

## Чего НЕ делать

- **Не редактировать `game/generated/registry/{characters,images}.gen.rpy`** и не класть PNG в `game/`. Перезапишется ближайшим `vn build` / `vn assets build`.
- **Не переименовывать папку персонажа и не менять `id:`** после релиза. Механизма отката нет: `renames@1` персонажей не поддерживает, G7-проверка даст красный CI.
- **Не создавать `assets_src/png/characters/<id>/<pose>/side/`** — ветка не реализована, файлы просто не соберутся, а норма в `naming.md:18` описывает будущее.
- **Не складывать аксессуары в `overlays/`** — соберутся в WebP, поедут в дистрибутив и не будут видны в игре.
- **Не использовать один токен в двух группах matrix** (`school` и в `outfits`, и в `emotions`) — ошибка «имя используется в двух группах», layeredimage сломался бы на гейтинге.
- **Не полагаться на `animated`** — его не читает ни одна строка кода. Live2D/Spine сегодня не поддержаны. (`canvas` с ADR-0012 — рабочий контракт.)
- **Не объявлять персонажа в `packs/<id>/characters/`** — компилятор туда не смотрит, `Character` не сгенерится, `say` упадёт `NameError`.
- **Не запускать `vn build` до `vn assets build` вручную по частям**: `matrix.required` проверяется против **собранной** зоны, а не против `assets_src/`. `vn build` делает это в правильном порядке сам.
- **Не рассчитывать на `vn char new/validate/sheet`** — три заглушки, exit 3.
- **Не забывать `RENPY_SDK`** в bash-сессиях агента: компиляция сцен требует SDK (парсер `.rpy` идёт через `renpy.exe <root> vn_analyze`, G24). Экспортить вручную: `export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"` (именно в кавычках и с прямыми слэшами: путь читает Python-код `sdk_path()` / `sdk_renpy_exe()`, а MSYS-форма `/c/...` и обратные слэши дают битое значение и «SDK не найден»).

---

## Проверка

```bash
vn content lint                 # id == папка, конвенции имён, бюджет assets_src
vn assets build                 # сборка слоёв; ошибки конвенции и отсутствующий base.png
vn assets validate              # matrix против собранной зоны + ссылки контента, ничего не пишет
vn build                        # полный проход, включая layeredimage-эмиттер
vn build --check                # CI-режим: свеж ли генерат (ничего не пишет)
vn loc report                   # покрытие переводов, включая имя персонажа
vn test smoke                   # автопилот: сцены реально проходятся, спрайты не падают
python -m pytest tools/vn/tests -q   # 254 теста
vn play                         # глазами
```

Точечно по кодогену:

```bash
grep -n "define mira" game/generated/registry/characters.gen.rpy
grep -n "layeredimage mira" -A 15 game/generated/registry/images.gen.rpy
grep -rn "config.tag_layer" game/generated/registry/images.gen.rpy
```

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `content/characters/mira/character.yaml`, `tools/schemas/character@1.schema.json`, `tools/vn/src/vn/content/images.py` (весь `emit_images`, :48-246), `tools/vn/src/vn/assets/pipeline.py:102-135` (`_discover`) и `:481-499` (`sprite_tree`), `tools/vn/src/vn/content/scenes.py:310-322` (`emit_characters`), `tools/vn/src/vn/content/lint.py:297-310,331-363`, `docs/conventions/naming.md` |
| **Не трогать** | `game/generated/**` (генерат `vn build`), `game/assets/**` (генерат `vn assets build`), `game/tl/**` (генерат `vn loc import`), `.vncache/**` (кэш). Правки перезапишутся |
| **Зависимости** | Изменение `matrix` → `images.gen.rpy` → `show <id> …` в сценах; изменение `id`/имени папки → ломает `participants`, `say`, галерею (`characters:`), `id_registry` (G7); изменение `name`/`color` → `characters.gen.rpy` + PO-ключ `char:<id>` в `loc/po/*/common.po`; изменение состава слоёв → `assets-manifest.json`, orphan-удаление в `game/assets` |
| **Валидация** | `vn content lint && vn assets build && vn assets validate && vn build` (порядок важен: matrix проверяется против собранной зоны). Для CI — `vn build --check` |
| **Частые ошибки** | 1) правка `game/generated/registry/images.gen.rpy` вместо `character.yaml` — молча теряется; 2) `vn build` без предварительной сборки ассетов при новом слое — «нет слоя faces/x для позы p»; 3) один токен в двух группах `matrix` — ошибка дизъюнктности; 4) вера в комментарий `# layeredimage появятся вместе с ассет-пайплайном` в `characters.gen.rpy:11` — он устарел, layeredimage уже эмитятся в `images.gen.rpy`; 5) попытка вызвать `vn char new`/`validate`/`sheet` — заглушки, exit 3; 6) `canvas`/`animated` в `character.yaml` — валидны по схеме, но не имеют потребителей: не строить на них логику |

**Соседние файлы:** [08-content-pipeline.md](08-content-pipeline.md) (сквозной конвейер), [11-locations.md](11-locations.md) (фоны и тонировка), [12-scenes.md](12-scenes.md) (обвязка сцены, `renpy.scene("sprites")`), [14-localization.md](14-localization.md) (PO round-trip), [15-gallery.md](15-gallery.md), [16-assets.md](16-assets.md) (кэш, трансформации, хранилище), [17-daz-studio.md](17-daz-studio.md), [20-image-generation.md](20-image-generation.md), [22-rendering.md](22-rendering.md), [25-custom-engine.md](25-custom-engine.md) (устройство `vn`).
