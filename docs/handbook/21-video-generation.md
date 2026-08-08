# 21. Генерация видео

> **Статус подсистемы:** IMPLEMENTED (энкод-трек) — `assets_src/video_src/**` → `game/assets/mov/**.webm` + `mov_meta@1` + строгая валидация + `image mov … = Movie(...)` работают целиком. **Но** всё, что *до* ffmpeg, делает человек руками: вызова ComfyUI из тулинга нет, ни одного workflow-JSON в репозитории нет, а схема `video_src@1` **не применяется на пути сборки** — sidecar проверяет только линтер.
> **Отвечает на вопрос:** «Как получить движущийся кадр, превратить его в `.webm`, который Ren'Py гарантированно играет, и не выйти за 300 МБ бюджета».

Видео-трек — это один модуль `../../tools/vn/src/vn/assets/video.py` (326 строк) плюс ветка discovery в `../../tools/vn/src/vn/assets/pipeline.py:170-201` и группа команд `vn assets video` (`../../tools/vn/src/vn/cli.py:573-647`). Нормируется ADR-0006, а не ARCHITECTURE.md: слова «DAZ», «Comfy», «Wan» в ARCHITECTURE.md не встречаются ни разу, и её видео-раздел описывает **другой, непостроенный** дизайн (см. §10). Всё про статику, кэш и зоны — в [Ассеты](16-assets.md); здесь только видео.

## Быстрый ответ

```bash
# 0. окружение (ffmpeg с libvpx-vp9, ComfyUI, модели, GPU)
vn pipeline doctor

# 1. кладёте клип: assets_src/video_src/<group>/<name>.mp4  [+ <name>.video.yaml]
# 2. собираете и проверяете
vn assets video build                 # только видео-ветка, профиль full
vn assets video build --profile draft # crf 42 / cpu-used 8 / ≤720p — быстрые итерации
vn assets video validate              # все game/assets/mov/**.webm
vn assets video inspect game/assets/mov/demo/ambient.webm

# 3. образ для Ren'Py эмитит компилятор, не ассет-конвейер
vn build                              # -> image mov <group> <name> в images.gen.rpy
```

Группа обязательна: `video_src/<name>.mp4` без папки-группы — ошибка сборки (`pipeline.py:188-191`). Каждый сегмент пути и `stem` файла обязан матчить `^[a-z][a-z0-9_]*$`.

## 1. Сквозной конвейер: от кадра до `Movie` в сцене

| # | Шаг | Чем делается | Статус |
|---|---|---|---|
| 1 | Кадр-источник: DAZ Iray-рендер 1920×1080 или CG-стилл | DAZ Studio вручную ([DAZ Studio](17-daz-studio.md)) | IMPLEMENTED (декларации+провенанс) / **рендер-автоматизации нет** |
| 2 | Оживление кадра: Wan 2.2 I2V в ComfyUI GUI | человек, стоковый шаблон ComfyUI **Templates → Video** (`../pipeline/phase-0.md:174-175`) | NOT IMPLEMENTED в тулинге — ни API-клиента, ни workflow-JSON в репозитории |
| 3 | Сырой клип → `assets_src/video_src/<group>/<name>.mp4` (+ опц. `<name>.video.yaml`) | человек копирует файл | IMPLEMENTED (конвенция зоны) |
| 4 | `vn assets video build` → энкод VP9/WebM + валидация + `mov_meta@1` | `tools/vn/src/vn/assets/video.py`, `tools/vn/src/vn/assets/pipeline.py` | IMPLEMENTED |
| 5 | `game/assets/mov/<group>/<name>.webm` + `.webm.meta.json` | тот же прогон | IMPLEMENTED |
| 6 | `vn build` → `image mov <group> <name> = Movie(play=…, loop=…)` | `tools/vn/src/vn/content/images.py:89-99` | IMPLEMENTED |
| 7 | Использование: `show mov demo ambient` в сцене / запись галереи `kind: movie` | автор сцены / `content/gallery/*.gallery.yaml` | IMPLEMENTED (галерея), сцен с видео в контенте пока **ноль** |

Между шагами 2 и 3 есть провал: провенанс генеративного ассета (`vn assets provenance record`) — отдельная ручная команда, и **ни одного `*.provenance.json` в репозитории нет**. `mov_meta@1` фиксирует `src` + `src_hash` + `out_hash`, то есть цепочку «сырец → выход», но **не** «промпт/seed/модель → сырец»: поля-ссылки на провенанс в схеме нет (ADR-0006 §2 обещает продолжение цепочки — PARTIALLY IMPLEMENTED).

Кэш и инвалидация (норма G13): ключ = `blake3(f"{src_hash}:{transform}:{version}:{profile}")` (`pipeline.py:307-309`), а для видео `src_hash = blake3(байты клипа + b"\x00" + байты sidecar)` (`pipeline.py:297-301`) — **правка `.video.yaml` инвалидирует выход**, правка пресета в коде — нет, для неё надо руками бампнуть `video2webm` в `TRANSFORMS` (`pipeline.py:38-46`). У видео два выхода в одной ветке: `only_transforms={"video2webm"}` автоматически добавляет `mov_meta`, чтобы `.webm` и `.meta.json` не разъехались (`pipeline.py:274-275`).

## 2. Чем генерировать движение (данные ресёрча 2026)

### 2.1 Железо: что реально считает RTX 5080 16 ГБ

Карта владельца — 16 ГБ GDDR7 (не 32; 32 ГБ — это 5090). Это отсекает часть моделей на входе и делает дистилляцию обязательной, а не желательной.

