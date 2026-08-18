# 18. Virt-a-Mate

> **Статус подсистемы:** IMPLEMENTED (ветка источника) — контракт «декларация → выход → провенанс» общий с DAZ и Sims 4 (`assets/sources.py`), и с ADR-0012 закрыт весь производственный путь VaM: `.var` в `scene`, `capture.fps` и сверка `mode`/`fps`/`resolution` с фактическим файлом, склейка PNG-секвенции (`vn assets video seq`) с записью провенанса, постер-кадр видео, скаффолд (`vn assets new vam`), симметричный релизный гейт. **Остаётся внешним:** VaM на этой машине не установлен (doctor → WARN, не FAIL), деклараций в репозитории ноль, автоматизация захвата — **WONT_FIX** (у VaM нет официального headless-режима, см. `../audit/daz-wan-readiness.audit.yaml`: VAM-005), а `docs/ARCHITECTURE.md` о VaM не знает — 0 упоминаний.
> **Отвечает на вопрос:** «Нужен ли мне VaM вместо/рядом с DAZ, как его легально поставить и как затащить захват в наш конвейер, чтобы он не выпал из провенанса и релизного гейта».

VaM (Virt-a-Mate) — Unity-песочница с физическим позингом персонажей. В этом проекте это **опциональный третий источник** кадров (ADR-0006 §2a), а не замена DAZ. Продакшен-трек проекта — DAZ → ComfyUI/Wan I2V → ffmpeg → Ren'Py (см. [DAZ Studio](17-daz-studio.md), [Видео](21-video-generation.md)). VaM берут точечно, когда нужна физика тел и анимация, которую AI-видео пока не вытягивает. Код источника: `../../tools/vn/src/vn/assets/vam.py` (24 строки — тонкая обёртка над общим валидатором `assets/sources.py`, ADR-0012), схема `../../tools/schemas/vam_render@1.schema.json`, детект `../../tools/vn/src/vn/pipeline.py:173`, установщик-детектор `../../tools/install-vam.ps1`.

## Быстрый ответ

```bash
# 0. Проверить, видит ли тулинг VaM (сейчас на этой машине — WARN, не установлен)
vn pipeline doctor            # строка «Virt-a-Mate: ...»

# 1. Поставить (легально; мастера установки у VaM нет — см. §2)
pwsh -File tools/install-vam.ps1

# 2. Сцену собрать и захватить РУКАМИ в VaM (автоматизации нет).
#    Скриншот  -> assets_src/png/cg/<...>/<name>.png
#    Секвенция -> assets_src/video_src/<group>/<name>.mp4  (собрать из PNG самому, §5)

# 3. Объявить захват (иначе он невоспроизводим и провенанс пуст)
#    assets_src/vam/<...>/<name>.render.yaml  (schema vam_render@1, §4)

# 4. Проверить + записать провенанс
vn assets vam validate

# 5. Дальше — общий трек, ничего VaM-специфичного:
vn assets build && vn build
```

Сейчас команда честно отвечает: `деклараций нет (assets_src/vam/**/<name>.render.yaml) — VaM опционален, см. docs/pipeline/phase-0.md (раздел VaM)`, exit 0.

## 1. Когда VaM реально нужен в этом проекте

ADR-0006 §2a формулирует роль в одну строку: «основной путь анимации остаётся DAZ→Wan I2V; VaM берут точечно ради физики тел». Разворачиваю в рабочие критерии.

| Задача | Брать VaM? | Почему |
|---|---|---|
| Главный CG-кадр, крупный план лица | **Нет** | VaM — растеризатор, не path tracer: кожа/SSS, контактные тени, преломление глаз и волосы проигрывают Iray |
| Двухфигурная поза с контактом, объятие, борьба | **Да** | Физика и коллизии дают правдоподобный контакт за минуты вместо часа ручного выкручивания суставов в DAZ |
| Анимация/луп, который Wan I2V «размазывает» | **Да** | Timeline даёт детерминированные ключи; Wan догадывается о движении, VaM его знает |
| 5 эмоциональных вариантов одного кадра | **Да** | Морфы — живые слайдеры, вариант стоит секунды |
| Много ракурсов одной сцены | **Да** | Сцену ставят один раз, камеры снимают пачкой |
| Фон/локация без людей | **Нет** | Нет смысла: контентная база VaM — персонажи |
| Спрайт персонажа (наш `spr/**`, 2× разрешение, альфа) | **Осторожно** | Технически возможно, но стилевой разрыв с DAZ-спрайтами в одной игре виден сразу |

