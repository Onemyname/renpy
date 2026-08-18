# 03. Начало работы: от чистой машины до запущенной игры

> **Статус подсистемы:** IMPLEMENTED — путь `clone → pip install → vn doctor → vn build → vn play` работает целиком, но однокомандного инсталлера по ролям нет (`vn bootstrap` без опций, `--role` NOT IMPLEMENTED), а `RENPY_SDK` приходится ставить руками.
> **Отвечает на вопрос:** «Что мне выполнить прямо сейчас, чтобы игра запустилась, и как понять, почему не запустилась?»

Всё окружение проекта диагностируется двумя командами: `vn doctor` (нужна всем — репозиторий, схемы, шрифты, SDK) и `vn pipeline doctor` (нужна только тем, кто производит картинки и видео — GPU, ComfyUI, модели, DAZ, ffmpeg). Обе печатают рецепт починки прямо под провалившейся строкой. Код: `tools/vn/src/vn/doctor.py`, `tools/vn/src/vn/pipeline.py:455-581`.

---

## Быстрый ответ

```bash
git lfs install                                  # ОДИН раз на машину
git clone https://github.com/Onemyname/renpy vn  # репозиторий приватный
cd vn
git lfs pull                                     # шрифты UI — бинари из LFS
pip install -e "tools/vn[dev]"                   # ставит команду vn; [dev] нужен для pytest
setx RENPY_SDK "C:\Users\<you>\renpy-sdk\renpy-8.5.3-sdk"   # и ОТКРОЙТЕ НОВЫЙ терминал
vn doctor                                        # должно быть 8 галок, exit 0
vn build                                         # -> build: OK
vn play                                          # запуск игры
```

Проверено на машине владельца 2026-08-08: `vn doctor` — 8 PASS / 0 FAIL, `vn build` — `build: OK` за **0.29 с** на прогретом кэше, `python -m pytest tools/vn/tests -q` — 253 passed.

---

## 1. Требования

| Компонент | Что нужно | Проверяет | Обязателен? |
|---|---|---|---|
| Python | код требует `>= 3.10` (`doctor.py:72`, `tools/vn/pyproject.toml:9`), но проверяется проект на **3.12** (CI `setup-python 3.12`; машина владельца 3.12.10) | `vn doctor` | да, hard fail |
| git | в PATH | `vn doctor` | да, hard fail |
| git-lfs | `git lfs version` должен отвечать | `vn doctor` | да, hard fail |
| Ren'Py SDK | версия **8.5.3** — пин `project.yaml:5 renpy_sdk: "8.5.3"` (G18); путь в `RENPY_SDK` | `vn doctor` | hard fail, **если** есть `content/chapters/ch*` (а они есть) |
| ffmpeg (полный, с libvpx-vp9) | только для видео-трека | `vn pipeline doctor` | нет |
| NVIDIA GPU + ComfyUI + модели | только для генерации картинок/видео | `vn pipeline doctor` | нет |
| DAZ Studio **6** (+ драйвер NVIDIA ≥ 576.57) | только для рендеров | `vn pipeline doctor` | нет |

`vn doctor` **не проверяет** ffmpeg, GPU и ComfyUI — они видны только в `vn pipeline doctor`. Не ищите их в первой команде.

**Про версию DAZ.** `../pipeline/phase-0.md:27` и `../../tools/install-daz.ps1:109` до сих пор пишут «4.24+» — это требование устарело и вводит в заблуждение: Iray в ветке 4.x собран до Blackwell, и на RTX 50xx он не работает вообще (тихий CPU-рендер либо «found no usable devices»). Ставьте **ветку 6**; на машине проекта `vn pipeline doctor` находит именно `DAZStudio6`. Подробности — [17-daz-studio.md](17-daz-studio.md) §2.3 и [22-rendering.md](22-rendering.md).

### Зависимости и пины

`pip install -e tools/vn` тянет `click>=8.1, PyYAML>=6.0, jsonschema>=4.21, blake3>=0.4, Pillow>=10.0, psd-tools>=1.9, polib>=1.2` (`tools/vn/pyproject.toml:10-18`); `[dev]` добавляет `pytest>=8.0`.

