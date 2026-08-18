# 29. Сборка и релиз

> **Статус подсистемы:** IMPLEMENTED — путь «тег `v*` → гейт из 21 проверки → дистрибутивы обоих флейворов → GitHub Release» работает целиком и обкатан пятью реальными релизами (`v0.1.0`, `v0.1.2`…`v0.1.5`); **и все четыре рычага флейвора теперь гейтят**: `nsfw`, `watermark` + `--patron-token`, `packs` (рантайм-гейт установленности, §3.2) и `early_content` (проверка №4 гейта, §5.1 — самоактивирующаяся: на этом дереве, где ни одна глава ещё не `release`, она даёт WARN и оба флейвора собираются, а с первой `release`-главой становится строгой сама). **Но** кэш `.rpyc` ключуется версией без флейвора, у Steam-поставки автоматизирована только подготовка (`vn release steam`: VDF + раскладка депотов — она понимает форматы всех трёх платформ, включая `tar.bz2` для Linux, §14.2), а **аплоад делает человек** и в этом чекауте команду вообще не получится довести до конца: `platform.steam.appid: null` и ключа `depots` нет (§14.1), а QA на живом железе (Windows/mac/Deck) не автоматизировано ничем.
> **Отвечает на вопрос:** «Глава готова. Что запустить, в каком порядке, что проверить на каждой стадии и как выпустить сборку, которую не стыдно отдать игроку?»

Весь релизный путь живёт в двух файлах: `../../tools/vn/src/vn/release.py` (629 строк — гейт, флейворы, build-info, changelog, бюджеты, Steam-поставка) и группы `package` / `release` / `pack` в `../../tools/vn/src/vn/cli.py` (2117 строк; группа `release` начинается на `:1720`). CI — тонкая обёртка: `.github/workflows/release.yml` не содержит ни одной релизной проверки собственного изготовления, он вызывает `vn release build`. Поэтому всё, что делает CI на теге, воспроизводится локально одной командой.

Сквозной практический маршрут от «правлю сцену» до «нажал setlive» — §13. Если нужен только чеклист перед тегом — §15.

**Состояние релизной линии на 2026-08-18 (проверено: `git tag -l`, `project.yaml:2`, `ci/release-manifest.json`):** тег `v0.1.5` **уже выпущен**, `project.yaml: version` тоже `0.1.5`, а поверх тега лежат 9 невыпущенных коммитов (в `../CHANGELOG.md` они собраны в разделе «Не выпущено»). Значит первый шаг следующего релиза — **бамп до `0.1.6`**; попытка поставить `v0.1.5` повторно упрётся в существующий тег, а `v0.1.6` без бампа `project.yaml` упадёт на `release.yml:47-54`.

## Быстрый ответ

```bash
export RENPY_SDK=/путь/к/renpy-8.5.3-sdk    # без него package/release/smoke не работают

# Проверить, готов ли репозиторий к релизу (ничего не пишет, ~30 c)
vn release validate --flavor public
vn release validate --flavor patron

# Собрать флейвор целиком (сборка + гейт + дистрибутивы) — то же, что делает CI на теге
vn release build --flavor public --package win
#   -> build/dist/0.1.6-public/vn-0.1.6+<sha>-win.zip + build-info.json

# Выпустить: правки в трёх-четырёх файлах одним коммитом, потом тег
vn release changelog                  # docs/CHANGELOG.md + ci/release-manifest.json
#   вручную: version в project.yaml (0.1.5 -> 0.1.6) + проза в CHANGELOG
git commit -m "release: 0.1.6 — <итог одной строкой>"
git tag v0.1.6 && git push --follow-tags     # -> .github/workflows/release.yml
```

**Главное правило:** тег `v<X.Y.Z>` обязан посимвольно совпадать с `project.yaml: version`, иначе `release.yml:47-54` рубит сборку на первом шаге, до установки SDK.

---

## 1. Пять команд сборки и чем они отличаются

| Команда | Что делает | Что на выходе | Флейвор |
|---|---|---|---|
| `vn build` | lint → ассеты → компилятор → `vn loc import` → бюджеты размера **и памяти** (`cli.py`) | `game/generated/`, `game/assets/`, `game/tl/` | нет |
| `vn package` | `vn build --profile full` → перенос `.rpyc` → `renpy compile` → `launcher distribute` → снимок `.rpyc` (`cli.py`) | `build/dist/<version>/*` | **нет — опасно, см. §4** |
| `vn release build --flavor <f>` | `vn build` → гейт → `build_id.json` → `vn package` → `build-info.json` (`cli.py`) | `build/dist/<version>-<f>/` | да |
| `vn release steam --flavor <f>` | VDF из `ci/steam/app_build.vdf.tmpl` + распаковка архивов distribute под депоты — zip и `tar.bz2` (`cli.py`) | `build/steam/app_build_<f>.vdf` + `build/steam/content/<f>/<platform>/` | да — §14 и [39-platforms.md](39-platforms.md) |
| `vn pack build <id>` | зип генерата глав пака + манифест (`cli.py`) | `build/packs/<id>.zip` | — см. [30-packs-and-dlc.md](30-packs-and-dlc.md) |

Сам конвейер `content/` → `game/generated/` разобран в [08-content-pipeline.md](08-content-pipeline.md), ассеты — в [16-assets.md](16-assets.md); здесь только то, что происходит **после** зелёной сборки.

**Exit-коды `vn`** (докстринг `cli.py`): `0` — успех; `1` — ошибка проверки/сборки (всегда с сообщением `ошибка: …` на stderr, `cli.py`); `2` — usage error от click; `3` — «команда появится в фазе N» (`cli.py`). Заглушек фазы, дающих ровно `3`, в релизном тракте две — `vn migrate` и `vn shell` (`cli.py`); `vn validate` и `vn release build --channel` не существуют вовсе, то есть дают `2`, а не `3`.

---

## 2. Профили сборки: development / testing / release / Steam / non-Steam

Слово «профиль» в проекте означает **две разные вещи**, и их путают чаще всего:

1. **Профиль энкода ассетов** — `--profile full|draft` у `vn build` (`cli.py`). Это единственный флаг, меняющий байты в `game/assets/`.
2. **Флейвор релиза** — `--flavor public|patron` у `vn release build` (§3). Он не меняет ни один ассет, только состав дистрибутива и метаданные.

Отдельной «Steam-сборки» в конвейере нет: тот же артефакт становится Steam-сборкой из-за окружения, а не из-за флага. Сводно:

| Режим | Команды | Профиль ассетов | `game/build_id.json` | `90_debug/**` | Steam |
|---|---|---|---|---|---|
| **development** | `vn dev` (`cli.py`), `vn build --profile draft`, `vn play` | `draft` — quality 50 у bg/cg/spr/shot, панели без `method=4` (`render_config.py:65,76,88,102`; `pipeline.py:654`) | нет → `flavor="dev"` | активны | по факту окружения |
| **testing / QA** | `vn build` (full), `pytest`, `vn test smoke`, `vn test oversample`, `vn save corpus` | `full` | нет → `flavor="dev"` | активны; автопилот пишет `game/generated/qa/` | нет |
| **release** | `vn release build --flavor <f>` | `full` **принудительно** (`cli.py`, `cli.py` — оба зовут `build` с `profile="full"`) | пишется на время distribute, удаляется в `finally` | вырезаются `build.classify` (`game/options.rpy:31`) | зависит от окружения |
| **Steam build** | тот же артефакт release | — | — | — | **да**: `platform.steam.appid` ≠ `null` **и** steam_api рядом с исполняемым |
| **non-Steam build** | тот же артефакт release | — | — | — | нет: движок тихо пропускает `steam_init()` |

**Что реально различает development и release.**

- **Ассеты.** `draft` уходит в ключ кэша и в `.vncache/assets-manifest.json` (`pipeline.py:725,740`), а `vn build --check` сверяет поле `profile` (`pipeline.py:867`). Практическое следствие: после `vn dev` (он собирает ассеты в `draft`, `cli.py`) `vn build --check` **красный** — «источник изменился». Лечится одним полным `vn build`. Релизная сборка от этого защищена: она сама навязывает `full`.
- **Dev-инструменты.** `game/framework/90_debug/` — три файла: `010_dev.rpy` (`config.console = True`), `020_jump_menu.rpy` (Shift+J по `config.developer`), `030_oversample.rpy` (движковая команда `vn_oversample`). В дистрибутив не уезжают (`options.rpy:31`), поэтому «в собранной игре нет консоли» — норма, а не поломка.
- **Флейвор в рантайме.** Без `build_id.json` игра идёт как `dev` со всем контентом открытым (§4). Проверять NSFW-гейты и вотермарку можно **только** на собранном флейворе.
- **Steam.** Единственное отличие Steam-сборки от non-Steam — наличие `steam_api64.dll` / `libsteam_api.so` / `libsteam_api.dylib` в `$RENPY_SDK/lib/py3-*/` на build-машине плюс непустой `appid`. Кода, который «включает Steam», в проекте нет; см. [39-platforms.md](39-platforms.md) §3.

**Чего в проекте нет:** отдельного `--profile release`, отдельного дистрибутива «для QA», подписи кода. `grep -rni "codesign\|notariz\|signtool" .github/ tools/ game/ ci/` даёт только `hdiutil` в `release.yml:109` — то есть **ни Windows-, ни macOS-артефакт не подписан** (§13, стадии 6-7).

---

## 3. Флейворы: `public` и `patron` — IMPLEMENTED (наполовину)

Объявлены в `../../project.yaml:66-76`, схема — `tools/schemas/project@1.schema.json` (`packs` и `nsfw` обязательны, `early_content`/`watermark` опциональны с дефолтом `false`).

| Ключ | `public` | `patron` | Кто читает | Статус |
|---|---|---|---|---|
| `packs` | `[ep_beach]` | `[ep_beach, nsfw]` | `release.py:483` → `build_info.packs`; гейт проверяет наличие `packs/<id>/manifest.yaml` (`release.py:539-543`); **рантайм** — `vn.pack_registry.installed()` (`030_flow.rpy:77-91`) | IMPLEMENTED (рантайм-гейт установленности, §3.2) |
| `nsfw` | `false` | `true` | `release.py:484,488` → исключение ассетов + рантайм-гейты | IMPLEMENTED |
| `early_content` | `false` | `true` | `release.py:485` → `vn_build.early_content` (рантайм-флаг для контент-кода); **релизный гейт** — `early_content_checks` (`release.py:403-438`) | IMPLEMENTED как гейт релиза (самоактивирующийся: строгим становится с первой главой `status: release`, §5.1); рантайм-потребителей у флага по-прежнему ноль |
| `watermark` | `false` | `true` | `release.py:486` → overlay-экран | IMPLEMENTED |

### 3.1 Что реально работает — три механизма

**1. Исключение NSFW-ассетов из дистрибутива (build-time).** `nsfw_exclude_globs()` (`release.py:441-452`) обходит **фактические** каталоги: для каждого `game/assets/<cat>/`, где есть подпапка `nsfw/`, добавляет глоб `game/assets/<cat>/nsfw/**`. Список кладётся в `build_id.json: exclude`, а `game/options.rpy:51-58` при distribute применяет его через `build.classify(_glob, None)`.

Честно: **сегодня это no-op.** Категории в `game/assets/` — `bg cg mov shots spr ui voice`, подпапки `nsfw/` нет ни в одной, поэтому в `build-info.json` поле `"exclude": []`. Механизм покрыт юнит-тестом на синтетических каталогах (`tools/vn/tests/test_release.py`, 13 тестов). Конвенция размещения зафиксирована в комментарии `packs/nsfw/manifest.yaml`.

**2. Рантайм-гейты по `nsfw` (логические).** `game/framework/00_core/060_build_info.rpy:10-45` создаёт `init -985 python in vn_build` и читает `build_id.json` через `renpy.open_file`. Потребители:

- `080_achievements.rpy` — достижение с `nsfw: true` не выдаётся в SFW-сборке (`visible()`);
- `090_gallery.rpy` — то же для элементов и целых категорий галереи ([15-gallery.md](15-gallery.md));
- `070_crash.rpy` — `build_id`/`flavor` штампуются в crash-репорт ([28-debugging.md](28-debugging.md)).

**3. Вотермарка.** Механизм — 20 строк в `game/framework/20_ui/screens/build_overlay.rpy`:

```renpy
init python:
    if vn_build.watermark:
        config.overlay_screens.append("vn_build_overlay")
```

Подпись рисуется полупрозрачным текстом 12 px в правом нижнем углу, `zorder 1090` (`build_overlay.rpy:6-16`), со сдвигом на `gui.overscan_pad` (Big Picture, `:15-16`; [39-platforms.md](39-platforms.md) §8). Её содержимое — `060_build_info.rpy:42-45`: `build_id` плюс **метка получателя** `patron_tag`, если она задана (`build_id · <8 hex>`).

