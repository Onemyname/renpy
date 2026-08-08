# 20. Генерация изображений (ComfyUI / SD / Flux)

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — окружение и провижининг моделей автоматизированы полностью (`tools/setup-comfyui.ps1`, `tools/comfyui-models.yaml`, `vn pipeline doctor|models`), учёт происхождения написан и покрыт тестами (`vn assets provenance record|workflow|verify`). **Но** самой генерации в тулинге нет: ComfyUI-клиента (`/prompt`) не существует, в репозитории **ноль** workflow-JSON, **ноль** `*.provenance.json` и **ноль** `*.render.yaml` — каждый кадр сегодня рождается в GUI-сессии человека.
> **Отвечает на вопрос:** «Как получить картинку, которая (а) похожа на предыдущие кадры того же персонажа, (б) воспроизводима через полгода, (в) не создаёт правовой проблемы при продаже игры».

Базовый визуал проекта — **не** AI. По ADR-0006 арт-направление зафиксировано как «DAZ Studio (реализм, стиллы) + AI-анимация (ComfyUI/Wan 2.2, I2V)». Генерация изображений в этом конвейере — **полировка и вариации поверх рендера**, а не первичный источник картинки. Живёт это всё за пределами репозитория: ComfyUI в `D:\ComfyUI`, модели в `D:\ComfyUI\models\` (~35 ГБ обязательных), а в git попадают только манифест моделей, схемы и сайдкары происхождения. Про видео — [21. Генерация видео](21-video-generation.md), про DAZ — [17. DAZ Studio](17-daz-studio.md), про то, куда класть готовый PNG — [16. Ассеты](16-assets.md).

## Быстрый ответ

```bash
# 0. Проверить окружение (FAIL только на Python/ffmpeg/VP9/ffprobe/битом манифесте)
vn pipeline doctor

# 1. Развернуть/починить ComfyUI (идемпотентно, безопасно перезапускать)
pwsh -File tools/setup-comfyui.ps1

# 2. Модели: статус / загрузка
vn pipeline models                       # таблица ✓ ✗ ! ?
vn pipeline models --pull                # только required: true, auth: none
vn pipeline models --pull --all          # + опциональные (bigASP, RealESRGAN, NSFW-LoRA)

# 3. Запустить UI (в vn такой команды НЕТ — руками)
D:\ComfyUI\venv\Scripts\python.exe D:\ComfyUI\main.py

# 4. Сгенерировали PNG -> ДО переименования зафиксировать происхождение
vn assets provenance record assets_src/png/cg/ch01/kiss.png \
    --source assets_src/png/cg/ch01/kiss_render.png