**Практический гибрид** (рекомендация ресёрча, в проекте NOT IMPLEMENTED как оформленный workflow): VaM для постановки и позинга → скриншот в 8K через SuperResolution → даунсемпл → ComfyUI img2img/ControlNet с малым denoise → в `art/cg/**`. Провенанс это поддерживает из коробки: цепочка получается `["vam_render", "comfyui"]` — ровно это проверяет тест `../../tools/vn/tests/test_provenance.py:171-208`.

## 2. Установка: что делает `tools/install-vam.ps1`

Мастера установки у VaM нет — это распаковка архива плюс файл-ключ рядом либо установка через Steam. Скрипт (`../../tools/install-vam.ps1`) это не скрывает.

| Делает | Не делает |
|---|---|
| Детектит VaM: `VN_VAM` → `D:\VaM` → `C:\VaM` → Steam-библиотеки (`libraryfolders.vdf`, appId **2149830**) — `install-vam.ps1:38-61` | Не покупает, не логинится, не качает сборку |
| Создаёт `D:\VaM` (параметр `-InstallRoot`) | Не ставит ключ Patreon (кладёте вручную рядом с `VaM.exe`) |
| Если в `~/Downloads` лежит `VaM*.zip` — `Expand-Archive` в `$InstallRoot` (`:88-97`) | Не ставит плагины, `.var`-пакеты, vamX |
| Прописывает user-env `VN_VAM` (`:66-72`); флаг `-NoEnvVar` отключает | Не запускает VaM и ничего не рендерит |
| Печатает чеклист ручных шагов (`:99-112`) | — |

**Грабля с env:** `VN_VAM` пишется в user-env — его подхватят только **новые** процессы (та же природа, что у `setx` для `CIVITAI_API_KEY`, [Генерация изображений](20-image-generation.md)). После скрипта перезапустите терминал, иначе `vn pipeline doctor` его не увидит.

Легальные пути получения (из ресёрча 2026; скрипт печатает те же варианты, `install-vam.ps1:102-109`):

| Путь | Ссылка | Заметки |
|---|---|---|
| Steam | appId 2149830, EULA `https://store.steampowered.com/eula/2149830_eula_0` | Проще всего; издатель — Mesh VR, LLC; поставляется как «Virt-a-Mate + vamX» |
| Free-сборка | `https://hub.virtamate.com/` (аккаунт, age-gate) | Демо-контент; создание ограничено |
| Patreon | `https://www.patreon.com/meshedvr/posts/downloading-and-32794384` | Полная сборка + файл-ключ рядом с `VaM.exe`. **Ссылка отдаёт 403 автоматическим фетчерам** — открывайте руками; названия/цены тиров ресёрчем не подтверждены |
| vamX-бандл | `https://vamx.itch.io/vamx` | «Virt-a-Mate + vamX», $39.99+ |

**Пиратские сборки/крэки не используются** — это записано и в скрипте (`install-vam.ps1:18`), и в phase-0. **VR не нужен**: работаем в desktop-режиме (`install-vam.ps1:112`, `../pipeline/phase-0.md:130`).

### Как именно тулинг ищет VaM

`vam_path()` (`../../tools/vn/src/vn/pipeline.py:173`): `VN_VAM` (принимается и папка, и путь к `.exe`) → `D:\VaM\VaM.exe` → `C:\VaM\VaM.exe` → каждая Steam-библиотека `steamapps\common\Virt-A-Mate\VaM.exe`. Библиотеки берутся из `HKCU\Software\Valve\Steam\SteamPath` + разбора `libraryfolders.vdf` (`pipeline.py:143`). Результат уходит одной строкой в doctor (`pipeline.py:543-546`) — **всегда PASS/WARN, никогда FAIL**: отсутствие VaM не роняет ни один прогон.

## 3. Состояние VaM в 2026 (по верифицированному ресёрчу)

Это раздел «что умеет инструмент вообще». Что из этого подключено у нас — §4–§6.

