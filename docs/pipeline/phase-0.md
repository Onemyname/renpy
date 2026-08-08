# Фаза 0: развёртывание production-окружения (DAZ → ComfyUI/Wan → ffmpeg → Ren'Py)

Норма — ADR-0006. Этот документ — путь от чистой машины до работающего
конвейера рендеров/видео. Единая проверка всего описанного здесь:

```bash
vn pipeline doctor
```

## 1. Требования

| Компонент | Минимум | Референс-машина проекта |
|---|---|---|
| GPU | NVIDIA, 12+ ГБ VRAM (генерация видео) | RTX 5080, 16 ГБ (Blackwell) |
| RAM | 32 ГБ (offload 14B-моделей) | 61 ГБ |
| Диск | 100+ ГБ свободно под модели/рендеры | D: (747 ГБ свободно) |
| ОС | Windows 10/11 | Windows 11 Pro |
| Python | 3.10+ (у ComfyUI свой venv) | 3.12 |
| ffmpeg | полная сборка с libvpx-vp9 | winget Gyan.FFmpeg 8.x |

**Blackwell (RTX 50xx) — два критичных пина:**

- **PyTorch только с индексом cu128** (`https://download.pytorch.org/whl/cu128`) —
  старые wheel'ы не знают sm_120: CUDA «есть», а ядра не запускаются.
  `tools/setup-comfyui.ps1` ставит правильный сам.
- **DAZ Studio 4.24+**: только свежий Iray умеет Blackwell; старые версии молча
  падают в CPU-рендер (кадр «считается» в 50 раз дольше — это главный симптом).

## 2. Раскладка дисков

Тяжёлое живёт на D:, репозиторий и инструменты — на C:.

```
D:\ComfyUI\                # ComfyUI + venv (setup-comfyui.ps1)
D:\ComfyUI\models\         # модели (~37 ГБ обязательных; vn pipeline models)
D:\DAZ3D\Library\          # библиотека контента DAZ (install-daz.ps1 создаёт)
C:\Users\<you>\vn-assets-store\   # хранилище сырцов (.vnstorage.yaml)
```

## 3. Установка

### 3.1 ComfyUI (автоматически)

```bash
pwsh -File tools/setup-comfyui.ps1
```

Идемпотентен (перезапуск безопасен): клонирует ComfyUI в `D:\ComfyUI`, создаёт
venv, ставит torch cu128 + зависимости + ComfyUI-Manager, создаёт структуру
`models/{checkpoints,diffusion_models,text_encoders,vae,loras,upscale_models}`,
прописывает `VN_COMFYUI`. Запуск UI:

```bash
D:\ComfyUI\venv\Scripts\python.exe D:\ComfyUI\main.py
```

### 3.2 Модели (полуавтоматически)

Манифест — `tools/comfyui-models.yaml` (comfyui_models@1): источники, размеры,
лицензии; sha256 фиксируется при первой загрузке в `<models>/.vn-models.json`.

```bash
vn pipeline models          # статус
vn pipeline models --pull   # скачать свободные (Wan 2.2 I2V fp8 ×2, UMT5, VAE,
                            # LightX2V-лоры, RealESRGAN) — резюмируемо (curl -C -)
```

Позиции `auth: civitai_key` (NSFW-LoRA) качаются с вашим ключом Civitai из env
`CIVITAI_API_KEY`; позиции `auth: manual` требуют явного логина/лицензии —
команда печатает URL и путь. Обход логинов **запрещён** архитектурно.

Ключ Civitai: civitai.com → Account Settings → API Keys → Add API key
(preset Read-only достаточно; включите показ взрослого контента). Затем:

```bash
setx CIVITAI_API_KEY "<ключ>"     # пишет в реестр User-окружения
```

**Грабля Windows:** `setx` виден только НОВЫМ процессам. Если после `setx`
в том же открытом терминале `vn pipeline models --pull` пишет «нужен ключ» —
откройте **новый** терминал и повторите (vn это распознаёт и подскажет). Значение
ключа в логи/провенанс не попадает; в git не коммитится.

### 3.3 DAZ Studio (ручной шаг — лицензия/аккаунт)

```bash
pwsh -File tools/install-daz.ps1
```

