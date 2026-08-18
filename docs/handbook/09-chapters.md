# 09. Выпуск главы: от идеи до релиза

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — скаффолдинг, компиляция, граф, локализация и smoke-прогон главы работают; но `vn chapter new`/`vn scene new` не умеют паки, `scene_order` ни на что не влияет кроме проверок, а исчерпывающего обхода веток (`vn test paths`) нет — ветки перебираются руками через `--picks`.
> **Отвечает на вопрос:** «Я пишу новую главу — какие файлы создать, в каком порядке, и чем проверить, что я ничего не сломал?»

Глава — это папка `content/chapters/ch<NN>_<slug>/` с `chapter.yaml`, `vars.yaml` и каталогом `scenes/`, где каждая сцена — **пара** файлов `s<NNN>_<slug>.scene.yaml` + `.scene.rpy` (правило G3). Всё остальное — обвязка сцен, реестры, экран выбора глав, переводы — генерируется из этих деклараций (`vn build` → `game/generated/`). Руками в `game/generated/` не пишут никогда. Устройство самого конвейера — [08-content-pipeline.md](08-content-pipeline.md), анатомия одной сцены — [12-scenes.md](12-scenes.md).

## Быстрый ответ

```bash
vn chapter new reunion                 # -> content/chapters/ch02_reunion/ (chapter.yaml, vars.yaml, s010_intro)
vn scene new ch02 school_gate          # -> scenes/s020_school_gate.scene.{yaml,rpy}  (шаг 10)
#   вручную: exits: в каждой scene.yaml + entry_scene/scene_order в chapter.yaml
#   вручную: диалоги в *.scene.rpy (метки только ch02_sNNN__body / __<branch>)
vn content lint                        # конвенции имён, граф, достижимость
vn content graph                       # mermaid: увидеть ветвление глазами
vn build                               # lint -> ассеты -> генерат -> game/tl
vn loc keys                            # say-id в .rpy + loc/ledger/ch02.json
vn loc extract && vn loc import        # PO -> переводы
vn test smoke --picks 0,1              # прогон конкретной ветки автопилотом
```

`vn chapter new` **не** добавляет владельца в `CODEOWNERS` и **не** трогает `content/ui/strings.yaml` — оба шага ручные (см. чеклист).

---

## 1. Сквозной workflow выпуска главы

| # | Шаг | Вход | Выход | Команда | Проверка |
|---|---|---|---|---|---|
| 1 | Замысел главы | — | номер `chNN`, слуг, роль в арке | тулинга нет | — |
| 2 | Скелет главы | слуг | `content/chapters/chNN_<slug>/{chapter.yaml,vars.yaml,scenes/s010_intro.scene.{yaml,rpy}}` | `vn chapter new <slug>` | `vn content lint` |
| 3 | Разбиение на сцены | план сцен | пары `sNNN_<slug>.scene.{yaml,rpy}` | `vn scene new chNN <slug>`; для ещё не написанных целей — `vn scene stub chNN sNNN` | `vn content lint` |
| 4 | Каркас графа | список сцен | `entry_scene`, `scene_order` в `chapter.yaml`; `exits:` в каждой `scene.yaml` | правка YAML руками | `vn content graph`, `vn content lint` |
| 5 | Персонажи и локации | — | `content/characters/<id>/character.yaml`, `content/locations/<id>/location.yaml` | **скаффолда нет**: `vn char new` — stub фазы 1, exit 3 | `vn content lint` |
| 6 | Диалоги | — | тело `label chNN_sNNN__body:` в `*.scene.rpy` | редактор | `vn build` |
| 7 | Выборы и ветвление | — | `menu:` + метки `__<branch>` + `return "<exit_id>"` | редактор | `vn build`, `vn test smoke --picks` |
| 8 | Переменные | — | `content/chapters/chNN_*/vars.yaml` (или `content/variables/*.vars.yaml` для `g.*`) | редактор | `vn build` — сверка с Variable Registry |
| 9 | Ассеты (фоны, спрайты, CG, видео) | `assets_src/**` | `game/assets/**` | `vn assets build` (входит в `vn build`) | `vn assets validate` |
| 10 | CG в галерею | логический id ассета | запись в `content/gallery/core.gallery.yaml` | редактор | `vn build` (проверяет существование ассета и якоря) |
| 11 | Достижения главы | якорь `scene`/`var` | `content/achievements/core.achievements.yaml` | редактор | `vn build` |
| 12 | Звук | `assets_src/audio_stems/{bgm,amb,sfx}/*.ogg` | треки в `content/audio/bgm.yaml`; `music: bgm/<id>` в `scene.yaml` | редактор | `vn build` |
| 13 | say-id и маркеры меню | `*.scene.rpy` | `id chNN_sNNN_NNNN` в .rpy + `loc/ledger/chNN.json` | `vn loc keys` | `vn loc keys --check` |
| 14 | PO-заготовки | ledger | `loc/po/<lang>/chNN.po` | `vn loc extract` | — |
| 15 | Перевод / псевдолокаль | PO | `msgstr` | переводчик; `vn loc pseudo` для QA переполнений | `vn loc report` |
| 16 | Импорт переводов | PO | `game/tl/<lang>/dialogue_chNN.rpy` | `vn loc import` (входит в `vn build`) | `vn build --check` |
| 17 | QA-прохождение веток | генерат | `.vncache/smoke/` (скриншоты, `RESULT.txt`, `picks.log`) | `vn test smoke --picks …` | exit 0 + `OK: vn_end_of_content` |
| 18 | Перевод в `playtest` | `chapter.yaml` | `status: playtest` | редактор | `vn content lint` — граф-предупреждения становятся ошибками |
| 19 | Релизный гейт | всё дерево | вердикт 21 проверки | `vn release validate --flavor patron` | exit 0 (у `public` тоже exit 0: гейт зрелости даёт WARN, пока нет ни одной `release`-главы) |
| 20 | Сборка | всё дерево | `build/dist/<version>-<flavor>/` | `vn release build --flavor public` | — |
| 21 | Фиксация id и changelog | `status: release` | `docs/CHANGELOG.md`, `ci/release-manifest.json`, `content/registry/id_registry.json` | `vn release changelog` | — |

Статус: шаги 2–4, 6–17 — **IMPLEMENTED**; шаг 5 (скаффолд персонажа/локации) — **NOT IMPLEMENTED** (фаза 1, `cli.py:958`); шаг 21 видит главы паков с 2026-08-18 (`snapshot_content` → `repo.chapter_zones`, в снимке появилось поле `pack`) — **IMPLEMENTED**.

