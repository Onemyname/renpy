# 27. Тестирование: уровни проверок, smoke-автопилот, сейв-корпус, чеклисты

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — **518 pytest-тестов** (31 файл), автопилот в реальном движке, сейв-корпус и **корпус масштаба** работают и гоняются в GitHub Actions; сейв-корпус проверяет **реальную миграцию** (2 фикстуры, вторая на старой схеме), корпус масштаба — конвейер до 20 000 сцен ([32](32-performance-and-scalability.md) §7.5). **Но** `cli.py` (2117 строк) покрыт точечно — `pack build` плюс 14 тестов `test_cli.py` из 69 листовых команд, а `vn test replay|screens|paths` — заглушки. Известная механическая проблема осталась: `python -m pytest tools/vn/tests -q` **из корня** даёт `1 failed` — теперь все пайплайны зовут pytest из `tools/vn` (§2.1).
> **Отвечает на вопрос:** «Что запустить, чтобы убедиться, что я не сломал игру — в каком порядке, что каждая команда ловит и чего не ловит».
> **Сверено прогонами:** 2026-08-18, HEAD `db28ce6`, SDK 8.5.3, ffmpeg 7.x в PATH.

Тестов у проекта два сорта: обычный pytest над Python-тулингом (`tools/vn/tests/`, **27 файлов** `test_*.py` + `conftest.py` + `helpers.py`) и прогон **настоящей игры** автопилотом внутри её собственного процесса (`vn test smoke`, `vn test oversample`, `vn save corpus`). Рантайм Ren'Py питоном не тестируется — до `game/framework/**` не дотягивается ни один pytest (его проверяют только прогоны движка), исключения статические: `test_crash_handler.py`, `test_platform.py:183` и `test_ui_panels.py:325,295,320` читают исходники `game/**` регексом. Чеклисты (§9) — главный практический раздел этого файла.

## Быстрый ответ

Девять уровней, от самого быстрого к самому медленному. Первые три — обязательный минимум перед push; девятый (корпус масштаба) нужен, когда меняете конвейер, а не контент.

```bash
vn content lint                          # 1. ~1 с, SDK не нужен: схемы, именование, граф, достижимость
cd tools/vn && .venv/bin/python -m pytest -q && cd -   # 2. 518 passed (про cwd — §2!)
vn build --check                         # 3. свежесть генерата и ассетов, разметка PO, два бюджета
bash "$RENPY_SDK/renpy.sh" . lint        # 4. движковый lint (Windows: "$RENPY_SDK/renpy.exe" . lint)
vn test oversample --scale 2             # 5. движок реально подхватывает @2-варианты (ADR-0012)
vn test smoke --picks 0,0                # 6. автопрохождение в реальном движке (~10-20 с)
vn save check && vn save corpus          # 7. 2 фикстуры сейвов + реально исполняемая миграция
vn release validate --flavor public      # 8. релизный гейт: 21 проверка в коде, 20 строк на экране
                                         #    (сейчас 0 FAIL, exit 0; WARN зрелости — пока нет release-глав)
```

Уровни 4-8 требуют `RENPY_SDK`. **Грабля:** в bash-сессиях агента переменная не наследуется — экспортируйте вручную (путь свой):
`export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"`.

Фактический вывод этих команд на текущем чекауте — в разделе «Проверка» в конце файла.

---

## 1. Инвентарь тестов — IMPLEMENTED

**31 файл `test_*.py` + `conftest.py` + `helpers.py`.** Собирается **518 тестов** (было 278 до итерации 2026-08-18); расхождение с числом функций `def test_*` дают параметризованные тесты — два в `test_ui_panels.py` (`scale` 1/2 и `ui_scale` 1.0/1.4), плюс `test_android.py` (парсер JDK) и `test_cli.py` (шесть новых команд). Все тесты лежат плоско в одной директории, тестовых классов нет.

Три файла добавлены этой итерацией: `test_android.py` (43 — мобильный канал: `rapt_status`, парсер JDK, предполётные лимиты и бандл, утечка ключей, гарды `options.rpy` и тач-токенов, контракт запуска шагов `setup` и совпадение их списка с движковой командой, эмиссия мобильного лимита кэша, факт по собранному пакету против потолков канала), `test_corpus.py` (14 — корпус масштаба: схемная валидность генерата и чистый `lint`, соблюдение заданного масштаба **по факту на диске**, идемпотентность, неприкосновенность репозитория, отказ писать в чужой каталог, SDK-гейтом — полный измерительный прогон), `test_cli.py` (14 — реестр заглушек, соответствие перечня доменов норме C13, маппинг флагов `test corpus` и `voice tts` на API, порядок «тулчейн до сборки» у `release android build`, закрытый список шагов `release android setup`).

`tools/vn/tests/helpers.py` — общая обвязка синтетических корней: `mk_root()` / `write_project()`
кладут **свой** render-профиль с экраном 64×48 вместо боевых 4K-мастеров, `img()` пишет мастер
заданного размера и формата, причём у RGBA по умолчанию делает реальную прозрачную рамку — без неё
«альфа есть, но всё непрозрачно» было бы тем самым состоянием, которое конвейер обязан считать
ошибкой. Побочный эффект: тесты доказывают, что render-профиль действительно data-driven, а не зашит
в конвейер.