| Модель / стек | Что умеет | Подключено у нас | Статус в конвейере |
|---|---|---|---|
| **Wan 2.2 I2V-A14B** (Apache-2.0) | I2V-«спина» конвейера: подаёте свой DAZ-кадр, получаете движение с сохранением идентичности | **Да** — обе половины MoE в манифесте моделей (`tools/comfyui-models.yaml`) | IMPLEMENTED (провижининг моделей) |
| **LightX2V 4-step LoRA** (high+low) | дистилляция: 4 шага вместо ~20 | **Да**, `required: true`, комментарий в манифесте: «без неё клип считается в ~10 раз дольше» | IMPLEMENTED (провижининг) |
| Wan 2.2 TI2V-5B | одна плотная модель, официально «5 c 720p менее чем за 9 минут» на потребительской карте | нет в манифесте | не используется |
| Wan-Animate-2, Wan-Dancer | перенос движения с драйвер-видео / танцы | нет | не используется |
| HunyuanVideo 1.5 (8.3B) | быстрый previz, «14 ГБ с оффлоадом» | нет | не используется; лицензия Tencent имеет территориальные оговорки |
| LTX-2 / 2.3 | видео+звук одним проходом | нет | нода-репо требует **32 ГБ VRAM** — мимо нашего железа |
| LongCat-Video-Avatar 1.5 (MIT) | talking-head/lip-sync, обобщается на стилизованных персонажей | нет | см. §2.4 |
| SeedVR2 (Apache-2.0) | апскейл/реставрация видео одним шагом | нет | см. §2.3 |
| ComfyUI-Frame-Interpolation (RIFE/FILM) | 12–16 fps → 24/30 fps | нет | см. §2.3 |
| RealESRGAN x4plus | апскейл **кадров/стиллов** | **Да**, `required: false` в манифесте | IMPLEMENTED (провижининг) |
| bigASP v2, Civitai NSFW-LoRA (пара high/low) | img2img-полировка и NSFW-motion | **Да**, опциональные; `commercial_use: restricted` / `unknown`, `auth: civitai_key` | IMPLEMENTED (провижининг), **юридически не разобрано** |

Важно про границу: `vn pipeline models` и `vn pipeline doctor` умеют **скачать и проверить** модели — и всё. Запуска генерации из тулинга нет: ComfyUI открывается руками, воркфлоу берётся стоковый, PNG/MP4 сохраняется руками. Это NOT IMPLEMENTED, а не «пока не описано».

**Ориентиры по времени** (из ресёрча, не измерено на этой машине): 5–12 минут на 5-секундный 720p-клип с 14B-модели на тюненой 16 ГБ-карте; 1–3 минуты с 5B/дистиллированных. Приёмочный критерий проекта мягче: 480p/49 кадров с LightX2V, клип **≤ 15 мин без OOM** (`../pipeline/phase-0.md:174-175`).

### 2.2 Blender как детерминированная альтернатива

Для камеры и частиц AI-генерация — худший инструмент. Берите Blender, когда нужно:

- медленный push-in / pan по уже утверждённому CG-фону (AI перерисует детали при движении, Blender — нет);
- параллакс по фону, который встречается в десятках сцен (детерминизм = фон одинаков везде);
- дождь, снег, пылинки, лучи, светлячки — частицы лупятся идеально по построению;
- любой луп с нулевым стыком и нулевым дрейфом яркости;
- альфа-канал (RGBA PNG-секвенция → side-by-side для `side_mask`);
- всё, что придётся перерендерить в другом разрешении.

Не берите Blender для органики: волосы, ткань, дыхание, вода, огонь — там генерация Wan дешевле в человеко-часах. Практика из ресёрча: рендерить **PNG-секвенцию**, а не видео, и кодировать её ffmpeg'ом — встроенный энкодер Blender даёт меньше контроля над pix_fmt.

**Статус в проекте: NOT IMPLEMENTED.** Blender нигде не упомянут — ни в `tools/`, ни в `vn pipeline doctor`, ни в ADR. Сборки секвенции кадров в клип в тулинге тоже нет (§10): PNG-секвенцию придётся склеивать ffmpeg'ом вручную **до** того, как класть `.mp4` в `assets_src/video_src/`.

### 2.3 Интерполяция и апскейл

Экономика 16 ГБ-карты: генерировать мелко и коротко, добирать качество постобработкой. Порядок из ресёрча — **сначала апскейл/реставрация, потом интерполяция, потом энкод** (интерполировать первым — удвоить работу апскейлеру и запечь смазы).

| Приём | Инструмент из ресёрча | Когда | Статус у нас |
|---|---|---|---|
| Апскейл 480p → 720p/1080p | SeedVR2 (нода `numz/ComfyUI-SeedVR2_VideoUpscaler`) | финишный проход по каждому клипу; на 12–16 ГБ — fp8 + BlockSwap | NOT IMPLEMENTED |
| Интерполяция 12–16 → 24 fps | ComfyUI-Frame-Interpolation, RIFE VFI | всегда на плавных ambient-лупах; **не** там, где быстрые перекрытия/волосы/частицы — RIFE их смазывает | NOT IMPLEMENTED |
| Апскейл кадра (не видео) | RealESRGAN x4plus | стиллы и отдельные кадры | модель в манифесте, вызова нет |

Наш энкод-пресет fps **не меняет** по умолчанию (`fps: null` = fps источника), так что интерполяция должна произойти до попадания клипа в `assets_src/`. Единственный fps-рычаг конвейера — поле `fps` в sidecar, оно вставляет фильтр `fps=<n>` (см. §4).

### 2.4 Lip-sync / talking-head

Актуальный ответ 2026 по ресёрчу — **LongCat-Video-Avatar 1.5** (MIT, обобщается на аниме/стилизацию, 8-шаговая дистилляция, INT8-режим для малой VRAM). Осторожно с **Sonic**: его лицензия **CC BY-NC-SA 4.0, некоммерческая**, а он широко советуется в туториалах.

Применимость к этому проекту: у нас говорящие головы — **спрайты** (`layeredimage mira`, [Персонажи](10-characters.md)), а не видео. Видео-talking-head раздувает сборку и ломает бюджет `video_total_mb`. Статус: **NOT IMPLEMENTED и не планируется** — ни одной строки про липсинк в `tools/`, ADR или манифесте моделей. Про озвучку как таковую: `vn voice *` — заглушка фазы 2 (`cli.py:1087`).

## 3. Бесшовные лупы

Ключевой раздел: конвейер измеряет качество лупа и краснеет предупреждением, но починить его может только генерация.

### 3.1 Как сгенерировать

