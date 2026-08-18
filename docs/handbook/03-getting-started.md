# 03. Начало работы: первые 30 минут

> **Статус подсистемы:** IMPLEMENTED — путь `clone → pip install → vn doctor → vn build → vn play` работает целиком, но однокомандного инсталлера по ролям нет (`vn bootstrap` без опций, `--role` NOT IMPLEMENTED), а `RENPY_SDK` приходится ставить руками.
> **Отвечает на вопрос:** «Что мне выполнить прямо сейчас, чтобы игра запустилась, как понять, почему не запустилась, и что читать дальше».

Всё окружение проекта диагностируется двумя командами: `vn doctor` (нужна всем — репозиторий, схемы, шрифты, SDK) и `vn pipeline doctor` (нужна только тем, кто производит картинки и видео — GPU, ComfyUI, модели, DAZ, ffmpeg). Обе печатают рецепт починки прямо под провалившейся строкой. Код: `tools/vn/src/vn/doctor.py` (153 строки), `tools/vn/src/vn/pipeline.py:455-581`.

---

## Первые 30 минут: пронумерованный путь

Восемь шагов. Каждый — проверяемый: если шаг не дал ожидаемого вывода, дальше не идите, а прочитайте разбор в §8. Ориентир по времени — 20-30 минут, из них большая часть на скачивание SDK.

### Шаг 1. Склонировать репозиторий вместе с LFS (2 мин)

```bash
git lfs install                                  # ОДИН раз на машину
git clone https://github.com/Onemyname/renpy vn  # репозиторий приватный
cd vn
git lfs pull                                     # шрифты UI — бинари из LFS
```

`git lfs pull` не косметика: в LFS живут три шрифта UI и все растровые мастера `assets_src/**` (`.gitattributes` — 22 правила на зону мастеров). Чекаут без LFS однажды уже уехал в сборку 0.1.1 и падал у игроков `FreetypeError`.

**Проверка шага:** `head -c 4 game/fonts/*.ttf | xxd | head -1` — должно начинаться не с `version`; надёжнее — шаг 4, где это проверит `vn doctor`.

### Шаг 2. Поставить тулчейн — сначала лок, потом editable (3 мин)

```bash
python3 -m venv .venv && source .venv/bin/activate    # macOS/Linux; на Windows: .venv\Scripts\activate
pip install -r tools/vn.lock                          # 18 точных пинов (G17)
pip install -e "tools/vn[dev]"                        # даёт команду vn; [dev] добавляет pytest
```

**Порядок обязателен.** `tools/vn.lock` ставится **первым**: после него editable-установка не поднимает ни один пакет, потому что её `>=`-диапазоны уже удовлетворены. В обратном порядке лок не применится, и вы получите не то окружение, что в CI. Тот же порядок стережёт `tools/vn/tests/test_ci_config.py` (7 тестов) во всех пяти пайплайнах.

**Ставьте в одно окружение и `vn`, и `pytest`.** Системный Python обычно не имеет `PyYAML`/`blake3`/`Pillow`, и тогда `python -m pytest` даст десятки ошибок коллекции вместо тестов — это не поломка репозитория, а другой интерпретатор.

**Проверка шага:** `python -c "import vn, sys; print(vn.__file__, sys.executable)"` — путь должен указывать в `tools/vn/src/vn/__init__.py`.

### Шаг 3. Скачать Ren'Py SDK 8.5.3 и указать `RENPY_SDK` (10-15 мин)

Версия пиннована: `project.yaml:5 renpy_sdk: "8.5.3"` (норма G18). Любая другая — hard fail в `vn doctor`.

```bash
# Ссылка, которой пользуется CI (.github/workflows/ci.yml:74):
#   https://www.renpy.org/dl/8.5.3/renpy-8.5.3-sdk.zip
# Страница загрузки: https://www.renpy.org/latest.html
```

Распакуйте так, чтобы `renpy.py` лежал **прямо в указываемом каталоге** — поиск SDK идёт только по переменной окружения и проверяет наличие `renpy.py` (`doctor.py:24-30`).

**macOS / Linux** — в текущую сессию и в профиль:

```bash
export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"
echo 'export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"' >> ~/.zshrc   # или ~/.bashrc
```

**Windows** (PowerShell):

```powershell
setx RENPY_SDK "C:\Users\<you>\renpy-sdk\renpy-8.5.3-sdk"
```

**`setx` виден только НОВЫМ процессам** — закройте и откройте терминал (и IDE), иначе `vn doctor` покажет `✗ Ren'Py SDK не найден` сразу после успешного `setx`. Подробности и две родственные грабли — §2.

**Проверка шага:** `ls "$RENPY_SDK/renpy.py"` (Windows: `dir %RENPY_SDK%\renpy.py`).

### Шаг 4. `vn doctor` — 8 галок, exit 0 (1 мин)

```bash
vn doctor; echo "EXIT=$?"
```

Ожидаемый вывод (реальный прогон на этой машине, 2026-08-18):

```
 ✓ Python 3.14.5
 ✓ git
 ✓ git-lfs (git-lfs/3.7.1 (GitHub; darwin arm64; go 1.25.3))
 ✓ корень репозитория: /Users/vkonovalov/Projects/personal/renpy
 ✓ project.yaml (min_tools 0.1, vn 0.1.0)
 ✓ реестр схем: 39 схем
 ✓ шрифты UI: 3/3 материализованы
 ✓ Ren'Py SDK 8.5.3.26051504: /…/renpy-8.5.3-sdk
EXIT=0
```

