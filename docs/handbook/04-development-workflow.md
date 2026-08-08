# 04. Цикл разработки

> **Статус подсистемы:** IMPLEMENTED (инструментальная часть) / PARTIAL (процессная) — цикл «правка → `vn build` → `vn play`/`vn dev` → `vn content lint` → `pytest` → commit» работает целиком и покрыт CI из 4 GitHub-workflow; **но** процесс вокруг него держится на дисциплине одного человека: веток и PR нет (51 коммит линейно в `main`), все хэндлы в `CODEOWNERS` — плейсхолдеры, pre-commit-хука из `ARCHITECTURE.md:659` не существует, а `.gitlab-ci.yml` устарел и вводит в заблуждение.
> **Отвечает на вопрос:** «Я поправил файл — что запустить, чем проверить и как это закоммитить, чтобы CI не покраснел?»

Всё, что делает разработчик руками, проходит через CLI `vn` (`../../tools/vn/src/vn/cli.py`, 1632 строки, 20 команд/групп верхнего уровня). CI — тонкая обёртка над теми же командами: `.github/workflows/ci.yml:1-2` явно фиксирует правило «вся логика — в CLI `vn`, конфиг тонкий». Поэтому локальный прогон и CI отличаются только окружением (Linux + `xvfb-run`, у Ren'Py нет headless-режима — норма G23), а не набором проверок.

## Быстрый ответ

```bash
# 1. Итерация: игра + автопересборка content/ и assets_src/ (нужен RENPY_SDK)
vn dev
#    ...или разово
vn build && vn play

# 2. Перед коммитом (минимум — 5-10 секунд)
vn content lint
git status --short          # game/generated|assets|tl быть не должно

# 3. Перед коммитом (полный прогон, зеркалит ci.yml — около минуты)
vn build
vn loc keys --check
vn content compile --check
python -m pytest tools/vn/tests -q

# 4. Коммит: type(scope): описание по-русски + трейлер Co-Authored-By
git commit -m "feat(gallery): ..."
```

**Грабля окружения:** в bash-сессиях агента `RENPY_SDK` не наследуется из User-переменных Windows — экспортить вручную: `export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`. Без него падают `vn play`, `vn dev`, `vn package`, `vn test smoke` и компиляция сцен (`doctor.py:24-30` — поиск SDK **только** через эту переменную, никакого PATH-фолбэка).

---

## 1. Цикл разработки: что пересобирать после какой правки

| Что правишь | Чем пересобирается | Что упадёт, если забыть | Подробнее |
|---|---|---|---|
| `content/**/*.scene.yaml`, `chapter.yaml`, `*.vars.yaml` | `vn build` (или `vn dev` автоматически) | `vn content compile --check` в CI: «генерат не свеж» | [12-scenes.md](12-scenes.md), [09-chapters.md](09-chapters.md) |
| авторский `content/**/*.scene.rpy` | `vn build` (парсинг через SDK, G24) | то же + `vn loc keys --check`, если добавлены реплики | [13-dialogue.md](13-dialogue.md) |
| `game/framework/**/*.rpy` | ничего — Ren'Py читает файл напрямую; в игре Shift+R | `renpy … . lint` в CI | [05-renpy-development.md](05-renpy-development.md), [06-frontend.md](06-frontend.md) |
| `assets_src/**` (PNG/PSD/видео) | `vn assets build` или `vn dev` | `vn build` в CI: «game/assets не свеж» | [16-assets.md](16-assets.md) |
| `content/ui/panels.yaml` | `vn build` (трансформация `ui_panel`) | несвежие `vn_frame_*` в генерате | [06-frontend.md](06-frontend.md) |
| `loc/po/**` | `vn loc import` — входит в полный `vn build` (`cli.py:151`) | сборка уедет без переводов: `game/tl/` не в git | [14-localization.md](14-localization.md) |
| `tools/vn/**` | ничего — установка editable (`pip install -e "tools/vn[dev]"`) | `pytest tools/vn/tests -q` | [25-custom-engine.md](25-custom-engine.md) |
| `project.yaml`, `tools/schemas/**` | `vn build` целиком | лавинообразно: lint, компилятор, релизный гейт | [02-architecture.md](02-architecture.md) |

Сквозная картина конвейера `content/` → `game/generated/` — в [08-content-pipeline.md](08-content-pipeline.md).

### `vn dev` — что именно watch'ится — IMPLEMENTED

`cli.py:225-276` + `../../tools/vn/src/vn/devloop.py` (56 строк).

- **Корни watch'а зашиты в код:** `root/assets_src` и `root/content` (`devloop.py:33-34`). Больше **ничего**: ни `loc/`, ни `packs/`, ни `game/framework/`, ни `project.yaml`, ни `tools/`. Правку в `packs/ep_beach/chapters/...` вотчер не увидит — пересобирайте руками.
- **Механизм:** polling без внешних зависимостей. Каждую итерацию `_snapshot()` обходит `rglob("*")` и запоминает `{путь: (mtime, size)}`; неравенство словарей = изменение (`devloop.py:15-28`).
- **Интервал — 1.0 секунды** (`devloop.py:31`), причём `time.sleep(interval)` выполняется **до** первого сравнения (`devloop.py:40`): первая реакция наступает через секунду после старта, не мгновенно.
- **Изменился `assets_src/`** → `_assets_build(root, "draft")`, затем `compile_content(root)` — реестр образов зависит от собранных ассетов (`cli.py:243-252`).
- **Изменился `content/`** → только `compile_content(root)` (`cli.py:254-262`).
- **Колбэк не убивает вотчер:** исключение печатается как `[vn watch] пересборка ассетов упала: …` / `[vn watch] компиляция контента упала: …` и цикл продолжается (`devloop.py:46-56`). Залоченный Photoshop'ом файл или битый YAML — не повод перезапускать `vn dev`.
- **Выход:** закрытие окна игры останавливает вотчер (`stop_check = lambda: game.poll() is not None`, `cli.py:269`), Ctrl+C — тоже.
- **После пересборки в игре — Shift+R.** Замена пикселей подхватывается по месту; структурные правки (новая сцена, новый слой) могут сбросить позицию (`cli.py:229-230`).

**Важно про качество:** `vn dev` собирает ассеты в профиле `draft`, а не `full`. Разница ровно в трёх местах: качество WebP (95/90/90 → 50), `method` для `ui_panel` (4 → 0) и видео (`crf 30 / cpu-used 2 / ≤1080` → `crf 42 / cpu-used 8 / ≤720`). То, что вы видите в `vn dev`, **не** релизная картинка — оценивать качество по нему нельзя.

### `vn assets watch` теряет события `content/` — PARTIALLY IMPLEMENTED

`cli.py:550-568` использует тот же вотчер, но подставляет пустой колбэк:

```python
watch(root, on_assets, lambda: None)   # cli.py:566
```

Вотчер честно снимает снапшот `content/` каждый тик, обнаруживает изменения — и выбрасывает их. Для художника, который только кладёт PNG в папку, это работает; **для полноценного цикла используйте `vn dev`**. Профиль по умолчанию у `assets watch` — `draft` (у `vn assets build` — `full`).

---

## 2. Конвенция коммитов — IMPLEMENTED / UNDOCUMENTED

Конвенция соблюдается в истории, но **нигде не записана**: в репозитории нет `CONTRIBUTING.md`, нет `.github/PULL_REQUEST_TEMPLATE.md`, каталог `.github/` содержит только `workflows/`. Ниже — то, что выведено из реального `git log`.

Из 51 коммита **35 в формате Conventional Commits** (всё начиная с `ecd12fe feat(pipeline): окружение Фазы 0`), 16 более ранних — свободная форма вида `Фаза 1 (контент-конвейер): …`, `Локализация: языки как пакеты (ADR-0005) — тулинг`. Новые коммиты пишем по конвенции; старые не переписываем.

**Формат заголовка:** `type(scope): краткое описание по-русски`

| type | Сколько в логе | Пример из истории |
|---|---|---|
| `feat` | 22 | `feat(gallery): галерея/экстры — декларации, разблокировка по якорям, UI (ADR-0010)` |
| `fix` | 6 | `fix(ci): checkout с lfs:true + гейт ловит шрифты-указатели (релиз 0.1.2)` |
| `docs` | 3 | `docs(ui): бриф дизайн-итерации для экрана выбора ответов` |
| `test` | 1 | `test: обновить ожидания состава генерата под ui_frames.gen.rpy` |
| `refactor` | 1 | `refactor(pipeline): Sims 4 — только движок источника, лицензионная механика убрана (ADR-0007)` |
| `release` | 2 | `release: 0.1.4 — галерея/экстры` (без скоупа, см. §3) |

**Реально встречавшиеся scope'ы** — это подсистемы, а не каталоги:

| scope | Раз | Что покрывает |
|---|---|---|
| `pipeline` | 9 | внешние источники и окружение: DAZ/VaM/Sims4, ComfyUI, `vn pipeline doctor\|models` |
| `ui` | 6 | `game/framework/20_ui/**`, токены, экраны, генерируемые панели |
| `release` | 3 | флейворы, гейт, `vn release *` |
| `ci` | 2 | `.github/workflows/**` |
| `lint` | 2 | правила `tools/vn/src/vn/content/lint.py` |
| `licenses` | 2 | `content/licenses.yaml`, third-party notices |
| `gallery`, `achievements`, `compile`, `doctor`, `provenance`, `qa`, `runtime`, `video` | по 1 | соответствующая подсистема |

Скоуп опускается, когда правка не привязана к подсистеме (`test:`) или является релизом (`release:`).

**Тело коммита** (все 35 конвенциональных коммитов имеют непустое тело):

- по-русски, объясняет **почему**, а не пересказывает диф;
- маркированные списки по разрезам («Данные:», «UI:», «Валидация:», «QA:»);
- ссылки на нормы и решения: `(ADR-0010)`, `(G6)`, `(раздел 7)`;
- если чинится инцидент — прямо сказано, что сломалось и как проверено (`ff28ba9` — эталон: симптом `FreetypeError`, причина, две линии защиты, как проверено на артефакте);
- **обязательный трейлер `Co-Authored-By:`** — он есть в 51 коммите из 51.

---

## 3. Ветки, теги, релиз

**Факт на 2026-08-08:** одна ветка `main` (+ `origin/main` на `github.com/Onemyname/renpy`, приватный), 51 коммит, **ноль merge-коммитов** (`git log --merges` пуст), история линейная. Тегов четыре: `v0.1.0`, `v0.1.2`, `v0.1.3`, `v0.1.4`. `v0.1.1` отсутствует — сборка 0.1.1 оказалась нерабочей (LFS-указатели вместо шрифтов), см. `../CHANGELOG.md:20-24` и коммит `ff28ba9`.

Работа идёт прямо в `main` — это осознанное состояние соло-разработки, а не недосмотр.

**Правило, когда всё-таки нужна ветка + PR.** Оно следует из устройства CI, а не из вкуса:

- `ci.yml` триггерится на `push` в `main` **и на любой `pull_request`** (`ci.yml:7-10`) — PR получает ровно те же проверки, что и main. Ветка ничего не теряет и ничего не стоит.
- `release.yml` триггерится тегом `v*`, и **первым шагом** сверяет тег с `project.yaml` (`release.yml:44-51`): `TAG="${GITHUB_REF_NAME#v}"` против `yaml.safe_load(open('project.yaml'))['version']`, при расхождении — `::error::тег v$TAG != project.yaml version $VER` и `exit 1`.
- Значит, откат «плохого» коммита в `main` — это ещё один коммит в истории, поверх которого придётся тегировать. В ветке откат = «не мержить».

Практический критерий: **ветка + PR** для правок в `tools/vn/`, `tools/schemas/`, `game/framework/00_core/`, `content/migrations/`, `save_schema`, workflow-файлов — то есть всего, что ломается не у вас, а у игрока или у CI. Правки контента в главе со `status: draft` — можно прямо в `main`, граф-проверки для `draft` понижены до warning (G15).

### Ритуал релиза — как он реально выполнялся

Релизный коммит `dd1cb3e` (0.1.4) и `9e1170c` (0.1.3) трогают **ровно три файла**: `project.yaml`, `docs/CHANGELOG.md`, `ci/release-manifest.json`.

```bash
vn release changelog                       # обновит ci/release-manifest.json (+ CHANGELOG, если менялись главы/сцены)
#  вручную: дописать в docs/CHANGELOG.md 2-5 предложений для игрока
#  вручную: бампнуть version в project.yaml (semver: патч — фиксы, НОВАЯ ГЛАВА = minor, мажор — сезон)
vn release validate --flavor public        # 19 проверок, локально, до тега
vn release validate --flavor patron
git commit -m "release: 0.1.5 — <итог одной строкой>"
git tag v0.1.5 && git push --follow-tags   # -> release.yml
```

Подробности гейта, флейворов и дистрибутивов — [29-build-and-release.md](29-build-and-release.md), паков — [30-packs-and-dlc.md](30-packs-and-dlc.md).

**Грабля:** pre-release-теги невозможны. Схема `project@1` требует `version` строго `^\d+\.\d+\.\d+$`, а гейт тега требует точного совпадения — `v1.0.0-rc1` не пройдёт ни там, ни там. Бета-канал из `../ARCHITECTURE.md` сегодня непредставим — NOT IMPLEMENTED.

---

## 4. Что проверяет CI

**Два конфига, авторитетный один.** Живой пайплайн — GitHub Actions: 4 workflow, **7 определений джоб** (`lint`, `build-test`, `smoke`, `fresh-renpy`, `build`, `dmg`, `publish`); на теге релизная `build` разворачивается матрицей `flavor: [public, patron]` в 2 прогона, то есть максимум 8 реальных прогонов. `.gitlab-ci.yml` — исторический, не в паритете (см. долг в конце раздела). Общее для всех GitHub-workflow: `actions/checkout@v4` с `with: {lfs: true}` (без него шрифты приезжают 131-байтовыми указателями и игра падает `FreetypeError` — это и был инцидент 0.1.1), Python 3.12, установка тулчейна **двумя шагами** — сначала `pip install --quiet -r tools/vn.lock` (точные версии, G17), затем `pip install --quiet -e "tools/vn[dev]"` (его `>=`-диапазоны уже удовлетворены локом, так что pip ничего не поднимает), `SDL_AUDIODRIVER: dummy`, `PYTHONIOENCODING: utf-8`, SDK 8.5.3 из кэша `actions/cache` по ключу `renpy-sdk-8.5.3-linux`, движок под `xvfb-run -a`.

### `ci.yml` — на каждый push в `main` и на каждый PR — IMPLEMENTED

| Джоба | Шаг | Падает, если |
|---|---|---|
| `lint` | `vn content lint` (`ci.yml:32`) | любая ошибка линта контента |
| `build-test` (needs `lint`) | `xvfb-run -a vn build` (`:67`) | lint, несобираемые ассеты, компилятор, битая разметка PO, бюджеты G19 |
| | `xvfb-run -a vn loc keys --check` (`:70`) | в авторском `.rpy` есть say/menu без id или ledger устарел (G8) |
| | `xvfb-run -a bash "$RENPY_SDK/renpy.sh" . lint` (`:73`) | движковый lint по `framework/` и генерату |
| | `xvfb-run -a vn content compile --check` (`:76`) | генерат не соответствует `content/` |
| | `xvfb-run -a python -m pytest tools/vn/tests -q` (`:79`) | любой из тестов `tools/vn/tests` |
| | `upload-artifact generated-<sha>` (`:81-86`) | — (аварийный режим G4, хранится 30 дней) |

`ffmpeg` в `ci.yml` ставится только в `build-test` (`:49`) — джобе `lint` он не нужен, она не собирает ассеты. **Чего `ci.yml` НЕ проверяет:** smoke-автопилот, сейв-корпус, релизный гейт, флейворы, бюджет `cold_start_s` (он живёт только внутри `vn test smoke`).

### `nightly.yml` — cron `30 2 * * *` + `workflow_dispatch` — IMPLEMENTED

Одна джоба `smoke`:

| Блок | Команды | Смысл |
|---|---|---|
| сборка | `vn build`; `vn loc import`; `vn loc report` (`:49-53`) | переводы генерируются из PO |
| smoke-матрица | `vn test smoke --picks 0,0`; `--picks 0,1 --lang en`; `--picks 1`; `--picks 0,0 --lang pseudo` (`:55-60`) | ветки × языки; здесь же гейт `cold_start_s: 30` |
| сейвы | `vn save check`; `vn save corpus` (`:62-65`) | загрузка фикстур в реальном движке, G5/G6 |
| релизный dry-run | `rm -rf game/generated`, затем `vn release build --flavor public` и `--flavor patron` (`:70-74`) | ловит регрессию «гейт требует генерат, которого в свежем чекауте нет» |
| артефакт | `.vncache/smoke/` при `if: always()` (`:76-82`) | скриншоты прогона, 7 дней |

**Долг закрыт:** nightly ставил только `xvfb libgl1` и падал бы `VideoError` на сырцах `assets_src/video_src/` — теперь ставит `ffmpeg` тем же шагом, что и `ci.yml` (`nightly.yml:32`). Инвариант «джоба зовёт `vn build` ⇒ раньше поставлен `ffmpeg`» держится тестом `tools/vn/tests/test_ci_config.py`.

### `canary.yml` — cron `0 3 * * 1` (понедельник) + dispatch — IMPLEMENTED

Скачивает **самый свежий** Ren'Py с `renpy.org/latest.html` (grep по `/dl/X.Y.Z/`), подменяет `RENPY_SDK` через `$GITHUB_ENV`, гоняет `vn build` → `renpy.sh . lint` → `pytest` → `vn test smoke --picks 0,0` (`canary.yml:35-51`). Смысл: расхождения с пиннованным SDK всплывают по одному в неделю, а не скопом в момент вынужденного апгрейда (G18). Отсюда же требование к установке: canary варьирует **только** версию Ren'Py, поэтому питоновский тулчейн берётся из `tools/vn.lock` (`:30`) — иначе красноту нельзя было бы приписать движку. `ffmpeg` (`:33`) обязателен по той же причине, что и в `ci.yml`. **`continue-on-error` нет** — красный canary валит workflow; это строже, чем `allow_failure: true` из `../ARCHITECTURE.md`, и это осознанное расхождение.

### `release.yml` — на тег `v*` — IMPLEMENTED

| Джоба | Что делает | Падает, если |
|---|---|---|
| `build` (matrix `flavor: [public, patron]`, `fail-fast: false`) | гейт тега (`:47-54`); кэш SDK; кэш `build/rpyc-cache` **отдельно на флейвор** (`key: rpyc-<flavor>-<ref>`, `:71-76`); `vn release build --flavor <f> --package win --package linux --package mac --timeout 1800`, для `patron` добавляется `--patron-token` из `secrets.PATRON_TOKEN` (`:78-87`) | тег ≠ `project.yaml version`; любой FAIL из 19 проверок гейта |
| `dmg` (needs `build`, `macos-latest`) | из артефакта `dist-public` берёт `*-mac.zip` → `hdiutil create … -format UDZO` (`:95-115`) | mac-zip или `.app` не найден |
| `publish` (needs `build`, `dmg`) | `gh release create "$GITHUB_REF_NAME" … --generate-notes --verify-tag` (`:117-135`) | — |

**Patron-артефакт в публичный релиз не уходит:** в GitHub Release попадают только `dist-public` + dmg; `dist-patron` остаётся артефактом workflow на 7 дней для ручной раздачи по каналам.

### Долг: `.gitlab-ci.yml` — PARTIAL / STALE

Три джобы: `lint` (`vn content lint`), `build` (`vn build` + `renpy.sh . lint`, артефакт `game/generated/` на 30 дней), `test` (`vn content compile --check` + `pytest`). По сравнению с GitHub здесь **нет**: релиза и флейворов, `vn loc keys --check`, обработки LFS (тот самый класс поломки, что убил 0.1.1), `ffmpeg`, smoke-автопилота, сейв-корпуса, canary, кэша `.rpyc`. Единственное, что подтянуто к паритету, — установка из `tools/vn.lock` перед editable (`:23-24` и `:37-38`): пин тулчейна по G17 держится во всех пяти пайплайнах, чтобы «откат = revert одного файла» не зависело от того, где именно прогон. `ffmpeg` сюда **не добавлялся сознательно**: без LFS этот конфиг всё равно упадёт раньше, на шрифтах, — чинить его по одной строке бессмысленно, решение долга целиком ниже.

При этом `../../ci/README.md:6` до сих пор называет `.gitlab-ci.yml` «конфигом пайплайна» и обещает, что «перенос на GitHub Actions = те же четыре команды» — это уже неправда: GitHub-ветка живёт, богаче и авторитетна. `../../CODEOWNERS:23` покрывает `/.gitlab-ci.yml` и **не покрывает `/.github/`**. Решение долга (паритет либо удаление + правка `ci/README.md` и `CODEOWNERS`) — [37-roadmap.md](37-roadmap.md).

---

## 5. Pre-commit и pre-push чеклисты

**Автоматики нет.** `ARCHITECTURE.md:659` требует pre-commit-хук, отклоняющий staged-файлы под `game/generated/`, `game/assets/`, `game/tl/` — **NOT IMPLEMENTED**: в `.git/hooks/` лежат только четыре стандартных хука git-lfs (`post-checkout`, `post-commit`, `post-merge`, `pre-push`), проектных хуков нет, конфигов вида `.pre-commit-config.yaml` нет. Единственная защита — `.gitignore:1-14`, и её достаточно: попасть в индекс генерат может только через `git add -f`.

**Pre-commit, минимум (5-10 с) — после любой правки:**

```bash
vn content lint            # 34 правила: схемы, именование, exits, граф, бюджет бинарей ADR-0004
git status --short         # ничего из game/generated|assets|tl; если есть — вы делали git add -f
```

**Pre-commit, полный (около минуты) — зеркалит `ci.yml`, гоняем перед push:**

```bash
vn build                                  # lint -> ассеты -> компилятор -> vn loc import -> бюджеты G19
vn loc keys --check                       # say-id и ledger свежи (G8)
xvfb-run -a bash "$RENPY_SDK/renpy.sh" . lint   # Linux; на Windows исполняемый файл — renpy.exe (cli.py:194-198)
vn content compile --check                # генерат свеж, без записи
python -m pytest tools/vn/tests -q        # 138 тестов, ~9 с
```

**Pre-push, если трогали рантайм, сейвы, локализацию или релизный путь** — то, что `ci.yml` не гоняет вообще:

```bash
vn test smoke --picks 0,0                 # прохождение в реальном движке + гейт cold_start_s
vn save check                             # фикстуры читаются, vn_save_schema на месте
vn save corpus                            # реальная загрузка сейва + миграции в after_load
vn release validate --flavor public       # 19 проверок релизного гейта
```

Разбор самих проверок — [27-testing.md](27-testing.md); что делать с падением — [28-debugging.md](28-debugging.md).

**Про `vn build` vs `vn build --check`:** `--check` ничего не пишет и дополнительно валидирует разметку PO (`cli.py:133-141`) — то, на чём полный build упал бы позже, на импорте `tl`. Полный `vn build` пишет генерат и делает `vn loc import`. CI использует **обе** формы: сначала пишущий `vn build`, потом `vn content compile --check`.

---

## 6. Красный CI — что делать

Порядок из `../runbooks/pipeline-broken-at-night.md` плюс то, что подтверждено кодом:

1. **Прочитать, какая джоба и какой шаг.** Сообщения `vn` всегда осмысленные: exit 1 всегда сопровождается строкой `ошибка: …` на stderr, голого трейсбека не бывает — даже внутренняя ошибка компилятора оборачивается (`cli.py:22-24`, `cli.py:119-123`). Коды: `0` успех, `1` ошибка проверки/сборки, `2` usage error (click), `3` «команда появится в фазе N».
2. **Воспроизвести локально ровно той же командой** из workflow. Разницы окружений быть не должно, но воспроизводится она только парой шагов: `pip install -r tools/vn.lock`, затем `pip install -e "tools/vn[dev]"` — CI ставит именно так, и одна editable-установка даст вам другие версии пакетов.
3. **«CI красный, локально зелёно»** → `git stash -u`, затем `vn content lint` на чистом чекауте. Незакоммиченные локальные файлы регулярно «чинят» сборку невидимо.
4. **`FreetypeError` / шрифты** → LFS: локально `git lfs install && git lfs pull`; в workflow — `with: {lfs: true}`. Проверка есть и в `vn doctor`, и в релизном гейте: она смотрит **содержимое** файла, а не расширение.
5. **`vn build` падает у всех** → сначала `vn doctor` (окружение, не код). Runbook предлагает откат тулчейна через `git revert` бампа `tools/vn.lock` — **и это работает**: все семь мест установки в пяти пайплайнах (`ci.yml` ×2, `nightly.yml`, `canary.yml`, `release.yml`, `.gitlab-ci.yml` ×2) ставят лок первым шагом, editable следом уже ничего не поднимает. Ограничение честное: лок содержит 18 прямых пинов, транзитивные зависимости `pytest` (`pygments`) в нём не закреплены — полной герметичности нет, откат гарантирован только по перечисленным пакетам. Норма G17 «откат = revert одного файла» — IMPLEMENTED для тулчейна `vn`.
6. **Аварийный обход:** скачать артефакт `generated-<sha>` джобы `build-test` (30 дней) и распаковать в `game/generated/` — игра запустится без локальной компиляции. `vn build --use-artifact <sha>`, обещанный в runbook и упомянутый в `ARCHITECTURE.md` 14 раз, **NOT IMPLEMENTED** — во всём тулчейне строка `use-artifact` встречается один раз, в заголовке схемы `tools/schemas/gen_manifest@1.schema.json`. Только руками.
7. **Хотфиксы поверх непонятного пайплайна запрещены** (runbook:22-23). Если причина — архитектурная норма, после инцидента пишется ADR в `../adr/`.

Справочник конкретных симптомов — [36-troubleshooting.md](36-troubleshooting.md).

---

## 7. CODEOWNERS и ревью — PARTIAL

`../../CODEOWNERS` — 19 правил, шапка честно помечает состояние: «TODO(команда): заменить плейсхолдеры на реальные хэндлы при найме» (`CODEOWNERS:3`).

- **Все хэндлы — плейсхолдеры** (`@tech-lead`, `@engine-dev-1`, `@engine-dev-2`, `@lead-writer`, `@art-director`, `@loc-lead`). GitHub не может назначить по ним ревьюера: сегодня файл — **карта ответственности за зоны**, а не работающий механизм ревью.
- Норма G20 «≥2 владельца на инструмент» выполнена текстуально для покрытых зон.
- **Не покрыто вовсе** (реальный долг): `/content/gallery/`, `/content/achievements/`, `/content/ui/`, `/content/licenses.yaml`, `/packs/`, `/assets_src/`, `/game/fonts/`, **`/.github/`** и `/docs/` целиком, кроме `conventions/` и `adr/`. То есть релизный workflow, паки и все сырцы формально ничьи.
- Правило «одна глава = одна папка = один владелец» существует только закомментированным образцом (`CODEOWNERS:25-26`) — строку на новую главу добавляют руками, см. [09-chapters.md](09-chapters.md).

**Что делать при найме:** одним PR заменить плейсхолдеры и добавить непокрытые зоны, затем включить branch protection на `main` с required review — механика `ci.yml` для этого уже готова (триггер на `pull_request` есть).

---

## 8. Производные зоны: что нельзя коммитить и нельзя править

| Зона | Кто её создаёт | В git | `.gitignore` |
|---|---|---|---|
| `game/generated/` | `vn build` / `vn content compile` | нет | `:2` |
| `game/assets/` | `vn assets build` | нет | `:3` |
| `game/tl/` | `vn loc import` | нет | `:4` |
| `game/cache/`, `game/saves/` | движок | нет | `:5-6` |
| `game/build_id.json` | `vn release build`, только на время distribute | нет | `:8` |
| `*.rpyc`, `*.rpymc`, `*.rpyb` | движок | нет | `:9-11` |
| `build/`, `.vncache/` | `vn package`/`release`/`pack`, тулинг | нет | `:20-21` |

**Единственное исключение** — каталог `ci/fixtures/rpyc-line/` (негативное правило `!ci/fixtures/rpyc-line/**` в `.gitignore:14`): 34 `.rpyc` в git, это линия statement-имён для сейв-корпуса (G6). Не удалять, не «чистить», не пересобирать руками — ими управляют `_rpyc_line_restore`/`_rpyc_line_snapshot` (`cli.py:1130-1164`).

Правка файла в производной зоне бесполезна дважды: она не попадёт в git **и** будет перезаписана ближайшей сборкой. Ошибку, найденную в `game/generated/scenes/ch01/ch01_s020.gen.rpy`, чинят в `content/`, в `tools/vn/src/vn/content/compile.py` или в `game/framework/` — и только там.

---

## 9. Как обновлять `docs/CHANGELOG.md` — PARTIAL

Команда: `vn release changelog` (`cli.py:1471-1489` → `release.update_changelog`, `release.py:141-178`).

1. Снимок `content/chapters/` — **только его** — в вид `{ch_id: {status, scenes[]}}`.
2. Дифф против `ci/release-manifest.json` (предыдущее состояние).
3. Если появились/исчезли главы или сцены — блок вставляется сразу после первой строки `../CHANGELOG.md`:

```markdown
## 0.1.0

Новые главы: ch01
Новые сцены (3): ch01_s010, ch01_s020, ch01_s030
```

4. `ci/release-manifest.json` перезаписывается версией из `project.yaml`.
5. `stamp_id_registry` дописывает id в `content/registry/id_registry.json` — **только для глав со `status: release`**. `ch01` сейчас `draft`, поэтому реестр состоит из пустых массивов и страховка G7 инертна.

**Реальность:** сгенерирован ровно один блок — `## 0.1.0` (`../CHANGELOG.md:36-39`). Записи 0.1.1–0.1.4 написаны руками прозой для игрока, и это правильно: генератор умеет говорить только про главы и сцены, а релизы 0.1.1–0.1.4 несли UI, галерею и фиксы. Утверждение `ARCHITECTURE.md:3785` «никто не пишет changelog руками» на практике не выполняется.

**Ограничения (NOT IMPLEMENTED):** нет `--from <tag>`, нет `--audience player|internal`, нет диффа между git-тегами. `snapshot_content` не заглядывает в `packs/*/chapters/` — глава `ch90` из пака `ep_beach` **никогда** не попадёт ни в `release-manifest.json`, ни в сгенерированный блок changelog. Для паков описание пишется руками.

**Порядок действий:** сначала `vn release changelog`, потом дописывайте прозу — иначе ваш текст окажется ниже сгенерированного блока той же версии.

---

## 10. Работа через AI-агента

Агент работает в этом же цикле и по этим же командам — отличие в том, что **проверки для него обязательны, а не по вкусу**: правка декларации без `vn build` молча оставляет генерат несвежим, и это всплывёт у следующего человека, а не у агента. Минимальный хвост любой задачи агента: `vn content lint` → `vn build` → `python -m pytest tools/vn/tests -q`.

Самая частая ошибка агента именно в этом репозитории — «поправить `game/generated/*.gen.rpy`, там же видно ошибку»: файл не в git и будет перезаписан (§8). Вторая — придумать несуществующий флаг (`vn build --use-artifact`, `vn validate`, `vn content lint --strict`); проверяйте по `vn --help` и по `cli.py`, а не по `ARCHITECTURE.md`, который является целевым документом.

Коммиты агента — в том же формате `type(scope):` с трейлером `Co-Authored-By:` (§2). Подробности: [34-ai-vibe-coding.md](34-ai-vibe-coding.md), [35-agent-rules.md](35-agent-rules.md).

---

## Как изменить / Как расширить

- **Добавить проверку в CI.** Сначала команда в `vn` (правило проекта: логика — в CLI, конфиг тонкий, `ci.yml:1-2`), затем шаг в `.github/workflows/ci.yml`. Логику в YAML не писать — её нельзя воспроизвести локально.
- **Ускорить локальную итерацию.** `vn build --profile draft` или `vn dev` (там `draft` уже по умолчанию). Помнить про качество: draft — это WebP q50 и видео `crf 42` в 720p.
- **Завести PR-процесс.** Настраивать нечего: `ci.yml` уже триггерится на `pull_request`. Нужны только реальные хэндлы в `CODEOWNERS` и branch protection на `main`.
- **Ввести watch для `packs/`.** Корни зашиты в `devloop.py:33-34` — добавляется одной строкой в список; отдельно решить, чем перестраивать пак (`vn build` собирает паки в общий генерат).
- **Починить `vn assets watch`.** Заменить `lambda: None` (`cli.py:566`) на реальный колбэк компиляции — или удалить команду в пользу `vn dev`.
- **Ввести pre-commit-хук из `ARCHITECTURE.md:659`.** Скрипт в `tools/` + `git config core.hooksPath`; учитывая, что `.gitignore` уже закрывает три производные зоны, приоритет низкий.
- **Закрыть долг GitLab.** Либо паритет с GitHub, либо `git rm .gitlab-ci.yml` + правка `ci/README.md:6` и `CODEOWNERS:23`.

## Чего НЕ делать

- **Не править `game/generated/`, `game/assets/`, `game/tl/`** — правка не попадёт в git и умрёт при первой сборке.
- **Не удалять `ci/fixtures/rpyc-line/`** как «мусорные `.rpyc`» — это единственные `.rpyc` в git, без них сейв-корпус перестанет быть детерминированным (G6).
- **Не ставить тег, не бампнув `project.yaml`** — `release.yml:44-51` упадёт на первом шаге, ещё до сборки.
- **Не пытаться выпустить `v1.0.0-rc1`** — схема `project@1` запрещает pre-release-суффикс в `version`.
- **Не полагаться на `vn assets watch` при работе с контентом** — события `content/` он выбрасывает (`cli.py:566`).
- **Не ставить тулчейн одной командой `pip install -e "tools/vn[dev]"`** — так вы отрезолвите свободные `>=` из `pyproject.toml` и получите не то окружение, что в CI. Сначала `pip install -r tools/vn.lock`, потом editable — порядок обязателен, обратный лок не применит.
- **Не рассчитывать на `vn build --use-artifact <sha>`, `vn validate`, `vn content lint --strict`** — этих команд не существует, `vn` ответит usage error (exit 2).
- **Не забывать `export RENPY_SDK=...`** в bash-сессиях: переменная не наследуется, а `vn doctor` при наличии `content/chapters/ch*` считает отсутствие SDK жёсткой ошибкой.
- **Не запускать `vn test smoke` параллельно со своей игрой** — автопилот пишет во временный `game/generated/qa/autopilot.gen.rpy` и убивает дерево процессов по таймауту.
- **Не редактировать `docs/CHANGELOG.md` до `vn release changelog`** — генератор вставит свой блок выше вашего текста.

## Проверка

```bash
# Цикл цел: окружение -> сборка -> свежесть -> тесты
vn doctor                                 # ожидается 8 PASS, 0 FAIL
vn build                                  # build: OK
vn content lint                           # lint: OK (N предупреждений)
vn content compile --check                # check: генерат свеж
vn loc keys --check
python -m pytest tools/vn/tests -q        # 138 passed

# Релизный путь цел (то, что ci.yml не гоняет)
vn test smoke --picks 0,0                 # RESULT.txt = OK: vn_end_of_content
vn save check && vn save corpus
vn release validate --flavor public       # 16 PASS, exit 0
vn release validate --flavor patron

# Гигиена git
git status --short                        # чисто; производных зон нет
git log --oneline -5                      # заголовки в формате type(scope): ...
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `../../tools/vn/src/vn/cli.py` (команды и их флаги — источник истины, не `ARCHITECTURE.md`), `../../tools/vn/src/vn/devloop.py`, `../../.github/workflows/ci.yml`, `../../.github/workflows/release.yml`, `../../CODEOWNERS`, `../../.gitignore` |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `game/build_id.json`, `build/**`, `.vncache/**` — производные зоны; `ci/fixtures/rpyc-line/**` — линия statement-имён (G6), управляется только через `vn save corpus` |
| **Зависимости** | правка `content/**` → несвежий генерат → красный `vn content compile --check` в CI; правка `tools/vn/**` → pytest + все команды; правка workflow → релиз; бамп `project.yaml: version` без тега (и наоборот) → падение `release.yml:44-51`; правка `renpy_sdk` → руками синхронизировать `RENPY_VERSION` в `ci.yml:13`, `nightly.yml:12`, `release.yml:19` (автопроверки согласованности НЕТ) |
| **Валидация** | `vn content lint && vn build && vn content compile --check && python -m pytest tools/vn/tests -q`; для рантайма/сейвов дополнительно `vn test smoke --picks 0,0` и `vn save corpus` |
| **Частые ошибки** | 1) правка генерата вместо источника; 2) выдуманные флаги (`--use-artifact`, `vn validate`, `--strict`) — их нет, exit 2; 3) забытый `export RENPY_SDK` в bash → «Ren'Py SDK не найден»; 4) тег без бампа `project.yaml`; 5) `vn assets watch` вместо `vn dev` при правке контента; 6) коммит без трейлера `Co-Authored-By:` и без `type(scope):` — расходится со всеми 51 коммитами истории |