**Токен получателя в дистрибутив не едет (ADR-0011).** Флаг `--patron-token` (`cli.py`) — вход команды, но в `build_id.json` пишется односторонняя производная: `patron_tag(token)` = `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex (`release.py:374-425`, поле собирается в `release.py:451`). Рантайм читает готовую метку и никакого трекинга не делает. В CI токен подставляется из `secrets.PATRON_TOKEN` и только для patron-ноги матрицы (`release.yml:79-87`).

Сопоставить утёкшую сборку с получателем владелец может сам — метка детерминирована:

```bash
python -c "import hashlib,sys; print(hashlib.blake2s(sys.argv[1].encode(), digest_size=4, person=b'vnpatron').hexdigest())" tok_demo42
# caf5afd4
```

**Требование к процессу, вытекающее из короткой метки:** токен получателя обязан быть случайным (`secrets.token_hex(16)` и подобное). Короткий низкоэнтропийный токен подбирается по 8-символьной метке перебором. Подробности и правовая грань — [33-security-and-legal.md](33-security-and-legal.md) §3.

### 3.2 `packs` и `early_content`: где именно они гейтят

**`flavors.<f>.packs` гейтит в рантайме, а не на сборке.** Скрипты глав уезжают в дистрибутив всегда (гейт логический, G9), поэтому `VN_PACKS` в генерате перечисляет **все** паки дерева независимо от флейвора:

```renpy
define VN_PACKS = {'ep_beach': {'kind': 'dlc', 'version': '1.0.0'}, 'nsfw': {'kind': 'dlc', 'version': '0.1.0'}}
```

Список поставки живёт отдельно — в `build_id.json: packs`, — и `pack_registry.installed()` (`030_flow.rpy:77-91`) с ним сверяется:

```renpy
installed(pack_id) = pack_id == "core"
                     or (pack_id in VN_PACKS and (не релиз или pack_id in vn_build.packs))
```

Признак «не релиз» — отсутствие `game/build_id.json`, то есть производный флаг `vn_build.is_release` (`060_build_info.rpy:24-38`): в dev-чекауте видно всё установленное, иначе dev-прогон и `vn test smoke` гейтились бы вслепую. **Пустой `packs` в релизной сборке гейтит, а не считается dev** — флейвор без паков легитимен.

Следствие: в `public`-сборке пак `nsfw` больше не считается установленным, и его главы, элементы галереи и достижения игроку не видны. Знаменатели счётчиков (`vn_gal.progress()`, `vn_ach.progress()`) считают только видимое, поэтому 100 % достижимы в каждом флейворе.

**Гейт установленности ≠ гейт владения.** Второй существует отдельно и работает под живым Steam: провайдер `_steam_owns_pack` ставится в `035_platform.rpy:75`, и у пака с `steam_dlc_appid` в манифесте `owned()` честно вернёт `False`. Без провайдера (DRM-free поставка) владение = установленность — и именно поэтому сверка со списком поставки обязательна: иначе пак `patron`-флейвора в `public`-сборке был бы и «установлен», и «куплен». Разделяйте эти два утверждения — они про разные моменты жизни сборки ([39-platforms.md](39-platforms.md) §5, [30-packs-and-dlc.md](30-packs-and-dlc.md) §4).

**`early_content` гейтит релиз, но не рантайм.** На сборке его читает проверка №4 гейта (`early_content_checks`, `release.py:403-438`, [§5.1](#maturity-gate-rule)), и она самоактивирующаяся: при `early_content: false` строгость (`draft` = FAIL, `playtest` = WARN) включается **с первой главой `status: release`**; пока таких глав в проекте нет — одна строка WARN, и флейвор собирается. В рантайме значение по-прежнему только объявляется (`vn_build.early_content`, `060_build_info.rpy`) — потребителей у флага ноль, и если понадобится «показывать плашку раннего доступа» или гейтить контент из сцены, писать это придётся с нуля.

Бизнес-контекст флейворов (кому что продаётся) — [01-project-overview.md](01-project-overview.md) §2.

---

## 4. `game/build_id.json` — паспорт сборки

**Кто пишет.** `compute_build_info()` (`release.py:479-506`) собирает документ `build_info@2`, `write_build_info()` (`release.py:456-465`) валидирует его схемой `tools/schemas/build_info@2.schema.json` (`additionalProperties: false`, все 12 полей обязательны) и пишет в `game/build_id.json`. `clear_build_info()` (`release.py:468`) удаляет файл в блоке `finally` (`cli.py`) — **файл существует только на время distribute**. Он в `.gitignore:8`.

Форма документа (`compute_build_info(root, "patron", patron_token="tok_demo42")`):

```json
{"build_id": "0.1.6+<sha>.patron.202608181905", "built_at": "2026-08-18T19:05:31+00:00",
 "early_content": true, "exclude": [], "flavor": "patron", "nsfw": true,
 "packs": ["ep_beach", "nsfw"], "patron_tag": "caf5afd4", "schema": "build_info@2",
 "sha": "<sha>", "version": "0.1.6", "watermark": true}
```

**Версия схемы бампнута с `@1` на `@2` (ADR-0011):** поле `patron_token` (сам секрет) заменено на `patron_tag` (невосстановимая метка). `build_info@1.schema.json` остался в реестре с пометкой «УСТАРЕЛА» — чтобы читались артефакты старых сборок.

Формат `build_id` — `{version}+{sha}.{flavor}.{YYYYMMDDHHMM}` в UTC (`release.py:444`).

**Кто читает.** Двое, в разное время:

| Читатель | Когда | Что берёт |
|---|---|---|
| `game/options.rpy:51-58` | во время `launcher distribute` | только `exclude` → `build.classify(glob, None)` |
| `060_build_info.rpy:26-40` | при каждом старте игры | `flavor`, `build_id`, `version`, `packs`, `nsfw`, `early_content`, `watermark`, `patron_tag` |

**Файла нет → игра идёт как `dev`.** Дефолты (`060_build_info.rpy:14-23`): `flavor="dev"`, `build_id="dev"`, `nsfw=True`, `early_content=True`, `watermark=False`. Чтение обёрнуто в `try/except Exception` — битый или отсутствующий файл не роняет старт. Это именно то, что нужно в рабочем чекауте: разработчик видит весь контент и не таскает чужую вотермарку.

**Грабля с ценой в деньги.** Из этих же дефолтов следует: архив, собранный голым `vn package` (без `--dest-suffix`, то есть без флейвора), **не содержит `game/build_id.json`**. Такой билд у игрока стартует как `dev`: NSFW-достижения и NSFW-галерея открыты, ранний контент открыт, вотермарки нет, NSFW-ассеты не исключены. **Голый `vn package` — инструмент отладки дистрибуции, а не способ собрать сборку для раздачи.** Для раздачи — только `vn release build --flavor <f>`.

---

## 5. `vn release validate --flavor <f>` — предрелизный гейт из 21 проверки

Точка входа `cli.py`, логика — `validate_release()` (`release.py:525-750`). Возвращает список пар `(PASS|WARN|FAIL, строка)`; `ok` становится `False` **на любом FAIL** (`release.py:532-536`), WARN не валит никогда. При FAIL — `_fail("release validate --flavor <f>: есть FAIL")`, **exit 1**.

Философия зафиксирована в докстринге (`release.py:526-528`): «своих правил у релиза нет» — гейт агрегирует уже существующие проверки конвейера, чтобы не расходиться с `vn build`. Единственное исключение — проверка зрелости контента (№4): у неё нет чужого владельца, потому что `early_content` объявляется только во флейворе, а решение «эту главу игроку показывать нельзя» принимается ровно на границе релиза.

### 5.1 Полный список проверок, в порядке выполнения

| # | Проверка | Код | FAIL когда | Печатается всегда? |
|---|---|---|---|---|
| 1 | `project.yaml` валиден по схеме `project@1` | `release.py:543` | любая ошибка схемы | да |
| 2 | Флейвор описан в `project.yaml` | `release.py:546-552` | нет такого флейвора — **и гейт немедленно возвращается**, остальные 19 проверок не выполняются | да |
| 3 | На каждый пак флейвора есть `packs/<id>/manifest.yaml` | `release.py:554-558` | манифест отсутствует | по одной строке на пак |
| 4 | **Зрелость контента для флейвора** | `release.py:560-561`, логика — `early_content_checks` (`release.py:403-438`) | `early_content: false` **и в проекте есть хотя бы одна глава `status: release`**: глава `status: draft` → **FAIL**, `status: playtest` → WARN, незнакомый статус трактуется как draft (fail-closed). Пока ни одной `release`-главы нет — одна строка **WARN** (гейт самоактивирующийся, см. ниже). При `early_content: true` — одна строка PASS без разбора статусов | да |
| 5 | `vn content lint` — 0 ошибок | `release.py:563-567` | есть ошибки линта ([08-content-pipeline.md](08-content-pipeline.md) §7) | да |
| 6 | Шрифты UI — не LFS-указатели | `release.py:570-583`, реализация `doctor.py: _lfs_pointer_fonts` | хоть один `.ttf/.otf` в `game/fonts/` — указатель LFS. WARN, если `game/fonts` пуст | да |
| 7 | `game/assets` свежи (`build_assets(check=True)`) | `release.py:585-591` | есть ошибки или несвежие выходы | да |
| 8 | Собранные видео-лупы валидны + бюджет на файл | `release.py:593-602` | ошибка валидации `.webm`; предупреждения → WARN | да |
| 9 | Генерат свеж (`compile_content(check=True)`) | `release.py:604-612` | несвежие выходы или `CompileError` | да |
| 10 | Размер-бюджеты G19 | `release.py:614-616` | см. §10 | да |
| 11 | Провенанс ассетов согласован | `release.py:618-626` | разрыв цепочки; предупреждения → WARN | да |
| 12 | DAZ-декларации рендеров | `release.py:628-637` | ошибка в `*.render.yaml`; неотрендеренные выходы → WARN | да |
| 13 | VaM-декларации сцен | `release.py:639-648` | ошибка; при нуле деклараций — `PASS … 0 проверено` | да |
| 14 | Sims4-декларации сцен | `release.py:650-659` | то же | да |
| 15 | Покрытие переводов ≥ `loc/loc.yaml: release_coverage_min` | `release.py:661-687` | язык ниже порога (сейчас 0.98). Языки с `synthetic: true` (pseudo) исключаются по `game/tl/<lang>/language.json` | только если есть и покрытие, и порог |
| 16 | **Озвучка** | `release.py:689-704` | ошибки манифестов → FAIL; **непокрытые реплики в озвученных главах → FAIL**; черновые дубли → WARN | только если есть покрытие |
| 17 | Реестр лицензий ассетов | `release.py:706-714` | нарушение | только если деклараций > 0 |
| 18 | Хранилище сырцов | `release.py:716-730` | локально изменённые и не запушенные сырцы (G14); недоступное хранилище → WARN | да |
| 19 | `ci/release-manifest.json` версия == `project.yaml` | `release.py:732-740` | **никогда** — только WARN | да |
| 20 | git sha получен | `release.py:742-743` | **никогда** — WARN при `nogit` | да |
| 21 | Есть фикстуры сейв-корпуса | `release.py:745-749` | **никогда** — WARN при нуле фикстур (сейчас их 2) | да |

**Строк на экране может быть меньше, чем проверок:** безусловной `else`-ветки нет у трёх — №15 (молчит без `release_coverage_min`), №16 (молчит при пустом покрытии озвучки) и №17 (молчит при нуле лицензионных деклараций). На **этом** чекауте молчит только №17: порог покрытия задан, а озвучка демо-главы даёт WARN. VaM и Sims4 (№13-14) печатаются **всегда**, включая `0 проверено` — безусловный `else: add("PASS", …)`.

<a id="maturity-gate-rule"></a>
**Проверка №4 самоактивирующаяся — и сегодня она даёт WARN, а не FAIL. Прочитайте этот абзац, чтобы через месяц не удивиться внезапному FAIL.** Правило состоит из трёх ветвей, и переключаются они сами, без флага и без ручной донастройки (`early_content_checks`, `release.py:403-438`):

1. `early_content: true` (флейвор `patron`) → **PASS**: незрелые главы для такого флейвора штатны, статусы не разбираются вообще.
2. `early_content: false` **и в проекте нет ни одной главы `status: release`** → **WARN** `зрелость контента: ни одна глава ещё не доведена до status=release (ch01) — флейвор с early_content=false собирается, но гейт станет строгим с первой release-главой`. Это состояние текущего дерева: единственная глава `ch01_awakening` объявлена `draft`. Причина мягкости — в комментарии кода (`release.py:422-427`): требование «в публичном флейворе только зрелые главы» до первой зрелой главы **невыполнимо** — гейт запретил бы собрать что угодно, включая демо, а невыполнимый гейт учит игнорировать гейты. Поэтому до первой `release`-главы это предупреждение, а не отказ.
3. `early_content: false` **и хотя бы одна глава уже `status: release`** → прежняя строгость: `draft` → **FAIL**, `playtest` → **WARN**, незнакомый статус трактуется как `draft` (fail-closed).

**Что произойдёт при первой `release`-главе.** В тот же прогон, в котором вы поднимете статус любой главы до `release`, ветвь 3 включится сама — и все остальные незрелые главы станут блокерами публикации: `vn release validate --flavor public` покраснеет строкой `early_content=false, а в сборке главы status=draft: chNN — доведите до release или собирайте флейвором с early_content=true`, exit 1. Это не регрессия и не поломка конфигурации, а спроектированный момент включения нормы: с появлением первой зрелой главы «публичный флейвор = только зрелое» становится выполнимым требованием. Выходы те же три: довести главу до `status: release`, собирать флейвором с `early_content: true` (`patron`), либо осознанно объявить `early_content: true` и у `public`. Планируйте это заранее: релиз первой главы — это ещё и момент, когда решается судьба всех черновых.

Смысл проверки от смягчения не изменился: `draft` ослабляет граф-проверки конвейера до warnings (ненаписанная ветка легальна и у игрока станет «сцена недоступна» — [08-content-pipeline.md](08-content-pipeline.md) §7), а `playtest` проходит ровно те же строгие проверки, что `release`, и отличается только подписью выпускающего. Контент при этом **не вырезается** ни в одной ветви: главы уезжают в дистрибутив всегда (гейт логический, G9), а сейв игрока мог на них уже ссылаться — поэтому решение «показывать ли эту главу» принимается здесь, до сборки.

### 5.2 Реальный вывод (проверено 2026-08-18, HEAD `e3c2842` + текущая итерация)

```
$ vn release validate --flavor public
 PASS  project.yaml: схема валидна
 PASS  флейвор public: packs=['ep_beach'], nsfw=False, early=False
 PASS  пак ep_beach: manifest.yaml на месте
 WARN  зрелость контента: ни одна глава ещё не доведена до status=release (ch01) — флейвор с early_content=false собирается, но гейт станет строгим с первой release-главой
 PASS  lint: 0 ошибок, 0 предупреждений
 PASS  шрифты UI: 3/3 материализованы
 PASS  ассеты: свежи
 PASS  видео: собранные лупы валидны
 PASS  генерат: свеж
 PASS  бюджеты G19: в рамках
 PASS  провенанс: 0 цепочек согласованы
 PASS  DAZ-декларации: 0 проверено
 PASS  VaM-декларации: 0 проверено
 PASS  Sims4-декларации: 0 проверено
 PASS  покрытие переводов: все языки ≥ 98%
 WARN  озвучка: 14 черновых дублей (draft) — ru: ch01_s010_0001
 PASS  хранилище сырцов: локальные копии согласованы
 PASS  release-manifest: версия 0.1.5 == project.yaml
 PASS  git sha: e3c2842
 PASS  сейв-корпус: 2 фикстур
