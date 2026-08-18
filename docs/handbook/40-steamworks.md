# 40. Steamworks: приложение, депоты, SteamPipe, ачивки, Cloud

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — техническая часть проекта готова (`define config.steam_appid` из генерата, ачивки и DLC-владение через штатный стек движка), и **раскладка депотов работает на всех трёх платформах**: `steam_stage_content` знает фактические форматы пакетов движка — zip для Windows/mac и `tar.bz2` для Linux (§4.3), — и ожидает только те платформы, у которых объявлен депот. Но **поставка целиком не пройдена**: **приложения в Steamworks ещё нет** — `platform.steam.appid: null` (`../../project.yaml:15`), ключа `platform.steam.depots` в файле нет вообще, поэтому `vn release steam` сегодня честно останавливается на первом же шаге с сообщением про `appid` (§4.2); steam_api-редистрибутивов Valve на build-машине нет; аплоад — ручной `steamcmd`, в CI не заведён; на живом Steam не проверялось ничего ([43](43-steam-qa.md)). Steam Cloud — **NOT IMPLEMENTED** и это решение (§7).
> **Отвечает на вопрос:** «Я никогда не выпускал Ren'Py-игру в Steam. Что я должен создать в Steamworks своими руками, какие числа после этого попадут в `project.yaml`, что происходит при `vn release steam`, как игра узнаёт про Steam, как заводить ачивки и что делать с сохранениями».

Разделение труда между этим файлом и соседями: **[39-platforms.md](39-platforms.md)** описывает *архитектуру* платформенного слоя (единственная точка касания, capability-фасад, controller-first UX, как добавить платформу). Здесь — *процесс*: что делается руками в Steamworks и вне репозитория, какие механики движка при этом включаются и какие данные проекта их питают. Предрелизная приёмка — **[43-steam-qa.md](43-steam-qa.md)**.

Официальную документацию этот файл не пересказывает: короткое объяснение + ссылка на Valve/Ren'Py, и обязательно «как это применяется именно у нас».

---

## Быстрый ответ

```bash
# ── Вне репозитория (руками, один раз, см. §1) ─────────────────────────────
#  Steamworks: партнёрский аккаунт -> app credit -> приложение -> App ID
#             -> депоты (по одному на платформу) -> ветка beta -> ачивки
#  Build-машина: лаунчер Ren'Py -> preferences -> Install libraries
#                                -> Install Steam Support         (§5.2)

# ── В репозитории (данные, не код) ─────────────────────────────────────────
# project.yaml:
#   platform:
#     steam:
#       appid: 480
#       depots: {windows: 481, linux: 482, mac: 483}
vn build                       # -> game/generated/platform.gen.rpy

# ── Поставка ───────────────────────────────────────────────────────────────
vn release build --flavor public --package win --package linux --package mac
vn release steam --flavor public --branch beta      # VDF + build/steam/content/ (в корне, без обёртки)
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit
#   -> дальше SetLive в beta; release-ветку переключает человек в Steamworks (§4.5)

# Те же три шага из CI: workflow steam-upload (ручной запуск, входы flavor/branch).
# Без секретов STEAM_USERNAME/STEAM_CONFIG_VDF аплоад — no-op, сборка и VDF всё равно
# проверяются (§12 в 29-build-and-release.md, донастройка — ci/steam/README.md).
```

Фактическое состояние чекаута (проверено 2026-08-18, HEAD `e3c2842` + текущая итерация):

```
$ vn release steam --flavor public
ошибка: platform.steam.appid не задан в project.yaml — заполните App ID из Steamworks (публичный, не секрет)
$ cat game/generated/platform.gen.rpy | grep define
define config.steam_appid = None
define VN_STEAM_DLC = {}
```

**Это рабочее состояние, а не поломка.** Игра полноценна как standalone: ачивки лежат в `persistent`, паки гейтятся установленностью. Steam включается двумя правками данных и одной установкой библиотек.

---

## 1. Что нужно создать в Steamworks (вне репозитория)

Ни один из этих шагов не автоматизируется тулингом и не может быть сделан из репозитория — это веб-интерфейс Steamworks и юридические действия. Точка входа: https://partner.steamgames.com/ , обзорный гайд Valve — https://partner.steamgames.com/doc/gettingstarted .

| # | Шаг | Что появляется | Что после этого попадает в репозиторий | Статус у нас |
|---|---|---|---|---|
| 1 | Партнёрский аккаунт: юрлицо/самозанятость, налоговая анкета, банковские реквизиты, подписание Steam Distribution Agreement | доступ в Steamworks | ничего | **нет** |
| 2 | Покупка **app credit** (Steam Direct recoupable fee) | право создать приложение | ничего | **нет** |
| 3 | Создание приложения | **App ID** (одно число) | `project.yaml: platform.steam.appid` | **нет** (`appid: null`) |
| 4 | Создание **депотов** контента (обычно по одному на ОС) | **Depot ID** — как правило `appid+1`, `appid+2`, … | `project.yaml: platform.steam.depots.{windows,linux,mac}` | **нет** (ключа `depots` в файле нет) |
| 5 | Настройка **веток** (betas): минимум одна тестовая, например `beta` | имя ветки для `SetLive` | `--branch beta` в командной строке, в файлы не пишется | **нет** |
| 6 | Страница магазина, возрастной гейт 18+, скриншоты, трейлер, review-заявка | публикуемая страница | ничего | **нет** |
| 7 | **Ачивки**: заведение по одной, API Name = наш id | список ачивок приложения | ничего (id уже в `content/achievements/*.yaml`) | id есть, в Steamworks не заведены — §6.4 |
| 8 | **Steam Cloud** (Auto-Cloud): корневые пути и маски | ничего | ничего (кода в игре нет — §7) | **нет** — но 6 строк конфигурации готовы к вводу (`../../ci/steam/README.md`, «Steam Cloud»; §7.2) |
| 9 | **DLC** как отдельные приложения (для паков) | DLC App ID | `packs/<id>/manifest.yaml: steam_dlc_appid` | **нет** (в манифестах поля нет) |

Дополнительно про сроки и правовое: релиз невозможен раньше чем через 30 дней после покупки app credit или через две недели после аппрува страницы (что позже), плюс отдельные правила для nudity-патчей — организационная часть разобрана в [33-security-and-legal.md](33-security-and-legal.md) §11 и не дублируется здесь.

### 1.1 Почему `appid: null` — это одно «выключено», а `depots` — совсем другое

Тонкость, на которой легко потерять полчаса. Схема `project@1` объявляет `appid` как `[integer, null]`, то есть `null` — **валидное значение** «Steam выключен во всех сборках»; а `depots` — объект, которого в файле просто **нет** (см. `../../tools/schemas/project@1.schema.json`, блок `platform.steam` с `additionalProperties: false`).

Следствие: включение Steam — это **две независимые правки** `project.yaml`, и ошибка про депоты вылезет только вторым запуском, уже после того как App ID заполнен:

```
1-й запуск: ошибка: platform.steam.appid не задан в project.yaml …    (release.py:214-222)
2-й запуск: ошибка: platform.steam.depots пуст — задайте номера депотов по платформам …  (release.py:232-236)
```

Депот, заданный не для всех платформ, ошибкой не считается — это `warning`, и платформа просто не уезжает (`release.py:242-245`, тест `../../tools/vn/tests/test_platform.py`, `test_steam_app_build_warns_on_missing_depot`).

---

## 2. Что публично, а что нельзя коммитить

| Данные | Публично? | Где живёт | Почему так |
|---|---|---|---|
| **App ID** | **да** | `../../project.yaml:13-15` | Виден в URL страницы магазина; в клиенте — в `steam_appid.txt` любой игры. Не секрет по построению |
| **Номера депотов** | **да** | `project.yaml: platform.steam.depots` | Видны в манифестах, скачиваемых клиентом |
| **DLC App ID** | **да** | `packs/<id>/manifest.yaml: steam_dlc_appid` (`../../tools/schemas/pack_manifest@1.schema.json:32-35`) | То же: это номер витринного товара |
| **Логин/пароль/Steam Guard `steamcmd`** | **НИКОГДА** | CI-секреты или интерактивный ввод | Полный доступ к выкладке билдов приложения |
| **steam_api-редистрибутивы Valve** (`steam_api64.dll`, `libsteam_api.so`, `libsteam_api.dylib`) | **нельзя коммитить** | `$RENPY_SDK/lib/py3-*/` на build-машине | Лицензия Steamworks SDK: распространение библиотек разрешено только в составе игры, не как файлы в репозитории. Формально это фиксирует и `ci/steam/README.md` |
| **Steamworks SDK целиком** (`sdk/`, `redistributable_bin/`, `tools/ContentBuilder`) | **нельзя коммитить** | скачивается партнёром | То же лицензионное основание |
| **VDF для steamcmd** | генерат, в git не нужен | `build/steam/app_build_<flavor>.vdf` | `build/` в `../../.gitignore:20`; файл целиком выводится из `project.yaml` |
| `PATRON_TOKEN` | секрет CI | `secrets.PATRON_TOKEN` (`../../.github/workflows/release.yml:80-81`) | К Steam не относится, но соседствует в релизном пути — см. [33-security-and-legal.md](33-security-and-legal.md) |

