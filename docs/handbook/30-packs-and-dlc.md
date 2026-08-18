# 30. Паки и DLC

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — формат пака, валидация манифеста и компиляция пак-глав наравне с ядром работают полностью; гейт **установленности** стал честным (`installed()` сверяет `VN_PACKS` со списком поставки `vn_build.packs`, §6), гейт **владения** ожил ([ADR-0014](../adr/0014-platform-services.md): провайдер подключается в `00_core/035_platform.rpy` при живом Steam, маппинг — `steam_dlc_appid` в манифесте), **но** вне Steam `owned()` по-прежнему равно `installed()`, `vn pack build` кладёт в zip только сцены и манифест, а из зон пака компилятор читает **только** `chapters/` — `characters/`, `vars.yaml`, `loc/`, галерея и ачивки пака не собираются.
> **Отвечает на вопрос:** «Как выпустить кусок контента отдельной единицей поставки — и что из обещанного про DLC на самом деле работает».

Пак — это каталог `packs/<id>/` с `manifest.yaml` и деревом, зеркалящим `content/`. В репозитории живут два реальных примера: `ep_beach` (пак-эпизод с одной главой `ch90`) и `nsfw` (пак-контейнер без глав вообще). Весь код подсистемы — это `_collect_packs` в компиляторе (`../../tools/vn/src/vn/content/compile.py:437-472`), группа `vn pack` в CLI (`../../tools/vn/src/vn/cli.py:1568-1639`) и класс `_PackRegistry` в рантайме (`../../game/framework/00_core/030_flow.rpy:63-102`). Всё вместе — меньше 150 строк.

---

## Быстрый ответ

```bash
vn pack validate            # схемы всех манифестов + api_level против фасада vn.*
vn build                    # главы паков компилируются ВМЕСТЕ с ядром, отдельной команды нет
vn pack build ep_beach      # -> build/packs/ep_beach.zip (манифест + генерат глав пака)
```

Проверено на машине владельца 2026-08-08:

```
 ✓ ep_beach: dlc v1.0.0, api_level [1, 2) (фасад 1)
 ✓ nsfw: dlc v0.1.0, api_level [1, 2) (фасад 1)
pack validate: OK (2 паков)
```

Отдельной команды «собрать только пак» **нет и не нужно**: пак-главы попадают в `game/generated/scenes/` при обычном `vn build`. `vn pack build` — это упаковка уже собранного генерата в zip-заготовку Steam-депота, не сборка.

---

## 1. Модель: один пак = одно дерево

`packs/README.md` формулирует норму в трёх строках: одно дерево, зеркалящее `content/`, принадлежность — **по расположению**, поля `pack:` в `chapter.yaml` не существует. Это подтверждается кодом: `_collect_chapters` строит список зон `[("core", content/chapters)] + [(pack_id, packs/<id>/chapters) …]` и проставляет `meta["pack"] = pack_id` по зоне (`compile.py:500-514`, `:541`).

Фактическое содержимое репозитория:

```
packs/
├── README.md
├── ep_beach/
│   ├── manifest.yaml                                  # kind: dlc, v1.0.0
│   └── chapters/ch90_beach/
│       ├── chapter.yaml                               # id: ch90, status: draft, entry_scene: s010
│       └── scenes/s010_shore.scene.{yaml,rpy}         # 4 + 5 строк
└── nsfw/
    ├── manifest.yaml                                  # kind: dlc, v0.1.0
    └── chapters/.gitkeep                              # ГЛАВ НЕТ — это пак-контейнер
```

`nsfw` — важный пример: пак **без единой главы**. Он существует, чтобы (а) быть перечисленным в `project.yaml: flavors.patron.packs`, (б) документировать конвенцию `assets_src/png/cg/nsfw/**` (комментарий в самом манифесте), (в) дать релизному гейту что проверять (`release.py:539-543` требует наличие `packs/<pid>/manifest.yaml` для каждого пака флейвора). Никакого рантайм-эффекта у него нет.

### 1.1 Какие зоны пака компилятор читает — исчерпывающе

| Зона пака | Читается? | Кем / почему нет |
|---|---|---|
| `packs/<id>/manifest.yaml` | **да** | `_collect_packs` (`compile.py:437-472`) |
| `packs/<id>/chapters/**` | **да** | `_collect_chapters` (`compile.py:500-514`) |
| `packs/<id>/chapters/*/vars.yaml` | **НЕТ** | компилятор глобит только `content/chapters/*/vars.yaml` (`compile.py:621`) |
| `packs/<id>/characters/**` | **НЕТ** | компилятор глобит только `content/characters/*/character.yaml` (`compile.py:878`) |
| `packs/<id>/loc/**` | **НЕТ** | зоны не существует в коде; PO пак-глав живут в общем `loc/` (см. §3.3) |
| `packs/<id>/gallery/`, `achievements/`, `ui/`, `audio/` | **НЕТ** | все эти зоны жёстко `content/…` (`compile.py:628,642,656,693,700`) |
| любые `*.yaml` под `packs/` | частично | `vn content lint` валидирует **схемы** всех yaml под `packs/` (`tools/vn/src/vn/content/lint.py:89-91`) |

**Ловушка №1.** Положить `packs/ep_beach/chapters/ch90_beach/vars.yaml` — линт его провалидирует и зачтёт переменные как существующие (`lint.py:339-346`), а компилятор их **не эмитит** в `game/generated/state/defaults.gen.rpy`. В рантайме будет `NameError`. Именованный store `dlc_<pack_id>.*` из `docs/ARCHITECTURE.md:1786,3244` — **NOT IMPLEMENTED**.

**Ловушка №2.** Персонаж в `packs/<id>/characters/` — линт видит его как существующего (`lint.py:332-338`), а компилятор упадёт понятной ошибкой на `participants`: `участник 'X' не объявлен в content/characters/ (say упадёт NameError в рантайме)` (`compile.py:755-760`). Ошибка честная, но зона у неё «не та». Персонажи DLC сейчас объявляются в ядре.

---

## 2. `manifest.yaml` — полная таблица полей

Схема: `../../tools/schemas/pack_manifest@1.schema.json`, `additionalProperties: false`. Обязательные — `schema, id, kind, version, api_level`.

