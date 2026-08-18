# 13. Диалоги, выборы и ветвление

> **Статус подсистемы:** IMPLEMENTED — реплики, say-id, маркеры меню, выборы, ветвление внутри сцены и переходы между сценами работают целиком. Главное «но»: номера say-id **переиспользуемы** после удаления строки (high-watermark из ARCHITECTURE.md:2505 — NOT IMPLEMENTED), а перевод пунктов меню держится на позиционном индексе, который легко сдвинуть.
> **Отвечает на вопрос:** «Как написать реплику, выбор и развилку так, чтобы это собралось, перевелось и не сломало сейвы».

Диалог живёт в авторском `*.scene.rpy` рядом с декларацией `*.scene.yaml` — например
`content/chapters/ch01_awakening/scenes/s020_school_gate.scene.{yaml,rpy}`. Это обычный
Ren'Py-скрипт с четырьмя ограничениями (метки, `id`, маркеры меню, `return`). Компилятор
не переписывает ваш текст: он копирует файл дословно в генерат и добавляет вокруг
`label`-обвязку (`tools/vn/src/vn/content/scenes.py:270-271`). Всё, что вы пишете руками,
проверяется парсером самого Ren'Py через build-bridge — регексов по `.rpy` в проекте нет
(G24, `game/framework/00_core/050_build_bridge.rpy`).

## Быстрый ответ

```bash
# 1. Пишете реплики и menu в content/chapters/chNN_*/scenes/sNNN_*.scene.rpy — БЕЗ id и БЕЗ vn_menu
# 2. Проставить идентификаторы (правит ваш же файл на месте):
vn loc keys
# 3. Собрать:
vn build
# 4. Посмотреть глазами:
vn test smoke --picks 0,0        # скриншоты в .vncache/smoke/
```

Минимальная сцена целиком (`content/chapters/ch01_awakening/scenes/s010_intro.scene.rpy:4-14`,
состояние после `vn loc keys`):

```renpy
label ch01_s010__body:
    "Первый учебный день. Звонок уже прозвенел, а ты всё ещё стоишь у ворот." id ch01_s010_0001

    $ vn_menu = "ch01_s010_m001"
    menu:
        "Подойти к воротам":
            $ ch01.met_mira = True
            "У ворот кто-то есть." id ch01_s010_0002
            return "gate"
        "Подняться сразу на крышу":
            return "roof"
```

Ключи `gate`/`roof` объявлены в паре — `s010_intro.scene.yaml:5-7`: `exits: {gate: s020, roof: s030}`.

---

## 1. Как пишется реплика

**Статус: IMPLEMENTED.**

| Форма | Пример | Кто говорит |
|---|---|---|
| Нарратор | `"Крыша. Ветер. Город до горизонта." id ch01_s030_0001` | `who: null` в ledger |
| Персонаж | `mira "Ты опять проспал?" id ch01_s020_0001` | `who: "mira"` |

Объект `mira` не объявляется в сцене. Его генерирует компилятор из
`content/characters/mira/character.yaml` в `game/generated/registry/characters.gen.rpy:9`:

```renpy
define mira = Character(_('Мира'), color='#c94f7c', image='mira', voice_tag='mira')
```

`init offset = 500` (`tools/vn/src/vn/content/scenes.py:311`) — то есть `Character` создаётся
после всех реестров. Добавление персонажа — см. [Персонажи](10-characters.md).

`participants: [mira]` в `scene.yaml` **не обязателен** для того, чтобы персонаж заговорил:
единственный потребитель этого поля — проверка «такой персонаж объявлен»
(`tools/vn/src/vn/content/compile.py:755-760`). Если персонажа нет в `content/characters/`
вообще — `say` упадёт `NameError` в рантайме, и никакой сборочный гейт это не поймает,
пока вы не укажете его в `participants`. **Поэтому указывайте.**

### Клауза `id` — её НЕ пишут руками

`id chNN_sNNN_NNNN` дописывает команда `vn loc keys` (`tools/vn/src/vn/loc/keys.py:126`),
разобрав файл парсером Ren'Py. Формат — нормативный (`docs/conventions/naming.md`):

