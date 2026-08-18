# 27. Тестирование: уровни проверок, smoke-автопилот, сейв-корпус, чеклисты

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — 253 pytest-теста, автопилот в реальном движке и сейв-корпус работают и гоняются в GitHub Actions; сейв-корпус с 2026-08-08 проверяет **реальную миграцию** (2 фикстуры, вторая на старой схеме). **Но** `cli.py` (1643 строки) покрыт одной командой из ~50 (`pack build`), а `vn test replay|screens|paths` — заглушки.
> **Отвечает на вопрос:** «Что запустить, чтобы убедиться, что я не сломал игру — в каком порядке, что каждая команда ловит и чего не ловит».

Тестов у проекта два сорта: обычный pytest над Python-тулингом (`tools/vn/tests/`, 24 файла) и прогон **настоящей игры** автопилотом внутри её собственного процесса (`vn test smoke`, `vn save corpus`). Рантайм Ren'Py питоном не тестируется — до `game/framework/**` не дотягивается ни один pytest (единственная его проверка — smoke-прогон), исключение одно и статическое: `test_crash_handler.py` читает исходники `game/framework/**` регексом. Чеклисты (§9) — главный практический раздел этого файла.

## Быстрый ответ

Семь уровней, от самого быстрого к самому медленному. Первые три — обязательный минимум перед push.

```bash
vn content lint                          # 1. ~1 с, SDK не нужен: схемы, именование, граф, достижимость
python -m pytest tools/vn/tests -q       # 2. 253 теста
vn build --check                         # 3. свежесть генерата и ассетов, разметка PO, бюджеты G19
bash "$RENPY_SDK/renpy.sh" . lint        # 4. движковый lint (Windows: "$RENPY_SDK/renpy.exe" . lint)
vn test smoke --picks 0,0                # 5. автопрохождение в реальном движке (~10-20 с)
vn save check && vn save corpus          # 6. 2 фикстуры сейвов + реально исполняемая миграция
vn release validate --flavor public      # 7. релизный гейт, 19 проверок PASS/WARN/FAIL
```

Уровни 4-7 требуют `RENPY_SDK`. **Грабля:** в bash-сессиях агента переменная не наследуется — экспортируйте вручную:
`export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`.

---

## 1. Инвентарь тестов — IMPLEMENTED

**24 файла `test_*.py` + `conftest.py`, 253 тестовые функции** (проверено `grep -h '^def test_' tools/vn/tests/*.py | wc -l` → 253). Все тесты лежат плоско в одной директории, тестовых классов нет.

| Файл | Тестов | Что покрывает | Заметные фикстуры и механики |
|---|---|---|---|
| `test_loc.py` | 25 | `vn.loc.po` + `vn.loc.keys`: дискавери пакетов языков (ADR-0005), PO round-trip, fuzzy при смене исходника, псевдолокаль, `game/tl/<code>/language.json`, валидация разметки, orphan-сверка ledger | Локальный `_mk_loc_root(tmp_path)` строит синтетический репозиторий; реальный `polib`. Единственный e2e-тест (`:392`) **мутирует настоящий `loc/ledger/ch01.json`** и восстанавливает его в `finally` |
| `test_lint.py` | 16 | `vn.content.lint.lint` + `vn.release.stamp_id_registry`: чистый репозиторий, битые пакеты языков, осиротевшие пары сцен, downgrade ошибок на `draft`, исчезновение выпущенных id, исключение по `renames`, недостижимость и тупики, бинарный бюджет ADR-0004 | `_copy_skeleton()` копирует скелет без глав; `_mk_chapter()` строит главы с произвольным графом exits. `test_lint_clean_repo` линтует **живой репозиторий** |
| `test_scene_pipeline.py` | 24 | `vn.content.scenes`: контракт меток, запрет межсценовых jump, соответствие `return` ↔ `exits`, Variable Registry, эмиссия обвязки, фоны локаций | `_unit()`/`_analysis()` фабрикуют `SceneUnit` и результат парсера — SDK не нужен. e2e-компиляция демо-главы — `skipif` без `RENPY_SDK` (`:332`) |
| `test_provenance.py` | 12 | `vn.assets.provenance` (извлечение параметров из PNG ComfyUI, `record`/`verify`, дедуп workflow), декларации DAZ/VaM/Sims4, композиция цепочки DAZ→AI | Константа `API_GRAPH` — реалистичный API-граф ComfyUI; `_comfy_png()` пишет PNG с чанком `prompt` |
| `test_gallery.py` | 13 | `_emit_gallery` (ADR-0010): форма реестра, разрешение превью, отсутствующий ассет, неизвестная категория, несоответствие kind/asset, существование якоря, дубликаты id | Заглушка `_Rep` с одним полем `.warnings`; `_mk_assets()` пишет однобайтовые файлы-пустышки. Компиляция реального реестра — `pytest.skip` без SDK (`:181`) |
| `test_verify_regressions.py` | 11 | Регрессии находок фазы 0: устойчивость lint к схемно-невалидным `exits`, отсутствующие входы компилятора, «`--check` ничего не пишет», shim-размотка, префикс `vn_` в persistent, схема gen-манифеста, `_lfs_pointer_fonts` | Свой `_copy_skeleton`. `assert len(res.stale) == 14` (`:84`) — хрупкая магическая константа |
| `test_assets.py` | 27 | `build_assets`: трансформации, кэш и восстановление `from_cache`, orphan-очистка, нарушения именования, `sprite_tree`, `emit_images`, `build_graph`; **`:52`** — ветка звука читает `assets_src/audio_stems/`; **`:69`** — манифест сборки проходит схему `assets_manifest@1` из реестра (G16) | `_png()` через Pillow; цвета намеренно разные, чтобы дедуп по content-hash не маскировал результат |
| `test_ui_panels.py` | 10 | `vn.assets.ui` (ADR-0009): парсинг hex/RGBA, геометрия `borders_of` (radius + blur + dy), 9-patch и альфа, градиент, `emit_frames`, инкрементальность по панели, orphan; **`:244`** — ни один потребитель `vn_frame_*` не меньше `2*Borders`; **`:284`** — вкладки и кнопки галереи сидят на панелях `chip`/`chip_active` (Borders 11, минимум 22×22), а не на `choice` (54-60 px) | Pillow читает пиксели рендера. `test_repo_panels_declaration_is_valid` проверяет живой `content/ui/panels.yaml` (сейчас **8 панелей**: 2026-08-08 добавлены `chip` и `chip_active`) |
| `test_ci_config.py` | 7 | Инварианты конфигов CI по YAML: набор workflow найден; `-r tools/vn.lock` стоит **до** editable-установки во всех 8 местах (G17); `ffmpeg` ставится до любого `vn build`/`vn release build`; видео-сырцы в `assets_src/video_src` на месте (иначе требование ffmpeg вырождается) | Свои парсеры `_github_jobs()`/`_gitlab_jobs()`: у GitLab разворачивается `extends` и `before_script` |
| `test_crash_handler.py` | 2 | Регрессия «мёртвый обработчик»: `config.exception_handler` присваивается **ровно один раз** и именно в `070_crash.rpy`; обработчик пишет строку `[vn] unhandled exception:` и возвращает `False` | Статический: рантайм Ren'Py в pytest недоступен, поэтому регекс по `game/framework/**/*.rpy` |
| `test_licenses.py` | 7 | `vn.assets.licenses`: загрузка реестра, блок `game_use: false`, гейт `nsfw_allowed`, warning про непокрытые декларации | Инлайн-константа `REGISTRY` на 3 ассета + проверка живого `content/licenses.yaml` |
| `test_video.py` | 9 | `vn.assets.video` и видеоветка `build_assets`: энкод VP9, `mov_meta@1`, детект шва лупа, инвалидация по sidecar `*.video.yaml`, нейминг, orphan, бюджеты/кодек | **Весь модуль `skipif` без ffmpeg/ffprobe** (`:13-16`). Сырцы синтезируются `ffmpeg -f lavfi`: `color=` — идеальный луп, `testsrc` — рваный |
| `test_release.py` | 13 | `vn.release`: конфиг флейвора, NSFW-глобы исключения, `build_info@2` write/validate/clear, видео-бюджеты, гейт LFS-указателей шрифтов; **`:79`** — `patron_tag` короткая, стабильная и **не равна токену** (ADR-0011); **`:149-192`** — три теста `vn pack build` через `CliRunner`; **`:233`** — `built_asset_ids` игнорирует производные (`@2`, `.thumb`, постеры); **`:250`** — гард-тест россыпи: `build.archive` в `game/options.rpy` запрещён (норма §2.4, `.rpa` — только mobile фазы 3 через ADR) | Инлайн `PROJECT`; `_run_pack_build()` (`:141-146`) = `CliRunner` + `monkeypatch.chdir`. `validate_release` **по-прежнему никогда не исполняется**: тесты гейта (`:195-230`) ассертят только `inspect.getsource(...)` |
| `test_saves.py` | 6 | Сейв-часть компилятора (G5): дыра в цепочке миграций, незарезервированный номер, несовпадение схемы, встраивание исходников `_emit_migrations`, пары стора в `_emit_snapshot`, рантайм-эквивалентное исполнение миграции | `_mk_migrations()` пишет `content/migrations/registry.yaml` + нумерованные `.py`; `_src_factory` подделывает колбэк хеша входов |
| `test_storage.py` | 5 | `vn.assets.storage` (G14/G21): push требует лока, round-trip lock→push→pull с иммутабельными версиями, чужой лок и `--force`, состояния `status`, честная заглушка s3 | `.vnstorage.yaml` в `tmp_path` с файловым бэкендом |
| `test_compile.py` | 7 | `compile_content`: набор выходов пустого проекта, идемпотентность, точечная очистка осиротевших `.rpy`+`.rpyc`, `CompileError` при главах без `RENPY_SDK` | `BASE_OUTPUTS` — замороженный набор из 16 имён (`:11-28`, включая `platform.gen.rpy` по ADR-0014); `monkeypatch.delenv("RENPY_SDK")` |
| `test_achievements.py` | 4 | `_emit_achievements` (`achievements@1`): значения по умолчанию, пустой реестр, правило `oneOf` (ровно один триггер), валидность живой декларации | Фабрика `_doc(**achievements)`; `pytest.skip`, если деклараций нет |
| `test_voice.py` | 13 | Голосовой контур (§4.9/C5): `vn.voice` — валидация манифестов против ledger (сироты в обе стороны, чужая глава), CSV-лист `manifest`, атомарный `import_takes`, маппинг дыр покрытия в FAIL релизного гейта, инжекция voice-операторов `_inject_voice`, транскод `voice_opus` и отбраковка путей вне конвенции | Транскод-тест скипается без ffmpeg (`:189`) |
| `test_shots.py` | 11 | Послойные шоты (shots@1, ADR-0013): сборка слоёв с вариантами, обязательность `env` и альфы, единый холст, эмиссия `layeredimage` (ошибка на несобранный вариант, warning на orphan-слой), атрибуты в индексе образов, учёт худшего шота моделью памяти, отказ компилятора на битой декларации | Tiny-профиль: экран 64×48, мастера 128×96 (`@2`) |
| `test_memory.py` | 5 | Модель памяти образов (ADR-0012): формулы движка дословно (лимит `mb*1024*1024//4`, стоимость `bbox*1.34`, bbox по альфе), worst-case сцены, ошибка при превышении бюджета, соответствие `render.gen.rpy` проекту | Сверено с `renpy/display/im.py` |
| `test_sources.py` | 8 | Единый контракт внешних источников (DAZ / VaM / Sims 4): скаффолд ↔ валидатор, id ↔ выход, заявленное разрешение ↔ файл, сквозная цепочка DAZ → Wan → игра, VaM `.var`-пакеты и кинематик-секвенции до сцены и галереи | Секвенция-тест требует ffmpeg (`:193`) |
| `test_schemas.py` | 3 | `SchemaRegistry`: имя файла ↔ `const`, `additionalProperties: false` у каждой схемы, валидность стартовых деклараций, ошибка на неизвестной схеме | Ассерты «не меньше»: `len(reg.schemas) >= 15`, `seen >= 10` |
| `test_engine_compat.py` | 5 | Контракт-тесты G18 против пиннованного SDK: существование `renpy.call_stack_depth`/`get_return_stack`, voice-стейтмент, `config.emphasize_audio_*`, **штатный Steam-стек** (`test_steam_engine_contract:62` — тихий no-op без steam_api, варианты `steam_deck`/`steam_big_picture`, `SteamBackend`, `dlc_installed`, `steam_init()` на `init -1499`; ADR-0014); равенство `VN_API_LEVEL` (тулинг) и `API_LEVEL` в `030_flow.rpy:9` | Маркер `requires_sdk` (`:11-14`) на четырёх из пяти. Тест про API_LEVEL SDK **не** требует — он регексом читает файл фреймворка |
| `test_platform.py` | 9 | Платформенный слой (ADR-0014): эмиттер `platform.gen.rpy` (Steam выключен без `appid`, карта `VN_STEAM_DLC` только из паков с `steam_dlc_appid`), рендер VDF из шаблона (`appid`/`SetLive`/депоты, warning на незаданный депот), обязательность `appid` и `depots`, распаковка зипов distribute под депоты и честные ошибки без дистрибутива, статус steam_api-библиотек; **`:107`** — гард-тест «слово Steam живёт только в `035_platform.rpy`» | `_steam_root()` строит синтетический репозиторий и копирует **живой** `ci/steam/app_build.vdf.tmpl`; SDK не нужен ни одному тесту |

