# 25. Собственный движок: CLI `vn`

> **Статус подсистемы:** IMPLEMENTED — одна точка входа, 20 команд/групп верхнего уровня, честный контракт кодов возврата, ~50 живых подкоманд. **Но:** 14 подкоманд — заглушки с номером фазы, десяток команд из `ARCHITECTURE.md` не существует вовсе (`vn validate`, `vn build --use-artifact`), а тестами покрыта ровно одна команда CLI — `pack build`. Lock-файл тулчейна `tools/vn.lock` с 2026-08-08 **читается** всеми пайплайнами (§8).
> **Отвечает на вопрос:** «Какая команда `vn` мне нужна, что она делает, чем кончится и как добавить свою».

`vn` — единственный инструмент проекта (норма G1). Это Python-пакет `vn-tools` в `tools/vn/`, ставится editable-установкой и даёт команду `vn`. Он собирает ассеты, компилирует контент, гоняет линт, локализацию, QA-прогоны, релизный гейт и паки. Ren'Py он **вызывает**, но не заменяет: движок остаётся Ren'Py 8.5.3, а `vn` — производственная обвязка вокруг него. Код: `../../tools/vn/src/vn/` (8112 строк, 30 модулей), точка входа `vn = "vn.cli:main"` (`../../tools/vn/pyproject.toml:24`).

---

## Быстрый ответ

```bash
pip install -e "tools/vn[dev]"     # ставит команду vn (editable: правки кода видны сразу)
vn --version                       # vn, version 0.1.0   ← версия ТУЛИНГА, не игры
vn --help                          # список групп
vn assets --help                   # список подкоманд группы

vn doctor        # окружение: python/git/lfs/корень/схемы/шрифты/SDK   → exit 0|1
vn build         # lint → ассеты → генерат → game/tl → бюджеты          → build: OK
vn build --check # то же, но ничего не пишет (режим CI)
vn play          # запуск игры через RENPY_SDK
vn dev           # игра + вотчер по content/ и assets_src/
```

Коды возврата: **0** успех · **1** ошибка проверки/сборки (всегда с сообщением) · **2** usage error от click · **3** «команда появится в фазе N». `exit 3` — не провал сборки.

Три версии в проекте не путать:

| Что | Значение | Где | Кто бампает |
|---|---|---|---|
| версия тулинга | `0.1.0` | `../../tools/vn/src/vn/__init__.py:3`, `pyproject.toml:7` | engine-team |
| версия игры | `0.1.4` | `../../project.yaml:2` | релиз-менеджер |
| минимум тулинга для дерева | `"0.1"` | `../../project.yaml:4` (`min_tools`) | проверяет `vn doctor` |

---

## 1. Почему один CLI (G1)

Норма G1 требует единой точки входа. Практический смысл — не эстетика:

- **Одна установка.** `pip install -e "tools/vn[dev]"` — и человек, и CI-раннер, и AI-агент получают одинаковый набор операций. Нет каталога `scripts/` с `build.ps1`, `build.sh`, `rebuild_assets.py` и тремя вариантами одного и того же.
- **Один контракт ошибок.** Любая ошибка проходит через `_fail()` (`../../tools/vn/src/vn/cli.py:22-24`) и печатает `ошибка: <текст>` красным в stderr. Голых трейсбеков в нормальном пути нет — даже внутренняя ошибка компилятора ловится и оформляется (`cli.py:119-123`).
- **Один порядок операций.** `vn build` фиксирует последовательность lint → ассеты → компиляция → импорт переводов → бюджеты. Собрать «частично и в другом порядке» нельзя случайно — только явной подкомандой.
- **CI и человек делают одно и то же.** `.github/workflows/*.yml` и `.gitlab-ci.yml` вызывают ровно те же команды `vn`, что и разработчик. Воспроизвести падение CI = выполнить его строку локально.

Обратная сторона, о которой стоит знать: `cli.py` вырос до 1643 строк и покрыт тестами **почти никак**. Единственное исключение появилось 2026-08-08: `tools/vn/tests/test_release.py:141-192` импортирует `vn.cli.pack_build` и гоняет его через `click.testing.CliRunner` (3 теста). Всё остальное — разбор аргументов, коды возврата, `_stub`, автопилот, линия `.rpyc`, `save check|corpus` — по-прежнему без тестов. См. [Тестирование](27-testing.md).

---

## 2. Полное дерево команд

Статусы: **IMPL** — работает; **PART** — работает частично (в примечании — чем именно); **STUB** — заглушка `_stub(N)`, exit 3.

### 2.1 Верхний уровень

| Команда | Опции / аргументы | Что делает | Статус |
|---|---|---|---|
| `vn --version` | — | `vn, version 0.1.0` (`cli.py:42`) | IMPL |
| `vn doctor` | — | Самодиагностика окружения, 8–9 проверок с рецептами; `sys.exit(run_doctor())` (`cli.py:60-64`) | IMPL |
| `vn build` | `--check`, `--profile [full\|draft]` (def `full`) | lint → ассеты → компиляция → `game/tl` → бюджеты (`cli.py:84-153`) | IMPL |
| `vn play` | — | Запуск игры через `RENPY_SDK`; требует `game/generated/manifest.json` (`cli.py:183-199`) | IMPL |
| `vn bootstrap` | — | `doctor` → `assets build (full)` → `compile` → `loc import` (`cli.py:202-222`) | PART — сборка только локальная; скачивание из remote cache / CI-артефактов (G4) не реализовано, о чём честно сказано в docstring (`cli.py:206-207`) |
| `vn dev` | — | Запускает игру + вотчер `content/` и `assets_src/` в демон-потоке (`cli.py:225-276`) | IMPL |
| `vn package` | `--package` (multiple, def `("win",)`), `--timeout` (def 900), `--dest-suffix` (**hidden**) | `vn build` → перенос `.rpyc` прошлого релиза (G6) → `renpy compile` → `launcher distribute` → кэш `.rpyc` этого релиза (`cli.py:279-370`) | IMPL |
| `vn migrate` | — | Миграции схем деклараций | STUB — фаза 2 (`cli.py:371`) |
| `vn shell` | — | Docker-репро CI-окружения | STUB — фаза 2 (`cli.py:372`) |

### 2.2 `vn content` — «Контент: lint, compile, graph» (`cli.py:377-379`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `content lint` | `--layout/--no-layout` (def **True**) | Схемы, naming-конвенции, структура глав, битые exits; строгость привязана к `status` главы (G15) (`cli.py:382-396`) | IMPL |
| `content compile` | `--check` | Компиляция деклараций в `game/generated/` **без линта** (`cli.py:399-422`) | IMPL |
| `content graph` | `--out PATH` (def stdout) | Mermaid-граф сцен: узлы, exits с условиями, тупик `vn_end` (`cli.py:425-437`) | PART — обходит **только** `content/chapters/` (`tools/vn/src/vn/content/graph.py:15`); главы из `packs/*/chapters/` в граф не попадают. Проверено прогоном 2026-08-08: вывод содержит только `ch01`, `ch90` из `packs/ep_beach` отсутствует |

