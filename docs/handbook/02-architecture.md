# 02. Архитектура

> **Статус подсистемы:** IMPLEMENTED — зоны каталогов, поток данных, слои `game/framework/` и init-шкала существуют ровно так, как описано ниже; главное «но» — часть норм раздела 0 `ARCHITECTURE.md` (G4, G10, C1, C19, C23, C24) кода под собой не имеет, они помечены в § 7.
> **Отвечает на вопрос:** «Куда класть файл, что его перезапишет, и какую норму я нарушу?»
> **Сверено с кодом:** 2026-08-18, HEAD `db28ce6`. Конвенции именования и полный свод запретов — [45-architecture-rules.md](45-architecture-rules.md).

Архитектура проекта — это не архитектура Ren'Py-игры, а архитектура **конвейера производства**:
источники истины лежат вне `game/`, тулинг `vn` превращает их в статический `.rpy` и собранные
ассеты, Ren'Py получает уже готовое дерево. Нормативный контракт — раздел 0
[`docs/ARCHITECTURE.md:36-203`](../ARCHITECTURE.md) (нормы G1–G24 на `:53-101` и C1–C24 на
`:109-203`), полностью воспроизведён здесь в § 5 и § 6 как справочник.

## Быстрый ответ

```
content/**  packs/**  assets_src/**  loc/po/**   ← вы пишете сюда (в git)
        │
        └── vn build ──→ game/generated/**  game/assets/**  game/tl/**   ← НЕ в git, перезапишется
                                    │
                                    └── Ren'Py (game/framework/** + генерат) ──→ build/dist/**
```

Три правила, которые закрывают 90 % вопросов:

1. **`content/` строго вне `game/`** (G2). Всё, что человек пишет руками, — это `content/`,
   `packs/`, `assets_src/`, `loc/`, `game/framework/`, `tools/`, `docs/`.
2. **`game/generated/`, `game/assets/`, `game/tl/` — производные и не в git** (G4). Правка там
   бессмысленна.
3. **Id неизменяемы навсегда** (G7). Переименование — не `git mv`, а новый id + запись в
   `content/renames.yaml`.

---

## 1. Поток данных

```mermaid
flowchart TB
    subgraph SRC["Источник истины (в git, пишет человек)"]
        C["content/**<br/>YAML-декларации + *.scene.rpy"]
        P["packs/PACK_ID/**<br/>DLC, зеркалит content/"]
        A["assets_src/**<br/>PNG/PSD/видео + *.render.yaml"]
        L["loc/po/LANG/*.po<br/>loc/ledger/chNN.json"]
        FW["game/framework/**<br/>рукописный Ren'Py"]
        PJ["project.yaml<br/>.vnstorage.yaml<br/>tools/schemas/**"]
    end

    subgraph TOOL["Тулинг vn (tools/vn/)"]
        LINT["vn content lint<br/>33 диагностики"]
        ASSETS["vn assets build<br/>tools/vn/src/vn/assets/pipeline.py"]
        COMP["vn content compile<br/>tools/vn/src/vn/content/compile.py"]
        LOCI["vn loc import<br/>tools/vn/src/vn/loc/po.py"]
        BRIDGE["renpy.exe vn_analyze<br/>парсер Ren'Py, G24"]
    end

    subgraph DER["Производное (НЕ в git, перезаписывается)"]
        GEN["game/generated/**<br/>21 *.gen.rpy + manifest.json"]
        GA["game/assets/**<br/>bg cg mov spr ui"]
        TL["game/tl/**<br/>de en pseudo"]
        CACHE[".vncache/**<br/>кэш трансформаций + AST"]
    end

    ENG["Ren'Py 8.5.3<br/>game/framework + генерат"]
    DIST["build/dist/VERSION-FLAVOR/<br/>vn package · vn release build"]

    C --> LINT
    P --> LINT
    L --> LINT
    PJ --> LINT
    LINT --> ASSETS
    A --> ASSETS
    ASSETS --> GA
    ASSETS --> CACHE
    GA --> COMP
    C --> COMP
    P --> COMP
    COMP <--> BRIDGE
    BRIDGE --> CACHE
    COMP --> GEN
    L --> LOCI
    LOCI --> TL
    GEN --> ENG
    GA --> ENG
    TL --> ENG
    FW --> ENG
    ENG --> DIST
```

Порядок внутри `vn build` жёсткий и проверяемый по [`tools/vn/src/vn/cli.py:88-157`](../../tools/vn/src/vn/cli.py):

| Шаг | Что делает | Строка | Провал → |
|---|---|---|---|
| 1 | `lint(root)` — полный линт, `--layout` включён по умолчанию | `:98` | exit 1, сборка не начинается |
| 2 | `_assets_build(root, profile)`, при `--check` — `build_assets(check=True)` | `:118` / `:108` | exit 1 |
| 3 | `compile_content(root, check)` — через `renpy.exe <root> vn_analyze` | `:120` | `CompileError` → exit 1 |
| 4a | при `--check`: сверка свежести → `validate_translations` → `_check_budgets` → `check: генерат свеж` | `:133-147` | exit 1 |
| 4b | при записи: `_loc_import` (PO → `game/tl/`) → `_check_budgets` → `build: OK` | `:155-157` | exit 1 |

**У `vn build` два независимых способа упасть на бюджетах** — `_check_budgets` (`cli.py:176-203`)
проверяет и то, и другое в обоих режимах:

1. **размерные бюджеты G19** — `budget_failures(root)` по `project.yaml: budgets`; сообщение
   `бюджеты G19 превышены (project.yaml: budgets)`;
2. **бюджет памяти сцены** (ADR-0012) — `assets.memory.analyze(root)` по формулам движка над
   `game/assets`; сообщение `бюджет памяти сцены превышен (project.yaml: render.image_cache_mb)`.

Второго линтер не видит вовсе: он считается по собранным ассетам, которых `vn content lint` не
касается. Это третий класс падений после зелёного линта — см. [45 §Частые ошибки](45-architecture-rules.md).

Обратный поток ровно один: **`vn loc keys` дописывает say-id и маркеры меню обратно в авторский
`*.scene.rpy`** парсером Ren'Py (`tools/vn/src/vn/loc/keys.py`). Это единственный инструмент, который правит
источник истины. Подробности — [14-localization.md](14-localization.md).

## 2. Зоны каталогов

| Зона | Что это | В git? | Кто пишет | Что снесёт вашу правку |
|---|---|---|---|---|
| `content/` | Источник истины ядра: YAML-декларации + авторские `*.scene.rpy` | да | человек | — (кроме say-id от `vn loc keys`) |
| `packs/<id>/` | DLC: дерево, зеркалящее `content/`; принадлежность — по расположению (C10) | да | человек | — |
| `game/framework/` | Рукописный Ren'Py-код надстройки | да | человек | — |
| `game/generated/` | 21 `*.gen.rpy` + `manifest.json` (перечень — § 3.1) | **нет** (`.gitignore:2`) | `vn build` | `vn build`, `vn content compile` |
| `game/assets/` | Собранные ассеты: `bg cg mov shots spr ui voice` | **нет** (`.gitignore:3`) | `vn assets build` | `vn assets build`, `vn build` |
| `game/tl/` | Переводы `de/en/pseudo` | **нет** (`.gitignore:4`) | `vn loc import` | `vn loc import`, `vn build` |
| `game/fonts/` | Единственный разрешённый бинарь в `game/`, в LFS | да | человек | — |
| `assets_src/` | Сырцы: `art audio_stems daz live2d psd sims4 spine_export vam video_src voice` (`png/` — исторический алиас `art/`, на диске отсутствует) | да, **через Git LFS** ([ADR-0012](../adr/0012-render-profile-and-oversampling.md) переписал [ADR-0004](../adr/0004-local-png-sources-in-git.md): 22 правила в `.gitattributes`; порог 50 МБ считается только по файлам **мимо** LFS) | человек + рендер | — |
| `loc/` | Обмен с переводчиками: `loc.yaml`, `po/<lang>/`, `ledger/chNN.json` | да | `vn loc *` + переводчик | `vn loc extract` перезаписывает PO-заголовки |
| `tools/vn/` | Единственный CLI проекта (G1) | да | человек | — |
| `tools/schemas/` | 39 JSON Schema — единственный реестр версий схем (G16); устаревшие версии не удаляются, а помечаются в `title`/`description` (так живёт `build_info@1` рядом с `build_info@2`) | да | человек | — |
| `.vncache/` | Кэш трансформаций, AST-кэш, артефакты прогонов | **нет** (`.gitignore:21`) | тулинг | `vn assets cache --gc` |
| `build/` | Дистрибутивы, `rpyc-cache`, паки | **нет** (`.gitignore:20`) | `vn package`, `vn release`, `vn pack build` | — |
| `ci/` | Скрипты и фикстуры CI; `ci/fixtures/rpyc-line/**` — **единственные `.rpyc` в git** (52 файла, негейт `.gitignore:14`); `ci/fixtures/saves/**` — 2 сейва сейв-корпуса | да | человек | — |
| `docs/` | `ARCHITECTURE.md`, `adr/`, `conventions/`, `runbooks/`, `onboarding/`, `pipeline/`, `licenses/`, `handbook/` | да | человек | — |