`tools/vn.lock` (18 пинов) — **PARTIALLY IMPLEMENTED**: с 2026-08-08 лок **читается CI**. Во всех в 8 джобах установки тулчейна (7 строк в конфигах: GitLab-шаблон `.with-sdk` разворачивается в `build` и `test`) — 5 шагов в четырёх GitHub-workflow (`ci.yml` дважды: `lint` и `build-test`; `nightly.yml`, `canary.yml`, `release.yml`) и 2 строки в `.gitlab-ci.yml` — перед editable-установкой идёт `pip install --quiet -r tools/vn.lock`, и только потом `pip install -e "tools/vn[dev]"`, который уже не может подтянуть свежие версии поверх пинов. Порядок стережёт `tools/vn/tests/test_ci_config.py` (4 теста), поэтому новый workflow без лока не пройдёт CI.

**Честный остаток:** закреплены 18 пакетов — прямые зависимости `vn-tools` и их основные транзитивные. Транзитивные зависимости самого лока (например `pygments`, тянущийся за `pytest`) в файле не перечислены и по-прежнему резолвятся свободно. Норма G17 («откат тулчейна = git revert одного файла») выполняется для этих 18, но не абсолютна.

Локально `pip install -e "tools/vn[dev]"` по-прежнему резолвит `>=`-диапазоны из `pyproject.toml`. Чтобы получить ровно то же окружение, что в CI, выполните сначала `pip install -r tools/vn.lock`.

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

То есть `RENPY_SDK` обязан указывать на каталог, в котором лежит `renpy.py` (у владельца — `C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk`). Через `sdk_path()` ходят **все** потребители SDK: `vn play`, `vn dev`, `vn package`, `vn test smoke`, `vn save corpus`, `vn release build`, а также build-bridge `tools/vn/src/vn/content/analyze.py:24-33`.

Установка на Windows:

```powershell
setx RENPY_SDK "C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk"
```

### ГРАБЛЯ №1: `setx` виден только НОВЫМ процессам

`setx` пишет в User-окружение реестра. Уже открытые терминалы, запущенная IDE и все их дочерние процессы продолжают видеть старое окружение. Симптом — `vn doctor` показывает `✗ Ren'Py SDK не найден` сразу после успешного `setx`. Лечение: **закройте и откройте терминал**. Та же грабля отдельно обработана для `CIVITAI_API_KEY` — `_civitai_key_in_registry()` (`pipeline.py:318-330`) специально лезет в `HKCU\Environment`, чтобы отличить «ключа нет» от «ключ есть, но не в этом процессе».

### ГРАБЛЯ №2: в bash-сессии AI-агента переменная не наследуется

Проверено на этой машине прямо сейчас. Без экспорта:

```
 ✗ Ren'Py SDK не найден
     → скачайте SDK с renpy.org и укажите путь: setx RENPY_SDK <путь>; в content/
       есть главы — без SDK сцены не компилируются (G24)
EXIT=1
```

С экспортом в той же сессии:

```bash
export RENPY_SDK="C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk"
vn doctor    # ✓ Ren'Py SDK 8.5.3.26051504: ... ; EXIT=0
```

Правило для агента: **экспортируй `RENPY_SDK` первой строкой каждого bash-вызова**, где дальше идёт `vn build` / `vn play` / `vn dev` / `vn test smoke` / `vn save corpus` / `vn release *`.

### ГРАБЛЯ №3: тёплый `.vncache` маскирует отсутствие SDK

`analyze_scene_files` кэширует результат разбора сцен в `.vncache/analyze-<hash>.json` по blake3 от (версия vn + байты `050_build_bridge.rpy` + пути и байты всех `scene.rpy`) — `tools/vn/src/vn/content/analyze.py:41-56`. Если кэш попал, движок не запускается вовсе. Проверено: в сессии **без** `RENPY_SDK` `vn build` отработал `build: OK`, exit 0. Тот же комментарий стоит в `doctor.py:119-120`.

Следствие: «у меня собирается» ≠ «SDK настроен». Честная проверка — `vn doctor`, а не `vn build`. Чтобы заставить сборку реально дёрнуть движок: `rm .vncache/analyze-*.json`.