Восемь строк — норма. Девятая (`! локальное переопределение .vnstorage.local.yaml активно`) появляется только если у вас есть этот файл, и на exit-код не влияет. Разбор каждой проверки — §3.

Если exit ≠ 0 — **останавливайтесь здесь**: следующие шаги на сломанном окружении дадут ложные диагнозы.

### Шаг 5. `vn build` — собрать производные зоны (1 мин)

```bash
vn build     # -> build: OK
```

Внутри: схемы → lint → сборка ассетов → компиляция контента в `game/generated/` → `vn loc import` в `game/tl/` → бюджеты (`cli.py:88-157`). Ни `game/generated/`, ни `game/assets/`, ни `game/tl/` не хранятся в git — на свежем чекауте их создаёт именно этот шаг.

**Проверка шага:** `ls game/generated/manifest.json game/assets/bg` — оба существуют.

### Шаг 6. `vn play` — увидеть игру (1 мин)

```bash
vn play      # запуск через SDK; закрытие окна возвращает управление
```

В игре: Shift+O — консоль, Shift+D — dev-меню движка, Shift+J — прыжок в любую сцену, Shift+R — перезагрузка скриптов.

Для долгой итерации вместо `vn play` берите `vn dev`: он поднимает игру и вотчер по `content/` + `assets_src/`, пересобирая при каждой правке (§6).

### Шаг 7. `pytest` — 373 теста (1 мин)

```bash
cd tools/vn && python -m pytest tests -q; cd -     # -> 373 passed
```

**Две тонкости, из-за которых у новичка «тесты не такие»:**

- Без `RENPY_SDK` в этой же сессии семь тестов **skip**: четыре контракта движка (`test_engine_compat.py:25,33,55,62` — «контракт-тесты движка гоняет canary-джоба CI») и по одному в `test_gallery.py:181`, `test_loc.py:448`, `test_scene_pipeline.py:332` (им нужен парсер сцен из SDK). Получите `246 passed, 7 skipped` — это не провал, но и не полный прогон.
- Запуск **из корня репозитория** (`python -m pytest tools/vn/tests -q`) на этой машине даёт `1 failed, 245 passed, 7 skipped`: `test_verify_regressions.py:84` делает `from tests.test_compile import BASE_OUTPUTS`, а в `sys.path` при таком CWD есть только `tools/vn/src` (editable-установка добавляет именно его, `conftest.py:8` — тоже его). Надёжная форма — из каталога `tools/vn`. Учтите расхождение: шаг CI (`ci.yml:97`) зовёт pytest в root-относительной форме.

### Шаг 8. Что читать дальше — четыре страницы в этом порядке

| # | Страница | Зачем именно она и именно сейчас |
|---|---|---|
| 1 | [02-architecture.md](02-architecture.md) — «Быстрый ответ» и §1 | Карта зон и правило «источник vs генерат». Без него первая же правка уйдёт не в тот файл. 15 минут, дальше §1 можно закрыть. |
| 2 | [44-how-do-i.md](44-how-do-i.md) | Практический FAQ: «мне надо добавить X» → минимальная последовательность команд. Держите открытым в фоне первую неделю. |
| 3 | [04-development-workflow.md](04-development-workflow.md) §1 и §8 | Таблица «что правишь → чем пересобирается» и перечень зон, которые нельзя коммитить. |
| 4 | своя роль: [13-dialogue.md](13-dialogue.md) + [12-scenes.md](12-scenes.md) (сценарист) · [16-assets.md](16-assets.md) + [22-rendering.md](22-rendering.md) (художник) · [14-localization.md](14-localization.md) (локализатор) · [25-custom-engine.md](25-custom-engine.md) + [27-testing.md](27-testing.md) (tools) | Единственная страница, которую надо прочитать целиком. |

**Чего в первый день читать НЕ надо:** `docs/ARCHITECTURE.md` (целевой норматив, большая часть — будущие фазы; расхождения с кодом там штатны), главы 17-21 (внешний 3D/AI-конвейер — только если вы производите картинки), 29-33 (релиз, паки, хранилище, безопасность — нужны, когда дойдёте до релиза).

**Первое реальное изменение** — §7 ниже: поменять реплику и увидеть её в игре.

---

## 1. Требования

| Компонент | Что нужно | Проверяет | Обязателен? |
|---|---|---|---|
| Python | код требует `>= 3.10` (`doctor.py:72`, `tools/vn/pyproject.toml:9`); CI гоняет **3.12** (`setup-python: "3.12"`), на этой машине зелено и на 3.14.5 | `vn doctor` | да, hard fail |
| git | в PATH | `vn doctor` | да, hard fail |
| git-lfs | `git lfs version` должен отвечать | `vn doctor` | да, hard fail |
| Ren'Py SDK | версия **8.5.3** — пин `project.yaml:5 renpy_sdk: "8.5.3"` (G18); путь в `RENPY_SDK` | `vn doctor` | hard fail, **если** есть `content/chapters/ch*` (а они есть) |
| ffmpeg (полный, с libvpx-vp9) | видео-трек **и** транскод озвучки | `vn pipeline doctor` | нет — но см. грабли ниже |
| NVIDIA GPU + ComfyUI + модели | только для генерации картинок/видео | `vn pipeline doctor` | нет |
| DAZ Studio **6** (+ драйвер NVIDIA ≥ 576.57) | только для рендеров | `vn pipeline doctor` | нет |