release validate: OK (флейвор public)      # exit 0
```

**20 строк: 18 PASS + 2 WARN + 0 FAIL, exit 0.** Оба WARN штатные: зрелость контента (№4 — в проекте пока нет ни одной `release`-главы, см. правило выше) и 14 черновых дублей озвучки. У `--flavor patron` вывод тоже зелёный, но чище — **21 строка** (20 PASS + 1 WARN, exit 0): добавляется `пак nsfw: manifest.yaml на месте`, а зрелость даёт `PASS early_content=true: незрелые главы для этого флейвора штатны`. **Оба флейвора сегодня собираются**; красный `public` был состоянием предыдущей ревизии гейта, до смягчения №4.

**«Все PASS» не эталон.** Жёлтые строки про 14 черновых дублей и про зрелость контента — **штатное** состояние дерева с одной черновой демо-главой (её озвучили TTS-заглушками). Штатные WARN сегодня три класса: зрелость контента до первой `release`-главы, черновые дубли озвучки и (если сорвётся сеть/хранилище) недоступность объектного хранилища. Ничего искать не нужно — релиз валит только FAIL.

**Отдельно про озвучку:** проверка №16 даёт **FAIL**, если в главе, для которой уже есть voice-манифест, часть реплик не покрыта (`vo.holes`). То есть «начать озвучивать половину главы» — красный релиз, а не промежуточное состояние: игрок слышал бы обрыв посреди диалога. Либо озвучиваете главу целиком (пусть черновиками), либо не начинаете. Подробности — [23-audio.md](23-audio.md) §8.

Опечатка в имени флейвора обрывает гейт на второй строке:

```
$ vn release validate --flavor steam
 PASS  project.yaml: схема валидна
 FAIL  флейвор 'steam' не описан в project.yaml (есть: patron, public)
