# 16. Ассеты

> **Статус подсистемы:** IMPLEMENTED — конвейер `assets_src/` → `game/assets/` работает целиком: контентно-адресуемый кэш, точечная очистка осиротевших, профили `full`/`draft`. **Обновлено ADR-0012:** зона мастеров переехала в `assets_src/art/` (`png/` — алиас), форматы/разрешения/варианты задаются `project.yaml: render`, отгружаются оверсэмпл-варианты `@N`, любой неподобранный файл — ошибка сборки. **Но** три соседние подсистемы написаны и ни разу не запускались в этом репозитории: хранилище сырцов (`~/vn-assets-store` не существует), провенанс (ноль сайдкаров), PSD-нарезка (ноль `.psd`, ноль тестов). Ветка `copy_audio` ожила: зона источника приведена к норме `assets_src/audio_stems/`, но звуковых файлов в репозитории пока ноль.
> **Отвечает на вопрос:** «Куда положить картинку / видео / звук, как это должно называться и что запустить, чтобы оно появилось в игре».

Ассет-конвейер — это один модуль `tools/vn/src/vn/assets/pipeline.py` (1045 строк) плюс спутники: `video.py`, `ui.py`, `psd.py`, `storage.py`, `provenance.py`, `licenses.py`. Он берёт сырцы из `assets_src/`, прогоняет через версионированные трансформации и кладёт game-ready результат в `game/assets/` — зону, которой **нет в git**. Ren'Py-имена образов (`image bg rooftop day`, `layeredimage mira`) эмитит уже не он, а Content Compiler по факту собранных файлов — см. [Сквозной конвейер](08-content-pipeline.md).

## Быстрый ответ

```bash
# 1. Кладёте сырец в assets_src/ по конвенции (таблицы «Трансформации» и «Именование» ниже)
# 2. Собираете:
vn assets build                  # только ассеты, профиль full
vn assets build --profile draft  # быстрый черновой энкод (итерации)
vn build                         # lint -> ассеты -> генерат -> game/tl   ← обычный путь
# 3. Проверяете:
vn assets validate               # конвенции имён, обязательный base.png, свежесть, ссылки контента
vn build --check                 # CI-режим: ничего не пишет, краснеет на несвежем
vn assets cache --dry-run        # сколько мусора накопил кэш трансформаций
```

Свежий чекаут без `game/assets/`: `vn bootstrap` (`../../tools/vn/src/vn/cli.py:202-222`) — прогоняет `vn doctor`, затем локальную сборку ассетов, компиляцию контента и импорт переводов.

## 1. Две зоны: сырцы и собранное

| | `assets_src/` | `game/assets/` |
|---|---|---|
| Что лежит | PNG-слои, PSD, mp4-сырцы, декларации `*.render.yaml`, сайдкары `*.video.yaml` | WebP, WebM (+ `.webm.meta.json`), ogg |
| Кто пишет | человек / рендер-фермa | **только** `vn assets build` |
| В git | частично (ADR-0004, см. §7) | **нет** (`.gitignore:3`) |
| Разрешение | как отрисовано (спрайты — 2× виртуального) | то же, кроме `*.thumb.webp` (512 по длинной стороне) |
| Правка руками | норма | **бесполезна** — перезапишет ближайшая сборка |

Собранное не коммитится сознательно: `docs/ARCHITECTURE.md:1380,1975` объясняет — derived-бинари недетерминированы между версиями энкодеров и платформами, а массовая перегенерация раздувала бы append-only историю (в т.ч. LFS) на десятки ГБ.

**Честно про `vn bootstrap`:** ARCHITECTURE.md (G4, `:59`, `:425`, `:818`) обещает, что bootstrap *скачивает* готовые `game/assets/` + `game/generated/` + `game/tl/` из remote cache / CI-артефактов, чтобы сценарист и QA работали без asset-тулчейна. Это **NOT IMPLEMENTED**; текущая команда собирает всё локально, и её собственный докстринг это признаёт (`cli.py:205-206`). Практическое следствие: без Python-окружения с Pillow и без ffmpeg игру из чекаута не запустить. Аварийный режим `vn build --use-artifact <sha>` (14 упоминаний в ARCHITECTURE.md) — **NOT IMPLEMENTED**, флага не существует.

## 2. Полная таблица трансформаций (10 штук)

Реестр версий — `../../tools/vn/src/vn/assets/pipeline.py:54-65` (`TRANSFORMS`). Версия входит в ключ кэша: бамп `img_bg` не инвалидирует аудио- или видео-ветку (норма G13).

**Имена изменил ADR-0012.** Прежние `png2webp_*` в коде не существуют — grep по ним даёт ноль. Растровые ветки называются по классу ассетов, а класс → трансформация — это `CLASS_TRANSFORM` (`pipeline.py:68-69`): `spr → img_sprite`, `bg → img_bg`, `cg → img_cg`, `shot → img_shot`.

| Транформация | Вход | Выход (относительно `game/assets/`) | Параметры | Верс. | Код |
|---|---|---|---|---|---|
| `img_sprite` | `assets_src/art/characters/<key>/<pose>/base.<ext>` и `.../{outfits,faces,overlays}/<name>.<ext>`, плюс `<key>/side/<name>.<ext>`; плюс staging `.vncache/psd_png/characters/...` | `spr/<key>/<pose>/base[@N].webp`, `spr/<key>/<pose>/<group>/<name>[@N].webp`, `spr/<key>/side/<name>[@N].webp` | `quality` класса `spr` (по умолчанию 95 `full` / 50 `draft`), `keep_alpha`, целевой размер по `variants` | `2` | `pipeline.py:280-349`, `_image_jobs:212-260`, `_transform:625-630` |
| `img_bg` | `assets_src/art/backgrounds/<...>/<name>.<ext>` (вложенность любая) | `bg/<...>/<name>[@N].webp` + `<name>.thumb.webp` | `quality` класса `bg` (90 / 50), альфа запрещена | `2` | `pipeline.py:351-368` |
| `img_cg` | `assets_src/art/cg/<...>/<name>.<ext>` | `cg/<...>/<name>[@N].webp` + `<name>.thumb.webp` | `quality` класса `cg` (90 / 50), альфа запрещена | `2` | `pipeline.py:351-368` |
| `img_shot` | `assets_src/art/shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>].<ext>` (ADR-0013) | `shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>][@N].webp` | `quality` класса `shot` (90 / 50); `env` — без альфы и задаёт холст, остальные слои — с альфой и на том же холсте | `1` | `pipeline.py:370-412` |
| `img_thumb` | тот же файл растрового класса с `thumb: true` (`bg`, `cg`), вторая задача | `<...>/<name>.thumb.webp` | `max_side` и `quality` из `render.thumb` (512 / 80), `Image.thumbnail(..., LANCZOS)` | `2` | `_image_jobs:250-259`, `_thumb_ext:263-267`, `_transform:631-635` |
| `ui_panel` | **не файл**, а декларация: каждая панель из `content/ui/panels.yaml` × каждый масштаб класса `ui` | `ui/<panel_id>[@N].webp` | WebP `lossless=True, quality=100`, `method=4` (full) / `0` (draft) | `1` | `pipeline.py:471-483`, `_transform_ui_panel:641-656` |
| `copy_audio` | `assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg` | `audio/<kind>/<id>.ogg` | побайтовое копирование (`src.read_bytes()`) | `1` | `pipeline.py:414-430`, `_transform:636-637` |
| `voice_opus` | `assets_src/voice/<lang>/<chNN>/<line_id>.(wav\|flac\|ogg\|opus)` | `voice/<lang>/<chNN>/<line_id>.opus` | ffmpeg: Opus 96k, громкость к −19 LUFS (`voice.py:290-306`) | `1` | `pipeline.py:432-466`, `pipeline.py:771` |
| `video2webm` | `assets_src/video_src/<group>/…/<name>.{mp4,mov,mkv,webm,m4v,avi}` (+ опц. `<name>.video.yaml`) | `mov/<group>/…/<name>[@N].webm` | VP9 1-pass, см. §2.2 | `2` | `_video_jobs:533-599`, `video.py:101-120` |
| `mov_poster` | тот же видео-мастер | `mov/…/<name>.poster.webp` — постер-кадр для `Movie(image=)` и сетки галереи | кадр из видео → WebP | `1` | `pipeline.py:755`, `:846` |
| *(псевдо)* `mov_meta` | тот же прогон | `mov/…/<name>.webm.meta.json` (`mov_meta@1`) | JSON `indent=1, sort_keys=True` | версия берётся от `video2webm` | `pipeline.py:689` |