# 5. В игру
vn assets build && vn build
```

Порядок шага 4 неслучаен: `record` вытаскивает seed/модель/LoRA/промпты из tEXt-чанков PNG ComfyUI. Пересохранили файл в редакторе без сохранения метаданных — параметры генерации потеряны навсегда, останется только `--note`.

---

## 1. Что мы вообще генерируем (и чего не генерируем)

| Категория ассета | Первичный источник | Роль AI | Статус в репозитории |
|---|---|---|---|
| Спрайты персонажей (`spr/**`) | DAZ-рендер слоёв | i2i-полировка кожи/материалов, вариации выражений | сырцы `assets_src/png/characters/mira/a/**` — **placeholder-PNG**, не рендер |
| Фоны (`bg/**`) | DAZ-рендер локации | полировка, вариации времени суток | 2 файла 1920×1080 |
| CG-стиллы (`cg/**`) | DAZ-рендер | полировка, композитинг, inpaint | 2 файла 1920×1080 |
| Видео-лупы (`mov/**`) | **кадр DAZ → Wan 2.2 I2V** | основной инструмент | 1 демо-луп; см. [21](21-video-generation.md) |
| UI-панели (`ui/**`) | **генерируются кодом** из `content/ui/panels.yaml` | не применяется | IMPLEMENTED, ADR-0009 |

Норма ADR-0006 §2: «Каждый нетривиальный сырец несёт `<file>.provenance.json`». То есть *любой* кадр, прошедший через ComfyUI, обязан иметь сайдкар. Обязанность документирована в `docs/onboarding/artist.md` и **не проверяется автоматически**: гейт обходит только существующие сайдкары, а PNG без сайдкара проходит релиз молча (`provenance.py:328` — `rglob("*.provenance.json")`, ничего не требует наличия).

### Что реально стоит на машине владельца (проверено 2026-08-08)

| Компонент | Факт |
|---|---|
| ComfyUI | `D:\ComfyUI` (клон `comfyanonymous/ComfyUI`), `VN_COMFYUI=D:\ComfyUI` |
| Python-окружение | `D:\ComfyUI\venv`, **PyTorch 2.11.0+cu128**, `torch.cuda.is_available() == True`, устройство `NVIDIA GeForce RTX 5080` |
| Custom nodes | только `ComfyUI-Manager` (плюс штатные `websocket_image_save.py`, `example_node.py.example`) |
| Модели | **10 из 10 позиций манифеста скачаны** — 6 обязательных + RealESRGAN + bigASP v2 + 2 Civitai NSFW-LoRA; лок `D:\ComfyUI\models\.vn-models.json` (10 записей с sha256) |
| GPU | RTX 5080, **16 ГБ** VRAM (не 32 — это определяет весь выбор моделей ниже) |
| Диски | C: 535 ГБ, D: 616 ГБ свободно |

`vn pipeline doctor` печатает «модели: все обязательные на месте (6)» — считаются только `required: true`; остальные четыре стоят тоже.

---

## 2. Установка и окружение

### 2.1 `tools/setup-comfyui.ps1` — что делает пошагово

**IMPLEMENTED.** Параметры: `-InstallRoot` (по умолчанию `D:\ComfyUI`), `-Update`, `-NoEnvVar`. Идемпотентен: каждый шаг сначала проверяет, не сделан ли он, и печатает `= … (уже сделано)`.

| # | Шаг | Строки | Что именно |
|---|---|---|---|
| 1 | Предусловия | `:52-71` | `git` в PATH (иначе fail); Python `py -3.12` → `-3.11` → `-3.10` → `python`, нужен ≥ 3.10; **≥ 30 ГБ свободно** на диске `InstallRoot` |
| 2 | Клон | `:74-84` | `git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git`; если `main.py` есть — пропуск (или `git pull --ff-only` с `-Update`) |
| 3 | venv + torch | `:87-111` | `venv` рядом с ComfyUI; проба `import torch; assert torch.cuda.is_available()`; если не проходит — `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128` |
| 4 | Зависимости | `:113-116` | `pip install -r requirements.txt` |
| 5 | ComfyUI-Manager | `:119-127` | `git clone --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git` в `custom_nodes\ComfyUI-Manager` |
| 6 | Каталоги моделей | `:130-134` | создаёт `models\{checkpoints,diffusion_models,text_encoders,vae,loras,upscale_models}`. **Модели не качает** |
| 7 | `VN_COMFYUI` | `:136-144` | User-scope переменная = `InstallRoot` (+ в текущий процесс) |
| 8 | CUDA smoke | `:146-149` | печатает версию torch, `cuda.is_available()`, имя устройства; fail, если torch не импортируется |

Шесть каталогов из шага 6 — минимум, нужный манифесту. Сам ComfyUI при первом запуске создаёт свои (`controlnet`, `clip_vision`, `model_patches`, `embeddings`, `style_models`, …) — на рабочей машине их сейчас 25. Это нормально: манифест адресует файлы относительно `<ComfyUI>/models/` (`pipeline.py:270-271`), лишние каталоги ему безразличны.

Чего скрипт **не** делает: не ставит никаких custom nodes кроме Manager, не пишет `extra_model_paths.yaml` (модели обязаны лежать именно под `<ComfyUI>/models/`), не кладёт ни одного workflow, не запускает сервер.

### 2.2 Пин cu128 для Blackwell — почему это не «на всякий случай»

RTX 50xx — архитектура Blackwell, compute capability **sm_120**. Wheel'ы PyTorch, собранные до неё, не содержат ядер под sm_120: `torch.cuda.is_available()` возвращает `True`, устройство определяется, а вычисление либо падает, либо тихо уезжает на CPU. Симптом на глаз — «CUDA есть, но кадр считается в десятки раз дольше». Отсюда правило `docs/pipeline/phase-0.md:21-27` и константа `$TorchIndex = "https://download.pytorch.org/whl/cu128"` в скрипте (`setup-comfyui.ps1:41`).

Версии torch **сознательно не пиннуты** (комментарий `setup-comfyui.ps1:106-107`): индекс cu128 отдаёт последнюю совместимую сборку. Пин появится, если апстрим что-то сломает. Практическое следствие: `tools/vn.lock` (пины тулчейна `vn`) на окружение ComfyUI **не влияет** — это два независимых мира.

> **Развилка на будущее, не решение:** ресёрч 2026 отмечает, что 4-битный путь Nunchaku/NVFP4 требует torch, собранного против **CUDA 13.0**, иначе сэмплинг «may actually be up to 2x slower than fp8» ([blog.comfy.org](https://blog.comfy.org/p/new-comfyui-optimizations-for-nvidia)). Наш пин — cu128, и ни одна NVFP4-модель в манифесте не заведена, так что противоречия сегодня нет. Если кто-то соберётся переходить на NVFP4 — это правка `setup-comfyui.ps1` и отдельный ADR, а не «просто поставлю другой torch».

### 2.3 Обнаружение ComfyUI

`comfyui_root()` (`pipeline.py:62-75`): `--comfyui` → `$VN_COMFYUI` → `D:/ComfyUI` → `C:/ComfyUI` → `~/ComfyUI`. Корнем считается каталог, в котором есть `main.py`. Хардкода нет нигде — ровно как для ffmpeg (`VN_FFMPEG`/`VN_FFPROBE`) и Ren'Py SDK (`RENPY_SDK`).

Запуск UI командой `vn` **не предусмотрен** (NOT IMPLEMENTED, и это осознанно — ComfyUI работает как GUI-сессия):

```bash
D:\ComfyUI\venv\Scripts\python.exe D:\ComfyUI\main.py
```

---

## 3. Манифест моделей `tools/comfyui-models.yaml`

**IMPLEMENTED.** Схема `comfyui_models@1` (`tools/schemas/comfyui_models@1.schema.json`), `additionalProperties: false`. Обязательные поля позиции: `id, kind, dest, auth, required, role`. `kind` — enum ровно из шести каталогов моделей; `auth` — `none | civitai_key | manual`; `commercial_use` — `allowed | restricted | unknown`.

### 3.1 Полная таблица позиций (10 штук)

| id | Файл (относительно `<ComfyUI>/models/`) | Назначение | Размер | req | auth | Лицензия / `commercial_use` |
|---|---|---|---|---|---|---|
| `wan22_i2v_high_fp8` | `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | Wan 2.2 I2V, high-noise эксперт (первая половина шагов) | 13 633 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `wan22_i2v_low_fp8` | `diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | Wan 2.2 I2V, low-noise эксперт | 13 633 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `umt5_xxl_fp8` | `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | текст-энкодер UMT5-XXL для Wan | 6 424 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `wan21_vae` | `vae/wan_2.1_vae.safetensors` | VAE Wan 2.1 (14B-модели Wan 2.2 используют его же) | 242 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `wan22_lightx2v_high` | `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | 4-шаговая дистилляция, high-noise | 1 170 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `wan22_lightx2v_low` | `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | 4-шаговая дистилляция, low-noise | 1 170 МБ | ✅ | none | Apache-2.0 / `allowed` |
| `realesrgan_x4plus` | `upscale_models/RealESRGAN_x4plus.pth` | 4×-апскейл рендеров и кадров | 64 МБ | — | none | BSD-3-Clause / `allowed` |
| `sdxl_photoreal` (bigASP v2) | `checkpoints/bigasp_v2.safetensors` | **NSFW-фотореал SDXL для i2i-полировки DAZ-рендеров** | 6 617 МБ | — | none | CreativeML-OpenRAIL-M (SDXL-производная) / **`restricted`** |
| `wan22_nsfw_general_high` | `loras/wan22_nsfw_general_high.safetensors` | универсальная NSFW-motion LoRA (high-noise) | 585 МБ | — | **civitai_key** | Civitai per-model terms / **`unknown`** |
| `wan22_nsfw_general_low` | `loras/wan22_nsfw_general_low.safetensors` | та же LoRA (low-noise) | 585 МБ | — | **civitai_key** | Civitai per-model terms / **`unknown`** |

Итого: обязательных ≈ **35 ГиБ**, опциональных ≈ **7,7 ГиБ**. `nsfw_terms_url` заполнен у трёх непермиссивных позиций. Позиций с `auth: manual` в манифесте **нет** — ветка обработки написана (`pipeline.py:428-432`), но текущим манифестом не задействована.

Для генерации *изображений* из этого списка релевантны ровно два: **bigASP v2** (SDXL-чекпойнт под i2i-полировку) и **RealESRGAN_x4plus** (апскейл). Всё остальное — видео-стек.

### 3.2 `vn pipeline models` — режимы

`cli.py:1425-1461` → `pipeline.py:362-439`.

| Вызов | Что происходит |
|---|---|
| `vn pipeline models` | только статус-таблица: `✓ ok`, `✗ missing`, `! undersized`, `? no_root` |
| `vn pipeline models --pull` | скачивает недостающие с `required: true` и `auth: none` |
| `vn pipeline models --pull --all` | + позиции с `required: false` |
| `vn pipeline models --only a,b` | **⚠ СКАЧИВАЕТ, а не показывает.** `--only` включает режим загрузки сам по себе (`cli.py:1442`: `if pull or only_set`) и перекрывает фильтр `required` |
| `--comfyui <path>` | явный корень вместо `VN_COMFYUI` |

Загрузка (`pipeline.py:333-359`): `curl -L --fail --retry 3 --retry-delay 5 -C -` в файл `<dest>.part`, затем атомарный `os.replace`. **Докачка резюмируемая** (`-C -`) — оборванная 13-гигабайтная загрузка продолжается с места разрыва. Без `curl` в PATH — фоллбек на `urllib` (уже без докачки).

Коды выхода: 1, если хоть одна загрузка не удалась. Ручные шаги и «нужен ключ» — **не ошибка**: печатается `models: OK (N ручных шагов осталось)`, exit 0.

### 3.3 Режимы `auth` и почему обход логинов запрещён

| Режим | Поведение загрузчика |
|---|---|
| `none` | прямой `curl` по `source` |
| `civitai_key` | читает `CIVITAI_API_KEY` из окружения процесса (`pipeline.py:313-315`), шлёт `Authorization: Bearer <key>`. Ключ **не попадает в логи** — заголовок собирается в памяти |
| `manual` | ничего не качает: печатает URL, роль модели и точный целевой путь (`pipeline.py:428-432`) |

Норма ADR-0006 §3: «Загрузчик не обходит логины/лицензии (auth: manual = честная остановка с инструкцией)». Это архитектурное решение, а не недоделка: скрипт, обходящий gate принятия лицензии, делает правовой статус модели непроверяемым. Если новая модель требует принятия EULA — она заводится с `auth: manual`, а не «а я нашёл прямую ссылку».

### 3.4 `CIVITAI_API_KEY` и грабля `setx`

```powershell
# civitai.com -> Account Settings -> API Keys -> Add API key (Read-only достаточно;
# в настройках аккаунта включите показ взрослого контента, иначе файл не отдастся)
setx CIVITAI_API_KEY "<ключ>"
# ЗАТЕМ ОТКРОЙТЕ НОВЫЙ ТЕРМИНАЛ
vn pipeline models --pull --all
```

`setx` пишет значение в `HKCU\Environment`, но **уже запущенные процессы своё окружение не перечитывают**. В том же терминале `vn` ключа не увидит. Тулинг это распознаёт: `_civitai_key_in_registry()` (`pipeline.py:318-330`) лезет в реестр через `winreg` и, если ключ там есть, печатает «ключ ЕСТЬ в User-окружении, но не виден этому процессу — откройте НОВЫЙ терминал». Если ключа нет вообще — печатает 3-шаговую инструкцию.

### 3.5 Честно про целостность: `sha256: null` у всех позиций

У **всех десяти** записей манифеста `sha256: null`. Механизм сверки написан (`pipeline.py:414-419`: несовпадение → файл удаляется, засчитывается ошибка), но сравнивать не с чем. Что происходит на самом деле:

1. После первой успешной загрузки sha256 **вычисляется** и записывается в `<ComfyUI>/models/.vn-models.json` вместе с `size_mb`, `downloaded_at`, `source`.
2. Файл лока **не в git** — он локальный. У другого разработчика будет свой.
3. При повторных прогонах `model_status()` (`pipeline.py:290-302`) сверяет **только размер**: `|фактический − lock.size_mb| > 1 МБ` → `undersized`; либо `фактический < manifest.size_mb × 0.5` → `undersized`. **sha256 повторно не проверяется никогда.**

Следствие: манифест **не защищает от подмены модели в апстриме** и не ловит битый файл того же размера. Если это станет важно (а для коммерческого релиза со ссылкой на `chain[].model` в провенансе — станет), правильный ход: скопировать хэши из своего `.vn-models.json` в поле `sha256` манифеста и закоммитить. Это единственная строчка, которая превращает механизм из декоративного в рабочий.

---

## 4. Актуальный стек моделей 2026 — практичный срез

Ниже — выжимка из веб-ресёрча, ограниченная тем, что имеет смысл для **этого** проекта: фотореализм, взрослый контент, **16 ГБ VRAM**, коммерческая дистрибуция. Полные обзоры моделей сюда не переносятся.

> Про VRAM без иллюзий: RTX 5080 — **16 ГБ**, и это потолок. Все рекомендации ниже — под 16 ГБ. FLUX.2 [dev] (32B) на такой карте не запускается; 24 ГБ «5080 SUPER» на 2026-08 не подтверждён как отгружаемый SKU.

| Задача | Чем делать | Лицензия | Что у нас |
|---|---|---|---|
| i2i-полировка DAZ-рендера, NSFW-фотореал | **bigASP v2** (SDXL) | OpenRAIL-M-производная, `restricted` | ✅ скачан |
| Массовая генерация/итерации, вариации выражений | **Z-Image-Turbo** (6B, 8 шагов, **CFG 0.0**) | Apache-2.0 | ❌ не в манифесте |
| Hero-CG с мульти-референсом персонажа | **FLUX.2 [klein] 4B** (multi-reference до 10 картинок) | **Apache-2.0** (только 4B!) | ❌ не в манифесте |
| Текст внутри картинки (вывески, телефон, документы) | **Qwen-Image / Qwen-Image-Edit-2511** | Apache-2.0 | ❌ не в манифесте |
| Взрослый контент без RAIL-ограничений use-based | **Chroma1-HD** (8.9B, без safety-alignment) | Apache-2.0 | ❌ не в манифесте |
| Поза (ControlNet) | union-чекпойнт **под конкретную базу**, кросс-модельных нет | зависит от базы | ❌ ни одного |
| Апскейл | **Real-ESRGAN** / Ultimate SD Upscale поверх своей базы | BSD-3 / GPL-3.0 (код нод) | ✅ RealESRGAN скачан |
| Апскейл — **НЕ брать** | **SUPIR** | явно **non-commercial** | — |
| Видео-лупы | Wan 2.2 I2V + LightX2V | Apache-2.0 | ✅ весь стек скачан |

Три вещи, которые стоит держать в голове при добавлении любой модели:

1. **Одинаковое имя ≠ одинаковая лицензия.** FLUX.2 klein-**4B** — Apache-2.0; klein-**9B** и dev — FLUX Non-Commercial License. Перепутать легко, цена ошибки — весь релизный арт.
2. **ControlNet не переносится между базами.** ControlNet под FLUX.1 не работает с FLUX.2; Z-Image-овский union кладётся в `models\model_patches`, а не в `controlnet`. Если поза — критичный инструмент, это аргумент выбирать базу с готовой control-экосистемой.
3. **Turbo-чекпойнты требуют своих настроек.** Z-Image-Turbo хочет CFG **0.0** и 8 шагов; подача CFG 7 даёт кашу, после чего люди обвиняют модель. И LoRA под Z-Image тренируются на **Base**, а не на Turbo.

Все перечисленные модели, кроме уже скачанных, — **NOT IMPLEMENTED в нашем конвейере**: их нет в `tools/comfyui-models.yaml`, а значит нет ни воспроизводимой установки, ни зафиксированного правового статуса. Порядок добавления — §«Как изменить».

---

## 5. Консистентность персонажа

Главная практическая проблема AI-арта в новелле: читатель за 20 часов игры замечает, что лицо «поехало». Средства ниже упорядочены **по надёжности**, а не по моде. Правило: применяй самое верхнее, что решает задачу; спускайся ниже только когда верхнее не справляется.

### (а) Исходник идентичности — DAZ Character Preset · **основной путь проекта**

Идентичность персонажа задаётся не промптом, а **файлом**: пресет морфов/материалов в DAZ. Один и тот же пресет даёт биометрически одинаковое лицо в любой позе, при любом свете, в любом кадре — детерминированно, без seed-лотереи.

- Место в декларации: `render.character_presets` (массив строк) в `assets_src/daz/**/<name>.render.yaml`, схема `daz_render@1`.
- Цена: время на сборку пресета и рендер (минуты на кадр вместо секунд).
- **Честно:** поле `character_presets` схемой принимается, но **ничем не валидируется** — реестра пресетов, конвенции их именования и проверки «тот ли пресет» в репозитории нет (`tools/vn/src/vn/assets/daz.py:31-77` делает только проверку существования файлов). Деклараций `*.render.yaml` в репозитории **ноль**.

### (б) i2i-полировка поверх рендера с низким denoise · **рекомендуемый AI-шаг**

Берём готовый DAZ-рендер и прогоняем через SDXL (у нас — bigASP v2) с `denoise` в районе 0.2–0.35. Модель добавляет микрорельеф кожи, поры, реалистичное освещение — и **не имеет свободы переписать лицо**, потому что структура уже задана.

- Когда: почти всегда, это дефолтный AI-шаг проекта.
- Цена: `denoise` — единственный регулятор. Поднял выше ~0.45 — начинает уезжать геометрия лица, и вся консистентность из шага (а) обнуляется. Фиксируйте `denoise` один раз для персонажа и не трогайте между кадрами.
- Провенанс: `denoise` — одно из полей, которое `comfyui_step_from_graph` вытаскивает из сэмплера автоматически (`provenance.py:196`). То есть «какой denoise был на том кадре» — отвечаемый вопрос, если сайдкар написан.

### (в) LoRA на персонажа

Обученный на 20–50 кадрах персонажа адаптер — самый надёжный AI-якорь идентичности, если генерация идёт **без** исходного рендера.

- Когда: если однажды понадобится генерить персонажа с нуля (промо-арт, вариации, которые в DAZ дороже).
- Цена: **VRAM.** 16 ГБ хватает на SDXL-ветку; для Z-Image/Qwen/FLUX.2 практика 2026 — арендовать GPU-под. Это регулярная статья расходов, а не разовая.
- Инструменты (из ресёрча, статус на 2026): **ai-toolkit** (ostris, MIT) — держит темп релизов моделей, поддерживает FLUX.1/FLUX.2, Qwen-Image, Z-Image, SDXL; **kohya-ss/sd-scripts** (v0.11.1, июнь 2026) — лучший документированный путь для SDXL/Illustrious, **FLUX.2 не поддерживает**; **OneTrainer** (AGPL-3.0) — один GUI на всё, включая Chroma. Правило выбора: SDXL → kohya, Z-Image/Qwen/FLUX.2 → ai-toolkit.
- Провенанс: LoRA попадают в сайдкар как `loras: [{name, strength}]` из узлов `LoraLoader*` (`provenance.py:185-187`) — но **только имя файла**, не хэш. Переобучили LoRA под тем же именем — старые кадры стали невоспроизводимы молча. Версионируйте имя файла: `mira_v3.safetensors`, не `mira.safetensors`.

### (г) Мульти-референс и IP-Adapter/PuLID-класс

Ресёрч 2026 однозначен: **эпоха IP-Adapter как основы закончилась**. Референсная реализация `cubiq/ComfyUI_IPAdapter_plus` (GPL-3.0) переведена автором в режим maintenance-only — строить на ней шиппинг-конвейер нельзя. Актуальная замена — нативное мульти-референсное кондиционирование: FLUX.2 принимает до 10 референсов, Qwen-Image-Edit-2511 умеет identity-preserving re-pose.

- Когда: новая поза/наряд по уже утверждённым рендерам, без обучения LoRA.
- Цена: качество зависит от качества референсов; результат менее детерминирован, чем (а)/(б).
- **Ни одна из этих моделей у нас не установлена.**

### (д) Inpaint лица — последнее средство и главный инструмент матрицы эмоций

Маскируем только лицо, тело/поза/наряд остаются нетронутыми пиксельно.

- Когда: (1) точечная починка одного кадра; (2) **матрица выражений** — заблокировали позу, перегенерировали 12 эмоций только по лицу. Это дешевле и консистентнее, чем перекатывать спрайт целиком.
- Инструмент: `VAE Encode (for Inpainting)`, ключевой параметр `grow_mask_by` — расширение маски наружу, чтобы не было жёсткого шва. Мало — видно кольцо; много — модель переписывает челюсть, и персонаж уезжает. Подберите один раз и **заморозьте**.
- Специализированные inpaint-чекпойнты дают лучший переход, чем универсальные — это подтверждено официальным туториалом ComfyUI.
- Цена: маска — ручная работа; в текущем конвейере автоматизации нет.

### Что НЕ делать для консистентности

**Регионально промптить двух персонажей в одном кадре ради спрайтов.** В новелле два персонажа — это два спрайта, поставленные `left`/`right` средствами Ren'Py. Так они независимо меняют эмоции, переиспользуются между сценами и не требуют перегенерации кадра при правке одной реплики. Regional prompting/Attention Couple оправдан только для запечённого CG, где персонажи физически взаимодействуют.

---

## 6. Конвейер кадра: вход → выход → инструмент

| # | Шаг | Вход | Выход | Инструмент | Статус |
|---|---|---|---|---|---|
| 1 | Prompt / бриф кадра | сценарий сцены | текст + референсы | человек | — |
| 2 | Base generation | DAZ-сцена + Character Preset | `assets_src/png/…/<name>_render.png` (1920×1080) | DAZ Studio, Iray | **NOT IMPLEMENTED** (рендер только вручную в GUI; `.dsa`-скриптов, headless-запуска и сборщика секвенций в репозитории нет) |
| 3 | Character consistency | рендер шага 2 | тот же кадр, «дожатый» | ComfyUI i2i, `denoise` 0.2–0.35 | **NOT IMPLEMENTED в тулинге** — GUI-сессия |
| 4 | Pose | скелет/depth | контролируемая композиция | ControlNet под базу | **NOT IMPLEMENTED** — ни одного ControlNet-файла |
| 5 | Composition | несколько слоёв | собранный кадр | ComfyUI / редактор | — |
| 6 | Inpaint | кадр + маска лица | вариант выражения | `VAE Encode (for Inpainting)` | **NOT IMPLEMENTED в тулинге** |
| 7 | Upscale | кадр | 2×/4× | RealESRGAN_x4plus (BSD-3) | модель **есть**, workflow нет |
| 8 | Post-process | PNG | финальный PNG | см. [24. Постобработка](24-post-processing.md) | — |
| 9 | **QA + провенанс** | PNG | `<file>.provenance.json` | `vn assets provenance record` | **IMPLEMENTED**, ни разу не запускалось на реальном контенте |
| 10 | Export в игру | `assets_src/png/**` | `game/assets/{cg,bg,spr}/**.webp` | `vn assets build` → `vn build` | **IMPLEMENTED** |

Шаги 2–8 сегодня — **человек в GUI**. В `vn` нет ComfyUI-клиента: ни `requests`/`httpx` к серверу, ни порта 8188, ни `POST /prompt`, ни `GET /history`, ни websocket. Автоматизация этого куска — самая крупная незакрытая позиция конвейера ([37. Roadmap](37-roadmap.md)).

Что важно про переход 9→10: `vn assets build` **не читает провенанс вообще** (`grep -n provenance tools/vn/src/vn/assets/pipeline.py` → пусто). Связь «собранный ассет ↔ цепочка происхождения» существует только через совпадение blake3: `src_hash` в `.vncache/assets-manifest.json` против `artifact.hash.hex` в сайдкаре. Автоматического джойна нет.

---

## 7. Разрешения, соотношения, именование

### 7.1 Целевые разрешения проекта

Игра — **1920×1080** (см. `game/options.rpy` / [05. Ren'Py](05-renpy-development.md)).

| Ассет | Генерировать | Класть в | На выходе | Основание |
|---|---|---|---|---|
| Фон | 1920×1080 (или выше с даунскейлом) | `assets_src/png/backgrounds/<loc>/<variant>.png` | `bg/<loc>/<variant>.webp`, q90 | фактические сырцы 1920×1080 RGB |
| CG-стилл | 1920×1080 | `assets_src/png/cg/<...>/<name>.png` | `cg/….webp` (q90) **+ `cg/….thumb.webp`** | `pipeline.py:148-157` |
| Превью галереи | не генерировать | — | `.thumb.webp`, длинная сторона **512**, q80 | `pipeline.py:226-229` — считается автоматически |
| Спрайт персонажа | **1200×2200 RGBA** (холст `canvas` у `mira`) | `assets_src/png/characters/<char>/<pose>/{base,outfits/*,faces/*}.png` | `spr/…/<name>@2.webp`, q95 | `content/characters/mira/character.yaml:6`, фактические PNG 1200×2200 |
| UI-панель | **не генерировать вообще** | `content/ui/panels.yaml` | `ui/<id>.webp` lossless | ADR-0009, рисуется кодом |

**Три ловушки, каждая проверена по коду:**

1. **`@2` дописывает конвейер, а не вы.** Сырец называется `base.png`, `faces/smile.png`. Суффикс `@2` появляется в имени выходного файла (`pipeline.py:120-121,133`) и включает оверсэмплинг Ren'Py. Положили `base@2.png` — получите `base@2@2.webp` и сломанный слой.
2. **`canvas` в `character.yaml` — документация, а не контракт.** Его не читает ни одна строка кода (grep по `tools/vn/src/vn/` и `game/framework/` — ноль). Валидатор не сверит вашу картинку с объявленным холстом. Подробности — [10. Персонажи](10-characters.md).
3. **Все слои одной позы обязаны быть одного размера.** Это требование `layeredimage` Ren'Py, а не нашего тулинга: слои накладываются в одних координатах. Никакой проверки в `vn` нет — рассинхрон вы увидите как съехавшее лицо в игре.

### 7.2 Именование и NSFW

Норма — `docs/conventions/naming.md`. Ключевое для генерации:

- Логический id ассета: `^(bg|cg|spr|mov|ui|vfx|bgm|amb|sfx)/[a-z0-9_/]+$`. Каждый сегмент пути — slug `^[a-z][a-z0-9_]*$`, проверяет `_check_slug` (`pipeline.py:98-103`). Пробел, дефис, кириллица, заглавная — красная сборка.
- **Контент 18+ — только в подпапке `nsfw/` своей категории**: `assets_src/png/cg/nsfw/…`, `assets_src/video_src/nsfw/…`. По этой конвенции public-флейвор вырезает файлы на этапе distribute. Ошиблись папкой — 18+ уехал в публичную сборку; гейт ловит **каталоги, не содержимое** (ADR-0006 §4).
- Слуг живёт только в имени файла/папки; id и label неизменяемы навсегда (G7).

---

## 8. Воспроизводимость и провенанс

### 8.1 Что вообще нужно зафиксировать

Кадр воспроизводим, если известны **все четыре**:

| Что | Где фиксируется у нас | Надёжность |
|---|---|---|
| **Seed** | `chain[].seed` — из первого узла графа с `seed`/`noise_seed` | автоматически, если сайдкар написан |
| **Модель** | `chain[].model` — из `CheckpointLoaderSimple`/`*UNETLoader` | только **имя файла**; `model_hash` в схеме есть, кодом не заполняется |
| **Версия LoRA** | `chain[].loras[].name` + `strength` | только имя; версионируйте имя файла вручную |
| **Версия workflow** | `chain[].workflow_hash` = blake3 API-графа | автоматически |

Плюс то, что **не фиксирует никто**: версия ComfyUI, коммиты custom nodes, версия torch. Ресёрч 2026 рекомендует ComfyUI-Manager **Snapshot-Manager** как механизм заморозки окружения — у нас это NOT IMPLEMENTED и даже не заявлено. Практический минимум сегодня: не обновлять ComfyUI посреди производства главы.

### 8.2 Три команды провенанса

**IMPLEMENTED** (`tools/vn/src/vn/assets/provenance.py`, 11 тестов в `tools/vn/tests/test_provenance.py`), **UNEXERCISED** — в репозитории ноль сайдкаров.

```bash
# Записать: PNG из ComfyUI разбирается автоматически
vn assets provenance record <artifact> [--source <исходник>] [--workflow api.json] \
                                       [--note "..."] [--model ...] [--seed N]

# Восстановить граф (пригоден для загрузки обратно в ComfyUI)
vn assets provenance workflow <artifact> [--out graph.json]

# Сверить все цепочки
vn assets provenance verify [--scope <подпуть в assets_src>]
```

Как `record` достаёт параметры (`provenance.py:80-98`, `:160-199`): PIL открывает PNG, читает tEXt-чанки `prompt` (API-граф) и `workflow` (UI-граф), парсит JSON. Дальше по `class_type` узлов: `CheckpointLoaderSimple`/`CheckpointLoader` → `model`; `*UNETLoader` → `model`; `LoraLoader*` → `loras[]`; `EmptyLatentImage`/`EmptySD3LatentImage` → `resolution`. Сэмплером считается **первый узел, у которого в `inputs` есть `seed` или `noise_seed`** — из него `seed/steps/cfg/sampler_name/denoise`. Промпты трассируются по ссылкам `inputs.positive`/`negative` до узла со строковым `inputs.text`, максимум **8 переходов** (терпит цепочки Reroute).

Если параметры не извлеклись и `--note` не передан — жёсткая ошибка: «параметры генерации не извлекаются (не PNG ComfyUI) — передайте `--workflow <api.json>` или опишите шаг через `--note`». С `--note` пишется шаг `kind: manual`.

**Ограничение G2:** провенанс ведётся **только** для файлов внутри `assets_src/` (`provenance.py:50-56`). Попытка записать сайдкар для файла в `game/assets/` — `ProvenanceError`.

### 8.3 Формат сайдкара

Путь: `<artifact>.provenance.json` рядом с артефактом. Схема `provenance@1`, хэши — **blake3** везде.

```json
{
 "schema": "provenance@1",
 "artifact": {"path": "png/cg/ch01/kiss.png", "hash": {"algo": "blake3", "hex": "…"}},
 "pipeline": "vn 0.1.0",
 "updated_at": "2026-08-08T12:00:00+00:00",
 "chain": [
  {"kind": "daz_render", "source": {"path": "daz/ch01/kiss/scene.duf", "hash": {…}},
   "declaration": "daz/ch01/kiss/kiss.render.yaml",
   "settings": {"resolution": [1920,1080], "renderer": "iray", "camera": "cam_main"}},
  {"kind": "comfyui", "source": {"path": "png/cg/ch01/kiss_render.png", "hash": {…}},
   "workflow": null, "workflow_hash": {"algo": "blake3", "hex": "…"},
   "model": "bigasp_v2.safetensors", "seed": 12345, "denoise": 0.3,
   "loras": [], "resolution": [1920,1080], "sampler": "dpmpp_2m", "steps": 30, "cfg": 5.0,
   "prompt": "…", "negative_prompt": "…"}
 ]
}
```

`chain[]` — строгий `oneOf` из пяти видов шагов: `daz_render | vam_render | sims4_render | comfyui | manual`. Цепочка строится так: провенанс `--source` копируется как **префикс**, шаг текущего артефакта добавляется в конец (`provenance.py:217-227`). Шаг-происхождение (`*_render`) всегда встаёт в **начало** и заменяет предыдущий — у артефакта один источник (`provenance.py:283-285`).

### 8.4 Что проверяет `verify` и где он в релизе

`provenance.py:319-380`, вызывается из релизного гейта (`release.py:337-345`).

| Уровень | Условие |
|---|---|
| **ERROR** (FAIL релиза) | битый JSON; нарушение схемы; артефакт отсутствует; blake3 артефакта ≠ записанному («изменён после записи провенанса»); источник существует локально, но его хэш изменился |
| **WARNING** | `kind: comfyui` без инлайн-графа, чей `workflow_hash` не находится в хранилище; источника нет ни локально, ни в манифесте; хэш в манифесте хранилища разошёлся с записанным |

**Дыра, которую надо знать:** PNG **без** сайдкара проходит все гейты. `verify` обходит только существующие `*.provenance.json`; требования «у каждого файла в `assets_src/png/cg/**` должен быть провенанс» нет нигде. Дисциплина держится на человеке.

---

## 9. Где хранить ComfyUI-workflow'ы

**Текущее состояние: NOT IMPLEMENTED / ноль файлов.** В репозитории нет ни одного workflow-JSON (`find . -iname "*workflow*"` находит только `.github/workflows`). `docs/pipeline/phase-0.md:174` отправляет художника к **штатному шаблону ComfyUI** (Templates → Video, Wan 2.2 I2V) — своего графа проект не поставляет.

Механизм хранения при этом **уже написан** (`provenance.py:128-157`):

- `store_workflow()` считает blake3 от `json.dumps(api_graph, sort_keys=True)` и кладёт `{"prompt": api, "workflow": ui}` в хранилище сырцов под ключом `workflows/<blake3>`. При `.vnstorage.yaml` (`default: {type: file, path: "~/vn-assets-store"}`) физически это `~/vn-assets-store/objects/workflows/<hex>`.
- Если хранилище недоступно — граф **инлайнится** в `chain[].workflow` (аварийный fallback; обоснование прямо в коде `:240-242`: «потерять воспроизводимость хуже, чем раздуть git»).
- Обратная операция — `vn assets provenance workflow <artifact>`: берёт **последний** `comfyui`-шаг, предпочитает инлайн, иначе тянет из хранилища по `workflow_hash`, печатает или пишет в `--out`.

**Проблема здесь и сейчас:** `~/vn-assets-store` **не существует** на этой машине, а бэкенд `type: s3` честно кидает `StorageError` (NOT IMPLEMENTED, `storage.py:129-133`). То есть первый же `provenance record` из PNG уйдёт в инлайн-fallback и раздует сайдкар полным графом.

### Рекомендация (конкретная, с учётом того, что уже есть)

Не изобретать вторую систему. Порядок действий:

1. **Поднять хранилище** — это одна команда создания каталога: `mkdir ~/vn-assets-store`. После этого `store_workflow` заработает, графы поедут в контент-адресуемое хранилище с дедупликацией (одинаковые графы = один объект), а сайдкары останутся маленькими.
2. **Держать в git «эталонные» графы по классам кадров**, а не по кадрам. Ресёрч 2026 рекомендует `workflow_api.json` в git — но по одному на *класс ассета*, не на каждый артефакт. Предлагаемая конвенция (**сегодня её не существует; это предложение, а не действующая норма**):

```
tools/workflows/
  cg_polish@1.api.json          # i2i-полировка DAZ-рендера (bigASP, низкий denoise)
  sprite_expression@1.api.json  # inpaint лица под матрицу эмоций
  upscale_x4@1.api.json         # RealESRGAN
  README.md                     # какой граф под какую задачу, какие модели нужны
```

   Версия — суффиксом `@N`, как у схем (G16): правка графа, меняющая результат, = **новый файл** `cg_polish@2.api.json`, старый остаётся. Это делает историю кадров читаемой: «все кадры главы 1 сделаны на `cg_polish@1`».

3. **Ссылаться на граф из провенанса — по хэшу, а не по имени.** `workflow_hash` уже пишется автоматически и уже точнее любого имени файла. Имя из `tools/workflows/` — для человека, хэш — для машины. Соответствие «хэш ↔ файл в git» проверяется тривиально: `vn assets provenance workflow <artifact> --out /tmp/g.json` и `diff` с эталоном.
4. **`.render.yaml` про AI ничего не знает и знать не должен** — схемы `daz_render@1`/`vam_render@1`/`sims4_render@1` описывают только шаг-происхождение (`additionalProperties: false`, добавить поле нельзя). Связь «рендер → AI-шаг» выражается цепочкой провенанса: `record <ai.png> --source <render.png>`.

> Экспорт из ComfyUI: `/prompt` принимает **API-формат**, а не то, что сохраняет UI. Меню — `File → Export Workflow (API)`. На этом спотыкаются все ровно один раз.

---

## 10. Лицензии моделей (ADR-0008)

**ADR-0008 — единственный НЕ принятый ADR проекта** (статус: «предложено, требуется решение владельца по §Развилке»). Пока решения нет, действуют только его принятые пункты.

### Что уже действует

1. Правовой статус модели — **обязательная метадата**: `commercial_use` и `nsfw_terms_url` в `comfyui_models@1`, `license` заполнен у всех позиций.
2. **Ядро конвейера — чисто permissive.** Wan 2.2 I2V ×2, UMT5, VAE, LightX2V ×2 — Apache-2.0; RealESRGAN — BSD-3. Первая глава производится без правовых вопросов.
3. Модели с `restricted`/`unknown` — **`required: false`**, вне критического пути.
4. Дисциплина: новая модель заводится с заполненными `license`/`commercial_use`; `unknown` допустим **только** для `required: false`.

### Открытая развилка (bigASP v2 + Civitai NSFW-LoRA)

| Вариант | Суть | Плюсы | Минусы |
|---|---|---|---|
| **A** (рекомендация ADR) | использовать, зафиксировав снимок условий и дату | полный доступ к фотореалу и NSFW-моушену | автор Civitai может изменить условия; нужна перепроверка при обновлении |
| **B** | только permissive: статика — чистый DAZ, движение — Wan | нулевой правовой хвост | хуже фотореализм кожи, беднее NSFW-моушен |
| **C** (безопасный дефолт) | permissive для релиза; `restricted` — только внутренние превью | компромисс | дисциплина «что где» на художнике |

**Пока решение не принято, безопаснее считать, что действует C.** Обе NSFW-LoRA и bigASP v2 физически скачаны на машину — это не то же самое, что разрешение шипить сделанное ими.

### Таблица «модель → лицензия → коммерция → взрослый контент»

Все ссылки — на официальные страницы, проверенные в ресёрче. **Юридических выводов здесь нет:** перед коммерческой дистрибуцией проверьте актуальный EULA/лицензию по официальной ссылке.

| Модель | Лицензия | Официальная ссылка | Коммерческое использование | Взрослый контент |
|---|---|---|---|---|
| Wan 2.2 I2V / UMT5 / VAE / LightX2V *(у нас)* | Apache-2.0 | https://www.apache.org/licenses/LICENSE-2.0 | permissive | лицензия тематику не ограничивает |
| Real-ESRGAN *(у нас)* | BSD-3-Clause | https://github.com/xinntao/Real-ESRGAN | permissive | не ограничивает |
| **bigASP v2** *(у нас, `restricted`)* | CreativeML OpenRAIL-M (SDXL-производная) | https://huggingface.co/fancyfeast/big-asp-v2 | permissive по коммерции, **но** несёт use-based restrictions (Приложение A) | ADR-0008: взрослый контент со совершеннолетними вымышленными персонажами в перечень запретов не входит; запрещены эксплуатация несовершеннолетних и материалы, порочащие реальных лиц |
| **Civitai NSFW-LoRA ×2** *(у нас, `unknown`)* | per-model terms автора | https://civitai.com/models/1307155 | **единой лицензии нет**, флаги автора могут меняться | определяется карточкой модели |
| Z-Image-Turbo / Base | Apache-2.0 | https://huggingface.co/Tongyi-MAI/Z-Image-Turbo | permissive | не ограничивает |
| Qwen-Image / -Edit | Apache-2.0 | https://github.com/QwenLM/Qwen-Image | permissive | не ограничивает |
| Chroma1-HD / Base | Apache-2.0 | https://huggingface.co/lodestones/Chroma1-HD | permissive | карточка прямо отмечает отсутствие safety-alignment |
| **FLUX.2-klein-4B** | Apache-2.0 | https://huggingface.co/black-forest-labs/FLUX.2-klein-4B | permissive на веса | политика использования BFL распространяется и на производные — читать |
| **FLUX.2-dev, klein-9B** | FLUX Non-Commercial License v2.0 | https://bfl.ai/legal/non-commercial-license-terms | **модель non-commercial**; про Outputs отдельная формулировка | там же |
| Политика использования BFL | — | https://bfl.ai/legal/usage-policy | заявляет применимость к производным моделей | — |
| SD 3.5 | Stability AI Community License | https://stability.ai/license · https://stability.ai/community-license-agreement | бесплатно коммерчески **до $1M годовой выручки** | — |
| Illustrious XL v1.0+ | поле HF `sdxl-license` (CreativeML Open RAIL++-M) + сервисный ToS Onoma | https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.0 · https://www.illustrious-xl.ai/terms-of-service | RAIL use-restrictions; ToS ограничивает коммерцию **сервиса**, про мерджи молчит | цепочка мерджей = непрослеживаемая лицензия |
| **SUPIR** (апскейл) | кастомная **non-commercial** | https://github.com/kijai/ComfyUI-SUPIR/blob/main/LICENSE | **явно запрещена** без письменного разрешения | — |
| Ultimate SD Upscale (ноды) | GPL-3.0 | https://github.com/ssitu/ComfyUI_UltimateSDUpscale | copyleft на код нод; веса — по вашей базе | — |
| ai-toolkit / OneTrainer (тренеры) | MIT / AGPL-3.0 | https://github.com/ostris/ai-toolkit · https://github.com/Nerogar/OneTrainer | тренер лицензию **обученной LoRA** не ограничивает; правит базовая модель | — |

**Что стоит внутренне усвоить (формулировки ADR-0008 и ресёрча, не юридический вывод):**

- Apache-2.0/BSD/MIT **контент-нейтральны**. OpenRAIL — **нет**: у него есть приложение с ограничениями по применению.
- **Разрешение лицензии ≠ разрешение площадки.** Steam, Patreon, itch.io и платёжные провайдеры имеют собственные правила по взрослому контенту и раскрытию AI, они строже и меняются быстрее любой модельной лицензии. Это отдельный блокер — см. [33. Безопасность и правовое](33-security-and-legal.md).
- **Лицензии моделей и лицензии ассетов — разные механизмы.** Модели: `tools/comfyui-models.yaml`, гейта нет. Ассеты (DAZ-продукты, шрифты, музыка): `content/licenses.yaml` (`license_registry@1`) + `vn assets licenses`, **гейт есть** и он в релизе (`release.py:408-417`): неизвестный id лицензии → FAIL, `game_use: false` → FAIL, выход в `nsfw/` от ассета с `nsfw_allowed: false` → FAIL.
- **Авто-гейта «модель с `commercial_use != allowed` не должна участвовать в релизном контенте» НЕТ** — NOT IMPLEMENTED, ждёт решения по развилке. `commercial_use` сегодня читается только для печати таблицы. План отступления, если условия изменятся: найти затронутые артефакты запросом по `chain[].model` в сайдкарах и перегенерировать на permissive-стеке — что работает только при живой дисциплине провенанса.

---

## 11. Типичные ошибки

| Симптом | Причина | Лечение |
|---|---|---|
| **OOM на Wan 14B / SDXL при 16 ГБ** | жирный граф, высокое разрешение, резидентный текст-энкодер | fp8-модели из манифеста; 480→720p максимум для видео; LightX2V 4 шага; offload в RAM у ComfyUI автоматом (61 ГБ хватает) |
| **«CUDA есть, а ядра не идут»** — генерация в 10–50× медленнее | torch не cu128: wheel не знает sm_120 | `vn pipeline doctor` → строка `PyTorch …, CUDA доступна`; перезапустить `tools/setup-comfyui.ps1`; при упорстве снести `D:\ComfyUI\venv` |
| То же в DAZ: Iray считает часами, GPU молчит | ветка DAZ 4.x (Iray там собран до Blackwell и RTX 50xx не поддерживает вообще) или сцена не влезла в VRAM → тихий CPU-fallback | **DAZ Studio 6** + драйвер NVIDIA ≥ 576.57 (R575) — на 4.x обходного пути нет, см. [DAZ Studio](17-daz-studio.md) §2.3 и [Рендеринг](22-rendering.md) §7; **снять галку CPU** в Devices, чтобы падало явно; Scene Optimizer |
| **Лицо расползается между кадрами** | denoise слишком высокий (>0.45) на i2i; либо генерация «с нуля» без якоря идентичности | вернуться к лестнице §5: (а) один Character Preset, (б) фиксированный низкий denoise, (д) inpaint только лица |
| **Seed потерян** | PNG пересохранён редактором/конвертером — tEXt-чанки срезаны | `vn assets provenance record` **до** любой постобработки. Проверка: чанк `prompt` должен пережить весь экспорт-чейн |
| **Забытый провенанс** | сайдкар не написан, и никакой гейт этого не заметил | дисциплина + `vn assets provenance verify` вручную; авто-требования нет (§8.4) |
| **Артефакты апскейла** | апскейл там, где он не нужен | генерировать сразу в целевом разрешении; RealESRGAN брать для чистого 2×, а не для «дорисуй детали»; downscale безопасен, upscale читается как каша |
| **Несоответствие цветового профиля** | `_webp_encode` (`pipeline.py:82-91`) делает `im.convert("RGBA")` и сохраняет WebP **без `icc_profile`** — встроенный ICC теряется | работайте в sRGB от DAZ до финального PNG; не подавайте на вход Adobe RGB / P3 — цвет уедет молча, ошибки не будет |
| Спрайт «съехал» относительно лица | слои одной позы разного размера | все PNG позы — один холст (у `mira` — 1200×2200); валидатора нет |
| `vn pipeline models --only …` внезапно начал качать 13 ГБ | `--only` включает pull сам по себе (`cli.py:1442`) | для статуса — `vn pipeline models` без флагов |
| Civitai: «нужен ключ» сразу после `setx` | окружение не наследуется в открытый процесс | **новый** терминал; `vn` сам это распознаёт и подсказывает |

---

## Как изменить / Как расширить

### Добавить модель в конвейер

1. Открыть `tools/comfyui-models.yaml`, добавить запись. Обязательные поля схемы: `id` (`^[a-z][a-z0-9_]*$`), `kind` (один из шести), `dest`, `auth`, `required`, `role`.
2. **Заполнить `license` и `commercial_use`** — дисциплина ADR-0008 §3. `unknown` допустим **только** при `required: false`. Для непермиссивных — ещё `nsfw_terms_url`.
3. Если модель требует логина/принятия EULA — `auth: manual`. Прямую ссылку в обход gate ставить **нельзя** (ADR-0006 §3).
4. Проверить схему: `vn pipeline doctor` (битый манифест — единственный FAIL из этой области).
5. Скачать: `vn pipeline models --pull --all` (или `--only <id>`).
6. **Зафиксировать sha256:** взять хэш из `<ComfyUI>/models/.vn-models.json` и вписать в поле `sha256` манифеста. Это единственное, что превращает проверку целостности из декоративной в настоящую.

### Добавить workflow

Действующей нормы **нет**. Предложение — §9: `tools/workflows/<class>@<N>.api.json` (API-формат!) + `README.md`; версия суффиксом; правка, меняющая результат, = новый файл. Заводить каталог стоит вместе с первым реальным графом, не раньше.

### Включить контентно-адресуемое хранилище графов

```bash
mkdir ~/vn-assets-store          # путь из .vnstorage.yaml
vn assets provenance record <png> --source <render.png>
vn assets provenance workflow <png> --out /tmp/graph.json   # проверка round-trip
```

Без этого каталога графы инлайнятся в сайдкары.

### Сделать генерацию воспроизводимой на уровне окружения

NOT IMPLEMENTED, требует решения: заморозка окружения ComfyUI (снапшот ComfyUI-Manager), пин версии ComfyUI и коммитов custom nodes, запись их в провенанс. Сегодня сайдкар хранит модель/seed/граф, но не среду исполнения.

---

## Чего НЕ делать

- **Не переименовывать и не пересохранять PNG из ComfyUI до `vn assets provenance record`.** Любой редактор/конвертер может срезать tEXt-чанки — и seed с промптом исчезнут без сообщения об ошибке.
- **Не класть `@2` в имя сырца спрайта.** Суффикс дописывает конвейер (`pipeline.py:120-121,133`).
- **Не править `game/assets/`** — перезапишет ближайший `vn assets build`. Источник — только `assets_src/`.
- **Не поднимать `denoise` выше ~0.45 на i2i-полировке**, если рассчитываете на консистентность из DAZ-пресета: вы отдаёте лицо модели.
- **Не обходить логины/EULA моделей.** Это архитектурный запрет (ADR-0006 §3), а не рекомендация.
- **Не тащить SUPIR в конвейер.** Лицензия явно non-commercial, а сидит он в самом конце цепочки, куда никто не смотрит.
- **Не считать permissive-лицензию модели разрешением на публикацию.** Правила площадок и платёжных провайдеров — отдельный слой ([33](33-security-and-legal.md)).
- **Не строить новую систему метаданных.** ADR-0006 §2: «второй системы метаданных нет» — провенанс продолжают `.vncache/assets-manifest.json` и `mov_meta@1`.
- **Не полагаться на `canvas` в `character.yaml`** — его не читает ни одна строка кода.
- **Не обновлять ComfyUI/custom nodes посреди производства главы.** Механизма отката окружения у нас нет.
- **Не путать `vn pipeline models` и `vn pipeline models --only`** — второе качает.
- **Не генерировать двух персонажей одним кадром ради спрайтов** — композитьте в Ren'Py.

---

## Проверка

```bash
# Окружение генерации
vn pipeline doctor                  # PASS/WARN/FAIL: Python, ffmpeg/VP9, GPU, torch/CUDA,
                                    # ComfyUI, Manager, модели, DAZ, диски, SDK
vn pipeline models                  # ✓/✗/!/? по каждой позиции манифеста

# Целостность происхождения
vn assets provenance verify                  # все цепочки: схема + хэши
vn assets provenance verify --scope png/cg   # только CG
vn assets licenses                           # декларации против content/licenses.yaml

# Кадр доехал до игры
vn assets build                     # assets_src/ -> game/assets/
vn build                            # lint -> ассеты -> генерат -> game/tl
vn build --check                    # CI-режим: ничего не пишет, краснеет на несвежем

# Релизный гейт (провенанс и лицензии — часть 19 проверок)
vn release validate --flavor public
```

Что из этого **действительно** может покраснеть по вине генерации изображений: `vn pipeline doctor` — только на битом манифесте моделей (всё про GPU/ComfyUI/DAZ — WARN, exit 0). `vn assets provenance verify` — на расхождении хэшей. `vn assets licenses` — на ассетной лицензии. Ни одна проверка **не требует** наличия провенанса и не смотрит на `commercial_use` модели.

---

## Ресурсы

- **Официальная документация ComfyUI** — https://docs.comfy.org · список HTTP-маршрутов сервера (вся поверхность будущей автоматизации: `POST /prompt`, `GET /history`, `GET /view`, `POST /upload/image`, `GET /object_info`) — https://docs.comfy.org/development/comfyui-server/comms_routes
- **API-формат workflow против save-формата** — https://docs.comfy.org/development/api-development/workflow-api-format — то, обо что спотыкаются один раз, но обязательно.
- **Inpaint-туториал ComfyUI** (Mask Editor, `VAE Encode (for Inpainting)`, `grow_mask_by`) — https://docs.comfy.org/tutorials/basic/inpaint — прямой инструмент матрицы выражений.
- **Оптимизации ComfyUI под NVIDIA** (Blackwell, NVFP4 и ловушка cu130) — https://blog.comfy.org/p/new-comfyui-optimizations-for-nvidia
- **Оверсэмплинг Ren'Py `@2`** — https://www.renpy.org/doc/html/displaying_images.html — почему спрайты авторятся в 2× и как это работает в движке.
- **ComfyUI-Manager** (Snapshot-Manager = механизм заморозки окружения; уровни безопасности custom nodes) — https://github.com/Comfy-Org/ComfyUI-Manager

Внутренние документы: `../adr/0006-daz-comfyui-video-pipeline.md` (норма конвейера), `../adr/0008-ai-model-licensing-for-commercial-adult-content.md` (развилка по лицензиям), `../pipeline/phase-0.md` (§3.1–3.2 — установка и модели, §5 — troubleshooting), `../onboarding/artist.md` (контракт художника), `../conventions/naming.md`.

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/comfyui-models.yaml`, `../../tools/schemas/comfyui_models@1.schema.json`, `../../tools/vn/src/vn/pipeline.py` (`:250-446` — манифест/загрузка/статус, `:455-581` — doctor), `../../tools/vn/src/vn/assets/provenance.py`, `../../tools/schemas/provenance@1.schema.json`, `../../tools/setup-comfyui.ps1`, `../adr/0006-daz-comfyui-video-pipeline.md`, `../adr/0008-ai-model-licensing-for-commercial-adult-content.md` |
| **Не трогать** | `D:\ComfyUI\models\.vn-models.json` (лок загрузчика, не в git, пишется кодом); `game/assets/**` (генерат `vn assets build`); `.vncache/**`; сами файлы моделей — они внешняя зависимость уровня SDK, не ассет проекта |
| **Зависимости** | правка `dest`/`kind` в манифесте → загруженные модели становятся `missing`, ComfyUI не найдёт файл по старому пути; удаление позиции → `vn pipeline doctor` уронит счётчик обязательных; правка `sha256` с `null` на значение → **все ранее скачанные файлы будут удаляться при повторном `--pull`, если хэш не совпал**; изменение `tools/setup-comfyui.ps1` в части индекса torch → риск тихого CPU-fallback на Blackwell |
| **Валидация** | `vn pipeline doctor` (схема манифеста — единственный FAIL этой зоны) · `vn pipeline models` · `vn assets provenance verify` · `vn assets licenses` · `python -m pytest tools/vn/tests/test_provenance.py -q` (11 тестов) |
| **Частые ошибки** | 1) считать, что `vn` умеет запускать ComfyUI или ставить задачи в очередь — **API-клиента не существует**, порт 8188 нигде не упоминается; 2) искать workflow-JSON в репозитории — их **ноль**, `phase-0.md:174` отправляет к штатному шаблону ComfyUI; 3) описывать `vn pipeline models --only` как «показать выбранные» — он **качает** (`cli.py:1442`); 4) утверждать, что манифест проверяет целостность — у всех позиций `sha256: null`, повторные прогоны сверяют **только размер**; 5) искать DAZ/ComfyUI в `docs/ARCHITECTURE.md` — там **ноль** упоминаний, вся зона нормирована ADR-0006/0007/0008 и `docs/pipeline/phase-0.md`; 6) считать `content/licenses.yaml` реестром лицензий **моделей** — это реестр **ассетов** (DAZ-продукты, шрифты), у моделей гейта нет вообще; 7) предполагать, что провенанс обязателен — PNG без сайдкара проходит все проверки; 8) писать сайдкар для файла вне `assets_src/` — `ProvenanceError` (G2) |