Запрещённые пути, за которыми следит линтер (`tools/vn/src/vn/content/lint.py:50-53`): `game/content`,
`game/images`. Автоопределение образов по `game/images/` отключено намеренно — все `image`
приходят из `registry/images.gen.rpy`. Обязательные каталоги и файлы — там же
(`lint.py:21-32` `REQUIRED_DIRS`, `:35-43` `REQUIRED_FILES`).

**Каталог `game/assets/audio/` пока не создан, но не из-за поломки конвейера.** Ветка
`copy_audio` читает нормативную зону `assets_src/audio_stems/{bgm,amb,sfx}/`
(`tools/vn/src/vn/assets/pipeline.py:415-430`) и раскладывает `.ogg` в
`game/assets/audio/<kind>/`; каталоги зоны заведены, поведение закрыто тестом
`test_audio_stems_branch_copies_ogg` (`tools/vn/tests/test_assets.py:211`). Каталога нет просто
потому, что в репозитории **ноль `.ogg`**, а `content/audio/{bgm,amb,sfx}.yaml` — `tracks: {}`
у всех трёх. Подробности и оставшиеся дыры — [23-audio.md](23-audio.md).

## 3. Источник истины vs производное

Правило: **у каждого производного файла ровно один источник и ровно одна команда, которая его
воссоздаёт.** Если вы не знаете, кто пересоздаёт файл, — не правьте его.

| Производное | Источник | Команда | Заголовок в файле |
|---|---|---|---|
| `game/generated/**/*.gen.rpy` | `content/**`, `packs/**`, `project.yaml`, `loc/ledger/**` | `vn build` / `vn content compile` | `AUTO-GENERATED by vn content compile (vn 0.1.0)` + `# source:` + `blake3:` |
| `game/generated/manifest.json` | всё вышеперечисленное | та же | `schema: gen_manifest@1` |
| `game/assets/**` | `assets_src/**`, `content/ui/panels.yaml` | `vn assets build` | — (бинари) |
| `game/tl/**` | `loc/po/<lang>/*.po` | `vn loc import` | ручные правки ловит CI |
| `docs/CHANGELOG.md`, `ci/release-manifest.json` | декларации глав + `id_registry` | `vn release changelog` | — |
| `content/registry/id_registry.json` | главы со `status: release` | `vn release changelog` (`stamp_id_registry`, `release.py:126`) | append-only |
| say-id и маркеры `vn_menu` в `*.scene.rpy` | сам `*.scene.rpy` | `vn loc keys` | пишется **в источник** |

Проверить свежесть, ничего не записывая: `vn build --check` (свежесть считается **побайтовым
сравнением выходов**, а не хэшами входов — `manifest["inputs"]` пишется, но никогда не читается
обратно; см. [25-custom-engine.md](25-custom-engine.md)).

**Как именно сравниваются выходы.** Файл перезаписывается только при отличии байтов
(`compile.py:1193`), поэтому `vn build` на неизменённом дереве ничего не трогает. Исключение —
`version.gen.rpy`: при сверке свежести из него **вырезается** git-sha (`_stale_key`,
`compile.py:87-94`), иначе `--check` краснел бы после каждого коммита; semver при этом сравнивается
как есть — забытая пересборка после бампа `project.yaml: version` обязана ловиться.

### 3.1. 21 выход компилятора

Словарь `outputs` (`compile.py:1131-1157`) плюс по одному файлу на сцену. Факт на этом чекауте:
`find game/generated -name '*.gen.rpy' | wc -l` → **21**, `manifest.json` → `inputs: 36`,
`outputs: 21`.

| Выход | Эмиттер | Что несёт |
|---|---|---|
| `version.gen.rpy` | `_emit_version` (`:97`) | `config.version` = `<version>+<git-sha>` |
| `render.gen.rpy` | `_emit_render` (`:105`) | `config.image_cache_size_mb`, `config.automatic_oversampling`, `vn_build_max_oversampling` (ADR-0012) |
| `platform.gen.rpy` | `_emit_platform` (`:133`) | `config.steam_appid`, `VN_STEAM_DLC` (ADR-0014) |
| `state/defaults.gen.rpy` | `_emit_defaults` (`:155`) | создание named stores + все `default`, `vn_save_schema` |
| `state/snapshot.gen.rpy` | `_emit_snapshot` (`:435`) | `SNAPSHOT_VARS`, `SNAPSHOT_STORES` для миграций |
| `state/migrations.gen.rpy` | `_emit_migrations` (`:455`) | цепочка миграций со встроенными исходниками |
| `registry/images.gen.rpy` | `emit_images` (`images.py:281`) | `image`, `layeredimage` персонажей и шотов, `side`, `config.tag_layer` |
| `registry/audio.gen.rpy` | `_emit_audio` (`:399`) | `define audio.<id>` |
| `registry/characters.gen.rpy` | `emit_characters` (`scenes.py:447`) | `define <id> = Character(...)` |
| `registry/chapters.gen.rpy` | `emit_chapter_registry` (`scenes.py:413`) | `VN_CHAPTERS`, `VN_PACKS` |
| `registry/scenes.gen.rpy` | `emit_scene_registry` (`scenes.py:436`) | `VN_SCENES` |
| `registry/menus.gen.rpy` | `_emit_menus` (`:416`) | тексты пунктов меню для `vn_loc.choice_text` |
| `registry/achievements.gen.rpy` | `_emit_achievements` (`:179`) | `VN_ACHIEVEMENTS` |
| `registry/gallery.gen.rpy` | `_emit_gallery` (`:230`) | реестр галереи + `image_name_history` (ADR-0010/0012) |
| `registry/ui_frames.gen.rpy` | `_emit_ui_frames` (`:391`) | `define vn_frame_<id>` (ADR-0009) |
| `registry/overrides.gen.rpy` | `_emit_overrides` (`:510`) | `config.label_overrides.update(...)` + shim-метки |
| `screens/chapter_select.gen.rpy` | `emit_chapter_select` (`scenes.py:461`) | единственный экран выбора глав (C14); эмитится только при наличии глав |
| `scenes/chNN/<full_id>.gen.rpy` × 4 | `emit_scene` (`scenes.py:334`), путь — `compile.py:1044` | обвязка сцены + копия авторского `.rpy` с инжектированными `voice`-операторами |
| `manifest.json` | `compile_content` (`:1200-1210`) | `gen_manifest@1`: `inputs` (blake3) → `outputs` (blake3) |

Три выхода добавились после последнего пересчёта в старых редакциях хендбука: `render.gen.rpy`
и `platform.gen.rpy` (ADR-0012/0014) и четвёртая сцена `ch90_s010` из пака `ep_beach`.

### 3.2. Три границы «наш код / движок / генерат»

Новичок видит `game/framework/**` и считает всё это «нашим». Фактически границ три, и они
по-разному строгие.

| Граница | Где | Что разрешено | Кто стережёт |
|---|---|---|---|
| Движок | пиннованный SDK `renpy_sdk: "8.5.3"` (`project.yaml:5`) | читать исходники и `doc/*.html` как источник истины; **не править** | ревью; апгрейд — отдельным PR с прогоном `canary.yml` (G18) |
| Недокументированные API движка | **только** `00_core/engine_compat/000_compat.rpy` | любые допущения о внутренностях Ren'Py, каждое с контракт-тестом | `tools/vn/tests/test_engine_compat.py` + weekly canary (G18) |
| Платформа | **только** `00_core/035_platform.rpy` | `_renpysteam`, `steamapi`, capability-запросы | гард-тест `test_platform.py:183` — падает на любом другом файле `game/**/*.rpy` (ADR-0014) |
| Остальной framework | `00_core/**`, `20_ui/**`, `90_debug/**` | только документированные API движка; ни одного `chNN`-идентификатора в исполняемом коде ядра | `grep -rn "ch[0-9][0-9]" game/framework/ --include='*.rpy'` (норма: 2 комментария) |
| Генерат | `game/generated/**` | ничего: правки перезаписываются побайтово | `vn build --check` |

## 4. Слои `game/framework/`

Норма C17: числовые префиксы, никаких `framework/core|mechanics|ui/components|screens`.
Реальное дерево (`find game/framework -type f`):

