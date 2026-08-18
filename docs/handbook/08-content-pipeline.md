# 08. Контентный конвейер: `content/` → `game/generated/`

> **Статус подсистемы:** IMPLEMENTED — компилятор, линтер, реестр схем и build-bridge работают и покрыты тестами; **но** свежесть генерата определяется побайтовым сравнением выходов, `manifest["inputs"]` пишется и никогда не читается обратно, а инкрементальной пересборки «только изменённых источников» не существует.
> **Отвечает на вопрос:** «Я поправил файл в `content/` — что и в каком порядке пересоберётся, чем это проверить, и почему `vn build --check` красный?»

Конвейер — это `vn build`: линт деклараций → сборка ассетов → компиляция контента в `game/generated/` → импорт переводов в `game/tl/` → проверка размер-бюджетов. Единственная точка входа — CLI `vn` (`tools/vn/src/vn/cli.py`), сам компилятор — `tools/vn/src/vn/content/compile.py:587` `compile_content(root, out_dir=None, check=False)`. Про сам CLI как инструмент — [25-custom-engine.md](25-custom-engine.md); про ассетную ветку — [16-assets.md](16-assets.md).

## Быстрый ответ

```bash
vn build                    # полный цикл: lint → assets → compile → loc import → бюджеты
vn build --check            # CI-режим: ничего не пишет, краснеет если генерат не свеж
vn content lint             # только декларации (быстро, SDK не нужен)
vn content compile          # только компиляция (БЕЗ линта — не используйте как основную команду)
vn content graph            # Mermaid-граф сцен в stdout
```

Правило одной строкой: **правишь `content/` — запускаешь `vn build`.** Правки в `game/generated/`, `game/assets/`, `game/tl/` бессмысленны — они перезаписываются (все три зоны в `.gitignore:2-4`).

---

## 1. Направление потока и зоны

| Зона | Роль | В git |
|---|---|---|
| `content/`, `packs/<id>/` | источник истины: YAML-декларации + авторские `*.scene.rpy` | да |
| `loc/po/`, `loc/ledger/` | обмен с переводчиками; ledger — вход компилятора (реестр меню) | да |
| `assets_src/` | сырцы (PNG/PSD/видео) | частично, порог ADR-0004 |
| `game/assets/` | выход `vn assets build`; **вход** компилятора (реестр образов, галерея) | нет |
| `game/generated/` | выход компилятора, 21 файл + `manifest.json` | нет |
| `game/tl/` | выход `vn loc import` | нет |
| `game/framework/` | рукописный код надстройки — **не генерат** | да |

Важная неочевидность: **зона `game/assets/` — это одновременно выход ассетного конвейера и вход контентного.** `emit_images` (`tools/vn/src/vn/content/images.py:48`) сканирует `game/assets/{cg,mov,spr}`, `_emit_gallery` (`compile.py:197,209-222`) проверяет существование файлов галереи. Отсюда жёсткий порядок «assets → compile» в `vn build` и в `vn dev` (`cli.py:243-252`, комментарий там прямой: «реестр образов зависит от собранных ассетов»).

---

## 2. Полная таблица «вход → выход» (21 выход)

Все 21 путь — относительно `game/generated/`. Столбец «Заголовок» — что реально перечислено в шапке файла после `# source:` (см. §6, там есть расхождения).

| # | Выход | Назначение | Реально читает | Эмиттер |
|---|---|---|---|---|
| 1 | `version.gen.rpy` | `define config.version = "<project.version>+<git sha>"` | `project.yaml:version` + `git rev-parse --short HEAD` (`repo.py:35`) | `compile.py:82` |
| 2 | `state/defaults.gen.rpy` | создание named stores (`init -980 python in <store>`) + `default <store>.<name>` + `vn_save_schema` / `vn_build_save_schema` | `content/variables/*.vars.yaml`, `content/chapters/*/vars.yaml`, `project.yaml:save_schema` | `compile.py:90` |
| 3 | `state/snapshot.gen.rpy` | `SNAPSHOT_VARS` / `SNAPSHOT_STORES` для `vn_state` — единый маппинг store↔dict для миграций (G5) | те же vars-документы, `store: persistent` исключён | `compile.py:332` |
| 4 | `state/migrations.gen.rpy` | исходники миграций сейвов инлайнятся строковыми литералами и грузятся `exec` в `MIGRATIONS` | `content/migrations/NNNN_*.py` + `registry.yaml` | `compile.py:352` |
| 5 | `registry/audio.gen.rpy` | `define audio.<id> = "<file>"` (`loop_start` — штатным префиксом `"<loop N>file"`; `volume` уезжает клаузой play-оператора в обвязке сцены) | `content/audio/*.yaml` (`tracks`; коллизия id между kind — ошибка) | `compile.py:377` |
| 6 | `registry/characters.gen.rpy` | `define <id> = Character(...)` | `content/characters/*/character.yaml` (`id,name,color,voice_tag`) | `scenes.py:310` |
| 7 | `registry/images.gen.rpy` | `image bg …`, `image cg …`, `image mov … = Movie(...)`, `layeredimage <char>`, `layeredimage shot_<chNN>_<sNNN>` (shots@1, ADR-0013), `config.tag_layer` | `content/locations/*/location.yaml`, `character.yaml:matrix`, `chapters/*/shots/*.shots.yaml` + **скан `game/assets/{cg,mov,spr,shots}`** | `images.py:281` |
| 8 | `registry/chapters.gen.rpy` | `VN_CHAPTERS` (id, title_key, entry_label, status, pack) + `VN_PACKS` | все `chapter.yaml` (ядро + паки) + `packs/*/manifest.yaml` | `scenes.py:276` |
| 9 | `registry/scenes.gen.rpy` | `VN_SCENES` — плоский список сцен для QA и валидаторов | id сцен из имён файлов | `scenes.py:299` |
| 10 | `registry/menus.gen.rpy` | `VN_MENUS` (choice-id → подписи), пустые `VN_MENUS_TL`/`VN_STRINGS_TL`, `VN_STRINGS`, `VN_SOURCE_LANG` | `loc/ledger/ch*.json`, `content/ui/strings.yaml`, `loc/loc.yaml:source` | `compile.py:313` |
| 11 | `registry/overrides.gen.rpy` | `config.label_overrides.update({...})` + shim-метки с размоткой стека (G7); плюс shim-метки для выпущенных id, отсутствующих в этой сборке — маршрут на `vn_scene_unavailable` (`missing_content`) вместо ScriptError у игрока | `content/renames.yaml`, `content/registry/id_registry.json` | `compile.py:488` |
| 12 | `registry/ui_frames.gen.rpy` | `define vn_frame_<id> = Frame(..., Borders(...))` для генерируемых панелей (ADR-0009) | `content/ui/panels.yaml` | `tools/vn/src/vn/assets/ui.py:119` |
| 13 | `registry/achievements.gen.rpy` | `VN_ACHIEVEMENTS` — триггеры по стабильным якорям (scene/beat/var) | `content/achievements/*.yaml` | `compile.py:114` |
| 14 | `registry/gallery.gen.rpy` | `VN_GALLERY_CATEGORIES` + `VN_GALLERY` (ADR-0010) | `content/gallery/*.yaml` + проверки файлов в `game/assets/**` + `strings.yaml` (warn) | `compile.py:148` |
| 15 | `screens/chapter_select.gen.rpy` | статический шаблон экрана выбора глав; эмитится **только если есть главы** | ничего (шаблон) | `scenes.py:461` |
| 16 | `render.gen.rpy` | потолок качества текстур сборки (ADR-0012): `define config.automatic_oversampling` + `define vn_build_max_oversampling`; настройку игрока поверх применяет `00_core/095_quality.rpy` | `project.yaml: render.max_oversampling` | `compile.py:105` |
| 17 | `platform.gen.rpy` | платформенный конфиг ([ADR-0014](../adr/0014-platform-services.md)): `define config.steam_appid` (движок читает его на `init -1499`, поэтому обязателен `define`, а не присваивание) + `define VN_STEAM_DLC` — карта `pack_id → Steam DLC App ID` | `project.yaml: platform.steam.appid`, `steam_dlc_appid` из `packs/*/manifest.yaml` | `compile.py:133` |
| 18–21 | `scenes/<chNN>/<full_id>.gen.rpy` | label-обвязка сцены (см. §5) + инжекция `voice vn.voice_path("<say-id>")` перед озвученными репликами (C5). Сейчас 4 файла: `ch01/ch01_s010`, `ch01/ch01_s020`, `ch01/ch01_s030`, `ch90/ch90_s010` | пара `*.scene.{yaml,rpy}` + AST от build-bridge + локации + audio-id + voice-манифесты `chapters/*/voice/*.voice.yaml` | `scenes.py:334` |
| — | `manifest.json` | контракт инкрементальности: `{schema, tool, inputs, outputs}`; в `outputs` себя не включает | все зарегистрированные через `src()` входы + blake3 всех выходов | `compile.py:912-922` |