| Сущность | Паттерн | Пример | Где регекс |
|---|---|---|---|
| say-id | `^ch\d{2}_s\d{3}_\d{4}$` | `ch01_s020_0001` | `tools/vn/src/vn/loc/keys.py:23` |
| id меню | `^ch\d{2}_s\d{3}_m\d{3}$` | `ch01_s020_m001` | `tools/vn/src/vn/loc/keys.py:24` |

Что произойдёт, если написать `id` руками:

- **id вне конвенции или от чужой сцены** → ошибка `id ... вне конвенции chNN_sNNN_NNNN (naming.md)`
  (`keys.py:93-99`), exit 1.
- **дубликат id внутри главы** (обычно copy-paste) → ошибка `дубликат say-id ... — переводы
  перезаписали бы друг друга` (`keys.py:100-105`).
- **корректный, но «свой» номер** → пройдёт. Ваш номер попадёт в `used_nums`, и следующая
  новая строка получит `max+1`. Ничего не сломается, но смысла в ручной работе нет.

Что произойдёт, если поменять **текст** реплики и не прогнать `vn loc keys`:

- `id` в исходнике не меняется (это и есть смысл id — правка опечатки не теряет перевод,
  `keys.py:8-10`);
- но `loc/ledger/chNN.json` останется со старым текстом, и переводчики продолжат работать
  со старой строкой;
- гейт: `vn loc keys --check` побайтово сравнивает пересобранный ledger с диском
  (`keys.py:178-194`) и краснеет сообщением
  `loc/ledger/chNN.json устарел (тексты/структура разошлись со сценами) — выполните vn loc keys`;
- в CI это отдельный шаг `.github/workflows/ci.yml:64`, `xvfb-run -a vn loc keys --check`.

**`vn build` НЕ вызывает `vn loc keys`** (`tools/vn/src/vn/cli.py:84-153`: lint → assets →
compile → `_loc_import` → бюджеты). Сборка молча пройдёт с репликами без id — красным станет CI.

### Алгоритм назначения номеров (что важно знать автору)

`keys.py:86-127`:

1. Полный id сцены берётся из **имён файлов**: папка `chNN_<slug>` + файл `sNNN_<slug>.scene.rpy`.
   Слуг в id не входит — переименование слуга безопасно, переименование `chNN`/`sNNN`
   обнуляет все id внутри.
2. Существующие id никогда не пересчитываются.
3. Новый номер = `max(существующие) + 1` (`keys.py:39-40`) — **не** позиция в файле. Реальный
   пример: в `s030_rooftop.scene.rpy` строка `ch01_s030_0006` стоит **выше** `ch01_s030_0005`,
   потому что была вставлена позже.
4. Назначение идёт в порядке чтения, а запись правок — снизу вверх, чтобы номера строк
   не съезжали (`keys.py:111,118`).
5. После правки файлы **перечитываются мостом заново**. Если parse упал или остались say
   без id — все изменённые файлы откатываются из памяти и бросается `KeysError`
   (`keys.py:198-219`).

**Номера переиспользуемы.** `used_nums` собирается только из id, физически присутствующих
в файле (`keys.py:106`), а ledger пересобирается с нуля каждый прогон (`keys.py:88-89`).
Удалили последнюю по номеру реплику — её номер освободится для следующей новой.
ARCHITECTURE.md:2505 (и :2781) требует ledger-журнал с «пенсионными» id — **NOT IMPLEMENTED**.
Смягчение: `vn loc extract` пометит переиспользованный ctx как `fuzzy`, потому что msgid
изменился (`tools/vn/src/vn/loc/po.py:258-263`), и `vn loc import` fuzzy не доставляет — если только новый
текст не совпал с удалённым побайтово.

Подробности round-trip PO → `game/tl/` — в [Локализация](14-localization.md).

---

## 2. Выборы: `menu` и обязательный маркер `$ vn_menu`

**Статус: IMPLEMENTED.**

У пунктов `menu` в Ren'Py **нет клаузы `id`** — их нечем адресовать. Поэтому идентичность
меню несёт store-переменная `vn_menu`, а идентичность пункта — его позиционный индекс.
Контракт: строка `$ vn_menu = "chNN_sNNN_mNNN"` стоит **непосредственно перед** `menu:`.

Реальный пример (`content/chapters/ch01_awakening/scenes/s020_school_gate.scene.rpy:5-14`):

```renpy
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
```

Маркер тоже проставляет `vn loc keys` (`keys.py:129-171`) — руками не пишут. Технические детали,
которые иногда нужны:

| Факт | Где |
|---|---|
| Маркер считается «есть», если `$ vn_menu` стоит в пределах 3 строк выше `menu:` (пустые строки допустимы) | `keys.py:141` |
| Маркер от чужой сцены → ошибка «маркер ... принадлежит чужой сцене (copy-paste?)» | `keys.py:146-152` |
| `vn_menu` объявлена как `default vn_menu = None` **без** `_`-префикса — значит едет в сейв и в rollback | `game/framework/00_core/020_state.rpy:7` |
| Исходные подписи попадают в `VN_MENUS` (валидация/QA) | `game/generated/registry/menus.gen.rpy:11` |
| Переводы — в `VN_MENUS_TL[lang][menu_id]` = **список по индексам**, наполняется `game/tl/<lang>/common.rpy` на `init 600` | `tools/vn/src/vn/loc/po.py:438-440` |
| Рантайм-lookup: `vn_loc.choice_text(menu_id, idx, caption)` → `VN_MENUS_TL[lang][menu_id][idx]`, иначе авторский caption | `game/framework/00_core/040_localization.rpy:143-149` |
| Меню переводится «всё или ничего»: один непереведённый/fuzzy пункт — и меню целиком откатывается на исходный язык | `tools/vn/src/vn/loc/po.py:406-417` |

### ⛔ Условные пункты меню запрещены

**Статус: IMPLEMENTED (запрет), с ошибкой сборки.**

```renpy
    menu:
        "Соврать" if ch01.met_mira:      # ← ОШИБКА КОМПИЛЯЦИИ
            ...
```

`tools/vn/src/vn/content/scenes.py:106-114` даёт ошибку
`условный пункт меню #N (...) — запрещено (ломает перевод по индексу); используйте ветвление сцены`.

**Почему.** Движок отфильтровывает невыполнимые пункты **до** того, как список попадёт
в `screen choice(items)`. Индекс `idx` в `choice_text(vn_menu, idx, i.caption)` — это позиция
в уже отфильтрованном списке, а `VN_MENUS_TL[menu_id]` — позиции в исходном полном списке.
При скрытом пункте перевод съезжает на соседние строки. Плюс у экрана выбора нет состояния
`insensitive` — это зафиксировано в шапке `game/framework/20_ui/screens/choice.rpy:16-17`.

**Рабочие альтернативы:**

1. **Ветвление после выбора** (самое дешёвое): пункт показывается всегда, а последствие зависит
   от условия.
   ```renpy
       $ vn_menu = "ch01_s040_m001"
       menu:
           "Позвать Миру":
               if ch01.met_mira:
                   jump ch01_s040__call_known
               else:
                   jump ch01_s040__call_stranger
   ```
2. **Разные `menu` до входа в меню**: две ветки, в каждой — свой `menu` со своим маркером.
   ```renpy
   label ch01_s040__body:
       if ch01.met_mira:
           jump ch01_s040__menu_known
       jump ch01_s040__menu_cold
   ```
   Каждый `menu` получит собственный `chNN_sNNN_mNNN` и собственный набор переводов —
   индексы не пересекаются.
3. **Условие на переходе, а не на пункте**: `exits` в `scene.yaml` поддерживают `when`
   (см. §4).

### ⚠️ Ловушка: строка-заголовок внутри `menu:`

**Статус: NOT IMPLEMENTED (защиты нет).** Ren'Py разрешает строку-caption на отдельной
строке внутри `menu:`:

```renpy
    menu:
        "Что ответить?"          # ← НЕ ПИШИТЕ ТАК
        "Соврать":
            ...
```

Движок отдаёт такую строку нарратору, а не в `screen choice` (`renpy/ast.py`, `Menu.execute`,
ветка `block is None` при `config.narrator_menu = True` — дефолт движка, в проекте не
переопределён). А build-bridge складывает **все** подписи подряд, включая caption
(`050_build_bridge.rpy:78-79`), — значит в ledger и в PO caption станет пунктом `[0]`, и все
переводы реальных пунктов сдвинутся на единицу. Ни компилятор, ни lint этого не ловят.
Нужен вводный текст — пишите его обычной репликой **перед** `$ vn_menu`.

---

## 3. Как выбор меняет состояние

**Статус: IMPLEMENTED.**