**Качество и форматы больше не константы в коде.** Их источник — `project.yaml: render.classes.<c>` поверх дефолтов `render_config.py:42-114`; `_transform` только читает `job.params["quality"][profile]` (`pipeline.py:625-630`). Поэтому «поднять качество CG» — правка `project.yaml`, а не конвейера, и она сама инвалидирует свою ветку кэша (`params_digest`, `render_config.py:245-250`).

Ядро энкода — `imaging.encode` (`assets/imaging.py`): приведение к целевому размеру по `variants`, `keep_alpha` по политике класса (`alpha: require|forbid|any`), выходной формат из `out_format`.

**`copy_audio` — зона источника `assets_src/audio_stems/`** (`pipeline.py:415`), как и в нормативных документах (`docs/ARCHITECTURE.md:393`, `docs/conventions/folder-layout.md:29`). Раньше код искал `assets_src/audio/`, каталога с таким именем в репозитории нет — ветка не срабатывала никогда; расхождение устранено правкой кода (норма дороже: смена имени зоны потребовала бы ADR). Регрессия закрыта тестом `test_audio_stems_branch_copies_ogg` (`tools/vn/tests/test_assets.py`). Каталоги `assets_src/audio_stems/{bgm,amb,sfx}/` заведены (пока с одними `.gitkeep`), но `content/audio/{bgm,sfx}.yaml` всё ещё имеют `tracks: {}` — **вторая, декларативная половина звука по-прежнему пуста**. Рецепт — в §13.6.

### 2.1 Дополнительные жёсткие правила discovery

| Правило | Что будет | Код |
|---|---|---|
| Каждый сегмент пути и `stem` файла обязан матчить `^[a-z][a-z0-9_]*$` | error, задача пропускается | `SLUG_RE:77`, `_check_slug:132-138` |
| В каталоге позы нет `base.<ext>` | error «нет обязательного base.* (список форматов класса)» | `pipeline.py:321-324` |
| В каталоге шота нет слоя `env.<ext>` | error «нет обязательного слоя env.*» | `pipeline.py:392-395` |
| Два источника претендуют на один выход (ручной растр + нарезка PSD) | error «два источника претендуют на один выход» | `pipeline.py:702-704` |
| Видео лежит без группы (`video_src/<name>.mp4`) | error «видео кладутся в группу» | `pipeline.py:567-570` |
| Есть видео-сырцы, но нет ffmpeg/ffprobe | error, видео-трек не собирается | `pipeline.py:553-559` |
| Есть мастера озвучки, но нет ffmpeg | error, голосовая ветка не собирается | `pipeline.py:447-451` |
| Любая ошибка discovery | **цикл задач не выполняется вообще** — нарушение имени не может каскадом снести `game/assets` | `pipeline.py:680-683` |

### 2.2 Видео: пресет

Полностью развёрнутая команда (`full`, без сайдкара) — `video.py:101-120`:

```
ffmpeg -y -hide_banner -loglevel error -i <src>
  -vf scale=-2:2*trunc(min(1080\,ih)/2)
  -c:v libvpx-vp9 -b:v 0 -crf 30 -row-mt 1 -cpu-used 2 -pix_fmt yuv420p -an
  -f webm <root>/.vncache/video-tmp/<stem>.tmp.webm
```

Аудио вырезается (`-an`), если в сайдкаре нет `keep_audio: true` (тогда `libopus @ 96k`). Ключи сайдкара `video_src@1`: `loop`, `keep_audio`, `fps`, `max_height`, `crf` (`video.py:33-39`). Подробности энкода, валидации лупа и бюджетов — [Генерация видео](21-video-generation.md).

## 3. Профили `draft` / `full` — точные различия

Меняются ровно три вещи; всё остальное идентично.

| Транформация | `full` | `draft` | Код |
|---|---|---|---|
| `img_sprite` | quality 95 | quality 50 | `render_config.py:88`, применение — `pipeline.py:625-630` |
| `img_bg` | quality 90 | quality 50 | `render_config.py:65` |
| `img_cg` | quality 90 | quality 50 | `render_config.py:76` |
| `img_shot` | quality 90 | quality 50 | `render_config.py:102` |
| `img_thumb` | quality 80 | quality 80 (**идентично**) | `render_config.py:57` (`render.thumb`) |
| `copy_audio` | копия | копия (идентично) | `pipeline.py:636-637` |
| `voice_opus` | Opus 96k / −19 LUFS | то же (идентично) | `voice.py:290-306` |
| `ui_panel` | lossless, `method=4` | lossless, `method=0` (быстрее, **те же пиксели**) | `pipeline.py:653-654` |
| `video2webm` | crf 30, `cpu-used 2`, потолок 1080 | crf 42, `cpu-used 8`, потолок `min(max_height, 720)` | `video.py:86-95` |

Числа `quality` — не константы кода, а дефолты render-профиля; `project.yaml: render.classes.<c>.quality` их переопределяет.

Значения по умолчанию: `vn assets build` → `full` (`cli.py:536-537`); `vn assets watch` → **`draft`** (`cli.py:605-607`); `vn dev` при правке `assets_src/` → `draft` (`cli.py:265-268`); `vn build` → `full` (`cli.py:90-91`).

**Грабля:** профиль входит в ключ кэша *и* в сравнение свежести (`pipeline.py:724-725`, `:867`). После `vn assets build --profile draft` команда `vn build --check` объявит все выходы несвежими («источник изменился»), потому что сравнивает с `profile: full`. Перед пушем — пересоберите `full`. Обратное тоже верно: `full` и `draft` блобы сосуществуют в кэше, переключение профилей туда-сюда удваивает его объём.

## 4. Именование — справочник

Нормативный документ: `../conventions/naming.md`. Здесь — то же самое, но с указанием, где именно норма enforced в коде.

### 4.1 Логические id ассетов

`^(bg|cg|spr|mov|ui|vfx|bgm|amb|sfx)/[a-z0-9_/]+$` (`naming.md:17`). Пример: `bg/school_gate/day`, `mov/demo/ambient`.
Из девяти префиксов производятся восемь: `bg`, `cg`, `spr`, `mov`, `ui` и `bgm|amb|sfx` (ветка `copy_audio`, §2 — работает, но сырцов в репозитории пока нет). `vfx` — **NOT IMPLEMENTED**, схемы `vfx@1` в `tools/schemas/` нет. Отдельно живут два id-пространства вне этих девяти: слои послойных шотов `shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>]` (§13.7) и дубли озвучки `voice/<lang>/<chNN>/<line_id>` (транскод `voice_opus`, §2) — первые наравне с `bg|cg|spr|mov` считаются выпущенными id ассетов в `id_registry@1`/`renames@1`.