| Тема | Факт | Источник |
|---|---|---|
| VaM1, актуальная версия | **1.22.0.13**, security-патч, **8 октября 2025** — то есть десять месяцев без релизов (на 2026-08-08); ветка feature-complete | `https://www.patreon.com/meshedvr/posts/important-patch-140760387` |
| Безопасность | 1.22.0.10 и 1.22.0.12 закрыли escape из файловой песочницы плагинов; 1.22.0.13 добавил ограничение ещё одного небезопасного метода | там же |
| Документация | Формального сайта документации **нет**. Канон — Hub и посты Patreon | `https://hub.virtamate.com/` |
| VaM2 | Beta 1.2 в финальной полировке, движок обновляется до Unity 6000.5.6; публичной сборки нет, только Patreon early access | `https://www.patreon.com/meshedvr/posts/july-2026-vam2-165371181` |
| VaM2 и контент VaM1 | `.var` от VaM1 в VaM2 **не работает** — это форк, а не миграция | ресёрч (эко-система) |
| Пакеты | `.var` = zip с `meta.json`: `creatorName`, `packageName`, `licenseType`, `dependencies`, `programVersion`, плюс `standardReferenceVersionOption` / `scriptReferenceVersionOption` со значениями `"Latest"` / `"Exact"` | чтение `meta.json` четырёх пакетов |
| Менеджеры зависимостей | VaM Backstage (MIT) `https://github.com/cyberpunk2073/vam-backstage`; VamToolbox `https://github.com/Kruk2/VamToolbox` (симлинки, требует запуска от админа); PowerShell-скрипты iHV `https://github.com/BoominBobbyBo/iHV` | верифицировано |
| Плагины: индекс | 15 плагинов acidbubbles: `https://github.com/acidbubbles/vam-acidbubbles-home` | верифицировано |
| Анимация | Timeline **v6.5.1, 25 августа 2024** — ключи/безье, слои, сегменты, очередь анимаций: `https://github.com/acidbubbles/vam-timeline` | верифицировано |
| Хоткеи/командная шина | Keybindings, >200 команд, палитра с fuzzy-поиском, broadcast-протокол `OnActionsProviderAvailable`: `https://github.com/acidbubbles/vam-keybindings` | верифицировано |
| «Живой» взгляд | Glance `https://github.com/acidbubbles/vam-glance` (GPL-3.0) — саккады, моргание, цели взгляда | верифицировано |
| Оверлеи/субтитры | VAMOverlays `https://github.com/hazmhox/vam-overlays`, Hub `https://hub.virtamate.com/resources/vamoverlays.2438/` — fade in/out, **субтитры и текст** на камере | верифицировано |
| Стиллы | MacGruber Essentials: **SuperShot / SuperResolution** — гонят встроенный скриншот до 8K (в архивном исходнике 0.1.0 рендер-текстура 8192×4608); PostMagic `https://hub.virtamate.com/resources/postmagic.161/` — bloom/DoF/AA/грейдинг в реальном времени. Лицензия Essentials — CC BY-SA | верифицировано косвенно (атрибуция в исходнике VRRenderer) |
| Видео | Eosin VRRenderer `https://github.com/yunidatsu/Eosin_VRRenderer` (CC BY-SA) — **офлайновый покадровый рендер**; пишет **нумерованные PNG/JPG** (`_%06d`, PNG с альфой) и **WAV** отдельно. **Внутри нет ffmpeg и нет видео-энкодера** — контейнер собираете сами. Супер-семплинг 1–8, пресеты до 8192×6144 | чтение исходника плагина |
| Экспорт движения | BVH-экспорт есть; при импорте в Blender ставить **Y up, −Z forward**; rest-pose DAZ ≠ внутренняя rest-pose VaM/DAZ — использовать опцию «unoriented rest pose» | верифицировано |
| Железо | VaM1 упирается в **CPU/физику**, а не в GPU. RTX 5080 будет наполовину простаивать, пока soft-body на двух персонажах держит ~40 fps | анализ ресёрча |
| Диск | Серьёзная библиотека `.var` — **200 ГБ – 1 ТБ**. Отдельный SSD | ресёрч |

**Что из этого важно нам практически:** VRRenderer отдаёт PNG-секвенцию, а видео-трек ждёт собранный контейнер. Сборщик есть (ADR-0012) — руками ffmpeg больше не нужен:

```bash
# PNG-секвенция VaM -> видео-мастер (libx264 CRF 12: это ИСХОДНИК, из него потом жмётся VP9)
vn assets video seq <папка-с-кадрами> assets_src/video_src/ch01/hug.mp4 --fps 30
```

Команда сама ловит дыру в нумерации кадров (ffmpeg молча оборвал бы видео на первой)
и пишет шаг провенанса — мастер не «берётся ниоткуда». Объявите тот же fps в
`capture.fps`: валидатор сверит его с собранным мастером, потому что один и тот же
набор кадров при 24 и 30 fps даёт разные по длительности лупы.

Дальше `vn assets build` сам перегонит в VP9/WebM по нашему пресету — см. [Видео](21-video-generation.md).

## 4. Декларация захвата: `vam_render@1`

Файл: `assets_src/vam/**/<name>.render.yaml`. Схема: `../../tools/schemas/vam_render@1.schema.json`, `additionalProperties: false` на **обоих** уровнях — незнакомый ключ это твёрдая ошибка, а не предупреждение.