ошибка: release validate --flavor steam: есть FAIL      # exit 1
```

### 5.3 Чего гейт НЕ проверяет

Пробелы реальные, знать их обязательно:

- **пин `renpy_sdk`** — только `vn doctor`;
- **`save_schema`** — ни соответствия миграций, ни бампа; ловится лишь косвенно через `vn save corpus`;
- **`cold_start_s`** — живёт исключительно внутри `vn test smoke` (`cli.py`), которого релизный workflow не запускает; **релиз может уехать за бюджет холодного старта**;
- **бюджет памяти сцены** — он в `vn build` (`cli.py`), а не в гейте; но так как `release build` сам зовёт `vn build` первым шагом, на этом пути он всё-таки проверяется;
- **движковый `renpy … . lint`** — только в `ci.yml:86` и `canary.yml`;
- **`vn test oversample`** — только `ci.yml:90-91`;
- **smoke-прохождение** — только nightly/canary ([27-testing.md](27-testing.md));
- **`min_tools`** из `project.yaml:4` — не сравнивается ни с чем;
- **платформа** — Steam-проверок в гейте нет ни одной; `steam_libs_status` зовётся только из `vn release steam` (`cli.py`) и тестов;
- **профиль ассетов** — `grep profile tools/vn/src/vn/release.py` = 0: гейт не отличит draft-артефакт от full. Единственная защита — `release build` навязывает `full` сам (§2).

Ещё одна тонкость: проверка №8 «генерат свеж» на пути `vn release build` **тавтологична** — генерат собран тем же процессом за секунду до гейта (§6.1). Смысл она имеет только при отдельном запуске `vn release validate`.

---

## 6. `vn release build --flavor <f>` — полная последовательность

`cli.py`. Опции: `--flavor` (обязательна), `--patron-token`, `--package` (можно несколько, по умолчанию `("win",)`), `--timeout` (900 с).

1. **`vn build --profile full` — ДО гейта** (`cli.py`, `ctx.invoke(build, check=False, profile="full")`), с печатью `сборка перед гейтом (флейвор <f>)…`.
2. **Гейт** `validate_release(root, flavor)` (§5). Любой FAIL → `_fail("release build --flavor <f>: гейт не пройден")`, exit 1.
3. **`compute_build_info` + `write_build_info`** → `game/build_id.json` (`cli.py`).
4. **Уведомления о сторонних лицензиях**: `docs/licenses/THIRD-PARTY-NOTICES.md` копируется в `game/THIRD-PARTY-NOTICES.md` (`cli.py`).
5. Печать `build-id: …` и, если `exclude` непуст, `(исключено: …)` (`cli.py`).
6. **`vn package`** с `dest_suffix=f"-{flavor}"` (`cli.py`) — см. §7. Внутри он **ещё раз** прогоняет `vn build`.
7. **`build-info.json`** пишется в `build/dist/<version>-<flavor>/` (`cli.py`) — обязательно после package, потому что package чистит каталог назначения.
8. **`finally`** (`cli.py`): удаляются `game/build_id.json` и `game/THIRD-PARTY-NOTICES.md` — даже при падении. Рабочий чекаут не остаётся с чужим флейвором.
9. `release build: OK — <build_id> -> build/dist/<version>-<flavor>/` (`cli.py`).

### 6.1 Почему сборка идёт ДО гейта

Комментарий в коде (`cli.py`) объясняет ровно это: в свежем чекауте CI **генерата нет вовсе** — `game/generated/` в `.gitignore:2`. Проверка №8 «генерат свеж» валила бы каждый релиз. Второй аргумент из того же комментария: так гейт проверяет ровно то состояние, которое уедет в дистрибутив, а не предыдущее.

Регрессию именно этого класса ловит nightly: он делает `rm -rf game/generated` и после этого гоняет оба флейвора (`nightly.yml:67-74`, комментарий там же: «ловит регрессии вида „гейт требует генерат, которого в CI ещё нет“»).

Плата за схему — `vn build` выполняется дважды (шаг 1 и внутри package). На прогретом кэше второй прогон почти бесплатен; в холодном CI это заметные секунды.

### 6.2 Разбор имени архива

| Часть | Откуда |
|---|---|
| `vn` | `build.name = "vn"` (`game/options.rpy:21`) |
| `0.1.6+<sha>` | `config.version` из `game/generated/version.gen.rpy`; эмиттер `_emit_version` (`tools/vn/src/vn/content/compile.py:95-100`) склеивает `project.yaml: version` с `git rev-parse --short HEAD` (`repo.py:35-43`; при отсутствии git — `nogit`) |
| `win` | значение `--package`, переданное в `launcher distribute` (`distribute.rpy:1501`: `filename = base_name + "-" + variant`) |
| `.zip` | формат, объявленный для пакета `win` в `$RENPY_SDK/renpy/common/00build.rpy:426` |

Проект **не задаёт** `build.directory_name` и `build.version`, поэтому имя целиком выводится движком из `build.name` и `config.version`.

**Флейвора в имени архива нет.** `public` и `patron` одной версии отличаются только вкомпилированным git-sha и каталогом-родителем `<version>-<flavor>/`. Перепутать файлы на диске легко — не переименовывайте их и не складывайте в одну папку.

---

## 7. `vn package` — как вызывается Ren'Py SDK

`cli.py`. Опции: `--package` (multiple, дефолт `win`; help: «Целевые пакеты launcher distribute (win/linux/mac/market)»), `--timeout` (900), `--dest-suffix` (**скрытая**, ей пользуется только `vn release build`).

**Поиск SDK — только через переменную окружения.** `doctor.sdk_path()` читает `RENPY_SDK` и принимает путь, лишь если `<RENPY_SDK>/renpy.py` — файл. Ни PATH, ни ключа в конфиге, ни автопоиска. Нет → `_fail("Ren'Py SDK не найден (RENPY_SDK)")`. Исполняемый файл: `renpy.exe` на `win32`, иначе `renpy.sh` (`cli.py`).

Шаги:

1. `ctx.invoke(build, check=False, profile="full")` — генерат `.rpy` обязан существовать до восстановления `.rpyc` (`cli.py`).
2. Перенос `.rpyc` прошлого релиза (`cli.py`) — §8.
3. `subprocess.run([exe, root, "compile"], capture_output=True, timeout=timeout_s)` (`cli.py`). Ненулевой код → `_fail("renpy compile упал:\n…")` с хвостами stdout (1500 симв.) и stderr (800).
4. Дистрибуция (`cli.py`): `dest = build/dist/<version><dest_suffix>`, каталог **удаляется целиком** перед сборкой («старые архивы не должны вкладываться в новые»), затем
   ```python
   cmd = [str(exe), str(sdk / "launcher"), "distribute", "--dest", str(dest)]
   for p in packages: cmd += ["--package", p]
   cmd.append(str(root))
   ```
5. Снимок `.rpyc` нового релиза (`cli.py`) — §8.
6. `package: OK — <имена файлов в dest>` (`cli.py`).

### 7.1 Пакеты `launcher distribute`: форматы и статус у нас

Значение `--package` CLI не валидирует и передаёт как есть. Что объявлено движком (`$RENPY_SDK/renpy/common/00build.rpy:421-432`) и что из этого мы используем:

| `--package` | Формат(ы) | Файл на выходе | У нас |
|---|---|---|---|
| `win` | `zip` (`:426`) | `vn-<ver>-win.zip` | **используется** (дефолт CLI, CI) |
| `linux` | `tar.bz2` (`:424`) | `vn-<ver>-linux.tar.bz2` — **не zip** | используется в CI; Steam-staging распаковывает именно этот формат (§14.2) |
| `mac` | `app-zip app-dmg` (`:425`) | `vn-<ver>-mac.zip`; **dmg НЕ создаётся** | используется в CI |
| `pc` | `zip` (`:423`) | Windows+Linux одним зипом | не используется |
| `market` | `bare-zip` (`:427`) | зип без каталога-обёртки | не используется |
| `steam` | `zip`, **hidden** (`:429`) | `vn-<ver>-steam.zip`, windows+linux+mac в одном | не используется: раскладка депотов собирается из платформенных пакетов (§14.2) |
| `android` / `ios` / `web` / `gameonly` | `directory` / `null`, hidden | — | NOT IMPLEMENTED (ни `rapt`, ни `.aab`, ни `.apk` в `tools/` нет) |

**Почему `--package mac` не даёт dmg.** `distribute.rpy:1537-1540`: `if dmg and (mac_identity is None): return` — формат `app-dmg` пропускается, если не задан `build.mac_identity`. Проект его не задаёт (grep по `game/options.rpy` — только `build.name` и `build.classify`), поэтому от `mac` приходит **только zip**. Именно поэтому dmg собирает отдельная джоба `release.yml:95-115` штатным `hdiutil` на macOS-раннере. Следствие для QA: артефакт для mac **не подписан и не нотаризован** (стадия 8 в §13).

**`--timeout` покрывает оба subprocess-вызова** (компиляцию и дистрибуцию) по отдельности. Дефолт 900 с хватает локально; CI ставит 1800 (`release.yml:83`), потому что три платформы сразу.

### 7.2 Что не уезжает в дистрибутив

`game/options.rpy:19-58`, всё через `build.classify(…, None)`: исходные зоны `tools/** content/** assets_src/** loc/** docs/** ci/** packs/** build/** .vncache/** .git/**`, дотфайлы, `CODEOWNERS`, `README.md`, `project.yaml`, `.vnstorage.yaml`, `hdrs.tmp`, `log.txt`, `traceback.txt`, `errors.txt` (цикл `:24-29`); плюс `game/framework/90_debug/**` (`:31`), `game/generated/qa/**` (`:32`), `game/generated/manifest.json` (`:33`); плюс каждый `game/tl/<code>/**`, у которого в `language.json` стоит `"synthetic": true` (то есть pseudo, `:36-47`, [14-localization.md](14-localization.md)); плюс глобы флейвора (`:51-58`).

**`.rpa`-архивов нет — и это норма, а не недоделка.** Вызова `build.archive(...)` нет нигде в `game/`; ассеты едут россыпью — `../ARCHITECTURE.md` §2.4 фиксирует это осознанно: Steam дельта-патчит отдельные файлы, монолитный `.rpa` при правке одного спрайта перекачивался бы игроками целиком, а защиты упаковка не добавляет. Инвариант закреплён гард-тестом `test_options_rpy_ships_assets_loose_without_rpa` в `tools/vn/tests/test_release.py`.

---

## 8. `.rpyc` как релизный артефакт (G6)

**Зачем.** Ren'Py хранит в сейвах и в журнале rollback *имена стейтментов* (файл + версия + серийный номер). При перекомпиляции изменённого `.rpy` имена неизменившихся стейтментов сохраняются **только если рядом лежит старый `.rpyc`**. Поэтому `.rpyc` для нас — не мусор, а релизный артефакт: без него старые сейвы игроков перестают попадать «в то же место» истории.

**Восстановление** (`cli.py`):

- каталоги в `build/rpyc-cache/` сортируются функцией `_semver_key` (`cli.py`: `"0.1.6"` → `(0,1,6)`; нечисловое имя → `(0,)`), берётся **самый старший по версии**, а не самый свежий по времени;
- для каждого `*.rpyc`: цель `game/<rel>`; если рядом нет одноимённого `.rpy`, пробуется `game/generated/<rel>` (legacy-раскладка кэша);
- копирование **с перезаписью** — канонический носитель имён это кэш релиза, а не локальные `.rpyc`;
- `restored == 0` при существующем кэше → `_fail("rpyc-перенос: кэш … есть, но не восстановлено ни одного .rpyc — save-совместимость под угрозой (G6), сборка остановлена")`;
- кэша нет → печатается `rpyc-перенос: кэша прошлых релизов нет (первый релиз)` и сборка идёт дальше.

**Снимок** (`cli.py`): после distribute `build/rpyc-cache/<version>/` очищается и туда копируются **все** `.rpyc` из-под `game/` — не только из `generated/`, потому что метки framework тоже попадают в сейвы и rollback.

**Каталога `build/` в чистом чекауте нет** (`.gitignore:20`), поэтому все «замеры на диске» про `build/rpyc-cache/` и `build/dist/` — снимок конкретной машины, а не свойство репозитория. На новой машине первый `vn package` честно скажет «первый релиз»: настоящий носитель линии имён — кэш GitHub Actions (`release.yml:71-76`).

**Проблема: кэш ключуется версией, а не флейвором.** `save_dir = cache_root / version` (`cli.py`). Оба флейвора одной версии пишут в один каталог — кто собрался последним, тот и записал. Практических расхождений сегодня нет (исключение работает на уровне `build.classify`, а не на уровне набора `.rpy`), но гарантий тоже нет. CI обходит это своим слоем: `actions/cache` ключуется по флейвору — `key: rpyc-${{ matrix.flavor }}-${{ github.ref_name }}` (`release.yml:71-76`).

**Отдельная сущность, не путать: линия имён сейв-корпуса.** `ci/fixtures/rpyc-line/` — **52 `.rpyc`**, **единственные `.rpyc` в git** (негативное правило `.gitignore:12-14`). Ими управляют `_rpyc_line_restore` (`cli.py`) и `_rpyc_line_snapshot` (`cli.py`) вокруг `vn save corpus`, чтобы фикстуры в `ci/fixtures/saves/` (сейчас **две** — `schema1-demo.save` и `schema2-demo.save`) грузились детерминированно на любой машине. Подробности — [27-testing.md](27-testing.md).

**Регрессионной джобы `rpyc-compat` не существует.** Ничто не проверяет, что перенос имён реально работает: нет ни workflow, ни флага. NOT IMPLEMENTED.

---

## 9. Версионирование

| Поле | Где | Правило | Кто проверяет |
|---|---|---|---|
| `version` | `project.yaml:2` | semver: патч — фиксы, **новая глава = minor**, мажор — сезон/сеттинг | схема `^\d+\.\d+\.\d+$`; `release.yml:47-54` сверяет с тегом (hard fail); `release.py:680-688` сверяет с `ci/release-manifest.json` (**только WARN**) |
| `save_schema` | `project.yaml:3` | целое, бампает tech-lead при несовместимом изменении vars | схема `integer, minimum: 1`. Эмитится как `define vn_build_save_schema` в `game/generated/state/defaults.gen.rpy`; сравнение и миграции — `020_state.rpy`. **В гейте проверки нет** |
| `min_tools` | `project.yaml:4` | минимальная версия `vn` для дерева контента | **никто** — сравнения с `vn.__version__` (`0.1.0`) в коде нет; `vn doctor` только печатает оба числа |
| `renpy_sdk` | `project.yaml:5` | пин SDK (G18); апгрейд — отдельным PR с прогоном canary | только `vn doctor`. Продублирован руками как `RENPY_VERSION` в `ci.yml:26`, `nightly.yml`, `release.yml:19` — **автопроверки согласованности нет** |
| `config.version` | генерат | `{version}+{git-short-sha}` (`compile.py:95-100`) | это, а не `build_id`, даёт имя архиву |
| версия пака | `packs/<id>/manifest.yaml` | `^\d+\.\d+\.\d+$` | связи «бампнул ядро → бампни пак» нет |
| версия `vn` | `tools/vn/pyproject.toml` и `tools/vn/src/vn/__init__.py` | `0.1.0`, продублирована руками | — |

**Версия игры и версия тулинга независимы.** Игра — `0.1.5`, `vn --version` — `0.1.0`. Это не рассинхрон, это два разных счётчика.

**Pre-release-теги невозможны.** Схема `project@1` требует `version` строго `^\d+\.\d+\.\d+$`, а гейт тега требует точного совпадения: `v1.0.0-rc1` не пройдёт ни там, ни там. Значит и «release candidate» у нас — не отдельная версия, а **состояние** (§13, стадия 8): та же `0.1.6`, выложенная в бета-ветку Steam.

**Бамп `save_schema` — точка невозврата.** Игрок, который сохранился на новой схеме, не сможет играть на старой сборке: `after_load` увидит `_loaded_schema > _target_schema`, вызовет `renpy.block_rollback()`, покажет `ui.flow.save_from_newer` и сделает `renpy.full_restart()` (`020_state.rpy`). Понижать `save_schema` нельзя никогда, откатывать релиз с бампом — §17.

Ветки, теги и формат коммитов — [04-development-workflow.md](04-development-workflow.md) §3.

---

## 10. Бюджеты: размерные G19 плюс память сцены

`vn build` может упасть на бюджетах **двумя разными способами** — `_check_budgets()` (`cli.py`, вызовы на `cli.py` и `:156`) проверяет и размеры, и модель памяти образов.

### 10.1 Размерные бюджеты (G19)

Реализация — `budget_failures()` (`release.py:29-54`), читает `project.yaml: budgets` (`:57-65`).

| Бюджет | Значение | Что меряется | Факт на 2026-08-18 |
|---|---|---|---|
| `assets_total_mb` | **20000** | `game/assets/` | десятки МБ |
| `generated_total_kb` | **65536** | `game/generated/` | десятки КБ |
| `video_total_mb` | **8000** | `game/assets/mov/` | < 1 МБ |
| `video_file_mb` | **512** | каждый `mov/**/*.webm` | 1 файл |
| `cold_start_s` | 30 | init → первая интеракция | **не в `budget_failures`** |

Комментарий в `project.yaml:58-60` объясняет, почему числа именно такие: это **предохранители от аварии** (зацикленный экспорт, забытый 8K-вариант), а не потолок игры — «8–15 ГБ качественного контента — норма жанра» (ADR-0012). Не оптимизируйте под них: они не узкое место, и упрутся сотнями глав позже, чем всё остальное.

`video_file_mb` дополнительно передаётся в `videomod.validate_all(root, file_budget_mb=…)` (`release.py:540-541`), поэтому перевес одного `.webm` даёт **две** строки — в проверке №7 и в №9. Это не баг, просто не пугайтесь дубля.

### 10.2 Бюджет памяти сцены (ADR-0012)

Второй, менее известный fail-режим `vn build`: `assets.memory.analyze(root)` считает худшую сцену и сравнивает с бюджетом, выведенным из `render.image_cache_mb` и `render.cache_generations`. Провал → `_fail("бюджет памяти сцены превышен (project.yaml: render.image_cache_mb)")`.

Живой вывод сборки на HEAD:

```
память: худшая сцена ch01_s030 — 28.5 Мпикс из 89.5 (масштаб @2)
```

Детальный разбор — отдельной командой (`cli.py`):

```
$ vn assets memory
кэш образов: 1024 МБ -> 268 Мпикс; бюджет сцены 89.5 Мпикс (3 поколения), масштаб @2
  ch01_s030           28.5 Мпикс    32%
      ui+текстбокс                    4.17
      bg rooftop/day                 11.11
      mira (a)                        1.48
      shot sunset                    11.79
  …
рекомендуемый render.image_cache_mb: 327
память: OK
```

**Этого бюджета в релизном гейте нет** — только в `vn build`. На пути `vn release build` он всё равно исполняется (шаг 1), но при отдельном `vn release validate` — нет. Подробности модели — [16-assets.md](16-assets.md), [32-performance-and-scalability.md](32-performance-and-scalability.md).

### 10.3 Что делать при превышении

| Бюджет | Первое действие |
|---|---|
| `assets_total_mb` | `vn assets status`; лишние выходы удаляются как осиротевшие при `vn assets build` ([16-assets.md](16-assets.md)) |
| `video_total_mb` / `video_file_mb` | поднять `crf` или укоротить луп ([21-video-generation.md](21-video-generation.md)); менять пресет, а не бюджет |
| `generated_total_kb` | реальная причина — рост числа сцен; бюджет поднимается осознанно, вместе с ADR |
| память сцены | `vn assets memory --top 10`: смотреть, какой слой съел бюджет; чаще всего это раздутый холст или лишний альфа-пиксель |
| `cold_start_s` | `vn test smoke --picks 0,0` локально и профилирование init ([32-performance-and-scalability.md](32-performance-and-scalability.md)) |

Поднятие числа в `project.yaml` — легальный, но **последний** ход, и он идёт отдельным коммитом с обоснованием, а не в составе релизного.

---

## 11. CHANGELOG — PARTIALLY IMPLEMENTED

`vn release changelog` (`cli.py` → `update_changelog()`). Единственный флаг — `--force`.

0. **Гейт версии** (`released_version_conflict`, 2026-08-18): если раздел `## <version>` уже есть в `../CHANGELOG.md` или существует тег `v<version>` — команда отказывается работать и требует бампнуть `project.yaml: version`. Причина не в дублировании заголовка: манифест после прогона становится базой следующего диффа, поэтому прогон на уже выпущенной версии **съедает дифф** — сцены, добавленные после релиза, в блок следующей версии не попадут вовсе. Именно так и произошло 2026-08-18 (раздел `## 0.1.5` появился второй раз, дифф `ch90` был съеден; и то, и другое отменено вручную). `--force` оставлен для перезаписи после ручной правки CHANGELOG.
1. `snapshot_content(root)` обходит зоны `repo.chapter_zones` — `content/chapters/` **и** `packs/*/chapters/`, даёт `{ch_id: {status, scenes[], pack}}`.
2. Предыдущее состояние читается из `ci/release-manifest.json` (`.chapters`).
3. Дифф: новые главы, новые сцены, удалённые сцены.
4. Если что-то изменилось — блок вставляется сразу после первой строки `../CHANGELOG.md`.
5. `ci/release-manifest.json` перезаписывается целиком (`release_manifest@1`, `indent=1, sort_keys=True`).
6. `stamp_id_registry()` (`release.py:126`) — append-only объединение в `content/registry/id_registry.json`. `_released_ids()` (`release.py:69`) собирает **только главы со `status: "release"`**; если released-сцен нет, штамповать нечего.