Прямо в ветке меню: `$ ch01.met_mira = True` (`s010_intro.scene.rpy:10`).

Переменную обязательно объявить заранее, иначе будет **ошибка сборки** (для `status: draft` —
warning, `scenes.py:235`):
`ch01.met_mira пишется, но не объявлена в Variable Registry ... — молчаливый фантом-стор вне сейва/миграций (G5)`.

| Что объявляем | Файл | Пример |
|---|---|---|
| Переменная главы (store = id главы) | `content/chapters/chNN_*/vars.yaml` | `content/chapters/ch01_awakening/vars.yaml` |
| Глобальная (store `g`) | `content/variables/*.vars.yaml` | `content/variables/core.vars.yaml` |

```yaml
# content/chapters/ch01_awakening/vars.yaml
schema: vars@1
store: ch01
vars:
  met_mira:
    type: bool
    default: false
    doc: "Игрок встретил Миру у ворот в первой сцене"
    since: 1
```

Допустимые имена стора: `g | chNN | mech_<slug> | dlc_<slug> | persistent` — регекс дублируется
в build-bridge (`050_build_bridge.rpy:13`) и в схеме `vars@1`. Всё остальное build-bridge
просто не заметит: обращение к незарегистрированному стору — «молчаливый фантом» вне сейва.
Механика сейвов/миграций — в [Backend / runtime](07-backend.md).

Необязательно, но полезно: продублировать факт в `scene.yaml`, тогда расхождение факта
и декларации станет warning'ом (`scenes.py:160-175`):

```yaml
vars:
  writes: [ch01.met_mira]
```

---

## 4. Условия

### 4.1 Обычный Python-`if` внутри сцены — **IMPLEMENTED**, основной инструмент

```renpy
    if ch01.met_mira:
        show mira a casual smile at center with dissolve
        mira "А ты быстрее, чем кажешься." id ch01_s030_0002
    else:
        "Ты здесь один. Тихо. Слишком тихо." id ch01_s030_0004
```
(`content/chapters/ch01_awakening/scenes/s030_rooftop.scene.rpy:4-9`)

Никаких ограничений на выражение: build-bridge разбирает `if` штатным ast и вытаскивает
из условия чтения атрибутов управляемых сторов (`050_build_bridge.rpy:86-89`) — они
сверяются с Variable Registry так же, как записи.

### 4.2 `when` в `exits` и `vn.eval_when` — **IMPLEMENTED, но не обкатано**

`scene.yaml` разрешает условный переход (`tools/schemas/scene@1.schema.json`, `$defs.cond_exit`):

```yaml
exits:
  done: s020                      # короткая форма
  alt:
    - {when: "g.route == 'mira'", to: s030}
    - {to: ch02/s010}             # межглавная ссылка, без when — fallback
```

Компилятор превращает это в строку обвязки (`scenes.py:249-251`):

```renpy
    if _return == "alt" and vn.eval_when("g.route == 'mira'"):
        jump ch01_s030
```

Что `eval_when` реально умеет (`game/framework/00_core/030_flow.rpy:57-60`):

```python
def eval_when(expr):
    return renpy.python.py_eval(expr)
```

**Это не мини-язык.** Это полноценный `py_eval` в контексте игры: любое Python-выражение,
любые сторы, любые вызовы. Никакого белого списка операторов нет.

**Не приписывайте ему проверок, которых нет.** Docstring в `030_flow.rpy:58-59` утверждает, что
выражение «валидируется компилятором против реестра переменных» — **это неверно**: строка `when`
нигде не парсится (в `scenes.py` она только прокидывается в шаблон, `:190-192,250-251`), схема
описывает её как `{"type": "string", "minLength": 1}`, lint её не смотрит. Опечатка в имени
переменной внутри `when` вылезет только в рантайме исключением.

Практика: `when` в репозитории **не используется ни одной сценой** (проверено: единственные
`exits` — `s010: {gate, roof}`, `s020: {roof}`, `s030: {}`), то есть путь не обкатан.
Порядок проверки условий = порядок ключей `exits` в YAML (`scenes.py:247`) — записывайте
специфичное выше общего и всегда оставляйте ветку без `when`, иначе игрок уедет на
`vn_scene_unavailable`.

---

## 5. Ветвление внутри сцены

**Статус: IMPLEMENTED.**