`vn doctor` **не проверяет** ffmpeg, GPU и ComfyUI — они видны только в `vn pipeline doctor`. Не ищите их в первой команде.

**Грабля про ffmpeg.** Он помечен «необязательный», но в репозитории уже лежат 14 wav-мастеров озвучки (`assets_src/voice/ru/ch01/`) и видео-мастер (`assets_src/video_src/demo/ambient.mp4`). Discovery ассетов при найденных мастерах и отсутствующем ffmpeg даёт **ошибку**, а ошибки discovery останавливают сборку **до первой трансформации** — то есть `vn assets build` не соберёт вообще ничего, включая картинки. Симптом «не собралось, хотя я правил один PNG» читается как поломка тулинга, если этого не знать.

**Про версию DAZ.** `../pipeline/phase-0.md:27` и `../../tools/install-daz.ps1:109` до сих пор пишут «4.24+» — требование устарело: Iray в ветке 4.x собран до Blackwell, и на RTX 50xx он не работает вообще. Ставьте **ветку 6**. Подробности — [17-daz-studio.md](17-daz-studio.md) §2.3 и [22-rendering.md](22-rendering.md).

### Зависимости и пины

`pip install -e tools/vn` тянет `click>=8.1, PyYAML>=6.0, jsonschema>=4.21, blake3>=0.4, Pillow>=10.0, psd-tools>=1.9, polib>=1.2` (`tools/vn/pyproject.toml:10-18`); `[dev]` добавляет `pytest>=8.0`.

`tools/vn.lock` (18 пинов) — **PARTIALLY IMPLEMENTED**: лок читается CI. Во всех восьми джобах установки тулчейна (GitHub: `ci.yml` дважды — `lint` и `build-test`; `nightly.yml`, `canary.yml`, `release.yml`; GitLab-шаблон разворачивается в `build` и `test`) перед editable-установкой идёт `pip install --quiet -r tools/vn.lock`. Порядок стережёт `test_ci_config.py::test_lock_installed_before_editable`, поэтому новый workflow без лока не пройдёт CI.

**Честный остаток:** закреплены 18 пакетов — прямые зависимости `vn-tools` и их основные транзитивные. Транзитивные зависимости самого лока (например `pygments`, тянущийся за `pytest`) в файле не перечислены и резолвятся свободно. Норма G17 («откат тулчейна = `git revert` одного файла») выполняется для этих 18, но не абсолютна.

---

## 2. `RENPY_SDK` — переменная, на которой держится половина тулинга

Поиск SDK **только по переменной окружения**, без PATH и без стандартных мест установки (`doctor.py:24-30`):

```python
def sdk_path() -> Path | None:
    env = os.environ.get("RENPY_SDK")
    if env:
        p = Path(env)
        if (p / "renpy.py").is_file():
            return p
    return None
```

Через `sdk_path()` ходят **все** потребители SDK: `vn play`, `vn dev`, `vn package`, `vn test smoke`, `vn test oversample`, `vn save corpus`, `vn release build`, `vn release steam`, а также build-bridge `tools/vn/src/vn/content/analyze.py:24-33`.

### ГРАБЛЯ №1: `setx` виден только НОВЫМ процессам (Windows)

`setx` пишет в User-окружение реестра. Уже открытые терминалы, запущенная IDE и все их дочерние процессы продолжают видеть старое окружение. Симптом — `vn doctor` показывает `✗ Ren'Py SDK не найден` сразу после успешного `setx`. Лечение: **закройте и откройте терминал**. Та же грабля отдельно обработана для `CIVITAI_API_KEY` — `_civitai_key_in_registry()` (`pipeline.py:318-330`) специально лезет в `HKCU\Environment`, чтобы отличить «ключа нет» от «ключ есть, но не в этом процессе».

На macOS/Linux аналог — правка `~/.zshrc` / `~/.bashrc` не действует на уже открытые оболочки: либо `source ~/.zshrc`, либо новое окно.

### ГРАБЛЯ №2: в bash-сессии AI-агента переменная не наследуется

Проверено на этой машине. Без экспорта:

```
 ✗ Ren'Py SDK не найден
     → скачайте SDK с renpy.org и укажите путь: setx RENPY_SDK <путь>; в content/
       есть главы — без SDK сцены не компилируются (G24)
EXIT=1
```

С экспортом в той же сессии:

```bash
export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"
vn doctor    # ✓ Ren'Py SDK 8.5.3.26051504: ... ; EXIT=0
```

Правило для агента: **экспортируй `RENPY_SDK` первой строкой каждого bash-вызова**, где дальше идёт `vn build` / `vn play` / `vn dev` / `vn test smoke` / `vn test oversample` / `vn save corpus` / `vn release *` / `pytest`.

### ГРАБЛЯ №3: тёплый `.vncache` маскирует отсутствие SDK

`analyze_scene_files` кэширует результат разбора сцен в `.vncache/analyze-<hash>.json` по blake3 от (версия vn + байты `050_build_bridge.rpy` + пути и байты всех `scene.rpy`) — `tools/vn/src/vn/content/analyze.py:41-56`. Если кэш попал, движок не запускается вовсе. Проверено: в сессии **без** `RENPY_SDK` `vn build` отработал `build: OK`, exit 0. Тот же комментарий стоит в `doctor.py:119-120`.