| Поле | Тип / ограничение схемы | Обязательно | Кто читает | Статус |
|---|---|---|---|---|
| `schema` | `const: pack_manifest@1` | да | `SchemaRegistry.validate` (`schemas.py:13-51`) | IMPLEMENTED |
| `id` | `^[a-z][a-z0-9_]{1,31}$` | да | `_collect_packs`: **обязан совпадать с именем каталога** (`compile.py:454-456`); ключ в `VN_PACKS` | IMPLEMENTED |
| `kind` | enum `dlc` \| `voice_pack` \| `mod` | да | выводится в `VN_PACKS[<id>]["kind"]` (`scenes.py:287-289`) и в выводе `vn pack validate` | IMPLEMENTED (но поведение от `kind` **не зависит** ни в одной ветке кода) |
| `version` | `^\d+\.\d+\.\d+$` | да | `VN_PACKS[<id>]["version"]` | IMPLEMENTED |
| `api_level` | объект `{min: int≥1, below: int≥2}`, оба обязательны, `additionalProperties: false` | да | `_collect_packs` (`compile.py:457-462`) | IMPLEMENTED |
| `requires.core` | строка-диапазон версий ядра | нет | `_semver_in_range` (`compile.py:464-470`, `:479-497`) | IMPLEMENTED |
| `requires.packs` | массив pack-id | нет | **никто** — схема разрешает, кода нет | NOT IMPLEMENTED |
| `title_key` | `^[a-z0-9_.]+$` | нет | **никто**. Строки `meta.packs.ep_beach.title` / `meta.packs.nsfw.title` заведены в `content/ui/strings.yaml:11-12` и переведены на de/en/pseudo, но `VN_PACKS` несёт только `kind` и `version` — ни один экран не показывает название пака | IMPLEMENTED / МЁРТВЫЙ (строка есть, потребителя нет) |
| `fallback_anchor` | `^ch\d{2}_s\d{3}$` | нет | **никто** — единственное вхождение строки в репозитории — сама схема | NOT IMPLEMENTED |
| `lang` | `^[a-z]{2}(_[A-Z]{2})?$`, «только для `kind: voice_pack`» | нет | **никто**; связь с `kind` схемой не выражена и кодом не проверяется | NOT IMPLEMENTED |
| `steam_dlc_appid` | integer ≥ 1 | нет | `_emit_platform` → `VN_STEAM_DLC` в `platform.gen.rpy` (`compile.py:143-144`); рантайм — ownership-провайдер `vn_platform._steam_owns_pack` | IMPLEMENTED (ADR-0014, [39](39-platforms.md) §5). Один пак = один DLC App ID; бандлы — на стороне Steamworks |

Реальный манифест целиком (`packs/ep_beach/manifest.yaml`, 8 строк):

```yaml
schema: pack_manifest@1
id: ep_beach
kind: dlc
version: 1.0.0
title_key: meta.packs.ep_beach.title
api_level: {min: 1, below: 2}
requires:
  core: ">=0.1.0 <1"
```

### 2.1 `api_level`: против чего именно проверяется

`api_level` — это диапазон версий **фасада `vn.*`**, единственного API, через которое сгенерированный код обращается к движку. Константа фасада живёт в двух местах и синхронизируется вручную:

| Где | Значение | Строка |
|---|---|---|
| Рантайм-фасад | `API_LEVEL = 1` | `game/framework/00_core/030_flow.rpy:9` |
| Компилятор (зеркало) | `VN_API_LEVEL = 1` | `../../tools/vn/src/vn/content/compile.py:554` (сверка — `:577-581`) |

Проверка — одно условие (`compile.py:457-462`):

```python
if not (api["min"] <= VN_API_LEVEL < api["below"]):
    errors.append(f"{rel}: api_level [{api['min']}, {api['below']}) несовместим с фасадом "
                  f"vn.* (текущий {VN_API_LEVEL}) — пак не собирается (G9)")
```

Ключевое слово — **«не собирается»**. Несовместимый пак роняет `vn build` целиком, а не «отключается с внятным сообщением», как обещает `docs/ARCHITECTURE.md:3278` («DLC „Лето“ требует обновления игры»). Рантайм-деградация несовместимого пака — **NOT IMPLEMENTED**: реестр `VN_PACKS` собирается только из паков, которые прошли валидацию на этапе сборки.

**Ничто не проверяет, что `API_LEVEL` в `030_flow.rpy` и `VN_API_LEVEL` в `compile.py` совпадают.** Расхождение обнаружится только тем, что паки перестанут собираться (или наоборот — соберутся с несовместимым фасадом).

### 2.2 `requires.core`

`_semver_in_range(version, spec)` (`compile.py:479-497`) — самописный, 19 строк. Пробел = логическое И. Поддерживаются ровно пять операторов: `>=`, `<=`, `==`, `<`, `>`. **Неизвестный оператор трактуется как `False`** — совместимость не угадывается (это осознанно, комментарий в докстринге). Версия ядра берётся из `project.yaml: version` (сейчас `0.1.4`).

Нет `^`, `~`, `*`, `||`. `">=0.1.0 <1"` работает; `"^0.1"` — молча несовместимо и уронит сборку.

### 2.3 Схема против ARCHITECTURE.md — расхождения, которые сломают вам манифест

`docs/ARCHITECTURE.md:3244-3257` показывает манифест, который **не пройдёт валидацию** (схема `additionalProperties: false`):

| В ARCHITECTURE.md | В реальной схеме |
|---|---|
| `api_level: ">=2 <3"` (строка) | объект `{min: 2, below: 3}` |
| `steam_appid: 1234571` | поле запрещено; App ID **DLC** называется `steam_dlc_appid` (ADR-0014), а App ID игры живёт в `project.yaml: platform.steam.appid` |
| `injects: [{anchor, chapter}]` | поле запрещено |
| `state_store: dlc_summer` | поле запрещено |
| `requires: {core: ">=2.3.0 <3.0.0"}` | совпадает |

Пишите манифест по схеме, а не по ARCHITECTURE.md. `vn pack validate` скажет прямо, если ошиблись.

---

## 3. Как контент пака попадает в игру

### 3.1 Один общий id-space, одно дерево генерата

Главы ядра и паков собираются в **одно и то же** `game/generated/scenes/`. Проверено на диске: `game/generated/scenes/ch90/ch90_s010.gen.rpy` собран из `packs/ep_beach/chapters/ch90_beach/scenes/s010_shore.scene.{yaml,rpy}` — это видно в шапке файла:

```
# source: packs/ep_beach/chapters/ch90_beach/scenes/s010_shore.scene.yaml  blake3:81e1e63d8013e62d
# source: packs/ep_beach/chapters/ch90_beach/scenes/s010_shore.scene.rpy  blake3:0fbcdf43d462544d
```

