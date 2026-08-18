# 07. Backend (Game Logic / Runtime Architecture)

> **Статус подсистемы:** IMPLEMENTED — состояние, снапшот, миграции, флоу сцен и крах-репорт работают; главное «но»: весь внешний тулинг миграций (`vn save migrate`, `vn migrate`) — стабы фаз 2–3, цепочка миграций исполняется **только внутри игры** в `label after_load`.
> **Отвечает на вопрос:** «Где живёт состояние игры, как добавить переменную, что происходит при загрузке сейва и как не сломать чужие сейвы».

## Сервера здесь нет

**В проекте нет и не планируется классического backend: ни HTTP-API, ни БД, ни авторизации, ни аналитики по сети.** Это оффлайн-игра на Ren'Py, распространяемая архивом/через Steam. Ни одного сетевого вызова в `game/` нет. Всё, что в вебе назвали бы «backend», здесь — **слой Game Logic / Runtime** внутри игрового процесса: named stores вместо БД, `.save`-файлы вместо persistence-слоя, `label after_load` вместо миграций схемы БД, `vn_log`/crash-репорт вместо серверных логов.

Живёт этот слой в двух местах, и путать их нельзя:

| Зона | Что там | В git | Кто пишет |
|---|---|---|---|
| `game/framework/00_core/` | рукописный рантайм-код: фасад `vn.*`, `vn_state`, `vn_registry`, `vn_build`, крах | да | человек |
| `game/generated/state/` | **генерат**: `defaults.gen.rpy`, `snapshot.gen.rpy`, `migrations.gen.rpy` | **нет** | `vn build` |
| `content/variables/`, `content/chapters/*/vars.yaml` | источник истины по переменным | да | человек |
| `content/migrations/` | код миграций + реестр занятых номеров | да | человек |

Правки в `game/generated/` бесполезны — их перетрёт следующая сборка. Меняйте декларацию и пересоберите.

## Быстрый ответ

```bash
# добавить глобальную переменную -> правим content/variables/core.vars.yaml, потом:
vn build                                   # lint -> assets -> compile -> loc import -> бюджеты
vn build --check                           # ничего не пишет; ненулевой exit = генерат протух

# посмотреть, что реально попадает в сейв
cat game/generated/state/snapshot.gen.rpy  # SNAPSHOT_VARS / SNAPSHOT_STORES
cat game/generated/state/defaults.gen.rpy  # default <store>.<var> + vn_save_schema

# проверить сейвы
vn save check                              # оффлайн: читает JSON-заголовок слота без unpickle
vn save corpus                             # загружает обе фикстуры в реальной игре, гоняет миграции
vn test smoke                              # прогон главы автопилотом (in-process)
```

Три файла, которые надо открыть перед любой правкой состояния: `content/variables/core.vars.yaml`, `game/framework/00_core/020_state.rpy`, `project.yaml` (ключ `save_schema`).

---

## 1. Модель состояния: named stores — IMPLEMENTED

Всё сохраняемое состояние живёт в **named stores** Ren'Py, а не в глобальном `store`. Разрешённые имена пиннованы регексом в трёх местах одновременно:

* JSON-схема декларации — `tools/schemas/vars@1.schema.json:10`
  `^(g|ch\d{2}|mech_[a-z0-9_]+|dlc_[a-z0-9_]+|persistent)$`
* build-bridge, который классифицирует чтения/записи в авторском `.rpy` — `game/framework/00_core/050_build_bridge.rpy:13` (тот же регекс)
* конвенция именования — `../conventions/naming.md:22`

| Store | Назначение | Декларация | Живой пример |
|---|---|---|---|
| `g` | глобальное состояние кампании | `content/variables/*.vars.yaml` | `g.route = 'prologue'` |
| `chNN` | состояние главы; имя store обязано совпадать с id главы | `content/chapters/chNN_*/vars.yaml` | `ch01.met_mira = False` |
| `mech_*` | состояние механики (фаза 2) | `content/variables/*.vars.yaml` | **нет ни одной** |
| `dlc_*` | состояние пака | пак | **нет ни одной** |
| `persistent` | межсейвовые данные; имена **обязаны** начинаться с `vn_` (C9) | `*.vars.yaml` со `store: persistent` | деклараций нет; во framework: `persistent.vn_achievements`, `persistent.vn_gallery_unlocked` |

Правило `store == id главы` проверяет линтер: `tools/vn/src/vn/content/lint.py:348-352` (компилятор эту проверку не делает).

**Правило `_`-префикса.** Ren'Py не кладёт в сейв переменные, начинающиеся с `_`. Поэтому:

* сохраняемые переменные **никогда** не начинаются с `_` (`../conventions/naming.md:29`);
* `snapshot()` явно пропускает все `_*`-атрибуты (`020_state.rpy:40`);
* и наоборот, служебные счётчики автопилота специально названы `_vn_ap_shot` / `_vn_ap_menu` (`030_flow.rpy:113,138`) — но, поскольку они лежат в обычном `store`, движок их всё равно сериализует; это видно по корпусному прогону, где нумерация скриншотов возобновилась с `shot003.png`;
* `vn_menu` и `vn_scene` в `020_state.rpy:7,10` намеренно **без** `_`: они обязаны ехать в сейв и участвовать в rollback.

### Что в сейв не попадает

| Данные | Почему |
|---|---|
| `VN_CHAPTERS`, `VN_SCENES`, `VN_MENUS`, `VN_STRINGS`, `VN_GALLERY`, `VN_ACHIEVEMENTS`, `VN_PACKS` | это `define` — константы, вне сейва и вне rollback |
| `vn_build.*` (`060_build_info.rpy:14-23`) | init-константы процесса, не `default` |
| `vn_lang._languages` | заполняется один раз на `init 999` |
| `persistent.*` | отдельный механизм движка, живёт вне слота; `_emit_snapshot` его исключает (`compile.py:336-337`) |
| всё, что начинается с `_` | движок не сериализует |

