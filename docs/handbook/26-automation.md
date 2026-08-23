# 26. Автоматизация

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — всё, что происходит **после** появления пикселей на диске, автоматизировано целиком и одной командой (`vn build` → `vn release build`). Всё, что происходит **до** — рендер в DAZ, генерация в ComfyUI, приёмка кадра — на 100% ручные GUI-шаги: в репозитории ноль `.dsa`, ноль ComfyUI-workflow, ноль HTTP-клиентов к ComfyUI.
> **Отвечает на вопрос:** «Что уже делает машина, что я до сих пор делаю руками, и что автоматизировать следующим».

Граница автоматизации в этом проекте проходит ровно по `assets_src/`. Слева от неё — человек с мышкой и GPU. Справа — 20 групп/команд `vn` верхнего уровня (68 листовых, из них 9 — честные заглушки), 39 схем, 33 диагностики линта, релизный гейт из 21 проверки и 10 определений CI-джоб в 5 workflow. Этот файл — карта обеих сторон и приоритизированный список того, что стоит перетащить слева направо. Критерий приоритета один: **ускоряет ли это производство контента**.

## Быстрый ответ

```bash
# Всё, что автоматизировано, запускается этими шестью командами:
vn doctor                       # окружение тулчейна (8 проверок)
vn pipeline doctor              # окружение рендер-конвейера (ffmpeg/GPU/ComfyUI/DAZ/модели)
vn build                        # lint -> ассеты -> кодоген -> game/tl  (один вызов на всё)
vn dev                          # то же в цикле: watch content/ + assets_src/ + запущенная игра
vn test smoke --picks 0,0       # прогон игры автопилотом, скриншоты, бюджет холодного старта
vn release build --flavor public  # сборка -> гейт (21 проверка) -> дистрибутив
```

Не автоматизировано вообще ничего из этого: запуск DAZ Studio, рендер, запуск ComfyUI, генерация кадра, апскейл, ретушь, художественная приёмка. См. [DAZ](17-daz-studio.md), [Генерация изображений](20-image-generation.md), [Генерация видео](21-video-generation.md).

---

# Часть 1. Что УЖЕ автоматизировано

Статусы — по коду, не по `docs/ARCHITECTURE.md`. Строки с пометкой PARTIAL/UNEXERCISED читать вместе с колонкой «Что делает»: там указано ровно то, чего не хватает.

Ссылки вида `tools/vn/src/vn/assets/pipeline.py:38-46`, `tools/vn/src/vn/content/lint.py:34-42`, `tools/vn/src/vn/loc/keys.py:86-127` — сокращение относительно `tools/vn/src/vn/`, а не путь от корня: каталоги `content/` и `loc/` в корне репозитория — зоны YAML-деклараций и обмена с переводчиками, Python там не лежит. См. [25-custom-engine.md §7](25-custom-engine.md).

## 1.1 Окружение и онбординг

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Диагностика тулчейна | `vn doctor` | 8 проверок: Python ≥ 3.10, git, git-lfs, корень репо, `min_tools` vs версия `vn`, реестр схем, шрифты UI (LFS-указатели по магическим байтам), пин Ren'Py SDK. Девятая строка — предупреждение про локальный override хранилища — печатается, только если есть `.vnstorage.local.yaml` (`doctor.py:104-106`); в репозитории его нет. ffmpeg **не** проверяется — это `vn pipeline doctor`. Exit 1 на любом hard-fail | IMPLEMENTED — `../../tools/vn/src/vn/doctor.py:69-153` |
| Диагностика рендер-конвейера | `vn pipeline doctor` | 12 групп проверок: ffmpeg + наличие `libvpx-vp9`, ffprobe, `nvidia-smi`, ComfyUI + venv + torch.cuda + ComfyUI-Manager, манифест моделей, DAZ Studio + библиотека DIM, VaM, Sims 4, свободное место, Ren'Py SDK | IMPLEMENTED — `../../tools/vn/src/vn/pipeline.py:455-581` |
| Подготовка свежего чекаута | `vn bootstrap` | `vn doctor` → `_assets_build(full)` → `compile_content` → `vn loc import`. Собирает **локально** | PARTIAL — скачивание из remote cache / CI-артефактов (G4) не подключено; сказано в самом docstring — `../../tools/vn/src/vn/cli.py` |
| Скачивание моделей ComfyUI | `vn pipeline models --pull` | `curl -L --fail --retry 3 -C -` по манифесту `tools/comfyui-models.yaml`, атомарный `os.replace`, лок-файл `<ComfyUI>/models/.vn-models.json`. Ключ Civitai — из `CIVITAI_API_KEY` | PARTIAL — все `sha256` в манифесте `null`, поэтому проверки целостности по доверенному дайджесту нет; повторные прогоны сверяют только размер — `pipeline.py:290-302,362-439` |
| Установка ComfyUI / DAZ / VaM / Sims 4 | `tools/setup-comfyui.ps1`, `tools/install-{daz,vam,sims4}.ps1` | ComfyUI: клон, venv, torch cu128, requirements, ComfyUI-Manager, каталоги моделей, `VN_COMFYUI`. Остальные три — **детекторы + печать чеклиста**, ничего не ставят кроме распаковки скачанного архива | PARTIAL — установка DAZ/VaM/Sims4 остаётся ручной (аккаунт, логин, DIM) |

## 1.2 Ассеты: сборка, кэш, чистка

Подробности — [Ассеты](16-assets.md). Здесь только «что делает машина».

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Сборка ассетов | `vn assets build [--profile full\|draft]`, а также внутри `vn build` | 10 версионированных трансформаций: `img_sprite`, `img_bg`, `img_cg`, `img_shot`, `img_thumb`, `ui_panel`, `copy_audio`, `voice_opus`, `video2webm`, `mov_poster` | IMPLEMENTED — `../../tools/vn/src/vn/assets/pipeline.py:54-65` |
| Генерация превью (thumbs) | та же сборка, второй job на тот же PNG | `cg/**/<name>.thumb.webp`, `quality=80` фиксировано, `max_side=512` через `Image.thumbnail(..., LANCZOS)`. Используется галереей | IMPLEMENTED — `tools/vn/src/vn/assets/pipeline.py:157,228-231` |
| Копирование звука | та же сборка, ветка `copy_audio` | Зона сырцов — **`assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg`** (нормативное имя, `ARCHITECTURE.md:393`); `.ogg` копируется байт в байт в `game/assets/audio/<kind>/`. Ветка была мертва до 2026-08-08 — конвейер смотрел в несуществующий `assets_src/audio/`; тест `test_assets.py:52` (`test_audio_stems_branch_copies_ogg`) стережёт зону | IMPLEMENTED — `tools/vn/src/vn/assets/pipeline.py:159-170,232-233`. **Но контента нет:** в репозитории ноль `.ogg`, `content/audio/{bgm,sfx}.yaml` — `tracks: {}`, поля `loop`/`loop_start`/`volume` схемы `audio@1` эмиттер игнорирует (`compile.py:301-310`), нормализации громкости (loudnorm) нет |
| Генерация UI-панелей (9-patch) | та же сборка, job на каждый id из `content/ui/panels.yaml` | Рисует PNG (тень→заливка/градиент→обводка) → lossless WebP → `define vn_frame_<id> = Frame(..., Borders(r,r,r,r), tile=False)` с минимальным размером в комментарии | IMPLEMENTED (ADR-0009) — `../../tools/vn/src/vn/assets/ui.py:43-137` |
| Кодирование видео в VP9/WebM | `vn assets video build`; внутри общей сборки | 1-pass libvpx-vp9, `-b:v 0 -crf 30 -row-mt 1 -cpu-used 2 -pix_fmt yuv420p -an`, сайдкар `mov_meta@1` рядом с выходом | IMPLEMENTED — `../../tools/vn/src/vn/assets/video.py:85-120` |
| Кэш трансформаций | автоматически при любой сборке | Ключ = `blake3(src_hash:transform:version:profile)`, блоб в `.vncache/assets/<2hex>/<64hex>`, все записи атомарны (`.tmp` + `os.replace`) | IMPLEMENTED — `tools/vn/src/vn/assets/pipeline.py:298-311` |
| Сборка мусора кэша | `vn assets cache --gc [--dry-run]` | mark & sweep от манифеста сборки; заодно подбирает осиротевшие `*.tmp` | IMPLEMENTED — `tools/vn/src/vn/assets/pipeline.py:458-491`, CLI `cli.py` |
| Удаление осиротевших выходов | автоматически в конце сборки | Диффом манифеста: `set(old_manifest) - set(seen_outputs)`, потом `rmdir` опустевших каталогов вверх до `game/assets` | PARTIAL — удаляются **только** файлы, когда-то бывшие в манифесте; потеря `.vncache/assets-manifest.json` (он gitignored) навсегда выключает удаление — `tools/vn/src/vn/assets/pipeline.py:416-433` |
| Валидация манифеста сборки (G16) | автоматически при записи манифеста | `.vncache/assets-manifest.json` объявляет `assets_manifest@1` и **проверяется схемой из реестра** перед записью; ошибки схемы идут в `rep.errors`, но манифест всё равно пишется — иначе следующая сборка потеряет точечную очистку сирот | IMPLEMENTED (с 2026-08-08) — схема `tools/schemas/assets_manifest@1.schema.json`, вызов `tools/vn/src/vn/assets/pipeline.py:441-454`, тест `test_assets.py:69` |
| Валидация ассетов | `vn assets validate` | Discovery + свежесть (`build_assets(check=True)`) плюс контентный слой: реестр образов и музыкальные треки (`compile_content(check=True)`) | IMPLEMENTED — `cli.py` |
| Нарезка PSD | автоматически в начале каждой пишущей сборки | `assets_src/psd/characters/<key>/<key>_<pose>.psd` → staging `.vncache/psd_png/...`, слои `base`/`outfits`/`faces`/`overlays`, видимость слоёв **игнорируется** | IMPLEMENTED / UNEXERCISED — ноль `.psd` в репо, ноль тестов, не инкрементально — `../../tools/vn/src/vn/assets/psd.py` |
| Вотчер сырцов | `vn dev`, `vn assets watch` | Поллинг раз в 1 с по `assets_src/` и `content/`, снапшот `(mtime, size)`, исключения колбэков не фатальны | IMPLEMENTED — `../../tools/vn/src/vn/devloop.py:31-56`. У `vn assets watch` события `content/` выброшены (`lambda: None`, `cli.py`) — см. [Цикл разработки](04-development-workflow.md) |

