# 12. Сцены: пара `yaml` + `rpy`, обвязка, exits

> **Статус подсистемы:** IMPLEMENTED — контракт сцены, валидация авторского `.rpy` через парсер Ren'Py и эмиссия обвязки работают полностью; частичные дыры: `scene.yaml:id`/`title_key` читает только линтер (или никто), `exits.when` не валидируется ничем, скаффолдер не умеет в `packs/`.
> **Отвечает на вопрос:** «Как написать сцену так, чтобы она собралась, и как связать её со следующей?»

Сцена — это **пара файлов с одинаковым именем** в `content/chapters/chNN_<slug>/scenes/`: `sNNN_<slug>.scene.yaml` (декларация) и `sNNN_<slug>.scene.rpy` (только тело диалога). Компилятор читает пару, прогоняет `.rpy` через настоящий парсер Ren'Py (build-bridge, G24), валидирует контракт меток и переходов и генерирует третий файл — `game/generated/scenes/chNN/chNN_sNNN.gen.rpy`, где лежит label-обвязка плюс дословная копия авторского источника. Ни `screen`, ни `jump` между сценами, ни `scene bg` автор не пишет.

## Быстрый ответ

```bash
vn scene new ch01 rooftop_night     # -> content/chapters/ch01_awakening/scenes/s040_rooftop_night.scene.{yaml,rpy}
# 1) в s040_*.scene.yaml: location:, participants:, exits:
# 2) в s040_*.scene.rpy: label ch01_s040__body: ... return "<exit_id>"
# 3) связать: в предыдущей сцене exits: { <id>: s040 }
# 4) добавить s040 в scene_order главы (скаффолдер chapter.yaml НЕ трогает)
vn loc keys                          # проставит say-id и маркеры $ vn_menu
vn build                             # lint -> assets -> compile
```

Правило одной строкой: **внутри сцены — `jump ch01_s040__branch`; между сценами — `return "exit_id"` и `exits:` в YAML.**

## Пара файлов: кто за что отвечает

| | `sNNN_<slug>.scene.yaml` | `sNNN_<slug>.scene.rpy` |
|---|---|---|
| Что это | декларация: где, кто, куда ведёт | только текст, показ спрайтов, ветвление внутри сцены |
| Кто читает | `compile.py` + `scenes.py` + `lint.py` | парсер Ren'Py через `renpy.exe <root> vn_analyze` |
| Схема | `scene@1` (`tools/schemas/scene@1.schema.json`) | контракт в `tools/vn/src/vn/content/scenes.py:152-280` (`validate_scene`) + `:76-149` (`_validate_refs`) |
| Обязателен | да | да — отсутствие пары = ошибка `нет парного .scene.rpy (G3)` (`compile.py:770-772`, дублирует `lint.py:229-231,236-238`) |

Разделение жёсткое: **`.rpy` не решает, куда идти дальше**, он только возвращает строковый ярлык. Куда ведёт ярлык — знает YAML. Поэтому переставить порядок сцен = правка YAML, не текста.

Живой пример — `content/chapters/ch01_awakening/scenes/s020_school_gate.scene.yaml`:

```yaml
schema: scene@1
id: s020
participants: [mira]
location: school_gate/day
vars:
  reads: [ch01.met_mira]
exits:
  roof: s030
```

## Полная таблица полей `scene.yaml`

Схема требует ровно `["schema","id"]` и запрещает всё лишнее (`additionalProperties: false`). Ниже — как поле читает **компилятор**, и где схема расходится с кодом.