| Слой | Состав | Роль слоя |
|---|---|---|
| `00_core/` | 13 `.rpy` (перечень — § 4.1) | Ядро: фасад `vn.*`, состояние и миграции, платформа, локализация, аудио, мост к компилятору, крэш, достижения, галерея, качество текстур |
| `00_core/engine_compat/` | `000_compat.rpy` | **Единственный** модуль, которому разрешено касаться недокументированных API движка (G18) |
| `10_systems/` | только `README.md` | Механики как плагины — **NOT IMPLEMENTED**, «появятся в фазе 1–2» |
| `20_ui/` | 4 файла верхнего уровня + 8 в `screens/`; **28 объявлений `screen`** (21 в `screens/`, 7 компонентов `vn_*` в `components.rpy`) | Компоненты и экраны (§ 4.2) |
| `90_debug/` | `010_dev.rpy`, `020_jump_menu.rpy`, `030_oversample.rpy` | Dev-инструменты; исключаются из релиза через `build.classify("game/framework/90_debug/**", None)` в `game/options.rpy:31` |

### 4.1. `00_core/` — по файлу

| Файл | Строк | За что отвечает |
|---|---|---|
| `001_boot.rpy` | 49 | `config.rollback_enabled`, `hard_rollback_limit`, `vn_log`, `config.save_json_callbacks` (три ключа сейв-json: `vn_save_schema`, `vn_version`, `vn_scene`) |
| `010_registry.rpy` | 18 | store `vn_registry` — доступ к данным реестров генерата; сами данные приходят на `init -100`/`500` |
| `020_state.rpy` | 107 | Инфраструктура состояния и раннер миграций; `label after_load` — единственное место, где миграции исполняются |
| `030_flow.rpy` | 252 | Фасад `vn.*` (`API_LEVEL = 1`), `vn.pack_registry`, store `vn_qa` (автопилот), метки `start` / `vn_scene_unavailable` / `vn_end_of_content` |
| `035_platform.rpy` | 89 | Platform Services (ADR-0014): **единственная** точка касания платформы; 8 публичных capability-функций + провайдеры ownership и ачивок |
| `040_localization.rpy` | 157 | Language Registry `vn_lang` + текстовые lookup'ы `vn_loc` (ADR-0005) |
| `045_audio.rpy` | 45 | Канал `ambient` (`mixer=music`, loop, tight), дакинг под голос через штатный `config.emphasize_audio_*`, резолвер `vn.voice_path` |
| `050_build_bridge.rpy` | 185 | Команда `vn_analyze`: разбор авторских `.scene.rpy` **парсером самого Ren'Py** (G24) |
| `060_build_info.rpy` | 45 | store `vn_build` — метаданные флейвора из `game/build_id.json`; **не** `default`, в сейв не идут |
| `070_crash.rpy` | 82 | `config.exception_handler` — **единственное** присваивание в проекте; breadcrumbs + crash-отчёт в savedir |
| `080_achievements.rpy` | 92 | store `vn_ach`: выдача по стабильным якорям из реестра, а не по тексту сцен |
| `090_gallery.rpy` | 141 | store `vn_gal`: два источника разблокировки (ADR-0010) + `image_name_history` |
| `095_quality.rpy` | 34 | Потолок качества текстур: `persistent.vn_quality_cap` ограничивает `config.automatic_oversampling` сверху (ADR-0012) |

### 4.2. `20_ui/` — по файлу

| Файл | Строк | За что отвечает |
|---|---|---|
| `components.rpy` | 385 | 7 компонентов `vn_*` (`vn_scrim`, `vn_panel`, `vn_modal_dialog`, `vn_button`, `vn_game_menu`, `vn_save_slot`, `vn_chapter_card`) + store `vn_ui`; все значения — из `gui.*` |
| `images.rpy` | 5 | Служебные образы framework. Ровно один: `vn_black`; он же перечислен в `FRAMEWORK_IMAGE_TAGS` (`images.py:59`) |
| `scale.rpy` | 57 | Масштаб интерфейса: `gui.ui_scale`, `gui.overscan_pad`, `vn.ui_scale_pref` / `vn.set_ui_scale` |
| `input.rpy` | 29 | **Единственное** место дополнений `config.pad_bindings` (controller-first, [39](39-platforms.md)) |
| `screens/core_screens.rpy` | 476 | `say`, `input`, `navigation`, `main_menu`, `save`, `load`, `file_menu`, `preferences`, `vn_pref_slider`, `language_picker`, `confirm`, `notify` |
| `screens/choice.rpy` | 88 | Кастомный `screen choice` (G8/C1): `vn_loc.choice_text(vn_menu, idx, caption)` + таймер автопилота |
| `screens/gallery.rpy` | 245 | `gallery`, `vn_gal_cell`, `gallery_viewer` — знают только store `vn_gal` (ADR-0010) |
| `screens/history.rpy` | 88 | Backlog реплик |
| `screens/quick_menu.rpy` | 60 | `vn_quick_menu` через `config.overlay_screens` |
| `screens/unavailable.rpy` | 33 | `vn_content_unavailable(reason)` — объяснение вместо безусловного выброса в меню |
| `screens/crash_screen.rpy` | 67 | `screen _exception` — движок подхватывает его сам |
| `screens/build_overlay.rpy` | 20 | `vn_build_overlay` — вотермарка build-id у флейворов с `watermark: true` (ADR-0006) |

Конвенция имён (`components.rpy:1`): наши экраны и компоненты — `^vn_[a-z0-9_]+$`; экраны, которые
ищет сам движок, сохраняют его имена (`say`, `choice`, `preferences`, `_exception`, …).
Автоматической проверки префикса нет — подробнее в [45 §5](45-architecture-rules.md).

**Правило «`00_core` не знает ни одной главы».** Проверено: `grep -rn "ch[0-9][0-9]"
game/framework/ --include='*.rpy'` даёт ровно два попадания, и оба — в комментариях
(`050_build_bridge.rpy:113` — пример `$ ch01.x = True`; `090_gallery.rpy:56` — пример имени
образа `cg ch01 rooftop_day`). **Ни одного `chNN`-идентификатора в исполняемом коде ядра нет.**
Это инвариант: как только ядру понадобится знать про конкретную главу, вы делаете что-то не так —
глава должна прийти через генерат (`VN_CHAPTERS`, `VN_SCENES`) или через декларацию.

**Обработчик исключений в проекте ровно один.** `config.exception_handler` — единственное поле,
и побеждает последнее присваивание, поэтому обработчик живёт только в `070_crash.rpy:82`
(init −950): он пишет `[vn] unhandled exception: <Тип: сообщение>` в `log.txt`, кладёт crash-отчёт
в savedir и возвращает `False`, оставляя показ экрана движку. В `001_boot.rpy` (init −999) второе
присваивание было мёртвым и удалено — на его месте стоит комментарий-предупреждение
(`001_boot.rpy:42-49`). Инвариант «присваивание ровно одно и именно там» стережёт
`tools/vn/tests/test_crash_handler.py`.

**Фасад `vn.*` — единственный API генерата (C15), и он собран из четырёх файлов.** Ядро создаёт
store `vn` на `init -999` (`030_flow.rpy:4`), остальные **дополняют** его на `init -998`:

| Член | Файл | Кто зовёт |
|---|---|---|
| `checkpoint`, `beat`, `chapter_done`, `check_scene_stack`, `unwind_call_stack`, `eval_when` | `030_flow.rpy:12,19,26,44,50,57` | обвязка сцен и shim-метки генерата |
| `pack_registry` (`installed`, `owned`, `set_ownership_provider`) | `030_flow.rpy:63-88` | `chapter_select`, `vn_gal`, `vn_ach` (G9/C14) |
| `voice_path(line_id)` | `045_audio.rpy:26` (`init -998`) | инжектированные компилятором `voice`-операторы (C5) |
| `quality_cap()`, `set_quality_cap(cap)` | `095_quality.rpy:22,26` (`init -998`) | экран настроек (ADR-0012) |
| `ui_scale_pref()`, `set_ui_scale(mode)` | `20_ui/scale.rpy:48,52` (`init -998`) | экран настроек |

`API_LEVEL = 1` (`030_flow.rpy:9`) — его проверяют манифесты DLC-паков; зеркало в тулинге —
`VN_API_LEVEL` (`compile.py:554`), равенство закрыто тестом `test_engine_compat.py:91`. Уровень
остался 1, хотя фасад расширен: **добавление** члена совместимо назад, бампа требуют удаление или
смена сигнатуры. Почему именно `-998`, а не `-999` — § 5, расхождение с C8.

`vn.beat()` существует, но компилятор его **никогда не эмитит**: якорь `beat` в достижениях и галерее
мёртв без ручного вызова из сцены.

