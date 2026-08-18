# 11. Локации и фоны

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — декларация + фоны + эмиссия `image bg` работают полностью; поле `lighting` (тонировка/`matrixcolor`) объявлено в схеме и в ARCHITECTURE.md §4.6, но **кода нет ни строчки**.
> **Отвечает на вопрос:** «Как завести новое место действия и подставить его фон в сцену?»

Локация в этом проекте — не объект и не сущность рантайма. Это **декларация из трёх строк**, которая связывает логический id места с готовыми webp-файлами фонов и позволяет сцене написать `location: school_gate/day` вместо пути к файлу. Живёт в `content/locations/<id>/location.yaml`, читается только компилятором (`tools/vn/src/vn/content/images.py:21`), превращается в `image bg <loc> <variant> = "..."` внутри `game/generated/registry/images.gen.rpy`. Скаффолдера для локаций нет — папка и YAML создаются руками.

## Быстрый ответ

Добавить локацию `beach` с вариантом `day`:

```bash
mkdir -p content/locations/beach assets_src/png/backgrounds/beach
# положить рендер: assets_src/png/backgrounds/beach/day.png
cat > content/locations/beach/location.yaml <<'YAML'
schema: location@1
id: beach
title_key: meta.locations.beach.title
backgrounds:
  day: assets/bg/beach/day.webp
YAML
vn build          # assets build (img_bg) -> compile (image bg beach day)
```

Дальше в любой сцене: `location: beach/day` в `*.scene.yaml`. Экран, `image`-стейтмент и `scene`-строку писать не нужно — их эмитит компилятор.

## Реальное состояние

В репозитории **две** локации, у каждой ровно один вариант:

| Файл | id | backgrounds |
|---|---|---|
| `content/locations/school_gate/location.yaml` | `school_gate` | `day: assets/bg/school_gate/day.webp` |
| `content/locations/rooftop/location.yaml` | `rooftop` | `day: assets/bg/rooftop/day.webp` |

Полный текст одного из них (5 строк, `content/locations/school_gate/location.yaml`):

```yaml
schema: location@1
id: school_gate
title_key: meta.locations.school_gate.title
backgrounds:
  day: assets/bg/school_gate/day.webp
```

Сырцы: `assets_src/png/backgrounds/{rooftop,school_gate}/day.png`. Собранное: `game/assets/bg/{rooftop,school_gate}/day.webp` (зона не в git).

## Поля `location.yaml`

Схема — `tools/schemas/location@1.schema.json`, `additionalProperties: false` (любое новое поле сначала в схему, потом в YAML).

| Поле | Обяз. | Паттерн / форма (схема) | Кто читает | Статус |
|---|---|---|---|---|
| `schema` | да | `const: "location@1"` | `registry.validate` из `images.py:43` | IMPLEMENTED |
| `id` | да | `^[a-z][a-z0-9_]*$` | `images.py:47-49`; **обязан совпадать с именем папки** | IMPLEMENTED |
| `backgrounds` | да | объект, `minProperties: 1`; ключ `^[a-z][a-z0-9_]*$`, значение `^assets/bg/[a-z0-9_/]+\.webp$` | `images.py:291-304` (эмиссия), `scenes.py:344-370` (проверка варианта) | IMPLEMENTED |
| `title_key` | нет | `^[a-z0-9_.]+$` | **никто** — grep по `tools/vn/src/vn/` и `game/framework/` даёт 0 попаданий на `meta.locations` | IMPLEMENTED / UNUSED |
| `lighting` | нет | объект `вариант → профиль` (`^[a-z][a-z0-9_]*$`) | **никто** (`grep -rn lighting tools/vn/src game/framework` → пусто) | NOT IMPLEMENTED |

Про `title_key` без иллюзий: строка `meta.locations.school_gate.title: "Школьные ворота"` реально лежит в `content/ui/strings.yaml:8-9`, попадает в `VN_STRINGS` (`game/generated/registry/menus.gen.rpy:18`) и уезжает переводчикам через PO. Но **это происходит потому, что она объявлена в `strings.yaml`, а не потому, что на неё ссылается `location.yaml`**. Ни один экран её не рисует. Удалите `title_key` из `location.yaml` — не изменится ничего.