Подробности компилятора, линта и реестра схем — в [Контентный конвейер](08-content-pipeline.md), здесь не дублируются.

### 2.3 `vn chapter` / `vn scene`

| Команда | Аргументы | Что делает | Статус |
|---|---|---|---|
| `chapter new SLUG` | `SLUG` | Каталог `chNN_<slug>/` со скелетом (`chapter.yaml`, `vars.yaml`, `s010`) (`cli.py:447-459`) | IMPL |
| `scene new CHAPTER SLUG` | 2 позиционных | Пара `sNNN_<slug>.scene.{yaml,rpy}`, следующий номер с шагом 10 (`cli.py:467-481`) | IMPL |
| `scene stub CHAPTER SCENE_ID` | 2 позиционных | Placeholder-сцена для объявленной, но не написанной цели перехода (G15) (`cli.py:484-496`) | IMPL |

Обе команды после успеха печатают напоминание («владельца главы в CODEOWNERS», «добавить сцену в `scene_order`»). См. [Главы](09-chapters.md), [Сцены](12-scenes.md).

### 2.4 `vn assets` — «Конвейер ассетов: assets_src → game/assets» (`cli.py:510-512`)

| Команда | Опции / аргументы | Что делает | Статус |
|---|---|---|---|
| `assets build` | `--profile [full\|draft]` (def `full`) | Сборка `game/assets` из `assets_src` (`cli.py:515-519`) | IMPL |
| `assets validate` | — | Два уровня: сырцы (`build_assets(check=True)`) + ссылки контента (`compile_content(check=True)`); несвежие выходы — **warning**, не ошибка (`cli.py:522-547`) | IMPL |
| `assets watch` | `--profile [full\|draft]` (def **`draft`**) | Вотчер `assets_src` (`cli.py:550-568`) | PART — на `content/`-события передан `lambda: None` (`cli.py:566`), хотя вотчер их снимает: правки контента молча теряются |
| `assets cache` | `--gc`, `--dry-run` | Размер `.vncache/assets` и mark&sweep GC от манифеста сборки (`cli.py:744-764`) | IMPL |
| `assets licenses` | — | Сверка деклараций рендеров с `content/licenses.yaml`: ссылка есть, `game_use`, `nsfw_allowed` для выходов в `nsfw/**` (`cli.py:767-787`) | IMPL |
| `assets push PATHS...` | `PATHS` (nargs=-1, **required**, `exists=True`), `--storage` (def `"default"`) | Залить сырцы в хранилище (**требует лока**, G14) + обновить манифесты (`cli.py:894-908`) | IMPL / никогда не запускалось в этом репозитории |
| `assets pull` | `--scope`, `--edit` | Восстановить бинари сырцов по манифестам (`cli.py:911-924`) | IMPL / не запускалось |
| `assets lock REL_PATH` | `--release`, `--force` | Взять/снять лок; путь нормализуется `\`→`/` (`cli.py:937`) | IMPL / не запускалось |
| `assets status` | — | Версии, локальное состояние, держатели локов (`cli.py:943-956`) | IMPL — сейчас печатает «манифестов нет — сырцы ещё не пушились» |

#### `vn assets video` (ADR-0006, `cli.py:573-575`)

| Команда | Опции / аргументы | Что делает | Статус |
|---|---|---|---|
| `video build` | `--profile [full\|draft]` (def `full`) | Только видео-ветка: `_assets_build(..., only_transforms={"video2webm"})` (`cli.py:578-583`) | IMPL |
| `video validate [PATHS...]` | `PATHS` (nargs=-1, `exists=True`) | Кодек/пиксели/размеры/fps/луп/бюджет. Без аргументов — все `game/assets/mov/**/*.webm`; бюджет из `project.yaml budgets.video_file_mb`; workdir `.vncache/video-tmp` (`cli.py:586-627`) | IMPL |
| `video inspect PATH` | `PATH` (`exists=True`) | Свойства видео + сайдкары `.webm.meta.json` и `.provenance.json` (`cli.py:630-647`) | IMPL / **UNDOCUMENTED** — нет упоминаний в `docs/` вне хендбука |

#### `vn assets daz` / `vam` / `sims4` — одинаковая форма (`cli.py:652-741`)

| Команда | Опции | Статус |
|---|---|---|
| `assets daz validate` | `--scope` (подпуть в `assets_src/daz`), `--no-provenance` | IMPL (`cli.py:657-679`) |
| `assets vam validate` | те же | IMPL (`cli.py:687-709`), источник объявлен опциональным |
| `assets sims4 validate` | те же | IMPL (`cli.py:718-741`), ADR-0007, опциональный задел |

Все три проверяют схему деклараций `*.render.yaml`, наличие сцен и выходов, и по умолчанию **пишут провенанс** для готовых рендеров. Деклараций в репозитории пока ноль — команды печатают «деклараций нет» и выходят с 0. См. [DAZ Studio](17-daz-studio.md), [Virt-a-Mate](18-vam.md), [The Sims 4](19-sims4.md).

#### `vn assets provenance` (`cli.py:790-792`)

| Команда | Опции / аргументы | Что делает | Статус |
|---|---|---|---|
| `provenance record ARTIFACT` | `--source`, `--workflow`, `--note`, `--model`, `--seed` (int) | Записать провенанс; PNG из ComfyUI разбирается автоматически из tEXt-чанков (`cli.py:795-820`) | IMPL / ни разу не выполнялось (ноль сайдкаров в репозитории) |
| `provenance workflow ARTIFACT` | `--out PATH` (def stdout) | Восстановить workflow-граф ComfyUI по `workflow_hash` или инлайн-fallback (`cli.py:823-854`) | IMPL / **UNDOCUMENTED** |
| `provenance verify` | `--scope` | Сверка цепочек: схема, хэш артефакта, хэши источников (`cli.py:857-875`) | IMPL / не выполнялось |

### 2.5 `vn char` — «Персонажи: new, validate, sheet» (`cli.py:958`)

| Команда | Статус |
|---|---|
| `char new` | STUB — **фаза 1** |
| `char validate` | STUB — **фаза 1** |
| `char sheet` | STUB — фаза 2 |

Персонажей сейчас заводят руками, редактируя `content/characters/<id>/character.yaml` (персонаж — **каталог**: компилятор глобит `content/characters/*/character.yaml`, `tools/vn/src/vn/content/compile.py:665`). См. [Персонажи](10-characters.md).

### 2.6 `vn loc` — «Локализация (раздел 5, G8)» (`cli.py:961-963`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `loc keys` | `--check` | Дописать say-id и маркеры меню в авторские `scene.rpy` **парсером Ren'Py** (G24); `--check` — CI-режим (`cli.py:966-993`) | IMPL |
| `loc add CODE` | `--name` | Создать пакет `loc/po/<code>/` (ADR-0005) и сразу выполнить `extract` (`cli.py:996-1016`) | IMPL |
| `loc extract` | — | Обновить PO всех языков из ledger/strings/персонажей (`cli.py:1019-1032`) | IMPL |
| `loc import` | — | PO → `game/tl/<lang>/`; ручные правки `tl` запрещены (`cli.py:1035-1051`) | IMPL |
| `loc pseudo` | — | Псевдолокаль `pseudo` + импорт (`cli.py:1054-1069`) | IMPL |
| `loc report` | — | Покрытие по языкам и число fuzzy (`cli.py:1072-1086`) | IMPL — но **без** `--gate/--format`: гейтинг живёт только в релизном гейте (`release.py:408-434`) |

Подробно — [Локализация](14-localization.md).

### 2.7 `vn voice` — «Озвучка (C5)» (`cli.py:1087`)

`voice manifest`, `voice import`, `voice tts`, `voice validate` — все четыре STUB, **фаза 2**.

### 2.8 `vn save` (`cli.py:1093-1096`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `save check` | — | Оффлайн: каждая `ci/fixtures/saves/*.save` открывается как zip, читается член `json`, требуется целочисленный `vn_save_schema` (`cli.py:1099-1124`) | IMPL |
| `save corpus` | `--add NAME`, `--timeout` (def 180) | Каждая фикстура **реально загружается** в игре с `--savedir`, миграции идут в `after_load`, автопилот доигрывает; линия `.rpyc` восстанавливается из `ci/fixtures/rpyc-line/` (`cli.py:1167-1256`) | IMPL — 2 фикстуры: `schema2-demo` (текущая схема) и `schema1-demo` (старая), на второй миграция `0002` реально исполняется в игре |
| `save migrate` | — | Оффлайн-миграция файла сейва | STUB — фаза 3 (`cli.py:1259-1260`) |

### 2.9 `vn test` — «QA-прогоны (7.4)» (`cli.py:1263-1265`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `test smoke` | `--picks` (def `""`), `--lang` (def `""`), `--timeout` (def 180) | In-process автопилот: авто-advance, авто-выбор, скриншоты движка, проверка бюджета `cold_start_s` (`cli.py:1347-1401`) | IMPL |
| `test replay` | — | Замысел (`../ARCHITECTURE.md:3672`): автопилот скармливает записанные индексы выборов из `*.vnrec.json` | STUB — фаза 2 (`cli.py:1404-1405`) |
| `test screens` | — | Замысел (`../ARCHITECTURE.md:3720`): скриншоты экранов против эталонов с допуском по пикселям | STUB — фаза 3 (`cli.py:1404-1405`) |
| `test paths` | — | Замысел (`../ARCHITECTURE.md:3685`): обход графа выборов без полного перебора | STUB — фаза 2 (`cli.py:1404-1405`) |

`--lang` умеет отдельный случай: если указан исходный язык, подставляется маркер `@source` (иначе `change_language` молча показал бы исходный язык и дал ложно-зелёный прогон, `cli.py:1354-1367`). См. [Тестирование](27-testing.md).

### 2.10 `vn pipeline` — «Окружение production-конвейера» (`cli.py:1409-1411`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `pipeline doctor` | `--comfyui` (def `VN_COMFYUI`, затем `D:/ComfyUI`, `C:/ComfyUI`, `~/ComfyUI`) | PASS/WARN/FAIL: Python, ffmpeg/VP9, GPU, CUDA/PyTorch, ComfyUI, модели, DAZ, диски, SDK (`cli.py:1414-1422`) | IMPL |
| `pipeline models` | `--pull`, `--all`, `--only <ids>`, `--comfyui` | Статус моделей по `tools/comfyui-models.yaml`; `--pull` — загрузка (`cli.py:1425-1461`) | IMPL — **грабля:** условие `if pull or only_set` (`cli.py:1442`), поэтому `--only` **сам по себе запускает скачивание**, а не фильтрует список |

### 2.11 `vn release` (`cli.py:1466-1468`)

| Команда | Опции | Что делает | Статус |
|---|---|---|---|
| `release changelog` | — | Обновляет `docs/CHANGELOG.md` и `ci/release-manifest.json` по диффу реестров, штампует `id_registry` (G7) (`cli.py:1471-1489`) | PART — нет `--from/--audience`; главы из `packs/*/chapters/` не видит |
| `release validate` | `--flavor` (**required**) | Предрелизный гейт: 19 проверок PASS/WARN/FAIL (`cli.py:1492-1505`) | IMPL |
| `release build` | `--flavor` (**required**), `--patron-token`, `--package` (multiple), `--timeout` (def 900) | `vn build` → гейт → `game/build_id.json` → `vn package` с суффиксом `-<flavor>` → `build-info.json`; `build_id.json` и скопированный `THIRD-PARTY-NOTICES.md` снимаются в `finally` (`cli.py:1508-1562`) | IMPL — `--patron-token` это **вход**: наружу уходит только производная метка `patron_tag` (ADR-0011, см. ниже) |
| `release steam` | — | Аплоад депотов в Steam (нужен аккаунт партнёра) | STUB — фаза 3 (`cli.py:1565`) |

Сборка идёт **до** гейта осознанно: в свежем чекауте генерата нет вовсе, и проверка «генерат свеж» валила бы каждый релиз (комментарий `cli.py:1526-1528`). См. [Сборка и релиз](29-build-and-release.md).

**`--patron-token` ≠ то, что уедет игроку (ADR-0011, 2026-08-08).** `game/build_id.json` целиком лежит внутри дистрибутива — он нужен рантайму (`060_build_info.rpy`) и ни одно правило `build.classify` его не исключает. Поэтому до `build_info@2` в поле `patron_token` уезжал сам секрет (в CI — `secrets.PATRON_TOKEN`). Теперь `compute_build_info` (`release.py:230-255`) кладёт в документ поле `patron_tag` = `release.patron_tag(token)` (`release.py:206-227`) — `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex. Вотермарка = `build_id + " · " + patron_tag` (`060_build_info.rpy:42-45`). Схема бампнута `build_info@1` → `build_info@2`; `build_info@1` осталась в реестре с пометкой «устарела» — чтобы читались `build-info.json` сборок до 0.1.5. Проверено сквозным прогоном: в patron-дистрибутиве 1663 файла, токен не встречается ни в одном.