**Реальность.** `ci/release-manifest.json` сейчас: версия `0.1.5`, одна глава `ch01` (`draft`, 3 сцены). `content/registry/id_registry.json` состоит из пустых массивов, потому что `ch01` — `draft`; страховка G7 инертна. Проза для игрока в `../CHANGELOG.md` (включая большой раздел «Не выпущено») написана руками: генератор умеет говорить только про главы и сцены.

**Ограничения (NOT IMPLEMENTED):** нет `--from <tag>`, нет `--audience player|internal`, нет диффа между git-тегами, нет пер-релизных `releases/<version>.yaml`. Главы паков в манифест и в блок попадают с 2026-08-18 (в блоке помечены `(pack <id>)`), но проза для игрока по-прежнему пишется руками.

**Порядок:** бамп `project.yaml: version` → `vn release changelog` → проза. Первый шаг теперь обязателен механически (гейт версии), последний — по-прежнему по дисциплине: генератор вставляет свой блок выше вашего текста.

---

## 12. CI/CD

Живой пайплайн — GitHub Actions: **5 workflow, 10 определений джоб** (на теге релизная `build` разворачивается матрицей в 2 прогона; ночная `corpus` добавлена 2026-08-18). Общее для всех: `actions/checkout@v4` с `with: {lfs: true}`, Python 3.12, установка тулчейна двумя шагами — `pip install --quiet -r tools/vn.lock` и следом `pip install --quiet -e "tools/vn[dev]"` (лок первым, G17), `SDL_AUDIODRIVER: dummy`, `PYTHONIOENCODING: utf-8`, движок под `xvfb-run -a` (headless-режима у Ren'Py нет, G23). Везде, где джоба доходит до `vn build`, раньше него ставится `ffmpeg`.

**Эти инварианты — не соглашение, а тест.** `tools/vn/tests/test_ci_config.py` (**14 тестов**) парсит YAML конфигов и проверяет в том числе: (а) перед каждой editable-установкой идёт `pip install -r tools/vn.lock` (мест установки — 8, по джобе); (б) в каждой GitHub-джобе, которая зовёт `vn build` или `vn release build`, `ffmpeg` ставится раньше; (в) вариантные прогоны и корпус масштаба живут в `nightly`, а не в `ci` (G15: MR-пайплайн держим под 10 минут); (г) `vn release android preflight` стоит **после** `vn build` — на пустом `game/` он зелен всегда, и гейт был бы ложно-зелёным; (д) провал внешнего тулчейна не заглушён `|| true` / `continue-on-error`, а `voice tts` в CI пиннует бэкенд флагом; (е) масштаб корпуса задан явно и ограничен потолком; (ж) pytest запускается из `tools/vn`; (з) второго конфига CI в репозитории нет — половинчатое зеркало опаснее его отсутствия (`.gitlab-ci.yml` выведен 2026-08-18).

| Workflow | Триггер | Джобы | Ключевые шаги | Артефакты |
|---|---|---|---|---|
| `ci.yml` | push в любую ветку, dispatch | `lint`; `build-test` (needs `lint`) | `vn content lint`; кэш SDK; `vn build` → `vn loc keys --check` → `renpy.sh . lint` → **`vn test oversample --scale 2`** → **`vn release android preflight --bundle`** (после сборки: на пустом `game/` проверка зелена всегда) → **шаг `must_fail`** (отсутствие RAPT и piper обязано давать НЕнулевой код с именем тулчейна в выводе) → `vn content compile --check` → `pytest -q` из `tools/vn` (`working-directory`) | `generated-<sha>` = `game/generated/`, 30 дней |
| `nightly.yml` | cron `30 2 * * *`, dispatch | `smoke`; `controller-first`; **`corpus`** | `smoke`: `vn build`; `vn loc import`; `vn loc report`; smoke-матрица из 4 прогонов (`:57-60`); `vn save check` + `vn save corpus` (`:62-65`); **`rm -rf game/generated` → `vn release build --flavor public --package win` и то же для patron** (`:70-74`). `controller-first`: матрица двух профилей (`RENPY_VARIANT="steam_deck medium touch"` и `steam_big_picture`, `:97-105`) → `vn build` → `vn test smoke --picks 0,0` с `VN_AUTOPILOT_SCREENS=main_menu,preferences,gallery,chapter_select` (`:138-144`). **`corpus`**: свой checkout с LFS, SDK, ffmpeg → `xvfb-run -a vn test corpus --scenes 600 --images 400 --videos 2 --lines 8 --vars 100` — измерительный прогон конвейера на синтетическом проекте вне репозитория ([32 §7.5](32-performance-and-scalability.md)) | `smoke-shots-<run_id>`; `controller-shots-<profile>-<run_id>` — оба `.vncache/smoke/`, 7 дней, `if: always()`; у `corpus` артефактов нет — числа в логе джобы |
| `canary.yml` | cron `0 3 * * 1`, dispatch | `fresh-renpy` | берёт **самый свежий** Ren'Py с `renpy.org/latest.html`, подменяет `RENPY_SDK` через `$GITHUB_ENV`, гоняет `vn build` → `renpy.sh . lint` → `pytest` (в подоболочке из `tools/vn`) → `vn test smoke --picks 0,0` | — |
| `release.yml` | push тега `v*` | `build` (matrix `flavor: [public, patron]`, `fail-fast: false`); `dmg`; `publish` | сверка тега с `project.yaml` (`:47-54`); кэш SDK; кэш `build/rpyc-cache` **на флейвор** (`:71-76`); `vn release build --flavor <f> --package win --package linux --package mac --timeout 1800` (+`--patron-token` из secrets только для patron) | `dist-public`, `dist-patron` (7 дней); `dmg`; GitHub Release |
| `steam-upload.yml` | **только** `workflow_dispatch` (входы `flavor`: public/patron, `branch`: по умолчанию `beta`) | `upload` | `vn release build --flavor <f> --package win/linux/mac` → `vn release steam --flavor <f> --branch <b>` → steamcmd (`+login … +run_app_build`). Кэш `.rpyc` — **restore-only** (ручная выкладка не должна становиться источником релизной линии, G6); `concurrency: steam-upload` без cancel-in-progress (аккаунт-билдер один) | `steam-vdf-<flavor>-<run_id>` — только сгенерированный VDF, 7 дней |

**`steam-upload` не привязан к тегу намеренно** — «эта сборка уходит игрокам» решает человек. Без секретов `STEAM_USERNAME` и `STEAM_CONFIG_VDF` (base64 сентри-файла Steam Guard, снятого один раз вручную) шаг аплоада — no-op с `::notice::` и зелёным выходом: сборку и VDF можно проверить до появления аккаунта. Пока `platform.steam.appid` в `project.yaml` равен `null`, workflow осознанно падает раньше — на шаге `vn release steam` («заполните App ID»). Что нужно донастроить руками — `ci/steam/README.md`.

**Разделение публикации — политика CI, а не кода.** В GitHub Release уходит только `dist-public` + dmg (`release.yml:117-135`, `gh release create … --generate-notes --verify-tag`; маска поиска — `*.zip`, `*.tar.bz2`, `*.dmg`). `dist-patron` остаётся артефактом workflow на 7 дней для ручной раздачи по своим каналам.

**`dmg` не требует движка:** macos-раннер берёт `*-mac.zip` из `dist-public`, распаковывает, находит `.app` и делает `hdiutil create -volname "VN" -format UDZO` (`release.yml:95-115`). См. §7.1 о том, почему launcher сам dmg не отдаёт.

**Долги CI, которые касаются релиза:**

- Второго пайплайна больше нет: `.gitlab-ci.yml` (3 джобы против 8, без релиза, флейворов, LFS, ffmpeg и кэша `.rpyc`) выведен из эксплуатации 2026-08-18, `../../CODEOWNERS` теперь покрывает `/.github/`.
- `canary.yml` не имеет `continue-on-error`: красный canary валит workflow. Это строже, чем `allow_failure: true` из `../ARCHITECTURE.md`, и это осознанное расхождение.
- Не существует ни одной из джоб `rpyc-compat`, `screens`, `nightly-paths`, `nightly-perf`, `steam-publish`, матрицы `PLATFORM: [win, mac, linux, android]` и шага `vn validate --budgets --dist dist/` — всё NOT IMPLEMENTED (команды `vn validate` нет вовсе). Мобильный канал в CI присутствует, но **только арифметикой**: `vn release android preflight --bundle` считает предпосылки по `game/`, а сборки APK/AAB в CI нет. Причина не техническая — тулчейн ставится командой (`vn release android setup sdk --download-rapt`), — а в цене и в секретах: ~700 МБ Android SDK на каждый пуш и ключ подписи в раннере. Локально APK собран и вскрыт ([39 §2.1.1](39-platforms.md)).
- **QA на живом железе не автоматизировано ничем**: ни Windows-, ни mac-, ни Deck-прогона в CI нет; всё это стадии 5-7 §13, и все они ручные.

---

## 13. Сквозной маршрут релиза: девять стадий

Здесь собран практический путь целиком. Стадии 1-3 автоматизированы, 4-9 — процесс, и часть его сегодня **невозможна** (нет App ID и физического Deck) — это помечено явно.

Общее условие для всего, что дальше стадии 2: `export RENPY_SDK=/путь/к/renpy-8.5.3-sdk` и зелёный `vn doctor` (8 PASS: Python, git, git-lfs, корень репозитория, `project.yaml`, реестр схем — 39, шрифты UI 3/3, пин SDK 8.5.3).

### Стадия 1. Development

| | |
|---|---|
| **Команда** | `vn dev` (watch + запущенная игра, ассеты в `draft`) либо `vn build` + `vn play` |
| **Условия** | `RENPY_SDK`; для `vn play` — непустой `game/generated/manifest.json` |
| **Expected output** | `vn build`: `assets: … собрано, … из кэша, N актуально, … осиротевших удалено` → `generated: N записано, M без изменений, K осиротевших удалено` → `память: худшая сцена <id> — X Мпикс из Y (масштаб @2)` → зелёное `build: OK`. `vn dev`: `игра запущена; watch активен`, дальше на каждую правку `content изменился — компиляция… / готово — Shift+R в игре` |
| **Типичные ошибки** | `lint: N ошибок — сборка остановлена` (диагноз — в строках `error:` выше); `внутренняя ошибка компилятора: KeyError…` (битый YAML прошёл мимо линта — прогоните `vn content lint`); `бюджеты G19 превышены`; `бюджет памяти сцены превышен`; `game/generated/ пуст — сначала vn build` от `vn play` |
| **Как проверить** | глазами в игре (Shift+R перезагружает); `vn content compile --check` → `check: генерат свеж` |
| **Грабля стадии** | `vn dev` собрал ассеты в `draft` → следующий `vn build --check` красный «источник изменился». Перед push всегда один полный `vn build` (§2) |

### Стадия 2. Local QA

Всё, что CI делает на push, плюс то, чего CI не делает. Порядок — от дешёвого к дорогому.

| Команда | Expected output (проверено на HEAD) | Что ловит |
|---|---|---|
| `vn content lint` | `lint: 0 ошибок, 0 предупреждений` | схемы, графы, id, LFS-покрытие бинарей |
| `vn loc keys --check` | `loc keys --check: все строки с id, ledger свеж` | say-id и ledger разошлись с текстом (G8) |
| `vn content compile --check` | `check: генерат свеж` | несвежий генерат, разметка переводов, бюджеты |
| `python -m pytest tools/vn/tests -q` | `400 passed` | тулинг; **из venv проекта** — системный python без `yaml`/`blake3` даст ошибки коллекции |
| `bash "$RENPY_SDK/renpy.sh" . lint` | движковый отчёт без ошибок | то, что видит только Ren'Py: битые метки, отсутствующие образы |
| `vn test oversample --scale 2` | `oversample: OK` | что 4K-варианты реально подхватываются движком (ADR-0012) |
| `vn loc report` | `de: 136/136 (100%), fuzzy: 0` и так для каждого языка | покрытие переводов (гейт — не здесь, а в `release validate`) |
| `vn voice validate` | `voice: OK (драфтов: 14, непокрыто: 0)` | дыры в озвученных главах — будущий FAIL гейта |
| `vn pack validate` | ` ✓ ep_beach: dlc v1.0.0, api_level [1, 2) (фасад 1)` … `pack validate: OK (2 паков)` | несовместимый пак |
| `vn save check` | ` ✓ schema1-demo.save: schema 1, версия 0.1.4+dd1cb3e, сцена ch01_s010` … `save check: OK (2 фикстур)` | структура фикстур (оффлайн, без движка) |
| `vn save corpus` | `линия имён: 52 .rpyc восстановлено из ci/fixtures/rpyc-line/ (G6)` → по фикстуре ` ✓ …: OK: …; schema после загрузки: 2 (цель 2)` → `save corpus: OK (2 фикстур загружены и мигрированы)` | что старые сейвы грузятся и миграции доводят схему |
| `vn test smoke --picks 0,0` | `скриншоты: N -> …/.vncache/smoke` → `cold start (init -> первая интеракция): X.XX c` → `путь: …` → `smoke: OK: vn_end_of_content (N скриншотов)` | прохождение целиком + **единственная** проверка `cold_start_s` |

**Типичные ошибки стадии.** `smoke: игра упала с traceback` (хвост `traceback.txt` печатается тут же); `smoke: игра не завершилась за N c — прогон снят`; `cold start X c > бюджета 30 c (G19)`; `save corpus: N фикстур не прошли` (почти всегда — забытая миграция после бампа `save_schema`); `языка 'xx' нет в game/tl/ — выполните vn loc import`.

**Как проверить результат.** Скриншоты в `.vncache/smoke/` смотрят **глазами**: ни один автотест не видит сплющенную панель или обрезанный текст.

### Стадия 3. Build

| | |
|---|---|
| **Команда** | `vn release build --flavor public --package win --package linux --package mac --timeout 1800` (и то же для `patron`, при необходимости с `--patron-token`) |
| **Условия** | `RENPY_SDK`; чистое дерево; для полноценной линии имён — `build/rpyc-cache/<прошлая версия>/` или кэш CI |
| **Expected output** (по коду `cli.py`, `cli.py`) | `сборка перед гейтом (флейвор public)…` → вывод `vn build` → 20-21 строка гейта → `build-id: 0.1.6+<sha>.public.<YYYYMMDDHHMM>` → `rpyc-перенос: N файлов из релиза <ver> (G6, с перезаписью)` **или** `rpyc-перенос: кэша прошлых релизов нет (первый релиз)` → `distribute win, linux, mac -> build/dist/0.1.6-public …` → `rpyc-кэш релиза: N файлов -> build/rpyc-cache/0.1.6/` → `package: OK — <файлы>` → `release build: OK — <build_id> -> build/dist/0.1.6-public/` |
| **Типичные ошибки** | `Ren'Py SDK не найден (RENPY_SDK)`; `release build --flavor public: гейт не пройден` (смотрите строку FAIL); `rpyc-перенос: кэш … есть, но не восстановлено ни одного .rpyc` (кэш от другой раскладки — удалите каталог); `renpy compile упал:` / `distribute упал:` с хвостом лога SDK |
| **Как проверить** | `cat build/dist/0.1.6-public/build-info.json` — `flavor`, `version`, `sha`, `exclude`; затем состав архива скриптом из «Проверки» ниже: внутри обязан быть `game/build_id.json`, не должно быть `90_debug/` и `tl/pseudo/`, должен быть `THIRD-PARTY-NOTICES.md` |
| **Что получится** | `vn-<ver>-win.zip`, `vn-<ver>-linux.tar.bz2`, `vn-<ver>-mac.zip` (dmg — нет, §7.1) |

### Стадия 4. Steam test branch — **BLOCKED сегодня** (нет приложения в Steamworks)

| | |
|---|---|
| **Команда** | `vn release steam --flavor public --branch beta`, затем `steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit` |
| **Условия** | `platform.steam.appid` ≠ `null` **и** непустой `platform.steam.depots` в `project.yaml`; `ci/steam/app_build.vdf.tmpl`; собранный `build/dist/<version>-public/`; steam_api-библиотеки в `$RENPY_SDK/lib/py3-*/`; ветка `beta` **заранее создана в Steamworks** |
| **Expected output при успехе** | предупреждения о ненайденных депотах/библиотеках, затем `steam: build/steam/app_build_public.vdf готов; платформы: windows, linux, mac; аплоад: steamcmd +run_app_build (README)` (`cli.py`). В списке платформ будут ровно те, у которых объявлен депот |
| **Что мешает сегодня** | 1) в `project.yaml:13-15` только `appid: null` — команда падает `ошибка: platform.steam.appid не задан в project.yaml` (exit 1, проверено 2026-08-18); 2) ключа `depots` в файле нет вообще → после заполнения одного `appid` придёт второе исключение `platform.steam.depots пуст`. Это два **редактирования данных**, а не правки кода: раскладка депотов сама по себе рабочая и понимает форматы всех трёх платформ (§14.2). 3) Дальше в силе остаются внешние блокеры: steam_api-редистрибутивов Valve на build-машине нет, аплоад запускает человек, ветку `beta` нужно создать в Steamworks заранее, и ни один прогон на живом Steam/Deck ещё не делался. Релизное следствие механики: **любая** ошибка staging = `_fail("steam: контент депотов не собран")` **до** записи VDF (`cli.py`) — промежуточных состояний не бывает |
| **Как проверить** | `ls build/steam/` → `app_build_public.vdf` + `content/public/<platform>/`; открыть VDF и убедиться, что `AppID`, `SetLive` и номера депотов те, что нужно |