Следствие: «у меня собирается» ≠ «SDK настроен». Честная проверка — `vn doctor`, а не `vn build`. Чтобы заставить сборку реально дёрнуть движок: `rm .vncache/analyze-*.json`.

### ГРАБЛЯ №4: `vn --help` в Git Bash — кракозябры

Реконфигурация stdout в UTF-8 живёт в callback группы (`cli.py:49-55`), а `--help` — eager-опция click, которая печатает и выходит **до** callback. Проверено: в Git Bash `vn --help` выдаёт мусор вместо русских описаний, при этом `vn doctor` и все остальные команды печатаются корректно. В PowerShell 7 и в macOS/Linux-оболочках проблемы нет. Если нужен `--help` из Git Bash — читайте его через PowerShell или смотрите докстринги в `tools/vn/src/vn/cli.py`.

---

## 3. `vn doctor` — расшифровка каждой проверки

`IMPLEMENTED` — `tools/vn/src/vn/doctor.py:69-153`. Формат строки: `✓` (PASS) / `!` (WARN, не влияет на exit-код) / `✗` (hard fail). Рецепт печатается отступом `→` только для не-PASS. Exit 1, если есть хоть один `✗`.

| # | Проверка | Условие PASS | Что печатает при провале / как чинить | Код |
|---|---|---|---|---|
| 1 | Python | `sys.version_info >= (3,10)` | `нужен Python >= 3.10` | `:72-73` |
| 2 | git | `shutil.which("git")` | `установите git и добавьте в PATH` | `:75` |
| 3 | git-lfs | `git lfs version` вернул строку | `установите git-lfs: https://git-lfs.com` | `:76-77` |
| 4 | корень репозитория | `find_root()` нашёл `project.yaml` **и** `tools/schemas/` | `не найден корень репозитория: нужен project.yaml + tools/schemas/ в текущем каталоге или выше` → `cd` в репозиторий | `:79-84` |
| 5 | `project.yaml` / `min_tools` | `(major,minor)` версии `vn` `>=` `min_tools`; сейчас `vn 0.1.0` vs `min_tools "0.1"` | `обновите vn: pip install -e tools/vn`; нечитаемый файл → `не читается: <e>` | `:87-96` |
| 6 | реестр схем | `SchemaRegistry(tools/schemas)` сконструировался; в заголовке — число схем (**39**) | текст исключения: имя файла вне конвенции `<name>@<int>.schema.json` или `const` поля `schema` ≠ имени файла | `:98-102` |
| 7 | `.vnstorage.local.yaml` | **WARN-only** и только если файл есть: «локальное переопределение … активно» | ничего не чинить — это напоминание, что физика хранилища у вас своя | `:104-106` |
| 8 | шрифты UI | все `game/fonts/*.ttf|*.otf` начинаются с `\x00\x01\x00\x00` / `true` / `ttcf` / `OTTO` | `git lfs install && git lfs pull — файлы приехали указателями, а не шрифтами` | `:50-66`, `:111-117` |
| 9 | Ren'Py SDK | `sdk_path()` нашёл; `sdk_version()` из `<sdk>/renpy/vc_version.py` начинается с пина `project.yaml: renpy_sdk` | несовпадение пина → `поставьте пиннованную версию SDK или обновите пин отдельным PR (G18)` | `:124-137` |
| 9b | SDK отсутствует | — | **severity зависит от контента**: `✗` если есть каталоги `content/chapters/ch*`, иначе `!` | `:119-142` |

Строк на экране обычно **восемь**: #7 молчит, когда файла нет.

Про #8 подробнее — проверка **по содержимому файла**, а не по `git lfs status`, поэтому работает даже там, где git-lfs не установлен вообще (`doctor.py:50-66`). Тот же самый `_lfs_pointer_fonts` переиспользован релизным гейтом (`release.py:519-528`), потому что чекаут без LFS однажды уже уехал в сборку 0.1.1.

Про #9b: без глав SDK — предупреждение («нужен для vn play»), с главами — жёсткий провал («без SDK сцены не компилируются (G24)»). В текущем дереве `content/chapters/ch01_awakening/` есть, значит **у вас это всегда hard fail**.

`vn doctor` — единственная команда, которая работает вне репозитория: `find_root()` вызывается внутри try, дальше проверки продолжаются с `root = None` (`doctor.py:80-84`).

`vn bootstrap` (PARTIALLY IMPLEMENTED, `cli.py:224-245`) начинается с `run_doctor()` и при exit ≠ 0 останавливается: `bootstrap остановлен: почините окружение по рецептам vn doctor`. Дальше он делает `_assets_build(root, "full")` → `compile_content` → `_loc_import`. Скачивания из remote cache / CI-артефактов (норма G4) в нём **нет** — это прямо написано в его же докстринге. Опции `--role` не существует, хотя `README.md:11` обещает «однокомандный инсталлер по ролям — фаза 1» — **NOT IMPLEMENTED**.

---

## 4. `vn pipeline doctor` — расшифровка (нужна только контент-продакшену)

`IMPLEMENTED` — `pipeline.py:455-581`. Метки `PASS` / `WARN` / `FAIL`, exit 1 только на `FAIL`. Реальный вывод здорового окружения (машина владельца, Windows, 2026-08-08, exit 0):