| Поле | Схема (`scene@1`) | Кто читает | Эффект | Расхождение |
|---|---|---|---|---|
| `schema` | `const: "scene@1"`, **required** | `compile.py:766-769` (`registry.validate`) | иначе «неизвестная схема» / «нет поля schema (G16)» | — |
| `id` | `^s\d{3}$`, **required** | **компилятор не читает** | identity сцены выводится из имени файла регуляркой `SCENE_YAML_RE` (`compile.py:32`), `full_id = f"{ch_id}_{short_id}"` (`compile.py:775-777`) | `id`, противоречащий имени файла, **компилируется**; ловит только линтер, правило `{f}: id (...) != номеру файла (...)` (`lint.py:233-234`) |
| `title_key` | `^[a-z0-9_.]+$` | **никто** | — | мёртвая поверхность схемы: `grep title_key` по `tools/vn/src/vn/` даёт только главы и галерею |
| `participants` | массив `^[a-z][a-z0-9_]{1,23}$`, uniqueItems | `compile.py:1031-1037` | каждый id обязан существовать в `content/characters/`, иначе ошибка `участник 'x' не объявлен в content/characters/ (say упадёт NameError в рантайме)` | проверка **односторонняя**: персонаж, использованный в `.rpy` но не указанный в `participants`, не ловится ничем |
| `location` | `^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)?$` — вариант **опционален** | `scenes.py:344-370` | `scene bg <loc> <variant> with dissolve`; при любой ошибке или отсутствии поля — `scene vn_black with dissolve` | компилятор **требует** `/<variant>`: `location: rooftop` lint-зелёный, build-красный |
| `music` | `^bgm/[a-z][a-z0-9_]*$` | `_emit_track`, `scenes.py:304-331` | трек обязан быть объявлен в `content/audio/` с `kind: bgm` → `play music <id> fadeout 1.0 fadein 1.0` (+ `volume` из `audio@1`, если ≠ 1) | сегодня все `content/audio/*.yaml` имеют `tracks: {}` — **любое** значение `music:` = ошибка компиляции. Схема не допускает `/` в хвосте, т.е. `bgm/ch01/theme` невалиден |
| `ambient` | `^amb/[a-z][a-z0-9_]*$` | `_emit_track`, `scenes.py:304-331`; вызов — `:372-375` | зацикленный эмбиенс локации: `play ambient <id> …` на канале `ambient` (`045_audio.rpy:13`) — играет **одновременно** с `music` | то же: треков `amb` пока ноль. См. [23-audio.md](23-audio.md) §3 |
| `vars.reads` / `vars.writes` | массивы `^(g\|chNN\|mech_*\|dlc_*)\.<name>$` | `scenes.py:244-259` | **только предупреждения**: сверка объявленного с фактом из AST | реальная проверка переменных — другая: любой store-атрибут из `.rpy` обязан быть в Variable Registry (`scenes.py:232-243`), ошибка (warning для `status: draft`) |
| `exits` | объект; ключ `^[a-z][a-z0-9_]*$`; значение — `oneOf`: строка-target \| `{to,when}` \| массив `{to,when}`; `target` = `^(s\d{3}\|ch\d{2}/s\d{3})$` | `scenes.py:200-227` (валидация) + `:264-279` (резолв цели) + `:380-392` (эмиссия) | таблица диспетчеризации `if _return == "<id>"` | `when` — `{"type":"string","minLength":1}`, **никем не парсится и не проверяется**, несмотря на docstring `030_flow.rpy:57-59` «валидируется компилятором против реестра переменных» |

Чего в схеме **нет** и заводить нельзя без правки схемы: `beat`, `nsfw`, `pack`, `status`, `owner`, `anchors`.

## Контракт авторского `.scene.rpy`

Всё проверяется на реальном AST от Ren'Py SDK — не регулярками по тексту (`tools/vn/src/vn/content/analyze.py` → `renpy.exe <root> vn_analyze`, мост в `game/framework/00_core/050_build_bridge.rpy:98-144`).

