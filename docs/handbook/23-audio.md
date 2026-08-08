# 23. Аудио

> **Статус подсистемы:** PARTIALLY IMPLEMENTED. Декларации, кодоген и ветка сборки `copy_audio` работают: зона источника приведена к нормативной `assets_src/audio_stems/{bgm,amb,sfx}/`. Но в репозитории **ноль звуковых файлов**, `content/audio/*.yaml` пусты (`tracks: {}`), озвучка (`vn voice`) — заглушка фазы 2, нормализация громкости NOT IMPLEMENTED.
> **Отвечает на вопрос:** «Как в игре появляется музыка и звук, что из этого уже работает, и что конкретно сделать, чтобы добавить первый трек».

Аудио-контур размазан по четырём местам: декларации `content/audio/{bgm,sfx}.yaml` (схема `audio@1`), эмиттер `_emit_audio` в Content Compiler, ветка `copy_audio` в ассет-конвейере и поле `music:` в `*.scene.yaml`. Голос — отдельный контур (`vn voice`, voice-паки), которого не существует. Общая механика ассетов — [Ассеты](16-assets.md), общий поток данных — [Сквозной конвейер](08-content-pipeline.md).

## Быстрый ответ

```bash
# Что есть сейчас — проверьте сами, это займёт 10 секунд:
cat content/audio/bgm.yaml            # → tracks: {}
cat game/generated/registry/audio.gen.rpy   # → "# Треки не объявлены"
ls assets_src/audio_stems/            # → bgm/ amb/ sfx/, в каждом только .gitkeep
vn voice validate                     # → «появится в фазе 2», exit 3
```

Чтобы добавить трек — раздел «Как добавить трек» ниже.
Коротко: `.ogg` → `assets_src/audio_stems/bgm/<id>.ogg` →
запись в `content/audio/bgm.yaml` → `music: bgm/<id>` в `*.scene.yaml` → `vn build`.

## 1. Карта статусов