**Требование к процессу:** токен-метка получателя обязана быть случайной (`secrets.token_hex(16)` и подобное). Короткий низкоэнтропийный токен подбирается перебором по 8-символьной метке — это единственное, что метка не защищает.

### 2.12 `vn pack` — «DLC/voice-паки (G9/G10)» (`cli.py:1568-1570`)

| Команда | Аргументы | Что делает | Статус |
|---|---|---|---|
| `pack validate` | — | Схема манифестов паков + `api_level` против фасада `VN_API_LEVEL` (`cli.py:1573-1597`) | IMPL / **UNDOCUMENTED** |
| `pack build PACK_ID` | `PACK_ID` | Zip: `packs/<id>/manifest.yaml` + `game/generated/scenes/<ch>/*` → `build/packs/<id>.zip` (`cli.py:1600-1639`) | PART — охранник починен (`cli.py:1624-1626`): сцены считаются отдельно от манифеста, «главы объявлены, а генерата нет» = exit 1 **до** создания zip; пак-контейнер без глав (`packs/nsfw`) собирается штатно и печатает предупреждение «не объявляет глав» (`cli.py:1635-1637`). Остаётся: в архив идут только сцены и манифест (ни ассетов, ни `tl/`), и охранник требует «хоть одну сцену на весь пак», а не по каждой объявленной главе |