| Ключ | Обяз. | Тип / ограничение | Строка схемы |
|---|---|---|---|
| `schema` | ✅ | const `vam_render@1` | :8 |
| `id` | ✅ | `^(bg\|cg\|spr\|mov)/[a-z0-9_/]+$` — логический id результата (naming.md) | :9 |
| `scene` | ✅ | `^vam/.+\.(json\|vac\|vap)$`, путь относительно `assets_src/` | :10 |
| `output` | ✅ | `^(png\|video_src)/.+`, путь относительно `assets_src/` | :11 |
| `version` | ❌ | integer ≥ 1 | :12 |
| `license` | ❌ | массив id из `content/licenses.yaml` (`^[a-z][a-z0-9_]*$`) | :13-17 |
| `capture` | ✅ | объект (ниже) | :18 |
| `capture.resolution` | ✅ | массив ровно из 2 int ≥ 16 | :21-24 |
| `capture.mode` | ✅ | enum `screenshot` \| `sequence` | :25 |
| `capture.camera` | ❌ | строка — имя WindowCamera/атома камеры в сцене | :26 |
| `capture.plugins` | ❌ | массив строк — задействованные плагины | :27 |
| `capture.vamx` | ❌ | boolean — использовалось расширение vamX | :28 |
| `capture.notes` | ❌ | строка | :29 |

Рабочий пример (структура — из единственного конкретного примера в репозитории, теста `../../tools/vn/tests/test_provenance.py:181-193`):

```yaml
schema: vam_render@1
id: cg/ch01/beach
scene: vam/ch01/beach/scene.json
output: png/cg/ch01/beach.png
license: [g9_starter_essentials]      # id из content/licenses.yaml
capture:
  resolution: [1920, 1080]
  mode: screenshot
  camera: WindowCamera
  plugins: [MacGruber.Essentials.12, acidbubbles.Timeline.290]
  vamx: true
  notes: "SuperResolution 4x, PostMagic preset ch01_warm"
```

**Место для воспроизводимости пакетов — `capture.plugins` и `capture.notes`.** Сам пакет объявляется полем `scene` (см. ниже); `plugins`/`notes` фиксируют ЗАВИСИМОСТИ и настройки. Пишите в `plugins` полную тройку `creator.package.version`, а не «Timeline»: ресёрч прямо предупреждает, что `scriptReferenceVersionOption: "Latest"` тихо меняет лицо персонажа между кадрами при обновлении зависимости. В `notes` — пресет PostMagic, множитель супер-семплинга, всё, без чего кадр не повторить.

### Формат сцены: `.var` объявляется напрямую

Паттерн `scene` принимает `json | vac | vap | var` (ADR-0012). Ссылайтесь прямо на пакет `.var` — именно он воспроизводимый артефакт; распаковывать ради декларации не нужно. Расширение паттерна сделано в `vam_render@1`, а не новой версией схемы: документ, валидный по старой версии, валиден и по новой (политика версионирования — ADR-0012 §9).

### Где лежат бинари сцены

`.json`/`.vac`/`.vap`/`.var` — тяжёлые сырцы. С ADR-0012 у них два легальных пути:

1. **Git LFS** (`.gitattributes` покрывает `assets_src/**/*.var` и остальные бинарные расширения) — история git получает указатель на ~130 байт, а не пакет целиком. Порог ADR-0004 считает теперь **только бинари мимо LFS**, поэтому серьёзный `.var` его не перекрывает; зато файл, не покрытый LFS, — отдельная ошибка линтера.
2. **Хранилище** через `vn assets push` — для библиотек, которые не хочется тянуть каждым клоном. **Честно:** `~/vn-assets-store` на этой машине не создан, а бэкенд `type: s3` осознанно бросает `StorageError` — NOT IMPLEMENTED.

Практически на сегодня: кладите `.var` в LFS.

## 5. Что делает `vn assets vam validate`

Код: `../../tools/vn/src/vn/cli.py` → `../../tools/vn/src/vn/assets/vam.py` (обёртка, 24 строки) → общий валидатор `../../tools/vn/src/vn/assets/sources.py:145-206`. Флаги: `--scope <подпуть>`, `--no-provenance`. **Обновлено ADR-0012:** три структурные копии сведены к одному контракту; различия источников — данные (`SourceKind`, `sources.py:47-67`).