| Техника | Суть | Когда |
|---|---|---|
| **FLF2V: первый кадр = последнему** | в ComfyUI-воркфлоу Wan 2.2 первому и последнему кадру подаётся **одна и та же** картинка; затем нодой `ImageSelector`/`ImageFromBatch` **выбросить последний кадр** — иначе кадр N дублирует кадр 0 и на каждом обороте будет однокадровый рывок | основной путь, лучшее качество |
| **VACE loop-closer** | синтезировать переход «конец → начало» для уже готового клипа; есть официальный шаблон-воркфлоу «Video to Seamless Loop Converter» | клип уже снят/сгенерирован |
| **Ping-pong** | приклеить реверс: математически бесшовно, стоит ноль | блики воды, качание ткани, пламя свечи, дыхание. **Заметно неправильно** на направленном движении: дождь, снег, дым |
| **Crossfade wrap** | наложить последние N кадров на первые с растворением | только расфокусированные фоновые планы; на контрастных краях даёт призраки |

Общая грабля всех четырёх: даже при идентичных первом/последнем кадрах диффузия дрейфует по **глобальной яркости и зерну**, и стык читается как ступенька яркости, а не как скачок геометрии. Чинить пост-обработкой (luma-match по стыку), а не перегенерацией. Держите лупы в районе 5 c / 121 кадра — дальше рассыпается временная когерентность; длинную атмосферу делают циклом короткого клипа.

### 3.2 Как проект это измеряет: `loop_seam`

`loop_seam` — RMS-разница **первого и последнего кадров** в шкале 0..255 (`video.py:173-197`):

1. ffmpeg извлекает первый кадр (`-frames:v 1`) и последний (`-sseof -0.2 -update 1`) в `.vncache/video-tmp/loop_first.png` / `loop_last.png`;
2. PIL: `convert("L").resize((64,64))` → серый 64×64 → RMS по 4096 байтам → `round(rms, 1)`.

| Значение | Что означает |
|---|---|
| `0.0 … 18.0` | стык в пределах нормы; порог `LOOP_SEAM_WARN = 18.0` (`video.py:29`) |
| `> 18.0` | **warning** «стык лупа заметен (RMS … > 18.0) — первый/последний кадры расходятся». Сборку **не** валит, но всплывёт в релизном гейте как WARN |
| `null` | `loop: false` в sidecar (метрика не считалась) **или** кадры не извлеклись (ffmpeg упал — метрика не валит сборку, `video.py:187-188`) |
| реальный пример | `game/assets/mov/demo/ambient.webm.meta.json`: `"loop_seam": 2.1` — эталон «хороший стык» |

Метрика грубая сознательно: 64×64 в градациях серого поймает ступеньку яркости и грубое расхождение композиции, но **не** заметит сдвиг мелкой детали. Зелёный `loop_seam` не заменяет просмотр глазами: соберите проверочный ролик из трёх оборотов и посмотрите.

Плюс отдельное предупреждение по длительности: луп длиннее `MAX_LOOP_DURATION_S = 30.0` c → warning «точно луп?» (`video.py:30, 239-241`).

### 3.3 Не-лупы

Если клип — не луп (одноразовая вставка, переход), поставьте в sidecar:

```yaml
schema: video_src@1
loop: false
```

Последствия ровно три: стык не измеряется, `loop_seam: null` в meta, и компилятор эмитит `Movie(..., loop=False)` (`images.py:95-96`). **Внимание:** экран галереи это игнорирует и всегда играет `loop=True` (`game/framework/20_ui/screens/gallery.rpy:107`) — расхождение реально, см. §8.

## 4. Sidecar `<name>.video.yaml` — схема `video_src@1`

Файл опционален; имя выводится как `<stem> + ".video.yaml"` (`video.py:25`, `pipeline.py:194`). Источник истины — `../../tools/schemas/video_src@1.schema.json` (`additionalProperties: false`, `required: ["schema"]`).

| Ключ | Тип / диапазон | Дефолт | Что делает |
|---|---|---|---|
| `schema` | const `video_src@1` | **обязателен** | норма G16 |
| `loop` | boolean | `true` | считать стык + `loop=` в эмитируемом `Movie()` |
| `keep_audio` | boolean | `false` | оставить звук: `-c:a libopus -b:a 96k` вместо `-an` |
| `fps` | number \| null, `exclusiveMinimum: 0` | `null` | добавляет фильтр `fps=<n>`; `null` = fps источника |
| `max_height` | integer \| null, `minimum: 16` | `1080` | потолок высоты (только даунскейл); профиль `draft` дожимает до 720 |
| `crf` | integer \| null, `4..63` | `null` | VP9 CRF; `null` → 30 (full) / 42 (draft) |

Дефолты продублированы в коде: `DEFAULT_OPTS` (`video.py:33-39`). Сборка читает **только** ключи из `DEFAULT_OPTS` (`video.py:77-79`) — незнакомый ключ молча игнорируется энкодером.

Весь реальный sidecar в репозитории — `assets_src/video_src/demo/ambient.video.yaml`, 31 байт:

```yaml
schema: video_src@1
loop: true
```

### ЧЕСТНО: схема не применяется на пути сборки

`load_opts(sidecar, registry=None)` умеет валидировать документ по реестру схем (`video.py:64, 73-76`), но **единственный вызов передаёт только путь**:

```python
opts, opt_errors = videomod.load_opts(sidecar)      # tools/vn/src/vn/assets/pipeline.py:195
```

Ветка `registry` — мёртвый код. Практические следствия:

- битый или невалидный sidecar (опечатка в ключе, `crf: 200`, отсутствующий `schema:`) **соберётся молча** под `vn assets video build`;
- поймает его только `vn content lint` — он сметает `assets_src/**/*.yaml` через реестр схем (`tools/vn/src/vn/content/lint.py:96-102`), а значит и `vn build`, который начинается с линта (`cli.py:93-100`);
- вывод для процесса: **`vn assets video build` — не проверка. Перед коммитом гоняйте `vn build` или как минимум `vn content lint`.**

## 5. `.webm.meta.json` — схема `mov_meta@1`