Контракт меток (`tools/vn/src/vn/content/scenes.py:18,81-90`, `docs/conventions/naming.md`):

- разрешены **только** `^chNN_sNNN__[a-z0-9_]+$`;
- `<full_id>__body` обязательна — точка входа, её вызывает обвязка;
- любая другая метка в файле, не подходящая под шаблон, — ошибка;
- на верхнем уровне файла допустимы **только** `label` (`050_build_bridge.rpy:127-133`).

`jump` **внутри своей сцены разрешён** — это штатный способ ветвиться и сходиться обратно.
Реальный пример схождения (`s020_school_gate.scene.rpy:10,16-19`): ветка «Соврать» делает
`jump ch01_s020__caught`, ветка «Сказать правду» уходит `return "roof"` сразу, а `__caught`
дописывает реплику и тоже возвращает `"roof"`.

```renpy
label ch01_s020__caught:
    show mira smile
    mira "Ладно. Беги, звонок уже был." id ch01_s020_0004
    return "roof"
```

Запрещено (`scenes.py:92-104`):

| Что | Сообщение |
|---|---|
| `jump`/`call` на метку **не своей** сцены | `переход вне своей сцены; межсценовые переходы только через return "<exit_id>" + exits (C2)` |
| `jump expression …` / `call expression …` | `expression запрещён в авторских сценах (динамические цели ломают статический анализ и prediction)` |

**Про `call`.** Формально `call chNN_sNNN__sub` на свою метку контракт проходит, но на практике
не используйте: любой **пустой** `return` в сцене с объявленными `exits` — ошибка компиляции
(`scenes.py:127-132`), а `return "<exit>"` из вызванной метки по штатной семантике Ren'Py вернёт
управление в место вызова, а не в обвязку сцены. Плюс инвариант G7 «глубина call-стека на границе
сцены = 0» проверяется в обвязке (`vn.check_scene_stack()`), и нарушение только **логируется**,
не чинится (`030_flow.rpy:44-48`). Ветвитесь через `jump`.

### Выход из сцены

Из **любой** ветки — `return "<exit_id>"`, где `exit_id` объявлен в `exits:` парного YAML.
Проверки (`scenes.py:116-143`):

| Ситуация | Реакция |
|---|---|
| `return "roof"`, а `roof` нет в `exits` | ошибка: `return 'roof' не объявлен в exits (…: [gate])` |
| пустой `return` в сцене с непустыми `exits` | ошибка: `пустой return в сцене с объявленными exits` |
| `return` с не-литеральным выражением | ошибка: `exit-id обязан быть строковым литералом` |
| `exits.X` не достигается ни одним `return` | warning |

Терминальная сцена главы — `exits: {}` и пустой `return` (`s030_rooftop.scene.rpy:17`).
Обвязка тогда добавляет `$ vn.chapter_done("ch01")` и `if _return is None: jump vn_end_of_content`
(`scenes.py:260-265`). Что именно эмитится вокруг вашего файла — см. [Сцены](12-scenes.md).

---

## 6. Что видит игрок

**Статус: IMPLEMENTED** (`game/framework/20_ui/screens/choice.rpy`, ADR-0009 + `docs/pipeline/design-brief-choices.md`).

Экран выбора рисуется автоматически, своего `screen` в сцене писать не нужно и нельзя.
Коротко, детали — в [UI / frontend](06-frontend.md):

- стек прижат к низу и растёт вверх (`choice.rpy:57-62`), ширина `gui.choice_width` = 880;
- каждый ряд — `side "l c r"`: номер `[_num]`, текст, маркер (`choice.rpy:44-48`);
- цифры **1–9** работают как горячие клавиши (`choice.rpy:49-51`);
- текст берётся **только** через `vn_loc.choice_text(vn_menu, idx, i.caption)` (`choice.rpy:47`) —
  это и есть причина, по которой маркер `$ vn_menu` обязателен;
- `i.chosen` → приглушённый фон `vn_frame_choice_chosen` + ромб-маркер (`choice.rpy:39,41,70-71`).
  Важно понимать источник флага: движок вычисляет его как `(location, label) in persistent._chosen`
  (`renpy/ui.py`, `ChoiceReturn.get_chosen`), то есть это «выбирали **в любом прошлом
  прохождении**», персистентно, и ключ включает **исходный текст пункта** — правка подписи
  сбрасывает отметку. Это не состояние rollback;