## 5. init-шкала

Норма C8 (`ARCHITECTURE.md:147`) задаёт единую шкалу. [ADR-0003](../adr/0003-init-scale-engine-limit.md)
сдвинул её начало с −1000 на −999: реальный `renpy lint` на SDK 8.5.3 отвечает
«init priority (-1000) is not in the -999 to 999 range». **Верхняя граница 999 тоже жёсткая —
новых уровней выше не заводить.**

Фактическая раскладка (собрана `grep -rn "^init " game/framework/ game/generated/`):

| Приоритет | Что здесь живёт | Файлы |
|---|---|---|
| `-999` | Ядро: boot, `vn_registry`, `vn_state`, **создание** store `vn`, `vn_qa` | `001_boot.rpy:5`, `010_registry.rpy:4`, `020_state.rpy:12`, `030_flow.rpy:4,91` |
| `-998` | **Дополнения фасада `vn.*`**: `voice_path`, `quality_cap`/`set_quality_cap`, `ui_scale_pref`/`set_ui_scale` | `045_audio.rpy:24`, `095_quality.rpy:20`, `20_ui/scale.rpy:46` |
| `-995` | Реестр языков `vn_lang`, лукап строк `vn_loc` | `040_localization.rpy:15,137` |
| `-990` | store `vn_ui` (хелперы вёрстки: `reveal` и т.п.) | `20_ui/components.rpy:115` |
| `-985` | `vn_build` — метаданные флейвора | `060_build_info.rpy:10` |
| `-980` | Named stores генерата + `vn_ach` + `vn_gal` | `state/defaults.gen.rpy:12,15`, `080_achievements.rpy:12`, `090_gallery.rpy:20` |
| `-970` | `SNAPSHOT_VARS` / `SNAPSHOT_STORES` | `state/snapshot.gen.rpy:10` |
| `-960` | Цепочка миграций; store `vn_platform` (фасад платформы, ADR-0014) | `state/migrations.gen.rpy:7`, `035_platform.rpy:16` |
| `-950` | `engine_compat`, обработчик крэшей; **`offset = -950`** — `config.image_cache_size_mb`, `config.automatic_oversampling` | `engine_compat/000_compat.rpy:5`, `070_crash.rpy:10`, `render.gen.rpy:6` |
| `-900` | `config.emphasize_audio_*` и `register_channel("ambient")`; **`offset = -900`** — `config.version` | `045_audio.rpy:8`, `version.gen.rpy:6` |
| `-100` / `offset = -100` | Данные реестров: chapters, scenes, menus, achievements, gallery, `config.label_overrides` | `registry/{chapters,scenes,menus,achievements,gallery}.gen.rpy:6`, `registry/overrides.gen.rpy:8` |
| `-4` / `offset = -3` | Хелпер `gui.vn_ui_scale()`, затем токены `gui.ui_scale` и `gui.overscan_pad` — **до** `gui.rpy` (`offset = -2`), который на них умножает кегли | `20_ui/scale.rpy:15,35-42` |
| `offset = -2` | `gui.init(1920, 1080)` и все токены `gui.*` | `game/gui.rpy:6` |
| `0` (`init python`) / `offset = 0` | UI-компоненты и экраны, `layeredimage`/`image`, `Frame`-панели, дополнения `config.pad_bindings`, `build.classify`, dev-инструменты, `VN_STEAM_DLC` | `20_ui/**`, `20_ui/input.rpy:19`, `registry/images.gen.rpy:7`, `registry/ui_frames.gen.rpy:7`, `platform.gen.rpy` (без `offset`), `game/options.rpy:15,20`, `90_debug/{010_dev.rpy:7,020_jump_menu.rpy:5,030_oversample.rpy:16}` |
| `offset = 500` | Контентные `define`: аудио, персонажи | `registry/audio.gen.rpy:9`, `registry/characters.gen.rpy:7` |
| `999` | Пересборка рантайм-реестра языков; подключение платформенных провайдеров (ownership + ачивки); применение `persistent.vn_quality_cap` — реестры уже загружены, Steam уже инициализирован движком | `040_localization.rpy:131`, `035_platform.rpy:71`, `095_quality.rpy:12` |

**Расхождения с C8, зафиксированные честно (IMPLEMENTED с дрейфом):**

- **Уровень −998 в C8 не описан вовсе, но он обязателен.** Store `vn` создаётся на −999
  (`030_flow.rpy:4`); при равном приоритете Ren'Py упорядочивает файлы по пути, поэтому
  `045_audio.rpy` на −999 иногда исполнился бы **раньше** `030_flow.rpy` и упал бы на «no such
  store». Все три дополнения фасада поэтому сидят на −998 с одинаковым комментарием в коде.
  Правило для новых дополнений — там же и в [45 §10.1](45-architecture-rules.md).
- C8 отводит `build_info` уровень −900; реально `vn_build` сидит на −985, а слот −900 занят
  `version.gen.rpy` (`init offset = -900`) и аудио-конфигом (`045_audio.rpy:8`).
- Уровень −995 (`vn_lang`/`vn_loc`) в C8 не описан вовсе — он введён [ADR-0005](../adr/0005-language-packages-and-runtime-registry.md).
- **`render.gen.rpy` занял `offset = -950`**, то есть слот, который C8 отдаёт `engine_compat`.
  Конфликта нет: это `define config.*`, а не создание store. Не «чините» это.
- **`platform.gen.rpy` вообще без `init offset`**, то есть на 0: он состоит из двух `define`, ни один
  не требуется раньше (провайдеры подключаются на 999).
- «DLC-слоты 999» из C8 используются по назначению: на 999 вместе с пересборкой реестра
  языков живёт подключение платформенных провайдеров ([ADR-0014](../adr/0014-platform-services.md),
  `035_platform.rpy:71-89`) и применение потолка качества (`095_quality.rpy:12`, ADR-0012).
- `image`- и `layeredimage`-стейтменты имеют базовый приоритет 500 внутри движка, поэтому
  `registry/images.gen.rpy` намеренно ставит `init offset = 0` (`tools/vn/src/vn/content/images.py:289`) —
  не «исправляйте» это на 500.
- Уровни −60…−50 («темы» в C8) не заняты никем: тем как сущности не существует, токены живут в
  `gui.rpy` на `offset = -2`.

## 6. Нормы G1–G24 и C1–C24 — полный справочник

Раздел 0 `ARCHITECTURE.md` — контракт: код и процессы, ему противоречащие, не проходят ревью.
Изменение любого пункта — только новым ADR (`ARCHITECTURE.md:36`, `ADR-0001:15-18`).
Столбец «Статус» — фактическое состояние кода, не текст документа.

### 6.1. G1–G24 — нормативные решения (`ARCHITECTURE.md:51-99`)