См. [Паки и DLC](30-packs-and-dlc.md).

### 2.13 Чего в CLI нет вообще

Эти команды описаны в `../ARCHITECTURE.md`, но не реализованы и не заглушены — click ответит `Error: No such command`, **exit 2**:

| Что обещано | Где обещано | Реальность |
|---|---|---|
| `vn build --use-artifact <sha>` | `../ARCHITECTURE.md` (14 упоминаний) | NOT IMPLEMENTED. У `build` только `--check` и `--profile` (`cli.py:85-87`). Строка `use-artifact` во всём тулинге встречается ровно один раз — в **title** схемы `tools/schemas/gen_manifest@1.schema.json` |
| `vn validate --schemas` / `--budgets` | `../ARCHITECTURE.md` | NOT IMPLEMENTED — группы `vn validate` не существует |
| `vn content lint --strict/--arch/--schemas` | `../ARCHITECTURE.md` | NOT IMPLEMENTED — есть только `--layout/--no-layout` |
| `vn content who-writes`, `vn content rename`, `vn content compile --watch`, `vn content graph --chapter` | `../ARCHITECTURE.md` | NOT IMPLEMENTED |
| `vn play --scene <id>` | `../ARCHITECTURE.md` | NOT IMPLEMENTED — `play` не принимает опций (`cli.py:183-184`) |
| `vn bootstrap --role <role>` | `../ARCHITECTURE.md`, `../../README.md:11` | NOT IMPLEMENTED — `bootstrap` без опций |
| `vn loc screenshots`, `vn loc report --gate`, `vn loc extract --push` | `../ARCHITECTURE.md` | NOT IMPLEMENTED |
| `vn char report`, `vn assets sheet` | `../ARCHITECTURE.md` | NOT IMPLEMENTED |
| `vn test perf --budgets`, `vn test smoke --affected`, `vn test smoke --menu-only` | `../ARCHITECTURE.md` | NOT IMPLEMENTED — команды `test perf` нет вовсе |
| `vn release changelog --from`, `vn save corpus --report` | `../ARCHITECTURE.md` | NOT IMPLEMENTED |

Никогда не берите синтаксис команды из `../ARCHITECTURE.md` — это целевой документ. Единственный источник истины по флагам — `vn <cmd> --help` и `cli.py`.

---

## 3. Контракт кодов возврата

Объявлен в docstring корневой группы (`cli.py:46-47`) и соблюдается:

| Код | Значение | Где реализовано | Что это значит для CI/скрипта |
|---|---|---|---|
| `0` | успех | нормальный выход | продолжать |
| `1` | ошибка проверки или сборки | `_fail()` (`cli.py:22-24`): `ошибка: <msg>` красным в **stderr** | красный билд, чинить |
| `2` | usage error | резервирует click; сам код 2 никогда не возвращает (комментарий `cli.py:37`) | опечатка в команде/флаге, а не поломка проекта |
| `3` | не реализовано в этой фазе | `_stub()` (`cli.py:34-38`): жёлтое `эта команда появится в фазе {phase} (раздел 8 ARCHITECTURE.md)` в **stdout**, затем `sys.exit(3)` | **НЕ провал.** Честная заглушка |

Практическое следствие: в shell-обвязке и в CI отделяйте 3 от 1.

```bash
vn voice tts || rc=$?
if [ "${rc:-0}" -eq 3 ]; then echo "ещё не фаза — пропускаем"; else exit "${rc:-0}"; fi
```

Проброшенные коды (команда возвращает не свой код, а чужой):

| Команда | Что возвращается |
|---|---|
| `vn doctor` | `run_doctor()` — 1 при любом hard-fail, иначе 0 (`doctor.py:144-153`) |
| `vn pipeline doctor` | `run_pipeline_doctor()` — 1 при любом FAIL |
| `vn pipeline models --pull` | `pull_models()` — 1 если какая-то загрузка провалилась; ручные шаги (auth `manual`) провалом **не** считаются |
| `vn play` | код выхода самого движка: `sys.exit(subprocess.run(cmd).returncode)` (`cli.py:199`) |

`vn build` дополнительно оборачивает любое неожиданное исключение компилятора в exit 1 с сообщением `внутренняя ошибка компилятора: <Type>: <msg>` и трёхкадровым трейсбеком (`cli.py:119-123`) — контракт «exit 1 всегда с сообщением» соблюдается даже при внутреннем баге.

Проверено прогоном 2026-08-08: `vn char new` → 3; `vn voice tts` → 3; `vn char new x` (лишний аргумент) → 2; `vn build` вне репозитория → 1.

---

## 4. Полный список заглушек по фазам

Всё, что печатает «появится в фазе N» и выходит с 3 — исчерпывающе:

| Фаза | Команды | Регистрация |
|---|---|---|
| **1** | `char new`, `char validate` | `cli.py:958` |
| **2** | `migrate`, `shell` | `cli.py:371`, `cli.py:372` |
| **2** | `char sheet` | `cli.py:958` |
| **2** | `voice manifest`, `voice import`, `voice tts`, `voice validate` | `cli.py:1087` |
| **2** | `test replay`, `test paths` | `cli.py:1404-1405` |
| **3** | `save migrate` | `cli.py:1259-1260` |
| **3** | `test screens` | `cli.py:1404-1405` |
| **3** | `release steam` | `cli.py:1565` |

Итого 14 заглушек (пересчитано по таблице выше и по `grep -n '_stub' cli.py`). Обратите внимание на аномалию: `char new` и `char validate` помечены **фазой 1**, то есть по плану они должны существовать уже сейчас. Персонажей приходится заводить редактированием YAML вручную.

Заглушки бывают двух видов в коде:

```python
main.command(name="migrate", help="Миграции схем деклараций (фаза 2).")(_stub(2))   # одиночная
_stub_group("voice", "Озвучка (C5).", {"manifest": 2, "import": 2, "tts": 2, "validate": 2})  # группа
```

`_stub_group` (`cli.py:501-505`) создаёт `click.Group` и вешает на каждую подкоманду `_stub(phase)` с автоматическим help-текстом.

---

## 5. Как находится корень репозитория

`../../tools/vn/src/vn/repo.py:15-23`:

```python
def find_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / "project.yaml").is_file() and (cand / "tools" / "schemas").is_dir():
            return cand
    raise RepoError("не найден корень репозитория: нужен project.yaml + tools/schemas/ ...")
```

| Факт | Следствие |
|---|---|
| Маркер — **оба** признака сразу: файл `project.yaml` **и** каталог `tools/schemas/` | Голый `project.yaml` в чужом каталоге корнем не считается |
| `.git` не участвует | Работает в архиве, в worktree, в развёрнутой копии без истории |
| Идёт от CWD **вверх** по `parents`, первое совпадение | Можно вызывать `vn` из `content/chapters/ch01_awakening/` — найдётся тот же корень |
| Не смотрит на аргументы команды | Нельзя «указать корень флагом»: только `cd` |