### 4.2 Пути: сырец → выход

| Сущность | Сырец | Выход | Код |
|---|---|---|---|
| База спрайта | `assets_src/png/characters/<key>/<pose>/base.png` | `spr/<key>/<pose>/base@2.webp` | `pipeline.py:119-122` |
| Слой спрайта | `assets_src/png/characters/<key>/<pose>/<group>/<name>.png`, `<group> ∈ {outfits, faces, overlays}` | `spr/<key>/<pose>/<group>/<name>@2.webp` | `pipeline.py:125-135` |
| Фон локации | `assets_src/png/backgrounds/<location>/<variant>.png` | `bg/<location>/<variant>.webp` | `pipeline.py:137-144` |
| CG-стилл | `assets_src/png/cg/<...>/<name>.png` | `cg/<...>/<name>.webp` + `cg/<...>/<name>.thumb.webp` | `pipeline.py:148-157` |
| Видео-луп | `assets_src/video_src/<group>/…/<name>.<ext>` | `mov/<group>/…/<name>.webm` + `.webm.meta.json` | `pipeline.py:172-203` |
| UI-панель | запись в `content/ui/panels.yaml` | `ui/<panel_id>[@N].webp` (сегодня `@1` + `@2`) | `pipeline.py:205-216` |
| Аудио | `assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg` | `audio/<kind>/<id>.ogg` | `pipeline.py:159-170` |
| PSD | `assets_src/psd/characters/<key>/<key>_<pose>.psd` | staging `.vncache/psd_png/characters/<key>/<pose>/` | `psd.py:25`, `:98` |
| Декларация рендера | `assets_src/{daz,vam,sims4}/**/<name>.render.yaml` | — (декларация) | `licenses.py:23-27` |
| NSFW | подпапка `nsfw/` **внутри категории**: `cg/nsfw/…`, `mov/nsfw/…`, `assets_src/video_src/nsfw/…` | тот же префикс в выходе | `licenses.py:48-50`, `release.py:441-452` |

Файл спрайт-слоя по `naming.md:18`:
`^assets/spr/<char>/(<pose>/(base|outfits/*|faces/*|overlays/*)|side/*)@2\.webp$`.
**Честно:** ветка `side/<emotion>@2.webp` — **NOT IMPLEMENTED**. Grep по `tools/vn/src/vn/` на `side/` даёт ноль попаданий, хотя она нормативна и в `naming.md:18`, и в `ARCHITECTURE.md:144,454,922`. Группа `overlays` — **PARTIALLY IMPLEMENTED**: слои собираются в `game/assets/`, но эмиссия overlay-группы в `layeredimage` не написана, компилятор выдаёт предупреждение «сейчас мёртвый груз в дистрибутиве» (`tools/vn/src/vn/content/images.py:178-182`).

### 4.3 Про суффикс `@2`

`@2` — суффикс oversampling Ren'Py: движок трактует картинку как 2× виртуального разрешения. Это **чистая конвенция имени выхода**, никакого масштабирования в коде нет — спрайт кодируется 1:1 (`pipeline.py:223` не передаёт `max_side`). Получают его только выходы `spr/`; у `bg/`, `cg/`, `ui/`, `mov/` суффикса нет.

## 5. Кэш трансформаций

**Ключ** (`pipeline.py:298-312`):

```python
key = blake3(f"{src_hash}:{transform}:{TRANSFORMS[transform]}:{profile}")
blob = root/".vncache"/"assets"/key[:2]/key
```

`src_hash` — обычно `blake3(байты сырца)`, но с двумя исключениями:

| Транформация | `src_hash` считается от | Последствие |
|---|---|---|
| `video2webm` | `blake3(байты видео + b"\x00" + байты сайдкара)` (`pipeline.py:299-303`) | правка `<name>.video.yaml` инвалидирует выход |
| `ui_panel` | `blake3(json.dumps({spec, scale}, sort_keys=True))` **одной панели в одном масштабе** (`pipeline.py:304-308`, `ui.py: panel_hash_source`) — масштаб входит в ключ, иначе `@2` приехал бы байт-в-байт из блоба 1× | правка одной панели не перерисовывает остальные; но правка косметического поля `doc:` тоже инвалидирует блоб |

**Раскладка на диске:** `.vncache/assets/<2 hex>/<64 hex>` — двухсимвольный fan-out, имя файла = полный blake3. Сейчас: 53 блоба, 500,7 КБ; манифест перечисляет 55 выходов. Разница в два — это видео: у трансформации `video2webm` один блоб даёт три выхода (`.webm`, сайдкар `.webm.meta.json` по `mov_meta@1` и постер-кадр `.poster.webp`, `pipeline.py:726-735`).

**Все записи атомарны** — `<name>.tmp` + `os.replace` (`pipeline.py:71-79`). Причина в комментарии кода: обрезанный кэш-блоб «отравлял бы сборки навсегда». Выход в `game/assets/` перезаписывается только если байты отличаются (`pipeline.py:352-356`) — иначе выход помечается `fresh` и mtime сохраняется.

**Сборка мусора:**

```bash
vn assets cache             # только размер кэша
vn assets cache --dry-run   # сколько будет удалено
vn assets cache --gc        # удалить
```

`cache_gc` (`pipeline.py:458-491`, CLI `cli.py:744-765`) — mark & sweep от манифеста: пересчитывает ключ для каждой записи, чья трансформация есть в `TRANSFORMS` (записи `mov_meta@1` пропускаются — у них нет блоба), удаляет всё остальное под `.vncache/assets/`, включая осиротевшие `*.tmp`.

**Что будет, если удалить кэш целиком.** Ничего необратимого: следующая `vn assets build` заново прогонит все трансформации. Плата — время: PNG-энкод дёшев, VP9-энкод дорог (`cpu-used 2`), а PSD-нарезка не инкрементальна вовсе и пересекается заново при каждой сборке (`psd.py:91-95`). Опаснее удалять **манифест** — см. §6.

`.vncache/video-tmp/` GC **не подметается**: `cache_gc` чистит только `.vncache/assets` (`pipeline.py:462`). Временные файлы там удаляются по ходу (`video.py:126`, `:195-196`), но сам каталог живёт вечно.

## 6. Манифест сборки и удаление осиротевших

`.vncache/assets-manifest.json` (`pipeline.py:49`, `:441`, `:453-455`):

```json
{"schema": "assets_manifest@1",
 "outputs": {"spr/mira/a/base@2.webp": {
   "src": "assets_src/png/characters/mira/a/base.png",
   "src_hash": "00d4f13f…", "out_hash": "81599b48…",
   "transform": "img_sprite@2", "profile": "full"}}}
```

**Удаление осиротевших идёт ТОЛЬКО по диффу манифеста** — дерево `game/assets/` никогда не сканируется (`pipeline.py:416-433`):

```python
candidates = set(old_manifest) - set(seen_outputs)
for orphan in sorted(candidates):
    if (out_root / orphan).is_file():
        p.unlink(); rep.deleted.append(orphan)
```

Затем опустевшие каталоги `rmdir`-ятся вверх до `game/assets` (`pipeline.py:430-433`).

Следствия, которые надо помнить:

- Файл, которого **никогда не было в манифесте**, не удалится никогда. Руками положенный в `game/assets/` PNG будет молча ехать в каждый дистрибутив.
- **ОПАСНОСТЬ: манифест лежит в `.vncache/`, а `.vncache/` — в `.gitignore:21`.** Он машинно-локальный и не восстанавливается ни из git, ни из CI. Удалили его (или он побился — исключение молча глотается, `pipeline.py:396-399`) → `old_manifest` пуст → **удаление осиротевших отключается навсегда**, при этом сборка продолжает выглядеть зелёной. Лечение: снести `game/assets/` целиком и пересобрать `vn assets build`.
- В режиме `check=True` удаление не выполняется (возврат на `pipeline.py:414`), только отчёт «осиротел».
- При `--only`-подмножестве (`vn assets video build`) чужие ветки не трогаются ни очисткой, ни перезаписью манифеста: их старые записи вклеиваются обратно дословно (`pipeline.py:435-439`).
- Схема `assets_manifest@1` заведена (`tools/schemas/assets_manifest@1.schema.json`) и проверяется **на записи**: `build_assets` валидирует готовый документ через `SchemaRegistry` и кладёт расхождения в `rep.errors` — красная сборка (`pipeline.py:441-450`). Линтер сюда не дотягивается (файл вне `content/`), поэтому проверка живёт в самом писателе. Синтетические корни без `tools/schemas/` (тесты) валидацию пропускают — сверять не с чем.

## 7. Что в git, что нет

| Путь | В git | Механизм |
|---|---|---|
| `assets_src/**/*.png`, `*.mp4` | **да, временно** | ADR-0004, порог 50 МБ |
| `assets_src/**/*.manifest.json`, `*.render.yaml`, `*.video.yaml`, `*.provenance.json` | да | текст, им место в git |
| `content/ui/panels.yaml`, `content/licenses.yaml`, `.vnstorage.yaml` | да | источники истины |
| `game/assets/**` | **нет** | `.gitignore:3` |
| `game/generated/**`, `game/tl/**` | **нет** | `.gitignore:2`, `:4` |
| `.vncache/**` (кэш + манифест сборки) | **нет** | `.gitignore:21` |
| `.vnstorage.local.yaml` | **нет** | `.gitignore:22` |
| `game/fonts/*.ttf|otf|woff2` | да, **через LFS** | `.gitattributes:11-13` |
| `docs/**/*.png|jpg` | да, **через LFS** | `.gitattributes:14-15` |
| `assets_src/**` — растр, аудио, видео, PSD, `.duf`, `.var`, `.zip`, `.package` | да, **через LFS** (22 правила) | `.gitattributes:18-39` |

**Мастера сырцов в LFS заведены — это переписал ADR-0012** (`.gitattributes:17-39`, 22 правила). Game-ready ассеты не коммитятся вовсе (`.gitattributes:1-2`). Объектное хранилище (`vn assets push`) остаётся для не-растровых гигантов — PSD, Tray-бандлы, `.duf`, исходники видео (комментарий `.gitattributes:9-10`).

**ADR-0004** (`../adr/0004-local-png-sources-in-git.md`) разрешал небольшие демо-PNG прямо в зоне мастеров; **ADR-0012 переписал правило**: мастера легальны в git, но обязаны идти через LFS. Порог **enforced в тулинге**, а не на словах — `tools/vn/src/vn/content/lint.py:47`, `:422-452`:

| Состояние `assets_src/` | Реакция линта |
|---|---|
| нетекстовый файл, которому `git check-attr filter` не отдаёт `lfs` | **error** на каждый такой файл: «бинарь в assets_src не покрыт Git LFS» (`lint.py:436-441`) |
| сумма таких файлов **мимо LFS** > 50 МБ (`ADR0004_BINARY_LIMIT_MB`) | **error**, красный `vn build` и красный CI (`lint.py:445-452`) |
| всё в LFS | тихо — LFS кладёт в историю указатель на ~130 байт, поэтому вес мастеров под порог не идёт |

**Warn-порога «30 МБ / 60 % от лимита» в коде нет** — если встретите его в старых заметках, это устаревшее описание до-ADR-0012 версии проверки. Покрытие спрашивается у самого git (`_lfs_tracked`, `lint.py:76-102`), из подсчёта исключаются `.json/.yaml/.yml/.md/.txt/.gitkeep` (`lint.py:429-432`). Фактическое состояние: 28 бинарных файлов, ~1,0 МБ, **все покрыты LFS** → счётчик порога равен нулю; `vn content lint` — 0 ошибок, 0 предупреждений.

## 8. Хранилище сырцов

**Статус: IMPLEMENTED (`type: file`) / NEVER RUN HERE.** `~/vn-assets-store` не существует, `assets_src/**/*.manifest.json` — ноль, `vn assets status` печатает «манифестов нет — сырцы ещё не пушились (vn assets lock + push)» (`cli.py:953-955`).

### 8.1 Конфигурация

`.vnstorage.yaml` (`schema: storage@1`, обязательный файл для линта — `tools/vn/src/vn/content/lint.py:37`):

```yaml
schema: storage@1
storages:
  default: {type: file, path: "~/vn-assets-store"}
```

Локальные переопределения — `.vnstorage.local.yaml`, мержится поверх (`storage.py:57-62`) и лежит в `.gitignore:22`. Смысл разделения: манифесты в git ссылаются на **имя** хранилища, физика меняется одной строкой.

| `type` | Статус |
|---|---|
| `file` | IMPLEMENTED — `FileBackend`, `os.path.expanduser`, раскладка `<base>/objects/<key>` и `<base>/locks/<rel>.lock`, атомарный put через `.tmp`+`os.replace` (`storage.py:65-118`) |
| `s3` | **NOT IMPLEMENTED** — честный `StorageError`: «s3-бэкенд подключается при переходе команды на облако (G21: манифесты не изменятся) — пока используйте type: file» (`storage.py:129-133`) |
| любой другой | `StorageError` (`storage.py:134`) |

### 8.2 Команды

```bash
vn assets lock  png/characters/mira/a/base.png          # взять лок (путь ОТ assets_src/)
vn assets push  assets_src/png/characters/mira/a/base.png
vn assets lock  png/characters/mira/a/base.png --release
vn assets pull  --scope psd/characters/mira --edit      # получить + сразу залочить
vn assets status                                         # версии, локальное состояние, держатели локов
```

| Операция | Семантика | Код |
|---|---|---|
| `push` | путь обязан быть внутри `assets_src/` («сырцы живут только в assets_src/ (G2)»); `*.manifest.json` пропускаются; хранилище **закрепляется** первым манифестом (файл не мигрирует между хранилищами повторным push); совпал хэш → `fresh`, версия не растёт; иначе `version = prev+1`, иммутабельный ключ `<rel>/v<N>` | `storage.py:156-211` |
| `pull` | идёт по всем `assets_src/**/*.manifest.json` (фильтр `--scope`); локальный файл совпал по хэшу → `fresh`, скачивания нет; иначе `backend.get`, **перехэширование скачанного** и ошибка при несовпадении, затем атомарная запись | `storage.py:214-243` |
| `lock` | `--release` снять свой, `--force` снять чужой | `storage.py:246-267` |
| `status` | по манифесту: `нет локально` / `ИЗМЕНЁН локально (не запушен)` / `ok` + держатель лока; вшит в релизный гейт (`release.py:486-493`) | `storage.py:270-290` |

### 8.3 Лок обязателен для push (G14)

`push` **отказывает** без лока и при чужом локе (`storage.py:178-187`):

```
<rel>: push без лока запрещён (G14) — возьмите: vn assets lock <rel>
<rel>: залочен «<holder>» — push отклонён (G14)
```

Формат лок-файла — `<storage base>/locks/<rel>.lock`, ровно два поля (`storage.py:106-108`):

```json
{"by": "<git config user.name>", "at": "2026-08-08T12:00:00+00:00"}
```