| # | Правило | Нарушение | Код |
|---|---|---|---|
| 1 | На верхнем уровне файла — **только `label`** | `line N: стейтмент Say вне label запрещён в scene.rpy` | `050_build_bridge.rpy:129-134` |
| 2 | Имя метки матчит `^ch\d{2}_s\d{3}__[a-z0-9_]+$` **и** префикс равен `full_id` этой сцены | `метка 'x' вне контракта ^ch01_s020__<suffix>$ (C2; naming.md)` | `scenes.py:18,165-172` |
| 3 | Метка `<full_id>__body` обязательна | `нет обязательной метки ch01_s020__body (C2)` | `scenes.py:173-174` |
| 4 | `jump`/`call` — только на метки своей сцены | `jump ch02_s010 — переход вне своей сцены; межсценовые переходы только через return "<exit_id>" + exits (C2)` | `scenes.py:184-188` |
| 5 | `jump expression` / `call expression` запрещены | `jump expression запрещён в авторских сценах (динамические цели ломают статический анализ и prediction)` | `scenes.py:178-182` |
| 6 | Условные пункты `menu` запрещены | `условный пункт меню #0 ('...') — запрещено (ломает перевод по индексу); используйте ветвление сцены` | `scenes.py:190-198` |
| 7 | `return <expr>` — только строковый литерал или пусто | `return с не-литеральным выражением — exit-id обязан быть строковым литералом` | `_literal_exit`, `scenes.py:56-66`; проверка — `:202-209` |
| 8 | Возвращаемое значение обязано быть объявлено в `exits` | `return 'roof' не объявлен в exits (…: ['gate'])` | `scenes.py:217-221` |
| 9 | Пустой `return` при непустых `exits` | `пустой return в сцене с объявленными exits — завершайте return "<exit_id>"` | `scenes.py:211-216` |
| 10 | Объявленный exit, до которого не доходит ни один `return` | **предупреждение** `exits.roof не достигается ни одним return в …` | `scenes.py:223-227` |
| 11 | Любой store-атрибут (`ch01.met_mira`) обязан быть в Variable Registry | ошибка (для `status: draft` — предупреждение): `… пишется, но не объявлена в Variable Registry … молчаливый фантом-стор вне сейва/миграций (G5)` | `scenes.py:232-243` |
| 12 | `show`/`hide` на несуществующий образ, тег или атрибут персонажа; `show expression` | `show mira hapy — у персонажа mira нет атрибут(ов) hapy (есть: …)`, `hide X — нет такого образа/тега`, `show expression — динамический образ запрещён` | `_validate_refs`, `scenes.py:89-121` |
| 13 | `play music/ambient/sound <id>` на необъявленный трек или на канал, не соответствующий `kind` | `play music clam_theme — трек не объявлен в content/audio/*.yaml (в рантайме будет тишина)`, `— трек объявлен как sfx, каналу music разрешены только amb/bgm` | `_validate_refs`, `scenes.py:123-149`, карта `CHANNEL_KINDS:73` |

**Грабля парсера:** Ren'Py дописывает неявный `Return` в конец каждого файла. Build-bridge его отрезает (`050_build_bridge.rpy:122-127`) — иначе каждый файл ловил бы правило №9. Если вы правите мост, не потеряйте этот срез.

## Послойные шоты в сцене (shots@1)

Полнокадровый кинематографический кадр можно собрать из слоёв вместо плоского `cg` ([ADR-0013](../adr/0013-layered-shots.md), декларация и мастера — [16-assets.md](16-assets.md)). На сцену эмитится один `layeredimage shot_<chNN>_<sNNN>`; в авторском `.rpy` шот показывается как обычный образ:

```renpy
# content/chapters/ch01_awakening/scenes/s030_rooftop.scene.rpy — рабочий пример
scene shot_ch01_s030 sunset with dissolve        # шот sunset, наряд — из переменной гардероба
scene shot_ch01_s030 sunset mira_school          # явный атрибут <layer>_<variant> переопределяет её
```

Смена шота — смена атрибута группы `shot` (предыдущий снимается сам, выбранный наряд «липнет» между шотами сцены). Слой с `var:` в декларации по умолчанию выбирает вариант `ConditionSwitch`'ем по переменной Variable Registry (у демо — `g.mira_outfit`). Ссылки `scene`/`show shot_… <шот> [<layer>_<variant>]` сверяются с декларацией на сборке, как атрибуты персонажей (`images.py:164-169`) — опечатка в имени шота или варианта краснит `vn build`, а не даёт пустой кадр игроку.

## Разбор реального генерата: `game/generated/scenes/ch01/ch01_s020.gen.rpy`

Файл 39 строк. Первые 19 — обвязка (её пишет `emit_scene`, `scenes.py:334-410`), остальное — дословная копия авторского `.rpy`.