### 36 входов

Ровно те, что перечислены в `game/generated/manifest.json`. Их регистрирует `src()`, и он же поднимает `CompileError`, если обязательный файл отсутствует:

```
project.yaml
content/renames.yaml, content/ui/{panels,strings}.yaml
content/registry/id_registry.json                       (shim-метки выпущенных id, G7)
content/variables/{core,settings,wardrobe}.vars.yaml
content/audio/{bgm,amb,sfx}.yaml
content/achievements/core.achievements.yaml
content/gallery/core.gallery.yaml
content/characters/mira/character.yaml
content/locations/{rooftop,school_gate}/location.yaml
content/migrations/{registry.yaml,0002_route_prologue.py}
content/chapters/ch01_awakening/{chapter.yaml,vars.yaml}
content/chapters/ch01_awakening/scenes/s0{10,20,30}_*.scene.{yaml,rpy}   (6 файлов)
content/chapters/ch01_awakening/shots/s030.shots.yaml   (послойные шоты, ADR-0013)
content/chapters/ch01_awakening/voice/ru.voice.yaml     (voice-манифест, C5)
loc/loc.yaml, loc/ledger/{ch01,ch90}.json
packs/{ep_beach,nsfw}/manifest.yaml
packs/ep_beach/chapters/ch90_beach/chapter.yaml
packs/ep_beach/chapters/ch90_beach/scenes/s010_shore.scene.{yaml,rpy}
```

**Чего в этом списке нет и почему это важно:**

- `content/flags.yaml`, `content/anchors.yaml` — компилятор их **не открывает вовсе** (строки `flags`/`anchors` в `compile.py` не встречаются). Их держит живыми только линтер (§8, `lint.py:39-41`) и релизный гейт. (`id_registry.json` из этой категории выбыл: компилятор читает его для shim-меток выпущенных сцен, `compile.py:872-879`.)
- `game/assets/**` — сканы `emit_images` и пробы галереи **не проходят через `src()`**, значит их нет в `manifest["inputs"]`. Пересобрали ассеты — генерат меняется, а «входы» в манифесте те же. Это одна из причин, по которой инкрементальность по входам не построена.

---

## 3. Порядок работы `vn build`

Код: `tools/vn/src/vn/cli.py:84-153`.

| Шаг | Строка | Что делает | Что при провале |
|---|---|---|---|
| 1 | `cli.py:93` | `root = _root()` — поиск корня по `project.yaml` + `tools/schemas/` (`repo.py:15-23`) | exit 1, красное `ошибка: не найден корень репозитория` |
| 2 | `cli.py:94` | `lint(root)` — полный линт, `layout=True` | печатает все ошибки, `_fail("lint: N ошибок — сборка остановлена")`, exit 1 |
| 3 | `cli.py:95-96` | печать `rep.warnings` жёлтым (предупреждения никогда не валят сборку) | — |
| 4 | `cli.py:113-114` | `_assets_build(root, profile)` → `tools/vn/src/vn/assets/pipeline.py:251 build_assets` | exit 1 с перечнем ошибок ассетов |
| 5 | `cli.py:116` | `compile_content(root, check=False)` | `CompileError` → exit 1 с текстом; любое другое исключение → `внутренняя ошибка компилятора: <Type>: <msg>` + 3 кадра трейсбека (`cli.py:119-123`) |
| 6 | `cli.py:145-148` | сводка `generated: N записано, N без изменений, N осиротевших удалено` | — |
| 7 | `cli.py:151` | `_loc_import(root)` → `game/tl/` из `loc/po/` | exit 1 при ошибках разметки переводов |
| 8 | `cli.py:156` | `_check_budgets(root)` → `release.py:29-66 budget_failures` (G19) | `бюджет: …` + exit 1 |
| 9 | `cli.py:153` | зелёное `build: OK` | — |

### Что меняется при `--check` (CI-режим, G1)

| Шаг | Строка | Отличие |
|---|---|---|
| 4′ | `cli.py:104` | `build_assets(root, check=True)` — **ничего не пишет**; любой несвежий выход → `устарело: assets/<rel>` + `_fail("game/assets не свеж")` |
| 5′ | `cli.py:116` | `compile_content(root, check=True)` — выходы считаются в память, побайтово сравниваются с диском, `result.stale` наполняется; запись не происходит (`compile.py:882-890`) |
| 8a′ | `cli.py:127-130` | `res.stale` → `устарело: <rel>` + `_fail("генерат не свеж — выполните vn build")` |
| 8b′ | `cli.py:133-141` | **дополнительно** `validate_translations(root)` — read-only проверка разметки PO. Комментарий в коде честный: полный build упал бы на импорте tl, поэтому `--check` обязан ловить то же до мержа |
| 8c′ | `cli.py:142` | бюджеты G19 проверяются и в CI-режиме |
| 9′ | `cli.py:143` | зелёное `check: генерат свеж` и **ранний return** — `_loc_import` не выполняется |