| id | Стр. | Норма | Статус |
|---|---|---|---|
| **G1** | :53 | Один CLI `vn` (пакет `tools/vn/`), домены-подкоманды; других утилит не существует; CI-режим проверки без записи — флаг `--check` везде | IMPLEMENTED (20 доменов); `--check` есть не у всех команд |
| **G2** | :55 | Зоны каталогов: `content/` строго вне `game/`; `game/generated/` — единственная зона генерата (в .gitignore); `game/assets/` не в git; `assets_src/` — сырцы (в git только манифесты); `game/framework/` — рукописный код | IMPLEMENTED; ослаблено ADR-0004 (PNG временно в git) |
| **G3** | :57 | Диалоги живут в `scene.rpy`; сцена = `scene.yaml` (метаданные) + `scene.rpy` (диалоги/show/hide/menu); диалогов в YAML не существует | IMPLEMENTED |
| **G4** | :59 | `game/assets/`, `game/generated/`, `game/tl/` не коммитятся; обязательный `vn bootstrap` тянет их из remote cache/CI-артефактов последнего зелёного main; гарантия «clone → bootstrap → запуск ≤ 5 минут»; аварийный режим `vn build --use-artifact <sha>` | PARTIAL: зоны не в git — да; доставка из артефактов, CI-джоба ≤ 5 мин и `--use-artifact` — NOT IMPLEMENTED |
| **G5** | :61 | Состояние — named stores + миграции над dict-снапшотом; `default` генерируется из `vars.yaml`; в сейве только простые типы; единственный счётчик `vn_save_schema`; одна цепочка `migrate(state)` и в игре, и оффлайн; номера миграций резервируются реестром | PARTIAL: всё, кроме оффлайн-исполнения (`vn save migrate` — фаза 3) |
| **G6** | :63 | `.rpyc` генерата — релизный артефакт: подкладывается перед компиляцией следующего релиза; очистка `generated/` точечная по диффу манифеста; полный wipe только в release-CI | IMPLEMENTED; кэш разложен по линиям флейворов — `build/rpyc-cache/<флейвор>/<версия>/` (2026-08-18), прямой `vn package` пишет в линию `dev` |
| **G7** | :65 | Идентификаторы: id сцены `chNN_sNNN`, слуг только в имени файла; id неизменяемы навсегда; переименование = `renames.yaml` → `config.label_overrides` + физическая shim-метка; `config.missing_label` не существует; инвариант call-стека (глубина 0 на входе в сцену) | IMPLEMENTED и расширено на **пятый класс id** — ассеты (ADR-0012: `renames.assets` → `image_name_history` галереи). Защита «выпущенный id исчез» инертна: `id_registry.json` пуст, потому что `stamp_id_registry` пишет только главы со `status: release`. Инвариант call-стека `vn.check_scene_stack()` нарушение **только логирует**, не чинит |
| **G8** | :67 | Локализация поверх `scene.rpy`: `vn loc keys` дописывает id-клаузы парсером Ren'Py; у menu-пунктов клаузы `id` нет — перевод выборов через lookup по choice-id; обмен — gettext PO с msgctxt; ledger шардирован по главам; `game/tl/` генерируется | IMPLEMENTED (включая голос: озвучка привязана к тем же say-id, `config.auto_voice` не используется — см. C5) |
| **G9** | :69 | DLC: скрипты всех паков грузятся всегда; владение — логический гейт после инициализации Steam через `pack_registry.owned()`; манифест пака несёт `api_level` фасада `vn.*`; каждый релиз ядра переиздаёт все DLC-депоты | PARTIAL: `api_level` и `owned()` IMPLEMENTED; провайдер владения **подключён** [ADR-0014](../adr/0014-platform-services.md) (`035_platform.rpy:75`, `steam_dlc_appid` в манифесте, fail-open) — но только при живом Steam, вне него `owned()` = True. Переиздание всех DLC-депотов на релиз и депот пака как товара — NOT IMPLEMENTED ([39](39-platforms.md), [30](30-packs-and-dlc.md)) |
| **G10** | :73 | Моды: инжекты только на реестр стабильных якорей; подпись отделена от проверки совместимости; Mod SDK — фаза 3, но формат паков мод-совместим с первого дня | NOT IMPLEMENTED: `content/anchors.yaml` пуст и никем не читается |
| **G11** | :75 | layeredimage-эмиттер: `attribute X default Null()`, гейтинг `if_any`/`if_all`, у каждого attribute явный displayable; golden-тесты через `renpy compile`+lint; тонировка через генерируемый `config.tag_layer` + `camera sprites` | PARTIAL: эмиттер и `config.tag_layer` есть; golden-тестов нет (ноль тестов, запускающих SDK) |
| **G12** | :77 | Live2D/Spine: один тег = одно определение image; prebaked fallback обязателен для 100 % анимированных персонажей; проприетарные рантаймы вендорятся; экспортированные секвенции — самостоятельные сырцы в S3 | NOT IMPLEMENTED (фаза 3); зоны `assets_src/{live2d,spine_export}/` заведены пустыми |
| **G13** | :79 | Кэш ассетов: ключ = хэш содержимого (PSD — послойно) + версия инструмента трансформации; draft-энкод локально, полное качество в CI; warm-up remote cache перед бампом тулчейна; бюджет цикла художника P95 < 15 с | PARTIAL: ключ и профили `draft/full` есть; remote cache и замер P95 — нет |
| **G14** | :81 | Локи на сырцы обязательные: `vn assets push` без валидного лока отказывает; `pull --edit` берёт лок; бот-нотификации; TTL с эскалацией | PARTIAL: лок обязателен на push; TTL, эскалация, атомарность и нотификации — NOT IMPLEMENTED |
| **G15** | :83 | Строгость валидации по статусу главы: `draft` → граф-проверки warnings; orphan-ассеты — error только в release-гейте; scope-check заменён CODEOWNERS-approve; smoke на MR — только затронутые главы (< 10 мин), полный — nightly | PARTIAL: градация по статусу IMPLEMENTED (`lint.py:209,231,270`); `smoke --affected` не существует |
| **G16** | :85 | Каждый YAML начинается с `schema: <name>@<int>` без исключений; реестр схем — `tools/schemas/`; `vn migrate` покрывает все типы деклараций | PARTIAL: правило и реестр IMPLEMENTED (39 схем); дыра `assets_manifest@1` закрыта — схема заведена, и манифест `.vncache/assets-manifest.json` валидируется ею при записи (`assets/pipeline.py:441-450`). Остаётся: `vn migrate` — заглушка фазы 2 |
| **G17** | :87 | Версии: `project.yaml` несёт `version` (semver, новая глава = minor), `save_schema` (int), `min_tools`; версии tools — lockfile, откат = git revert | PARTIAL: `project.yaml` — да; `tools/vn.lock` теперь **читается** — во всех 8 джобах установки тулчейна перед editable-установкой идёт `pip install --quiet -r tools/vn.lock`, свойство стережёт `tools/vn/tests/test_ci_config.py`. Остаётся: в локе 18 пакетов, транзитивные зависимости (`pygments`) не закреплены |
| **G18** | :89 | Эволюция движка: недокументированные API — только в `framework/00_core/engine_compat/` с контракт-тестами; weekly canary CI на свежем Ren'Py; апгрейд SDK минимум раз в год как плановая работа | IMPLEMENTED: `engine_compat/000_compat.rpy`, `tests/test_engine_compat.py`, `.github/workflows/canary.yml` |
| **G19** | :91 | Перф-бюджеты в CI: cold start, baseline RSS (слабое железо + Android-эмулятор), суммарный размер `.rpyc`, размер реальных `.aab`/`.apk` по каналам; утверждения о масштабе — измерением, а не рассуждением | PARTIAL: `cold_start_s` (в `vn test smoke`), размеры каталогов и **корпус масштаба** `vn test corpus` (ночная джоба, конвейер измерен до 20 000 сцен — [32](32-performance-and-scalability.md) §7.5); RSS движка, бюджет `.rpyc` и размер фактического `.aab`/`.apk` — NOT IMPLEMENTED (в CI считается только арифметика `vn release android preflight`) |
| **G20** | :93 | Скоуп по фазам (1 — компилятор/ассеты/валидаторы/bootstrap/CI; 2 — локализация/миграции/QA/релиз; 3 — Live2D/DLC/моды/скриншот-тесты/телеметрия); два владельца на инструмент; runbook аварий; онбординг tools-инженера | PARTIAL: runbook и онбординг есть; все владельцы в `CODEOWNERS` — плейсхолдеры |
| **G21** | :95 | Хранилище сырцов адресуется логическими id (`storage: default, key: …` в манифестах); маппинг на физические endpoint'ы — один конфиг | IMPLEMENTED (`.vnstorage.yaml`), но ни разу не использовано — `~/vn-assets-store` не существует |
| **G22** | :97 | Онбординг по ролям: однокомандный инсталлер + `vn doctor`; метрика — сценарист от чистой машины до правки в игре < 1 дня | PARTIAL: `vn doctor` есть; однокомандного ролевого инсталлера нет (`pip install -e tools/vn` вручную) |
| **G23** | :99 | QA/headless: headless у Ren'Py нет — xvfb; savecheck = оффлайн-структурная проверка + полный прогон (процесс-на-слот); автопилот через QA-label с fixed seed | IMPLEMENTED: `vn test smoke` (in-process), `vn save check` + `vn save corpus` на 2 фикстурах, одна из которых на старой схеме — цепочка миграций проигрывается в реальной игре |
| **G24** | :101 | Content Compiler: разбор `.rpy` только парсером Ren'Py из пиннованного SDK; архитектура frontend/IR/backends с плагинными стадиями; e2e golden-тесты; поддержка схем N и N−1 | PARTIAL: парсер SDK — IMPLEMENTED (`tools/vn/src/vn/content/analyze.py:37-70` + `050_build_bridge.rpy:98-144`); плагинных стадий, golden-тестов и поддержки N−1 нет |

### 6.2. C1–C24 — интеграционный канон (`ARCHITECTURE.md:103-201`)