```renpy
 1  # ══════════════════════════════════════════════════════════════
 2  # AUTO-GENERATED by vn content compile (vn 0.1.0)
 3  # source: content/.../s020_school_gate.scene.yaml  blake3:46a374fe6412ff5c
 4  # source: content/.../s020_school_gate.scene.rpy   blake3:827e6eee29a4c014
 5  # НЕ РЕДАКТИРОВАТЬ. Правки перезапишутся. Меняйте источник.
 6  # ══════════════════════════════════════════════════════════════
 7
 8  label ch01_s020:
 9      $ vn.checkpoint("ch01_s020")
10      $ renpy.scene("sprites")
11      scene bg school_gate day with dissolve
12      call ch01_s020__body from _call_ch01_s020__body
13      $ vn.check_scene_stack()
14      if _return == "roof":
15          jump ch01_s030
16      # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)
17      $ vn.unwind_call_stack()
18      $ vn_unavailable_reason = "unknown_exit"
19      jump vn_scene_unavailable
20
21  # ══ Авторский источник (копия): content/.../s020_school_gate.scene.rpy ══
22  label ch01_s020__body:
    …далее — файл автора байт в байт…
```

| Строка | Что это | Откуда |
|---|---|---|
| 1-6 | Шапка с blake3 каждого источника. Меняется при любой правке источника → файл считается «несвежим» в `vn build --check` | `compile.py:62` |
| 8 | **Метка-обвязка = ровно `full_id`**, без слуга. Именно на неё делают `jump` соседние сцены и `entry_label` главы | `scenes.py:338` |
| 9 | Отметка прохождения: питает галерею, достижения и `vn.chapter_done` | `scenes.py:339`; рантайм `030_flow.rpy:12` |
| 10 | Явная очистка слоя `sprites`. `scene` чистит только свой слой (`master`) — без этой строки персонажи предыдущей сцены протекали бы в следующую | `scenes.py:340-342` |
| 11 | Фон из `location: school_gate/day`. Без `location:` здесь было бы `scene vn_black with dissolve` | `scenes.py:344-370`, см. [11-locations.md](11-locations.md) |
| (нет) | `play music <id> fadeout 1.0 fadein 1.0` и/или `play ambient <id> …` — появились бы между 11 и 12 при наличии `music:`/`ambient:` | `scenes.py:304-331`, вызов `:372-375` |
| 12 | `call` (не `jump`!) в тело автора с явным `from`-именем: Ren'Py требует стабильные имена точек возврата для совместимости сейвов | `scenes.py:377` |
| 13 | Инвариант G7: глубина call-стека на границе сцены = 0. Нарушение пишется в лог, не падает | `scenes.py:378`; рантайм `030_flow.rpy:44-48` |
| 14-15 | Таблица диспетчеризации: **по одному блоку `if` на каждую запись `exits`**, в порядке YAML. С `when` строка была бы `if _return == "roof" and vn.eval_when('g.route == "mira"'):` | `scenes.py:380-392` |
| 16-19 | Терминальный fallback: неизвестный/отсутствующий exit → размотать стек → причина `"unknown_exit"` → `vn_scene_unavailable` | `scenes.py:400-403` |
| 21+ | Копия авторского файла (с инжектированными `voice vn.voice_path("<say-id>")` перед озвученными репликами, если глава покрыта voice-манифестом) — в отладчике Ren'Py вы видите ваш текст | `scenes.py:405-408`, `_inject_voice` `scenes.py:283-300` |

Два других варианта финала обвязки — оба живые в репозитории:

**Терминальная сцена (пустые `exits`)** — `game/generated/scenes/ch01/ch01_s030.gen.rpy:13-19`:

```renpy
    $ vn.check_scene_stack()
    $ vn.chapter_done("ch01")
    if _return is None:
        jump vn_end_of_content
    # Неизвестный exit: …
    $ vn.unwind_call_stack()
    $ vn_unavailable_reason = "unknown_exit"
    jump vn_scene_unavailable
```

`chapter_done` — единственный якорь «глава пройдена» для галереи и достижений; ручного кода в сценах он не требует (`scenes.py:394-399`).

**Draft-глава с ненаписанной целью** (`status: draft` + exit на несуществующую сцену) — вместо `jump` эмитится живая заглушка (`scenes.py:386-390`, ветка `to_label is None` из `:269-276`):

```renpy
    if _return == "roof":
        # TODO(draft): цель ch01_s040 ещё не написана
        $ vn.unwind_call_stack()
        $ vn_unavailable_reason = "draft_todo"
        jump vn_scene_unavailable
```