**Про шаг 12 (звук). Аудио-тракт живой — IMPLEMENTED.** Конвейер читает нормативную зону `assets_src/audio_stems/{bgm,amb,sfx}/` (`tools/vn/src/vn/assets/pipeline.py:159-170`; имя закреплено `docs/ARCHITECTURE.md:392` и `docs/conventions/folder-layout.md:29`, поэтому код пошёл к норме, а не наоборот). Каталоги `assets_src/audio_stems/{bgm,amb,sfx}/` созданы; `.ogg` оттуда копируется трансформацией `copy_audio` в `game/assets/audio/<kind>/<имя>.ogg`. Ветку стережёт тест `test_audio_stems_branch_copies_ogg` (`tools/vn/tests/test_assets.py:52`). Каталога `assets_src/audio/` нет и не должно быть.

**Что в аудио-тракте всё ещё не готово:**

- `content/audio/{bgm,sfx}.yaml` по-прежнему `tracks: {}`, и ни одного `.ogg` в репозитории нет — то есть **любое** значение `music:` в `scene.yaml` сегодня даёт ошибку компиляции, пока вы не объявите трек;
- поля `loop`, `loop_start`, `volume` схемы `audio@1` эмиттер **игнорирует**: `_emit_audio` (`compile.py:301-310`) пишет только `define audio.<id> = "<file>"`;
- нормализации громкости (`loudnorm`) в конвейере нет.

Детали — [23-audio.md](23-audio.md).

Подробности по соседним зонам: ассеты — [16-assets.md](16-assets.md), персонажи — [10-characters.md](10-characters.md), локации — [11-locations.md](11-locations.md), галерея — [15-gallery.md](15-gallery.md), релиз — [29-build-and-release.md](29-build-and-release.md).

---

## 2. Создать главу с нуля

**Статус: IMPLEMENTED** — `tools/vn/src/vn/content/scaffold.py:59-78`, CLI `tools/vn/src/vn/cli.py:447-459`.

```bash
vn chapter new reunion
# создана глава: content/chapters/ch02_reunion/
# не забудьте: владельца главы в CODEOWNERS; vn build для регистрации в меню
```

Что делает `new_chapter`:

1. Проверяет слуг против `SLUG_RE = ^[a-z][a-z0-9_]{2,30}$` (`scaffold.py:10`). Иначе — `ScaffoldError`, exit 1.
2. Сканирует **только** `content/chapters/` регуляркой `^ch(\d{2})_` и берёт `max+1` (`scaffold.py:63-69`). Главы в `packs/*/chapters/` на нумерацию не влияют.
3. Создаёт `content/chapters/ch<NN>_<slug>/scenes/` и **четыре** файла — дословно:

`chapter.yaml` (`scaffold.py:17-25`):

```yaml
schema: chapter@1
id: chNN                             # слуг <slug> — только в имени папки
title_key: meta.chapters.chNN.title
status: draft                        # draft | playtest | release (G15)
entry_scene: s010
scene_order: [s010]
```

`vars.yaml` (`scaffold.py:51-56`):

```yaml
schema: vars@1
store: chNN
vars: {}
```

`scenes/s010_intro.scene.yaml` (`scaffold.py:28-38`):

```yaml
schema: scene@1
id: s010
exits: {}
# exits:
#   done: s020                        # короткая ссылка внутри главы
#   alt:
#     - {when: "g.route == 'mira'", to: s030}
#     - {to: ch02/s010}              # межглавная ссылка
```

`scenes/s010_intro.scene.rpy` (`scaffold.py:41-48`):

```renpy
# Метки — только chNN_s010__body и chNN_s010__<branch> (C2, naming.md).
# Переходы между сценами — return "<exit_id>"; цели в exits: scene.yaml.

label chNN_s010__body:
    "…"
    return
```

### Что скаффолд НЕ делает (доделываете руками)

| Пропущено | Где доделать | Что будет, если забыть |
|---|---|---|
| `meta.chapters.chNN.title` | `content/ui/strings.yaml` | `vn build` даёт warning «в меню глав отобразится сырой ключ» (`compile.py:1048-1053`) |
| Владелец главы | `CODEOWNERS` (см. закомментированный образец `CODEOWNERS:25-26`) | ревью главы никому не назначается |
| `scene_order` при добавлении сцен | `chapter.yaml` | сцена-финал вне `scene_order` ловит warning «тупик»; сама `scene_order` при этом на кодогенерацию не влияет |
| `exits` между сценами | каждая `scene.yaml` | сцены недостижимы; в draft — warning, в playtest/release — ошибка |
| Регистрация в git | `git add content/chapters/chNN_*` | — |

### Добавить сцену

```bash
vn scene new ch02 rooftop     # -> scenes/s020_rooftop.scene.{yaml,rpy}
vn scene stub ch02 s040       # -> scenes/s040_stub.scene.{yaml,rpy} — заглушка под объявленную цель
```

- Номер: `(max // 10) * 10 + 10` (`scaffold.py:131`) — то есть `s010, s020, s030…`.
- Глава ищется по точному имени папки **или** по префиксу `ch02_`; неоднозначность — ошибка (`scaffold.py:81-95`).
- CLI печатает напоминание «добавить сцену в `scene_order` главы и связать exits» (`cli.py:481`) — скаффолд `chapter.yaml` не трогает.
- `vn scene stub` пишет тело `"Заглушка: сцена в разработке."` и `exits: {}`; нужен, чтобы draft-глава со ссылкой на ненаписанную сцену проходила smoke, а не падала в `vn_scene_unavailable`.

---

## 3. `chapter.yaml` — полная таблица полей

Схема: `tools/schemas/chapter@1.schema.json`, `additionalProperties: false` (лишнее поле = ошибка линта).

| Поле | Обяз. в схеме | Ограничение схемы | Что делает код | Статус |
|---|---|---|---|---|
| `schema` | да | `const: chapter@1` | точка входа реестра схем (G16) | IMPLEMENTED |
| `id` | да | `^ch\d{2}$` | должен совпадать с префиксом имени папки — иначе ошибка и в линте (`lint.py:211-212`), и в компиляторе (`compile.py:740-743`) | IMPLEMENTED |
| `title_key` | да | `^[a-z0-9_.]+$` | попадает в `VN_CHAPTERS` (`scenes.py:417`); отсутствие ключа в `content/ui/strings.yaml` → warning (`compile.py:1048-1053`) | IMPLEMENTED |
| `status` | да | enum `draft \| playtest \| release` | управляет строгостью проверок (G15) — см. §4 | IMPLEMENTED |
| `entry_scene` | да | `^s\d{3}$` | `entry_label = f"{id}_{entry_scene}"` в `VN_CHAPTERS` (`scenes.py:418`); `label start` прыгает на `entry_label` первой главы (`030_flow.rpy:217-224`) | IMPLEMENTED |
| `scene_order` | да | массив `^s\d{3}$`, `minItems: 1`, уникальные | **проверяется, но не используется**: только существование сцен (`compile.py:1061-1063`, `lint.py:245-247`) и «последняя в `scene_order`» как легитимный тупик (`lint.py:321-330`). Порядок прохождения задают `exits`, а не это поле | PARTIALLY IMPLEMENTED |
| `owner` | нет | `^@[A-Za-z0-9_-]+$` | **не читается никаким кодом** (grep по `tools/vn/src/vn/` — 0 попаданий) | NOT IMPLEMENTED |
| `requires.systems` / `requires.chapters` | нет | массивы строк | **не читаются**; `requires` разрешается только у манифестов паков (`compile.py:464`) | NOT IMPLEMENTED |
| `pack` | — | поля не существует | принадлежность паку выводится из расположения файла (`compile.py:744`, `packs/README.md:3-5`) | по замыслу |