`tools/vn/tests/conftest.py` — вся общая обвязка, 13 строк:

```python
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT
```

`sys.path`-инъекция `tools/vn/src` означает, что тесты импортируют `vn.*` **без установки пакета**. Часть файлов делает `from conftest import REPO_ROOT` напрямую (`test_gallery.py`, `test_licenses.py`, `test_release.py`, `test_provenance.py`, `test_ci_config.py`).

---

## 2. Как запускать pytest

```bash
python -m pytest tools/vn/tests -q          # из КОРНЯ репозитория
python -m pytest tools/vn/tests/test_lint.py -q          # один файл
python -m pytest tools/vn/tests -q -k gallery            # по имени
```

- **Запускать из корня.** `REPO_ROOT` вычисляется от файла теста (`conftest.py:7`), поэтому фикстура `repo_root` корректна из любого cwd, но сам путь `tools/vn/tests` относительный.
- **Установка не обязательна** для импортов, но зависимости нужны: `click, PyYAML, jsonschema, blake3, Pillow, psd-tools, polib` + `pytest>=8.0`. Канонично — `pip install -e "tools/vn[dev]"`, ровно как в CI.
- **Гейтинг по окружению.** Тихо скипаются на голой машине **18 тестов из 253**: `test_video.py` целиком (9, нужны `ffmpeg`+`ffprobe` в PATH), по одному ffmpeg-тесту в `test_voice.py:189` и `test_sources.py:193`, и 7 тестов под `RENPY_SDK` — четыре контракт-теста `test_engine_compat.py` (:25, :33, :55, :62 — последний это `test_steam_engine_contract`, ADR-0014) и по одному e2e в `test_scene_pipeline.py:332`, `test_gallery.py:181`, `test_loc.py:448` (нужен `RENPY_SDK` с `renpy.py` внутри). Проверено прогоном без SDK: `246 passed, 7 skipped`. Зелёный прогон без SDK и ffmpeg **не** означает, что путь через движок цел. Ни один из тестов, добавленных 2026-08-08 (`test_ci_config.py`, `test_crash_handler.py`, CLI-тесты `pack build`, ветка звука, схема манифеста, геометрия чипов), окружения не требует — они гоняются везде.
- **Нет `pytest.ini`, нет `[tool.pytest]`, нет зарегистрированных маркеров** — только инлайновые `pytest.mark.skipif` и модульный `pytestmark`. `-m <marker>` использовать не с чем.
- **Риск изоляции:** `test_loc.py:392-415` правит настоящий `loc/ledger/ch01.json` и откатывает его в `finally`. Прерванный по Ctrl+C прогон оставит рабочее дерево грязным — проверяйте `git status` после аварийной остановки.