Владелец = `git config user.name`, fallback `getpass.getuser()` (`storage.py:46-54`).

**ЧЕСТНО о гарантиях лока:**

- `acquire_lock` — read-then-write **без атомарного создания** (`storage.py:99-109`). Гонка двух клиентов: оба «выигрывают». ARCHITECTURE.md:293 требует условной записи `If-None-Match` — NOT IMPLEMENTED.
- **TTL нет**, эскалации на лида нет, уведомлений в чат нет (ARCHITECTURE.md:295, :903-906) — NOT IMPLEMENTED.
- `--force` снимает чужой лок **без записи в аудит** (`storage.py:111-118`).
- Личность — `git config user.name`, то есть переопределяется одной командой. Гарантия G14 процедурная, а не техническая.
- Локальную правку файла в `assets_src/` ничто не блокирует; `pull` без `--edit` лок не берёт и не проверяет.
- Поле `exports[]` объявлено в `tools/schemas/asset_src@1.schema.json` и в ARCHITECTURE.md:266, но `push` его **никогда не пишет** — обратной ссылки «сырец → выходы» не существует.

Про бэкапы и внешний диск/NAS — [Хранилище и бэкап](31-storage-and-backup.md).

## 9. Провенанс

**Статус: IMPLEMENTED / UNEXERCISED.** Код полон и покрыт 11 юнит-тестами (`tools/vn/tests/test_provenance.py`), но в репозитории **ноль** `*.provenance.json`, ноль `*.render.yaml`, ноль `.duf`, ноль workflow-JSON. Механизм ни разу не прогонялся на реальном контенте.

Сайдкар: `<artifact>.provenance.json` рядом с артефактом, **только внутри `assets_src/`** (`provenance.py:23`, `:50-56`). Хэши везде blake3. Документ (`provenance.py:258-262` + автоштамп `pipeline: "vn 0.1.0"` и `updated_at` при каждой записи, `:69-75`):

```json
{"schema": "provenance@1",
 "artifact": {"path": "png/cg/ch01/kiss.png", "hash": {"algo": "blake3", "hex": "…"}},
 "chain": [ {"kind": "daz_render", …}, {"kind": "comfyui", "model": …, "seed": …} ]}
```

`chain` — `oneOf` из `daz_render | vam_render | sims4_render | comfyui | manual` (`tools/schemas/provenance@1.schema.json`).

```bash
vn assets provenance record <artifact> [--source S] [--workflow api.json] [--note "…"] [--model M] [--seed N]
vn assets provenance workflow <artifact> [--out graph.json]
vn assets provenance verify [--scope png/cg]
```

**`record`** (`cli.py:795-816` → `provenance.py:204-263`):
1. `--source` → цепочка источника копируется как **префикс**, записывается `src_ref = {path, hash}`.
2. Шаг выводится так: `--workflow api.json` → парсинг графа; иначе, если артефакт `.png` → `extract_comfyui_png` читает `tEXt`-чанки `prompt` (API-граф) и `workflow` (UI-граф) (`provenance.py:80-98`).
3. Из графа извлекаются (`provenance.py:160-199`): `model` из `CheckpointLoaderSimple`/`CheckpointLoader.ckpt_name` или `*UNETLoader.unet_name`; `loras[] = {name, strength_model}`; `resolution` из `EmptyLatentImage`/`EmptySD3LatentImage`; из первого узла с `seed`/`noise_seed` — `seed, steps, cfg, sampler_name, denoise`; `prompt`/`negative_prompt` прослеживаются по связям `inputs.positive|negative` **до 8 переходов** до узла с `inputs.text`.
4. Граф **не инлайнится**: `store_workflow` кладёт `{"prompt": api, "workflow": ui}` в бэкенд `"default"` под ключ `workflows/<blake3(api-граф)>` (`provenance.py:128-147`). Инлайн `step["workflow"]` — только fallback, когда хранилище недоступно.
5. Нет графа и нет `--note` → `ProvenanceError`. С `--note` пишется шаг `{"kind": "manual", …}`.

**`verify`** (`provenance.py:317-378`) — ERROR: битый JSON, нарушение схемы, артефакт пропал, хэш артефакта разошёлся, хэш локального источника шага разошёлся («артефакт больше не воспроизводим из этой цепочки»). WARNING: comfyui-шаг без инлайн-графа, чей `workflow_hash` не резолвится в хранилище; источник не найден ни локально, ни в манифесте; хэш манифеста источника отличается.

**Шаги-происхождения** (`record_render`, `provenance.py:279-304`) пишутся не руками, а командами `vn assets {daz,vam,sims4} validate`: `*_render`-шаг встаёт в **голову** цепочки, последующие AI/ручные шаги сохраняются, прошлый шаг-происхождение заменяется («у артефакта один источник»). Практика — [DAZ Studio](17-daz-studio.md), [Генерация изображений](20-image-generation.md).

## 10. Лицензии ассетов

**Статус: IMPLEMENTED, вшито в релизный гейт.** Реестр — `content/licenses.yaml` (`schema: license_registry@1`), сейчас 3 записи: `g9_starter_essentials`, `font_literata`, `font_inter`.

Обязательные поля записи: `title, vendor, license_type, game_use, nsfw_allowed`; опциональные `sku, url, purchased_at, invoice, notes`.
`vendor ∈ {daz, renderotica, renderhub, vam_hub, gumroad, fontsource, audio_stock, other}`;
`license_type ∈ {daz_standard, daz_interactive, cc0, cc_by, ofl, royalty_free, custom, unknown}` (`tools/schemas/license_registry@1.schema.json`).

`vn assets licenses` → `validate_licenses` (`licenses.py:53-109`):

| Проверка | Уровень |
|---|---|
| Сам реестр не проходит схему | **ERROR**, дальше не идём |
| `license: [id]` в декларации не найден в реестре | **ERROR** |
| Запись помечена `game_use: false` | **ERROR** |
| Запись помечена `nsfw_allowed: false`, а `output` декларации содержит сегмент `/nsfw/` | **ERROR** |
| Декларация вообще без поля `license:` | одно агрегирующее **WARNING**, релиз не блокирует |

NSFW определяется строкой: `"/nsfw/" in f"/{output}"` (`licenses.py:48-50`). Проверяются `assets_src/{daz,vam,sims4}/**/*.render.yaml`, у которых `schema` совпадает с `daz_render@1|vam_render@1|sims4_render@1`.

Гейт: `release.py:475-484` — errors → `FAIL`, warnings → `WARN`, иначе `PASS`. Сейчас деклараций ноль, вывод: «деклараций рендеров нет; в реестре 3 записей».

Дисциплина из шапки самого реестра: **покупка ассета → запись здесь → только потом первый рендер с ним.** Ретрофит стоит ручной пробивки SKU по сотням деклараций. Юридический контекст (DAZ Standard vs Interactive, adult-запреты Published Artists, OFL) — [Безопасность и право](33-security-and-legal.md).

## 11. PSD

**Статус: IMPLEMENTED / UNEXERCISED.** Код полный и подключён к боевому пути, но: в `assets_src/psd/{characters,backgrounds,cg,ui}/` только `.gitkeep`, `.vncache/psd_png/` не существует, и **тестового файла на `psd.py` нет вообще** (в `tools/vn/tests/` нет `test_psd.py`). Самый нагруженный путь художника не обкатан.

Вызывается безусловно в начале каждой не-`check` сборки: `slice_all_psd(root, rep)` (`pipeline.py:266-268`). Зависимость — `psd-tools>=1.9` (`tools/vn/pyproject.toml:16`).