Обвязка сцены пака **ничем не отличается** от обвязки сцены ядра (`game/generated/scenes/ch90/ch90_s010.gen.rpy:8-19`) — тот же `vn.checkpoint`, тот же `call …__body`, тот же `vn.check_scene_stack()`. Подробнее про обвязку — [Сцены](12-scenes.md).

Столкновение id главы между ядром и паком — **ошибка компиляции** (`compile.py:524-526`: `id ch90 уже занят другой главой (ядро/пак)`). Нумерация пак-глав с `ch90` — de-facto соглашение демо-контента; **в `docs/conventions/naming.md` его нет**, и `vn chapter new` о паках не знает вовсе (`tools/vn/src/vn/content/scaffold.py:59-78` считает `max+1` только по `content/chapters/`) — если ядро дорастёт до `ch90`, будет коллизия.

### 3.2 Реестры

`emit_chapter_registry` (`../../tools/vn/src/vn/content/scenes.py:276-296`) кладёт в `game/generated/registry/chapters.gen.rpy` ровно две строки данных:

```renpy
define VN_CHAPTERS = ({'id': 'ch01', …, 'pack': 'core'}, {'id': 'ch90', …, 'pack': 'ep_beach'})
define VN_PACKS = {'ep_beach': {'kind': 'dlc', 'version': '1.0.0'}, 'nsfw': {'kind': 'dlc', 'version': '0.1.0'}}
```

`VN_PACKS` собирается из **всех** валидных манифестов под `packs/`, независимо от флейвора (`scenes.py:287-289`) — см. §6.

### 3.3 Локализация пак-глав идёт через ОБЩИЙ `loc/`

Вопреки `docs/ARCHITECTURE.md:3240` (`packs/<id>/loc/`), say-id и PO пак-глав живут в том же дереве, что и ядро. Проверено на диске:

```
loc/ledger/ch90.json          # ledger@1, 3 say-ключа ch90_s010_0001..0003
loc/po/{de,en,pseudo}/ch90.po
```

Код: `assign_ids` добавляет `packs/*/chapters` к зонам сканирования (`../../tools/vn/src/vn/loc/keys.py:49`), домен PO = глава. Зоны `packs/<id>/loc/` в коде **не существует**. UI-строки пака (`title_key`, названия глав) кладутся в общий `content/ui/strings.yaml`. Подробности round-trip — [Локализация](14-localization.md).

### 3.4 Чего пак-контент НЕ получает

| Механизм | Что происходит | Код |
|---|---|---|
| `vn content graph` | пак-главы **не видны** в Mermaid — сканируется только `content/chapters/` | `tools/vn/src/vn/content/graph.py:15` |
| `vn release changelog` | видит главы паков с 2026-08-18: `ch90` попадает и в `ci/release-manifest.json` (поле `pack`), и в `docs/CHANGELOG.md` с пометкой `(pack ep_beach)` | `release.py: snapshot_content` |
| `id_registry.json` (G7) | `_released_ids` собирает только главы со `status: "release"`; `ch90` — `draft` | `release.py:69-96` |
| CODEOWNERS | записи `/packs/` **нет** вообще | `CODEOWNERS:1-26` |

Проверить графом: `vn content graph` сейчас печатает `subgraph ch01` с тремя сценами и ни одного узла `ch90`.

---

## 4. Почему гейт логический, а не файловый (G9)

Норма G9 (`docs/ARCHITECTURE.md:69`, развёрнуто `:3261-3271`): **скрипты всех установленных паков грузятся всегда**. Причина движковая, а не проектная — Ren'Py индексирует `.rpa` и загружает все `.rpyc` **до** исполнения любых init-блоков (иначе он не мог бы грузить игры, у которых сами скрипты лежат в архиве). Значит:

- менять `config.archives` в `init` бесполезно — состав загруженных скриптов уже зафиксирован;
- `_renpysteam` в раннем init ещё не инициализирован, `dlc_installed()` в этот момент недостоверен;
- наличие `.rpa` ничем не защищено (архив распаковывается извне).

Отсюда единственный работающий дизайн: **гейт логический** — метки пака физически присутствуют и инертны, а фильтрация идёт по данным реестров через `vn.pack_registry.owned()`.

Дополнительный факт этого репозитория: `.rpa`-архивов **нет вовсе** — ни одного `build.archive(...)` в `game/`, ассеты едут россыпью. То есть даже файловой границы «что лежит в депоте пака» сегодня физически не существует. Это норма, а не пробел: `docs/ARCHITECTURE.md` §2.4 (`:943`) фиксирует россыпь ради Steam-дельта-патчей; тематические `.rpa` — только опция mobile-поставки фазы 3, в desktop — лишь через ADR.

Комментарий к этому есть прямо в докстринге команды (`cli.py:1603-1604`): «Скрипты пака грузятся всегда (управлять загрузкой нельзя, G9) — гейт логический».

---

## 5. Владение паком: `vn.pack_registry`

Платформенная половина этой темы (кто ставит провайдера, как считается `dlc_installed`, почему fail-open) вынесена в [39-platforms.md](39-platforms.md) §5 — здесь только контракт ядра.

**Имя API — `vn.pack_registry`, не `vn.packs`.** `docs/ARCHITECTURE.md:170` фиксирует это прямо: «Единственное API: `vn.pack_registry.owned(pack_id)` (через фасад). `vn_packs.*` и `vn.pack_flag` не существуют».

Реализация целиком — `../../game/framework/00_core/030_flow.rpy:63-88`:

```python
def installed(self, pack_id):
    return pack_id == "core" or pack_id in getattr(renpy.store, "VN_PACKS", {})

def owned(self, pack_id):
    if pack_id == "core":          return True
    if not self.installed(pack_id): return False
    if self._provider is not None:  return bool(self._provider(pack_id))
    return True                     # ← без провайдера установленный пак считается купленным
```