Для `status: playtest|release` та же ситуация — ошибка компиляции, не заглушка (G15, `scenes.py:269-275`).

## Что происходит при неизвестном exit

`vn.unwind_call_stack()` в цикле делает `renpy.pop_call()`, пока глубина стека не станет 0 — **и только это**; куда идти дальше, решает вызывающий код. Обвязка перед `jump vn_scene_unavailable` выставляет причину (`vn_unavailable_reason = "draft_todo" | "unknown_exit"`; рантайм добавляет `"missing_content"` для shim-меток выпущенных id, отсутствующих в сборке). Дальше (`030_flow.rpy:232-242`):

```renpy
label vn_scene_unavailable:
    if vn_qa.autopilot_active():
        $ vn_qa.autopilot_finish("FAIL: vn_scene_unavailable")
    $ renpy.block_rollback()    # гейт нельзя объехать колёсиком
    call screen vn_content_unavailable(vn_unavailable_reason)
    $ vn_unavailable_reason = None
    $ renpy.full_restart()
```

Игрок видит модальный экран `vn_content_unavailable` (`game/framework/20_ui/screens/unavailable.rpy`) с объяснением причины и действиями «меню / загрузка / выход» вместо безусловного выброса в меню, а **smoke-автопилот считает прогон проваленным**. Это и есть способ поймать битую связку в CI: `vn test smoke` вернёт FAIL. Симметрично `vn_end_of_content` (`030_flow.rpy:245-…`) завершает автопилот успехом.

## `vn scene new` vs `vn scene stub`

Обе команды — `tools/vn/src/vn/content/scaffold.py`, CLI на `cli.py`. Обе создают **пару** файлов и **не трогают `chapter.yaml`**.

### `vn scene new <chapter> <slug>`

`scaffold.py:120-137`. Глава ищется по точному имени папки или префиксу `<chapter>_`, совпадение должно быть единственным (`_find_chapter`, `scaffold.py:81-95`). Слуг обязан матчить `^[a-z][a-z0-9_]{2,30}$`. Номер — `(max_существующий // 10) * 10 + 10`, то есть шаг 10.

Создаёт `sNNN_<slug>.scene.yaml` дословно (`scaffold.py:28-38`):

```yaml
schema: scene@1
id: sNNN
exits: {}
# exits:
#   done: s020                        # короткая ссылка внутри главы
#   alt:
#     - {when: "g.route == 'mira'", to: s030}
#     - {to: ch02/s010}              # межглавная ссылка
```

и `sNNN_<slug>.scene.rpy` (`scaffold.py:41-48`):

```renpy
# Метки — только chNN_sNNN__body и chNN_sNNN__<branch> (C2, naming.md).
# Переходы между сценами — return "<exit_id>"; цели в exits: scene.yaml.

label chNN_sNNN__body:
    "…"
    return
```

CLI печатает напоминание `не забудьте: добавить сцену в scene_order главы и связать exits` (`cli.py`) — сделайте это руками.

### `vn scene stub <chapter> <sNNN>`

`scaffold.py:98-117`. Номер задаётся **явно**, обязан матчить `^s\d{3}$` и не существовать. Файлы называются `<sNNN>_stub.scene.{yaml,rpy}`, содержимое минимальное:

```yaml
schema: scene@1
id: sNNN
exits: {}
```
```renpy
label chNN_sNNN__body:
    "Заглушка: сцена в разработке."
    return
```

**Когда нужен stub:** вы уже объявили `exits: { roof: s040 }`, но `s040` ещё не написана. В `draft`-главе такой exit скомпилируется в `# TODO(draft)` + `vn_scene_unavailable`, и `vn test smoke`, дойдя до него, упадёт с FAIL. Stub закрывает дыру: smoke-прогон проходит, игрок видит заглушку (G15).

| | `new` | `stub` |
|---|---|---|
| Номер | автоматический, шаг 10 | вы задаёте |
| Имя файла | `sNNN_<ваш slug>` | `sNNN_stub` |
| YAML | с закомментированным примером `exits` | три строки |
| RPY | `"…"` + `return` | `"Заглушка: сцена в разработке."` + `return` |
| Проверка занятости | нет (номер вычисляется) | есть — `сцена sNNN уже существует` |