### ГРАБЛЯ №4: `vn --help` в Git Bash — кракозябры

Реконфигурация stdout в UTF-8 живёт в callback группы (`cli.py:49-55`), а `--help` — eager-опция click, которая печатает и выходит **до** callback. Проверено: в Git Bash `vn --help` выдаёт мусор вместо русских описаний, при этом `vn doctor` и все остальные команды печатаются корректно. В PowerShell 7 проблемы нет (в том числе при перенаправлении в файл). Если нужен `--help` из bash — читайте его через PowerShell или смотрите докстринги в `tools/vn/src/vn/cli.py`.

---

## 3. `vn doctor` — расшифровка каждой проверки

`IMPLEMENTED` — `tools/vn/src/vn/doctor.py:69-153`. Формат строки: `✓` (PASS) / `!` (WARN, не влияет на exit-код) / `✗` (hard fail). Рецепт печатается отступом `→` только для не-PASS. Exit 1, если есть хоть один `✗`.

Реальный вывод на здоровой машине (2026-08-08):

```
 ✓ Python 3.12.10
 ✓ git
 ✓ git-lfs (git-lfs/3.7.1 (GitHub; windows amd64; go 1.25.1; git b84b3384))
 ✓ корень репозитория: C:\Users\Vadim\IdeaProjects\renpy
 ✓ project.yaml (min_tools 0.1, vn 0.1.0)
 ✓ реестр схем: 39 схем
 ✓ шрифты UI: 3/3 материализованы
 ✓ Ren'Py SDK 8.5.3.26051504: C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk
```

| # | Проверка | Условие PASS | Что печатает при провале / как чинить | Код |
|---|---|---|---|---|
| 1 | Python | `sys.version_info >= (3,10)` | `нужен Python >= 3.10` | `:72-73` |
| 2 | git | `shutil.which("git")` | `установите git и добавьте в PATH` | `:75` |
| 3 | git-lfs | `git lfs version` вернул строку | `установите git-lfs: https://git-lfs.com` | `:76-77` |
| 4 | корень репозитория | `find_root()` нашёл `project.yaml` **и** `tools/schemas/` | `не найден корень репозитория: нужен project.yaml + tools/schemas/ в текущем каталоге или выше` → `cd` в репозиторий | `:79-84` |
| 5 | `project.yaml` / `min_tools` | `(major,minor)` версии `vn` `>=` `min_tools`; сейчас `vn 0.1.0` vs `min_tools "0.1"` | `обновите vn: pip install -e tools/vn`; нечитаемый файл → `не читается: <e>` | `:87-96` |
| 6 | реестр схем | `SchemaRegistry(tools/schemas)` сконструировался; в заголовке — число схем (36) | текст исключения: имя файла вне конвенции `<name>@<int>.schema.json` или `const` поля `schema` ≠ имени файла | `:98-102` |
| 7 | `.vnstorage.local.yaml` | **WARN-only** и только если файл есть: «локальное переопределение … активно» | ничего не чинить — это напоминание, что физика хранилища у вас своя | `:104-106` |
| 8 | шрифты UI | все `game/fonts/*.ttf|*.otf` начинаются с `\x00\x01\x00\x00` / `true` / `ttcf` / `OTTO` | `git lfs install && git lfs pull — файлы приехали указателями, а не шрифтами` | `:45-66`, `:111-117` |
| 9 | Ren'Py SDK | `sdk_path()` нашёл; `sdk_version()` из `<sdk>/renpy/vc_version.py` начинается с пина `project.yaml: renpy_sdk` | несовпадение пина → `поставьте пиннованную версию SDK или обновите пин отдельным PR (G18)` | `:124-137` |
| 9b | SDK отсутствует | — | **severity зависит от контента**: `✗` если есть каталоги `content/chapters/ch*`, иначе `!` | `:119-142` |

Про #8 подробнее — проверка **по содержимому файла**, а не по `git lfs status`, поэтому работает даже там, где git-lfs не установлен вообще (`doctor.py:50-66`). Тот же самый `_lfs_pointer_fonts` переиспользован релизным гейтом (`release.py:293-302`), потому что чекаут без LFS однажды уже уехал в сборку 0.1.1.