## 1.3 Кодоген контента

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Компиляция деклараций | `vn content compile`, внутри `vn build` | 36 отслеживаемых входов → **21 выход** в `game/generated/`: 10 реестров (`chapters`, `characters`, `images`, `scenes`, `menus`, `audio`, `gallery`, `achievements`, `ui_frames`, `overrides`), 4 обёртки сцен, `screens/chapter_select`, 3 файла состояния (`defaults`, `snapshot`, `migrations`), `version.gen.rpy`, `render.gen.rpy` (ADR-0012), `platform.gen.rpy` (ADR-0014) | IMPLEMENTED — `../../tools/vn/src/vn/content/compile.py:790-1211` (`compile_content`) |
| Разбор авторского `.rpy` | внутри компиляции | Только через Ren'Py SDK: `renpy.exe <root> vn_analyze` (G24) — свой парсер запрещён | IMPLEMENTED — `tools/vn/src/vn/content/analyze.py:37-70`, мост `game/framework/00_core/050_build_bridge.rpy:98-144` |
| Скелеты глав и сцен | `vn chapter new <slug>`, `vn scene new <ch> <slug>`, `vn scene stub <ch> <id>` | Создаёт пары `*.scene.{yaml,rpy}` со следующим номером (шаг 10), `chapter.yaml`, `vars.yaml` | IMPLEMENTED — `../../tools/vn/src/vn/content/scaffold.py` |
| Линт контента | `vn content lint`, первым шагом `vn build` | 33 диагностики: схемы, конвенции имён, структура глав, битые exits, достижимость, недостижимые сцены, бинарный бюджет ADR-0004 (warn > 30 МБ, error > 50 МБ), сверка структуры каталогов (`--layout`: 10 обязательных + 2 запрещённых) | IMPLEMENTED — `../../tools/vn/src/vn/content/lint.py` |
| Валидация по схемам | всюду, где читается декларация | **36** файлов `tools/schemas/*.schema.json` (2026-08-08: +`assets_manifest@1`, +`build_info@2`; `build_info@1` осталась с пометкой «устарела» — читать старые артефакты), конвенция имени `<name>@<N>.schema.json`, `properties.schema.const` обязан совпасть с именем файла, Draft 2020-12 | IMPLEMENTED — `../../tools/vn/src/vn/schemas.py:13-51` |
| Граф сцен | `vn content graph [--out]` | Mermaid `flowchart TD`: сцены, условные exits, тупики; экранирует кавычки/угловые скобки в `when`; главы паков включены и подписаны (`· pack <id>`) | IMPLEMENTED (2026-08-18) |
| Валидация паков | `vn pack validate`, а также внутри каждой сборки | `manifest.yaml` есть, схема валидна, `id` == имени папки, `api_level` совместим с `VN_API_LEVEL = 1`, `requires.core` совместим с версией ядра | IMPLEMENTED / UNDOCUMENTED — `compile.py:437-471`, CLI `cli.py` |

## 1.4 Локализация

Подробности — [Локализация](14-localization.md).

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Генерация say-id | `vn loc keys` (и `--check` в CI) | Через парсер Ren'Py дописывает `id chNN_sNNN_NNNN` в авторский `.rpy`, маркирует меню `$ vn_menu = "chNN_sNNN_mNNN"`, перегенерирует ledger `loc/ledger/chNN.json` | IMPLEMENTED — `../../tools/vn/src/vn/loc/keys.py:86-127` |
| Экспорт в PO | `vn loc extract` | Обновляет все PO из ledger + `strings.yaml` + имён персонажей | IMPLEMENTED — `../../tools/vn/src/vn/loc/po.py` |
| Импорт переводов | `vn loc import`, автоматически в хвосте `vn build` | PO → `game/tl/<lang>/`. Правки в `game/tl/` руками запрещены — зона генерируемая и не в git | IMPLEMENTED — `cli.py` |
| Псевдолокаль | `vn loc pseudo` | Пакет `pseudo` + импорт; экранирует `[` как `[[`, чтобы Ren'Py не принял его за интерполяцию | IMPLEMENTED |
| Новый язык | `vn loc add <code>` | Создаёт `loc/po/<code>/` (ADR-0005), подставляет нативное имя из таблицы 43 кодов, сразу запускает extract | IMPLEMENTED |
| Отчёт покрытия | `vn loc report` | `de/en/pseudo`: переведено/всего, fuzzy | PARTIAL — флагов `--gate`/`--format` нет; гейт по покрытию живёт **только** в релизной валидации — `release.py:475-501` |

## 1.5 Проверка и QA

Подробности — [Тестирование](27-testing.md).

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Юнит-тесты тулинга | `python -m pytest tools/vn/tests -q` | 373 теста в 27 файлах. На машине без `RENPY_SDK` и ffmpeg 22 из них скипаются, и один падает (27 §2.3) | IMPLEMENTED — но CLI покрыт почти никак: из `cli.py` (2117 строк) тестами закрыта одна команда `pack build` (`test_release.py:141-192`, через `CliRunner`); `analyze.py`, `scaffold.py`, `psd.py`, `devloop.py` не импортирует ни один тест |
| Smoke-автопилот | `vn test smoke [--picks] [--lang] [--timeout]` | Пишет временный `game/generated/qa/autopilot.gen.rpy`, запускает движок с `VN_AUTOPILOT=1`, тикает раз в 0.6 с (скриншот + `dismiss`), выбирает пункты меню по индексам, пишет `RESULT.txt`/`state.json`/`gallery.json`/`picks.log` в `.vncache/smoke/`. Никакого синтетического ввода на рабочий стол — всё in-process | IMPLEMENTED — `cli.py`, рантайм `game/framework/00_core/030_flow.rpy:91-211` |
| Бюджет холодного старта | внутри `vn test smoke` | Читает `startup.txt`, падает при превышении `budgets.cold_start_s` (30 с) | IMPLEMENTED — `cli.py`. В релизном гейте этой проверки **нет** |
| Проверка сейв-фикстур | `vn save check` | Оффлайн: открывает каждый `ci/fixtures/saves/*.save` как zip, читает член `json`, требует целый `vn_save_schema` | IMPLEMENTED — `cli.py` |
| Прогон сейв-корпуса | `vn save corpus [--add NAME]` | Восстанавливает «линию statement-имён» из `ci/fixtures/rpyc-line/` (52 `.rpyc` — единственные `.rpyc` в git), грузит каждую фикстуру в реальном движке со скретч-`--savedir`, миграции идут в `label after_load` | IMPLEMENTED — 2 фикстуры: `schema2-demo` (текущая схема) и `schema1-demo` (`vn_save_schema=1`, сцена `ch01_s010`). На второй прогон печатает «schema после загрузки: 2 (цель 2)», а в `log.txt` появляется `[vn] migration 0002` — миграция реально исполняется в игре — `cli.py` |
| Бюджеты размеров (G19) | `vn build`, `vn build --check`, релизный гейт | `assets_total_mb 20000`, `generated_total_kb 65536`, `video_total_mb 8000`, `video_file_mb 512` — одна реализация на всех потребителей | IMPLEMENTED — `../../tools/vn/src/vn/release.py:29-56` |
| Провенанс ассетов | `vn assets provenance record\|workflow\|verify` | Достаёт `model`/`loras`/`seed`/`steps`/`cfg`/`sampler`/промпты из PNG-чанков `tEXt` ComfyUI, складывает граф в хранилище по blake3, собирает цепочку `daz_render → comfyui`, проверяет хеши | IMPLEMENTED / UNEXERCISED — ноль `*.provenance.json` в репозитории — `../../tools/vn/src/vn/assets/provenance.py` |
| Проверка лицензий ассетов | `vn assets licenses`, гейт релиза | Сверяет `license: [...]` в `*.render.yaml` с реестром `content/licenses.yaml`: неизвестный id → ERROR, `game_use: false` → ERROR, `nsfw_allowed: false` при выходе в `/nsfw/` → ERROR, отсутствие `license` → WARNING | IMPLEMENTED — `../../tools/vn/src/vn/assets/licenses.py:53-109`, включено в гейт `release.py:503-512` |

## 1.6 Релиз и упаковка

Подробности — [Сборка и релиз](29-build-and-release.md), [Паки и DLC](30-packs-and-dlc.md).