**Ограничение обеих:** `_find_chapter` смотрит только в `content/chapters/` (`scaffold.py:82`). **Сцену внутри пака (`packs/ep_beach/chapters/…`) скаффолдер создать не может** — там всё руками. Скаффолда для `location.yaml`, `character.yaml`, `*.vars.yaml` не существует вовсе (`vn char new` — заглушка фазы 1, `cli.py`).

Ещё нюанс: `scaffold.py:10 SLUG_RE` ограничивает слуг 30 символами, а линтер (`lint.py:17`) разрешает до 40. Легальный 35-символьный слуг скаффолдером не создать — только руками.

## Как добавить ветку внутри сцены

Ветка — это ещё одна метка **того же** `full_id`. Реальный пример, `content/chapters/ch01_awakening/scenes/s020_school_gate.scene.rpy`:

```renpy
label ch01_s020__body:
    show mira a school neutral at center with dissolve
    mira "Ты опять проспал?" id ch01_s020_0001

    $ vn_menu = "ch01_s020_m001"
    menu:
        "Соврать":
            show mira angry
            mira "Ну-ну. Очень убедительно." id ch01_s020_0002
            jump ch01_s020__caught
        "Сказать правду":
            show mira smile
            mira "Хотя бы честно. Пойдём, провожу до крыши." id ch01_s020_0003
            return "roof"

label ch01_s020__caught:
    show mira smile
    mira "Ладно. Беги, звонок уже был." id ch01_s020_0004
    return "roof"
```

Правила: метка ветки — `ch01_s020__<что_угодно_в_нижнем_регистре>`; `jump` на неё легален (та же сцена); каждая ветка обязана завершиться `return "<exit_id>"` из объявленных `exits`. Маркер `$ vn_menu = "chNN_sNNN_mNNN"` перед `menu:` ставит `vn loc keys` — не пишите его руками. Условные пункты меню (`"Текст" if cond:`) запрещены правилом №6: переводы пунктов идут по индексу, и фильтрация движком сдвинула бы их на соседние строки. Нужна условность — делайте ветвление сцены или отдельный exit с `when`.

Подробнее про меню, `i.chosen` и экран выбора — [13-dialogue.md](13-dialogue.md).

## Как соединить сцены

Три формы значения в `exits` (нормализует `_exit_entries`, `scenes.py:39-45`):

```yaml
exits:
  # 1. простая цель — внутри главы или межглавная
  gate: s020
  epilogue: ch02/s010

  # 2. цель с условием
  secret: {when: "g.route == 'mira'", to: s050}

  # 3. список: первый подошедший по условию выигрывает (порядок = порядок YAML)
  next:
    - {when: "ch01.met_mira", to: s030}
    - {to: s040}
```

Резолв цели: `s030` → `ch01_s030`, `ch02/s010` → `ch02_s010` (`resolve_target`, `scenes.py:48-53`). Метка сцены = её полный id, поэтому межглавный переход работает без регистрации где-либо ещё.

`when` превращается в `and vn.eval_when('<выражение>')`, а `eval_when` — это буквально `renpy.python.py_eval(expr)` (`030_flow.rpy:57-60`). **Выражение не проверяется никем**: ни схемой (там только `minLength: 1`), ни компилятором, ни линтером. Опечатка в имени переменной = `NameError` в рантайме на этом переходе. Пишите `when` только по переменным из Variable Registry и прогоняйте `vn test smoke`.

Проверка связности: `vn content lint` строит BFS от `entry_scene` по `exits` и ругается на недостижимые сцены и тупики (`lint.py:257-295`). Для `status: draft` это предупреждения, для `playtest|release` — ошибки (G15). Визуально: `vn content graph` печатает Mermaid:

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

Граф читает и `content/chapters/`, и `packs/*/chapters/` (`repo.chapter_zones`, 2026-08-18): `ch90_s010` из `packs/ep_beach` в выводе есть, а её подграф подписан `· pack ep_beach`.

## Как изменить / Как расширить

