# 33. Безопасность и лицензии

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — состав дистрибутива закрыт жёстко и проверяемо (`build.classify`, проверено по реальному zip), реестр лицензий и релизный гейт написаны и подключены, утечка patron-токена в дистрибутив закрыта (ADR-0011: наружу едет метка `patron_tag`, не токен). **Но:** гейт лицензий сегодня ИНЕРТЕН (0 деклараций рендеров), `sha256` всех моделей в манифесте — `null`, а ADR-0008 (лицензии AI-моделей для 18+) остаётся **единственным непринятым ADR** проекта.
> **Отвечает на вопрос:** «Какие секреты есть в проекте и где они текут; что уезжает игроку, а что не должно; и что нужно закрыть по лицензиям, прежде чем брать за игру деньги».

Файл состоит из двух половин. Первая — техническая: секреты, состав дистрибутива, честная оценка защиты от копирования, цепочка поставок. Вторая — правовая механика проекта: `content/licenses.yaml` (`license_registry@1`), гейт `vn assets licenses`, реестр моделей `tools/comfyui-models.yaml`, `docs/licenses/THIRD-PARTY-NOTICES.md` и таблица источников контента с официальными ссылками.

## Быстрый ответ

```bash
vn assets licenses                     # реестр лицензий vs декларации рендеров
vn release validate --flavor public    # 19 проверок; #15 — лицензии ассетов
vn release validate --flavor patron
vn pipeline models                     # статусы моделей (id, размер, путь, required, способ авторизации)
grep -n "license\|commercial_use" tools/comfyui-models.yaml   # лицензии моделей видны ТОЛЬКО в YAML
python -m pytest tools/vn/tests/test_licenses.py -q
```

| Что | Где живёт |
|---|---|
| Реестр лицензий покупных ассетов | [`content/licenses.yaml`](../../content/licenses.yaml) (`license_registry@1`) |
| Схема реестра | [`tools/schemas/license_registry@1.schema.json`](../../tools/schemas/license_registry@1.schema.json) |
| Гейт | [`tools/vn/src/vn/assets/licenses.py:53-109`](../../tools/vn/src/vn/assets/licenses.py), подключён в [`release.py:436-445`](../../tools/vn/src/vn/release.py) |
| Уведомления, едущие с игрой | [`docs/licenses/THIRD-PARTY-NOTICES.md`](../licenses/THIRD-PARTY-NOTICES.md) |
| Лицензии AI-моделей | [`tools/comfyui-models.yaml`](../../tools/comfyui-models.yaml), поля `license` / `commercial_use` / `nsfw_terms_url` |
| Открытая правовая развилка | [ADR-0008](../adr/0008-ai-model-licensing-for-commercial-adult-content.md) — статус «предложено» |
| Состав дистрибутива | [`game/options.rpy:13-51`](../../game/options.rpy) |
| Тексты OFL | `game/fonts/OFL-Inter.txt`, `game/fonts/OFL-Literata.txt` |

---

# Часть 1. Безопасность

## 1. Инвентарь секретов

Секретов в проекте ровно три вида, и ни одного из них нет в git.

| Секрет | Где задаётся | Кто читает | Статус |
|---|---|---|---|
| `CIVITAI_API_KEY` | User-окружение Windows (`setx`) | `pipeline.py:313-315` → заголовок `Authorization: Bearer` при скачивании NSFW-LoRA | IMPLEMENTED |
| `--patron-token` | флаг `vn release build`, в CI — `secrets.PATRON_TOKEN` | `release.py:206-227` (`patron_tag`) → в `game/build_id.json` уходит **только 8-hex метка** (`release.py:253`) → `060_build_info.rpy:40` | IMPLEMENTED, секрет не покидает машину сборки (§3) |
| `GITHUB_TOKEN` | выдаётся раннером (`${{ github.token }}`) | шаг `gh release create` в `.github/workflows/release.yml` | IMPLEMENTED |

**Проверено grep-ом:** захардкоженных ключей/паролей/токенов в `tools/`, `game/framework/`, `content/`, `ci/` нет. В `.github/workflows/` всего два обращения к секретам: `permissions: contents: write` (`release.yml:15-16`) и `PATRON_TOKEN: ${{ secrets.PATRON_TOKEN }}` (`release.yml:81`).

**Где обеспечено, что `CIVITAI_API_KEY` не течёт:**

- **не в логи** — ключ используется ровно один раз, для сборки заголовка (`pipeline.py:403`); ни одна `click.echo`/`click.secho` в `pipeline.py` его не печатает. Печатается только инструкция «как завести ключ» (`pipeline.py:398-400`);
- **не в lock** — `<ComfyUI>/models/.vn-models.json` (`MODELS_LOCK_NAME`, `pipeline.py:32`; фактически `D:\ComfyUI\models\.vn-models.json`) хранит только `sha256`, `size_mb`, `downloaded_at`, `source` (`pipeline.py:420-425`);
- **не в git** — файл лежит вне репозитория, в дереве ComfyUI;
- **не в провенанс** — `provenance.py` извлекает данные из tEXt-чанков PNG ComfyUI (`prompt` / `workflow`, `provenance.py:91-95`): граф, модель, seed, промпты. Окружение процесса он не читает вообще.

**Честная оговорка (IMPLEMENTED-UNDOCUMENTED):** ключ передаётся в `curl` как аргумент `-H "Authorization: Bearer …"` (`pipeline.py:341-345`), то есть на время загрузки он виден в списке процессов машины. Для однопользовательской рабочей станции это приемлемо; на общей машине — нет. Плюс `setx` кладёт значение в `HKCU\Environment` открытым текстом — это свойство Windows, а не проекта.

**Грабля `setx`.** `setx` виден только **новым** процессам. Код это знает и отдельно проверяет реестр (`_civitai_key_in_registry`, `pipeline.py:318-330`): если ключ есть в `HKCU\Environment`, но не в окружении процесса, печатается «ключ ЕСТЬ в User-окружении, но не виден этому процессу — откройте НОВЫЙ терминал».

**Чего в проекте НЕТ (и это хорошо):** ни одного сетевого вызова в `game/framework/` (grep по `urlopen|requests.|socket|http` — ноль). Игра не звонит наружу, телеметрии нет, ключей аналитики в клиенте нет. `ARCHITECTURE.md:4018` заранее фиксирует честную позицию на будущее: клиентский ключ аналитики спрятать нельзя, опора будет на серверный rate-limiting провайдера. Статус аналитики — **NOT IMPLEMENTED**.

## 2. Что уезжает игроку: состав дистрибутива

Ren'Py по умолчанию пакует **всё дерево проекта**: последнее правило в SDK — `("**", "all")` (`<RENPY_SDK>/renpy/common/00build.rpy:233`). То есть без `build.classify(..., None)` в дистрибутив уехали бы `content/`, `assets_src/`, `tools/`, `.git/` — целиком. Отсечение делает [`game/options.rpy:13-51`](../../game/options.rpy) — **IMPLEMENTED**.