Два приятных факта, которые не надо изобретать заново:

- **`steam_appid.txt` исключён из дистрибутивов самим движком**: `("**/steam_appid.txt", None)` в `renpy_patterns` (`$RENPY_SDK/renpy/common/00build.rpy:87`). То есть dev-файл (§5.4) физически не может уехать игроку.
- **Секретов в VDF не бывает по построению**: `steam_app_build` подставляет только appid, версию, флейвор, ветку и номера депотов (`../../tools/vn/src/vn/release.py:225-263`); логина в шаблоне `../../ci/steam/app_build.vdf.tmpl` нет вовсе.

---

## 3. Где в проекте лежит Steam-конфигурация

Карта, по которой можно пройти сверху вниз и увидеть весь путь «данные → генерат → рантайм → поставка».

| Слой | Файл | Что именно |
|---|---|---|
| Данные | `../../project.yaml:13-15` | `platform.steam.appid` (сейчас `null`), сюда же добавляется `depots` |
| Данные | `packs/<id>/manifest.yaml` | `steam_dlc_appid` пака (в `../../packs/ep_beach/manifest.yaml` и `../../packs/nsfw/manifest.yaml` сейчас **нет**) |
| Схема | `../../tools/schemas/project@1.schema.json` | `platform.steam.{appid,depots}`, `additionalProperties: false` — незнакомый ключ красит `vn build` |
| Эмиттер | `../../tools/vn/src/vn/content/compile.py:133-152` (`_emit_platform`), регистрация выхода — `:1136` | превращает данные в два `define` |
| Генерат | `game/generated/platform.gen.rpy` | `define config.steam_appid = …`, `define VN_STEAM_DLC = {…}` — **править нельзя** |
| Рантайм | `../../game/framework/00_core/035_platform.rpy` | единственная точка касания: `vn_platform` (`init -960`, `:16`) + подключение провайдеров (`init 999`, `:71-89`) |
| Поставка | `../../tools/vn/src/vn/release.py:151-326` | `steam_config` (`:187`), `steam_app_build` (`:197`), `steam_stage_content` (`:238`), `steam_libs_status` (`:275`); форматы архивов по платформам — `_DIST_SUFFIX` (`:159`), `_find_dist_archive` (`:166`), `_extract_archive` (`:174`) |
| Поставка | `../../tools/vn/src/vn/cli.py:1819-1852` | команда `vn release steam` |
| Шаблон | `../../ci/steam/app_build.vdf.tmpl` | VDF с подстановками `{APPID} {DESC} {BRANCH} {CONTENT_ROOT} {BUILD_OUTPUT} {DEPOTS}` |
| Норматив | `../../ci/steam/README.md` | что где живёт, процесс релиза, Cloud, правило ачивок |
| Норматив | [`../adr/0014-platform-services.md`](../adr/0014-platform-services.md) | решение и его последствия |
| Тесты | `../../tools/vn/tests/test_platform.py` | 10 тестов: эмиттер, VDF, раскладка (реальные zip **и** tar.bz2), статус библиотек, гард-тест фасада |

Чего в этом списке **нет** и быть не должно: ветвлений `if steam:` в экранах и сценах (гард-тест `test_platform.py:183-193`), собственных биндингов Steamworks, таблиц «наш id → Steam-имя».

---

## 4. SteamPipe: от зипов до выложенного билда

SteamPipe — механизм выкладки Valve: вы описываете билд в текстовом VDF-файле, `steamcmd` заливает содержимое депотов и (необязательно) сразу публикует его в ветку. Официально: https://partner.steamgames.com/doc/sdk/uploading .

### 4.1 Наш app_build VDF

Шаблон (`../../ci/steam/app_build.vdf.tmpl`, 12 строк) — ровно минимальный AppBuild:

```
"AppBuild"
{
	"AppID" "{APPID}"
	"Desc" "{DESC}"
	"SetLive" "{BRANCH}"
	"ContentRoot" "{CONTENT_ROOT}"
	"BuildOutput" "{BUILD_OUTPUT}"
	"Depots"
	{
{DEPOTS}
	}
}
```

Что подставляет `steam_app_build` (`release.py:256-262`):

| Поле | Значение | Откуда |
|---|---|---|
| `AppID` | число | `project.yaml: platform.steam.appid` |
| `Desc` | `"<version> <flavor>"`, например `0.1.5 public` | `project.yaml: version` + `--flavor` |
| `SetLive` | имя ветки или **пустая строка** | `--branch` (по умолчанию пусто = загрузить, но не публиковать) |
| `ContentRoot` | `"."` | константа |
| `BuildOutput` | `"output"` | константа |
| `Depots` | блок на каждый депот с номером | `platform.steam.depots` |

Блок депота (`release.py:248-253`) — рекурсивный маппинг всего каталога платформы:

```
		"481"
		{
			"FileMapping"
			{
				"LocalPath" "content/public/windows/*"
				"DepotPath" "."
				"recursive" "1"
			}
		}
```

**Важно про пути:** `ContentRoot` и `BuildOutput` относительные, а SteamPipe разрешает их **относительно самого VDF-файла**, а не относительно рабочего каталога. Наш VDF лежит в `build/steam/`, поэтому `content/public/windows/*` — это `build/steam/content/public/windows/*`, а логи и чанки SteamPipe создаст в `build/steam/output/`. Запускать `steamcmd` можно из любого каталога, но **переносить VDF отдельно от `content/` нельзя**.

### 4.2 Что делает `vn release steam`

`../../tools/vn/src/vn/cli.py:1819-1852`, пять локальных шагов, ни один не ходит в сеть:

| Шаг | Функция | Поведение при проблеме |
|---|---|---|
| 1. Прочитать `platform.steam` | `steam_config` (`release.py:215-222`) | нет `appid` → **exit 1**. Сегодня прогон останавливается ровно здесь: в `../../project.yaml:15` стоит `appid: null` |
| 2. Отрендерить VDF | `steam_app_build` (`release.py:225-263`) | пустые `depots` → exit 1; депот платформы не задан → `warning`, платформа не уедет |
| 3. Проверить steam_api в SDK | `steam_libs_status` (`release.py:312-326`) | `warning` на каждую недостающую библиотеку — сборка валидна, просто standalone |
| 4. Распаковать дистрибутив в раскладку депотов | `steam_stage_content` (`release.py:266-309`) | нет `build/dist/<version>-<flavor>/` → error «сначала vn release build»; у платформы **с объявленным депотом** нет артефакта → error с подсказкой `--package <plat>`; любая ошибка → **exit 1 до записи VDF** (`cli.py:1843-1846`) |
| 5. Записать VDF | `cli.py:1847-1849` | — |

Шаг 4 ожидает по умолчанию **только те платформы, у которых в `platform.steam.depots` есть номер** (`release.py:287-288`): собирать все три ради одного депота незачем, и «нет артефакта» для платформы, которую вы не отгружаете, — не ошибка, а шум. Явный список можно передать аргументом `platforms=` при вызове из кода.

Раскладка после успешного прогона:

```
build/steam/
  app_build_public.vdf
  content/public/windows/**      <- распакованный vn-<version>-win.zip
  content/public/linux/**        <- распакованный vn-<version>-linux.tar.bz2
  content/public/mac/**          <- распакованный vn-<version>-mac.zip
  output/                        <- создаст steamcmd
```

Команда **чистит** каталог платформы перед распаковкой (`release.py:296-298`), поэтому повторный прогон не смешивает старые и новые файлы. Из подходящих архивов берётся последний по сортировке (`found[-1]`, `release.py:165-170`).

Чего команда не делает: не логинится, не запускает `steamcmd`, не хранит credentials, не проверяет содержимое архива и **не является аплоадом**.

### 4.3 Форматы пакетов distribute по платформам (Linux — не zip)

**STATUS: IMPLEMENTED.** Главное, что нужно знать про этот шаг: **launcher distribute выдаёт разные форматы по платформам**, и «всё zip» — неверное предположение. Фактические объявления SDK:

```
package("linux", "tar.bz2", "linux linux_arm renpy all", "Linux")     # 00build.rpy:424
package("win",   "zip",     "windows renpy all", "Windows")          # 00build.rpy:426
package("mac",   "app-zip app-dmg", "mac renpy all", "Macintosh")    # 00build.rpy:425
```

Имена файлов складываются как `<build.directory_name>-<variant><ext>`, где `directory_name = "vn-" + config.version` (`00build.rpy:640-651`, `distribute.rpy:1501`), то есть после `vn release build --flavor public --package win --package linux --package mac` в `build/dist/0.1.5-public/` лежат:

```
vn-0.1.5+<sha>-win.zip        <- windows-депот
vn-0.1.5+<sha>-linux.tar.bz2  <- linux-депот
vn-0.1.5+<sha>-mac.zip        <- mac-депот (app-zip)
vn-0.1.5+<sha>-mac.dmg        <- игнорируется намеренно
```