- в прогоне `vn test smoke` пункт жмёт таймер-экшен `vn_qa.autopilot_choose` (`choice.rpy:52-54`).

---

## 7. Стиль текста: сколько влезает

Замерено PIL по реальным файлам шрифтов проекта (не из кода — это измерение, а не константа):

| Зона | Токен | Значение | Влезает в строку |
|---|---|---|---|
| Реплика | `gui.dialogue_width` / `gui.text_size` / `gui.text_font` | 1180 px / 34 px / Literata-Regular | **≈ 65** кириллических символов (≈ 70 латинских) |
| Пункт выбора | `gui.choice_width` 880 − паддинги 2×26 − колонка номера 26 − 2×spacing 16 = **770 px** при `gui.choice_text_size` 25 / Inter-Regular | | **≈ 55** символов |

(`game/gui.rpy:41,46,52,60,61`; `choice.rpy:66,45,74`.)

Практические ориентиры:

- Реальная демо-реплика `"Первый учебный день. Звонок уже прозвенел, а ты всё ещё стоишь у ворот."`
  — 71 символ ≈ 1298 px, то есть **уже две строки**. Это нормальная длина.
- Высота диалоговой зоны — `gui.textbox_height` = 500 px, из них 78 px нижний паддинг
  (`game/gui.rpy:38,40`). Физический потолок — порядка 7 строк; рабочий ориентир —
  **2–3 строки на реплику**, дальше режьте на две.
- Пункт выбора: держитесь **одной строки**, ≤ 55 символов. Перенос не сломает вёрстку
  (высота ряда авто), но ряд станет визуально тяжёлым, а панель-фон рассчитана на
  минимум 60 px высоты (ловушка `2*Borders`, `choice.rpy:9-12`).

**Проверка переполнений — псевдолокалью, а не глазомером.** `vn loc pseudo` собирает пакет
`loc/po/pseudo/`, где каждая строка = `[[` + текст с акцентами + `~` × `max(2, 0.4·len)` + `]`
(`tools/vn/src/vn/loc/po.py:516-552`). То есть строка раздувается в **1,4 раза + 3 символа**: реплика в 46
символов даст ровно заполненную строку в 65. Прогон:

```bash
vn loc pseudo && vn build
vn test smoke --lang pseudo --picks 0,0
# смотреть .vncache/smoke/shot*.png
```

`pseudo` помечен `synthetic: true` — в игре он виден только при `config.developer`
(`040_localization.rpy:78-83`) и исключается из релизных гейтов покрытия.

---

## Как изменить / Как расширить

### Чеклист «новый диалог» (реплики без выбора)

1. Файл: `content/chapters/chNN_<slug>/scenes/sNNN_<slug>.scene.rpy`. Нет сцены — создать пару
   файлов: `vn scene new ch01 rooftop` (следующий номер с шагом 10, `cli.py:488-503`).
2. Писать в `label chNN_sNNN__body:`; **никаких `id`** — их проставит тулинг.
3. Персонажу нужен `define` — проверить, что он есть в `content/characters/<id>/character.yaml`,
   и добавить id в `participants:` парного YAML.
4. Пишете в переменную — объявить её в `vars.yaml` (см. §3).
5. `vn loc keys` → в файле появятся `id chNN_sNNN_NNNN`, обновится `loc/ledger/chNN.json`.
6. `vn build`.
7. `"$RENPY_SDK/renpy.exe" . lint` — движковый линт по framework и генерату.
8. `vn test smoke --picks 0,0`, посмотреть `.vncache/smoke/shot*.png`.
9. Коммитить: `content/**` и `loc/ledger/chNN.json`. `game/generated/`, `game/assets/`,
   `game/tl/` — не коммитить, они не в git.

### Чеклист «новый выбор»

1. Написать `menu:` с 2–5 пунктами, **без** `$ vn_menu` и без условий на пунктах.
   Вводный текст — обычной репликой перед меню, не строкой-заголовком внутри `menu:`.
2. Каждая ветка обязана закончиться `return "<exit>"` или `jump chNN_sNNN__<branch>`.
   «Проваливание» вниз работает как в обычном Ren'Py, но проверить, что путь всё равно
   приходит к `return`.
