# 29. Сборка и релиз

> **Статус подсистемы:** IMPLEMENTED — путь «тег `v*` → гейт → дистрибутивы обоих флейворов → GitHub Release» работает целиком и обкатан четырьмя реальными релизами; **но** из четырёх заявленных рычагов флейвора реально гейтят только два (`nsfw`, `watermark` + `--patron-token`), `packs` и `early_content` не читает никто, кэш `.rpyc` ключуется версией без флейвора, а из Steam-поставки автоматизирована подготовка (VDF + раскладка депотов, `vn release steam`) — сам аплоад ручной, каналов dev/beta/release нет.
> **Отвечает на вопрос:** «Глава готова. Что запустить, в каком порядке, что проверить и как выпустить сборку, которую не стыдно отдать игроку?»

Весь релизный путь живёт в двух файлах: `../../tools/vn/src/vn/release.py` (629 строк — гейт, флейворы, build-info, changelog, бюджеты, Steam-поставка) и группы `package` / `release` / `pack` в `../../tools/vn/src/vn/cli.py`. CI — тонкая обёртка: `.github/workflows/release.yml` не содержит ни одной релизной проверки собственного изготовления, он вызывает `vn release build`. Поэтому всё, что делает CI на теге, воспроизводится локально одной командой.

## Быстрый ответ

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"   # без него package/release не работают

# Проверить, готов ли репозиторий к релизу (ничего не пишет, ~30 c)
vn release validate --flavor public
vn release validate --flavor patron

# Собрать флейвор целиком (гейт + дистрибутивы) — то же, что делает CI на теге
vn release build --flavor public --package win
#   -> build/dist/0.1.4-public/vn-0.1.4+<sha>-win.zip + build-info.json