```
 PASS  Python 3.12.10
 PASS  vn 0.1.0
 PASS  ffmpeg 8.1.2-full_build-www.gyan.dev (...\Gyan.FFmpeg...\bin\ffmpeg.EXE)
 PASS  VP9-энкодер (libvpx-vp9)
 PASS  ffprobe
 PASS  GPU: NVIDIA GeForce RTX 5080, 16303 MiB, 610.74
 PASS  ComfyUI: D:\ComfyUI
 PASS  PyTorch 2.11.0+cu128, CUDA доступна
 PASS  ComfyUI-Manager
 PASS  модели: все обязательные на месте (6)
 PASS  DAZ Studio: D:\DAZ3D\Library\Applications\64-bit\DAZ 3D\DAZStudio6\DAZStudio.exe
 PASS  библиотека DAZ: D:\DAZ3D\Library\Applications\Data\DAZ 3D\My DAZ 3D Library
 WARN  Virt-a-Mate: не установлен (опционально)
       -> опционально: tools/install-vam.ps1 (третий источник рендеров)
 WARN  The Sims 4: не установлен (опционально)
       -> опционально: tools/install-sims4.ps1 (четвёртый источник рендеров)
 PASS  диск C:\ (репозиторий): свободно 535 ГБ
 PASS  диск D:\ (модели): свободно 616 ГБ
 PASS  Ren'Py SDK: 8.5.3.26051504
```