| Файл | Тестов | Что покрывает | Заметные фикстуры и механики |
|---|---|---|---|
| `test_loc.py` | 31 | `vn.loc.po` + `vn.loc.keys`: дискавери пакетов языков (ADR-0005), PO round-trip, fuzzy при смене исходника, псевдолокаль, `game/tl/<code>/language.json`, валидация разметки, orphan-сверка ledger | Локальный `_mk_loc_root(tmp_path)` строит синтетический репозиторий; реальный `polib`. Единственный e2e-тест (`:392`) **мутирует настоящий `loc/ledger/ch01.json`** и восстанавливает его в `finally` |
| `test_lint.py` | 16 | `vn.content.lint.lint` + `vn.release.stamp_id_registry`: чистый репозиторий, битые пакеты языков, осиротевшие пары сцен, downgrade ошибок на `draft`, исчезновение выпущенных id, исключение по `renames`, недостижимость и тупики, бинарный бюджет ADR-0004 | `_copy_skeleton()` копирует скелет без глав; `_mk_chapter()` строит главы с произвольным графом exits. `test_lint_clean_repo` линтует **живой репозиторий** |
| `test_scene_pipeline.py` | 29 | `vn.content.scenes`: контракт меток, запрет межсценовых jump, соответствие `return` ↔ `exits`, Variable Registry, эмиссия обвязки, фоны локаций | `_unit()`/`_analysis()` фабрикуют `SceneUnit` и результат парсера — SDK не нужен. e2e-компиляция демо-главы — `skipif` без `RENPY_SDK` (`:332`) |
| `test_provenance.py` | 12 | `vn.assets.provenance` (извлечение параметров из PNG ComfyUI, `record`/`verify`, дедуп workflow), декларации DAZ/VaM/Sims4, композиция цепочки DAZ→AI | Константа `API_GRAPH` — реалистичный API-граф ComfyUI; `_comfy_png()` пишет PNG с чанком `prompt` |
| `test_gallery.py` | 24 | `_emit_gallery` (ADR-0010 + `kind: shot` по ADR-0013): форма реестра, разрешение превью (включая композитное превью шота), отсутствующий ассет, неизвестная категория, несоответствие kind/asset, `variants` у шота, шот вне `shots@1`, существование якоря, дубликаты id, состав `shot_layers`, разблокировка шота по тегу+атрибуту | Заглушка `_Rep` с одним полем `.warnings`; `_mk_assets()` пишет однобайтовые файлы-пустышки. Компиляция реального реестра — `pytest.skip` без SDK (`:181`) |
| `test_verify_regressions.py` | 13 | Регрессии находок фазы 0: устойчивость lint к схемно-невалидным `exits`, отсутствующие входы компилятора, «`--check` ничего не пишет», shim-размотка, префикс `vn_` в persistent, схема gen-манифеста, `_lfs_pointer_fonts` | Свой `_copy_skeleton`. Магическая константа `14` заменена на `len(BASE_OUTPUTS)` из `test_compile.py` (`:84`) — но именно этот межмодульный импорт и делает прогон зависимым от cwd (§2) |
| `test_assets.py` | 27 | `build_assets`: трансформации, кэш и восстановление `from_cache`, orphan-очистка, нарушения именования, `sprite_tree`, `emit_images`, `build_graph`; **`:52`** — ветка звука читает `assets_src/audio_stems/`; **`:69`** — манифест сборки проходит схему `assets_manifest@1` из реестра (G16) | `_png()` через Pillow; цвета намеренно разные, чтобы дедуп по content-hash не маскировал результат |
| `test_ui_panels.py` | 13 (15 прогонов) | `vn.assets.ui` (ADR-0009): парсинг hex/RGBA, геометрия `borders_of` (radius + blur + dy), 9-patch и альфа, градиент, `emit_frames`, инкрементальность по панели, orphan. Три **гард-теста по живому репозиторию**: `:232` — декларация валидна и панели `choice*` не выше 60 px; `:251` — ни один потребитель `vn_frame_*` не меньше `2*Borders`, **параметризован `ui_scale` 1.0 и 1.4**; `:295` — интерфейсные кегли `gui.*` растут с `gui.ui_scale`, диалоговые не растут, ни один токен не уменьшается; `:320` — вкладки и кнопки галереи сидят на `chip`/`chip_active`, а не на `choice` | Pillow читает пиксели рендера; `_load_gui_tokens` парсит `game/gui.rpy` и `eval`-ит выражения токенов, `_load_styles` — все `style` в `game/**/*.rpy`. Панелей в `content/ui/panels.yaml` — **8** (`choice`, `choice_hover`, `choice_chosen`, `chip`, `chip_active`, `panel`, `slot`, `toast`) |
| `test_artifact.py` | 20 | Аварийный путь G4 (`vn build --use-artifact`): выбор новейшего ЗЕЛЁНОГО прогона, отказы (нет прогонов / все красные / нет gh / неизвестная ссылка), верификация артефакта (манифест реестром схем, пересчёт хешей, zip-slip, исторический `gen_manifest@1`), замена генерата и пометка `source.kind=artifact`, предупреждение о рассинхроне с HEAD | Подставной `gh` sh-скриптом в PATH (приём `_fake_javac` из `test_android.py`); сети не требует |
| `test_char.py` | 23 | `vn char new|validate|sheet`: заготовка валидна по `character@1` сразу, каталог позы НЕ создаётся, скаффолд не перезаписывает, цвет стабилен и различим; валидатор — те же формулировки, что у сборки (`check_matrix`), подсказка `canvas: [W, H]` по факту мастера, «мастера без декларации», ничего не пишет на диск (сверка mtime); лист — все допустимые комбинации, запрещённые пропущены, идемпотентность, серая подложка | `helpers.mk_root_with_schemas` + синтетические слои |
| `test_qa.py` | 25 | Машинерия прогонов: парсер `picks.log`, чтение артефактов (включая битые и отсутствующие), вердикт (traceback первым, таймаут vs код выхода), декларация тура и статический гард «каждый экран проекта покрыт туром», записи повтора (отказ на красном прогоне, схема), сверка повтора (переменная названа, дрейф версии останавливает сверку), рантайм-бюджеты и отсутствие `vn test perf` | Артефакты выкладываются на диск руками — движок не запускается |
| `test_ci_config.py` | 14 | Инварианты конфигов CI по YAML: набор workflow найден (`:66`); `-r tools/vn.lock` стоит **до** editable-установки во всех **8** джобах (G17); `ffmpeg` ставится до любого `vn build`/`vn release build`; видео-сырцы в `assets_src/video_src` на месте (иначе требование ffmpeg вырождается); `ci.yml` триггерится на **любой** ветке, а не только `main`; push-триггер `ci.yml` **не** ловит теги, иначе дублировал бы `release.yml`; у `ci.yml` нет `pull_request`, пока push нефильтрован; вариантные прогоны и корпус — в `nightly`, а не в `ci`; `android preflight` — после `vn build`; провал тулчейна не заглушён `\|\| true`/`continue-on-error`, а `voice tts` пиннует бэкенд; масштаб корпуса явный и ограничен; pytest запускается из `tools/vn`; второго конфига CI в репозитории нет (`.gitlab-ci.yml` выведен 2026-08-18 — полузеркало ночью починят вместо настоящего пайплайна) | Свой парсер `_github_jobs()` по YAML workflow |
| `test_crash_handler.py` | 6 | Регрессия «мёртвый обработчик»: `config.exception_handler` присваивается **ровно один раз** и именно в `070_crash.rpy`; обработчик пишет строку `[vn] unhandled exception:` и возвращает `False` | Статический: рантайм Ren'Py в pytest недоступен, поэтому регекс по `game/framework/**/*.rpy` |
| `test_licenses.py` | 7 | `vn.assets.licenses`: загрузка реестра, блок `game_use: false`, гейт `nsfw_allowed`, warning про непокрытые декларации | Инлайн-константа `REGISTRY` на 3 ассета + проверка живого `content/licenses.yaml` |
| `test_video.py` | 9 | `vn.assets.video` и видеоветка `build_assets`: энкод VP9, `mov_meta@1`, детект шва лупа, инвалидация по sidecar `*.video.yaml`, нейминг, orphan, бюджеты/кодек | **Весь модуль `skipif` без ffmpeg/ffprobe** (`:13-16`). Сырцы синтезируются `ffmpeg -f lavfi`: `color=` — идеальный луп, `testsrc` — рваный |
| `test_release.py` | 33 | `vn.release`: конфиг флейвора, NSFW-глобы исключения, `build_info@2` write/validate/clear, видео-бюджеты, гейт LFS-указателей шрифтов; **`:79`** — `patron_tag` короткая, стабильная и **не равна токену** (ADR-0011); **`:149-192`** — три теста `vn pack build` через `CliRunner`; **`:233`** — `built_asset_ids` игнорирует производные (`@2`, `.thumb`, постеры); **`:250`** — гард-тест россыпи: `build.archive` в `game/options.rpy` запрещён (норма §2.4, `.rpa` — только mobile фазы 3 через ADR) | Инлайн `PROJECT`; `_run_pack_build()` (`:141-146`) = `CliRunner` + `monkeypatch.chdir`. `validate_release` **по-прежнему никогда не исполняется**: тесты гейта (`:195-230`) ассертят только `inspect.getsource(...)` |
| `test_saves.py` | 6 | Сейв-часть компилятора (G5): дыра в цепочке миграций, незарезервированный номер, несовпадение схемы, встраивание исходников `_emit_migrations`, пары стора в `_emit_snapshot`, рантайм-эквивалентное исполнение миграции | `_mk_migrations()` пишет `content/migrations/registry.yaml` + нумерованные `.py`; `_src_factory` подделывает колбэк хеша входов |
| `test_storage.py` | 5 | `vn.assets.storage` (G14/G21): push требует лока, round-trip lock→push→pull с иммутабельными версиями, чужой лок и `--force`, состояния `status`, честная заглушка s3 | `.vnstorage.yaml` в `tmp_path` с файловым бэкендом |
| `test_compile.py` | 8 | `compile_content`: набор выходов пустого проекта, идемпотентность, точечная очистка осиротевших `.rpy`+`.rpyc`, `CompileError` при главах без `RENPY_SDK` | `BASE_OUTPUTS` — замороженный набор из **16** имён (`:11-28`, включая `render.gen.rpy` по ADR-0012 и `platform.gen.rpy` по ADR-0014); ровно эти 16 остаются от 21 выхода, когда в проекте нет ни одной главы. `monkeypatch.delenv("RENPY_SDK")` |
| `test_achievements.py` | 17 | `_emit_achievements` (`achievements@1`): значения по умолчанию, пустой реестр, правило `oneOf` (ровно один триггер), валидность живой декларации | Фабрика `_doc(**achievements)`; `pytest.skip`, если деклараций нет |
| `test_voice.py` | 27 | Голосовой контур (§4.9/C5): `vn.voice` — валидация манифестов против ledger (сироты в обе стороны, чужая глава), CSV-лист `manifest`, атомарный `import_takes`, маппинг дыр покрытия в FAIL релизного гейта, инжекция voice-операторов `_inject_voice`, транскод `voice_opus`, отбраковка путей вне конвенции; **+14 про TTS-черновики**: снятие разметки перед синтезом, выбор бэкенда по доступности и `--backend`, оба диалекта флагов piper, разрешение модели голоса и отказ без `--allow-download`, неприкосновенность `final`, идемпотентность, текст дубляжа из PO | Транскод-тест и e2e TTS скипаются без ffmpeg (`:199`) и без macOS `say` с русским голосом (`:493-497`) |
| `test_shots.py` | 15 | Послойные шоты (shots@1, ADR-0013): сборка слоёв с вариантами, обязательность `env` и альфы, единый холст, эмиссия `layeredimage` (ошибка на несобранный вариант, warning на orphan-слой), атрибуты в индексе образов, учёт худшего шота моделью памяти, отказ компилятора на битой декларации | Tiny-профиль: экран 64×48, мастера 128×96 (`@2`) |
| `test_memory.py` | 8 | Модель памяти образов (ADR-0012): формулы движка дословно (лимит `mb*1024*1024//4`, стоимость `bbox*1.34`, bbox по альфе), worst-case сцены, ошибка при превышении бюджета, соответствие `render.gen.rpy` проекту | Сверено с `renpy/display/im.py` |
| `test_sources.py` | 8 | Единый контракт внешних источников (DAZ / VaM / Sims 4): скаффолд ↔ валидатор, id ↔ выход, заявленное разрешение ↔ файл, сквозная цепочка DAZ → Wan → игра, VaM `.var`-пакеты и кинематик-секвенции до сцены и галереи | Секвенция-тест требует ffmpeg (`:193`) |
| `test_schemas.py` | 8 | `SchemaRegistry`: имя файла ↔ `const`, `additionalProperties: false` у каждой схемы, валидность стартовых деклараций, ошибка на неизвестной схеме | Ассерты «не меньше»: `len(reg.schemas) >= 15`, `seen >= 10` |
| `test_engine_compat.py` | 6 | Контракт-тесты G18 против пиннованного SDK: существование `renpy.call_stack_depth`/`get_return_stack`, voice-стейтмент, `config.emphasize_audio_*`, **штатный Steam-стек** (`test_steam_engine_contract:62` — тихий no-op без steam_api, варианты `steam_deck`/`steam_big_picture`, `SteamBackend`, `dlc_installed`, `steam_init()` на `init -1499`; ADR-0014); равенство `VN_API_LEVEL` (тулинг) и `API_LEVEL` в `030_flow.rpy:9` | Маркер `requires_sdk` (`:11-14`) на четырёх из пяти. Тест про API_LEVEL SDK **не** требует — он регексом читает файл фреймворка |
| `test_platform.py` | 21 | Платформенный слой (ADR-0014): эмиттер `platform.gen.rpy` (Steam выключен без `appid`, карта `VN_STEAM_DLC` только из паков с `steam_dlc_appid`), рендер VDF из шаблона (`appid`/`SetLive`/депоты, warning на незаданный депот), обязательность `appid` и `depots`, раскладка депотов из **реальных** архивов distribute (win-`zip` и linux-`tar.bz2` в одном кейсе, `:78-102`) и честные ошибки — без дистрибутива и при объявленном депоте без артефакта (`:104-111`), статус steam_api-библиотек; **`:129`** — гард-тест «слово Steam живёт только в `035_platform.rpy`» | `_steam_root()` строит синтетический репозиторий и копирует **живой** `ci/steam/app_build.vdf.tmpl`; SDK не нужен ни одному тесту |

| `test_android.py` | 43 | Мобильный канал (2026-08-18): `rapt_status` на синтетическом SDK (пусто / частично / полно, внешний SDK через `rapt/sdk.txt`, несовпадение хешей), парсер JDK (параметризован, включая Java 8 и вывод в stderr), предполётные лимиты канала и пофайловый лимит бандла, мобильный кэш образов из `project.yaml` и `for_mobile()`, утечка ключей подписи (tracked / not-ignored / ignored), «в схеме `project@1` нет android-секретов», гард порядка `build.classify` в `options.rpy`, гард «тач-профиль в токенах», отказ `build_apk` без тулчейна | `no_windows`/`needs_git` — точечные скипы; синтетический SDK и `git init` в `tmp_path` |
| `test_corpus.py` | 15 | Корпус масштаба: все декларации проходят схемы и `lint` **без предупреждений**, заданный масштаб соблюдён по факту на диске (мастера/сцены/переменные/реплики), идемпотентность генерации (`written == []`, дерево байт-в-байт), смена спеки = чистая пересборка, неприкосновенность репозитория (снимок mtime до и после), `_Writer` не пускает путь наружу, `cleanup`/`generate` не трогают чужой каталог, лимиты спеки, превышенный бюджет G19 = не зелёный прогон | Два теста под `skipif RENPY_SDK` (`:221`, `:246`) — полный измерительный прогон и авто-очистка |
| `test_cli.py` | 21 | Сам CLI: реестр заглушек равен замороженному списку (9), новые команды **не** заглушки (`voice tts`, `test corpus`, четыре `release android`), перечень доменов верхнего уровня совпадает с нормой C13, `release android status` называет команду-лекарство и падает кодом 1, `release android setup` отбивает неизвестный шаг кодом 2, `release android build` проверяет тулчейн **до** долгой сборки, флаги `test corpus` и `voice tts` доезжают до публичного API один в один | `click.testing.CliRunner` + `monkeypatch` на функции модулей |

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