### Стадия 5. Steam Deck QA — частично, физического Deck нет

| | |
|---|---|
| **Команда (эмуляция вёрстки)** | `RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0` |
| **Почему работает** | `vn test smoke` наследует окружение процесса (`cli.py`: `env = dict(os.environ, VN_AUTOPILOT="1", …)`), а движок читает `RENPY_VARIANT` в `renpy/main.py:158-159` |
| **Тонкость, о которой легко забыть** | `RENPY_VARIANT` **заменяет** `config.variants` целиком (`main.py:159`: список из переменной + `[None]`). То есть штатных `pc`/`large`/`desktop` в прогоне не будет — это эмуляция набора вариантов, а не эмуляция Deck |
| **Expected output** | обычный `smoke: OK: vn_end_of_content (N скриншотов)`; ценность — в самих скриншотах: масштаб интерфейса 1.4, фуллскрин, ничего не срезано |
| **Чего этот прогон НЕ проверяет** | реального геймпада (событий `pad_*` в автопилоте нет), Steam-инициализации, оверлея, `dlc_installed`, экранной клавиатуры Deck |
| **Статус живого прогона** | **не проверялось** — физического Steam Deck нет; прогон на нём перед `setlive default` объявлен обязательным в `../../ci/steam/README.md` и остаётся невыполненным пунктом |

Ещё один вариант той же стадии — `RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0`: проверяет, что оверлеи отъехали от кромки на `gui.overscan_pad` ([39-platforms.md](39-platforms.md) §8).

### Стадия 6. Windows QA — ручная

| | |
|---|---|
| **Что делать** | распаковать `vn-<ver>-win.zip`, запустить `.exe`, пройти демо-главу, открыть галерею, историю, настройки, сменить язык, сохранить/загрузить |
| **Условия** | машина с Windows; артефакт из стадии 3 либо скачанный `dist-public` из `release.yml` |
| **Что смотреть** | `flavor` в вотермарке (для patron), отсутствие консоли и Shift+J (dev-зона вырезана), сейв грузится, `log.txt` рядом с игрой без строк `error` |
| **Автоматизации нет** | ни джобы, ни команды: `vn test smoke` гоняет игру из чекаута, а не из дистрибутива |
| **Известный пробел** | артефакт **не подписан** (нет `signtool` нигде в репозитории) — SmartScreen покажет предупреждение при первом запуске. Это RECOMMENDED FUTURE STATE, не текущее поведение |
| **Статус** | **не проверялось на этой машине** (darwin arm64) |

### Стадия 7. Mac / Linux QA — ручная

| | |
|---|---|
| **macOS** | распаковать `vn-<ver>-mac.zip`, запустить `.app`. Сборка **не подписана и не нотаризована**: `build.mac_identity` в `game/options.rpy` не задан, поэтому launcher даже dmg не делает (§7.1), а Gatekeeper будет ругаться на первый запуск. dmg из `release.yml:95-115` — обычный `hdiutil`, подписи в нём тоже нет |
| **Linux** | распаковать `vn-<ver>-linux.tar.bz2` (**не zip**), запустить `.sh`. На Deck поедет именно этот пакет |
| **Что смотреть** | старт без окна ошибки, шрифты (не «тофу»), звук, сейв/загрузка, `log.txt` |
| **Автоматизации нет** | единственная mac-джоба в CI (`dmg`) движок не запускает — она только упаковывает |
| **Статус** | **не проверялось**: mac-пакет на этой машине не собирался, Linux-машины нет |

### Стадия 8. Release candidate

RC у нас — **состояние, а не версия**: pre-release-теги запрещены схемой (§9). Практически это значит:

1. `project.yaml: version` уже бампнут до целевого (`0.1.6`), `vn release changelog` прогнан, проза дописана.
2. Оба флейвора собраны локально и прошли стадии 5-7 на том железе, которое доступно.
3. Артефакт выложен в **бета-ветку** Steam (`--branch beta`) или роздан узкому кругу как `dist-patron`.
4. Тег **ещё не поставлен**: тег запускает публикацию, поэтому он — последний шаг, а не первый.

Expected state перед переходом дальше: `git status --short` пуст, `vn release validate` зелёный по обоим флейворам, чеклист §15 закрыт.

### Стадия 9. Steam release

| | |
|---|---|
| **Команды** | `git tag v0.1.6 && git push --follow-tags` (→ GitHub Release), затем для Steam — `vn release steam --flavor public` + `steamcmd … +run_app_build …` и **вручную в Steamworks**: переключить default-ветку |
| **Условия** | зелёный `release.yml`; ветка `beta` проверена; App ID и депоты заполнены |
| **Expected output** | в GitHub — Release с `*-win.zip`, `*-linux.tar.bz2`, `*-mac.zip`, `*.dmg`; артефакты `dist-public`/`dist-patron` живут 7 дней |
| **Типичные ошибки** | `::error::тег v0.1.6 != project.yaml version 0.1.5` (первый шаг workflow, `release.yml:47-54`); `::error::mac-zip не найден среди артефактов` (собрали без `--package mac`); `steam: контент депотов не собран` |
| **Чего нет** | джобы `steam-publish`, каналов `dev/beta/release` как сущностей конвейера, Steam-префлайта в гейте (§14) |
| **Статус** | Steam-часть — **не выполнялась**: приложения в Steamworks нет |

---

## 14. Steam и магазины — PARTIALLY IMPLEMENTED

Полная страница платформенного слоя — [39-platforms.md](39-platforms.md) ([ADR-0014](../adr/0014-platform-services.md)); Steamworks-процесс (App ID, депоты, SteamPipe, ачивки, ветки, Cloud) — [40-steamworks.md](40-steamworks.md); предрелизная приёмка — [43-steam-qa.md](43-steam-qa.md); здесь только релизная часть.

`vn release steam --flavor <f> [--branch <b>]` (`cli.py`) **реализована**: рендерит `build/steam/app_build_<flavor>.vdf` из шаблона `../../ci/steam/app_build.vdf.tmpl` по номерам из `project.yaml: platform.steam.{appid,depots}` и распаковывает зипы `build/dist/<version>-<flavor>/` в раскладку депотов `build/steam/content/<flavor>/<platform>/` (`release.py:153-284`).

### 14.1 Чего нет

| Что | Статус |
|---|---|
| Аплоад | **автоматизирован, но не проверен** — workflow `steam-upload` (`workflow_dispatch`, входы `flavor`/`branch`, §12) гоняет `release build` → `release steam` → `steamcmd`. Без секретов `STEAM_USERNAME`/`STEAM_CONFIG_VDF` шаг аплоада — no-op; при `appid: null` workflow падает раньше, на `vn release steam`. Живой выкладки не было ни разу |
| Каналы `dev`/`beta`/`release` как сущности конвейера | NOT IMPLEMENTED. `--branch beta` — это только значение `"SetLive"` в VDF; ветка обязана существовать в Steamworks, иначе публикация в неё не произойдёт; теги `vX.Y.Z-rcN` невозможны (§9) |
| Steam-проверки в релизном гейте | нет ни одной из 21; всё платформенное валидируется внутри `vn release steam` и в `tools/vn/tests/test_platform.py` (13 тестов) |
| Депот отдельного пака/DLC как товара | NOT IMPLEMENTED — и дело не только в `vn pack build`: схема `project@1` разрешает в `platform.steam.depots` **ровно** ключи `windows`/`linux`/`mac` при `additionalProperties: false`, то есть номер DLC-депота сегодня физически некуда положить ([30-packs-and-dlc.md](30-packs-and-dlc.md) §7.3) |
| steam_api-библиотеки в репозитории | и не будет: редистрибутив Valve ставится лаунчером в `$RENPY_SDK/lib/py3-*/`. Их отсутствие — `warning`, сборка остаётся валидной (просто standalone) |

### 14.2 Раскладка депотов: форматы архивов по платформам

**STATUS: IMPLEMENTED.** `steam_stage_content` знает, что launcher distribute отдаёт **разные
форматы**: win — `zip`, linux — `tar.bz2`, mac — `app-zip` (`00build.rpy:423-427`). Карта
`_DIST_SUFFIX` (`release.py:158-162`) держит для каждой платформы суффикс имени и расширения по
приоритету, `_extract_archive` (`:173-183`) распаковывает zip или tar.bz2 по фактическому типу
файла; `.dmg` игнорируется намеренно (кроссплатформенно не распаковать, `app-zip` несёт то же).
Ожидаются только платформы **с объявленным депотом** в `platform.steam.depots` — собирать все три
ради одного депота незачем. Разбор по коду и тесты на реальные архивы —
[40-steamworks.md](40-steamworks.md) §4.3.