Вне репозитория: `RepoError` → `_root()` (`cli.py:27-31`) → `_fail()` → красное `ошибка: не найден корень репозитория…` в stderr, **exit 1**. Исключение — `vn doctor`: он вызывает `find_root()` в собственном `try` (`doctor.py:80-84`), продолжает с `root = None` и печатает полный отчёт, помечая отсутствие корня как hard-fail. То есть `vn doctor` осмысленно работает откуда угодно, всё остальное — нет.

Прочие помощники `repo.py`: `load_yaml(path)` (всегда `encoding="utf-8"`, `:26-28`), `load_project(root)` (`:31-32`), `git_sha(root)` = `git rev-parse --short HEAD` с глухим `except Exception: return "nogit"` (`:35-43`) — именно поэтому сборка без git не падает, а помечает генерат как `nogit`.

---

## 6. Windows-специфика

Проект разрабатывается на Windows 11, и в коде это видно.

### 6.1 Кодировка консоли — главная аккомодация

Колбэк корневой группы (`cli.py:49-55`):

```python
# Windows-консоль/пайп по умолчанию в locale-кодировке (cp1251): без этого
# русские сообщения в CI — кракозябры, а '✓' в doctor — UnicodeEncodeError.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
```

Именно поэтому `run_doctor()` может позволить себе голый `print()` с символами `✓ ! ✗` (`doctor.py:146-150`). CI дополнительно ставит `PYTHONIOENCODING: utf-8` во всех четырёх workflow (`.github/workflows/ci.yml:16`, `canary.yml:14`, `nightly.yml:15`, `release.yml:22`).

**Грабля (проверено 2026-08-08, ранее не задокументирована):** `vn --help` **корневой** группы печатается ДО того, как колбэк успевает переконфигурировать потоки — click обрабатывает `--help` как eager-параметр. На консоли/в пайпе без `PYTHONIOENCODING` русский текст корневого help выходит в cp1251 (`file` определяет вывод как `Non-ISO extended-ASCII text`). Help любой подкоманды и любой группы (`vn content --help`, `vn doctor --help`) уже в UTF-8, потому что к тому моменту колбэк отработал. Лечится тем же `PYTHONIOENCODING=utf-8`. В CI не проявляется — там переменная выставлена.

### 6.2 Выбор исполняемого файла SDK

`renpy.exe` на win32, иначе `renpy.sh` — шесть мест: `cli.py:194-198` (`play`), `264` (`dev`), `337` (`package`), `1313` (`_autopilot_run`), `tools/vn/src/vn/content/analyze.py:31`.

### 6.3 Убийство дерева процессов по таймауту

`renpy.exe` — лаунчер: убить только его недостаточно, игра переживёт (`cli.py:1322-1335`):

```python
popen = subprocess.Popen(cmd, env=env, start_new_session=(sys.platform != "win32"))
...
if sys.platform == "win32":
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(popen.pid)], capture_output=True)
else:
    os.killpg(os.getpgid(popen.pid), signal.SIGKILL)
```

### 6.4 Пути

- `vn assets lock` нормализует пользовательский ввод: `rel_path.replace("\\", "/")` (`cli.py:937`) — можно скопировать путь из проводника.
- В выводе пути всегда через `.as_posix()` (`cli.py:352, 458, 479, 820, 1210, 1627`), чтобы вывод не зависел от платформы.
- Анализ сцен нормализует ключи от build-bridge через `.replace("\\", "/")` с fallback на исходную форму (`tools/vn/src/vn/content/compile.py:749-750`).

### 6.5 Реестр Windows и `setx`

`pipeline.py` читает `winreg` (всё под `sys.platform == "win32"` + `except ImportError`): DAZ Studio (`HKLM\SOFTWARE\DAZ\Studio6|5|4`), библиотеки Steam (`HKCU\Software\Valve\Steam` + разбор `libraryfolders.vdf`), The Sims 4 (`HKLM\SOFTWARE\Maxis\The Sims 4` и `WOW6432Node`). Отдельно `_civitai_key_in_registry()` (`pipeline.py:318-330`) читает `HKCU\Environment\CIVITAI_API_KEY`, чтобы отличить «ключа нет» от «`setx` выполнен, но текущий процесс унаследовал старое окружение», и напечатать «откройте НОВЫЙ терминал». Ровно та же грабля касается `RENPY_SDK`: `setx` виден только новым процессам.

### 6.6 Имя слота сейва в Ren'Py 8.5

Слот получил токен локации (`1-1-LT1.save`), поэтому `save corpus` кладёт в временный savedir **оба** варианта имени, `1-1-LT1.save` и `1-1.save` (`cli.py:1228-1231`), и ищет фикстуру по маске `1-1*.save` (`cli.py:1195`).

### 6.7 Явный UTF-8 везде

Каждый `read_text`/`write_text` в тулинге передаёт `encoding="utf-8"`; чтение трейсбеков и ini добавляет `errors="replace"` (`cli.py:1253, 1375, 1397`).

---

## 7. Архитектура пакета

```
tools/vn/
  pyproject.toml            вн. имя дистрибутива vn-tools, entry point vn = vn.cli:main
  src/vn/
    __init__.py    3        __version__ = "0.1.0"
    cli.py      1643        ВСЕ команды click; никакой логики кроме печати и склейки
    repo.py       43        find_root / load_yaml / load_project / git_sha
    doctor.py    153        vn doctor: 8-9 проверок, sdk_path(), детект LFS-указателей шрифтов
    devloop.py    56        polling-вотчер для vn dev и vn assets watch
    schemas.py    51        SchemaRegistry: загрузка tools/schemas/*.schema.json + validate()
    pipeline.py  581        vn pipeline doctor|models: внешнее окружение (ffmpeg/GPU/ComfyUI/DAZ)
    release.py   481        бюджеты, changelog, флейворы, build_info@2 + patron_tag, гейт (19 проверок)
    content/
      compile.py 923        Content Compiler: 19 выходов + manifest.json
      lint.py    411        34 правила, layout-проверка, статус-градация G15
      scenes.py  339        контракт авторского .rpy + эмиссия label-обвязки
      images.py  246        реестр образов: image / layeredimage
      scaffold.py 137       vn chapter new / scene new / scene stub
      analyze.py  70        мост в парсер Ren'Py: renpy.exe <root> vn_analyze (G24) + кэш
      graph.py    45        Mermaid-граф сцен
    assets/
      pipeline.py 512       7 трансформаций, контентно-адресуемый кэш, GC, осиротевшие,
                            валидация манифеста по assets_manifest@1
      provenance.py 380     цепочки провенанса, разбор tEXt-чанков ComfyUI PNG
      video.py    326       VP9/WebM, loop-валидация, mov_meta@1
      storage.py  290       хранилище сырцов: file-бэкенд, локи (G14/G21)
      ui.py       137       ADR-0009: панели → 9-patch WebP → Frame
      psd.py      126       нарезка PSD по конвенции слоёв
      licenses.py 109       реестр лицензий, гейт коммерческого использования
      sims4.py     80  vam.py 78  daz.py 77   валидаторы деклараций внешних 3D-источников
    loc/
      po.py       566       PO round-trip, пакеты языков, псевдолокаль, отчёт покрытия
      keys.py     249       say-id и маркеры меню, ledger
  tests/                    19 файлов test_*.py + conftest.py, 152 теста, 3103 строки
```