---

## 2. Декларация переменной → `default` — IMPLEMENTED

Источник истины — `*.vars.yaml`. Реальный файл `content/variables/core.vars.yaml`:

```yaml
schema: vars@1
store: g
vars:
  route:
    type: str
    default: prologue
    doc: "Активный роут; prologue до первой развилки"
    since: 1
```

Поля (`tools/schemas/vars@1.schema.json:19-32`):

| Поле | Обяз. | Значение | Кто читает |
|---|---|---|---|
| `type` | да | `str\|int\|float\|bool\|list\|dict` | только JSON-схема; кодоген тип **не** проверяет |
| `default` | да | литерал; проходит через `_py_literal` (`compile.py:71-77`) — только `str/int/float/bool/None/list/dict` | `_emit_defaults` |
| `doc` | нет | строка-описание | никто (документация для человека) |
| `since` | нет | `save_schema`, с которой переменная существует | **никто** — поле сейчас без потребителя (NOT IMPLEMENTED) |
| `range` | нет | `[min, max]`; схема обещает clamp в `vn.set()` | **NOT IMPLEMENTED** — `vn.set()` не существует |
| `export` | нет | видимость переменной главы из других глав | **NOT IMPLEMENTED** — нет потребителя |

`additionalProperties: false` — новое поле сначала добавляется в схему, потом в YAML.

### Что проверяет линтер и компилятор

1. **Сцена не может трогать необъявленную переменную.** Build-bridge вытаскивает из авторского `.rpy` фактические `var_reads`/`var_writes` по ast-контексту (`050_build_bridge.rpy:15-37`), а `validate_scene` сверяет их с Variable Registry: `tools/vn/src/vn/content/scenes.py:145-159`. Незадекларированный атрибут — **ошибка**, а в главе со `status: draft` — предупреждение (G15). Формулировка ошибки: «молчаливый фантом-стор вне сейва/миграций (G5)».
2. **Направленная сверка с манифестом сцены.** Если в `scene.yaml` объявлен блок `vars: {reads: [...], writes: [...]}` — расхождение с фактом даёт предупреждения (`scenes.py:160-175`). Если блока нет — молчит. Живой пример декларации: `content/chapters/ch01_awakening/scenes/s010_intro.scene.yaml` (`vars.writes: [ch01.met_mira]`).
3. **`store == id главы`** для `chapters/*/vars.yaml` — `lint.py:348-352`.
4. **C9:** `store: persistent` + имя без `vn_` → `CompileError` (`compile.py:100-104`).
5. **G7:** выпущенная переменная не может молча исчезнуть — `lint.py:399-404` сверяет `content/registry/id_registry.json` с существующими. **Гарантия сейчас инертна:** все четыре массива реестра пусты, потому что штампуются только главы со `status: release` (`release.py:69-95`), а `ch01` — `draft`.

### Реальный генерат

`game/generated/state/defaults.gen.rpy` (эмиттер — `tools/vn/src/vn/content/compile.py:90-111`):

```renpy
# Создание named stores (шкала init-приоритетов — C8/ADR-0003)
init -980 python in ch01:
    pass

init -980 python in g:
    pass

default ch01.met_mira = False
default g.route = 'prologue'

default vn_save_schema = 2
define vn_build_save_schema = 2
```

Пара `vn_save_schema` / `vn_build_save_schema` — центральный механизм миграций: первая едет в сейв, вторая — константа текущей сборки. Обе берутся из `project.yaml:save_schema`.

`game/generated/state/snapshot.gen.rpy` (эмиттер — `compile.py:332-349`):

```renpy
init -970 python in vn_state:
    SNAPSHOT_VARS = (('ch01', 'met_mira'), ('g', 'route'))
    SNAPSHOT_STORES = ('ch01', 'g')
```

---

## 3. Сейвы: JSON-заголовок слота (G5) — IMPLEMENTED

Ren'Py кладёт в `.save`-zip член `json` — словарь, читаемый **без unpickle**. Проект дописывает туда три своих ключа: `game/framework/00_core/001_boot.rpy:31-36`

```python
def _vn_save_json(d):
    d["vn_save_schema"] = getattr(store, "vn_save_schema", None)
    d["vn_version"] = config.version
    d["vn_scene"] = getattr(store, "vn_scene", None)

config.save_json_callbacks.append(_vn_save_json)
```

Зачем: оффлайн-инструменты обязаны понимать сейв, не поднимая игру. Потребитель ровно один — `vn save check` (`tools/vn/src/vn/cli.py:1099-1124`), который открывает слот как zip, читает `json`, требует целочисленный `vn_save_schema` и печатает `schema / версия / сцена`. Фикстур в корпусе **две**, вот их реальные заголовки:

```json
// ci/fixtures/saves/schema2-demo.save — сейв текущей схемы
{"_renpy_version": [8,5,3,26051504], "_version": "0.1.0+48d19a3",
 "vn_save_schema": 2, "vn_version": "0.1.0+48d19a3", "vn_scene": "ch01_s020"}

// ci/fixtures/saves/schema1-demo.save — сейв старой схемы, проверяет ветку миграций
{"_renpy_version": [8,5,3,26051504], "_version": "0.1.4+dd1cb3e",
 "vn_save_schema": 1, "vn_version": "0.1.4+dd1cb3e", "vn_scene": "ch01_s010"}
```