Генерат, лежит рядом с `.webm`, пишется `json.dumps(..., ensure_ascii=False, indent=1, sort_keys=True)` (`pipeline.py:381-382`), перегенерируется только когда `.webm` только что записан или meta отсутствует (`pipeline.py:369`). Собирается в `video.py:252-272`. Это **контракт** для эмиттера `Movie`-образов и для `vn assets video validate`.

| Поле | Тип | Обяз. | Значение в `game/assets/mov/demo/ambient.webm.meta.json` |
|---|---|---|---|
| `schema` | const `mov_meta@1` | да | `mov_meta@1` |
| `id` | string, `^mov/[a-z0-9_/]+$` | да | `mov/demo/ambient` (это `out_rel` минус `.webm`) |
| `loop` | boolean | да | `true` — **читается компилятором**, попадает в `Movie(loop=…)` |
| `keep_audio` | boolean | нет | `false` — используется `opts_from_meta` при повторной валидации |
| `width` | integer ≥ 2 | да | `256` |
| `height` | integer ≥ 2 | да | `144` |
| `fps` | number > 0 | да | `24.0` |
| `duration_s` | number > 0 | да | `2.0` |
| `size_bytes` | integer ≥ 1 | да | `5683` |
| `loop_seam` | number \| null | нет | `2.1` (см. §3.2) |
| `src` | string | нет | `assets_src/video_src/demo/ambient.mp4` |
| `src_hash` | `{algo: "blake3", hex}` | нет | `308320cbab9b831c…` — хэш **клипа + sidecar** |
| `out_hash` | `{algo: "blake3", hex}` | нет | `7c4621cbcbb88891…` |
| `transform` | string | да | `video2webm@1` |
| `profile` | enum `full` \| `draft` | да | `full` |

Meta — **вторая запись в манифесте сборки** `.vncache/assets-manifest.json` под трансформацией `mov_meta@1` (`pipeline.py:383-389`), поэтому её удаление вручную = «осиротевший выход» на следующей сборке. Файл в git не попадает: `game/assets/` целиком в `.gitignore`.

Из чего meta **не** состоит: ни ссылки на провенанс, ни промпта, ни seed'а, ни модели. Всё это живёт (точнее, должно жить) в `*.provenance.json` рядом с **сырцом**, и таких файлов в репозитории ноль.

## 6. ffmpeg: точный энкод

### 6.1 Команда как есть

`encode_video` (`video.py:114-127`) собирает:

```python
cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
       "-i", str(src), *encode_args(opts, profile), "-f", "webm", str(out)]
```

`encode_args` (`video.py:85-111`) вставляет между `-i` и выходом:

```python
args = [
    "-vf", ",".join(filters),
    "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
    "-row-mt", "1", "-cpu-used", str(cpu_used),
    "-pix_fmt", "yuv420p",
]
```

и затем `["-c:a", "libopus", "-b:a", "96k"]` при `keep_audio`, иначе `["-an"]`.

Полностью развёрнуто, профиль `full`, без sidecar:

```
ffmpeg -y -hide_banner -loglevel error -i <src>
  -vf scale=-2:2*trunc(min(1080\,ih)/2)
  -c:v libvpx-vp9 -b:v 0 -crf 30 -row-mt 1 -cpu-used 2 -pix_fmt yuv420p -an
  -f webm .vncache/video-tmp/<stem>.tmp.webm
```

| Флаг | Зачем именно так |
|---|---|
| `-vf scale=-2:2*trunc(min(1080\,ih)/2)` | даунскейл **только вниз** (`min` с высотой источника), пропорции сохраняются, обе стороны принудительно чётные — этого требует `yuv420p` |
| `fps=<n>` (перед `scale`, только если задан) | нормализация кадровой частоты; фильтры идут строго в порядке `fps` → `scale` (`video.py:96-100`) |
| `-c:v libvpx-vp9` | захардкожен, альтернативной ветки нет |
| `-b:v 0 -crf N` | режим постоянного качества (1 проход). Для ассетов нужен **пол качества на файл**, а не битрейт-бюджет потока |
| `-row-mt 1` | построчная многопоточность libvpx |
| `-cpu-used N` | компромисс скорость/качество: 2 (full) / 8 (draft) |
| `-pix_fmt yuv420p` | Ren'Py: «YUV444 movies are not hardware accelerated». Без явного флага PNG-секвенции и ProRes уводят libvpx в `yuv444p` — и вы получаете «в VLC норм, в игре тормозит» |
| `-an` | звук вырезан (см. §6.4) |
| `-f webm` | контейнер задаётся явно, а не по расширению |

Результат пишется во временный файл в `.vncache/video-tmp/`, читается байтами, `unlink`, и байты уходят в контентно-адресуемый кэш и в `game/assets/` (`video.py:118, 125-126`). Провал (`returncode != 0`, или файла нет, или он нулевой) → `VideoError` с последними 600 символами stderr.

**Чего в команде НЕТ** (и не выдумывайте, что есть): `-deadline`, `-tile-columns`, `-g`, `-lag-in-frames`, `-auto-alt-ref`, `-threads`, `-pass`. Только перечисленные выше флаги.

### 6.2 Профили

| | `full` | `draft` |
|---|---|---|
| CRF (если sidecar не задал) | `30` (`video.py:94`) | `42` (`video.py:91`) |
| `-cpu-used` | `2` | `8` |
| Потолок высоты | `max_height` или `1080` | `min(max_height, 720)` |
| `crf` из sidecar | уважается | уважается |

Профиль входит в ключ кэша (`pipeline.py:308`), пишется в `mov_meta.profile` и в манифест сборки, так что full- и draft-блобы сосуществуют. **Дыра:** релизный гейт про профиль не знает — в `release.py` нет ни одного упоминания `profile`. Draft-энкод 720p/CRF 42 пройдёт `vn release validate` как ни в чём не бывало. Дисциплина ручная: перед релизом `vn assets video build` (без `--profile draft`).

### 6.3 Почему VP9/WebM, а не MP4/H.264