**Конвенция сокращений в хендбуке.** Ссылки вида `tools/vn/src/vn/content/lint.py:20-53`, `tools/vn/src/vn/loc/po.py:44`, `tools/vn/src/vn/assets/pipeline.py:38-46` — это **сокращение относительно `tools/vn/src/vn/`**, а не путь от корня репозитория. Каталоги `content/` и `loc/` в корне — совсем другие зоны (YAML-декларации и обмен с переводчиками), Python-файлов там нет. Полная форма первого сегмента: `tools/vn/src/vn/content/lint.py`, `tools/vn/src/vn/loc/po.py`, `tools/vn/src/vn/assets/pipeline.py`.

### 7.1 Разделение ответственности

`cli.py` — **только** обвязка: разбор аргументов, вызов функции из модуля, печать отчёта, выбор кода возврата. Вся логика живёт в модулях и тестируется отдельно от CLI. Отсюда правило: новая функциональность идёт в модуль, в `cli.py` попадает только 10–20 строк.

### 7.2 Ленивые импорты

На уровне модуля `cli.py` импортирует только `json, os, subprocess, sys, pathlib.Path, click`, `__version__` и `repo` (`cli.py:8-19`). Все остальные импорты — **внутри тел команд**: 58 таких строк.

```python
@main.command()
def doctor():
    """Самодиагностика окружения."""
    from .doctor import run_doctor          # ← импорт внутри команды
    sys.exit(run_doctor())
```

Зачем: `vn --version` и `vn --help` не должны тянуть `jsonschema`, `Pillow`, `psd-tools`, `polib` и `blake3`. Измерено 2026-08-08: `python -m vn.cli --version` — **0.078 с** полного цикла процесса (три прогона: 0.079 / 0.078 / 0.077). Это ощутимо, когда `vn` вызывается в цикле из скриптов и вотчеров. Держите новый импорт внутри команды.

### 7.3 Кому нужен Ren'Py SDK

| Команда | Нужен SDK? | Через что |
|---|---|---|
| `vn doctor`, `vn content lint`, `vn content graph`, `vn loc *`, `vn assets *` (кроме сборок с новыми сценами) | нет | — |
| `vn build` / `vn content compile` | **да, если в `content/` есть сцены** | `analyze_scene_files` → `renpy.exe <root> vn_analyze` (`tools/vn/src/vn/content/analyze.py:37-70`) |
| `vn play`, `vn dev`, `vn package`, `vn release build` | да | прямой запуск `renpy.exe` |
| `vn test smoke`, `vn save corpus` | да | `_autopilot_run` (`cli.py:1285-1344`) |

SDK ищется **только** через переменную окружения: `sdk_path()` читает `RENPY_SDK` и требует наличия `<path>/renpy.py` (`doctor.py:24-30`). Ни поиска по PATH, ни дефолтных путей установки нет. Все потребители SDK в CLI ходят через эту функцию, кроме `tools/vn/src/vn/content/analyze.py:23-34` (`sdk_renpy_exe()`), где та же проверка сделана отдельно и с другим сообщением.

### 7.4 Реестр схем

`SchemaRegistry` (`schemas.py:16-51`) строится **на каждый вызов заново** — синглтона нет; 13 мест в `tools/vn/src/vn/` создают собственный экземпляр (`doctor.py:99`, `tools/vn/src/vn/content/lint.py:114`, `tools/vn/src/vn/content/compile.py:591`, `release.py:261,292`, `cli.py:1580`, `pipeline.py:264`, шесть модулей в `assets/` — включая `assets/pipeline.py:450`, где с 2026-08-08 валидируется манифест сборки). Внутри экземпляра валидаторы `Draft202012Validator` мемоизируются по schema-id (`schemas.py:22, 43-46`). Правила именования и `const`-проверка — в [Контентный конвейер §8](08-content-pipeline.md).

В `tools/schemas/` **36 схем** (было 34 до 2026-08-08): добавлены `assets_manifest@1` — под манифест `.vncache/assets-manifest.json`, и `build_info@2` — замена `build_info@1` по ADR-0011. `build_info@1` из реестра не удалена: она нужна, чтобы читались артефакты сборок до 0.1.5.

---

## 8. Зависимости и pinning

`../../tools/vn/pyproject.toml`:

| Поле | Значение |
|---|---|
| build backend | `setuptools.build_meta`, `requires = ["setuptools>=68"]` |
| name / version | `vn-tools` / `0.1.0` |
| `requires-python` | `>=3.10` (проект де-факто гоняется на 3.12: CI `setup-python 3.12`, машина владельца 3.12.10) |
| layout | src-layout, `[tool.setuptools.packages.find] where = ["src"]` |
| entry point | `vn = "vn.cli:main"` |
| dependencies | `click>=8.1`, `PyYAML>=6.0`, `jsonschema>=4.21`, `blake3>=0.4`, `Pillow>=10.0`, `psd-tools>=1.9`, `polib>=1.2` |
| extras | `dev = ["pytest>=8.0"]` |

`../../tools/vn.lock` — 18 закреплённых пакетов с шапкой «Пиннованный тулчейн (G17): откат = git revert этого файла».

**С 2026-08-08 файл читается — G17 обеспечен для этих 18 пакетов.** Перед каждой editable-установкой в конфигурации идёт `pip install --quiet -r tools/vn.lock`, и только потом `pip install --quiet -e "tools/vn[dev]"`: пины встают первыми, а `>=`-диапазоны из `pyproject.toml` ими уже удовлетворены, так что editable не поднимает ни один пакет. Семь строк установки тулчейна в конфигурации:

| Конфиг | Строки `-r tools/vn.lock` → `-e tools/vn[dev]` |
|---|---|
| `.github/workflows/ci.yml` | `:30`→`:31` (джоба `lint`), `:46`→`:47` (`build-test`) |
| `.github/workflows/nightly.yml` | `:29`→`:30` |
| `.github/workflows/canary.yml` | `:30`→`:31` |
| `.github/workflows/release.yml` | `:42`→`:43` |
| `.gitlab-ci.yml` | `:23`→`:24` (шаблон `.with-sdk`), `:37`→`:38` (джоба `lint`) |

По числу **джоб** мест установки восемь: `before_script` шаблона `.with-sdk` разворачивается и в `build`, и в `test`. Именно восьмёрку ассертит тест `tools/vn/tests/test_ci_config.py:73-90` — он проверяет не только факт установки лока, но и **порядок** (лок строго до editable). Второй тест того же файла (`:93-107`) стережёт установку `ffmpeg` до любого `vn build`.

**Честное ограничение.** В локе только прямые зависимости и то, что попало в него на момент регенерации; транзитивные пины неполны — например `pygments`, который тянет `pytest`, в файле отсутствует и разрешается PyPI на момент установки. То есть «откат = `git revert` одного файла» работает для 18 перечисленных пакетов, но не для всего дерева.

Что с этим делать дальше (по возрастанию цены):