---

## 3. Уровни проверок: что каждая ловит и чего не ловит

| № | Команда | Время | Нужен SDK | Ловит | НЕ ловит |
|---|---|---|---|---|---|
| 1 | `vn content lint` | ~1 с | нет | схемы деклараций, именование, обязательные файлы, граф сцен, недостижимость и тупики (серьёзность по `status`, G15), бинарный бюджет `assets_src/` | ничего внутри `.rpy`, ничего в рантайме, свежесть генерата |
| 2 | `python -m pytest tools/vn/tests -q` | секунды | частично | логику модулей `vn.*`; инварианты конфигов CI; единственность обработчика краха | `cli.py` кроме `pack build`, `analyze.py`, `scaffold.py`, `psd.py`, `devloop.py`, поведение `game/framework/**` в рантайме |
| 3 | `vn build --check` | секунды | да, если есть главы | несвежий генерат (побайтово), несвежие ассеты, ошибки разметки PO, бюджеты G19 | падения в рантайме, вёрстку экранов |
| 4 | `renpy.sh . lint` | ~10 с | да | движковые проблемы: неопределённые образы/метки, синтаксис `.rpy` во **всём** `game/` | логику ветвления, вёрстку, производительность |
| 5 | `vn test smoke` | 10-20 с локально | да | реальные падения (`traceback.txt`), недостижимую сцену (`FAIL: vn_scene_unavailable`), превышение `cold_start_s`, фактический путь по меню | ветки, которые вы не перечислили в `--picks`; вёрстку (кроме экранов из `VN_AUTOPILOT_SCREENS`) |
| 6 | `vn save check` + `vn save corpus` | секунды / ~40 с | corpus — да | битые фикстуры; поломку загрузки старого сейва; **исполнение миграции `0002`** на фикстуре `schema1-demo` | миграции, для которых нет фикстуры со «своей» исходной схемой (сейчас в корпусе только переход 1 → 2) |
| 7 | `vn release validate --flavor <f>` | ~10 с | да | 19 агрегированных проверок: схема `project.yaml`, флейвор, паки, lint, LFS-шрифты, свежесть ассетов и генерата, видео, бюджеты, провенанс, декларации DAZ/VaM/Sims4, покрытие переводов, лицензии, хранилище сырцов, версия манифеста, git sha, наличие фикстур (сейчас PASS: «сейв-корпус: 2 фикстур») | ничего нового: **своих правил у гейта нет**, он агрегирует существующие (`release.py:276-282`) |

### Где именно вызывается `renpy lint`

Важная деталь: **`vn` никогда не вызывает движковый `renpy lint` сам.** Во всём тулинге SDK-исполняемый файл запускается только для `vn play` (`cli.py:194-198`), `vn dev` (`cli.py:264`), `vn package` (`cli.py:337`), автопилота (`cli.py:1313`) и парсер-моста `vn_analyze` (`tools/vn/src/vn/content/analyze.py:31,57`). Движковый lint запускается **только из CI-конфигов**:

- `.github/workflows/ci.yml:73` — `xvfb-run -a bash "$RENPY_SDK/renpy.sh" . lint`
- `.github/workflows/canary.yml:49` — то же на свежайшем Ren'Py
- `.gitlab-ci.yml:47` — `xvfb-run -a "$RENPY_SDK/renpy.sh" . lint`

Локально его надо запускать руками. Ren'Py не имеет headless-режима (G23) — на Linux нужен `xvfb-run`, на Windows окно просто открывается и закрывается.

---

## 4. Smoke-автопилот — IMPLEMENTED

`vn test smoke` (`cli.py:1347-1401`) + `_autopilot_run` (`cli.py:1285-1344`) + рантайм `vn_qa` (`game/framework/00_core/030_flow.rpy:91-211`).

### 4.1. Механизм: прогон ВНУТРИ процесса игры

Никакого управления окном снаружи. Автопилот — это код, который на время прогона подкладывается в игру:

1. **Предусловия** (`cli.py:1293-1298`): `RENPY_SDK` резолвится, иначе `Ren'Py SDK не найден (RENPY_SDK) — vn doctor подскажет`; существует `game/generated/manifest.json`, иначе `game/generated/ пуст — сначала vn build`.
2. **Каталог артефактов вычищается и создаётся заново** (`cli.py:1300-1302`): `.vncache/smoke` для smoke, `.vncache/corpus` для корпуса.
3. **Инъекция кода** (`cli.py:1268-1282, 1305-1311`): `game/generated/qa/` полностью пересоздаётся, туда пишется временный `autopilot.gen.rpy`:

```renpy
label main_menu:
    if not vn_qa.autopilot_active():
        $ renpy.quit(save=False)   # осиротевший прогон-файл вне smoke: не играем сами с собой
    $ vn_qa.autopilot_boot()
    return

init python:
    if vn_qa.autopilot_active():
        config.overlay_screens.append("vn_autopilot")

screen vn_autopilot():
    timer 0.6 action Function(vn_qa.autopilot_tick) repeat True
```

   Две независимые страховки: пречистка `qa/` и env-гейт внутри самого файла — осиротевший `.rpyc` от жёстко убитого прогона без `VN_AUTOPILOT` мёртв.
4. **Запуск** (`cli.py:1313-1322`): `subprocess.Popen([<sdk>/renpy.exe|renpy.sh, <root>], env=…)`, на не-Windows — `start_new_session=True`. `traceback.txt` в корне удаляется заранее, поэтому его появление после прогона — надёжный признак падения.
5. **Уборка в `finally`** (`cli.py:1336-1343`): удаляются `autopilot.gen.rpy` и его `.rpyc`, затем `qa/` (best-effort `rmdir`).

Обратите внимание: `label main_menu` переопределяется целиком. В контексте главного меню Ren'Py оверлеи и таймеры не тикают — поэтому автопилот и не пытается «нажать Start», он делает `return` и передаёт управление обычному потоку.

### 4.2. Протокол переменных окружения

| Переменная | Кто ставит | Кто читает | Эффект |
|---|---|---|---|
| `VN_AUTOPILOT=1` | `cli.py:1314`, всегда | `030_flow.rpy:106-107` | Главный гейт: `autopilot_active()` — это буквально `"VN_AUTOPILOT" in os.environ` |
| `VN_AUTOPILOT_DIR` | `cli.py:1314`, всегда | `030_flow.rpy:112,144,172,190` | Каталог артефактов: `shot%03d.png`, `startup.txt`, `picks.log`, `screen_<name>.png`, `RESULT.txt`, `state.json`, `gallery.json` |
| `VN_AUTOPILOT_PICKS` | `--picks` (`cli.py:1370`); в `save corpus --add` захардкожено `"0,1"` (`cli.py:1191`) | `030_flow.rpy:137` | Индексы через запятую, **по одному на каждое встреченное меню** |
| `VN_AUTOPILOT_LANG` | `--lang` (`cli.py:1370`) | `030_flow.rpy:155-159` | `renpy.change_language(lang)`; маркер `"@source"` → `change_language(None)` |
| `VN_AUTOPILOT_SAVE_AT` | `save corpus --add`, захардкожено `"4"` (`cli.py:1191`) | `030_flow.rpy:124-127` | На этом тике вызывается `renpy.save("1-1")` |
| `VN_AUTOPILOT_LOAD` | прогон корпуса, `"1-1"` (`cli.py:1234`) | `030_flow.rpy:162-164` | `renpy.load(slot)` прямо из `autopilot_boot` |
| `VN_AUTOPILOT_SCREENS` | **ни один флаг CLI её не ставит** — только наследование из `os.environ` (`cli.py:1314`) | `030_flow.rpy:166-184` | Список экранов через запятую: `show_screen` → `renpy.pause(0.3)` → `screenshot` → `hide_screen` |

`VN_AUTOPILOT_SCREENS` и запись `gallery.json` — **IMPLEMENTED / UNDOCUMENTED**: кода нет ни в одном doc-файле, флага CLI не существует. Что механизм рабочий, доказывает `.vncache/smoke/screen_gallery.png` из прошлого прогона — переменная выставлялась снаружи. Чтобы снять экраны сегодня:

```bash
VN_AUTOPILOT_SCREENS=gallery,preferences vn test smoke --picks 0,0    # bash
$env:VN_AUTOPILOT_SCREENS="gallery,preferences"; vn test smoke --picks 0,0   # PowerShell
```

Тем же наследованием окружения (`cli.py:1538` — `env = dict(os.environ, VN_AUTOPILOT="1", …)`) до движка доезжает **`RENPY_VARIANT`** — единственный способ проверить controller-first вёрстку без железа (ADR-0014):

```bash
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0   # Deck: авто-масштаб 1.4, фуллскрин
RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0         # ТВ: оверлеи ушли на gui.overscan_pad
```

Чего этот прогон **не** проверяет: событий геймпада (автопилот их не шлёт), инициализации Steam, оверлея и `dlc_installed` — только вёрстку. Подробности — [39-platforms.md](39-platforms.md) §7.1.

### 4.3. Тайминги: продвижение, выбор, подтверждение

- **Продвижение диалога:** оверлей `vn_autopilot` дёргает `vn_qa.autopilot_tick` каждые **0.6 с**; тик делает скриншот и `renpy.queue_event("dismiss")` (`030_flow.rpy:109-128`).
- **Выбор в меню:** `game/framework/20_ui/screens/choice.rpy:53-54` — `timer 1.0 action Function(vn_qa.autopilot_choose, items) repeat True`. Именно таймер, а не выражение экрана: side effect в screen-выражении запрещён, потому что экран переоценивается предикцией и каждым тиком оверлея, и счётчик picks дрейфовал бы (`030_flow.rpy:131-133`).
- **Модальные подтверждения:** `game/framework/20_ui/screens/core_screens.rpy:403-404` — `timer 0.8 action yes_action repeat True`. Автопилот всегда отвечает «да».
- **Семантика picks** (`030_flow.rpy:134-143`): действуют только пункты с `action is not None`; кончились значения — берётся `0`; индекс больше числа пунктов — прижимается к последнему; если выбранный пункт заблокирован — берётся первый действующий.

### 4.4. ЖЕЛЕЗНОЕ ПРАВИЛО: `autopilot_choose` обязан вернуть `renpy.run(action)`

```python
        # ВАЖНО: значение action обязано вернуться из Function — интеракция меню
        # завершается только non-None результатом action (иначе вечное перевыбирание).
        return renpy.run(items[idx].action)
```

`030_flow.rpy:148-150`. Если убрать `return` — `Function(...)` вернёт `None`, интеракция меню не завершится, таймер выберет пункт снова и снова, и прогон повиснет до `--timeout`. Симптом в логе: `picks.log` растёт бесконечно, `RESULT.txt` не появляется. То же правило действует для любого нового автопилот-хука в экране с меню.

### 4.5. ЗАПРЕТ: синтетический ввод на рабочий стол

Автопилот работает **только внутри процесса игры** (`cli.py:1286-1287`: «Никакого синтетического ввода на рабочий стол — только in-process автоматизация»; `030_flow.rpy:103-105`). Никогда не добавляйте в тулинг `SendKeys`, `pyautogui`, `xdotool` и прочую эмуляцию клавиатуры/мыши по окну: такой «тест» кликает по случайному окну на машине владельца, зависит от фокуса и раскладки, не воспроизводится в CI и не даёт ни одного детерминированного артефакта. Всё, что нужно автоматизировать, добавляется как функция в `vn_qa` и дёргается из таймера экрана.

### 4.6. Артефакты прогона и вердикт

`autopilot_finish(reason)` (`030_flow.rpy:186-211`) пишет `RESULT.txt`, `state.json` (снапшот `vn_state`), `gallery.json` (`{unlocked, total, ids}` из `vn_gal`) и делает `renpy.quit(save=False)`. Вызывается из двух меток:

- `label vn_end_of_content` → сначала `autopilot_screens()`, затем `autopilot_finish("OK: vn_end_of_content")` (`030_flow.rpy:235-240`);
- `label vn_scene_unavailable` → `autopilot_finish("FAIL: vn_scene_unavailable")` (`030_flow.rpy:227-229`).

Реальное содержимое `.vncache/smoke/` от последнего прогона на машине владельца:

```
RESULT.txt    OK: vn_end_of_content
startup.txt   1.13                       ← cold start, секунды
picks.log     menu 0 -> pick 0 (ch01_s010_m001)
              menu 1 -> pick 1 (ch01_s020_m001)
state.json    {"ch01.PY2": false, "ch01.met_mira": true, "g.PY2": false,
               "g.route": "prologue", "vn_save_schema": 2}
gallery.json  {"unlocked": 4, "total": 5,
               "ids": ["cg_ch01_finale","cg_ch01_rooftop","mov_ch01_ambient","cg_ch01_concept"]}
shot000.png … shot020.png (21 кадр), screen_gallery.png
```

Логика вердикта (`cli.py:1372-1401`), по порядку:

1. Таймаут + есть `traceback.txt` → печатаются последние 1500 символов, `smoke: игра упала с traceback (и висела до таймаута)`.
2. Таймаут без traceback → `игра не завершилась за N c — прогон снят (дерево процессов убито)`.
3. Печатается число `shot*.png`.
4. Читается `startup.txt` как float и **сравнивается с `budgets.cold_start_s` из `project.yaml`** (сейчас `30`, норма G19). Превышение = exit 1. Комментарий в `project.yaml:9` калибрует ожидания: CI-раннер на llvmpipe ~14 с, RTX ~1 с.
5. Печатается каждая строка `picks.log` как `путь: …`.
6. Есть `traceback.txt` → fail.
7. `returncode != 0` или вердикт не начинается с `OK` → fail.

**Таймаут и убийство процесса** (`cli.py:1325-1335`): `--timeout` по умолчанию 180 с. На Windows — `taskkill /T /F /PID <pid>`, потому что `renpy.exe` это лаунчер и умереть должно всё дерево; на POSIX — `os.killpg(os.getpgid(pid), SIGKILL)`; затем `popen.wait(timeout=10)`.

### 4.7. `--lang`: защита от ложно-зелёного прогона

`cli.py:1354-1367`: если `--lang` совпадает с исходным языком (`source_language(root).code`), он подменяется маркером `"@source"` — `tl/<code>/` для исходного языка не существует по определению. Иначе требуется существующий `game/tl/<lang>/`, иначе команда падает: `языка … нет в game/tl/ — выполните vn loc import (change_language молча показал бы исходный язык — ложно-зелёный прогон)`. Про сам round-trip переводов — [14-localization.md](14-localization.md).

### 4.8. `.vncache/langqa/` — артефакт-сирота

В `.vncache/langqa/` лежат `01_prefs_ru.png … 04_prefs_ru_again.png` и `RESULT.txt` с содержимым `OK`. **Ни одна строка кода в репозитории этого не производит:** автопилот пишет только `shot%03d.png`/`screen_<name>.png` и `RESULT.txt` вида `OK: <причина>`, а `grep -rn langqa tools/ game/ docs/ .github/` даёт ноль. Это ручной артефакт разовой языковой проверки. Не ссылайтесь на него как на воспроизводимый прогон и не пытайтесь «починить» — воспроизвести его нечем.

---

## 5. Сейв-корпус — IMPLEMENTED, миграция проверяется по-настоящему

### 5.1. Зачем

Игрок ставит апдейт поверх своего прохождения. Сейв Ren'Py — это pickle состояния плюс ссылки на позиции скрипта; любая правка сцены, переименование метки или бамп `save_schema` могут сделать старый слот незагружаемым. Корпус — единственный автоматический ответ на вопрос «сейвы игроков переживут этот релиз?».

### 5.2. `vn save check` — офлайн, SDK не нужен

`cli.py:1099-1124`. Открывает каждый `ci/fixtures/saves/*.save` как zip, читает член `json`, требует целочисленный `vn_save_schema`, печатает схему / версию / сцену. **Без unpickle** — то есть работает даже если сейв не загружается движком. Эти три ключа кладёт `config.save_json_callbacks` (`game/framework/00_core/001_boot.rpy:31-36`).