| Шаг | Что происходит | Строка |
|---|---|---|
| 1 | Рекурсивный обход `assets_src/vam/**/*.render.yaml`. Нет каталога — тихий пустой отчёт | `sources.py:154`, `:151-152` |
| 2 | Валидация по JSON Schema. Ошибка схемы → декларация **пропускается целиком**, дальше по ней не проверяется ничего | `sources.py:160-163` |
| 3 | Существование сцены: `assets_src/<scene>` **или** `assets_src/<scene>.manifest.json`. Иначе error `«сцены … нет ни локально, ни в манифестах (vn assets push после экспорта сцены)»` | `sources.py:166-172` |
| 4 | Дубликат `output` между декларациями → error | `sources.py:174-179` |
| 5 | `id` не соответствует выходу (пересчёт той же арифметикой, что у конвейера) → error | `sources.py:183-188` |
| 6 | Нет файла выхода → **только warning** `«выход … ещё не получен»`, обработка декларации останавливается | `sources.py:190-193` |
| 7 | `capture.resolution` против фактического файла → error при расхождении | `_check_resolution`, `sources.py:252-286` |
| 8 | `capture.mode` (`sequence`/`screenshot`) против типа выхода и `capture.fps` против фактического fps мастера → error | `_check_sequence`, `sources.py:209-249` (молчит без `ffprobe`) |
| 9 | Выход есть и не задан `--no-provenance` → пишется/обновляется `<output>.provenance.json` | `sources.py:198-205` |

Exit 1 при любой ошибке, иначе 0.

**Чего валидатор НЕ делает** (симметрично DAZ):

- не открывает и не парсит сцену VaM — это чистая проверка существования файла;
- не требует `license` — его отсутствие ловит `vn assets licenses`, и то как WARN (`../../tools/vn/src/vn/assets/licenses.py:104-108`);
- не проверяет наличие плагинов, версий пакетов, ничего про саму инсталляцию VaM;
- ничего не захватывает и не запускает.

Сверка `capture.resolution` с файлом и согласованность `id` ↔ `output` в этом списке были до ADR-0012 — теперь это шаги 5 и 7 выше.

### Провенанс

`record_render` (`../../tools/vn/src/vn/assets/provenance.py:279-304`) кладёт в начало цепочки шаг `{kind: "vam_render", source: {path, hash}, declaration, settings}`, где `settings` — дословный снимок блока `capture`. Хэши — blake3. Переобъявление источника **заменяет** предыдущий `*_render`-шаг и сохраняет хвост `comfyui`/`manual` (`provenance.py:294-299`). Это и даёт цепочку `vam_render → comfyui` для гибрида из §1.

### Релизный гейт

`../../tools/vn/src/vn/release.py:587-595` вызывает тот же валидатор с `write_provenance=False`. Ветвление симметрично DAZ (`release.py:576-584`) и Sims 4 (`:528-537`): `errors → FAIL`, иначе `warnings → WARN`, иначе `else → PASS`. Поэтому при нуле деклараций гейт печатает три строки:

```
 PASS  DAZ-декларации: 0 проверено
 PASS  VaM-декларации: 0 проверено
 PASS  Sims4-декларации: 0 проверено
```

Прошлая асимметрия (`elif vrep.checked:`, из-за которой пустая VaM-зона молчала) в коде **исправлена** — если встретите это утверждение в старых заметках, оно устарело.

Что осталось честной дырой: **незахваченный выход даёт WARN, а не FAIL** — декларация, по которой ничего не сняли, релиз не блокирует.

## 6. Автоматизация: что возможно и что подключено

| Возможность (по ресёрчу) | В нашем конвейере |
|---|---|
| Официального CLI / headless-режима / batch-render у VaM1 **нет** | — |
| `MVRScript` — C#-плагины, компилируются в рантайме; шаблон `https://github.com/acidbubbles/vam-plugin-template`, утилиты `https://github.com/acidbubbles/vam-devtools` | **NOT IMPLEMENTED** — плагинов проекта нет |
| Scripter — JS-подобный движок внутри VaM с классом `FileSystem`: `https://github.com/acidbubbles/vam-scripter` (GPLv3) | **NOT IMPLEMENTED** |
| Keybindings как командная шина: свои `JSONStorableAction` + broadcast-протокол → вся серия захватов с одной клавиши | **NOT IMPLEMENTED** |
| Внешнее управление процессом: `chat.appTrigger` умеет дёргать любой action/storable любого атома — `https://doc.voxta.ai/docs/integrations/vam/creators/app-triggers` | **NOT IMPLEMENTED** |
| Скриптование библиотеки `.var` из PowerShell: `https://github.com/BoominBobbyBo/iHV` | **NOT IMPLEMENTED** |
| Наш `vam_path()` знает, где `VaM.exe` | Путь **только печатается** в doctor и никогда не исполняется (`pipeline.py:543-546`) |