**Ожидаемая конвенция (по коду `psd.py:60-88`):**

| Уровень PSD | Требование | Нарушение |
|---|---|---|
| Имя файла | `assets_src/psd/characters/<key>/<key>_<pose>.psd`, `PSD_NAME_RE = ^(?P<key>[a-z][a-z0-9_]{1,23})_(?P<pose>[a-z][a-z0-9_]*)\.psd$`, и `key` обязан совпасть с именем папки | error (`psd.py:104-115`) |
| Слой `base` | верхний уровень, **пиксельный слой, не группа** | error «нет пиксельного слоя 'base'» |
| Группа `outfits` | группа слоёв, по слою на наряд | нет группы → warning; не группа → error |
| Группа `faces` | группа слоёв, по слою на эмоцию | нет группы → warning; не группа → error |
| Группа `overlays` | опциональна | отсутствие — тихо |
| Имя каждого слоя в группе | `^[a-z][a-z0-9_]*$` | error |

Специфика, которую надо знать до того, как отдать PSD художнику:

- **Флаг видимости слоя игнорируется намеренно** — экспортируются ВСЕ слои конвенционных групп: `layer.composite(layer_filter=lambda l: True)` (`psd.py:38`). Видимость в рабочем PSD отражает состояние работы, а не состав ассетов. Полностью прозрачный результат → warning «пустой арт?».
- Каждый слой кладётся на **полный холст PSD** (`psd.width × psd.height`), позиция сохраняется (`psd.py:37-40`).
- Выход — **только staging** `.vncache/psd_png/characters/<key>/<pose>/{base.png, outfits/*, faces/*, overlays/*}`; в `assets_src/` нарезка не пишет никогда (`psd.py:98`, `:116-118`).
- Каталог позы **полностью `rmtree`-ится** перед каждой нарезкой, а staging без соответствующего PSD удаляется (`psd.py:64-65`, `:120-127`).
- **Нарезка не инкрементальна:** каждая сборка режет каждый PSD заново, кэшируется только последующий WebP-энкод (признано в докстринге `psd.py:91-95`). На боевых PSD в единицы гигабайт это будет доминировать во времени сборки.
- PSD, залоченный Photoshop'ом или антивирусом → аккуратная запись в `rep.errors`, не трейсбек (`psd.py:56-59`).
- Обрабатывается **только** `psd/characters/`. Каталоги `psd/{backgrounds,cg,ui}/` существуют, но кода под них нет.
- Конфликт «ручной PNG и нарезка PSD дают один выход» ловится в `pipeline.py:289-290`.

## 12. UI-панели

Кратко: панель **объявляется** в `content/ui/panels.yaml`, рисуется конвейером в `game/assets/ui/<id>[@N].webp` (lossless WebP), а Content Compiler эмитит `define vn_frame_<id> = Frame(..., Borders(...))` в `game/generated/registry/ui_frames.gen.rpy`. Вёрстка знает только имя. **Восемь** панелей сейчас: `choice`, `choice_hover`, `choice_chosen`, `chip`, `chip_active`, `panel`, `slot`, `toast` — и каждая отгружается **двумя** файлами: `<id>.webp` и `<id>@2.webp`.

Ключевое, что относится к ассетам: `ui_panel` — единственная трансформация, у которой источник не файл, а словарь параметров, и ключ кэша считается **по одной панели и одному масштабу** (`pipeline.py:304-308`, `assets/ui.py: panel_hash_source`). Побочный эффект: правка комментария `doc:` инвалидирует блоб и вызывает перерисовку (байты выхода те же, `dest` не переписывается).

**Оверсэмпл-варианты — с этой итерации (ADR-0012).** У класса `ui` в render-профиле появился набор масштабов (`variants: [1, 2]`, `render_config.py: DEFAULTS`), и `_discover` заводит по одному job на каждый масштаб. Мастера у класса нет, поэтому апскейла и «пропуска варианта» здесь не бывает: панель просто **рисуется заново** крупнее — `_scaled_spec` умножает `radius`, `border.width`, `shadow.blur`, `shadow.dy` и тянущуюся полосу, цвета не трогает. Сторона `@2` ровно вдвое больше 1×, а `Borders` в эмитируемом `Frame` остаются **виртуальными** и имя образа — безсуффиксным: движок сам подставит крупный вариант и сам сочтёт его «меньше в N раз для целей вёрстки». Проверяется `vn test oversample --scale 2` (панели вошли в проверку: 22 ассета, 21 поднят).

**Настраивается пока только в коде.** Класс `ui` есть в `DEFAULTS`, но `project.yaml` его не примет: `render.classes.propertyNames.pattern` в `tools/schemas/project@1.schema.json` перечисляет `^(spr|bg|cg|mov|shot)$`. Сборка корректна (боевой профиль набор не переопределяет), но «поднять UI до 4K профилем» сегодня нельзя — **STATUS: OPEN**, правка на одну строку паттерна плюс описание классов.

Геометрия, правило `2*Borders` и полный список ключей панели — в [UI-слой](06-frontend.md) и `../adr/0009-generated-ui-panels.md`; нарушений в вёрстке сейчас нет. ADR-0009 в `ARCHITECTURE.md` **не отражён вовсе** (grep на `ui_panel|panels.yaml|vn_frame` → 0 попаданий): IMPLEMENTED / UNDOCUMENTED.

## 13. Как добавить ассет — рецепты

### 13.1 Фон локации

```bash
# 1. PNG сюда (имена — слуги!):
#    assets_src/png/backgrounds/rooftop/night.png
vn assets build
# 2. Объявить вариант в декларации локации:
#    content/locations/rooftop/location.yaml -> backgrounds: {night: assets/bg/rooftop/night.webp}
vn build
# 3. В сцене:  scene bg rooftop night with dissolve
```

Компилятор эмитит `image bg rooftop night = "assets/bg/rooftop/night.webp"` и **hard-error**, если объявленного в `location.yaml` файла нет в `game/assets` (`tools/vn/src/vn/content/images.py:62-66`). Подробнее — [Локации](11-locations.md).

### 13.2 Слой спрайта

```bash
# assets_src/png/characters/mira/a/faces/sad.png     (или outfits/, overlays/)
vn assets build            # -> game/assets/spr/mira/a/faces/sad@2.webp
# Добавить имя в matrix: content/characters/mira/character.yaml -> matrix.emotions: [..., sad]
vn build
```

`layeredimage mira` строится из пересечения `matrix` и **фактически собранных** файлов (`tools/vn/src/vn/content/images.py:104-236`). Собранный слой вне `matrix` → warning; заявленная в `matrix` поза без `base@2.webp` → error. Полный цикл — [Персонажи](10-characters.md).

### 13.3 CG-стилл

```bash
# assets_src/png/cg/ch01/kiss.png     (вложенность произвольная, все сегменты — слуги)
vn assets build   # -> cg/ch01/kiss.webp  +  cg/ch01/kiss.thumb.webp (512 по длинной стороне)
vn build          # -> image cg ch01 kiss = "assets/cg/ch01/kiss.webp"
```

Своей декларации у CG нет: реестр образов строится сканом собранной зоны (`tools/vn/src/vn/content/images.py:73-87`), `*.thumb.webp` из образов исключается. Миниатюра нужна галерее — [Галерея](15-gallery.md). NSFW-стиллы кладите в `cg/nsfw/…`.

### 13.4 UI-панель

```yaml
# content/ui/panels.yaml
tooltip:
  radius: 8
  fill: "#1c1c20f2"
  border: {color: "#ffffff1a", width: 1}
  shadow: {color: "#00000073", blur: 8, dy: 2}
  doc: "Всплывающая подсказка"
```