**Каталог-обёртку разворачивает `_flatten_wrapper_dir` (`release.py:186-212`).** У форматов `zip` и
`tar.bz2` launcher добавляет верхний каталог с именем артефакта (`prepend=True` в `FORMATS`,
`distribute.rpy:1513-1530`; применение — `:1580-1581`), поэтому без разворачивания путь запуска в Steamworks зависел бы от
версии. Теперь содержимое депота лежит **в корне** `build/steam/content/<flavor>/<platform>/`, а
Launch Options задаются без версии: `vn.exe`, `vn.sh`. Разворачивается только однозначный случай
(ровно один верхний каталог и ничего рядом); mac-бандл (`app-zip` идёт без обёртки, в корне сам
`VN.app/`) не трогается — поднятие его `Contents/` сломало бы приложение. Коллизия имён — не тихая
правка, а `ReleaseError`: платформа не попадает в `staged`, потому что депот с чужой раскладкой хуже
отсутствующего.

Релизное следствие механики никуда не делось: **промежуточных состояний нет.** Любая ошибка
staging (нет `build/dist/`, нет артефакта у платформы с депотом) даёт
`_fail("steam: контент депотов не собран")` **до** записи VDF (`cli.py`) — либо все
объявленные депоты и VDF, либо exit 1 и ничего, а `steamcmd` без VDF бесполезен. Что остаётся
непроверенным: раскладка ни разу не проходила через реальный SteamPipe. Разворачивание обёртки
проверено юнит-тестами на синтетических архивах (`test_platform.py`: обёртка, mac-бандл,
неоднозначный случай), но не на артефакте живого `launcher distribute` — структуру взяли из кода
SDK, а не из фактической сборки.

### 14.3 Что придётся сделать руками сегодня

1. `vn release build --flavor public --package win --package linux --package mac` локально или скачать `dist-public` из `release.yml`.
2. Проверить `build/dist/<version>-public/build-info.json`: `flavor`, `version`, `sha`, `exclude`.
3. Распаковать архив нужной платформы, убедиться, что внутри есть `game/build_id.json` (иначе флейвор не применится — §4).
4. Для Steam — `vn release steam --flavor public [--branch beta]`, затем `steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit`; либо тот же путь из CI — workflow `steam-upload` (§12). Содержимое депота лежит в корне `build/steam/content/<flavor>/<platform>/`, без каталога-обёртки, поэтому Launch Options в Steamworks не зависят от версии. Что нужно заполнить в `project.yaml`, чтобы команда вообще дошла до раскладки, — §14.1. Для остальных витрин архивы заливаются их собственным загрузчиком (itch и т. п.).
5. Описание релиза собрать из `../CHANGELOG.md` руками — `--audience player` не существует.
6. Для patron-канала брать `dist-patron` и раздавать напрямую; вотермарка с `build_id` и меткой `patron_tag` уже в кадре. Сам токен в архив не попадает (ADR-0011).

Пак как отдельный товар (`vn pack build`) — [30-packs-and-dlc.md](30-packs-and-dlc.md); зип пака содержит только манифест и скомпилированные сцены, без ассетов и переводов.

---

## 15. RELEASE CHECKLIST

Выполняется на чистом `main`, до релизного коммита. Здесь только то, что реально необходимо; пункты, которые сегодня выполнить нельзя, помечены явно.

**Окружение и дерево**

- [ ] `export RENPY_SDK=…`; `vn doctor` — **8 PASS, 0 FAIL** (Python, git, git-lfs, корень, `project.yaml`, 39 схем, шрифты 3/3, пин SDK 8.5.3)
- [ ] `git status --short` пуст: ничего из `game/generated|assets|tl`, никаких локальных правок
- [ ] Последняя сборка ассетов была **полной**, не `draft` (после `vn dev` — один `vn build`)

**Содержимое и тулинг**

- [ ] `vn build` — `build: OK` (и строка `память: худшая сцена … из …` в рамках)
- [ ] `vn content lint` — `0 ошибок`
- [ ] `vn content compile --check` — `check: генерат свеж`
- [ ] `python -m pytest tools/vn/tests -q` — **400 passed** (из venv проекта: `tools/vn/.venv/bin/python`; с системным python часть тестов не соберётся)
- [ ] `bash "$RENPY_SDK/renpy.sh" . lint` — движковый lint чист
- [ ] `vn test oversample --scale 2` — `oversample: OK`
- [ ] `vn loc keys --check` — `все строки с id, ledger свеж`
- [ ] `vn loc report` — все несинтетические языки ≥ 98 % (порог `loc/loc.yaml: release_coverage_min`)
- [ ] `vn voice validate` — `непокрыто: 0` (иначе гейт даст FAIL, §5.2)
- [ ] `vn pack validate` — все паки совместимы с фасадом `vn.*`

**Сейвы (G5/G6)**

- [ ] `vn save check` — `save check: OK (2 фикстур)`
- [ ] `vn save corpus` — все фикстуры дают `schema после загрузки: <save_schema> (цель <save_schema>)`
- [ ] Если бампался `save_schema` — миграция написана, добавлена в `content/migrations/registry.yaml`, свежая фикстура положена через `vn save corpus --add`
- [ ] `vn test smoke --picks 0,0` — `OK: vn_end_of_content`, cold start в бюджете 30 с

**Гейт и сборка**