| Что исключается | Строка | Зачем |
|---|---|---|
| `tools/**` | `options.rpy:17` | весь CLI проекта |
| `content/**`, `packs/**` | `:17-18` | источник истины: YAML-декларации, авторские `.scene.rpy` **всех** глав, включая неопубликованные — прямые спойлеры |
| `assets_src/**` | `:17` | сырцы в полном разрешении, PSD, DAZ-сцены — основной актив студии |
| `loc/**` | `:17` | PO-файлы содержат каждую реплику, в т.ч. непереведённую и невыпущенную |
| `docs/**` | `:17` | ADR, роадмап, внутренние решения |
| `ci/**` | `:18` | фикстуры сейвов, конфигурация пайплайнов |
| `build/**` | `:18` | **самый опасный пункт**: там лежат дистрибутивы прошлых флейворов. Без этого правила `public`-сборка могла бы утащить внутрь себя patron-zip |
| `.vncache/**`, `.git/**` | `:18` | кэш трансформаций и вся история репозитория |
| `.gitignore`, `.gitattributes`, `.gitlab-ci.yml`, `CODEOWNERS`, `README.md`, `project.yaml`, `.vnstorage.yaml` | `:19-20` | конфигурация процесса, не игры |
| `hdrs.tmp`, `log.txt`, `traceback.txt`, `errors.txt` | `:20-21` | локальные логи разработчика |
| `game/framework/90_debug/**` | `:24` | dev-меню, Shift+J-переход по сценам |
| `game/generated/qa/**` | `:25` | QA-генерат (каталога сейчас нет — правило на вырост) |
| `game/generated/manifest.json` | `:26` | хэши входов сборки |
| synthetic-языки (`pseudo`) | `:27-40` | псевдолокаль — QA-инструмент; исключается **по манифесту** `tl/<code>/language.json: synthetic`, без хардкода кодов |
| NSFW-каталоги для SFW-флейвора | `:41-51` | глобы приходят из `game/build_id.json: exclude`, который считает `release.py:192-203` |

**Проверено по реальному артефакту.** В `build/dist/0.1.0-patron/vn-0.1.0+d020c37-win.zip` (1618 записей) корневых зон ровно четыре: `game/` (121), `lib/` (941), `renpy/` (554), `vn.exe` + `vn.py`. Записей с `/content/`, `/tools/`, `/assets_src/`, `/loc/`, `/docs/`, `/90_debug/` — **ноль**. В `game/tl/` — `de`, `en`, нет `pseudo`. `game/generated/manifest.json` отсутствует.

**Грабля флейворов** ([`01-project-overview.md`](01-project-overview.md), [`30-packs-and-dlc.md`](30-packs-and-dlc.md)): исключение NSFW считается по **фактическим** каталогам `game/assets/<cat>/nsfw/` (`release.py:192-203`). Такого каталога сейчас нет ни одного, поэтому в обоих `build-info.json` лежит `"exclude": []`, а `VN_PACKS` перечисляет пак `nsfw` независимо от флейвора. Отсечение 18+ в `public`-сборке **сегодня опирается только на то, что NSFW-контента ещё не существует** — это не защита, это отсутствие данных.

## 3. Метка получателя patron-сборки — IMPLEMENTED (ADR-0011)

**Дыра закрыта 2026-08-08.** Раньше `--patron-token` писался в `game/build_id.json` как есть, а этот файл физически едет внутри дистрибутива — иначе рантайм не смог бы его прочитать (`060_build_info.rpy:27`), и ни одно правило `classify` его не исключает и исключить не может. Артефакт-улика лежит на диске до сих пор: в `build/dist/0.1.0-patron/vn-0.1.0+d020c37-win.zip` внутри `game/build_id.json` — `"patron_token": "tok_demo42"`, схема `build_info@1`. 

**Насколько дефект успел сработать (проверено 2026-08-08):** секрет `PATRON_TOKEN` в репозитории **не заведён** — `gh secret list` пуст, а `release.yml:84` передаёт флаг только при непустом значении. Реальные CI-сборки уезжали с `patron_token: null`, то есть настоящий секрет наружу не попадал ни разу; утёк бы он в день, когда секрет завели бы. Проверено на скачанном артефакте `dist-patron` прогона v0.1.5: `patron_tag: null`, поля `patron_token` в документе больше нет вовсе.

**Как устроено сейчас.** `vn release build --patron-token <токен>` (`cli.py:1510-1511`) по-прежнему принимает токен, но наружу уходит односторонняя производная:

```python
# tools/vn/src/vn/release.py:206-227
hashlib.blake2s(token.encode("utf-8"), digest_size=4, person=b"vnpatron").hexdigest()
```

Восемь hex-символов кладутся в поле `patron_tag` документа `build_info@2` (`release.py:253`), рантайм читает готовую метку (`060_build_info.rpy:40`), вотермарка рисует `build_id · <patron_tag>` (`060_build_info.rpy:42-45`, экран `build_overlay.rpy:6-17`). Схема бампнута `build_info@1` → `@2`; старая осталась в реестре с пометкой «УСТАРЕЛА», чтобы читались архивные `build-info.json`.

**Проверка сквозным прогоном** (ADR-0011, раздел «Последствия»): в собранной patron-сборке 1663 файла, токен не встречается **ни в одном**.

Сопоставление «утёкшая сборка → получатель» не потеряно: метка детерминирована, владелец пересчитывает её из своего токена одной строкой.

```bash
python -c "import hashlib,sys; print(hashlib.blake2s(sys.argv[1].encode(), digest_size=4, person=b'vnpatron').hexdigest())" tok_demo42
# caf5afd4
```

Что осталось знать и делать:

1. **Токен-метку получателя обязательно генерировать случайной** — `secrets.token_hex(16)` или эквивалент. Это единственное новое требование к процессу и оно жёсткое: короткий низкоэнтропийный токен (`mira2026`, ник, e-mail) подбирается по 8-символьной метке перебором за секунды. Метка не обратима математически, но словарь ей не помеха.
2. **Соответствие «метка → получатель» нигде в репозитории не хранится** — реестр выданных токенов ведёт владелец вне репозитория, метка вычисляется по требованию.
3. **Токен по-прежнему один на всю patron-сборку**: CI подставляет единственный репозиторный `secrets.PATRON_TOKEN` для всей матрицы (`release.yml:78-87`). Это трассирует «какая сборка утекла», а не «кто её слил». Персональная раздача = отдельный прогон `vn release build --patron-token <id>` на получателя, автоматизации этого в проекте **NOT IMPLEMENTED**.
4. **Метка не защищает от вырезания.** Кто угодно распакует zip, найдёт `build_id.json` и удалит поле. Вотермарка — сдерживающий фактор для ленивого, не DRM (§4).
5. **Артефакты сборок до 0.1.5 содержат токен открытым текстом.** Если там был боевой секрет — отозвать и перевыпустить; разовое действие вне кода.

`game/build_id.json` живёт только на время `distribute`: он в `.gitignore:8` и удаляется в `finally` (`cli.py:1558`), поэтому dev-чекаут никогда не носит чужой флейвор и вотермарку.

## 4. Честно про защиту от копирования

**Технической защиты нет, и это осознанное решение проекта**, а не недоработка. `ARCHITECTURE.md:3275` и `:4177` формулируют прямо: гейт владения DLC — логический, не криптографический; `.rpa` распаковывается извне; «цена честной защиты несоразмерна жанру».