1. Добавить тест, сверяющий имена пакетов в `vn.lock` со списком `dependencies` + `dev` из `pyproject.toml`, чтобы lock не расходился с зависимостями.
2. Перейти на настоящий lock-инструмент (`pip-tools`/`uv`) с полным замыканием транзитивных зависимостей — но это меняет процедуру обновления, отдельным ADR.

Приоритет и место в плане — [Роадмап](37-roadmap.md).

---

## 9. Границы движка: чего `vn` не делает

`vn` — **оркестратор и валидатор**, а не производитель картинок. Он никогда:

| Не делает | Что делает вместо | Где живёт ручной шаг |
|---|---|---|
| не рендерит в DAZ Studio | проверяет, что рендер **объявлен** (`*.render.yaml`, схема `daz_render@1`) и выход существует; пишет провенанс | [DAZ Studio](17-daz-studio.md) |
| не вызывает ComfyUI | находит установку и модели (`vn pipeline doctor` / `vn pipeline models`), умеет **прочитать** параметры из tEXt-чанков готового PNG и восстановить workflow-граф | [Генерация изображений](20-image-generation.md) |
| не управляет Virt-a-Mate / The Sims 4 | детектит установку, валидирует декларации захватов | [VaM](18-vam.md), [Sims 4](19-sims4.md) |
| не рисует UI руками | генерирует 9-patch панели из деклараций (ADR-0009) | [Фронтенд](06-frontend.md) |
| не переводит текст | делает PO round-trip и считает покрытие; перевод — человек или CAT | [Локализация](14-localization.md) |
| не заменяет Ren'Py | вызывает движок для парсинга (`vn_analyze`), компиляции, дистрибуции и QA-прогонов | [Разработка на Ren'Py](05-renpy-development.md) |

Причина одна: эти шаги либо GUI-интерактивные (DAZ, VaM, Photoshop), либо требуют API-клиента, которого в репозитории нет (ComfyUI). Контракт конвейера держится не на автоматизации шага, а на том, что **результат объявлен декларацией и проверяем**. Что из этого стоит автоматизировать и в каком порядке — [Автоматизация](26-automation.md) и [Роадмап](37-roadmap.md).

Отдельно: в репозитории нет ни одного `*.render.yaml`, `*.duf`, `*.provenance.json` и ни одного ComfyUI workflow JSON. Валидаторы внешних 3D-источников написаны и покрыты тестами, но на реальных данных ни разу не работали.

---

## Как изменить / Как расширить

### Добавить команду

1. **Логику — в модуль**, не в `cli.py`. Новый файл или существующий в `tools/vn/src/vn/<домен>/`. Функция возвращает отчёт (dataclass со списками `errors/warnings/...`), а не печатает и не вызывает `sys.exit`.
2. **Обвязку — в `cli.py`**, рядом с соседями домена, в существующую группу:

```python
@assets.command("thumbs")                                   # kebab-case имя в CLI
@click.option("--profile", type=click.Choice(["full", "draft"]), default="full")
def assets_thumbs(profile: str):                            # snake_case имя функции
    """Первая строка docstring попадает в vn assets --help."""
    from .assets.thumbs import build_thumbs                 # ЛЕНИВЫЙ импорт

    rep = build_thumbs(_root(), profile=profile)
    for w in rep.warnings:
        click.secho(f"warning: {w}", fg="yellow")
    for e in rep.errors:
        click.secho(f"error: {e}", fg="red")
    if rep.errors:
        _fail(f"thumbs: {len(rep.errors)} ошибок")          # exit 1 с сообщением
    click.secho(f"thumbs: OK ({len(rep.built)})", fg="green")
```

Конвенции, которые соблюдает весь файл:

| Правило | Пример |
|---|---|
| имя команды в CLI задаётся явной строкой, если отличается от имени функции | `@content.command("lint")` при `def content_lint` |
| функция группы называется `<группа>_<команда>` | `assets_video_validate` |
| docstring обязателен — это текст `--help` | `"""Строгая проверка .webm: ..."""` |
| корень репозитория — только через `_root()` | `root = _root()` |
| ошибка — только через `_fail()`, никогда `raise` наружу | `_fail("...")` |
| цвета: warning жёлтый, error красный, успех зелёный, прогресс cyan | `click.secho(..., fg="yellow")` |
| пути в выводе — `.as_posix()` | `p.relative_to(root).as_posix()` |

3. **Проверьте `--help`**: `vn assets --help` и `vn assets thumbs --help`.

### Завести заглушку правильно

Никогда не оставляйте тихий `pass` — команда обязана честно сказать, что её нет:

```python
main.command(name="foo", help="Что это будет (фаза 2).")(_stub(2))          # одиночная
_stub_group("bar", "Домен bar (раздел N).", {"new": 1, "check": 2})          # целая группа
```

Проверка: `vn foo` печатает жёлтое сообщение и возвращает **3**.

### Зарегистрировать новую схему

Файл `tools/schemas/<name>@<N>.schema.json`, имя строго по `^[a-z][a-z0-9_]*@\d+\.schema\.json$`, и `properties.schema.const` обязан совпадать с `<name>@<N>` — иначе `SchemaRegistry` падает `ValueError` при конструировании, а `vn doctor` краснеет на проверке реестра. Плюс `additionalProperties: false` — этого требует `test_registry_loads` (`tools/vn/tests/test_schemas.py:9-14`). Подробности и порядок выпуска новой версии схемы — [Контентный конвейер §8](08-content-pipeline.md).

### Добавить тест

Файл `tools/vn/tests/test_<тема>.py`, функции `def test_*`. `conftest.py` кладёт `tools/vn/src` в `sys.path` и даёт фикстуру `repo_root` (реальный корень репозитория). Два рабочих шаблона в коде:

- **на реальном репозитории** — `test_schemas.py` берёт `repo_root` и валидирует все стартовые декларации;
- **на синтетическом скелете** — `test_compile.py:29` (`skeleton_no_chapters`) собирает в `tmp_path` минимальный репозиторий (копирует `project.yaml`, `.vnstorage.yaml`, `tools/schemas/`, `content/` без глав и локаций) — так тест не требует Ren'Py SDK.

Запуск: `python -m pytest tools/vn/tests -q` (152 теста). См. [Тестирование](27-testing.md).

Третий шаблон появился 2026-08-08 — **тест над CLI**: `test_release.py:141-146` (`_run_pack_build`) даёт `click.testing.CliRunner` + `monkeypatch.chdir(root)` (чтобы `_root()` нашёл синтетический корень) и проверяет код возврата и текст вывода команды. Так стоит закрывать команды, у которых логика неотделима от обвязки.

---

## Как отлаживать сам тулинг

```bash
pip install -e "tools/vn[dev]"          # editable: правка .py видна следующей же командой
python -m vn.cli build --check          # эквивалент `vn build --check`, но без entry-point
python -m vn.cli content lint

python -m pytest tools/vn/tests -q                    # весь набор
python -m pytest tools/vn/tests/test_lint.py -q       # один файл
python -m pytest tools/vn/tests -q -k "gallery"       # по имени
python -m pytest tools/vn/tests -x -vv                # стоп на первом падении, подробно

python -m pdb -m vn.cli build           # пошагово
python -X importtime -m vn.cli --version 2>&1 | tail -20   # что тянется на старте
```