| id | Стр. | Канон | Статус |
|---|---|---|---|
| **C1** | :111 | Идентичность пунктов меню: маркер `vn_menu` (без `_`, попадает в сейв), формат id меню `m\d{3}`, текст — `vn_loc.choice_text(vn_menu, idx, caption)`, QA-якорь `vn_qa.choice(...)` первым стейтментом ветки; «стабильных label-имён меню» и `vn_qa.menu_enter` НЕ существует | PARTIAL: `vn_menu` и `choice_text` IMPLEMENTED; `vn_qa.choice()` — `pass`-заглушка (`030_flow.rpy:98-101`), компилятор её не эмитит |
| **C2** | :118 | Контракт авторского `scene.rpy`: автор пишет `label <full_id>__body:` и ветки `<full_id>__<branch>:`; обвязку `label <full_id>:` эмитит компилятор; межсценовые переходы — ТОЛЬКО `return "<exit_id>"`, прямые `jump`/`call` наружу запрещены линтером | IMPLEMENTED (`tools/vn/src/vn/content/scenes.py:18,81-104`) |
| **C3** | :125 | Путь генерата сцены — `game/generated/scenes/chNN/<full_id>.gen.rpy`, имя только по id (без слуга); каталога `generated/content/` не существует | IMPLEMENTED (`compile.py:766`) |
| **C4** | :128 | Единая схема scene/chapter: `schema: scene@1`/`chapter@1` без префикса `vn/`; `id: sNNN` короткий (полный выводится из пути), блок `vars: {reads, writes}` (не `flags:`); exits — map с `when:`/`to:`; заголовки только `title_key:` | IMPLEMENTED; при этом `scene.yaml:id` и `title_key` компилятором **не читаются** (id — из имени файла) |
| **C5** | :135 | Голосовой контур: манифесты `content/chapters/chNN/voice/<lang>.voice.yaml`, оператор `voice vn.voice_path("<line_id>")`, домен `vn voice manifest\|import\|tts\|validate`; `vn loc report --domain voice` не существует | IMPLEMENTED **целиком** (с 2026-08-18 заглушек в домене нет): схема `voice@1`, инжекция voice-операторов компилятором, `vn.voice_path` с деградацией язык→оригинал→no-op (`045_audio.rpy`), транскод `voice_opus`, TTS-черновики `vn voice tts`, гейт в `vn release validate` — см. [23-audio.md](23-audio.md) §8, §8.1. Расхождение с нормой осталось одно: обещанный примером C5 пер-персонажный TTS-профиль (`voice.tts_draft` в `character.yaml`) схемой `character@1` не предусмотрен — профиль живёт во флагах команды |
| **C6** | :141 | Состав спрайтов объявляется единым `character.yaml` с блоком `matrix:` (poses/outfits/emotions/required/forbidden); файла `sprites.yaml` НЕ существует | IMPLEMENTED (`tools/vn/src/vn/content/images.py:101-237`) |
| **C7** | :144 | Раскладка слоёв: `game/assets/spr/<char>/<pose>/base@2.webp`, `<pose>/{outfits,faces,overlays}/*@2.webp`, `side/<emotion>@2.webp`; в генерате пути с префиксом зоны `"assets/spr/…"` | IMPLEMENTED целиком: `base`/`outfits`/`faces`, `overlays` (эмитятся **независимыми** атрибутами, `images.py:493-507`), `side/` (`pipeline.py:288-306` → `images.py:512-526`, `image side <char> …`). **Но** ADR-0012 изменил вид пути: ссылка идёт на референсное, безсуффиксное имя (`assets/spr/mira/a/base.webp`), `@2` лежит рядом и подбирается движком |
| **C8** | :149 | Единая init-шкала: ядро −999, named stores −980, engine_compat −950, build_info −900, реестры −100, темы −60…−50, styles/screens 0, контентные define 500, DLC-слоты 999 (правка ADR-0003) | IMPLEMENTED с дрейфом — см. § 5 |
| **C9** | :152 | Persistent — плоская модель с префиксом `persistent.vn_*` (никакого dict-корня `persistent.vn`); разблокировка галереи — штатный `Gallery` + `persistent._seen_images` | Префикс `vn_*` IMPLEMENTED и проверяется компилятором; механизм галереи ЗАМЕНЁН [ADR-0010](../adr/0010-gallery-extras.md) на два источника |
| **C10** | :155 | DLC-контент живёт в `packs/<pack_id>/` в корне репозитория (зеркалит `content/`); поля `pack:` в chapter.yaml НЕ существует — принадлежность по расположению; `content/` = core | IMPLEMENTED (`compile.py:505-513,541`) |
| **C11** | :158 | Имена схем без префикса `vn/`, версии `@1`; манифест сырца — единый `asset_src@1`; vars-файлы — единый `vars@1` (`store:` + `vars:`); хэш всего тулинга — blake3 | IMPLEMENTED |
| **C12** | :163 | `renames.yaml`: `schema: renames@1`, секции `scenes:`, `deleted_scenes:` (`{fallback:, since:}`), `labels:`, `vars:`; генерат — `registry/overrides.gen.rpy` с `init -100 python: config.label_overrides.update({...})` + shim-метки | IMPLEMENTED (`_emit_overrides`, `compile.py:510`) и **расширено пятой секцией `assets:`** (ADR-0012, `renames@1.schema.json`): переименование ассета иначе стирало бы игроку открытый CG. Сегодня все пять секций пусты. Помимо переименований эмитятся shim-метки для выпущенных id, отсутствующих в **этой** сборке (`compile.py:534-546`, причина `missing_content`) |
| **C13** | :166 | Финальный перечень доменов CLI (`bootstrap\|doctor\|dev\|build\|play\|package`, `assets/content/scene/chapter/char/loc/voice/save/test/release/pack`, `shell`, `migrate`); `--check` везде (`--verify` не существует); `vn dev` — комбинированный цикл | IMPLEMENTED по составу доменов; `char`, `shell`, `migrate` — заглушки; в `voice` заглушка только `tts` |
| **C14** | :171 | Владение паками — единственное API `vn.pack_registry.owned(pack_id)`; экран выбора глав один — `screen chapter_select()` в `generated/screens/chapter_select.gen.rpy` по define `VN_CHAPTERS` | IMPLEMENTED по форме; `owned()` всегда True — провайдера нет |
| **C15** | :175 | Фасад рантайма: `vn.checkpoint()`, `vn.beat()`, `vn.unwind_call_stack()`, `vn.check_scene_stack()`, глубина — `renpy.call_stack_depth()`; голых глобалов `vn_checkpoint`/`vn_beat` не существует | IMPLEMENTED; фасад с 2026-08 расширен пятью членами и объектом `pack_registry` из трёх других файлов на `init -998` (§ 4). `vn.beat()` существует, но компилятор его **никогда не эмитит** — якорь `beat` мёртв без ручного вызова. `API_LEVEL` остался 1: добавление члена совместимо назад |
| **C16** | :178 | Реестр id — единственный путь `content/registry/id_registry.json` (append-only) | IMPLEMENTED; схема `id_registry@1` знает **пять** классов (`chapters`, `scenes`, `characters`, `vars` — обязательны; `assets` — опционален, ADR-0012). В файле четыре массива, все пусты; ключа `assets` в нём нет, линтер читает его через `.get("assets", [])` |
| **C17** | :181 | Раскладка framework с числовыми префиксами: `00_core/` (+ `engine_compat/`), `10_systems/<mechanic_id>/`, `20_ui/` (`20_ui/screens/choice.rpy`), `90_debug/` | IMPLEMENTED; `10_systems/` содержит только README |
| **C18** | :184 | Аудио по логическим id: `define audio.<id> = "assets/audio/bgm/<file>.ogg"`, в сценах `play music <id>`; физические пути только `assets/audio/{bgm,amb,sfx}/…`; форматы `.ogg` (bgm/amb/sfx), `.opus` (voice); каталога `audio/music/` нет | PARTIAL: реестр `registry/audio.gen.rpy` эмитится (`loop_start` — префиксом `"<loop N>file"`, `volume` — клаузой play-оператора сцены), ветка `copy_audio` жива, канал `ambient` и дакинг под голос — в `045_audio.rpy`, kind трека сверяется с каналом при компиляции. Остаётся: ни одного `.ogg` в репозитории (`tracks: {}` во всех трёх `content/audio/*.yaml`), поле `loop` не читается, loudnorm для bgm/amb/sfx нет |
| **C19** | :187 | Служебные зоны: локальный кэш `.vncache/` (одно написание); два манифеста с разными ролями — `game/generated/manifest.json` (Content Compiler) и `.vncache/build-graph.json` (DAG оркестратора); хэш — blake3 | PARTIAL: `.vncache/` и `manifest.json` IMPLEMENTED; `.vncache/build-graph.json` — NOT IMPLEMENTED (оркестратора нет) |
| **C20** | :190 | Сырцы Live2D/Spine — отдельные ветки `assets_src/live2d/characters/<key>/` и `assets_src/spine_export/characters/<key>/`, НЕ внутри `assets_src/psd/` | Зоны заведены, содержимого нет — NOT IMPLEMENTED по существу |
| **C21** | :193 | Regex-константы: ключ персонажа `^[a-z][a-z0-9_]{1,23}$`; переменная `^(g\|ch\d{2}\|mech_[a-z0-9_]+\|dlc_[a-z0-9_]+)\.[a-z][a-z0-9_]*$` | IMPLEMENTED (`vars@1.schema.json`, `character@1.schema.json`) |
| **C22** | :196 | `vn bootstrap` доставляет `game/assets/` + `game/generated/` + `game/tl/` последнего зелёного main | NOT IMPLEMENTED — команда делает локальную пересборку, о чём честно пишет её docstring (`cli.py:206-207`) |
| **C23** | :199 | `vn play --scene` реализуется env-вариантом: `game/generated/qa/dev_boot.gen.rpy` читает `VN_SCENE`/`VN_PRESET`; release-CI проверяет отсутствие файла | NOT IMPLEMENTED — ни файла, ни опции `--scene` у `vn play` |
| **C24** | :202 | Галерея: разблокировка штатным `Gallery` + `persistent._seen_images`; генерат `game/generated/screens/gallery.gen.rpy`; пути `assets/cg/…`, `assets/bg/…` — сегмента `images/` не существует | ЗАМЕНЁН ADR-0010: два источника разблокировки, экран рукописный (`20_ui/screens/gallery.rpy`), генерат — `registry/gallery.gen.rpy`. Норма «сегмента `images/` не существует» — IMPLEMENTED |

