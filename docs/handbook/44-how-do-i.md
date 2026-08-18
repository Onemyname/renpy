# 44. Как мне… — практический FAQ

> **Статус подсистемы:** справочник, а не подсистема. Каждая команда ниже проверена по `../../tools/vn/src/vn/cli.py` на текущем HEAD (`vn` 0.1.0, игра 0.1.5, Ren'Py 8.5.3.26051504): в CLI **20 групп/команд верхнего уровня и 68 листовых команд, из них 59 живых и 9 честных заглушек** (`exit 3`). Заглушки помечены в тексте отдельно — их вызов ничего не делает.
> **Отвечает на вопрос:** «Мне надо сделать конкретную вещь — какие файлы завести, какие команды выполнить, на чём я почти наверняка спотыкнусь».

Страница намеренно плоская: один вопрос — одна минимальная последовательность, ссылка на подробную главу и одна типичная ошибка. Подробностей здесь нет по замыслу; если ответ вызывает вопрос «а почему так» — идите по ссылке.

**Три правила, из которых следует почти всё остальное:**

1. Источник истины — `content/`, `packs/`, `assets_src/`, `loc/`, `game/framework/`. Всё в `game/generated/`, `game/assets/`, `game/tl/` — производное (§26).
2. После любой правки источника — `vn build`. Он делает lint → ассеты → компиляцию → `vn loc import` → бюджеты.
3. Команды и их флаги проверяются по `vn --help` и `cli.py`, а не по `docs/ARCHITECTURE.md` (там целевой норматив, часть команд не существует).

---

## Указатель

| Хочу | § | Основная команда |
|---|---|---|
| персонажа | [1](#1-как-добавить-персонажа) | `vn assets build` → `vn build` |
| сцену | [2](#2-как-добавить-сцену) | `vn scene new <ch> <slug>` |
| локацию | [3](#3-как-добавить-локацию) | `vn assets build` → `vn build` |
| CG | [4](#4-как-добавить-cg) | `vn assets build` → `vn build` |
| послойный шот | [5](#5-как-добавить-послойный-шот-shots1) | `vn assets build` → `vn build` |
| анимацию / видео | [6](#6-как-добавить-анимацию--видео) | `vn assets video build` |
| главу | [7](#7-как-добавить-главу) | `vn chapter new <slug>` |
| диалог | [8](#8-как-написать-диалог-и-почему-id-проставляет-vn-loc-keys) | `vn loc keys` |
| озвучку реплики | [9](#9-как-озвучить-реплику) | `vn voice manifest` → `vn voice import` |
| черновую озвучку без актёров | [9.1](#91-как-сгенерировать-tts-черновики) | `vn voice tts chNN` |
| переменную состояния | [10](#10-как-добавить-переменную-состояния) | `vn build` |
| достижение | [11](#11-как-добавить-достижение) | `vn build` |
| элемент галереи | [12](#12-как-добавить-элемент-галереи) | `vn build` |
| послойный шот в галерею | [12.1](#121-как-показать-послойный-шот-в-галерее) | `vn assets build` → `vn build` |
| трек музыки / эмбиенса | [13](#13-как-добавить-трек-музыки-или-эмбиенса) | `vn assets build` → `vn build` |
| новый язык | [14](#14-как-добавить-новый-язык) | `vn loc add <code>` |
| DLC-пак | [15](#15-как-добавить-dlc-пак) | `vn pack validate` → `vn pack build` |
| собрать Steam-версию | [16](#16-как-собрать-steam-версию) | `vn release steam --flavor` |
| протестировать Steam | [17](#17-как-протестировать-steam-интеграцию) | `pytest test_platform.py` |
| протестировать Deck | [18](#18-как-протестировать-на-steam-deck) | `RENPY_VARIANT=… vn test smoke` |
| протестировать Big Picture | [19](#19-как-протестировать-big-picture) | `RENPY_VARIANT=steam_big_picture vn test smoke` |
| релизную сборку | [20](#20-как-сделать-релизную-сборку) | `vn release build --flavor` |
| загрузить билд в Steam | [21](#21-как-загрузить-билд-в-steam) | `steamcmd +run_app_build` |
| собрать APK/AAB | [21.1](#211-как-собрать-apk-или-aab) | `vn release android build` |
| проверить масштаб конвейера | [21.2](#212-как-прогнать-корпус-масштаба) | `vn test corpus` |
| откатить релиз | [22](#22-как-откатить-релиз) | Steamworks UI + `git revert` |
| отладить краш | [23](#23-как-отладить-краш) | `crash/*.txt`, `log.txt` |
| найти сейвы | [24](#24-где-хранятся-сейвы) | `%APPDATA%/RenPy/vn-1755000000` |
| найти собранные ассеты | [25](#25-где-генерируемые-ассеты) | `game/assets/` |
| знать, что нельзя править | [26](#26-какие-файлы-генерируются-и-их-нельзя-править-руками) | таблица зон |

---

# Контент

## 1. Как добавить персонажа

**Последовательность**

```bash
# 1. Декларация (id ОБЯЗАН совпадать с именем папки)
mkdir -p content/characters/aiko
$EDITOR content/characters/aiko/character.yaml     # schema: character@1

# 2. Мастера позы: base обязателен, слои — по группам
mkdir -p assets_src/art/characters/aiko/a/{outfits,faces}
#   assets_src/art/characters/aiko/a/base.png            <- обязателен
#   assets_src/art/characters/aiko/a/outfits/school.png
#   assets_src/art/characters/aiko/a/faces/neutral.png
#   (опционально: overlays/*.png, side/*.png — портреты say-окна)

# 3. Сборка
vn assets build          # spr/**: референс без суффикса + @2
vn build                 # layeredimage aiko в generated/registry/images.gen.rpy
```

Минимальная декларация — по образцу `content/characters/mira/character.yaml`: `id`, `name`, `color`, `voice_tag`, `canvas: [W, H]`, `matrix.{poses, outfits, emotions, required}`. Имя персонажа переводить в `content/ui/strings.yaml` **не нужно**: `name` уезжает в PO отдельной записью `msgctxt "char:aiko"` (`tools/vn/src/vn/loc/po.py:244`).

**Подробнее:** [10-characters.md](10-characters.md), правила мастеров — [16-assets.md](16-assets.md), [22-rendering.md](22-rendering.md).

**Типичные ошибки**

- `vn char new` — **заглушка** (`cli.py:1097`, `exit 3`): каталог и YAML создаются руками.
- Слои разного размера: `canvas` из `character.yaml` (а если его нет — холст `base`) обязателен для **каждого** слоя позы, `layeredimage` кладёт всё в (0,0). Сообщение: «холст …x… != …x… — слои одной позы обязаны лежать на ОДНОМ холсте» (`pipeline.py:225-229`).
- Спрайт без прозрачности: класс `spr` имеет `alpha: require`, невырезанный фон — ошибка сборки, а не предупреждение.
- Файл, положенный не в `base`/`outfits`/`faces`/`overlays`/`side`, не исчезает молча: `_orphan_masters` даёт ошибку «файл в зоне мастеров не подобран» — и она валит **всю** сборку ассетов, а не только эту ветку.

## 2. Как добавить сцену

**Последовательность**

```bash
vn scene new ch01 rooftop_night     # -> s040_rooftop_night.scene.{yaml,rpy}, шаг номера 10
$EDITOR content/chapters/ch01_awakening/scenes/s040_rooftop_night.scene.yaml
#   location: rooftop/day  participants: [mira]  exits: {...}
$EDITOR content/chapters/ch01_awakening/scenes/s040_rooftop_night.scene.rpy
$EDITOR content/chapters/ch01_awakening/chapter.yaml    # scene_order: [..., s040]  <- РУКАМИ
vn loc keys                          # проставит say-id новым репликам
vn build && vn play
```

Сцена — **пара файлов**: `.scene.yaml` (декларация: фон, музыка, эмбиенс, участники, exits) + `.scene.rpy` (авторский текст в `label <full_id>__body`). Переход наружу — `return "<exit_id>"`, цель прописана в `exits:`.

**Подробнее:** [12-scenes.md](12-scenes.md).

**Типичные ошибки**

- `vn scene new` **не трогает** `chapter.yaml`: без правки `scene_order` сцена окажется недостижимой. В `draft`-главе это warning (`lint.py:305`), в `playtest`/`release` — ошибка.
- `jump ch01_s040` между сценами вместо `return "<exit>"`: пропускаются `vn.checkpoint`, очистка слоя спрайтов, фон и треки, а call-стек остаётся невыровненным.
- Заглушка для объявленной, но не написанной цели — `vn scene stub ch01 s050`, а не «пустой .rpy руками».

## 3. Как добавить локацию

**Последовательность**

```bash
mkdir -p content/locations/rooftop_night
$EDITOR content/locations/rooftop_night/location.yaml
#   schema: location@1 / id: rooftop_night / title_key: meta.locations.rooftop_night.title
#   backgrounds: {night: assets/bg/rooftop_night/night.webp}
mkdir -p assets_src/art/backgrounds/rooftop_night
#   положить night.png (или .jpg/.webp/.tif) — мастер 3840x2160
$EDITOR content/ui/strings.yaml          # meta.locations.rooftop_night.title
vn assets build && vn build
```

В `scene.yaml` локация указывается как `location: rooftop_night/night`.

**Подробнее:** [11-locations.md](11-locations.md).

**Типичные ошибки**

- Мастер меньше 4K: у классов `bg`/`cg`/`shot` в `project.yaml` стоит `source_min: [3840, 2160]`, меньший файл — **ошибка** сборки. Уменьшает конвейер сам (`day.webp` 1920×1080 + `day@2.webp` 3840×2160).
- `@2` в ссылке: в `location.yaml` пишется **референсное** имя без суффикса — иначе движок не подберёт крупный вариант и на 1080p игрок получит 4K-текстуру. Схема `location@1` это оговаривает явно.
- Пропорции: расхождение с `render.screen` больше `aspect_tolerance` (0.01) — ошибка «пропорции расходятся с экраном».
- Отсутствующий `meta.locations.*` ключ в `strings.yaml` **не** ловится ни линтом, ни компилятором (в отличие от `title_key` главы, где это ошибка) — проверяйте глазами.

## 4. Как добавить CG

**Последовательность**

```bash
mkdir -p assets_src/art/cg/ch01
#   положить kiss.png / kiss.webp / kiss.jpg — мастер 3840x2160, БЕЗ альфы
vn assets build            # -> game/assets/cg/ch01/kiss.webp, kiss@2.webp, kiss.thumb.webp
vn build                   # -> image cg ch01 kiss = "assets/cg/ch01/kiss.webp"
# в сцене:
#   scene cg ch01 kiss with dissolve
```

Отдельной декларации у CG нет: логический id получается из пути (`cg/ch01/kiss`), имя образа — `cg ch01 kiss`. Чтобы CG появился в галерее — §12.

**Подробнее:** [16-assets.md](16-assets.md), [15-gallery.md](15-gallery.md).

**Типичные ошибки**

- Альфа у CG: класс `cg` объявлен `alpha: forbid`, альфа-канал будет **отброшен** с предупреждением — если картинка на него рассчитывала, вы увидите чёрный/белый фон.
- Показ CG сам засчитывает разблокировку через штатный `persistent._seen_images` — писать `vn_gal.unlock(...)` в сцене не надо и нечем.
- Переименование выпущенного CG без записи в `content/renames.yaml: assets` — ошибка линта: у игроков кадр останется закрытым (`lint.py:416`).

## 5. Как добавить послойный шот (shots@1)

Шот — полнокадровая композиция: `env`-подложка + вырезанные слои, наряд выбирается переменной.

**Последовательность**

```bash
# 1. Мастера: ЖЁСТКАЯ глубина art/shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>].<ext>
mkdir -p assets_src/art/shots/ch01/s040/night
#   env.jpg              <- подложка, БЕЗ альфы, задаёт холст шота
#   mira__school.png     <- слой с альфой, на ТОМ ЖЕ холсте
#   mira__casual.png

# 2. Декларация шотов сцены
$EDITOR content/chapters/ch01_awakening/shots/s040.shots.yaml
#   schema: shots@1 / scene: s040
#   shots: {night: {layers: {env: {}, mira: {variants: [school, casual], var: g.mira_outfit}},
#                   order: [env, mira]}}

# 3. Переменная гардероба ОБЯЗАНА быть в Variable Registry
$EDITOR content/variables/wardrobe.vars.yaml

vn assets build && vn build
# в сцене:  scene shot_ch01_s040 night with dissolve
```

Эмитится `layeredimage shot_ch01_s040` с эксклюзивной группой `shot` и группой на каждый слой; вариант по умолчанию — `<layer>_auto` через `ConditionSwitch` по переменной. Живой пример на диске: `content/chapters/ch01_awakening/shots/s030.shots.yaml` → `game/generated/registry/images.gen.rpy`.

**Подробнее:** [12-scenes.md](12-scenes.md) (ссылки в сценах), [16-assets.md](16-assets.md) (мастера).

**Типичные ошибки**

- `var` не объявлена в Variable Registry — **ошибка даже в `draft`-главе**: «гардероб не попадёт в сейв (G5)» (`compile.py:990-996`). Это единственная проверка шотов, не смягчаемая статусом главы.
- `order` не перечисляет каждый слой ровно один раз — ошибка: z-порядок эмитится буквально, пропущенный слой молча исчез бы из кадра.
- `variants` у `env` — ошибка: «вариативная среда = отдельный шот».
- Липкость: выбранный вариант слоя — обычный липкий атрибут тега, поэтому `scene shot_ch01_s040 night` **сохранит** ранее выбранный `mira_casual`. Полный сброс — только через `_auto` или явный вариант.
- Явный `mira_casual` и `mira_auto` — атрибуты одной группы: явный вытесняет `ConditionSwitch`, и переменная перестаёт влиять на кадр до следующего показа с `_auto`.

## 6. Как добавить анимацию / видео

**Последовательность**

```bash
# Вариант А: готовый видео-мастер
mkdir -p assets_src/video_src/ch01
cp ~/render/wind.mp4 assets_src/video_src/ch01/wind.mp4
$EDITOR assets_src/video_src/ch01/wind.video.yaml   # schema: video_src@1 / loop: true

# Вариант Б: PNG-секвенция -> мастер
vn assets video seq ~/render/frames assets_src/video_src/ch01/wind.mp4 --fps 24 --crf 12

vn assets video validate assets_src/video_src/ch01/wind.mp4   # необязательно
vn assets video build          # только видео-ветка: VP9/WebM + meta + постер-кадр
vn build                       # -> image mov ch01 wind = Movie(play=..., loop=True, image=<постер>)
vn assets video inspect game/assets/mov/ch01/wind.webm
```

Видео **обязано** лежать в группе: `video_src/<group>/<name>.<ext>`, файл прямо в `video_src/` — ошибка. Постер-кадр (`<name>.poster.webp`) конвейер извлекает сам и подставляет в `Movie(image=…)` и в сетку галереи, поэтому ручное `thumb:` у `kind: movie` больше не обязательно.

**Подробнее:** [21-video-generation.md](21-video-generation.md).

**Типичные ошибки**

- Нет ffmpeg/ffprobe: «есть видео-мастера, но ffmpeg/ffprobe не найдены» — и это **ошибка discovery**, то есть `vn assets build` не собирает вообще ничего, включая картинки. Проверка окружения — `vn pipeline doctor`.
- `vn assets video build` — **частичная** сборка: схема sidecar на этом пути не применяется (битый `.video.yaml` поймает только `vn content lint` / `vn build`), сироты чужих ветвей не убираются, а записи чужих ветвей переносятся из прошлого манифеста. На чистом чекауте она оставит манифест без записей о картинках.
- 4K-варианты видео выключены: `render.classes.mov.variants: [1]`. Включаются сменой на `[1, 2]`, энкод дорогой.

## 7. Как добавить главу

**Последовательность**

```bash
vn chapter new awakening_two        # -> content/chapters/ch02_awakening_two/
                                    #    chapter.yaml, vars.yaml, scenes/s010_intro.scene.{yaml,rpy}
$EDITOR content/ui/strings.yaml     # meta.chapters.ch02.title  <- ОБЯЗАТЕЛЬНО
$EDITOR CODEOWNERS                  # /content/chapters/ch02_awakening_two/  @writer
# дальше — сцены (§2), диалог (§8), озвучка (§9)
vn loc keys && vn loc extract
vn build && vn play
```

Каталог главы может содержать пять вещей: `chapter.yaml`, `vars.yaml`, `scenes/`, `shots/` (§5) и `voice/` (§9).

**Подробнее:** [09-chapters.md](09-chapters.md).

**Типичные ошибки**

- Забыть `meta.chapters.chNN.title` в `strings.yaml` — это **ошибка** компилятора («покажется сырой ключ»), в отличие от ключей галереи и достижений, где только warning.
- `status: draft` понижает до warning три класса проверок (`scene_order`, `entry_scene`, достижимость/exits). Зелёный прогон draft-главы не является приёмкой — перед `playtest` перечитайте вывод `vn content lint`.
- Главы паков (`packs/*/chapters/`) **не попадают** ни в `ci/release-manifest.json`, ни в сгенерированный блок changelog (`snapshot_content` смотрит только `content/chapters/`) — описание пишется руками.

## 8. Как написать диалог (и почему id проставляет `vn loc keys`)

**Последовательность**

```bash
$EDITOR content/chapters/ch01_awakening/scenes/s010_intro.scene.rpy   # пишете текст БЕЗ id
vn loc keys          # допишет `id ch01_s010_00NN` и `$ vn_menu = "..."`, обновит loc/ledger/chNN.json
vn loc extract       # прокатит новые/изменённые строки в loc/po/*/
vn build && vn play
```

**Почему id ставит команда, а не вы.** Идентификатор реплики — ключ перевода на всю жизнь строки. `vn loc keys` разбирает файл **парсером Ren'Py из пиннованного SDK** (G24), нумерует say/menu в порядке AST и пишет ledger; ledger — источник PO-экстракции. Руками это делать нельзя по трём причинам: (1) номер должен быть уникальным и монотонным в пределах сцены, (2) тот же проход вставляет маркер `$ vn_menu = "<id>"` перед каждым `menu`, (3) после правки команда **перечитывает файлы парсером заново** и при любом расхождении откатывает изменения.

Правя существующую реплику, меняйте **только текст в кавычках**: `id` сохраняет уже сделанные переводы. Смена id = осиротевшая PO-запись и потерянный перевод.

**Подробнее:** [13-dialogue.md](13-dialogue.md), round-trip — [14-localization.md](14-localization.md).

**Типичные ошибки**

- Забыть `vn loc keys`: локально всё зелено (линтер про ledger не знает), а CI падает на шаге `vn loc keys --check`: «есть строки без id или устаревший ledger». Новая реплика без id никогда не попадёт в PO и останется на русском во всех языках.
- Считать откат `vn loc keys` абсолютной гарантией: восстановление идёт **из памяти процесса** (`keys.py:198-219`). Ctrl+C или kill по таймауту оставит `.scene.rpy` полуправленными — восстанавливать из git.
- Ждать, что `vn content compile --check` поймает проблему с диалогом: он проверяет только свежесть генерата. Диагноз ошибок — всегда `vn build`.

## 9. Как озвучить реплику

**Последовательность**

```bash
# 1. Лист записи для актёра (CSV: line_id, who, text, prev, next, status)
vn voice manifest ch01 --lang ru -o /tmp/ch01-ru.csv
#   опционально: --char mira

# 2. Дубли названы по line_id: ch01_s010_0001.wav и т.д.
vn voice import ~/takes/ch01-ru --lang ru          # боевые дубли -> status: final
vn voice import ~/takes/ch01-ru --lang ru --draft  # черновики/TTS -> status: draft

# 3. Транскод и сборка
vn assets build      # voice_opus: loudnorm I=-19 -> game/assets/voice/ru/ch01/<line_id>.opus
vn build             # инжектирует `voice vn.voice_path("<line_id>")` перед каждой покрытой репликой
vn voice validate --report
```

Мастера живут в `assets_src/voice/<lang>/<chNN>/<line_id>.<wav|flac|ogg|opus>`, манифест — в `content/chapters/chNN_*/voice/<lang>.voice.yaml`.

**Почему не `config.auto_voice`.** У штатного авто-войса имя файла производно от метки и текста, поэтому правка реплики молча отвязала бы записанный дубль. Компилятор вместо этого вставляет `voice vn.voice_path("<say-id>")` в копию сцены — привязка идёт к стабильному id. Смотрите живой `game/generated/scenes/ch01/ch01_s020.gen.rpy`: строки `voice …` есть в генерате и отсутствуют в авторском файле — это норма, а не испорченный генерат.

**Подробнее:** [23-audio.md](23-audio.md) §8, [09-chapters.md](09-chapters.md).

**Типичные ошибки**

- Озвучить половину главы: непокрытые реплики языка, который для этой главы уже начали озвучивать, — это **FAIL релизного гейта** («дыры покрытия»), потому что игрок слышит обрыв. Драфты — только WARN. Сейчас в репозитории 14 draft-дублей демо-главы, поэтому зелёный `vn release validate` штатно содержит одну жёлтую строку.
- Ждать ошибку вместо тишины: `vn.voice_path()` возвращает `""`, если файла нет ни в одном языке (voice-пак не установлен), а `voice`-оператор с falsy-именем — no-op. Тишина вместо реплики — это не баг конвейера.
- Не ждать актёров, чтобы услышать главу: черновую озвучку делает `vn voice tts chNN` (§9.1) — она закрывает FAIL «дыры покрытия» и оставляет WARN «драфты».
- Импорт атомарен: любая ошибка имён/ledger — и **ни один** файл не скопирован. Половинчатого импорта не бывает.

## 9.1. Как сгенерировать TTS-черновики

**Последовательность**

```bash
# 1. Что-нибудь одно должно быть в PATH (или указано в VN_PIPER / VN_SAY):
#      piper — основной бэкенд (кроссплатформенный, голоса моделями .onnx)
#      say   — дев-фолбэк, только macOS, ставить нечего
vn voice tts ch01                       # непокрытые реплики исходного языка
vn voice tts ch01 --char mira           # только один персонаж
vn voice tts ch01 --lang en             # дубляж: текст берётся из PO этого языка
vn voice tts ch01 --backend piper --voice ru_RU-irina-medium --rate 1.1
vn voice tts ch01 --regenerate-drafts   # перезаписать черновики (final не тронет)

# 2. Транскод и сборка — как у боевых дублей
vn assets build && vn build
vn voice validate --report
```

Мастер пишется сразу `.opus` (Opus 96k, −19 LUFS) в `assets_src/voice/<lang>/<chNN>/`, строка в манифесте получает `status: draft`. Модель голоса piper скачивается **только** по `--allow-download` (в `.vncache/piper-voices`).

**Подробнее:** [23-audio.md](23-audio.md) §8.1.

**Типичные ошибки**

- Ждать, что синтез заменит запись: `status: draft` — это **WARN релизного гейта** до самого конца. Замена — `vn voice import` с боевыми дублями (он ставит `final`, и TTS их больше не трогает никогда).
- Звать `--lang en` до перевода: текст черновика дубляжа берётся из PO, и реплика без перевода даёт warning и пропускается. Порядок — `vn loc keys` → `extract` → перевод → `import` → и только потом `tts`.
- Ставить `--rate` за пределами 0,5…2,0 — команда откажется: за этими границами синтез перестаёт быть разборчивым, а черновик нужен для вычитки.
- Считать, что повтор что-то испортит: без непокрытых реплик команда даже не ищет бэкенд и выходит зелёной.

## 10. Как добавить переменную состояния

**Последовательность**

```bash
# Глобальная (store g)                 -> content/variables/core.vars.yaml
# Только для главы (store chNN)        -> content/chapters/chNN_*/vars.yaml
# Межсейвовая (store persistent)       -> content/variables/settings.vars.yaml, имя с vn_
$EDITOR content/variables/core.vars.yaml
#   vars:
#     trust_mira: {type: int, default: 0, range: [0, 100], doc: "…", since: 2}
vn build      # -> default g.trust_mira = 0 в game/generated/state/defaults.gen.rpy
```

Типы — только простые: `str|int|float|bool|list|dict`. `default: null` допустим и означает «не выбрано». `since` — номер `save_schema`, с которой переменная существует.

**Подробнее:** [07-backend.md](07-backend.md), [09-chapters.md](09-chapters.md) §8.

**Типичные ошибки**

- Присвоить в сцене переменную, которой нет в Registry: она не попадёт в снапшот сейва, и rollback вернёт другое состояние. Ссылки из `exits.when`, `unlock.var`, `trigger.var` и `shots@1: var` сверяются с Registry на сборке.
- Менять смысл существующей переменной без бампа `project.yaml: save_schema` и миграции в `content/migrations/` — старые сейвы прочитаются молча и неправильно. Номер миграции резервируется в `content/migrations/registry.yaml` тем же PR.
- `store: persistent` в `vars.yaml` **главы** линтер не увидит (он фильтрует по `content/chapters/`), а компилятор — увидит. Настройки объявляйте в `content/variables/`.

## 11. Как добавить достижение

**Последовательность**

```bash
$EDITOR content/achievements/core.achievements.yaml
#   my_ach:
#     name_key: ach.my_ach.name
#     desc_key: ach.my_ach.desc
#     trigger: {scene: ch01_s030}          # ровно ОДИН из scene | beat | var
$EDITOR content/ui/strings.yaml            # ach.my_ach.name / .desc
vn build

# посмотреть глазами, как она выглядит игроку (прохождение этот экран не открывает)
VN_AUTOPILOT_SCREENS=achievements vn test smoke --picks 0,0
open .vncache/smoke/screen_achievements.png
```

Якоря стабильны и переживают правку/перевод текста, поэтому ачивку можно добавить в уже написанную главу, не трогая её `.rpy`. **Экран достижений правок не требует** — он читает реестр и не знает ни одного id.

**Подробнее:** [15-gallery.md](15-gallery.md) (тот же механизм якорей), Steam-сторона — [39-platforms.md](39-platforms.md) §4.

**Типичные ошибки**

- Якорь `beat: <name>` мёртв без ручного вызова: компилятор `vn.beat(...)` **не эмитит** (проверено: в `game/generated/**` ни одного вхождения). Нужен явный `$ vn.beat("name")` в авторском `.rpy`.
- `trigger: {var: …}` срабатывает не мгновенно: `check()` вызывается только из `vn.checkpoint` / `vn.beat` / `vn.chapter_done`, поэтому присваивание в середине сцены выдаст ачивку лишь на следующей границе.
- Забытый `name_key`/`desc_key` в `strings.yaml` — только **warning**, в UI появится сырой ключ.
- В Steamworks API Name ачивки обязан **побуквенно** совпадать с id из YAML — маппингов нет намеренно (`ci/steam/README.md`).
- `hidden: true` прячет **и название, и описание** до получения (на экране будет «???»). Это удобно для сюжетных спойлеров, но проверить внешний вид такой ачивки на боевых декларациях сегодня нельзя — обе объявленные видимы и к концу прогона получены ([15-gallery.md](15-gallery.md)).
- Прогресса («10 из 30») у ачивки нет: поля `progress` нет ни в схеме, ни в эмиттере, ни в сторе. Не обещайте его игроку в описании.

## 12. Как добавить элемент галереи

**Последовательность**

```bash
$EDITOR content/gallery/core.gallery.yaml
#   items:
#     cg_ch01_kiss:
#       category: cg          # категория объявлена там же, в categories:
#       kind: image           # image | movie | shot (шот — см. §12.1)
#       asset: cg/ch01/kiss   # ЛОГИЧЕСКИЙ id существующего ассета, без assets/ и без расширения
#       variants: [cg/ch01/kiss_night]
#       title_key: gal.cg_ch01_kiss.title
#       chapter: ch01
#       order: 10
#       unlock: {seen_image: true}       # либо scene | beat | var+equals | chapter_done | always
$EDITOR content/ui/strings.yaml          # gal.cg_ch01_kiss.title / .desc
vn build
```

**Два независимых источника разблокировки.** `seen_image` держит движок (`persistent._seen_images`), всё остальное — `persistent.vn_gallery_unlocked`. Переименование ассета не стирает игроку открытый кадр: `renames.yaml: assets` → `image_name_history` → рантайм засчитывает исторические имена.

**Подробнее:** [15-gallery.md](15-gallery.md).

**Типичные ошибки**

- `asset:` с префиксом `assets/` или с расширением — id логический (`cg/ch01/kiss`), путь и превью конвейер выводит сам.
- Ждать `thumb:` у видео: постер-кадр подставляется автоматически, если `game/assets/mov/**/<name>.poster.webp` существует.
- Пытаться положить в галерею **спрайт**: `asset` для плоских элементов ограничен паттерном `^(cg|bg|mov)/…`. Послойные шоты теперь можно — но через `kind: shot` и ссылку на шот (§12.1), а не как `cg/…`.
- var-якорь срабатывает с задержкой до следующей границы (см. §11).

## 12.1. Как показать послойный шот в галерее

**Последовательность**

```bash
# Слои и декларация шота — как в §5 (shots@1). Дальше:
vn assets build
ls game/assets/shots/ch01/s030/sunset.thumb.webp   # композитное превью склеил конвейер

$EDITOR content/gallery/core.gallery.yaml
#   shot_ch01_s030_sunset:
#     category: cg
#     kind: shot                            # НЕ image
#     asset: shots/ch01/s030/sunset         # ссылка на ШОТ, а не на файл
#     title_key: gal.shot_ch01_s030_sunset.title
#     unlock: {seen_image: true}
#     # variants и thumb НЕ указывать: виды кадра берутся из shots@1,
#     # превью — из трансформации shot_thumb
$EDITOR content/ui/strings.yaml             # gal.shot_ch01_s030_sunset.title / .desc
vn build
```

В сетке игрок видит композит дефолтного кадра, в просмотрщике — **живой layeredimage**: кнопка «Вариант» (и `↑`/`↓` с клавиатуры) листает комбинации вариантов слоёв, первая = ровно то, что было в игре.

**Подробнее:** [15-gallery.md](15-gallery.md) («Послойные шоты в галерее»), [16-assets.md](16-assets.md) §13.7, [ADR-0013](../adr/0013-layered-shots.md).

**Типичные ошибки**

- Указать `variants:` — **ошибка компиляции**: у шота виды кадра уже объявлены в `shots@1`, второй источник истины запрещён.
- Сослаться на шот с `kind: image` (или на файл с `kind: shot`) — тоже ошибка компиляции, с текстом, что именно перепутано.
- Забыть показать кадр в сцене: у шота нет файла, и `unlock: {seen_image: true}` засчитывается только фактом `scene shot_chNN_sNNN <шот>` в сценарии.
- Ждать, что переименование шота поймает реестр id: `built_asset_ids` перечисляет файлы, поэтому в `id_registry@1` попадают слои, а составной id шота — нет.

## 13. Как добавить трек музыки или эмбиенса

**Последовательность**

```bash
# 1. Мастер — ТОЛЬКО .ogg, плоско в зоне своего kind
cp theme.ogg assets_src/audio_stems/bgm/school_theme.ogg
cp wind.ogg  assets_src/audio_stems/amb/rooftop_wind.ogg

# 2. Реестр логических id (три файла, по kind)
$EDITOR content/audio/bgm.yaml      # tracks: {school_theme: {file: assets/audio/bgm/school_theme.ogg}}
$EDITOR content/audio/amb.yaml      # tracks: {rooftop_wind: {...}}
# content/audio/sfx.yaml — для звуков

vn assets build && vn build
# в scene.yaml:  music: bgm/school_theme
#                ambient: amb/rooftop_wind
```

`music` и `ambient` — **разные каналы**: `ambient` регистрируется отдельно (`045_audio.rpy:13`, `mixer=music, loop=True, tight=True`) и играет **одновременно** с музыкой, но громкость у них общая (один слайдер «Музыка»).

**Подробнее:** [23-audio.md](23-audio.md), [11-locations.md](11-locations.md).

**Типичные ошибки**

- Не-`.ogg` в `audio_stems/` — ошибка «в audio_stems только .ogg».
- Одинаковый id в разных `kind`: уникальность проверяется **глобально** между bgm/amb/sfx, иначе `define audio.<id>` перезаписался бы молча.
- Класть sfx на канал `music` (занял бы его и оборвал музыку) или bgm на `sound` (не зациклится) — запрещено `CHANNEL_KINDS` (`scenes.py:73`).
- Писать свой дакинг под голос: используется штатный `config.emphasize_audio_channels/_volume/_time` (0.6 / 0.5 c). Своя математика громкостей будет драться с движком.
- `loop:` в `audio@1` эмиттер игнорирует; `loop_start:` и `volume:` — применяются.

---

# Языки и паки

## 14. Как добавить новый язык

**Последовательность**

```bash
vn loc add ja --name 日本語        # создаст loc/po/ja/{language.yaml,ch01.po,ch90.po,common.po}
# перевести loc/po/ja/*.po (Poedit и т.п.) — правится ТОЛЬКО эта зона
# для своей письменности — шрифты в своём пакете:
#   game/fonts/NotoSansJP-Regular.ttf  (через git lfs!)
#   loc/po/ja/language.yaml: fonts: {text: fonts/NotoSansJP-Regular.ttf, ...}
vn loc extract        # подтянуть новые строки, переводы сохраняются
vn loc import         # PO -> game/tl/ja/ (входит в vn build)
vn loc report         # покрытие; сейчас de/en/pseudo — 136/136
vn build && RENPY_VARIANT= vn play
```

Наличие каталога с `language.yaml` = язык существует; ни в каких конфигах он не регистрируется (ADR-0005). Порог релиза — `loc/loc.yaml: release_coverage_min` (0.98).

**Подробнее:** [14-localization.md](14-localization.md).

**Типичные ошибки**

- Пер-языковой шрифт «не применился» без единой ошибки: если файла нет в `game/`, переопределение роли **не эмитится**, выдаётся только warning импорта, и рантайм остаётся на базовом шрифте. Для CJK это тофу вместо текста.
- Шрифт приехал LFS-указателем: релизный гейт даёт **FAIL** («шрифты UI: N/M материализованы»), потому что чекаут без `lfs: true` однажды уже уехал в сборку. Лечение — `git lfs install && git lfs pull`.
- Верить `vn loc report` как гейту: он всегда `exit 0` и печатает один глобальный total для всех языков. Настоящий порог — только в `vn release validate`.
- Забыть `vn build` перед `vn release validate`: synthetic-признак читается из `game/tl/<lang>/language.json`, а не из `loc/po`, поэтому `pseudo` без сборки оценится как боевой язык.

## 15. Как добавить DLC-пак

**Последовательность**

```bash
mkdir -p packs/ep_winter/chapters
$EDITOR packs/ep_winter/manifest.yaml
#   schema: pack_manifest@1 / id: ep_winter (== имени папки) / kind: dlc | voice_pack | mod
#   version: 1.0.0 / title_key: meta.packs.ep_winter.title
#   api_level: {min: 1, below: 2} / requires: {core: ">=0.1.0 <1"}
#   steam_dlc_appid: 1234570        # опционально: гейт владения под Steam
$EDITOR content/ui/strings.yaml     # meta.packs.ep_winter.title
# главы пака — зеркало content/: packs/ep_winter/chapters/ch91_winter/...
$EDITOR project.yaml                # flavors.<f>.packs: [..., ep_winter]

vn pack validate                    # схема, api_level против фасада vn.*, структура
vn build
vn pack build ep_winter             # -> build/packs/ep_winter.zip (манифест + генерат его глав)
```

Принадлежность паку определяется **расположением**: поля `pack:` в `chapter.yaml` не существует.

**Подробнее:** [30-packs-and-dlc.md](30-packs-and-dlc.md), Steam-сторона — [39-platforms.md](39-platforms.md) §5.

**Типичные ошибки**

- Отключать пак переименованием каталога: сборка упадёт на сверке `id` с именем папки. Каталог надо **вынести** из `packs/`.
- `vn pack build` до `vn build`: если главы объявлены, а их генерата нет, команда честно падает («сначала vn build»). Пак-контейнер без глав (например `nsfw`) даёт warning и архив из одного манифеста — это норма.
- Ждать, что владение проверяется в dev: `owned() == False` возможно **только** под живым Steam с реальным DLC. Ни `vn play`, ни `vn test smoke`, ни pytest этой ветки не видят — регрессия «карточка главы пропала у всех» ловится только ручным прогоном.
- Забыть, что скрипты пака грузятся **всегда** (G9): гейт логический, а не защита от распаковки.
- Ждать, что депот пака можно объявить в `project.yaml`: `platform.steam.depots` в схеме допускает только `windows`/`linux`/`mac` при `additionalProperties: false` — номер DLC-депота сегодня положить некуда (`steam_dlc_appid` живёт только в манифесте пака).

---

# Steam и релиз

## 16. Как собрать Steam-версию

Steam — не фундамент, а один из способов распространения: тот же дистрибутив становится Steam-сборкой за счёт `steam_api`-библиотеки рядом с исполняемым файлом.

**Последовательность**

```bash
# 0. Разово на build-машине: редистрибутивы Valve из Steamworks SDK -> в SDK
#    $RENPY_SDK/lib/py3-windows-x86_64/steam_api64.dll
#    $RENPY_SDK/lib/py3-linux-x86_64/libsteam_api.so
#    $RENPY_SDK/lib/py3-mac-universal/libsteam_api.dylib      (в git НЕ кладутся — лицензия Valve)

# 1. Данные в project.yaml — ДВЕ независимые правки
$EDITOR project.yaml
#   platform: {steam: {appid: 1234560,
#                      depots: {windows: 1234561, linux: 1234562, mac: 1234563}}}
vn build            # -> game/generated/platform.gen.rpy: config.steam_appid, VN_STEAM_DLC

# 2. Дистрибутивы всех платформ депотов
vn release build --flavor public --package win --package linux --package mac

# 3. Раскладка депотов + VDF
vn release steam --flavor public            # [--branch beta]
#   -> build/steam/app_build_public.vdf, build/steam/content/public/<platform>/
```

**Подробнее:** [40-steamworks.md](40-steamworks.md) (приложение, депоты, SteamPipe), [39-platforms.md](39-platforms.md) (рантайм), `ci/steam/README.md`.

**Типичные ошибки**

- `appid: null` — рабочее состояние (standalone), но `depots` в `project.yaml` **отсутствует иначе**: его там физически нет. Включение Steam — два редактирования, и ошибка про депоты вылезет только вторым запуском, уже после заполненного appid.
- **Не ждать от `--package linux` зипа.** Ren'Py 8.5.3 объявляет linux как `tar.bz2` (`$RENPY_SDK/renpy/common/00build.rpy:424`; win — zip, mac — app-zip + dmg). Раскладка депотов это знает и распаковывает оба формата, `.dmg` игнорирует намеренно; ожидаются только платформы с объявленным депотом, так что собирать все три ради одной не нужно. Но всё, что вы делаете рядом руками (распаковка, копирование на устройство), считайте от фактического формата. Steam-проверок в релизном гейте нет ни одной — `vn release steam` вы запускаете и читаете сами.
- Ждать, что `vn release steam` заливает билд: она **только** готовит VDF и контент. Аплоад — §21.
- Ждать, что `--branch beta` создаст ветку: `SetLive` в несуществующую ветку не публикует ничего — `betas` создаётся руками в Steamworks.
- Pre-release-версии невозможны: схема `project@1` требует `version` строго `^\d+\.\d+\.\d+$`.

## 17. Как протестировать Steam-интеграцию

**Что реально проверяется без Steam**

```bash
python -m pytest tools/vn/tests/test_platform.py -q      # 10 тестов, включая гард
#   гард: слово Steam / _renpysteam запрещено вне game/framework/00_core/035_platform.rpy
export RENPY_SDK=<путь к 8.5.3>
python -m pytest tools/vn/tests/test_engine_compat.py -q  # контракт штатного стека 00steam.rpy
vn build && vn play                                       # standalone-ветка: no-op провайдеры
```

`035_platform.rpy` — единственная точка касания платформы (8 публичных функций + провайдер владения). Steam работает через **штатный** стек движка (`00steam.rpy` / `00achievement.rpy`, движковый `init -1499`), сторонних биндингов в проекте нет.

**Отладочные рычаги движка** (нигде больше в хендбуке не описаны): `steam_init()` выходит без инициализации при `not config.enable_steam` и при наличии переменной окружения `RENPY_NO_STEAM` (`00steam.rpy:1022-1025`). Это единственный способ прогнать сборку с библиотекой рядом как standalone — например, чтобы сравнить ветви ownership-гейта.

**Что проверяется только на живом Steam:** `owned() == False`, оверлей, `dlc_installed`, реальные ачивки, Timeline.

**Подробнее:** [39-platforms.md](39-platforms.md) §1, §4; приёмка — [43-steam-qa.md](43-steam-qa.md).

**Типичные ошибки**

- Дублировать движок внутри `035_platform.rpy`: движок сам пишет/удаляет `steam_appid.txt`, ставит позицию тостов, вставляет варианты `steam_deck`/`steam_big_picture`, включает экранную клавиатуру Deck для `input()`, регистрирует `SteamBackend` и гоняет callbacks. Гард-тест единственной точки касания от этого не защищает.
- Считать `vn test smoke` под `RENPY_VARIANT` проверкой Steam: варианты и масштаб он даёт, Steam-инициализацию и `dlc_installed` — нет.
- Проверять `steam_libs_status` через `vn doctor`: она вызывается **только** из `vn release steam` (`cli.py:1839`) и из тестов, и даёт warning, а не ошибку.

## 18. Как протестировать на Steam Deck

**Вёрстка — локально**

```bash
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0
open .vncache/smoke/            # смотреть ГЛАЗАМИ: движковый lint визуальных поломок не видит
```

`vn test smoke` наследует окружение процесса, поэтому `RENPY_VARIANT` доезжает до движка: вставляются варианты, включается авто-масштаб интерфейса 1.4 и фуллскрин по умолчанию (`options.rpy:15-17` через `vn_platform.controller_first()`).

**Пад, оверлей и Steam API — только на живом Deck.** Порядка «как доставить сборку на Deck» в репозитории нет; фактические шаги: собрать нативный linux-пакет (`vn release build --flavor public --package linux` → `*-linux.tar.bz2`), распаковать на Deck в desktop mode, добавить как non-Steam game либо выложить в бета-ветку и установить через клиент. Обязательный прогон перед `setlive default` — требование `ci/steam/README.md`.

**На что смотреть:** кегли (масштаб 1.4), safe-area, экранная клавиатура для `input()`, доступность каждого действия без мыши.

**Подробнее:** [41-steam-deck.md](41-steam-deck.md) (процедура целиком), [39-platforms.md](39-platforms.md) §7.

**Типичные ошибки**

- Выкладывать в release-ветку, не прогнав на живом Deck.
- Искать «калибровку геймпада» в настройках: движок даёт `GamepadCalibrate()` / `GamepadExists()`, но проект заменил штатный `preferences` своим `core_screens.rpy`, и вкладки Gamepad в нём **нет** — откалибровать или переназначить пад игрок не может.
- Ждать, что копия экранов под Deck где-то есть: вёрстка одна и та же, различается только масштаб и `overscan_pad`.

## 19. Как протестировать Big Picture

```bash
RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0
open .vncache/smoke/
```

Проверять ровно одно: прижатые к кромке оверлеи (quick menu, контролы просмотрщика, вотермарка) ушли от края на `gui.overscan_pad = 48` (`game/framework/20_ui/scale.rpy:42`). `controller_first()` истинен и здесь, поэтому фуллскрин и крупный масштаб включаются так же, как на Deck.

**Подробнее:** [41-steam-deck.md](41-steam-deck.md), [39-platforms.md](39-platforms.md) §7, токены — [06-frontend.md](06-frontend.md).

**Типичная ошибка:** менять крупный масштаб (`scale.rpy:19`) и не перепроверить 9-patch панели — при масштабировании рамке нужно минимум `2*Borders`, иначе панель сплющится, и ни один автотест этого не заметит.

## 20. Как сделать релизную сборку

**Последовательность**

```bash
vn release changelog                    # обновит ci/release-manifest.json (+ блок в CHANGELOG, если менялись главы/сцены)
$EDITOR docs/CHANGELOG.md               # 2-5 предложений для игрока — ПОСЛЕ генератора
$EDITOR project.yaml                    # version: 0.1.6   (патч — фиксы, НОВАЯ ГЛАВА = minor)
vn release validate --flavor public     # локально, до тега
vn release validate --flavor patron
git commit -m "release: 0.1.6 — <итог одной строкой>"
git tag v0.1.6 && git push --follow-tags        # -> .github/workflows/release.yml
```

Гейт — **21 проверка**; на текущем чекауте `--flavor public` печатает 20 строк: молчит одна — реестр лицензий (деклараций ноль). Молчать могут три (покрытие переводов, озвучка, лицензии) — у них нет безусловной `else`-ветки; здесь озвучка не молчит, а даёт WARN. Молчащая проверка — не пропущенная.

**Реальный вывод на HEAD (`vn release validate --flavor public`, exit 0):** 20 строк, из них 18 PASS и два WARN — `озвучка: 14 черновых дублей (draft) — ru: ch01_s010_0001` и `зрелость контента: ни одна глава ещё не доведена до status=release (ch01) — флейвор с early_content=false собирается, но гейт станет строгим с первой release-главой`. `--flavor patron` — 21 строка, один WARN, тоже exit 0. **WARN релиз не валит** — `ok` становится `False` только на FAIL. Держите в голове вторую строку: гейт зрелости самоактивирующийся, и `draft`-главы станут FAIL в тот прогон, где появится первая `status: release` ([29 §5.1](29-build-and-release.md#maturity-gate-rule)). «Все строки PASS» не эталон.

**Подробнее:** [29-build-and-release.md](29-build-and-release.md).

**Типичные ошибки**

- Тег без бампа версии: `release.yml:47-54` сверяет `${GITHUB_REF_NAME#v}` с `project.yaml: version` и падает первым шагом. Обратное тоже верно.
- Взять `v0.1.5`: тег уже выпущен, а поверх него лежат невыпущенные коммиты при неизменной `version: 0.1.5`. Следующий релиз обязан начинаться с бампа до 0.1.6.
- Править `docs/CHANGELOG.md` до `vn release changelog`: генератор вставит свой блок **выше** вашего текста.
- Считать, что проверка «генерат свеж» внутри `vn release build` что-то проверяет: команда сама вызывает `vn build` до гейта, поэтому в этом контексте проверка тавтологична.
- Собирать оба флейвора и надеяться на изоляцию: `build/rpyc-cache/<version>/` общий для флейворов, и кто собрался последним — тот и перезаписал носитель statement-имён, от которого зависит совместимость сейвов (G6).

## 21. Как загрузить билд в Steam

```bash
# 1. Подготовить (см. §16)
vn release build --flavor public --package win --package linux --package mac
vn release steam --flavor public [--branch beta]

# 2. Аплоад — steamcmd, credentials ВНЕ репозитория
steamcmd +login <build-account> +run_app_build build/steam/app_build_public.vdf +quit
```

Шаблон VDF подставляет `ContentRoot "."` и `BuildOutput "output"` **относительными** путями (`release.py:231-232`), поэтому SteamPipe создаст `build/steam/output/` и будет искать `content/<flavor>/<platform>/*` относительно самого VDF, а не текущего каталога.

**Подробнее:** [40-steamworks.md](40-steamworks.md), `ci/steam/README.md`, [39-platforms.md](39-platforms.md) §3.

**Типичные ошибки**

- Ждать, что первый вход пройдёт без Steam Guard: для CI нужен отдельный build-аккаунт с сохранённым sentry-файлом.
- Ждать, что `--branch beta` опубликует в ветку, которой нет в Steamworks: ветку `betas` создают руками, `default` переключают в UI после проверки.
- Класть `steam_api`-библиотеки в git — запрещено лицензией Valve; они живут в SDK на build-машине. Без них дистрибутив соберётся, но будет standalone: `vn release steam` предупредит, а не остановится.
- Искать Steam-проверки в релизном гейте: их нет ни одной (`vn release validate` про Steam не знает).

## 21.1. Как собрать APK или AAB

**Последовательность**

```bash
vn release android status          # что мешает: RAPT, Android SDK, JDK 21, ключи, android.json
#   -> код 1 и перечень штатных шагов лаунчера. CLI-пути установки тулчейна
#      у Ren'Py НЕТ: RAPT ставит апдейтер лаунчера, SDK — кнопка Install SDK,
#      ключи — Generate Keys, конфиг приложения — Configure
"$RENPY_SDK/renpy.sh"              # ^ выполнить эти четыре шага в лаунчере, раздел Android

vn release android preflight --bundle   # предпосылки: потолок канала 2 ГБ, лимит 500 МБ
                                        # на файл в Play-бандле, мобильный кэш образов,
                                        # утечка *.keystore в git, иконки и пресплэш
vn release android build [--bundle] [--install] [--launch] [--timeout 3600]
                                        # status -> vn build -> launcher android_build
```

**Что делает `build`:** проверяет тулчейн **до** долгой сборки, затем зовёт штатную команду лаунчера `renpy.sh <SDK>/launcher android_build <проект> --destination …`. Лог gradle/RAPT идёт живьём — молчащая сборка неотличима от зависшей.

**Подробнее:** [39-platforms.md](39-platforms.md) §2.1.

**Типичные ошибки**

- Искать `vn package --package android`: мобильный канал — **другая команда лаунчера**, со своим тулчейном и своими потолками, поэтому он живёт в `vn release android`, а не в `vn package`.
- Коммитить `android.keystore` / `bundle.keystore`: ключ в истории git = скомпрометированный ключ навсегда, а потеря = невозможность обновить опубликованное приложение. `preflight` называет это блокером; бэкап — **вне** репозитория. (В `.gitignore` их пока нет — добавьте `*.keystore` до генерации ключей.)
- Ждать `@N`-вариантов на телефоне: `build.classify("**@[2-9].*", "windows linux mac")` их отсекает, движок берёт безсуффиксный референс — это осознанная экономия веса при потолке 2 ГБ.
- Считать `preflight` измерением веса пакета: он оценивает `game/` + накладные ~150 МБ **сверху**; фактический вес APK узнаётся только первой реальной сборкой, которой ещё не было.

## 21.2. Как прогнать корпус масштаба

**Последовательность**

```bash
export RENPY_SDK=...          # прогон поднимает движок (build-bridge разбирает сцены корпуса)
vn test corpus --scenes 2000 --images 2000 --lines 8 --vars 201 --dest /tmp/corp
vn test corpus --scenes 600 --images 400 --videos 2 --lines 8 --vars 100 --dest /tmp/corp
                              # ровно то, что гоняет ночная джоба corpus
vn test corpus --scenes 100 --images 100 --keep --dest /tmp/corp   # оставить дерево для разбора
```

Печатается таблица «метрика × масштаб»: время и cpu каждой стадии (`assets build → lint → compile → повторный compile → модель памяти`), пики RSS, объём каждой зоны, генерат на сцену, доли бюджетов G19 и худшая сцена модели памяти. Прогон красный, если упала стадия, если повторная компиляция что-то перезаписала или превышен бюджет.

**Подробнее:** [32-performance-and-scalability.md](32-performance-and-scalability.md) §7.5.

**Типичные ошибки**

- Не задать `--dest`: каталог по умолчанию `.vncache/corpus` совпадает с каталогом скриншотов `vn save corpus --add`, и после сейв-корпуса прогон откажется работать («не пуст и не является корпусом»).
- Мерить корпусом вес ассетов: его render-профиль 64×48, 8 000 мастеров = 3 МБ. Сопоставимы `game/generated`, времена стадий и «сцена в экранах», а не мегабайты `game/assets`.
- Считать корпус проверкой игры: он **не запускает** её — ни cold start, ни RSS движка, ни `chapter_select` на 99 главах им не измеряются.
- Гонять без `RENPY_SDK`: стадия компиляции требует движок, прогон честно упадёт.

## 22. Как откатить релиз

Три разные вещи, у которых разная обратимость.

**Откатывается легко — выкладка в Steam.** Билды в Steamworks не удаляются: на странице Builds выбирается предыдущий билд и переключается `SetLive` на нужную ветку. Из репозитория это не делается — только в Steamworks UI. Наш `--branch` умеет лишь выставить `setlive` в VDF при **новой** выкладке.

**Откатывается с оговоркой — код и контент.**

```bash
git revert <sha>            # откат = ещё один коммит; история линейная, merge-коммитов нет
$EDITOR project.yaml        # version: 0.1.7   <- НОВЫЙ номер, старый тег переиспользовать нельзя
vn release validate --flavor public
git commit -m "release: 0.1.7 — откат <что>" && git tag v0.1.7 && git push --follow-tags
```

Тег `v0.1.6` уже занят, а гейт требует точного совпадения тега с `version` — поэтому «перевыпустить ту же версию» невозможно по конструкции. Откат тулчейна — `git revert` бампа `tools/vn.lock`: все семь мест установки в пяти пайплайнах ставят лок первым шагом (G17).

**НЕ откатывается — `save_schema`.** Понизить `project.yaml: save_schema` нельзя: сейв, записанный на схеме 2, при загрузке в сборке со схемой 1 **не мигрируется вниз**. `label after_load` показывает `ui.flow.save_from_newer` («Сохранение сделано в более новой версии игры»), делает `block_rollback()` и `full_restart()` (`020_state.rpy:87-94`). То есть откат релиза, который бампнул `save_schema`, ломает сейвы всем, кто успел поиграть. Единственный путь вперёд — новая версия с миграцией, а не понижение схемы.

Так же необратимы: **выпущенные id** (append-only, `content/renames.yaml` + `content/registry/id_registry.json`) и **statement-имена** в `build/rpyc-cache/`.

**Подробнее:** [29-build-and-release.md](29-build-and-release.md), [07-backend.md](07-backend.md) (сейвы и миграции), [39-platforms.md](39-platforms.md) §3.

**Типичная ошибка:** удалить «плохую» главу вместо `status: draft` — id сцен уже выпущены, и у игроков с сейвом внутри неё будет `ScriptError`. Для этого и существуют shim-метки: сцена из `id_registry.json`, которой нет в сборке, получает метку с `vn_unavailable_reason = "missing_content"` и уходит на экран «сцена недоступна».

---

# Диагностика и зоны

## 23. Как отладить краш

**Порядок**

```bash
# 1. Отчёт в savedir (переживает перезапуск, храним 10 последних)
#    <savedir>/crash/crash-YYYYMMDD-HHMMSS.txt  — build, flavor, version, renpy,
#    breadcrumbs (до 40 последних авторских меток) и полный traceback
ls -t ~/Library/RenPy/vn-1755000000/crash/ | head    # macOS; пути по ОС — §24

# 2. Лог текущего запуска (ПЕРЕЗАПИСЫВАЕТСЯ на каждом старте)
grep "\[vn\]" log.txt              # строки надстройки, включая
                                   #   [vn] unhandled exception: <Тип: сообщение>
cat errors.txt                     # ошибка скрипта: игра не стартовала
cat traceback.txt                  # падение в рантайме

# 3. Воспроизвести
vn test smoke --picks 0,0          # автопилот + скриншоты в .vncache/smoke/
```

**В игре:** Shift+O — консоль, Shift+D — dev-меню движка, Shift+J — прыжок в любую сцену из реестра (`90_debug/020_jump_menu.rpy`), Shift+R — перезагрузка. Вся зона `game/framework/90_debug/**` вырезается из дистрибутива (`options.rpy:31`).

**Флаги движка** (`renpy.sh <root> …`): `--trace 1|2` (журнал в `trace.txt`), `--warp file:line`, `--safe-mode`, `--compile`, `--savedir DIR`. Переменные окружения: `RENPY_LOG_TO_STDOUT`, `RENPY_DEBUG_IMAGE_CACHE`, `RENPY_DEBUG_SOUND`, `RENPY_RAW_TRACEBACKS`.

**Подробнее:** [28-debugging.md](28-debugging.md), симптомы — [36-troubleshooting.md](36-troubleshooting.md).

**Типичные ошибки**

- **Флага `--debug` у Ren'Py нет** — ни у движка, ни у `vn`. Аналог «подробнее» — `--trace 1` и `RENPY_LOG_TO_STDOUT`.
- Считать `log.txt` журналом: файл открывается в режиме `w` и обнуляется каждым старом. Если игра уже перезапускалась, единственный источник — отчёт из `crash/`. Просить у игрока надо именно его.
- Диагностировать по `errors.txt` в корне, не глядя на дату: файл легко бывает устаревшим.
- Заводить второй `config.exception_handler`: поле одно, побеждает последнее присваивание по init-порядку. Единственность стережёт `tools/vn/tests/test_crash_handler.py`.
- Править `game/generated/…gen.rpy`, где «видно ошибку»: чинить надо в `content/`, в `tools/vn/src/vn/content/` или в `game/framework/` (§26).

## 24. Где хранятся сейвы

`config.save_directory = "vn-1755000000"` (`game/options.rpy:7`). Разрешение пути — `path_to_saves()` в `$RENPY_SDK/renpy.py:95-202`:

| ОС | Путь |
|---|---|
| Windows | `%APPDATA%\RenPy\vn-1755000000\` (если `APPDATA` нет — `~\RenPy\vn-1755000000\`) |
| macOS | `~/Library/RenPy/vn-1755000000/` |
| Linux / прочее | `~/.renpy/vn-1755000000/` |
| Android | `<ANDROID_PUBLIC>/saves` (или старый public/private, что писабельно) |
| iOS | каталог Documents приложения |

Внутри: `<page>-<slot>.save` (слоты), `persistent` (файл **без расширения**), `crash/` (§23).

**Переопределения, в порядке приоритета:** каталог `Ren'Py Data/` в любом каталоге **выше** `renpy_base` (то есть выше SDK при dev-запуске) → переменная окружения `RENPY_PATH_TO_SAVES` → аргумент `--savedir DIR`. Последним пользуется `vn save corpus`: он гоняет фикстуры в изолированном `.vncache/corpus-savedir/`.

**Подробнее:** [07-backend.md](07-backend.md), Steam Cloud — `ci/steam/README.md`.

**Типичные ошибки**

- Искать dev-сейвы в `game/saves/`: туда они попадают **только** если `config.save_directory` пуст — а он у нас задан. `game/saves/` есть в `.gitignore:6` по историческим причинам.
- Настраивая Steam Auto-Cloud, забыть про `persistent`: он без расширения и маской `*.save` не покрывается — нужно отдельное правило.
- Верить `ci/steam/README.md` в части Windows-пути: там написано `%LOCALAPPDATA%/RenPy/…`, а SDK 8.5.3 резолвит **`%APPDATA%`** (`renpy.py:194-196`). Правильно — `APPDATA`.
- Менять `config.save_directory`: это смена личности игры для ОС и для Steam Cloud — все существующие сейвы «исчезнут».

## 25. Где генерируемые ассеты

| Что | Где | Кто создал |
|---|---|---|
| Отгружаемые ассеты | `game/assets/**` | `vn assets build` |
| Кэш трансформаций | `.vncache/assets/**` + `.vncache/assets-manifest.json` | `vn assets build` |
| Скриншоты smoke | `.vncache/smoke/**` | `vn test smoke` |
| PSD-нарезка (staging) | `.vncache/psd_png/characters/**` | конвейер PSD |

Раскладка `game/assets/`: `bg/`, `cg/`, `spr/`, `shots/`, `mov/`, `ui/`, `voice/<lang>/<chNN>/`, `audio/{bgm,amb,sfx}/`. У классов `bg`, `cg`, `spr`, `shot` отгружаются **два** варианта: референсный без суффикса и `@2`; у `bg` и `cg` дополнительно `.thumb.webp`, у видео — `.poster.webp`. Ссылаться в контенте и декларациях надо **только** на референсное имя — крупный вариант подбирает движок.

```bash
vn assets validate                 # сырцы + свежесть + ссылки контента
vn assets memory --top 5           # во что обходится худшая сцена (гейт vn build!)
vn assets cache --gc --dry-run     # что удалит сборка мусора кэша
vn test oversample --scale 2       # ДВИЖОК подтверждает, что @2 реально подхватывается
```

**Подробнее:** [16-assets.md](16-assets.md), [22-rendering.md](22-rendering.md).

**Типичные ошибки**

- Править файл в `game/assets/`: если он есть в манифесте — вернётся к сгенерированным байтам на следующей сборке; если его в манифесте нет — **не удалится никогда** (точечная очистка ходит по разнице манифестов) и поедет в каждый дистрибутив. И `vn build --check` не заметит ни того, ни другого: он сверяет `src_hash`/трансформацию/профиль, а не байты выхода.
- `vn assets cache --gc` без манифеста: `live`-множество строится **из** манифеста, поэтому без него `--gc` вынесет весь кэш. Порядок восстановления — сначала `vn assets build`, только потом `--gc`.
- Оценивать качество по `vn dev`: он собирает профиль `draft` (WebP q50, видео `crf 42` ≤720p). Перед пушем — `vn assets build` без флагов.
- Забыть, что бюджет памяти сцены — **гейт**: `_check_budgets` гоняет `assets.memory.analyze` и в `vn build`, и в `vn build --check`, и валит сборку сообщением «бюджет памяти сцены превышен (project.yaml: render.image_cache_mb)». Один лишний полупрозрачный пиксель в углу растягивает bbox на весь холст и двигает стоимость сцены.

## 26. Какие файлы генерируются и их нельзя править руками

**Признак генерата** — шапка в каждом файле:

```
# AUTO-GENERATED by vn content compile (vn 0.1.0)
# source: content/…  blake3:…
# НЕ РЕДАКТИРОВАТЬ. Правки перезапишутся. Меняйте источник.
```

**Полный перечень зон** (все — вне git, `.gitignore:2-21`):

| Зона | Кто создаёт | Что внутри сейчас |
|---|---|---|
| `game/generated/**` | `vn build` / `vn content compile` | **21** `*.gen.rpy` + `manifest.json` (36 входов → 21 выход) |
| ↳ `registry/` | | `achievements`, `audio`, `chapters`, `characters`, `gallery`, `images`, `menus`, `overrides`, `scenes`, `ui_frames` |
| ↳ `scenes/chNN/` | | обвязка + копия авторского `.rpy` с инжектированными `voice …` |
| ↳ `state/` | | `defaults`, `migrations`, `snapshot` |
| ↳ `screens/` | | `chapter_select` |
| ↳ корень | | `version.gen.rpy`, **`render.gen.rpy`** (ADR-0012), **`platform.gen.rpy`** (ADR-0014) |
| ↳ `qa/` | `vn test smoke` | `autopilot.gen.rpy`, вырезается из дистрибутива |
| `game/assets/**` | `vn assets build` | см. §25 |
| `game/tl/**` | `vn loc import` (внутри `vn build`) | `translate`-блоки, `language.json` |
| `game/cache/`, `game/saves/` | движок | байткод, сейвы |
| `game/build_id.json` | `vn release build` | живёт только на время `distribute` |
| `game/THIRD-PARTY-NOTICES.md` | `vn release build` | копия из `docs/licenses/`, удаляется в `finally` |
| `*.rpyc`, `*.rpymc`, `*.rpyb` | движок | байткод скриптов |
| `.vncache/**` | тулинг | кэш трансформаций, анализа, smoke, corpus-savedir |
| `build/**` | `vn package` / `release` / `pack` | `dist/`, `rpyc-cache/`, `steam/`, `packs/` |

**Единственное исключение — `ci/fixtures/rpyc-line/**`:** негативное правило `!ci/fixtures/rpyc-line/**` (`.gitignore:14`) держит в git **52** `.rpyc` — линию statement-имён для сейв-корпуса (G6). Их нельзя удалять, «чистить» и пересобирать руками: ими управляют `_rpyc_line_restore` / `_rpyc_line_snapshot` (`cli.py:1354`, `cli.py:1375`), меняются они только через `vn save corpus --add`.

**Что произойдёт, если всё-таки поправить**

1. **Файл есть в манифесте** → компилятор сравнивает выход побайтово и перезаписывает только при отличии, то есть ваша правка исчезнет на ближайшей сборке (`compile.py:1187-1198`).
2. **До сборки** → `vn build --check` / `vn content compile --check` объявят генерат stale и **упадут** (в CI это шаг «Свежесть генерата»). Тонкость: `version.gen.rpy` сравнивается с вырезанным git-sha, иначе `--check` краснел бы после каждого коммита.
3. **Рядом остаётся `.rpyc` прошлой версии** до следующей сборки — движок может исполнять его, а не ваш текст.
4. **В git это не попадёт**: зоны в `.gitignore`, единственный способ — `git add -f`, и pre-commit-хука, который бы это отклонил, в проекте **нет** (NOT IMPLEMENTED).

Ошибку, найденную в `game/generated/scenes/ch01/ch01_s020.gen.rpy`, чинят в `content/`, в `tools/vn/src/vn/content/compile.py` (или `scenes.py` / `images.py`) либо в `game/framework/` — и только там.

**Подробнее:** [08-content-pipeline.md](08-content-pipeline.md), [04-development-workflow.md](04-development-workflow.md) §8.

---

## Чего НЕ делать

- **Не изобретать команды.** Их нет: `vn validate`, `vn build --use-artifact <sha>`, `vn content lint --strict`, `vn test perf`, `vn bootstrap --role`, `vn release build --channel`. Ответ будет usage error (`exit 2`), а не «не реализовано».
- **Не путать два класса «нет команды».** `exit 3` («появится в фазе N») — честная заглушка: `vn migrate`, `vn shell`, `vn char new|validate|sheet`, `vn save migrate`, `vn test replay|screens|paths` — девять штук, состав закреплён тестом `test_cli.py`. `exit 2` — команды не существует вовсе. `vn voice tts` из этого списка ушла: она реализована (§9.1).
- **Не считать зелёный `vn build` доказательством настроенного окружения** — тёплый `.vncache/analyze-*.json` пропускает сборку без SDK. Доказательство — `vn doctor` с exit 0.
- **Не менять `id`** сцены, реплики, ассета или элемента галереи «для порядка»: say-id держит переводы, scene-id — метку, from-имя в сейвах и якоря, логический id ассета — открытые игроку CG, id элемента галереи — ключ в `persistent.vn_gallery_unlocked`.
- **Не считать `docs/ARCHITECTURE.md` описанием построенного** — это целевой норматив. Источник истины по командам — `cli.py`.
- **Не доверять номерам строк в этом хендбуке буквально.** `cli.py` (2117 строк) и `release.py` правятся чаще всего, вставка блока в середину сдвигает сотню ссылок. Ищите по имени функции; номер — подсказка.

## Проверка

```bash
export RENPY_SDK="<путь к renpy-8.5.3-sdk>"       # в bash — обязательно

vn doctor                                  # 8 галок, exit 0
vn content lint                            # lint: OK (0 предупреждений)
vn build                                   # build: OK
vn build --check                           # ничего не пишет
vn loc keys --check
vn loc report                              # de/en/pseudo — 136/136 (100%), fuzzy 0
vn voice validate --report
vn assets memory                           # память: OK
vn test oversample --scale 2               # oversample: OK
(cd tools/vn && python -m pytest -q)       # 373 passed
vn release validate --flavor public        # 20 строк, 0 FAIL, 2 WARN (зрелость контента, драфты озвучки), exit 0
vn release validate --flavor patron        # 21 строка, 0 FAIL, 1 WARN — норма
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/cli.py` (единственный источник истины по командам и флагам), `../../project.yaml`, `../../tools/schemas/` (39 схем), соответствующую страницу хендбука из указателя выше |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `game/build_id.json`, `*.rpyc`, `.vncache/**`, `build/**` — производные зоны (§26); `ci/fixtures/rpyc-line/**` — линия statement-имён (G6), только через `vn save corpus`; `loc/ledger/*.json` — только через `vn loc keys` |
| **Зависимости** | `assets_src/` → `vn assets build` → `game/assets/` → `vn build` (реестр образов зависит от собранных ассетов) → `game/generated/` → `vn play` / `vn test smoke` / `vn package` / `vn release build`. Правка авторского `.rpy` → `vn loc keys` → `loc/ledger/` → `vn loc extract` → `loc/po/` → `vn loc import` → `game/tl/`. Правка `project.yaml: save_schema` → миграция в `content/migrations/` + запись в `registry.yaml` |
| **Валидация** | `vn doctor && vn content lint && vn build && vn content compile --check && (cd tools/vn && python -m pytest -q)`; для рантайма/сейвов дополнительно `vn test smoke --picks 0,0` и `vn save corpus`; для релизного пути `vn release validate --flavor public` |
| **Частые ошибки** | 1) правка генерата вместо источника (§26); 2) выдуманные флаги — их нет, `exit 2`; 3) забытый `export RENPY_SDK` в bash-вызове; 4) забытый `vn loc keys` после правки реплик — локально зелено, CI красный; 5) `@2` в ссылке на ассет вместо референсного имени; 6) переменная шота/галереи/exits вне Variable Registry; 7) `vn release steam` считается пройденной поставкой — раскладку депотов она делает (включая linux-`tar.bz2`), но в репозитории нет `appid`/`depots`, аплоад ручной, живого прогона не было (§16); 8) ожидание, что WARN в релизном гейте означает поломку; 9) `vn release android build` считается проверенным путём — ни одного APK/AAB ещё не собрано, тулчейн ставится только лаунчером (§21.1) |

---

Соседние файлы: [03-getting-started.md](03-getting-started.md) — первые 30 минут; [04-development-workflow.md](04-development-workflow.md) — цикл, git и CI; [08-content-pipeline.md](08-content-pipeline.md) — что во что превращается; [25-custom-engine.md](25-custom-engine.md) — устройство CLI `vn`; [36-troubleshooting.md](36-troubleshooting.md) — справочник симптомов; [39-platforms.md](39-platforms.md) — Steam / Deck / Big Picture.