| Метод | Статус | Комментарий |
|---|---|---|
| `installed(pack_id)` | IMPLEMENTED | `core` или ключ в `VN_PACKS` |
| `owned(pack_id)` | **IMPLEMENTED** | под Steam — по провайдеру: пак с `steam_dlc_appid` даёт `False`, пока DLC не установлен. **Вне Steam** (или у пака без маппинга) — по-прежнему `True` для всего, что есть в `VN_PACKS` |
| `set_ownership_provider(fn)` | **IMPLEMENTED / ПОДКЛЮЧЁН** | вызывающий один: `game/framework/00_core/035_platform.rpy:75` (`init 999`, только если `vn_platform.steam()` не `None`) — [ADR-0014](../adr/0014-platform-services.md), [39-platforms.md](39-platforms.md) §5 |
| `installed_versions()`, `owned_ids()` (`ARCHITECTURE.md:2993-2994`) | **NOT IMPLEMENTED** | методов не существует |
| `refresh_ownership()` в `label splashscreen` (`ARCHITECTURE.md:3269`) | **NOT IMPLEMENTED** | метода и метки не существует |

Три реальных потребителя `owned()`:

| Место | Что фильтрует |
|---|---|
| `game/generated/screens/chapter_select.gen.rpy:18` (шаблон `scenes.py:335-338`) | карточки глав в меню выбора |
| `game/framework/00_core/080_achievements.rpy:40-41` | видимость достижения (`spec["pack"]`, по умолчанию `core`) |
| `game/framework/00_core/090_gallery.rpy:44` | видимость элемента галереи |

Поля `pack:` в `achievements@1` и `gallery@1` реальны (`tools/schemas/achievements@1.schema.json:19`, `gallery@1.schema.json:63`), и компилятор проверяет, что указанный пак существует: `достижение {aid}: пак {pack_id!r} не установлен` (`compile.py:814-817`). В standalone-сборке `owned()` всё ещё возвращает `True` и фильтрация ничего не отсекает; **под Steam у пака с `steam_dlc_appid` без купленного DLC отсекутся все три места сразу** — карточка главы, элементы галереи и ачивки этого пака.

DLC-бейдж на карточке главы — единственный видимый игроку признак пака: `if ch["pack"] != "core"` → фрейм со строкой `ui.chapters.dlc` (`game/framework/20_ui/components.rpy:273-277`).

### 5.1 Условный контент ядра «если куплен пак» — не так, как в ARCHITECTURE.md

`docs/ARCHITECTURE.md:1858` описывает мини-язык `when:` с базой `packs.<pack_id>`, компилируемой в `vn.pack_registry.owned("<pack_id>")`, и утверждает, что «в рантайме нет ни eval-обёртки, ни интерпретатора». **Обе половины неверны.** Реальный эмиттер (`../../tools/vn/src/vn/content/scenes.py:250-251`):

```python
if e.get("when"):
    cond += f" and vn.eval_when({e['when']!r})"
```

То есть выражение попадает в рантайм **дословно** и исполняется через `vn.eval_when` → `renpy.python.py_eval` (`030_flow.rpy:57-60`). Ни синтаксиса `packs.<id>`, ни `pack_owned(...)`, ни валидации выражения против реестра переменных в коде нет. В реальном контенте `when:` не используется **ни разу** (единственное вхождение — синтетический тест `tools/vn/tests/test_verify_regressions.py:44`).

Практический вывод: условный переход «если куплен ep_beach» пришлось бы писать полным Python-выражением, и это **непроверенный путь** — ни теста, ни сцены. Подробнее про `exits` и условия — [Диалоги и ветвление](13-dialogue.md).

---

## 6. Связь с флейворами: `packs` гейтит установленность в рантайме

`project.yaml:66-76` объявляет два флейвора:

```yaml
public:  {packs: [ep_beach],       nsfw: false, early_content: false, watermark: false}
patron:  {packs: [ep_beach, nsfw], nsfw: true,  early_content: true,  watermark: true}
```

Что список `packs` делает:

| Эффект | Есть? | Код |
|---|---|---|
| Релизный гейт проверяет наличие `packs/<pid>/manifest.yaml` для каждого пака флейвора | **да** | `release.py:539-543` |
| Список попадает в `game/build_id.json` как `build_info.packs` | **да** | `release.py:483` |
| Экспонируется в рантайме как `vn_build.packs` | **да** | `060_build_info.rpy` |
| **Рантайм-гейт установленности читает его** | **да, с этой итерации** | `_PackRegistry.installed()` (`030_flow.rpy:77-91`) |
| Исключает пак из сборки / из `VN_PACKS` | **НЕТ, и не будет** | скрипты глав уезжают всегда — гейт логический (G9); `VN_PACKS` строится из всех манифестов под `packs/` (`scenes.py:287-289`) |

Формула гейта:

```renpy
installed(pack_id) = pack_id == "core"
                     or (pack_id in VN_PACKS
                         and (не релизная сборка or pack_id in vn_build.packs))
```

Два решения, которые стоит понимать буквально:

1. **«Не релизная сборка» = отсутствия `game/build_id.json`**, то есть производный флаг `vn_build.is_release` (`060_build_info.rpy:24-38`; в схеме `build_info@2` этого поля нет — он выводится из факта файла). В dev-чекауте разработчику видно всё установленное, иначе dev-прогон и `vn test smoke` гейтились бы вслепую.
2. **Пустой `packs` в релизной сборке гейтит, а не считается dev.** Флейвор без паков легитимен, и именно в нём баг «пак чужого флейвора считается установленным» воспроизводился бы в чистом виде.

**Следствие:** в `public`-сборке пак `nsfw` больше **не** считается ни установленным, ни купленным (без Steam-провайдера владение = установленность). Его главы, элементы галереи и достижения игроку не видны, а знаменатели счётчиков (`vn_gal.progress()`, `vn_ach.progress()`) считают только видимое — 100 % достижимы в любом флейворе.

**Гейт установленности ≠ гейт владения.** Второй — провайдер `_steam_owns_pack` (`035_platform.rpy:75`), работает только под живым Steam и только для пака с `steam_dlc_appid`. Именно из-за DRM-free-случая («нет провайдера → владение = установленность») сверка со списком поставки и обязательна: без неё пак `patron`-флейвора в `public`-сборке был бы и «установлен», и «куплен».

Что дополнительно гейтит NSFW-контент — `nsfw: false` → `nsfw_exclude_globs()` строит `game/assets/<cat>/nsfw/**` по **реально существующим** каталогам, и `build.classify(glob, None)` выкидывает их из дистрибутива (`release.py:493-504`, `game/options.rpy:44-51`), плюс рантайм-гейты галереи/ачивок по `vn_build.nsfw`. Подробно — в [Сборка и релиз](29-build-and-release.md).