**Грабля `--check --profile draft`.** На check-пути профиль ассетов не передаётся: `build_assets(root, check=True)`, а дефолт сигнатуры — `profile="full"` (`tools/vn/src/vn/assets/pipeline.py:251`). Значит зона, собранная как `vn build --profile draft`, в `vn build --check` всегда покажется несвежей. Перед проверкой пересоберите на `full`.

`vn content compile` — **не** укороченный `vn build`. Он не запускает линт (`cli.py:421-424`: команда зовёт только `compile_content`) и не валидирует по схемам `*.vars.yaml`, `content/audio/*.yaml`, `content/ui/strings.yaml`, `content/renames.yaml`, `content/migrations/registry.yaml`. Битый файл из этого списка даст не понятную схемную ошибку, а `внутренняя ошибка компилятора: KeyError`. Используйте его только для быстрой итерации, финальная команда — `vn build`.

---

## 4. Куда встроен компилятор кроме `vn build`

| Команда | Строка | Режим |
|---|---|---|
| `vn content compile [--check]` | `cli.py:399-422` | напрямую, без линта |
| `vn bootstrap` | `cli.py:208-218` | doctor → assets full → compile → loc import |
| `vn assets validate` | `cli.py:522-547` | `build_assets(check=True)` + `compile_content(check=True)` |
| `vn dev` (watcher) | `cli.py:243-262` | правка `assets_src/` → assets draft + compile; правка `content/` → только compile |
| `vn release build` | `cli.py:1529-1530` | `vn build` выполняется **до** релизного гейта |

Полный список вызовов `compile_content` — этот и есть: `cli.py:116` (build), `cli.py:216` (bootstrap), `cli.py:247,257` (dev), `cli.py:407` (content compile), `cli.py:541` (assets validate), `release.py:391` (релизный гейт). Проверяется одной командой: `grep -rn "compile_content" tools/vn/src/vn/`.

**`vn pack build` компилятор НЕ вызывает.** `pack_build` (`cli.py:1602-1639`) только зипует **уже существующий** генерат: `manifest.yaml` пака плюс файлы из `game/generated/scenes/<ch>/`. Прогоняйте `vn build` перед `vn pack build` руками. (`cli.py:1576` — это импорт внутри **`vn pack validate`**, а не `pack build`.)

**Охранник «нет скомпилированных сцен» теперь рабочий — IMPLEMENTED.** Раньше он был недостижим: сцены считались общим счётчиком вместе с манифестом, манифест давал `n = 1` всегда, и при пустом или несвежем `game/generated/` пак молча уезжал как zip почти без содержимого. Сейчас список сцен собирается отдельно от манифеста и **до** открытия архива (`cli.py:1617-1619` — иначе «нет генерата» обнаруживалось бы, когда неполный zip уже лежит в `build/packs/` и может уехать в депот), а условие звучит так (`cli.py:1624-1626`):

```
пак объявляет главы, но в game/generated/scenes/ нет ни одной их
скомпилированной сцены — сначала vn build
```

Падение происходит **до** создания zip. Ноль сцен сам по себе ошибкой не считается: пак-контейнер `packs/nsfw` глав не объявляет, собирается штатно и получает жёлтое предупреждение «не объявляет глав … — в архиве только манифест» (`cli.py:1635-1637`), чтобы архив из одного манифеста не выглядел поломкой сборки.

**Что осталось незакрытым:** охранник проверяет «хоть одна скомпилированная сцена на весь пак», а не по каждой главе. Пак с двумя главами, у которого собрана одна, пройдёт молча.

`vn assets watch` использует тот же watcher, но передаёт `lambda: None` вместо контентного колбэка (`cli.py:566`) — правки `content/` в этом режиме молча игнорируются. Для одновременного слежения нужен `vn dev`.

---

## 5. Как разбирается авторский `.rpy` — build-bridge (G24)

**Регексами `.rpy` не парсится нигде.** Единственный легальный способ — парсер самого движка из пиннованного SDK.

```
tools/vn (compile) ──► renpy.exe <root> vn_analyze <out.json> <файлы…> ──► JSON AST-сводка
```

- Команда объявлена в `game/framework/00_core/050_build_bridge.rpy:144` через `renpy.arguments.register_command("vn_analyze", …)`. Обработчик возвращает `False` — игра не запускается, движок используется как парсер.
- Вызов и таймаут: `tools/vn/src/vn/content/analyze.py:57-70`, `subprocess.run(..., timeout=300)`. Ненулевой код или отсутствующий `out.json` → `AnalyzeError` → `CompileError`.
- Путь к SDK — **только** из переменной окружения `RENPY_SDK` (`analyze.py:23-34`; тот же механизм у `doctor.py:24-30`). Нет SDK и при этом в `content/` есть главы — честная ошибка, а не трейсбек: «RENPY_SDK не установлен, а в content/ есть главы: компиляция сцен требует парсер Ren'Py из пиннованного SDK (G24)».
- Кэш: `.vncache/analyze-<24 hex>.json`, ключ = blake3 от `vn.__version__` + байтов самого `050_build_bridge.rpy` + пар (путь, байты) всех входных файлов (`analyze.py:42-53`). Правка моста или бамп версии тулинга инвалидируют кэш целиком.

Что мост возвращает на файл (`050_build_bridge.rpy:109-113`): `labels`, `jumps`, `calls`, `returns`, `menus`, `says`, `say_list`, `menu_markers`, `var_reads`, `var_writes`, `errors`.

**Две ключевые грабли внутри моста:**

1. **Неявный `Return` в конце файла.** Парсер Ren'Py дописывает `Return` без выражения в конец любого `.rpy`. Без обрезки он ловился бы как «пустой авторский return» и валил валидацию сцены с объявленными exits. Мост его отрезает — `050_build_bridge.rpy:124-126`:
   ```python
   if stmts and type(stmts[-1]).__name__ == "Return" \
           and getattr(stmts[-1], "expression", None) is None:
       stmts = stmts[:-1]
   ```
2. **На верхнем уровне `scene.rpy` разрешён только `label`.** Любой другой стейтмент → ошибка «line N: стейтмент X вне label запрещён в scene.rpy» (`050_build_bridge.rpy:127-133`).

Переменные извлекаются не текстом, а `ast`-контекстом: `Store` → запись, `Load` → чтение, только для управляемых stores по регексу `^(g|ch\d{2}|mech_[a-z0-9_]+|dlc_[a-z0-9_]+|persistent)$` (`050_build_bridge.rpy:13-37`). Непарсящийся python-фрагмент молча пропускается — анализ не валится.

### Что компилятор делает с этой сводкой

`scenes.py:69-194 validate_scene` — контракт C2 (детали в [12-scenes.md](12-scenes.md)): метки только `^ch\d{2}_s\d{3}__[a-z0-9_]+$` и с префиксом своей сцены (`scenes.py:18,81-88`); обязательна `<full_id>__body` (`:89-90`); `jump`/`call` только внутрь своей сцены и без expression-целей (`:92-104`); условные пункты `menu` запрещены — движок фильтрует их до `screen choice`, и перевод по индексу съехал бы (`:106-114`); `return` только строковым литералом из `exits` (`:118-137`); фактические чтения/записи store-атрибутов сверяются с Variable Registry (`:148-159`).