Живой пример — `content/chapters/ch01_awakening/chapter.yaml`:

```yaml
schema: chapter@1
id: ch01                             # слуг awakening — только в имени папки
title_key: meta.chapters.ch01.title
status: draft                        # draft | playtest | release (G15)
entry_scene: s010
scene_order: [s010, s020, s030]
```

---

## 4. `status: draft | playtest | release` (G15)

**Статус: IMPLEMENTED** — `lint.py:244,266,305` (три точки `complain = rep.warn if status == "draft" else rep.error`), `compile.py:1057-1063`, `scenes.py:235,261`.

Механика одна и та же везде: `complain = warn if status == "draft" else error`.

| Проверка | Где | `draft` | `playtest` / `release` |
|---|---|---|---|
| `scene_order` ссылается на несуществующую сцену | `lint.py:245-247`, `compile.py:1061-1063` | warning | **error** |
| `entry_scene` не существует | `lint.py:248-249`, `compile.py:1059-1060` | warning | **error** |
| `exits.<id> -> <target>`: цели нет | `lint.py:277-289`, `scenes.py:269-275` | warning | **error** |
| Сцена недостижима из `entry_scene` | `lint.py:314-320` | warning | **error** |
| Переменная пишется/читается, но не в Variable Registry | `scenes.py:232-243` | warning | **error** |
| Сцена без `exits`, не последняя в `scene_order` («тупик») | `lint.py:321-330` | warning | warning (**всегда** warning) |
| Битая цель exit при эмиссии | `scenes.py:269-276` (решение) + `:386-390` (эмиссия) | эмитится `# TODO(draft)` + `$ vn.unwind_call_stack()` + `jump vn_scene_unavailable` | ветка не эмитится вовсе |

Дополнительный эффект `release`: `vn release changelog` штампует главу и все её сцены в `content/registry/id_registry.json` (`release.py:69-121`) — после этого исчезновение id ловится линтом как ошибка G7 (`lint.py:383-388`), а вернуть id назад нельзя: главы вообще не переименовываются (для сцен есть аварийный выход через `content/renames.yaml`).

**Факт репозитория:** `ch01` и `ch90` — оба `draft`, поэтому `content/registry/id_registry.json` содержит четыре пустых массива и защита G7 сегодня **инертна**. Первая же глава со `status: release` включает её навсегда.

Практическое правило перехода: `draft` — пока глава пишется и мержится ежедневно; `playtest` — когда граф закрыт и вы хотите, чтобы CI ловил разрывы; `release` — только в том коммите, где глава действительно уходит в сборку игрокам.

---

## 5. Нумерация: `chNN`, `sNNN`, слуги

**Статус: IMPLEMENTED** — регулярки продублированы в `lint.py:16-18` и `compile.py:31-32`; норматив — [`docs/conventions/naming.md`](../conventions/naming.md).

| Сущность | Паттерн | Кто проверяет |
|---|---|---|
| Папка главы | `^ch(\d{2})_([a-z][a-z0-9_]{2,30})$` | `lint.py:16`, `compile.py:31` |
| id главы | `^ch\d{2}$` | `chapter@1.schema.json` |
| Файл сцены | `^s(\d{3})_([a-z][a-z0-9_]{2,40})\.scene\.(yaml\|rpy)$` | `lint.py:17`; компилятор — только `.yaml` (`compile.py:32`) |
| Полный id сцены | `^ch\d{2}_s\d{3}$` — **выводится из путей**, нигде не хранится | `compile.py:775-777` |
| Метка-обвязка | `= полному id` (`label ch01_s020:`) | эмитит компилятор |
| Авторская метка | `^ch\d{2}_s\d{3}__[a-z0-9_]+$` | `scenes.py:18` |

Правила:

- **Слуг живёт только в имени файла/папки.** Ни в id, ни в метках, ни в say-id его нет. Поэтому слуг можно переименовать в любой момент — при условии, что переименована **обе** файла пары (`s030_rooftop.scene.yaml` **и** `.scene.rpy`, иначе ошибка G3 «нет парного…»).
- **Номер менять нельзя.** `s030 → s035` меняет полный id сцены, а значит: все say-id внутри `.rpy` становятся «чужими» (`vn loc keys` выдаст «id … вне конвенции», `keys.py:93-99`), ломаются якоря галереи/достижений (`scene: ch01_s030`), а после релиза срабатывает G7. Не переименовывайте — добавьте новую сцену.
- **Шаг 10 у сцен** — чтобы вставить сцену между `s010` и `s020` без переименования соседей: занимаете `s015` руками (`vn scene new` всегда идёт по десяткам, `scaffold.py:131`). Слот `s015` легален для линта и компилятора, просто скаффолд его не выдаёт.
- **Нумерация глав ядра** идёт от `max+1` по `content/chapters/`. Если положить в ядро главу с номером 90, следующий `vn chapter new` выдаст `ch91`. В этом репозитории 90-е номера зарезервированы под паки (`ch90_beach` в `packs/ep_beach/`) — но это **соглашение, а не проверка**: кодом гарантируется только уникальность id по объединению ядра и паков (`compile.py:524-526`).

---

## 6. Разбиение на сцены

Что физически задаёт границу сцены (всё — из `emit_scene`, `scenes.py:197-273`): вход в сцену — это `$ vn.checkpoint("<full_id>")`, очистка слоя `sprites`, установка **одного** фона из `location:` и **одного** трека из `music:`. То есть:

| Критерий | Почему это граница сцены |
|---|---|
| Смена локации | `location:` в `scene.yaml` — ровно одна на сцену; фон ставится обвязкой на входе |
| Смена музыки | `music:` — ровно одна на сцену; `play music … fadein 1.0` эмитится на входе |
| Точка восстановления | `vn.checkpoint()` зовётся **только** на входе в сцену — это якорь позиции сейва и триггер ачивок/галереи с `trigger: {scene: chNN_sNNN}` |
| Узел ветвления между линиями | `exits` — единственный легальный межсценовый переход; ветка, ведущая в другую сцену, обязана заканчивать текущую |
| Смена состава/времени | косвенно: обычно тянет за собой фон и/или музыку |

Внутри сцены менять фон руками можно и это используется — `content/chapters/ch01_awakening/scenes/s030_rooftop.scene.rpy:13` содержит `scene cg ch01 rooftop_day with dissolve` для CG-вставки. Но декларативный `location:` в сцене один: он и валидируется, и рисуется обвязкой.