Что проверено по фактам:

- **`.rpa`-архивы в проекте не используются — по норме.** `build.archive` не встречается в `game/` ни разу, и `ARCHITECTURE.md` §2.4 (`:943`) фиксирует россыпь как норму: Steam дельта-патчит отдельные файлы, а защиты `.rpa` всё равно не даёт (распаковывается извне, G9). Тематическая упаковка (`archive_spr.rpa`, `archive_bg.rpa`) осталась лишь опцией mobile-поставки фазы 3, её появление в desktop-дистрибутиве — осознанное решение с ADR. Сама документация Ren'Py про архивы: «While not very secure, this protects files from casual copying» (https://www.renpy.org/doc/html/build.html).
- **Скрипт едет открытым текстом.** В patron-zip лежат 36 `.rpy` и 36 `.rpyc`. Генерируемая сцена содержит авторское тело целиком: `game/generated/scenes/ch01/ch01_s010.gen.rpy` включает секцию «Авторский источник (копия)» с блоком `label ch01_s010__body:` и всеми репликами. То есть распаковщик даже не нужен — достаточно распаковать zip.
- **Декомпилятор существует и работает.** `unrpyc` v2.0.4 (2026-02-24, MIT, https://github.com/CensoredUsername/unrpyc) восстанавливает `.rpy` из `.rpyc` для Ren'Py 8.x. Инструменты семейства «распаковать чужую VN» публичны и общеизвестны в жанре.
- **Вотермарка ≠ защита.** `build_overlay.rpy` — 17 строк, статичный полупрозрачный текст в углу; никакого рантайм-трекинга. Это трассировка утечки, а не DRM.

**Что из этого следует практически.** Продаётся время и удобство (ранний доступ, готовая сборка, обновления), а не эксклюзивность битов. И жёсткое правило: **в `.rpy` не должно быть ничего секретного** — ни ключей, ни логики гейтинга, на которую вы всерьёз рассчитываете. Ren'Py не умеет песочничать Python (`ARCHITECTURE.md:3349`): любой `.rpyc` исполняется с полными правами процесса, поэтому «поддержка модов» = организационный контракт с ревью, а не техническая изоляция.

## 5. Гигиена репозитория

| Правило | Где | Статус |
|---|---|---|
| Remote приватный — `github.com/Onemyname/renpy` | `git remote -v` | IMPLEMENTED |
| Производные зоны не в git: `game/generated/`, `game/assets/`, `game/tl/`, `game/cache/`, `game/saves/` | `.gitignore:2-6` | IMPLEMENTED |
| `game/build_id.json` не в git | `.gitignore:8` | IMPLEMENTED |
| `*.rpyc` не в git, кроме линии имён фикстур | `.gitignore:9`, негация `:14` | IMPLEMENTED |
| Локальные артефакты: `build/`, `.vncache/` | `.gitignore:20-21` | IMPLEMENTED |
| Локальный override хранилища `.vnstorage.local.yaml` | `.gitignore:22` | IMPLEMENTED |
| Шрифты и docs-картинки через LFS | `.gitattributes:3-7` | IMPLEMENTED |

**Почему `.vnstorage.local.yaml` локальный.** В git лежит `.vnstorage.yaml` — логическая карта: `default: {type: file, path: "~/vn-assets-store"}`. Манифесты сырцов ссылаются на **имя** хранилища, а физика (путь к NAS, endpoint S3, bucket) у каждого своя и меняется одним файлом. Мержится поверх в `storage.py:59`; `vn doctor` печатает WARN-напоминание, если override активен (`doctor.py:104-106`). Побочный и важный эффект: endpoint'ы и bucket'ы конкретной инфраструктуры не попадают в историю репозитория. Подробнее — [`31-storage-and-backup.md`](31-storage-and-backup.md).

## 6. Цепочка поставок: модели, пакеты, кастом-ноды

Это самый слабый по безопасности участок конвейера, и он весь про доверие внешним URL.

**Модели — PARTIALLY IMPLEMENTED.** [`tools/comfyui-models.yaml`](../../tools/comfyui-models.yaml) содержит 10 записей, и у **всех** `sha256: null`. Логика загрузки (`pipeline.py:406-427`):

1. скачать по URL из манифеста (`curl -L --fail --retry 3 -C -` в `.part`, затем `os.replace` — обрезанный файл никогда не выглядит готовым, `pipeline.py:337-359`);
2. посчитать `sha256` файла;
3. сравнить с манифестом — **но `if entry.get("sha256")` ложно для всех записей, поэтому сравнение не выполняется никогда**;
4. записать посчитанный хэш в `.vn-models.json`.

Дальше при каждом прогоне `model_status` сверяет только **размер** (±1 МБ, `pipeline.py:296-302`), а не хэш. Итог: это **trust-on-first-use**. Подменённый или изменённый апстримом файл будет зафиксирован как «эталон» без единого сигнала, а последующая подмена файла того же размера не поймается вообще. Закрывается это дёшево: проставить реальные `sha256` в манифест после проверенной загрузки. Приоритет — см. [`37-roadmap.md`](37-roadmap.md).

**Питон-зависимости — PARTIALLY IMPLEMENTED, но уже не декоративно.** `tools/vn.lock` (18 закреплённых пакетов) **теперь читается всеми пайплайнами**: `pip install --quiet -r tools/vn.lock` стоит **перед** editable-установкой во всех 8 местах установки тулчейна (`ci.yml:30`, `:46`, `nightly.yml:29`, `canary.yml:30`, `release.yml:42`, `.gitlab-ci.yml:23`, `:37` — последние две строки разворачиваются в три джобы через `extends`). Порядок — предмет теста `tools/vn/tests/test_ci_config.py::test_lock_installed_before_editable`: если editable окажется первым, pip отрезолвит `>=`-диапазоны и пины станут бесполезными.

**Что по G17 всё ещё не закрыто:** в локе пиннованы только прямые зависимости. Транзитивные (например `pygments`, приезжающий с `pytest`) не закреплены, то есть supply-chain-поверхность закрыта частично — компрометация транзитивного пакета в CI по-прежнему возможна. Полное закрытие — регенерация лока с транзитивными пинами (`pip-compile` / `uv pip compile`).

**Кастом-ноды ComfyUI — вне нашего тулинга.** ComfyUI-Manager устанавливает произвольный Python-код из GitHub; наш `vn pipeline doctor` только фиксирует факт установки. Ни песочницы, ни пиннинга нод у нас нет.

**Грабля.** `vn pipeline models --only <id>` **скачивает**, а не показывает статус: условие в `cli.py:1442-1443` — `if pull or only_set`. Можно случайно вытянуть `restricted`/`unknown`-модель (bigASP, Civitai-LoRA) в момент, когда решение по ADR-0008 ещё не принято.

---

# Часть 2. Лицензии и право

> **Это не юридическая консультация.** Ниже — механика проекта и ссылки на первоисточники. Тексты лицензий и EULA меняются: DAZ-EULA, например, не имеет ни номера версии, ни даты вступления в силу. **Перед любой коммерческой дистрибуцией проверяйте актуальный текст лицензии/EULA по официальной ссылке и консультируйтесь с юристом.** Ни одна строка этого файла не является разрешением что-либо использовать.

## 7. Механика проекта: реестр лицензий

**Статус: IMPLEMENTED, но ИНЕРТЕН** — код работает, гейт подключён, проверять пока нечего: деклараций рендеров в репозитории ноль.

Единственное место правового учёта покупных ассетов — [`content/licenses.yaml`](../../content/licenses.yaml), схема `license_registry@1`. Ключ записи — внутренний id по маске `^[a-z][a-z0-9_]*$`, на него ссылаются декларации рендеров полем `license: [...]`.

### Полная таблица полей записи

| Поле | Тип | Обяз. | Значение |
|---|---|---|---|
| `title` | string (min 1) | **да** | Человекочитаемое имя продукта |
| `vendor` | enum: `daz` `renderotica` `renderhub` `vam_hub` `gumroad` `fontsource` `audio_stock` `other` | **да** | Поставщик |
| `license_type` | enum: `daz_standard` `daz_interactive` `cc0` `cc_by` `ofl` `royalty_free` `custom` `unknown` | **да** | `daz_standard` — 2D-рендеры (пиксели); `daz_interactive` — поставка самого меша/real-time-ассета |
| `game_use` | bool | **да** | Разрешено использование результата в **коммерческой** игре |
| `nsfw_allowed` | bool | **да** | Разрешено **взрослое** использование именно этого ассета |
| `sku` | string \| null | нет | SKU/id продукта у вендора (у DAZ — числовой id страницы) |
| `url` | string \| null | нет | Ссылка на продукт |
| `purchased_at` | string \| null, `format: date` | нет | **В кавычках**: без них YAML отдаёт date-объект, и схема падает |
| `invoice` | string \| null | нет | Номер заказа — доказательство покупки |
| `notes` | string | нет | Свободный текст |

`additionalProperties: false` — лишнее поле = ошибка схемы.

### Что именно проверяет `vn assets licenses`

Реализация — `licenses.py:53-109`, CLI — `cli.py:767-786`.

1. Схема-валидация самого реестра; битый реестр → ошибки и немедленный выход (`licenses.py:62-67`).
2. Обход `assets_src/{daz,vam,sims4}/**/*.render.yaml`; берутся только документы, у которых `schema` равен `daz_render@1` / `vam_render@1` / `sims4_render@1` (`licenses.py:23-27`, `:72-82`).
3. Для каждого id в `license: [...]`:
   - id отсутствует в реестре → **ERROR** (`:90-93`);
   - `game_use: false` → **ERROR** (`:94-98`);
   - путь `output` содержит сегмент `/nsfw/` **и** `nsfw_allowed: false` → **ERROR** (`:99-103`; детектор — `"/nsfw/" in f"/{output}"`, `:48-50`).
4. Декларация вообще без поля `license:` → попадает в `unlicensed` и даёт **одно агрегированное WARNING** (`:83-85`, `:104-108`).

**Дыра, которую надо знать:** пункт 4 — предупреждение, а не ошибка. Декларация без лицензии релиз **не блокирует**. Дисциплина «сначала запись в реестр, потом первый рендер» держится на человеке, а не на гейте.

**Где подключено:** проверка №15 из 19 в релизном гейте (`release.py:436-445`). FAIL при нарушениях, WARN при незалицензированных декларациях, PASS с числом покрытых деклараций. Полная таблица гейта — [`29-build-and-release.md`](29-build-and-release.md).

**Текущее состояние.** В реестре 3 записи: `g9_starter_essentials` (DAZ, `daz_standard`), `font_literata` и `font_inter` (обе `ofl`). Деклараций 0, поэтому вывод сегодня — `деклараций рендеров нет; в реестре 3 записей (content/licenses.yaml)`. Записи про шрифты — чистая бухгалтерия: на них никто не ссылается, гейт их не читает.

### Как зарегистрировать новый ассет

```yaml
# content/licenses.yaml
assets:
  daz_school_uniform_g9:
    title: "School Uniform for Genesis 9"
    vendor: daz
    sku: "98765"
    url: https://www.daz3d.com/...
    license_type: daz_standard
    game_use: true
    nsfw_allowed: false        # если продукт отдельно запрещает adult-использование
    purchased_at: "2026-08-09" # кавычки обязательны
    invoice: "DAZ-1234567"
    notes: >
      Проверено на странице продукта: <что именно вы прочитали и когда>.
```

Затем сослаться из декларации рендера: `license: [daz_school_uniform_g9]` и прогнать `vn assets licenses`. Модели и кастом-ноды учитываются **не здесь**, а в `tools/comfyui-models.yaml` (§9). Шрифты, музыка и всё, что физически уезжает игроку, дополнительно попадают в `THIRD-PARTY-NOTICES.md` (§12).

## 8. Таблица источников контента

Ссылки — только те, что прошли верификацию в ресёрче проекта. Формулировки — фактические цитаты условий, а не выводы.

### 8.1. 3D-источники

| Источник | Официальные ссылки | Ключевой вопрос для коммерции | Статус в проекте |
|---|---|---|---|
| **DAZ-контент** | EULA https://www.daz3d.com/eula · типы лицензий https://www.daz3d.com/daz-licenses · https://www.daz3d.com/interactive-license-info | Три отдельных вопроса: **(а)** 2D-рендеры vs поставка меша — страница Interactive License называет ровно наш случай: «one exception being content created using a stack of renders, such as a sprite — in which case the standard agreement would suffice»; **(б)** §1.0 запрещает распространять продукт, из которого Content можно «separately exported, extracted or de-compiled»; **(в)** §1.0 запрещает использование Content «in connection with … any AI engine, program, or system … with capabilities or instructions to auto-generate materials» — это напрямую про наш DAZ → ComfyUI img2img/ControlNet | Основной трек ([`17-daz-studio.md`](17-daz-studio.md)). В реестре 1 запись, рендеров 0. **EULA без номера версии и даты** — перечитывать перед каждым релизом |
| **DAZ Editorial-продукты** | та же страница типов лицензий | «Content with specific, non-commercial editorial use restrictions». После установки они визуально неотличимы от остальных | Фиксировать **в момент покупки** — иначе не восстановить |
| **Virt-a-Mate** | EULA https://store.steampowered.com/eula/2149830_eula_0 · Hub Terms https://hub.virtamate.com/help/terms/ · `licenseType` в `meta.json` каждого ресурса | «Я купил VaM» и «я могу шипнуть рендер этого Hub-лука» — **независимые** вопросы. `licenseType` в `meta.json` может расходиться с README ресурса (проверенный пример: VAMOverlays — README «CC BY», `meta.json` «CC BY-SA») | Схема `vam_render@1` есть, деклараций 0, VaM не установлен (`vn pipeline doctor` → WARN). [`18-vam.md`](18-vam.md) |
| **The Sims 4** | EA User Agreement https://www.ea.com/legal/user-agreement (обновлён 14.05.2026) · Content Policy https://help.ea.com/en/articles/security-and-rules/ea-content-policy/ · Mods Policy https://help.ea.com/en/articles/the-sims/the-sims-4/mods-policy/ | §2 User Agreement даёт лицензию «for your non-commercial use». Content Policy дословно называет запрещённым «put your fansite, videos, or other content behind paywalls like Patreon» и требует дисклеймер «This [project/website] is not endorsed by or affiliated with EA or its licensors». Формальный путь — rights clearance form, при этом EA прямо пишет, что молчание не является одобрением | ADR-0007 принят **как задел**: «условия использования визуала EA … оформляются отдельным решением — амендментом к этому ADR». Sims 4 не установлен, деклараций 0. Ресёрч: previz-слой, не shipped-арт. [`19-sims4.md`](19-sims4.md) |

### 8.2. AI-модели (изображения, видео, LoRA, апскейл)

Ключевое различие, которое надо держать в голове: **Apache-2.0/MIT/BSD content-neutral — они не ограничивают тематику. OpenRAIL — нет: у него приложение с use-restrictions.**

| Модель / роль | Лицензия и ссылка | Что читать | В нашем манифесте |
|---|---|---|---|
| Wan 2.2 I2V A14B (high/low) — ядро видео | Apache-2.0, https://github.com/Wan-Video/Wan2.2/blob/main/LICENSE.txt | самая чистая позиция из всего стека | `required: true`, `commercial_use: allowed` |
| UMT5-XXL, Wan 2.1 VAE, LightX2V 4-step (high/low) | Apache-2.0 | — | `required: true`, `allowed` |
| Real-ESRGAN x4plus — апскейл | BSD-3-Clause, https://github.com/xinntao/Real-ESRGAN | — | `required: false`, `allowed` |
| **bigASP v2** — SDXL-фотореал | CreativeML OpenRAIL-M (SDXL-производная), https://huggingface.co/fancyfeast/big-asp-v2 | Приложение A OpenRAIL: перечень запрещённых применений. По разбору ADR-0008 — взрослый контент с совершеннолетними вымышленными персонажами в перечень не входит; запрещены эксплуатация несовершеннолетних и материалы, порочащие реальных лиц | `required: false`, **`commercial_use: restricted`** |
| **Wan 2.2 NSFW motion LoRA (high/low)** | per-model условия Civitai, https://civitai.com/models/1307155 | Единой лицензии нет: флаги («commercial use», «sell images», «no merges») задаёт автор и **может менять**. Реальная правовая экспозиция проекта — здесь, а не в базовых моделях | `required: false`, **`commercial_use: unknown`**, `auth: civitai_key` |
| **SUPIR** — апскейл | явно **некоммерческая**, https://github.com/kijai/ComfyUI-SUPIR/blob/main/LICENSE | «strictly for non-commercial purposes», коммерческое использование — только с письменного разрешения автора | **В проекте нет и не должно появиться** |
| LTX-2 / 2.3 — видео | LTX-2 Community License, https://github.com/Lightricks/LTX-2/blob/main/LICENSE | Порог выручки $10M, Attachment A (20 ограничений) и **требование явно раскрывать машинно-сгенерированный контент при распространении** — это обязательство на странице стора/в титрах | не используется |
| HunyuanVideo 1.5 | Tencent Hunyuan Community, https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/LICENSE | Territory **исключает EU / UK / Южную Корею** | не используется |
| Sonic (lip-sync) | CC BY-NC-SA 4.0, https://github.com/jixiaozhong/Sonic | некоммерческая | не используется |
| FLUX.2-dev / klein-9B | FLUX Non-Commercial License v2.0, https://bfl.ai/legal/non-commercial-license-terms | Модель некоммерческая; клауза про Outputs отдельная. Плюс Usage Policy https://bfl.ai/legal/usage-policy распространяется на **производные** FLUX-моделей | не используется |
| SD 3.5 | Stability AI Community License, https://stability.ai/license | Бесплатное коммерческое использование **до $1M годовой выручки** | не используется |
| Z-Image / Qwen-Image / Chroma1-HD / FLUX.2-klein-4B | Apache-2.0: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo · https://github.com/QwenLM/Qwen-Image · https://huggingface.co/lodestones/Chroma1-HD · https://huggingface.co/black-forest-labs/FLUX.2-klein-4B | Кандидаты, если понадобится permissive-стек для статики | не используется |

Подробности по применению — [`20-image-generation.md`](20-image-generation.md) и [`21-video-generation.md`](21-video-generation.md).

### 8.3. Шрифты, движок, аудио, голос

| Источник | Лицензия и ссылка | Ключевое обязательство | Статус |
|---|---|---|---|
| **Inter** (Regular, SemiBold) | OFL 1.1, https://github.com/rsms/inter | Не продавать сам шрифт отдельно; сохранять уведомление в дистрибутиве | IMPLEMENTED: файлы в `game/fonts/`, текст — `game/fonts/OFL-Inter.txt`, запись `font_inter` в реестре |
| **Literata** (Regular) | OFL 1.1, https://github.com/googlefonts/literata | то же | IMPLEMENTED: `game/fonts/OFL-Literata.txt`, запись `font_literata` |
| **Ren'Py** | MIT + LGPL-части, https://www.renpy.org/doc/html/license.html | Большая часть движка — MIT, но части производны от LGPL-кода (FFmpeg, Fribidi, chardet, libusb, Pygame_SDL2); документация требует распространять игру так, чтобы удовлетворять LGPL, прикладывать копию лицензии к каждой копии и ссылаться на неё из README/описания в сторе | IMPLEMENTED: `renpy/LICENSE.txt` едет в дистрибутиве (проверено по zip) |
| **ComfyUI** | GPL-3.0 | Ограничивает распространение самого ComfyUI, не ваши рендеры | Инструмент производства, не поставляется |
| **ffmpeg** | LGPL/GPL — зависит от сборки | Влияет, если бы вы вендорили бинарь; у нас ffmpeg только на машине художника | Инструмент производства |
| **MusicGen / AudioCraft** | код MIT, **веса CC-BY-NC**, https://github.com/facebookresearch/audiocraft | ⛔ Коммерчески неприменимо ни в каком виде, включая patron-финансирование | не используется |
| **Suno** | https://suno.com/terms (действует с 26.03.2026) | Платный тир — assignment прав на Output; free — non-commercial и права остаются у Suno. Prohibited-uses клауза достаёт до **продукта**, в котором используется Output («is used for or in connection with any purpose … pornographic»). Права привязаны к активной подписке **на момент генерации** — храните датированные чеки и лог генераций | не используется |
| **Udio** | ToS верифицировать не удалось | Не строить саундтрек на этом источнике в 2026 | не используется |
| **ACE-Step 1.5** | https://github.com/ace-step/ACE-Step-1.5 | Локальная модель → нет сервисной клаузы про порнографию; дисклеймер просит раскрывать участие ИИ | кандидат |
| **Sonniss GDC bundles** | https://sonniss.com/gdc-bundle-license/ | Коммерческое использование без атрибуции разрешено; нельзя продавать сами эффекты; **запрещено использовать их для обучения ИИ**; morality-клаузы нет | рекомендованный источник SFX |
| **Freesound** | https://freesound.org/help/faq/ | Лицензия **у каждого звука своя**: CC0 / CC-BY (атрибуция) / **CC-BY-NC (нельзя)**. Практическое правило — только CC0 | — |
| **A Sound Effect** | https://www.asoundeffect.com/ | Royalty-free, атрибуция не нужна; но операционные условия задаёт вендор конкретной библиотеки — сохраняйте файл лицензии в папку покупки | — |
| **Chatterbox** (TTS) | MIT, https://github.com/resemble-ai/chatterbox | Самая чистая лицензия в категории. Все выходы несут нейро-вотермарку Perth — это нормально, снимать её не нужно и не следует | кандидат под `vn voice tts` (сама команда — стаб фазы 2, `cli.py:1278-1281`; остальной контур `vn voice` работает — [23-audio.md](23-audio.md) §8) |
| **Kokoro-82M** (TTS) | Apache-2.0, https://huggingface.co/hexgrad/Kokoro-82M | Без клонирования, 54 фиксированных голоса | — |
| **XTTS-v2 / F5-TTS / Fish Speech / IndexTTS-2** | CPML (текст больше не отдаётся) / веса CC-BY-NC / research license / bilibili custom: https://huggingface.co/coqui/XTTS-v2 · https://github.com/SWivid/F5-TTS · https://github.com/fishaudio/fish-speech · https://github.com/index-tts/index-tts | ⛔ Коммерчески неприменимы или требуют отдельного договора | не используются |
| **ElevenLabs** | https://elevenlabs.io/terms-of-use · https://elevenlabs.io/use-policy | Условия по взрослому контенту **верифицировать не удалось** — читать самому в браузере и получать ответ от поддержки письменно | — |

**Красная линия, не зависящая ни от одной лицензии:** никогда не клонировать голос реального узнаваемого человека для взрослого контента (право на изображение/голос + законы 2024–2026 о voice-likeness), и никакая сексуализация несовершеннолетних — это жёсткий правовой предел, ограничивающий дизайн персонажей, а не только выбор TTS. Подробности по аудио — [`23-audio.md`](23-audio.md).

## 9. ADR-0008 — единственный непринятый ADR (открытый риск P0)

[ADR-0008](../adr/0008-ai-model-licensing-for-commercial-adult-content.md) имеет статус **«предложено (требуется решение владельца)»**. Все остальные ADR проекта приняты.

> **2026-08-08: владелец сознательно отложил решение** — развилку задали прямо, ответ был
> «оставить „предложено“». Отсюда два практических следствия, и оба надо помнить.
> Первое: авто-гейт «модель с `commercial_use != allowed` не участвует в релизном контенте»
> **не реализован и не будет** до выбора варианта — инструмент вас не остановит.
> Второе: до решения `restricted`/`unknown`-модели не должны попадать в релизный кадр,
> и следит за этим человек. Проверять глазами: `grep -n "commercial_use" tools/comfyui-models.yaml`.

**Что уже зафиксировано и работает (IMPLEMENTED):**

- в схему `comfyui_models@1` добавлены `commercial_use` (`allowed|restricted|unknown`) и `nsfw_terms_url`; `license` заполнен у всех 10 позиций манифеста;
- ядро видео-конвейера (Wan 2.2 I2V ×2, UMT5, VAE, LightX2V ×2 — Apache-2.0; Real-ESRGAN — BSD-3) помечено `commercial_use: allowed`. **Первая глава производится на чисто permissive-стеке**;
- модели с `restricted`/`unknown` (bigASP v2, Civitai NSFW-LoRA) стоят `required: false` — они не в критическом пути;
- дисциплина: новая модель заводится с заполненными `license`/`commercial_use`; `unknown` допустим только при `required: false`.

**Что не решено — развилка по bigASP v2 и Civitai NSFW-LoRA:**

| Вариант | Суть | Плюс | Минус |
|---|---|---|---|
| **A** (рекомендация ADR) | Использовать, зафиксировав условия: прочитать карточку каждой модели, сохранить снимок условий и дату, держать контент в рамках OpenRAIL | Полный доступ к качеству фотореала и NSFW-моушену | Автор Civitai может изменить условия; нужна перепроверка при обновлении модели |
| **B** | Только permissive-стек: отказ от bigASP/Civitai-LoRA, статика — чистый DAZ-рендер | Нулевой правовой хвост | Хуже фотореализм кожи, беднее NSFW-моушен |
| **C** (безопасный дефолт) | Гибрид: permissive для релизного контента, `restricted` — только внутренние превью | Компромисс | Дисциплина «что где» ложится на художника |

**Почему решение не зафиксировано:** ADR явно требует продюсерского выбора — это вопрос риск-аппетита, а не техники. Пока варианта нет, **невозможно построить авто-гейт** «модель с `commercial_use != allowed` не участвует в релизном контенте» — статус **NOT IMPLEMENTED**. Технически он был бы возможен: провенанс хранит имя модели в `chain[].model` — но и провенанс в этом репозитории ни разу не создавался (0 сайдкаров `*.provenance.json`), так что данных для гейта тоже пока нет.

**Это открытый правовой риск уровня P0** — единственный пункт хендбука, где нерешённый вопрос напрямую блокирует коммерческую дистрибуцию части контента. См. [`37-roadmap.md`](37-roadmap.md).

## 10. Взрослый контент, AI-дисклоузер и площадки

**Честно о границах проверенного.** Ресёрч проекта прямо фиксирует: «Licence permission ≠ distribution permission. Steam, Patreon, itch.io, and payment processors have their own adult-content and AI-disclosure rules that are stricter and change faster than any model licence» — и помечает это как **отдельную непроработанную тему**. Поэтому конкретные требования площадок (форма AI-дисклоузера в Steamworks, теги и правила оформления на f95zone, политики платёжных процессоров) в материалах проекта **НЕ верифицированы**. Не воспроизводите их по памяти — проверяйте на самих площадках непосредственно перед публикацией и сохраняйте датированный снимок правил.

Что **проверено** и относится к раскрытию AI-контента:

- **LTX-2 Community License** требует «expressly and intelligibly disclaim» машинно-сгенерированный контент при распространении. Если LTX когда-нибудь войдёт в конвейер, это обязательство на странице магазина и в титрах, а не сноска.
- **FLUX Non-Commercial License** содержит клаузу AI-дисклоузера «where law requires».
- **ACE-Step** в дисклеймере просит раскрывать участие ИИ и проверять оригинальность.
- **US Copyright Office** (пересказано в ADR-0008): авторское право на чисто AI-сгенерированное изображение в США не возникает. Практический вывод ADR: это ослабляет антипиратскую позицию, но не мешает продавать игру целиком.
- **OpenRAIL Appendix A** (для bigASP и любых SD/SDXL-производных): запрещены эксплуатация несовершеннолетних и материалы, порочащие реальных лиц.
- **EA Content Policy** прямо называет Patreon-пейволл примером запрещённого использования игрового контента The Sims 4 — если Sims-трек когда-нибудь включат, это блокер для монетизации, а не формальность.
- Ren'Py: секция **Age Verification** существует в changelog ветки `master` (8.6), которая **не выпущена**. У нас закреплён 8.5.3 (`project.yaml:5`) — движковой возрастной проверки нет, статус **NOT IMPLEMENTED**.

Внутренний контракт проекта на 18+ уже есть и он технический: NSFW-контент живёт в подпапке `nsfw/` своей категории (ADR-0006 §4, детектор `licenses.py:48-50`), плюс пак `nsfw` и флаг `flavors.<id>.nsfw`. Нарушение конвенции = 18+ в public-сборке; ADR-0006 это прямо оговаривает. См. §2 про то, почему сегодня это ещё не защита.

## 11. Steam: что придётся проверить дополнительно

`vn release steam` — **NOT IMPLEMENTED** (стаб фазы 3, `cli.py:1565`); депотов и каналов dev/beta/release нет. Никаких обещаний по срокам. Что известно фактически:

- **Steam-поддержка Ren'Py — не часть SDK.** Ставится через лаунчер: «preferences» → «Install libraries» → «Install Steam Support», и **гейтится приёмом в Steam partner program** (https://www.renpy.org/doc/html/achievement.html). Это не добавляется в последний момент. Ren'Py 8.5 требует Steamworks SDK 1.62.
- **`achievement.steam` равен `None`, если Steam не инициализировался** — вызов без guard уронит билд у любого, кто запустит игру вне Steam, включая ваши dev-прогоны. Наши достижения к платформе не привязаны: `080_achievements.rpy:17-18` объявляет хук `vn_ach.set_provider(fn)`, и **вызывающих у него нет** — Steam-синк **NOT IMPLEMENTED**.
- **Организационные сроки** (VNDev Wiki, https://vndev.wiki/Guide:Ren%27Py_visual_novels_on_Steam, обновление 25.11.2025): релиз невозможен раньше чем через 30 дней после покупки app credit или через две недели после аппрува страницы — что позже. Гайд отдельно разбирает случай внешне распространяемого nudity-патча.
- **Пакет для магазинов** — «Windows, Mac, and Linux for Markets» из `build.package()` (https://www.renpy.org/doc/html/build.html); наш `vn release build` собирает `--package win|linux|mac`.

Что придётся проверить **дополнительно** к нашему гейту, прежде чем жать «опубликовать»: правовой статус каждого стороннего ассета (§7), лицензии музыки и SFX с номерами заказов, OFL-уведомления для шрифтов, LGPL-обязательство Ren'Py (копия лицензии + ссылка из описания в сторе), раскрытие AI-контента по правилам самой площадки (§10) и решение по ADR-0008, если в релиз попадает что-то, сделанное на `restricted`/`unknown`-моделях.

## 12. `docs/licenses/THIRD-PARTY-NOTICES.md`

**Статус: IMPLEMENTED, но содержимое частично устарело.**

Файл — единственное, что едет игроку в качестве уведомлений о сторонних компонентах. Механика (`cli.py:1545-1548`): `vn release build` копирует его в `game/THIRD-PARTY-NOTICES.md` **на время** `distribute` и удаляет в `finally` (`cli.py:1559-1560`), чтобы dev-чекаут не носил копию. Разделение зон в самом файле правильное: `content/licenses.yaml` — учёт покупных ассетов (в git, с гейтом), а `THIRD-PARTY-NOTICES.md` — «только то, что уезжает игроку».

Что там сейчас: движок и рантайм (Ren'Py MIT + LGPL, Python PSF, SDL2/FFmpeg), раздел шрифтов, раздел аудио, таблица AI-моделей на 7 строк (покрывает все 10 позиций манифеста, парные high/low сгруппированы) и раздел инструментов производства.

**Две задачи, которые надо закрыть:**

1. **Раздел «Шрифты» устарел.** Там стоит заглушка «*(шрифты проекта пока не добавлены)*» (`THIRD-PARTY-NOTICES.md:25`), хотя `game/fonts/` уже содержит `Inter-Regular.ttf`, `Inter-SemiBold.ttf`, `Literata-Regular.ttf`. Сами тексты OFL едут с игрой (`game/fonts/OFL-*.txt` не исключены из дистрибутива), так что формальное «сохранять уведомление» соблюдается, но сводный файл врёт. Заполнить: шрифт → OFL 1.1 → где используется.
2. **Раздел «Аудио»** — заглушка «*(треков и SFX пока нет)*» (`:31`). Заполнять при добавлении первого трека: лицензия + номер заказа.

Ещё одна мелочь того же рода: `game/fonts/README.md` ссылается на «schema licenses@1», хотя реальная схема называется `license_registry@1`.

**Правило поддержки:** любая новая зависимость, шрифт, трек или модель, влияющая на поставляемый результат, добавляется в этот файл **в том же коммите**, что и сама зависимость. Иначе его придётся восстанавливать археологией по истории.

## 13. Чеклист «перед коммерческим релизом»

Пункты команд — реальные команды этого проекта; пункты «человек» требуют вашего решения и датированного снимка условий.

```bash
vn doctor                              # 1. окружение здорово
vn build --check                       # 2. генерат и ассеты свежи
vn assets licenses                     # 3. лицензии ассетов: 0 ошибок, 0 «без license»
vn release validate --flavor public    # 4. 19 проверок, exit 0
vn release validate --flavor patron    # 5. то же для платного флейвора
vn loc report                          # 6. покрытие переводов ≥ порога loc.yaml
python -m pytest tools/vn/tests -q     # 7. тесты тулинга зелёные
```

Дальше — руками:

8. **ADR-0008 переведён из «предложено» в «принято»**, вариант A/B/C выбран и записан. Если выбран A — снимки условий Civitai-моделей и bigASP сохранены с датой.
9. **`content/licenses.yaml` покрывает каждый купленный продукт**: SKU, тип лицензии, инвойс. DAZ Editorial-продукты помечены `game_use: false`.
10. **AI-клауза DAZ EULA прочитана в текущей редакции** (текст без версии и даты) и решён вопрос, что именно из DAZ-рендеров попадает в ComfyUI.
11. **`docs/licenses/THIRD-PARTY-NOTICES.md` актуален**: шрифты, аудио, модели, движок. Раздел «Шрифты» заполнен (§12).
12. **LGPL-обязательство Ren'Py выполнено**: копия лицензии в дистрибутиве (проверить в собранном zip) и ссылка из описания в магазине.
13. **Раскрытие AI-контента** оформлено по актуальным правилам конкретной площадки; правила сохранены снимком с датой (§10).
14. **Патрон-метка**: токен получателя сгенерирован случайным (`secrets.token_hex(16)`), сам токен сохранён у вас вне репозитория, а в `game/build_id.json` собранной сборки лежит только `patron_tag` — проверьте это на артефакте (§3).
15. **Модели**: `sha256` в `tools/comfyui-models.yaml` проставлены для всего, что участвовало в релизном контенте (§6).
16. **Состав дистрибутива проверен на реальном артефакте** — командой из раздела «Проверка», а не «по правилам в options.rpy».

## Как изменить / Как расширить

| Задача | Что делать |
|---|---|
| Завести новый покупной ассет | Запись в `content/licenses.yaml` **до первого рендера** → ссылка `license: [id]` в декларации → `vn assets licenses` |
| Добавить нового вендора | Расширить enum `vendor` в `tools/schemas/license_registry@1.schema.json` (это версионируемая схема — новое значение в существующей `@1` допустимо, удаление старого требует `@2`) |
| Добавить AI-модель | Запись в `tools/comfyui-models.yaml` с заполненными `license` и `commercial_use`; `unknown` — только при `required: false` (правило ADR-0008 §3). Проставить `sha256` после проверенной загрузки |
| Закрыть дыру «декларация без `license` не блокирует релиз» | `licenses.py:104-108`: перенести `unlicensed` из `warnings` в `errors`. Сначала убедиться, что все существующие декларации покрыты, иначе релиз встанет |
| Сделать авто-гейт по `commercial_use` | Требует решения по ADR-0008 **и** работающего провенанса (сегодня 0 сайдкаров). Источник данных — `chain[].model` |
| Персональный patron-токен на получателя | Отдельный прогон `vn release build --patron-token <случайный токен>` на каждого; автоматизации нет. Токен генерировать `secrets.token_hex(16)` и держать в своём реестре вне репозитория — в сборку уедет только `patron_tag` |
| Исключить новую зону из дистрибутива | `build.classify("<glob>", None)` в `game/options.rpy`; **обязательно** проверить результат по собранному zip |
| Добавить `.rpa`-архивы | Только через ADR: `ARCHITECTURE.md` §2.4 фиксирует россыпь как desktop-норму (Steam-дельта-патчи), тематические `.rpa` — опция mobile фазы 3. И помнить: это не защита («not very secure» по докам Ren'Py), а упаковка |

## Чего НЕ делать

- **Не считать `public`-сборку «безопасно SFW» по факту существования флейвора.** Отсечение работает только по каталогу `game/assets/<cat>/nsfw/**`, которого сейчас нет ни одного, а `VN_PACKS` перечисляет пак `nsfw` независимо от флейвора.
- **Не выдавать в `--patron-token` осмысленную строку** — ник, e-mail, `patron_<имя>`. Сам токен в дистрибутив больше не едет (ADR-0011), но метка `patron_tag` едет, а короткий низкоэнтропийный токен подбирается по ней словарём. Токен обязан быть случайным (`secrets.token_hex(16)`).
- **Не считать `patron_tag` защитой сборки.** Это трассировка утечки: поле лежит в `game/build_id.json` внутри архива и вырезается вручную за минуту.
- **Не рассчитывать, что `.rpy` кто-то не прочитает.** В сборке лежат 36 `.rpy` рядом с 36 `.rpyc`, и авторский текст сцен вкопирован в генерат целиком.
- **Не запускать `vn pipeline models --only <id>`, думая, что это «показать статус».** Флаг `--only` включает загрузку (`cli.py:1442-1443`) — можно случайно вытянуть `restricted`/`unknown`-модель.
- **Не заводить в конвейер SUPIR.** Его лицензия явно некоммерческая, а находится он в самом конце экспорта, где никто не смотрит.
- **Не шипить MusicGen/AudioCraft, F5-TTS, XTTS-v2, Fish Speech, Sonic** — веса некоммерческие или под research-лицензией.
- **Не кормить материалы Sonniss в обучение ИИ** — их лицензия это прямо запрещает, включая RVC-датасеты и аудио-LoRA.
- **Не доверять README ресурса вместо `meta.json`** у VaM-контента: они расходятся (проверенный случай — VAMOverlays).
- **Не восстанавливать лицензионный учёт задним числом.** Пробивать SKU по сотням деклараций дороже, чем заполнять реестр с первой покупки — это ровно тот аргумент, который вынесен в докстринг `licenses.py:9-11`.
- **Не редактировать `game/build_id.json` руками** — его пишет и удаляет `vn release build`; он в `.gitignore:8`.
- **Не считать этот файл юридическим заключением.** Перед коммерческой дистрибуцией — актуальные тексты по официальным ссылкам и юрист.

## Проверка

```bash
vn assets licenses                              # реестр vs декларации
vn release validate --flavor public             # проверка #15 — лицензии ассетов
python -m pytest tools/vn/tests/test_licenses.py -q

# Секретов в git нет:
git grep -nE "api[_-]?key *= *[\"']|secret *= *[\"']|token *= *[\"'][a-z0-9]{10,}" -- tools game content ci

# Состав собранного дистрибутива (главная проверка §2):
python -c "import zipfile,glob,collections; z=glob.glob('build/dist/*/*.zip')[0]; f=zipfile.ZipFile(z); n=f.namelist(); print(sorted(collections.Counter(x.split('/')[1] for x in n if '/' in x).items())); print('утечки:',[x for x in n if '/content/' in x or '/tools/' in x or '/assets_src/' in x or '/90_debug/' in x or '/loc/' in x][:5])"
```

Ожидаемое: зоны только `game`, `lib`, `renpy`, `vn.exe`, `vn.py`; список утечек пустой; `game/tl/` без `pseudo`; `game/generated/manifest.json` отсутствует.

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `content/licenses.yaml`, `tools/schemas/license_registry@1.schema.json`, `tools/vn/src/vn/assets/licenses.py`, `tools/vn/src/vn/release.py:192-255,436-445` (`nsfw_exclude_globs`, `patron_tag`, `compute_build_info`, гейт лицензий), `tools/schemas/build_info@2.schema.json`, `docs/adr/0011-patron-tag-instead-of-token.md`, `game/options.rpy`, `tools/comfyui-models.yaml`, `docs/adr/0008-ai-model-licensing-for-commercial-adult-content.md`, `docs/licenses/THIRD-PARTY-NOTICES.md` |
| **Не трогать** | `game/build_id.json` (пишет `vn release build`, `.gitignore:8`), `<ComfyUI>/models/.vn-models.json` (lock загрузчика, вне репозитория), `game/generated/**` и `game/assets/**` (генерат), `game/fonts/*.ttf` (LFS) |
| **Зависимости** | Правка `game/options.rpy` меняет состав **всех** дистрибутивов — проверять по собранному zip. Правка `license_registry@1.schema.json` ломает существующие записи реестра и валится в `licenses.py:62-67` до всех остальных проверок. Ужесточение `licenses.py:104-108` (warning → error) остановит релиз, если есть декларации без `license`. Правка `nsfw_exclude_globs` (`release.py:192-203`) меняет, что уедет в SFW-сборку |
| **Валидация** | `vn assets licenses` → `vn release validate --flavor public` → `python -m pytest tools/vn/tests/test_licenses.py -q` → проверка zip командой из раздела «Проверка» |
| **Частые ошибки** | 1) `purchased_at: 2026-08-08` без кавычек — YAML отдаёт date-объект и схема падает. 2) Добавление поля, которого нет в схеме: `additionalProperties: false`. 3) Вера в то, что `vn release validate` проверяет лицензии моделей — **нет**, он проверяет только реестр ассетов; лицензии моделей не гейтятся вообще (ADR-0008 не принят). 4) Вера в то, что декларация без `license` завалит релиз — это WARNING. 5) Правка `THIRD-PARTY-NOTICES.md` в `game/` — файл там временный, источник в `docs/licenses/`. 6) Писать, что patron-токен уезжает игроку: с ADR-0011 в `build_id.json` лежит `patron_tag` (схема `build_info@2`); токен открытым текстом остался только в архивных артефактах до 0.1.5. 7) Писать, что `tools/vn.lock` никто не читает — читают все 8 мест установки; незакрытым остался лишь пиннинг транзитивных зависимостей |