Скрипт детектирует установленное, создаёт `D:\DAZ3D\Library`, запускает
установщик DIM из `~/Downloads`, печатает чеклист. Ручными остаются: бесплатный
аккаунт DAZ, установка DAZ Studio 4.24+ и Genesis Starter Essentials через DIM,
привязка библиотеки к `D:\DAZ3D\Library`.

### 3.4 Настройки GPU в DAZ (Iray, RTX 5080)

Render Settings → Advanced:

1. **Devices:** галка на RTX 5080, **CPU снять** — иначе не заметите тихий
   CPU-fallback при нехватке VRAM;
2. **OptiX Prime acceleration:** включить;
3. Editor → Progressive Rendering: Max Samples ~1500–3000, Rendering Quality
   Enable + denoiser (Post Denoiser Available, старт с ~50% семплов);
4. 16 ГБ VRAM: держите сцену < ~12 ГБ текстур — **Scene Optimizer** (даунскейл
   текстур 4K→2K для второстепенного) обязателен в библиотеке.

### 3.5 ffmpeg

Ставится winget'ом: `winget install Gyan.FFmpeg` (полная сборка, с libvpx-vp9).
Пути не хардкодятся: PATH либо переопределения `VN_FFMPEG`/`VN_FFPROBE`.

## 4. Проверочный рендер (приёмка окружения)

1. **DAZ:** сцена с одной G8/G9-фигурой и HDRI → Iray-рендер 1920×1080.
   Приёмка: GPU-рендер (в логе Iray — «device 0», не CPU), ≤ 5 мин.
2. **ComfyUI/Wan:** шаблон Wan 2.2 I2V (Templates → Video), на вход — рендер
   из шага 1, 480p/49 кадров с LightX2V-лорами (4 шага). Приёмка: клип ≤ 15 мин
   без OOM.
3. **Конвейер:** положите клип в `assets_src/video_src/<group>/<name>.mp4` →

```bash
vn assets video build
vn assets video validate
vn build
```

Приёмка: `.webm + .webm.meta.json` в `game/assets/mov/`, `image mov <group>
<name>` в `game/generated/registry/images.gen.rpy`, `vn build: OK`.

## 5. Troubleshooting

| Симптом | Причина | Лечение |
|---|---|---|
| Iray рендерит минуты→часы, GPU молчит | CPU-fallback: старый DAZ (не знает Blackwell) или сцена не влезла в VRAM | DAZ 4.24+; Scene Optimizer; снять CPU-галку, чтобы падало явно |
| `torch.cuda.is_available() == False` | torch не cu128 | перезапустить `setup-comfyui.ps1` (снесите `D:\ComfyUI\venv` при упорстве) |
| ComfyUI: OOM на Wan 14B | 16 ГБ VRAM: жирный воркфлоу/высокое разрешение | fp8-модели из манифеста; 480→720p максимум; LightX2V 4 шага; RAM-offload у Comfy автоматом (61 ГБ хватает) |
| Генерация видео «висит» | считается без дистилляции | проверьте, что LightX2V-лоры подключены (4 шага вместо 20) |
| `vn assets build`: «есть видео-сырцы, но ffmpeg не найден» | ffmpeg не в PATH | `winget install Gyan.FFmpeg` или `VN_FFMPEG` |
| `.webm` не играет в Ren'Py | кодек/пиксели вне канона | `vn assets video validate <file>` скажет точно (vp9/yuv420p — норма ADR-0006) |
| «стык лупа заметен (RMS …)» | первый/последний кадры расходятся | генерируйте с последним кадром = первому (I2V loop-воркфлоу) либо `loop: false` в sidecar |
| Модель качается вечно/рвётся | сеть | `vn pipeline models --pull` докачивает с места обрыва |

## 6. Что дальше (Фаза A из плана производства)

Пилот контента: один персонаж (Character Preset = исходник идентичности),
одна локация, ~10 стиллов + 1–2 лупа через полный конвейер:
`<name>.render.yaml` → рендер → `vn assets daz validate` (провенанс) →
[опц. AI-полировка → `vn assets provenance record`] → `vn build` →
`vn release build --flavor patron`.