**Объём реплик.** Нормы объёма в репозитории нет — ни линт, ни схемы, ни `docs/ARCHITECTURE.md` её не задают (проверено grep). Реальные жёсткие потолки, вытекающие из формата id (`tools/vn/src/vn/loc/keys.py:23-24`): **9999 реплик** на сцену (say-id `_\d{4}`) и **999 меню** на сцену (`_m\d{3}`). Демо-глава для калибровки: `ch01` = 3 сцены, 16 реплик всего (`loc/ledger/ch01.json`), из них s010 — 2, s020 — 4, s030 — 6.

---

## 7. Ветвление: выборы, exits, условия

### 7.1. Железное правило

> **Ветка живёт ВНУТРИ сцены (метки `chNN_sNNN__*`). Между сценами — ТОЛЬКО `return "<exit_id>"` + `exits:` в `scene.yaml`.**

Контракт проверяется компилятором (`scenes.py:81-143`, все — **IMPLEMENTED**):

| Нарушение | Сообщение |
|---|---|
| Метка вне `^<full_id>__[a-z0-9_]+$` | `метка … вне контракта ^chNN_sNNN__<suffix>$ (C2; naming.md)` |
| Нет `<full_id>__body` | `нет обязательной метки … __body (C2)` |
| `jump`/`call` за пределы своей сцены | `переход вне своей сцены; межсценовые переходы только через return "<exit_id>" + exits (C2)` |
| `jump expression …` | `jump expression запрещён в авторских сценах` |
| `return <не строковый литерал>` | `exit-id обязан быть строковым литералом` |
| `return "x"`, где `x` нет в `exits` | `return 'x' не объявлен в exits (…: [список])` |
| Пустой `return` в сцене с непустыми `exits` | `завершайте return "<exit_id>"` |
| Условный пункт меню (`"текст" if cond:`) | `условный пункт меню #N — запрещено (ломает перевод по индексу)` |
| Объявлен `exits.x`, но ни один `return` его не достигает | warning `exits.x не достигается ни одним return` |

**Почему нельзя `jump` в чужую сцену:** прыжок мимо метки-обвязки пропускает `vn.checkpoint()` (нет якоря сейва, не сработают ачивки и галерея по `scene:`), не поставит фон и музыку, и оставит `call`-стек невыровненным — инвариант G7 (`vn.check_scene_stack()`, `030_flow.rpy:44-48`) сломается молча.

### 7.2. Формы `exits`

Схема `scene@1` (`tools/schemas/scene@1.schema.json:45-59`) допускает три формы значения; цель — `^(s\d{3}|ch\d{2}/s\d{3})$`:

```yaml
exits:
  gate: s020                                   # 1) строка — безусловный переход внутри главы
  next: {when: "g.route == 'mira'", to: s030}   # 2) объект — условный переход
  fork:                                        # 3) список — первый подошедший
    - {when: "ch02.saw_letter", to: s040}
    - {to: s050}                               # ← безусловный «иначе» ОБЯЗАН быть последним
  epilogue: ch03/s010                          # межглавная ссылка
```

Эмиссия (`scenes.py:247-258`) — по одному `if` на запись, **в порядке YAML, без `else`**:

```renpy
    call ch01_s020__body from _call_ch01_s020__body
    $ vn.check_scene_stack()
    if _return == "roof":
        jump ch01_s030
    # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)
    $ vn.unwind_call_stack()
    jump vn_scene_unavailable
```

Условие `when` превращается в `if _return == "fork" and vn.eval_when('ch02.saw_letter'):`, а `vn.eval_when` — это буквально `renpy.python.py_eval(expr)` (`030_flow.rpy:57-60`). **Грабля:** если ни одно `when` не сработало и безусловной записи нет, игрок улетает в `vn_scene_unavailable` (в smoke это `FAIL`). Всегда завершайте список условных переходов записью без `when`.

### 7.3. Как не сделать spaghetti

| Приём | Как | Живой пример |
|---|---|---|
| **Ветка = метка внутри сцены** | `menu:` → `jump chNN_sNNN__caught` → своя метка → `return "<exit>"` | `s020_school_gate.scene.rpy:10,16` |
| **Сходящиеся ветки** | Обе ветки делают `return` одного и того же exit-id → в графе одно ребро | `s020`: и `__caught`, и «сказать правду» дают `return "roof"` |
| **Флаг вместо копии сцены** | Записать переменную в ветке, прочитать `if` в следующей сцене — одна сцена, два текста | `ch01.met_mira` пишется в `s010`, читается в `s030:4` |
| **Заглушка вместо мёртвой ссылки** | `vn scene stub chNN sNNN` — граф закрыт, smoke зелёный, текст допишете позже | — |
| **Финал главы** | сцена с `exits: {}` — компилятор сам добавит `$ vn.chapter_done("chNN")` и `jump vn_end_of_content` (`scenes.py:260-265`) | `s030_rooftop.scene.yaml:7` |

Анти-паттерны: копировать сцену ради двух вариантов текста (вместо флага); плодить exit-id, различающиеся только условием (используйте список записей одного exit); делать финальными несколько сцен главы без обновления `scene_order` (каждая лишняя даст warning «тупик»).

---

## 8. Переменные главы

**Статус: IMPLEMENTED** — `content/chapters/chNN_*/vars.yaml` → `game/generated/state/defaults.gen.rpy`. Схема `vars@1`.

```yaml
schema: vars@1
store: ch01
vars:
  met_mira:
    type: bool
    default: false
    doc: "Игрок встретил Миру у ворот в первой сцене"
    since: 1
```

Правила:

- `store` главы **обязан** равняться `chNN` — проверяет линт (`lint.py:348-352`). **Грабля:** проверка ограничена префиксом `content/chapters/`, поэтому `vars.yaml` главы **в паке** может объявить любой store и линт промолчит.
- Компилятор создаёт named store и дефолты: `init -980 python in ch01: pass` + `default ch01.met_mira = False` (`compile.py:94-105`), реальный результат — `game/generated/state/defaults.gen.rpy:9-17`.
- Каждое чтение/запись атрибута стора в `.rpy` сверяется с Variable Registry по AST от build-bridge: незадекларированная переменная — warning в `draft`, ошибка в `playtest`/`release` (`scenes.py:148-159`).
- Необязательные `vars.reads` / `vars.writes` в `scene.yaml` — **справочные**: если объявили и разошлось с фактом, получите warning (`scenes.py:160-175`); если не объявили — никто не требует.
- Поля `doc`, `since`, `range`, `export` схемой описаны, но **ни одной строкой кода не читаются** (grep по `tools/vn/src/vn/` — 0 попаданий). Это документация для человека и для автора миграции. Статус: **NOT IMPLEMENTED** как механизм.
- `store: persistent` — имена обязаны начинаться с `vn_`, иначе `CompileError` (C9, `compile.py:100-104`). Это уже не «переменная главы» — см. [07-backend.md](07-backend.md).