Документация Ren'Py перечисляет как играбельные AV1, VP9, VP8, Theora, MPEG-4 part 2, MPEG-2, MPEG-1 в контейнерах WebM/Matroska/Ogg/AVI/MPEG и рекомендует дословно: «When in doubt, and especially for commercial games, we recommend using AV1, VP9, VP8, or Theora; Opus or Vorbis; and WebM, Matroska, or Ogg» — то есть H.264/MP4 не в списке рекомендованных из-за патентной стороны. Плюс два инженерных пункта: YUV444 не аппаратно-ускоряется, полноэкранное видео эффективнее, и одновременные `Movie` обязаны иметь **одинаковый fps**.

Наш докстринг формулирует это так: «контейнер WebM + libvpx-vp9 + yuv420p — единственная комбинация, которую движок играет на всех платформах без сюрпризов» (`video.py:10-12`). AV1 Ren'Py тоже играет (с 8.1.0), и по ресёрчу даёт заметную экономию байт — но **у нас не реализован** (§10).

Практический нюанс железа: NVENC **не умеет VP9** ни на одном поколении, так что `libvpx-vp9` — чистый CPU, и RTX 5080 в энкоде не помогает вообще. Планируйте wall-clock под процессор.

### 6.4 Почему звук вырезается

По умолчанию `-an`: лупы немые (ADR-0006 §1). Причины конкретные:

- Ren'Py не умеет кроссфейдить звуковую дорожку видео — на точке лупа будет щелчок;
- аудио-канал движка даёт синтаксис точек лупа (`play music "<loop 6.333>song.opus"`), которого у видеодорожки нет;
- звук в видео дублирует байты, которые уже посчитаны в аудио-бюджете.

`keep_audio: true` включает `libopus @ 96k`. Берите его только для одноразовых не-лупов, где звук синхронен картинке. И помните обратную проверку: **аудиодорожка в файле при `keep_audio: false` — это error сборки**, а не предупреждение (`video.py:231-233`).

## 7. Валидация и бюджеты

### 7.1 `vn assets video validate` — полный список условий

`validate_output(path, opts, workdir, file_budget_mb)` (`video.py:200-249`) возвращает `(errors, warnings, summary)`. **Errors валят сборку** (`pipeline.py:373-375`) и валят команду с exit 1 (`cli.py:625-626`).

Errors (красное):

| Условие | Код |
|---|---|
| ffprobe не смог прочитать файл / нет видеопотока | `video.py:137-139, 157` |
| контейнер не `webm` и не `matroska` | `video.py:212-213` |
| кодек не `vp9` | `video.py:214-215` |
| `pix_fmt` не `yuv420p` и не `yuva420p` | `video.py:220-221` |
| нечётная ширина или высота | `video.py:222-223` |
| `duration_s < 0.2` — «файл битый/пустой» | `video.py:227-228` |
| есть аудиодорожка при `keep_audio: false` | `video.py:231-233` |
| `size_bytes > video_file_mb × 1024 × 1024` | `video.py:234-236` |

Warnings (жёлтое, никогда не валят):

| Условие | Код |
|---|---|
| `pix_fmt == yuva420p` — «в Ren'Py прозрачность через side-mask, проверьте отдельно» | `video.py:217-219` |
| height > 1080 или width > 1920 | `video.py:224-226` |
| fps дальше 0.06 от `(23.976, 24.0, 25.0, 30.0, 60.0)` | `video.py:31, 229-230` |
| луп длиннее 30 c | `video.py:239-241` |
| `loop_seam > 18.0` | `video.py:244-246` |

Три места, где эти правила срабатывают:

1. **сборка** — по каждому вновь записанному файлу, с опциями из sidecar (`pipeline.py:365-375`);
2. **`vn assets video validate [paths…]`** — без аргументов проверяет все `game/assets/mov/**.webm`; опции восстанавливаются из meta через `opts_from_meta` — оттуда берутся **только `loop` и `keep_audio`** (`video.py:275-286`);
3. **релизный гейт** — `validate_all(root, file_budget_mb)` (`video.py:289-306`), проводка в `release.py:312-321`: errors → `FAIL "видео: N ошибок"`, warnings → `WARN`, иначе `PASS "видео: собранные лупы валидны"`.

Полезный факт про вывод: настоящий ffprobe отдаёт `format_name = "matroska,webm"`, а `summarize` берёт `.split(",")[0]` (`video.py:161`) — значит **у корректного файла в выводе `inspect` будет `container: matroska`**, и это норма, а не поломка.

### 7.2 `vn assets video inspect <файл>`

`cli.py:630-647`. Печатает поля `summarize()` — `container, codec, pix_fmt, width, height, fps, duration_s, size_bytes, has_audio` — и затем **дописывает содержимое сайдкаров, если они есть**: `<file>.meta.json` (метка `meta`) и `<file>.provenance.json` (метка `provenance`). Второго в репозитории пока не бывает. Команда только читает, ничего не валидирует и не пишет. В ADR-0006 она не описана — IMPLEMENTED / UNDOCUMENTED.

### 7.3 Бюджеты

`project.yaml:6-11`:

```yaml
budgets:
  assets_total_mb: 500   # ВЕСЬ game/assets, включая mov
  video_total_mb: 300    # суммарно game/assets/mov (ADR-0006)
  video_file_mb: 40      # один луп
```

| Бюджет | Где проверяется | Кем |
|---|---|---|
| `video_file_mb` | **дважды**: внутри `validate_output` (`video.py:234-236`) и в `budget_failures` (`release.py:47-52`) | `vn build`, `vn assets video build/validate`, релизный гейт |
| `video_total_mb` | **только** `budget_failures` (`release.py:42-46`) | `vn build` (`cli.py:142, 152` → `_check_budgets`) и релизный гейт (`release.py:333-335`) |

То есть `vn assets video validate` про суммарный бюджет **не знает** — его ловит `vn build`. И держите в голове вложенность: `assets_total_mb` считает `game/assets` целиком, mov внутри. 300 МБ видео оставляют 200 МБ на всю статику.

## 8. Как видео попадает в игру

### 8.1 Образ