**Чего в схеме нет:** `nsfw`, `pack`, `music`, `ambience`, размеров, точек привязки спрайтов. Локация — это только «id → набор фоновых файлов».

## Как локация попадает в игру: две независимые дороги

### 1. Реестр образов — `image bg <loc> <variant>`

`load_locations` (`tools/vn/src/vn/content/images.py:27-51`) обходит `content/locations/*/`, для каждой папки:

- нет `location.yaml` → ошибка `content/locations/<dir>: нет location.yaml`;
- документ валидируется по `location@1`;
- `id != имени папки` → ошибка `<rel>: id (<id>) != имени папки (<dir>)` (`images.py:47-49`).

Затем `emit_images` (`images.py:281-305`) на каждый вариант проверяет, что файл **физически лежит** в `game/assets`, и эмитит стейтмент:

```renpy
image bg rooftop day = "assets/bg/rooftop/day.webp"
image bg school_gate day = "assets/bg/school_gate/day.webp"
```

(`game/generated/registry/images.gen.rpy:9-10`, блок под `init offset = 0` — `image`/`layeredimage` уже имеют собственный базовый приоритет 500, см. `images.py:286-288`.)

Отсутствующий файл — **жёсткая ошибка компиляции**, а не пропуск:

```
content/locations/beach/location.yaml: day: файла assets/bg/beach/day.webp нет
в game/assets — прогоните vn assets build
```

Поэтому порядок в `vn build` именно такой: lint → **assets build** → compile (`tools/vn/src/vn/cli.py`). Запускать `vn content compile` в одиночку после добавления фона бесполезно — он упадёт, пока `vn assets build` не создаст webp.

### 2. Обвязка сцены — `scene bg <loc> <variant> with dissolve`

Связь `scene.yaml` → генерат целиком в `emit_scene` (`tools/vn/src/vn/content/scenes.py:206-232`):

```yaml
# content/chapters/ch01_awakening/scenes/s020_school_gate.scene.yaml
location: school_gate/day
```

↓

```renpy
# game/generated/scenes/ch01/ch01_s020.gen.rpy:10-11
    $ renpy.scene("sprites")
    scene bg school_gate day with dissolve
```

Значение обязано быть **`<локация>/<вариант>`**. Разбор ошибок:

| Что в `scene.yaml` | Что делает компилятор | Цитата |
|---|---|---|
| `location: school_gate/day`, всё существует | `scene bg school_gate day with dissolve` | `scenes.py:229` |
| `location: rooftop` (без варианта) | ошибка `location 'rooftop' без варианта — нужно <location>/<variant> (например rooftop/day)` | `scenes.py:209-212` |
| `location: beach/day`, локации нет | ошибка `location 'beach' не объявлена в content/locations/` | `scenes.py:218-220` |
| `location: rooftop/night`, варианта нет | ошибка `у локации 'rooftop' нет варианта 'night' (есть: ['day'])` | `scenes.py:360-365` |
| поля `location` нет вообще | `scene vn_black with dissolve` — **молча, без предупреждения** | `scenes.py:230-232` |

`vn_black` — это `image vn_black = Solid("#000000")` из `game/framework/20_ui/images.rpy:5`. Сцены `ch01_s010` и `ch90_s010` сегодня идут именно так: они не объявляют `location`, и игрок видит чёрный экран (`game/generated/scenes/ch01/ch01_s010.gen.rpy:11`).

**Расхождение схемы и кода:** `scene@1.location` имеет паттерн `^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)?$` — вариант **опционален** по схеме. Компилятор его требует. То есть `location: rooftop` проходит `vn content lint` зелёным и падает на `vn build`. Это известное нарушение инварианта линтера «зелёный lint ⇒ build не упадёт».

## Pipeline фона: PNG → WebP

Одна трансформация, `img_bg`, версия `2` (`tools/vn/src/vn/assets/pipeline.py:54-65`; имя после ADR-0012 — прежнего `png2webp_bg` в коде нет).

```
assets_src/png/backgrounds/<loc>/<variant>.png
        │  vn assets build   (pipeline.py:137-144 — discovery)
        ▼
game/assets/bg/<loc>/<variant>.webp
        │  vn content compile (images.py:291-304)
        ▼
image bg <loc> <variant> = "assets/bg/<loc>/<variant>.webp"
```

Что происходит с картинкой:

| Параметр | full | draft | Цитата |
|---|---|---|---|
| WebP quality | 90 | 50 | `pipeline.py:223` |
| `method` | 4 | 4 | `pipeline.py:82-91` |
| Ресайз | **нет** (`max_side` не передаётся) | нет | `pipeline.py:82-91` |
| Суффикс `@2` | **нет** (только у спрайтов) | нет | `pipeline.py:144` |
| Конверсия | принудительный `im.convert("RGBA")` | то же | `pipeline.py:84` |

Профиль `draft` включается `vn assets build --profile draft`, `vn assets watch` (по умолчанию draft) и `vn dev`. `vn build` всегда `full` по умолчанию.

Имя папки локации и имя файла проходят slug-гейт `^[a-z][a-z0-9_]*$` (`pipeline.py:48`, применяется в `pipeline.py:142`). `Beach.png`, `beach-day.png`, `day 2.png` — ошибка сборки ассетов, не сцены.

Кэш: ключ `blake3("<src_hash>:img_bg:2:<profile>")`, блоб в `.vncache/assets/<2hex>/<64hex>`, запись в `.vncache/assets-manifest.json` (`pipeline.py:723-727`, `:794`). Подробности кэша, GC и удаления сирот — [16-assets.md](16-assets.md).

## Варианты времени суток

Вариант — это **произвольный ключ в `backgrounds`**, а не enum. Никакого списка `day|evening|night` в коде нет: паттерн ключа — `^[a-z][a-z0-9_]*$`, и всё. Имя ключа обязано совпасть с именем PNG-файла, потому что путь выхода строится как `bg/<папка>/<имя файла>.webp` (`pipeline.py:144`), а `location.yaml` просто указывает на этот путь.

Завести вариант `sunset` для `rooftop`:

```bash
# 1) сырец — имя файла = имя варианта
cp <рендер>.png assets_src/png/backgrounds/rooftop/sunset.png
# 2) декларация
#    backgrounds:
#      day:    assets/bg/rooftop/day.webp
#      sunset: assets/bg/rooftop/sunset.webp
# 3)
vn build
# 4) в сцене: location: rooftop/sunset
```

Смена времени суток **внутри** сцены — не поддерживается декларативно: обвязка эмитит ровно один `scene bg` на сцену (`scenes.py:229`). Варианты: либо разбить на две сцены, либо в авторском `.scene.rpy` написать `scene bg rooftop sunset with dissolve` руками (это легальный контентный код — образ существует в реестре). Второй путь не отражается в `location:` метаданных, поэтому пометьте его комментарием.

## Тонировка / `matrixcolor` — NOT IMPLEMENTED

`docs/ARCHITECTURE.md` §4.6 (строки 2259-2300) описывает целевую систему: библиотека профилей `content/library/lighting.yaml` со схемой `lighting@1`, генерируемый `game/generated/lighting.gen.rpy` с `transform vn_light_<profile>: matrixcolor TintMatrix(...) * SaturationMatrix(...)`, и один оператор `camera sprites` на сцену, который тонирует всех персонажей и не трогает фон.

Что из этого есть в репозитории на 0.1.4:

| Элемент | Статус | Проверка |
|---|---|---|
| `config.tag_layer` (теги персонажей → слой `sprites`) | **IMPLEMENTED** | `images.py:528-532`; живой вывод `game/generated/registry/images.gen.rpy:44`: `define config.tag_layer = {"mira": "sprites"}` |
| Поле `lighting` в `location@1` | **NOT IMPLEMENTED** | схема есть, читателей ноль |
| `content/library/lighting.yaml` | **NOT IMPLEMENTED** | каталога `content/library/` не существует |
| Схема `lighting@1` | **NOT IMPLEMENTED** | нет среди 34 файлов `tools/schemas/*.schema.json` |
| `game/generated/lighting.gen.rpy` | **NOT IMPLEMENTED** | не эмитится ничем |
| `camera sprites` + `matrixcolor` в обвязке | **NOT IMPLEMENTED** | `emit_scene` не эмитит `camera` (см. полный список строк в [12-scenes.md](12-scenes.md)) |
| Baked `lit/<profile>` слои в PSD, `lighting.baked` в `character.yaml` | **NOT IMPLEMENTED** | `character@1` не имеет поля `lighting` |