Раскладка это учитывает: `_DIST_SUFFIX` (`release.py:158-162`) — карта «платформа → (суффикс имени, кортеж расширений по приоритету)»: windows `(-win, .zip)`, linux `(-linux, .tar.bz2, .zip)`, mac `(-mac, .zip)`. `_find_dist_archive` (`:165-170`) проходит расширения в этом порядке и берёт первое, где нашлись файлы; `_extract_archive` (`:173-183`) распаковывает **zip или tar.bz2 по фактическому типу файла**. Косвенное подтверждение набора расширений — маска артефактов релизного workflow: `*.zip -o *.tar.bz2 -o *.dmg` (`../../.github/workflows/release.yml:133`).

**Почему `.dmg` в карте нет.** Это осознанное решение, а не пробел: кроссплатформенно распаковать `.dmg` нельзя (нужен macOS-хост), а `app-zip` того же прогона несёт то же содержимое приложения — в депот уезжает он. `.dmg` остаётся артефактом GitHub Release для людей, скачивающих игру напрямую.

**Что покрыто тестами** (`../../tools/vn/tests/test_platform.py`, 13 тестов): `test_steam_stage_content_unpacks_dist` подкладывает **и** `vn-0.0.1-win.zip`, **и** реальный `vn-0.0.1-linux.tar.bz2`, и требует, чтобы встали **оба** депота с `errors == []` — то есть форматы зафиксированы, а не подразумеваются. `test_steam_stage_content_reports_missing_declared_platform` фиксирует обратное: если депот объявлен, а артефакта нет, это честная ошибка, а не пустой депот.

### 4.3.1 Каталог-обёртка: депот несёт игру в корне — IMPLEMENTED

Формат `zip` и `tar.bz2` launcher оборачивает содержимое в каталог с именем артефакта:
`FORMATS["zip"]` и `FORMATS["tar.bz2"]` имеют четвёртое поле `prepend = True`
(`distribute.rpy:1513-1530`), и на `:1580-1581` вызывается `fl.prepend_directory(filename)`. У
`app-zip` то же поле `False` — в mac-архиве в корне лежит сам `VN.app/`.

Шаблон VDF объявляет `LocalPath "content/<flavor>/<platform>/*"` с `recursive 1` и `DepotPath "."`,
поэтому обёртка уехала бы в депот как есть, и Launch Options пришлось бы править после каждого бампа
версии. `_flatten_wrapper_dir` (`release.py:186-212`) её разворачивает: если в распакованном ровно
один верхний узел и он каталог — содержимое поднимается на уровень выше. Правила:

- **mac-бандл не трогается** (`*.app` пропускается явно) — поднятие его `Contents/` в корень
  сломало бы приложение;
- **коллизия имени — `ReleaseError`**, а не тихая перезапись: `steam_stage_content` переводит её в
  `errors` и **не** добавляет платформу в `staged` (`release.py:302-307`) — депот с чужой раскладкой
  хуже отсутствующего;
- разворачивается только однозначный случай (один каталог и ничего рядом).

Практическое следствие для Steamworks: **Launch Options задаются от корня депота и не содержат
версии** — `vn.exe` (Windows), `vn.sh` (Linux), `VN.app/Contents/MacOS/<исполняемый>` (mac). Смена
версии игры их не меняет.

**Чего этот шаг всё ещё не гарантирует.** Разворачивание обёртки проверено тремя тестами на
синтетических архивах (`test_platform.py`: обёртка снимается, mac-бандл сохраняется, неоднозначный
случай отвергается), но **не на артефакте живого `launcher distribute`** — структуру взяли из кода
SDK. Через реальный SteamPipe раскладка ни разу не проходила, поэтому первую выкладку всё равно
сверяют глазами ([41-steam-deck.md](41-steam-deck.md) §2.3, [43-steam-qa.md](43-steam-qa.md)).

Ручной обход (распаковать `tar.bz2` в `build/steam/content/<flavor>/linux/` самому и запустить `steamcmd` на готовом VDF) больше не нужен, но остаётся рабочим — например, когда хочется подменить содержимое депота перед загрузкой. Обёртку в этом случае снимать придётся вручную.

### 4.4 Аплоад: steamcmd

`steamcmd` — консольный клиент Valve; в комплекте Steamworks SDK он же лежит как `tools/ContentBuilder/builder/steamcmd.exe`. Ставится на build-машину отдельно, в репозиторий не попадает.

```bash
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit
```

Что нужно знать до первого запуска:

- **Первый вход интерактивен**: Steam Guard запросит код, `steamcmd` сохранит sentry-файл рядом со своей конфигурацией. Для CI обычно завод**и**тся отдельный build-аккаунт с ролью «может выкладывать билды», и его sentry кладётся в раннер как секрет. Пароль в командной строке — плохая практика (попадёт в историю оболочки и в логи джобы).
- **Успех — это ещё не публикация.** При пустом `SetLive` билд загружен и виден в Steamworks → Builds, но ни в одной ветке не активен.
- **Логи и чанки** окажутся в `build/steam/output/` (см. §4.1) — это мусор сборки, `build/` уже в `.gitignore`.

Steam-проверок в релизном гейте нет ни одной: `vn release validate` о Steam не знает (см. полный список из 21 проверки в [29-build-and-release.md](29-build-and-release.md)), а `steam_libs_status` (`release.py:311`) вызывается ровно из одного места — `cli.py:1839`, и только как предупреждение. Практический вывод: **префлайт делает человек по этому разделу.**

### 4.5 Ветки и `SetLive`: почему release переключают руками

`--branch beta` — это одна строка в VDF (`"SetLive" "beta"`). Она означает «после успешной загрузки сделать этот билд активным в ветке beta». Требования, о которых VDF не расскажет:

- Ветка **должна существовать** в Steamworks (Steamworks → приложение → Builds/Betas). `SetLive` в несуществующую ветку публикацию не сделает.
- **Дефолтную ветку (`default`, то есть то, что видят все покупатели) мы через `--branch` не трогаем.** Норма проекта (`../../ci/steam/README.md`): выкладка идёт в бета-ветку, а `default` переключает человек в Steamworks — **после прогона на живом Steam Deck** ([43-steam-qa.md](43-steam-qa.md) §1).
- Каналов `dev`/`beta`/`release` как сущностей конвейера у нас нет, и pre-release-теги невозможны: `project@1` требует `version` вида `^\d+\.\d+\.\d+$`, поэтому тегов `v0.1.6-rc1` не бывает. Различие «что в beta, что в default» живёт только в Steamworks.
- Движок умеет спросить текущую ветку из игры: `achievement.steam.get_current_beta_name()` (`$RENPY_SDK/renpy/common/00steam.rpy:227`). **У нас не используется** (grep по `game/` — 0) и не нужно, пока нет ветвлений по каналу. Если понадобится «показать плашку BETA» — это новый capability-метод в `035_platform.rpy`, а не `if` в экране (см. [39-platforms.md](39-platforms.md) §9).

---

## 5. Ren'Py × Steam: как это включается и что движок делает сам

Официально: https://www.renpy.org/doc/html/achievement.html (модуль `achievement`, Steam-раздел, Workshop, `config.automatic_steam_timeline`). Исходники штатного стека — `$RENPY_SDK/renpy/common/00steam.rpy` (1085 строк) и `00achievement.rpy` (323 строки); читать их можно и нужно, править — нельзя (пин SDK, G18).

### 5.1 Единственный рычаг включения: `define config.steam_appid`

`_emit_platform` (`compile.py:133-152`) эмитит:

```renpy
define config.steam_appid = None            # или число из project.yaml
define VN_STEAM_DLC = {}                    # или {'ep_beach': 481, ...}
```

Почему именно `define`, а не присваивание в `init python` — теперь это не «так решили», а свойство движка: `config.steam_appid` входит в множество **`EARLY_CONFIG`** (`$RENPY_SDK/renpy/ast.py:61-75`), а `Define.early_execute()` применяет такие значения **до любого init-блока** (`ast.py:2444-2455`). Steam инициализируется на `init -1499` (`00steam.rpy:31`, `:1070-1071`) — раньше всего пользовательского кода, поэтому единственный способ успеть — early-define. В том же множестве, кстати, `save_directory`, `name`, `version`, `check_conflicting_properties` — ровно те `config`, которые у нас заданы `define` в `../../game/options.rpy:6-9`.

Соседний факт с практическим следствием: `config.enable_steam` объявлен движком в блоке **`python early:`** (`00steam.rpy:22-25`) и в `EARLY_CONFIG` **не входит**. Значит `define config.enable_steam = False` в нашем коде исполнится позже `init -1499` и Steam не выключит. Рабочий рычаг «выключить Steam при живой библиотеке» ровно один — переменная окружения `RENPY_NO_STEAM` (§5.3).

### 5.2 steam_api-библиотеки: как их положить и как они попадают в билд

Steam-поддержка Ren'Py **не входит в SDK**. Ставится лаунчером: **preferences → Install libraries → Install Steam Support** (`$RENPY_SDK/launcher/game/install.rpy:121-136`, кнопка ведёт на `label install_steam` → `add_dlc("steam", restart=True)`, `:220-222`). Экран честно предупреждает: «Before installing Steam support, please make sure you are a Steam partner» — то есть доступ гейтится участием в partner program. Ren'Py 8.5 требует **Steamworks SDK 1.62** (`$RENPY_SDK/doc/changelog.html:803`).