| Процесс | Команда / триггер | Что делает | Статус |
|---|---|---|---|
| Релизный гейт | `vn release validate --flavor <f>`, внутри `vn release build` | **21 проверка** PASS/WARN/FAIL: схема `project.yaml`, существование флейвора, манифесты паков, **зрелость контента** (`early_content` против `status` глав), lint, LFS-указатели шрифтов, свежесть ассетов, валидность видео, свежесть генерата, бюджеты G19, провенанс, DAZ/VaM/Sims4-декларации, покрытие переводов, лицензии, статус хранилища сырцов, версия release-manifest, git sha, наличие сейв-корпуса (сейчас PASS: «сейв-корпус: 2 фикстур», `release.py:542-549`). Своих правил у гейта нет — он агрегатор | IMPLEMENTED — `release.py:313-551` |
| Сборка дистрибутива | `vn package`, `vn release build --flavor` | `vn build` → перенос `.rpyc` прошлого релиза → `renpy compile` → `launcher distribute --dest build/dist/<version>[-flavor]` → снапшот нового `.rpyc`-кэша | IMPLEMENTED — `cli.py` |
| Перенос `.rpyc` между релизами (G6) | автоматически внутри `vn package` | Копирует с перезаписью все `.rpyc` из `build/rpyc-cache/<макс. версия>/`; ноль восстановленных при непустом кэше = жёсткая остановка сборки | PARTIAL — каталог кэша ключуется **только версией**, не флейвором: локально public и patron затирают друг друга (`cli.py`); в CI это прикрыто ключами `actions/cache` |
| Материализация флейвора | `vn release build --flavor` | Пишет `game/build_id.json` (`build_info@2`) на время дистрибуции, удаляет в `finally`. NSFW-глобы считаются по **реальным** каталогам `game/assets/<cat>/nsfw/`. Секрета в документе нет: `--patron-token` — вход, наружу уходит производная метка `patron_tag` (ADR-0011) | IMPLEMENTED — `release.py:258-310`, метка — `release.py:455-476`. Сейчас глобы пусты: каталогов `nsfw/` в `game/assets/` нет |
| Changelog из диффа реестров | `vn release changelog` | Снимок глав ядра и паков → дифф с `ci/release-manifest.json` → блок «Новые главы / Новые сцены / Удалены сцены» в начало `docs/CHANGELOG.md`; штамп `id_registry` (G7) | PARTIAL — нет `--from`/`--audience`; паки видит с 2026-08-18 |
| Сборка пака | `vn pack build <id>` | Zip `build/packs/<id>.zip`: `manifest.yaml` + весь генерат глав пака | PARTIAL — охранник починен 2026-08-08 (`cli.py`): сцены считаются отдельно от манифеста, «главы объявлены, генерата нет» валит команду **до** создания zip; пак-контейнер без глав собирается штатно с предупреждением. Остаётся: в архиве только сцены и манифест (ни ассетов, ни `tl/`, ни персонажей, ни депот-раскладки), и проверка «хоть одна сцена» — на весь пак, а не по каждой объявленной главе |
| Штамп реестра выпущенных id (G7) | внутри `vn release changelog` | Append-only объединение глав/сцен/персонажей/переменных со `status: release` | IMPLEMENTED но ИНЕРТЕН — `ch01` в статусе `draft`, поэтому `content/registry/id_registry.json` состоит из пустых массивов |

## 1.7 CI: 5 workflow, 10 определений джоб

`.github/workflows/` — это **настоящий** пайплайн проекта. Он нигде не описан в `docs/`, и в `CODEOWNERS` нет записи на `/.github/`.

Джобы: `ci.yml` → `lint`, `build-test`; `nightly.yml` → `smoke`, **`controller-first`**, **`corpus`**; `canary.yml` → `fresh-renpy`; `release.yml` → `build`, `dmg`, `publish`; **`steam-upload.yml` → `upload`**. Итого **10 определений** (джоба `corpus` добавлена 2026-08-18); матрицами разворачиваются две джобы — релизная `build` по `flavor: [public, patron]` и `controller-first` по двум геймпадным профилям, — так что реальных прогонов за ночь и на теге больше числа определений.