## 7. Что в ARCHITECTURE.md есть, а в коде НЕТ

Список отсортирован по риску «прочитать документ и поверить». План закрытия — [37-roadmap.md](37-roadmap.md).

| Обещание | Где обещано | Реальность |
|---|---|---|
| `vn build --use-artifact <sha>` — аварийный запуск на артефактном генерате | G4 (`:59`), § 8.5 (`:4120`), `docs/runbooks/pipeline-broken-at-night.md:11`; **14 упоминаний в документе** | **NOT IMPLEMENTED.** У `vn build` есть только `--check` и `--profile` (`cli.py:84-88`). Во всём `tools/`, `ci/`, `.github/` строка `use-artifact` встречается **один раз** — в title схемы `tools/schemas/gen_manifest@1.schema.json:4`. Аварийный путь исполняется только вручную: скачать артефакт CI и распаковать в `game/generated/` |
| `vn validate --schemas` / `--budgets` | § 7 | **NOT IMPLEMENTED.** Группы `vn validate` не существует вовсе |
| `vn bootstrap` доставляет три зоны из CI-артефактов; CI-джоба «clone → ≤ 5 мин» | G4, C22, § 7.4, § 8.2 | **NOT IMPLEMENTED.** Команда пересобирает локально; такой джобы в `.github/workflows/` нет |
| `content/flags.yaml` — флаг как условие **компиляции** («выключенный контент не существует в release-сборке») | `:696` | **NOT IMPLEMENTED.** Файл обязан существовать (`lint.py:40`), но `flags` не читает ни компилятор, ни рантайм |
| `content/anchors.yaml` — реестр инжект-якорей для модов | G10, `:3255,3317` | **NOT IMPLEMENTED.** То же самое: существование проверяется, содержимое не читается |
| `vn_qa.choice(scene_id, vn_menu, idx)` первым стейтментом каждой ветки | C1, `:544-551,572` | **NOT IMPLEMENTED.** `emit_scene` копирует авторский исходник дословно и не переписывает menu-блоки; сама функция — `pass` |
| `game/generated/qa/dev_boot.gen.rpy` и `vn play --scene <id>` | C23 | **NOT IMPLEMENTED** |
| `.vncache/build-graph.json` — граф оркестратора сборки | C19 | **NOT IMPLEMENTED** |
| `game/assets/registry.json` | `:1085` | **NOT IMPLEMENTED** |
| Мини-язык условий `when:`: валидация через `ast.parse(expr, mode="eval")` с whitelist узлов, вставка в генерат **дословно** как обычное `if`, «в рантайме нет ни eval-обёртки, ни интерпретатора» | § 3.11 (`:1853-1860`) | **NOT IMPLEMENTED.** `ast.parse` во всём `tools/vn/src/vn/` встречается ноль раз (единственный `literal_eval` — `scenes.py:61`, он про `return`-значение). Схема требует от `when` только `minLength: 1` (`scene@1.schema.json:19`), а генерат заворачивает выражение именно в eval-обёртку: `if _return == "x" and vn.eval_when('…')` → `renpy.python.py_eval` (`scenes.py:383-384`, `030_flow.rpy:57-59`). Опечатка в имени переменной всплывёт `NameError` у игрока |
| Golden-тесты «декларации → байт-в-байт `.rpy`» через `renpy compile`+lint | G11, G24, § 9.4 | **NOT IMPLEMENTED.** В `tools/vn/tests/` ноль совпадений на «golden» и ни один тест не запускает SDK |
| Поддержка схем N и N−1, `vn migrate` переписывает контент | G16, G24, § 9.4 | **NOT IMPLEMENTED** — `vn migrate` заглушка фазы 2 |
| `docs/adr/engine-assumptions.md` — живой список движковых допущений | § 9.1 (`:4137`) | **NOT IMPLEMENTED.** Файла нет; допущения рассыпаны по ADR-0003 (предел −999) и ADR-0005 (мёртвый `config.change_language_callbacks` в Ren'Py 8.5) |
| `.rpa`-архивы / `build.archive` | § 2.4 (`:943`) | **Больше не обещано**: §2.4 фиксирует россыпь как норму (Steam дельта-патчит отдельные файлы); тематические `.rpa` — только опция mobile-поставки фазы 3, их появление в desktop-дистрибутиве — осознанное решение с ADR. В `game/` — ноль вхождений `build.archive`, и это соответствует норме |
| Перф-бюджеты RSS, суммарный `.rpyc`, `.aab`/`.apk` | G19 | **NOT IMPLEMENTED** — только `cold_start_s` и размеры каталогов |
| Live2D/Spine, моды, телеметрия, скриншот-тесты | G12, G10, § 8.4 | **NOT IMPLEMENTED** — фазы 2–3 (голосовой контур C5 из этого списка выбыл: реализован целиком, включая `vn voice tts`) |

Обратная асимметрия — **реализовано, но в `ARCHITECTURE.md` не описано вообще**
(проверено case-insensitive grep'ом: 0 вхождений DAZ / ComfyUI / Virt-a-Mate / Sims / `ui_panel` /
`panels.yaml` / `vn_frame`): весь внешний 3D-конвейер ([ADR-0006](../adr/0006-daz-comfyui-video-pipeline.md),
[ADR-0007](../adr/0007-sims4-optional-source.md)), генерируемые UI-панели
([ADR-0009](../adr/0009-generated-ui-panels.md)), достижения, `vn pack validate`,
`vn assets video inspect`, `vn assets provenance workflow` и все четыре GitHub-workflow.
Для них единственный нормативный источник — ADR и этот хендбук.

## 8. Id неизменяемы навсегда

Это самая дорогая для нарушения норма проекта (G7, C16), потому что statement-имена в `.rpyc` —
единственная опора позиционной save-совместимости Ren'Py.

**Что такое id.** Id сцены — `chNN_sNNN`, выводится **из имени файла**, а не из поля `id:`
в YAML (`compile.py:31-32,752`). Слуг живёт только в имени файла и в имени папки:
`content/chapters/ch01_awakening/scenes/s020_school_gate.scene.yaml` → id `ch01_s020` →
генерат `game/generated/scenes/ch01/ch01_s020.gen.rpy` → метка `label ch01_s020:`.
Слуга в генерате нет намеренно (C3).

**Как переименовать сцену.** `git mv` — неправильный ответ. Правильный:

1. Создать сцену с **новым** id (новый номер), перенести содержимое.
2. Записать соответствие в `content/renames.yaml` (`schema: renames@1`). Секций **пять**: `scenes:`,
   `deleted_scenes:` с `{fallback:, since:}`, `labels:`, `vars:` и `assets:` (ADR-0012).
3. `vn build` — компилятор сгенерирует `game/generated/registry/overrides.gen.rpy`:
   `init -100 python: config.label_overrides.update({...})` **плюс** физические shim-метки
   (`compile.py:524-530`). Именно `update`, а не `define`: паки должны иметь возможность
   дополнять карту (C12).
4. Старый id **никогда** не переиспользуется под другой смысл.

Сегодня `content/renames.yaml` пуст (все пять секций `{}`), а сгенерированный
`overrides.gen.rpy` содержит `config.label_overrides.update({})` и комментарий
«Переименований нет — shim-метки не требуются».

**Что именно теряется при смене какого id** — четыре разных последствия, а не одно:

| Id | Что теряется |
|---|---|
| say-id | переводы в `loc/po/**` и `game/tl/**`; привязка записанного дубля озвучки (`voice@1` ссылается на тот же say-id) |
| id сцены | метка сцены, from-имя `_call_<full_id>__body` в сейвах, якоря галереи и достижений, запись в `id_registry` |
| логический id ассета | `persistent._seen_images` — уже открытые игроку CG в галерее |
| id элемента галереи | ключ в `persistent.vn_gallery_unlocked` |

Сводная таблица и порядок для каждого случая — [45 §12.1](45-architecture-rules.md).

**`content/registry/id_registry.json`** (`schema: id_registry@1`, append-only) — вторая половина
защиты: реестр выпущенных id. `stamp_id_registry` (`release.py:126`) записывает туда главы
только со `status: "release"`, а линтер (`lint.py:383-420`) падает, если выпущенный id исчез из
дерева: отдельно по сценам (с исключением через `renames.scenes`/`deleted_scenes`), главам,
персонажам, переменным (через `renames.vars`) и ассетам (через `renames.assets`).
**Сегодня механизм инертен:** единственная глава `ch01_awakening` имеет `status: draft`,
поэтому все массивы реестра пусты и защите нечего охранять. Она включится сама при первой
главе со статусом `release`. Отдельная ловушка: `stamp_id_registry` смотрит только
`content/chapters/` — сцены из `packs/*/chapters/` в реестр не попадут никогда, значит и shim-метки
`missing_content` для них не сгенерируются, хотя механизм делался ровно ради этого случая.

`config.missing_label` не используется намеренно (G7): вместо динамического перехвата
отсутствующей метки генерируются физические shim-метки для всех отсутствующих id.

## Как изменить / Как расширить

| Задача | Порядок действий |
|---|---|
| Завести новую зону каталога | 1) ADR по `docs/adr/template.md` с полем «Затрагивает нормы: G2/...»; 2) обновить `REQUIRED_DIRS`/`FORBIDDEN_PATHS` в `tools/vn/src/vn/content/lint.py:21-53`; 3) обновить `docs/conventions/folder-layout.md`; 4) добавить строку в `CODEOWNERS`; 5) при необходимости — `.gitignore` и `.gitattributes` (бинари в `assets_src/` обязаны быть в LFS, иначе линт красный) |
| Добавить уровень init | Нельзя выйти за `-999..999`. Согласовать с C8 и ADR-0003, вписать в § 5 этого файла и в заголовок затронутого файла `game/framework/` |
| Дополнить фасад `vn.*` | Новый блок `init -998 python in vn:` (не −999!) в профильном файле `00_core/`; образцы — `045_audio.rpy:24`, `095_quality.rpy:20`. Удаление члена или смена сигнатуры — бамп `API_LEVEL` (`030_flow.rpy:9`) **и** `VN_API_LEVEL` (`compile.py:554`) |
| Добавить новый вид генерата | Эмиттер в `tools/vn/src/vn/content/compile.py`, регистрация выхода в словаре `outputs` (`compile.py:1131`), схема входа в `tools/schemas/<name>@1.schema.json`, тест в `tools/vn/tests/`. См. [25-custom-engine.md](25-custom-engine.md) |
| Изменить норму G/C | Только новым ADR со ссылкой на заменяемую норму. Правка `ARCHITECTURE.md` без ADR не проходит ревью (`ARCHITECTURE.md:36`) |
| Добавить слой в `game/framework/` | Только по схеме C17 — числовой префикс каталога; `10_systems/<mechanic_id>/` для механик |
| Переименовать сцену/главу/переменную | См. § 8 — через `content/renames.yaml`, никогда `git mv` |