Про #9b: без глав SDK — предупреждение («нужен для vn play»), с главами — жёсткий провал («без SDK сцены не компилируются (G24)»). В текущем дереве `content/chapters/ch01_awakening/` есть, значит **у вас это всегда hard fail**.

`vn doctor` — единственная команда, которая работает вне репозитория: `find_root()` вызывается внутри try, дальше проверки продолжаются с `root = None` (`doctor.py:80-84`).

`vn bootstrap` (PARTIALLY IMPLEMENTED, `cli.py:202-222`) начинается с `run_doctor()` и при exit ≠ 0 останавливается: `bootstrap остановлен: почините окружение по рецептам vn doctor`. Дальше он делает `_assets_build(root, "full")` → `compile_content` → `_loc_import`. Скачивания из remote cache / CI-артефактов (норма G4) в нём **нет** — это прямо написано в его же докстринге. Опции `--role` не существует, хотя `README.md:11` обещает «однокомандный инсталлер по ролям — фаза 1» — **NOT IMPLEMENTED**.

---

## 4. `vn pipeline doctor` — расшифровка (нужна только контент-продакшену)

`IMPLEMENTED` — `pipeline.py:455-581`. Метки `PASS` / `WARN` / `FAIL`, exit 1 только на `FAIL`. Реальный вывод здорового окружения (2026-08-08, exit 0):

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

**Два WARN про VaM и Sims 4 — это норма, а не проблема.** Продакшен-трек проекта — DAZ (+ Wan I2V); VaM берут точечно под физику тел, Sims 4 — задел на будущее (ADR-0007, `docs/pipeline/phase-0.md:132-138`). Оба источника технически готовы (валидаторы деклараций реализованы), но **ноль деклараций** существует в репозитории, так что установка их не требуется.

Что здесь `FAIL` (то есть реально ломает конвейер): Python < 3.10, отсутствующий ffmpeg, сборка ffmpeg без libvpx-vp9, отсутствующий ffprobe, нечитаемый манифест моделей. Всё остальное — `WARN`. Про установку по шагам — `docs/pipeline/phase-0.md` и [17-daz-studio.md](17-daz-studio.md) / [20-image-generation.md](20-image-generation.md) / [21-video-generation.md](21-video-generation.md).

---

## 5. Роль → что ставить

| Роль | Минимум | Дополнительно | Онбординг |
|---|---|---|---|
| **Сценарист** | Python 3.12, git, git-lfs, Ren'Py SDK 8.5.3, `pip install -e tools/vn` | текстовый редактор с подсветкой `.rpy` | `../onboarding/writer.md` → [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md) |
| **Художник / motion** | то же **+** ffmpeg (полный) | DAZ Studio **6** (на 4.x Iray не видит RTX 50xx), ComfyUI + модели (`vn pipeline models --pull`), NVIDIA GPU 12+ ГБ VRAM и драйвер ≥ 576.57, опц. VaM | `../onboarding/artist.md`, `../pipeline/phase-0.md` → [16-assets.md](16-assets.md), [17-daz-studio.md](17-daz-studio.md) |
| **Локализатор** | то же, что сценарист | PO-редактор (Poedit и т.п.) — правится **только** `loc/po/<code>/*.po` | `../onboarding/localizer.md` → [14-localization.md](14-localization.md) |
| **Tools-инженер** | всё вышеперечисленное + `pip install -e "tools/vn[dev]"` (pytest) | — | `../onboarding/tools-engineer.md` → [25-custom-engine.md](25-custom-engine.md), [27-testing.md](27-testing.md) |

Все четыре файла `docs/onboarding/*.md` начинаются с оговорки «фаза 0 / появится в фазе N» — это **контракты заранее**, а не инструкции по установке. Единственная реальная установочная последовательность — раздел «Быстрый ответ» выше.

---

## 6. Ежедневные команды