Эмиссия — `scenes.py:197-273`, фиксированный порядок. Реальный файл `game/generated/scenes/ch01/ch01_s020.gen.rpy`:

```renpy
label ch01_s020:
    $ vn.checkpoint("ch01_s020")
    $ renpy.scene("sprites")
    scene bg school_gate day with dissolve
    call ch01_s020__body from _call_ch01_s020__body
    $ vn.check_scene_stack()
    if _return == "roof":
        jump ch01_s030
    # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)
    $ vn.unwind_call_stack()
    jump vn_scene_unavailable
```

Авторский `.rpy` дописывается в конец генерата **дословно**, после маркера `# ══ Авторский источник (копия)` (`scenes.py:270-271`). Компилятор внутрь авторского кода не лезет — в частности, `$ vn_qa.choice(...)` в ветки меню не вставляется, вопреки `docs/ARCHITECTURE.md:544-551` (**NOT IMPLEMENTED**).

---

## 6. Свежесть, детерминизм, манифест

**Хэш везде blake3** (`compile.py:22,48-53`). В шапке каждого генерата — `# source: <rel>  blake3:<первые 16 hex>` (`compile.py:56-68`).

**Как на самом деле определяется свежесть.** Честно и без прикрас:

1. Компилятор всегда строит **все** выходы в память целиком — инкрементальности по входам нет.
2. `--check`: побайтовое сравнение `path.read_bytes() != text.encode("utf-8")` (`compile.py:882-890`). Несовпало — в `result.stale`.
3. Плюс к этому: выходы прошлого `manifest.json`, которых нет в новом наборе, докладываются как `"<rel> (осиротел)"`.
4. Режим записи: неизменённые файлы **не перезаписываются байтово** (`compile.py:905-907`) — иначе Ren'Py перекомпилировал бы все `.rpyc`. Второй прогон подряд даёт `written == []` (проверяется `tools/vn/tests/test_compile.py:80-88`).
5. Осиротевшие выходы удаляются парой `.rpy` + `.rpyc` по диффу манифестов (`compile.py:892-897`).

**`manifest["inputs"]` пишется, но обратно не читается.** Из манифеста используется ровно одно поле — `outputs`, для диффа осиротевших (`compile.py:873-879`). Ни одна строка кода не сравнивает сохранённые хэши входов с текущими. Следствия:

- обещание `docs/ARCHITECTURE.md:655` «пересборка только изменённых источников по manifest.json» — **NOT IMPLEMENTED**;
- правка источника, не меняющая выход, — полный no-op;
- `game/generated/manifest.json` объявляет `schema: gen_manifest@1`, но **никто его не валидирует по схеме** в проде: только тест `tools/vn/tests/test_verify_regressions.py:127-133`.

**Заголовки `# source:` местами врут.** Это известное расхождение, не выдумывайте по ним зависимости:

| Файл | Заявляет | Реально зависит ещё и от |
|---|---|---|
| `state/migrations.gen.rpy` | `project.yaml` | `content/migrations/*.py` (инлайнится текст!) |
| `registry/{chapters,scenes,menus}.gen.rpy` | `project.yaml` | все `chapter.yaml`, `loc/ledger/*`, `content/ui/strings.yaml` |
| `registry/images.gen.rpy` | `character.yaml` | `content/locations/*` и скан `game/assets/{cg,mov,spr}` |

**Что детерминировано, а что нет.** Выходы итерируются `sorted(outputs.items())`; vars/audio/персонажи сортируются. Но: `VN_GALLERY` сохраняет порядок объявления в YAML (`compile.py:180-186`), `VN_GALLERY_CATEGORIES` сортируется по `(order, id)` (`compile.py:281`), а порядок веток `if _return == …` следует порядку `exits` в `scene.yaml` (`scenes.py:247`). Перестановка ключей в YAML меняет байты генерата.

### `version.gen.rpy` привязан к коммиту

`compile.py:82-87`:

```python
version = f"{project['version']}+{sha}"          # sha = repo.git_sha(root)
... f'define config.version = "{version}"\n'
```

Сейчас на диске: `define config.version = "0.1.4+dd1cb3e"`, `git rev-parse --short HEAD` = `dd1cb3e` — совпадает. Но **любой новый коммит, checkout или pull делает `version.gen.rpy` несвежим сам по себе**, даже если ни один файл `content/` не тронут.

Практические следствия:

- Локально: после `git commit` первый же `vn build --check` покажет `устарело: version.gen.rpy`. Это норма, не баг — просто прогоните `vn build`.
- Ставить `vn content compile --check` в pre-commit hook бессмысленно: он будет краснеть после каждого коммита.
- В CI проблемы нет, потому что `game/generated/` не в git (`.gitignore:2`) и каждый прогон собирает генерат заново на своём коммите: `.github/workflows/ci.yml` делает `vn build`, затем `vn content compile --check` в том же job'е и на той же ревизии. В `.gitlab-ci.yml` стадия `test` получает `game/generated/` артефактом стадии `build` — тоже одна ревизия.
- `git_sha` при отсутствии git возвращает `"nogit"` (`repo.py:35-43`), так что сборка в чистом tarball не падает — но `config.version` будет `0.1.4+nogit`.

---

## 7. Линтер: 33 диагностики

`tools/vn/src/vn/content/lint.py` (463 строки), точка входа `lint(root, layout=True)` (`lint.py:146`). CLI — `vn content lint [--layout/--no-layout]` (`cli.py:382-396`), по умолчанию layout включён. Предупреждения никогда не валят прогон; ошибки → `_fail("lint: N ошибок")`, exit 1.

Инвариант, записанный в самом коде (`lint.py:34`): **«lint зелёный ⇒ build не падает»**. Он держится не полностью — см. §7.3.

### 7.1 Таблица правил

Sev: `E` — ошибка, `W` — предупреждение, `E/W` — зависит от `status` главы (§7.2).