```
$ vn save check
 ✓ schema1-demo.save: schema 1, версия 0.1.4+dd1cb3e, сцена ch01_s010
 ✓ schema2-demo.save: schema 2, версия 0.1.0+48d19a3, сцена ch01_s020
save check: OK (2 фикстур)
```

### 5.3. Линия statement-имён — почему 52 `.rpyc` лежат в git

Ren'Py адресует позиции скрипта **именами стейтментов**, которые выдаёт компилятор. Сейв валиден только против того `.rpyc`, с которым создавался: перекомпиляция чужим деревом выдаёт другие имена, и фикстура перестаёт грузиться. Решение проекта (`cli.py:1130-1134`) — держать «линию имён» в git:

```
ci/fixtures/rpyc-line/     52 файла .rpyc, 337 КБ
  framework/00_core/{001_boot,010_registry,020_state,030_flow,050_build_bridge}.rpyc
  framework/00_core/engine_compat/000_compat.rpyc
  framework/20_ui/{images,screens/choice,screens/core_screens}.rpyc
  framework/90_debug/{010_dev,020_jump_menu}.rpyc
  generated/{version,registry/*,scenes/*,screens/*,state/*}.rpyc
  gui.rpyc  options.rpyc  tl/…
```

Линия пересобрана 2026-08-08: было 34 файла, стало 52. Старая снималась до появления галереи (ADR-0010), достижений и генерируемых UI-панелей (ADR-0009), то есть покрывала уже не всё дерево — а фикстура валидна только против той линии, с которой снята.

`.gitignore:9` игнорирует `*.rpyc` глобально, и ровно одно исключение возвращает эту папку (`.gitignore:12-14`):

```
*.rpyc
…
# Линия statement-имён фикстур сейв-корпуса — ЕДИНСТВЕННЫЕ .rpyc в git (G6):
# без неё фикстуры валидны только на машине, где создавались
!ci/fixtures/rpyc-line/**
```

Две функции управляют линией:

| Функция | Что делает | Тонкость |
|---|---|---|
| `_rpyc_line_restore(root)` (`cli.py:1130-1148`) | Для каждого `*.rpyc` в `ci/fixtures/rpyc-line/` копирует его поверх `game/<rel>` — **только если рядом существует `game/<rel>.rpy`**. Возвращает счётчик | Устаревшие записи для удалённых исходников молча игнорируются |
| `_rpyc_line_snapshot(root)` (`cli.py:1151-1164`) | `rmtree` папки фикстур, затем копирует **все** `.rpyc` из `game/` | Без фильтров: снимок берёт то, что лежит в дереве прямо сейчас |

### 5.4. Добавить фикстуру: `vn save corpus --add <имя>`

`cli.py:1167-1213`. Порядок:

1. `.vncache/corpus-savedir` вычищается.
2. Автопилот прогоняется с `VN_AUTOPILOT_SAVE_AT=4` и `VN_AUTOPILOT_PICKS=0,1` — **обе величины захардкожены**, точку сохранения и маршрут флагом не задать.
3. Слот ищется как `sorted(savedir.glob("1-1*.save"))`: Ren'Py 8.5 добавляет к имени токен локации (`1-1-LT1.save`, `cli.py:1194`).
4. Копируется в `ci/fixtures/saves/<имя>.save` (расширение добавляется, если забыли).
5. Если фикстуры уже были — жёлтое предупреждение: линия `.rpyc` сейчас перезапишется, и старые фикстуры могли создаваться на другой линии.
6. `_rpyc_line_snapshot(root)` пересоздаёт линию целиком.

```bash
vn build                                  # линия снимается с ТЕКУЩЕГО генерата
vn save corpus --add schema2-rooftop
git add ci/fixtures/saves ci/fixtures/rpyc-line
```

**Коммитьте фикстуру и линию одним коммитом.** Разошлись — корпус красный у всех, а причина невидима в диффе.

### 5.5. Прогон корпуса: `vn save corpus`

`cli.py:1215-1256`:

1. `_rpyc_line_restore(root)` и сообщение `линия имён: N .rpyc восстановлено из ci/fixtures/rpyc-line/ (G6)`.
2. Нет `*.save` → fail с подсказкой создать.
3. На каждую фикстуру: `.vncache/corpus-savedir` пересоздаётся, фикстура кладётся **двумя именами** — `1-1-LT1.save` и `1-1.save` (какое имя ждёт SDK, зависит от версии, `cli.py:1228-1231`), автопилот запускается с `VN_AUTOPILOT_LOAD=1-1` и `--savedir`.
4. Критерий прохода (`cli.py:1243-1244`): не было таймаута **И** `RESULT.txt` начинается с `OK` **И** `state.json["vn_save_schema"] == project["save_schema"]`. При падении печатаются последние 1200 символов `traceback.txt`.

Миграции CLI не вызывает — они исполняются **в игре**, в `label after_load` (`game/framework/00_core/020_state.rpy:82-107`): сейв из будущей схемы блокируется (`renpy.block_rollback()` + сообщение + `full_restart()`), сейв из прошлой — прогоняет `vn_state.run_migrations()` и поднимает `vn_save_schema` ровно до фактически применённой миграции, не до цели. Подробности модели состояния — [07-backend.md](07-backend.md).

Реальный выход прогона (`.vncache/corpus/`): `RESULT.txt` = `OK: vn_end_of_content`, `state.json` со схемой 2, `picks.log` в одну строку `menu 1 -> pick 0 (ch01_s020_m001)` (счётчик меню приехал из сейва), кадры `shot003.png … shot018.png` — нумерация продолжается с сохранённого значения `_vn_ap_shot`, а не с нуля. Каталог перезаписывается на каждой фикстуре, так что после прогона в нём лежит выход **последней** из них.

### 5.6. Грабли корпуса

- **Ren'Py 8 подписывает слоты per-machine токеном** (в zip есть член `signatures`). Сейв, созданный на другой машине или в другой инсталляции, при загрузке даёт модальный `confirm`. Автопилот проходит его автоматически — таймер жмёт «да» каждые 0.8 с (`core_screens.rpy:403-404`). Руками при отладке этот диалог придётся подтверждать самому; это не поломка.
- **Фикстур две, и одна из них на старой схеме — миграция проверяется по-настоящему** (с 2026-08-08). `ci/fixtures/saves/schema2-demo.save` (8912 Б) — на текущей схеме: `{"vn_save_schema": 2, "vn_version": "0.1.0+48d19a3", "vn_scene": "ch01_s020"}`. `ci/fixtures/saves/schema1-demo.save` (10746 Б) — `vn_save_schema=1`, сцена `ch01_s010`; при `project.yaml:3` `save_schema: 2` на ней исполняется ветка `_loaded_schema < _target_schema` в `after_load`. Прогон печатает `schema после загрузки: 2 (цель 2)`, а в `log.txt` появляется `[vn] migration 0002` — доказательство, что миграция реально отработала в игре, а не «сейв просто открылся».
- **Проверяется ровно один переход, 1 → 2.** Каждый следующий бамп `save_schema` требует своей фикстуры, снятой **до** бампа (§9.8) — иначе новая миграция снова окажется непроверенной.
- **Обязательные фикстуры из `ARCHITECTURE.md:3681`** (сейв внутри переименованной сцены, «грязный» call-стек, сейв релиза N−1, DLC-контент без DLC) — **NOT IMPLEMENTED**, их просто нет.
- **Регрессия `rpyc-compat`** (`ARCHITECTURE.md:3508,3602-3605`): пара прогонов «с переносом `.rpyc` обязан пройти / без — обязан упасть». Негативной ветки в коде нет вообще — **NOT IMPLEMENTED**. Без неё нельзя доказать, что механизм переноса линии вообще работает.

---

## 6. Что не покрыто тестами

**Модули, которых тесты почти или совсем не касаются** (проверено грепом всех `from vn.…` в `tools/vn/tests/`; `vn.cli` с 2026-08-08 импортируется, но ровно ради одной команды):