3. Новые `exit_id` добавить в `exits:` парного `scene.yaml`; цель — `sNNN` внутри главы
   или `chNN/sNNN` между главами.
4. Цели ещё нет — `vn scene stub ch01 s040` (`cli.py:484-500`), иначе для не-`draft` главы
   будет ошибка «сцена не существует».
5. Записи состояния из веток — объявить переменные.
6. `vn loc keys` → появится `$ vn_menu = "chNN_sNNN_mNNN"`, в ledger — блок `menus`.
7. `vn build`; убедиться, что в `game/generated/registry/menus.gen.rpy` новый id и правильные подписи.
8. `vn content graph` — увидеть развилку в Mermaid (учтите: команда сканирует **только**
   `content/chapters/`, главы из `packs/*` в граф не попадают, `tools/vn/src/vn/content/graph.py:15`).
9. `vn test smoke --picks 0,1` — прогнать альтернативную ветку; фактический путь пишется
   в `.vncache/smoke/picks.log`.
10. Переводы: `vn loc extract` → перевести `loc/po/{en,de}/chNN.po` (ctx `chNN_sNNN_mNNN[i]`)
    → `vn loc import`. Непереведённый **один** пункт откатывает на исходный язык **всё** меню.

### Чего в проекте пока нет (не планируйте на это)

| Механизм | Статус |
|---|---|
| `$ vn_qa.choice(scene_id, menu_id, idx)` первым стейтментом каждой ветки (ARCHITECTURE.md:544-551) | **NOT IMPLEMENTED** — `030_flow.rpy:98-101` это `pass`-заглушка, компилятор её не эмитит |
| `vn.beat("<id>")` — мелкий якорь внутри сцены для галереи/достижений | **IMPLEMENTED, но не эмитится**: `030_flow.rpy:19-24` работает, вызовов в `content/` ноль. Хотите якорь — пишите `$ vn.beat("x")` руками |
| `vn loc keys --migrate --from --to` (перенос id между сценами) | **NOT IMPLEMENTED** — есть только `--check` |
| High-watermark / «пенсионные» say-id | **NOT IMPLEMENTED** (ARCHITECTURE.md:2505, 2781) |
| TTS-черновики озвучки (`vn voice tts`) | **NOT IMPLEMENTED** — заглушка фазы 2, `cli.py:1278-1281`. Сама озвучка реплик (`voice@1`, `vn voice manifest\|import\|validate`, инжекция `voice vn.voice_path("<say-id>")` в генерат) — **IMPLEMENTED**, см. [23-audio.md](23-audio.md) §8 |
| Градация строгости по `status` главы для say-id (draft = warning) | **NOT IMPLEMENTED** — `keys.py` одинаково строг ко всем главам |

---

## Чего НЕ делать

- **Не писать `id` и `$ vn_menu` руками.** Это работа `vn loc keys`. Ручной id вне конвенции
  или из чужой сцены = ошибка; дубликат = молча перезаписанные переводы, если бы проверки не было.
- **Не использовать monologue mode** (тройные кавычки с несколькими абзацами). Парсер Ren'Py
  прямо запрещает `id` на таких стейтментах («Monologue mode say statements cannot have an id
  clause», `renpy/parser.py`), а `vn loc keys` попытается его дописать → парс упадёт → файлы
  откатятся с `KeysError`. Пишите абзацы отдельными say-стейтментами.
- **Не ставить хвостовой комментарий на строке say.** `id` дописывается в конец строки
  (`keys.py:126`) и уедет внутрь комментария. Ловится только пост-фактум откатом с сообщением
  «после правки остались say без id (say с хвостовым комментарием?)» (`keys.py:209-212`).
- **Не писать условные пункты меню** — компилятор откажет (§2).
- **Не писать строку-заголовок внутри `menu:`** — сдвинет индексы переводов (§2).
- **Не переименовывать `chNN_`/`sNNN` в путях**, если строка уже переведена: id завязаны на
  номера в именах файлов, все переводы главы осиротеют. Слуг менять можно.
- **Не копировать блок с id из другой сцены.** Скопированные `id`/`vn_menu` дадут ошибки
  «вне конвенции» / «принадлежит чужой сцене» — удалите их и прогоните `vn loc keys`.