`vn_scene` пишет `vn.checkpoint()` на входе в каждую сцену — это якорь «где игрок был», а не механизм восстановления позиции: позицию восстанавливает сам движок по statement-именам `.rpyc` (см. [27-testing.md](27-testing.md) про линию имён).

**Грабля движка:** Ren'Py 8 подписывает сейвы per-machine токеном; чужой сейв на другой машине открывается через модальный confirm. Для корпуса это обходится тем, что фикстура кладётся в изолированный `--savedir`, а автопилот подтверждает модалку таймером (`core_screens.rpy:409-410`).

---

## 4. Снапшот состояния — IMPLEMENTED

`vn_state.snapshot()` (`game/framework/00_core/020_state.rpy:29-48`) превращает named stores в плоский `dict` с ключами `"store.var"`. Асимметрия чтения и записи сделана намеренно:

| Функция | Что берёт | Зачем |
|---|---|---|
| `snapshot()` | **ВСЕ** не-`_`, не-callable, не-module атрибуты каждого store из `SNAPSHOT_STORES`, если тип простой | переменная, удалённая из новой схемы, лежит в старом сейве и обязана быть **видима** миграции — иначе миграциям нечего переносить |
| `apply_snapshot(state)` | **только** объявленные пары из `SNAPSHOT_VARS` | обратно в игру возвращается лишь то, что существует в текущей схеме |

Фильтр простых типов: `_SIMPLE = (str, int, float, bool, list, dict, type(None))` (`020_state.rpy:27`). Кортежи, множества и объекты не проходят.

Значения на обратном пути прогоняются через `vn_compat.revertable()` (`020_state.rpy:58`, реализация — `game/framework/00_core/engine_compat/000_compat.rpy:17-30`): плоские `dict`/`list`/`set`, пришедшие из json и чистого python, не участвуют в rollback, пока не станут `RevertableDict`/`RevertableList`/`RevertableSet`.

### Шум `_Feature` в логе — ожидаемое поведение, НЕ ошибка

Живой факт из `log.txt:44-55` — 12 строк на каждый снапшот:

```
[vn] snapshot: ch01.division пропущен (не-простой тип _Feature)
[vn] snapshot: ch01.absolute_import пропущен (не-простой тип _Feature)
[vn] snapshot: ch01.with_statement пропущен (не-простой тип _Feature)
[vn] snapshot: ch01.print_function пропущен (не-простой тип _Feature)
[vn] snapshot: ch01.unicode_literals пропущен (не-простой тип _Feature)
[vn] snapshot: ch01.basestring пропущен (не-простой тип tuple)
```

и те же шесть для `g`. Причина: Ren'Py заранее наполняет namespace любого store объектами `from __future__ import …` (`_Feature`) и совместимостным `basestring` (кортеж). `snapshot()` идёт по `vars(module)`, натыкается на них, видит не-простой тип, **корректно отбрасывает** и логирует. Это ровно тот случай, ради которого фильтр и написан. Реагировать не нужно; сообщения — цена честного «читаю всё, что есть в store».

### Что реально протекает: `PY2`

Побочный эффект того же обхода: атрибут `PY2` — обычный `bool`, поэтому фильтр его **пропускает**. Он есть в каждом снапшоте, что видно в реальных артефактах прогонов `.vncache/smoke/state.json` и `.vncache/corpus/state.json`:

```json
{"ch01.PY2": false, "ch01.met_mira": true, "g.PY2": false, "g.route": "prologue", "vn_save_schema": 2}
```

Практический вывод для автора миграции: **`state` содержит больше ключей, чем объявлено в `vars.yaml`**. Никогда не пишите миграцию, которая перебирает `state.keys()` и что-то делает со «всеми переменными» — трогайте только известные вам ключи по имени.

---

## 5. Миграции сейвов — IMPLEMENTED (внутри игры) / внешний тулинг NOT IMPLEMENTED

### Полная цепочка

```
project.yaml: save_schema: 2
        │
        ├─> compile.py:107-110  ->  default vn_save_schema = 2   (едет в сейв)
        │                           define vn_build_save_schema = 2 (константа сборки)
        │
        └─> _collect_migrations (compile.py:371-404)
                 ├─ читает content/migrations/NNNN_slug.py
                 ├─ требует номер в content/migrations/registry.yaml -> reserved[]
                 ├─ требует непрерывную цепочку == range(2, save_schema+1)
                 └─> _emit_migrations (compile.py:352-368)
                          -> game/generated/state/migrations.gen.rpy  (init -960)
                                   исходник миграции вшит как python-строка,
                                   грузится через exec(), кладётся в vn_state.MIGRATIONS
                                                │
                                       label after_load (020_state.rpy:83-107)
```

**Номер файла = целевая `save_schema`.** Миграция `0002_*.py` переводит сейв со схемы 1 на схему 2. Дыры и лишние номера — ошибка сборки.

### Реальная миграция, разобранная построчно

`content/migrations/0002_route_prologue.py` — единственная в проекте:

```python
"""Миграция схемы 1 -> 2: значение route 'common' переименовано в 'prologue'."""


def migrate(state):
    if state.get("g.route") == "common":
        state["g.route"] = "prologue"
    return state
```

Контракт, который держит весь механизм:

| Правило | Почему |
|---|---|
| функция обязана называться `migrate` | загрузчик падает без неё: `raise Exception("...: нет функции migrate(state)")` — `migrations.gen.rpy:11-12` |
| сигнатура строго `migrate(state: dict) -> dict` | одна и та же функция исполняется и в игре, и (в будущем) внешним тулингом |
| работает над **dict-снапшотом**, а не над живыми переменными | перед цепочкой снапшот проходит json-раундтрип: `state = json.loads(json.dumps(snapshot()))` (`020_state.rpy:66`). Миграция видит только плоские типы; Revertable-обёртки движка не протекают в чистый python, и та же функция гоняется юнит-тестом без запуска игры (`tools/vn/tests/test_saves.py`) |
| ключи — `"store.var"`, не атрибуты | `state["g.route"]`, а не `g.route` |
| `.get()`, а не `[]` | старый сейв может не содержать ключа вообще |
| идемпотентность желательна | цепочка может доехать не до конца (см. ниже) и повториться на следующей загрузке |

Номер обязан быть заранее занят в `content/migrations/registry.yaml`:

```yaml
schema: migrations_registry@1
reserved:
  - {number: 2, slug: route_prologue, by: "@tech-lead"}
```

Резервируется **в том же PR**, что и файл миграции: две параллельные ветки иначе создадут `0003_*.py` каждая и конфликт всплывёт только на мерже.

### Что происходит при загрузке — `label after_load`

`020_state.rpy:83-107`. Весь control flow после загрузки живёт **только здесь**; `config.after_load_callbacks` зарезервирован под чистую валидацию без переходов (G5).

| Случай | Поведение |
|---|---|
| `loaded == target` | ничего не происходит; это 99 % загрузок |
| `loaded > target` (сейв из будущей версии) | `renpy.block_rollback()` → сообщение `ui.flow.save_from_newer` через `vn_loc.t()` → `renpy.full_restart()`. `block_rollback` стоит **до** `say` намеренно: `say` — это интеракция, и откат колёсиком мыши вернул бы игрока в немигрируемое состояние в обход гейта |
| `loaded < target` | `vn_state.run_migrations(loaded)`; схема поднимается **до фактически применённой** миграции, не до целевой; затем `renpy.block_rollback()` |
| цепочка не доехала до цели | `vn_log("migrations incomplete: X -> Y (target Z)")`, игра продолжается на достигнутой схеме |
| разрыв в цепочке номеров | `vn_log("migration chain gap: %d -> %d")` (`020_state.rpy:71-72`), прогон не прерывается |

Почему схема поднимается только до фактически применённой: дыра в цепочке не должна пометить сейв «актуальным» без миграции.

### Как написать миграцию — пошагово

1. Решите, что именно ломается. Миграция нужна, если **старое значение перестаёт быть корректным**: переименование значения, смена типа, слияние двух переменных, изменение смысла. Простое **добавление** новой переменной миграции не требует — `default` в новой сборке даст значение сам.
2. `project.yaml`: `save_schema: 2` → `3`.
3. Займите номер: в `content/migrations/registry.yaml` добавьте `- {number: 3, slug: <slug>, by: "@вы"}`.
4. Создайте `content/migrations/0003_<slug>.py` с функцией `migrate(state)`. Только простые типы, только `.get()`, ключи вида `"store.var"`.
5. `vn build` — компилятор проверит резервирование и непрерывность цепочки и вошьёт исходник в `game/generated/state/migrations.gen.rpy`.
6. Проверьте: `vn save corpus`. Критерий прохода (`cli.py:1243-1244`): прогон не по таймауту **и** `RESULT.txt` начинается с `OK` **и** `state.json["vn_save_schema"] == project["save_schema"]`.

### Когда бампать `save_schema`

| Изменение | Бампать? |
|---|---|
| добавили переменную | нет — `default` покроет старый сейв |
| удалили переменную | нет для работоспособности, **да** если её значение нужно перенести в другую |
| переименовали переменную | да + запись в `content/renames.yaml → vars` (G7) |
| сменили тип или семантику значения | да |
| сменили набор допустимых значений (`common` → `prologue`) | да — ровно случай `0002` |
| правки текста, ассетов, экранов | нет |

### Ограничения, о которых надо знать заранее

* **PARTIALLY IMPLEMENTED:** внешнего прогона миграций нет. `vn save migrate` — стаб фазы 3 (`cli.py:1259-1260`, exit 3), `vn migrate` (миграции схем деклараций — другая сущность) — стаб фазы 2 (`cli.py:371`). Цепочку можно проверить только запуском игры.
* **Корпус теперь гоняет настоящую миграцию — IMPLEMENTED.** Фикстур две. `schema2-demo.save` создана на схеме 2 при `save_schema: 2` и всегда идёт в ветку «схемы равны»; `schema1-demo.save` несёт `vn_save_schema: 1` (сцена `ch01_s010`) и попадает в ветку `loaded < target`. Прогон `vn save corpus` печатает по ней `schema после загрузки: 2 (цель 2)`, а в `log.txt` появляется строка `[vn] migration 0002` — то есть `run_migrations` действительно исполняется в игре, а не только в юнит-тесте. Подробнее — [27-testing.md](27-testing.md).

---

## 6. Флоу: точка входа, обвязка сцены, стек — IMPLEMENTED

### Фасад `vn.*`

`game/framework/00_core/030_flow.rpy`, `init -999 python in vn`, `API_LEVEL = 1` (`:9`). Это **единственный** API, через который генерат обращается к движку; его `api_level` проверяют манифесты паков (`compile.py` константа `VN_API_LEVEL = 1`).