| Модуль | Строк | Последствие |
|---|---|---|
| `tools/vn/src/vn/cli.py` | 1643 | Почти не покрыт. Единственный CLI-level тест — `pack build` через `click.testing.CliRunner` (`test_release.py:141-192`, 3 теста). Не покрыты: разбор аргументов и коды выхода остальных команд, маршрутизация `_stub`, `_autopilot_run`, `_rpyc_line_restore/_snapshot`, `save_check`, `save_corpus`, `test_smoke` |
| `tools/vn/src/vn/content/analyze.py` | 70 | Мост к парсеру Ren'Py не проверен вообще; `test_scene_pipeline.py` подсовывает фабрикованные словари анализа |
| `tools/vn/src/vn/content/scaffold.py` | 137 | Генераторы `vn chapter new`, `vn scene new`, `vn scene stub` не проверены |
| `tools/vn/src/vn/assets/psd.py` | 126 | Нарезка PSD не проверена (и не исполнялась ни разу — в репозитории нет ни одного `.psd`) |
| `tools/vn/src/vn/devloop.py` | 56 | Watch-цикл `vn dev` не проверен |

**Покрыто частично:** `doctor.py` — только `_lfs_pointer_fonts`; `pipeline.py` (581 строка) — только `find_ffmpeg`/`find_ffprobe`; `release.py` — `validate_release` **никогда не исполняется в тестах** (`test_release.py:212-214` ассертит только текст исходника); `repo.py` — используется косвенно, своих тестов нет.

**Целые подсистемы без автоматической проверки:** рантайм `game/framework/**`, включая `vn_qa` — ни один pytest не исполняет его код (единственное, что до него дотягивается, — статический `test_crash_handler.py`, читающий исходники регексом); сами `vn save check`/`vn save corpus`; `vn package`, `vn release build`, `vn pack validate`. `vn pack build` с 2026-08-08 покрыт.

**Хрупкие магические числа** — упадут от несвязанного изменения: `assert len(res.stale) == 14` (`test_verify_regressions.py:84`), набор `BASE_OUTPUTS` из 14 имён (`test_compile.py:11-26`), `assert cov == {"total": 6, "translated": 5, "fuzzy": 0}` (`test_loc.py:124`), `assert sites == 8` (`test_ci_config.py:90` — число мест установки тулчейна в CI; добавили джобу → поправьте константу).

**Инфраструктурные пробелы:** нет `pytest.ini` и зарегистрированных маркеров; нет джобы `rpyc-compat`; `game/framework/00_core/engine_compat/tests`, на который ссылается `ARCHITECTURE.md:3612`, **не существует** — контракт-тесты живут в `tools/vn/tests/test_engine_compat.py`.

---

## 7. Заглушки и несуществующие команды

| Команда | Статус | Поведение |
|---|---|---|
| `vn test smoke` | IMPLEMENTED | флаги ровно три: `--picks`, `--lang`, `--timeout` (`cli.py:1348-1350`) |
| `vn test replay` | NOT IMPLEMENTED, фаза 2 | `_stub(2)`: жёлтое «эта команда появится в фазе 2», exit **3** (`cli.py:1404-1405`) |
| `vn test paths` | NOT IMPLEMENTED, фаза 2 | `_stub(2)`, exit 3 |
| `vn test screens` | NOT IMPLEMENTED, фаза 3 | `_stub(3)`, exit 3 |
| `vn test perf` | NOT IMPLEMENTED | подкоманды **не существует вовсе** — click ответит usage-ошибкой, exit 2. `ARCHITECTURE.md:3644` её описывает |
| `vn save migrate` | NOT IMPLEMENTED, фаза 3 | `_stub(3)` (`cli.py:1259-1260`); миграции идут в игре, в `after_load` |

Докстринг группы всё ещё рекламирует все четыре: `"""QA-прогоны (7.4): smoke, replay, screens, paths."""` (`cli.py:1265`).

Отдельно — флаги, которые **заявлены в `ARCHITECTURE.md` и не существуют**: `vn test smoke --affected --shard N/M --seed <n>` и `--menu-only` (`:3530,3587,3595`), `vn test screens --update-baselines` (`:3617,3720`), `vn save corpus <dir> --report out/savecheck.json` и `--rpyc-regression` (`:3403,3600,3605`), `vn test paths --coverage edges` (`:3638`). Реальные пути артефактов тоже другие: `qa/saves-corpus/`, `tests/save_corpus/<version>/`, `.vncache/qa/smoke/` из `ARCHITECTURE.md` не существуют — есть `ci/fixtures/saves/` и `.vncache/smoke/`.

---

## 8. Кто и что гоняет в CI

Короткая сводка; подробный разбор workflow — [04-development-workflow.md](04-development-workflow.md) §4 и [29-build-and-release.md](29-build-and-release.md).

| Workflow | Триггер | Что из этого файла гоняет |
|---|---|---|
| `.github/workflows/ci.yml` | push в `main`, любой PR | `vn content lint` → `vn build` → `vn loc keys --check` → `renpy.sh . lint` → `vn content compile --check` → `pytest -q` (`:79`); артефакт `generated-<sha>` на 30 дней (`:81-86`) |
| `.github/workflows/nightly.yml` | cron `30 2 * * *` + dispatch | `vn build`, `vn loc import/report`; **матрица smoke**: `--picks 0,0` / `--picks 0,1 --lang en` / `--picks 1` / `--picks 0,0 --lang pseudo` (`:57-60`); `vn save check` + `vn save corpus` (`:64-65`); релизная сборка обоих флейворов на снесённом `game/generated` (`:70-74`); выгрузка `.vncache/smoke/` артефактом на 7 дней (`:76-82`) |
| `.github/workflows/canary.yml` | cron `0 3 * * 1` + dispatch | на **свежайшем** Ren'Py: `vn build` → `renpy.sh . lint` → `pytest` → `vn test smoke --picks 0,0` (`:48-51`) |
| `.github/workflows/release.yml` | тег `v*` | `vn release build --flavor <public\|patron>` (гейт внутри, `:78-87`) |
| `.gitlab-ci.yml` | — | PARTIAL / STALE: три джобы `lint`/`build`/`test`, ни smoke, ни корпуса, ни релиза, ни ffmpeg. `ci/README.md` всё ещё называет его «конфигом пайплайна» |

То есть: **smoke и корпус гоняются только ночью** и в canary. Ваш PR их не проверяет — прогоняйте руками перед push, если трогали рантайм, сейвы, локализацию или релизный путь.

Два окруженческих инварианта всех четырёх GitHub-workflow закрыты 2026-08-08 и стерегутся `tools/vn/tests/test_ci_config.py`: `pip install -r tools/vn.lock` стоит **до** editable-установки (G17), а `ffmpeg` ставится **до** любого `vn build`. Второе прямо касается ночных прогонов: раньше ffmpeg был только в `ci.yml`/`release.yml`, а видео-сырцы в `assets_src/video_src/` есть — то есть `nightly` и `canary` обязаны были краснеть на видео-ветке конвейера.

---

## 9. Чеклисты

Каждый пункт — команда этого проекта. Ожидаемое «зелёное» состояние: `vn doctor` — 8 PASS, `pytest` — 253 passed, `vn release validate --flavor public` — ни одного FAIL.

### 9.1. Pre-commit (5-10 с, после любой правки)

```bash
vn content lint
git status --short      # ничего из game/generated|assets|tl — иначе вы делали git add -f
```

### 9.2. Pre-build / pre-push — зеркало `ci.yml` (около минуты)

```bash
vn build
vn loc keys --check
bash "$RENPY_SDK/renpy.sh" . lint          # Linux: под xvfb-run -a
vn content compile --check
python -m pytest tools/vn/tests -q
```

Тот же список с пояснениями — [04-development-workflow.md](04-development-workflow.md) §5.

### 9.3. Pre-release (то, чего `ci.yml` не делает вообще)

```bash
vn doctor                                  # 8 PASS
vn build                                   # полная сборка, не --check
vn test smoke --picks 0,0                  # + по прогону на каждую развилку главы
vn test smoke --picks 0,0 --lang pseudo    # псевдолокаль ловит невынесенные строки
vn save check                              # ожидание: 2 фикстур
vn save corpus                             # схема после загрузки == project.yaml save_schema
vn loc report                              # покрытие; порог форсит только релизный гейт
vn release changelog                       # обновляет ci/release-manifest.json и штампует id_registry
vn release validate --flavor public
vn release validate --flavor patron
```