| Команда | Что делает | Когда | Статус |
|---|---|---|---|
| `vn build` | lint → сборка ассетов → компиляция контента → `vn loc import` → бюджеты G19 | после любой правки `content/` или `assets_src/` | IMPLEMENTED (`cli.py:84-153`) |
| `vn build --check` | то же без записи: свеж ли генерат + валидация разметки PO + бюджеты. Никогда ничего не пишет | перед коммитом, режим CI | IMPLEMENTED |
| `vn dev` | запускает игру и watch по `content/` + `assets_src/` (polling 1 с); в игре Shift+R | долгая итерация | IMPLEMENTED (`cli.py:225-276`, `devloop.py:31-56`) |
| `vn play` | запускает игру через SDK | быстрая проверка | IMPLEMENTED (`cli.py:183-199`) |
| `vn content lint` | 34 правила: схемы, именование, структура глав, exits, layout | когда `vn build` упал на lint | IMPLEMENTED |
| `vn loc keys` | дописывает say-id и маркеры меню в авторские `.rpy`, обновляет `loc/ledger/chNN.json` | после правки/добавления реплик | IMPLEMENTED (`cli.py:966-993`) |
| `vn test smoke` | in-process автопилот: проходит игру, скриншоты в `.vncache/smoke/`, проверка cold-start против бюджета 30 с | перед PR с изменением флоу | IMPLEMENTED (`cli.py:1347-1401`) |
| `python -m pytest tools/vn/tests -q` | 253 теста в 24 файлах, ~7 с | при правке `tools/vn/` | IMPLEMENTED |
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
- **CI покраснеет.** Джоб `build-test` в `.github/workflows/ci.yml` выполняет `xvfb-run -a vn loc keys --check`, а тот сравнивает пересобранный ledger с диском и падает:
  `расхождение: loc/ledger/ch01.json устарел (тексты/структура разошлись со сценами) — выполните vn loc keys`, затем `ошибка: loc keys --check: есть строки без id или устаревший ledger` (`cli.py:981-987`, `tools/vn/src/vn/loc/keys.py:178-194`).
- **Если вы добавили НОВУЮ реплику** без `vn loc keys` — у неё вообще нет id, она никогда не попадёт в PO, и в релизе останется на исходном русском во всех языках. `--check` сообщит: `s010_intro.scene.rpy:12: say без id (будет ch01_s010_0002)`.

Аналогично для нового `menu`: `vn loc keys` вставит строку `$ vn_menu = "ch01_s010_m001"` перед ним (`tools/vn/src/vn/loc/keys.py:169-171`). После правки файлов команда **перечитывает их парсером заново**, и при любом расхождении делает полный откат изменённых файлов (`keys.py:198-219`) — так что запускать её безопасно.

Полный round-trip локализации — [14-localization.md](14-localization.md).

---

## 8. Если что-то не собралось