| # | Точный текст сообщения | Триггер | Sev | Код |
|---|---|---|---|---|
| 1 | `tools/schemas: {e}` | конструктор `SchemaRegistry` бросил `ValueError`. **Линт немедленно возвращается — остальные проверки не выполняются** | E | `lint.py:116` |
| 2 | `{rel}: обязательный файл отсутствует` | путь из `REQUIRED_FILES` не существует | E | `lint.py:129` |
| 3 | `{rel}: не парсится: {e}` | исключение YAML/JSON-парсера; документ помечается `invalid` и пропускается граф-проверками | E | `lint.py:134` |
| 4 | `{path}: отсутствует обязательное поле schema (правило G16)` | документ не dict или без ключа `schema` | E | `schemas.py:37` |
| 5 | `{path}: неизвестная схема {sid!r}; зарегистрированы: {known}` | `schema:` не найдена в реестре; сообщение перечисляет все id | E | `schemas.py:42` |
| 6 | `{path}: {loc}: {err.message}` | любое нарушение JSON Schema Draft 2020-12; `loc` — путь через `/` или `<root>` | E | `schemas.py:50` |
| 7 | `loc/po/{d.name}/: нет language.yaml — пакет языка не собран (vn loc add {d.name} --name <native>)` | каталог в `loc/po/` без манифеста | E | `lint.py:150` |
| 8 | `{mf_rel}: code ({code}) != имени каталога ({d.name})` | `language.yaml:code` ≠ имени папки (ADR-0005) | E | `lint.py:155` |
| 9 | `{dir}: имя папки главы вне конвенции ch<NN>_<slug> (1.4)` | каталог в `content/chapters/` или `packs/*/chapters/` не матчит `CHAPTER_DIR_RE` | E | `lint.py:168` |
| 10 | `{dir}: нет chapter.yaml` | корректная папка главы без манифеста | E | `lint.py:174` |
| 11 | `{ch_yaml}: id ({meta['id']}) != префиксу папки ({ch_id})` | `chapter.yaml:id` ≠ `ch<NN>` из имени папки | E | `lint.py:177` |
| 12 | `{f}: имя файла сцены вне конвенции s<NNN>_<slug>.scene.(yaml\|rpy)` | файл в `scenes/` не матчит `SCENE_FILE_RE` (`.gitkeep` и подкаталоги пропускаются) | E | `lint.py:187` |
| 13 | `{f}: дубликат id сцены {sid} в главе` | два `.scene.yaml` с одним `sNNN` в одной главе | E | `lint.py:192` |
| 14 | `{f}: нет парного .scene.rpy (сцена = ПАРА файлов, G3)` | `.scene.yaml` без соседа `.rpy` | E | `lint.py:196` |
| 15 | `{f}: id ({smeta['id']}) != номеру файла ({sid})` | `scene.yaml:id` ≠ `sNNN` из имени файла | E | `lint.py:233-234` |
| 16 | `{f}: нет парного .scene.yaml (сцена = ПАРА файлов, G3)` | `.scene.rpy` без соседа `.yaml` | E | `lint.py:203` |
| 17 | `{ch_yaml}: scene_order ссылается на несуществующую сцену {s}` | элемент `scene_order` без файла сцены | E/W | `lint.py:212` |
| 18 | `{ch_yaml}: entry_scene {entry} не существует` | `entry_scene` без файла сцены | E/W | `lint.py:214` |
| 19 | `{rel}: exits.{exit_id} -> {t}: цель не существует` | межглавный exit `chNN/sNNN` в никуда | E/W | `lint.py:248` |
| 20 | `{rel}: exits.{exit_id} -> {t}: цель не существует в главе {ch_id}` | внутриглавный exit `sNNN` в никуда | E/W | `lint.py:251` |
| 21 | `{ch_id}: сцена {sid} недостижима из entry_scene {entry} — на неё не ведёт ни один exit (мёртвый контент)` | обход графа от `entry_scene` сцену не достиг | E/W | `lint.py:282` |
| 22 | `{ch_id}: сцена {sid} — тупик (нет exits, но не последняя в scene_order): игрок упрётся в «конец контента»` | достижимая сцена с пустыми `exits`, не равная `scene_order[-1]` | **всегда W** | `lint.py:292` |
| 23 | `{d}: ключ персонажа вне конвенции ^[a-z][a-z0-9_]{1,23}$` | каталог в `content/characters/` не матчит `CHAR_DIR_RE` | E | `lint.py:302` |
| 24 | `{d}: нет character.yaml` | папка персонажа без манифеста | E | `lint.py:306` |
| 25 | `{c_yaml}: id ({cmeta['id']}) != имени папки ({d.name})` | `character.yaml:id` ≠ имени папки | E | `lint.py:310` |
| 26 | `{rel}: store ({data['store']}) != id главы ({ch_id})` | `content/chapters/<dir>/vars.yaml` с чужим `store` | E | `lint.py:317` |
| 27 | `{reg_rel}: выпущенная сцена {released} исчезла без записи в renames.yaml (id неизменяемы навсегда, G7)` | id сцены в реестре, файла нет, и нет записи в `renames.scenes` / `deleted_scenes` | E | `lint.py:351` |
| 28 | `{reg_rel}: выпущенная глава {released} исчезла (главы не переименовываются, G7)` | id главы в реестре, каталога нет. Escape-hatch отсутствует | E | `lint.py:389-393` |
| 29 | `{reg_rel}: выпущенный персонаж {released} исчез (id неизменяемы, G7)` | id персонажа в реестре, папки нет ни в `content/characters/`, ни в `packs/*/characters/` | E | `lint.py:394-398` |
| 30 | `{reg_rel}: выпущенная переменная {released} исчезла без записи в renames.vars (id неизменяемы, G7)` | `store.name` в реестре не найден ни в одном `vars@1` и не покрыт `renames.vars` | E | `lint.py:399-404` |
| 31 | `{path}: бинарь в assets_src не покрыт Git LFS — он уедет в историю целиком и навсегда. Добавьте расширение в .gitattributes (filter=lfs) или уберите файл из зоны мастеров` | любой нетекстовый файл под `assets_src/`, которому `git check-attr filter` не отдаёт `lfs` | E | `lint.py:436-441` |
| 32 | `assets_src: бинарей мимо LFS на {actual_mb} МБ > порога ADR-0004 ({limit_mb} МБ); крупнейший — {path} ({mb} МБ). Заведите их в LFS (.gitattributes) либо в хранилище (vn assets lock + push)` | сумма нетекстовых байт **мимо LFS** > 50 МБ | E | `lint.py:445-452` |
| 33 | `layout: обязательный каталог отсутствует: {d}/` | отсутствует элемент `REQUIRED_DIRS`; только при `--layout` | E | `lint.py:456-458` |
| 34 | `layout: запрещённый путь существует: {p} (G2/1.2)` | существует элемент `FORBIDDEN_PATHS`; только при `--layout` | E | `lint.py:459-461` |

Порог ADR-0004 в редакции **ADR-0012** (правила 31–32) считается только по бинарям **мимо LFS**: покрытие спрашивается у самого git (`_lfs_tracked`, `lint.py:76-102`), файл в LFS в историю объектом не уезжает и под порог не попадает. Из подсчёта исключены расширения `.json .yaml .yml .md .txt .gitkeep` (`lint.py:429-432`). Константа — `ADR0004_BINARY_LIMIT_MB = 50` (`lint.py:47`). **Warn-порога «60 % / 30 МБ» в коде нет** — правило 31 краснит на первом же файле мимо LFS, а правило 32 срабатывает только за 50 МБ (`vn content lint` на этом дереве сегодня: 0 ошибок, 0 предупреждений).