**Чего в этом гейте нет.** Проверить его в dev-чекауте нельзя (`build_id.json` отсутствует по построению), поэтому он покрыт юнит-тестами, которые **исполняют реальные блоки** `init python in vn` и `init python in vn_build` из `.rpy` на заглушке `store` (`tools/vn/tests/test_release.py`: `test_pack_gate_honours_flavor_pack_list`, `test_pack_gate_open_in_dev_checkout`). Цепочка теста идёт от настоящего `compute_build_info(..., "public")`, то есть связывает `project.yaml` → `build_info@2` → рантайм-гейт. Живого прогона релизной сборки с непустым `packs/nsfw/chapters/` не было — контента там пока нет.

---

## 7. `vn pack validate` и `vn pack build`

### 7.1 `vn pack validate` — IMPLEMENTED / UNDOCUMENTED

`cli.py:1573-1597`. Переиспользует `_collect_packs` автономно (свой `SchemaRegistry`, свой сборщик ошибок), то есть проверяет ровно то же, что `vn build`, но без компиляции контента: наличие `manifest.yaml`, схему, `id == имя каталога`, `api_level` против фасада, `requires.core` против `project.yaml: version`.

Выход при успехе — по строке на пак плюс `pack validate: OK (N паков)`. При ошибках — `error: …` красным и `_fail(f"pack validate: {N} ошибок")` → exit 1.

В `docs/` про эту команду нет ни слова — ни в ARCHITECTURE.md, ни в ADR.

### 7.2 `vn pack build <id>` — PARTIALLY IMPLEMENTED

`cli.py:1600-1639`. Что кладётся в `build/packs/<id>.zip`:

1. `packs/<id>/manifest.yaml` → архивный путь `packs/<id>/manifest.yaml`;
2. для каждого каталога `packs/<id>/chapters/ch*` берётся `ch_id = d.name[:4]` и в архив идут **все** файлы из `game/generated/scenes/<ch_id>/` → архивный путь `game/generated/scenes/<ch>/<имя>`.

Реальное содержимое `build/packs/ep_beach.zip` (3522 байта):

```
packs/ep_beach/manifest.yaml                    160
game/generated/scenes/ch90/ch90_s010.gen.rpy   1542
game/generated/scenes/ch90/ch90_s010.gen.rpyc  2245
```

Чего в архиве нет и никогда не будет при текущем коде: ассетов, `game/tl/`, персонажей, дельт реестров (`VN_CHAPTERS`/`VN_PACKS` живут в ядре), `.rpa`, раскладки Steam-депота, версии пака в имени файла.

#### Охранник «главы объявлены, а генерата нет»

Сцены считаются **отдельно от манифеста** (`cli.py:1617-1626`): манифест в архиве есть всегда, и до правки общий счётчик делал проверку недостижимой — пустой пак уезжал архивом из одного манифеста и печатал `OK`.

Семантика охранника — **не «ноль сцен»**, а «объявлено, но не собрано»:

| Пак | Поведение | Почему |
|---|---|---|
| главы объявлены (`chapters/chNN*` есть), генерата для них нет | `exit 1`, zip **не создаётся** | типовая причина — забыли `vn build`; неполный zip не должен лежать в `build/packs/` как готовый депот |
| глав нет вовсе (`chapters/` пуст) | `exit 0` + отдельная строка-предупреждение | пак-контейнер (`nsfw`) везёт ассеты, а не эпизод — «ноль сцен» для него норма |

Проверено на машине владельца 2026-08-08:

```
$ vn pack build nsfw
warning: пак 'nsfw' не объявляет глав (packs/nsfw/chapters/ пуст) — в архиве только манифест
pack build: OK — build/packs/nsfw.zip (1 файлов, главы: —)

$ vn pack build ep_beach
pack build: OK — build/packs/ep_beach.zip (3 файлов, главы: ch90)
```

Текст ошибки для пака с главами без генерата:

```
ошибка: pack build: у пака 'ep_winter' объявлены главы (ch91), но в
game/generated/scenes/ нет ни одной их скомпилированной сцены — сначала vn build
```

Обе ветки покрыты тестами: `tools/vn/tests/test_release.py::test_pack_build_fails_when_declared_chapters_have_no_generated_scenes` и `::test_pack_build_ok_for_container_pack_without_chapters` (плюс `::test_pack_build_packs_generated_scenes_of_declared_chapters` на состав архива).

**Что охранник по-прежнему НЕ ловит:** проверка — «хоть одна сцена на весь пак». Пак с главами `ch91` и `ch92`, у которого собрана только `ch91`, соберётся молча и без `ch92` в архиве. Хотите строгости — считайте сцены по каждой главе (см. «Как изменить»).

Мелочь: `from .repo import load_yaml` на `cli.py:1611` импортируется и не используется.

### 7.3 Чего нет вообще

| Заявлено | Где | Статус |
|---|---|---|
| Депот **пака** отдельным товаром: раскладка, ассеты, `tl/` в архиве пака | `ARCHITECTURE.md:69`, `:3278`, `:3805` | NOT IMPLEMENTED. Депоты **игры** (win/linux/mac) генерируются: `vn release steam` → VDF + `build/steam/content/` ([39-platforms.md](39-platforms.md) §3.3); `vn pack build` по-прежнему кладёт в zip только манифест и сцены, и `platform.steam.depots` не знает про паки |
| Переиздание всех DLC-депотов на каждый релиз ядра | `ARCHITECTURE.md:69` | NOT IMPLEMENTED как процесс — ни джобы, ни чеклиста |
| Smoke-матрица «ядро-кандидат × версии DLC» | `ARCHITECTURE.md:3278`, `:4165` | NOT IMPLEMENTED — ни джобы, ни флага |
| Рантайм-отключение несовместимого пака с сообщением | `ARCHITECTURE.md:3278` | NOT IMPLEMENTED — компилятор падает на этапе сборки |
| `fallback_anchor` и graceful degradation сейва внутри отсутствующего DLC | `ARCHITECTURE.md:3300-3306` | NOT IMPLEMENTED — поле в схеме, читателей нет |
| Вкомпилированные копии манифестов всех выпущенных паков | `ARCHITECTURE.md:3300` | NOT IMPLEMENTED |
| `voice_pack`-депоты | `ARCHITECTURE.md:2883` | NOT IMPLEMENTED как поставка: `vn pack build` не пакует ассеты, opus-файлы едут в основном дистрибутиве. Сам голосовой контур (`voice@1`, `vn voice manifest\|import\|validate`, транскод) работает, и рантайм `vn.voice_path` уже готов к отсутствию файлов пака — no-op вместо падения ([23-audio.md](23-audio.md) §8) |