**Глобальная (`g.*`) или главы (`chNN.*`)?**

| Кладите в `g.*` (`content/variables/core.vars.yaml`) | Кладите в `chNN.*` (`chapters/chNN_*/vars.yaml`) |
|---|---|
| Читается или пишется больше чем одной главой | Не покидает свою главу |
| Определяет роут/концовку (`g.route`) | Локальный флаг сцены/выбора |
| Является якорем галереи или достижения, живущим дольше главы | Якорь внутри одной главы (`{var: ch01.met_mira}` — легально) |
| Владелец: `@tech-lead @lead-writer` по `CODEOWNERS:10` | Владелец — автор главы |

Смена типа или смысла уже выпущенной переменной = миграция сейвов (`content/migrations/NNNN_*.py` + резерв номера в `content/migrations/registry.yaml` + бамп `project.yaml: save_schema`) — механика в [07-backend.md](07-backend.md).

---

## 9. Возврат к прошлым решениям

Никакого специального API нет и не нужно: решение — это переменная состояния, а возврат к нему — обычный `if`. Реальная цепочка в `ch01`:

```renpy
# s010_intro.scene.rpy:9-12 — решение
    menu:
        "Подойти к воротам":
            $ ch01.met_mira = True
            "У ворот кто-то есть." id ch01_s010_0002
            return "gate"
```

```renpy
# s030_rooftop.scene.rpy:4-9 — возврат к решению двумя сценами позже
    if ch01.met_mira:
        show mira a casual smile at center with dissolve
        mira "А ты быстрее, чем кажешься." id ch01_s030_0002
    else:
        "Ты здесь один. Тихо. Слишком тихо." id ch01_s030_0004
```

Та же переменная без правки текста сцен питает две другие подсистемы:

- достижение — `content/achievements/core.achievements.yaml:16`: `trigger: {var: ch01.met_mira, equals: true}`;
- галерею — `content/gallery/core.gallery.yaml:82`: `unlock: {var: g.route, equals: mira}`.

Компилятор проверяет, что якорь существует в Variable Registry (`compile.py:239-243` для галереи, `:806-813` для достижений) — опечатка в имени переменной ловится на сборке, а не в игре. Именно поэтому ачивки и галерею можно навешивать на уже написанные главы задним числом, ничего не переписывая.

Условный переход по прошлому решению — `exits` с `when` (см. §7.2): `- {when: "ch01.met_mira", to: s040}`.

---

## 10. Тестирование всех веток

### 10.1. `vn test smoke --picks`

**Статус: IMPLEMENTED** — `cli.py:1347-1401`, автопилот `030_flow.rpy:106-211`.

```bash
vn build                              # обязателен: smoke падает без game/generated/manifest.json
vn test smoke --picks 0,0
vn test smoke --picks 0,1 --lang en
vn test smoke --picks 1
vn test smoke --picks 0,0 --lang pseudo --timeout 300
```

- `--picks` — индексы пунктов **по порядку встреченных меню**; не хватило значений — берётся `0`; индекс больше числа пунктов — прижимается к последнему (`030_flow.rpy:137-141`).
- `--lang` требует, чтобы `game/tl/<code>/` существовал, иначе явный отказ (иначе был бы ложно-зелёный прогон на исходном языке); исходный язык подставляется как маркер `@source` (`cli.py:1354-1367`).
- Выход — `.vncache/smoke/`: `shot*.png`, `RESULT.txt` (`OK: vn_end_of_content` / `FAIL: vn_scene_unavailable`), `picks.log` (фактический путь: `menu 0 -> pick 1 (ch01_s010_m001)`), `startup.txt` (cold start, гейтится бюджетом `cold_start_s: 30`), `state.json`, `gallery.json`.
- Автопилот работает **внутри процесса игры**; синтетический ввод на рабочий стол не используется никогда (G23).

**Перебор веток `ch01` — это ровно то, что гоняет `.github/workflows/nightly.yml:57-60`:** `0,0`, `0,1 --lang en`, `1`, `0,0 --lang pseudo`. Для своей главы составьте такой же список: одно значение на каждое меню самого длинного пути, плюс по прогону на каждую развилку.

`vn test paths` (исчерпывающий обход графа), `vn test replay`, `vn test screens` — **NOT IMPLEMENTED**, заглушки фаз 2/2/3, exit 3 (`cli.py:1404-1405`). Полный перебор веток сегодня — ручной список `--picks`.

### 10.2. `vn content graph`

**Статус: PARTIALLY IMPLEMENTED** — `tools/vn/src/vn/content/graph.py`. Читает только декларации, SDK не нужен. Реальный вывод сегодня:

```
flowchart TD
    subgraph ch01["ch01_awakening (draft)"]
        ch01_s010["ch01_s010<br/>intro"]
        ch01_s020["ch01_s020<br/>school_gate"]
        ch01_s030["ch01_s030<br/>rooftop"]
    end
    ch01_s010 -->|"gate"| ch01_s020
    ch01_s010 -->|"roof"| ch01_s030
    ch01_s020 -->|"roof"| ch01_s030
    ch01_s030 --> vn_end([конец контента])
```

Что видно глазом: сцены без входящих рёбер (недостижимые), сцены с ребром в `vn_end` (терминальные), подписи условий на рёбрах.

**Паки в графе есть** (2026-08-18): Граф обходит ядро И главы паков (`repo.chapter_zones`), пак подписан в заголовке подграфа: `ch90_beach (draft) · pack ep_beach`. До этого главы паков в граф не попадали, и межпаковые ссылки выглядели висящими узлами.

### 10.3. Что именно ловит линт-правило достижимости

`lint.py:251-330`, **IMPLEMENTED**:

1. BFS от `entry_scene` главы по рёбрам `exits` (включая условные — условия не вычисляются, ребро считается проходимым всегда).
2. Сцена, не попавшая в обход → `chNN: сцена sNNN недостижима из entry_scene sNNN — на неё не ведёт ни один exit (мёртвый контент)`. Серьёзность — по `status`.
3. Достижимая сцена с пустыми `exits`, не равная `scene_order[-1]` → **всегда warning** `тупик … игрок упрётся в «конец контента»`.

Чего это правило **не** ловит:

- недостижимую **метку внутри** сцены (`chNN_sNNN__branch`, на которую никто не прыгает) — граф строится по сценам, не по меткам;
- ветку, недостижимую из-за `when`, которое никогда не истинно — выражения `when` не парсятся и не типизируются вообще (`scene@1` требует лишь непустую строку);
- сцену, недостижимую потому, что автор забыл `return "<exit>"` в какой-то ветке — это ловит компилятор отдельным warning «exits.x не достигается ни одним return» (`scenes.py:139-143`);
- **тонкость:** граф достижимости ключуется по `scene.yaml: id` (`lint.py:290`), а множество существующих сцен — по номеру из имени файла. При расхождении сработает отдельная ошибка `id (…) != номеру файла (…)` (`lint.py:233-234`), но заодно исказится и граф. Держите `id` в `scene.yaml` синхронным с именем файла.