## Чего НЕ делать

Полный свод запретов с последствиями и ловцами — [45-architecture-rules.md §15](45-architecture-rules.md).
Здесь только то, что относится к архитектуре зон и init-шкале.

- **Не правьте файлы с шапкой `AUTO-GENERATED by vn content compile`** — их **21** в
  `game/generated/` (перечень — § 3.1), следующая сборка сотрёт правку без предупреждения, а
  `vn build --check` до тех пор помечает файл `устарело:` и валит сборку.
- **Не делайте `git mv` сцене или главе.** Statement-имена в `.rpyc` — опора save-совместимости;
  переименование ломает сейвы игроков навсегда. Только `content/renames.yaml`.
- **Не ставьте `init -1000`** — движок отвергает: «init priority (-1000) is not in the -999 to 999
  range» (ADR-0003). И не заводите уровни выше 999.
- **Не расширяйте store `vn` на `init -999`** — только `-998`: при равном приоритете порядок файлов
  решает путь, и вы получите невоспроизводимый «no such store» (§ 5).
- **Не «исправляйте» `init offset = 0` в `registry/images.gen.rpy` на 500** — `image`-стейтменты
  и так имеют базовый приоритет 500. То же про `offset = -950` у `render.gen.rpy`: это `define
  config.*`, а не создание store, конфликта с `engine_compat` нет.
- **Не переставляйте приоритеты в `20_ui/scale.rpy` и `game/gui.rpy`** — связка «−4 → offset −3 →
  offset −2» единственная, и её поломка молча даёт масштаб интерфейса 1.0 без единой ошибки.
- **Не заводите второй CLI** (G1). Любая новая утилита — подкоманда `vn`, иначе она не пройдёт ревью.
- **Не полагайтесь на `manifest["inputs"]`** для инкрементальной пересборки: он пишется, но
  никогда не читается, а сканы `game/assets/{cg,mov,spr}` вообще не попадают во входы.
- **Не считайте `docs/conventions/folder-layout.md` полным**: в нём нет `content/gallery/`,
  `content/achievements/`, `content/ui/`, `content/licenses.yaml`, `game/fonts/`,
  `docs/licenses/`, `.github/` — при этом документ объявлен эталоном для `vn content lint --layout`.
- **Не добавляйте ключ в YAML, не добавив его в схему**: у схем стоит
  `additionalProperties: false` (ADR-0002), линт свалится.

## Проверка

```bash
vn content lint                        # 33 диагностики + сверка раскладки каталогов
vn build --check                       # CI-режим: свежесть генерата, ассетов, бюджеты (два класса)
vn content graph                       # mermaid-граф сцен (только content/, паки не видны)
cd tools/vn && .venv/bin/python -m pytest -q   # 400 passed; про cwd — 27-testing.md §2
find game/generated -name '*.gen.rpy' | wc -l              # ожидание: 21
grep -rn "^init " game/framework/ game/generated/ | sort   # ручная сверка init-шкалы с § 5
grep -rn "ch[0-9][0-9]" game/framework/ --include='*.rpy'  # должны остаться только 2 комментария
grep -rln "_renpysteam\|steamapi" game/ --include='*.rpy'  # только 035_platform.rpy (§ 3.2)
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `docs/ARCHITECTURE.md` § 0 (строки 36–203), [45-architecture-rules.md](45-architecture-rules.md), `docs/conventions/folder-layout.md`, `docs/conventions/naming.md`, `tools/vn/src/vn/content/lint.py`, `CODEOWNERS` |
| **Не трогать** | `game/generated/**` (21 `*.gen.rpy` + `manifest.json`), `game/assets/**`, `game/tl/**`, `.vncache/**`, `build/**` — производные зоны; `ci/fixtures/rpyc-line/**` руками; `docs/ARCHITECTURE.md` — только через ADR |
| **Зависимости** | Правка `content/**` → перегенерация `game/generated/**` → перекомпиляция `.rpyc` → потенциальный слом сейвов; правка `assets_src/**` → `game/assets/**` → `registry/images.gen.rpy` + бюджет памяти сцены; правка `content/ui/panels.yaml` → `game/assets/ui/*.webp` + `registry/ui_frames.gen.rpy`; правка `loc/po/**` → `game/tl/**`; правка `project.yaml: render.*` → `render.gen.rpy` + инвалидация ветки кэша; правка `project.yaml: platform.steam` → `platform.gen.rpy` |
| **Валидация** | `vn content lint && vn build && (cd tools/vn && .venv/bin/python -m pytest -q)` |
| **Частые ошибки** | 1) считать текст `ARCHITECTURE.md` описанием кода — сверяйтесь с § 6 и § 7; 2) переименовывать сцену через `git mv` вместо `renames.yaml`; 3) писать в `game/generated/`; 4) добавлять YAML-ключ без правки схемы (`additionalProperties: false`); 5) вводить `chNN`-идентификатор в `game/framework/00_core/` — ядро глав не знает; 6) ожидать, что `vn content graph` покажет главы из `packs/` — он сканирует только `content/chapters/`; 7) расширять фасад `vn.*` на `init -999` вместо `-998`; 8) доверять номеру строки в цитате `tools/**` — они плывут после каждой вставки блока, ищите по имени символа |