# Выпустить: три файла в коммите, потом тег
vn release changelog                  # docs/CHANGELOG.md + ci/release-manifest.json
#   вручную: version в project.yaml + проза в CHANGELOG
git commit -m "release: 0.1.5 — <итог одной строкой>"
git tag v0.1.5 && git push --follow-tags     # -> .github/workflows/release.yml
```

**Главное правило:** тег `v<X.Y.Z>` обязан посимвольно совпадать с `project.yaml: version`, иначе `release.yml:47-54` рубит сборку на первом шаге, до установки SDK.

---

## 1. Четыре команды сборки и чем они отличаются

| Команда | Что делает | Что на выходе | Флейвор |
|---|---|---|---|
| `vn build` | lint → ассеты → компилятор → `vn loc import` → бюджеты (`cli.py:84-153`) | `game/generated/`, `game/assets/`, `game/tl/` | нет |
| `vn package` | `vn build` → перенос `.rpyc` → `renpy compile` → `launcher distribute` → снимок `.rpyc` (`cli.py:279-370`) | `build/dist/<version>/*.zip` | **нет — опасно, см. §3** |
| `vn release build --flavor <f>` | `vn build` → гейт → `build_id.json` → `vn package` → `build-info.json` (`cli.py:1508-1562`) | `build/dist/<version>-<f>/` | да |
| `vn pack build <id>` | зип генерата глав пака + манифест (`cli.py:1600-1628`) | `build/packs/<id>.zip` | — см. [30-packs-and-dlc.md](30-packs-and-dlc.md) |
| `vn release steam --flavor <f>` | VDF из `ci/steam/app_build.vdf.tmpl` + распаковка зипов distribute под депоты (`cli.py:1819-1852`) | `build/steam/app_build_<f>.vdf` + `build/steam/content/<f>/<platform>/` | да — см. §12 и [39-platforms.md](39-platforms.md) |

Сам конвейер `content/` → `game/generated/` разобран в [08-content-pipeline.md](08-content-pipeline.md), ассеты — в [16-assets.md](16-assets.md); здесь только то, что происходит **после** зелёной сборки.

**Exit-коды `vn`** (`cli.py:46-47`): `0` — успех; `1` — ошибка проверки/сборки (всегда с сообщением `ошибка: …` на stderr, `cli.py:22-24`); `2` — usage error от click; `3` — «команда появится в фазе N» (`cli.py:34-38`).

---

## 2. Флейворы: `public` и `patron` — IMPLEMENTED (наполовину)

Объявлены в `../../project.yaml:12-22`, схема — `tools/schemas/project@1.schema.json` (`packs` и `nsfw` обязательны, `early_content`/`watermark` опциональны с дефолтом `false`).

| Ключ | `public` | `patron` | Кто читает | Статус |
|---|---|---|---|---|
| `packs` | `[ep_beach]` | `[ep_beach, nsfw]` | `release.py:249` → `build_info.packs`; гейт проверяет наличие `packs/<id>/manifest.yaml` (`release.py:305-309`) | **NOT IMPLEMENTED как гейт** |
| `nsfw` | `false` | `true` | `release.py:250,254` → исключение ассетов + рантайм-гейты | IMPLEMENTED |
| `early_content` | `false` | `true` | `release.py:251` → `vn_build.early_content` | **NOT IMPLEMENTED** — ноль потребителей |
| `watermark` | `false` | `true` | `release.py:252` → overlay-экран | IMPLEMENTED |

### 2.1 Что реально работает — три механизма

**1. Исключение NSFW-ассетов из дистрибутива (build-time).** `nsfw_exclude_globs()` (`release.py:192-203`) обходит **фактические** каталоги: для каждого `game/assets/<cat>/`, где есть подпапка `nsfw/`, добавляет глоб `game/assets/<cat>/nsfw/**`. Список кладётся в `build_id.json: exclude`, а `game/options.rpy:44-51` при distribute применяет его через `build.classify(_glob, None)`.

Честно: **сегодня это no-op.** Категории в `game/assets/` — `bg cg mov spr ui`, подпапки `nsfw/` нет ни в одной, поэтому в обоих реально собранных `build/dist/0.1.0-{public,patron}/build-info.json` поле `"exclude": []`. Механизм покрыт только юнит-тестом на синтетических каталогах (`tools/vn/tests/test_release.py`). Конвенция размещения зафиксирована в комментарии `packs/nsfw/manifest.yaml` (`assets_src/png/cg/nsfw/**`).

**2. Рантайм-гейты по `nsfw` (логические).** `game/framework/00_core/060_build_info.rpy:10-40` создаёт `init -985 python in vn_build` и читает `build_id.json` через `renpy.open_file`. Потребители:

- `080_achievements.rpy:37-41` — достижение с `nsfw: true` не выдаётся в SFW-сборке;
- `090_gallery.rpy:40-44` — то же для элементов и целых категорий галереи ([15-gallery.md](15-gallery.md));
- `070_crash.rpy:57-60` — `build_id`/`flavor` штампуются в crash-репорт ([28-debugging.md](28-debugging.md)).

**3. Вотермарка.** Весь механизм — 17 строк в `game/framework/20_ui/screens/build_overlay.rpy`:

```renpy
init python:
    if vn_build.watermark:
        config.overlay_screens.append("vn_build_overlay")
```

Подпись рисуется полупрозрачным текстом 12 px в правом нижнем углу, `zorder 1090`. Её содержимое — `060_build_info.rpy:42-45`: `build_id` плюс **метка получателя** `patron_tag`, если она задана (`build_id · <8 hex>`).

**Токен получателя в дистрибутив больше не едет (ADR-0011).** Флаг `--patron-token` (`cli.py:1510-1511`) — это по-прежнему вход команды, но в `build_id.json` пишется односторонняя производная: `patron_tag(token)` = `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex (`release.py:206-227`, поле собирается в `release.py:253`). Рантайм читает готовую метку и никакого трекинга не делает. В CI токен подставляется из `secrets.PATRON_TOKEN` и только для patron-ноги матрицы (`release.yml:79-87`).

Сопоставить утёкшую сборку с получателем владелец может сам — метка детерминирована:

```bash
python -c "import hashlib,sys; print(hashlib.blake2s(sys.argv[1].encode(), digest_size=4, person=b'vnpatron').hexdigest())" tok_demo42
# caf5afd4
```

**Требование к процессу, вытекающее из короткой метки:** токен получателя обязан быть случайным (`secrets.token_hex(16)` и подобное). Короткий низкоэнтропийный токен подбирается по 8-символьной метке перебором. Подробности и правовая грань — [33-security-and-legal.md](33-security-and-legal.md) §3.

### 2.2 Что объявлено, но не работает

**`flavors.<f>.packs` ничего не гейтит.** `vn_build.packs` заполняется и не читается никем. Установленность пака определяет `pack_registry.installed()` (`030_flow.rpy:76-77`) по словарю `VN_PACKS`, а компилятор эмитит туда **все** паки из `packs/` независимо от флейвора. Живой генерат:

```renpy
define VN_PACKS = {'ep_beach': {'kind': 'dlc', 'version': '1.0.0'}, 'nsfw': {'kind': 'dlc', 'version': '0.1.0'}}
```

То есть `public`-сборка сообщает, что пак `nsfw` установлен и принадлежит игроку. Безвредно ровно потому, что `packs/nsfw/chapters/` содержит один `.gitkeep`. Как только туда попадёт глава — она уедет в публичную сборку. Обходной путь на сегодня: держать NSFW-материал ассетами в `nsfw/`-подпапках (механизм 1 работает), а не отдельным паком со сценами.

**`early_content` не читает никто.** Значение вычисляется, валидируется схемой и выставляется в `vn_build.early_content` — и на этом всё: grep по `game/` даёт только само объявление в `060_build_info.rpy`. Если ранний доступ нужен как гейт — писать потребителя придётся с нуля.

Бизнес-контекст флейворов (кому что продаётся) — [01-project-overview.md](01-project-overview.md) §2.

---

## 3. `game/build_id.json` — паспорт сборки

**Кто пишет.** `compute_build_info()` (`release.py:230-255`) собирает документ `build_info@2`, `write_build_info()` (`release.py:258-267`) валидирует его схемой `tools/schemas/build_info@2.schema.json` (`additionalProperties: false`, все 12 полей обязательны) и пишет в `game/build_id.json`. `clear_build_info()` (`release.py:270`) удаляет файл в блоке `finally` (`cli.py:1558-1560`) — **файл существует только на время distribute**. Он в `.gitignore:7-8`.

Живой документ (`compute_build_info(root, "patron", patron_token="tok_demo42")` на HEAD `dd1cb3e`):

```json
{"build_id": "0.1.4+dd1cb3e.patron.202608081905", "built_at": "2026-08-08T19:05:31+00:00",
 "early_content": true, "exclude": [], "flavor": "patron", "nsfw": true,
 "packs": ["ep_beach", "nsfw"], "patron_tag": "caf5afd4", "schema": "build_info@2",
 "sha": "dd1cb3e", "version": "0.1.4", "watermark": true}
```

**Версия схемы бампнута с `@1` на `@2` (ADR-0011):** поле `patron_token` (сам секрет) заменено на `patron_tag` (невосстановимая метка). `build_info@1.schema.json` остался в реестре с пометкой «УСТАРЕЛА» — чтобы читались артефакты сборок до 0.1.5. Артефакт `build/dist/0.1.0-patron/build-info.json`, который лежит на диске, — как раз `build_info@1` и содержит `"patron_token": "tok_demo42"` открытым текстом; это исторический документ, а не образец.

Формат `build_id` — `{version}+{sha}.{flavor}.{YYYYMMDDHHMM}` в UTC (`release.py:246`).

**Кто читает.** Двое, в разное время:

| Читатель | Когда | Что берёт |
|---|---|---|
| `game/options.rpy:44-51` | во время `launcher distribute` | только `exclude` → `build.classify(glob, None)` |
| `060_build_info.rpy:26-40` | при каждом старте игры | `flavor`, `build_id`, `version`, `packs`, `nsfw`, `early_content`, `watermark`, `patron_tag` |

**Файла нет → игра идёт как `dev`.** Дефолты (`060_build_info.rpy:14-23`): `flavor="dev"`, `build_id="dev"`, `nsfw=True`, `early_content=True`, `watermark=False`. Чтение обёрнуто в `try/except Exception` — битый или отсутствующий файл не роняет старт. Это именно то, что нужно в рабочем чекауте: разработчик видит весь контент и не таскает чужую вотермарку.

**Грабля с ценой в деньги.** Из этих же дефолтов следует: архив, собранный голым `vn package` (без `--dest-suffix`, то есть без флейвора), **не содержит `game/build_id.json`** — проверено на реальном `build/dist/0.1.0/vn-0.1.0+193f6b4-win.zip`, файла внутри нет. Такой билд у игрока стартует как `dev`: NSFW-достижения и NSFW-галерея открыты, ранний контент открыт, вотермарки нет, NSFW-ассеты не исключены. **Голый `vn package` — это инструмент отладки дистрибуции, а не способ собрать сборку для раздачи.** Для раздачи — только `vn release build --flavor <f>`.

---

## 4. `vn release validate --flavor <f>` — предрелизный гейт

Точка входа `cli.py:1492-1505`, логика — `validate_release()` (`release.py:276-481`). Возвращает список пар `(PASS|WARN|FAIL, строка)`; `ok` становится `False` **на любом FAIL**, WARN не валит никогда. При FAIL — `_fail("release validate --flavor <f>: есть FAIL")`, **exit 1**.

Философия зафиксирована в докстринге (`release.py:278-279`): «своих правил у релиза нет» — гейт агрегирует уже существующие проверки конвейера, чтобы не расходиться с `vn build`.

### 4.1 Полный список проверок, в порядке выполнения

| # | Проверка | Код | FAIL когда |
|---|---|---|---|
| 1 | `project.yaml` валиден по схеме `project@1` | `release.py:291-295` | любая ошибка схемы |
| 2 | Флейвор описан в `project.yaml` | `release.py:297-303` | нет такого флейвора — **и гейт немедленно возвращается**, остальные 17 проверок не выполняются |
| 3 | На каждый пак флейвора есть `packs/<id>/manifest.yaml` | `release.py:305-309` | манифест отсутствует |
| 4 | `vn content lint` — 0 ошибок | `release.py:311-315` | есть ошибки линта (34 правила, [08-content-pipeline.md](08-content-pipeline.md) §7) |
| 5 | Шрифты UI — не LFS-указатели | `release.py:321-330`, реализация `doctor.py:50-66` | хоть один `.ttf/.otf` в `game/fonts/` не начинается с сигнатуры sfnt. WARN, если `game/fonts` пуст |
| 6 | `game/assets` свежи (`build_assets(check=True)`) | `release.py:332-338` | есть ошибки или несвежие выходы |
| 7 | Собранные видео-лупы валидны + бюджет на файл | `release.py:340-349` | ошибка валидации `.webm`; предупреждения → WARN |
| 8 | Генерат свеж (`compile_content(check=True)`) | `release.py:351-359` | несвежие выходы или `CompileError` |
| 9 | Бюджеты G19 | `release.py:361-363` | см. §8 |
| 10 | Провенанс ассетов согласован | `release.py:365-373` | разрыв цепочки; предупреждения → WARN |
| 11 | DAZ-декларации рендеров | `release.py:375-384` | ошибка в `*.render.yaml`; неотрендеренные выходы → WARN |
| 12 | VaM-декларации сцен | `release.py:386-395` | ошибка; **строки нет вовсе, если деклараций нет** |
| 13 | Sims4-декларации сцен | `release.py:397-406` | то же |
| 14 | Покрытие переводов ≥ `loc/loc.yaml: release_coverage_min` | `release.py:408-434` | язык ниже порога (сейчас 0.98). Языки с `synthetic: true` (pseudo) исключаются по `game/tl/<lang>/language.json`. Проверка пропускается целиком, если покрытия или порога нет |
| 15 | Реестр лицензий ассетов | `release.py:436-445` | нарушение; **строки нет, если деклараций 0** |
| 16 | Хранилище сырцов | `release.py:447-460` | локально изменённые и не запушенные сырцы (G14); недоступное хранилище → WARN |
| 17 | `ci/release-manifest.json` версия == `project.yaml` | `release.py:462-470` | **никогда** — только WARN |
| 18 | git sha получен | `release.py:472-473` | **никогда** — WARN при `nogit` |
| 19 | Есть фикстуры сейв-корпуса | `release.py:475-479` | **никогда** — WARN при нуле фикстур (сейчас их 2, см. §4.2) |

**19 проверок в коде, но строк на экране меньше:** №12, 13 и 15 молчат, когда нечего проверять. Сегодня это ровно так.

### 4.2 Реальный вывод (2026-08-08, HEAD `dd1cb3e`)

```
$ vn release validate --flavor public
 PASS  project.yaml: схема валидна
 PASS  флейвор public: packs=['ep_beach'], nsfw=False, early=False
 PASS  пак ep_beach: manifest.yaml на месте
 PASS  lint: 0 ошибок, 0 предупреждений
 PASS  шрифты UI: 3/3 материализованы
 PASS  ассеты: свежи
 PASS  видео: собранные лупы валидны
 PASS  генерат: свеж
 PASS  бюджеты G19: в рамках
 PASS  провенанс: 0 цепочек согласованы
 PASS  DAZ-декларации: 0 проверено
 PASS  покрытие переводов: все языки ≥ 98%
 PASS  хранилище сырцов: локальные копии согласованы
 PASS  release-manifest: версия 0.1.4 == project.yaml
 PASS  git sha: dd1cb3e
 PASS  сейв-корпус: 2 фикстур
release validate: OK (флейвор public)
```

16 строк, exit 0. У `--flavor patron` их 17 — добавляется `пак nsfw: manifest.yaml на месте`.

Опечатка в имени флейвора обрывает гейт на второй строке:

```
$ vn release validate --flavor steam
 PASS  project.yaml: схема валидна
 FAIL  флейвор 'steam' не описан в project.yaml (есть: patron, public)
ошибка: release validate --flavor steam: есть FAIL      # exit 1
```

### 4.3 Чего гейт НЕ проверяет

Пробелы реальные, знать их обязательно:

- **пин `renpy_sdk`** — только `vn doctor` (`doctor.py:124-140`);
- **`save_schema`** — ни соответствия миграций, ни бампа; ловится лишь косвенно через `vn save corpus`;
- **`cold_start_s`** — живёт исключительно внутри `vn test smoke` (`cli.py:1386-1392`), которого релизный workflow не запускает; **релиз может уехать за бюджет холодного старта**;
- **движковый `renpy … . lint`** — только в `ci.yml:73` и `canary.yml:49`;
- **smoke-прохождение** — только nightly/canary ([27-testing.md](27-testing.md));
- **`min_tools`** из `project.yaml:4` — не сравнивается ни с чем.

---

## 5. `vn release build --flavor <f>` — полная последовательность

`cli.py:1508-1562`. Опции: `--flavor` (обязательна), `--patron-token`, `--package` (можно несколько, по умолчанию `("win",)`), `--timeout` (900 с).

1. **`vn build` — ДО гейта** (`cli.py:1529-1530`, `ctx.invoke(build, check=False, profile="full")`).
2. **Гейт** `validate_release(root, flavor)` (§4). Любой FAIL → `_fail("release build --flavor <f>: гейт не пройден")`, exit 1.
3. **`compute_build_info` + `write_build_info`** → `game/build_id.json` (`cli.py:1539-1543`).
4. **Уведомления о сторонних лицензиях**: `docs/licenses/THIRD-PARTY-NOTICES.md` копируется в `game/THIRD-PARTY-NOTICES.md` (`cli.py:1545-1548`). Файл существует; в собранном `0.1.0-public` он присутствует внутри архива — проверено.
5. Печать `build-id: …` и, если `exclude` непуст, `(исключено: …)`.
6. **`vn package`** с `dest_suffix=f"-{flavor}"` (`cli.py:1552-1553`) — см. §6. Внутри он **ещё раз** прогоняет `vn build`.
7. **`build-info.json`** пишется в `build/dist/<version>-<flavor>/` (`cli.py:1554-1557`) — обязательно после package, потому что package чистит каталог назначения.
8. **`finally`** (`cli.py:1558-1560`): удаляются `game/build_id.json` и `game/THIRD-PARTY-NOTICES.md` — даже при падении. Рабочий чекаут не остаётся с чужим флейвором.
9. `release build: OK — <build_id> -> build/dist/<version>-<flavor>/`.

### 5.1 Почему сборка идёт ДО гейта

Комментарий в коде (`cli.py:1526-1528`) объясняет ровно это: в свежем чекауте CI **генерата нет вовсе** — `game/generated/` в `.gitignore:2`. Проверка №8 «генерат свеж» валила бы каждый релиз. Второй, менее очевидный аргумент из того же комментария: так гейт проверяет ровно то состояние, которое уедет в дистрибутив, а не предыдущее.

Регрессию именно этого класса ловит nightly: он делает `rm -rf game/generated` и после этого гоняет оба флейвора (`nightly.yml:70-74`).

Плата за схему — `vn build` выполняется дважды (шаг 1 и внутри package). На прогретом кэше второй прогон почти бесплатен; в холодном CI это заметные секунды.

### 5.2 Артефакты и разбор имени архива

Реально лежит на диске (`build/` в `.gitignore:20`, поэтому у каждого своё):

| Путь | Размер | Чем собрано |
|---|---|---|
| `build/dist/0.1.0-public/vn-0.1.0+94970b3-win.zip` + `build-info.json` | 31 489 064 Б | `vn release build --flavor public` |
| `build/dist/0.1.0-patron/vn-0.1.0+d020c37-win.zip` + `build-info.json` | 30 865 170 Б | `--flavor patron`; это ещё `build_info@1`, с `patron_token` внутри (до ADR-0011) |
| `build/dist/0.1.0/vn-0.1.0+193f6b4-win.zip` | 30 829 470 Б | голый `vn package` — **без `build-info.json` и без `build_id.json` внутри** |

Разбор `vn-0.1.0+193f6b4-win.zip`:

| Часть | Откуда |
|---|---|
| `vn` | `build.name = "vn"` (`game/options.rpy:14`) |
| `0.1.0+193f6b4` | `config.version` из `game/generated/version.gen.rpy:8`; эмиттер `tools/vn/src/vn/content/compile.py:82-87` склеивает `project.yaml: version` с `git rev-parse --short HEAD` (`repo.py:34-43`) |
| `win` | значение `--package`, переданное в `launcher distribute` |
| `.zip` | формат, который `launcher distribute` даёт для `win` |

Проект **не задаёт** `build.directory_name` и `build.version`, поэтому имя целиком выводится движком из `build.name` и `config.version`.

**Флейвора в имени архива нет.** `public` и `patron` одной версии отличаются только вкомпилированным git-sha и каталогом-родителем `<version>-<flavor>/`. Перепутать файлы на диске легко — не переименовывайте их и не складывайте в одну папку.

**Про `+sha` в версии:** генерат привязан к коммиту, любая перекомпиляция после нового коммита меняет `config.version`, а значит и имя архива. Собранный из чекаута тега архив воспроизводим по имени (та же версия, тот же sha).

---

## 6. `vn package` — как вызывается Ren'Py SDK

`cli.py:279-370`. Опции: `--package` (multiple, дефолт `win`; help: «Целевые пакеты launcher distribute (win/linux/mac/market)»), `--timeout` (900), `--dest-suffix` (**скрытая**, ей пользуется только `vn release build`).

**Поиск SDK — только через переменную окружения.** `doctor.sdk_path()` (`doctor.py:24-30`) читает `RENPY_SDK` и принимает путь, лишь если `<RENPY_SDK>/renpy.py` — файл. Ни PATH, ни ключа в конфиге, ни автопоиска. Нет → `_fail("Ren'Py SDK не найден (RENPY_SDK)")`. Исполняемый файл: `renpy.exe` на `win32`, иначе `renpy.sh` (`cli.py:337`).

Шаги:

1. `ctx.invoke(build, check=False, profile="full")` — генерат `.rpy` обязан существовать до восстановления `.rpyc` (`cli.py:299-301`).
2. Перенос `.rpyc` прошлого релиза (`cli.py:303-334`) — §7.
3. `subprocess.run([exe, root, "compile"], capture_output=True, timeout=timeout_s)` (`cli.py:338-341`). Ненулевой код → `_fail("renpy compile упал:\n…")` с хвостами stdout (1500 симв.) и stderr (800).
4. Дистрибуция (`cli.py:344-355`): `dest = build/dist/<version><dest_suffix>`, каталог **удаляется целиком** перед сборкой («старые архивы не должны вкладываться в новые»), затем
   ```python
   cmd = [str(exe), str(sdk / "launcher"), "distribute", "--dest", str(dest)]
   for p in packages: cmd += ["--package", p]
   cmd.append(str(root))
   ```
5. Снимок `.rpyc` нового релиза (`cli.py:357-369`) — §7.
6. `package: OK — <имена файлов в dest>`.

**Какие пакеты доступны.** Ровно те, что понимает `launcher distribute`; CLI значение не валидирует и передаёт как есть. CI собирает `--package win --package linux --package mac` (`release.yml:83`). **Android/rapt не подключён** — ни `rapt`, ни `.aab`, ни `.apk` в `tools/` не встречаются (NOT IMPLEMENTED).

**`--timeout` покрывает оба subprocess-вызова** (компиляцию и дистрибуцию) по отдельности. Дефолт 900 с хватает локально; CI ставит 1800 (`release.yml:83`), потому что три платформы сразу.

**Что не уезжает в дистрибутив** (`game/options.rpy:13-51`, всё через `build.classify(…, None)`): исходные зоны `tools/** content/** assets_src/** loc/** docs/** ci/** packs/** build/** .vncache/** .git/**`, дотфайлы, `CODEOWNERS`, `README.md`, `project.yaml`, `.vnstorage.yaml`, `hdrs.tmp`, `log.txt`, `traceback.txt`, `errors.txt`; плюс `game/framework/90_debug/**`, `game/generated/qa/**`, `game/generated/manifest.json`; плюс каждый `game/tl/<code>/**`, у которого в `language.json` стоит `"synthetic": true` (то есть pseudo, [14-localization.md](14-localization.md)); плюс глобы флейвора. Проверено на архивах: в `0.1.0-public` и `0.1.0-patron` нет ни `90_debug/`, ни `tl/pseudo/`.

**`.rpa`-архивов нет — и это норма, а не недоделка.** Вызова `build.archive(...)` нет нигде в `game/`; ассеты едут россыпью — `../ARCHITECTURE.md` §2.4 (`:943`) фиксирует это осознанно: Steam дельта-патчит отдельные файлы, монолитный `.rpa` при правке одного спрайта перекачивался бы игроками целиком, а защиты упаковка не добавляет. Тематические `.rpa` (`archive_spr.rpa` и т. д.) — только опция mobile-поставки фазы 3; их появление в desktop-дистрибутиве — осознанное решение с ADR. Инвариант закреплён гард-тестом: `test_options_rpy_ships_assets_loose_without_rpa` (`tools/vn/tests/test_release.py:250`) краснеет на любом `build.archive` в `game/options.rpy`.

---

## 7. `.rpyc` как релизный артефакт (G6)

**Зачем.** Ren'Py хранит в сейвах и в журнале rollback *имена стейтментов* (файл + версия + серийный номер). При перекомпиляции изменённого `.rpy` имена неизменившихся стейтментов сохраняются **только если рядом лежит старый `.rpyc`**. Поэтому `.rpyc` для нас — не мусор, а релизный артефакт: без него старые сейвы игроков перестают попадать «в то же место» истории.

**Восстановление** (`cli.py:303-334`):

- каталоги в `build/rpyc-cache/` сортируются функцией `_semver_key` (`cli.py:307-311`: `"0.1.4"` → `(0,1,4)`; нечисловое имя → `(0,)`), берётся **самый старший по версии**, а не самый свежий по времени;
- для каждого `*.rpyc`: цель `game/<rel>`; если рядом нет одноимённого `.rpy`, пробуется `game/generated/<rel>` (legacy-раскладка кэша);
- копирование **с перезаписью** — канонический носитель имён это кэш релиза, а не локальные `.rpyc`;
- `restored == 0` при существующем кэше → `_fail("rpyc-перенос: кэш … есть, но не восстановлено ни одного .rpyc — save-совместимость под угрозой (G6), сборка остановлена")`;
- кэша нет → печатается `rpyc-перенос: кэша прошлых релизов нет (первый релиз)` и сборка идёт дальше.

**Снимок** (`cli.py:357-369`): после distribute `build/rpyc-cache/<version>/` очищается и туда копируются **все** `.rpyc` из-под `game/` — не только из `generated/`, потому что метки framework тоже попадают в сейвы и rollback (`cli.py:306`).

Реальные кэши на диске — два: `build/rpyc-cache/0.1.0/` (**48 файлов**, 159 395 Б) и `build/rpyc-cache/0.1.4/` (**52 файла**, 190 269 Б). Состав свежего: `framework/00_core/*` (11 с учётом `engine_compat/`), `framework/20_ui/*` (9), `framework/90_debug/*` (2), `generated/registry/*` (10), `generated/scenes/ch01|ch90/*` (4), `generated/screens|state|version` (5), `gui.rpyc`, `options.rpyc`, `tl/{de,en,pseudo}/*` (9).

**Проблема: кэш ключуется версией, а не флейвором.** `save_dir = cache_root / version` (`cli.py:358`). Оба флейвора одной версии пишут в один каталог — кто собрался последним, тот и записал. Локально это значит, что после `release build --flavor patron` кэш 0.1.4 содержит patron-компиляцию, и следующий public-релиз восстановится из неё. Практических расхождений сегодня нет (исключение работает на уровне `build.classify`, а не на уровне набора `.rpy`), но гарантий тоже нет. CI обходит это своим слоем: `actions/cache` ключуется по флейвору — `key: rpyc-${{ matrix.flavor }}-${{ github.ref_name }}`, `restore-keys: rpyc-${{ matrix.flavor }}-` (`release.yml:71-76`).

**Второй наблюдаемый факт:** в локальном `build/rpyc-cache/` лежат `0.1.0` и `0.1.4`; версии 0.1.2–0.1.3 собирались в CI, не на этой машине. Восстановление берёт старший по semver каталог, то есть локально это `0.1.4` — но полной линии релизов на машине всё равно нет, настоящий носитель — кэш GitHub Actions.

**Отдельный, не путать: линия имён сейв-корпуса.** `ci/fixtures/rpyc-line/` — **52 `.rpyc`** (183,9 КБ), **единственные `.rpyc` в git** (негативное правило `.gitignore:14`). Линия пересобрана 2026-08-08: было 34 файла, снятых ещё до появления галереи, ачивок и генерируемых UI-панелей. Ими управляют `_rpyc_line_restore` / `_rpyc_line_snapshot` (`cli.py:1130-1164`) вокруг `vn save corpus`, чтобы фикстуры в `ci/fixtures/saves/` (сейчас **две** — `schema1-demo.save` и `schema2-demo.save`) грузились детерминированно на любой машине. Подробности — [27-testing.md](27-testing.md).

**Регрессионной джобы `rpyc-compat` не существует** (`../ARCHITECTURE.md:3508` называет её обязательным release-гейтом, скелет джобы — `:3602`). Ничто не проверяет, что перенос имён реально работает: нет ни workflow, ни флага. NOT IMPLEMENTED.

---

## 8. Версионирование

| Поле | Где | Правило | Кто проверяет |
|---|---|---|---|
| `version` | `project.yaml:2` | semver: патч — фиксы, **новая глава = minor**, мажор — сезон/сеттинг | схема `^\d+\.\d+\.\d+$`; `release.yml:47-54` сверяет с тегом (hard fail); `release.py:462-470` сверяет с `ci/release-manifest.json` (**только WARN**) |
| `save_schema` | `project.yaml:3` | целое, бампает tech-lead при несовместимом изменении vars | схема `integer, minimum: 1`. Эмитится как `define vn_build_save_schema` в `game/generated/state/defaults.gen.rpy`; сравнение и миграции — `020_state.rpy:83-107`. **В гейте проверки нет** |
| `min_tools` | `project.yaml:4` | минимальная версия `vn` для дерева контента | **никто** — сравнения с `vn.__version__` (`0.1.0`) в коде нет |
| `renpy_sdk` | `project.yaml:5` | пин SDK (G18); апгрейд — отдельным PR с прогоном canary | только `vn doctor` (`doctor.py:124-140`). Продублирован руками как `RENPY_VERSION` в `ci.yml:13`, `nightly.yml:12`, `release.yml:19` — **автопроверки согласованности нет** |
| `config.version` | генерат | `{version}+{git-short-sha}` (`compile.py:82-87`) | это, а не `build_id`, даёт имя архиву |
| версия пака | `packs/<id>/manifest.yaml` | `^\d+\.\d+\.\d+$` | связи «бампнул ядро → бампни пак» нет |
| версия `vn` | `tools/vn/pyproject.toml` и `tools/vn/src/vn/__init__.py:3` | `0.1.0`, продублирована руками | — |

**Версия игры и версия тулинга независимы.** Игра — `0.1.4`, `vn --version` — `0.1.0`. Это не рассинхрон, это два разных счётчика.

**Pre-release-теги невозможны.** Схема `project@1` требует `version` строго `^\d+\.\d+\.\d+$`, а гейт тега требует точного совпадения: `v1.0.0-rc1` не пройдёт ни там, ни там. Бета-канал из `../ARCHITECTURE.md` сегодня непредставим — NOT IMPLEMENTED.

**Бамп `save_schema` — точка невозврата.** Игрок, который сохранился на новой схеме, не сможет играть на старой сборке: `after_load` увидит `_loaded_schema > _target_schema`, вызовет `renpy.block_rollback()`, покажет `ui.flow.save_from_newer` и сделает `renpy.full_restart()` (`020_state.rpy:83-93`). Понижать `save_schema` нельзя никогда, откатывать релиз с бампом — см. §12.

Ветки, теги и формат коммитов — [04-development-workflow.md](04-development-workflow.md) §3.

---

## 9. Бюджеты G19

Единственная реализация — `budget_failures()` (`release.py:29-54`), читает `project.yaml: budgets` (`:6-11`).

| Бюджет | Значение | Что меряется | Текущий факт |
|---|---|---|---|
| `assets_total_mb` | 500 | `game/assets/` | 0,14 МБ |
| `generated_total_kb` | 2048 | `game/generated/` | 73 КБ |
| `video_total_mb` | 300 | `game/assets/mov/` | 0,006 МБ |
| `video_file_mb` | 40 | каждый `mov/**/*.webm` | 1 файл |
| `cold_start_s` | 30 | init → первая интеракция | **не в `budget_failures`** |

**Где проверяются первые четыре:** `_check_budgets()` в `vn build` — и в `--check`, и в полном режиме (`cli.py:142`, `:152`, реализация `cli.py:172-180`; сообщения с префиксом `бюджет: …`, затем `_fail("бюджеты G19 превышены (project.yaml: budgets)")`) — и проверка №9 релизного гейта (`release.py:361`). Одна реализация на оба пути: гейт не может разойтись со сборкой.

`video_file_mb` дополнительно передаётся в `videomod.validate_all(root, file_budget_mb=…)` (`release.py:342-343`), поэтому перевес одного `.webm` даёт **две** разные строки — в проверке №7 и в №9. Это не баг, просто не пугайтесь дубля.

**`cold_start_s` — исключение.** Он проверяется только внутри `vn test smoke` (`cli.py:1386-1392`: `_fail(f"cold start {cold:.2f} c > бюджета {budget} c (G19)")`), который гоняют nightly и canary, но **не** `ci.yml` и **не** релизный workflow. Релиз может уехать за бюджет холодного старта. Комментарий `project.yaml:9` даёт ориентиры: CI-раннер на llvmpipe ~14 с, RTX ~1 с.

**Что делать при превышении:**

| Бюджет | Первое действие |
|---|---|
| `assets_total_mb` | `vn assets status`; лишние выходы удаляются как осиротевшие при `vn assets build` ([16-assets.md](16-assets.md) §6) |
| `video_total_mb` / `video_file_mb` | поднять `crf` или укоротить луп ([21-video-generation.md](21-video-generation.md)); менять пресет, а не бюджет |
| `generated_total_kb` | реальная причина — рост числа сцен; бюджет поднимается осознанно, вместе с ADR |
| `cold_start_s` | `vn test smoke --picks 0,0` локально и профилирование init ([32-performance-and-scalability.md](32-performance-and-scalability.md)) |

Поднятие числа в `project.yaml` — легальный, но **последний** ход, и он идёт отдельным коммитом с обоснованием, а не в составе релизного.

---

## 10. CHANGELOG — PARTIALLY IMPLEMENTED

`vn release changelog` (`cli.py:1471-1489` → `update_changelog()`, `release.py:142-179`). Флагов у команды нет.

1. `snapshot_content(root)` (`release.py:124-139`) обходит **только `content/chapters/`**, даёт `{ch_id: {status, scenes[]}}`.
2. Предыдущее состояние читается из `ci/release-manifest.json` (`.chapters`).
3. Дифф: новые главы, новые сцены, удалённые сцены.
4. Если что-то изменилось — блок вставляется сразу после первой строки `../CHANGELOG.md`:
   ```markdown
   ## 0.1.0

   Новые главы: ch01
   Новые сцены (3): ch01_s010, ch01_s020, ch01_s030
   ```
5. `ci/release-manifest.json` перезаписывается целиком (`release_manifest@1`, `indent=1, sort_keys=True`).
6. `stamp_id_registry()` (`release.py:99-121`) — append-only объединение в `content/registry/id_registry.json`. `_released_ids()` (`release.py:69-96`) собирает **только главы со `status: "release"`**; если released-сцен нет, возвращаются пустые списки и штамповать нечего.

**Реальность.** `ci/release-manifest.json` сейчас: версия `0.1.4`, одна глава `ch01` (`draft`, 3 сцены). `content/registry/id_registry.json` состоит из пустых массивов, потому что `ch01` — `draft`; страховка G7 инертна. В `../CHANGELOG.md` **сгенерирован ровно один блок** — `## 0.1.0` (`:36-39`); записи 0.1.1–0.1.4 написаны руками прозой для игрока. Утверждение `../ARCHITECTURE.md:3785` «никто не пишет changelog руками» на практике не выполняется — и это правильно: генератор умеет говорить только про главы и сцены, а 0.1.1–0.1.4 несли UI, галерею и фиксы.