---

## 11. Локализация главы

**Статус: IMPLEMENTED** (round-trip), подробности — [14-localization.md](14-localization.md).

```bash
vn loc keys            # 1. проставить say-id в *.scene.rpy + собрать loc/ledger/chNN.json
vn loc extract         # 2. обновить loc/po/<lang>/chNN.po (переводы сохраняются)
#    3. перевод: правка msgstr в loc/po/<lang>/chNN.po
vn loc pseudo          # 3'. или синтетический язык для QA переполнений UI
vn loc import          # 4. PO -> game/tl/<lang>/dialogue_chNN.rpy  (входит в vn build)
vn loc report          # 5. покрытие: "en: 136/136 (100%), fuzzy: 0"
```

Что важно знать именно при выпуске главы:

- **`vn build` НЕ вызывает `vn loc keys` и `vn loc extract`** — только `_loc_import` (`cli.py:151`). Прогонять `vn loc keys` после каждой правки текста — ваша обязанность; CI проверяет это через `vn loc keys --check` (`.github/workflows/ci.yml:69-70`).
- `vn loc keys` **пишет прямо в ваш авторский `.rpy`** (дописывает ` id chNN_sNNN_NNNN` и вставляет `$ vn_menu = "chNN_sNNN_mNNN"` перед `menu:`). Изменённые файлы надо закоммитить. Требуется `RENPY_SDK` — разбор идёт парсером самого движка (G24).
- Новая глава автоматически становится новым PO-доменом: `loc/po/<lang>/chNN.po` + шард `loc/ledger/chNN.json`.
- `vn loc report` даёт **глобальный** процент по всем доменам сразу; порога он не применяет и всегда возвращает 0. Гейт 98 % живёт только в релизе (`release.py:475-502`, порог из `loc/loc.yaml: release_coverage_min`).
- **Грабля:** номера say-id переиспользуемы. Удалили последнюю реплику — её номер освободится для следующей новой (`keys.py:106`). Спасает то, что `vn loc extract` помечает такую запись `fuzzy` (текст-то другой), а `fuzzy` не доезжает до игры (`po.py:385-386`).
- **Грабля:** хвостовой комментарий на строке say ломает вставку id — ошибка обнаруживается постфактум, файлы откатываются (`keys.py:209-212`). Не пишите `"реплика"  # коммент`.
- Меню переводится «всё или ничего»: если хоть один пункт не переведён или fuzzy, всё меню откатывается на исходные подписи (`po.py:406-417`).

---

## 12. CHAPTER DEFINITION CHECKLIST

Полный чеклист выпуска главы. Каждый пункт — команда или конкретный файл.

### Дизайн и каркас

- [ ] Номер и слуг выбраны; слуг проходит `^[a-z][a-z0-9_]{2,30}$`
- [ ] `vn chapter new <slug>` выполнен; папка `content/chapters/chNN_<slug>/` в git
- [ ] `title_key` добавлен в `content/ui/strings.yaml` (иначе warning «сырой ключ в меню глав»)
- [ ] Строка владельца добавлена в `CODEOWNERS` (`/content/chapters/chNN_<slug>/  @handle`, образец — `CODEOWNERS:25-26`)
- [ ] Все сцены созданы: `vn scene new chNN <slug>` (по одному вызову на сцену)
- [ ] Ненаписанные цели переходов закрыты заглушками: `vn scene stub chNN sNNN`
- [ ] `entry_scene` и `scene_order` в `chapter.yaml` перечисляют реальные сцены; последняя в `scene_order` — та, у которой `exits: {}`
- [ ] `exits:` заполнены во всех `scene.yaml`; у каждого списка условных переходов последняя запись без `when`
- [ ] `vn content graph` показывает связный граф: недостижимых узлов нет, `vn_end` ровно один
- [ ] `vn content lint` — 0 ошибок

### Текст и ветвление

- [ ] В каждой `*.scene.rpy` есть `label chNN_sNNN__body:` и он единственная точка входа
- [ ] Все прочие метки — `chNN_sNNN__<branch>`; `jump`/`call` только на них
- [ ] Межсценовые переходы — только `return "<exit_id>"`, и каждый id объявлен в `exits`
- [ ] Условных пунктов меню нет (`"текст" if cond:` запрещён — ломает перевод по индексу)
- [ ] Ни одного `jump` в чужую сцену и ни одного `jump expression`
- [ ] Сходящиеся ветки возвращают один exit-id, а не дублируют сцену
- [ ] `vn build` — 0 ошибок и 0 неожиданных warning по сценам главы

### Персонажи, локации, ассеты

- [ ] Каждый участник объявлен: `content/characters/<id>/character.yaml` (иначе `участник … не объявлен … say упадёт NameError`)
- [ ] `participants:` в `scene.yaml` перечисляет всех говорящих
- [ ] Локация объявлена и вариант существует: `content/locations/<id>/location.yaml`, `location: <loc>/<variant>`
- [ ] Фон реально собран: `game/assets/bg/<loc>/<variant>.webp` (отсутствие файла — жёсткая ошибка компилятора, `images.py:60-68`)
- [ ] Спрайты собраны и матрица поз/одежд/эмоций сходится (`character.yaml: matrix`)
- [ ] `vn assets validate` — 0 ошибок
- [ ] Бюджеты не превышены: `vn build` печатает `бюджет: …` при выходе за `project.yaml: budgets`

### CG, галерея, достижения, звук

- [ ] CG-кадры лежат в `game/assets/cg/**` и показываются в сцене (`scene cg …`)
- [ ] Каждый CG/видео-луп, который должен попасть в галерею, имеет запись в `content/gallery/core.gallery.yaml` с `category`, `kind`, `asset`, `title_key`, `unlock`
- [ ] Якоря разблокировки существуют: `unlock: {scene: chNN_sNNN}` / `{chapter_done: chNN}` / `{var: <store>.<name>}` — компилятор проверит
- [ ] Достижения главы объявлены в `content/achievements/core.achievements.yaml`, `name_key`/`desc_key` есть в `strings.yaml`
- [ ] Треки объявлены в `content/audio/bgm.yaml`; `music: bgm/<id>` в `scene.yaml` ссылается на существующий id
- [ ] Сырцы звука лежат в `assets_src/audio_stems/{bgm,amb,sfx}/` — это нормативная зона, которую читает конвейер
- [ ] Поведение главы не опирается на `loop` / `loop_start` / `volume` из `content/audio/*.yaml`: схема их принимает, эмиттер **игнорирует** — в игре они пока ни на что не влияют

### Состояние