### 2.1. Рабочая команда — из `tools/vn`, а не из корня

```bash
cd tools/vn && .venv/bin/python -m pytest -q                  # 518 passed
cd tools/vn && .venv/bin/python -m pytest -q tests/test_lint.py   # один файл
cd tools/vn && .venv/bin/python -m pytest -q -k gallery       # по имени
```

**Прогон из корня по-прежнему не проходит целиком** (пайплайны с 2026-08-18 зовут pytest из `tools/vn`, поэтому CI это больше не задевает — см. ниже):

```
$ python -m pytest tools/vn/tests -q          # из КОРНЯ
FAILED tools/vn/tests/test_verify_regressions.py::test_check_mode_writes_nothing_and_detects_stale
    from tests.test_compile import BASE_OUTPUTS
    E   ModuleNotFoundError: No module named 'tests'
1 failed, 399 passed
```

Причина механическая, а не логическая. `tools/vn/tests/` — не пакет (`__init__.py` нет), поэтому
pytest в режиме `prepend` кладёт в `sys.path` **сам каталог тестов**, а `conftest.py:8` добавляет
`tools/vn/src`. Каталога `tools/vn` в путях не оказывается ни от кого — а `test_verify_regressions.py:84`
импортирует `tests.test_compile`, то есть требует именно его. Когда cwd = `tools/vn`, `python -m pytest`
добавляет cwd первым элементом `sys.path`, и импорт находится.

Три рабочих варианта:

| Команда | Результат |
|---|---|
| `cd tools/vn && python -m pytest -q` | 518 passed |
| `PYTHONPATH=tools/vn python -m pytest tools/vn/tests -q` (из корня) | 518 passed |
| `python -m pytest tools/vn/tests -q` (из корня) | **1 failed, 399 passed** |

**Что изменилось 2026-08-18:** CI больше не красный на этом тесте — шаг pytest в `ci.yml` получил
`working-directory: tools/vn`, а в `canary.yml` команда обёрнута в подоболочку
`(cd tools/vn && …)`; инвариант закреплён тестом `test_ci_config.py::test_pytest_runs_from_tools_vn`.
Второй конфиг, который содержал ту же строку из корня и оставался красным, больше не существует:
GitLab-зеркало выведено из эксплуатации 2026-08-18 ([04](04-development-workflow.md) §4).

Правильное исправление — по-прежнему снять саму зависимость, а не переносить cwd: `BASE_OUTPUTS`
логичнее вынести в `tests/helpers.py`, который уже импортируется без пакета
(`from helpers import mk_root`), либо добавить `[tool.pytest.ini_options] pythonpath = ["."]` в
`tools/vn/pyproject.toml`. Общее правило отсюда: **не импортировать один тестовый модуль из другого.**

### 2.2. Окружение

- **Установка не обязательна** для импортов (`conftest.py:8` инжектирует `tools/vn/src` в `sys.path`),
  но зависимости нужны: `click, PyYAML, jsonschema, blake3, Pillow, psd-tools, polib` + `pytest>=8.0`.
  Канонично — `pip install -r tools/vn.lock && pip install -e "tools/vn[dev]"`, ровно как в CI.
  Системный `python3` этого чекаута зависимостей не имеет — прогон идёт через `tools/vn/.venv`.
- **Нет `pytest.ini`, нет `[tool.pytest.ini_options]`, нет зарегистрированных маркеров** — только
  инлайновые `pytest.mark.skipif` и модульный `pytestmark`. `-m <marker>` использовать не с чем.
- **Риск изоляции:** `test_loc.py:448-470` правит настоящий `loc/ledger/ch01.json` и откатывает его в
  `finally`. Прерванный по Ctrl+C прогон оставит рабочее дерево грязным — проверяйте `git status`
  после аварийной остановки.

### 2.3. Гейтинг по окружению: 10 скипов без SDK, 12 скипов + 1 ПАДЕНИЕ без ffmpeg

Измерено на этом чекауте (2026-08-18, из `tools/vn`).

| Окружение | Результат |
|---|---|
| SDK + ffmpeg | `518 passed` |
| без `RENPY_SDK`, ffmpeg есть | `501 passed, 11 skipped` |
| SDK есть, без ffmpeg | `499 passed, 12 skipped, **1 failed**` |
| без SDK и без ffmpeg | `488 passed, 23 skipped, **1 failed**` |

**10 тестов под `RENPY_SDK`:** четыре контракт-теста `test_engine_compat.py` (`:26`, `:34`, `:56`,
`:63` — последний `test_steam_engine_contract`, ADR-0014), два e2e через build-bridge в
`test_scene_pipeline.py` (`:468`, `:498`), два в `test_corpus.py` (`:221` полный измерительный прогон,
`:246` авто-очистка) и по одному в `test_gallery.py:302`, `test_loc.py:448`. Тест
`test_engine_compat.py:91` (`test_api_level_sync`) SDK **не** требует — он читает `030_flow.rpy` регексом.

**12 тестов под ffmpeg/ffprobe:** весь модуль `test_video.py` (9, модульный `pytestmark` на
`:15-17`), плюс `test_sources.py:193` и два в `test_voice.py` (`:199` — транскод, `:493-497` — e2e
TTS-черновиков, которому нужны и ffmpeg, и macOS `say` с русским голосом).

**Одно падение вместо скипа.** `test_voice.py::test_pipeline_rejects_bad_voice_layout` (`:199-208`)
гейта не имеет, а проверяет, что мастер озвучки вне конвенции пути даёт ошибку «вне конвенции». Без
ffmpeg голосовая ветка отваливается **раньше**, с другой ошибкой, и ассерт не находит ожидаемую
строку:

```
tests/test_voice.py:208: assert any("вне конвенции" in e for e in rep.errors)
E   assert False
```

То есть без ffmpeg прогон не «молча зеленеет», а даёт один непонятный красный тест. Лечится либо тем
же гейтом, что у соседнего теста, либо тем, что проверка раскладки должна идти до проверки ffmpeg в
`pipeline.py`.

**Вывод для чеклистов:** зелёный прогон без SDK и ffmpeg не означает, что путь через движок цел. Все
гард-тесты по файлам репозитория (`test_ci_config.py`, `test_crash_handler.py`, `test_platform.py:183`,
`test_ui_panels.py:306,325,369,400`, `test_engine_compat.py:91`) окружения не требуют — они гоняются
везде.

---

## 3. Уровни проверок: что каждая ловит и чего не ловит

| № | Команда | Время | Нужен SDK | Ловит | НЕ ловит |
|---|---|---|---|---|---|
| 1 | `vn content lint` | ~1 с | нет | 33 диагностики: схемы деклараций, именование, обязательные файлы, пары `scene.yaml`+`scene.rpy`, граф сцен, недостижимость и тупики (серьёзность по `status`, G15), исчезновение выпущенных id, LFS-покрытие сырцов | ничего внутри `.rpy`, ничего в рантайме, свежесть генерата, бюджет памяти сцены |
| 2 | pytest (518) | секунды | частично | логику модулей `vn.*`; инварианты конфигов CI (включая «вариантные прогоны — в nightly»); гард-тесты по файлам репозитория (обработчик краха, Steam-фасад, экран достижений, `build.archive`, токены `gui.*`, `API_LEVEL`); рантайм-гейт паков — **исполнением** блоков `init python` из `.rpy` на заглушке `store` | `cli.py` кроме `pack build`, `analyze.py`, `scaffold.py`, `psd.py`, `devloop.py`, поведение `game/framework/**` в рантайме |
| 3 | `vn build --check` | секунды | да, если есть главы | несвежий генерат (побайтово), несвежие ассеты, ошибки разметки PO, **бюджеты G19 и бюджет памяти сцены** (два разных fail-режима, `cli.py:176-203`) | падения в рантайме, вёрстку экранов, побитые байты выходов в `game/assets` (сверяется `src_hash`, не выход) |
| 4 | `renpy.sh . lint` | ~10 с | да | движковые проблемы: неопределённые образы/метки, синтаксис `.rpy` во **всём** `game/` | логику ветвления, вёрстку, производительность |
| 5 | `vn test oversample --scale 2` | ~10 с | да | **единственная** проверка, что отгружаемые `@2`-варианты движок реально подхватит: зовёт настоящий `Image.get_oversampled_image()` на настоящем `game/assets` | всё остальное; это одна узкая проверка ADR-0012 |
| 6 | `vn test smoke` | 10-20 с локально | да | реальные падения (`traceback.txt`), недостижимую сцену (`FAIL: vn_scene_unavailable`), превышение `cold_start_s`, фактический путь по меню | ветки, которые вы не перечислили в `--picks`; вёрстку (кроме экранов из `VN_AUTOPILOT_SCREENS`); события геймпада; инициализацию Steam и `owned()==False` |
| 7 | `vn save check` + `vn save corpus` | секунды / ~40 с | corpus — да | битые фикстуры; поломку загрузки старого сейва; **исполнение миграции `0002`** на фикстуре `schema1-demo` | миграции, для которых нет фикстуры со «своей» исходной схемой (сейчас в корпусе только переход 1 → 2) |
| 8 | `vn release validate --flavor <f>` | ~10 с | да | **21 тема проверок** в `validate_release` (`release.py:525-750`), включая новую «зрелость контента» (`early_content` против `status` глав): схема `project.yaml`, флейвор, паки (строка на каждый), lint, LFS-шрифты, свежесть ассетов и генерата, видео, бюджеты, провенанс, декларации DAZ/VaM/Sims4, покрытие переводов, **озвучка**, лицензии, хранилище сырцов, версия манифеста, git sha, сейв-корпус | ничего нового: **своих правил у гейта нет**, он агрегирует существующие (`release.py:526-528`). Не отличает draft-профиль ассетов от full; Steam-префлайта нет вовсе |
| 9 | `vn test corpus --scenes N --images M` | секунды-минуты (1,8 с на 100 сцен, 62 с на 20 000) | да | **масштаб конвейера числами**: время и память каждой стадии на синтетическом проекте заданного размера, объём генерата на сцену, идемпотентность повторной компиляции, доли бюджетов G19, худшая сцена модели памяти. Ловит то, чего не видно на демо-объёме: жёсткие обрывы (`ARG_MAX` в build-bridge) и сверхлинейные стадии | рантайм игры (корпус не запускается), энкод боевых 4K, ветки голоса и локализации, другие ОС — [32](32-performance-and-scalability.md) §7.5 |

