# 23. Аудио

> **Статус подсистемы:** PARTIALLY IMPLEMENTED. Декларации, кодоген, ветка сборки `copy_audio`, канал `ambient`, дакинг под голос и **весь голосовой контур** (`voice@1`, `vn voice manifest|import|validate`, `vn.voice_path`, транскод `voice_opus` с loudnorm) работают. Но музыки/SFX в репозитории **ноль** (`content/audio/*.yaml` пусты, `tracks: {}`), loudnorm для bgm/amb/sfx NOT IMPLEMENTED (`copy_audio` копирует байты), `vn voice tts` — заглушка фазы 2.
> **Отвечает на вопрос:** «Как в игре появляется музыка, звук и озвучка, что из этого уже работает, и что конкретно сделать, чтобы добавить первый трек или дубль».

Аудио-контур размазан по нескольким местам: декларации `content/audio/{bgm,amb,sfx}.yaml` (схема `audio@1`), эмиттер `_emit_audio` в Content Compiler, ветка `copy_audio` в ассет-конвейере, поля `music:`/`ambient:` в `*.scene.yaml` и аудио-рантайм `game/framework/00_core/045_audio.rpy` (канал `ambient`, дакинг, `vn.voice_path`). Голос — отдельный контур: манифесты `voice@1` + `vn voice` + ветка `voice_opus` (§8). Общая механика ассетов — [Ассеты](16-assets.md), общий поток данных — [Сквозной конвейер](08-content-pipeline.md).

## Быстрый ответ

```bash
# Что есть сейчас — проверьте сами, это займёт 10 секунд:
cat content/audio/bgm.yaml            # → tracks: {}
cat game/generated/registry/audio.gen.rpy   # → "# Треки не объявлены"
ls assets_src/audio_stems/            # → bgm/ amb/ sfx/, в каждом только .gitkeep
vn voice validate --report            # → покрытие озвучки по главам и языкам
ls assets_src/voice/ru/ch01/          # → wav-мастера демо-дублей ch01
```

Чтобы добавить трек — раздел «Как добавить трек» ниже.
Коротко: `.ogg` → `assets_src/audio_stems/bgm/<id>.ogg` →
запись в `content/audio/bgm.yaml` → `music: bgm/<id>` в `*.scene.yaml` → `vn build`.

## 1. Карта статусов