Проектная позиция ADR-0006: рендер/захват — **сознательно ручной GUI-шаг**. Автоматизация не «забыта», её нет в плане. Если будете её строить — держите в голове ограничение песочницы: 1.22.0.10/1.22.0.12/1.22.0.13 последовательно резали плагинам файловый доступ, так что file-based IPC наружу из VaM — фундамент, который может уехать со следующим патчем.

## 7. Лицензии

**Никаких юридических выводов здесь нет.** Проверьте актуальный EULA / условия Hub по официальным ссылкам перед коммерческой дистрибуцией; при сомнениях — юрист, а не хендбук.

| Документ | Официальный URL | О чём |
|---|---|---|
| EULA VaM + vamX (Mesh VR, LLC) | `https://store.steampowered.com/eula/2149830_eula_0` | Лицензия на **само ПО**: одна копия одновременно, запрет переуступки/перепродажи/сублицензирования |
| Terms of Use Hub | `https://hub.virtamate.com/help/terms/` (последнее обновление 29 мая 2020) | §5.3(b) — запрет коммерческого использования сайта/материалов через него; §7.3 — лицензия, которую загрузчик даёт платформе; §9.15 — коммерческая активность в User Contributions |
| Лицензия конкретного ресурса | страница ресурса на Hub, напр. `https://hub.virtamate.com/resources/vamoverlays.2438/` | Управляет **этим** ассетом через `licenseType` в его `meta.json` |
| DAZ 3D EULA | `https://www.daz3d.com/eula` | Важен для кроссовера: §1.0 — и разрешение распространять производные 2D-изображения, и запрет использования Content «in connection with» AI-движками, авто-генерирующими производные материалы. Interactive License — **не аддендум к EULA**, а отдельная страница `https://www.daz3d.com/interactive-license-info`; разбор — [DAZ Studio](17-daz-studio.md) §лицензии и [Безопасность и право](33-security-and-legal.md) |

Три практических тезиса, которые нельзя пропустить:

1. **«Я купил VaM» и «я могу продавать кадры с этим луком с Hub» — разные вопросы.** Первый закрывает EULA софта, второй — `licenseType` конкретного пакета. У нас под это уже есть механизм: реестр `../../content/licenses.yaml` (`license_registry@1`) с вендором **`vam_hub`** в enum (`../../tools/schemas/license_registry@1.schema.json`) и поля `game_use` / `nsfw_allowed`. Заводите запись **до** первого захвата — ретрофит по сотням деклараций дорог (docstring `licenses.py:1-11`).
2. **`licenseType` в `meta.json` может не совпадать с README пакета** — у VAMOverlays README говорит CC BY, а `meta.json` CC BY-SA. Ресёрч советует считать источником истины `meta.json` и перепроверять на странице Hub.
3. **Перераспространение чужого контента с Hub — отдельная тема.** Многие «луки» тянут за собой скины/одежду, изначально проданные на DAZ/Renderosity с мутными правами; плюс лицензии семейства CC BY-SA накладывают требования на производные. Для героев проекта разумно строить персонажа из ассетов, права на которые держите вы, — тогда запись в `content/licenses.yaml` вообще возможна.

Плагины VaM — это **компилируемый в рантайме C#**, то есть исполняемый код. Незнакомый `.var` с плагином = незнакомый exe; сюда же — «держитесь пропатченной версии».

## 8. DAZ vs VaM: когда что

| Критерий | DAZ Studio | Virt-a-Mate |
|---|---|---|
| Качество финального кадра | Iray — path tracing, побеждает на коже/SSS, контактных тенях, глазах, ткани, волосах | Растеризатор Unity; конкурентоспособен на средних/общих планах и стилизованном грейде |
| Скорость итерации | Очередь рендера; правка света = новый рендер | Финальный-ish кадр мгновенно; экономический аргумент для сотен стиллов |
| Анимация | Болезненная | Родная: Timeline (ключи, слои, сегменты, очередь) + процедурная «жизнь» |
| Физика тел | dForce для ткани/волос хорош; контакт тел — ручная работа | Главное преимущество: коллизии и soft-body в реальном времени |
| Доступность контента | Огромный коммерческий рынок Genesis 8/9 с внятными SKU | Hub: много и бесплатно, но лицензии разнородны и часто наследуют чужие права |
| Автоматизируемость | Есть скриптовый API и почти-headless batch-рендер (**в нашем проекте всё равно NOT IMPLEMENTED**: ни `.dsa`, ни headless-вызова) | Официального CLI/headless нет вообще; только плагины/Scripter изнутри |
| Лицензионная чистота для коммерции | Выше: покупка → SKU → инвойс → запись в `content/licenses.yaml`. Помнить про AI-пункт EULA при img2img поверх DAZ-рендера | Ниже: цепочка `.var`-зависимостей = цепочка лицензий; ToU Hub от 2020 года; проверять каждый пакет |
| Требования к железу | GPU/VRAM: RTX 5080 16 ГБ (`vn pipeline doctor` подтверждает), Iray упирается в VRAM | CPU/физика; GPU наполовину простаивает. Диск: библиотека 200 ГБ–1 ТБ на отдельный SSD |
| Статус в проекте | **Продакшен-трек** (ADR-0006), окружение доступно: DAZ Studio 6 найден | **Опциональный источник**, не установлен (doctor → WARN) |