Компилятор сканирует `game/assets/mov/**.webm`, читает рядом лежащий `.meta.json` (без него — консервативный дефолт `{"loop": True}`) и эмитит (`tools/vn/src/vn/content/images.py:89-99`):

```python
out.append(f'image {tokens} = Movie(play="assets/{rel}", loop={loop})')
```

Реальная строка, `game/generated/registry/images.gen.rpy:15`:

```renpy
image mov demo ambient = Movie(play="assets/mov/demo/ambient.webm", loop=True)
```

Дальше это обычный образ: `show mov demo ambient`. **Ни одна сцена в `content/` сейчас на видео не ссылается** — единственный потребитель `mov/` в контенте — галерея.

Эмитятся ровно два параметра: `play=` и `loop=`. `start_image=`, `group=`, `channel=`, `side_mask=` **не эмитятся никогда**. Если они понадобятся (а `start_image` понадобится: между `show` и первым декодированным кадром реально есть прозрачная вспышка), это правка эмиттера `tools/vn/src/vn/content/images.py:96` — правка `images.gen.rpy` бессмысленна, файл перезаписывается.

### 8.2 Галерея

Подробности — в [Галерея](15-gallery.md); здесь только видео-специфика:

```yaml
  mov_ch01_ambient:
    category: videos
    kind: movie
    asset: mov/demo/ambient
    thumb: cg/ch01/rooftop_sunset
    unlock: {scene: ch01_s030}
```

- `kind: movie` ⇔ префикс `mov/` — компилятор сверяет это как **error** (`tools/vn/src/vn/content/compile.py:200-203`); расширение подставляется по префиксу: `mov/` → `.webm`, иначе `.webp` (`compile.py:142-145`).
- **`thumb:` обязателен по смыслу.** У видео нет своего превью: конвейер делает `.thumb.webp` только для CG. Без `thumb` — warning и в ячейку сетки попадёт сам `.webm`.
- `unlock: {seen_image: …}` для `kind: movie` — **ошибка компиляции**: `persistent._seen_images` про видео ничего не знает. Разблокировка видео — только по якорю сцены/флагу.
- Проигрывание: `add Movie(play=_spec["asset"], loop=True)` (`game/framework/20_ui/screens/gallery.rpy:105-107`) — **`loop=True` захардкожен**, `mov_meta.loop` игнорируется. Клип с `loop: false` в галерее всё равно зациклится.

### 8.3 NSFW

Конвенция ADR-0006: NSFW-видео живёт в `mov/nsfw/…` (сырец — `assets_src/video_src/nsfw/…`). SFW-флейворы исключают `game/assets/*/nsfw/**` на этапе distribute; глобы считаются по **реально существующим** каталогам (`release.py:191-202`). Каталога `game/assets/mov/nsfw/` сейчас нет, поэтому в обоих отгруженных `build-info.json` стоит `"exclude": []`.

## 9. Практические ориентиры и арифметика бюджета

Единственный **измеренный** артефакт в репозитории — демо: 256×144, 24 fps, 2.0 c, **5683 байта**, `loop_seam 2.1`. Он нерепрезентативен по разрешению, зато показывает форму данных.

Ориентиры ниже — арифметика из битрейтных диапазонов ресёрча (низкодинамичный 1080p ambient при CRF 30–34 ≈ **0.6–1.8 Мбит/с**), **не замеры на нашем контенте**. Диффузионное видео шумнее живой съёмки и будет ближе к верхней границе.

| Параметр | Рекомендация | Почему |
|---|---|---|
| Длительность лупа | **5 c** (до 10 c) | предел временной когерентности генерации; > 30 c даёт warning |
| fps | **24** (или 30), один на весь проект | одновременные `Movie` обязаны совпадать по fps; вне `SANE_FPS` — warning |
| Разрешение | **1080p потолок**, 720p — нормально для фонового плана | > 1080p/1920 — warning «дороже декодировать»; в draft всё равно 720 |
| CRF | 30 по умолчанию; A/B 30 / 32 / 34, брать самый высокий, который выживает | ниже CRF = больше байт, не всегда больше видимого качества |
| Вес одного лупа | целиться **≤ 5 МБ** | бюджет на файл 40 МБ — это аварийный потолок, а не цель |

Сколько лупов влезает в `video_total_mb: 300`:

| Сценарий (5 c, 1080p) | Вес одного | Влезает в 300 МБ |
|---|---|---|
| оптимистичный, 0.6 Мбит/с | ≈ 0.4 МБ | ~800 |
| середина, 1.2 Мбит/с | ≈ 0.75 МБ | ~400 |
| пессимистичный, 1.8 Мбит/с | ≈ 1.1 МБ | ~270 |
| «целевой потолок» 5 МБ | 5 МБ | **60** |
| один файл на пределе бюджета | 40 МБ | 7 |

Вывод для планирования: узкое место — не 300 МБ, а **200 МБ, остающиеся статике** внутри `assets_total_mb: 500`, и время генерации (5–12 мин на клип). Реалистичная цель на главу — единицы лупов, не десятки.

## 10. Чего НЕТ (NOT IMPLEMENTED)