Ни один FAIL в гейте. Строка про корпус сейчас зелёная — `PASS  сейв-корпус: 2 фикстур`. WARN разбирайте глазами: «ci/release-manifest.json нет» — WARN, не FAIL, релиз с ним уедет; отсутствие фикстур вообще (`0 фикстур`) — тоже всего лишь WARN, так что пустой корпус релиз не остановит.

### 9.4. Новая глава

```bash
vn content lint                            # entry_scene, scene_order, exits, достижимость
vn build
vn content graph                           # глазами: нет висящих узлов и неожиданных тупиков
vn test smoke --picks <по одному индексу на каждое меню самого длинного пути>
# … и по отдельному прогону на каждую развилку — vn test paths НЕ существует
vn test smoke --picks … --lang en
vn loc keys && vn loc extract              # say-id и PO для переводчиков
python -m pytest tools/vn/tests -q
```

Развёрнутый порядок выпуска главы — [09-chapters.md](09-chapters.md); там же §10 про перебор веток.

### 9.5. Новый персонаж

```bash
vn content lint                            # декларация персонажа, матрица спрайтов
vn build                                   # emit_images: реестр образов строится из game/assets/
vn test smoke --picks 0,0                  # ловит «образ не найден» в реальном движке
bash "$RENPY_SDK/renpy.sh" . lint          # движковый lint видит неопределённые образы
python -m pytest tools/vn/tests/test_assets.py -q
```

Жизненный цикл персонажа целиком — [10-characters.md](10-characters.md).

### 9.6. Новый ассет (PNG / видео / UI-панель)

```bash
vn assets build                            # или vn assets build --profile draft для итерации
vn content lint                            # именование, зоны, бинарный бюджет ADR-0004
vn build                                   # ассеты — вход компилятора: реестр образов и галерея
vn build --check                           # бюджеты G19: assets_total_mb / video_total_mb / video_file_mb
python -m pytest tools/vn/tests/test_assets.py tools/vn/tests/test_video.py -q
vn test smoke --picks 0,0                  # видео и панели видно только в движке
```

Для видео `ffmpeg`/`ffprobe` обязаны быть в PATH, иначе `test_video.py` (9 тестов) молча скипнется. Детали — [16-assets.md](16-assets.md), [21-video-generation.md](21-video-generation.md).

### 9.7. Новая локализация

```bash
vn loc add <code>                          # пакет loc/po/<code>/language.yaml
vn loc extract                             # PO для переводчиков
vn loc import                              # game/tl/<code>/ (производная зона)
vn loc report                              # покрытие и fuzzy: сейчас de/en/pseudo — 115/115, fuzzy 0
vn build --check                           # валидация разметки PO ловится именно здесь
vn test smoke --picks 0,0 --lang <code>    # без game/tl/<code>/ команда откажет — это защита
vn test smoke --picks 0,0 --lang pseudo
python -m pytest tools/vn/tests/test_loc.py -q
```

Round-trip и грабли (`config.language_callbacks`, экранирование `[[`) — [14-localization.md](14-localization.md).

### 9.8. Перед бампом `save_schema`

Самая опасная операция в проекте: ошибка здесь ломает сейвы **уже вышедшим игрокам**, и откатить это патчем нельзя.

```bash
# 1. ДО правки project.yaml — зафиксировать текущее состояние как фикстуру
vn build
vn save corpus --add schema<N>-<маршрут>       # прогон + снимок линии .rpyc
git add ci/fixtures/saves ci/fixtures/rpyc-line && git commit
vn save check                                  # заголовок фикстуры: schema должна быть СТАРАЯ

# 2. Правка: миграция + бамп
#    content/migrations/<N+1>_*.py и content/migrations/registry.yaml, затем project.yaml: save_schema
vn content lint
python -m pytest tools/vn/tests/test_saves.py -q   # дыра в цепочке, незарезервированный номер, схема
vn build

# 3. Доказательство, что миграция реально проигрывается
vn save corpus                                 # старая фикстура -> after_load -> схема N+1
```

На шаге 3 в выводе должно быть `schema после загрузки: <N+1> (цель <N+1>)`, а в `log.txt` — строка `[vn] migration <NNNN>`. Если фикстура была снята уже на новой схеме, ветка миграции не исполнится и прогон будет ложно-зелёным.

**Рабочий пример в репозитории:** так снята `ci/fixtures/saves/schema1-demo.save` (`vn_save_schema=1`, сцена `ch01_s010`) — на ней корпус реально прогоняет миграцию `0002` (`content/migrations/0002_route_prologue.py`). До 2026-08-08 фикстура была одна и уже на схеме 2, то есть корпус ни одной миграции не проверял; теперь эта дыра закрыта, но **только для перехода 1 → 2**. Следующий бамп обязан начинаться с шага 1 — иначе новая миграция снова окажется без доказательства.

---

## 10. Ночной runbook — «пайплайн сломан перед релизом»

`../runbooks/pipeline-broken-at-night.md`, 24 строки, единственный файл в `docs/runbooks/`. Норма G20, владельцы — по `CODEOWNERS` (`/tools/` — минимум два человека).

**Симптом A — `vn build` падает локально у всех:**

1. `vn doctor` — сначала окружение, не код.
2. Откат тулчейна: `git log tools/vn.lock` → `git revert <bump-commit>` → `pip install -r tools/vn.lock && pip install -e tools/vn`. **Рецепт рабочий с 2026-08-08:** лок (18 пинов) ставится первым во всех пайплайнах (`ci.yml:30,46`, `nightly.yml:29`, `canary.yml:30`, `release.yml:42`, `.gitlab-ci.yml:23,37`), так что revert файла действительно меняет версии в CI. Остаточный риск: транзитивные зависимости в локе не закреплены (например `pygments` от `pytest`) — если поплыло что-то из них, revert не поможет.
3. Если сломан компилятор, а не lock: последний зелёный генерат лежит артефактом CI (`generated-<sha>`, джоба `build-test`, 30 дней) — скачать и распаковать в `game/generated/`, игра запустится без локальной компиляции. Runbook обещает `vn build --use-artifact <sha>` «с фазы 1» — флага **не существует**: `vn build` принимает только `--check` и `--profile` (`cli.py:84-88`), а строка `use-artifact` во всём тулчейне встречается один раз, в заголовке схемы `tools/schemas/gen_manifest@1.schema.json`. Только руками.

**Симптом B — CI красный, локально зелёно:**

1. Диффа окружений быть не должно — CI ставит тот же тулчейн, но **строго по локу**: `pip install -r tools/vn.lock`, затем `pip install -e "tools/vn[dev]"`. Локально без первой команды версии могут разойтись — повторите обе.
2. `git stash -u`, затем `vn content lint` на чистом чекауте: незакоммиченные локальные файлы регулярно «чинят» сборку невидимо.

**Эскалация:** владельцы `/tools/` по CODEOWNERS; оба недоступны — релиз переносится, «хотфиксы поверх непонятного пайплайна запрещены». После инцидента — post-mortem/ADR в `../adr/`, если причина архитектурная.

Симптом C, которого в runbook нет, но он самый частый в ночном режиме: **ночной smoke красный, локально зелёный** → скачайте артефакт `smoke-shots-<run_id>` (7 дней, `nightly.yml:76-82`), посмотрите `RESULT.txt` и последний `shot*.png`. `FAIL: vn_scene_unavailable` = jump на несуществующую метку; таймаут без traceback = скорее всего повисшее меню (см. §4.4).

---

## Как изменить / Как расширить

**Добавить pytest-тест.** Файл `tools/vn/tests/test_<модуль>.py`, функции `def test_*`, докстринг модуля — одной строкой про норму, которую тест защищает (так написаны все 19). Фикстура `repo_root` доступна из `conftest.py`. Нужен SDK — копируйте паттерн `test_engine_compat.py:11-14`; нужен ffmpeg — модульный `pytestmark`, как `test_video.py:13-16`. Не трогайте настоящий рабочий каталог: `tmp_path` + `_copy_skeleton`.