### 7.2 G15: что именно деградирует в `status: draft`

Механизм — одна строка, повторённая трижды: `complain = rep.warn if status == "draft" else rep.error`.

| Точка | Строка | Деградирует |
|---|---|---|
| Порядок и вход главы | `lint.py:209` | правила 17 (`scene_order`), 18 (`entry_scene`) |
| Цели exits | `lint.py:231` | правила 19, 20 |
| Достижимость | `lint.py:270` | правило 21 |

**Не деградирует ничего больше.** Схемы, парность файлов, конвенции имён, `id_registry`, порог `assets_src`, layout — всегда ошибки. Правило 22 (тупик) — всегда предупреждение независимо от статуса.

Компилятор применяет ту же логику к своим проверкам: `entry_scene`/`scene_order` (`compile.py:1057-1063`), необъявленные переменные сцены (`scenes.py:235`), недостижимые цели exits (`scenes.py:261,269-275`). У draft-главы битая цель не роняет сборку — вместо `jump` эмитится живая заглушка (`scenes.py:253-257`):

```renpy
    # TODO(draft): цель ch01_s040 ещё не написана
    $ vn.unwind_call_stack()
    jump vn_scene_unavailable
```

Практический вывод: `status: draft` в `chapter.yaml` — рабочий режим «пишу главу, куски ещё не связаны». Перед релизом статус меняется на `playtest`/`release`, и все эти предупреждения обязаны превратиться в зелёный прогон. Подробнее — [09-chapters.md](09-chapters.md).

### 7.3 `REQUIRED_FILES` (7) и `--layout` (10 + 2)

`REQUIRED_FILES` (`lint.py:35-43`) — безусловные входы компилятора и реестры G7:

```
project.yaml
.vnstorage.yaml
content/renames.yaml
content/registry/id_registry.json
content/flags.yaml
content/anchors.yaml
content/migrations/registry.yaml
```

`REQUIRED_DIRS` — 10 каталогов, обязанных существовать (`lint.py:21-32`):

```
game/framework/00_core          content/chapters
game/framework/00_core/engine_compat   content/characters
game/framework/10_systems       content/registry
game/framework/20_ui            tools/schemas
game/framework/90_debug         docs
```