| Механизм | Где обещано | Реальность |
|---|---|---|
| **Альфа-видео** (`yuva420p`, оверлей поверх сцены) | `docs/ARCHITECTURE.md:1143` (`alphaextract` + `hstack` + `side_mask=True`) | `video.py:217-219` только **предупреждает** про `yuva420p` и пропускает файл. Side-mask не собирается, `Movie(side_mask=True)` не эмитится — такой файл сыграет в игре **непрозрачным**. Тупик, не «частично» |
| **VP9 2-pass** | `ARCHITECTURE.md:1179` | только 1-pass CRF |
| **Профили `hd` / `mobile`** | `ARCHITECTURE.md:1179` (матрица full/hd/mobile) | только `full` и `draft` |
| **Нормализация громкости** (Opus 128k + `loudnorm −16 LUFS`) | `ARCHITECTURE.md:1179` | Opus **96k**, без loudnorm |
| **`renpy.movie_cutscene`-хелперы** | `ARCHITECTURE.md:1179`, «фаза 2» | нет |
| **Сборка секвенции кадров в клип** (`vfx@1`, `target: webm\|atlas`) | `ARCHITECTURE.md:1074` | схемы `vfx@1` в `tools/schemas/` нет. PNG-секвенцию склеивайте ffmpeg'ом руками до `assets_src/` |
| **AV1** | — | не заявлен и не реализован; Ren'Py его играет с 8.1.0, но наш пресет — VP9 |
| **Зона `assets_src/video/<name>/<name>.mov` + `*.meta.yaml`** | `ARCHITECTURE.md:858, 963`; дерево `:345` называет `game/assets/video/` | реальные зоны — `assets_src/video_src/<group>/` и `game/assets/mov/`. ARCHITECTURE.md **не обновлена** после ADR-0006, маркера «superseded» нет |
| **Запрет draft-артефактов в релизе** | — | `release.py` про `profile` не знает |
| **Enforcement `video_src@1` при сборке** | ADR-0006 (G16) | `load_opts` вызывается без реестра (§4) |
| **Вызов ComfyUI из тулинга, workflow-JSON** | ADR-0006 §2 подразумевает | ни HTTP-клиента, ни порта 8188, ни одного графа в репозитории |
| **Timeout у энкода** | — | `subprocess.run` без `timeout=` (`video.py:121`): зависший ffmpeg вешает сборку |
| **GC для `.vncache/video-tmp/`** | — | `vn assets cache --gc` подметает только `.vncache/assets` (`pipeline.py:449`) |

## Как добавить луп (пошагово)

```bash
# 1. окружение
vn pipeline doctor                        # ffmpeg + libvpx-vp9 + ffprobe + GPU + модели

# 2. кадр-источник: DAZ/CG-рендер 1920x1080  ->  ComfyUI (Wan 2.2 I2V + LightX2V, 4 шага)
#    первый и последний кадр = одна картинка; последний кадр выбросить нодой

# 3. клип в зону (группа обязательна, слуги ^[a-z][a-z0-9_]*$)
cp clip.mp4 assets_src/video_src/rooftop/rain.mp4
```

```yaml
# 4. опционально: assets_src/video_src/rooftop/rain.video.yaml
schema: video_src@1
loop: true
fps: 24
max_height: 1080
```

```bash
# 5. сборка + проверка
vn assets video build --profile draft     # быстрая итерация
vn assets video validate                  # смотрим loop_seam и предупреждения
vn assets video build                     # финальный full перед коммитом
vn build                                  # lint (вот тут проверится sidecar!) + image mov …

# 6. проверка результата
vn assets video inspect game/assets/mov/rooftop/rain.webm
grep "image mov rooftop rain" game/generated/registry/images.gen.rpy
```

Приёмка (`../pipeline/phase-0.md:184-185`): `.webm` + `.webm.meta.json` в `game/assets/mov/`, строка `image mov <group> <name>` в `game/generated/registry/images.gen.rpy`, `vn build: OK`.

## Как изменить пресет энкода

1. Правите `encode_args` в `../../tools/vn/src/vn/assets/video.py:85-111`.
2. **Обязательно** бампаете версию `video2webm` в `TRANSFORMS` (`../../tools/vn/src/vn/assets/pipeline.py:38-46`) — иначе кэш отдаст старые байты как свежие, и это никем не проверяется (конвенция без enforcement).
3. Прогоняете `python -m pytest tools/vn/tests/test_video.py -q` (7 тестов) — там есть `test_validate_output_budget_and_codec` и `test_sidecar_options_and_invalidation`.
4. Пересобираете: `vn assets video build` — все лупы перекодируются заново.
5. Проверяете бюджеты: `vn build` (там `_check_budgets`) и `vn release validate --flavor public`.

Меняете **пороги** валидации (`LOOP_SEAM_WARN`, `MAX_LOOP_DURATION_S`, `SANE_FPS`) — это `video.py:29-31`, бампать `TRANSFORMS` не нужно: на байты выхода они не влияют.

## Чего НЕ делать

- **Не считать `vn assets video build` проверкой.** Схема `video_src@1` на этом пути не применяется — битый sidecar соберётся молча. Проверка = `vn build` / `vn content lint`.
- **Не класть видео без группы.** `video_src/ambient.mp4` → error «видео кладутся в группу». Нужен `video_src/<group>/ambient.mp4`.
- **Не заливать `.mp4` с альфой в надежде на прозрачность.** `yuva420p` пройдёт валидацию с warning и сыграет в игре непрозрачным: Ren'Py не декодирует альфу, а side-mask у нас NOT IMPLEMENTED.
- **Не оставлять аудиодорожку «на всякий случай»** — при `keep_audio: false` это **error** сборки, а не предупреждение.
- **Не коммитить draft-энкод.** Профиль участвует в ключе кэша и в сравнении свежести: после `--profile draft` команда `vn build --check` покраснеет. Плюс релизный гейт draft **не отлавливает** — 720p/CRF 42 уедет в дистрибутив.
- **Не редактировать `game/assets/mov/**` и `.webm.meta.json` руками.** Зона производная, не в git, перезапишется. Удаление meta вручную = осиротевший выход в манифесте.
- **Не переопределять `VN_FFMPEG`/`VN_FFPROBE` кривым путём.** Битое явное переопределение возвращает `None` **без** фоллбека на PATH (`../../tools/vn/src/vn/pipeline.py:42-51`) — получите «ffmpeg не найден» при живом ffmpeg в PATH.
- **Не удивляться `container: matroska` в выводе `inspect`** — это нормальный ffprobe-ответ на корректный WebM.
- **Не полагаться на `loop: false` в галерее** — экран играет `loop=True` всегда (`gallery.rpy:107`).
- **Не смешивать fps между одновременно показываемыми `Movie`** — документация Ren'Py требует одинаковой кадровой частоты; нормализуйте через `fps:` в sidecar.
- **Не ставить видео там, где хватит статики или ATL.** Трёхкадровое «видео» хуже анимации, а каждый `Movie` на экране — декодер в реальном времени на машине игрока.
- **Не тянуть 1080p×N лупов в главу.** 300 МБ на видео вычитаются из 500 МБ на все ассеты.
- **Не ожидать, что `vn pipeline models --only <id>` просто покажет список** — при `--only` загрузка включается (см. [Ассеты](16-assets.md) и `pipeline.py`).