| Символ | Строка | Что делает | Эмитится компилятором? |
|---|---|---|---|
| `vn.checkpoint(scene_id)` | `:12` | `vn_scene = scene_id`; дёргает `vn_ach.check` и `vn_gal.check` по якорю `scene` | **да**, первым стейтментом обвязки |
| `vn.beat(beat_id=None)` | `:19` | мелкий якорь внутри сцены | **нет** — автор пишет `$ vn.beat("x")` руками. Вызовов в `content/` **ноль** → IMPLEMENTED / UNUSED |
| `vn.chapter_done(chapter_id)` | `:26` | якорь «глава пройдена» | **да**, только в терминальной сцене (без `exits`) |
| `vn.check_scene_stack()` | `:44` | инвариант G7: глубина call-стека на границе сцены = 0. **Только логирует нарушение, не чинит** | да |
| `vn.unwind_call_stack()` | `:50` | `renpy.pop_call()` до глубины 0; никуда не прыгает | да |
| `vn.eval_when(expr)` | `:57` | `py_eval` для условных exits | только если exit объявил `when:`; в контенте таких нет → не покрыт рантаймом |
| `vn.pack_registry` | `:88` | гейт владения паками | см. ниже |

Глубину стека считает `vn_compat.call_stack_depth()` (`engine_compat/000_compat.rpy:8-15`) — единственный модуль, которому разрешено трогать полудокументированный API движка (G18), с контракт-тестом `tools/vn/tests/test_engine_compat.py`.

**NOT IMPLEMENTED, хотя заявлено в `../ARCHITECTURE.md`:** `vn.register_system()` (`:717`), `vn.safe_jump()` (`:1733`), `vn.scene_enter()` / `vn.scene_leave()` (`:1325,1555`), сохраняемые `vn_pos_scene` / `vn_pos_beat` (`:3136-3151`), блокировка rollback внутри `checkpoint()` на границе главы (`:3151`). В коде есть только `vn_scene`. Каталог `game/framework/10_systems/` содержит один `README.md` и ни одной системы.

**NOT IMPLEMENTED:** `vn_qa.choice(scene_id, menu_id, idx)` (`030_flow.rpy:98-101`) — `pass`-стаб. Докстрока и `../ARCHITECTURE.md:544-551` утверждают, что компилятор эмитит его первым стейтментом каждой ветки выбора; `emit_scene` копирует авторский источник дословно и меню не переписывает.

### Точка входа

`label start` (`030_flow.rpy:217-224`): берёт `vn_registry.chapters()`; пустой список → две локализованные строки и `return` (игра честно говорит, что контента нет); иначе `renpy.jump(_chapters[0]["entry_label"])`. Ни одного `chNN`-идентификатора во framework нет — правило слоя 0.

### Обвязка сцены (генерат)

Реальный файл `game/generated/scenes/ch01/ch01_s020.gen.rpy:8-18`:

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

Контракт переходов: авторское тело возвращает **строковый литерал** — `return "roof"` — а обвязка диспетчеризует по `_return`. Прыгать `jump`/`call` за пределы своей сцены авторскому `.rpy` запрещено (`scenes.py:100-104`). Терминальная сцена (`ch01_s030.gen.rpy:14-16`) вместо диспетча получает:

```renpy
    $ vn.chapter_done("ch01")
    if _return is None:
        jump vn_end_of_content
```

Аварийные метки (`030_flow.rpy:227-242`):

| Метка | Когда | Что делает |
|---|---|---|
| `vn_scene_unavailable` | `_return` не совпал ни с одним exit; цель ещё не написана (draft) | под автопилотом — `FAIL`-маркер и выход; иначе две строки + `renpy.full_restart()` |
| `vn_end_of_content` | терминальная сцена вернула `None` | под автопилотом — снимки экранов + `OK`-маркер; иначе строка + `full_restart()` |

### Shim-метки и G7

`config.label_overrides` сам по себе не даёт rollback-логу и call-стеку точки опоры, поэтому переименование сцены порождает **и** запись в карту, **и** реальную метку-заглушку. Источник — `content/renames.yaml` (сейчас пустой: `scenes: {}`, `deleted_scenes: {}`, `labels: {}`, `vars: {}`), эмиттер — `compile.py:407-427`, генерат — `game/generated/registry/overrides.gen.rpy`:

```renpy
init -100 python:
    # update, а не define: DLC-паки могут дополнять карту (C12).
    config.label_overrides.update({})

# Переименований нет — shim-метки не требуются.
```

При непустых переименованиях на каждую пару эмитится:

```renpy
label <old>:
    $ vn.unwind_call_stack()
    jump <new>
```

Размотка стоит перед `jump` намеренно: сейв со старым id и грязным call-стеком не должен тащить лишние кадры.

**Хука «перехват jump на несуществующую метку» в Ren'Py не существует** — прямо записано в `001_boot.rpy:38-49`. Shim-метки и есть единственная реальная защита; `config.exception_handler` — последний эшелон, а не решение.

---

## 7. Реестры рантайма — IMPLEMENTED

`game/framework/00_core/010_registry.rpy`, `init -999 python in vn_registry`. Данные — генерат (`init -100`), здесь только доступ:

| Функция | Строка | Возвращает |
|---|---|---|
| `chapters()` | `:7` | `list(VN_CHAPTERS)`; пустой проект → пустой список |
| `menus()` | `:12` | `VN_MENUS` (реестр choice-id из `registry/menus.gen.rpy`) |
| `scene_label(full_id)` | `:16` | сам `full_id` — метка обвязки сцены равна её id (G7) |

Живой `VN_CHAPTERS` (`game/generated/registry/chapters.gen.rpy`) содержит две записи: `ch01` (`pack: core`, `status: draft`, `entry_label: ch01_s010`) и `ch90` (`pack: ep_beach`).

---

## 8. Паки и владение — честно

`_PackRegistry` в `030_flow.rpy:63-88`:

| Метод | Поведение сейчас |
|---|---|
| `installed(pack_id)` | `pack_id == "core"` или наличие в `VN_PACKS` (генерат) |
| `owned(pack_id)` | `core` → True; не установлен → False; есть провайдер → его вердикт; **иначе True** |
| `set_ownership_provider(fn)` | **IMPLEMENTED (ADR-0014)**: единственный вызывающий — `035_platform.rpy:75`, `init 999`, и только если движок поднял Steam |