| Задача | Шаги |
|---|---|
| Переставить сцены местами | правьте только `exits:` в YAML и `scene_order` в `chapter.yaml`; текст не трогается. Номера `sNNN` — человекочитаемые якоря, а не порядок (`scene_order` компилятором на порядок **не** влияет: проверяется только существование, `compile.py:782-784`) |
| Вставить сцену между s020 и s030 | `vn scene new` даст `s040`; перенаправьте `exits` s020 → `s040`, у `s040` → `s030`; допишите `s040` в `scene_order` |
| Добавить условную развилку | форма 3 в `exits` (список с `when`), первый подошедший выигрывает |
| Разрезать длинную сцену | новая сцена + exit; **не** делайте `call` в чужую сцену — правило №4 |
| Удалить сцену | удалите пару файлов + все `exits`, которые на неё вели. Если сцена была выпущена (есть в `content/registry/id_registry.json`) — обязательна запись в `content/renames.yaml`, иначе `lint.py:351` красный (G7). Сегодня реестр пуст, глава `draft`, гейт инертен |
| Переименовать сцену | id неизменяем. Меняйте только слуг в имени файла (id — из `sNNN`), это безопасно |
| Сцена в паке | всё руками в `packs/<id>/chapters/chNN_<slug>/scenes/`; правила и генерат идентичны (`game/generated/scenes/ch90/ch90_s010.gen.rpy` — рабочий пример). См. [30-packs-and-dlc.md](30-packs-and-dlc.md) |

## Чего НЕ делать

- **Не правьте `game/generated/scenes/**`** — перезапишет `vn build`, файлы вне git. Ошибку ищите в `content/`.
- **Не делайте `jump`/`call` в другую сцену.** Только `return "<exit_id>"`. Прямой `jump ch01_s030` из тела сцены — ошибка компиляции и, в обход `checkpoint`, сломанный call-стек.
- **Не используйте `jump expression` / `call expression`** — динамические цели ломают статический анализ и prediction Ren'Py.
- **Не пишите условные пункты меню** — ломается перевод по индексу (G8).
- **Не выдумывайте имена меток.** Только `chNN_sNNN__body` и `chNN_sNNN__<branch>`; префикс обязан совпасть с id **этой** сцены (скопировали файл — поправьте все метки).
- **Не проставляйте `id ch01_s020_0005` руками** — say-id раздаёт `vn loc keys` и пишет их в `loc/ledger/chNN.json`. Дубликат id ловится с сообщением `дубликат say-id … (copy-paste?) — переводы перезаписали бы друг друга` (`tools/vn/src/vn/loc/keys.py:100-105`).
- **Не забывайте `vn loc keys` после написания реплик.** CI гоняет `vn loc keys --check` (`.github/workflows/ci.yml:64`) и падает на строках без id. `vn build` эту команду **не** вызывает.
- **Не ставьте `location: rooftop`** без варианта — схема пропустит, компилятор упадёт.
- **Не пишите `music:`/`ambient:` сегодня** — в `content/audio/*.yaml` нет ни одного трека, любое значение = ошибка.
- **Не рассчитывайте, что `id:` в YAML что-то решает** — identity сцены берётся из имени файла.
- **Не кладите стейтменты вне `label`** в `.scene.rpy` — build-bridge отклонит файл целиком.
- **Не ждите `$ vn_qa.choice(...)` в генерате.** `ARCHITECTURE.md:544-551` описывает его как первый стейтмент каждой ветки меню — **NOT IMPLEMENTED**: `emit_scene` копирует авторский источник дословно, а `vn_qa.choice` в `030_flow.rpy:98-101` — пустой `pass`.

## Проверка

```bash
vn content lint                 # схемы, пары файлов, дубликаты id, достижимость, тупики
vn content graph                # глазами: развилки и тупики (только core-главы)
vn loc keys --check             # все ли реплики с id и свеж ли ledger
vn build                        # lint -> assets -> compile (нужен RENPY_SDK: парсер сцен)
vn build --check                # CI: ничего не пишет, падает на несвежем генерате
vn test smoke                   # прогон автопилотом; vn_scene_unavailable = FAIL
python -m pytest tools/vn/tests -q
```

`vn build` и `vn content compile` **требуют `RENPY_SDK`**, если в `content/chapters/` есть главы: разбор `.rpy` идёт только через SDK (G24). В bash-сессиях агента переменная не наследуется — экспортьте вручную:
`export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`.

