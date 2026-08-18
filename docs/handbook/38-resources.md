# 38. Инструменты и ресурсы

> **Статус подсистемы:** справочник, а не подсистема. Версии инструментов проверены запуском на машине владельца 2026-08-08. **Но** половина «инструментов конвейера» подключена к репозиторию только на уровне детекции: ComfyUI, DAZ Studio, Virt-a-Mate и Sims 4 у нас умеет находить `vn pipeline doctor` — и больше ничего (ни API-клиента, ни headless-рендера, ни воркфлоу в git).
> **Отвечает на вопрос:** «Какой инструмент за что отвечает именно в этом репозитории, какая версия у меня стоит, что из его возможностей реально подключено — и куда идти читать, чтобы не утонуть в SEO-мусоре».

Файл состоит из четырёх частей: (1) инструменты, которые стоят на машине и участвуют в сборке; (2) инструменты, которые имеет смысл рассмотреть, но стек мы не меняем; (3) учебные материалы по темам; (4) карта внутренних документов репозитория. Установка с нуля — [Getting started](03-getting-started.md); что где лежит — [Архитектура](02-architecture.md).

## Правила этого файла (важно для того, кто будет его дополнять)

1. **URL только из верифицированного ресёрч-пакета.** Каждая ссылка ниже прошла отдельную проверку на живость и на то, что по ней лежит заявленное. Если инструмент используется, а проверенной ссылки на его документацию нет — так и написано: «проверенной ссылки нет». Не добавляйте URL «по памяти»: сломанная ссылка в хендбуке хуже её отсутствия.
2. **Про лицензии — никаких юридических выводов.** Формулировка везде одна: *проверьте актуальный EULA/лицензию по официальной ссылке перед коммерческой дистрибуцией*. Файл даёт адреса документов и называет пункты, на которые стоит смотреть, — и всё.
3. **Разделяем «умеет инструмент» и «подключено у нас».** У каждого инструмента есть строка «Где используется» — это про наш репозиторий, а не про мир вообще.
4. **Лучше три полезных ресурса, чем двадцать случайных.** Ссылка без строки «зачем она стоит времени» подлежит удалению.

---

## Быстрый ответ

```bash
# Что у меня вообще стоит и всё ли на месте
vn doctor                 # 8 строк: Python, git, git-lfs, корень репо, project.yaml, схемы, шрифты LFS, SDK
                          # (+ WARN про .vnstorage.local.yaml, если он есть)
vn pipeline doctor        # ffmpeg/ffprobe, GPU+драйвер, ComfyUI+venv+PyTorch+Manager, модели, DAZ, VaM, Sims4, диски, SDK

# Версии по отдельности
vn --version              # vn, version 0.1.0            (версия игры — project.yaml: 0.1.4)
python --version          # 3.12.10
git --version; git lfs version
ffmpeg -version | head -1
echo $RENPY_SDK           # bash-сессии агента НЕ наследуют переменную — экспортить руками
```

| Мне нужно… | Инструмент | Команда/файл в этом репозитории |
|---|---|---|
| собрать игру | `vn` (наш CLI) | `vn build` |
| скомпилировать `.rpy` в контенте | Ren'Py SDK через build-bridge | `vn content compile` → `renpy.exe . vn_analyze` |
| перегнать сырец в game-ready | Pillow / ffmpeg | `vn assets build` |
| закодировать видео-луп | ffmpeg (libvpx-vp9) | `vn assets video build` |
| проверить окружение рендера | — | `vn pipeline doctor` |
| скачать модели ComfyUI | `curl`/urllib по манифесту | `vn pipeline models --pull` |
| собрать дистрибутив | Ren'Py SDK `launcher distribute` | `vn package` / `vn release build` |
| прогнать тесты | pytest | `python -m pytest tools/vn/tests -q` |

---

# Часть 1. Инструменты проекта

Всё, что перечислено здесь, **реально установлено и участвует в работе**. Порядок — от того, без чего репозиторий вообще не живёт, к тому, что нужно только контент-продакшену.

## 1.1. Ren'Py SDK

**Назначение в проекте:** движок игры **и** внешний инструмент сборки. Две роли, которые легко спутать: (а) `game/` исполняется движком в рантайме; (б) `renpy.exe` вызывается нашим CLI как подпроцесс — для разбора авторских `.rpy` (норма G24: никаких регексов по скрипту) и для `launcher distribute`.

**Версия (проверено):** **8.5.3.26051504** (`vn doctor` читает её из `<SDK>/renpy/vc_version.py`, `../../tools/vn/src/vn/doctor.py:33-41`). Пин — `project.yaml:5` (`renpy_sdk: "8.5.3"`); несовпадение фактической версии с пином = **FAIL** в `vn doctor` (`doctor.py:133-135`). Апгрейд SDK — отдельный PR с прогоном canary (норма G18).

**Установка:** скачать zip с https://www.renpy.org/latest.html, распаковать, переменную окружения указать на корень. У нас: `C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk`. Установщика/PATH нет — путь задаёте вы. *(Совет сообщества, не из официальных доков: распаковывать в путь без пробелов и не-ASCII.)*

**Конфигурация:** **единственный способ найти SDK — переменная `RENPY_SDK`**, и она обязана содержать `renpy.py` (`doctor.py:24-30`). Никакого автопоиска по реестру и по PATH нет; все потребители SDK (`tools/vn/src/vn/content/analyze.py:23-31`, `cli.py:195,264,337,1313`) ходят через эту функцию.
**Грабля:** `setx RENPY_SDK ...` виден только НОВЫМ процессам; в bash-сессиях AI-агента переменная часто не наследуется — экспортируйте руками перед запуском.

**Где используется:**
- `tools/vn/src/vn/content/analyze.py:37-70` → `renpy.exe <root> vn_analyze` — собственная команда, зарегистрированная нашим мостом `game/framework/00_core/050_build_bridge.rpy:98-144`. Это единственный парсер `.rpy` в проекте (G24).
- `cli.py:264` — `vn play`; `cli.py:337` — `vn package` (`launcher distribute`); `cli.py:1313` — `vn test smoke` (in-process автопилот).
- CI: `.github/workflows/ci.yml:57-64` качает SDK по пину, `:72-73` гоняет движковый `lint`.

**Когда использовать / когда НЕ использовать:** используйте CLI SDK как бэкенд сборки; **не** дёргайте GUI-лаунчер из автоматизации. Не поднимайте минорную версию посреди продакшена без прогона `vn test smoke` и pytest: 8.4 перешёл на Python 3.12, 8.5 выпилил внешний `pygame_SDL2` — большая часть сниппетов с форумов старше 2024 требует аудита.

**Официальная документация:** https://www.renpy.org/doc/html/
**Лучшие материалы:**
- https://www.renpy.org/doc/html/cli.html — полный список подкоманд и глобальных опций; там же `renpy.arguments.register_command(...)` — механизм, на котором стоит наш `vn_analyze`.
- https://www.renpy.org/doc/html/changelog.html — обязательная сверка перед тем, как поверить онлайн-докам (см. грабли ниже).
- https://www.renpy.org/doc/html/license.html — MIT + части под LGPL (FFmpeg, Fribidi, chardet, libusb, Pygame_SDL2); доки требуют распространять игру так, чтобы LGPL был соблюдён. **Проверьте актуальный текст по этой ссылке перед коммерческой дистрибуцией.**
- https://patreon.renpy.org/framerate-stability.html — «Avoiding Framerate Glitches Caused By Image Prediction», лучший текст про предсказание/кэш образов, который вообще существует; читается публично.

**Грабли, специфичные для версии:**
- **Онлайн-доки опережают загрузку.** Страницы на renpy.org рендерятся как «8.5.4 Documentation», а скачать можно только 8.5.3. Всё, что вы прочли, может отсутствовать в вашем SDK — сверяйтесь с `changelog.html`.
- `atl.html` жив (HTTP 200), но это **пустой редирект-заглушка**; канон — https://www.renpy.org/doc/html/transforms.html#atl. Линк-чекер этого не поймает.
- Тег релиза в GitHub — `8.5.3.26051504`, простого тега `8.5.3` в репозитории движка нет: CI-джоба, пиннующая строку `8.5.3` в git-тег, упадёт. Наш CI качает zip с renpy.org по номеру — это правильный путь.

## 1.2. `vn` — единственный CLI проекта

**Назначение в проекте:** норма G1 — «один инструмент». Сборка, валидация, контент-компилятор, локализация, ассеты, релизы, QA. Всё, что делает CI, — это те же команды `vn`.

**Версия (проверено):** `vn, version 0.1.0` (`tools/vn/src/vn/__init__.py:3`), имя дистрибутива `vn-tools` (`tools/vn/pyproject.toml:6-7`). **Версия тулинга и версия игры — независимые числа**: игра сейчас 0.1.4 (`project.yaml:2`), минимальная требуемая версия тулинга — `min_tools: "0.1"`.

**Установка:** `pip install -e tools/vn[dev]` из корня репозитория. Точка входа — `vn = "vn.cli:main"` (`pyproject.toml:24`), требуется Python ≥ 3.10.

**Конфигурация:** конфигов нет — поведение задают `project.yaml`, `.vnstorage.yaml` и содержимое `content/`. Корень репозитория определяется как первый предок, где лежат **одновременно** `project.yaml` и `tools/schemas/` (`repo.py:15-23`) — `.git` не участвует, поэтому CLI работает и в worktree, и в распакованном архиве.

**Где используется:** везде. 20 команд/групп верхнего уровня: `assets bootstrap build chapter char content dev doctor loc migrate pack package pipeline play release save scene shell test voice`. Контракт кодов возврата (`cli.py:22-38`): `0` — ок; `1` — ошибка валидации/сборки (всегда с сообщением); `2` — ошибка использования (click); `3` — «не реализовано в этой фазе» (честная заглушка `_stub`).

**Когда использовать / когда НЕ использовать:** любой шаг сборки — через `vn`. **Не** пишите ad-hoc скрипты рядом: логика, не попавшая в CLI, не попадёт и в CI. Не полагайтесь на команды из ARCHITECTURE.md, которых нет в `vn --help` (`vn validate`, `vn build --use-artifact`, `vn content lint --strict` — NOT IMPLEMENTED, см. [Архитектура §7](02-architecture.md)).

**Официальная документация:** сам код — `../../tools/vn/src/vn/cli.py` (1643 строки) плюс [Свой движок](25-custom-engine.md).
**Лучшие материалы:** `docs/onboarding/tools-engineer.md` (карта модулей), `../runbooks/pipeline-broken-at-night.md` (что делать, когда `vn build` красный у всех).

## 1.3. Python

**Назначение в проекте:** язык всего тулинга. К движку отношения не имеет: Ren'Py 8.5 несёт собственный интерпретатор внутри SDK.

**Версия (проверено):** **3.12.10** (системная). `pyproject.toml` требует `>=3.10`; `vn doctor` проверяет именно `>= 3.10` (`doctor.py:72-73`). CI-образ — `python:3.12-slim` (`.gitlab-ci.yml:7`).

**Установка:** отдельно от SDK. Проверка — `python --version` и `vn doctor`.