Куда попадают файлы и что проверяет тулинг (`steam_libs_status`, `release.py:312-326`):

| Платформа | Файл | Каталог |
|---|---|---|
| Windows x86_64 | `steam_api64.dll` | `$RENPY_SDK/lib/py3-windows-x86_64/` |
| Linux x86_64 | `libsteam_api.so` | `$RENPY_SDK/lib/py3-linux-x86_64/` |
| macOS universal | `libsteam_api.dylib` | `$RENPY_SDK/lib/py3-mac-universal/` |

Те же три файла можно разложить руками из `redistributable_bin/` Steamworks SDK. Признак «уже стоит» у лаунчера — `achievement.has_steam` (`install.rpy:121`), у distribute — наличие `lib/py3-linux-x86_64/libsteam_api.so` (`$RENPY_SDK/launcher/game/distribute.rpy:99`).

**Почему этого достаточно, чтобы библиотека уехала в дистрибутив:** distribute классифицирует зону `lib/` по платформам — `("lib/py*-windows-x86_64/**", "windows")`, `("lib/py*-linux-*/**", "linux")`, `("lib/py*-mac-*/**", "mac")` (`00build.rpy:120-129`). Всё, что вы положили в эти каталоги, едет с соответствующим пакетом. И там же оказывается рядом с `sys.executable` игрока (в дистрибутиве исполняемый файл движка — это `lib/py3-<platform>/renpy[.exe]`, `distribute.rpy:1268-1269`), а именно рядом с `sys.executable` движок и ищет библиотеку (§5.3).

В чекауте разработчика картина та же: `renpy.sh`/`renpy.exe` запускает `$RENPY_SDK/lib/py3-<platform>/renpy`, поэтому dev-прогон видит библиотеку из SDK.

Проверить статус:

```bash
vn release steam --flavor public   # печатает warning на каждую недостающую библиотеку
# warning: в SDK нет py3-mac-universal/libsteam_api.dylib — дистрибутив будет
#          standalone, не Steam-сборкой (ci/steam/README.md)
```

### 5.3 `steam_init`: как движок определяет наличие Steam

`00steam.rpy:996-1067`, вызывается на `init -1499` (`:1070-1071`) только на desktop-платформах (`if renpy.windows or renpy.macintosh or renpy.linux`, `:1069`). Порядок ровно такой:

| Шаг | Строки | Что происходит |
|---|---|---|
| 1 | `:1007-1014` | выбирается имя библиотеки по платформе и разрядности (`steam_api64.dll` / `steam_api.dll` / `libsteam_api.dylib` / `libsteam_api.so`) |
| 2 | `:1016-1017` | путь = каталог `sys.executable` + это имя; `has_steam = os.path.exists(dll_path)` |
| 3 | `:1019-1020` | **нет файла → `return`.** Молча. Никакой ошибки, никакого лога |
| 4 | `:1022-1023` | `not config.enable_steam` → `return` |
| 5 | `:1025-1026` | `"RENPY_NO_STEAM" in os.environ` → `return` |
| 6 | `:1028-1041` | загрузка DLL через `ctypes`, `steamapi.load`, `InitFlat`; ошибка инициализации → исключение |
| 7 | `:1043-1044` | `import store._renpysteam as steam` — с этого момента `achievement.steam` не `None` |
| 8 | `:1045-1047` | `config.periodic_callbacks.append(steam.periodic)`, `needs_redraw_callbacks`, позиция тостов `POSITION_TOP_RIGHT` |
| 9 | `:1049-1059` | Big Picture → вариант `steam_big_picture`; Steam Deck → вариант `steam_deck`, из вариантов убирается `large`, добавляются `medium` и `touch` |
| 10 | `:1061` | `backends.insert(0, SteamBackend())` — ачивки начинают уходить в Steam |
| 11 | `:1063-1067` | **любое исключение** → `write_log("Failed to initialize steam: …")`, `steam = None`, `steamapi = None` |

Три вывода, важных именно для нашего проекта:

1. **Без библиотеки та же сборка — обычный standalone.** Не «сломанная Steam-сборка», а полноценная игра: `vn_platform.steam()` вернёт `None` (`035_platform.rpy:19-23`), ownership-провайдер и провайдер ачивок просто не подключатся (`:71-89`), ачивки останутся в `persistent.vn_achievements`.
2. **Отладочный рычаг — `RENPY_NO_STEAM`.** Единственный способ прогнать сборку с библиотекой рядом как standalone и сравнить ветки (например «карточка пака есть / нет»). В хендбуке он до этого файла не упоминался; в коде проекта не используется (grep — 0), потому что это env, а не настройка.
3. **Отказ Steam выглядит как тишина.** Диагностика — единственная строка в `log.txt`: либо `Initialized steam.` (`:1062`), либо `Failed to initialize steam: …`. Наш фасад дописывает туда же `[vn] platform: steam deck=… bigpicture=… touch=…` (`035_platform.rpy:89`, `describe()` — `:50-53`).

Что движок делает **сам**, и что поэтому не надо писать в `035_platform.rpy`:

| Механика | Где | Наш статус |
|---|---|---|
| Варианты `steam_deck` / `steam_big_picture` + подмена `large`→`medium`+`touch` | `00steam.rpy:1049-1059` | используем через `vn_platform.is_steam_deck()` / `is_big_picture()` |
| Экранная клавиатура Deck для `input()` | `00steam.rpy:704-705`, `:756+` (`keyboard_periodic`) | ничего не делаем — работает само |
| Позиция тостов ачивок | `00steam.rpy:1047`; переопределяется `achievement.steam_position` (`00steam.rpy:885`, применяется на `init 1500`, `:1074-1085`) | `steam_position` не задаём (grep — 0) → дефолт top-right. OPTIONAL |
| Прокачка Steam-callbacks | `config.periodic_callbacks` (`00steam.rpy:1045`) | ничего не делаем |
| Ограничение фреймрейта на время Steam-операций (15 fps, `steam_maximum_framerate`) | `00steam.rpy:881` (`steam_maximum_framerate = 15`), `:899`, `:910` | ничего не делаем |
| Steam Timeline | `00steam.rpy:707-727` | включён по умолчанию, но мы его не кормим — §5.6 |
| `steam_appid.txt` в dev | `00steam.rpy:962-984` | §5.4 |

### 5.4 `steam_appid.txt`: dev-режим и защита от чужого App ID

`steam_preinit()` (`00steam.rpy:962-984`) выполняется до `steam_init()` (`:1070`):

- `config.steam_appid` задан → рядом с `sys.executable` создаётся `steam_appid.txt` с этим числом. Это стандартный приём Steamworks: запущенная **не из клиента** игра всё равно инициализирует API, читая appid из файла. Практически: в dev-чекауте файл появится в `$RENPY_SDK/lib/py3-<platform>/`.
- `config.steam_appid = None` → файл **удаляется** (`:980-984`). Это защита от «прошлый проект оставил свой appid, и наша игра тихо инициализировалась чужим приложением».
- В дистрибутив файл не попадает никогда (`00build.rpy:87`).

Следствие для QA: **локально Steam-путь проверяется без выкладки** — заполнили `appid`, `vn build`, положили библиотеку, запустили при живом Steam-клиенте (`vn play`). Ачивки и `dlc_installed` начнут работать по-настоящему.

### 5.5 Overlay

Оверлей рисует сам клиент Steam — от игры не требуется ничего, кроме корректной инициализации и того, что она не перехватывает ввод намертво. Что доступно движком и что у нас:

| API | Где | У нас |
|---|---|---|
| `is_overlay_enabled()` | `00steam.rpy:305-313` | обёрнут в `vn_platform.overlay_enabled()` (`035_platform.rpy:43-48`) — **ни одного потребителя** |
| `activate_overlay_to_store(appid, flag)` | `00steam.rpy:375-393` | **не используем.** Это прямой путь «пак не куплен → предложить купить»: сейчас при `owned() == False` карточка главы просто исчезает, а `screen vn_content_unavailable` купить не предлагает. **OPTIONAL/FUTURE** |
| `activate_overlay_to_web_page(url)` | `00steam.rpy:366-373` | не используем |
| `set_overlay_notification_position` | `00steam.rpy:340`, через `achievement.steam_position` | не задаём → top-right |

**RECOMMENDED FUTURE STATE:** «купить DLC из игры» — это новый метод фасада (`vn_platform.open_store(appid)`) + кнопка в `unavailable.rpy`, читающая `VN_STEAM_DLC`. Ветвления `if steam:` в экране быть не должно (гард-тест).

### 5.6 Steam Timeline — включён движком, но не наполнен

**STATUS: PARTIAL (движком — да, нашими данными — нет).**

`config.automatic_steam_timeline = True` — значение **по умолчанию** (`00steam.rpy:24-28`, документировано в `$RENPY_SDK/doc/achievement.html`). В `periodic()` (`00steam.rpy:707-727`) движок сам:

- ставит Timeline Game Mode `MENUS` или `PLAYING` по `store._menu`;
- открывает/закрывает **game phase** по строковой переменной `save_name`: `start_game_phase(save_name)` при смене значения, `end_game_phase()` перед этим. Changelog 8.5 прямо советует считать `save_name` именем главы (`$RENPY_SDK/doc/changelog.html:803`).

В нашем проекте `save_name` **не присваивается нигде** (grep по `game/`, `tools/vn/src/`, `content/` — 0 вхождений). Итог: у игрока в Timeline будет корректное «в меню / в игре» и ни одной фазы с человеческим названием.

**RECOMMENDED FUTURE STATE:** одна строка в обвязке сцены или в `vn.checkpoint` — `save_name = <название главы>` (локализованное `title_key` главы). Это же значение движок включает в метаданные сейва («A save name that is included with saves», `$RENPY_SDK/doc/store_variables.html`), так что улучшение двойное. Работа мелкая, но она меняет обвязку генерата — то есть требует правки эмиттера (`scenes.py`) и прогона `vn build`, а не ручной вставки.

### 5.7 DLC и владение паком

Рантайм-часть разобрана в [39-platforms.md](39-platforms.md) §5 и [30-packs-and-dlc.md](30-packs-and-dlc.md); здесь — процессная сторона.

| Что | Где | Статус |
|---|---|---|
| DLC как отдельное приложение в Steamworks (свой App ID, привязка к базовому) | Steamworks, руками | **нет** |
| `steam_dlc_appid` в манифесте пака | `pack_manifest@1` (`../../tools/schemas/pack_manifest@1.schema.json:32-35`) | схема есть, в `packs/*/manifest.yaml` поле не заполнено |
| Карта `pack_id → DLC App ID` в рантайме | `define VN_STEAM_DLC` (`compile.py:143-151`); пак без поля в карту не попадает (`test_platform.py:31-36`) | IMPLEMENTED |
| Проверка владения | `_steam_owns_pack` → `steam().dlc_installed(appid)` (`035_platform.rpy:55-68`; API — `00steam.rpy:244-250`) | IMPLEMENTED, fail-open |
| **Депот DLC** (куда физически кладётся контент пака) | `platform.steam.depots` допускает только `windows`/`linux`/`mac` при `additionalProperties: false` | **NOT IMPLEMENTED**: номер DLC-депота сегодня некуда положить даже как данные |

То есть сейчас у нас есть половина механизма: *владение* DLC читается, а *поставка* DLC-контента депотом — нет. **RECOMMENDED FUTURE STATE:** расширить `project@1` (например `platform.steam.pack_depots: {<pack_id>: <depot_id>}`) и `steam_app_build`, чтобы VDF получал дополнительные депоты с `LocalPath` пака; альтернатива — отдельный VDF на DLC-приложение. Решение требует ADR: оно меняет форму `platform.steam` и релизный путь.

Ограничение по построению остаётся: маппинг живёт в манифесте пака, поэтому **один пак — один DLC App ID**; бандлы собираются на стороне Steamworks.

Ещё одна возможность движка, к которой стыкуется `kind: mod` из `pack_manifest@1`: **Steam Workshop** — `get_subscribed_items()` и `get_subscribed_item_path()` (`00steam.rpy:483-533`). У нас не используется (grep — 0), моды — фаза 3 ([30-packs-and-dlc.md](30-packs-and-dlc.md) §10). Полезно знать, что перечисление подписанных айтемов движок уже умеет и своей инфраструктуры для этого не потребуется.

### 5.8 Данные пользователя Steam — OPTIONAL/FUTURE, не используем

Движок отдаёт `get_persona_name()` (`00steam.rpy:395-401`), `get_csteam_id()` (`:405-414`), `get_account_id()` (`:418-425`), `get_session_ticket()` (`:428+`), а также статы и прогресс-ачивки: `get_int_stat`/`set_int_stat` (`:166-190`), `retrieve_stats`/`store_stats` (`:43-64`), `indicate_achievement_progress` (`:125-140`).

**Ничего из этого в проекте не используется** (grep по `game/` — 0 вхождений каждого). Причины, по которым это не «недоделка»:

- имя игрока в VN не нужно ни для чего, кроме «здравствуй, <ник>» — а это привязка к платформе в контентном слое, то есть прямое нарушение ADR-0014;
- session ticket нужен только для серверной аутентификации, которой у автономной игры нет;
- статы и прогресс-ачивки требуют регистрации с `stat_max`/`stat_modulo` (`00achievement.rpy:160-190`) — см. §6.6.

Если что-то из этого понадобится — путь тот же: новый capability-метод в `035_platform.rpy`, а не импорт `_renpysteam` где-то ещё.

### 5.9 Что получает игрок в каждом из четырёх режимов

| Режим | `config.steam_appid` | Библиотека рядом | Что работает |
|---|---|---|---|
| **Сегодняшний dev/standalone** | `None` | не важно | Всё, кроме Steam: ачивки в `persistent`, паки по установленности, никаких вариантов Deck |
| **Сборка с appid, но без библиотеки** | число | нет | То же самое. `steam_preinit` создаст `steam_appid.txt`, `steam_init` выйдет на шаге 3 |
| **Steam-сборка, запущена из клиента** | число | да | Ачивки в Steam + догон офлайн-выдач, `dlc_installed`, оверлей, Timeline (menus/playing), варианты Deck/BP, экранная клавиатура Deck |
| **Steam-сборка, запущена мимо клиента** | число | да | API инициализируется через `steam_appid.txt`, если клиент запущен в системе; клиента нет — `InitFlat` не пройдёт, движок залогирует и уйдёт в standalone |

---

## 6. Ачивки: от `content/achievements/*.yaml` до Steamworks

### 6.1 Одно правило, которое нельзя нарушать

**API Name ачивки в Steamworks обязан ПОБУКВЕННО совпадать с её id из `content/achievements/*.yaml`.** Маппингов нет **намеренно**: движок принимает `achievement.register(name, steam="Другое_имя")` (`00achievement.rpy:160-190`), но мы регистрируем без kwargs — `achievement.register(_vn_aid)` (`035_platform.rpy:81`). Любая таблица соответствий стала бы вторым источником истины, который расходится молча и обнаруживается только жалобой игрока «ачивка не выдалась».

Конвенция id закреплена схемой (`../../tools/schemas/achievements@1.schema.json`): `propertyNames.pattern = ^[a-z][a-z0-9_]{2,47}$` — строчные латинские, цифры, подчёркивание, от 3 до 48 символов. Живые id: `met_mira`, `reached_rooftop` (`../../content/achievements/core.achievements.yaml`).

### 6.2 Полный путь ачивки в нашем проекте

| Этап | Файл | Что там |
|---|---|---|
| Объявление | `../../content/achievements/core.achievements.yaml` | id + `name_key`/`desc_key` + `trigger` (ровно один из `scene`/`beat`/`var`), опционально `hidden`, `nsfw`, `pack` |
| Реестр | `game/generated/registry/achievements.gen.rpy` (`init offset = -100`) | `define VN_ACHIEVEMENTS = {...}` — эмитит `_emit_achievements` (`compile.py:179`) |
| Локальная выдача | `../../game/framework/00_core/080_achievements.rpy` | `vn_ach.check()` прогоняет триггеры, `vn_ach.grant()` пишет `persistent.vn_achievements` и дёргает провайдера |
| Когда прогоняются триггеры | `../../game/framework/00_core/030_flow.rpy:12-29` | `vn.checkpoint(scene_id)`, `vn.beat(beat_id)`, `vn.chapter_done(chapter_id)` |
| Подключение Steam | `035_platform.rpy:71-89` (`init 999`) | `achievement.register(id)` для всех id → `vn_ach.set_provider(achievement.grant)` → догон уже выданных → `achievement.sync()` |
| Steam-бэкенд | `$RENPY_SDK/renpy/common/00steam.rpy:887-950` (`SteamBackend`) | `grant` → `steam.grant_achievement(name)` + `store_stats()` |

Фильтрация происходит **до** провайдера: `visible()` (`080_achievements.rpy:31-41`) скрывает NSFW-ачивки в SFW-флейворе и ачивки непринадлежащих паков, `grant()` для невидимой ачивки возвращает `False` и в Steam ничего не уходит.

### 6.3 Как добавить новую ачивку

```bash
# 1. Объявить (данные). Триггер — только стабильный якорь.
$EDITOR content/achievements/core.achievements.yaml
#   new_ach_id:
#     name_key: ach.new_ach_id.name
#     desc_key: ach.new_ach_id.desc
#     trigger: {scene: ch01_s030}          # либо {beat: …} либо {var: ch01.flag, equals: true}

# 2. Завести строки названия и описания (иначе UI покажет ключ)
$EDITOR content/ui/strings.yaml

# 3. Пересобрать реестр и проверить
vn build
grep new_ach_id game/generated/registry/achievements.gen.rpy

# 4. Проверить, что триггер вообще срабатывает: прогон + консоль разработчика
vn test smoke --picks 0,0          # прогон не падает и доходит до конца
vn play                            # Shift+O -> persistent.vn_achievements
#   консоль включена только в dev: 90_debug/010_dev.rpy (config.console = True),
#   этот каталог вырезается из релиза (options.rpy:31)

# 5. Посмотреть, как она выглядит игроку (экран достижений — 20_ui/screens/achievements.rpy)
VN_AUTOPILOT_SCREENS=achievements vn test smoke --picks 0,0
open .vncache/smoke/screen_achievements.png

# 6. Завести ачивку в Steamworks с API Name = new_ach_id  (§6.4)
```