**Ограничения (NOT IMPLEMENTED):** нет `--from <tag>`, нет `--audience player|internal`, нет диффа между git-тегами, нет пер-релизных `releases/<version>.yaml`. `snapshot_content` **не заглядывает в `packs/*/chapters/`** — глава `ch90` из `ep_beach` никогда не попадёт ни в манифест, ни в сгенерированный блок; для паков описание пишется руками.

**Порядок:** сначала `vn release changelog`, потом дописывать прозу — иначе генератор вставит свой блок выше вашего текста в той же версии.

---

## 11. CI/CD

Живой пайплайн — GitHub Actions: **4 workflow, 7 определений джоб** (на теге релизная `build` разворачивается матрицей в 2 прогона). Общее для всех: `actions/checkout@v4` с `with: {lfs: true}`, Python 3.12, установка тулчейна двумя шагами — `pip install --quiet -r tools/vn.lock` и следом `pip install --quiet -e "tools/vn[dev]"` (лок первым, G17: диапазоны `>=` из `pyproject.toml` к этому моменту уже удовлетворены, pip ничего не поднимает), `SDL_AUDIODRIVER: dummy`, `PYTHONIOENCODING: utf-8`, движок под `xvfb-run -a` (headless-режима у Ren'Py нет, G23). Везде, где джоба доходит до `vn build`, раньше него ставится `ffmpeg` — видео-ветка конвейера без него бросает `VideoError` (ADR-0006).

**Оба этих инварианта — не соглашение, а тест.** `tools/vn/tests/test_ci_config.py` (4 теста) парсит YAML всех пяти конфигов и проверяет: (а) перед каждой editable-установкой идёт `pip install -r tools/vn.lock` — таких мест **8** (5 джоб GitHub + 3 джобы GitLab: строк с локом в `.gitlab-ci.yml` две, но `before_script` шаблона `.with-sdk` разворачивается и в `build`, и в `test`); (б) в каждой GitHub-джобе, которая зовёт `vn build` или `vn release build`, `ffmpeg` ставится раньше. GitLab из проверки (б) исключён намеренно — конфиг исторический и вне паритета.

| Workflow | Триггер | Джобы | Ключевые шаги | Артефакты |
|---|---|---|---|---|
| `ci.yml` | push в `main`, любой PR | `lint`; `build-test` (needs `lint`) | `vn content lint`; кэш SDK `renpy-sdk-8.5.3-linux`; `vn build` → `vn loc keys --check` → `renpy.sh . lint` → `vn content compile --check` → `pytest tools/vn/tests -q` | `generated-<sha>` = `game/generated/`, 30 дней |
| `nightly.yml` | cron `30 2 * * *`, dispatch | `smoke` | `vn build`; `vn loc import`; `vn loc report`; smoke-матрица из 4 прогонов; `vn save check` + `vn save corpus`; **`rm -rf game/generated` → `vn release build --flavor public` и `--flavor patron`** (`:70-74`) | `smoke-shots-<run_id>` = `.vncache/smoke/`, 7 дней, `if: always()` |
| `canary.yml` | cron `0 3 * * 1`, dispatch | `fresh-renpy` | берёт **самый свежий** Ren'Py с `renpy.org/latest.html`, подменяет `RENPY_SDK` через `$GITHUB_ENV`, гоняет `vn build` → `renpy.sh . lint` → `pytest` → `vn test smoke --picks 0,0` | — |
| `release.yml` | push тега `v*` | `build` (matrix `flavor: [public, patron]`, `fail-fast: false`); `dmg`; `publish` | сверка тега с `project.yaml` (`:47-54`); кэш SDK; кэш `build/rpyc-cache` **на флейвор** (`:71-76`); `vn release build --flavor <f> --package win --package linux --package mac --timeout 1800` (+`--patron-token` из secrets только для patron) | `dist-public`, `dist-patron` (7 дней); `dmg`; GitHub Release |

**Разделение публикации — политика CI, а не кода.** В GitHub Release уходит только `dist-public` + dmg (`release.yml:117-135`, `gh release create … --generate-notes --verify-tag`). `dist-patron` остаётся артефактом workflow на 7 дней для ручной раздачи по своим каналам. Скачали — раздали, через неделю артефакт исчезает.

**`dmg` не требует движка:** macos-раннер берёт `*-mac.zip` из `dist-public`, распаковывает, находит `.app` и делает `hdiutil create -volname "VN" -format UDZO` (`release.yml:95-115`).

**Долги CI, которые касаются релиза:**

- `.gitlab-ci.yml` — 3 джобы (`lint`, `build`, `test`), **ни релиза, ни флейворов, ни LFS, ни ffmpeg, ни кэша `.rpyc`**. При этом `../../ci/README.md:6` до сих пор называет его «конфигом пайплайна». `../../CODEOWNERS:23` покрывает `/.gitlab-ci.yml` и **не покрывает `/.github/`** — релизный workflow формально ничей. Разбор — [04-development-workflow.md](04-development-workflow.md) §4.
- ~~`nightly.yml` ставит только `xvfb libgl1` — без ffmpeg~~ — **закрыто**: `nightly.yml:32` и `canary.yml:33` ставят `ffmpeg` тем же шагом, что `ci.yml:49` и `release.yml:45`. Долг был не теоретическим — сырцы в `assets_src/video_src/` уже лежат, то есть ночной и еженедельный прогоны падали бы `VideoError`. Инвариант закреплён тестом `test_ffmpeg_installed_before_vn_build`.
- ~~`tools/vn.lock` не читает ни одна джоба — G17 только на бумаге~~ — **закрыто**: лок ставится во всех 8 местах установки тулчейна (`ci.yml:30`, `:46`, `nightly.yml:29`, `canary.yml:30`, `release.yml:42`, `.gitlab-ci.yml:23`, `:37`) и **до** editable-установки. Остаток честный: в локе закреплены 18 прямых пакетов, транзитивные зависимости (например `pygments`) не пиннованы — полной воспроизводимости окружения это ещё не даёт. Инвариант закреплён тестом `test_lock_installed_before_editable`.
- `canary.yml` не имеет `continue-on-error`: красный canary валит workflow. Это строже, чем `allow_failure: true` из `../ARCHITECTURE.md:3596`, и это осознанное расхождение.
- Не существует ни одной из джоб `rpyc-compat`, `screens`, `nightly-paths`, `nightly-perf`, `steam-publish`, матрицы `PLATFORM: [win, mac, linux, android]` и шага `vn validate --budgets --dist dist/` — всё NOT IMPLEMENTED (команды `vn validate` нет вовсе).

---

## 12. Steam и магазины — PARTIALLY IMPLEMENTED

Полная страница платформенного слоя — [39-platforms.md](39-platforms.md) ([ADR-0014](../adr/0014-platform-services.md)); здесь — только релизная часть.

`vn release steam --flavor <f> [--branch <b>]` (`cli.py:1819-1852`) **реализована**: рендерит `build/steam/app_build_<flavor>.vdf` из шаблона `../../ci/steam/app_build.vdf.tmpl` по номерам из `project.yaml: platform.steam.{appid,depots}` и распаковывает зипы `build/dist/<version>-<flavor>/` в раскладку депотов `build/steam/content/<flavor>/<platform>/` (`release.py:151-252`). Проверка владения DLC тоже ожила: провайдер ставится в `game/framework/00_core/035_platform.rpy:75` при живом Steam, маппинг — `steam_dlc_appid` в манифесте пака.

Чего по-прежнему нет:

| Что | Статус |
|---|---|
| Аплоад | **ручной** — `steamcmd +login … +run_app_build … +quit`; credentials вне репозитория, джобы `steam-publish` не существует |
| Каналы `dev`/`beta`/`release` как сущности конвейера | NOT IMPLEMENTED. `--branch beta` — это только строка `"SetLive"` в VDF; теги `vX.Y.Z-rcN` невозможны: `project@1` требует `^\d+\.\d+\.\d+$` (`release.yml:47-54`) |
| Steam-проверки в релизном гейте | нет ни одной из 19; всё платформенное валидируется внутри `vn release steam` и в `tools/vn/tests/test_platform.py` |
| Депот отдельного пака/DLC как товара | NOT IMPLEMENTED — `vn pack build` кладёт в zip только манифест и сцены ([30](30-packs-and-dlc.md) §7.2) |
| steam_api-библиотеки в репозитории | и не будет: редистрибутив Valve ставится лаунчером в `$RENPY_SDK/lib/py3-*/`. Их отсутствие — `warning`, сборка остаётся валидной (просто standalone) |

**Что придётся сделать руками сегодня, если релиз выкладывается в Steam или куда-то кроме GitHub:**

1. `vn release build --flavor public --package win --package linux --package mac` локально или скачать `dist-public` из `release.yml`.
2. Проверить `build/dist/<version>-public/build-info.json`: `flavor`, `version`, `sha`, `exclude`.
3. Распаковать zip нужной платформы, убедиться, что внутри есть `game/build_id.json` (иначе флейвор не применится — §3).
4. Для Steam — `vn release steam --flavor public [--branch beta]`, затем `steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit`. Для остальных витрин архивы заливаются их собственным загрузчиком (itch и т. п.).
5. Описание релиза собрать из `../CHANGELOG.md` руками — `--audience player` не существует.
6. Для patron-канала брать `dist-patron` и раздавать напрямую; вотермарка с `build_id` и меткой `patron_tag` уже в кадре. Сам токен в архив не попадает (ADR-0011) — сопоставление «метка → получатель» считается на вашей стороне.

Пак как отдельный товар (`vn pack build`) — [30-packs-and-dlc.md](30-packs-and-dlc.md); напомню, что зип пака содержит только манифест и скомпилированные сцены, без ассетов и переводов.

---

## 13. PRE-RELEASE CHECKLIST

Выполняется на чистом `main`, до коммита версии. Все пункты — команды этого проекта.

**Окружение**

- [ ] `export RENPY_SDK=…`; `vn doctor` — 8 PASS, 0 FAIL (в том числе пин SDK 8.5.3 и шрифты без LFS-указателей)
- [ ] `git status --short` пуст: ничего из `game/generated|assets|tl`, никаких локальных правок

**Содержимое**

- [ ] `vn build` — `build: OK`
- [ ] `vn content lint` — 0 ошибок
- [ ] `vn content compile --check` — `check: генерат свеж`
- [ ] `python -m pytest tools/vn/tests -q` — 253 passed (с заданным `RENPY_SDK`; без него и ffmpeg часть тестов молча скипается — см. 27-testing.md §1)
- [ ] `vn loc keys --check` — say-id и ledger свежи (G8)
- [ ] `vn loc report` — все несинтетические языки ≥ 98 % (порог `loc/loc.yaml: release_coverage_min`)
- [ ] `vn pack validate` — все паки совместимы с фасадом `vn.*` (`api_level`, `requires.core`)

**Рантайм** (`ci.yml` этого не гоняет)

- [ ] `vn test smoke --picks 0,0` — `OK: vn_end_of_content`, cold start в бюджете 30 с
- [ ] `vn save check` и `vn save corpus` — обе фикстуры грузятся, миграции доводят схему до `project.yaml: save_schema` (`schema1-demo` обязан дать «schema после загрузки: 2 (цель 2)», а в `log.txt` — строку `[vn] migration 0002`)
- [ ] Если бампался `save_schema` — миграция написана, добавлена в `content/migrations/registry.yaml`, свежая фикстура положена через `vn save corpus --add` ([07-backend.md](07-backend.md))

**Релиз**

- [ ] `vn release validate --flavor public` — 0 FAIL (16 строк PASS)
- [ ] `vn release validate --flavor patron` — 0 FAIL (17 строк)
- [ ] `vn release build --flavor public --package win` прошёл локально хотя бы раз за цикл
- [ ] Главы, которые считаются выпущенными, переведены в `status: release` (иначе `id_registry.json` останется пустым и G7 не сработает)
- [ ] `vn release changelog` прогнан, проза для игрока дописана **после** него
- [ ] `project.yaml: version` бампнут по политике: новая глава = **minor**, фиксы = patch
- [ ] `ci/release-manifest.json` в коммите (иначе гейт даст WARN о расхождении версий)

---

## 14. RELEASE RUNBOOK

Пошагово, от «глава готова» до опубликованного релиза.

```bash
# 0. Чистый main, SDK на месте
git switch main && git pull && git status --short
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"
vn doctor

# 1. Поднять статус выпускаемых глав (граф-проверки станут строгими, G15)
#    content/chapters/chNN_*/chapter.yaml -> status: release
vn content lint            # должно остаться 0 ошибок

# 2. Полный круг проверок
vn build
vn loc keys --check
vn content compile --check
python -m pytest tools/vn/tests -q
vn test smoke --picks 0,0
vn save check && vn save corpus

# 3. Changelog и манифест (ДО правки версии — генератор берёт version из project.yaml,
#    поэтому бампайте версию сразу после и перезапустите команду, если блок уже вставлен)
vn release changelog
#    вручную: docs/CHANGELOG.md — 2-5 предложений для игрока
#    вручную: project.yaml: version -> 0.1.5

# 4. Гейт по обоим флейворам
vn release validate --flavor public
vn release validate --flavor patron

# 5. Локальная контрольная сборка (необязательно, но ловит проблемы distribute до тега)
vn release build --flavor public --package win
ls build/dist/0.1.5-public/            # vn-0.1.5+<sha>-win.zip + build-info.json
#    содержимое архива проверяется скриптом из раздела «Проверка» ниже

# 6. Релизный коммит — ровно три файла
git add project.yaml docs/CHANGELOG.md ci/release-manifest.json content/registry/id_registry.json
git commit -m "release: 0.1.5 — <итог одной строкой>"

# 7. Тег и пуш
git tag v0.1.5
git push --follow-tags                 # -> release.yml: гейт тега -> build x2 -> dmg -> publish

# 8. После зелёного workflow
#    - GitHub Release создан, в нём только public-архивы + dmg
#    - dist-patron скачать из артефактов workflow (7 дней!) и раздать по своим каналам
```

**Что проверить на артефактах перед раздачей:**

| Проверка | Как |
|---|---|
| Флейвор применился | внутри архива есть `game/<name>/game/build_id.json`, поле `flavor` верное |
| Вотермарка там, где надо | `patron` → `watermark: true`; `public` → `false` |
| Нет dev-инструментов | в архиве нет `game/framework/90_debug/` |
| Нет псевдолокали | нет `game/tl/pseudo/` |
| Лицензии едут | есть `game/THIRD-PARTY-NOTICES.md` |
| Размер похож на прошлый релиз | резкое изменение = что-то попало или пропало |

---

## 15. Откат: релиз сломан

**Прецедент проекта.** Сборка `0.1.1` оказалась нерабочей: чекаут в CI шёл без LFS, в дистрибутив уехали 131-байтные указатели вместо шрифтов, игра падала `FreetypeError` на главном меню. Тега `v0.1.1` в репозитории **нет** — сломанная версия не откатывалась, она была вытеснена вперёд: коммит `ff28ba9` добавил `lfs: true` во все workflow и проверку шрифтов по содержимому (`doctor.py:50-66`, гейт `release.py:293-302`), после чего вышел `0.1.2`, а `../CHANGELOG.md:20-24` прямо говорит игроку «сборки 0.1.1 непригодны — используйте 0.1.2».

**Это и есть штатная процедура: катим вперёд, а не назад.** Причины технические, не идеологические:

1. Тег обязан совпадать с `project.yaml: version` (`release.yml:47-54`). Перевыпустить ту же версию с другим содержимым можно только удалив тег и релиз — а у игроков он уже скачан.
2. `config.version` содержит git-sha, поэтому «та же версия» после фикса всё равно даёт другое имя архива.
3. Если в сломанном релизе бампался `save_schema`, откат назад для игроков **невозможен в принципе**: их сейвы будут «из будущего», и `after_load` покажет `ui.flow.save_from_newer` и перезапустит игру (`020_state.rpy:83-93`).

**Порядок действий:**

```bash
# 1. Остановить распространение (руками, инструмента нет)
gh release edit v0.1.5 --draft        # убрать из публичного списка
#   или gh release delete v0.1.5 --yes , если скачиваний ещё не было

# 2. Починить причину в main отдельным коммитом (fix(...): ...), с тестом/проверкой,
#    которая поймала бы этот класс поломки. Хотфикс поверх непонятного пайплайна запрещён.

# 3. Бампнуть patch и выпустить новую версию по runbook §14
#    project.yaml: 0.1.5 -> 0.1.6 ; в CHANGELOG честно: «сборки 0.1.5 непригодны»

# 4. Сломанный тег НЕ переиспользовать. Если тег ещё никуда не уехал:
git tag -d v0.1.5 && git push origin :refs/tags/v0.1.5
```

**Чего откат НЕ трогает:**

- `build/rpyc-cache/` — кэш сломанной версии остаётся и станет базой для следующей (локально берётся старший по версии каталог). Если сломанная сборка меняла структуру `.rpy`, безопаснее удалить `build/rpyc-cache/<сломанная версия>/` локально; в CI — сменить ключ кэша.
- `content/registry/id_registry.json` — append-only, из него ничего не вычёркивается. Это by design (G7).
- `ci/release-manifest.json` — перезапишется следующим `vn release changelog`.

**Если ломается не релиз, а сборка** (красный CI, не собирается генерат) — порядок в [36-troubleshooting.md](36-troubleshooting.md) и [04-development-workflow.md](04-development-workflow.md) §6. Аварийный режим G4 «взять `game/generated/` из артефакта `generated-<sha>`» работает только руками: `vn build --use-artifact <sha>` **не существует**, хотя упомянут в `../ARCHITECTURE.md` 14 раз.

---

## Как изменить / Как расширить

**Добавить флейвор.** Дописать блок в `project.yaml:12-22` (ключи `packs` и `nsfw` обязательны схемой). Кода менять не нужно: `--flavor` принимает любое имя из `project.yaml`, а гейты в игре спрашивают `vn_build.nsfw` / `vn_build.early_content`, а не имя флейвора (`060_build_info.rpy:6-8`). Добавить ногу в матрицу `release.yml:32`, если он должен собираться на теге.

**Сделать `packs` настоящим гейтом.** Точка правки — `030_flow.rpy:76-77`: `installed()` должен пересекать `VN_PACKS` с `vn_build.packs`, а не смотреть только на генерат. Проверить потребителей `owned()`: `chapter_select.gen.rpy`, `080_achievements.rpy:41`, `090_gallery.rpy:44`. Тест: `public`-сборка не должна показывать главы пака `nsfw`.

**Оживить `early_content`.** Потребителя нужно написать: гейт по главе (`chapter.yaml`) или по элементу галереи, по образцу NSFW-гейта в `090_gallery.rpy:40-44`.

**Развести кэш `.rpyc` по флейворам.** Одна строка — `cli.py:358`: `cache_root / version` → `cache_root / f"{version}-{flavor}"`. Потребуется прокинуть флейвор в `package` (сейчас туда идёт только `dest_suffix`) и поправить `_semver_key`, который парсит имя каталога как semver.

**Добавить проверку в гейт.** Правило пишется как функция в своём модуле (`assets/`, `content/`, `loc/`) и вызывается из `validate_release` через `add("PASS"/"WARN"/"FAIL", …)`. Собственной логики в `release.py` быть не должно — иначе гейт разойдётся с `vn build`.

**Затащить `cold_start_s` в релиз.** Либо шаг `vn test smoke --picks 0,0` в `release.yml` перед `vn release build`, либо новая проверка в гейте, читающая результат последнего smoke из `.vncache/smoke/`. Первый вариант честнее — он меряет ту же сборку.

**Включить `.rpa`-архивы (только через ADR).** Россыпь в desktop-каналах — норма `../ARCHITECTURE.md` §2.4 (Steam-дельта-патчи); тематические `.rpa` допустимы лишь как опция mobile-поставки фазы 3. Технически это `build.archive(...)` + `build.classify(..., "archive_*")` в `game/options.rpy`; помнить, что после этого проверки размеров придётся считать по архивам, а каждый патч будет размером с архив.

## Чего НЕ делать

- **Не раздавать архив из голого `vn package`** — в нём нет `game/build_id.json`, игра пойдёт как `dev`: NSFW открыт, ранний контент открыт, вотермарки нет.
- **Не ставить тег, не бампнув `project.yaml: version`** — `release.yml:47-54` рубит workflow первым шагом.
- **Не пытаться выпустить `v1.0.0-rc1`** — схема `project@1` запрещает pre-release-суффикс.
- **Не понижать `save_schema` и не откатывать релиз с его бампом** — сейвы игроков станут «из будущего», игра перезапустится (`020_state.rpy:83-93`).
- **Не коммитить `game/build_id.json`** — он в `.gitignore:8` и должен жить только во время distribute; закоммиченный, он превратит все dev-запуски в чужой флейвор.
- **Не считать, что `flavors.<f>.packs` кого-то ограничивает** — `VN_PACKS` перечисляет все паки из `packs/` независимо от флейвора.
- **Не класть главу со сценами в пак `nsfw`, рассчитывая на исключение по флейвору** — она уедет и в `public`. Гейт по ассетам (`nsfw/`-подпапки) работает, гейт по пакам — нет.
- **Не переименовывать архивы в `build/dist/`** — имя выводится движком из `build.name` и `config.version`; переименованный файл не соотнесётся с `build-info.json`.
- **Не удалять `ci/fixtures/rpyc-line/`** как «лишние `.rpyc`» — это единственные `.rpyc` в git и основа детерминированности сейв-корпуса (G6).
- **Не полагаться на `vn release validate` как на полную проверку** — он не гоняет ни smoke, ни движковый lint, ни бюджет холодного старта, ни пин SDK.
- **Не рассчитывать на `vn validate`, `vn build --use-artifact`, `vn release changelog --from/--audience`, `vn release build --channel`** — этих команд и флагов не существует (exit 3 или usage error). `vn release steam` **существует** (§12), но готовит VDF и раскладку депотов, а не заливает: аплоад — ручной `steamcmd`.
- **Не забывать про 7 дней хранения `dist-patron`** — артефакт workflow исчезнет, а собрать бит-в-бит тот же архив заново уже не получится (в `build_id` зашита минута сборки).

## Проверка

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"

# Гейт цел и проходит по обоим флейворам
vn release validate --flavor public       # 16 PASS, exit 0
vn release validate --flavor patron       # 17 PASS, exit 0
vn release validate --flavor nosuch; echo $?   # FAIL на 2-й строке, exit 1

# Релизная сборка проходит целиком
vn release build --flavor public --package win
cat build/dist/$(python -c "import yaml;print(yaml.safe_load(open('project.yaml'))['version'])")-public/build-info.json

# Артефакт содержит то, что должен
python - <<'PY'
import glob, zipfile
z = sorted(glob.glob("build/dist/*-public/*.zip"))[-1]
n = zipfile.ZipFile(z).namelist()
print(z)
print("build_id.json:", any("build_id.json" in x for x in n))
print("90_debug:", any("90_debug" in x for x in n))          # должно быть False
print("tl/pseudo:", any("tl/pseudo" in x for x in n))        # должно быть False
print("notices:", any("THIRD-PARTY-NOTICES" in x for x in n))
PY

# Бюджеты и версии
vn build                                  # бюджеты G19 проверяются здесь же
git describe --tags --exact-match 2>/dev/null   # тег == project.yaml: version?
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/release.py` (гейт, флейворы, build-info, `patron_tag`, changelog, бюджеты), группы `package`/`release`/`pack` в `../../tools/vn/src/vn/cli.py:279-370,1466-1639`, `../../project.yaml`, `../../game/options.rpy`, `../../game/framework/00_core/060_build_info.rpy`, `../../.github/workflows/release.yml`, `../../tools/schemas/build_info@2.schema.json` (действующая; `build_info@1` — только для чтения старых артефактов), `../adr/0011-patron-tag-instead-of-token.md`, `../adr/0014-platform-services.md` + `../../ci/steam/README.md` (Steam-поставка), `../../tools/vn/tests/test_ci_config.py` |
| **Не трогать** | `game/build_id.json` (пишет и удаляет `vn release build`), `build/**` (dist, rpyc-cache, packs — производная зона, `.gitignore:20`), `game/generated/**`, `game/assets/**`, `game/tl/**`; `ci/fixtures/rpyc-line/**` — только через `vn save corpus` |
| **Зависимости** | правка `project.yaml: version` → тег, `config.version`, имя архива, каталог `build/rpyc-cache/<version>/`; правка `flavors` → `build_id.json` → рантайм-гейты достижений и галереи; правка `budgets` → и `vn build`, и гейт; правка `renpy_sdk` → руками синхронизировать `RENPY_VERSION` в `ci.yml:13`, `nightly.yml:12`, `release.yml:19`; правка `game/options.rpy` → состав каждого дистрибутива |
| **Валидация** | `vn release validate --flavor public && vn release validate --flavor patron`; полная — `vn release build --flavor public --package win` с проверкой содержимого zip (см. «Проверка») |
| **Частые ошибки** | 1) выдумать флаг: `vn validate`, `vn build --use-artifact`, `vn release changelog --from`, `vn release build --channel` — их нет; 2) считать `flavors.<f>.packs` и `early_content` работающими гейтами — они не читаются никем; 3) назвать `vn package` способом собрать релиз — получится dev-сборка без `build_id.json`; 4) цитировать `../ARCHITECTURE.md` как описание реализованного (это целевой документ: каналы `dev`/`beta`/`release`, `steam-publish`-джоба, `rpyc-compat` — NOT IMPLEMENTED; Steam-депоты — отдельный случай: подготовка есть по ADR-0014, нет только аплоада, §12; `.rpa` — §2.4 фиксирует россыпь как норму, и код ей соответствует); 5) утверждать, что гейт — 19 строк вывода: в коде 19 проверок, но три молчат при пустых данных, сегодня видно 16/17; 6) ставить тег, не бампнув `project.yaml`; 7) писать про `patron_token` в `build_id.json` — с ADR-0011 туда пишется `patron_tag` (схема `build_info@2`), а сам токен остаётся на машине сборки |