Посчитайте минимальный размер ДО сборки: `Borders = radius + max(blur + |dy|, border.width)` = `8 + max(10, 1) = 18` → элемент не может быть меньше **36×36 px**. Затем `vn build` (одной `vn assets build` мало: `define` эмитит компилятор), сверьте напечатанный минимум в `game/generated/registry/ui_frames.gen.rpy` и используйте `background vn_frame_tooltip` в стиле.

### 13.5 Видео-луп

```bash
# assets_src/video_src/demo/rain.mp4  [+ demo/rain.video.yaml — schema: video_src@1]
vn assets video build --profile draft     # быстрая итерация
vn assets video build                     # full перед коммитом
vn assets video validate                  # кодек/пиксели/размеры/fps/стык лупа/бюджет
vn assets video inspect game/assets/mov/demo/rain.webm
vn build                                  # -> image mov demo rain = Movie(...)
```

Группа обязательна (`video_src/<group>/<name>.<ext>`). Ошибки валидации — **красная сборка** (`pipeline.py:375-377`). Детали — [Генерация видео](21-video-generation.md).

### 13.6 Звук — читайте внимательно

**Трансформация `copy_audio` работает** (§2): кладёте `.ogg` в `assets_src/audio_stems/{bgm,amb,sfx}/`, `vn assets build` копирует его в `game/assets/audio/<kind>/<id>.ogg` байт в байт. Нормализации громкости для музыки/SFX в конвейере нет — файл должен приезжать уже сведённым.

```bash
cp market_theme.ogg assets_src/audio_stems/bgm/market_theme.ogg
vn assets build && ls game/assets/audio/bgm/
```

Декларативная половина — отдельный шаг: `content/audio/*.yaml` (`schema: audio@1`, `kind: bgm|amb|sfx`) компилируется в `define audio.<id> = "<file>"`, и сейчас все три файла имеют `tracks: {}`. Пока трек там не объявлен, `music:`/`ambient:` в сцене даёт ошибку компиляции. **Озвучка идёт своей веткой** `voice_opus`: мастера `assets_src/voice/<lang>/<chNN>/<line_id>.(wav|flac|ogg|opus)` транскодируются в `game/assets/voice/<lang>/<chNN>/<line_id>.opus` (Opus 96k, loudnorm −19 LUFS); покрытие описывают манифесты `voice@1`. См. [Аудио](23-audio.md) §3 и §8.

### 13.7 Послойный шот (shots@1, ADR-0013)

Полнокадровый кадр как `env`-подложка + вырезанные слои поверх — наряд персонажа меняется без перерендера кадра. Полное решение — [ADR-0013](../adr/0013-layered-shots.md).

```bash
# 1. Мастера — класс `shot` render-профиля (env — непрозрачная подложка, задаёт холст;
#    остальные слои — с альфой, на том же холсте; оверсэмпл @N — как у всех классов):
#    assets_src/art/shots/ch01/s030/sunset/env.jpg
#    assets_src/art/shots/ch01/s030/sunset/mira__school.png     # <layer>__<variant>
#    assets_src/art/shots/ch01/s030/sunset/mira__casual.png
vn assets build      # -> game/assets/shots/ch01/s030/sunset/*.webp

# 2. Декларация — content/chapters/ch01_awakening/shots/s030.shots.yaml (schema: shots@1):
#    shots.<shot>.layers (env обязателен; у слоя — variants и опц. var: переменная гардероба)
#    shots.<shot>.order — ЯВНЫЙ z-порядок, обязан перечислить каждый слой ровно один раз
vn build             # -> layeredimage shot_ch01_s030 в game/generated/registry/images.gen.rpy

# 3. В сцене:  scene shot_ch01_s030 sunset  (наряд — из переменной g.mira_outfit;
#              явный атрибут mira_school / mira_casual переопределяет)
```

Что валидируется на сборке (битый layeredimage не эмитится): схема; сцена-владелец существует; `order` ↔ `layers`; `var` объявлена в Variable Registry (иначе гардероб не попал бы в сейв, G5); каждый объявленный слой/вариант собран — ошибка; собранный, но не объявленный — предупреждение; ссылки `scene shot_… <шот> <вариант>` в `.rpy` сверяются индексом образов (`tools/vn/src/vn/content/compile.py:961-976`, `images.py:182-279`, `assets/pipeline.py:370-412`). Модель памяти `vn assets memory` учитывает худший шот сцены (env + самый тяжёлый вариант каждого слоя), id слоёв `shots/...` — выпущенные id в `id_registry@1`/`renames@1`. У `env` вариантов не бывает — вариативная среда объявляется отдельным шотом. Показ в сцене — [12-scenes.md](12-scenes.md).

## 14. Чеклист нового ассета

```
[ ] Все сегменты пути и имя файла матчат ^[a-z][a-z0-9_]*$ (без дефисов, CamelCase, пробелов и кириллицы)
[ ] Файл лежит в assets_src/ (или объявлен в content/ui/panels.yaml — для панелей)
[ ] Если это поза персонажа — в каталоге позы есть base.png
[ ] Если это видео — есть каталог группы: video_src/<group>/<name>.<ext>
[ ] Если NSFW — путь содержит сегмент nsfw/ внутри своей категории
[ ] Если ассет куплен/скачан — запись заведена в content/licenses.yaml ДО первого рендера
[ ] vn assets build проходит без error
[ ] vn assets validate: нет «несвежих выходов» и нет предупреждений об именах
[ ] Логическая половина объявлена: location.yaml / character.yaml matrix / gallery.yaml / panels.yaml
[ ] vn build: OK
[ ] "$RENPY_SDK/renpy.exe" . lint — нет битых ссылок на образы
[ ] vn content lint не ругается на порог ADR-0004 (бинари в assets_src)
[ ] Собранные файлы НЕ добавлены в git (git status чист по game/)
```

## 15. Как изменить / как расширить

| Задача | Что править | Обязательно после |
|---|---|---|
| Поменять качество WebP фонов | `project.yaml: render.classes.bg.quality` (дефолт — `render_config.py:65`) | бампать `TRANSFORMS` **не нужно**: качество едет в `params_digest` и само инвалидирует ветку кэша (`render_config.py:245-250`). Бамп `TRANSFORMS["img_bg"]` (`pipeline.py:54-65`) нужен, только если меняется сам код энкода |
| Поменять пресет ffmpeg | `video.py:101-111` | бампнуть `TRANSFORMS["video2webm"]` (правило зафиксировано комментарием `pipeline.py:37`, но **ничем не проверяется**) |
| Добавить новую трансформацию | запись в `TRANSFORMS`; ветка в `_discover` (`pipeline.py:102-218`); ветка в `_transform` (`pipeline.py:221-234`) или отдельная функция как у `ui_panel`/`video2webm` | тест в `tools/vn/tests/test_assets.py`; строка в таблице §2 этого файла и в `../conventions/naming.md` |
| Добавить исходную зону (`fonts/`, `seq/`, `spine/`) | `_discover`; сейчас известны ровно пять корней: `png/characters`, `png/backgrounds`, `png/cg`, `audio_stems`, `video_src` + декларация `content/ui/panels.yaml` | ADR: зоны из ARCHITECTURE §2.2 (`.rpa`, атласы, AVIF, ProRes-мастера) — NOT IMPLEMENTED |
| Перевести сырцы на реальное хранилище | `.vnstorage.yaml` → `path` на внешний диск/NAS; затем `vn assets lock` + `vn assets push` по файлам | закрыть ADR-0004; манифесты `*.manifest.json` коммитятся, бинари удаляются из git |
| Перейти на S3 | реализовать ветку `storage.py:129-133` | манифесты по контракту G21 не меняются |
| Поменять формат манифеста сборки | поля в `pipeline.py:359-365` (+ `:385-391` для `mov_meta`) | синхронно править `tools/schemas/assets_manifest@1.schema.json` — манифест валидируется при записи (`pipeline.py:441-450`), расхождение краснит сборку; несовместимая правка = новая версия схемы `@2` |