**Автоматической проверки выдачи ачивок нет.** Автопилот дампит состояние (`state.json`) и галерею (`gallery.json`, `030_flow.rpy:186-211`), но `persistent.vn_achievements` — нет. Косвенный признак в прогоне: `vn_ach.grant` возвращает `True` и в UI уходит штатный `renpy.notify` только у галереи, у ачивок уведомления нет вовсе.

Грабли по порядку частоты:

- **`trigger.var` обязана существовать в Variable Registry** — иначе `vn build` покраснеет; шаблон в схеме: `^(g|ch\d{2}|mech_[a-z0-9_]+|dlc_[a-z0-9_]+)\.[a-z][a-z0-9_]*$`.
- **`trigger.beat` без ручного `$ vn.beat("name")` в сцене — мёртвый якорь.** Компилятор `vn.beat` не эмитит, это осознанно ([09-chapters.md](09-chapters.md)).
- **`var`-триггер срабатывает не мгновенно**: `check()` зовётся только из `vn.checkpoint` / `vn.beat` / `vn.chapter_done`, поэтому флаг, выставленный посреди сцены, откроет ачивку на следующей границе.
- **Ачивка пака** (`pack: ep_beach`) под Steam честно не выдастся тем, кто не купил DLC (`visible()` → `pack_registry.owned()`).

### 6.4 Что заводится в Steamworks на каждую ачивку

Документация Valve: https://partner.steamgames.com/doc/features/achievements . Минимум, который придётся сделать руками для каждой ачивки:

- **API Name** = наш id, побуквенно (§6.1);
- отображаемое название и описание **на каждом языке магазина** — это отдельная от нашей локализации копия текста: `name_key`/`desc_key` живут в игре, Steamworks своих строк из игры не читает;
- **две иконки**: полученная и не полученная (закрытая);
- флаг «скрытая», если у нас `hidden: true`;
- **публикация**: ачивки должны быть опубликованы в Steamworks до того, как игра начнёт их выдавать, иначе `grant` уходит в никуда.

Рассинхрон «ачивки в игре есть, в Steamworks нет» ничем у нас не проверяется — Steam-проверок в релизном гейте нет (§4.4). Ручная сверка: список id даёт `vn_ach.all_ids()` (`080_achievements.rpy:89-90`), он же — ключи `VN_ACHIEVEMENTS` в генерате.

### 6.5 Синхронизация и догон офлайн-выдач

Три механизма, все уже подключены (`035_platform.rpy:80-88`):

```renpy
for _vn_aid in vn_ach.all_ids():
    achievement.register(_vn_aid)          # те же стабильные id, без steam=
vn_ach.set_provider(achievement.grant)     # дальнейшие выдачи уходят и в Steam
for _vn_aid in vn_ach.all_ids():           # ДОГОН: выданное офлайн/до покупки Steam-версии
    if vn_ach.has(_vn_aid):
        achievement.grant(_vn_aid)          # grant идемпотентен (00achievement.rpy:193-201)
achievement.sync()                         # сводит бэкенды и батчит StoreStats
```

- `achievement.grant` сам проверяет `has()` и ничего не делает повторно (`00achievement.rpy:193-201`), поэтому догон безопасен на каждом старте.
- `achievement.sync()` (`00achievement.rpy:293-304`) идёт по `persistent._achievements` и выдаёт в те бэкенды, где ачивки нет. Наш локальный список хранится **отдельно** — в `persistent.vn_achievements`, поэтому догон делается нашим циклом, а `sync()` подчищает штатное хранилище движка.
- Ошибка провайдера не роняет игру: `vn_ach.grant` оборачивает вызов в `try/except` и пишет в лог (`080_achievements.rpy:59-62`).
- Готовое screen-action **`achievement.Sync()`** (`00achievement.rpy:306-322`) чувствительно только при расхождении бэкендов — кнопка «синхронизировать достижения» в настройках делается им, без своего кода. У нас её нет. **OPTIONAL.**

### 6.6 Чего у ачивок нет (честно)

| Возможность | Движок даёт | У нас | Комментарий |
|---|---|---|---|
| **UI достижений в игре** | — | **есть** | Экран `achievements` (`20_ui/screens/achievements.rpy`), пункт рельсы рядом с «Галереей». В standalone игрок видит прогресс в игре, под Steam — ещё и в оверлее/профиле. Скрытые (`hidden: true`) до получения показываются как «???» |
| **Прогресс-ачивки** («открыто 10 из 30 CG») | `register(..., stat_max=, stat_modulo=)`, `achievement.progress/grant_progress`, `steam.indicate_achievement_progress` (`00achievement.rpy:160-190`, `00steam.rpy:125-140`) | **нет**: регистрируем без kwargs, `vn_ach` знает только `grant/has/all_ids/visible`, а поля `progress` нет ни в схеме `achievements@1`, ни в эмиттере, ни на экране | **OPTIONAL/FUTURE**. Нужны сразу три правки: схема + `_emit_achievements` + счётчик в `vn_ach`. Плюс требует, чтобы `SteamBackend.progress` нашёл ачивку в `self.stats` — иначе в dev-режиме бросит исключение (`00steam.rpy:932-936`) |
| **Steam-статы** | `get_int_stat`/`set_int_stat`, `retrieve_stats`/`store_stats` | **нет** | Отдельная сущность Steamworks, заводится там же, где ачивки |
| **Сброс ачивок для тестов** | `SteamBackend.clear_all()` (`00steam.rpy:920-924`) | не выведено в наш UI | Для QA проще удалить `persistent` и сбросить статистику в клиенте Steam |

---

## 7. Steam Cloud

> **STATUS: NOT IMPLEMENTED — и это решение, а не долг.** В игре нет ни одного вызова Cloud API (grep по `game/` — 0). Норматив: `../../ci/steam/README.md`, раздел «Steam Cloud» — синхронизация делается **Auto-Cloud** в настройках Steamworks.

Почему так (то же обоснование, что в [39-platforms.md](39-platforms.md) §6, здесь — процессная часть):

- локальная система сейвов самодостаточна: `vn_save_schema` + цепочка миграций (G5) уже решает единственную реальную опасность синхронизации — «сейв из другой версии»;
- конфликты «две машины» разруливает клиент Steam своим UI; свой мердж сейвов VN — работа без выгоды;
- Cloud API в коде означал бы вторую точку касания платформы, то есть прямое нарушение ADR-0014.

### 7.1 Где Ren'Py хранит сохранения (по коду SDK)

Разрешение пути — `$RENPY_SDK/renpy.py:95-203` (`path_to_saves`), порядок проверок именно такой:

| Условие | Каталог |
|---|---|
| `config.save_directory` пуст | `<game>/saves` |
| переменная окружения `RENPY_PATH_TO_SAVES` | `$RENPY_PATH_TO_SAVES/<save_directory>` |
| выше каталога игры есть папка `Ren'Py Data` | `<…>/Ren'Py Data/<save_directory>` — «портативный» режим (флешка) |
| **Windows** | `%APPDATA%/RenPy/<save_directory>` (при отсутствии `APPDATA` — `~/RenPy/<save_directory>`) |
| **macOS** | `~/Library/RenPy/<save_directory>` |
| **Linux / Steam Deck** | `~/.renpy/<save_directory>` |

У нас `define config.save_directory = "vn-1755000000"` (`../../game/options.rpy:7`), то есть на Windows это `%APPDATA%/RenPy/vn-1755000000`.

> **Почему это важно ровно до буквы.** root-переменная Auto-Cloud выбирается из фиксированного списка Valve, и `WinAppDataLocal` вместо `WinAppDataRoaming` даст «Cloud настроен, но ничего не синхронизируется». Windows-путь — именно **`%APPDATA%`** (Roaming), `renpy.py:194-196`. Ранее норматив `../../ci/steam/README.md` называл здесь `%LOCALAPPDATA%`; исправлено, оба документа теперь совпадают.

> **`save_directory` не переименовывать.** `vn-1755000000` выглядит временным, но это штатное имя от лаунчера — `<simple_name>-<unixtime создания проекта>` (`$RENPY_SDK/launcher/game/gui7/parameters.py:113`). Переименование = смена каталога сейвов: у игроков «пропадает» весь прогресс и `persistent`, а Auto-Cloud начинает синхронизировать пустой каталог, продолжая держать старый в облаке. Если однажды всё же понадобится — это миграция при первом запуске, а не правка `options.rpy` (предохранитель — inline-комментарий на `../../game/options.rpy:7`).

### 7.2 Что синхронизировать и что нет