**Вывод одной строкой:** герой-кадры, спрайты и всё, что несёт лицо — DAZ. Физический контакт, анимация и пачки ракурсов, где важнее скорость, чем микродеталь, — VaM, и лучше не как финальный кадр, а как база под ComfyUI-полировку. Не смешивайте два сырых источника в одной сцене без полировочного прохода: разница в шейдинге кожи и волос читается сразу.

## 9. Как расширить

**Добавить первый VaM-захват (весь путь):**

1. Записать в `../../content/licenses.yaml` каждый использованный платный/чужой ассет: `vendor: vam_hub`, `license_type`, `game_use`, `nsfw_allowed`, `url`, `invoice`. **До** захвата.
2. Собрать и сохранить сцену в VaM; путь сцены — `assets_src/vam/<ch>/<name>/scene.json`. Бинарь — через `vn assets push` (когда хранилище появится), не в git.
3. Захватить: скриншот через SuperShot/SuperResolution → `assets_src/png/cg/<...>/<name>.png`; секвенцию через VRRenderer → PNG-кадры → ffmpeg → `assets_src/video_src/<group>/<name>.mp4`.
4. Написать `assets_src/vam/<ch>/<name>/<name>.render.yaml` по таблице §4. Скаффолда нет — **`vn assets vam new` не существует**, YAML пишется руками против схемы.
5. `vn assets vam validate` — должно стать `vam validate: OK (1 деклараций, 0 предупреждений)` и записать `<output>.provenance.json`.
6. `vn assets build && vn build` — дальше кадр живёт как обычный `cg/**` или `mov/**` (см. [Ассеты](16-assets.md), [Сквозной конвейер](08-content-pipeline.md)).
7. `vn release validate --flavor public` — убедиться, что появилась строка `VaM-декларации: N проверено`.

**Улучшения тулинга** (зачёркнутое сделано в ADR-0012; остальное — NOT IMPLEMENTED):

| Приоритет | Что | Где менять |
|---|---|---|
| ~~P1~~ | ~~Скаффолд декларации~~ — **сделано** (ADR-0012): `vn assets new vam <id> --scene …` | `../../tools/vn/src/vn/assets/sources.py` |
| ~~P1~~ | ~~Сборщик «PNG-секвенция → `video_src`»~~ — **сделано**: `vn assets video seq` (+ провенанс, + проверка дыр в нумерации) | `../../tools/vn/src/vn/assets/video.py` |
| ~~P2~~ | ~~Допуск `.var` в `scene`~~ — **сделано** расширением `vam_render@1` (новая версия схемы не понадобилась) | `../../tools/schemas/vam_render@1.schema.json` |
| ~~P2~~ | ~~Симметрия гейта~~ — **сделано**: гейт отчитывается обо всех трёх источниках | `../../tools/vn/src/vn/release.py` |
| ~~P3~~ | ~~Сверка `capture.resolution` с выходом~~ — **сделано** для всех источников разом, плюс `mode` и `fps` | `../../tools/vn/src/vn/assets/sources.py` |
| ~~P3~~ | ~~Строка про VaM/Sims4-декларации в `../conventions/naming.md`~~ — **сделано** | документация |

## 10. Чего НЕ делать