**Конфигурация:** пиннованный тулчейн — `../../tools/vn.lock` (18 пакетов, точные версии). **IMPLEMENTED с 2026-08-08:** лок читается — `pip install --quiet -r tools/vn.lock` стоит перед editable-установкой во всех в 8 джобах установки тулчейна (7 строк в конфигах: GitLab-шаблон `.with-sdk` разворачивается в `build` и `test`) — `ci.yml:30,46`, `nightly.yml:29`, `canary.yml:30`, `release.yml:42`, `.gitlab-ci.yml:23,37`. Порядок «лок раньше editable» не косметика — editable следом уже ничего не поднимает, потому что его `>=`-диапазоны удовлетворены; именно порядок стережёт `tools/vn/tests/test_ci_config.py`. Норма G17 («пиннованный тулчейн, откат = `git revert` этого файла») выполнена для 18 прямых пакетов, и шаг из `../runbooks/pipeline-broken-at-night.md` стал исполнимым. **Остаток:** транзитивные зависимости в локе не закреплены (`pygments`) — одинаковый лок не означает побайтово одинаковое дерево пакетов.

**Где используется:** `pip install -e tools/vn[dev]`, `python -m pytest tools/vn/tests -q`.

**Когда использовать / когда НЕ использовать:** для тулинга — да. Внутри `game/` Python-код пишется как Ren'Py-скрипт и исполняется интерпретатором SDK; версии там свои.

**Официальная документация:** проверенной ссылки в ресёрч-пакете нет — намеренно не подставляю непроверенный URL.

### Зависимости `vn` (что каждая делает у нас)

Источник истины — `../../tools/vn/pyproject.toml:10-18` и `../../tools/vn.lock`. Версии — фактические, из `pip show` на машине владельца.

| Пакет | В lock | Стоит | Зачем именно у нас | Статус |
|---|---|---|---|---|
| `click` | 8.4.2 | 8.4.2 | вся структура CLI: группы, коды возврата, `--help` | IMPLEMENTED |
| `PyYAML` | 6.0.3 | 6.0.3 | чтение `project.yaml`, `*.scene.yaml`, `panels.yaml`, манифеста моделей | IMPLEMENTED |
| `jsonschema` | 4.26.0 | 4.26.0 | реестр из 39 схем `tools/schemas/*.schema.json`, Draft 2020-12 (`schemas.py:13-51`) | IMPLEMENTED |
| `blake3` | 1.0.9 | 1.0.9 | ключ кэша трансформаций `blake3(src:transform:version:profile)` (`tools/vn/src/vn/assets/pipeline.py`) | IMPLEMENTED |
| `Pillow` | 12.3.0 | 12.3.0 | PNG→WebP, миниатюры, генерация UI-панелей (`tools/vn/src/vn/assets/ui.py`) | IMPLEMENTED |
| `psd-tools` | 1.18.0 | 1.18.0 | нарезка PSD в `assets_src/png/**` (`tools/vn/src/vn/assets/psd.py`) | **IMPLEMENTED / UNEXERCISED** — в репозитории ноль `.psd`, ноль тестов, `.vncache/psd_png/` не создавался |
| `polib` | 1.2.0 | 1.2.0 | PO round-trip локализации (`tools/vn/src/vn/loc/po.py`) | IMPLEMENTED |
| `pytest` | 9.1.1 | 9.1.1 | 253 теста в 24 файлах `tools/vn/tests/` | IMPLEMENTED |

Полезно знать про **Pillow**: WebP-`quality` по умолчанию **80** (у `cwebp` и ImageMagick — 75), `alpha_quality` — 100, `method` 0–6 (по умолчанию 4); `Image.open()` **ленив** — для QA нужен `.load()`/`.verify()`, иначе обрезанный файл пройдёт молча; Pillow **не** делает цветоуправление при открытии — `info['icc_profile']` это просто bytes.
Документация: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html — таблица параметров сохранения по форматам (единственная страница, которая нужна для нашего конвейера). Релизы смотреть на https://github.com/python-pillow/Pillow/releases: внутренний `CHANGES.rst` остановлен на 11.0.0 и отсылает туда же.
Про **psd-tools**: ставить с экстрой — `pip install "psd-tools[composite]"`, иначе слои с эффектами композитятся неверно. Документация: https://psd-tools.readthedocs.io/. Гарантий побайтового совпадения с Photoshop нет — один раз на персонажа сверьте экспорт глазами.

## 1.4. git и git-lfs

**Назначение в проекте:** git — история и ветки; git-lfs — **только** те немногие бинари, которые вообще коммитятся.

**Версия (проверено):** git **2.55.0.windows.3**, git-lfs **3.7.1**. Оба проверяются в `vn doctor` (`doctor.py:75-77`), git-lfs — жёсткая проверка (FAIL при отсутствии).

**Установка:** git-lfs `vn doctor` предлагает ставить по адресу, который печатает сам: `https://git-lfs.com` (`doctor.py:77`). *Эта ссылка взята из кода репозитория, а не из верифицированного ресёрч-пакета.*

**Конфигурация:** `.gitattributes` — под LFS уходят `*.ttf`, `*.otf`, `*.woff2`, `docs/**/*.png`, `docs/**/*.jpg`. Плюс нормализация переводов строк: `* text=auto eol=lf`, `*.cmd text eol=crlf`. **Game-ready ассеты не коммитятся вообще** — их собирает `vn assets build`; сырцы по замыслу живут в S3-хранилище через манифесты (ADR-0004).

**Где используется:**
- `doctor.py:45-66` — **детекция LFS-указателей по содержимому файла**: если чекаут сделан без git-lfs, вместо шрифта приезжает текстовый указатель, и игра падает в рантайме с невнятной ошибкой шрифта. Проверка сравнивает магические байты (`\x00\x01\x00\x00`, `true`, `ttcf`, `OTTO`) и сигнатуру `version https://git-lfs.github.com/spec/v1`. Тот же код используется релизным гейтом (`release.py:~293`).
- `tools/vn/src/vn/assets/storage.py` — владелец лока берётся из `git config user.name`.
- `tools/vn/src/vn/content/compile.py:82-87` — короткий sha HEAD зашивается в `config.version` (`game/generated/version.gen.rpy`: `"0.1.4+dd1cb3e"`).

**Когда использовать / когда НЕ использовать:** **не** добавляйте новые маски в `.gitattributes` без ADR — репозиторий сознательно держит бинарную массу около нуля; лимит ADR-0004 проверяется линтом (warn > 30 МБ, error > 50 МБ нетекстовых байт под `assets_src/`, `tools/vn/src/vn/content/lint.py:47,371-399`).

**Официальная документация:** проверенной ссылки в ресёрч-пакете нет (см. правило 1 файла). Практика ветвления/коммитов проекта — [Цикл разработки](04-development-workflow.md).

## 1.5. ffmpeg

**Назначение в проекте:** единственный кодировщик видео. Превращает сырцы из `assets_src/video_src/` в WebM/VP9, который умеет играть Ren'Py; `ffprobe` даёт длительность и параметры для сайдкаров `mov_meta@1`.

**Версия (проверено):** **8.1.2-full_build-www.gyan.dev** (ветка «Hoare»). Актуальный релиз на 2026-08 — 9.0 «Lei» (2026-08-04); мы сознательно на maintenance-ветке. **Берите full-сборку:** essentials **не содержит `libsvtav1`**, поэтому AV1-рецепты на ней просто не запустятся (`libaom`, `libvpx`, `libopus`, `libzimg` в essentials есть).

**Установка:** `winget install Gyan.FFmpeg` (full) — именно это печатает наш doctor (`pipeline.py:473`). Альтернатива — статический zip с https://www.gyan.dev/ffmpeg/builds/ или https://github.com/BtbN/FFmpeg-Builds/releases, распаковать и добавить `bin\` в PATH.

**Конфигурация:** поиск — PATH, переопределение — переменные **`VN_FFMPEG` / `VN_FFPROBE`** (`pipeline.py:42-59`). `vn pipeline doctor` обязан показывать, **чем именно** кодируем, — это осознанное требование, а не диагностика ради диагностики.

**Где используется:** `../../tools/vn/src/vn/assets/video.py`. Наш реальный пресет — **одинпроходный VP9, `yuv420p`, звук отрезается**, если не указан `keep_audio`:
`-c:v libvpx-vp9 -b:v 0 -crf N -row-mt 1 -cpu-used N -pix_fmt yuv420p -an` (`video.py:101-120`). Профили: `full` → `crf 30 / cpu-used 2 / ≤1080p`, `draft` → `crf 42 / cpu-used 8 / ≤720p` (`video.py:86-95`). Рядом пишется сайдкар `*.webm.meta.json` (`mov_meta@1`, с `loop_seam`).

**Что ffmpeg умеет и что у нас НЕ подключено:** двухпроходный VP9, AV1 (`libsvtav1`), `alphaextract`+`hstack` для `side_mask`-альфы, loudnorm, профили `hd`/`mobile` — **NOT IMPLEMENTED**. Схема `video_src@1` **не применяется на пути сборки**: `load_opts(sidecar, registry=None)` — единственная форма вызова (`video.py:64` против `tools/vn/src/vn/assets/pipeline.py:197`), сайдкары валидирует только линт.

**Когда использовать / когда НЕ использовать:** только на шаге упаковки. Мастером держите PNG/EXR-последовательность или исходный mp4 — не гоняйте ffmpeg между стадиями ComfyUI. Не кодируйте H.264/MP4 для поставки: Ren'Py его не декодирует нативно и сам рекомендует AV1/VP9/VP8/Theora + Opus/Vorbis в WebM/Matroska/Ogg.

**Официальная документация:** https://ffmpeg.org/download.html (релизы и сборки под Windows)
**Лучшие материалы:**
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/doc/encoders.texi — настоящая семантика опций `libvpx-vp9`; закрывает споры про `deadline`, `cpu-used` (для VP9 диапазон **−8…8**, по умолчанию 1), `row-mt`, `tile-columns` (значение — **log2**!), `crf` (**0…63**). Страница `ffmpeg-codecs.html` слишком велика и обрезается фетчерами.
- https://developers.google.com/media/vp9/settings/vod — единственная конкретная таблица «разрешение → битрейт/CRF/tile-columns», плюс пропорции 50 %/145 % для constrained-quality.
- https://wiki.webmproject.org/ffmpeg/vp9-encoding-guide — гайд самого WebM-проекта: двухпроходный VOD (speed 4 → speed 1), `-b:v 0 -crf 33`, правило `auto-alt-ref` + `lag-in-frames ≥ 12`.
- https://github.com/slhck/ffmpeg-encoding-course — курс Вернера Робицы на 1,5 часа (MIT): базовая модель мышления про кодирование и `ffprobe`. Не про Ren'Py, но лечит «копипащу команды из блогов».
- https://ffmpeg.org/legal.html — LGPL 2.1+ база, GPL при `--enable-gpl`; про патенты FFmpeg честно пишет, что не даёт советов. **Проверьте актуальный текст перед коммерческой дистрибуцией.** Использование `ffmpeg.exe` как build-time инструмента и поставка бинарей — разные вопросы.
- ⚠️ https://trac.ffmpeg.org/wiki/Encode/VP9 — каноничная вики-страница VP9, но она за bot-challenge: отдаёт HTTP 200 с телом-заглушкой. В браузере открывается нормально; для автоматической проверки берите две ссылки выше.