- [ ] Все переменные главы объявлены в `content/chapters/chNN_*/vars.yaml`, `store: chNN`
- [ ] Кросс-главные переменные вынесены в `content/variables/*.vars.yaml` (`store: g`)
- [ ] `vn build` не выдаёт «… не объявлена в Variable Registry» (в `draft` это warning — не игнорируйте его, в `playtest` он станет ошибкой)
- [ ] Изменения типа/смысла уже выпущенных переменных сопровождены миграцией + бампом `project.yaml: save_schema`
- [ ] `vn save check` и `vn save corpus` зелёные на обеих фикстурах (сейвы прошлых версий грузятся; `schema1-demo` реально прогоняет миграцию — в `log.txt` обязана быть строка `[vn] migration 0002`)

### Локализация

- [ ] `vn loc keys` прогнан, изменённые `.scene.rpy` закоммичены
- [ ] `vn loc keys --check` — зелёный (ledger свеж)
- [ ] `loc/ledger/chNN.json` в git
- [ ] `vn loc extract` прогнан; `loc/po/<lang>/chNN.po` появились
- [ ] Переводы залиты; `vn loc report` показывает нужное покрытие, `fuzzy: 0`
- [ ] `vn loc pseudo` + `vn test smoke --lang pseudo` — UI не переполняется
- [ ] `vn loc import` (или `vn build`) прогнан; `game/tl/<lang>/dialogue_chNN.rpy` появился

### QA

- [ ] `vn test smoke --picks …` прогнан по каждой ветке; `RESULT.txt` = `OK: vn_end_of_content` во всех
- [ ] Ни один прогон не даёт `FAIL: vn_scene_unavailable`
- [ ] `picks.log` подтверждает, что автопилот реально ходил разными путями
- [ ] Cold start в бюджете (`cold_start_s: 30`) — печатается smoke'ом
- [ ] `vn test smoke --lang en` (или ваш целевой язык) — зелёный
- [ ] Скриншоты `.vncache/smoke/shot*.png` просмотрены глазами: фоны, спрайты, CG на месте
- [ ] `vn build --check` — генерат свеж (то, что проверит CI)

### Релиз