| Приём | Зачем |
|---|---|
| `python -m vn.cli` вместо `vn` | обходит скрипт-обёртку из `Scripts/`; полезно, когда в PATH подозревается старая установка |
| `python -c "import vn; print(vn.__file__, vn.__version__)"` | подтвердить, что импортируется дерево из репозитория, а не копия из site-packages |
| `pip show vn-tools` | строка `Editable project location:` должна указывать на `tools/vn` |
| `PYTHONIOENCODING=utf-8` | лечит кракозябры корневого `vn --help` (§6.1) |
| `.vncache/analyze-*.json` удалить | сбросить кэш анализа сцен, если подозреваете, что build-bridge отдал устаревшую сводку |

Промежуточные артефакты, которые стоит смотреть при разборе падения:

| Путь | Что там |
|---|---|
| `.vncache/analyze-<hash>.json` | кэш разбора авторских `.rpy` парсером Ren'Py |
| `.vncache/smoke/` | `RESULT.txt`, `startup.txt`, `picks.log`, `shot*.png` от `vn test smoke` |
| `.vncache/corpus/`, `.vncache/corpus-savedir/` | прогон `vn save corpus` |
| `.vncache/assets-manifest.json`, `.vncache/assets/` | манифест и блобы кэша трансформаций |
| `traceback.txt` в корне | падение движка; `vn test smoke` печатает последние 1500 символов сам |
| `game/generated/manifest.json` | 30 входов / 19 выходов; без него `vn play` и автопилот отказываются стартовать |

---

## Чего НЕ делать

- **Не добавлять второй инструмент.** Скрипт в `scripts/`, отдельный `Makefile`, «маленький хелпер на bash» нарушают G1. Всё, что делает больше одной команды, — подкоманда `vn`.
- **Не писать логику в `cli.py`.** Она почти наверняка останется непокрытой: из всей обвязки тестами закрыта одна команда — `pack build` (`test_release.py:141-192`).
- **Не поднимать импорт из тела команды на уровень модуля** «чтобы аккуратнее» — это платится стартом CLI при каждом вызове из вотчера.
- **Не считать `exit 3` провалом.** Скрипт, который делает `vn voice tts && ...`, сломается на честной заглушке.
- **Не брать синтаксис команд из `../ARCHITECTURE.md`.** `--use-artifact`, `vn validate`, `--role`, `--gate` не существуют (§2.13). Источник истины — `--help` и `cli.py`.
- **Не искать SDK «где-нибудь».** Только `RENPY_SDK`, и только с `renpy.py` внутри. После `setx` обязательно **новый** терминал.
- **Не полагаться на `vn content graph` для паков** — главы из `packs/` в граф не попадают.
- **Не использовать `vn pipeline models --only <ids>` как фильтр статуса** — этот флаг сам по себе запускает скачивание (`cli.py:1442`).
- **Не ожидать, что `vn assets watch` подхватит правку `content/`** — эти события выбрасываются (`cli.py:566`). Для полного цикла — `vn dev`.
- **Не менять `tools/vn.lock` мимоходом** — теперь он действительно определяет версии в CI (§8): каждая правка меняет тулчейн всех пяти пайплайнов. И наоборот: не добавляйте зависимость в `pyproject.toml`, не дописав пин в лок — editable-установка молча дотянет её с PyPI.
- **Не ставить editable раньше лока** в новой джобе — пины окажутся декоративными, и `test_ci_config.py` покраснеет с объяснением.
- **Не менять текст сообщений об ошибках бездумно** — часть из них ловится тестами и глазами в CI-логах.

---

## Проверка

```bash
# 1. Тулинг цел и виден
vn --version                       # vn, version 0.1.0
pip show vn-tools                  # Editable project location: .../tools/vn

# 2. Окружение
vn doctor                          # ожидание: 8 галок, exit 0

# 3. Полный круг сборки
vn build                           # build: OK
vn build --check                   # check: генерат свеж   ← то же гоняет CI

# 4. Тесты тулинга
python -m pytest tools/vn/tests -q # 152 passed

# 5. Контракт кодов возврата (после правок в cli.py)
vn char new;    echo $?            # 3  — заглушка фазы 1
vn voice tts;   echo $?            # 3  — заглушка фазы 2
vn char new x;  echo $?            # 2  — usage error от click
cd /tmp && vn build; echo $?       # 1  — вне репозитория, с сообщением

# 6. Справка не разъехалась с кодом
vn --help && vn assets --help && vn assets video --help
```

Значения из п.1–4 — фактические на 2026-08-08 (машина владельца, Windows 11, Python 3.12.10).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/cli.py` (обвязка всех команд), `../../tools/vn/src/vn/repo.py` (поиск корня), `../../tools/vn/src/vn/doctor.py` (обнаружение SDK), `../../tools/vn/pyproject.toml` (зависимости, entry point), целевой модуль домена в `../../tools/vn/src/vn/<домен>/` |
| **Не трогать** | `game/generated/`, `game/assets/`, `game/tl/`, `.vncache/`, `build/` — производные зоны, перезапишет сборка. `../ARCHITECTURE.md` — целевой документ, не описание построенного: не «приводить код в соответствие» с ним без задачи |
| **Зависимости** | Правка `cli.py` ломает CI (`.github/workflows/{ci,nightly,canary,release}.yml`, `.gitlab-ci.yml` вызывают команды `vn` по именам), хуки и любые скрипты. Переименование команды/флага — breaking change. Новая зависимость в `pyproject.toml` **обязана** получить пин в `tools/vn.lock`: лок ставится первым во всех пайплайнах, и незапиненный пакет приедет из PyPI произвольной версии. Новая джоба CI обязана ставить лок до editable и `ffmpeg` до `vn build` — оба инварианта стережёт `tools/vn/tests/test_ci_config.py` |
| **Валидация** | `python -m pytest tools/vn/tests -q` → 152 passed · `vn build --check` → `check: генерат свеж` · `vn doctor` → exit 0 · `vn --help` и `vn <группа> --help` без исключений |
| **Частые ошибки** | 1) Логика написана прямо в `cli.py` — попадает в почти непокрытую тестами зону (закрыт только `pack build`). 2) Импорт модуля поднят на уровень `cli.py` — старт CLI дорожает для всех команд. 3) Заглушка сделана как `pass` вместо `_stub(N)` — команда молча «успешна». 4) Ошибка выброшена исключением вместо `_fail()` — нарушен контракт «exit 1 всегда с сообщением». 5) Флаг взят из `ARCHITECTURE.md` (`--use-artifact`, `vn validate`, `--gate`) — таких команд нет. 6) Предположение, что `RENPY_SDK` унаследован bash-сессией — его надо экспортировать вручную. 7) Схема добавлена без совпадения `properties.schema.const` с именем файла или без `additionalProperties: false` — падает `SchemaRegistry` и `test_registry_loads`. 8) Утверждение, что `tools/vn.lock` никем не читается — устарело с 2026-08-08 (§8) |