Это **снимок конкретной машины** (пути `D:\`, `C:\` — её), а не свойство репозитория. У вас имена дисков и версии будут другими; сравнивать надо метки PASS/WARN/FAIL, а не строки.

**Два WARN про VaM и Sims 4 — норма, а не проблема.** Продакшен-трек проекта — DAZ (+ Wan I2V); VaM берут точечно под физику тел, Sims 4 — задел на будущее (ADR-0007). Оба источника технически готовы (валидаторы деклараций реализованы и общие для трёх источников — `assets/sources.py`), но **ноль деклараций** существует в репозитории, так что установка не требуется.

Что здесь `FAIL` (то есть реально ломает конвейер): Python < 3.10, отсутствующий ffmpeg, сборка ffmpeg без libvpx-vp9, отсутствующий ffprobe, нечитаемый манифест моделей. Всё остальное — `WARN`. Про установку по шагам — `docs/pipeline/phase-0.md` и [17-daz-studio.md](17-daz-studio.md) / [20-image-generation.md](20-image-generation.md) / [21-video-generation.md](21-video-generation.md).

---

## 5. Роль → что ставить

| Роль | Минимум | Дополнительно | Онбординг |
|---|---|---|---|
| **Сценарист** | шаги 1-7 выше | текстовый редактор с подсветкой `.rpy` | `../onboarding/writer.md` → [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md) |
| **Художник / motion** | то же **+** ffmpeg (полный, с libvpx-vp9) | DAZ Studio **6**, ComfyUI + модели (`vn pipeline models --pull`), NVIDIA GPU 12+ ГБ VRAM и драйвер ≥ 576.57, опц. VaM | `../onboarding/artist.md`, `../pipeline/phase-0.md` → [16-assets.md](16-assets.md), [17-daz-studio.md](17-daz-studio.md) |
| **Локализатор** | то же, что сценарист | PO-редактор (Poedit и т.п.) — правится **только** `loc/po/<code>/*.po` | `../onboarding/localizer.md` → [14-localization.md](14-localization.md) |
| **Tools-инженер** | всё вышеперечисленное + `[dev]` (pytest) | — | `../onboarding/tools-engineer.md` → [25-custom-engine.md](25-custom-engine.md), [27-testing.md](27-testing.md) |

Все четыре файла `docs/onboarding/*.md` начинаются с оговорки «фаза 0 / появится в фазе N» — это **контракты заранее**, а не инструкции по установке. Единственная реальная установочная последовательность — «Первые 30 минут» выше.

---

## 6. Ежедневные команды

В CLI сейчас **20 групп/команд верхнего уровня и 68 листовых команд**, из них 59 живых и 9 заглушек (`exit 3`). Ниже — те, что нужны каждый день; полный указатель «задача → команда» — [44-how-do-i.md](44-how-do-i.md).

| Команда | Что делает | Когда | Статус |
|---|---|---|---|
| `vn build` | lint → сборка ассетов → компиляция контента → `vn loc import` → бюджеты (размер G19 **и** память сцены) | после любой правки `content/` или `assets_src/` | IMPLEMENTED (`cli.py:88-157`) |
| `vn build --check` | то же без записи: свеж ли генерат + валидация разметки PO + бюджеты. Никогда ничего не пишет | перед коммитом, режим CI | IMPLEMENTED |
| `vn dev` | запускает игру и watch по `content/` + `assets_src/` (polling 1 с); в игре Shift+R. Профиль ассетов — `draft` | долгая итерация | IMPLEMENTED (`cli.py:247-298`, `devloop.py`) |
| `vn play` | запускает игру через SDK | быстрая проверка | IMPLEMENTED (`cli.py:205-221`) |
| `vn content lint` | схемы, именование, структура глав, exits, граф, LFS-покрытие бинарей `assets_src/` | когда `vn build` упал на lint | IMPLEMENTED (`cli.py:404-419`) |
| `vn loc keys` | дописывает say-id и маркеры меню в авторские `.rpy`, обновляет `loc/ledger/chNN.json` | после правки/добавления реплик | IMPLEMENTED (`cli.py:1105-1132`) |
| `vn assets memory` | во что обходится худшая сцена и влезает ли она в кэш образов | после тяжёлого шота/фона | IMPLEMENTED (`cli.py:572-604`) |
| `vn test oversample --scale 2` | **движком** подтверждает, что варианты `@2` реально подхватываются | после правки render-профиля | IMPLEMENTED (`cli.py:1628-1660`) |
| `vn test smoke` | in-process автопилот: проходит игру, скриншоты в `.vncache/smoke/`, гейт cold-start против бюджета 30 с | перед PR с изменением флоу | IMPLEMENTED (`cli.py:1571-1626`) |
| `python -m pytest tests -q` (из `tools/vn`) | 373 теста в 27 файлах, ~16 с | при правке `tools/vn/` | IMPLEMENTED |
| `vn doctor` | самодиагностика | когда «вчера работало» | IMPLEMENTED |

Что `vn dev` **не** отслеживает: `loc/`, `packs/`, `game/`, `tools/`, `project.yaml` — пути watch-а захардкожены как `root/assets_src` и `root/content` (`devloop.py:33-34`). Правку пака или PO-файла придётся пересобирать руками.

Подробности цикла разработки, веток и коммитов — [04-development-workflow.md](04-development-workflow.md).

---

## 7. Первое изменение: поменять реплику и увидеть её в игре

Задача: изменить первую фразу игры.

**Шаг 1.** Откройте `content/chapters/ch01_awakening/scenes/s010_intro.scene.rpy`. Сейчас там:

```renpy
label ch01_s010__body:
    "Первый учебный день. Звонок уже прозвенел, а ты всё ещё стоишь у ворот." id ch01_s010_0001
```

**Шаг 2.** Замените **только текст в кавычках**. Клаузу `id ch01_s010_0001` не трогайте — именно она сохраняет уже сделанные переводы при правке опечатки (`tools/vn/src/vn/loc/keys.py:9-10`).

**Шаг 3.** Обновите ledger:

```bash
vn loc keys        # -> ledger: loc/ledger/ch01.json ; loc keys: OK (0 файлов изменено)
```

Файл `.rpy` не изменится (id уже стоит), но `loc/ledger/ch01.json` перепишется новым исходным текстом. Ledger — источник для PO-экстракции.

**Шаг 4.** Прокатите текст до переводчиков (иначе они переводят старую фразу):

```bash
vn loc extract     # PO обновятся, изменённая строка станет fuzzy
```

**Шаг 5.** Соберите и посмотрите:

```bash
vn build           # build: OK ; внутри сам вызовет loc import -> game/tl
vn play
```

### Что будет, если забыть `vn loc keys`

- **`vn build` останется зелёным.** Проверено: `tools/vn/src/vn/content/lint.py` не знает ни про ledger, ни про say-id (grep по `ledger|say_list` — ноль совпадений). Локально вы ничего не заметите.
- **CI покраснеет.** Джоба `build-test` в `.github/workflows/ci.yml:83` выполняет `xvfb-run -a vn loc keys --check`, а тот сравнивает пересобранный ledger с диском и падает: `расхождение: loc/ledger/ch01.json устарел (тексты/структура разошлись со сценами)`, затем `ошибка: loc keys --check: есть строки без id или устаревший ledger — выполните vn loc keys` (`cli.py:1120-1125`, `keys.py:189`).
- **Если вы добавили НОВУЮ реплику** без `vn loc keys` — у неё вообще нет id, она никогда не попадёт в PO, и в релизе останется на исходном русском во всех языках. `--check` сообщит: `s010_intro.scene.rpy:12: say без id (будет ch01_s010_0002)` (`keys.py:124`).

Аналогично для нового `menu`: `vn loc keys` вставит строку `$ vn_menu = "ch01_s010_m001"` перед ним. После правки файлов команда **перечитывает их парсером заново** и при любом расхождении откатывает изменённые файлы (`keys.py:198-219`) — так что запускать её безопасно. Оговорка: откат идёт **из памяти процесса**, поэтому прерванный Ctrl+C прогон может оставить `.rpy` полуправленными — восстанавливать из git.

Полный round-trip локализации — [14-localization.md](14-localization.md).

---

## 8. Если что-то не собралось

| Симптом (дословный вывод) | Причина | Лечение |
|---|---|---|
| `vn: command not found` / `vn не является командой` | пакет не поставлен или поставлен в другой интерпретатор | `pip install -e "tools/vn[dev]"`; проверьте `python -c "import vn; print(vn.__file__)"` |
| десятки `ModuleNotFoundError: No module named 'yaml'` при `pytest` | pytest вызван другим интерпретатором, чем тот, куда ставили тулчейн | один venv на всё; `pip install -r tools/vn.lock` в то же окружение |
| `1 failed … No module named 'tests'` в `test_verify_regressions.py` | pytest запущен из корня репозитория: в `sys.path` нет `tools/vn` | `cd tools/vn && python -m pytest tests -q` |
| `ошибка: не найден корень репозитория: нужен project.yaml + tools/schemas/ в текущем каталоге или выше` | CWD вне репозитория. Маркер — **оба** файла сразу, `.git` не участвует (`repo.py:15-23`) | `cd` в корень репозитория |
| `✗ Ren'Py SDK не найден` в `vn doctor` | `RENPY_SDK` не задан / задан в другом процессе / указывает не туда (нужен каталог с `renpy.py`) | `export` (macOS/Linux) или `setx` + **новый терминал** (Windows) — см. §2 |
| `RENPY_SDK не установлен, а в content/ есть главы: компиляция сцен требует парсер Ren'Py из пиннованного SDK (G24)` | то же, но поймано компилятором при холодном кэше (`analyze.py:26-29`) | то же |
| `build-bridge (renpy vn_analyze) упал: код N` + stdout/stderr | версия SDK не та, либо авторский `.rpy` не парсится | сверьте `vn doctor` (пин `8.5.3`); читайте stderr — там ошибка парсера Ren'Py с номером строки |
| `error: …` ×N, затем `ошибка: lint: N ошибок — сборка остановлена` | нарушены декларации/именование/exits | `vn content lint` — печатает те же ошибки без сборки; [08-content-pipeline.md](08-content-pipeline.md) |
| `assets_src/voice: есть мастера озвучки, но ffmpeg не найден` / то же про `video_src` | ffmpeg отсутствует, а мастера в репозитории есть | поставьте полный ffmpeg (`vn pipeline doctor`); без него **вся** сборка ассетов красная, а не только эта ветка |
| `<путь>: файл … не подобран ни одной веткой` | мастер лежит вне известной зоны или в неподдержанном формате | перечитайте конвенцию зоны в [16-assets.md](16-assets.md); одна такая ошибка останавливает сборку целиком |
| `память: худшая сцена … бюджет памяти сцены превышен (project.yaml: render.image_cache_mb)` | worst-case сцена не влезает в кэш образов (ADR-0012) | `vn assets memory --top 5`; лишний полупрозрачный пиксель растягивает bbox на весь холст |
| `✗ шрифты UI: 0/3 материализованы (указатели LFS: …)` | чекаут без git-lfs | `git lfs install && git lfs pull` |
| `ошибка: game/generated/ пуст — сначала vn build` (из `vn play`) | нет `game/generated/manifest.json`; генерат не в git | `vn build` (или `vn bootstrap` на свежем чекауте) |
| `бюджет: game/assets: … МБ > бюджета 20000 МБ` + `ошибка: бюджеты G19 превышены` | превышен размер-бюджет из `project.yaml:57-65` | это предохранитель от аварии (зацикленный экспорт, забытый 8K-вариант), а не потолок игры; [32-performance-and-scalability.md](32-performance-and-scalability.md) |
| `vn build` зелёный, но `vn doctor` красный по SDK | тёплый кэш анализа (`.vncache/analyze-*.json`) | `rm .vncache/analyze-*.json` и пересоберите — увидите настоящее состояние |
| Кракозябры вместо русского в `vn --help` под Git Bash | реконфигурация stdout не успевает отработать до eager-опции `--help` (`cli.py:49-55`) | смотрите help из PowerShell |
| `эта команда появится в фазе N (раздел 8 ARCHITECTURE.md)`, exit **3** | команда — честная заглушка `_stub` (`cli.py:34-38`) | это не поломка. Полный список (9, состав закреплён тестом `test_cli.py`): `vn migrate`, `vn shell` (фаза 2), `vn char new|validate` (фаза 1), `vn char sheet`, `vn test replay`, `vn test paths` (фаза 2), `vn save migrate`, `vn test screens` (фаза 3) |
| `Error: No such command '…'`, exit **2** | команды не существует вовсе | не путать с exit 3: `vn validate`, `vn build --use-artifact`, `vn content lint --strict`, `vn test perf`, `vn bootstrap --role` в CLI отсутствуют |

Exit-коды CLI: `0` успех, `1` ошибка проверки/сборки (**всегда с сообщением, никогда голым трейсбеком** — `cli.py:22-24`), `2` usage error от click, `3` не реализовано в этой фазе (`cli.py:34-38`).

Более широкий справочник проблем — [36-troubleshooting.md](36-troubleshooting.md), разбор падений в рантайме — [28-debugging.md](28-debugging.md), «как сделать X» — [44-how-do-i.md](44-how-do-i.md).

---

## Как изменить / Как расширить

- **Добавить проверку в `vn doctor`:** `tools/vn/src/vn/doctor.py:69-153`. Формат — кортеж `(ok: bool|None, заголовок, рецепт)`; `None` = WARN (не влияет на exit). Рецепт обязателен и должен быть исполнимой командой, а не «проверьте настройки» (норма G22). Тестов у `run_doctor()` нет — покрыт только `_lfs_pointer_fonts` (`test_verify_regressions.py:155-184`), так что новую проверку тестируйте вручную в обоих состояниях.
- **Добавить проверку в `vn pipeline doctor`:** `pipeline.py:455-581`, хелпер `_check(checks, state, title, hint)`. Помните: `FAIL` = красный конвейер; всё опциональное (третьи источники рендера, необязательные модели) обязано быть `WARN`.
- **Поднять минимальную версию тулинга:** `project.yaml:4 min_tools` + `tools/vn/src/vn/__init__.py:3` + `tools/vn/pyproject.toml:7` (версия продублирована руками в двух местах). Сравнение живёт **только** в `vn doctor` (`doctor.py:87-96`) — `vn build` `min_tools` не смотрит.
- **Сменить пин SDK:** `project.yaml:5 renpy_sdk` + вручную `RENPY_VERSION` в `.github/workflows/{ci,nightly,release}.yml`. Автоматической сверки этих значений нет — расхождение никто не поймает. Норма G18 требует отдельного PR с прогоном canary.
- **Однокомандный инсталлер по ролям** (`vn bootstrap --role`) — NOT IMPLEMENTED, обещан `README.md:11` как фаза 1. См. [37-roadmap.md](37-roadmap.md).

---

## Чего НЕ делать

- **Не правьте `game/generated/`, `game/assets/`, `game/tl/`.** Это производные зоны, их нет в git, и следующий `vn build` перезапишет вашу правку. Полный перечень зон и что именно произойдёт — [44-how-do-i.md](44-how-do-i.md) §26.
- **Не считайте зелёный `vn build` доказательством настроенного окружения** — тёплый `.vncache` пропускает сборку без SDK. Доказательство — `vn doctor` с exit 0.
- **Не запускайте `setx` и не ждите эффекта в текущем терминале.** Новый процесс — обязательно.
- **Не правьте текст реплики вместе с её `id`.** Смена id = потеря всех переводов этой строки; `vn loc keys` заново назначит номер, а PO-запись осиротеет.
- **Не убирайте `id …` из авторской `.rpy` «чтобы было чище»** — CI-шаг `vn loc keys --check` покраснеет, а строка выпадет из локализации.
- **Не ставьте произвольную версию Ren'Py SDK.** Пин `8.5.3` (G18): `vn doctor` сверяет `<sdk>/renpy/vc_version.py` с `project.yaml` и падает на несовпадении.
- **Не ставьте тулчейн одной командой `pip install -e "tools/vn[dev]"`** — так вы отрезолвите свободные `>=` из `pyproject.toml`. Сначала `pip install -r tools/vn.lock`, потом editable; обратный порядок лок не применит.
- **Не заводите новый CI-шаг установки без `pip install -r tools/vn.lock` перед editable-установкой** — `test_ci_config.py` проверяет порядок во всех workflow и покраснеет (G17). И не считайте лок исчерпывающим: транзитивные зависимости пинов (`pygments` и подобные) в нём не перечислены.
- **Не отправляйте синтетический ввод (SendKeys и подобное) в окно игры для «автотеста»** — единственный поддерживаемый способ прогнать игру автоматически — in-process автопилот `vn test smoke`.
- **Не считайте `docs/ARCHITECTURE.md` инструкцией по установке** — это целевой норматив. Установочная последовательность одна, она выше.

---

## Проверка

```bash
export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"   # в bash — обязательно

vn doctor                          # 8 галок, exit 0
vn build                           # build: OK
vn build --check                   # ничего не пишет
vn content lint                    # lint: OK (0 предупреждений)
vn loc keys --check                # все строки с id, ledger свеж
vn loc report                      # de/en/pseudo — 136/136 (100%), fuzzy 0
vn voice validate --report         # ch01 [ru]: покрыто 14/14 (100%)
vn assets memory                   # память: OK
vn test oversample --scale 2       # oversample: OK
(cd tools/vn && python -m pytest tests -q)   # 373 passed
vn play                            # игра стартует
```

Для контент-продакшена дополнительно: `vn pipeline doctor` (exit 0; два WARN про VaM/Sims 4 — норма).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/doctor.py`, `tools/vn/src/vn/repo.py`, `tools/vn/src/vn/cli.py:18-300`, `tools/vn/src/vn/pipeline.py:455-581`, `project.yaml`, `.github/workflows/ci.yml` |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `.vncache/**`, `build/**` — производные зоны, перезаписываются сборкой; `loc/ledger/*.json` правится только через `vn loc keys` |
| **Зависимости** | `RENPY_SDK` → build-bridge (`game/framework/00_core/050_build_bridge.rpy` + `tools/vn/src/vn/content/analyze.py`) → `compile_content` → `game/generated/` → `vn play` / `vn test smoke` / `vn package` / `vn release build`. Нет SDK и нет тёплого кэша → падает вся цепочка. `project.yaml: renpy_sdk` продублирован как `RENPY_VERSION` в трёх workflow — сверки нет |
| **Валидация** | `vn doctor && vn build --check && vn content lint && vn loc keys --check && (cd tools/vn && python -m pytest tests -q)` |
| **Частые ошибки** | 1) не экспортировать `RENPY_SDK` в bash-вызове — `vn doctor` падает, `vn build` обманчиво зеленеет на кэше; 2) запускать pytest из корня репозитория (`No module named 'tests'`) или другим интерпретатором (`No module named 'yaml'`); 3) забыть `vn loc keys` после правки реплики — локально зелено, CI красный; 4) считать `docs/ARCHITECTURE.md` описанием построенного: `vn validate`, `vn build --use-artifact <sha>`, `vn bootstrap --role`, `vn test perf` там упомянуты, но в CLI их **нет** (exit 2); 5) запускать `vn` из подкаталога вне репозитория — `find_root()` ищет `project.yaml` **и** `tools/schemas/`, `.git` не считается; 6) путать exit 3 (заглушка фазы) и exit 2 (команды нет вовсе) |

---

Соседние файлы: [02-architecture.md](02-architecture.md) — зоны и нормы G/C; [04-development-workflow.md](04-development-workflow.md) — цикл разработки, git, CI; [44-how-do-i.md](44-how-do-i.md) — «как сделать X»; [25-custom-engine.md](25-custom-engine.md) — устройство `vn` CLI; [27-testing.md](27-testing.md) — тесты и smoke; [29-build-and-release.md](29-build-and-release.md) — сборка и релиз; [36-troubleshooting.md](36-troubleshooting.md) — справочник проблем.