Быстрая проверка одной сцены глазами:

```bash
cat game/generated/scenes/ch01/ch01_s020.gen.rpy | head -20
```

## Чеклист новой сцены

- [ ] Пара файлов создана: `sNNN_<slug>.scene.yaml` **и** `sNNN_<slug>.scene.rpy`, имена совпадают
- [ ] Имя матчит `^s(\d{3})_([a-z][a-z0-9_]{2,40})\.scene\.(yaml|rpy)$`, номер кратен 10
- [ ] `id:` в YAML равен `sNNN` из имени файла (иначе красный линтер)
- [ ] `participants:` перечисляет всех, кто говорит; каждый существует в `content/characters/`
- [ ] `location: <loc>/<variant>` — **с вариантом**; локация и вариант объявлены (см. [11-locations.md](11-locations.md))
- [ ] Метка `chNN_sNNN__body` есть; все остальные метки — `chNN_sNNN__<branch>`
- [ ] Ни одного `jump`/`call` за пределы сцены; ни одного `expression`-перехода
- [ ] Каждая ветка завершается `return "<exit_id>"`, и каждый такой id объявлен в `exits:`
- [ ] Каждый объявленный exit достижим хотя бы одним `return` (иначе предупреждение)
- [ ] Все переменные из `.rpy` объявлены в `content/variables/*.vars.yaml` или `chapters/*/vars.yaml`
- [ ] Сцена добавлена в `scene_order` главы; на неё ведёт `exits` предыдущей сцены (иначе «недостижима»)
- [ ] Если объявлен exit на ненаписанную сцену — создан `vn scene stub`
- [ ] `vn loc keys` прогнан: say-id проставлены, маркеры `$ vn_menu` на месте, ledger обновлён
- [ ] `vn content lint`, `vn build`, `vn test smoke`, `pytest` — зелёные
- [ ] `vn content graph` показывает сцену на нужном месте, без неожиданного тупика

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/content/scenes.py` (весь, 483 строки — это и есть контракт), `tools/schemas/scene@1.schema.json`, `tools/vn/src/vn/content/scaffold.py`, `game/framework/00_core/030_flow.rpy:1-70,227-242`, любая пара `content/chapters/ch01_awakening/scenes/s020_*` как эталон |
| **Не трогать** | `game/generated/**` (генерат `vn build`), `loc/ledger/*.json` (генерат `vn loc keys`, перезаписывается целиком), `game/tl/**` (генерат `vn loc import`) |
| **Зависимости** | Сцена → `registry/scenes.gen.rpy` (`VN_SCENES`), `registry/menus.gen.rpy` (через ledger), `registry/chapters.gen.rpy` (`entry_label`), достижения (`trigger.scene`) и галерея (`unlock.scene`) в `content/{achievements,gallery}/*.yaml`. Удаление сцены, на которую ссылается достижение, — ошибка компиляции (`compile.py:797-816`) |
| **Валидация** | `vn content lint` → `vn loc keys --check` → `vn build` → `vn test smoke`; в CI это `.github/workflows/ci.yml:29,61,64` |
| **Частые ошибки** | 1) `return "x"`, где `x` не в `exits` → ошибка компиляции. 2) Скопировали файл сцены и забыли переименовать метки — префикс метки обязан совпадать с id новой сцены. 3) Забыли `vn loc keys` → красный CI на `--check`. 4) Забыли добавить сцену в `scene_order`/`exits` → «недостижима» (warning в draft, error в release). 5) `jump` в соседнюю сцену вместо `return`. 6) Правка `.gen.rpy` вместо источника. 7) `vn build` без `RENPY_SDK` → чистая `CompileError`, не traceback |

Смежное: [09-chapters.md](09-chapters.md) — глава целиком, `status` и G15; [11-locations.md](11-locations.md) — `location:`; [13-dialogue.md](13-dialogue.md) — меню, выборы, условия; [14-localization.md](14-localization.md) — say-id, ledger, PO; [25-custom-engine.md](25-custom-engine.md) — как устроен компилятор; [27-testing.md](27-testing.md) — smoke-автопилот; [36-troubleshooting.md](36-troubleshooting.md) — расшифровка сообщений об ошибках.