**Грабли:** `-pix_fmt yuv420p` указывайте **явно** — PNG-последовательность утащит кодек в `yuv444p`, который «работает», но по докам Ren'Py не имеет аппаратного ускорения; `yuva420p` (альфа в VP9) Ren'Py молча игнорирует — нужен `side_mask`; на Windows первый проход пишется в `NUL`, а лог — `ffmpeg2pass-0.log` в текущем каталоге (параллельные энкоды перетрут друг друга без `-passlogfile`).

## 1.6. ComfyUI (+ PyTorch, ComfyUI-Manager)

**Назначение в проекте:** хост AI-генерации. По ADR-0006 — второе звено конвейера DAZ → **ComfyUI/Wan** → ffmpeg → Ren'Py.

**Версия (проверено):** установлен в **`D:\ComfyUI`**, venv с **PyTorch 2.11.0+cu128**, `custom_nodes/ComfyUI-Manager` на месте — всё это подтверждает `vn pipeline doctor`. Номер версии самого ComfyUI наш doctor не читает: он проверяет наличие каталога, venv, импорт `torch` и наличие Manager (`pipeline.py:484-505`). Актуальный релиз ComfyUI на дату ресёрча — **v0.31.0 (2026-08-07)**.

**Установка:** `powershell -ExecutionPolicy Bypass -File tools/setup-comfyui.ps1` — идемпотентный bootstrap: git + Python ≥ 3.10 + место → клон ComfyUI → venv → **PyTorch с CUDA 12.8** (по комментарию скрипта, единственная ветка с поддержкой Blackwell/RTX 50xx; более старые wheel'ы не знают sm_120 и молча падают на CPU) → зависимости + ComfyUI-Manager → структура `models/` → запись переменной `VN_COMFYUI`. Модели скрипт **не** качает.

**Конфигурация:** переменная **`VN_COMFYUI`**; при её отсутствии перебираются `D:/ComfyUI`, `C:/ComfyUI`, `~/ComfyUI` (`pipeline.py:31-33,64`). Модели описаны манифестом **`tools/comfyui-models.yaml`** (`comfyui_models@1`), лок-файл фактических размеров/хешей — `<ComfyUI>/models/.vn-models.json`, **не в git**.

**Где используется:**
```bash
vn pipeline doctor                 # детекция + проверка обязательных моделей
vn pipeline models                 # статус по манифесту
vn pipeline models --pull          # скачать (только auth: none)
vn pipeline models --only <id>     # ⚠ тоже СКАЧИВАЕТ, а не «показывает» (cli.py:1442-1443)
```
Манифест сегодня — 10 записей, 6 из них `required: true`:

| id | Роль | Лицензия в манифесте | auth |
|---|---|---|---|
| `wan22_i2v_high_fp8` / `wan22_i2v_low_fp8` | Wan 2.2 I2V, два эксперта MoE | Apache-2.0 | none |
| `umt5_xxl_fp8` | текст-энкодер UMT5-XXL | Apache-2.0 | none |
| `wan21_vae` | VAE Wan 2.1 (14B-модели Wan 2.2 используют его же) | Apache-2.0 | none |
| `wan22_lightx2v_high` / `_low` | LightX2V 4-step LoRA | Apache-2.0 | none |
| `realesrgan_x4plus` | 4× апскейлер (опционально) | BSD-3-Clause | none |
| `sdxl_photoreal` | bigASP v2, NSFW-фотореал SDXL для img2img-полировки | CreativeML-OpenRAIL-M | none |
| `wan22_nsfw_general_high` / `_low` | NSFW-motion LoRA 18+ | Civitai per-model terms | **civitai_key** |

**Честно про статус:** `sha256` у **всех** записей — `null`. Целостность проверяется только по `size_mb` с порогом 50 %, реальный хеш фиксируется в лок-файл после первой успешной загрузки. `auth: civitai_key` берёт токен из переменной **`CIVITAI_API_KEY`** (`pipeline.py:315`) — и здесь живёт классическая грабля: `setx` виден только новым процессам.

**Что ComfyUI умеет и что у нас НЕ подключено:** ComfyUI — это HTTP-сервер, исполняющий граф из JSON (`POST /prompt`, `GET /history/{id}`, `GET /view`, `POST /upload/image`, `GET /object_info`, `ws /ws`). **В нашем репозитории нет ни API-клиента, ни единого workflow-JSON.** Генерация сегодня — ручная работа в GUI, а конвейер подхватывает уже готовые файлы. Статус: **NOT IMPLEMENTED** (вызов ComfyUI из `vn`), при том что детекция и провижининг моделей — IMPLEMENTED.

**Когда использовать / когда НЕ использовать:** используйте для видео-лупов (Wan 2.2 I2V) и полировки DAZ-рендеров. Не привязывайте продакшен к экспериментальной установке: держите два инстанса (боевой замороженный + лабораторный) — см. часть 2.

**Официальная документация:** https://docs.comfy.org (+ https://docs.comfy.org/changelog)
**Лучшие материалы:**
- https://docs.comfy.org/development/comfyui-server/comms_routes — весь API одной страницей; это ровно то, что понадобится, когда мы решим автоматизировать генерацию.
- https://docs.comfy.org/development/api-development/workflow-api-format — разница между «сохранённым» и «API»-JSON. На этом спотыкаются все один раз: `/prompt` принимает **только** API-формат (File → Export Workflow (API)).
- https://blog.comfy.org/p/new-comfyui-optimizations-for-nvidia (2026-01-09) — оптимизации под RTX 50xx и главная ловушка: **NVFP4-ускорение работает только на PyTorch, собранном с CUDA 13.0 (cu130); иначе сэмплинг может быть до 2× медленнее fp8.** Мы на cu128 — значит, NVFP4-весов брать не надо.
- https://docs.comfy.org/tutorials/video/wan/wan2_2 — актуальный официальный воркфлоу Wan 2.2, включая first-and-last-frame (тот же чекпойнт I2V, отдельной модели FLF2V у Wan 2.2 нет).
- https://github.com/Comfy-Org/ComfyUI-Manager — снапшоты установки (Snapshot-Manager) — единственный документированный способ заморозить окружение. **Уровни безопасности имеют значение:** кастом-ноды — это произвольный Python; для коммерческого проекта имеет смысл `strong`.

**Грабли:** `--listen 0.0.0.0` открывает **неаутентифицированный** эндпойнт, который умеет писать файлы и выполнять Python кастом-нод; биндите `127.0.0.1`.

## 1.7. DAZ Studio 6 + DIM

**Назначение в проекте:** источник статики (реализм). ADR-0006 фиксирует арт-направление: DAZ (стиллы) + AI-анимация.

**Версия (проверено):** DAZ Studio 6 по пути `D:\DAZ3D\Library\Applications\64-bit\DAZ 3D\DAZStudio6\DAZStudio.exe`, библиотека контента — `D:\DAZ3D\Library\Applications\Data\DAZ 3D\My DAZ 3D Library` (обе строки печатает `vn pipeline doctor`). Актуальный GA-билд по ресёрчу — **6.25.2026.14722 (4 июня 2026)**; ветка 4.24 ставится параллельно и не заменяется.

**Установка:** `powershell -ExecutionPolicy Bypass -File tools/install-daz.ps1` — доводит машину до последнего ручного шага: детектирует установленные DAZ/DIM (реестр + стандартные пути), готовит библиотеку на `D:`, ищет установщик DIM в `~/Downloads`, печатает чеклист (аккаунт → DIM → Iray). Полная автоматизация невозможна: дистрибутив привязан к бесплатному аккаунту DAZ. Пиратские сборки не используются — только официальный дистрибутив.

**Конфигурация:** детекция в `pipeline.py:86-124` — `%APPDATA%\DAZ 3D\InstallManager`, стандартные пути `DAZ 3D/DAZStudio*/DAZStudio.exe`, реестр, фоллбек `C:\Program Files\DAZ 3D\DAZStudio<v> 64-bit\DAZStudio.exe`.

**Где используется:** только диагностика и валидация деклараций. `vn assets daz validate` проверяет `assets_src/daz/**/*.render.yaml` по схеме `daz_render@1`; `tools/vn/src/vn/assets/licenses.py` сверяет поле `license` каждой декларации с реестром `content/licenses.yaml` (`license_registry@1`), и релизный гейт отказывается собирать билд с ассетом `game_use: false` или с nsfw-выходом из ассета `nsfw_allowed: false` (`release.py:436-445`, правила — `assets/licenses.py:94-103`). **В репозитории сегодня ноль `*.render.yaml`, ноль `.duf`, ноль `*.provenance.json`** — вся эта машинерия написана и ни разу не запускалась на реальных данных.

**Что DAZ умеет и что у нас НЕ подключено:** headless-рендер (`-headless`, `-noPrompt`, `-scriptArg`, `-scriptArgsFile`), DzScript-автоматизация, `DzRenderMgr::doRender()`, сборка кадровых последовательностей — **NOT IMPLEMENTED**: ни одного `.dsa` в репозитории, ни одного вызова DAZ из `vn`.

**Когда использовать / когда НЕ использовать:** **критично для нашего железа** — Iray в DAZ Studio 4.x скомпилирован до Blackwell и на RTX 5080 уходит в CPU-рендер (подтверждено модератором DAZ в форумном треде, не фольклор). На 4.24 оставаться нельзя. Filament — только для блокинга/итераций, не для поставляемых кадров.

**Официальная документация:** https://docs.daz3d.com/doku.php/public/software/dazstudio/4/start — по-прежнему **единственный полный** User Guide + Reference Guide + Scripting API. Ветка 6: https://docs.daz3d.com/doku.php/public/software/dazstudio/6/start — это индекс-страница (таблица билдов + ссылка на change log), гайда и API-референса по 6 не существует.
**Лучшие материалы:**
- https://www.daz3d.com/blog/daz-studio-6-technical-highlights — читать первым: Qt6, Iray 2025.0.3, DzScript с ECMAScript 5.1 → ES7/2016, поддержка Blackwell/RTX 50-series, и **список того, что в DS6 выпилено** (3Delight, Collada-экспортёр, Dynamic Clothing, Mimic, Photoshop 3D Bridge, Render Album, Shader Baker/Builder).
- https://www.daz3d.com/forums/discussion/728091/daz-studio-2025-6-25-2025-x-nvidia-iray-2024-2025 — канонический тред «версия Iray ↔ ветка драйвера»: минимум **NVIDIA 576.57 (R575)**, первый Studio Driver после минимума — 576.80.
- https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/tech_articles/command_line_options/start — самая ценная страница темы, если мы когда-нибудь автоматизируем рендер: точный список флагов с версиями появления.
- https://3dshards.com/daz-studio-iray-settings-guide/ — три конкретных пресета Iray (Fast Preview: Max Samples 500, Converged 85–90 %; Standard Final: 2500, 95 %; Portrait: 4000–8000, RQ 2.0, 95–98 %, денойзер на коже — осторожно).
- https://www.daz3d.com/forums/discussion/185446/tricks-for-speeding-up-iray-rendering-let-s-hear-em — длинный практический тред; главный вывод, который стоит запомнить: **текстуры дороже геометрии**, уменьшение текстур даёт кратный выигрыш.

**Лицензии:** https://www.daz3d.com/eula · обзор типов лицензий https://www.daz3d.com/daz-licenses (Standard / Editorial / Interactive / 3D Printing) · https://www.daz3d.com/interactive-license-info. Два пункта, на которые прямо стоит посмотреть глазами: (а) разграничение «2D-рендеры» и «продукты, из которых Content можно извлечь»; (б) пункт про использование Content «в связке с любым AI-движком … с возможностями автогенерации» — он напрямую касается связки DAZ → ComfyUI (img2img/ControlNet/обучение LoRA). **Никаких юридических выводов здесь нет: проверьте актуальный текст EULA и условия Interactive License по официальным ссылкам перед коммерческой дистрибуцией.** Проектная позиция по AI-моделям — ADR-0008, единственный **непринятый** ADR.

## 1.8. Virt-a-Mate и The Sims 4 — задекларированы, не установлены

`vn pipeline doctor` на машине владельца выдаёт по ним **WARN: не установлен**. Обе интеграции существуют в тулинге на уровне «детекция + валидатор декларации»:

| Источник | Детекция | Схема декларации | Статус |
|---|---|---|---|
| Virt-a-Mate | `VN_VAM` → стандартные корни → Steam-библиотеки (appid 2149830), `pipeline.py:174-190` | `vam_render@1` | IMPLEMENTED (валидатор) / **не установлен**, ноль деклараций |
| The Sims 4 | `VN_SIMS4` → реестр Maxis (пишут EA App и Origin), `pipeline.py:196-210` | `sims4_render@1` | то же; ADR-0007 прямо называет это **заделом**, продакшен-контент на Sims 4 не производится и не планируется |

Установочные скрипты есть: `tools/install-vam.ps1`, `tools/install-sims4.ps1`. Подробности — [VaM](18-vam.md) и [Sims 4](19-sims4.md); ссылки на материалы — часть 3 этого файла.

**Отдельно про Sims 4 и монетизацию.** Модель проекта — коммерческая игра с patron-тиром. Официальный EA content policy содержит пункты, которые касаются ровно этого сценария (продажа, paywall), а EA User Agreement даёт лицензию «for your non-commercial use». Три документа, которые надо прочесть глазами до того, как кадр из Sims 4 попадёт в `game/`:
https://www.ea.com/legal/user-agreement · https://help.ea.com/en/articles/security-and-rules/ea-content-policy/ · https://help.ea.com/en/articles/the-sims/the-sims-4/mods-policy/.
**Проверьте актуальный текст по этим ссылкам перед коммерческой дистрибуцией.** В content policy есть раздел про запрос разрешения на особые случаи с формой rights clearance — это единственный санкционированный путь, и это разговор с юристом, а не «наверное можно».

---

# Часть 2. Рекомендовано, но не внедрено

> **Это рекомендации, а не план. Стек автоматически не меняем.** Работающее решение не заменяется «потому что бывает иначе» — только при доказанном выигрыше в скорости или качестве продакшена. Приоритеты и сроки — [Roadmap](37-roadmap.md).

| # | Что | Зачем нам | Цена | Приоритет |
|---|---|---|---|---|
| 1 | `renpy lint --error-code --all-problems` в CI | **чинит существующий баг** | 1 строка × 3 файла | высокий |
| 2 | Ren'Py testcases (8.5) со скриншот-диффом | ловит регрессии перерендеренных спрайтов | новая подсистема | средний |
| 3 | `sha256` в `tools/comfyui-models.yaml` | воспроизводимость моделей | ручной прогон | средний |
| 4 | Снапшот ComfyUI-Manager + «боевой» инстанс | заморозка окружения генерации | конфигурация | средний |
| 5 | Blender для детерминированных камер/частиц | дешевле и стабильнее Wan там, где нужен детерминизм | новый инструмент | средний |
| 6 | Официальное расширение VS Code для Ren'Py | подсветка/переходы по коду | 1 клик | низкий |
| 7 | AV1 (`libsvtav1`) вместо VP9 | меньше вес билда на десктопе | пересборка всех лупов | низкий, только после веб-решения |
| 8 | SageAttention 2.2.0 на Blackwell | ~30–35 % к скорости генерации | сборка/wheel | низкий |

**1. Движковый `lint` в CI сейчас декоративный.** Все три конфига гоняют `renpy.sh . lint` (`.github/workflows/ci.yml:73`, `canary.yml:49`, `.gitlab-ci.yml:47`) — **без `--error-code` и без `--all-problems`**. По официальным докам Ren'Py (https://www.renpy.org/doc/html/cli.html) `lint` возвращает 0, если не передать `--error-code`, и **обрезает вывод десятью проблемами каждого вида** без `--all-problems`. То есть красный движковый lint нашу сборку сегодня не остановит. Это единственный пункт в списке, который является не улучшением, а починкой.

**2. Ren'Py 8.5 принёс собственный фреймворк тестов** — https://www.renpy.org/doc/html/testcases.html: блоки `testcase` со стейтментами (`advance`, `click`, `keysym`, `assert`, `screenshot`, `repeat`, `until`), сьюты, параметризация. Ключевая для нас часть — `screenshot` **сравнивает с эталоном**: «если файл уже существует, текущий скриншот сравнивается с существующим; если различие больше `max_pixel_difference` пикселей, поднимается `RenpyTestScreenshotError`». Для конвейера, где спрайты перегенерируются AI, baseline-дифф скриншотов — самая высокорычажная вещь в 8.5. Наш `vn test smoke` (in-process автопилот, `cli.py:1268-1401`) решает другую задачу — проход по веткам, — и одно другому не мешает. См. [Тесты](27-testing.md).

**3–4. Воспроизводимость генерации.** Сейчас у нас: `sha256: null` у всех моделей, ноль workflow-JSON в git, ноль зафиксированных сидов. Дисциплина, которую стоит завести до того, как накопится 200 ассетов: `workflow_api.json` в git по одному на класс ассета; фиксированные сиды в имени файла или сайдкаре; **хеши моделей**, потому что «flux2-klein-4b» — это не версия, версия — это SHA256, а репозитории моделей молча перезаливают; заморозка окружения через Snapshot-Manager (https://github.com/Comfy-Org/ComfyUI-Manager) на отдельном «боевом» инстансе. У нас уже есть куда это положить: `tools/vn/src/vn/assets/provenance.py` умеет вытаскивать метаданные из PNG ComfyUI и собирать цепочку — код написан, сайдкаров ноль.

**5. Blender там, где нужен детерминизм.** Для медленного наезда камеры, параллакса по слоям, дождя/снега/пылинок Blender **строго лучше** AI-видео: детерминирован, перерендеривается в любом разрешении, зацикливается по построению без дрейфа яркости, даёт альфу и не поднимает лицензионных вопросов (GPL; результат ваш). Wan остаётся для органического движения (волосы, ткань, дыхание, вода). Практический водораздел: **Blender — камера и детерминированные частицы, Wan — движение субъекта.** Материалы — часть 3.
Версия по ресёрчу: Blender **5.2 (14 июля 2026)**; статус LTS **не подтверждён** — проверьте на странице загрузки сами.

**6. Официальное расширение VS Code** — https://github.com/renpy/vscode-language-renpy (издатель `renpy`, id `renpy.language-renpy`; последняя опубликованная — 805.1.0 от 2025-11-16, репозиторий живой). Старый апстрим `LuqueDaniel/vscode-language-renpy` в маркетплейсе заморожен на 2.3.6 (2023) — ставьте официальное. Диагностику расширения считайте подсказкой, а не заменой `renpy lint`.

**7. AV1.** Ren'Py играет AV1 с 8.1.0, наша сборка ffmpeg — full, значит `libsvtav1` доступен. Выигрыш по весу относительно VP9 в ресёрче **не подтверждён измерением** на нашем типе контента, а веб-сборка (если она когда-нибудь появится) зависит от браузерного декодера, где VP9 — безопасный пол. Вывод: не трогать, пока не появится измеренная выгода и решение по web. Рецепты, когда дойдёт: https://gitlab.com/AOMediaCodec/SVT-AV1/-/blob/master/Docs/Ffmpeg.md.

**8. SageAttention 2.2.0 на Blackwell** — https://github.com/Comfy-Org/ComfyUI/discussions/11583 (≈30–35 % на RTX 5090, бенчмарк 14м30с → 9м30с на 40 шагов) и готовые wheel'ы https://github.com/mobcat40/sageattention-blackwell. **Важно:** глобальный флаг `--use-sage-attention` использовать нельзя — он тянет Triton-бэкенд и даёт чёрный вывод на Qwen/Wan; правильный путь — нода «Patch Sage Attention» из ComfyUI-KJNodes.

**Что рассматривали и решили НЕ брать:**
- **renkit** (https://github.com/kobaltcore/renkit, v6.1.0) — Rust-обвязка для headless-Ren'Py (`renutil`/`renconstruct`/`renotize`). У нас эту роль уже полностью занимает `vn package`/`vn release build`, а нотаризация macOS не нужна. Добавит движущихся частей без выигрыша.
- **ImageMagick** — мощнее Pillow на массовой конвертации, но у нас конвертация уже кэшируется по blake3 и не является узким местом; вводить второй бинарь в зависимости сборки не за что.
- **SUPIR** (апскейл) — https://github.com/kijai/ComfyUI-SUPIR/blob/main/LICENSE **явно некоммерческий**. Коммерческое использование требует письменного разрешения автора. Для платной игры это блокер, а не формальность; в манифесте у нас Real-ESRGAN (BSD-3-Clause) — и правильно.
- **Sonic** (липсинк) — https://github.com/jixiaozhong/Sonic, лицензия **CC BY-NC-SA 4.0**, репозиторий прямо отправляет коммерческих пользователей в облако Tencent. Его массово советуют в ComfyUI-туториалах; нам он не подходит.

---

# Часть 3. Обучающие материалы по темам

Всё ниже — проверенные ссылки. Если раздел выглядит коротким, это не лень: непроверенное и мусорное выкинуто.

## 3.1. Ren'Py

**Официальная документация** (все — `renpy.org/doc/html/`):
- https://www.renpy.org/doc/html/ — корень; помните, что он собран с ветки 8.5.4, а качается 8.5.3.
- https://www.renpy.org/doc/html/screens.html — полный список стейтментов языка экранов; там же `config.variants` / `RENPY_VARIANT` — механизм форка UI под Steam Deck и мобилки. Спутники: `screen_actions.html`, `screen_special.html`, `screen_python.html`, `style_properties.html`.
- https://www.renpy.org/doc/html/transforms.html#atl — канон ATL (`atl.html` — заглушка).
- https://www.renpy.org/doc/html/layeredimage.html — `layeredimage`/`group`/`attribute`/`always`/`if`/`when`, авто-паттерн, `LayeredImageProxy`. Важная фраза дословно: Ren'Py обрезает картинки по bbox непрозрачных пикселей перед загрузкой в RAM — предварительный кроп слоёв не даёт ничего.
- https://www.renpy.org/doc/html/movie.html — коды/контейнеры, сигнатура `Movie()`, `side_mask`, `start_image`, `group`, предупреждение про YUV444. **Читать раньше любых общих гайдов по видео** — она их отменяет.
- https://www.renpy.org/doc/html/build.html — `build.classify()`, `build.archive()`, `build.package()`; там же выбор пакета «Windows, Mac, and Linux for Markets» для Steam/itch и честная фраза про `.rpa`: защищает только от «казуального копирования».
- https://www.renpy.org/doc/html/achievement.html — единственная официальная поверхность Steam; `achievement.steam` равен `None`, если Steam не инициализировался, — **вызовы надо оборачивать проверкой**, иначе билд падает у всех, кто запускает вне Steam, включая вас.
- https://www.renpy.org/doc/html/testcases.html — фреймворк тестов 8.5 (см. часть 2).
- https://www.renpy.org/doc/html/config.html, https://www.renpy.org/doc/html/screen_optimization.html, https://www.renpy.org/doc/html/displaying_images.html — перф, предсказание, кэш образов. Ключевые числа: `config.predict_statements` = 32, `config.image_cache_size_mb` = 300, `config.cache_surfaces` по умолчанию **False** → 4 байта на пиксель (кадр 1920×1080 ≈ 8 МБ, в 300 МБ кэша влезает ~36 штук).
- https://www.renpy.org/doc/html/translation.html — штатная локализация движка. У нас она **не используется** (свой PO round-trip, ADR-0005), но страница нужна, чтобы понимать, чем наш путь отличается.
- https://www.renpy.org/doc/html/developer_tools.html — Shift+O консоль, Shift+D dev-меню, Shift+R перезагрузка, Shift+I инспектор стилей, `--warp file:line`.
- https://www.renpy.org/doc/html/web.html — веб-порт: **нет многопоточности, значит нет фонового предзагруза образов**; плавная на десктопе игра может дёргаться в браузере на тех же ассетах.

**Лучшие community-гайды:**
- https://feniksdev.com/organizing-a-renpy-project/ — лучший современный текст про организацию проекта: файл длиннее 1000 строк — делить; layeredimage-декларации в отдельный файл; большие системы (галерея, миниигры) — по файлу на систему; имена, начинающиеся с `00`, зарезервированы движком; переименовали `.rpy` — удалите `.rpyc`, иначе duplicate label. Индекс материалов автора: https://feniksdev.com/resources/.
- https://vndev.wiki/Guide:Ren%27Py_visual_novels_on_Steam — самый актуальный сквозной разбор «Ren'Py → Steam» (9 разделов: приложение, страница, загрузка, ачивки, тестирование, демо, DLC, бандл, патч с наготой), обновлялся в конце 2025. Заодно объясняет 30-дневное правило Steam между покупкой app credit и релизом.
- https://www.lezcave.com/renpy-tutorials/ — структурированные серии: основы (9 частей), **язык экранов (9 частей)**, **git (7 частей + бонус)**. Педагогика хорошая; в подвале сайта © 2021 — версионно-специфичные детали проверяйте.
- https://vndev.wiki/Main_Page — живая community-вики (правки августа 2026).

**Форумы и сообщества:**
- https://discord.gg/6ckxWYm — официальный Discord (ссылка присутствует на renpy.org). В 2026 ответы находятся именно там: обсуждение мигрировало с форумов.
- Lemma Soft Forums: https://lemmasoft.renai.us/forums/viewforum.php?f=8 (вопросы), https://lemmasoft.renai.us/forums/viewforum.php?f=51 (Cookbook), https://lemmasoft.renai.us/forums/viewtopic.php?t=60711 («BEST of Cookbook»). ⚠️ Все Lemma Soft-адреса отдают **HTTP 403 автоматическим фетчерам** (блокировка ботов phpBB) — форма URL канонична, но содержимое и актуальность верифицировать не удалось. Само сообщество предупреждает: большая часть кода в Cookbook старше 4 лет и предшествует Python 3 / Ren'Py 8.
- https://patreon.renpy.org/ — лонгриды автора движка; первые ~90 дней для спонсоров, потом публично. Самый высокий сигнал за пределами референса.

**GitHub-репозитории:**
- https://github.com/renpy/vscode-language-renpy — официальное расширение VS Code (см. часть 2).
- https://github.com/CensoredUsername/unrpyc — декомпилятор `.rpyc` (v2.0.4). Для нас это **модель угроз**, а не инструмент: шипнутый скрипт восстанавливается. Практический вывод — не держать в `.rpy` ничего секретного: ни ключей, ни логики гейтинга patron-контента, которой вы дорожите.
- https://github.com/shawna-p/RenPy-Achievements — обёртка над слоем ачивок Ren'Py (MIT, 12 коммитов, без тегов релизов). Читать как референс, не как поддерживаемую зависимость. У нас свои достижения — `game/framework/00_core/080_achievements.rpy`.
- https://github.com/topics/ren-py — топик-индекс целиком: **42 репозитория**. Полезно знать, что рынок инструментов вокруг Ren'Py именно такого размера.

**Отдельно — чего в интернете НЕТ.** Публичного разбора «как устроен большой коммерческий Ren'Py-проект» не существует. Ближайшее — гайд Feniks (уровень соло-разработчика). Единственный найденный материал по Black Tabby Games (Slay the Princess) — https://www.gamedeveloper.com/design/deep-dive-player-centered-narrative-design-in-slay-the-princess — и он **строго про нарративный дизайн**, ноль про движок и архитектуру. Ходящее по сети утверждение, что они заменили пререндеренное видео шейдерами, первоисточника не имеет — **не повторяйте его как факт**. Практическое следствие для нас: описание — это наш хендбук, брать его неоткуда.
Домены, которые высоко ранжируются по этим запросам и являются машинно-сгенерированным мусором: `mindfulchase.com`, `oreateai.com`, `brainbound.blog`, `sciencedepot.blog`, `cgpatool.com`.

## 3.2. Python и библиотеки конвейера

Верифицированный ресёрч покрывает только те библиотеки, которые реально стоят у нас, и только их официальные страницы:
- https://pillow.readthedocs.io/ (+ https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) — параметры сохранения WebP/AVIF со значениями по умолчанию. Pillow ≥ 12 читает и пишет AVIF **нативно**, плагин `pillow-avif-plugin` больше не нужен и создаёт конфликт регистрации.
- https://github.com/python-pillow/Pillow/releases — фактический changelog (внутренний `CHANGES.rst` остановлен на 11.0.0).
- https://psd-tools.readthedocs.io/ — итерация по слоям, `composite()` целиком и по слою, мост в PIL.
Для `click`, `PyYAML`, `jsonschema`, `blake3`, `polib`, `pytest` проверенных ссылок в ресёрч-пакете нет — намеренно их не подставляю.

## 3.3. DAZ Studio

**Официальная документация:** https://docs.daz3d.com/doku.php/public/software/dazstudio/4/start (полный User/Reference Guide + Scripting API — по-прежнему только для 4.x) · https://docs.daz3d.com/doku.php/public/software/dazstudio/6/start (индекс 6.x) · загрузка https://www.daz3d.com/get_studio.
**Скриптинг (если дойдём до автоматизации рендера):** API-референс https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/scripting/api_reference/start · опции командной строки https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/tech_articles/command_line_options/start · примеры https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/scripting/api_reference/samples/start · `DzRenderMgr` https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/rendermgr_dz · `DzRenderOptions` https://docs.daz3d.com/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/renderoptions_dz · `DzApp` https://docs.daz3d.com/doku.php/public/software/dazstudio/4/referenceguide/scripting/api_reference/object_index/app_dz. Форум скриптеров: https://www.daz3d.com/forums/categories/daz-script-developer-discussion. **Важно:** API-референса под 6.x не существует — вы пишете по докам 4.x на рантайме Qt6/ES7, дрейф гарантирован.
**Батч-рендер:** https://github.com/ephread/Autodazzler — архивирован (read-only с мая 2023), но его JSON-конфиг — хорошая спецификация для собственного драйвера. https://www.daz3d.com/daz-studio-premier — собственная Render Queue у DAZ теперь фича подписки ($18.98/мес по официальной странице), причём контент активен, пока активна подписка. https://auravix-studio.itch.io/batchflow-render — сторонний standalone-планировщик ($19.99+): очередь из `.duf`, детект зависания, режим перезапуска DAZ между задачами. Для одиночного продакшена дешевле написать свой драйвер на `-headless`/`-scriptArg`.
**Библиотека контента:** https://www.daz3d.com/install-manager-info · https://www.daz3d.com/install-manager-faq · тред про EOL Daz Central https://www.daz3d.com/forums/discussion/657301/daz-Central-Ending-New-Enhanced-Install-Manager · как организовать библиотеку https://www.daz3d.com/forums/discussion/427141/how-to-best-organize-my-library-starting-from-scratch · библиотека на нескольких машинах https://www.daz3d.com/forums/discussion/571176/managing-a-large-library-and-using-it-with-multiple-machines. Практика: **DIM, не Daz Connect** — Connect хранит контент в непрозрачной БД-раскладке, которую трудно бэкапить, версионировать и переносить.
**Фигуры:** https://www.daz3d.com/introducing-genesis-9 · https://www.daz3d.com/blog/a-first-look-at-whats-coming-in-genesis-9 · честный контрапункт от вендорского сообщества https://www.renderhub.com/forum/9144/daz-genesis-8-or-genesis-9-what-are-you-using-in-2025 (консенсус там — **за G8**: библиотеки, простота, ресурсы). Поколение выбирается **до первого кадра и не меняется**.
**Оптимизация и техника:** https://3dshards.com/daz-studio-iray-settings-guide/ (пресеты) · https://www.daz3d.com/forums/discussion/185446/tricks-for-speeding-up-iray-rendering-let-s-hear-em · https://www.daz3d.com/forums/discussion/635486/ (VRAM: пик приходится на фазу «Retrieving Geometry»; «текстуры бесконечно дороже моделей») · https://3dshards.com/daz-studio-geometry-shell-tutorial-what-it-is-and-how-to-use-it/ и https://renderguide.com/daz3d-geometry-shells-tutorial/ (геошеллы — штатный приём для слоёв кожи: пот, грязь, румянец, без правки базовых текстур) · https://medium.com/@seancannon/8-things-i-wish-i-knew-when-starting-daz-and-renpy-53356c957a18 (2022, но два совета всё ещё верны: лочить камеру и сохранять её пресетом; рендерить в 3840 3–4 минуты и уменьшать до 1920 вместо долгого добивания шума) · https://www.versluis.com/2015/04/how-to-render-iray-with-transparency-in-daz-studio/ (рендер на прозрачном фоне: Environment → Dome → выключить Draw Dome, Ground → выключить Draw Ground; PNG/TIFF, не JPG) · платный официальный курс https://www.daz3d.com/optimizing-daz-studio-memory-rendering-scenes-and-workflow.
**Правило, которое экономит недели:** уменьшать, а не денойзить. Рендер в 2× и даунсемпл сохраняет микродеталь кожи, которую OptiX-денойзер смазывает, — это самый частый признак дешёвой DAZ-новеллы.

## 3.4. Virt-a-Mate

Формальной документации не существует — канонические поверхности это хаб и Patreon автора.
- https://hub.virtamate.com/ — репозиторий контента и плагинов (возрастной гейт). Полезная проверенная деталь: несуществующий id даёт настоящий 404, поэтому страница с гейтом = ресурс реально есть.
- https://github.com/acidbubbles/vam-acidbubbles-home — индекс 15 плагинов автора; лучшая карта экосистемы.
- https://github.com/acidbubbles/vam-timeline — keyframe/bezier-анимация всех контроллеров и морфов, очередь анимаций. Для катсцен не опционален. v6.5.1 — **август 2024**: флагманский плагин экосистемы двухлетней давности, экосистема заморожена.
- https://github.com/acidbubbles/vam-keybindings — палитра из 200+ команд с fuzzy-поиском и **протоколом broadcast-интеропа** (`OnActionsProviderAvailable` → `OnBindingsListRequested`): это ваш «командный автобус» для съёмки серий кадров с одной клавиши.
- https://github.com/acidbubbles/vam-glance и https://github.com/acidbubbles/vam-improved-pov — предиктивное движение глаз и корректная позиция камеры от глаз. Направление взгляда — главный признак «живой/кукла» в VN-стилле.
- https://github.com/yunidatsu/Eosin_VRRenderer — оффлайн-рендер по кадрам. **Проверено по исходнику:** пишет нумерованные PNG/JPG-последовательности (`_%06d`, PNG — с альфой) и WAV отдельно; **никакого ffmpeg и никакого видеокодера внутри нет** — муксите сами. Для нас это плюс: PNG с альфой ложится в анимированные спрайты без кеинга. Хаб-страница ресурса: https://hub.virtamate.com/resources/video-renderer-for-3d-vr180-vr360-and-flat-2d-audio-bvh-animation-recorder.11994/
- Менеджеры пакетов `.var`: https://github.com/cyberpunk2073/vam-backstage (MIT, деревья зависимостей, докачка недостающего), https://github.com/Kruk2/VamToolbox (разреженная установка через симлинки; **требует запуска от админа**), https://github.com/BoominBobbyBo/iHV (правимые PowerShell-скрипты — единственный вариант, который встраивается в скриптуемый build-step).
- Автоматизация: https://acidbubbles.github.io/vam-scripter/ и https://github.com/acidbubbles/vam-scripter (JS-подобный движок скриптов **внутри** VaM, включая класс `FileSystem`), шаблон плагина https://github.com/acidbubbles/vam-plugin-template, утилиты https://github.com/acidbubbles/vam-devtools. Внешнее управление задокументировано в чужом продукте, но по делу: https://doc.voxta.ai/docs/integrations/vam/creators/app-triggers — как дёргать любой action/storable любого атома снаружи. **Официального CLI и headless-режима у VaM1 нет.**
- Лицензии: https://store.steampowered.com/eula/2149830_eula_0 (Mesh VR, LLC) и https://hub.virtamate.com/help/terms/ (условия хаба). Лицензия конкретного ассета — это поле `licenseType` в его `meta.json`, и **оно может расходиться с README** (у VAMOverlays README говорит CC BY, `meta.json` — CC BY-SA). **Проверьте актуальные условия по обеим ссылкам и `licenseType` каждого ассета перед коммерческой дистрибуцией.**
- Практическая грабля воспроизводимости: в `meta.json` выставляйте `scriptReferenceVersionOption` / `standardReferenceVersionOption` в `"Exact"`, а не `"Latest"` — иначе обновление зависимости молча поменяет лицо персонажа между кадрами.

## 3.5. The Sims 4

- Официально: https://www.ea.com/games/the-sims/the-sims-4 · политика по модам https://help.ea.com/en/articles/the-sims/the-sims-4/mods-policy/ · моды и патчи https://help.ea.com/en/articles/the-sims/the-sims-4/mods-and-the-sims-4-game-updates/ (почему после каждого патча моды отключаются автоматически, и коды ошибок: 110 — устаревшие моды после патча; 102/123/125/127/129/131 — проблемы скриптовых модов).
- https://simscommunity.info/game-updates/sims-4-updates/ — индекс всех патчей с датами; практический способ узнать **до** запуска, что ваш стек модов только что умер.
- Позирование: https://sims4studio.com/thread/2617/andrews-studio — тред автора Pose Player и Teleport Any Sim (канонические загрузки). Без Pose Player снимать VN в Sims 4 нельзя вообще. Обучение: https://srslysims.net/tutorials/sims4studio_poseplayer/ (самый внятный сквозной путь «сделать пак поз») и доска https://sims4studio.com/board/25/cas-pose-tutorials; общий индекс туториалов https://sims4studio.com/board/28/sims-custom-content-tutorial-index.
- Камера и сет-дека: https://twistedmexi.com/ (доска статусов модов автора — живая, показывает, что сейчас сломано) · https://www.curseforge.com/sims4/mods/t-o-o-l · https://www.curseforge.com/sims4/mods/better-buildbuy-organized-debug (Light Editor и кинематографическая камера по TAB в режиме строительства).
- Съёмка: https://snootysims.com/wiki/sims-4/hiding-the-ui/ — компактный список ровно тех настроек, которые нужны скриншот-конвейеру: снять «Capture UI» в **обоих** разделах Screen Capture, TAB в Live Mode, `headlineeffects off` (плюмбобы и облачка мыслей — вещь №1, которая протекает в кадр).
- Грейдинг: https://reshade.me/ (+ https://reshade.me/forum/releases — фактическая история версий, потому что GitHub-репозиторий https://github.com/crosire/reshade релизов не публикует). Правило гигиены прямо со страницы ReShade: **коммитить пресеты, не бинарники и не шейдеры**.
- **Главное:** технически всё зрелое и дешёвое — именно поэтому велик соблазн пропустить лицензионный шаг. Не пропускайте: см. §1.8.

## 3.6. Blender

- https://www.blender.org/download/ · руководство https://docs.blender.org/manual/en/latest/. Версия по ресёрчу — 5.2 (14 июля 2026); статус LTS не подтверждён.
- https://dreamjacob.com/how-to-create-stunning-2-5d-parallax-animations-in-blender/ — параллакс по слоям-плоскостям: разложить кадр по маскам, импортировать плоскостями на разной дистанции, анимировать камеру.
- https://blenderartists.org/t/2-5d-motion-parallax-from-single-image/602413 — долгоживущий тред по параллаксу из одного изображения, с альтернативным подходом через рисование альфы в UV-редакторе.
- https://patdavid.net/2014/02/25d-parallax-animated-photo-tutorial/ — старый (2014), но самое ясное объяснение техники, целиком на свободном софте, со скачиваемым `.blend`.
- Лицензия: Blender под GPL, результат вашей работы ограничений не несёт — самая беспроблемная позиция среди всего в этом файле. (Страница лицензии не была доступна автоматической проверке — при необходимости откройте её в браузере.)
- Практика для нас: рендерить **PNG-последовательность**, а не видео, и кодировать ffmpeg'ом в VP9/`yuv420p` — встроенный кодировщик Blender не даёт нужного контроля над пиксельным форматом. EEVEE Next достаточно быстр для 2.5D-параллакса, Cycles на плоских проекциях не нужен.
- Смежное: Blender 5.x убрал нативный Collada; 4.5 LTS — последняя версия с ним «из коробки» (актуально, если когда-нибудь понадобится импорт из Sims 4 Studio).

## 3.7. ComfyUI и генерация изображений

**Официальное:** https://docs.comfy.org · https://github.com/comfyanonymous/ComfyUI · https://blog.comfy.org · загрузка https://comfy.org/download · установка под Windows https://docs.comfy.org/installation/desktop/windows · шаблоны воркфлоу https://comfy.org/workflows (600+) · реестр нод https://registry.comfy.org/ · CLI https://github.com/Comfy-Org/comfy-cli (`comfy install`, `comfy launch`, `comfy node install`, `comfy model download`, `comfy run --workflow`).
**Читать в первую очередь:** https://blog.comfy.org/p/new-comfyui-optimizations-for-nvidia — NVFP4 (~2× на 50-й серии) **и ловушка cu130**; async offload и pinned memory включены по умолчанию с декабря 2025.
**Скорость на 16 ГБ:** https://github.com/nunchaku-ai/nunchaku (Apache-2.0) и ноды https://github.com/nunchaku-ai/ComfyUI-nunchaku — 4-битный инференс; метод описан в https://hanlab.mit.edu/blog/svdquant-nvfp4. Поддержки FLUX.2 в Nunchaku нет.
**Контроль и консистентность:**
- https://docs.comfy.org/tutorials/basic/inpaint — Mask Editor и `VAE Encode (for Inpainting)` с `grow_mask_by`. **Это и есть наш конвейер вариантов эмоций:** зафиксировать позу/тело, маскировать только лицо, перегенерировать 12 выражений. Гораздо дешевле и стабильнее, чем перекатывать спрайт целиком.
- ControlNet кросс-модельным не бывает — под каждую базовую модель свой: https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union (Apache-2.0), https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union (Apache-2.0), https://huggingface.co/alibaba-pai/FLUX.2-dev-Fun-Controlnet-Union (**наследует non-commercial-лицензию FLUX, несмотря на происхождение от Alibaba**).
- Обучение LoRA: https://github.com/ostris/ai-toolkit (MIT, держит темп с релизами моделей), https://github.com/Nerogar/OneTrainer (AGPL-3.0, GUI, поддерживает Chroma), https://github.com/kohya-ss/sd-scripts + GUI https://github.com/bmaltais/kohya_ss (лучший путь для SDXL-линейки).
**Апскейл, безопасный для коммерции:** https://github.com/xinntao/Real-ESRGAN (BSD-3-Clause; у нас в манифесте) и https://github.com/ssitu/ComfyUI_UltimateSDUpscale (GPL-3.0 на код нод; веса — те, что вы уже очистили по лицензии).
**Модели и их лицензии** (адреса для чтения, без выводов):
| Модель | Лицензия по карточке | Адрес |
|---|---|---|
| Z-Image-Turbo / Base | Apache 2.0 | https://huggingface.co/Tongyi-MAI/Z-Image-Turbo |
| Qwen-Image / -Edit | Apache 2.0 | https://github.com/QwenLM/Qwen-Image |
| Chroma1-HD | Apache 2.0, без safety-выравнивания | https://huggingface.co/lodestones/Chroma1-HD |
| FLUX.2-klein-4B | Apache 2.0 | https://huggingface.co/black-forest-labs/FLUX.2-klein-4B |
| FLUX.2-dev, klein-9B | FLUX Non-Commercial License | https://bfl.ai/legal/non-commercial-license-terms |
| Illustrious-XL | поле `sdxl-license` (RAIL++-M) + ToS сервиса | https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.0 |
**Проверьте актуальный текст каждой лицензии по её официальной ссылке перед коммерческой дистрибуцией.** Разбор того, как ломаются лицензионные цепочки в мерджах, — кейс https://civitai.com/articles/18619/what-the-license. Наша проектная позиция — ADR-0008 (статус: предложено).
**Ловушка, о которой все узнают дважды:** сохранённый из UI JSON воркфлоу **не принимается** эндпойнтом `/prompt` — нужен экспорт в API-формате.

## 3.8. Генерация видео

- **Wan 2.2** — https://github.com/Wan-Video/Wan2.2, веса https://huggingface.co/Wan-AI, лицензия https://github.com/Wan-Video/Wan2.2/blob/main/LICENSE.txt (**чистый Apache 2.0** без приложений с ограничениями — самая беспроблемная позиция среди видео-моделей). Официальный воркфлоу: https://docs.comfy.org/tutorials/video/wan/wan2_2. Модельный зоопарк 2.2: T2V-A14B, I2V-A14B, TI2V-5B, S2V-14B, Animate-14B. **Wan 2.5/2.6 — закрытые API-продукты, открытых весов нет**, что бы ни писали блоги.
- 16 ГБ VRAM: GGUF-кванты https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF (Q2_K 5,3 ГБ → Q8_0 15,4 ГБ) + загрузчик https://github.com/city96/ComfyUI-GGUF (файлы кладутся в `ComfyUI/models/unet`). Обёртка, куда новые модели приезжают раньше ядра: https://github.com/kijai/ComfyUI-WanVideoWrapper.
- Бесшовные лупы: первый и последний кадр — **одно и то же изображение**, затем выбросить последний кадр (иначе кадр N дублирует кадр 0 и на каждом цикле будет однокадровый рывок). Готовый шаблон «Video to Seamless Loop Converter»: https://comfy.org/workflows/template_sirolim_seamless_loop-31ea7d2d9224/. Держите лупы в пределах 5 с / 121 кадра.
- Интерполяция: https://github.com/Fannovel16/ComfyUI-Frame-Interpolation — генерировать в 12–16 fps и доводить до 24/30. На Windows ставить **через `install.bat`**. Порядок операций: восстановление/апскейл → интерполяция → кодирование, не наоборот.
- Апскейл видео: https://github.com/ByteDance-Seed/SeedVR (Apache 2.0) + нода https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler. `batch_size` — из ряда 4n+1, **минимум 5** для темпоральной консистентности; понижать его ради VRAM нельзя, сначала offload/BlockSwap/GGUF.
- Кодирование из ComfyUI: https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite (нода `Video Combine`, GPL-3.0; профили кодеков — JSON в папке `video_formats`). Дефолты не настроены под Ren'Py — либо один раз напишите VP9-профиль с `yuv420p`, либо кодируйте отдельным вызовом ffmpeg, как делает наш конвейер.
- Референс-пайплайн от вендора: https://www.nvidia.com/en-us/geforce/news/rtx-ai-video-generation-guide/ (март 2026) — там же честные требования: 16 ГБ VRAM, 64 ГБ RAM, клипы ≤ 5 с (121 кадр), 20–30 шагов при итерациях и 40+ на финал.
- **Лицензии, на которые стоит посмотреть до, а не после:** LTX-2 — https://github.com/Lightricks/LTX-2/blob/main/LICENSE (порог годовой выручки $10 млн, приложение из 20 ограничений и требование **явно раскрывать машинную природу контента** при распространении); HunyuanVideo 1.5 — https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/LICENSE (территория **исключает ЕС, Великобританию и Южную Корею**); Sonic — https://github.com/jixiaozhong/Sonic (**CC BY-NC-SA 4.0**). LongCat-Video/Avatar — MIT: https://github.com/meituan-longcat/LongCat-Video. **Проверьте актуальный текст по официальным ссылкам перед коммерческой дистрибуцией.**
- Реальность железа: наш RTX 5080 — **16 ГБ GDDR7** (https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/), не 32. Все рекомендации, где просят 32 ГБ (например, ноды LTX-2), к нам не относятся.

## 3.9. FFmpeg

См. §1.5 — там лежат все проверенные ссылки и наши фактические параметры кодирования. Отдельно стоит времени только одно: https://github.com/slhck/ffmpeg-encoding-course — если вы кодируете видео третий год и до сих пор копируете команды, полтора часа этого курса окупятся.

## 3.10. Git

Верифицированный ресёрч-пакет не содержит ссылок на материалы по git — подставлять непроверенные я не буду. Что есть:
- https://www.lezcave.com/renpy-tutorials/ — серия из 7 частей + бонус про git **в контексте Ren'Py-проекта**; единственный проверенный материал, где git объясняется на нашем предметном материале.
- Практика этого репозитория (ветки, коммиты, ревью, что коммитится, а что нет) — [Цикл разработки](04-development-workflow.md) и [Архитектура §2](02-architecture.md).
- `https://git-lfs.com` — адрес, который печатает `vn doctor` при отсутствии git-lfs (`doctor.py:77`); он взят из кода репозитория, не из ресёрча.

## 3.11. AI-assisted development

Это самый практически полезный раздел для того, как этот проект фактически разрабатывается. Подробности — [AI/vibe-coding](34-ai-vibe-coding.md) и [Правила для агента](35-agent-rules.md); здесь — источники.

**Официальная документация Claude Code:**
- https://code.claude.com/docs/en/best-practices — одна страница с наибольшей отдачей: цикл Explore → Plan → Implement → Commit, петли верификации, таблица «что писать и что не писать в CLAUDE.md», раздел про типовые провалы. Ключевая цитата, ради которой стоит зайти: *агент останавливается, когда работа «выглядит сделанной»; без проверки, которую он может запустить сам, петлёй верификации становитесь вы*.
- https://code.claude.com/docs/en/memory — порядок загрузки инструкций, `.claude/rules/` с glob-фронтматтером, лимит вложенности импортов, авто-память. **Цель — до 200 строк:** раздутый CLAUDE.md приводит к тому, что инструкции игнорируются.
- https://code.claude.com/docs/en/large-codebases — самая полезная страница для растущего репозитория: таблица «хочу X → используй Y», deny-правила на `Read`, скоупинг по каталогам, момент перехода на плагины.
- https://code.claude.com/docs/en/goal и https://code.claude.com/docs/en/hooks-guide — лестница верификации от «попроси прогнать тесты» до Stop-хука.
- https://code.claude.com/docs/en/code-review — фреш-контекстное ревью перед мержем.
- https://code.claude.com/docs/en/setup, https://code.claude.com/docs/en/data-usage, https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md.
**Инженерные разборы:**
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — словарь для разговора о контексте: «context rot», «минимальный набор высокосигнальных токенов», just-in-time-извлечение.
- https://www.anthropic.com/engineering/harness-design-long-running-apps — называет **bias самооценки** (агент уверенно хвалит собственную посредственную работу) и «context anxiety»; отсюда правило: генератор и оценщик должны быть разными.
- https://www.anthropic.com/engineering/building-c-compiler — что реально работает на 16 параллельных агентах; практический приём против дублирования: агент «берёт лок», записав файл-задачу.
- https://simonwillison.net/2025/Oct/7/vibe-engineering/ — 12 практик, которые делают AI-разработку выдерживающей продакшен; и https://simonwillison.net/2025/Mar/19/vibe-coding/ — определение дословно: *«написание софта с LLM без проверки написанного им кода»*. Если вы проверяете — это не vibe coding.
**Исследования (чтобы калибровать, а не вайбить):**
- https://metr.org/blog/2026-02-24-uplift-update/ — **читать до того, как цитировать знаменитые «19 %»**: METR сами повесили на старую страницу баннер «результаты устарели».
- https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ — исходное RCT; устойчивый вывод не в цифре, а в разрыве восприятия: разработчики ждали ускорения 24 %, после эксперимента считали, что ускорились на 20 %, фактически замедлились.
- https://dora.dev/research/2025/dora-report/ — AI как «великий усилитель»: положительная связь с пропускной способностью и **отрицательная — со стабильностью поставки**, если нет сильных автотестов, зрелого VCS и быстрой обратной связи. Это ровно аргумент за пункт 1 части 2.
- https://arxiv.org/abs/2509.14745 — 567 PR от Claude Code в 157 OSS-проектах: 83,8 % в итоге смержены, но **лишь 54,9 % смерженных вошли без доработки**; доработка концентрируется в багфиксах, документации и соблюдении проектных стандартов. Это и есть то, ради чего существует CLAUDE.md.
- https://arxiv.org/abs/2506.11022 — 400 сэмплов, 40 раундов «улучшений»: **+37,6 % критичных уязвимостей за пять итераций** без человеческой проверки между ними.
**Формат инструкций и решения:**
- https://agents.md/ — вендор-нейтральный аналог CLAUDE.md. Claude Code читает **CLAUDE.md, а не AGENTS.md**; если оба нужны — импорт (`@AGENTS.md` первой строкой), а не копия (симлинк на Windows требует админа или Developer Mode).
- https://adr.github.io/ — ADR как самый дешёвый машиночитаемый ответ на «почему это так и где оно лежит». У нас 14 ADR, см. часть 4. **Устаревший ADR активно вредит:** агент ему поверит и построит против системы, которую вы уже удалили.
- https://github.com/github/spec-kit + https://github.github.com/spec-kit/ — spec-driven разработка, если понадобится тяжёлая церемония на новую подсистему. Для одиночки чаще выигрывает лёгкий вариант из best-practices: дать интервьюировать себя, записать `SPEC.md`, выполнять в **свежей** сессии.

---

# Часть 4. Внутренние материалы проекта

Читать это дешевле, чем что-либо снаружи: оно про наш код.

## 4.1. Что где лежит

| Документ | Объём | Что это | Когда открывать |
|---|---|---|---|
| `../ARCHITECTURE.md` | 4180 строк | **нормативный целевой** документ; раздел 0 (G1–G24, C1–C24) — контракт | когда нужно понять *как должно быть*; **никогда** как описание построенного |
| `../adr/` | 10 решений + шаблон | принятые архитектурные решения с контекстом и последствиями | когда «почему это так?» |
| `../conventions/naming.md` | 30 строк | нормативные паттерны id, проверяются линтом | перед созданием любой сущности |
| `../conventions/folder-layout.md` | 39 строк | нормативная структура каталогов | перед созданием каталога |
| `../onboarding/` | 4 роли | writer / artist / localizer / tools-engineer | при входе в роль |
| `../pipeline/phase-0.md` | 206 строк | развёртывание production-окружения DAZ→ComfyUI→ffmpeg | при настройке машины под рендер |
| `../pipeline/design-brief-choices.md` | 132 строки | самодостаточный бриф дизайн-итерации экрана выбора | как образец постановки задачи дизайнеру/агенту |
| `../runbooks/pipeline-broken-at-night.md` | 24 строки | «сломалось ночью перед релизом» | в аварии |
| `../CHANGELOG.md` | 39 строк | пользовательские изменения по версиям | при подготовке релиза |
| `../licenses/THIRD-PARTY-NOTICES.md` | 53 строки | уведомления, которые едут вместе с игрой | при добавлении любой зависимости/шрифта/модели |
| `../../ci/README.md` | 7 строк | что делает CI | ⚠️ **устарел**: называет `.gitlab-ci.yml` «пайплайном», хотя настоящий CI — 4 workflow в `.github/workflows/` |
| `../../packs/README.md` | 7 строк | как устроен пак: одно дерево, зеркалящее `content/` + `manifest.yaml` | при заведении DLC; помечен «фаза 3», хотя `vn pack validate/build` уже есть |
| `../../game/fonts/README.md` | 22 строки | какие шрифты класть, откуда и под какой лицензией (OFL 1.1) | при смене шрифтов |
| `../../README.md` | 43 строки | точка входа в репозиторий | первым делом |
| `docs/handbook/` (этот каталог) | 39 файлов: карта `README.md` + 38 how-to | практический хендбук: «что мне конкретно сделать» | всегда, кроме случаев выше |

**Разделение ролей, которое важно не перепутать:** `ARCHITECTURE.md` отвечает на «как должно быть», ADR — «почему решили так», хендбук — «что я делаю руками прямо сейчас». Хендбук **не пересказывает** ARCHITECTURE.md, он на него ссылается.

## 4.2. Индекс ADR

Ни один ADR не имеет статуса «заменено». Десять приняты, один (0008) предложен и ждёт решения владельца.

| № | Заголовок | Суть одной строкой | Статус |
|---|---|---|---|
| 0001 | Принять ARCHITECTURE.md как нормативный фундамент | раздел 0 — контракт; менять норму можно только новым ADR со ссылкой на заменяемую | принято |
| 0002 | Схемы фазы 0 — валидируемое подмножество | реализуем минимальное ядро `chapter@1`/`scene@1`/`character@1`/`vars@1` с `additionalProperties: false`; при конфликте примеров ARCHITECTURE.md канон — профильный раздел | принято |
| 0003 | Init-шкала начинается с −999 | движок отверг приоритет −1000 (`renpy lint`); вся шкала C8 сдвинута, верхняя граница 999 — впритык | принято |
| 0004 | PNG-слои как открытый промежуточный формат; демо-сырцы временно в git | канон — дерево `assets_src/png/…`; PSD нарезается в ту же конвенцию; порог бинарей проверяет линт | принято |
| 0005 | Языковые пакеты с автодискавери и рантайм-реестр языков | язык = самоописывающийся пакет `loc/po/<code>/language.yaml`; списка языков нет нигде в коде | принято |
| 0006 | Production-конвейер DAZ→ComfyUI→ffmpeg, provenance и флейворы | зоны `assets_src/daz|png/cg|video_src`, трансформации `png2webp_cg@1`/`video2webm@1`, видео-пресет WebM/VP9, релизные флейворы | принято |
| 0007 | The Sims 4 как опциональный четвёртый источник | подключается паттерном VaM; **задел**, продакшен-контент на Sims 4 не производится | принято |
| 0008 | Лицензии AI-моделей для коммерческого 18+ контента | правовой статус модели — обязательная метадата (`commercial_use` в `comfyui_models@1`) | **предложено** — единственный непринятый |
| 0009 | UI-панели генерируются конвейером из деклараций | `content/ui/panels.yaml` → WebP → `define vn_frame_<id> = Frame(...)`; Ren'Py не рисует скругления на `Solid` | принято |
| 0010 | Галерея — декларации, два источника разблокировки | data-driven подсистема зеркально достижениям; **уточняет** прежнее решение раздела 6 ARCHITECTURE.md | принято |
| 0011 | В дистрибутив уходит метка получателя, а не сам patron-токен | `game/build_id.json` целиком уезжает игроку, поэтому вместо `patron_token` пишется `patron_tag` = `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex; схема бампнута `build_info@1` → `@2`, старая оставлена «устаревшей» для чтения артефактов до 0.1.5 | принято |

Шаблон нового ADR — `../adr/template.md`. Обязательная секция — «Затрагивает нормы: G…/C…», если ADR меняет норму раздела 0.

## 4.3. Где документации НЕТ (и это надо знать заранее)

Практические how-to существуют ровно для трёх областей: production-окружение, аварийный пайплайн, дизайн экрана выбора. Всё остальное описано только нормативно. Крупнейшие разрывы «код есть — документа нет»:

| Тема | Код | Документ |
|---|---|---|
| Content Compiler | IMPLEMENTED (`tools/vn/src/vn/content/compile.py`) | нет (одна строка в онбординге tools-инженера) |
| Достижения | IMPLEMENTED (`080_achievements.rpy`) | **нет ни ADR, ни doc-файла**; в ARCHITECTURE.md — одно упоминание как источника для loc-экстракции |
| Генерируемые UI-панели | IMPLEMENTED | только ADR-0009; в ARCHITECTURE.md — **ноль** упоминаний |
| Весь внешний 3D-конвейер (DAZ/VaM/Sims4/ComfyUI) | частично | только ADR-0006/0007; в ARCHITECTURE.md — **ноль** упоминаний DAZ, Comfy, Virt-a-Mate, Sims |
| GitHub Actions (4 workflow, 7 определений джоб) | IMPLEMENTED | нет ни документа, ни строки в CODEOWNERS |
| `docs/adr/engine-assumptions.md` | — | ARCHITECTURE.md:4137 требует этот файл; **его не существует**, допущения рассыпаны по ADR-0003 и ADR-0005 |

Этот хендбук существует ровно для того, чтобы закрыть эти разрывы. Перед тем как писать новый документ, проверьте, не ваш ли это файл из карты в `README.md` хендбука.

---

## Как изменить / Как расширить

**Добавить инструмент в часть 1** (то есть он реально появился на машине и участвует в сборке):
1. Убедитесь, что его находит `vn pipeline doctor` или `vn doctor`. Если нет — сначала патч в `../../tools/vn/src/vn/pipeline.py` или `doctor.py`, потом строка здесь. Инструмент, который не видит doctor, не является частью конвейера.
2. Впишите **фактическую** версию, полученную запуском, а не ожидаемую.
3. Обязательно заполните строку «Где используется» ссылками на файл:строку.
4. Разделите «что умеет» и «что подключено» — иначе через полгода кто-то будет искать несуществующий API-клиент.
5. Если инструмент влияет на поставляемый результат — добавьте запись в `../licenses/THIRD-PARTY-NOTICES.md`.

**Добавить ссылку в часть 3:** она должна (а) открываться, (б) иметь одну строку «зачем», (в) относиться к нашей задаче, а не к теме вообще. Ссылка на «10 лучших туториалов по X» удаляется без обсуждения.

**Обновить версии:** после апгрейда любого инструмента прогоните блок из раздела «Проверка» и обновите числа. Особенно `vn doctor`/`vn pipeline doctor` — они и есть источник истины для этого файла.

**Перенести рекомендацию из части 2 в часть 1:** только вместе с кодом. Пункт в части 2 без задачи в [Roadmap](37-roadmap.md) — это пожелание, а не план.

## Чего НЕ делать

- **Не добавляйте URL, которых нет в верифицированном источнике.** По этому файлу будут действовать человек и агент; битая ссылка стоит дороже, чем её отсутствие.
- **Не делайте юридических выводов о лицензиях.** Максимум — «вот адрес документа, вот пункт, который вас касается, проверьте актуальный текст перед коммерческой дистрибуцией». Особенно это касается EULA DAZ (пункт про AI-движки), EA content policy (paywall/Patreon) и non-commercial моделей (SUPIR, Sonic, FLUX-dev).
- **Не выдавайте `ARCHITECTURE.md` за описание построенного.** `vn validate`, `vn build --use-artifact`, `vn content lint --strict`, `game/assets/registry.json`, remote-cache в `vn bootstrap` — всё это в нормативном документе есть, а в коде нет.
- **Не считайте, что ComfyUI/DAZ/VaM/Sims4 «подключены»** потому, что про них есть ADR и они детектируются доктором. Вызова из `vn` нет ни у одного из четырёх.
- **Не апгрейдьте Ren'Py SDK «заодно».** Пин в `project.yaml:5` сверяется доктором, релизным гейтом и CI; апгрейд — отдельный PR с прогоном canary (G18).
- **Не ставьте DAZ Studio 4.24 на RTX 5080.** Iray в 4.x скомпилирован до Blackwell — получите тихий CPU-рендер и часы вместо минут.
- **Не берите essentials-сборку ffmpeg.** Нет `libsvtav1`, и версия в winget-пакете Essentials систематически отстаёт.
- **Не тащите NVFP4-веса на нашу связку.** У нас PyTorch cu128; NVFP4 без cu130 даёт **замедление** до 2× относительно fp8, а не ускорение.
- **Не правьте `game/generated/`, `game/assets/`, `game/tl/`** — перезапишет ближайшая сборка. Это относится и к «быстро поправить путь в сгенерированном файле, чтобы проверить ссылку».

## Проверка

```bash
# Окружение целиком — источник истины для части 1 этого файла
vn doctor                     # ожидаемо: 8 PASS, 0 FAIL
vn pipeline doctor            # ожидаемо: PASS по ffmpeg/GPU/ComfyUI/моделям/DAZ/дискам/SDK,
                              #           WARN по Virt-a-Mate и The Sims 4 (не установлены)

# Версии, которые указаны в таблицах выше
vn --version                                  # vn, version 0.1.0
python --version                              # 3.12.10
python -m pip show click PyYAML jsonschema blake3 Pillow psd-tools polib pytest | grep -E "^(Name|Version)"
git --version ; git lfs version               # 2.55.0.windows.3 ; git-lfs/3.7.1
ffmpeg -version | head -1                     # 8.1.2-full_build-www.gyan.dev

# Что этот файл описывает как работающее — работает
vn build                                      # build: OK
python -m pytest tools/vn/tests -q            # 253 passed
vn release validate --flavor public           # 16 PASS, exit 0
vn pipeline models                            # статус 10 записей манифеста
```

Если `vn pipeline doctor` перестал видеть инструмент, которого не двигали, — сначала проверьте переменные окружения (`RENPY_SDK`, `VN_COMFYUI`, `VN_FFMPEG`, `VN_FFPROBE`, `VN_VAM`, `VN_SIMS4`, `CIVITAI_API_KEY`) и помните: `setx` виден только новым процессам.

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/doctor.py` (какие инструменты и как проверяются), `../../tools/vn/src/vn/pipeline.py` (детекция ffmpeg/ComfyUI/DAZ/VaM/Sims4 + манифест моделей), `../../tools/vn/pyproject.toml` и `../../tools/vn.lock` (зависимости и пины), `../../project.yaml` (пин SDK, бюджеты, флейворы), `../../tools/comfyui-models.yaml`, `../../.gitattributes`, `../adr/0006-daz-comfyui-video-pipeline.md`, `../adr/0007-sims4-optional-source.md`, `../adr/0008-ai-model-licensing-for-commercial-adult-content.md`, `../pipeline/phase-0.md` |
| **Не трогать** | Ничего в коде из этого файла менять не нужно — он справочный. Не редактировать `../../tools/vn.lock` вручную (регенерация — `pip freeze` по зависимостям `vn-tools`, отдельным PR, G17). Не добавлять маски в `../../.gitattributes` без ADR. Не подставлять URL, которых нет в верифицированном источнике |
| **Зависимости (что ломается ниже по течению)** | Версии в этом файле должны совпадать с выводом `vn doctor` / `vn pipeline doctor` — иначе агент, читающий хендбук, будет строить планы на несуществующем окружении. Пин `project.yaml:5` (`renpy_sdk`) связан с `doctor.py:133-135`, `.github/workflows/ci.yml:13-14`, `.gitlab-ci.yml:10-11`; смена пина в одном месте без остальных даёт красный CI. Манифест `tools/comfyui-models.yaml` валидируется схемой `comfyui_models@1` — новое поле требует правки схемы |
| **Валидация** | `vn doctor` → `vn pipeline doctor` → `vn build` → `python -m pytest tools/vn/tests -q` → `vn release validate --flavor public` |
| **Частые ошибки** | 1) Считать, что ComfyUI/DAZ вызываются из `vn` — **нет**: только детекция и (для ComfyUI) скачивание моделей по манифесту. 2) Брать версии из ARCHITECTURE.md или из старых доков вместо запуска `vn doctor`. 3) Придумывать «официальные» URL по памяти вместо признания «проверенной ссылки нет». 4) Делать юридический вывод о лицензии модели или EULA вместо ссылки на документ. 5) Считать `renpy lint` в CI работающим гейтом — он без `--error-code`, то есть всегда зелёный (см. часть 2, пункт 1). 6) Путать версию тулинга (`vn 0.1.0`) с версией игры (`project.yaml: 0.1.4`) |