| Механизм | Статус | Код |
|---|---|---|
| Декларации `content/audio/*.yaml`, схема `audio@1` | IMPLEMENTED (все три файла — `bgm/amb/sfx` — пусты: `tracks: {}`) | `../../tools/schemas/audio@1.schema.json` |
| Эмиттер `define audio.<id>` → `registry/audio.gen.rpy` | IMPLEMENTED — `file` + `loop_start` (штатный префикс `"<loop N>file"`); `volume` уходит клаузой play-оператора в сцене; поле `loop` по-прежнему игнорируется | `../../tools/vn/src/vn/content/compile.py:377-391`, `scenes.py:328-331` |
| Коллизия id трека между `kind` (bgm/amb/sfx) | IMPLEMENTED — ошибка компиляции («define audio.<id> перезаписался бы молча») | `compile.py:843-852` |
| `music:` в `scene.yaml` → `play music <id> fadeout 1.0 fadein 1.0 [volume V]` | IMPLEMENTED | `../../tools/vn/src/vn/content/scenes.py:304-331` |
| `ambient:` в `scene.yaml` → `play ambient <id> …` (одновременно с музыкой) | IMPLEMENTED — канал `ambient` регистрирует рантайм | `scenes.py:304-331`, `../../game/framework/00_core/045_audio.rpy:13` |
| Дакинг под голос (`config.emphasize_audio_*`: канал voice приглушает остальные до 0.6) | IMPLEMENTED (штатный механизм движка) | `045_audio.rpy:18-20` |
| Проверка «трек объявлен» + «kind трека соответствует каналу» (и для рукописных `play`/`queue` в `.rpy`) | IMPLEMENTED (ошибка компиляции) | `scenes.py:71-73,123-149,314-325` |
| Проверка существования файла из `file:` | NOT IMPLEMENTED — ни в линтере, ни в компиляторе; `renpy lint` в конвейере не вызывается вообще | — |
| Запрет сырых путей в `play`-операторах (ARCHITECTURE.md:1181) | PARTIAL — строковый литерал в `play` статически не разрешается и просто пропускается проверкой; отдельного запрета нет | `scenes.py:126-131` |
| `loudnorm` для bgm/amb/sfx (ARCHITECTURE.md:1181) | NOT IMPLEMENTED — `copy_audio` = побайтовое копирование; loudnorm есть только в голосовой ветке `voice_opus` | `pipeline.py:636` |
| Трансформация `copy_audio` (`assets_src/audio_stems/…` → `game/assets/audio/…`) | IMPLEMENTED — зона источника совпадает с нормативной, ветка покрыта тестом `test_audio_stems_branch_copies_ogg` | `../../tools/vn/src/vn/assets/pipeline.py:415-430` |
| Микшеры и слайдеры громкости music/sound/voice | IMPLEMENTED (штатные Ren'Py; канал `ambient` висит на микшере music) | `../../game/framework/20_ui/screens/core_screens.rpy:283-287` |
| `voice_tag` персонажа → `Character(..., voice_tag=…)` | IMPLEMENTED | `game/generated/registry/characters.gen.rpy:9` |
| `vn voice manifest\|import\|validate` | IMPLEMENTED | `../../tools/vn/src/vn/cli.py:1226-1311`, `../../tools/vn/src/vn/voice.py` |
| `vn voice tts` (TTS-черновики непокрытых реплик) | NOT IMPLEMENTED — стаб фазы 2, exit 3 | `cli.py:1278-1281` |
| Схема `voice@1`, voice-манифесты, инжекция `voice vn.voice_path("<id>")`, транскод `voice_opus` | IMPLEMENTED (§8) | `../../tools/schemas/voice@1.schema.json`, `compile.py:985-1005`, `scenes.py:283-300`, `pipeline.py:432-466` |
| Гейт озвучки в `vn release validate` (ошибки/дыры = FAIL, драфты = WARN) | IMPLEMENTED | `../../tools/vn/src/vn/release.py:464-478` |
| Voice-паки как отдельные Steam-депоты | NOT IMPLEMENTED — `vn pack build` кладёт в архив только сцены и манифест | [30-packs-and-dlc.md](30-packs-and-dlc.md) |
| Аудио в реестре лицензий `content/licenses.yaml` | IMPLEMENTED вручную / автоматика NOT IMPLEMENTED — гейт сверяет только `*.render.yaml` из `assets_src/{daz,vam,sims4}` | `../../tools/vn/src/vn/assets/licenses.py:23-27,72-76` |

Проверено на диске: музыки и SFX нет — `find` по `*.ogg *.mp3 *.flac` в `assets_src/audio_stems/` пуст, `game/assets/audio/{bgm,amb,sfx}` отсутствуют. Озвучка есть: `assets_src/voice/ru/ch01/*.wav` (демо-дубли ch01) и их opus-выходы в `game/assets/voice/ru/ch01/` после `vn assets build`.

## 2. Декларации: `content/audio/*.yaml` (`audio@1`)

Один файл на вид звука. Сейчас их три (`bgm.yaml`, `amb.yaml`, `sfx.yaml`), все — скелеты:

```yaml
# content/audio/bgm.yaml
schema: audio@1
kind: bgm
tracks: {}
```

Компилятор берёт `content/audio/*.yaml` глобом — имя файла декоративно, вид звука определяет поле `kind`.

### Полная таблица полей (`tools/schemas/audio@1.schema.json`)

| Поле | Уровень | Тип / ограничение | Обяз. | Эмитится в генерат? |
|---|---|---|---|---|
| `schema` | корень | `const: "audio@1"` | да | нет (служебное) |
| `kind` | корень | `enum: bgm \| amb \| sfx` | да | не эмитится, но **валидируется**: канал play-оператора обязан соответствовать kind трека (`scenes.py:71-73,139-149`), а `music:`/`ambient:` в scene.yaml выбирают канал по kind (`scenes.py:326`) |
| `tracks` | корень | объект; ключи (id трека) по `^[a-z][a-z0-9_]*$` | да | ключ → имя `define audio.<id>` |
| `tracks.<id>.file` | трек | строка, строго `^assets/audio/(bgm\|amb\|sfx)/[a-z0-9_]+\.ogg$` | **да** | **да** — значение `define` |
| `tracks.<id>.loop` | трек | boolean | нет | **нет — игнорируется** (каналы music/ambient зациклены и так) |
| `tracks.<id>.loop_start` | трек | number ≥ 0 | нет | **да** — штатным префиксом partial playback: `define audio.<id> = "<loop N>file"` (`compile.py:383-386`) |
| `tracks.<id>.volume` | трек | number 0…1 | нет | **да** — клаузой `volume V` play-оператора сцены, если ≠ 1 (`scenes.py:328-331`); рукописный `play sound <id>` в `.rpy` её **не** получает |

`additionalProperties: false` на обоих уровнях — лишнее поле роняет валидацию схемы.

**Две оставшиеся ловушки и одна закрытая:**

1. **`.ogg` захардкожен в паттерне.** `.opus`, `.mp3`, `.flac` схему не пройдут, хотя Ren'Py их играет (раздел 5). Это соответствует норме ARCHITECTURE.md:183 («`.ogg` для bgm/amb/sfx, `.opus` для voice»), но означает, что переход на Opus для музыки = новая схема `audio@2`, а не правка одного файла.
2. **`kind` и префикс пути в `file` не связаны.** Ничто не мешает объявить в `sfx.yaml` трек с `file: assets/audio/bgm/x.ogg`. Проверки нет.
3. ~~Пространство id — плоское и коллизии не ловятся~~ — **закрыто**: id глобально уникален между kind'ами, дубль в двух файлах — ошибка компиляции «define audio.<id> перезаписался бы молча» (`compile.py:843-852`).

### Что получается на выходе

`game/generated/registry/audio.gen.rpy`, `init offset = 500`, по строке на трек:

```renpy
init offset = 500

define audio.market_theme = "assets/audio/bgm/market_theme.ogg"
define audio.rain = "<loop 6.333>assets/audio/amb/rain.ogg"    # loop_start: 6.333
```

Сейчас вместо строк — `# Треки не объявлены (content/audio/*.yaml пусты).` (`compile.py:389-390`).
Файл производный: правки в `game/generated/` перезапишет ближайший `vn build`.

## 3. Как трек попадает в сцену

Декларативный путь — поля `music:` и `ambient:` в `*.scene.yaml` (могут стоять одновременно):

```yaml
# content/chapters/ch01_awakening/scenes/s030_rooftop.scene.yaml
# (реальная сцена репозитория; строки music:/ambient: — то, что вы дописываете)
schema: scene@1
id: s030
location: rooftop/day
music: bgm/market_theme        # ^bgm/[a-z][a-z0-9_]*$
ambient: amb/rooftop_wind      # ^amb/[a-z][a-z0-9_]*$ — играет ОДНОВРЕМЕННО с музыкой
```

Компилятор (`scenes.py:304-331,372-375`) вставляет play-операторы в обёртку сцены — **после** `scene bg`, **до** `call …__body`:

```renpy
label ch01_s030:
    $ vn.checkpoint("ch01_s030")
    $ renpy.scene("sprites")
    scene bg rooftop day with dissolve
    play music market_theme fadeout 1.0 fadein 1.0
    play ambient rooftop_wind fadeout 1.0 fadein 1.0 volume 0.8   # volume — из audio@1, если ≠ 1
    call ch01_s030__body from _call_ch01_s030__body
```

Что здесь важно знать:

- **Канал выбирается по `kind` трека**: `bgm` → штатный `music`, `amb` → канал `ambient` (`scenes.py:326`), который регистрирует `045_audio.rpy:13` (`renpy.music.register_channel("ambient", mixer="music", loop=True, tight=True)`). Раньше эмбиенс пришлось бы играть на `music`, вытесняя музыку, — теперь они сосуществуют.
- **Незнакомый трек — ошибка компиляции**: `music bgm/x: трек 'x' не объявлен в content/audio/` (`scenes.py:316-320`). Несовпадение `kind` с префиксом декларации (`music: bgm/<id>`, а трек объявлен как `amb`) — тоже ошибка (`scenes.py:321-325`).
- **`fadeout 1.0 fadein 1.0` захардкожены**, менять нечем — только правкой `scenes.py`.
- **Клауза `if_changed` не эмитится**, `stop music` — тоже. Поведение при одном и том же треке в соседних сценах и на конце главы проверяйте на живом материале: треков в репозитории нет, утверждать нечего.
- **SFX через `scene.yaml` не декларируются.** Звуки пишутся руками в авторском `*.scene.rpy`: `play sound door_open`. Опечатка в id **ловится на сборке**: голый идентификатор в `play`/`queue` сверяется с объявленными треками, а канал — с `kind` трека (`sfx` на `music` занял бы канал и оборвал музыку) — `scenes.py:123-149`, карта каналов `CHANNEL_KINDS` (`scenes.py:71-73`: music ← bgm/amb, ambient ← amb, sound ← sfx). Строковые литералы и выражения статически не разрешаются и пропускаются.

## 4. Зона источника: `assets_src/audio_stems/`

**Вход тракта музыки/SFX** — `assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg` (мастера озвучки живут в своей зоне `assets_src/voice/`, §8). Discovery (`pipeline.py:415-430`):

```python
# Зона звука — audio_stems (ARCHITECTURE.md:393, conventions/folder-layout.md:29):
# имя нормативное, менять его пришлось бы через ADR, поэтому код идёт к норме.
audio = root / "assets_src" / "audio_stems"
if audio.is_dir():
    for kind in ("bgm", "amb", "sfx"):
        ...
        for f in sorted(kdir.iterdir()):
            ...
            if f.suffix.lower() != ".ogg":
                rep.errors.append(f"{_rel(root, f)}: в audio_stems только .ogg")
                continue
            jobs.append(Job(f, "copy_audio", f"audio/{kind}/{f.name}", {}))
```

Подкаталоги `bgm/`, `amb/`, `sfx/` заведены в репозитории (`.gitkeep`) — конвенция видна глазами, а не только в коде. Имена `.ogg` — обязательный slug `^[a-z][a-z0-9_]*$`; нарушение = ошибка сборки, а не молчание.

**Что здесь было сломано (история, чтобы не повторить).** Код искал `assets_src/audio/` — каталога с таким именем в репозитории нет и не было, `is_dir()` возвращал `False`, и ветка `copy_audio` не срабатывала **никогда**: звук не мог попасть в игру никаким путём. Расхождение прожило долго, потому что арбитра у него не было: `vn content lint --layout` сверяет 10 обязательных каталогов (`lint.py:21-33`), `assets_src` в списке нет вообще — ни одно из двух имён не проверялось.

**Почему чинили код, а не документы.** Имя `audio_stems` — нормативное: `docs/ARCHITECTURE.md:393` (дерево репозитория) и `../conventions/folder-layout.md:29`. Переименование зоны потребовало бы ADR и правки обоих документов; правка кода — одна строка и сходится с тем, что уже лежит на диске. Регрессия закрыта тестом `test_audio_stems_branch_copies_ogg` (`../../tools/vn/tests/test_assets.py`): `.ogg` в `assets_src/audio_stems/bgm/` обязан появиться в `game/assets/audio/bgm/`.

**Оставшаяся шероховатость — семантика имени.** «Stems» в звуковой индустрии — это многодорожечные исходники сведения (проекты DAW, WAV-мастера), а конвейер ждёт **финальный `.ogg`** для побайтового копирования (`pipeline.py:636` — байты как есть, без транскода). Пока зона одна, и правило простое:

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
| Голос | **моно** | 32–48 kbps | `.opus` 96k / −19 LUFS — делает конвейер (`voice_opus`, §8), мастера сдавайте wav/flac |
| Мастера | — | FLAC/WAV | `assets_src/audio_stems/`, **вне git** |

Opus заметно компактнее Vorbis при том же качестве (рекомендация VN-сообщества: https://vndev.wiki/Guide:Audio_Formats, там же — оговорка про чуть более дорогой декод). Для нас это аргумент в пользу `audio@2` в будущем, но не повод обходить схему сегодня.

**Зацикливание.** Ren'Py умеет задавать точки прямо в имени файла — свойства `from`, `loop`, `to` документированы по отдельности, например `play music "<loop 6.333>bgm.ogg"`. Комбинированная форма `<from X loop Y to Z>` в документации примером не показана — проверяйте, прежде чем закладываться. Есть также `"<silence 3.0>"` и `"<sync channelname>track.ogg"`.

**Точка лупа в нашем конвейере:** `loop_start` из `audio@1` эмитится штатным префиксом — `define audio.<id> = "<loop N>assets/audio/…"` (`compile.py:383-386`), движок сам зацикливает с указанной секунды. Поле `loop` (boolean) по-прежнему не читается — каналы `music`/`ambient` зациклены по умолчанию. Если материал позволяет, всё равно предпочитайте луп, срезанный в самом файле по нулевому пересечению: `<loop N>` не спасает от щелчка на стыке, если волна в точках стыка не совпадает.

Каналы и микшеры: штатные `music` / `sound` / `voice` плюс наш канал `ambient` (`045_audio.rpy:13` — `register_channel("ambient", mixer="music", loop=True, tight=True)`: громкость эмбиенса регулируется слайдером музыки, `tight` даёт бесшовный кроссфейд при смене файла). Дакинг под голос — штатный `config.emphasize_audio_*` (`045_audio.rpy:18-20`): пока звучит канал `voice`, остальные каналы приглушаются до 0.6 за 0.5 с; без озвучки конфиг безвреден. Три слайдера в настройках (`core_screens.rpy:283-287`, строки `ui.prefs.volume{,_music,_sound,_voice}` в `content/ui/strings.yaml`) — слайдер «Голос» управляет микшером озвучки (§8).

## 6. Нормализация громкости — делать до `assets_src/`

**Статус в конвейере: NOT IMPLEMENTED для bgm/amb/sfx.** ARCHITECTURE.md:1181 обещает, что аудио «проходит тот же компилятор (loudnorm; выход — `.ogg`)». Реально `copy_audio` — это побайтовая копия. Значит, **нормализованным файл должен приезжать в `assets_src/audio_stems/` уже готовым** — иначе разнобой громкости между 40 треками из четырёх генераторов уедет в билд как есть. Исключение — голос: ветка `voice_opus` нормализует каждый дубль однопроходным `loudnorm I=-19:TP=-1.5:LRA=11` при транскоде в Opus 96k (`voice.py:289-308`, §8) — мастера дублей класть в `assets_src/voice/` можно сырыми.

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

## 8. Озвучка — IMPLEMENTED (кроме `vn voice tts`)

Голосовой контур §4.9/C5 работает насквозь: манифест → мастер → транскод → voice-оператор в генерате → рантайм-резолвер → релизный гейт. Демо в репозитории: `content/chapters/ch01_awakening/voice/ru.voice.yaml` покрывает все реплики ch01 черновыми (`draft`) дублями, мастера — `assets_src/voice/ru/ch01/*.wav`.

**Источник истины — voice-манифесты** `content/chapters/chNN_slug/voice/<lang>.voice.yaml` (схема `voice@1`, шард глава × язык — merge-конфликтов между главами и языками нет):

```yaml
schema: voice@1
chapter: ch01
lang: ru
lines:
  ch01_s010_0001: {status: draft}            # draft = TTS/черновой дубль -> WARN в гейте
  ch01_s010_0002: {status: final, actor: aria}
```

Ключи `lines` — те же стабильные say-id, которые `vn loc keys` дописывает в авторский `.rpy` (формат `^ch\d{2}_s\d{3}_\d{4}$`, см. [Локализация](14-localization.md)): озвучка не отвязывается от реплики ни правкой текста, ни правкой перевода. `config.auto_voice` **сознательно не используется** (норма G8): его id — хэш от label+текста, любая правка реплики молча отвязала бы записанный дубль.

**Файлы.** Мастера дублей — `assets_src/voice/<lang>/<chNN>/<line_id>.(wav|flac|ogg|opus)` (`voice.py:38,123-130`). Ветка `voice_opus` ассет-конвейера (`pipeline.py:432-466`, транскод `voice.py:289-308` — ffmpeg, Opus 96k, однопроходный loudnorm −19 LUFS / TP −1.5) кладёт их в `game/assets/voice/<lang>/<chNN>/<line_id>.opus`. Путь шардирован по главе, чтобы тысячи файлов не легли в один каталог.

**Компилятор** (`compile.py:985-1005`, `scenes.py:283-300`) собирает множество реплик, покрытых хотя бы одним языком, и в копии авторского текста вставляет перед каждой из них `voice vn.voice_path("<line_id>")` — voice-оператор один, язык выбирает рантайм.

**Рантайм** — `vn.voice_path()` в `game/framework/00_core/045_audio.rpy:26-45`: файл текущего языка → деградация до языка оригинала → `""` (falsy → voice-оператор движка = no-op, закреплено контракт-тестом engine_compat). Не установлен voice-пак / нет дубля — реплика просто молчит, без падения. Плюс дакинг: пока канал `voice` звучит, остальные приглушаются (§5).

**CLI** (`cli.py:1226-1311`):

```bash
vn voice manifest ch01 --lang ru -o ch01_ru.csv   # лист записи для актёра/студии
                                                  #   (id, кто, текст, контекст, статус; --char — фильтр)
vn voice import takes/ --lang ru [--draft]        # разложить дубли <line_id>.<ext> по assets_src/voice/
                                                  #   и дописать манифесты; импорт атомарен
vn assets build                                   # транскод voice_opus -> game/assets/voice/
vn voice validate --report                        # манифесты<->ledger<->мастера: сироты в обе стороны,
                                                  #   драфты, дыры покрытия, сводка по главам и языкам
vn voice tts                                      # TTS-черновики: ЗАГЛУШКА фазы 2, exit 3 (cli.py:1278-1281)
```

**Валидация и гейт.** `vn voice validate` (`voice.py:133-187`) ловит: line_id вне ledger главы, манифест без мастера, мастер-сироту без строки манифеста, путь вне конвенции. В `vn release validate` (`release.py:464-478`): структурные ошибки и **дыры покрытия в озвученных главах = FAIL** (реплика без дубля посреди озвученной главы слышна игроку как обрыв), **драфты = WARN**.

**Что осталось NOT IMPLEMENTED:** `vn voice tts` (черновики для непокрытых реплик — фаза 2) и поставка `voice/<lang>/` отдельными voice-паками/Steam-депотами (сегодня opus-файлы едут в основном дистрибутиве; `vn pack build` ассеты не пакует — [30-packs-and-dlc.md](30-packs-and-dlc.md)). Рантайм к пакам уже готов: отсутствующий файл — no-op.

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
| `assets_total_mb` | **20000 МБ** (ADR-0012 поднял с 500) | `project.yaml:61`, `../../tools/vn/src/vn/release.py:35-38` | всё `game/assets/` целиком (спрайты + фоны + CG + видео + аудио) |
| `video_total_mb` | 300 МБ | там же | только `game/assets/mov/` — то есть аудио конкурирует со статикой за остаток |
| **ADR-0004 (в редакции ADR-0012): бинари в `assets_src/` мимо LFS** | error на каждый файл мимо LFS + error на 50 МБ таких файлов суммарно; **warn-порога нет** | `lint.py:422-452` | `.ogg` и wav-мастера озвучки покрыты `.gitattributes:26-27`, поэтому под порог не идут; файл с расширением вне правил LFS даст ошибку сразу |

Сейчас в `assets_src/` **0.126 МБ** бинарей (10 демо-PNG + один mp4). Считаем по формуле `размер ≈ битрейт × длительность / 8`:

| | Длит. | Битрейт | Размер | Сколько до порога ADR-0004 |
|---|---|---|---|---|
| BGM-трек | 3 мин | ~160 kbps стерео | ≈ 3.5 МБ | в LFS порог ADR-0004 не расходуется вовсе; ограничение — `video_total_mb`/`assets_total_mb` бюджеты G19 |
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
    loop_start: 6.333    # опционально: эмитится как "<loop 6.333>..." — луп с этой секунды
    volume: 0.8          # опционально: клауза volume у play-оператора сцены
```

Поле `loop` (boolean) писать можно, но оно игнорируется — каналы music/ambient зациклены и так.

**3. Подключите к сцене** — либо декларативно, либо руками:

```yaml
# в *.scene.yaml — музыка и/или эмбиенс сцены (играют одновременно)
music: bgm/market_theme
ambient: amb/rooftop_wind
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
- [ ] `vn content lint` зелёный: каждый новый `.ogg`/`.wav` покрыт правилом LFS в `.gitattributes`
- [ ] Прослушано в игре на дефолтных позициях микшеров

## Чего НЕ делать

- **Не класть `.ogg` мимо `assets_src/audio_stems/{bgm,amb,sfx}/`** — других зон звука конвейер не знает (§4). Симптом — пустой `game/assets/audio/` и полное молчание сборки.
- **Не править `game/generated/registry/audio.gen.rpy` и `game/assets/audio/`** — обе зоны производные, перезапишет ближайший `vn build` / `vn assets build`.
- **Не писать сырые пути в `play`-операторах** (`play music "assets/audio/bgm/x.ogg"`). ARCHITECTURE.md:1181 объявляет это запрещённым, но линтера на это нет — запрет держится только на вашей дисциплине, и он правильный: сырой путь ломает единый неймспейс `define audio.*` и переименование файла.
- **Не рассчитывать на поле `loop` в `audio@1`** — оно не читается (в отличие от `loop_start` и `volume`). И помните: `volume` применяется только к play-операторам, эмитируемым из `music:`/`ambient:` сцены, — рукописный `play sound <id>` его не получает.
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
vn voice validate --report # озвучка: манифесты <-> ledger <-> мастера, покрытие
vn build                   # полный проход: lint -> ассеты -> генерат -> tl
vn build --check           # CI-режим: ничего не пишет, краснеет на несвежем
vn play                    # слушаем в игре
python -m pytest tools/vn/tests -q
```

Отрицательный тест на связность: впишите в сцену `music: bgm/nonexistent` и запустите `vn build` — должно упасть с `трек 'nonexistent' не объявлен в content/audio/`.

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
| **Читать перед изменением** | `../../tools/schemas/audio@1.schema.json`, `../../tools/schemas/voice@1.schema.json`, `../../tools/vn/src/vn/voice.py`, `../../tools/vn/src/vn/content/compile.py:377-391,835-852,985-1005`, `../../tools/vn/src/vn/content/scenes.py:71-73,123-149,283-331`, `../../tools/vn/src/vn/assets/pipeline.py:415-466`, `../../game/framework/00_core/045_audio.rpy`, `../../tools/schemas/scene@1.schema.json`, `../ARCHITECTURE.md` §2.9, §4.9, §5.9.3 |
| **Не трогать** | `game/generated/registry/audio.gen.rpy` (генерат), `game/assets/audio/` и `game/assets/voice/` (генерат), `game/tl/` — всё перезаписывается сборкой |
| **Зависимости** | Новый id трека → `audio.gen.rpy` → `play music/ambient` в обёртках сцен. Смена паттерна `file` в `audio@1` → новая схема `audio@2` + миграция деклараций. Правка имени зоны `audio_stems` → инвалидация ключей кэша `copy_audio` и рассинхрон с ARCHITECTURE.md и `../conventions/folder-layout.md`. Voice-манифесты → ledger локализации (`vn loc keys`) → инжекция voice-операторов → релизный гейт. Любые файлы в `assets_src/` мимо LFS → счётчик ADR-0004 в `lint.py:375-399` |
| **Валидация** | `vn content lint` → `vn assets build` → `vn voice validate --report` → `vn build` → `vn build --check`; `python -m pytest tools/vn/tests -q` |
| **Частые ошибки** | 1) Класть `.ogg` мимо `assets_src/audio_stems/{bgm,amb,sfx}/` — другой зоны у `copy_audio` нет, а молчаливо пропущенный файл выглядит как зелёная сборка. 2) Верить полю `loop` — схема его принимает, эмиттер игнорирует (`loop_start` и `volume` при этом работают). 3) Считать `bgm/`/`amb/` в `music:`/`ambient:` декоративными — kind трека обязан соответствовать полю и каналу, иначе ошибка компиляции. 4) Ожидать проверки существования файла из `file:` — её нет нигде, `renpy lint` в конвейере не вызывается. 5) Верить ARCHITECTURE.md:1181 про `loudnorm` в компиляторе для музыки — это целевое состояние, реально `copy_audio` копирует байты (loudnorm есть только у `voice_opus`). 6) Расширять `.ogg` до `.opus` правкой одного YAML — паттерн `audio@1` этого не пропустит. 7) Эмитить voice-операторы руками или через `config.auto_voice` — их вставляет компилятор по манифестам (G8) |