## Проверка

```bash
vn pipeline doctor                     # ffmpeg (VP9!), ffprobe, GPU, ComfyUI, модели
vn assets video build                  # 0 ошибок
vn assets video validate               # « ✓ ambient.webm: 256x144 24.0fps 2.0c, 0.0 МБ, стык 2.1 »
vn assets video inspect game/assets/mov/demo/ambient.webm
vn build                               # lint (sidecar!) -> ассеты -> генерат -> бюджеты; «build: OK»
vn build --check                       # CI-режим: свежесть + бюджеты, ничего не пишет
python -m pytest tools/vn/tests/test_video.py -q     # 7 тестов
vn release validate --flavor public    # 19 проверок, среди них «видео: собранные лупы валидны»
```

Эталон репозитория на 2026-08-08: ровно один луп — `game/assets/mov/demo/ambient.webm` (5683 Б) + его `.webm.meta.json` (526 Б), один сырец `assets_src/video_src/demo/ambient.mp4` (13559 Б) + `ambient.video.yaml` (31 Б).

## Ресурсы

- [Ren'Py: Movie](https://www.renpy.org/doc/html/movie.html) — список кодеков/контейнеров, сигнатура `Movie()`, `side_mask`, `start_image`, `group`, предупреждение про YUV444. Перебивает любой общий совет по веб-видео.
- [ComfyUI: Wan 2.2](https://docs.comfy.org/tutorials/video/wan/wan2_2) — актуальная официальная страница, включая first-and-last-frame воркфлоу (тот самый приём для лупов; использует те же чекпойнты I2V-A14B).
- [Wan2.2 (GitHub)](https://github.com/Wan-Video/Wan2.2) — модельный зоопарк и лицензия. Перед коммерческой дистрибуцией проверьте актуальный EULA/лицензию по официальной ссылке.
- [Video to Seamless Loop Converter (шаблон ComfyUI)](https://comfy.org/workflows/template_sirolim_seamless_loop-31ea7d2d9224/) — замыкание лупа для уже готового клипа.
- [WebM project: VP9 encoding guide](https://wiki.webmproject.org/ffmpeg/vp9-encoding-guide) и [Google VP9 VOD settings](https://developers.google.com/media/vp9/settings/vod) — единственная вменяемая таблица «разрешение → битрейт/CRF», если решите менять пресет.
- [NVIDIA RTX AI video generation guide](https://www.nvidia.com/en-us/geforce/news/rtx-ai-video-generation-guide/) — вендорский end-to-end на 16 ГБ VRAM: 5 c / 121 кадр как потолок клипа, 20–30 шагов при итерациях.

Лицензии моделей (Wan 2.2, LightX2V, RealESRGAN, bigASP, Civitai-LoRA) перечислены в `../../tools/comfyui-models.yaml` с полями `license` / `commercial_use` / `nsfw_terms_url`. **Перед коммерческой дистрибуцией проверьте актуальный EULA/лицензию по официальной ссылке каждой модели** — особенно тех, у кого `commercial_use: restricted` или `unknown`. Юридическая сторона — [Безопасность и лицензии](33-security-and-legal.md).

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/assets/video.py` (весь, 326 строк), `../../tools/vn/src/vn/assets/pipeline.py:170-201` (discovery) и `:286-389` (кэш, энкод, валидация, meta), `../../tools/vn/src/vn/cli.py:573-647` (группа `vn assets video`), `../../tools/schemas/video_src@1.schema.json`, `../../tools/schemas/mov_meta@1.schema.json`, `../../tools/vn/src/vn/content/images.py:89-99`, `../../tools/vn/src/vn/release.py:28-53` и `:312-321`, `../adr/0006-daz-comfyui-video-pipeline.md`, `../pipeline/phase-0.md` §3.5–§4, `../conventions/naming.md` |
| **Не трогать** | `game/assets/mov/**` (генерат, не в git — перезапишет `vn assets build`), `game/generated/registry/images.gen.rpy` (эмитит компилятор), `.vncache/assets-manifest.json` и `.vncache/video-tmp/**` (кэш и tmp; ручная правка манифеста ломает удаление осиротевших) |
| **Зависимости (что ломается ниже по течению)** | `tools/vn/src/vn/content/images.py:89-99` строит `image mov …` **по факту собранных файлов** и читает `meta.loop`; `tools/vn/src/vn/content/compile.py:142-145, 200-203` резолвит галерейные `mov/`-ссылки; `release.py:28-53` считает `video_total_mb`/`video_file_mb`; `release.py:312-321` гоняет `validate_all`; `release.py:191-202` строит NSFW-глобы из существующих каталогов `mov/nsfw/**` |
| **Валидация** | `vn pipeline doctor` → `vn assets video build` → `vn assets video validate` → `vn build` → `python -m pytest tools/vn/tests/test_video.py -q` → `vn release validate --flavor public` |
| **Частые ошибки** | 1) Считать, что sidecar валидируется при `vn assets video build` — **нет**, `load_opts(sidecar)` вызывается без реестра (`pipeline.py:195`); валидирует только линт. 2) Менять `encode_args`, не бампнув `video2webm` в `TRANSFORMS` — кэш вернёт старые байты. 3) Опираться на `docs/ARCHITECTURE.md` (:345, :858, :963, :1074, :1143, :1179) — там **непостроенный** дизайн видео (2-pass, `hd`/`mobile`, loudnorm, side-mask, `vfx@1`, зона `assets_src/video/`); канон — ADR-0006 и код. 4) Ожидать альфу: `yuva420p` даёт warning и играет непрозрачным. 5) Считать `vn assets video validate` проверкой суммарного бюджета — `video_total_mb` живёт только в `release.budget_failures()`. 6) Искать ComfyUI-воркфлоу или API-клиент в репозитории — их нет ни одного |