Практический вывод: **свет сегодня врисован в фон художником**. Если нужны «те же ворота ночью» — это отдельный PNG и отдельный вариант в `backgrounds`, а не профиль. Крючок `config.tag_layer` уже стоит, поэтому когда §4.6 будут реализовывать, спрайты уже на своём слое и ломать show-стейтменты не придётся.

## Как добавить локацию — пошагово

1. **Каталог декларации.** `content/locations/<id>/` — имя папки станет `id`. Паттерн `^[a-z][a-z0-9_]*$`.
2. **Каталог сырцов.** `assets_src/png/backgrounds/<id>/`. Имя папки — тот же slug (совпадение обязательно только по факту: путь webp вы прописываете руками, но расхождение = гарантированная путаница).
3. **Фон.** Положите `<variant>.png`. Один PNG = один вариант. Помните про бюджет ADR-0004 в редакции ADR-0012: `vn content lint` краснеет на любом бинаре в `assets_src/` мимо Git LFS и на 50 МБ таких файлов суммарно (`tools/vn/src/vn/content/lint.py:47,422-452`); warn-порога на 30 МБ нет.
4. **`location.yaml`** — четыре обязательные строки (`schema`, `id`, `backgrounds` с ≥1 вариантом). `title_key` можно опустить: его никто не читает.
5. **Строка локализации** — только если добавили `title_key`: заведите ключ в `content/ui/strings.yaml`, иначе он останется висеть в PO без источника. Компилятор на это не ругается (проверка `title_key ∈ strings.yaml` есть только для глав, `compile.py:769-773`).
6. **Сборка.** `vn build` — сначала соберёт `game/assets/bg/<id>/<variant>.webp`, потом эмитит `image bg`.
7. **Использование.** В `*.scene.yaml`: `location: <id>/<variant>`. Пересоберите: `vn build`.
8. **Проверка глазами.** `vn play` и дойдите до сцены, либо `vn test smoke`.

Локация **не** требует: записи в `chapter.yaml`, в `content/registry/id_registry.json` (там только главы/сцены/персонажи/переменные), в CODEOWNERS, в `content/flags.yaml`.

## Как изменить / Как расширить

| Задача | Что делать |
|---|---|
| Добавить вариант | PNG в `assets_src/png/backgrounds/<id>/`, строка в `backgrounds`, `vn build` |
| Перерисовать фон | заменить PNG — кэш инвалидируется по `blake3` содержимого, `vn build` пересоберёт только его |
| Переименовать локацию | id **неизменяемы (G7)**, но локаций нет в `id_registry.json`, поэтому линтер-гейт на них не распространяется. Технически: переименовать папку + `id` + пути в `backgrounds` + папку сырцов + все `location:` в сценах. Старый webp удалится как сирота по диффу манифеста (`pipeline.py:417-431`) |
| Удалить локацию | удалить папку декларации, папку сырцов и все ссылки `location:` в сценах — иначе `vn build` упадёт на `location '<id>' не объявлена` |
| Завести NSFW-фон | категории `nsfw/` для `bg` в коде нет: `release.py:441-452` считает исключения по **реально существующим** каталогам, а `game/assets/bg/nsfw/` не существует. NSFW сегодня живёт в `cg/` и `mov/`. См. [30-packs-and-dlc.md](30-packs-and-dlc.md) |
| Реализовать тонировку | это работа уровня фазы: схема `lighting@1` + эмиттер + `camera sprites` в `emit_scene`. См. [37-roadmap.md](37-roadmap.md) |

## Чего НЕ делать

- **Не правьте `game/generated/registry/images.gen.rpy`** — файл перезапишет `vn build`, и он даже не в git.
- **Не кладите фоны прямо в `game/assets/bg/`.** Ручной файл переживёт сборку (удаление сирот идёт по диффу манифеста, а не по скану дерева — `pipeline.py:417-431`), но на другой машине и в CI его не будет, и `image bg` не соберётся.
- **Не создавайте `game/images/`** — путь в `FORBIDDEN_PATHS` линтера (`lint.py:50-53`): автообнаружение образов Ren'Py в проекте выключено намеренно, все `image` эмитятся явно.
- **Не пишите `location: rooftop` без варианта** — схема пропустит, компилятор упадёт.
- **Не рассчитывайте на `lighting:`** — поле пройдёт валидацию схемой и не сделает ничего.
- **Не ждите, что `vn content lint` поймает проблемы локаций.** В линтере **нет ни одного правила про `content/locations/`** — только общая валидация всех `content/**/*.yaml` по схеме. `id != имени папки`, отсутствующий `location.yaml`, отсутствующий webp — всё это ловит только компилятор.
- **Не забывайте `vn assets build` перед `vn content compile`**, если гоняете их по отдельности: `emit_images` проверяет наличие файла на диске.
- **Не пишите заглавные буквы и дефисы** в именах папок/файлов фонов — slug-гейт `pipeline.py:48`.