- **Не считать VaM заменой DAZ.** ADR-0006 §2a фиксирует роль: точечно, ради физики. Переезд продакшен-трека на VaM — это новый ADR, а не решение внутри задачи.
- **Не коммитить `.var`/`.vac`/сцены мимо Git LFS.** Порог ADR-0004 считает бинари, НЕ покрытые LFS, а непокрытый файл — отдельная ошибка линтера (ADR-0012).
- **Не писать «Timeline» в `capture.plugins`.** Без `creator.package.version` декларация не воспроизводима: с `"Latest"` в `scriptReferenceVersionOption` обновление зависимости молча меняет внешность персонажа между кадрами.
- **Не дописывать своё поле в `capture`** — `additionalProperties: false`; расширение контракта идёт в общую схему, а не обходом (ADR-0012 §9).
- **Не думать, что незахваченный выход поймает релиз.** Это WARN, не FAIL. (Гейт при нуле деклараций теперь печатает `VaM-декларации: 0 проверено`, а не молчит.)
- **Не рендерить сразу в целевом разрешении.** Ресёрч: снимайте в 8K через SuperResolution и даунсемплите — бесплатное сглаживание, ради которого VaM и выглядит дорого.
- **Не ждать, что `VN_VAM` подхватится в текущем терминале** — user-env виден только новым процессам.
- **Не ставить незнакомые плагины «на посмотреть»** перед продакшен-сессией: это компилируемый C# с доступом к файловой системе в пределах песочницы.
- **Не тащить VaM2 в конвейер.** Beta, контент VaM1 не переносится, плагины не переносятся. Оценивать — можно, закладываться — нет.
- **Не править `game/assets/`, `game/generated/`** после захвата: захват живёт в `assets_src/`, дальше всё генерируется (см. [Ассеты](16-assets.md)).

## 11. Проверка

```bash
vn pipeline doctor                 # строка «Virt-a-Mate: …» (сейчас WARN — не установлен; FAIL быть не может)
vn assets vam validate             # сейчас: «деклараций нет … VaM опционален», exit 0
vn assets vam validate --scope ch01 --no-provenance   # точечно, без записи сайдкаров
vn assets licenses                 # реестр + декларации без license
vn assets provenance verify        # цепочки: хэши артефактов и источников
vn content lint                    # в т.ч. порог бинарей ADR-0004
vn build                           # общий трек после захвата
vn release validate --flavor public
python -m pytest tools/vn/tests/test_provenance.py -q   # включая test_vam_validate_and_chain
```

Эталон на 2026-08-18 (HEAD `db28ce6`): `assets_src/vam/` содержит только `.gitkeep` (0 байт); `vn pipeline doctor` даёт `WARN Virt-a-Mate: не установлен (опционально)`; `vn release validate --flavor public` — 20 строк (18 PASS + 2 WARN: черновые дубли озвучки и зрелость контента), exit 0, и **строка про VaM в них есть всегда** — `PASS VaM-декларации: 0 проверено` (безусловная `else`-ветка, `release.py:587-596`).

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/assets/vam.py` (весь, 24 строки) и общий валидатор `../../tools/vn/src/vn/assets/sources.py` (весь, 286 строк), `../../tools/schemas/vam_render@1.schema.json`, `../../tools/vn/src/vn/assets/provenance.py:279-304` (`record_render`), `../../tools/vn/src/vn/cli.py`, `../../tools/vn/src/vn/pipeline.py:143-193` (`_steam_libraries`/`vam_path`) и `:544-548` (doctor), `../../tools/vn/src/vn/release.py:587-595`, `../../tools/install-vam.ps1`, `../adr/0006-daz-comfyui-video-pipeline.md` (§2a), `../pipeline/phase-0.md:107-130` |
| **Не трогать** | `assets_src/vam/.gitkeep` (маркер зоны), `game/assets/**` и `game/generated/**` (производные), `<output>.provenance.json` — сайдкары пишет `vn assets vam validate`, ручная правка ломает `provenance verify` по хэшу |
| **Зависимости (что ломается ниже по течению)** | Декларация → `provenance@1`-сайдкар → `vn assets provenance verify` → релизный гейт (`release.py:566-574`); `license` → `tools/vn/src/vn/assets/licenses.py:53-109` → гейт (`release.py:654-662`); `output` в `art/cg/**` → `img_cg` + `img_thumb` → `image cg …` от компилятора; `output` в `video_src/**` → `video2webm` + `mov_meta@1` |
| **Валидация** | `vn assets vam validate` → `vn assets provenance verify` → `vn assets licenses` → `vn content lint` → `vn build` → `vn release validate --flavor public` → `python -m pytest tools/vn/tests/test_provenance.py -q` |
| **Частые ошибки** | 1) Считать, что тулинг умеет запускать VaM: `vam_path()` только печатает путь, автоматизации захвата нет вообще. 2) Добавлять поле в `capture` — `additionalProperties: false`, любая «своя» пара ключ-значение = твёрдая ошибка схемы; расширение = новая версия схемы. 3) Ссылаться на `.var` в `scene` — паттерн принимает только `json/vac/vap`. 4) Ждать FAIL там, где код даёт WARN: незахваченный выход, декларация без `license`, отсутствие VaM в doctor. 5) Искать VaM в `docs/ARCHITECTURE.md` — там **ноль** упоминаний, норма живёт в ADR-0006/0007 и `docs/pipeline/phase-0.md`. 6) Класть сцены/`.var` в git — ADR-0004 порог 50 МБ красит линт и CI |