- [ ] `vn release validate --flavor public` — **0 FAIL**. Сегодня это 20 строк, 0 FAIL и 2 WARN (зрелость контента + черновые дубли озвучки), exit 0 — `public` собирается. Но помните правило №4 ([§5.1](#maturity-gate-rule)): как только любая глава станет `status: release`, все оставшиеся `draft`-главы превратятся в FAIL, и тег на `public` без бампа их статусов не поставить — гейт стоит внутри `vn release build`
- [ ] `vn release validate --flavor patron` — 0 FAIL (21 строка, один штатный WARN про черновые дубли озвучки)
- [ ] `vn release build --flavor public --package win` прошёл локально хотя бы раз за цикл
- [ ] Состав архива проверен: есть `game/build_id.json` и `THIRD-PARTY-NOTICES.md`, нет `90_debug/` и `tl/pseudo/`

**Прогоны вариантов и живое железо**

- [ ] `RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0` — скриншоты просмотрены **глазами**
- [ ] `RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0` — оверлеи не срезаны кромкой
- [ ] Windows-артефакт запущен на живой Windows — **не автоматизировано; на этой машине невозможно**
- [ ] mac/Linux-артефакты запущены — **не автоматизировано; mac-сборка на этой машине не проверялась, Linux-машины нет**
- [ ] Прогон на физическом Steam Deck — **невозможно сегодня: устройства нет** (требование `ci/steam/README.md` перед `setlive default`)

**Версии и документы**

- [ ] `project.yaml: version` бампнут по политике (новая глава = **minor**, фиксы = patch) и **не равен уже существующему тегу** (`git tag -l`)
- [ ] `save_schema` бампнут ровно тогда, когда менялись `vars` несовместимо — и никогда не понижен
- [ ] `vn release changelog` прогнан, проза для игрока дописана **после** него
- [ ] `ci/release-manifest.json` в коммите (иначе гейт даст WARN о расхождении версий)
- [ ] Главы, которые считаются выпущенными, переведены в `status: release` (иначе `id_registry.json` останется пустым и G7 не сработает)

**Steam и публикация**

- [ ] Депоты и ветка Steam: `platform.steam.appid` + `depots` заполнены, ветка `beta` создана в Steamworks — **сегодня невозможно: App ID нет** ([40-steamworks.md](40-steamworks.md))
- [ ] `vn release steam --flavor public` даёт VDF и раскладку без `error` — **в этом чекауте недостижимо**: `platform.steam.appid: null` и ключа `depots` нет, команда останавливается на первом шаге (§14.1). Сама раскладка депотов рабочая и знает форматы всех платформ (§14.2)
- [ ] Тег `v<version>` совпадает с `project.yaml: version`; `git push --follow-tags` запускает `release.yml`
- [ ] После зелёного workflow: GitHub Release проверен, `dist-patron` скачан (артефакт живёт **7 дней**)

---

## 16. RELEASE RUNBOOK

Пошагово, от «глава готова» до опубликованного релиза. Версии в примере — фактические: `0.1.5` уже выпущена, значит цель — `0.1.6`.

```bash
# 0. Чистый main, SDK на месте
git switch main && git pull && git status --short
export RENPY_SDK=/путь/к/renpy-8.5.3-sdk
vn doctor                             # 8 PASS

# 1. Поднять статус выпускаемых глав (граф-проверки станут строгими, G15)
#    content/chapters/chNN_*/chapter.yaml -> status: release
vn content lint                       # должно остаться 0 ошибок

# 2. Полный круг проверок (стадия 2 из §13)
vn build
vn loc keys --check
vn content compile --check
python -m pytest tools/vn/tests -q    # 400 passed
bash "$RENPY_SDK/renpy.sh" . lint
vn test oversample --scale 2
vn voice validate
vn pack validate
vn test smoke --picks 0,0
vn save check && vn save corpus

# 3. Changelog и манифест (ДО правки версии — генератор берёт version из project.yaml)
vn release changelog
#    вручную: docs/CHANGELOG.md — 2-5 предложений для игрока
#    вручную: project.yaml: version -> 0.1.6

# 4. Гейт по обоим флейворам
vn release validate --flavor public
vn release validate --flavor patron

# 5. Контрольная сборка (ловит проблемы distribute до тега)
vn release build --flavor public --package win
ls build/dist/0.1.6-public/           # vn-0.1.6+<sha>-win.zip + build-info.json

# 6. Прогоны вариантов (скриншоты смотреть глазами)
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0

# 7. Релизный коммит — ровно три-четыре файла
git add project.yaml docs/CHANGELOG.md ci/release-manifest.json content/registry/id_registry.json
git commit -m "release: 0.1.6 — <итог одной строкой>"

# 8. Тег и пуш
git tag v0.1.6
git push --follow-tags                # -> release.yml: гейт тега -> build x2 -> dmg -> publish

# 9. После зелёного workflow
#    - GitHub Release создан, в нём только public-архивы + dmg
#    - dist-patron скачать из артефактов workflow (7 дней!) и раздать по своим каналам
#    - для Steam: vn release steam --flavor public, затем steamcmd (§14)
```

**Что проверить на артефактах перед раздачей:**

| Проверка | Как |
|---|---|
| Флейвор применился | внутри архива есть `.../game/build_id.json`, поле `flavor` верное |
| Вотермарка там, где надо | `patron` → `watermark: true`; `public` → `false` |
| Нет dev-инструментов | в архиве нет `game/framework/90_debug/` |
| Нет псевдолокали | нет `game/tl/pseudo/` |
| Лицензии едут | есть `game/THIRD-PARTY-NOTICES.md` |
| Размер похож на прошлый релиз | резкое изменение = что-то попало или пропало |

---

## 17. Откат: релиз сломан

**Прецедент проекта.** Сборка `0.1.1` оказалась нерабочей: чекаут в CI шёл без LFS, в дистрибутив уехали 131-байтные указатели вместо шрифтов, игра падала `FreetypeError` на главном меню. Тега `v0.1.1` в репозитории **нет** — сломанная версия не откатывалась, она была вытеснена вперёд: коммит `ff28ba9` добавил `lfs: true` во все workflow и проверку шрифтов по содержимому (`doctor.py: _lfs_pointer_fonts`, гейт `release.py:519-528`), после чего вышел `0.1.2`, а `../CHANGELOG.md` прямо говорит игроку «сборки 0.1.1 непригодны — используйте 0.1.2».

**Это и есть штатная процедура: катим вперёд, а не назад.** Причины технические, не идеологические:

1. Тег обязан совпадать с `project.yaml: version` (`release.yml:47-54`). Перевыпустить ту же версию с другим содержимым можно только удалив тег и релиз — а у игроков он уже скачан.
2. `config.version` содержит git-sha, поэтому «та же версия» после фикса всё равно даёт другое имя архива.
3. Если в сломанном релизе бампался `save_schema`, откат назад для игроков **невозможен в принципе**: их сейвы будут «из будущего», и `after_load` покажет `ui.flow.save_from_newer` и перезапустит игру.

**Порядок действий:**

```bash
# 1. Остановить распространение (руками, инструмента нет)
gh release edit v0.1.6 --draft        # убрать из публичного списка
#   или gh release delete v0.1.6 --yes , если скачиваний ещё не было
#   в Steam: переключить default-ветку обратно в Steamworks (руками)

# 2. Починить причину в main отдельным коммитом (fix(...): ...), с тестом/проверкой,
#    которая поймала бы этот класс поломки. Хотфикс поверх непонятного пайплайна запрещён.

# 3. Бампнуть patch и выпустить новую версию по runbook §16
#    project.yaml: 0.1.6 -> 0.1.7 ; в CHANGELOG честно: «сборки 0.1.6 непригодны»

# 4. Сломанный тег НЕ переиспользовать. Если тег ещё никуда не уехал:
git tag -d v0.1.6 && git push origin :refs/tags/v0.1.6
```

**Чего откат НЕ трогает:**

- `build/rpyc-cache/` — кэш сломанной версии остаётся и станет базой для следующей (локально берётся старший по версии каталог). Если сломанная сборка меняла структуру `.rpy`, безопаснее удалить `build/rpyc-cache/<сломанная версия>/` локально; в CI — сменить ключ кэша.
- `content/registry/id_registry.json` — append-only, из него ничего не вычёркивается. Это by design (G7).
- `ci/release-manifest.json` — перезапишется следующим `vn release changelog`.

**Если ломается не релиз, а сборка** (красный CI, не собирается генерат) — порядок в [36-troubleshooting.md](36-troubleshooting.md) и [04-development-workflow.md](04-development-workflow.md) §6. Аварийный режим G4 «взять `game/generated/` из артефакта `generated-<sha>`» работает только руками: `vn build --use-artifact <sha>` **не существует**.

---

## Как изменить / Как расширить

**Добавить флейвор.** Дописать блок в `project.yaml:66-76` (ключи `packs` и `nsfw` обязательны схемой). Кода менять не нужно: `--flavor` принимает любое имя из `project.yaml`, а гейты в игре спрашивают `vn_build.nsfw` / `vn_build.early_content`, а не имя флейвора. Добавить ногу в матрицу `release.yml:32`, если он должен собираться на теге.

**Сделать `packs` build-time-гейтом.** Точка правки — `installed()` в `030_flow.rpy`: он должен пересекать `VN_PACKS` с `vn_build.packs`, а не смотреть только на генерат. Проверить потребителей `owned()`: `chapter_select.gen.rpy`, `080_achievements.rpy`, `090_gallery.rpy`. Тест: `public`-сборка не должна показывать главы пака `nsfw`.

**Оживить `early_content`.** Потребителя нужно написать: гейт по главе (`chapter.yaml`) или по элементу галереи, по образцу NSFW-гейта в `090_gallery.rpy`.

**Развести кэш `.rpyc` по флейворам.** Одна строка — `cli.py`: `cache_root / version` → `cache_root / f"{version}-{flavor}"`. Потребуется прокинуть флейвор в `package` (сейчас туда идёт только `dest_suffix`) и поправить `_semver_key`, который парсит имя каталога как semver.

**Довести Steam-поставку до конца (§14.1).** Раскладка депотов уже работает и покрыта тестами на реальные форматы архивов (§14.2). Осталось внешнее: приложение в Steamworks и номера в `project.yaml` (`platform.steam.appid` + `depots`), steam_api-редистрибутивы Valve на build-машине, первый прогон `steamcmd` в бета-ветку и сверка каталога-обёртки в депоте с путём запуска. Автоматизация аплоада (джоба `steam-publish`) — отдельное решение: credentials Steamworks в CI это не тот вопрос, который решается заодно.

**Добавить Steam-префлайт в гейт.** Дешёвый минимум, который предотвращает известные падения: `appid`/`depots` заполнены, `ci/steam/app_build.vdf.tmpl` на месте, `steam_libs_status()` пуст, и для каждой платформы депота в `build/dist/` есть артефакт **ожидаемого формата** (а не только `.zip`). Сейчас `steam_libs_status` зовётся из одного места (`cli.py`) и `vn doctor` о нём не знает.

**Добавить проверку в гейт.** Правило пишется как функция в своём модуле (`assets/`, `content/`, `loc/`) и вызывается из `validate_release` через `add("PASS"/"WARN"/"FAIL", …)`. Собственной логики в `release.py` быть не должно — иначе гейт разойдётся с `vn build`.

**Затащить `cold_start_s` в релиз.** Либо шаг `vn test smoke --picks 0,0` в `release.yml` перед `vn release build`, либо новая проверка в гейте, читающая результат последнего smoke из `.vncache/smoke/`. Первый вариант честнее — он меряет ту же сборку.

**Подписать артефакты (RECOMMENDED FUTURE STATE, сейчас NOT IMPLEMENTED).** Для macOS движок уже умеет: `build.mac_identity` + `build.mac_codesign_command` (`$RENPY_SDK/launcher/game/distribute.rpy:1348,1380`), и с заданным identity launcher сам начнёт отдавать dmg (`:1537-1540`) — джоба `dmg` тогда станет лишней. Для Windows — свой `signtool`-шаг. Требует сертификатов, то есть секретов CI, и отдельного ADR.

**Включить `.rpa`-архивы (только через ADR).** Россыпь в desktop-каналах — норма `../ARCHITECTURE.md` §2.4 (Steam-дельта-патчи); тематические `.rpa` допустимы лишь как опция mobile-поставки фазы 3. Технически это `build.archive(...)` + `build.classify(..., "archive_*")` в `game/options.rpy`.

## Чего НЕ делать

- **Не раздавать архив из голого `vn package`** — в нём нет `game/build_id.json`, игра пойдёт как `dev`: NSFW открыт, ранний контент открыт, вотермарки нет.
- **Не ставить тег, не бампнув `project.yaml: version`** — `release.yml:47-54` рубит workflow первым шагом. И помните, что `v0.1.5` уже занят.
- **Не пытаться выпустить `v1.0.0-rc1`** — схема `project@1` запрещает pre-release-суффикс; RC — состояние, а не версия (§13, стадия 8).
- **Не понижать `save_schema` и не откатывать релиз с его бампом** — сейвы игроков станут «из будущего», игра перезапустится.
- **Не коммитить `game/build_id.json`** — он в `.gitignore:8` и должен жить только во время distribute; закоммиченный, он превратит все dev-запуски в чужой флейвор.
- **Не считать, что `flavors.<f>.packs` кого-то ограничивает на сборке** — `VN_PACKS` перечисляет все паки из `packs/` независимо от флейвора. Runtime-гейт владения — другое дело и работает только под Steam (§3.2).
- **Не класть главу со сценами в пак `nsfw`, рассчитывая на исключение по флейвору** — она уедет и в `public`. Гейт по ассетам (`nsfw/`-подпапки) работает, build-time-гейт по пакам — нет.
- **Не собирать релиз после `vn dev`, не сделав полный `vn build`** — draft-профиль ассетов остаётся в манифесте; `release build` навяжет `full` сам, но `vn build --check` и `vn release validate` до этого будут красными.
- **Не переименовывать архивы в `build/dist/`** — имя выводится движком из `build.name` и `config.version`; переименованный файл не соотнесётся с `build-info.json`, а Steam-staging ищет их по суффиксу платформы.
- **Не удалять `ci/fixtures/rpyc-line/`** как «лишние `.rpyc`» — это единственные `.rpyc` в git и основа детерминированности сейв-корпуса (G6).
- **Не полагаться на `vn release validate` как на полную проверку** — он не гоняет ни smoke, ни движковый lint, ни `vn test oversample`, ни бюджет холодного старта, ни пин SDK, ни одной платформенной проверки.
- **Не считать `vn release steam` аплоадом и не считать её проходящей целиком** — она готовит VDF и раскладку (это работает, включая Linux-`tar.bz2`, §14.2), но в этом чекауте останавливается на пустом `appid` (§14.1), а `steamcmd` запускает человек.
- **Не искать в жёлтых строках гейта поломку** — 14 черновых дублей озвучки и «ни одна глава ещё не доведена до status=release» это штатные WARN; релиз валит только FAIL. Но вторую строку стоит перечитать перед релизом первой главы: с ней гейт зрелости включает строгость ([§5.1](#maturity-gate-rule)).
- **Не приводить размеры `build/dist/` и состав `build/rpyc-cache/` как свойства репозитория** — каталога `build/` в чекауте нет (`.gitignore:20`), это всегда снимок конкретной машины.
- **Не рассчитывать на `vn validate`, `vn build --use-artifact`, `vn release changelog --from/--audience`, `vn release build --channel`** — этих команд и флагов не существует (usage error 2, а не exit 3).
- **Не забывать про 7 дней хранения `dist-patron`** — артефакт workflow исчезнет, а собрать бит-в-бит тот же архив заново уже не получится (в `build_id` зашита минута сборки).

## Проверка

```bash
export RENPY_SDK=/путь/к/renpy-8.5.3-sdk

# Гейт цел и проходит по обоим флейворам
vn release validate --flavor public       # 20 строк (18 PASS + 2 WARN: зрелость контента + драфты озвучки), exit 0
vn release validate --flavor patron       # 21 строка (1 WARN), exit 0
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

# Бюджеты (размерные и память) и версии
vn build                                  # оба класса бюджетов проверяются здесь же
vn assets memory                          # детально по сценам
git tag -l                                # тег для новой версии обязан быть свободен
git describe --tags --exact-match 2>/dev/null   # тег == project.yaml: version?
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/release.py` (гейт `validate_release:407-629`, флейворы, build-info, `patron_tag`, changelog, бюджеты, Steam-поставка `:153-252`), группы `package`/`release`/`pack` в `../../tools/vn/src/vn/cli.py` (`:301-393`, `:1720-1852`, `:1855-1926`), `../../project.yaml`, `../../game/options.rpy`, `../../game/framework/00_core/060_build_info.rpy`, `../../.github/workflows/release.yml`, `../../tools/schemas/build_info@2.schema.json`, `$RENPY_SDK/renpy/common/00build.rpy:421-432` (форматы пакетов), `../adr/0011-patron-tag-instead-of-token.md`, `../adr/0014-platform-services.md`, `../../ci/steam/README.md`, `../../tools/vn/tests/test_ci_config.py` |
| **Не трогать** | `game/build_id.json` (пишет и удаляет `vn release build`), `build/**` (dist, rpyc-cache, packs — производная зона, `.gitignore:20`), `game/generated/**`, `game/assets/**`, `game/tl/**`; `ci/fixtures/rpyc-line/**` — только через `vn save corpus` |
| **Зависимости** | правка `project.yaml: version` → тег, `config.version`, имя архива, каталог `build/rpyc-cache/<version>/`; правка `flavors` → `build_id.json` → рантайм-гейты достижений и галереи; правка `budgets` → и `vn build`, и гейт; правка `render.image_cache_mb` → бюджет памяти сцены в `vn build`; правка `renpy_sdk` → руками синхронизировать `RENPY_VERSION` в `ci.yml:26`, `nightly.yml`, `release.yml:19`; правка `game/options.rpy` → состав каждого дистрибутива |
| **Валидация** | `vn release validate --flavor public && vn release validate --flavor patron`; полная — `vn release build --flavor public --package win` с проверкой содержимого архива (см. «Проверка»); при правке Steam-части — `pytest tools/vn/tests/test_platform.py -q` (10 тестов) |
| **Частые ошибки** | 1) выдумать флаг: `vn validate`, `vn build --use-artifact`, `vn release changelog --from`, `vn release build --channel` — их нет; 2) писать, что `flavors.<f>.packs` и `early_content` ничего не гейтят — с этой итерации `packs` гейтит установленность в рантайме, а `early_content` — зрелость контента в релизном гейте (§3.2, §5.1 №4); build-time-исключения скриптов по-прежнему нет (G9); 2а) обратная ошибка — писать «`public` не собирается / релиз падает по зрелости»: проверка №4 самоактивирующаяся, до первой главы `status: release` она даёт WARN, и оба флейвора сегодня зелёные ([§5.1](#maturity-gate-rule)); 3) назвать `vn package` способом собрать релиз — получится dev-сборка без `build_id.json`; 4) цитировать `../ARCHITECTURE.md` как описание реализованного (каналы `dev`/`beta`/`release`, `steam-publish`, `rpyc-compat` — NOT IMPLEMENTED); 5) писать «гейт из 20 проверок» — их **21**, а строк на экране сегодня 20 (`public`) / 21 (`patron`); 6) писать «все PASS» как эталон — штатны WARN про черновые дубли озвучки и (у `public`) про зрелость контента (§5.1 №4); 7) ставить тег, не бампнув `project.yaml` (и помнить, что `v0.1.5` уже выпущен, следующая версия — `0.1.6`); 8) писать про `patron_token` в `build_id.json` — с ADR-0011 туда пишется `patron_tag`; 9) утверждать, что `vn release steam` проходит целиком — раскладка депотов работает (§14.2), но `appid`/`depots` пусты, аплоад ручной, живого прогона не было (§14.1); и не писать обратное — «staging ищет zip» больше не факт; 10) приводить числа из `build/` как факт репозитория — этого каталога в чекауте нет |

---

**Смежные страницы:** [39-platforms.md](39-platforms.md) (платформенный слой, controller-first, `vn release steam`) · [40-steamworks.md](40-steamworks.md) (App ID, депоты, ачивки, ветки в Steamworks) · [41-steam-deck.md](41-steam-deck.md) (Deck: вёрстка и прогон) · [42-big-picture.md](42-big-picture.md) (ТВ и safe-area) · [43-steam-qa.md](43-steam-qa.md) (QA-протокол под Steam) · [44-how-do-i.md](44-how-do-i.md) («как мне…» одной строкой) · [27-testing.md](27-testing.md) (уровни проверок, smoke, сейв-корпус) · [30-packs-and-dlc.md](30-packs-and-dlc.md) (паки как единицы поставки) · [33-security-and-legal.md](33-security-and-legal.md) (секреты, состав дистрибутива, лицензии)