| Механизм | Статус | Код |
|---|---|---|
| Декларации `content/audio/*.yaml`, схема `audio@1` | IMPLEMENTED (файлы пусты: `tracks: {}`) | `../../tools/schemas/audio@1.schema.json` |
| Эмиттер `define audio.<id>` → `registry/audio.gen.rpy` | PARTIALLY IMPLEMENTED — эмитит только `file`, поля `loop`/`loop_start`/`volume` игнорируются | `../../tools/vn/src/vn/content/compile.py:301-311` |
| `music:` в `scene.yaml` → `play music <id> fadein 1.0` | IMPLEMENTED | `../../tools/vn/src/vn/content/scenes.py:231-242` |
| Проверка «трек объявлен» при компиляции сцены | IMPLEMENTED (ошибка компиляции) | `scenes.py:237-241` |
| Трансформация `copy_audio` (`assets_src/audio_stems/…` → `game/assets/audio/…`) | IMPLEMENTED — зона источника совпадает с нормативной, ветка покрыта тестом `test_audio_stems_branch_copies_ogg` | `../../tools/vn/src/vn/assets/pipeline.py:159-170`, `:232-233` |
| Проверка существования файла из `file:` | NOT IMPLEMENTED — ни в линтере, ни в компиляторе; `renpy lint` в конвейере не вызывается вообще | — |
| Запрет сырых путей в `play`-операторах (ARCHITECTURE.md:1181) | NOT IMPLEMENTED — в `lint.py` ноль аудио-правил | `../../tools/vn/src/vn/content/lint.py` |
| `loudnorm` в конвейере (ARCHITECTURE.md:1181) | NOT IMPLEMENTED — `copy_audio` = побайтовое копирование | `pipeline.py:232-233` |
| Микшеры и слайдеры громкости music/sound/voice | IMPLEMENTED (штатные Ren'Py) | `../../game/framework/20_ui/screens/core_screens.rpy:283-287` |
| `voice_tag` персонажа → `Character(..., voice_tag=…)` | IMPLEMENTED | `scenes.py:316-317`, `game/generated/registry/characters.gen.rpy:9` |
| `vn voice manifest\|import\|tts\|validate` | NOT IMPLEMENTED — стаб фазы 2, exit 3 | `../../tools/vn/src/vn/cli.py:1087` |
| Схема `voice@1`, voice-манифесты, `vn.voice_path()`, voice-паки | NOT IMPLEMENTED — ни схемы, ни каталогов, ни рантайм-функции | — |
| Аудио в реестре лицензий `content/licenses.yaml` | IMPLEMENTED вручную / автоматика NOT IMPLEMENTED — гейт сверяет только `*.render.yaml` из `assets_src/{daz,vam,sims4}` | `../../tools/vn/src/vn/assets/licenses.py:23-27,72-76` |

Проверено на диске: `find` по `*.ogg *.opus *.mp3 *.wav *.flac` во всём репозитории (кроме `.git`) даёт **пустой список**. `game/assets/audio/` отсутствует.

## 2. Декларации: `content/audio/*.yaml` (`audio@1`)

Один файл на вид звука. Сейчас их два, оба — скелеты:

```yaml
# content/audio/bgm.yaml
schema: audio@1
kind: bgm
tracks: {}
```

`content/audio/amb.yaml` **не существует**, но схема его допускает, а компилятор берёт `content/audio/*.yaml` глобом (`compile.py:656-660`) — достаточно создать файл с `kind: amb`.

### Полная таблица полей (`tools/schemas/audio@1.schema.json`)

| Поле | Уровень | Тип / ограничение | Обяз. | Эмитится в генерат? |
|---|---|---|---|---|
| `schema` | корень | `const: "audio@1"` | да | нет (служебное) |
| `kind` | корень | `enum: bgm \| amb \| sfx` | да | нет — **на генерат не влияет вообще** |
| `tracks` | корень | объект; ключи (id трека) по `^[a-z][a-z0-9_]*$` | да | ключ → имя `define audio.<id>` |
| `tracks.<id>.file` | трек | строка, строго `^assets/audio/(bgm\|amb\|sfx)/[a-z0-9_]+\.ogg$` | **да** | **да** — значение `define` |
| `tracks.<id>.loop` | трек | boolean | нет | **нет — игнорируется** |
| `tracks.<id>.loop_start` | трек | number ≥ 0 | нет | **нет — игнорируется** |
| `tracks.<id>.volume` | трек | number 0…1 | нет | **нет — игнорируется** |

`additionalProperties: false` на обоих уровнях — лишнее поле роняет валидацию схемы.

**Три ловушки в этой таблице:**

1. **`.ogg` захардкожен в паттерне.** `.opus`, `.mp3`, `.flac` схему не пройдут, хотя Ren'Py их играет (раздел 5). Это соответствует норме ARCHITECTURE.md:183 («`.ogg` для bgm/amb/sfx, `.opus` для voice»), но означает, что переход на Opus для музыки = новая схема `audio@2`, а не правка одного файла.
2. **`kind` и префикс пути в `file` не связаны.** Ничто не мешает объявить в `sfx.yaml` трек с `file: assets/audio/bgm/x.ogg`. Проверки нет.
3. **Пространство id — плоское.** `audio_ids` собирается объединением всех треков из всех файлов (`compile.py:661`), а `define audio.<id>` живёт в одном неймспейсе Ren'Py. Два трека с одинаковым id в `bgm.yaml` и `sfx.yaml` — коллизия `define`, которую никто не ловит.

### Что получается на выходе

`game/generated/registry/audio.gen.rpy`, `init offset = 500`, по строке на трек:

```renpy
init offset = 500

define audio.market_theme = "assets/audio/bgm/market_theme.ogg"
```

Сейчас вместо строк — `# Треки не объявлены (content/audio/*.yaml пусты).` (`compile.py:308-309`).
Файл производный: правки в `game/generated/` перезапишет ближайший `vn build`.

## 3. Как трек попадает в сцену

Единственный поддерживаемый путь — поле `music:` в `*.scene.yaml`:

```yaml
# content/chapters/ch01_awakening/scenes/s030_rooftop.scene.yaml
# (реальная сцена репозитория; строка music: — то, что вы дописываете)
schema: scene@1
id: s030
location: rooftop/day
music: bgm/market_theme        # ^(bgm|amb)/[a-z][a-z0-9_]*$
```

Компилятор (`scenes.py:231-242`) вставляет строку в обёртку сцены — **после** `scene bg`, **до** `call …__body`:

```renpy
label ch01_s030:
    $ vn.checkpoint("ch01_s030")
    $ renpy.scene("sprites")
    scene bg rooftop day with dissolve
    play music market_theme fadein 1.0
    call ch01_s030__body from _call_ch01_s030__body
```

Что здесь важно знать:

- **Префикс `bgm/`/`amb/` декоративен.** Код делает `track = music.split("/", 1)[1]` и дальше работает только с id. `music: amb/market_theme` даст тот же `play music market_theme`.
- **Незнакомый трек — ошибка компиляции**, а не предупреждение: `music bgm/x: трек 'x' не объявлен в content/audio/` (`scenes.py:237-241`). Это единственная аудио-проверка во всём тулинге.
- **`fadein 1.0` захардкожен**, менять нечем — только правкой `scenes.py`.
- **Клауза `if_changed` не эмитится**, `stop music` — тоже. Поведение при одном и том же треке в соседних сценах и на конце главы проверяйте на живом материале: треков в репозитории нет, утверждать нечего.
- **SFX через `scene.yaml` не декларируются.** Поле `music` — единственное аудио-поле в `scene@1`. Звуки пишутся руками в авторском `*.scene.rpy`: `play sound door_open`. Ограничение `__body`-контракта на это не распространяется (запрещены только jump/call наружу — см. [Сцены](12-scenes.md)), но и проверок никаких: опечатка в id вылезет в рантайме.

## 4. Зона источника: `assets_src/audio_stems/`

**Единственный вход аудио-тракта** — `assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg`. Discovery (`pipeline.py:159-170`):

```python
# Зона звука — audio_stems (ARCHITECTURE.md:393, conventions/folder-layout.md:29):
# имя нормативное, менять его пришлось бы через ADR, поэтому код идёт к норме.
audio = root / "assets_src" / "audio_stems"
if audio.is_dir():
    for kind in ("bgm", "amb", "sfx"):
        ...
        for f in sorted(kdir.glob("*.ogg")):
            jobs.append((f, "copy_audio", f"audio/{kind}/{f.name}", None))
```

Подкаталоги `bgm/`, `amb/`, `sfx/` заведены в репозитории (`.gitkeep`) — конвенция видна глазами, а не только в коде. Имена `.ogg` — обязательный slug `^[a-z][a-z0-9_]*$`; нарушение = ошибка сборки, а не молчание.

**Что здесь было сломано (история, чтобы не повторить).** Код искал `assets_src/audio/` — каталога с таким именем в репозитории нет и не было, `is_dir()` возвращал `False`, и ветка `copy_audio` не срабатывала **никогда**: звук не мог попасть в игру никаким путём. Расхождение прожило долго, потому что арбитра у него не было: `vn content lint --layout` сверяет 10 обязательных каталогов (`lint.py:21-33`), `assets_src` в списке нет вообще — ни одно из двух имён не проверялось.

**Почему чинили код, а не документы.** Имя `audio_stems` — нормативное: `docs/ARCHITECTURE.md:393` (дерево репозитория) и `../conventions/folder-layout.md:29`. Переименование зоны потребовало бы ADR и правки обоих документов; правка кода — одна строка и сходится с тем, что уже лежит на диске. Регрессия закрыта тестом `test_audio_stems_branch_copies_ogg` (`../../tools/vn/tests/test_assets.py`): `.ogg` в `assets_src/audio_stems/bgm/` обязан появиться в `game/assets/audio/bgm/`.

**Оставшаяся шероховатость — семантика имени.** «Stems» в звуковой индустрии — это многодорожечные исходники сведения (проекты DAW, WAV-мастера), а конвейер ждёт **финальный `.ogg`** для побайтового копирования (`pipeline.py:232-233` — `src.read_bytes()`, без транскода). Пока зона одна, и правило простое:

```
assets_src/audio_stems/{bgm,amb,sfx}/*.ogg   # готовые файлы — вход конвейера, в git
мастера .wav/.flac/проекты DAW               # НЕ в git: хранилище (ADR-0004) или внешний бэкап
```

Разделять зоны (`audio_stems/` под мастера + отдельная зона входа) — изменение нормативного дерева, то есть ADR; сегодня в этом нет нужды, потому что мастерам в git всё равно не место (§8). Отдельная незакрытая дыра: `assets_src` не входит в `REQUIRED_DIRS` линтера, поэтому исчезновение зоны по-прежнему не краснит сборку — кандидат в [Автоматизация](26-automation.md) и [Роадмап](37-roadmap.md).

## 5. Форматы и параметры

**Что играет Ren'Py 8.5.3** (дословно из официальной документации — Opus, Ogg Vorbis, MP3, MP2, FLAC, WAV только несжатый 16-bit signed PCM; https://www.renpy.org/doc/html/audio.html).

**Что разрешает наша схема:** только `.ogg` (Vorbis). Это осознанное сужение (ARCHITECTURE.md:183), и менять его — через `audio@2`.

**Ориентиры по битрейту.** Ресёрч сам помечает эти цифры как синтез общего руководства по Opus, а не спецификацию — A/B-тестируйте на своём материале:

| Ассет | Каналы | Ориентир (Opus) | Наш формат |
|---|---|---|---|
| Музыка / эмбиенс | стерео | 96 kbps | Vorbis VBR, `-q:a 4…5` — сверяйте по фактическому размеру |
| SFX (one-shot) | моно/стерео | 64–96 kbps | Vorbis `-q:a 3…4`; короткие файлы, битрейт почти не двигает итог |
| Голос | **моно** | 32–48 kbps | `.opus` (норма ARCHITECTURE.md:183) — контур не реализован |
| Мастера | — | FLAC/WAV | `assets_src/audio_stems/`, **вне git** |

Opus заметно компактнее Vorbis при том же качестве (рекомендация VN-сообщества: https://vndev.wiki/Guide:Audio_Formats, там же — оговорка про чуть более дорогой декод). Для нас это аргумент в пользу `audio@2` в будущем, но не повод обходить схему сегодня.

**Зацикливание.** Ren'Py умеет задавать точки прямо в имени файла — свойства `from`, `loop`, `to` документированы по отдельности, например `play music "<loop 6.333>bgm.ogg"`. Комбинированная форма `<from X loop Y to Z>` в документации примером не показана — проверяйте, прежде чем закладываться. Есть также `"<silence 3.0>"` и `"<sync channelname>track.ogg"`.

**Ловушка нашего конвейера:** поля `loop` и `loop_start` в `audio@1` есть, но эмиттер их **не читает**. Поставить точку лупа сегодня можно только одним способом — вписав префикс прямо в `file:`… чего не даст паттерн схемы (`^assets/audio/…\.ogg$`). Практический вывод: **точку лупа режьте в самом файле** (по нулевому пересечению, в REAPER/Audacity), чтобы файл зацикливался бесшовно сам по себе. Поддержка `loop_start` в эмиттере — отдельная задача.

Каналы и микшеры — штатные Ren'Py: каналы `music` / `sound`, микшеры `music` / `sfx` / `voice`, дополнительные каналы через `renpy.music.register_channel()`. Три слайдера в настройках уже есть (`core_screens.rpy:283-287`, строки `ui.prefs.volume{,_music,_sound,_voice}` в `content/ui/strings.yaml:103-106`) — слайдер «Голос» существует и работает как микшер, хотя озвучки в игре нет.

## 6. Нормализация громкости — делать до `assets_src/`

**Статус в конвейере: NOT IMPLEMENTED.** ARCHITECTURE.md:1181 обещает, что аудио «проходит тот же компилятор (loudnorm; выход — `.ogg`)». Реально `copy_audio` — это `src.read_bytes()`, побайтовая копия. Никакой нормализации, никакого транскода, никакой проверки громкости в тулинге нет. Значит, **нормализованным файл должен приезжать в `assets_src/audio_stems/` уже готовым** — иначе разнобой громкости между 40 треками из четырёх генераторов уедет в билд как есть.

**Целевые значения.** Единственная игровая рекомендация — **ASWG-R001 v1.10** (Sony Worldwide Studios Audio Standards Working Group, 2013): **−24 (±2) LKFS** интегрированно для домашних платформ, **−18 (±2) LKFS** для портативных, максимум True Peak **−1 dBTP**. LKFS и LUFS — взаимозаменяемы. Вещательный EBU R 128 — −23 LUFS (https://tech.ebu.ch/publications/r128).

⚠️ **Расхождение, о котором надо знать:** VN-специфичный гайд сообщества (https://vndev.wiki/index.php?title=Guide%3ABalancing_a_Game%27s_Loudness) рекомендует **−24 LUFS для десктопа** (совпадает с ASWG) и **−16 LUFS для портатива** — что на 2 LU громче стандарта ASWG (−18). Пресет «ASWG-R001 PORTABLE» в измерителе покажет −18. Выберите одно значение сознательно и запишите его сюда, а не в голову.

**Рецепт (два прохода, ffmpeg).** Однопроходный `loudnorm` — динамический нормализатор, для шипящихся ассетов он не годится; всегда два прохода + `linear=true` (объяснение автора фильтра: http://k.ylo.ph/2016/04/04/loudnorm.html).

```bash
# Проход 1 — измерение (числа из JSON подставляются в проход 2)
ffmpeg -i in.wav -af loudnorm=I=-24:TP=-1.0:LRA=11:print_format=json -f null -

# Проход 2 — применение + кодирование в наш .ogg (Vorbis)
ffmpeg -i in.wav -af loudnorm=I=-24:TP=-1.0:LRA=11:\
measured_I=-27.61:measured_LRA=18.06:measured_TP=-4.47:measured_thresh=-39.20:\
offset=0.58:linear=true -ar 48000 -c:a libvorbis -q:a 5 \
  assets_src/audio_stems/bgm/market_theme.ogg
```

**Три граблины, каждая кусается:**

- ⚠️ **`-ar 48000` обязателен.** `loudnorm` внутри апсемплит до 192 кГц ради look-ahead-лимитера и обратно **не** опускает — это на вашей совести. Классический баг.
- ⚠️ **Не нормализуйте каждый файл в −24 по отдельности.** Так SFX станет громким как музыка. Нормализуйте **по категориям** с внутренним оффсетом, а интегрированную громкость проверяйте на реальном прогоне игры.
- Цели должны выдерживаться **на дефолтных позициях микшеров** — игрок их двигает, вы меряете исходное состояние.

Измеритель: Youlean Loudness Meter 2 (https://youlean.co/youlean-loudness-meter/) — бесплатный тариф закрывает пресеты ASWG-R001 HOME/PORTABLE и показания INT/TP/LRA; Pro — $37 разово. Работает и как standalone (загнать в него системный звук и играть), и как VST в DAW.

ffmpeg в проекте уже пиннован и проверяется `vn pipeline doctor` (на машине владельца — 8.1.2 с VP9). Установка/обновление — [Видео](21-video-generation.md); текущий релиз ffmpeg — 9.0 «Lei» (2026-08-04), Windows-сборки: https://www.gyan.dev/ffmpeg/builds/

## 7. Откуда брать музыку и звук

Проект — коммерческий и взрослый, поэтому фильтр двойной: (1) разрешена ли коммерция, (2) нет ли в лицензии/AUP пункта про сексуальный контент. Второй пункт срезает половину «очевидных» вариантов, включая локально запускаемые модели: **acceptable-use policy приезжает вместе с лицензией на веса и на локальный запуск не смотрит**.

**Никаких юридических выводов из этой таблицы не делайте — проверяйте актуальный EULA/лицензию по официальной ссылке перед коммерческой дистрибуцией.** Ниже — навигация, а не заключение.

| Источник | Лицензия | Оговорка про 18+ | Пригодность |
|---|---|---|---|
| **ACE-Step 1.5** — локальная генерация музыки в ComfyUI (https://github.com/ace-step/ACE-Step-1.5, гайд ComfyUI: https://docs.comfy.org/tutorials/audio/ace-step/ace-step-v1-5) | MIT (у 1.5); Apache-2.0 у исходного ACE-Step | в README не найдено | 🟢 основной генератор музыки |
| **Incompetech / Kevin MacLeod** (https://incompetech.com/music/royalty-free/faq.html) | CC BY 4.0 | у CC нет ограничений по сфере применения | 🟢 бесплатный костяк; **атрибуция обязательна** |
| **Sonniss GDC Game Audio Bundle** (https://gdc.sonniss.com/, лицензия: https://sonniss.com/gdc-bundle-license/) | royalty-free, бессрочно, без атрибуции | не найдено | 🟢 основной источник SFX |
| **Freesound** (https://freesound.org/help/faq/) | per-sound: CC0 / CC-BY / **CC-BY-NC** | нет | 🟢 **только CC0**; CC-BY-NC в коммерческом билде = нарушение |
| **A Sound Effect** (https://www.asoundeffect.com/) | royalty-free, без атрибуции; условия — по вендору | по вендору | 🟢 точечные платные библиотеки |
| **WOW Sound** (https://wowsound.com/royalty-free-music-for-visual-novel/) | по выручке (Common — до $100K) | не проверено | 🟡 сделан под VN, читайте условия тира |
| **Stable Audio 3** (https://stability.ai/license, https://stability.ai/use-policy) | Community License (бесплатно до $1M выручки) | ⛔ AUP прямо запрещает sexually explicit content, а лицензия требует соблюдения AUP | 🔴 не для этого проекта |
| **Suno** (https://suno.com/terms) | платный тариф передаёт права на выход | ⛔ запрет достаёт до **продукта**, в котором используется выход, а не только до промпта | 🔴 только временные рыбы, и то с оглядкой |
| **Pixabay** (https://pixabay.com/service/license-summary/) | коммерция ок, без атрибуции | ⚠️ неопределённый пункт про «immoral» использование | 🟡 избегать для 18+ |
| **Artlist** / **Epidemic Sound** | не удалось прочитать машинно (403 / cookie-стена) | неизвестно | 🟡 читать в браузере; у Epidemic для игр отдельный Enterprise |
| **Udio** | после сделки с UMG — «walled garden» | — | 🔴 непригодно как основа звука в отгружаемой игре |
| **MusicGen / AudioCraft** (https://github.com/facebookresearch/audiocraft) | код MIT, **веса CC-BY-NC** | — | 🔴 нельзя отгружать, что бы ни писали туториалы |

**Три сквозных правила:**

1. Локальная модель ≠ отсутствие ограничений. Смотрите AUP лицензии, а не только «MIT/Apache» в шапке репозитория.
2. ⛔ Никогда не скармливайте лицензионные библиотеки (Sonniss и подобные) в обучение/дообучение моделей — это прямо запрещено их лицензией. Держите датасеты и библиотеки в физически разных деревьях каталогов, чтобы `*`-глоб не мог их пересечь.
3. Атрибуция CC BY — **условие лицензии, а не вежливость**. Экран титров стройте до того, как соберёте саундтрек, и ведите соответствие «трек → файл → запись реестра» с первого файла.

### Куда записывать лицензию

`content/licenses.yaml` (`license_registry@1`) — единственное место учёта; в схеме прямо предусмотрены `vendor: audio_stock` и `license_type: cc0 | cc_by | royalty_free | custom | unknown`:

```yaml
  sonniss_gdc2026:
    title: "Sonniss GDC 2026 Game Audio Bundle"
    vendor: audio_stock
    url: https://gdc.sonniss.com/
    license_type: royalty_free
    game_use: true
    nsfw_allowed: true       # пункта про контент в лицензии не найдено — сверьте текст сами
    purchased_at: "2026-08-08"
    invoice: "free-gdc-bundle"
```

⚠️ **Автоматика этого не проверит.** `validate_licenses` (`licenses.py:72-76`) сканирует только `assets_src/{daz,vam,sims4}/**/*.render.yaml` и сверяет их поле `license:`. У аудио деклараций `*.render.yaml` нет — записи в реестре живут «на честном слове» и в релизном гейте не участвуют. Дисциплина ручная: **покупка/скачивание → запись в реестр → только потом файл в `assets_src/`**. Подробности юридического контура — [Безопасность и право](33-security-and-legal.md), лицензирование AI-моделей — `../adr/0008-ai-model-licensing-for-commercial-adult-content.md` (статус: **предложено**, решение владельца не принято).

## 8. Озвучка — NOT IMPLEMENTED целиком

**Что есть:**

- `voice_tag` в `character@1`; у `mira` — `voice_tag: mira`; эмитится в `Character(..., voice_tag='mira')` (`characters.gen.rpy:9`). Это даёт бесплатный per-character mute в настройках — и всё.
- Слайдер микшера `voice` в настройках.

**Чего нет:** схемы `voice@1`, каталогов `content/chapters/*/voice/`, функции `vn.voice_path()`, паков `kind: voice_pack`, и самих команд:

```
$ vn voice validate
эта команда появится в фазе 2 (раздел 8 ARCHITECTURE.md)
$ echo $?
3
```

(`cli.py:1087` — `_stub_group("voice", "Озвучка (C5).", {"manifest": 2, "import": 2, "tts": 2, "validate": 2})`.)

**Как это спроектировано** (ARCHITECTURE.md §4.9 и §5.9.3 — читать целиком перед реализацией, ниже только каркас):

- `config.auto_voice` **сознательно не используется** (норма G8): его id — хэш от label+текста, любая правка реплики молча отвязывает записанный дубль. Вместо него компилятор вставляет явные операторы `voice vn.voice_path("ch03_s012_0042")` перед озвученными репликами.
- Стабильные line-id — те же say-id, которые `vn loc keys` физически дописывает в авторский `.rpy` парсером Ren'Py (это уже работает — см. [Локализация](14-localization.md)). Формат `^ch\d{2}_s\d{3}_\d{4}$`.
- Покрытие описывают манифесты `content/chapters/chNN/voice/<lang>.voice.yaml` (шард глава × язык).
- Файлы — `voice/<lang>/<line_id>.opus` **внутри voice-пака**, не в основном дистрибутиве: три языка × тысячи реплик — это гигабайты, из которых игроку нужен один язык.
- Пайплайн фазы 2: `vn voice manifest` (лист для студии) → `vn voice import` (раскладка дублей, транскод в opus 96k / LUFS −19) → `vn voice tts` (черновики для непокрытых реплик) → `vn voice validate --report` (покрытие, сироты, драфты).

**Решения по TTS на 2026** (из ресёрча; лицензии проверяйте сами по ссылкам перед коммерческим использованием):

| Модель | Лицензия | Заметки |
|---|---|---|
| **Chatterbox** (Resemble AI, https://github.com/resemble-ai/chatterbox) | MIT | 🟢 самый чистый вариант для голосов персонажей. Multilingual V3, 23+ языка включая русский; клон с ~10-секундного референса. Весь выход помечен нейронным вотермарком Perth — это нормально, снимать не пытайтесь. Просодия плавает между прогонами: рендерите все реплики персонажа одним батчем с фиксированным сидом и одним референсом |
| **Kokoro-82M** (https://huggingface.co/hexgrad/Kokoro-82M) | Apache 2.0 | 🟢 8 языков, 54 фиксированных голоса, без клонирования. Идеален для черновой озвучки всего скрипта на CPU, пока GPU занят ComfyUI. Веса — только из репозитория `hexgrad/Kokoro-82M`; домены вида `kokorotts*` в карточке модели названы вероятными скамами |
| **XTTS-v2**, **F5-TTS**, **Fish Speech** | CPML (текст лицензии больше не отдаётся, вендор мёртв) / CC-BY-NC веса / research-лицензия | 🔴 отгружать нельзя |
| **IndexTTS-2**, **Higgs TTS** | кастомные (bilibili; «other») | 🟡 читать LICENSE до того, как строить на них пайплайн |
| **ElevenLabs** | не удалось прочитать (гео-редирект) | 🟡 условия по 18+ получить письменно у поддержки до оплаты |

⛔ **Отдельным пунктом: никогда не клонируйте голос реального узнаваемого человека** — актёра, стримера, кого угодно — для взрослого контента. По оценке ресёрча это крупнейший единичный правовой риск во всём конвейере, крупнее любого вопроса по музыкальной лицензии. Только синтетические/смешанные референсы либо голос актёра с подписанным релизом в архиве.

## 9. Бюджет: сколько аудио влезает

Два независимых потолка, и **первым упирается репозиторий, а не билд**.

| Потолок | Значение | Где считается | Что попадает |
|---|---|---|---|
| `assets_total_mb` | 500 МБ | `project.yaml:8`, `../../tools/vn/src/vn/release.py:33-37` | всё `game/assets/` целиком (спрайты + фоны + CG + видео + аудио) |
| `video_total_mb` | 300 МБ | там же | только `game/assets/mov/` — то есть аудио конкурирует со статикой за остаток |
| **ADR-0004: бинари в `assets_src/`** | **warn > 30 МБ, error > 50 МБ** | `lint.py:375-399` | все нетекстовые файлы под `assets_src/` — **включая ваши `.ogg`** |

Сейчас в `assets_src/` **0.126 МБ** бинарей (10 демо-PNG + один mp4). Считаем по формуле `размер ≈ битрейт × длительность / 8`:

| | Длит. | Битрейт | Размер | Сколько до порога ADR-0004 |
|---|---|---|---|---|
| BGM-трек | 3 мин | ~160 kbps стерео | ≈ 3.5 МБ | **~8 треков до warn (30 МБ), ~14 до error (50 МБ)** |
| BGM-трек | 3 мин | ~128 kbps стерео | ≈ 2.8 МБ | ~10 / ~17 |
| SFX one-shot | 1.5 с | ~96 kbps | ≈ 20 КБ | сотни |

Прикидка на главу: 3–6 BGM + ~30 SFX ≈ **11–22 МБ** в `assets_src/`, если каждая глава получает свой набор. Музыка обычно переиспользуется — маржинальная стоимость второй и последующих глав сильно ниже. Но **уже на второй-третьей главе порог ADR-0004 упирается**, и это ожидаемый триггер: ADR-0004 прямо говорит, что при превышении сырцы обязаны переехать в хранилище (`vn assets lock` + `vn assets push`). Хранилище описано и написано, но **ни разу не разворачивалось** (`~/vn-assets-store` не существует) — см. [Ассеты](16-assets.md) §7 и [Хранилище и бэкап](31-storage-and-backup.md).

Практический вывод: **мастера (WAV/FLAC/проекты DAW) в git не кладите вообще** — только в `assets_src/audio_stems/` при развёрнутом хранилище, либо во внешний бэкап до тех пор. В git — только финальные `.ogg`, и то со счётчиком в голове.

## Как добавить трек / звук

Пошагово, с честной отметкой, что сломано.

**0. Подготовьте файл вне репозитория.** Отнормируйте (раздел 6), обрежьте точку лупа по нулевому пересечению, закодируйте в Ogg Vorbis 48 кГц. Имя = будущий id: `^[a-z][a-z0-9_]*$` (проверяется в `pipeline.py:168` через общий `_check_slug`).

**1. Положите в зону входа конвейера.**

```bash
cp market_theme.ogg assets_src/audio_stems/bgm/market_theme.ogg
```

Каталоги `assets_src/audio_stems/{bgm,amb,sfx}/` уже заведены. Кладите туда **готовый `.ogg`**: конвейер копирует байты как есть, ни транскода, ни нормализации не будет. Мастера (WAV/FLAC/проекты DAW) в git не кладите — им место в хранилище (ADR-0004), см. §8.

**2. Объявите трек.**

```yaml
# content/audio/bgm.yaml
schema: audio@1
kind: bgm
tracks:
  market_theme:
    file: assets/audio/bgm/market_theme.ogg     # путь ОТ game/, не от корня репозитория
```

Поля `loop`/`loop_start`/`volume` писать можно (схема пропустит), но эмиттер их игнорирует — не полагайтесь.

**3. Подключите к сцене** — либо декларативно, либо руками:

```yaml
# в *.scene.yaml — музыка сцены
music: bgm/market_theme
```

```renpy
# в *.scene.rpy — SFX внутри диалога
play sound door_open
```

**4. Соберите и проверьте.**

```bash
vn assets build                # copy_audio перенесёт .ogg в game/assets/audio/bgm/
ls game/assets/audio/bgm/      # ← если пусто, проверьте имя каталога и slug-имя файла
vn build                       # lint -> ассеты -> генерат
grep market_theme game/generated/registry/audio.gen.rpy
vn play                        # слушаем
```

**5. Запишите лицензию** в `content/licenses.yaml` (раздел 7). Автоматика не напомнит.

## Чеклист нового аудио-ассета

- [ ] Источник и лицензия зафиксированы в `content/licenses.yaml` **до** появления файла в репозитории
- [ ] Для CC BY — трек внесён в список титров с точной формулировкой атрибуции
- [ ] Отнормирован: интегрированно −24 LUFS (или ваше зафиксированное значение), True Peak ≤ −1 dBTP, два прохода `loudnorm` с `linear=true` и `-ar 48000`
- [ ] Формат `.ogg` (Vorbis), 48 кГц; музыка — стерео, SFX — как уместно
- [ ] Для зацикливаемой музыки: шов проверен на слух ≥ 10 повторов
- [ ] Имя файла = будущий id, `^[a-z][a-z0-9_]*$`, без дефисов и заглавных
- [ ] Лежит в `assets_src/audio_stems/{bgm,amb,sfx}/`, мастер (WAV/проект) — **не** в git
- [ ] `id` уникален во всех `content/audio/*.yaml` (неймспейс плоский)
- [ ] `file:` совпадает с фактическим путём под `game/` — существование файла никто не проверит
- [ ] `vn assets build` → файл появился в `game/assets/audio/<kind>/`
- [ ] `vn build` → зелёный; трек виден в `game/generated/registry/audio.gen.rpy`
- [ ] `vn content lint` → бюджет ADR-0004 не в warn (`assets_src` < 30 МБ)
- [ ] Прослушано в игре на дефолтных позициях микшеров

## Чего НЕ делать

- **Не класть `.ogg` мимо `assets_src/audio_stems/{bgm,amb,sfx}/`** — других зон звука конвейер не знает (§4). Симптом — пустой `game/assets/audio/` и полное молчание сборки.
- **Не править `game/generated/registry/audio.gen.rpy` и `game/assets/audio/`** — обе зоны производные, перезапишет ближайший `vn build` / `vn assets build`.
- **Не писать сырые пути в `play`-операторах** (`play music "assets/audio/bgm/x.ogg"`). ARCHITECTURE.md:1181 объявляет это запрещённым, но линтера на это нет — запрет держится только на вашей дисциплине, и он правильный: сырой путь ломает единый неймспейс `define audio.*` и переименование файла.
- **Не рассчитывать на `loop_start` и `volume` в `audio@1`** — эмиттер их не читает. Луп режьте в файле.
- **Не нормализовать каждый файл по отдельности в один и тот же LUFS** — категории поплывут относительно друг друга.
- **Не забывать `-ar 48000` после `loudnorm`** — фильтр оставит файл на 192 кГц.
- **Не заливать WAV/FLAC-мастера в git** — ADR-0004 краснеет на 50 МБ, а история append-only необратима.
- **Не тащить в билд CC-BY-NC (Freesound) и веса MusicGen/AudioCraft** — обе категории коммерчески неотгружаемы.
- **Не клонировать голоса реальных людей** — см. §8.
- **Не скармливать лицензионные SFX-библиотеки в обучение моделей** — прямо запрещено лицензией Sonniss.

## Проверка

```bash
vn content lint            # схемы деклараций + бюджет бинарей ADR-0004
vn assets build            # перенос .ogg; молчание = каталог-источник назван неверно
vn assets validate         # сырцы + ссылки контента (в т.ч. music-треки сцен)
vn build                   # полный проход: lint -> ассеты -> генерат -> tl
vn build --check           # CI-режим: ничего не пишет, краснеет на несвежем
vn play                    # слушаем в игре
python -m pytest tools/vn/tests -q    # 138 тестов; аудио-веток среди них нет
```

Отрицательный тест на связность (полезен, потому что это единственная аудио-проверка в тулинге): впишите в сцену `music: bgm/nonexistent` и запустите `vn build` — должно упасть с `трек 'nonexistent' не объявлен в content/audio/`.

## Ресурсы

- Ren'Py Audio — поддерживаемые форматы, префиксы `<from/loop/to>`, каналы и микшеры: https://www.renpy.org/doc/html/audio.html
- Ren'Py Voice — `voice`, `voice sustain`, `voice_tag`, `config.auto_voice`: https://www.renpy.org/doc/html/voice.html
- Баланс громкости в VN (цифры, процедура измерения): https://vndev.wiki/index.php?title=Guide%3ABalancing_a_Game%27s_Loudness
- `loudnorm` от автора фильтра (одно- vs двухпроходный режим, ресемплинг): http://k.ylo.ph/2016/04/04/loudnorm.html
- ASWG-R001 v1.10 — игровая рекомендация по громкости (PDF): http://gameaudiopodcast.com/ASWG-R001.pdf
- Sonniss GDC Game Audio Bundle + текст лицензии: https://gdc.sonniss.com/ · https://sonniss.com/gdc-bundle-license/
- ACE-Step 1.5 в ComfyUI (локальная генерация музыки): https://docs.comfy.org/tutorials/audio/ace-step/ace-step-v1-5

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/schemas/audio@1.schema.json`, `../../tools/vn/src/vn/content/compile.py:301-311,655-661`, `../../tools/vn/src/vn/content/scenes.py:231-242`, `../../tools/vn/src/vn/assets/pipeline.py:37-46,159-170,232-233`, `../../tools/schemas/scene@1.schema.json`, `../ARCHITECTURE.md` §2.9 (:183, :1181), §4.9 (:2341), §5.9.3 (:2867) |
| **Не трогать** | `game/generated/registry/audio.gen.rpy` (генерат), `game/assets/audio/` (генерат), `game/tl/` — всё перезаписывается сборкой |
| **Зависимости** | Новый id трека → `audio.gen.rpy` → `play music` в обёртках сцен. Смена паттерна `file` в `audio@1` → новая схема `audio@2` + миграция деклараций. Правка `pipeline.py:159` (имя зоны) → инвалидация ключей кэша `copy_audio` и рассинхрон с ARCHITECTURE.md:392 и `../conventions/folder-layout.md:29`. Любые файлы в `assets_src/` → счётчик ADR-0004 в `lint.py:375-399` |
| **Валидация** | `vn content lint` → `vn assets build` → `vn build` → `vn build --check`; `python -m pytest tools/vn/tests -q` |
| **Частые ошибки** | 1) Класть `.ogg` мимо `assets_src/audio_stems/{bgm,amb,sfx}/` — другой зоны у `copy_audio` нет, а молчаливо пропущенный файл выглядит как зелёная сборка. 2) Верить полям `loop`/`loop_start`/`volume` — схема их принимает, эмиттер игнорирует. 3) Считать `bgm/`/`amb/` в `music:` значащим префиксом — код его отбрасывает, неймспейс id плоский. 4) Ожидать проверки существования файла из `file:` — её нет нигде, `renpy lint` в конвейере не вызывается. 5) Верить ARCHITECTURE.md:1181 про `loudnorm` в компиляторе — это целевое состояние, реально `copy_audio` копирует байты. 6) Расширять `.ogg` до `.opus` правкой одного YAML — паттерн `audio@1` этого не пропустит |