| Симптом (дословный вывод) | Причина | Лечение |
|---|---|---|
| `vn: command not found` / `vn не является командой` | пакет не поставлен или поставлен в другой интерпретатор | `pip install -e "tools/vn[dev]"`; проверьте `python -c "import vn; print(vn.__file__)"` |
| `ошибка: не найден корень репозитория: нужен project.yaml + tools/schemas/ в текущем каталоге или выше` | CWD вне репозитория. Маркер — **оба** файла сразу, `.git` не участвует (`repo.py:15-23`) | `cd` в корень репозитория |
| `✗ Ren'Py SDK не найден` в `vn doctor` | `RENPY_SDK` не задан / задан в другом процессе / указывает не туда (нужен каталог с `renpy.py`) | `setx` + **новый терминал**; в bash — `export` в том же вызове (см. §2) |
| `RENPY_SDK не установлен, а в content/ есть главы: компиляция сцен требует парсер Ren'Py из пиннованного SDK (G24)` | то же, но поймано компилятором при холодном кэше (`analyze.py:26-29`) | то же |
| `build-bridge (renpy vn_analyze) упал: код N` + stdout/stderr | версия SDK не та, либо авторский `.rpy` не парсится | сверьте `vn doctor` (пин `8.5.3`); читайте stderr — там ошибка парсера Ren'Py с номером строки |
| `error: …` ×N, затем `ошибка: lint: N ошибок — сборка остановлена` | нарушены декларации/именование/exits | `vn content lint` — он печатает те же ошибки без сборки; [08-content-pipeline.md](08-content-pipeline.md) |
| `✗ шрифты UI: 0/3 материализованы (указатели LFS: …)` | чекаут без git-lfs | `git lfs install && git lfs pull` |
| `ошибка: game/generated/ пуст — сначала vn build` (из `vn play`) | нет `game/generated/manifest.json`; генерат не в git | `vn build` (или `vn bootstrap` на свежем чекауте) |
| `бюджет: game/assets: … МБ > бюджета 500 МБ` + `ошибка: бюджеты G19 превышены` | превышен размер-бюджет из `project.yaml:6-11` | почистите ассеты или обсудите бюджет отдельным PR; [32-performance-and-scalability.md](32-performance-and-scalability.md) |
| `vn build` зелёный, но `vn doctor` красный по SDK | тёплый кэш анализа (`.vncache/analyze-*.json`) | `rm .vncache/analyze-*.json` и пересоберите — увидите настоящее состояние |
| Кракозябры вместо русского в `vn --help` под Git Bash | реконфигурация stdout не успевает отработать до eager-опции `--help` (`cli.py:49-55`) | смотрите help из PowerShell |
| `эта команда появится в фазе N (раздел 8 ARCHITECTURE.md)`, exit **3** | команда — честная заглушка `_stub` | это не поломка: `vn char new/validate` (фаза 1), `vn migrate`, `vn shell`, `vn char sheet`, `vn voice tts`, `vn test replay|paths` (фаза 2), `vn save migrate`, `vn test screens` (фаза 3). `vn release steam` заглушкой быть перестала — она реализована по ADR-0014 |

Exit-коды CLI: `0` успех, `1` ошибка проверки/сборки (**всегда с сообщением, никогда голым трейсбеком** — `cli.py:22-24`), `2` usage error от click, `3` не реализовано в этой фазе (`cli.py:34-38`).

Более широкий справочник проблем — [36-troubleshooting.md](36-troubleshooting.md), разбор падений в рантайме — [28-debugging.md](28-debugging.md).

---

## Как изменить / Как расширить

- **Добавить проверку в `vn doctor`:** `tools/vn/src/vn/doctor.py:69-153`. Формат — кортеж `(ok: bool|None, заголовок, рецепт)`; `None` = WARN (не влияет на exit). Рецепт обязателен и должен быть исполнимой командой, а не «проверьте настройки» (норма G22). Тестов у `run_doctor()` нет — покрыт только `_lfs_pointer_fonts` (`test_verify_regressions.py:134-162`), так что новую проверку тестируйте вручную в обоих состояниях.
- **Добавить проверку в `vn pipeline doctor`:** `pipeline.py:455-581`, хелпер `_check(checks, state, title, hint)`. Помните: `FAIL` = красный конвейер; всё опциональное (третьи источники рендера, необязательные модели) обязано быть `WARN`.
- **Поднять минимальную версию тулинга:** `project.yaml:4 min_tools` + `tools/vn/src/vn/__init__.py:3` + `tools/vn/pyproject.toml:7` (версия продублирована руками в двух местах). Сравнение живёт **только** в `vn doctor` (`doctor.py:87-96`) — `vn build` `min_tools` не смотрит.
- **Сменить пин SDK:** `project.yaml:5 renpy_sdk` + вручную `RENPY_VERSION` в `.github/workflows/{ci,nightly,release}.yml`. Автоматической сверки этих значений нет — расхождение никто не поймает. Норма G18 требует отдельного PR с прогоном canary.
- **Однокомандный инсталлер по ролям** (`vn bootstrap --role`) — NOT IMPLEMENTED, обещан `README.md:11` как фаза 1. См. [37-roadmap.md](37-roadmap.md).

---

## Чего НЕ делать