- **Не делать `jump` в чужую сцену** — только `return "<exit>"` + `exits`.
- **Не править `game/generated/scenes/chNN/*.gen.rpy`.** Ваш `.rpy` там лежит копией, но
  зона перезаписывается сборкой и не в git. Правьте `content/`.
- **Голый `[` в тексте — это интерполяция Ren'Py.** Нужен литеральный символ — `[[`.
  Псевдолокаль этим и пользуется. То же с `{` → `{{`.
- **Не рассчитывать, что `vn build` поймает отсутствующие id.** Поймает только
  `vn loc keys --check` (в CI — `ci.yml:64`).

---

## Проверка

```bash
vn loc keys --check     # id проставлены, ledger свеж (главный гейт этого файла)
vn build                # lint -> ассеты -> компиляция; ошибки контракта сцен здесь
vn content graph        # развилки глазами (Mermaid); паки не сканируются
vn loc report           # покрытие переводов: сейчас de/en/pseudo 136/136, fuzzy 0
vn test smoke --picks 0,0
vn test smoke --picks 0,1          # вторая ветка; путь — .vncache/smoke/picks.log
vn test smoke --lang pseudo --picks 0,0   # переполнения текста
"$RENPY_SDK/renpy.exe" . lint
python -m pytest tools/vn/tests -q         # 278 тестов
```

В bash-сессии `RENPY_SDK` не наследуется — экспортируйте вручную:
`export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`.
Именно в кавычках и с прямыми слэшами: значение читает Python (`tools/vn/src/vn/doctor.py:24-30`,
`tools/vn/src/vn/content/analyze.py:23-34`), поэтому MSYS-форма `/c/...` и обратные слэши дают
несуществующий путь и «Ren'Py SDK не найден».

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `content/chapters/ch01_awakening/scenes/s010_intro.scene.rpy` (эталон реплики+меню), `tools/vn/src/vn/loc/keys.py` (алгоритм id), `tools/vn/src/vn/content/scenes.py:69-194` (весь контракт авторского `.rpy`), `game/framework/00_core/050_build_bridge.rpy` (что именно видит анализатор), `docs/conventions/naming.md` |
| **Не трогать** | `game/generated/**` (копия сцены + обвязка, перезапишется `vn build`), `game/tl/**` (перезапишется `vn loc import`), `loc/ledger/*.json` (пересобирается `vn loc keys` целиком — правка руками будет затёрта), `loc/po/*/…` для `pseudo` (регенерируется на каждом `extract`) |
| **Писать можно** | только `content/chapters/**/*.scene.{rpy,yaml}`, `content/chapters/**/vars.yaml`, `content/variables/*.vars.yaml` |
| **Зависимости** | `.scene.rpy` → build-bridge → ledger (`loc/ledger/chNN.json`) → PO (`loc/po/*/chNN.po`) → `game/tl/*/dialogue_chNN.rpy` + `VN_MENUS_TL`; `.scene.rpy` + `.scene.yaml` → `game/generated/scenes/chNN/<full_id>.gen.rpy`; `exits` → граф достижимости в lint |
| **Валидация** | `vn loc keys --check` → `vn build` → `"$RENPY_SDK/renpy.exe" . lint` → `vn test smoke --picks 0,0` |
| **Частые ошибки** | 1) сгенерировать `id`/`$ vn_menu` самому вместо запуска `vn loc keys`; 2) условный пункт меню (`"Текст" if cond:`) — компилятор откажет; 3) `jump` наружу сцены вместо `return "<exit>"` + `exits`; 4) запись в необъявленную переменную стора (для не-`draft` главы это ошибка, а не warning); 5) считать, что `vn build` проверяет свежесть say-id — не проверяет; 6) приписывать `vn.eval_when` валидацию выражения компилятором — её нет |

**Ссылки:** [Сцены](12-scenes.md) · [Локализация](14-localization.md) · [UI / frontend](06-frontend.md) ·
[Backend / runtime](07-backend.md) · [Персонажи](10-characters.md) · [Главы](09-chapters.md) ·
[vn CLI](25-custom-engine.md) · [Тесты](27-testing.md) ·
[`../conventions/naming.md`](../conventions/naming.md) ·
[ADR-0005](../adr/0005-language-packages-and-runtime-registry.md) ·
[ADR-0009](../adr/0009-generated-ui-panels.md) ·
[`../pipeline/design-brief-choices.md`](../pipeline/design-brief-choices.md)