## Проверка

```bash
vn content lint                 # схема location@1 (структуру локаций линтер не проверяет)
vn assets build                 # img_bg -> game/assets/bg/**
vn assets validate              # сырцы + ссылки контента (фоны локаций, matrix, треки)
vn build                        # полный проход: lint -> assets -> compile
vn build --check                # CI-режим: ничего не пишет, падает на несвежем генерате
grep -n "^image bg" game/generated/registry/images.gen.rpy   # что реально объявлено
python -m pytest tools/vn/tests -q                            # 373 теста
```

Ожидаемо на чистом дереве: `lint: OK (0 предупреждений)`, `build: OK`, `400 passed`.

## Чеклист новой локации

- [ ] `content/locations/<id>/` создан, `<id>` матчит `^[a-z][a-z0-9_]*$`
- [ ] `location.yaml`: `schema: location@1`, `id` == имени папки, `backgrounds` ≥ 1 записи
- [ ] Значение каждого фона матчит `^assets/bg/[a-z0-9_/]+\.webp$` и совпадает с реальным путём выхода `bg/<папка>/<файл>.webp`
- [ ] `assets_src/png/backgrounds/<id>/<variant>.png` на месте, имена — slug'и в нижнем регистре
- [ ] Если добавлен `title_key` — ключ заведён в `content/ui/strings.yaml`
- [ ] `vn build` зелёный; `game/assets/bg/<id>/<variant>.webp` появился
- [ ] `grep "image bg <id>" game/generated/registry/images.gen.rpy` находит строку
- [ ] Сцена ссылается как `location: <id>/<variant>` (обязательно с вариантом)
- [ ] `vn content lint` и `python -m pytest tools/vn/tests -q` зелёные
- [ ] Бюджет `assets_src/` не перевален (ADR-0004/ADR-0012: каждый бинарь покрыт LFS; мимо LFS суммарно < 50 МБ)

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/schemas/location@1.schema.json`, `tools/vn/src/vn/content/images.py:27-51,281-305`, `tools/vn/src/vn/content/scenes.py:344-370`, `tools/vn/src/vn/assets/pipeline.py:137-144,223`, любой `content/locations/*/location.yaml` как эталон |
| **Не трогать** | `game/generated/**` (генерат `vn build`), `game/assets/**` (генерат `vn assets build`), `.vncache/**` (кэш) — все три вне git и перезаписываются |
| **Зависимости** | `location.yaml` → `registry/images.gen.rpy` (`image bg`) и обвязка каждой сцены с этим `location:`. Удаление варианта ломает все сцены, которые на него ссылаются. Удаление webp из `game/assets` = ошибка компиляции, а не предупреждение |
| **Валидация** | `vn build` (полный путь) или `vn assets validate` + `vn build --check`; тесты `python -m pytest tools/vn/tests -q` |
| **Частые ошибки** | 1) `id` в YAML не равен имени папки — ошибка только на compile, lint зелёный. 2) `location: rooftop` без `/day` — схема пропустит, compile упадёт. 3) Забыт `vn assets build` — `emit_images` не найдёт webp. 4) Попытка использовать `lighting:` как рабочий механизм — поле мёртвое, NOT IMPLEMENTED. 5) Правка `images.gen.rpy` вместо `location.yaml` |

Смежное: [12-scenes.md](12-scenes.md) — как `location:` попадает в обвязку; [16-assets.md](16-assets.md) — кэш, профили, удаление сирот; [08-content-pipeline.md](08-content-pipeline.md) — сквозной поток `content/` → `game/generated/`; [20-image-generation.md](20-image-generation.md) и [22-rendering.md](22-rendering.md) — откуда берётся исходный PNG.