- [ ] `status` поднят до `playtest`, `vn content lint` всё ещё 0 ошибок (граф-проверки стали строгими)
- [ ] `vn release validate --flavor public` — 0 FAIL (21 проверка; сегодня exit 0, зрелость контента даёт WARN — но с первой главой `status: release` она станет строгой, [29 §5.1](29-build-and-release.md#maturity-gate-rule))
- [ ] `vn release validate --flavor patron` — 0 FAIL
- [ ] `project.yaml: version` поднят на **minor** (новая глава = minor по политике `project.yaml:2`)
- [ ] `status: release` выставлен в том же коммите, что и релиз
- [ ] `vn release changelog` прогнан → `docs/CHANGELOG.md`, `ci/release-manifest.json`, `content/registry/id_registry.json` обновлены и закоммичены
- [ ] Тег `v<version>` совпадает с `project.yaml: version` (иначе `release.yml:47-54` рубит сборку)
- [ ] `vn release build --flavor public` прошёл локально или в CI

---

## 13. Глава в DLC-паке

Подробности про паки — [30-packs-and-dlc.md](30-packs-and-dlc.md). Здесь — только отличия при написании главы.

Живой пример: `packs/ep_beach/chapters/ch90_beach/` — `chapter.yaml` (`id: ch90`, `status: draft`, `entry_scene: s010`, `scene_order: [s010]`) и пара `scenes/s010_shore.scene.{yaml,rpy}`.

| Аспект | Глава ядра | Глава пака |
|---|---|---|
| Расположение | `content/chapters/chNN_<slug>/` | `packs/<pack_id>/chapters/chNN_<slug>/` |
| Поле принадлежности | нет | нет — принадлежность **по расположению** (`compile.py:744`); поля `pack:` не существует |
| `vn chapter new` | работает | **не работает** — скаффолд жёстко пишет в `content/chapters/` (`scaffold.py:62`). Папку и 4 файла создаёте руками |
| `vn scene new` / `vn scene stub` | работает | **не работает** — `_find_chapter` ищет только в `content/chapters/` (`scaffold.py:82`) |
| Требование сверху | — | `packs/<id>/manifest.yaml` (`pack_manifest@1`): `id` == имени папки, `api_level {min ≤ 1 < below}`, `requires.core` совместим с `project.yaml: version` — иначе пак не собирается (G9, `compile.py:437-471`) |
| `vn content lint` | полная структурная проверка | структура глав и графа проверяется (`lint.py:194-196` добавляет `packs/*/chapters`), **но** `store` в `vars.yaml` пака не проверяется (`lint.py:348-349`), а персонажи пака структурно не линтуются (`lint.py:332-333`) |
| `vn content graph` | видит | видит (2026-08-18, `repo.chapter_zones`) |
| Куда компилируется | `game/generated/scenes/chNN/` | **туда же** — общее пространство имён; конфликт id ядра и пака = ошибка компиляции (`compile.py:727-729`) |
| `vn release changelog` / `ci/release-manifest.json` | видит | видит (2026-08-18): в changelog глава пака помечена `(pack <id>)`, в манифесте — полем `pack` |
| Гейт по флейвору | — | **NOT IMPLEMENTED**: `VN_PACKS` перечисляет все паки из `packs/` независимо от `flavors.<f>.packs`. Владение при этом гейтится: провайдер подключён (ADR-0014, `035_platform.rpy:75`), но только под Steam — вне него `owned()` всегда `True` |
| Поставка | вместе с игрой | `vn pack build <id>` → `build/packs/<id>.zip`: только `manifest.yaml` + скомпилированные `.gen.rpy`/`.rpyc` сцен. Ни ассетов, ни `tl/`, ни персонажей — **PARTIALLY IMPLEMENTED**. Охранник «объявлены главы, но нет ни одной скомпилированной сцены» рабочий и падает до создания zip (`cli.py:1624-1626`); пак без глав собирается штатно с предупреждением. Остаток: проверка идёт «хоть одна сцена на весь пак», не по каждой главе |

Практически: главу пака пишете тем же контрактом (метки, exits, say-id — всё идентично, `vn loc keys` и `vn loc extract` паки видят, `keys.py:48-49`), но скаффолдинг, граф и changelog делаете вручную и проверяете `vn pack validate`.

---

## Как изменить / Как расширить

**Добавить сцену в середину главы.** Займите свободный номер между соседями (`s015`) — создайте пару файлов руками по шаблонам из §2, добавьте `s015` в `scene_order`, перенаправьте `exits` предыдущей сцены на `s015`, а из `s015` — на бывшую цель. Ничего не переименовывайте.

**Разделить длинную сцену надвое.** Новая сцена получает следующий свободный номер (не «промежуточный» — это не обязано быть по порядку прохождения). В исходной сцене замените хвост на `return "<new_exit>"`, добавьте exit в её `scene.yaml`. say-id из перенесённого текста **умрут**: перенесённые реплики получат новые id при следующем `vn loc keys`, а старые уйдут в PO как obsolete. Инструмента переноса переводов нет (`vn loc keys --migrate` — **NOT IMPLEMENTED**).

**Переименовать слуг главы или сцены.** Переименуйте папку/оба файла пары, прогоните `vn content lint`. Id и say-id не меняются, переводы целы.

**Удалить сцену до релиза** (глава ещё `draft`/`playtest`, id не в `id_registry.json`): удалите пару файлов, уберите из `scene_order`, перенаправьте входящие `exits`, прогоните `vn loc keys` (осиротевший шард ledger чистится автоматически, `keys.py:235-249`).

**Удалить сцену после релиза:** нельзя просто удалить — G7. Заведите запись в `content/renames.yaml` (`deleted_scenes: {chNN_sNNN: {fallback: chNN_sMMM, since: X.Y.Z}}` или `scenes:` для переименования), иначе `lint.py:383-388` выдаст `выпущенная сцена … исчезла без записи в renames.yaml`.

**Добавить новый язык для главы** — ничего в главе менять не нужно: `vn loc add <code> --name <native>` и всё (ADR-0005, языки обнаруживаются автоматически).

**Сделать `scene_order` источником навигации** — сегодня это не так (поле проверяется, но не используется). Изменение затронет `compile.py:1061-1063` и `lint.py:321-330`; сначала ADR.

---

## Чего НЕ делать

- **Не править `game/generated/scenes/chNN/*.gen.rpy`.** Это выход компилятора; `vn build` перезапишет, `vn build --check` покраснеет. Авторский текст в конце сгенерированного файла — копия, а не источник (`scenes.py:270-271`).
- **Не менять номер сцены или главы.** Это смена id: гибнут say-id, якоря галереи/достижений, а после релиза — G7.
- **Не делать `jump` в чужую сцену.** Компилятор откажет, а если бы пропустил — сцена стартовала бы без фона, музыки, `checkpoint` и с рассинхроненным call-стеком.
- **Не писать условные пункты меню** (`"текст" if cond:`). Движок фильтрует их до `screen choice`, и перевод по индексу (G8) съедет на соседние пункты. Разводите ветвление сценой или флагом.
- **Не оставлять список условных `exits` без безусловной последней записи** — иначе игрок падает в `vn_scene_unavailable`, а smoke даёт `FAIL`.
- **Не ставить хвостовой комментарий на строке say** — `vn loc keys` не сможет дописать id и откатит файл.
- **Не игнорировать warning'и в `draft`.** Ровно они станут ошибками при переводе главы в `playtest` (G15).
- **Не рассчитывать, что `vn content graph` покажет главы паков** — он их не видит.
- **Не полагаться на `scene_order` как на порядок прохождения** — он ни на что не влияет, кроме проверок «существует» и «последняя = легитимный тупик».
- **Не забывать `vn loc keys` перед PR** — CI проверяет `--check` и рубит сборку.
- **Не заводить главу с `status: release` заранее.** Это включает G7-заморозку id через `vn release changelog` и делает граф-проверки жёсткими до того, как глава дописана.
- **Не создавать главу пака через `vn chapter new`** — она уедет в ядро.

---

## Проверка

```bash
vn content lint                          # конвенции, граф, достижимость, парность файлов
vn content graph                         # ветвление глазами (ядро; паки не видны)
vn build                                 # lint -> ассеты -> генерат -> game/tl; бюджеты G19
vn build --check                         # то же без записи — режим CI
vn loc keys --check                      # все say с id, ledger свеж
vn loc report                            # покрытие переводов
vn test smoke --picks 0,0                # прогон ветки автопилотом
vn test smoke --picks 0,1 --lang en
vn save check && vn save corpus          # совместимость сейвов (2 фикстуры)
vn release validate --flavor public      # 21 проверка релизного гейта
python -m pytest tools/vn/tests -q       # 373 теста тулинга
```

Ожидаемое сейчас: `vn content lint` → `lint: OK (0 предупреждений)`; `vn build` → `build: OK`; `vn release validate --flavor patron` → 21 строка (20 PASS + 1 WARN), exit 0 (среди них — `PASS сейв-корпус: 2 фикстур`); у `--flavor public` — 20 строк, 0 FAIL и второй WARN по зрелости контента, exit 0.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/content/scaffold.py` (шаблоны и нумерация), `tools/vn/src/vn/content/scenes.py:76-410` (контракт `.rpy` + эмиссия обвязки), `tools/vn/src/vn/content/lint.py:154-330` (структура глав, exits, достижимость), `tools/vn/src/vn/content/compile.py:500-583,740-784` (сбор глав, статус-градация), `tools/schemas/chapter@1.schema.json`, `tools/schemas/scene@1.schema.json`, `tools/schemas/vars@1.schema.json`, `docs/conventions/naming.md`, живой образец `content/chapters/ch01_awakening/**` |
| **Не трогать** | `game/generated/**` (выход `vn build`), `game/assets/**` (выход `vn assets build`), `game/tl/**` (выход `vn loc import`), `loc/ledger/*.json` руками (пересобирается `vn loc keys`), `content/registry/id_registry.json` руками (пишет `vn release changelog`), `.vncache/**`, `build/**` |
| **Зависимости (что сломается ниже по течению)** | id главы/сцены → метки генерата → say-id в PO → `game/tl/*` → якоря `content/gallery/*.yaml` и `content/achievements/*.yaml` → `content/registry/id_registry.json` (после релиза — навсегда). `exits` → граф достижимости в линте, dispatch-блоки в обвязке, `vn content graph`. `entry_scene` → `entry_label` в `VN_CHAPTERS` → `label start` и экран выбора глав. Переменные главы → `state/defaults.gen.rpy` → сейвы → миграции |
| **Валидация** | `vn content lint && vn build && vn loc keys --check && vn test smoke --picks 0,0` |
| **Частые ошибки** | 1) Создать сцену и забыть `exits`/`scene_order` — в `draft` это лишь warning, глава молча недостижима. 2) Написать `jump` в другую сцену вместо `return "<exit_id>"` — компилятор откажет. 3) Условный пункт меню — запрещён (ломает перевод по индексу). 4) Забыть `vn loc keys` после правки реплик — CI красный на `--check`. 5) Править `game/generated/` вместо `content/`. 6) Считать, что `scene_order` задаёт порядок прохождения — его задают только `exits`. 7) Пытаться создать главу пака через `vn chapter new`. 8) Менять номер сцены при рефакторинге — это смена id. 9) Ссылаться на `docs/ARCHITECTURE.md` как на описание работающего кода: там `vn validate`, `vn content lint --strict/--arch/--schemas`, `vn build --use-artifact`, `vn test paths` — всё **NOT IMPLEMENTED** |