| Файл/маска | В Cloud? | Почему |
|---|---|---|
| `*.save` | **да** | Слоты. **Маску надо писать именно `*.save`**: полное имя файла — `<slot>-LT1.save`, потому что `renpy.savegame_suffix = "-LT1.save"` (`$RENPY_SDK/renpy/__init__.py:144`), и суффикс зависит от версии движка (наш тулинг это уже учитывает: `cli.py:1418`, «Ren'Py 8.5 добавляет к имени слота токен локации») |
| `persistent` | **да** | Открытая галерея, ачивки, настройки качества и масштаба, `_seen_images`. Файл **без расширения** — нужно отдельное правило, маской `*.save` он не покрывается (`$RENPY_SDK/renpy/savelocation.py:136-137`) |
| `persistent.new`, `*.<epoch>.tmp` | **нет** | Транзиентные файлы атомарной записи (`savelocation.py:46`, `:411-431`) |
| `crash/crash-*.txt` | **нет** | Наши крэш-отчёты в подкаталоге savedir (`../../game/framework/00_core/070_crash.rpy:27-34`) — диагностика, а не состояние игрока |
| `log.txt`, `traceback.txt`, `errors.txt` | **нет** | Их вообще нет в savedir: логи движок пишет в `basedir` (`$RENPY_SDK/renpy.py:218-230`, `path_to_logdir`) |
| Кэш и ассеты | **нет** | Живут в каталоге установки, синхронизируются депотом |

**Готовая конфигурация Auto-Cloud — в нормативе.** `../../ci/steam/README.md`, раздел «Steam Cloud»: шесть строк `Root / Path / Pattern` (`WinAppDataRoaming`, `MacHome`, `LinuxHome` × `*.save`, `persistent`), готовые к вводу в Steamworks. **Recursive там выключен намеренно** — иначе под маску попадёт подкаталог `crash/`. Маска `persistent` задана точным именем, а не `persistent*`: звёздочка затянула бы `.tmp`-мусор атомарной записи.

Имена root'ов сверить без партнёрского аккаунта нельзя — если интерфейс Steamworks покажет другие, прав интерфейс.

Там же в Steamworks задаются квота и максимум файлов — с автосейвами (`config.autosave_slots = 10`, `../../game/options.rpy:9`) и ручными слотами счёт файлов растёт, поэтому лимит «десяток файлов» ставить нельзя. Официально: https://partner.steamgames.com/doc/features/cloud .

### 7.3 Риски и что произойдёт на другом ПК или на Deck

| Ситуация | Что произойдёт | Чем закрыто |
|---|---|---|
| Сейв со **старой** схемой на новой версии | `label after_load` прогоняет цепочку миграций и повышает `vn_save_schema` до фактически применённой (`../../game/framework/00_core/020_state.rpy:83-107`) | G5, проверяется `vn save corpus` |
| Сейв из **будущей** версии (играли на другом ПК, там обновились раньше) | вниз не мигрируем: `block_rollback()` → сообщение `ui.flow.save_from_newer` → `full_restart()` (`020_state.rpy:86-95`) | G5. Блокировка сделана **до** `say`, чтобы гейт нельзя было объехать колёсиком |
| Дыра в цепочке миграций | схема поднимается только до применённой миграции + строка `migrations incomplete: …` в лог | `020_state.rpy:96-107` |
| Конфликт «две машины редактировали» | решает клиент Steam (диалог выбора версии); игра об этом не знает | осознанно (§7) |
| Сейв ссылается на сцену, которой в этой сборке нет (пак не установлен) | shim-метка → `vn_unavailable_reason = "missing_content"` → экран `vn_content_unavailable` | G7, `compile.py:_emit_overrides` |
| **Windows-сейв на Deck (или наоборот)** | Формат слота платформонезависим, но пути разные (§7.1). Если поставить нативный linux-пакет — `~/.renpy/…`; если играть Windows-сборку под Proton — путь окажется **внутри Proton-префикса**, и это уже другой корень для Auto-Cloud | не проверено; см. [43-steam-qa.md](43-steam-qa.md) |
| **Сейв приехал с другого устройства** | Движок спросит «This save was created on a different device…» и попросит подтвердить доверие один раз (`$RENPY_SDK/renpy/common/00gui.rpy:459-460`, логика — `renpy/savetoken.py:141-185`). Причина: ключ подписи генерируется **на устройстве** и лежит в `<корень>/tokens/security_keys.txt`, то есть **вне** синхронизируемого каталога (`savetoken.py:290-306`) | ничем и не должно: подставить общий ключ нельзя — `config.save_token_keys` принимает только verifying-ключи и явно отвергает signing (`savetoken.py:316-337`). Это штатное поведение Cloud-переноса, а не дефект |

### 7.4 Как проверять сейвы без Cloud

```bash
vn save check                 # оффлайн: структура слота, JSON-заголовок, vn_save_schema
vn save corpus                # каждая фикстура ЗАГРУЖАЕТСЯ в реальной игре + миграции
vn save corpus --add my_case  # новая фикстура из прогона (сохранение на тике 4)
```

`vn save check` (`cli.py:1323-1348`) читает `json`-запись из zip-слота без unpickle и проверяет `vn_save_schema` (заголовок пишет `config.save_json_callbacks`, `../../game/framework/00_core/001_boot.rpy:31-36`). `vn save corpus` (`cli.py:1391-1480`) поднимает игру с `--savedir`, грузит слот, прогоняет `after_load` и сверяет фактическую пост-миграционную схему с `project.yaml: save_schema`. Обе гоняются в nightly (`../../.github/workflows/nightly.yml:64-65`).

Ручная проверка «перенос на другую машину» = скопировать каталог из §7.1 на другой ПК и запустить. Именно это и делает Auto-Cloud, только руками.

---

## Как изменить / Как расширить

| Задача | Что править | Обязательно после |
|---|---|---|
| Включить Steam в этом репозитории | `project.yaml: platform.steam.appid` **и** `platform.steam.depots` | `vn build` (перегенерит `platform.gen.rpy`), `vn release steam --flavor public`, прогон на живом Deck перед `setlive default` |
| Положить steam_api на build-машину | лаунчер SDK → preferences → Install libraries → Install Steam Support | `vn release steam` не должен печатать warning про библиотеки |
| Добавить платформу в раскладку депотов | `_DIST_SUFFIX` (`release.py:158-162`) — суффикс имени + кортеж расширений по приоритету; `_extract_archive` (`:173-183`), если формат не zip и не tar.bz2; `_flatten_wrapper_dir` (`:186-212`), если у формата своя обёртка | кейс в `test_platform.py` с **реальным** архивом этого формата; сверить формат по `00build.rpy:421-432`, а не по предположению |
| Отгружать не все три платформы | `project.yaml: platform.steam.depots` — оставить только нужные номера; раскладка сама ожидает ровно объявленные платформы (`release.py:288-289`) | `vn release steam --flavor <f>`: платформы без депота не должны давать `error` |
| Добавить ачивку | `content/achievements/*.yaml` + `content/ui/strings.yaml` — экран `achievements` правок не требует, он читает реестр | `vn build`, `VN_AUTOPILOT_SCREENS=achievements vn test smoke --picks 0,0` и просмотр `screen_achievements.png`, завести API Name в Steamworks (§6.4) |
| Привязать пак к DLC | `packs/<id>/manifest.yaml: steam_dlc_appid` | `vn pack validate`, `vn build`; проверить, что `owned()` даёт `False` без DLC |
| Кормить Steam Timeline | присваивание `save_name` в обвязке сцены — то есть эмиттер `scenes.py` | `vn build`, `vn content compile --check`, прогон под живым Steam |
| Предлагать покупку DLC из игры | новый метод фасада (`035_platform.rpy`) поверх `activate_overlay_to_store` + кнопка в `unavailable.rpy` | гард-тест `test_platform.py:183` должен остаться зелёным |
| Кнопка «синхронизировать достижения» | `achievement.Sync()` как action в `core_screens.rpy` (или на экране достижений) | без своего кода синхронизации |
| Выложить сборку из CI | `.github/workflows/steam-upload.yml` — ручной запуск; секреты `STEAM_USERNAME` + `STEAM_CONFIG_VDF` (base64 сентри Steam Guard, снимается один раз вручную) | процедура в `../../ci/steam/README.md` §2; без секретов шаг аплоада — зелёный no-op |
| Steam-префлайт в релизном гейте | `validate_release` (`release.py:525-750`): appid/depots заполнены, шаблон VDF на месте, `steam_libs_status` пуст, для каждого депота есть артефакт **ожидаемого формата** | обновить счётчик проверок в [29-build-and-release.md](29-build-and-release.md) |
| Депот для DLC-пака | расширение `project@1` + `steam_app_build` | **ADR**: меняет форму `platform.steam` и релизный путь |
| Steam Cloud через API вместо Auto-Cloud | **не делать без ADR** — вторая точка касания платформы (§7) | — |

---

## Чего НЕ делать

- **Не коммитить steam_api-библиотеки, Steamworks SDK и `steamcmd`** — лицензия Valve. Место библиотек — `$RENPY_SDK/lib/py3-*/` на build-машине.
- **Не хранить логин/пароль/Steam Guard `steamcmd`** нигде в репозитории, включая VDF и workflow-файлы. Только секреты раннера или интерактивный вход. И не передавать секрет `steamcmd` аргументом командной строки: аргументы видны в логе процесса — `steam-upload.yml` пишет `config.vdf` файлом именно поэтому.
- **Не задавать Launch Options через имя каталога-обёртки** — обёртку депота разворачивает раскладка, путь пишется от корня и не зависит от версии (§4.3.1).
- **Не задавать `config.steam_appid` присваиванием в `init python`** — он в `EARLY_CONFIG` (`ast.py:61-75`) и обязан быть `define` из генерата, иначе `steam_init` на `init -1499` его не увидит.
- **Не пытаться выключить Steam через `define config.enable_steam = False`** — этот `config` живёт в `python early` движка и в `EARLY_CONFIG` не входит; сработает только `RENPY_NO_STEAM` (§5.3).
- **Не считать `appid: null` поломкой** — это штатное «Steam выключен», и на этом поведении стоит половина тестов проекта.
- **Не заводить таблицу «наш id ачивки → API Name Steamworks»** и не передавать `steam=` в `achievement.register` — совпадение побуквенное (§6.1).
- **Не менять и не удалять id выпущенной ачивки.** Последствия разные и все плохие: в Steamworks она станет «чужой» и перестанет выдаваться, локально `persistent.vn_achievements` будет хранить мёртвый ключ, а `vn_ach.grant` неизвестного id только залогирует (`080_achievements.rpy:49-51`) — то есть тишина вместо ошибки.
- **Не считать `vn release steam` аплоадом.** Она готовит VDF и раскладку; `steamcmd` запускает человек или CI с секретами вне репозитория.
- **Не выкладывать в `default`-ветку, не прогнав на живом Steam Deck** — smoke под `RENPY_VARIANT` проверяет вёрстку, но не пад, не оверлей и не Steam API ([43-steam-qa.md](43-steam-qa.md)).
- **Не ждать, что релизный гейт поймает Steam-проблемы** — в нём нет ни одной Steam-проверки (§4.4).
- **Не настраивать Auto-Cloud на `%LOCALAPPDATA%`** — Ren'Py пишет в `%APPDATA%` (§7.1).
- **Не добавлять в Cloud `persistent.new`, `*.tmp` и `crash/`** — транзиенты и диагностика (§7.2).
- **Не писать `if steam:` вне `035_platform.rpy`** — гард-тест `test_platform::test_platform_facade_is_single_steam_touchpoint` покраснеет, и это правильно.

---

## Проверка

```bash
# 1. Генерат платформы (сейчас Steam выключен)
vn build && cat game/generated/platform.gen.rpy
#   define config.steam_appid = None
#   define VN_STEAM_DLC = {}

# 2. Тулинг Steam-поставки: эмиттер, VDF, раскладка депотов, статус библиотек, гард-тест
python -m pytest tools/vn/tests/test_platform.py -q            # 13 passed

# 3. Контракт со штатным стеком движка (нужен RENPY_SDK, иначе skip)
python -m pytest tools/vn/tests/test_engine_compat.py::test_steam_engine_contract -q

# 4. Команда поставки на репозитории без Steamworks-приложения
vn release steam --flavor public
#   ошибка: platform.steam.appid не задан в project.yaml — заполните App ID из Steamworks (публичный, не секрет)
#   exit 1  <- ОЖИДАЕМОЕ поведение

# 5. Релизный гейт (Steam-проверок в нём нет). Сейчас оба флейвора зелёные (exit 0);
#    у public есть WARN зрелости контента — release-глав в проекте пока нет
vn release validate --flavor public
vn release validate --flavor patron

# 6. Сейвы (единственная часть Cloud-темы, которую можно проверить локально)
vn save check && vn save corpus
```

Эталон на 2026-08-18 (HEAD `e3c2842` + текущая итерация, `vn` из `tools/vn/.venv`):

- `test_platform.py` — **13 passed** за ~0.4 с, ни один тест не требует SDK; три новых — про разворачивание каталога-обёртки депота (§4.3.1);
- `vn release steam --flavor public` — **exit 1** с сообщением про `appid`;
- `vn release validate --flavor public` — **20 строк, 18 PASS + 2 WARN, 0 FAIL, exit 0**: WARN — `зрелость контента: ни одна глава ещё не доведена до status=release (ch01)` (гейт самоактивирующийся, [29-build-and-release.md](29-build-and-release.md) §5.1 №4) и `озвучка: 14 черновых дублей (draft)`. `--flavor patron` — **21 строка**, один WARN, тоже exit 0;
- `game/generated/platform.gen.rpy` — Steam выключен.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | [`../adr/0014-platform-services.md`](../adr/0014-platform-services.md) (**норматив**, целиком), `../../ci/steam/README.md`, `../../ci/steam/app_build.vdf.tmpl`, `../../project.yaml:13-15`, `../../tools/vn/src/vn/release.py:150-326`, `../../tools/vn/src/vn/cli.py:1819-1852`, `../../tools/vn/src/vn/content/compile.py:133-152`, `../../game/framework/00_core/035_platform.rpy` (весь, 89 строк), `../../game/framework/00_core/080_achievements.rpy`, `../../game/framework/20_ui/screens/achievements.rpy`, `$RENPY_SDK/renpy/common/00steam.rpy` (`962-1071` — инициализация; `887-950` — SteamBackend), `$RENPY_SDK/renpy/ast.py:61-75` (`EARLY_CONFIG`), `$RENPY_SDK/renpy.py:95-203` (`path_to_saves`) |
| **Не трогать** | `game/generated/platform.gen.rpy` — генерат; `build/steam/**` — артефакт `vn release steam`; `$RENPY_SDK/**` — пиннованный движок (G18), только чтение; steam_api-библиотеки и Steamworks SDK — их в репозитории нет и добавлять нельзя; id уже выпущенных ачивок |
| **Зависимости (что ломается ниже по течению)** | `project.yaml: platform.steam` → `platform.gen.rpy` → `config.steam_appid` (early-define) → `steam_init` → варианты Deck/BP, `SteamBackend`, `dlc_installed`. `steam_dlc_appid` в манифесте пака → `VN_STEAM_DLC` → `owned()` → карточки глав в `chapter_select`, элементы галереи, видимость ачивок. `content/achievements/*.yaml` → `VN_ACHIEVEMENTS` → `achievement.register` → **имена в Steamworks**. `config.save_directory` → путь сейвов → корень Auto-Cloud |
| **Валидация** | `python -m pytest tools/vn/tests/test_platform.py -q` (13 passed) → `python -m pytest tools/vn/tests -q` → `vn build && cat game/generated/platform.gen.rpy` → `vn release validate --flavor public` → `vn save check && vn save corpus` → (при заполненном appid) `vn release steam --flavor public` → предрелизная приёмка [43-steam-qa.md](43-steam-qa.md) |
| **Частые ошибки** | 1) Считать, что `depots` можно оставить как `appid: null` — ключа в файле нет вовсе, и ошибка вылезет только вторым запуском (§1.1). 2) Ждать от `--package linux` зипа: движок отдаёт `tar.bz2` — раскладка это знает и распаковывает (§4.3), но всё, что вы пишете рядом руками, должно исходить из фактического формата. И не читать «раскладка работает» как «поставка пройдена»: `appid` пуст, аплоад ручной, живого прогона не было. 3) Читать `vn release steam` как аплоад — она готовит VDF и раскладку. 4) Переносить VDF без каталога `content/` — пути в нём относительны самого VDF (§4.1). 5) Выключать Steam через `config.enable_steam` вместо `RENPY_NO_STEAM` (§5.3). 6) Настраивать Auto-Cloud на `%LOCALAPPDATA%` — Ren'Py пишет в `%APPDATA%` (§7.1); и включать там Recursive — затянет `crash/` (§7.2). 7) Синхронизировать `persistent` маской `*.save` — файл без расширения, нужно отдельное правило (§7.2). 8) Ждать Steam-проверок от релизного гейта — их нет (§4.4). 9) Считать Steam Timeline сломанным: движок его включил сам, просто `save_name` мы не присваиваем (§5.6). 10) Считать Steam Cloud недоделкой — кода нет осознанно (§7). 11) Задавать Launch Options через имя каталога-обёртки (`vn-<версия>-win/vn.exe`) — обёртки в депоте больше нет, путь пишется от корня и не зависит от версии (§4.3.1). 12) Писать, что UI достижений нет — экран `achievements` есть с этой итерации (§6.6) |

---

**Смежные страницы:** [39-platforms.md](39-platforms.md) (архитектура платформенного слоя, controller-first UX, Deck/Big Picture) · [41-steam-deck.md](41-steam-deck.md) (доставка и прогон на устройстве) · [43-steam-qa.md](43-steam-qa.md) (предрелизная приёмка Steam/Deck) · [29-build-and-release.md](29-build-and-release.md) (флейворы, релизный гейт, дистрибутивы) · [30-packs-and-dlc.md](30-packs-and-dlc.md) (формат пака, логический гейт владения G9) · [33-security-and-legal.md](33-security-and-legal.md) (организационные сроки Steamworks, лицензии, 18+) · [15-gallery.md](15-gallery.md) (подсистема достижений и галереи) · [27-testing.md](27-testing.md) (smoke-автопилот, сейв-корпус)