---

## 8. Как создать пак с нуля — пошагово

Скаффолда для паков **нет** (`vn chapter new` и `vn scene new` работают только с `content/chapters/`, `tools/vn/src/vn/content/scaffold.py:62`, `:82`). Всё руками.

```bash
cd C:/Users/Vadim/IdeaProjects/renpy
mkdir -p packs/ep_winter/chapters
```

**1. Манифест** — `packs/ep_winter/manifest.yaml`:

```yaml
schema: pack_manifest@1
id: ep_winter                 # ОБЯЗАН совпадать с именем каталога
kind: dlc
version: 1.0.0
title_key: meta.packs.ep_winter.title
api_level: {min: 1, below: 2}   # объект, не строка
requires:
  core: ">=0.1.0 <1"
```

```bash
vn pack validate              # ← первая проверка: схема + api_level + requires.core
```

**2. Глава пака.** Номер выбирается вручную и не должен конфликтовать с ядром (конвенция демо — `ch90+`):

```
packs/ep_winter/chapters/ch91_winter/
├── chapter.yaml       # schema: chapter@1, id: ch91, status: draft, entry_scene: s010, scene_order: [s010]
└── scenes/
    ├── s010_arrival.scene.yaml   # schema: scene@1, id: s010, participants: [...], exits: {}
    └── s010_arrival.scene.rpy    # label ch91_s010__body: … return
```

Формат — ровно тот же, что у глав ядра: [Главы](09-chapters.md), [Сцены](12-scenes.md). Контракт авторского `.rpy` (метка `__body`, никаких jump наружу, переход только через `return "<exit_id>"`) — тот же (`tools/vn/src/vn/content/scenes.py:18`, `:81-104`).

**3. Строки в ядре** — `content/ui/strings.yaml`: `meta.packs.ep_winter.title` и `meta.chapters.ch91.title` (иначе UI покажет сырой ключ; компилятор предупредит).

**4. Сборка и локализация:**

```bash
vn content lint               # схемы + структура глав (packs/* включены, lint.py:157-161)
vn loc keys                   # проставит say-id в scene.rpy пака (keys.py:49)
vn build                      # -> game/generated/scenes/ch91/, VN_PACKS, VN_CHAPTERS
vn play                       # глава видна в меню с бейджем DLC
vn pack build ep_winter       # -> build/packs/ep_winter.zip
```

**5. Флейвор** (если пак должен числиться в релизе) — `project.yaml: flavors.<f>.packs`. Помните: из сборки список ничего не вырезает (§6) — он гейтит установленность в рантайме, а `vn release validate` проверит наличие манифеста.

**6. CODEOWNERS** — записи `/packs/` в файле нет; добавьте владельца вручную (`CODEOWNERS:25-26` показывает формат для глав).

---

## 9. Как перенести главу из ядра в пак

**Id главы и id сцен НЕ меняются** — принадлежность паку определяется расположением, а не идентификатором (`compile.py:541`, `packs/README.md:3-5`). Поэтому перенос — это `git mv`, и `content/renames.yaml` трогать **не нужно**: с точки зрения G7 ни один id не исчез.

```bash
git mv content/chapters/ch05_pier packs/ep_winter/chapters/ch05_pier
vn content lint
vn build
```

Что изменится в генерате: в `VN_CHAPTERS` у главы `'pack': 'core'` станет `'pack': 'ep_winter'`, на карточке появится бейдж DLC, а фильтр `vn.pack_registry.owned(...)` начнёт (номинально) применяться.

Что перенести **отдельно и вручную**, потому что компилятор эти зоны в паке не читает (§1.1):

| Что | Куда | Почему |
|---|---|---|
| `vars.yaml` главы | оставить в `content/chapters/<ch>/vars.yaml`? **нельзя** — каталога уже нет | переменные придётся переселить в `content/variables/*.vars.yaml` (глобальный неймспейс) — иначе они исчезнут из `defaults.gen.rpy` |
| персонажи, объявленные под главу | остаются в `content/characters/` | компилятор читает только ядро (`compile.py:878`) |
| ачивки/галерея с `pack:` | остаются в `content/{achievements,gallery}/`, добавьте поле `pack: ep_winter` | зоны пака не читаются; поле `pack` валидируется (`compile.py:814-817`) |
| PO и ledger | **ничего не делать** | `loc/ledger/chNN.json` и `loc/po/*/chNN.po` уже привязаны к id главы, а не к зоне (§3.3) |

После переноса проверьте релизный учёт: `vn release changelog` главу пака увидит (`snapshot_content` → `repo.chapter_zones`) и запишет её в манифест с полем `pack: <id>`, а в changelog — с пометкой `(pack <id>)`.

---

## 10. Моды

**Статус: NOT IMPLEMENTED.** `kind: mod` разрешён схемой и больше нигде не встречается; Mod SDK, Workshop и подпись — фаза 3 (`docs/ARCHITECTURE.md:3312`).

### 10.1 `content/anchors.yaml` (G10) — файл есть, читателей нет

Реальное содержимое (4 строки):

```yaml
schema: anchors@1
# Стабильные инжект-якоря для модов (G10): сцены с контрактом
# «не удаляются и не переименовываются в пределах мажора». Заполняется с фазы 3.
anchors: []
```

| Аспект | Факт |
|---|---|
| Файл обязателен | да — `REQUIRED_FILES` линта (`tools/vn/src/vn/content/lint.py:35-43`); удалите — красный `vn build` |
| Кто читает содержимое | **никто**. Строки `anchors` нет ни в `compile.py`, ни в `game/framework/` |
| Есть ли в `manifest.json` компилятора | **нет** — вопреки утверждению аудита компилятора, файл не попадает в `inputs` |
| Схема | `anchors@1`: массив `{scene: ^ch\d{2}_s\d{3}$, since: semver, desc?}` — **не** `stable_anchors:` со списком строк, как в `ARCHITECTURE.md:3316-3323` |
| `injects:` в манифесте пака | схемой **запрещено** (`additionalProperties: false`) |

То есть механизм инжектов не просто не реализован — его невозможно даже объявить.

Симметрично: `content/flags.yaml` (`flags@1`, сейчас `flags: {}`) — тот же статус: обязателен для линта, читателей ноль.

### 10.2 Что для модов уже работает

Две вещи, обе побочные:

**Shim-метки и `config.label_overrides`** (`compile.py:407-427` → `game/generated/registry/overrides.gen.rpy`). Комментарий в эмиттере прямо объявляет мод-контракт:

```python
out.append("init -100 python:")
out.append("    # update, а не define: DLC-паки могут дополнять карту (C12).")
out.append(f"    config.label_overrides.update({overrides!r})")
```

`update`, а не `define`, значит пак или мод может дописать свои переопределения меток, не затирая ядро. Плюс на каждое переименование эмитится настоящая метка-shim, а не только запись в словаре:

```renpy
label <old_id>:
    $ vn.unwind_call_stack()
    jump <new_id>
```

Сейчас `content/renames.yaml` пуст, и генерат содержит строку «Переименований нет — shim-метки не требуются».

**Щадящая очистка `game/tl/`** (`../../tools/vn/src/vn/loc/po.py:460-485`). `vn loc import` удаляет из `game/tl/` только **свои** файлы — владение определяется маркером в шапке `.rpy` и полем `"generator": "vn loc import"` в `language.json` (`po.py:66-72`). Чужой перевод, положенный в `game/tl/` мимо конвейера (модовый или ручной), не трогается. Комментарий в коде это фиксирует дословно: «модовый/ручной перевод, брошенный в game/tl, не наш — не удаляем».

---

## 11. Чеклист нового пака

```
[ ] packs/<id>/manifest.yaml создан; id == имени каталога
[ ] api_level — ОБЪЕКТ {min, below}, не строка; min <= 1 < below
[ ] requires.core использует только операторы >= <= == < > (пробел = И); ^ и ~ НЕ поддерживаются
[ ] title_key заведён в content/ui/strings.yaml (даже если UI его пока не показывает)
[ ] vn pack validate: OK
[ ] Номер главы пака не конфликтует с ядром (vn chapter new о паках НЕ знает)
[ ] chapter.yaml + scenes/*.scene.{yaml,rpy} по общей конвенции; метка __body на месте
[ ] Переменные главы НЕ лежат в packs/<id>/chapters/*/vars.yaml (не компилируется!) —
    только content/variables/*.vars.yaml
[ ] Персонажи объявлены в content/characters/, а не в packs/<id>/characters/
[ ] vn content lint: 0 ошибок
[ ] vn loc keys — say-id проставлены; vn loc report — покрытие не упало
[ ] vn build: OK; в game/generated/scenes/<ch>/ появился генерат
[ ] vn play — глава видна в меню с бейджем DLC
[ ] vn pack build <id> — zip собрался; если пак с главами, а генерата нет — команда упадёт
    (пак БЕЗ глав соберётся штатно и скажет об этом строкой warning)
[ ] project.yaml: flavors.<f>.packs обновлён, если пак должен числиться в релизе
[ ] vn release validate --flavor public / --flavor patron: 0 FAIL
[ ] CODEOWNERS: добавлена запись на пак (сейчас /packs/ не покрыт вовсе)
```

---

## Как изменить / Как расширить

| Задача | Что править | Обязательно после |
|---|---|---|
| Бампнуть `api_level` фасада `vn.*` | `game/framework/00_core/030_flow.rpy:9` **И** `../../tools/vn/src/vn/content/compile.py:554` — две константы, синхронизации нет | обновить `api_level.below` во **всех** `packs/*/manifest.yaml`, иначе `vn build` покраснеет; ADR на смену контракта фасада |
| Включить гейт владения для Steam | ничего в паках: заполнить `project.yaml: platform.steam.appid` и `steam_dlc_appid` в манифесте пака — провайдер уже подключён (`035_platform.rpy:75`) | `vn pack validate`, `vn build`; проверить `chapter_select`, галерею, ачивки под Steam ([39](39-platforms.md) §5) |
| Гейт владения для витрины без Steam (GOG/itch/Play) | новая ветка провайдера в `game/framework/00_core/035_platform.rpy` — **не** в `030_flow.rpy` и не в экранах (гард-тест ADR-0014) | тест на `owned()` = False; [39-platforms.md](39-platforms.md) §9 |
| ~~Сделать `flavors.packs` реальным гейтом~~ | **СДЕЛАНО** — рантайм-ный вариант: `_PackRegistry.installed()` читает `vn_build.packs` (§6). Смысл `VN_PACKS` не изменился: это по-прежнему «все паки дерева» | — |
| Сделать охранник `pack build` поглавным (сейчас «хоть одна сцена на пак») | `cli.py:1617-1626`: собирать сцены в `dict[ch] -> [files]` и валить на главах с пустым списком | обновить оба теста `test_pack_build_*` в `tools/vn/tests/test_release.py`; решить, что делать с главой, у которой генерат легитимно пуст |
| Класть в депот пака ассеты и `tl/` | `cli.py:1600-1639` — добавить ветки по `game/assets/**` и `game/tl/**`; сначала решить, как определять «ассеты пака» (сейчас признака нет) | ADR: нужна принадлежность ассета паку, её в манифесте ассетов нет |
| Компилировать зоны пака `characters/`, `vars.yaml`, `gallery/`, `achievements/` | `compile.py:616-700` — заменить жёсткие `root/"content"/…` на обход зон, как в `_collect_chapters` | `id_registry`, линт-инварианты, тесты компилятора |
| Включить `content/anchors.yaml` и `injects:` | читатель `anchors.yaml` в компиляторе; расширить `pack_manifest@1` полем `injects`; линт-правило «инжект только на объявленный якорь» | ADR (G10, фаза 3); привести схему `anchors@1` и ARCHITECTURE.md к одному виду |
| Видеть пак-главы в графе и changelog | `tools/vn/src/vn/content/graph.py:15` и `release.py:124-139` — добавить зоны `packs/*/chapters` | тест `test_release.py`; `ci/release-manifest.json` перегенерится |

---

## Чего НЕ делать