| Workflow | Триггер | Джобы и что реально гоняется | Статус |
|---|---|---|---|
| `ci.yml` | push в `main`, любой PR | `lint`: `vn content lint`. `build-test`: checkout `lfs: true` → SDK 8.5.3 из кэша → `vn build` → `vn loc keys --check` → `renpy.sh . lint` → `vn test oversample --scale 2` → **`vn release android preflight --bundle`** → **шаг `must_fail`** (`vn release android status`, `release android build --timeout 1`, `voice tts --backend piper` обязаны падать НЕнулевым кодом и называть отсутствующий тулчейн) → `vn content compile --check` → `pytest` (**`working-directory: tools/vn`**, иначе `ModuleNotFoundError: No module named 'tests'` — [27 §2.1](27-testing.md)) → артефакт `game/generated/` на 30 дней (аварийный режим G4) | IMPLEMENTED / UNDOCUMENTED |
| `nightly.yml` | cron `30 2 * * *` + dispatch | `smoke`: `vn build` → `vn loc import` → `vn loc report` (`:49-53`) → **4 smoke-прогона** (`:57-60`: `--picks 0,0`; `0,1 --lang en`; `1`; `0,0 --lang pseudo`) → `vn save check` + `vn save corpus` (`:64-65`) → `rm -rf game/generated` и обе релизные сборки dry-run (`:70-74`) → артефакт `.vncache/smoke/` (`:76-82`). `controller-first` (`:85-151`): матрица `steam_deck medium touch` / `steam_big_picture` → `vn build` → `vn test smoke --picks 0,0` с `VN_AUTOPILOT_SCREENS=main_menu,preferences,gallery,chapter_select` → артефакт `controller-shots-<profile>-<run_id>`. **Гейта у второй джобы нет намеренно:** поломка вёрстки видна на картинке, а не в коде выхода. **Внимание:** dry-run обоих флейворов сейчас проходит — гейт зрелости контента даёт WARN, пока в проекте нет ни одной главы `status: release`; покраснеет он с первой такой главой ([29 §5.1](29-build-and-release.md#maturity-gate-rule)). Третья джоба, **`corpus`** (добавлена 2026-08-18): свой checkout с LFS (корпус копирует `game/framework` и `gui.rpy` шаблоном, а шрифты UI лежат в LFS — с указателями прогон движка падает `FreetypeError`), SDK из кэша, ffmpeg, затем `xvfb-run -a vn test corpus --scenes 600 --images 400 --videos 2 --lines 8 --vars 100` — вдвое выше целевого масштаба проекта, ~5 с на этой машине. Отдельная джоба, а не шаги в `smoke`: корпусу не нужны ни сборка репозитория, ни переводы, ни сейв-фикстуры, и красный smoke не должен прятать измерения ([32 §7.5](32-performance-and-scalability.md)) | IMPLEMENTED / UNDOCUMENTED |
| `canary.yml` | cron `0 3 * * 1` + dispatch | Скачивает **свежайший** Ren'Py с renpy.org, `vn build` → `renpy.sh . lint` → `pytest` (в подоболочке `(cd tools/vn && …)`; остальные команды считают проект от корня) → `vn test smoke --picks 0,0`. Без `continue-on-error` — красный canary виден сразу | IMPLEMENTED / UNDOCUMENTED |
| `release.yml` | push тега `v*` | `build` (матрица `public`/`patron`, `fail-fast: false`): гард «тег == `project.yaml: version`» → кэш `.rpyc` **на флейвор** (`:71-76`) → `vn release build --package win --package linux --package mac` (`:78-87`; `--patron-token $PATRON_TOKEN` только для patron). `dmg`: `hdiutil` на macOS-раннере из public mac-zip. `publish`: `gh release create` — **только public** + dmg | IMPLEMENTED / UNDOCUMENTED |
| `steam-upload.yml` | **только** `workflow_dispatch` (входы `flavor`: public/patron, `branch`: по умолчанию `beta`) | `upload`: лок → editable → ffmpeg → SDK → **restore-only** кэш `.rpyc` (ручная выкладка не должна становиться источником релизной линии, G6) → `vn release build --package win/linux/mac` → `vn release steam --flavor --branch` → steamcmd `+login … +run_app_build`. Без секретов `STEAM_USERNAME`/`STEAM_CONFIG_VDF` шаг аплоада — зелёный no-op с `::notice::`; при пустом `appid` workflow упал бы раньше, на `vn release steam`; сейчас там плейсхолдер 480, то есть дойдёт до steamcmd и будет отвергнут Valve. `concurrency: steam-upload` без cancel-in-progress: аккаунт-билдер один, а убивать steamcmd на середине хуже, чем ждать. Артефакт — только VDF | IMPLEMENTED (аплоад ни разу не выполнялся) |

**Инварианты всех пайплайнов** (стережёт `tools/vn/tests/test_ci_config.py`, 14 тестов):

- **Пиннованный тулчейн (G17).** Во всех строках установки идёт `pip install --quiet -r tools/vn.lock` **перед** `pip install -e "tools/vn[dev]"` — `ci.yml` (2), `nightly.yml` (3, включая джобу `corpus`), `canary.yml`, `release.yml`, `steam-upload.yml`. Мест по числу джоб **восемь** — эту восьмёрку и ассертит тест. Порядок — часть контракта: поставь editable первым, и пины станут декоративными.
- **Вариантные прогоны — в `nightly`, а не в `ci`.** Прогон движка на геймпадный профиль стоит минуты, а MR-пайплайн держим под 10 минут (G15). Тест требует, чтобы матрица `controller-first` брала `RENPY_VARIANT` из матрицы, задавала непустой `VN_AUTOPILOT_SCREENS`, выгружала артефакт — и чтобы `RENPY_VARIANT` в `ci.yml` не встречался вовсе.
- **ffmpeg до `vn build`.** `ci.yml:49`, `nightly.yml:33,118`, `canary.yml:33`, `release.yml:45`, `steam-upload.yml:58`. До этого ffmpeg был только в `ci.yml` и `release.yml`, а в `assets_src/video_src/` лежат сырцы — то есть ночной и canary-прогоны обязаны были краснеть на видео-ветке конвейера.

---

# Часть 2. Что автоматизировать дальше

### ComfyUI: workflow-JSON как ассеты репозитория

**Current state:** в репозитории **ноль** ComfyUI-workflow любого вида (проверено сплошным сканом; единственное совпадение на «workflow» — каталог `.github/workflows`). `docs/pipeline/phase-0.md:174-175` отправляет художника к штатному шаблону ComfyUI «Templates → Video» Wan 2.2 I2V. Механизм хранения графа уже есть — `store_workflow()` кладёт `{"prompt": api, "workflow": ui}` в хранилище по ключу `workflows/<blake3>` (`tools/vn/src/vn/assets/provenance.py:128-147`), но хранилище `~/vn-assets-store` не создано, так что фактический граф живёт только внутри PNG, который художник не потерял.
**Potential automation:** завести зону `pipeline/workflows/*.api.json` в git — по одному экспортированному **API-format** графу на класс ассета (`sprite_base`, `sprite_expression`, `bg`, `cg`, `i2v_loop`, `upscale`), плюс правило линта «граф, на который ссылается провенанс, обязан существовать в этой зоне или в хранилище».
**Priority:** **P0**
**Expected benefit:** снимает единственную причину, по которой производство кадра невоспроизводимо. Сегодня повторить прошлогодний спрайт можно только найдя старый PNG и перетащив его в ComfyUI. Убивает класс ошибок «граф ушёл вместе с диском художника» и делает возможным всё остальное из этого раздела — без файла графа автоматизировать вызов нечего.
**Implementation idea:** новая зона + запись в `docs/conventions/folder-layout.md`; схема `comfy_workflow@1` в `tools/schemas/` (минимум: `schema`, `id`, `role`, `models[]`); проверка существования — в `tools/vn/src/vn/content/lint.py` рядом с `REQUIRED_FILES` (`lint.py:34-42`). Экспортировать обязательно через `File → Export Workflow (API)`: сохранённый из UI JSON эндпоинт `/prompt` не принимает.

### ComfyUI: вызов из `vn` (API-клиент)

**Current state:** NOT IMPLEMENTED. `vn pipeline` умеет только ставить ComfyUI и качать модели (`pipeline.py:290-581`). Ни одного HTTP-запроса к ComfyUI в репозитории нет: ни `8188`, ни `/prompt`, ни `/history`, ни websocket. Каждая генерация — GUI-сессия.
**Potential automation:** `vn assets gen --workflow <id> --params <yaml>`: подставить параметры в граф, `POST /prompt`, опросить `GET /history/<prompt_id>`, забрать результат через `GET /view`, положить в `assets_src/png/...` по конвенции имён и сразу вызвать `provenance.record`.
**Priority:** **P1** (P0 — только после того, как появятся файлы графов)
**Expected benefit:** переводит генерацию из «сессия за монитором» в «ночная очередь». Для главы с 40 CG и матрицей 3 позы × 4 эмоции это разница между двумя днями и одной ночью. Плюс автоматом закрывает дыру «PNG без сайдкара провенанса проходит все гейты» (`provenance.py:328` обходит только уже существующие сайдкары).
**Implementation idea:** новый модуль `tools/vn/src/vn/assets/comfy.py` + группа `vn assets gen` в `cli.py` рядом с `vn assets provenance` (`cli.py`). Зависимостей не добавлять — `urllib` из stdlib достаточно, как уже сделано в `pipeline._download` (`pipeline.py:333-359`). Биндиться на `127.0.0.1`, не на `0.0.0.0`: эндпоинт неаутентифицированный и умеет писать файлы и исполнять Python кастом-нод.

### Батч-рендер DAZ через DAZ Script

**Current state:** NOT IMPLEMENTED, причём радикально: сплошной скан по `*.dsa`, `*.dse`, `*.dsb`, `*.duf` даёт **ноль файлов**. `pipeline.daz_studio_path()` (`pipeline.py:102-130`) только **находит** `DAZStudio.exe` через DIM-ini → реестр `HKLM\SOFTWARE\DAZ\Studio{6,5,4}` → хардкод `C:\Program Files\...`; путь идёт в строчку `vn pipeline doctor` и никогда не исполняется. `vn assets daz validate` проверяет существование `.duf` и наличие выхода — сам `.duf` не открывает и не парсит (общий валидатор `tools/vn/src/vn/assets/sources.py:145-206`).
**Potential automation:** `vn assets daz render --scope <subpath>`: по каждой `*.render.yaml` собрать аргументы, запустить `DAZStudio.exe -headless -noPrompt -scriptArg <json> <script.dsa>`, скрипт ставит камеру/пресеты из блока `render:`, выставляет `DzRenderOptions.renderImgToId = DirectToFile` + `renderImgFilename`, зовёт `DzRenderMgr::doRender()`, выходит. Перезапускать процесс каждые N сцен.
**Priority:** **P0**
**Expected benefit:** самый крупный ручной блок конвейера. Матрица «сцена × N выражений × M ракурсов × K нарядов» сегодня кликается вручную; скрипт превращает её в детерминированный ночной прогон с именами файлов, которые конвейер ассетов уже умеет читать (`assets_src/png/characters/<key>/<pose>/faces/<name>.png`). Убивает класс ошибок «отрендерил в разрешении не из декларации» — сейчас никто не сверяет `render.resolution` с фактическим PNG.
**Implementation idea:** `tools/daz/render.dsa` + `tools/vn/src/vn/assets/daz.py` (там уже разобран формат декларации). Флаги `-headless`/`-noPrompt`/`-scriptArg` подтверждены в официальной документации командной строки DAZ; API-справочника под DS6 ещё нет, писать придётся против 4.x-доков на ES7-рантайме — закладывать идемпотентность и гарантированный выход, иначе останутся зомби-`DAZStudio.exe`. Готовые очереди (Render Queue в подписке Premier, сторонние плагины) — риск на каждой сборке DS6; свой процесс-драйвер структурно безопаснее.

### Сборка секвенции кадров в видео

**Current state:** NOT IMPLEMENTED. Схемы `vam_render@1` и `sims4_render@1` уже объявляют `capture.mode: sequence`, но никакой код не превращает последовательность кадров в контейнер: `tools/vn/src/vn/assets/video.py` ждёт **уже закодированный** `.mp4/.mov/.mkv/.webm/.m4v/.avi` в `assets_src/video_src/` (`video.py:24`). Между «отрендерил 96 PNG» и «получил `video_src/<group>/<name>.mp4`» — ручной вызов ffmpeg.
**Potential automation:** трансформация `seq2video` в `TRANSFORMS` (`tools/vn/src/vn/assets/pipeline.py:38-46`): каталог `assets_src/seq/<group>/<name>/%05d.png` + сайдкар с fps → `ffmpeg -framerate N -start_number 0 -i %05d.png -pix_fmt yuv420p ...` → `video_src`-эквивалент, дальше штатный `video2webm`.
**Priority:** **P1**
**Expected benefit:** закрывает единственный разрыв в цепочке DAZ/ComfyUI → Ren'Py для анимации. Сегодня каждый луп требует руками набранной команды ffmpeg, и `-pix_fmt yuv420p` в ней забывают — а именно это даёт «в VLC нормально, в игре тормозит».
**Implementation idea:** новая ветка в `_discover()` (`tools/vn/src/vn/assets/pipeline.py:102`) + функция рядом с `encode_args` (`video.py:85-111`). Ключ кэша считать по blake3 конкатенации хешей кадров + сайдкара — как уже сделано для видео с `*.video.yaml` (`pipeline.py:299-303`). Не забыть про соединение шва лупа: детектор уже есть (`vn assets video validate`, RMS по стыку), производителя нет.

### `vn char new` / `vn char validate`

**Current state:** NOT IMPLEMENTED — заглушки **фазы 1**, то есть просрочены на текущей стадии проекта: `_stub_group("char", ..., {"new": 1, "validate": 1, "sheet": 2})` (`cli.py`), exit 3. Персонаж заводится руками: `content/characters/<key>/character.yaml`, матрица поз/эмоций/нарядов, строки, запись в реестр. Скаффолдинг существует только для глав и сцен (`tools/vn/src/vn/content/scaffold.py`).
**Potential automation:** `vn char new <key>` — скелет декларации + каталоги `assets_src/png/characters/<key>/a/{faces,outfits}` + строка в `content/ui/strings.yaml`. `vn char validate` — сверка `matrix` с фактически собранными файлами **до** сборки, с внятным сообщением, а не ошибкой компилятора «у позы 'a' нет base@2.webp».
**Priority:** **P1**
**Expected benefit:** персонаж — вторая по частоте единица работы после сцены. Сейчас ошибки в матрице всплывают на середине `vn build` (`tools/vn/src/vn/content/images.py:170-190`) — цикл «правка → 30-секундная сборка → сообщение» вместо мгновенной проверки. При росте до 50 персонажей это часы.
**Implementation idea:** расширить `tools/vn/src/vn/content/scaffold.py` (там уже есть `new_chapter`/`new_scene`/`new_stub` и разбор существующих id) и заменить `_stub_group("char", ...)` на реальную группу в `cli.py`. Проверку матрицы переиспользовать из `tools/vn/src/vn/content/images.py`, вынеся её в функцию, вызываемую и линтом, и `char validate`.

### Чтение `tools/vn.lock` в CI (G17) — СДЕЛАНО 2026-08-08

**Current state:** IMPLEMENTED для 18 пиннованных пакетов. Во всех восьми джобах установки тулчейна (`ci.yml` ×2, `nightly.yml` ×3, `canary.yml`, `release.yml`, `steam-upload.yml`) перед editable-установкой идёт `pip install --quiet -r tools/vn.lock`. Порядок и число мест стережёт `tools/vn/tests/test_ci_config.py:73-90`. Рецепт из `docs/runbooks/pipeline-broken-at-night.md` («`git revert` бампа лока») теперь действительно влияет на CI.
**Что осталось (честно):** транзитивные зависимости в локе не закреплены — например `pygments`, который тянет `pytest`, в файле отсутствует и приезжает с PyPI произвольной версии. Проверки «пины покрывают все зависимости `pyproject.toml`» тоже нет: рассинхрон лока и `dependencies` никем не ловится.
**Potential automation (остаток):** тест сверки имён `vn.lock` ↔ `pyproject.toml` (`dependencies` + `dev`); дальше — переход на `pip-tools`/`uv` с полным замыканием транзитивных зависимостей, отдельным ADR.
**Priority:** **P3** (основная ценность снята; остаток — гигиена)
**Expected benefit:** класс «вчера было зелено, сегодня красно, никто ничего не менял» закрыт для прямых зависимостей — это и был самый дорогой по времени класс инцидентов. Остаточный риск теперь только по транзитивной части дерева.
**Implementation idea:** тест рядом с `test_ci_config.py` (читает `pyproject.toml` и `vn.lock`, сверяет множества имён) — или маленькая функция в `doctor.py` рядом с проверкой `min_tools` (`doctor.py:87-96`).

### `vn content graph` для паков

**Current state:** IMPLEMENTED (2026-08-18). `build_graph()` обходит зоны из `repo.chapter_zones` — ядро и `packs/*/chapters/`. Проверено прогоном на живом репозитории: в выводе `ch01` с тремя сценами и `ch90_beach (draft) · pack ep_beach`.
**Potential automation:** переиспользовать `_collect_chapters()` из компилятора (`compile.py:499-513`) — он уже строит зоны `[("core", content/chapters)] + [(pack_id, packs/<id>/chapters)]`. Главы паков рисовать отдельным subgraph с меткой пака.
**Priority:** **P2**
**Expected benefit:** сценарист видит ветвление DLC глазами, ревьюер — диффом. Стоимость — десяток строк, потому что вся нужная функция уже написана; поэтому в P2, а не ниже, несмотря на скромный выигрыш.
**Как сделано:** раскладка зон вынесена в `repo.chapter_zones` (ядро + `packs/*/chapters/`) и переиспользована четырьмя вызывающими: компилятор, граф, `snapshot_content` и модель памяти. До этого копия жила в каждом модуле, и две из них отставали — граф и changelog паков не видели.

### Эмиссия группы `overlays`

**Current state:** PARTIAL. Слои `overlays/*` собираются в `game/assets/spr/<key>/<pose>/overlays/*@2.webp` (`tools/vn/src/vn/assets/pipeline.py:125-135`), нарезаются из PSD (`psd.py:60-88`), но в `layeredimage` не эмитятся — вместо этого компилятор печатает предупреждение «overlays собраны, но эмиссия overlay-группы появится позже — сейчас мёртвый груз в дистрибутиве» (`tools/vn/src/vn/content/images.py:178-182`).
**Potential automation:** дописать группу в эмиттер `layeredimage`: `attribute`-группа без `auto`, семантика «наложение поверх base+outfit+face» (румянец, слёзы, синяки, капли).
**Priority:** **P2**
**Expected benefit:** снимает мёртвый вес из дистрибутива и открывает дешёвый способ увеличить выразительность без нового рендера: один overlay даёт вариацию на всех эмоциях. Для NSFW-контента это буквально основной приём.
**Implementation idea:** `tools/vn/src/vn/content/images.py:190-221` — рядом с эмиссией `faces`/`outfits`. Заодно решить, нужен ли `overlays` в матрице `character.yaml` отдельным ключом (сейчас там `poses`/`emotions`/`outfits`).

### Side images для say-окна

**Current state:** NOT IMPLEMENTED, при этом нормировано: `docs/conventions/naming.md:18` и `docs/ARCHITECTURE.md:144,454,922` описывают `assets/spr/<char>/side/<emotion>@2.webp`. `grep -rn "side/" tools/vn/src/vn/` — **ноль** попаданий.
**Potential automation:** ветка discovery `assets_src/png/characters/<key>/side/<emotion>.png` → `spr/<key>/side/<emotion>@2.webp` + эмиссия `image side <key> <emotion>` в реестр образов.
**Priority:** **P2**
**Expected benefit:** side image — стандартный способ показать говорящего, не занимая сцену спрайтом; экономит по одному рендеру ракурса на реплику в диалогах «за кадром». Ровно та функциональность, которую документация уже обещает, а код не даёт — то есть класс ошибок «сделал по naming.md, оно молча не собралось».
**Implementation idea:** `tools/vn/src/vn/assets/pipeline.py:110-135` (discovery спрайтов) + `tools/vn/src/vn/content/images.py:190-221` (эмиссия). Решить, где живёт декларация: отдельным ключом в `character.yaml` или по факту наличия каталога, как сейчас сделано для поз.

### High-watermark для say-id

**Current state:** NOT IMPLEMENTED. Номера берутся из множества уже занятых в **этом файле** id (`used_nums`, `tools/vn/src/vn/loc/keys.py:86-115`), ledger `loc/ledger/chNN.json` полностью перегенерируется каждым прогоном. Удалили реплику — её номер снова свободен и достанется следующей новой реплике.
**Potential automation:** хранить в ledger `next_num` (или список retired-id) и никогда не переиспользовать номер; `vn loc keys --check` краснеет на попытке.
**Priority:** **P2**
**Expected benefit:** убирает класс «переводчик получил старую строку под новым текстом». Сегодня риск смягчён тем, что polib помечает такую единицу как fuzzy при смене source (покрыто тестом в `test_loc.py`), поэтому это не P0/P1 — но fuzzy-пометку переводчик может снять не читая.
**Implementation idea:** `tools/vn/src/vn/loc/keys.py` + бамп схемы `ledger@1` → `ledger@2` в `tools/schemas/` (конвенция версионирования схем описана в [Контентном конвейере](08-content-pipeline.md)). Обязательно вместе с миграцией существующих ledger, иначе `vn loc keys --check` покраснеет у всех.

### Флейворный ключ у `build/rpyc-cache`

**Current state:** PARTIAL. Каталог кэша — `cache_root / version` (`cli.py`), флейвор в ключ не входит. Обе сборки одной версии пишут в один каталог, побеждает последняя. Локально это значит: собрал `patron`, потом `public` — линия statement-имён public построена на `.rpyc` от patron. В CI дыра прикрыта снаружи ключами `actions/cache` (`release.yml:71-76`), то есть исправлена не там, где сломано.
**Potential automation:** ключ `build/rpyc-cache/<version>-<flavor>/`, при отсутствии — фолбэк на безфлейворный каталог (совместимость с существующим `build/rpyc-cache/0.1.0/`, 48 файлов).
**Priority:** **P2**
**Expected benefit:** save-совместимость (G6) — тот класс ошибок, который обнаруживается уже у игрока: «сейв из 0.1.4 не грузится в 0.1.5». Стоимость — одна f-строка плюс фолбэк.
**Implementation idea:** `cli.py`, обе функции (restore и snapshot) плюс `_semver_key`. `dest_suffix` уже прокидывается из `release build` (`cli.py`) — флейвор в этой точке известен.

### `vn build --use-artifact <sha>` и группа `vn validate`

**Current state:** NOT IMPLEMENTED, и сильнее, чем кажется: `use-artifact` встречается в `docs/ARCHITECTURE.md` **14 раз** и в ночном runbook, а во всём тулчейне ровно один раз — в *заголовке* схемы `tools/schemas/gen_manifest@1.schema.json:4`. У `vn build` есть только `--check` и `--profile` (`cli.py`). Группы `vn validate` не существует вовсе. При этом сам артефакт реален: `ci.yml` кладёт `game/generated/` на 30 дней.
**Potential automation:** `vn build --use-artifact <sha>` — скачать артефакт `generated-<sha>` через `gh run download`, распаковать в `game/generated/`, проставить пометку «генерат чужой» так, чтобы `vn build --check` про неё знал.
**Priority:** **P2**
**Expected benefit:** это аварийный тормоз: «компилятор сломан, но играть и писать текст надо сейчас». Сегодня инструкция в `docs/runbooks/pipeline-broken-at-night.md` — «скачайте артефакт и распакуйте руками», что работает, но требует помнить имя артефакта и не перепутать `sha`. Производство контента не ускоряет — спасает день, когда всё встало.
**Implementation idea:** флаг в `vn build` (`cli.py`); скачивание — через `gh` CLI, а не свой HTTP-клиент к GitHub API (не нужен ни токен в коде, ни новая зависимость). Группу `vn validate` **не заводить**: `--schemas`/`--budgets` уже покрыты `vn content lint` и `_check_budgets` (`cli.py`) — правильнее вычистить упоминания из `ARCHITECTURE.md`, чем плодить второй вход.

### Второй конфиг CI — СДЕЛАНО 2026-08-18 (удаление)

**Current state:** IMPLEMENTED. `.gitlab-ci.yml` удалён: 3 джобы против 8 у GitHub, без релиза и флейворов, LFS (а именно потеря LFS дала однажды битую сборку со шрифтами-указателями), ffmpeg, `vn loc keys --check`, smoke, сейв-корпуса и canary, — при этом `ci/README.md` называл «конфигом пайплайна» именно его, а `CODEOWNERS` покрывал GitLab-файл и не покрывал `/.github/`. Из двух вариантов (паритет либо удаление) выбран второй: вести восемь джоб в двух системах разом, когда вторая не запускается ни разу (GitLab-remote нет), — это удвоение работы без выгоды. Портативность даёт CLI: конфиг тонкий, смысл в командах `vn`. Сделано заодно: `ci/README.md` переписан, `CODEOWNERS` покрывает `/.github/`, `/content/{gallery,achievements,ui}`, `/packs/`, `/assets_src/`.
**Что осталось (честно):** гард `test_no_second_ci_platform_config` запрещает файлы других систем CI по имени (`.gitlab-ci.yml`, `.circleci`, `azure-pipelines.yml`, `Jenkinsfile`, `bitbucket-pipelines.yml`, `.drone.yml`) — систему с другим именем конфига он не поймает.
**Восстановление, если понадобится зеркало:** `git log --diff-filter=D -- .gitlab-ci.yml`, затем `git show <sha>^:.gitlab-ci.yml`.

### Детект дублей и осиротевших ассетов на стороне сырцов

**Current state:** NOT IMPLEMENTED в сторону сырцов. Осиротевшее удаляется только в `game/assets/` и только диффом манифеста (`tools/vn/src/vn/assets/pipeline.py:416-433`); в `assets_src/` не проверяется ничего. Коллизия «два сырца претендуют на один выход» ловится (`pipeline.py:289-290`), а вот два **байт-в-байт одинаковых** PNG под разными именами проходят молча и оба попадают в дистрибутив. Сырец, который не участвует ни в одной трансформации (лежит не в той зоне), тоже молчит.
**Potential automation:** `vn assets validate --sources`: группировка `assets_src/**` по blake3 (функция `_b3_bytes` уже есть, `pipeline.py:67-68`) → WARN на дубли; discovery-diff «файл в `assets_src/` не попал ни в один job» → WARN с указанием ожидаемой зоны.
**Priority:** **P2**
**Expected benefit:** становится ощутимым ровно тогда, когда DAZ-рендеры пойдут потоком: тысячи PNG, ручное переименование, «а этот я уже рендерил?». Плюс прямая экономия по бюджету ADR-0004 (error выше 50 МБ нетекстовых байт в `assets_src/`, `tools/vn/src/vn/content/lint.py:47,371-399`) — дубль съедает лимит вдвое быстрее.
**Implementation idea:** `tools/vn/src/vn/assets/pipeline.py` — второй проход по `_discover()` со сравнением множества обойдённых файлов и полного `rglob` по `assets_src/`. Хеши уже считаются для ключей кэша, дополнительного чтения диска почти нет.

### Контакт-листы и пруфы рендеров

**Current state:** NOT IMPLEMENTED. `vn char sheet` — заглушка фазы 2 (`cli.py`), `vn assets sheet` из `ARCHITECTURE.md` не существует. Единственное, что генерируется автоматически для глаз — скриншоты автопилота `.vncache/smoke/shot%03d.png` (21 штука за прогон) и `screen_<name>.png`.
**Potential automation:** `vn char sheet <key>` — контакт-лист собранных спрайтов: сетка «поза × эмоция × наряд» одной WebP + подписи, из уже собранных `game/assets/spr/<key>/**`. Аналогично `vn assets sheet cg/ch01` для CG главы.
**Priority:** **P2**
**Expected benefit:** приёмка глазами — обязательный ручной шаг, который нельзя убрать (см. Часть 3), но можно радикально ускорить: один лист вместо открывания 60 файлов по одному. Побочно ловит «эмоция отрендерена не в том наряде» — класс ошибок, который сейчас всплывает только в игре.
**Implementation idea:** Pillow уже в зависимостях и уже используется для композита в `tools/vn/src/vn/assets/ui.py:59-116`. Читать матрицу из `content/characters/<key>/character.yaml`, файлы — из `game/assets/spr/`, писать в `.vncache/sheets/`. В git не класть.

### `vn test paths` — полный обход графа

**Current state:** NOT IMPLEMENTED — `_stub(2)`, фаза 2 (`cli.py`). Сегодняшняя замена — 4 smoke-прогона с руками выписанными `--picks` в `nightly.yml:57-60`. Достижимость и тупики проверяет линт статически (`tools/vn/src/vn/content/lint.py:209-270`), но живого прохода по всем ветвям нет.
**Potential automation:** построить перечисление путей из того же графа, что рисует `vn content graph`, и прогнать `_autopilot_run` по каждому пути (или по покрывающему множеству), собрав достигнутые сцены и разблокированные элементы галереи из `gallery.json`, который автопилот уже пишет.
**Priority:** **P1**
**Expected benefit:** прямо ускоряет производство контента: сценарист узнаёт о недостижимой ветке в ту же ночь, а не когда игрок напишет. С ростом до 50 глав ручное выписывание `--picks` перестанет масштабироваться в первый же месяц.
**Implementation idea:** заменить `_stub(2)` в `cli.py` на реальную команду; перечисление путей — поверх `tools/vn/src/vn/content/graph.py` и `_exit_entries`/`resolve_target` из `tools/vn/src/vn/content/scenes.py`. Инфраструктура прогона уже готова целиком: `_autopilot_run` (`cli.py`) и протокол `VN_AUTOPILOT_*`.

### `vn test replay`, `screens`, `perf`

**Current state:** IMPLEMENTED (2026-08-19). `vn test screens` — тур по декларации `content/ui/screens.yaml` со структурным гейтом (включая «экран есть в игре, но не назван ни в туре, ни в исключениях»); `vn test paths` — покрытие сцен и рёбер выбора против деклараций, отчёт `.vncache/paths/coverage.json` (трасса `--picks chNN:` заходит в главу с собственной точкой входа — эпизод, DLC); `vn test replay` — повтор записи `ci/fixtures/replays/*.vnrec.json`, запись делает `vn test smoke --record`. `vn test revisit` — прогон реплея каждой сцены графа истории во всех состояниях входа ([ADR-0021](../adr/0021-story-flow-projections.md)); отчёт `replays.json`, гейт в `nightly.yml`. `vn test perf` **не создаётся** ([ADR-0019](../adr/0019-qa-run-family.md)): три измеримых числа (cold start, пик RSS, вес `.rpyc`) снимает прогон автопилота и гейтят бюджеты `runtime_budget_failures`.
**Potential automation:** `--screens <names>` у `vn test smoke` (десять строк — переменная уже читается); `screens` с эталонами и сравнением; `replay` поверх записи взаимодействий; `perf` поверх уже существующего замера холодного старта (`cli.py`).
**Priority:** **P3**
**Expected benefit:** скриншотные эталоны ловят регрессии вёрстки UI, которые не видит ни один линт. Но экраны в проекте меняются редко, а эталоны требуют постоянного обновления — выигрыш ниже стоимости сопровождения, пока UI не устоялся.
**Implementation idea:** начать с самого дешёвого: флаг `--screens` в `vn test smoke` (`cli.py`) и запись в `docs/` про `VN_AUTOPILOT_SCREENS` — это переводит существующий недокументированный механизм в разряд рабочих за минимальную цену.

### Схема `assets_manifest@1` — СДЕЛАНО 2026-08-08

**Current state:** IMPLEMENTED. Схема `tools/schemas/assets_manifest@1.schema.json` создана, и манифест `.vncache/assets-manifest.json` валидируется ею **при записи** (`tools/vn/src/vn/assets/pipeline.py:441-454`): ошибки схемы уходят в `rep.errors`, но сам файл пишется всё равно — иначе следующая сборка потеряет точечную очистку сирот. Нарушение G16 «каждый документ несёт зарегистрированную схему» закрыто; тест — `tools/vn/tests/test_assets.py:69` (`test_manifest_matches_registered_schema`).
**Что осталось:** чтение манифеста (`pipeline.py:393-399`, `cache_gc` `:465-471`) по-прежнему глотает исключения и схему не проверяет — битый файл деградирует в «нечего удалять», а не в внятную ошибку.
**Priority:** **P3**
**Implementation idea (остаток):** тот же `registry.validate` на пути чтения, с понятным сообщением вместо `except Exception: pass`.

### `content/flags.yaml` и `content/anchors.yaml`

**Current state:** NOT IMPLEMENTED — оба файла обязаны существовать (`tools/vn/src/vn/content/lint.py:34-42`, `REQUIRED_FILES`), схемы `flags@1` и `anchors@1` зарегистрированы, а **читателя нет ни одного**: ни компилятор, ни рантайм их не открывает. Пустые обязательные файлы.
**Potential automation:** либо реализовать (флаги — compile-time gating контента; якоря — точки инъекции модов, G10), либо убрать из `REQUIRED_FILES` вместе со схемами.
**Priority:** **P3**
**Expected benefit:** сегодня — только устранение путаницы: человек и агент видят файл в обязательных и достраивают несуществующую семантику. Реальная ценность появится вместе с модами, то есть не в этой фазе.
**Implementation idea:** решение принимать вместе с [паками и DLC](30-packs-and-dlc.md). До тех пор — не трогать, но и не выдумывать, будто оно работает.

### S3-бэкенд хранилища сырцов

**Current state:** NOT IMPLEMENTED честно: `backend_for()` на `type: s3` бросает `StorageError` «s3-бэкенд подключается при переходе команды на облако (G21: манифесты не изменятся) — пока используйте type: file» (`tools/vn/src/vn/assets/storage.py:129-133`), и это зафиксировано тестом. `type: file` работает целиком (push/pull/lock/status с иммутабельными версиями `<rel>/v<N>`), но каталог `~/vn-assets-store` **не существует** — сюда ни разу ничего не клали, `assets_src/**/*.manifest.json` ноль.
**Potential automation:** реализовать `S3Backend` с тем же интерфейсом (`put`/`get`/`exists`/локи).
**Priority:** **P3**
**Expected benefit:** для одного человека на одной машине — почти ноль: `type: file` на внешнем диске решает ту же задачу. Ценность появляется при втором участнике или при отказе от ADR-0004 (сейчас маленькие PNG живут прямо в git с потолком 50 МБ в линте).
**Implementation idea:** `tools/vn/src/vn/assets/storage.py`, класс рядом с `FileBackend` (`storage.py:71-118`). **Раньше этого** — просто начать пользоваться `type: file`: создать `~/vn-assets-store` и сделать первый `vn assets push`. Пока хранилище не запускалось ни разу, писать второй бэкенд бессмысленно.

### TTL и атомарность локов

**Current state:** NOT IMPLEMENTED. `acquire_lock` — это read-then-write без атомарного create (`storage.py:99-109`): двое гонщиков выигрывают оба. Владелец — `git config user.name`, то есть подделывается тривиально. `--force` снимает чужой лок без записи в аудит. TTL, эскалации на лида и уведомлений (`ARCHITECTURE.md:293,295,903-906`) нет.
**Potential automation:** условная запись (`If-None-Match` для S3 / `O_EXCL` для файлового бэкенда), поле `ttl` в лок-файле, лог снятий.
**Priority:** **P3**
**Expected benefit:** нулевой при команде из одного человека: лок защищает от коллеги, которого нет. Становится обязательным ровно в день появления второго художника.
**Implementation idea:** `storage.py:99-118`. Файловый бэкенд чинится одной строкой — `open(path, "x")` вместо `write_text`.

### ~~Фильтрация `VN_PACKS` по флейвору~~ — СДЕЛАНО

**Current state:** **IMPLEMENTED** обоими концами. Ownership-провайдер подключён ([ADR-0014](../adr/0014-platform-services.md)): `pack_registry.set_ownership_provider` вызывается в `game/framework/00_core/035_platform.rpy:75` на `init 999` при живом Steam, маппинг — `steam_dlc_appid` в манифесте пака. А дыра «`VN_PACKS` перечисляет все паки, поэтому public-сборка считает `nsfw` установленным и купленным» закрыта **рантайм-ным** вариантом, а не фильтрацией компилятора: `_PackRegistry.installed()` (`030_flow.rpy:77-91`) сверяет `VN_PACKS` со списком поставки `vn_build.packs` из `build_id.json`. Смысл `VN_PACKS` при этом не изменился — это по-прежнему «все паки дерева», и так и должно быть: скрипты глав уезжают в дистрибутив всегда, гейт логический (G9).

Почему выбран рантайм, а не компиляция: фильтровать `VN_PACKS` пришлось бы **на этапе сборки**, то есть генерат стал бы зависеть от флейвора — а он один на все флейворы (иначе `vn build --check` и кэш `.rpyc` разъедутся). Признак релизной сборки — сам факт `game/build_id.json` (`vn_build.is_release`): в dev-чекауте гейт открыт, иначе dev-прогон и smoke гейтились бы вслепую.

**Что осталось:** живого прогона релизной сборки с непустым `packs/nsfw/chapters/` не было — контента там пока нет. Гейт покрыт юнит-тестами, которые исполняют реальные `init python`-блоки на заглушке `store` (`tools/vn/tests/test_release.py`).

### ~~`early_content` не читает никто~~ — СДЕЛАНО как гейт релиза

**Current state:** **IMPLEMENTED** на границе релиза, самоактивирующимся правилом. `early_content_checks` (`release.py:403-438`) — проверка №4 гейта: при `early_content: false` и хотя бы одной главе `status: release` глава `status: draft` = **FAIL**, `playtest` = WARN, незнакомый статус трактуется как draft (fail-closed). Строгость выведена из кода, а не из вкуса: для `draft` конвейер сам понижает граф-проверки до warnings, то есть ненаписанная ветка легальна и у игрока станет «сцена недоступна». Контент **не** вырезается (сейв игрока мог на него сослаться) — гейт просто не пропускает сборку.

Проверка вынесена отдельной функцией, а не инлайном в `validate_release`, потому что полный гейт в тестах не прогнать (нужны SDK, ассеты, хранилище) — иначе она осталась бы непокрытой.

**Почему WARN, а не FAIL до первой `release`-главы:** требование «в публичном флейворе только зрелые главы» до первой зрелой главы невыполнимо — гейт запретил бы собрать что угодно, включая демо, а невыполнимый гейт учит игнорировать гейты (`release.py:422-427`). Норма включается сама, без отдельного флага, с появлением первой главы `status: release`.

**Что осталось (OPEN):** рантайм-потребителей у флага `vn_build.early_content` по-прежнему ноль — «плашка раннего доступа» или гейт из сцены пишутся с нуля. И решение к тому дню, когда строгость включится: ночной шаг «релизная сборка обоих флейворов» (`nightly.yml:71-75`), релиз по тегу и `steam-upload` покраснеют на первой же оставшейся `draft`-главе — довести главы, гонять `patron` либо объявить `early_content: true` у `public`.

## Сводная таблица приоритетов

Закрыто 2026-08-08 и из таблицы убрано: чтение `tools/vn.lock` в CI (было P1) и схема `assets_manifest@1` (было P3). В таблице остались только их «хвосты».

| Приоритет | Кандидат | Где живёт | Почему здесь |
|---|---|---|---|
| **P0** | ComfyUI: workflow-JSON в репозитории | новая зона `pipeline/workflows/`, схема + правило линта | Без файла графа генерация невоспроизводима, и автоматизировать нечего |
| **P0** | Батч-рендер DAZ через DAZ Script | `tools/daz/render.dsa` + `tools/vn/src/vn/assets/daz.py` | Самый крупный ручной блок конвейера |
| **P1** | ComfyUI: API-клиент (`vn assets gen`) | новый `assets/comfy.py` + группа в `cli.py` | Генерация из сессии превращается в ночную очередь |
| **P1** | Сборка секвенции кадров в видео | `tools/vn/src/vn/assets/pipeline.py` + `tools/vn/src/vn/assets/video.py` | Единственный разрыв цепочки рендер → Ren'Py для анимации |
| **P1** | `vn char new` / `vn char validate` | `tools/vn/src/vn/content/scaffold.py`, `cli.py` | Просроченная заглушка фазы 1; персонаж — вторая по частоте единица работы |
| **P1** | `vn test paths` | `cli.py`, поверх `tools/vn/src/vn/content/graph.py` | Ручные `--picks` не масштабируются дальше нескольких глав |
| **P2** | `vn content graph` для паков | `tools/vn/src/vn/content/graph.py:15` (+ тот же баг в `release.py:289`) | Десяток строк, функция уже написана |
| **P2** | Эмиссия группы `overlays` | `tools/vn/src/vn/content/images.py:178-221` | Мёртвый вес в дистрибутиве превращается в выразительность |
| **P2** | Side images | `tools/vn/src/vn/assets/pipeline.py:110-135`, `tools/vn/src/vn/content/images.py` | Документация обещает, код не даёт |
| **P2** | High-watermark для say-id | `tools/vn/src/vn/loc/keys.py`, схема `ledger@2` | Убирает «старый перевод под новым текстом» (сейчас смягчено fuzzy) |
| **P2** | Флейворный ключ у `build/rpyc-cache` | `cli.py` | Save-совместимость; чинить надо в коде, а не в `actions/cache` |
| **P2** | Детект дублей/осиротевших сырцов | `tools/vn/src/vn/assets/pipeline.py`, `_discover` | Станет ощутимым в день, когда пойдут тысячи рендеров |
| **P2** | Контакт-листы и пруфы (`vn char sheet`) | `cli.py`, Pillow | Ускоряет обязательную ручную приёмку |
| **P2** | `vn build --use-artifact <sha>` | `cli.py` + `gh run download` | Аварийный тормоз, а не ускоритель |
| **P3** | `vn test replay` / `screens` / `perf` | `cli.py` | Начать с флага `--screens` — механизм уже написан |
| **P3** | Транзитивные пины в `tools/vn.lock` (остаток G17) | `tools/vn.lock`, тест рядом с `test_ci_config.py` | Сам лок в CI уже читается; не закреплены транзитивные (`pygments`) |
| **P3** | Валидация манифеста ассетов **на чтении** | `tools/vn/src/vn/assets/pipeline.py:393-399,465-471` | Схема `assets_manifest@1` и проверка при записи уже есть; чтение всё ещё глотает исключения |
| **P3** | `content/flags.yaml` / `anchors.yaml` | решение вместе с модами | Либо реализовать, либо убрать из `REQUIRED_FILES` |
| **P3** | S3-бэкенд хранилища | `tools/vn/src/vn/assets/storage.py:129` | Сначала хотя бы запустить `type: file` |
| **P3** | TTL и атомарность локов | `tools/vn/src/vn/assets/storage.py:99-118` | Защита от коллеги, которого нет |
| **P3** | Ownership provider (Steam) | `030_flow.rpy:73` | Нет аккаунта партнёра — не на чем проверять |

Дорожная карта с распределением по фазам — [Roadmap](37-roadmap.md).

---

# Часть 3. Что НЕ автоматизировать

| Шаг | Почему остаётся ручным |
|---|---|
| **Художественная приёмка кадра** | Единственный критерий — «похоже на этого персонажа и на эту сцену». Формализуется хуже, чем стоит: любой автоматический порог даст ложные срабатывания там, где кадр хорош, и пропустит там, где он мёртвый. Автоматизировать нужно **подачу материала на приёмку** (контакт-листы, P2), а не решение |
| **Художественное направление: свет, композиция, постановка камеры** | Скриптовать стоит слой **перестановок** — та же сцена × N выражений × M ракурсов. Скриптовать авторство сцены дороже, чем сделать руками; это подтверждено и практикой DAZ-сообщества |
| **Обход логинов и капч за моделями** | Архитектурный запрет и запрет в этом хендбуке. `pipeline.py` умеет ровно правильную вещь: модели с `auth: manual` не качаются, вместо этого печатается URL, целевой путь и инструкция (`pipeline.py:428-432`), а для `auth: civitai_key` читается `CIVITAI_API_KEY` из окружения. Логин — действие человека |
| **Установка DAZ Studio / VaM / Sims 4** | Требуют аккаунта, EULA и логина в DIM/Steam. `tools/install-*.ps1` честно останавливаются на детекте и печати чеклиста — это правильная граница |
| **Принятие ADR-0008 (лицензии AI-моделей)** | Единственный **непринятый** ADR: развилка «использовать bigASP v2 и Civitai-LoRA / остаться на permissive-стеке / гибрид» — решение владельца о юридическом риске. Автогейт `commercial_use != allowed` технически возможен уже сейчас (поле есть в `comfyui_models@1`), но включать его до решения — значит зафиксировать выбор кодом |
| **Текст сцен и правки диалогов** | `content/**/*.scene.rpy` — авторская зона. Автоматизируются обвязка (say-id, обёртки сцен, реестры), но не реплики. Генератор диалогов ломает и голос, и трассируемость переводов |
| **Бамп версии и текст CHANGELOG для игрока** | `vn release changelog` даёт машинный дифф реестров («новые главы, новые сцены»). Абзац для игрока пишется руками — и это видно по факту: из пяти записей `docs/CHANGELOG.md` сгенерирована одна. Формулировка «что нового» — маркетинг, а не дифф |
| **Правка `game/generated/`, `game/assets/`, `game/tl/`** | Не «не автоматизировать», а «не трогать»: это производные зоны, их не должно быть ни в git, ни в руках. Любая правка будет затёрта следующей сборкой |

---

## Как изменить / Как расширить

**Добавить автоматизированный шаг в конвейер ассетов** (новая трансформация):
1. Ключ и версия в `TRANSFORMS` (`../../tools/vn/src/vn/assets/pipeline.py:38-46`).
2. Ветка discovery в `_discover()` (`pipeline.py:102`) — вернуть `(src, transform, out_rel, extra)`; все сегменты пути обязаны пройти `SLUG_RE`.
3. Ветка исполнения в `_transform`/`_transform_ui_panel` (`pipeline.py:221-248`), с учётом `profile`.
4. Тест в `tools/vn/tests/test_assets.py` — обязательно на попадание в кэш и на удаление осиротевшего.
5. Если выход должен стать Ren'Py-образом — эмиссия в `tools/vn/src/vn/content/images.py`, а не в конвейере ассетов.

**Добавить команду `vn`:** новая подкоманда в соответствующей группе `cli.py` (список групп — `cli.py`), логика — в модуле, а не в `cli.py`: там уже 2117 строк и почти нет тестов (из всей обвязки закрыт только `pack build`). Exit-коды держать по контракту `cli.py` (0/1/2/3), ошибки — только через `_fail` (`cli.py`), никаких голых трейсбеков.

**Добавить джобу в CI:** править `.github/workflows/` — единственную систему CI проекта. Держать `ci.yml` в бюджете быстрого прогона; всё тяжёлое (smoke-матрица, корпус, релизный dry-run) — в `nightly.yml`. Если джоба требует движка — `xvfb-run -a`: headless-режима у Ren'Py нет (G23).

**Автоматизировать шаг «слева от `assets_src/`»:** сначала завести декларацию (`*.render.yaml` по `daz_render@1` / `vam_render@1` / `sims4_render@1`) и убедиться, что `vn assets daz validate` её принимает. Автоматизация без декларации нечего запускать: именно декларация несёт камеру, разрешение, пресеты и лицензии.

## Чего НЕ делать

- **Не автоматизировать поверх несуществующей декларации.** В репозитории **ноль** `*.render.yaml`, `.duf`, `.provenance.json` и ComfyUI-графов. Скрипт батч-рендера, написанный раньше первой декларации, будет автоматизировать воображаемый формат.
- **Не менять параметр трансформации, не бампнув её версию** в `TRANSFORMS` (`pipeline.py:38-46`) — кэш отдаст старые байты как свежие, и это не заметит ни один гейт.
- **Не слать синтетический ввод на рабочий стол** (SendKeys, автокликеры) для прогона игры. Автопилот работает in-process через `VN_AUTOPILOT*` и таймеры в экранах; синтетический ввод недетерминирован и ломает CI под `xvfb`.
- **Не писать свой парсер `.rpy`.** Норма G24: разбор идёт только через SDK (`renpy.exe <root> vn_analyze`, `tools/vn/src/vn/content/analyze.py:37-70`). Любая «быстрая регулярка» разойдётся с движком на первом же нестандартном блоке.
- **Не автоматизировать обход логинов, капч и paywall'ов** за моделями и ассетами. Правильное поведение уже реализовано: печать инструкции и целевого пути.
- **Не добавлять зависимость ради одной автоматизации.** В `pyproject.toml` 7 рантайм-зависимостей, и `tools/vn.lock` их пинует — а с 2026-08-08 лок ещё и ставится в CI первым, то есть новая зависимость без пина приедет случайной версией. HTTP делается `urllib`/`curl` — так уже сделано в `pipeline._download`.
- **Не чинить проблему в CI, если она в коде.** Флейворный ключ `rpyc-cache` — живой пример: баг в `cli.py`, обход в `release.yml:68-73`. Локальная сборка остаётся сломанной.
- **Не считать `docs/ARCHITECTURE.md` описанием построенного.** `rpyc-compat`, каналы dev/beta/release, депоты Steam — NOT IMPLEMENTED; `vn validate`, `vn migrate`, `vn shell`, `vn test perf` — выведены из нормы осознанно (ADR-0017, ADR-0019); `--use-artifact` реализован 2026-08-18 (`.rpa`-архивы документ больше не требует: россыпь — норма §2.4).
- **Не запускать ComfyUI с `--listen 0.0.0.0`.** Эндпоинт неаутентифицирован, умеет писать файлы и исполнять Python кастом-нод.

## Проверка

```bash
# Что автоматизировано — работает ли оно прямо сейчас
vn doctor                                  # 8 проверок окружения тулчейна, exit 0
vn pipeline doctor                         # окружение рендера: ffmpeg/VP9, GPU, ComfyUI, модели, DAZ
vn build                                   # lint -> ассеты -> 21 выход генерата -> game/tl
vn build --check                           # CI-режим: ничего не пишет, краснеет на несвежем
python -m pytest tools/vn/tests -q         # 373 теста

# Автоматизация QA и релиза
vn test smoke --picks 0,0                  # прогон игры, скриншоты, бюджет холодного старта
vn save check && vn save corpus            # фикстуры сейвов + прогон в движке
vn release validate --flavor public        # 21 проверка гейта; сейчас 0 FAIL, 2 WARN, exit 0

# Побочные автоматизации, которые легко забыть
vn assets cache --dry-run                  # сколько мусора накопил кэш трансформаций
vn assets licenses                         # реестр лицензий vs декларации рендеров
vn loc keys --check && vn loc report       # свежесть say-id + покрытие переводов
vn content graph                           # граф сцен (паки в него НЕ попадают)
vn pack validate                           # api_level паков против фасада vn.*

# Проверить, что заглушка всё ещё заглушка (exit 3 — ожидаемо)
vn char new x; echo "exit=$?"
vn test paths;  echo "exit=$?"
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/cli.py` (2117 строк — вся поверхность автоматизации), `../../tools/vn/src/vn/assets/pipeline.py:38-46` (таблица трансформаций), `../../tools/vn/src/vn/release.py:313-551` (релизный гейт), `../../tools/vn/src/vn/pipeline.py:290-581` (окружение рендера и модели), `../../.github/workflows/{ci,nightly,canary,release}.yml`, `../adr/0006-daz-comfyui-video-pipeline.md`, `../adr/0008-ai-model-licensing-for-commercial-adult-content.md` (**не принят**), `../pipeline/phase-0.md` |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `.vncache/**`, `build/**` — производные зоны, любая правка затирается сборкой. `ci/fixtures/rpyc-line/**` — единственные `.rpyc` в git, носитель линии statement-имён (G6): пересоздаётся только через `vn save corpus --add`. `content/**/*.scene.rpy` — авторская зона, не генерировать текст |
| **Зависимости (что ломается ниже по течению)** | Новая трансформация без бампа версии в `TRANSFORMS` → кэш отдаёт устаревшие байты молча. Новый выход конвейера ассетов → его надо эмитить в `tools/vn/src/vn/content/images.py`, иначе Ren'Py его не увидит. Новая джоба CI → бюджет прогона `ci.yml`; тяжёлое идёт в `nightly.yml`. Изменение схемы → бамп `@N` в `tools/schemas/` + миграция существующих деклараций. Любая новая команда `vn` → exit-коды по контракту `cli.py` |
| **Валидация** | `vn doctor` → `vn build` → `vn build --check` → `python -m pytest tools/vn/tests -q` → `vn test smoke --picks 0,0` → `vn save corpus` → `vn release validate --flavor public` |
| **Частые ошибки** | 1) Считать `docs/ARCHITECTURE.md` описанием построенного: `--use-artifact`, `vn validate`, `vn test perf`, `rpyc-compat`, депоты Steam — NOT IMPLEMENTED (а `.rpa` — не долг, а норма §2.4: россыпь). 2) Искать `.gitlab-ci.yml`: его нет с 2026-08-18, пайплайн один — `.github/workflows/`, 5 workflow, 9 определений джоб. 3) Автоматизировать рендер/генерацию раньше, чем появится первая `*.render.yaml` и первый workflow-JSON — сейчас в репозитории ноль тех и других. 4) Писать свой парсер `.rpy` вместо моста SDK (G24). 5) Считать, что `vn content graph` и `vn release changelog` слепы к пакам — оба обходят `repo.chapter_zones` с 2026-08-18. 6) Считать `tools/vn.lock` неработающим — он ставится первым во всех 8 джобах установки тулчейна, и новая зависимость без пина в нём приедет случайной версией. 7) Добавить джобу CI без `-r tools/vn.lock` до editable или без `ffmpeg` до `vn build` — покраснеет `tools/vn/tests/test_ci_config.py`. 8) Писать в `game/build_id.json` сам patron-токен — документ уезжает игроку целиком; наружу идёт только `patron_tag` (ADR-0011) |