Практический итог: **под Steam `owned()` честно спрашивает платформу, вне Steam — всегда True для любого установленного пака.** Провайдер (`_steam_owns_pack`, `035_platform.rpy:55-68`) отвечает по `dlc_installed(steam_dlc_appid)`; у пака без `steam_dlc_appid` — True, при ошибке API — fail-open True. Подключается это не в `label splashscreen` (такой метки в проекте нет — устаревшее указание в докстринге `030_flow.rpy:67`), а в `init 999` после загрузки реестров. Гейт логический и от копирования `.rpa` не защищает — так и задумано (G9), но полагаться на него как на DRM нельзя. Потребители: `game/generated/screens/chapter_select.gen.rpy`, `080_achievements.rpy:41`, `090_gallery.rpy:44`. Подробнее — [30-packs-and-dlc.md](30-packs-and-dlc.md), [39-platforms.md](39-platforms.md).

Смежное: `project.yaml` описывает у флейворов список `packs`, но **гейтом он не является** — `VN_PACKS` перечисляет все паки независимо от флейвора (NOT IMPLEMENTED).

---

## 9. `vn_build`: как игра узнаёт флейвор — IMPLEMENTED

`game/framework/00_core/060_build_info.rpy`, `init -985 python in vn_build`. Значения — **константы процесса, не `default`**: в сейв не попадают, rollback их не трогает.

Дефолты (`:14-23`): `flavor="dev"`, `build_id="dev"`, `version=None`, `packs=[]`, `nsfw=True`, `early_content=True`, `watermark=False`, `patron_tag=None`. Затем блок читает `game/build_id.json` через `renpy.open_file` и перекрывает поля (`:32-40`); отсутствие или битый файл — молча дефолты (`:26-30`), игра на старте не падает.

**Ключевой факт: `game/build_id.json` в чекауте отсутствует.** Файл пишет `vn release build` только на время `distribute` и удаляет после (`tools/vn/src/vn/release.py:258-310` — `compute_build_info` / `write_build_info` / `clear_build_info`). Значит:

* локально игра всегда идёт как `flavor=dev`;
* `nsfw=True` и `early_content=True` → весь контент виден;
* вотермарки нет (`20_ui/screens/build_overlay.rpy` добавляет оверлей только `if vn_build.watermark`);
* проверить поведение публичного билда локально **нельзя иначе как собрав его**: `vn release build --flavor public`.

Правило для контент-кода: спрашивайте `vn_build.nsfw` / `vn_build.early_content` / `vn.pack_registry.owned(...)`, **никогда не имя флейвора** — новый флейвор должен добавляться правкой `project.yaml`, а не кода игры.

`vn_build.early_content` — **NOT IMPLEMENTED как рантайм-гейт**: значение пишется, экспонируется и не читается ничем в `game/`. Гейтит оно на границе релиза, а не в игре: проверка «зрелость контента» в `vn release validate` (`early_content_checks`, `release.py:403-438`) — самоактивирующаяся, до первой главы `status: release` это WARN, после — `draft` = FAIL. `nsfw`, `watermark`, `patron_tag` — IMPLEMENTED и в рантайме. Детали флейворов — [29-build-and-release.md](29-build-and-release.md) §5.1.

### `patron_tag` вместо `patron_token` (ADR-0011) — IMPLEMENTED

`game/build_id.json` целиком уезжает игроку, поэтому класть в него секрет нельзя. Поле `patron_token` заменено на **`patron_tag`** — невосстановимую производную от токена получателя: `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex (`tools/vn/src/vn/release.py:455-476` `patron_tag()`). Схема бампнута `build_info@1` → **`build_info@2`** (`compute_build_info`, `release.py:479-506`); `build_info@1` оставлена в реестре схем с пометкой «устарела» — чтобы читать уже выпущенные артефакты.

Рантайм читает именно `patron_tag` (`060_build_info.rpy:23,40`), а вотермарка собирается как `build_id + " · " + patron_tag` (`vn_build.label()`, `:42-45`). Проверено сквозняком: в реальной patron-сборке из 1663 файлов дистрибутива токен не встречается ни в одном.

**Требование к процессу, а не к коду:** сам токен-метка получателя обязан быть случайным (`secrets.token_hex(16)`). По короткой метке 8 hex восстановить длинный случайный токен нельзя, а вот словарный или короткий токен подбирается перебором по этой же метке. Детали релизного тракта — [29-build-and-release.md](29-build-and-release.md).

---

## 10. Крах: breadcrumbs и отчёт — IMPLEMENTED

`game/framework/00_core/070_crash.rpy`, `init -950`:

1. **Хлебные крошки.** Кольцевой буфер `collections.deque(maxlen=40)` из пар `(HH:MM:SS, метка)`, наполняется через `config.label_callbacks.append(_vn_crash_breadcrumb)` (`:25`). Служебные метки движка (`_*`) отфильтрованы (`:22`). Это главный контекст «где случилось», которого нет в голом трейсбеке.
2. **Строка в лог.** Первое, что делает `vn_crash_write_report(te)` (`:41-52`), — пишет `[vn] unhandled exception: <последняя строка трейсбека>` через `vn_log`. Своим `try/except`, до всякой работы с диском: разбор падения начинается с `grep "\[vn\]" log.txt`, и факт краха не должен пропасть, если `savedir` недоступен и отчёт записать не удастся. Берётся **последняя** непустая строка `te.simple` (это `Тип: сообщение`), а не первая — первая всего лишь контекст движка «While running game code».
3. **Отчёт.** Дальше (`:53-79`) пишется `<savedir>/crash/crash-YYYYmmdd-HHMMSS.txt`: build id, флейвор, `config.version`, `renpy.version()`, время, список крошек, затем `te.full` или `te.simple`. Путь кладётся в `_vn_last_crash_report` (`:69`), каталог подрезается до 10 последних отчётов (`:71-77`). Тело обёрнуто в `try/except: pass` — репортер не имеет права добить игру вторым исключением.
4. **Возврат `False`** (`:80`) — «не обработано»: показ экрана остаётся движку, который подхватывает брендированный `screen _exception` из `game/framework/20_ui/screens/crash_screen.rpy` (см. [06-frontend.md](06-frontend.md)).

### Обработчик ровно один — и он здесь

`config.exception_handler` — **одно поле движка**, побеждает последнее по init-порядку присваивание. Раньше присваиваний было два: `001_boot.rpy` на `init -999` ставил `_vn_exception_handler` со старой трёхаргументной сигнатурой `(short, full, traceback_fn)`, а `070_crash.rpy` на `init -950` переприсваивал поле однoаргументным обработчиком 8.4+. Побеждало второе, боотовый блок был **мёртвым кодом**, и его строка `unhandled exception: …` в `log.txt` не появлялась никогда.

Сейчас обработчик один — `vn_crash_write_report`; логирование переехало в него (п. 2). На месте удалённого блока в `001_boot.rpy:38-49` оставлен комментарий-указатель, чтобы следующий читатель не завёл второй обработчик. Регрессию стережёт `tools/vn/tests/test_crash_handler.py`: присваивание `config.exception_handler` во всём `game/framework/` обязано быть ровно одно и именно в `070_crash.rpy`, а сам обработчик — логировать и возвращать `False`.

---

## 11. Логирование

Единственный логгер надстройки — `vn_log(msg)` (`001_boot.rpy:25-27`):

```python
def vn_log(msg):
    renpy.write_log("[vn] %s", msg)