**Добавить проверку в релизный гейт.** Только `tools/vn/src/vn/release.py`, внутри `validate_release`, через локальный `add(state, msg)`. Правило проекта — у гейта **нет своих правил**, он агрегирует существующие проверки конвейера, чтобы не расходиться с `vn build` (`release.py:278-279`). Реализуйте проверку в профильном модуле, в гейт добавьте только вызов.

**Добавить действие автопилота.** Функция в `init -999 python in vn_qa` (`030_flow.rpy:91`) + переменная окружения + `timer … action Function(...)` в нужном экране. Помните §4.4: если функция обслуживает интеракцию (меню, confirm), она обязана вернуть результат `renpy.run(action)`. Чтобы флаг CLI её включал — новая опция в `test_smoke` и передача через `extra_env` в `_autopilot_run` (`cli.py:1369-1371`).

**Снять фикстуру для следующего бампа схемы** — см. §9.8, шаг 1. Это единственный способ получить фикстуру со **старой** схемой, и делать это надо ДО бампа. Для перехода 1 → 2 такая фикстура уже есть (`schema1-demo.save`) — повторите приём на 2 → 3.

**Следующим CLI-тестом** логично закрыть `_rpyc_line_restore` / `_rpyc_line_snapshot`: чистые функции над файловой системой, `tmp_path` достаточно, SDK не нужен. Шаблон уже есть — `_run_pack_build()` (`test_release.py:141-146`): `click.testing.CliRunner` + `monkeypatch.chdir(root)`, чтобы `_root()` нашёл синтетический корень. Дальше — тот же `CliRunner` на `_stub`-командах (контракт exit 3).

---

## Чего НЕ делать

- **Не слать синтетический ввод на рабочий стол.** `SendKeys`/`pyautogui`/`xdotool` по окну игры — запрещённый приём (§4.5). Всё автоматизируется in-process через `vn_qa`.
- **Не писать автопилот-хук без `return renpy.run(action)`** — прогон повиснет до таймаута, и причина будет неочевидной (`030_flow.rpy:148-150`).
- **Не считать зелёный `pytest` доказательством работоспособности игры.** 253 теста почти не касаются `cli.py` (закрыт один `pack build`) и не исполняют `game/framework/**`. Без SDK и ffmpeg 18 из них ещё и скипнутся молча.
- **Не бампать `save_schema`, не сняв фикстуру заранее.** После бампа получить сейв со старой схемой уже нечем — в корпусе окажется ложно-зелёная проверка. Так и было до 2026-08-08; фикстура `schema1-demo.save` закрыла это только для перехода 1 → 2.
- **Не коммитить фикстуру без `ci/fixtures/rpyc-line/`** (и наоборот). Расхождение делает корпус красным на любой машине кроме той, где фикстуру снимали.
- **Не добавлять `.rpyc` в git руками.** Единственное легальное исключение — `ci/fixtures/rpyc-line/**` (`.gitignore:12-14`), и его пересоздаёт `_rpyc_line_snapshot`, а не человек.
- **Не редактировать `.vncache/smoke/`, `.vncache/corpus/`, `.vncache/corpus-savedir/`** — они вычищаются в начале каждого прогона (`cli.py:1300-1302`).
- **Не ориентироваться на `.vncache/langqa/`** — артефакт-сирота без производящего кода (§4.8).
- **Не описывать в задачах и PR флаги из `ARCHITECTURE.md`, которых нет** (`--affected`, `--shard`, `--update-baselines`, `--report`, `--rpyc-regression`, `vn test perf`, `vn build --use-artifact`). Это целевой документ, а не описание построенного.
- **Не полагаться на PR-пайплайн в вопросах рантайма** — smoke и корпус там не гоняются вообще (§8).

---

## Проверка

Полный локальный прогон «как в CI + то, чего CI на PR не делает»:

```bash
export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"   # в bash-сессии агента не наследуется

vn doctor                                  # ожидание: 8 PASS, 0 FAIL
vn content lint
vn build                                   # ожидание: build: OK
vn loc keys --check
bash "$RENPY_SDK/renpy.sh" . lint
vn content compile --check
python -m pytest tools/vn/tests -q         # ожидание: 253 passed
vn test smoke --picks 0,0                  # ожидание: smoke: OK: vn_end_of_content (21 скриншот)
vn save check                              # ожидание: save check: OK (2 фикстур)
vn save corpus                             # ожидание: OK (2 фикстур); на schema1-demo —
                                           #   «schema после загрузки: 2 (цель 2)» + [vn] migration 0002 в log.txt
vn release validate --flavor public        # ожидание: без FAIL, exit 0
```

Артефакты, по которым разбирают падение: `.vncache/smoke/{RESULT.txt,picks.log,startup.txt,state.json,gallery.json,shot*.png}`, `.vncache/corpus/*`, `traceback.txt` и `log.txt` в корне репозитория. Как ими пользоваться — [28-debugging.md](28-debugging.md).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/cli.py:1090-1260` (группа `save`, линия `.rpyc`), `cli.py:1263-1405` (группа `test`, `_AUTOPILOT_RPY`, `_autopilot_run`, `test_smoke`, заглушки), `game/framework/00_core/030_flow.rpy:91-211` (`vn_qa`), `game/framework/20_ui/screens/choice.rpy:53-54`, `game/framework/20_ui/screens/core_screens.rpy:403-404`, `game/framework/00_core/020_state.rpy:83-107` (`after_load`), `tools/vn/tests/conftest.py`, `tools/vn/src/vn/release.py:276-481` (гейт), `.github/workflows/{ci,nightly,canary}.yml` |
| **Не трогать** | `.vncache/**` (вычищается каждым прогоном), `game/generated/**` и `game/generated/qa/` (последняя создаётся и удаляется автопилотом), `ci/fixtures/rpyc-line/**` руками — только через `vn save corpus --add`; `.gitignore:12-14` (исключение для линии `.rpyc` — единственное легальное `.rpyc` в git) |
| **Зависимости (что сломается ниже по течению)** | правка `game/framework/**` или контента → линия statement-имён расходится с `ci/fixtures/rpyc-line/` → `vn save corpus` красный, пока фикстуру не пересняли; правка `choice.rpy`/`core_screens.rpy` → автопилот перестаёт выбирать/подтверждать → smoke виснет до `--timeout`; правка `autopilot_finish` → меняются `state.json`/`gallery.json`, на которых стоит критерий прохода корпуса; бамп `project.yaml: save_schema` → корпус падает по несовпадению схемы, если миграция не написана; правка `budgets.cold_start_s` → меняет вердикт `vn test smoke` (единственное место, где этот бюджет форсится) |
| **Валидация** | `vn content lint` → `python -m pytest tools/vn/tests -q` (253) → `vn build --check` → `vn test smoke --picks 0,0` → `vn save check && vn save corpus` → `vn release validate --flavor public`. Для всего с 3-го пункта обязателен `RENPY_SDK` |
| **Частые ошибки** | 1) Считать `ARCHITECTURE.md` описанием реальности: `--affected`, `--shard`, `--update-baselines`, `--report`, `--rpyc-regression`, `vn test perf`, `qa/saves-corpus/` — их нет. 2) Добавить автопилот-хук без `return renpy.run(action)` — вечное перевыбирание пункта меню (`030_flow.rpy:148-150`). 3) Предложить SendKeys/pyautogui для «теста UI» — прямой запрет, автопилот только in-process. 4) Считать зелёный `pytest` покрытием CLI и рантайма — из `cli.py` (1643 строки) покрыт только `pack build`, а код `game/framework/**` не исполняется ни одним тестом. 5) Забыть, что 17 тестов молча скипаются без `RENPY_SDK`/ffmpeg. 6) Утверждать, что корпус миграций не проверяет — с 2026-08-08 фикстура `schema1-demo.save` реально прогоняет миграцию `0002`; непокрытыми остаются будущие переходы схемы. 7) Ссылаться на `.vncache/langqa/` как на воспроизводимый прогон — его никакой код не производит. 8) Ожидать smoke/корпус в PR-пайплайне — они только в `nightly.yml` и `canary.yml` |