**Сколько строк печатает гейт.** Тем — 21, но три из них могут промолчать: покрытие переводов
(только при заданном `release_coverage_min`), озвучка (только при непустом покрытии) и лицензии
(только при непустых декларациях) — у них нет безусловной `else`-ветки. Строки про DAZ / VaM / Sims4,
наоборот, печатаются **всегда**, даже при нуле деклараций. Строка про паки печатается на каждый пак
флейвора. Фактически на этом чекауте: **public — 20 строк** (18 PASS + **2 WARN**, 0 FAIL, exit 0),
**patron — 21 строка** (`packs: [ep_beach, nsfw]` даёт две строки, `early_content: true` — зелёную),
20 PASS + 1 WARN, exit 0. Штатные WARN сейчас два:
`озвучка: 14 черновых дублей (draft) — ru: ch01_s010_0001` и (только у `public`)
`зрелость контента: ни одна глава ещё не доведена до status=release (ch01)` — гейт зрелости
самоактивирующийся и станет строгим с первой главой `status: release`
([29 §5.1](29-build-and-release.md#maturity-gate-rule)). `ok` становится `False` **только** на
FAIL (`release.py:532-536`), WARN релиз не валит — жёлтая строка в выводе это норма, а не поломка.

### Где именно вызывается `renpy lint`

Важная деталь: **`vn` никогда не вызывает движковый `renpy lint` сам.** Во всём тулинге SDK-исполняемый файл запускается для `vn play`, `vn dev`, `vn package`, автопилота (`_autopilot_run`, `cli.py:1509`), `vn test oversample` (`cli.py:1646`) и парсер-моста `vn_analyze` (`tools/vn/src/vn/content/analyze.py`). Движковый lint запускается **только из CI-конфигов**:

- `.github/workflows/ci.yml:86` — `xvfb-run -a bash "$RENPY_SDK/renpy.sh" . lint`
- `.github/workflows/canary.yml:49` — то же на свежайшем Ren'Py

Локально его надо запускать руками. Ren'Py не имеет headless-режима (G23) — на Linux нужен `xvfb-run`, на Windows окно просто открывается и закрывается.

---

## 4. Smoke-автопилот — IMPLEMENTED

`vn test smoke` (`cli.py:1571-1626`) + `_autopilot_run` (`cli.py:1509-1569`) + рантайм `vn_qa` (`game/framework/00_core/030_flow.rpy:91-211`).

### 4.1. Механизм: прогон ВНУТРИ процесса игры

Никакого управления окном снаружи. Автопилот — это код, который на время прогона подкладывается в игру:

1. **Предусловия** (`cli.py:1518-1522`): `RENPY_SDK` резолвится, иначе `Ren'Py SDK не найден (RENPY_SDK) — vn doctor подскажет`; существует `game/generated/manifest.json`, иначе `game/generated/ пуст — сначала vn build`.
2. **Каталог артефактов вычищается и создаётся заново** (`cli.py:1524-1526`): `.vncache/smoke` для smoke, `.vncache/corpus` для корпуса.
3. **Инъекция кода** (`cli.py:1492-1506` — шаблон `_AUTOPILOT_RPY`, `:1530-1535` — запись): `game/generated/qa/` полностью пересоздаётся, туда пишется временный `autopilot.gen.rpy`:

```renpy
label main_menu:
    if not vn_qa.autopilot_active():
        $ renpy.quit(save=False)   # осиротевший прогон-файл вне smoke: не играем сами с собой
    # Одно выражение, без runtime-import: rollback-лог записал бы модуль в сейв.
    $ vn_qa.autopilot_boot()
    return

init python:
    if vn_qa.autopilot_active():
        config.overlay_screens.append("vn_autopilot")

screen vn_autopilot():
    timer 0.6 action Function(vn_qa.autopilot_tick) repeat True
```

   Две независимые страховки: пречистка `qa/` и env-гейт внутри самого файла — осиротевший `.rpyc` от жёстко убитого прогона без `VN_AUTOPILOT` мёртв.
4. **Запуск** (`cli.py:1540-1546`): `subprocess.Popen([<sdk>/renpy.exe|renpy.sh, <root>], env=…)`, на не-Windows — `start_new_session=True`. `traceback.txt` в корне удаляется заранее, поэтому его появление после прогона — надёжный признак падения.
5. **Уборка в `finally`** (`cli.py:1560-1567`): удаляются `autopilot.gen.rpy` и его `.rpyc`, затем `qa/` (best-effort `rmdir`).

Обратите внимание: `label main_menu` переопределяется целиком. В контексте главного меню Ren'Py оверлеи и таймеры не тикают — поэтому автопилот и не пытается «нажать Start», он делает `return` и передаёт управление обычному потоку.

### 4.2. Протокол переменных окружения

| Переменная | Кто ставит | Кто читает | Эффект |
|---|---|---|---|
| `VN_AUTOPILOT=1` | `cli.py:1538`, всегда | `030_flow.rpy:106-107` | Главный гейт: `autopilot_active()` — это буквально `"VN_AUTOPILOT" in os.environ` |
| `VN_AUTOPILOT_DIR` | `cli.py:1538`, всегда | `030_flow.rpy:112,144,172,190` | Каталог артефактов: `shot%03d.png`, `startup.txt`, `picks.log`, `screen_<name>.png`, `RESULT.txt`, `state.json`, `gallery.json` |
| `VN_AUTOPILOT_PICKS` | `--picks` (`cli.py:1594`); в `save corpus --add` захардкожено `"0,1"` (`cli.py:1415`) | `030_flow.rpy:137` | Индексы через запятую, **по одному на каждое встреченное меню** |
| `VN_AUTOPILOT_LANG` | `--lang` (`cli.py:1594`) | `030_flow.rpy:155-159` | `renpy.change_language(lang)`; маркер `"@source"` → `change_language(None)` |
| `VN_AUTOPILOT_SAVE_AT` | `save corpus --add`, захардкожено `"4"` (`cli.py:1415`) | `030_flow.rpy:124-127` | На этом тике вызывается `renpy.save("1-1")` |
| `VN_AUTOPILOT_LOAD` | прогон корпуса, `"1-1"` (`cli.py:1458`) | `030_flow.rpy:162-164` | `renpy.load(slot)` прямо из `autopilot_boot` |
| `VN_AUTOPILOT_SCREENS` | **ни один флаг CLI её не ставит** — только наследование из `os.environ` (`cli.py:1538`) | `030_flow.rpy:166-184` | Список экранов через запятую: `show_screen` → `renpy.pause(0.3)` → `screenshot` → `hide_screen` |

`VN_AUTOPILOT_SCREENS` флага CLI по-прежнему не имеет — только наследование из окружения. Зато с этой итерации переменная **выставляется в CI**: ночная джоба `controller-first` задаёт `VN_AUTOPILOT_SCREENS=main_menu,preferences,gallery,chapter_select` (`nightly.yml:143`). Локально:

```bash
VN_AUTOPILOT_SCREENS=gallery,achievements,preferences vn test smoke --picks 0,0    # bash
$env:VN_AUTOPILOT_SCREENS="gallery,achievements,preferences"; vn test smoke --picks 0,0   # PowerShell
```

Это же — единственный способ снять вёрстку **экрана достижений**: прохождение сцен его не открывает. Оговорка: состояния «скрыто» и «не получено» в боевых декларациях не воспроизводятся (обе ачивки видимы и к концу прогона получены), поэтому «???» и «Не получено» на скриншот сегодня не попадут — см. открытый пункт в [15-gallery.md](15-gallery.md).

Тем же наследованием окружения (`cli.py:1538` — `env = dict(os.environ, VN_AUTOPILOT="1", …)`) до движка доезжает **`RENPY_VARIANT`** — единственный способ проверить controller-first вёрстку без железа (ADR-0014):

```bash
RENPY_VARIANT="steam_deck medium touch" vn test smoke --picks 0,0   # Deck: авто-масштаб 1.4, фуллскрин
RENPY_VARIANT="steam_big_picture" vn test smoke --picks 0,0         # ТВ: оверлеи ушли на gui.overscan_pad
```

**И это тоже теперь гоняет CI.** Джоба `controller-first` (`nightly.yml:85-152`) — матрица двух профилей (`steam_deck medium touch`, `steam_big_picture`), прогон `vn test smoke --picks 0,0` с набором экранов выше, шоты артефактом `controller-shots-<profile>-<run_id>`, **гейта нет**: поломка вёрстки видна на картинке, а не в коде выхода. Джоба живёт в `nightly`, а не в `ci` — прогон движка на профиль стоит минуты, MR-пайплайн держим под 10 минут (G15); отсутствие `RENPY_VARIANT` в `ci.yml` проверяет `test_ci_config.py: test_nightly_runs_controller_first_variants`.

Чего этот прогон **не** проверяет: событий геймпада (автопилот их не шлёт), инициализации Steam, оверлея и `dlc_installed` — только вёрстку. Подробности — [39-platforms.md](39-platforms.md) §7.1.

### 4.3. Тайминги: продвижение, выбор, подтверждение

- **Продвижение диалога:** оверлей `vn_autopilot` дёргает `vn_qa.autopilot_tick` каждые **0.6 с**; тик делает скриншот и `renpy.queue_event("dismiss")` (`030_flow.rpy:109-128`).
- **Выбор в меню:** `game/framework/20_ui/screens/choice.rpy:53-54` — `timer 1.0 action Function(vn_qa.autopilot_choose, items) repeat True`. Именно таймер, а не выражение экрана: side effect в screen-выражении запрещён, потому что экран переоценивается предикцией и каждым тиком оверлея, и счётчик picks дрейфовал бы (`030_flow.rpy:131-133`).
- **Модальные подтверждения:** `game/framework/20_ui/screens/core_screens.rpy:409-410` — `timer 0.8 action yes_action repeat True`. Автопилот всегда отвечает «да».
- **Семантика picks** (`030_flow.rpy:134-143`): действуют только пункты с `action is not None`; кончились значения — берётся `0`; индекс больше числа пунктов — прижимается к последнему; если выбранный пункт заблокирован — берётся первый действующий.

### 4.4. ЖЕЛЕЗНОЕ ПРАВИЛО: `autopilot_choose` обязан вернуть `renpy.run(action)`

```python
        # ВАЖНО: значение action обязано вернуться из Function — интеракция меню
        # завершается только non-None результатом action (иначе вечное перевыбирание).
        return renpy.run(items[idx].action)
```

`030_flow.rpy:148-150`. Если убрать `return` — `Function(...)` вернёт `None`, интеракция меню не завершится, таймер выберет пункт снова и снова, и прогон повиснет до `--timeout`. Симптом в логе: `picks.log` растёт бесконечно, `RESULT.txt` не появляется. То же правило действует для любого нового автопилот-хука в экране с меню.

### 4.5. ЗАПРЕТ: синтетический ввод на рабочий стол

Автопилот работает **только внутри процесса игры** (`cli.py:1510-1511`: «Никакого синтетического ввода на рабочий стол — только in-process автоматизация»; `030_flow.rpy:103-105`). Никогда не добавляйте в тулинг `SendKeys`, `pyautogui`, `xdotool` и прочую эмуляцию клавиатуры/мыши по окну: такой «тест» кликает по случайному окну на машине владельца, зависит от фокуса и раскладки, не воспроизводится в CI и не даёт ни одного детерминированного артефакта. Всё, что нужно автоматизировать, добавляется как функция в `vn_qa` и дёргается из таймера экрана.

### 4.6. Артефакты прогона и вердикт

`autopilot_finish(reason)` (`030_flow.rpy:186-211`) пишет `RESULT.txt`, `state.json` (снапшот `vn_state`), `gallery.json` (`{unlocked, total, ids}` из `vn_gal`) и делает `renpy.quit(save=False)`. Вызывается из двух меток:

- `label vn_end_of_content` → сначала `autopilot_screens()`, затем `autopilot_finish("OK: vn_end_of_content")` (`030_flow.rpy:235-240`);
- `label vn_scene_unavailable` → `autopilot_finish("FAIL: vn_scene_unavailable")` (`030_flow.rpy:227-229`).

Реальное содержимое `.vncache/smoke/` от прогона `vn test smoke --picks 0,0` на этом чекауте
(2026-08-18, macOS, RENPY_SDK 8.5.3):

```
RESULT.txt    OK: vn_end_of_content
startup.txt   1.25                       ← cold start, секунды (бюджет 30)
picks.log     menu 0 -> pick 0 (ch01_s010_m001)
              menu 1 -> pick 0 (ch01_s020_m001)
state.json    {"ch01.PY2": false, "ch01.met_mira": true, "g.PY2": false,
               "g.route": "prologue", "g.mira_outfit": "casual", "vn_save_schema": 2}
gallery.json  {"unlocked": 4, "total": 5,
               "ids": ["cg_ch01_finale","cg_ch01_rooftop","mov_ch01_ambient","cg_ch01_concept"]}
shot000.png … shot018.png (19 кадров)
```

Число кадров и `g.mira_outfit` зависят от маршрута: `--picks 0,0` даёт 19 кадров и наряд `casual`.
`screen_*.png` в этом прогоне нет — `VN_AUTOPILOT_SCREENS` не выставлялась (см. § 4.2).

Логика вердикта (`cli.py:1596-1626`), по порядку:

1. Таймаут + есть `traceback.txt` → печатаются последние 1500 символов, `smoke: игра упала с traceback (и висела до таймаута)`.
2. Таймаут без traceback → `игра не завершилась за N c — прогон снят (дерево процессов убито)`.
3. Печатается число `shot*.png`.
4. Читается `startup.txt` как float и **сравнивается с `budgets.cold_start_s` из `project.yaml`** (сейчас `30`, норма G19). Превышение = exit 1. Комментарий в `project.yaml` калибрует ожидания: CI-раннер на llvmpipe ~14 с, RTX ~1 с. Это **единственное** место, где `cold_start_s` вообще форсится — ни в `ci.yml`, ни в релизном гейте его нет.
5. Печатается каждая строка `picks.log` как `путь: …`.
6. Есть `traceback.txt` → fail.
7. `returncode != 0` или вердикт не начинается с `OK` → fail.

**Таймаут и убийство процесса** (`cli.py:1549-1559`): `--timeout` по умолчанию 180 с (`cli.py:1574`). На Windows — `taskkill /T /F /PID <pid>`, потому что `renpy.exe` это лаунчер и умереть должно всё дерево; на POSIX — `os.killpg(os.getpgid(pid), SIGKILL)`; затем `popen.wait(timeout=10)`.

### 4.7. `--lang`: защита от ложно-зелёного прогона

`cli.py:1578-1591`: если `--lang` совпадает с исходным языком (`source_language(root).code`), он подменяется маркером `"@source"` — `tl/<code>/` для исходного языка не существует по определению. Иначе требуется существующий `game/tl/<lang>/`, иначе команда падает: `языка … нет в game/tl/ — выполните vn loc import (change_language молча показал бы исходный язык — ложно-зелёный прогон)`. Про сам round-trip переводов — [14-localization.md](14-localization.md).

### 4.8. `.vncache/langqa/` — артефакт-сирота

В некоторых чекаутах в `.vncache/langqa/` лежат `01_prefs_ru.png … 04_prefs_ru_again.png` и `RESULT.txt` с содержимым `OK`. **Ни одна строка кода в репозитории этого не производит:** автопилот пишет только `shot%03d.png`/`screen_<name>.png` и `RESULT.txt` вида `OK: <причина>`, а `grep -rn langqa tools/ game/ docs/ .github/` даёт ноль. Это ручной артефакт разовой языковой проверки; на текущем чекауте каталога нет вовсе (`.vncache/` — гитигнор, состав зависит от машины). Не ссылайтесь на него как на воспроизводимый прогон и не пытайтесь «починить» — воспроизвести его нечем.

---

## 4а. `vn test oversample` — единственная проверка ADR-0012 движком

**IMPLEMENTED**, и ни один документ хендбука до сих пор её не описывал.

Весь смысл вариантов `<name>@2` в том, что подставляет их **Ren'Py**, а не наш конвейер: движок
включает автоподбор только для имени без собственного `@N` и решает по физическому размеру экрана
(`renpy/display/im.py: get_oversampled_image`). Проверить это честно можно только внутри движка —
чем и занимается связка `vn test oversample` (`cli.py:1628-1651`) + `game/framework/90_debug/030_oversample.rpy`.

Как работает:

1. Рантайм-файл регистрирует движковую команду: `renpy.arguments.register_command("vn_oversample", …)`
   (`030_oversample.rpy:16`).
2. CLI требует `RENPY_SDK` и непустой `game/generated/manifest.json`, затем запускает
   `renpy.exe <root> vn_oversample --scale <N>` (`cli.py:1640-1647`).
3. Внутри игры подменяется `renpy.display.draw.draw_per_virt` (эмуляция «физический экран крупнее
   виртуального в N раз») и на каждый собранный ассет зовётся настоящий
   `im.Image(rel).get_oversampled_image()`; результат сверяется с ожидаемым вариантом `@N`.
4. CLI ищет в выводе строку `oversample: OK`; её отсутствие — exit 1 с последними 1200 символами
   вывода.

Фактический вывод на этом чекауте:

```
$ vn test oversample --scale 2
oversample @2: проверено 22, поднято до варианта 13
oversample: OK
```

«Проверено 22, поднято 13» — нормально: `@2`-вариант существует не у всех классов
(`ui/` его не имеет, `mov` объявлен как `variants: [1]`), а у мастеров, из которых `@2` собрать
нельзя, вариант пропускается.

Команда стоит в `.github/workflows/ci.yml:90-91` («Оверсэмпл подтверждён движком
(ADR-0012)»). В `nightly.yml` и `canary.yml` её нет.

---

## 5. Сейв-корпус — IMPLEMENTED, миграция проверяется по-настоящему

### 5.1. Зачем

Игрок ставит апдейт поверх своего прохождения. Сейв Ren'Py — это pickle состояния плюс ссылки на позиции скрипта; любая правка сцены, переименование метки или бамп `save_schema` могут сделать старый слот незагружаемым. Корпус — единственный автоматический ответ на вопрос «сейвы игроков переживут этот релиз?».

### 5.2. `vn save check` — офлайн, SDK не нужен

`cli.py:1323-1351`. Открывает каждый `ci/fixtures/saves/*.save` как zip, читает член `json`, требует целочисленный `vn_save_schema`, печатает схему / версию / сцену. **Без unpickle** — то есть работает даже если сейв не загружается движком. Эти три ключа кладёт `config.save_json_callbacks` (`game/framework/00_core/001_boot.rpy:31-36`).

```
$ vn save check
 ✓ schema1-demo.save: schema 1, версия 0.1.4+dd1cb3e, сцена ch01_s010
 ✓ schema2-demo.save: schema 2, версия 0.1.0+48d19a3, сцена ch01_s020
save check: OK (2 фикстур)
```

### 5.3. Линия statement-имён — почему 52 `.rpyc` лежат в git

Ren'Py адресует позиции скрипта **именами стейтментов**, которые выдаёт компилятор. Сейв валиден только против того `.rpyc`, с которым создавался: перекомпиляция чужим деревом выдаёт другие имена, и фикстура перестаёт грузиться. Решение проекта (`_rpyc_line_restore`, `cli.py:1354`) — держать «линию имён» в git:

```
ci/fixtures/rpyc-line/     52 файла .rpyc, 312 КБ
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
| `_rpyc_line_restore(root)` (`cli.py:1354-1372`) | Для каждого `*.rpyc` в `ci/fixtures/rpyc-line/` копирует его поверх `game/<rel>` — **только если рядом существует `game/<rel>.rpy`**. Возвращает счётчик | Устаревшие записи для удалённых исходников молча игнорируются |
| `_rpyc_line_snapshot(root)` (`cli.py:1375-1388`) | `rmtree` папки фикстур, затем копирует **все** `.rpyc` из `game/` | Без фильтров: снимок берёт то, что лежит в дереве прямо сейчас |

### 5.4. Добавить фикстуру: `vn save corpus --add <имя>`

`cli.py:1391-1437`. Порядок:

1. `.vncache/corpus-savedir` вычищается.
2. Автопилот прогоняется с `VN_AUTOPILOT_SAVE_AT=4` и `VN_AUTOPILOT_PICKS=0,1` (`cli.py:1415`) — **обе величины захардкожены**, точку сохранения и маршрут флагом не задать.
3. Слот ищется как `sorted(savedir.glob("1-1*.save"))`: Ren'Py 8.5 добавляет к имени токен локации (`1-1-LT1.save`, `cli.py:1418-1419`).
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

`cli.py:1439-1480`:

1. `_rpyc_line_restore(root)` и сообщение `линия имён: N .rpyc восстановлено из ci/fixtures/rpyc-line/ (G6)` (`cli.py:1441`).
2. Нет `*.save` → fail с подсказкой создать.
3. На каждую фикстуру: `.vncache/corpus-savedir` пересоздаётся, фикстура кладётся **двумя именами** — `1-1-LT1.save` и `1-1.save` (какое имя ждёт SDK, зависит от версии, `cli.py:1454-1455`), автопилот запускается с `VN_AUTOPILOT_LOAD=1-1` и `--savedir` (`cli.py:1458`).
4. Критерий прохода (`cli.py:1467-1468`): не было таймаута **И** `RESULT.txt` начинается с `OK` **И** `state.json["vn_save_schema"] == project["save_schema"]`. При падении печатаются последние 1200 символов `traceback.txt`.

Фактический вывод на этом чекауте:

```
$ vn save corpus
линия имён: 52 .rpyc восстановлено из ci/fixtures/rpyc-line/ (G6)
 ✓ schema1-demo.save: OK: vn_end_of_content; schema после загрузки: 2 (цель 2)
 ✓ schema2-demo.save: OK: vn_end_of_content; schema после загрузки: 2 (цель 2)
save corpus: OK (2 фикстур загружены и мигрированы)
```

**Побочный эффект, о котором надо знать:** `_rpyc_line_restore` перезаписывает `game/**/*.rpyc`
байтами из фикстурной линии. Это гитигнор-зона, и следующий запуск игры/сборки перекомпилирует их —
но если сразу после корпуса вы полезли отлаживать рантайм, помните, что `.rpyc` в дереве не
обязательно соответствуют текущим `.rpy`.

Миграции CLI не вызывает — они исполняются **в игре**, в `label after_load` (`game/framework/00_core/020_state.rpy:82-107`): сейв из будущей схемы блокируется (`renpy.block_rollback()` + сообщение + `full_restart()`), сейв из прошлой — прогоняет `vn_state.run_migrations()` и поднимает `vn_save_schema` ровно до фактически применённой миграции, не до цели. Подробности модели состояния — [07-backend.md](07-backend.md).

Реальный выход прогона (`.vncache/corpus/`): `RESULT.txt` = `OK: vn_end_of_content`, `state.json` со схемой 2, `picks.log` в одну строку `menu 1 -> pick 0 (ch01_s020_m001)` (счётчик меню приехал из сейва), кадры `shot003.png … shot018.png` — нумерация продолжается с сохранённого значения `_vn_ap_shot`, а не с нуля. Каталог перезаписывается на каждой фикстуре, так что после прогона в нём лежит выход **последней** из них.

### 5.6. Грабли корпуса

- **Ren'Py 8 подписывает слоты per-machine токеном** (в zip есть член `signatures`). Сейв, созданный на другой машине или в другой инсталляции, при загрузке даёт модальный `confirm`. Автопилот проходит его автоматически — таймер жмёт «да» каждые 0.8 с (`core_screens.rpy:409-410`). Руками при отладке этот диалог придётся подтверждать самому; это не поломка.
- **Фикстур две, и одна из них на старой схеме — миграция проверяется по-настоящему** (с 2026-08-08). `ci/fixtures/saves/schema2-demo.save` (8912 Б) — на текущей схеме: `{"vn_save_schema": 2, "vn_version": "0.1.0+48d19a3", "vn_scene": "ch01_s020"}`. `ci/fixtures/saves/schema1-demo.save` (10746 Б) — `vn_save_schema=1`, сцена `ch01_s010`; при `project.yaml:3` `save_schema: 2` на ней исполняется ветка `_loaded_schema < _target_schema` в `after_load`. Прогон печатает `schema после загрузки: 2 (цель 2)`, а в `log.txt` появляется `[vn] migration 0002` — доказательство, что миграция реально отработала в игре, а не «сейв просто открылся».
- **Проверяется ровно один переход, 1 → 2.** Каждый следующий бамп `save_schema` требует своей фикстуры, снятой **до** бампа (§9.8) — иначе новая миграция снова окажется непроверенной.
- **Обязательные фикстуры из `ARCHITECTURE.md:3681`** (сейв внутри переименованной сцены, «грязный» call-стек, сейв релиза N−1, DLC-контент без DLC) — **NOT IMPLEMENTED**, их просто нет.
- **Регрессия `rpyc-compat`** (`ARCHITECTURE.md:3508,3602-3605`): пара прогонов «с переносом `.rpyc` обязан пройти / без — обязан упасть». Негативной ветки в коде нет вообще — **NOT IMPLEMENTED**. Без неё нельзя доказать, что механизм переноса линии вообще работает.

---

## 6. Что не покрыто тестами

**Модули, которых тесты почти или совсем не касаются** (проверено грепом всех `from vn.…` в `tools/vn/tests/`; `vn.cli` с 2026-08-08 импортируется, но ровно ради одной команды):

| Модуль | Строк | Последствие |
|---|---|---|
| `tools/vn/src/vn/cli.py` | **2117** | Покрыт точечно: `pack build` через `click.testing.CliRunner` (`test_release.py`, 3 теста) плюс `test_cli.py` (12) — реестр заглушек, перечень доменов против нормы C13, маппинг флагов `test corpus`/`voice tts` на публичный API, `release android status/build`. Итого около 6 из 68 листовых команд. Не покрыты: разбор аргументов и коды выхода остальных команд, `_autopilot_run`, `_rpyc_line_restore/_snapshot`, `save_check`, `save_corpus`, `test_smoke`, `test_oversample`, `_check_budgets` |
| `tools/vn/src/vn/content/analyze.py` | 70 | Мост к парсеру Ren'Py не проверен вообще (ноль импортов в тестах); `test_scene_pipeline.py` подсовывает фабрикованные словари анализа |
| `tools/vn/src/vn/content/scaffold.py` | 137 | Генераторы `vn chapter new`, `vn scene new`, `vn scene stub` не проверены |
| `tools/vn/src/vn/assets/psd.py` | 126 | Нарезка PSD не проверена (и не исполнялась ни разу — в репозитории нет ни одного `.psd`, а зона `assets_src/psd/characters/` пуста) |
| `tools/vn/src/vn/devloop.py` | 56 | Watch-цикл `vn dev` не проверен |

**Покрыто частично:** `doctor.py` (153) — только `_lfs_pointer_fonts` и `sdk_path`; `vn/pipeline.py` (581 — это внешний конвейер DAZ/ComfyUI, **не** ассет-конвейер) — только `find_ffmpeg`/`find_ffprobe`; `release.py` (736) — `validate_release` целиком **никогда не исполняется в тестах** (нужны SDK, ассеты и хранилище), но вынесенная из него `early_content_checks` исполняется: ради этого её и сделали отдельной функцией; `repo.py` (43) — используется косвенно, своих тестов нет; `assets/imaging.py` (143) и `assets/render_config.py` (280) — только через `build_assets`.

**Целые подсистемы без автоматической проверки:** рантайм `game/framework/**`, включая `vn_qa` — pytest исполняет его лишь точками (см. ниже про `test_release.py`), остальное берут **статические** гард-тесты: `test_crash_handler.py`, `test_platform.py:183`, `test_ui_panels.py:325,369,400`, `test_achievements.py`, `test_engine_compat.py:91` — все читают исходники регексом или парсером. Исключение появилось у гейта паков: `test_release.py` **исполняет** блоки `init python in vn` / `in vn_build` из `.rpy` на заглушке `store` — единственный способ проверить рантайм-логику без движка); сами `vn save check`/`vn save corpus`; `vn package`, `vn release build`, `vn release steam`, `vn pack validate`, `vn test oversample`. `vn pack build` покрыт.

**Хрупкие константы** — упадут от несвязанного изменения: набор `BASE_OUTPUTS` из **16** имён (`test_compile.py:11-28`) и его переиспользование в `test_verify_regressions.py:84` (оно же — источник cwd-зависимости, §2.1), `assert cov == {"total": 6, "translated": 5, "fuzzy": 0}` (`test_loc.py:124`), `assert sites == 8` (`test_ci_config.py:90` — число мест установки тулчейна в CI; добавили джобу → поправьте константу), `assert len(reg.schemas) >= 15` (`test_schemas.py:11` — «не меньше», поэтому не ломается при росте до 39).

**Инфраструктурные пробелы:** нет `pytest.ini`/`[tool.pytest.ini_options]` и зарегистрированных маркеров; нет джобы `rpyc-compat` (негативная ветка «без переноса `.rpyc` обязан упасть» не существует, то есть работоспособность самого механизма переноса линии не доказана); `game/framework/00_core/engine_compat/tests`, на который ссылается `ARCHITECTURE.md:3612`, **не существует** — контракт-тесты живут в `tools/vn/tests/test_engine_compat.py`; и главное — прогон из корня даёт `1 failed` (§2.1), то есть сегодня «зелёный pytest» требует знания про cwd.

---

## 7. Заглушки и несуществующие команды

| Команда | Статус | Поведение |
|---|---|---|
| `vn test smoke` | IMPLEMENTED | флаги ровно три: `--picks`, `--lang`, `--timeout` (`cli.py:1572-1574`) |
| `vn test oversample` | IMPLEMENTED | флаги `--scale` (по умолчанию 2.0) и `--timeout` (`cli.py:1628-1631`); см. § 4а |
| `vn test replay` | NOT IMPLEMENTED, фаза 2 | `_stub(2)`: жёлтое «эта команда появится в фазе 2», exit **3** (`cli.py:1658-1659`) |
| `vn test paths` | NOT IMPLEMENTED, фаза 2 | `_stub(2)`, exit 3 |
| `vn test screens` | NOT IMPLEMENTED, фаза 3 | `_stub(3)`, exit 3 |
| `vn test perf` | NOT IMPLEMENTED | подкоманды **не существует вовсе** — click ответит usage-ошибкой, exit 2. `ARCHITECTURE.md:3644` её описывает |
| `vn save migrate` | NOT IMPLEMENTED, фаза 3 | `_stub(3)` (`cli.py:1483`); миграции идут в игре, в `after_load` |

**Два класса «нет команды» и их коды выхода.** `_stub(phase)` печатает жёлтое «появится в фазе N» и
даёт **exit 3**; полный список заглушек в проекте: `vn migrate`, `vn shell` (`cli.py:393-394`),
`vn char new|validate|sheet`, `vn save migrate`
(`cli.py:1483`), `vn test replay|screens|paths` (`cli.py:1658-1659`). Команда, которой **не
существует вовсе** (`vn validate`, `vn test perf`, `vn build --use-artifact`), даёт usage error click
и **exit 2**. Путать эти два класса — прямой путь «чинить» то, чего нет.

Докстринг группы всё ещё рекламирует четыре подкоманды и молчит про `oversample`:
`"""QA-прогоны (7.4): smoke, replay, screens, paths."""` (`cli.py:1489`).

Отдельно — флаги, которые **заявлены в `ARCHITECTURE.md` и не существуют**: `vn test smoke --affected --shard N/M --seed <n>` и `--menu-only` (`:3530,3587,3595`), `vn test screens --update-baselines` (`:3617,3720`), `vn save corpus <dir> --report out/savecheck.json` и `--rpyc-regression` (`:3403,3600,3605`), `vn test paths --coverage edges` (`:3638`). Реальные пути артефактов тоже другие: `qa/saves-corpus/`, `tests/save_corpus/<version>/`, `.vncache/qa/smoke/` из `ARCHITECTURE.md` не существуют — есть `ci/fixtures/saves/` и `.vncache/smoke/`.

---

## 8. Кто и что гоняет в CI

Короткая сводка; подробный разбор workflow — [04-development-workflow.md](04-development-workflow.md) §4 и [29-build-and-release.md](29-build-and-release.md).

| Workflow | Триггер | Что из этого файла гоняет |
|---|---|---|
| `.github/workflows/ci.yml` | push в **любую ветку** (`branches: ['**']`, теги не матчатся), + `workflow_dispatch`; `pull_request` намеренно нет — голова PR это тот же push | джоба `lint`: `vn content lint` (`:45`). Джоба с SDK: `vn build` (`:80`) → `vn loc keys --check` (`:83`) → `renpy.sh . lint` (`:86`) → **`vn test oversample --scale 2`** (`:91`) → `vn content compile --check` (`:94`) → `pytest tools/vn/tests -q` (`:97`); артефакт `generated-<sha>` на 30 дней (`:99-102`) |
| `.github/workflows/nightly.yml` | cron `30 2 * * *` + dispatch | Джоба `smoke`: `vn build`, `vn loc import/report` (`:49-53`); **матрица smoke**: `--picks 0,0` / `--picks 0,1 --lang en` / `--picks 1` / `--picks 0,0 --lang pseudo` (`:55-60`); `vn save check` + `vn save corpus` (`:62-65`); релизная сборка обоих флейворов на снесённом `game/generated` (`:70-74`); артефакт `.vncache/smoke/` на 7 дней (`:76-82`). Джоба `controller-first` (`:85-151`): матрица `steam_deck medium touch` / `steam_big_picture`, `vn build` → `vn test smoke --picks 0,0` с `VN_AUTOPILOT_SCREENS`, артефакт `controller-shots-<profile>-<run_id>`. **Внимание:** шаг релизной сборки обоих флейворов сейчас проходит — гейт зрелости контента даёт WARN, пока в проекте нет ни одной главы `status: release`; он покраснеет в тот прогон, где такая глава появится ([29-build-and-release.md](29-build-and-release.md#maturity-gate-rule) §5.1 №4) |
| `.github/workflows/steam-upload.yml` | **только** `workflow_dispatch` (входы `flavor`, `branch`) | `vn release build --flavor <f> --package win/linux/mac` → `vn release steam --flavor <f> --branch <b>` → steamcmd. Кэш `.rpyc` — restore-only. Без секретов `STEAM_USERNAME`/`STEAM_CONFIG_VDF` шаг аплоада — зелёный no-op; при `appid: null` workflow падает раньше. Артефакт — только VDF |
| `.github/workflows/canary.yml` | cron `0 3 * * 1` + dispatch | на **свежайшем** Ren'Py: `vn build` → `renpy.sh . lint` → `pytest tools/vn/tests -q` → `vn test smoke --picks 0,0` (`:46-51`) |
| `.github/workflows/release.yml` | тег `v*` | гейт «тег == `project.yaml: version`» (`:47-54`), затем `vn release build --flavor <public\|patron>` (гейт внутри, `:78-87`); dmg на macOS-раннере (`:97-113`) |

То есть: **smoke и корпус гоняются только ночью** и в canary. Ваш PR их не проверяет — прогоняйте руками перед push, если трогали рантайм, сейвы, локализацию или релизный путь. `vn test oversample`, наоборот, стоит на каждом пуше.

Оба прогона pytest идут **из `tools/vn`** (`ci.yml` — полем `working-directory`, `canary.yml` — подоболочкой `(cd tools/vn && …)`), то есть в той же форме, что у разработчика: красное в CI воспроизводится одной командой локально.

Инварианты всех пяти GitHub-workflow стерегутся `tools/vn/tests/test_ci_config.py` (**14 тестов**): `pip install -r tools/vn.lock` стоит **до** editable-установки (G17) — мест установки **8**, по джобе, `ffmpeg` ставится **до** любого `vn build`, вариантные прогоны живут в `nightly`, а не в `ci`. Плюс пять инвариантов, добавленных 2026-08-18: раскладка команд по пайплайнам (G15 — в частности «корпус масштаба не в `ci`»), `vn release android preflight` стоит **после** `vn build` (на пустом `game/` он зелен всегда и гейт был бы ложно-зелёным), провал внешнего тулчейна не заглушён `|| true`/`continue-on-error` и `voice tts` пиннует бэкенд флагом (иначе на раннере взялся бы первый доступный и записал синтез мастерами в LFS-зону), масштаб корпуса задан явно и ограничен потолком, pytest запускается из `tools/vn`, а второго конфига CI в репозитории нет (`.gitlab-ci.yml` выведен 2026-08-18: полузеркало из трёх джоб, которое документация называла главным). Ещё три теста стерегут сам триггер `ci.yml`: любая ветка, не теги, без `pull_request`.

---

## 9. Чеклисты

Каждый пункт — команда этого проекта. Ожидаемое «зелёное» состояние: `vn doctor` — 8 PASS, `pytest` — 518 passed (из `tools/vn`, § 2.1), `vn release validate --flavor patron` — ни одного FAIL при одном штатном WARN про черновую озвучку. У `--flavor public` FAIL тоже нет (exit 0), но WARN два: к озвучке добавляется зрелость контента — в проекте пока нет ни одной главы `status: release`.

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
(cd tools/vn && .venv/bin/python -m pytest -q)   # НЕ из корня — §2.1
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

Ни один FAIL в гейте. Строка про корпус сейчас зелёная — `PASS  сейв-корпус: 2 фикстур`.

**«Все PASS» не эталон.** Сегодня зелёный гейт (`--flavor patron`) выглядит как 21 строка, одна из которых жёлтая:
`WARN озвучка: 14 черновых дублей (draft) — ru: ch01_s010_0001`. Это штатное состояние демо-главы
(озвучка есть, но `status: draft`), а не поломка. У `--flavor public` к ней добавляется вторая жёлтая —
`WARN зрелость контента: ни одна глава ещё не доведена до status=release (ch01)`, — и это тоже exit 0. `ok` становится `False` только на FAIL. Какие WARN
ещё бывают штатными: «ci/release-manifest.json нет» (релиз с ним уедет), «сейв-корпус: 0 фикстур»
(пустой корпус релиз не остановит), «шрифты UI: game/fonts пуст», «хранилище сырцов недоступно».
Отдельно помните, что озвучка **умеет** дать FAIL на полностью написанной главе: `holes` — реплики
главы, не покрытые манифестом языка, который для этой главы уже начали озвучивать (частично
озвученная глава хуже неозвученной — игрок слышит обрыв).

### 9.4. Новая глава

```bash
vn content lint                            # entry_scene, scene_order, exits, достижимость
vn build
vn content graph                           # глазами: нет висящих узлов и неожиданных тупиков
vn test smoke --picks <по одному индексу на каждое меню самого длинного пути>
# … и по отдельному прогону на каждую развилку — vn test paths НЕ существует
vn test smoke --picks … --lang en
vn loc keys && vn loc extract              # say-id и PO для переводчиков
(cd tools/vn && .venv/bin/python -m pytest -q)   # НЕ из корня — §2.1
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
vn loc report                              # покрытие и fuzzy: сейчас de/en/pseudo — 136/136, fuzzy 0
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
2. Откат тулчейна: `git log tools/vn.lock` → `git revert <bump-commit>` → `pip install -r tools/vn.lock && pip install -e tools/vn`. **Рецепт рабочий:** лок ставится первым во всех восьми джобах установки тулчейна (`ci.yml` ×2, `nightly.yml` ×3, `canary.yml`, `release.yml`, `steam-upload.yml`), так что revert файла действительно меняет версии в CI. Остаточный риск: транзитивные зависимости в локе не закреплены (например `pygments` от `pytest`) — если поплыло что-то из них, revert не поможет.
3. Если сломан компилятор, а не lock: последний зелёный генерат лежит артефактом CI (`generated-<sha>`, 30 дней, `ci.yml:99-102`) — скачать и распаковать в `game/generated/`, игра запустится без локальной компиляции. Runbook обещает `vn build --use-artifact <sha>` «с фазы 1» — флага **не существует**: `vn build` принимает только `--check` и `--profile` (`cli.py:89-91`), а строка `use-artifact` во всём тулчейне встречается один раз, в заголовке схемы `tools/schemas/gen_manifest@1.schema.json`. Только руками.

**Симптом B — CI красный, локально зелёно:**

1. Диффа окружений быть не должно — CI ставит тот же тулчейн, но **строго по локу**: `pip install -r tools/vn.lock`, затем `pip install -e "tools/vn[dev]"`. Локально без первой команды версии могут разойтись — повторите обе.
2. `git stash -u`, затем `vn content lint` на чистом чекауте: незакоммиченные локальные файлы регулярно «чинят» сборку невидимо.

**Эскалация:** владельцы `/tools/` по CODEOWNERS; оба недоступны — релиз переносится, «хотфиксы поверх непонятного пайплайна запрещены». После инцидента — post-mortem/ADR в `../adr/`, если причина архитектурная.

Симптом C, которого в runbook нет, но он самый частый в ночном режиме: **ночной smoke красный, локально зелёный** → скачайте артефакт `smoke-shots-<run_id>` (7 дней, `nightly.yml:76-82`), посмотрите `RESULT.txt` и последний `shot*.png`. `FAIL: vn_scene_unavailable` = jump на несуществующую метку; таймаут без traceback = скорее всего повисшее меню (см. §4.4).

---

## Как изменить / Как расширить

**Добавить pytest-тест.** Файл `tools/vn/tests/test_<модуль>.py`, функции `def test_*`, докстринг модуля — одной строкой про норму, которую тест защищает (так написаны все 27). Фикстура `repo_root` доступна из `conftest.py`, синтетический корень с tiny-профилем — из `helpers.py` (`mk_root`, `img`). Нужен SDK — копируйте паттерн `test_engine_compat.py:9-14`; нужен ffmpeg — модульный `pytestmark`, как `test_video.py:13-17`, **или** ранний `pytest.skip`, как `test_voice.py:187-189`. Не трогайте настоящий рабочий каталог: `tmp_path` + `mk_root`/`_copy_skeleton`. **Не импортируйте один тестовый модуль из другого** — это ломает прогон из корня (§2.1); общее выносите в `helpers.py`.

**Добавить проверку в релизный гейт.** Только `tools/vn/src/vn/release.py`, внутри `validate_release`, через локальный `add(state, msg)`. Правило проекта — у гейта **нет своих правил**, он агрегирует существующие проверки конвейера, чтобы не расходиться с `vn build` (`release.py:526-528`). Реализуйте проверку в профильном модуле, в гейт добавьте только вызов. Решите заранее, будет ли у проверки безусловная `else`-ветка: без неё гейт молчит, когда проверять нечего, и число строк на экране перестаёт совпадать с числом тем.

**Добавить действие автопилота.** Функция в `init -999 python in vn_qa` (`030_flow.rpy:91`) + переменная окружения + `timer … action Function(...)` в нужном экране. Помните §4.4: если функция обслуживает интеракцию (меню, confirm), она обязана вернуть результат `renpy.run(action)`. Чтобы флаг CLI её включал — новая опция в `test_smoke` и передача через `extra_env` в `_autopilot_run` (`cli.py:1594`).

**Добавить проверку движком (не pytest).** Образец — `vn test oversample` (§4а): рантайм-файл в
`game/framework/90_debug/` регистрирует команду через `renpy.arguments.register_command`, CLI
запускает `renpy.exe <root> <команда>` и ищет в выводе строку-вердикт. Это единственный способ
проверить решение, которое принимает движок, а не наш код. Файл обязан лежать в `90_debug/` — он
исключается из релиза (`options.rpy:31`).

**Снять фикстуру для следующего бампа схемы** — см. §9.8, шаг 1. Это единственный способ получить фикстуру со **старой** схемой, и делать это надо ДО бампа. Для перехода 1 → 2 такая фикстура уже есть (`schema1-demo.save`) — повторите приём на 2 → 3.

**Следующим CLI-тестом** логично закрыть `_rpyc_line_restore` / `_rpyc_line_snapshot`: чистые функции над файловой системой, `tmp_path` достаточно, SDK не нужен. Шаблон уже есть — `_run_pack_build()` (`test_release.py:141-146`): `click.testing.CliRunner` + `monkeypatch.chdir(root)`, чтобы `_root()` нашёл синтетический корень. Дальше — тот же `CliRunner` на `_stub`-командах (контракт exit 3).

---

## Чего НЕ делать

- **Не слать синтетический ввод на рабочий стол.** `SendKeys`/`pyautogui`/`xdotool` по окну игры — запрещённый приём (§4.5). Всё автоматизируется in-process через `vn_qa`.
- **Не писать автопилот-хук без `return renpy.run(action)`** — прогон повиснет до таймаута, и причина будет неочевидной (`030_flow.rpy:148-150`).
- **Не считать зелёный `pytest` доказательством работоспособности игры.** 518 тестов почти не касаются `cli.py` (покрыто ~7 из 69 команд) и не исполняют `game/framework/**`. Без SDK скипнутся 10, без ffmpeg — 12, и один при этом **упадёт** (§2.3).
- **Не запускать pytest из корня репозитория** — `1 failed` на `test_verify_regressions.py` из-за межмодульного импорта, а не из-за вашей правки (§2.1). Запускайте из `tools/vn` либо через `PYTHONPATH=tools/vn`.
- **Не бампать `save_schema`, не сняв фикстуру заранее.** После бампа получить сейв со старой схемой уже нечем — в корпусе окажется ложно-зелёная проверка. Так и было до 2026-08-08; фикстура `schema1-demo.save` закрыла это только для перехода 1 → 2.
- **Не коммитить фикстуру без `ci/fixtures/rpyc-line/`** (и наоборот). Расхождение делает корпус красным на любой машине кроме той, где фикстуру снимали.
- **Не добавлять `.rpyc` в git руками.** Единственное легальное исключение — `ci/fixtures/rpyc-line/**` (`.gitignore:12-14`), и его пересоздаёт `_rpyc_line_snapshot`, а не человек.
- **Не редактировать `.vncache/smoke/`, `.vncache/corpus/`, `.vncache/corpus-savedir/`** — они вычищаются в начале каждого прогона (`cli.py:1524-1526`).
- **Не ориентироваться на `.vncache/langqa/`** — артефакт-сирота без производящего кода (§4.8).
- **Не описывать в задачах и PR флаги из `ARCHITECTURE.md`, которых нет** (`--affected`, `--shard`, `--update-baselines`, `--report`, `--rpyc-regression`, `vn test perf`, `vn build --use-artifact`). Это целевой документ, а не описание построенного.
- **Не полагаться на PR-пайплайн в вопросах рантайма** — smoke и корпус там не гоняются вообще (§8).

---

## Проверка

Полный локальный прогон «как в CI + то, чего CI на PR не делает»:

```bash
export RENPY_SDK="$HOME/renpy-sdk/renpy-8.5.3-sdk"   # в bash-сессии агента не наследуется

vn doctor                                  # ожидание: 8 PASS, 0 FAIL
vn content lint                            # ожидание: 0 ошибок, 0 предупреждений
vn build                                   # ожидание: build: OK
vn loc keys --check
bash "$RENPY_SDK/renpy.sh" . lint
vn content compile --check                 # ожидание: check: генерат свеж
(cd tools/vn && .venv/bin/python -m pytest -q)  # ожидание: 518 passed (§2.1!)
vn test oversample --scale 2               # ожидание: «oversample @2: проверено 22, поднято 13» + OK
vn test smoke --picks 0,0                  # ожидание: OK: vn_end_of_content (19 скриншотов, cold start ~1.3 c)
vn save check                              # ожидание: save check: OK (2 фикстур)
vn save corpus                             # ожидание: OK (2 фикстур); линия имён: 52 .rpyc; на обеих —
                                           #   «schema после загрузки: 2 (цель 2)»
vn release validate --flavor public        # ожидание: 20 строк, 18 PASS + 2 WARN (озвучка, зрелость), exit 0
vn release validate --flavor patron        # ожидание: 21 строка (два пака, early_content=true), exit 0
```

Все ожидания выше — фактический вывод на HEAD `db28ce6` (2026-08-18, macOS, SDK 8.5.3, ffmpeg в PATH).
Числа `19 скриншотов`, `проверено 22 / поднято 13`, `52 .rpyc` меняются вместе с контентом и ассетами —
это снимок, а не инвариант; инварианты — `OK`-вердикты и `exit 0`.

Артефакты, по которым разбирают падение: `.vncache/smoke/{RESULT.txt,picks.log,startup.txt,state.json,gallery.json,shot*.png}`, `.vncache/corpus/*`, `traceback.txt` и `log.txt` в корне репозитория. Как ими пользоваться — [28-debugging.md](28-debugging.md).

---

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `tools/vn/src/vn/cli.py:1317-1484` (группа `save`, линия `.rpyc`), `cli.py:1487-1660` (группа `test`: `_AUTOPILOT_RPY`, `_autopilot_run`, `test_smoke`, `test_oversample`, заглушки), `game/framework/00_core/030_flow.rpy:91-211` (`vn_qa`), `game/framework/90_debug/030_oversample.rpy`, `game/framework/20_ui/screens/choice.rpy:53-54`, `game/framework/20_ui/screens/core_screens.rpy:409-410`, `game/framework/00_core/020_state.rpy:82-107` (`after_load`), `tools/vn/tests/{conftest.py,helpers.py}`, `tools/vn/src/vn/release.py:474-699` (гейт), `.github/workflows/{ci,nightly,canary}.yml` |
| **Не трогать** | `.vncache/**` (вычищается каждым прогоном), `game/generated/**` и `game/generated/qa/` (последняя создаётся и удаляется автопилотом), `ci/fixtures/rpyc-line/**` руками — только через `vn save corpus --add`; `.gitignore:12-14` (исключение для линии `.rpyc` — единственное легальное `.rpyc` в git) |
| **Зависимости (что сломается ниже по течению)** | правка `game/framework/**` или контента → линия statement-имён расходится с `ci/fixtures/rpyc-line/` → `vn save corpus` красный, пока фикстуру не пересняли; правка `choice.rpy`/`core_screens.rpy` → автопилот перестаёт выбирать/подтверждать → smoke виснет до `--timeout`; правка `autopilot_finish` → меняются `state.json`/`gallery.json`, на которых стоит критерий прохода корпуса; бамп `project.yaml: save_schema` → корпус падает по несовпадению схемы, если миграция не написана; правка `budgets.cold_start_s` → меняет вердикт `vn test smoke` (единственное место, где этот бюджет форсится) |
| **Валидация** | `vn content lint` → `(cd tools/vn && .venv/bin/python -m pytest -q)` (518) → `vn build --check` → `vn test oversample --scale 2` → `vn test smoke --picks 0,0` → `vn save check && vn save corpus` → `vn release validate --flavor public`. Для всего с 3-го пункта обязателен `RENPY_SDK` |
| **Частые ошибки** | 1) Считать `ARCHITECTURE.md` описанием реальности: `--affected`, `--shard`, `--update-baselines`, `--report`, `--rpyc-regression`, `vn test perf`, `qa/saves-corpus/` — их нет. 2) Добавить автопилот-хук без `return renpy.run(action)` — вечное перевыбирание пункта меню (`030_flow.rpy:148-150`). 3) Предложить SendKeys/pyautogui для «теста UI» — прямой запрет, автопилот только in-process. 4) Считать зелёный `pytest` покрытием CLI и рантайма — из `cli.py` (2117 строк) покрыто ~6 команд из 68, а код `game/framework/**` не исполняется ни одним тестом. 5) Запускать pytest из корня и объяснять `1 failed` своей правкой (§2.1); забыть, что без SDK скипается 10, а без ffmpeg — 12 и один падает (§2.3). 6) Утверждать, что корпус миграций не проверяет — фикстура `schema1-demo.save` реально прогоняет миграцию `0002`; непокрытыми остаются будущие переходы схемы. 7) Ссылаться на `.vncache/langqa/` как на воспроизводимый прогон — его никакой код не производит. 8) Ожидать smoke, сейв-корпус или корпус масштаба в PR-пайплайне — они только в `nightly.yml` и `canary.yml`; на пуше гоняются `vn test oversample` и арифметика `vn release android preflight --bundle`. 9) Считать «все PASS» эталоном гейта — один WARN про черновую озвучку сейчас штатен (§9.3). 10) Считать импорт одного тестового модуля из другого нормой — именно он и создал проблему §2.1 |