- **Не писать `api_level` строкой** (`">=1 <2"`) — схема требует объект `{min, below}`, а `additionalProperties: false` не простит и лишних полей. Пример в `docs/ARCHITECTURE.md:3244-3257` невалиден: там ещё и `steam_appid`, `injects`, `state_store`.
- **Не класть `vars.yaml` в главу пака.** Линт зачтёт переменные существующими, компилятор их не эмитит, игра упадёт `NameError` в рантайме. Переменные — только `content/variables/`.
- **Не объявлять персонажей в `packs/<id>/characters/`** — компилятор читает только `content/characters/` и упадёт на `participants`.
- **Не считать `warning: пак … не объявляет глав` поломкой.** Для пака-контейнера (`nsfw`) архив из одного манифеста — норма; строка есть ровно затем, чтобы это не выглядело сбоем (§7.2). А вот пак с главами и без генерата теперь честно падает — не обходите это, а запустите `vn build`.
- **Не полагаться на охранник как на проверку полноты депота.** Он требует хотя бы одну сцену на весь пак, а не по главе: недостающая `ch92` при собранной `ch91` пройдёт молча (§7.2).
- **Не считать `flavors.packs` гейтом.** `public`-сборка сегодня сообщает `nsfw` как установленный и купленный.
- **Не рассчитывать на `owned()` вне Steam.** Провайдер подключается только при живом Steam (`035_platform.rpy:74-75`); в standalone-сборке и в dev-прогонах он всегда `True`, то есть любая «платная» глава видна всем. И не делайте его fail-closed: ошибка `dlc_installed` = `True` по норме G9 (гейт логический, не DRM).
- **Не писать `steam_dlc_appid` в `project.yaml`, а `appid` — в манифест пака.** Поля разные и живут в разных файлах ([39-platforms.md](39-platforms.md) §3).
- **Не полагаться на `fallback_anchor`, `requires.packs`, `lang`, `title_key`** — схема их принимает, код не читает ни одного.
- **Не пытаться управлять загрузкой скриптов пака** через `config.archives` в `init` — Ren'Py индексирует архивы и грузит `.rpyc` до init-фазы (G9). Единственный «жёсткий» путь — `renpy.utter_restart()`, и проект спроектирован так, чтобы он не понадобился.
- **Не переименовывать главу при переносе в пак.** Id неизменяемы (G7), а принадлежность и так определяется расположением — `renames.yaml` тут не нужен.
- **Не искать пак-главы в `vn content graph`, `ci/release-manifest.json` и `docs/CHANGELOG.md`** — они туда не попадают by design текущего кода.
- **Не заводить главу с номером, уже занятым в ядре или другом паке** — коллизия id останавливает сборку целиком; `vn chapter new` о паках не знает и не защитит.

---

## Проверка

```bash
vn pack validate                        # 2 пака, api_level [1, 2) (фасад 1), exit 0
vn content lint                         # схемы всех yaml под packs/ + структура глав
vn build                                # генерат пак-глав в game/generated/scenes/<ch>/
vn build --check                        # CI-режим: «check: генерат свеж»
vn pack build ep_beach                  # -> build/packs/ep_beach.zip (3 файла)
python -c "import zipfile;print([i.filename for i in zipfile.ZipFile('build/packs/ep_beach.zip').infolist()])"
grep -n "VN_PACKS" game/generated/registry/chapters.gen.rpy
vn release validate --flavor public     # проверка #3: manifest.yaml каждого пака флейвора
vn release validate --flavor patron
vn play                                 # глава ch90 в меню с бейджем DLC
python -m pytest tools/vn/tests -q      # 400 passed (RENPY_SDK задан; без него часть контракт-тестов skip)
```

Эталон на 2026-08-08: 2 пака (`ep_beach` с `ch90`, `nsfw` без глав), `VN_PACKS` из двух записей, `build/packs/ep_beach.zip` — 3522 байта / 3 файла, `build/packs/nsfw.zip` — 1 файл плюс строка `warning:` про отсутствие глав.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/content/compile.py:434-514` (`VN_API_LEVEL`, `_collect_packs`, `_semver_in_range`, `_collect_chapters`), `../../tools/vn/src/vn/cli.py:1568-1639` (группа `vn pack`), `../../tools/vn/src/vn/content/scenes.py:276-296` (эмиттер `VN_CHAPTERS`/`VN_PACKS`) и `:324-339` (шаблон `chapter_select`), `../../game/framework/00_core/030_flow.rpy:9,63-88` (`API_LEVEL`, `_PackRegistry`), `../../tools/schemas/pack_manifest@1.schema.json`, `../../packs/README.md`, `../adr/0014-platform-services.md` (ownership-провайдер, `steam_dlc_appid`), `../ARCHITECTURE.md` §6.7-6.8 (**целевой**, не описание построенного) |
| **Не трогать** | `game/generated/**` — весь генерат пак-глав (`.gitignore:2`); `build/packs/**` — артефакт `vn pack build` (`.gitignore:20`); `content/anchors.yaml` и `content/flags.yaml` — файлы обязаны существовать, но наполнять их бессмысленно до появления читателей |
| **Зависимости (что ломается ниже по течению)** | Смена `VN_API_LEVEL` или `API_LEVEL` → все манифесты паков надо перепроверить (`vn build` падает целиком, а не отключает пак). Смена ключей `VN_PACKS` → `_PackRegistry.installed()`, `chapter_select.gen.rpy:21`, `080_achievements.rpy:40-41`, `090_gallery.rpy:44`. Правка `flavors.<f>.packs` → **видимость контента в рантайме** (§6), а не только состав артефактов. Перенос главы между зонами → `pack` в `VN_CHAPTERS`, бейдж DLC, `release.py:342-346`. Добавление пака → `release.py` гейт #3 и `vn release validate` обоих флейворов |
| **Валидация** | `vn pack validate` → `vn content lint` → `vn build` → `vn build --check` → `vn pack build <id>` + ручная проверка содержимого zip → `vn release validate --flavor public` → `python -m pytest tools/vn/tests -q` |
| **Частые ошибки** | 1) Верить `docs/ARCHITECTURE.md` §6.7 как описанию реализованного: `api_level` там строкой, поля `steam_appid`/`injects`/`state_store` схемой запрещены (App ID DLC называется `steam_dlc_appid`), `refresh_ownership()`/`installed_versions()`/`owned_ids()` не существуют. 2) Считать, что `owned()` ничего не фильтрует: с ADR-0014 провайдер подключён (`035_platform.rpy:75`) и под Steam честно даёт `False` — но только под Steam и только для пака с `steam_dlc_appid`. 3) Класть контент в зоны пака, которые компилятор не читает (`characters/`, `vars.yaml`, `loc/`, `gallery/`, `achievements/`) — §1.1. 4) Читать охранник `pack build` как «ноль сцен = ошибка»: ошибка — только «главы объявлены, а генерата нет»; пак-контейнер без глав собирается штатно (`cli.py:1617-1626`, §7.2). 5) Ожидать, что `flavors.packs` исключит пак из сборки — не исключает |