```

Пишет в `log.txt` в корне проекта (в релизе — рядом с игрой). Префикс `[vn]` отделяет наши сообщения от движковых, поэтому диагностика начинается с `grep "\[vn\]" log.txt`. Кто пишет: снапшот (пропуски типов), миграции (`migration NNNN`, `chain gap`, `migrations incomplete`), `check_scene_stack` (нарушение инварианта), `vn_ach.grant` (неизвестный id — логируется, а не падает), автопилот (ошибки скриншотов и экранов), крэш-репортер (`unhandled exception: …`, см. §10). Структурированной телеметрии и отправки логов наружу нет и не планируется. Подробнее — [28-debugging.md](28-debugging.md).

---

## Как изменить / Как расширить

**Добавить глобальную переменную**
1. `content/variables/core.vars.yaml` → блок `vars:` → `type` + `default` (+ `doc`).
2. `vn build`.
3. Убедиться: в `game/generated/state/defaults.gen.rpy` появился `default g.<name> = …`, в `snapshot.gen.rpy` — пара в `SNAPSHOT_VARS`.
4. `save_schema` **не** бампать: старые сейвы получат значение из `default`.

**Добавить переменную главы**
1. `content/chapters/chNN_*/vars.yaml`, `store` обязан равняться `chNN`.
2. Дальше — как выше. Если сцена уже её пишет, до `vn build` линтер ругался на «молчаливый фантом-стор».

**Изменить смысл существующего значения** → раздел 5, «Как написать миграцию».

**Переименовать переменную**
1. Новое имя в `vars.yaml`, старое удалить.
2. `content/renames.yaml` → `vars: {старое: новое}` (append-only, старый id больше никогда не переиспользуется — G7).
3. Бампнуть `save_schema` и написать миграцию, переносящую значение.

**Добавить якорь для достижений/галереи внутри сцены** → `$ vn.beat("<id>")` руками в авторском `.rpy`. Компилятор `beat` не эмитит. См. [15-gallery.md](15-gallery.md).

**Расширить фасад `vn.*`** → только `030_flow.rpy` + синхронный бамп `API_LEVEL` там и `VN_API_LEVEL` в `tools/vn/src/vn/content/compile.py` (равенство проверяет `tools/vn/tests/test_engine_compat.py`). Бамп ломает совместимость с уже выпущенными паками — сначала прочитайте [30-packs-and-dlc.md](30-packs-and-dlc.md).

**Тронуть недокументированный API движка** → только `game/framework/00_core/engine_compat/000_compat.rpy` + контракт-тест в `tools/vn/tests/test_engine_compat.py` (G18).

---

## Чего НЕ делать

* **Не редактировать `game/generated/state/*.gen.rpy`.** Перезапишет `vn build`. Источник — `content/variables/`, `content/chapters/*/vars.yaml`, `content/migrations/`, `project.yaml`.
* **Не заводить переменную состояния прямым `default g.x = …` в рукописном `.rpy`.** Она не попадёт ни в `SNAPSHOT_VARS`, ни в миграции, ни в проверку линтера — это и есть «молчаливый фантом-стор» из G5.
* **Не начинать сохраняемые имена с `_`.** Движок такие не сериализует, `snapshot()` их пропускает.
* **Не бампать `save_schema` без файла миграции.** Компилятор упадёт: цепочка обязана быть непрерывной от 2 до `save_schema`.
* **Не создавать файл миграции без записи в `content/migrations/registry.yaml`.** Ошибка сборки «номер N не зарезервирован».
* **Не писать миграцию, которая перебирает все ключи `state`.** Там лежат `ch01.PY2` и `g.PY2` и, потенциально, retired-переменные старых сейвов.
* **Не полагаться на `state[...]` без `.get()`.** Старый сейв мог не знать ключа.
* **Не делать переходы между сценами через `jump`/`call` из авторского `.rpy`.** Только `return "<exit_id>"`; всё остальное запретит `validate_scene`.
* **Не выносить логику восстановления в `config.after_load_callbacks`.** Контракт G5: control flow после загрузки — только в `label after_load`; коллбэки — чистая валидация без переходов.
* **Не полагаться на `owned()` как на защиту.** Под Steam он спрашивает платформу (`dlc_installed`), вне Steam — всегда True; при ошибке API — fail-open True. Это гейт витрины, не DRM (§8).
* **Не рассчитывать, что `flavor` в dev что-то ограничивает.** `game/build_id.json` отсутствует → `nsfw=True`, `early_content=True`, весь контент виден.
* **Не возвращать в `build_id.json` сам patron-токен.** Файл уезжает игроку целиком; в схеме `build_info@2` есть только производная метка `patron_tag` (ADR-0011). Поля `patron_token` в рантайме больше нет — `vn_build.patron_token` вернёт `AttributeError`.
* **Не переиспользовать удалённый id** (сцены, главы, персонажа, переменной). G7: id неизменяемы навсегда; исчезновение выпущенного id ловит `lint.py:383-420` — но только если `id_registry.json` непустой, а он наполняется лишь при релизе главы со `status: release`.
* **Не считать, что `vn.check_scene_stack()` что-то чинит.** Он только логирует; восстановление — задача `unwind_call_stack()` в обвязке и shim-метках.

---

## Проверка

```bash
vn content lint                  # переменные сцен против Variable Registry, store==id главы, G7
vn build                         # полная сборка; падает на разрыве цепочки миграций
vn build --check                 # ничего не пишет; exit 1 = генерат протух относительно источников
python -m pytest tools/vn/tests -q          # 278 тестов; test_saves.py — эмиссия миграций и снапшота
vn save check                    # JSON-заголовки 2 фикстур: schema/версия/сцена, без unpickle
vn save corpus                   # обе фикстуры грузятся в реальной игре, after_load гоняет миграции
vn test smoke                    # автопилот проходит главу; .vncache/smoke/state.json = финальный снапшот
```

Что смотреть глазами после прогона:

* `.vncache/smoke/state.json` — фактический снапшот на конец прогона; здесь видно, попала ли новая переменная в сейв;
* `.vncache/smoke/RESULT.txt` — `OK: vn_end_of_content` или `FAIL: vn_scene_unavailable`;
* `log.txt` — строки `[vn] migration NNNN`, `[vn] migration chain gap`, `[vn] scene stack invariant violated`;
* `traceback.txt` в корне — если появился, прогон упал (автопилот удаляет его перед стартом, так что наличие однозначно).

Про сам корпус, линию `.rpyc` (52 файла в `ci/fixtures/rpyc-line/`) и обе фикстуры — [27-testing.md](27-testing.md). Про чтение логов и дев-меню — [28-debugging.md](28-debugging.md).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `game/framework/00_core/020_state.rpy`, `game/framework/00_core/030_flow.rpy`, `content/variables/core.vars.yaml`, `content/chapters/*/vars.yaml`, `project.yaml` (`save_schema`), `content/migrations/registry.yaml`, `tools/schemas/vars@1.schema.json`, `tools/vn/src/vn/content/compile.py:90-111,332-404`; при работе с флейворами — `game/framework/00_core/060_build_info.rpy`, `tools/schemas/build_info@2.schema.json`, `docs/adr/0011-patron-tag-instead-of-token.md` |
| **Не трогать** | `game/generated/**` целиком (генерат `vn build`), `game/assets/**`, `game/tl/**`, `.vncache/**`, `ci/fixtures/rpyc-line/**` (линия statement-имён — правится только через `vn save corpus --add`) |
| **Зависимости** | новая переменная → `defaults.gen.rpy` + `snapshot.gen.rpy` + Variable Registry линтера + возможная миграция; бамп `save_schema` → обязательный файл миграции + резерв номера + перепроверка корпуса; правка `API_LEVEL` → `VN_API_LEVEL` в компиляторе + манифесты паков + `test_engine_compat`; правка `030_flow.rpy` → обвязка всех сцен, которую эмитит `tools/vn/src/vn/content/scenes.py:197-273` |
| **Валидация** | `vn content lint && vn build --check && python -m pytest tools/vn/tests -q && vn save corpus` |
| **Частые ошибки** | 1) правка `game/generated/state/*.gen.rpy` вместо декларации — исчезнет на следующей сборке; 2) бамп `save_schema` без файла миграции или без резерва номера — красная сборка; 3) миграция, обходящая `state.keys()`, — там лежат `ch01.PY2`/`g.PY2` и retired-переменные; 4) попытка «починить» строки `[vn] snapshot: … пропущен (не-простой тип _Feature)` — это штатный фильтр, а не баг; 5) вывод из `docs/ARCHITECTURE.md`, что `vn.safe_jump` / `vn.scene_enter` / `vn_pos_scene` / `vn.register_system` существуют — их нет в коде; 6) допущение, что `owned()` ограничивает кого-то в standalone-сборке — провайдер подключается только при живом Steam (`035_platform.rpy:75`), иначе вердикт всегда True; 7) обращение к `vn_build.patron_token` — поля больше нет, в `build_info@2` лежит только производная метка `patron_tag` (ADR-0011); 8) ожидание, что корпус сейвов «просто грузит» — фикстур две, и `schema1-demo` обязана поднять схему до 2 через миграцию `0002`, иначе `vn save corpus` красный |