`FORBIDDEN_PATHS` — 2 пути, которых существовать не должно (`lint.py:50-53`): `game/content` (контент строго вне `game/`, G2) и `game/images` (автоопределение образов Ren'Py сознательно не используется).

`--layout` — это ровно две проверки `is_dir()` / `exists()` по хардкод-спискам. Он **не** сверяется с `docs/conventions/folder-layout.md`, хотя тот документ (строка 3) это утверждает — **PARTIALLY IMPLEMENTED**.

### 7.4 Проверки, которых в линте НЕТ (живут только в компиляторе)

Инвариант «lint зелёный ⇒ build не падает» ломают: участники сцены не объявлены в `content/characters/` (`compile.py:1031-1037`), коллизия id главы «ядро vs пак» (`compile.py:727-729`), `id` манифеста пака ≠ имени папки (`compile.py:572-575`), имя миграции вне конвенции и незарезервированный номер (`compile.py:386,391`), разрыв цепочки миграций (`compile.py:400`), persistent-переменная без префикса `vn_` (C9, `compile.py:102`), `location.yaml:id` ≠ имени папки (`tools/vn/src/vn/content/images.py:42`), вся валидация галереи и достижений (`compile.py:173-247, 797-816`), отсутствие метки `__body` (`scenes.py:90`). Отсюда правило: **не считайте зелёный `vn content lint` доказательством, что `vn build` пройдёт.**

---

## 8. Реестр схем (39 файлов)

`tools/vn/src/vn/schemas.py` (51 строка). Каталог — `tools/schemas/`, никакого синглтона нет: каждый потребитель строит свой `SchemaRegistry` (линтер `lint.py:114`, компилятор `compile.py:591`, доктор, релизный гейт, `vn pack validate` и др.).

Правила, которые проверяются при загрузке реестра — оба фатальны для всего прогона линта:

| Правило | Код |
|---|---|
| Имя файла матчит `^(?P<name>[a-z][a-z0-9_]*)@(?P<ver>\d+)\.schema\.json$` | `schemas.py:13,26` |
| `properties.schema.const` строго равен `<name>@<ver>` из имени файла | `schemas.py:29-31` |

Плюс инварианты, зафиксированные тестом `tools/vn/tests/test_schemas.py:9-14`: `const` совпадает с id **и** на верхнем уровне схемы стоит `additionalProperties: false`. Валидатор — `jsonschema.Draft202012Validator`, кэшируется на schema-id внутри экземпляра реестра (`schemas.py:43-46`). Все `$ref` — внутридокументные (`#/$defs/...`); кросс-файловые ссылки не резолвятся, `referencing`-реестр не подключён.

### Как добавить новую схему

1. Создайте `tools/schemas/<name>@1.schema.json`. Обязательный минимум:
   ```json
   {
     "$schema": "https://json-schema.org/draft/2020-12/schema",
     "$id": "vn:schemas/<name>@1",
     "title": "<name>@1 — что описывает",
     "type": "object",
     "properties": { "schema": {"const": "<name>@1"} },
     "required": ["schema"],
     "additionalProperties": false
   }
   ```
2. Проверьте, что документы попадают в поле зрения линта — `_iter_declarations` (`lint.py:76-102`) обходит `REQUIRED_FILES`, `loc/loc.yaml`, `loc/po/*/language.yaml`, `content/**/*.{yaml,yml}`, `packs/**/*.{yaml,yml}`, `content/registry/*.json`, `assets_src/**/*.{manifest.json,yaml,provenance.json}`. Файл вне этих путей схемой валидироваться не будет, даже если несёт `schema:` — так сейчас живут `tools/comfyui-models.yaml`, `loc/ledger/*.json`, `ci/release-manifest.json`, `game/generated/manifest.json`.
3. Прогоните `python -m pytest tools/vn/tests/test_schemas.py -q` — тест поймает несовпадение `const` и забытый `additionalProperties: false`.
4. `vn content lint` и `vn doctor` (проверка №6 — «реестр схем: N схем») должны остаться зелёными.

### Как выпустить новую версию схемы

Версия — часть имени файла и id. Ломающее изменение = **новый файл** `<name>@2.schema.json` рядом со старым; старый не удаляется, пока хоть один документ объявляет `<name>@1`. Два живых примера: `loc@1.schema.json` остался в реестре, хотя все документы переехали на `loc@2` (список языков убран по ADR-0005); `build_info@1` оставлена с пометкой «устарела» после перехода на `build_info@2` (поле `patron_token` заменено на производную метку `patron_tag`, ADR-0011) — она нужна, чтобы читать уже выпущенные артефакты. Совместимое расширение (новое опциональное поле) делается правкой существующего файла — но помните про `additionalProperties: false`: любое новое поле в декларациях обязано быть сначала добавлено в схему, иначе линт покраснеет.

### Бывшая дыра G16 закрыта — IMPLEMENTED

Раньше `.vncache/assets-manifest.json` объявлял `"schema": "assets_manifest@1"`, а самого файла схемы в `tools/schemas/` не было: формальное нарушение G16, которое не взрывалось лишь потому, что `.vncache/` лежит вне `_iter_declarations`.

Сейчас `tools/schemas/assets_manifest@1.schema.json` существует, и манифест **валидируется ею при каждой записи**: `tools/vn/src/vn/assets/pipeline.py:441-450` собирает документ, строит `SchemaRegistry(tools/schemas)` и складывает результат `validate()` в `rep.errors`. Проверка сознательно идёт по живому документу — расхождение писателя и схемы иначе всплывало бы у читателя (`cache_gc`, `--check`) уже в виде мусора. Реестр берётся, только если каталог `tools/schemas/` существует (у синтетических корней в тестах его нет — сверять не с чем), а сам файл пишется **даже при ошибке схемы**: манифест описывает то, что уже лежит на диске, и без записи следующая сборка потеряет точечную очистку сирот (`pipeline.py:451-454`).

---

## 9. `vn content graph` — граф сцен

```bash
vn content graph                       # Mermaid в stdout
vn content graph --out docs/graph.mmd  # в файл
```

`tools/vn/src/vn/content/graph.py:13-45`, CLI `cli.py:425-437`. Читает **только декларации** — SDK не нужен, работает мгновенно. Узлы — `chNN_sNNN` с подписью-слагом, рёбра — `exits` (метка = `<exit_id>` плюс `[when]`, если условие есть), сцена без `exits` получает ребро на `vn_end([конец контента])` (`graph.py:41-42`). Кавычки и угловые скобки в `when` экранируются в `#quot;`/`#lt;`/`#gt;` (`graph.py:37-39`), иначе Mermaid ломается.

**Честно: паки он не видит.** `graph.py:15` итерирует только `content/chapters`. Проверено запуском на текущем репозитории: в выводе есть подграф `ch01_awakening (draft)` с тремя сценами, `ch90` из `packs/ep_beach` отсутствует. Межпаковые `exits` отрисовались бы висячими узлами. **PARTIALLY IMPLEMENTED.** Флага `--chapter` нет.

---

## 10. Мёртвые декларации

| Файл | Кто читает | Статус |
|---|---|---|
| `content/flags.yaml` (`flags@1`) | только проверка существования + схема в `lint.py:40`. Компилятор его не открывает | **NOT IMPLEMENTED.** `docs/ARCHITECTURE.md:696` требует флаги как гейт **компиляции** («выключенный контент не существует в release-сборке») — такого гейта в `compile.py` нет. Поле `expires` в схеме описано как «линтер напомнит» — кода нет вообще |
| `content/anchors.yaml` (`anchors@1`) | только `lint.py:41` | **NOT IMPLEMENTED.** Точки инъекции модов (G10) существуют как данные; `scene:` в них не сверяется с реальными сценами |
| `content/registry/id_registry.json` (`id_registry@1`) | пишет `release.py:99 stamp_id_registry`, читает `lint.py:354-420` (правила 27–30 и ассеты ADR-0012) | **IMPLEMENTED, но ИНЕРТЕН.** Все четыре массива пусты, потому что `stamp_id_registry` записывает только главы со `status: "release"`, а единственная глава `ch01_awakening` — `draft`. Гейт G7 сегодня ничего не ловит |

Все три обязаны существовать (`REQUIRED_FILES`) — удалять их нельзя, линт немедленно покраснеет правилом 2. Просто не рассчитывайте, что запись в них на что-то влияет.

---

## 11. Чего в конвейере нет

| Заявлено | Где заявлено | Реальность |
|---|---|---|
| `vn build --use-artifact <sha>` (аварийный режим) | `docs/ARCHITECTURE.md` — 14 упоминаний (проверено `grep -c`) | **NOT IMPLEMENTED.** У `build` есть только `--check` и `--profile` (`cli.py:85-87`). Во всём тулчейне строка `use-artifact` встречается один раз — в `title` схемы `tools/schemas/gen_manifest@1.schema.json:4`. Аварийный откат сегодня делается руками: скачать артефакт `generated-<sha>` из GitHub Actions (`ci.yml`, `retention-days: 30`) и распаковать в `game/generated/` |
| Группа `vn validate --schemas/--budgets` | ARCHITECTURE.md | **NOT IMPLEMENTED** — группы `vn validate` не существует вовсе |
| `vn content lint --strict` | `ARCHITECTURE.md:1911` | **NOT IMPLEMENTED** — есть только `--layout/--no-layout` |
| `vn content lint --arch` (AST-скан python-блоков на нарушения границ слоёв) | `ARCHITECTURE.md:722` | **NOT IMPLEMENTED** |
| `vn content lint --schemas` | `ARCHITECTURE.md:776` | **NOT IMPLEMENTED** — схемная валидация безусловна (это строже, но описанная CLI-поверхность неверна) |
| Запрет `{font=...}` линтером | `ARCHITECTURE.md:2865` | **NOT IMPLEMENTED** |
| `loc/interpolation.yaml` (белый список интерполяций) | `ARCHITECTURE.md:2896` | **NOT IMPLEMENTED** — файла нет, схемы нет, кода нет |
| Инкрементальная пересборка по `manifest.json` | `ARCHITECTURE.md:655` | **NOT IMPLEMENTED** — см. §6 |
| `$ vn_qa.choice(...)` первым стейтментом каждой ветки меню | `ARCHITECTURE.md:544-551` | **NOT IMPLEMENTED** — авторский код копируется дословно; `vn_qa.choice` в `030_flow.rpy:98-101` — заглушка `pass` |
| `vn content compile --watch`, `vn content graph --chapter`, `vn content who-writes`, `vn content rename` | ARCHITECTURE.md | **NOT IMPLEMENTED** |

---

## 12. Как изменить / как расширить

**Добавить поле в существующую декларацию.**
1. Схема: `tools/schemas/<name>@1.schema.json` — из-за `additionalProperties: false` без этого шага линт покраснеет.
2. Компилятор: научите эмиттер читать поле (`compile.py` или `content/{scenes,images}.py`).
3. Рантайм: если поле должно доехать до игры — это `game/framework/`, см. [07-backend.md](07-backend.md).
4. Тест в `tools/vn/tests/` + `vn build`.

**Добавить новый выход генерата.**
1. Напишите эмиттер, возвращающий `str` (заголовок берите через `_header([...])` — иначе файл потеряет blake3-шапку).
2. Впишите путь → текст в словарь `outputs` (`compile.py:850-871`). Всё остальное — сравнение, запись, очистка сирот, манифест — произойдёт само.
3. Ren'Py должен подхватить файл из `game/generated/` — про init-приоритеты и `init offset` см. [05-renpy-development.md](05-renpy-development.md) и ADR-0003.
4. Учтите: старый `manifest.json` из прошлой сборки не знает нового пути — первый прогон просто запишет его; удалённый выход будет вычищен вместе с `.rpyc` по диффу.

**Зарегистрировать новый входной файл.** Обязательно проведите его через `src(path)` (`compile.py:599`), иначе он не попадёт в `manifest["inputs"]` и не получит запись `# source:` в шапке. Помните: `src()` бросает `CompileError`, если файла нет, — регистрируйте только по-настоящему обязательные входы, опциональные оборачивайте в `if path.is_file()`.

**Добавить правило линта.** Пишите в `lint.py` в соответствующую секцию, соблюдая формат сообщения `«<rel>: <что не так> (<норма>)»` — по этому формату сообщения читаются и человеком, и агентом. Для граф-проверок берите `complain = rep.warn if status == "draft" else rep.error`. Тест — `tools/vn/tests/test_lint.py` (16 тестов).

**Добавить главу/сцену.** Скаффолдингом, не руками: `vn chapter new <slug>`, `vn scene new <chapter> <slug>`, `vn scene stub <chapter> sNNN`. Детали — [09-chapters.md](09-chapters.md), [12-scenes.md](12-scenes.md).

---

## Чего НЕ делать

- **Не редактировать `game/generated/`.** В каждом файле шапка `НЕ РЕДАКТИРОВАТЬ. Правки перезапишутся.` Ближайший `vn build` их сотрёт, а зона не в git — восстановить будет неоткуда.
- **Не парсить `.rpy` регексами** ни в тулинге, ни в скриптах. Это прямой запрет G24; единственный легальный путь — `vn_analyze` через build-bridge. Строчка комментария в `050_build_bridge.rpy:4` формулирует это буквально.
- **Не убирать обрезку неявного `Return`** в `050_build_bridge.rpy:124-126`. Уберёте — все сцены с объявленными `exits` начнут падать с «пустой return в сцене с объявленными exits».
- **Не возвращать буквальное сравнение `version.gen.rpy`** в `--check`: git sha внутри него меняется на каждом коммите, и гейт свежести снова начнёт краснеть всегда, то есть перестанет что-либо означать. Нормализация — `_stale_key` (§6), инвариант закрыт тестами в `tools/vn/tests/test_compile.py`.
- **Не запускать `vn build --check --profile draft`** — профиль на check-пути игнорируется, зона всегда покажется несвежей.
- **Не полагаться на `vn content compile` как на основную команду сборки** — он не запускает линт и не валидирует по схемам пять типов документов (§3).
- **Не считать `vn content graph` полной картиной ветвления** — паки в него не попадают.
- **Не рассчитывать, что `vn pack build` пересоберёт генерат** — он только зипует то, что уже лежит в `game/generated/scenes/`; сначала `vn build` (§4). Забудете — охранник упадёт до создания zip, но только если пак объявляет главы: у пака без глав проверять нечего.
- **Не верить строкам `# source:` как списку зависимостей** — для четырёх выходов они неполные (§6).
- **Не рассчитывать, что зелёный `vn content lint` гарантирует зелёный `vn build`** (§7.4).
- **Не заводить схему с `additionalProperties: true`** — тест `test_schemas.py:14` сразу упадёт.

---

## Проверка

```bash
# Быстрый круг (без SDK, секунды)
vn content lint

# Полная сборка
vn build                      # ожидается: build: OK
vn build --check              # ожидается: check: генерат свеж

# Тесты тулинга
python -m pytest tools/vn/tests -q          # 278 тестов
python -m pytest tools/vn/tests/test_compile.py tools/vn/tests/test_lint.py \
                tools/vn/tests/test_schemas.py tools/vn/tests/test_scene_pipeline.py \
                tools/vn/tests/test_verify_regressions.py -q

# Проверка глазами
vn content graph                            # граф ветвления
vn play                                     # требует непустой game/generated/manifest.json
```

В bash-сессиях агента `RENPY_SDK` не наследуется — экспортируйте вручную перед всем, что трогает сцены:
`export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`.

Что проверяет CI (`.github/workflows/ci.yml`): job `lint` → `vn content lint`; job `build-test` → `vn build` → `vn loc keys --check` → `renpy.sh . lint` → `vn content compile --check` → `pytest` → выгрузка `game/generated/` артефактом `generated-<sha>` на 30 дней. Подробности — [29-build-and-release.md](29-build-and-release.md).

Типовые ошибки компиляции с расшифровкой — [36-troubleshooting.md](36-troubleshooting.md).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/content/compile.py` (1211 стр., эмиттеры + оркестрация `compile_content:790`), `tools/vn/src/vn/content/lint.py` (463 стр.), `tools/vn/src/vn/content/scenes.py` (валидация C2 + эмиссия обвязки), `tools/vn/src/vn/content/analyze.py`, `game/framework/00_core/050_build_bridge.rpy`, `tools/vn/src/vn/schemas.py`, `tools/vn/src/vn/cli.py:84-153` (порядок `vn build`), `game/generated/manifest.json` (актуальные 36 входов / 21 выход) |
| **Не трогать** | `game/generated/**` (генерат), `game/assets/**` (выход `vn assets build`), `game/tl/**` (выход `vn loc import`), `.vncache/**` (кэш), `build/**` — всё производное и вне git. Правки там исчезнут при первой же сборке |
| **Зависимости (что сломается ниже по течению)** | правка эмиттера → меняются байты генерата → `vn build --check` краснеет у всех, пока не пересоберут; правка `050_build_bridge.rpy` → инвалидируется весь `.vncache/analyze-*.json` и требуется полный прогон движка; правка схемы → линт, компилятор, `vn doctor` (проверка №6) и релизный гейт строят реестр заново; добавление/удаление выхода → предыдущий `manifest.json` даст диффом удаление осиротевших `.rpy` + `.rpyc`; правка `content/renames.yaml` → `registry/overrides.gen.rpy` (shim-метки и `config.label_overrides`) |
| **Валидация** | `vn content lint` → `vn build` → `vn build --check` → `python -m pytest tools/vn/tests -q`. Для сцен обязателен `RENPY_SDK` |
| **Частые ошибки** | 1) Считать `docs/ARCHITECTURE.md` описанием построенного — это целевой документ; `--use-artifact`, `vn validate`, `lint --strict/--arch/--schemas`, флаги-гейты компиляции там есть, в коде нет. 2) Думать, что `manifest["inputs"]` используется для инкрементальности — он пишется и не читается; свежесть = побайтовое сравнение выходов. 3) Забыть, что `game/assets/` — вход компилятора: `compile` без предшествующего `assets build` даст ошибки реестра образов или warning галереи. 4) Добавить поле в YAML, не добавив в схему — `additionalProperties: false` уронит линт. 5) Разбирать `.rpy` регексами вместо `vn_analyze` (нарушение G24). 6) Вернуть буквальное сравнение `version.gen.rpy` в `--check` — git sha сделает гейт свежести всегда красным и бессмысленным (`_stale_key`) |