## 16. Чего НЕ делать

- **Не править `game/assets/**` руками.** Ближайшая сборка перезапишет; хуже — файл, которого нет в манифесте, **не удалится никогда** и поедет мёртвым грузом в каждый дистрибутив.
- **Не удалять `.vncache/assets-manifest.json`.** Он не в git и ниоткуда не восстанавливается. Без него удаление осиротевших молча отключается, а сборка остаётся зелёной. Если удалили — сносите `game/assets/` целиком и пересобирайте.
- **Не собирать `--profile draft` перед `vn build --check` / пушем.** Профиль участвует в сравнении свежести — check покраснеет «источник изменился» на всех выходах.
- **Не рассчитывать, что `vn assets watch` подхватит правку `content/ui/panels.yaml`.** Вотчер следит и за `content/`, и за `assets_src/`, но content-события выброшены: `watch(root, on_assets, lambda: None)` (`cli.py:566`). Для панелей — `vn dev` или ручной `vn build`.
- **Не ждать `define vn_frame_<id>` от `vn assets build`.** Панель нарисуется, но Frame эмитит компилятор — нужен `vn build` (или `vn content compile`).
- **Не класть аудио в `assets_src/audio/`** — такой зоны нет ни в коде, ни в нормативном дереве; единственный вход конвейера — `assets_src/audio_stems/{bgm,amb,sfx}/` (§13.6). Файл в неизвестной зоне не соберётся, и сборка об этом промолчит.
- **Не пушить сырцы без лока** — `push` откажет (G14). И не считать лок защитой: он не атомарный, без TTL, владелец = `git config user.name`, `--force` снимает чужой без следа.
- **Не запускать `vn build --check` на чистом чекауте с PSD-источниками.** `slice_all_psd` в режиме `check` пропускается (`pipeline.py:263-268`), `_discover` читает пустой `.vncache/psd_png/` — и все PSD-производные выходы объявляются осиротевшими.
- **Не кладите в `assets_src/` бинарь, не покрытый правилом LFS в `.gitattributes`** — это ошибка линта на первом же файле (и 50 МБ таких файлов суммарно — вторая ошибка). Warn-порога на 30 МБ в коде нет.
- **Не переименовывать собранный ассет, не пройдя через сырец.** Id ассетов неизменяемы (G7); переименование = новый id + запись в `content/renames.yaml`.
- **Не ждать, что `.vncache/video-tmp/` подметёт `vn assets cache --gc`** — GC знает только `.vncache/assets`.

## 17. Проверка

```bash
vn assets build                     # 0 ошибок; строка «N собрано, M из кэша, K актуально, D удалено»
vn assets validate                  # конвенции + свежесть + ссылки контента
vn build --check                    # CI-режим: «check: генерат свеж»
vn assets cache --dry-run           # мусор в кэше (сейчас: 24 блоба, ~5 устаревших)
vn assets licenses                  # «деклараций рендеров нет; в реестре 3 записей»
vn assets provenance verify         # «провенанс-сайдкаров нет (assets_src/**/*.provenance.json)»
vn assets status                    # «манифестов нет — сырцы ещё не пушились»
vn assets video validate            # все game/assets/mov/**
vn content lint                     # в т.ч. порог ADR-0004
python -m pytest tools/vn/tests/test_assets.py tools/vn/tests/test_ui_panels.py \
  tools/vn/tests/test_video.py tools/vn/tests/test_storage.py \
  tools/vn/tests/test_provenance.py tools/vn/tests/test_licenses.py -q   # 46 тестов
vn release validate --flavor public  # 21 проверка, включая лицензии, провенанс, видео, бюджеты
```

Эталонное состояние репозитория на 2026-08-18 (HEAD `e3c2842` + текущая итерация): `assets_src/` — 28 бинарных файлов / 964,0 КБ (14 из них — черновые дубли озвучки `voice/ru/ch01/*.wav`); `game/assets/` — 63 файла / 514,4 КБ (8 из них — оверсэмпл-варианты панелей `@2`); `.vncache/assets/` — 69 блобов / 519,6 КБ; манифест — 63 выхода.

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/assets/pipeline.py` (весь: 1045 строк, discovery+кэш+манифест+GC), `../../tools/vn/src/vn/assets/video.py`, `../../tools/vn/src/vn/assets/ui.py`, `../../tools/vn/src/vn/assets/psd.py`, `../../tools/vn/src/vn/assets/storage.py`, `../../tools/vn/src/vn/assets/provenance.py`, `../../tools/vn/src/vn/assets/licenses.py`, `../../tools/vn/src/vn/cli.py:511-955` (группа `vn assets`), `../conventions/naming.md`, `../adr/0004-local-png-sources-in-git.md`, `../adr/0006-daz-comfyui-video-pipeline.md`, `../adr/0009-generated-ui-panels.md` |
| **Не трогать** | `game/assets/**` (производная зона, `.gitignore:3`), `game/generated/**` (`.gitignore:2`), `.vncache/**` — кэш, манифест сборки, staging PSD (`.gitignore:21`). Любая правка там будет затёрта; правка `.vncache/assets-manifest.json` вручную ломает удаление осиротевших |
| **Зависимости (что ломается ниже по течению)** | `tools/vn/src/vn/content/images.py` строит `image bg/cg/mov` и `layeredimage` **по факту собранных файлов** — пропавший выход даёт ошибку компилятора или битую ссылку в рантайме; `tools/vn/src/vn/content/compile.py:139-227` резолвит `*.thumb.webp` для галереи; `tools/vn/src/vn/assets/ui.py:119-137` эмитит `vn_frame_*`; `release.py:29-53` считает бюджеты (`assets_total_mb 20000`, `video_total_mb 8000`, `video_file_mb 512` — ADR-0012); `release.py:441-452` строит NSFW-глобы из реальных каталогов; `release.py:475-493` — гейты лицензий и статуса хранилища |
| **Валидация** | `vn assets build` → `vn assets validate` → `vn build --check` → `vn content lint` → `python -m pytest tools/vn/tests -q` (278 тестов) → `vn release validate --flavor public` |
| **Частые ошибки** | 1) Менять параметр трансформации, не бампнув её версию в `TRANSFORMS` (`pipeline.py:38-46`) — кэш отдаст старые байты как свежие. 2) Считать, что `game/assets/` можно получить из git или через `vn bootstrap` без тулчейна — remote-fetch **NOT IMPLEMENTED**, bootstrap собирает локально. 3) Опираться на `docs/ARCHITECTURE.md` как на описание построенного: `game/assets/registry.json` (:1085), `assets_src/video/` (:858), side-mask alpha (:1143), VP9 2-pass и профили `hd`/`mobile` (:1179), `vfx@1` (:1074), зоны `.rpa`/атласов/AVIF (§2.2) — всё NOT IMPLEMENTED. 4) Ожидать, что `vn assets build` эмитит Ren'Py-`define` — это делает компилятор. 5) Класть звук мимо `assets_src/audio_stems/{bgm,amb,sfx}/` — иначе трансформация `copy_audio` его не увидит и промолчит (§2, §13.6) |