- **Не правьте `game/generated/`, `game/assets/`, `game/tl/`.** Это производные зоны, их нет в git, и следующий `vn build` перезапишет вашу правку. `game/tl/` регенерируется даже неявно — `vn build` вызывает `_loc_import` в конце (`cli.py:151`).
- **Не считайте зелёный `vn build` доказательством настроенного окружения** — тёплый `.vncache` пропускает сборку без SDK. Доказательство — `vn doctor` с exit 0.
- **Не запускайте `setx` и не ждите эффекта в текущем терминале.** Новый процесс — обязательно.
- **Не правьте текст реплики вместе с её `id`.** Смена id = потеря всех переводов этой строки; `vn loc keys` заново назначит номер, а PO-запись осиротеет.
- **Не убирайте `id …` из авторской `.rpy` «чтобы было чище»** — CI-джоб `vn loc keys --check` покраснеет, а строка выпадет из локализации.
- **Не ставьте произвольную версию Ren'Py SDK.** Пин `8.5.3` (G18): `vn doctor` сверяет `<sdk>/renpy/vc_version.py` с `project.yaml` и падает на несовпадении.
- **Не заводите новый CI-шаг установки без `pip install -r tools/vn.lock` перед editable-установкой** — `test_ci_config.py` проверяет порядок во всех workflow и покраснеет (G17). И не считайте лок исчерпывающим: транзитивные зависимости пинов (`pygments` и подобные) в нём не перечислены.
- **Не отправляйте синтетический ввод (SendKeys и подобное) в окно игры для «автотеста»** — единственный поддерживаемый способ прогнать игру автоматически — in-process автопилот `vn test smoke`.

---

## Проверка

```bash
export RENPY_SDK="C:\Users\Vadim\renpy-sdk\renpy-8.5.3-sdk"   # в bash — обязательно

vn doctor                          # ожидается 8 галок, exit 0
vn build                           # build: OK
vn build --check                   # check: генерат свеж  (ничего не пишет)
vn content lint                    # 0 ошибок
python -m pytest tools/vn/tests -q # 253 passed
vn loc keys --check                # loc keys --check: все строки с id, ledger свеж
vn loc report                      # de/en/pseudo — 115/115 (100%), fuzzy 0
vn play                            # игра стартует
```

Для контент-продакшена дополнительно: `vn pipeline doctor` (exit 0; два WARN про VaM/Sims 4 — норма).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/doctor.py`, `tools/vn/src/vn/repo.py`, `tools/vn/src/vn/cli.py:41-276`, `tools/vn/src/vn/pipeline.py:455-581`, `project.yaml`, `README.md` |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `.vncache/**`, `build/**` — производные зоны, перезаписываются сборкой; `loc/ledger/*.json` правится только через `vn loc keys` |
| **Зависимости** | `RENPY_SDK` → build-bridge (`tools/vn/src/vn/content/analyze.py`) → `compile_content` → `game/generated/` → `vn play` / `vn test smoke` / `vn package` / `vn release build`. Нет SDK и нет тёплого кэша → падает вся цепочка. `project.yaml: renpy_sdk` продублирован как `RENPY_VERSION` в трёх workflow — сверки нет |
| **Валидация** | `vn doctor && vn build --check && vn content lint && python -m pytest tools/vn/tests -q && vn loc keys --check` |
| **Частые ошибки** | 1) не экспортировать `RENPY_SDK` в bash-вызове — `vn doctor` падает, `vn build` обманчиво зеленеет на кэше; 2) читать `vn --help` из Git Bash и получить кракозябры (`cli.py:49-55`); 3) забыть `vn loc keys` после правки реплики — локально зелено, CI красный; 4) считать `docs/ARCHITECTURE.md` описанием построенного: `vn validate`, `vn build --use-artifact <sha>`, `vn bootstrap --role`, `vn test perf` там упомянуты, но в CLI их **нет** (unknown command → exit 2); 5) запускать `vn` из подкаталога вне репозитория — `find_root()` ищет `project.yaml` **и** `tools/schemas/`, `.git` не считается |

---

Соседние файлы: [02-architecture.md](02-architecture.md) — зоны и нормы G/C; [04-development-workflow.md](04-development-workflow.md) — цикл разработки; [25-custom-engine.md](25-custom-engine.md) — устройство `vn` CLI; [27-testing.md](27-testing.md) — тесты и smoke; [29-build-and-release.md](29-build-and-release.md) — сборка и релиз; [36-troubleshooting.md](36-troubleshooting.md) — справочник проблем.
