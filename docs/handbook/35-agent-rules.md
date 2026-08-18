# 35. Правила для AI-агента

> **Статус подсистемы:** NOT IMPLEMENTED (инфраструктура) — в репозитории **нет** ни `CLAUDE.md`, ни `AGENTS.md`, ни каталога `.claude/`, ни `REVIEW.md` (проверено `ls` на 2026-08-18: в корне только `README.md`, `CODEOWNERS`, `project.yaml`, `android.json`, `.vnstorage.yaml`, `.gitattributes`, `.gitignore`). Правила ниже существуют **только в этом файле хендбука**; §1 даёт готовый черновик, чтобы это исправить.
> **Отвечает на вопрос:** «Что агент обязан прочитать, чем ограничен, и что обязан вернуть, прежде чем сказать "готово"?»

Этот файл — операционная инструкция, а не эссе. Он рассчитан на то, что его читает агент перед задачей и владелец — когда решает, доверять ли результату. Общая философия работы через AI — [34-ai-vibe-coding.md](34-ai-vibe-coding.md); здесь — жёсткие правила именно этого репозитория.

## Быстрый ответ

```
1. Прочитать docs/handbook/README.md + профильный файл хендбука.
2. Найти существующую реализацию: vn --help; grep по tools/vn/src/vn/, game/framework/,
   tools/schemas/, content/. Не изобретать второй такой же механизм.
3. Определить зону файла: источник истины / генерат / сырец  (02-architecture.md §2-3).
4. Проверить статус механизма в хендбуке: IMPLEMENTED / PARTIAL / NOT IMPLEMENTED.
5. Сделать минимальную правку. Данные — в YAML+схему, не в код.
6. Прогнать:  vn content lint && vn build && python -m pytest tools/vn/tests -q
   рантайм/сейвы/локализация: + vn test smoke --picks 0,0 && vn save corpus
   релизный путь:             + vn release validate --flavor public
7. Прочитать git diff целиком; убедиться, что в diff нет game/generated|assets|tl.
8. Вернуть отчёт по форме §6: файлы, команды с фактическим выводом, нормы, что не сделано.
```

**Правило номер ноль:** источник истины по командам и флагам — `vn --help` и `../../tools/vn/src/vn/cli.py`. `../ARCHITECTURE.md` — целевой документ; описанные там `vn build --use-artifact`, `vn validate`, `vn content lint --strict` **не существуют** и дадут usage error (exit 2).

---

## 1. Документы для агента: что должно быть и что есть

| Файл | Что там должно быть | Есть сейчас |
|---|---|---|
| `CLAUDE.md` (корень) | Короткие постоянные правила, которые агент видит **всегда**: язык, ключевые команды, запретные зоны, обязательный хвост проверок, 10 жёстких контрактов. Не пересказ архитектуры, не карта каталогов. Цель — до 200 строк, реально хватит 60–70 | **НЕТ** |
| `AGENTS.md` (корень) | Вендор-нейтральный эквивалент по конвенции `agents.md`. На практике — тонкий файл-указатель на `CLAUDE.md` и хендбук | **НЕТ** |
| `docs/ARCHITECTURE.md` | Нормативный **целевой** документ. Раздел 0 (G1–G24, C1–C24) — контракт ревью: «Изменение любого пункта — только через ADR» (`../ARCHITECTURE.md:36`) | ЕСТЬ, 4182 строки |
| `docs/adr/` | Точечные решения с обоснованием и планом отступления. ADR обязателен при изменении нормы раздела 0 | ЕСТЬ: 14 ADR + `template.md`; ADR-0008 — единственный со статусом «предложено» |
| `docs/handbook/` | Практические how-to со статусами реализации — **точка входа агента** | ЕСТЬ (этот корпус) |
| `.claude/settings.json` | `permissions.deny` на производные зоны, чтобы генерат не съедал контекст; hook-гейт на `vn content lint` | **НЕТ** |
| `REVIEW.md` | Правила код-ревью для managed GitHub App | **НЕТ**, и заводить преждевременно: локальное ревью в Claude Code этот файл не читает — рычагом остаётся `CLAUDE.md` |

**Кто что читает.** Claude Code читает `CLAUDE.md`, а не `AGENTS.md`. Если инструмент один — второй файл только создаёт расхождение, а расхождение инструкций — главная причина того, что агент строит вторую копию уже существующей подсистемы. Поэтому рекомендация: **сначала `CLAUDE.md`, `AGENTS.md` — только когда появится агент другого вендора**, и тогда — указателем, а не копией. Симлинк `ln -s AGENTS.md CLAUDE.md` на Windows требует прав администратора или Developer Mode — вместо него используется импорт: первая строка `CLAUDE.md` = `@AGENTS.md`.

### Готовый черновик `CLAUDE.md`

Скопировать в корень репозитория как есть; править по мере расхождения с кодом. **Этот файл сам по себе не создаётся** — данный хендбук только предлагает содержимое.

```markdown
# CLAUDE.md

Коммерческая визуальная новелла на Ren'Py 8.5.3. Весь тулинг — один CLI `vn` (`tools/vn/`).
Документация, комментарии и коммиты — по-русски. Термины кода — латиницей, как есть.

## Куда смотреть
- Практика: `docs/handbook/README.md` — карта + 38 файлов how-to со статусами реализации. Начинать отсюда.
- Нормы: `docs/ARCHITECTURE.md`, раздел 0 = G1-G24 / C1-C24. Это ЦЕЛЕВОЙ документ,
  а не описание построенного: половина разделов — будущие фазы.
- Решения: `docs/adr/` (14 ADR; 0008 не принят).
- Правила агента целиком: `docs/handbook/35-agent-rules.md`.

## Команды
    vn doctor                            # окружение; норма — 8 PASS, 0 FAIL
    vn build                             # lint -> ассеты -> компилятор -> loc import -> бюджеты
    vn content lint                      # 33 диагностики, 5-10 c
    vn play  |  vn dev                   # запуск | запуск + watch content/ и assets_src/
    python -m pytest tools/vn/tests -q   # 373 теста, ~5-9 c
Обязательный хвост ЛЮБОЙ правки:
    vn content lint && vn build && python -m pytest tools/vn/tests -q
Трогал рантайм/сейвы/локализацию — добавь: vn test smoke --picks 0,0 && vn save corpus
Трогал релизный путь — добавь:            vn release validate --flavor public

## Зоны
Пишет человек: `content/`, `packs/`, `game/framework/`, `tools/`, `loc/po/`, `assets_src/`, `docs/`.
Пишет тулинг — НЕ ПРАВИТЬ: `game/generated/`, `game/assets/`, `game/tl/`, `game/build_id.json`,
`build/`, `.vncache/`. Эти зоны не в git (`.gitignore:1-22`) и перезаписываются сборкой.
Ошибку, видимую в `game/generated/**.gen.rpy`, чинят в `content/`, в
`tools/vn/src/vn/content/compile.py` или в `game/framework/` — и только там.
Исключение: `ci/fixtures/rpyc-line/**` — единственные `.rpyc` в git (`.gitignore:14`), не удалять.

## Жёсткие правила
1. Флаги CLI проверять по `vn --help` и `tools/vn/src/vn/cli.py`, а не по ARCHITECTURE.md.
   `vn build --use-artifact`, `vn validate`, `vn content lint --strict` НЕ существуют.
2. Id (`chNN`, `chNN_sNNN`, ключ персонажа, имя переменной) неизменяемы навсегда.
   Переименование = новый id + запись в `content/renames.yaml` (G7). Переиспользование запрещено.
3. В авторском `*.scene.rpy` только `label chNN_sNNN__body:` и `chNN_sNNN__<branch>:`.
   Выход из сцены — ТОЛЬКО `return "<exit_id>"` (C2); `jump`/`call` наружу режет линтер.
4. Перед каждым `menu` — `$ vn_menu = "chNN_sNNN_mNNN"`; текст пункта только через
   `vn_loc.choice_text(vn_menu, idx, i.caption)` (C1).
5. В экранах нет строковых литералов: только `vn_loc.t("ключ")` + `content/ui/strings.yaml`.
6. В экранах нет магических чисел: только токены `gui.*` (`game/gui.rpy`) и панели
   `vn_frame_*` (`content/ui/panels.yaml`, ADR-0009). Элемент не может быть меньше `2*Borders`.
7. Каждый YAML начинается с `schema: <name>@<int>`; схема лежит в
   `tools/schemas/<name>@<N>.schema.json` (G16). Данные — в YAML+схему, а не в код.
8. Заглушка = честный отказ: `_stub(phase)` + exit 3 (`cli.py:34-38`). Тихий no-op запрещён.
9. Изменение нормы раздела 0 ARCHITECTURE.md — только новым ADR (`docs/adr/template.md`).
10. Не запускать GUI-автоматизацию рабочего стола. QA-прогон — только `vn test smoke`.

## Окружение (Windows 11, Python 3.12)
- `RENPY_SDK` не наследуется в bash-сессиях агента:
  `export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`. Без него падают
  `vn play`, `vn dev`, `vn package`, `vn test smoke` и компиляция сцен.
- Ren'Py 8.5: `config.change_language_callbacks` мёртв — живой хук `config.language_callbacks[lang]`.
- `setx` виден только НОВЫМ процессам (грабля `CIVITAI_API_KEY`).

## Коммит
`type(scope): описание по-русски` + непустое тело (почему, а не что) + трейлер
`Co-Authored-By:` — он есть во всех 51 коммитах истории. Ветка `main`, PR не обязателен,
но обязателен для правок `tools/`, `game/framework/00_core/`, `content/migrations/`, workflow.
```

### Черновик `AGENTS.md` (заводить только при втором вендоре)

```markdown
# AGENTS.md

Правила для AI-агентов этого репозитория едины и лежат в `CLAUDE.md` (корень) — читать его.
Практические how-to — `docs/handbook/` (вход: `docs/handbook/README.md`).
Нормативный целевой документ — `docs/ARCHITECTURE.md`, раздел 0 (G1-G24, C1-C24).
Принятые решения — `docs/adr/`.

Перед правкой: определи зону файла (`docs/handbook/02-architecture.md`).
После правки:  vn content lint && vn build && python -m pytest tools/vn/tests -q
Никогда не редактируй `game/generated/`, `game/assets/`, `game/tl/` — это генерат.
```

---

## 2. Протокол работы агента

### 2.1. Перед изменением

1. **Прочитать точку входа и профильный файл.** `README.md` хендбука → нужный файл из карты §4. Хендбук содержит статусы; `../ARCHITECTURE.md` — нет.
2. **Найти существующую реализацию.** По порядку:
   ```bash
   vn --help                                  # 20 команд/групп верхнего уровня
   vn <group> --help                          # флаги конкретной команды
   grep -rn "<термин>" tools/vn/src/vn/       # тулинг
   grep -rn "<термин>" game/framework/        # рантайм
   ls tools/schemas/ | grep <сущность>        # 39 схем — есть ли уже декларация
   ls content/                                # чем объявляется предметная область
   ```
   Если механизм уже есть — расширять его, а не писать второй. Каталог `content/` содержит 8 предметных зон (`chapters characters locations audio variables migrations registry ui`) плюс `gallery/`, `achievements/`, `licenses.yaml` — половину «нового» уже можно объявить существующей схемой.
3. **Определить зону файла.** Три категории: **источник истины** (`content/`, `packs/`, `game/framework/`, `tools/`, `loc/po/`), **генерат** (`game/generated/`, `game/assets/`, `game/tl/`, `build/`, `.vncache/`), **сырцы** (`assets_src/`). Правка в генерате бесполезна дважды: не попадёт в git и умрёт при первой сборке. Полная таблица — [02-architecture.md](02-architecture.md) §2–3.
4. **Проверить статус механизма.** В хендбуке у каждого механизма стоит ровно одна пометка. `NOT IMPLEMENTED` означает, что описанное в `../ARCHITECTURE.md` поведение отсутствует в коде — строить поверх него нельзя. `PARTIAL` — читать, чем именно ограничено.
5. **Зафиксировать затронутые нормы G/C.** Справочник — [02-architecture.md](02-architecture.md) §6. Минимальный набор, который задевается чаще всего: G1 (единый CLI), G2 (зоны), G7 (id), G16 (schema в каждом YAML), C1 (маркер меню), C2 (контракт меток), C8 (init-шкала), C17 (раскладка `framework/`).

### 2.2. Во время

| Правило | Конкретно в этом репозитории |
|---|---|
| Минимальный scope | Одна задача = один слой. Не «заодно» рефакторить `cli.py` (2117 строк) при правке одной сцены |
| Переиспользовать существующее | `vn_*`-фасад рантайма, `gui.*`-токены, `vn_frame_*`-панели, схемы из `tools/schemas/` |
| Не менять архитектуру попутно | Норма раздела 0 меняется ADR-ом отдельным коммитом, а не строчкой внутри фичи |
| Данные — в YAML + схему | Новая сущность = `content/<зона>/*.yaml` + `tools/schemas/<name>@1.schema.json` + правило в `tools/vn/src/vn/content/lint.py` + тест. Хардкод в `.rpy` не переводится, не валидируется и не мигрируется |
| UI — через `vn_*` и `gui.*` | Литерал в экране не попадёт в PO-экстракцию (`content/ui/strings.yaml:3-4`); число вместо токена ломает панели (ADR-0009) |
| Обновить тесты | `tools/vn/tests/` — 27 файлов `test_*.py` + `conftest.py`, 373 теста. Новое правило линтера без теста в `test_lint.py` — незакрытая правка |
| Обновить документацию | Назвать, какой файл хендбука затронут, и поправить его. Если изменился статус механизма — поправить пометку |

### 2.3. После

```bash
# 1. Цепочка валидации — обязательный минимум
vn content lint                          # 33 диагностики
vn build                                 # lint -> ассеты -> компилятор -> loc import -> бюджеты
vn content compile --check               # «check: генерат свеж»
python -m pytest tools/vn/tests -q       # 400 passed

# 2. Дополнительно по зоне правки
vn loc keys --check                      # трогал реплики/меню в *.scene.rpy
vn test smoke --picks 0,0                # трогал рантайм, флоу, экраны
vn save check && vn save corpus          # трогал состояние, миграции, save_schema
vn release validate --flavor public      # трогал релизный путь, флейворы, лицензии
vn assets validate                       # трогал assets_src/ или реестр образов

# 3. Гигиена
git diff                                 # прочитать ЦЕЛИКОМ, а не по кускам
git status --short                       # game/generated|assets|tl быть не должно
```

Затем: обновить затронутые файлы `docs/handbook/*`; если менялась норма раздела 0 — завести ADR по `../adr/template.md` (обязательные секции: Статус, Дата, **Затрагивает нормы**, Контекст, Решение, Последствия с планом отступления).

Полные pre-commit / pre-push чеклисты и разбор CI — [04-development-workflow.md](04-development-workflow.md) §5–6.

---

## 3. ЗАПРЕТЫ

Каждый пункт — с причиной. Причина важнее запрета: она позволяет распознать новый случай того же класса.

1. **Не править `game/generated/`, `game/assets/`, `game/tl/`, `game/build_id.json`, `build/`, `.vncache/`.**
   Причина: зоны в `.gitignore:1-22`, правка не попадёт в git и будет затёрта ближайшей сборкой. Единственное исключение — `ci/fixtures/rpyc-line/**` (негативное правило `.gitignore:14`): 52 `.rpyc` в git, линия statement-имён для сейв-корпуса (G6). Не удалять, не «чистить», не пересобирать руками.
2. **Не переиспользовать и не переименовывать id.**
   Причина: G7 — id сцен, глав, персонажей и переменных попадают в сейвы игроков, в `loc/ledger/chNN.json`, в msgctxt PO и в `persistent`. Переименование = **новый** id + запись в `content/renames.yaml` (`schema: renames@1`, секции `scenes/deleted_scenes/labels/vars`, файл append-only). Компилятор из него генерирует `config.label_overrides` и shim-метки.
3. **Не писать label вне контракта C2.**
   Причина: обвязку `label chNN_sNNN:` эмитит компилятор; авторские метки — только `chNN_sNNN__body` и `chNN_sNNN__<branch>`. Межсценовый переход — только `return "<exit_id>"`. Прямой `jump`/`call` наружу ломает инвариант глубины call-стека и режется линтером (`tools/vn/src/vn/content/scenes.py`).
4. **Не ставить `menu` без `$ vn_menu = "chNN_sNNN_mNNN"` и не подставлять `i.caption` напрямую.**
   Причина: C1 — без маркера пункт не переводится (`vn_loc.choice_text(vn_menu, idx, i.caption)`, `game/framework/20_ui/screens/choice.rpy:47`) и не опознаётся QA-автопилотом.
5. **Не хардкодить строки в экранах.**
   Причина: литерал не попадает в PO-экстракцию и останется непереведённым при смене языка (прямо написано в `content/ui/strings.yaml:3-4`). Все пользовательские строки — ключи в `content/ui/strings.yaml`, в экране — `vn_loc.t("ключ")`.
6. **Не использовать магические числа в UI.**
   Причина: размеры/отступы/цвета — токены `gui.*` из `game/gui.rpy`; фоны — генерируемые панели ADR-0009. Ловушка геометрии: `Borders = radius + max(blur+|dy|, border.width)`, элемент не может быть меньше `2*Borders`. Живых нарушений в репозитории **нет** (закрыто 2026-08-08): `style vn_gal_tab` (`game/framework/20_ui/screens/gallery.rpy:161-168`) и `style vn_gal_ctl_button` (`:221-225`) переведены с панелей `choice*` (минимум 60 и 54 px) на пару `chip`/`chip_active` — radius 8, Borders 11, минимум 22×22 px при фактической высоте ≈31 и ≈29 px. Мелкому элементу нужна своя панель, а не чужая: копировать в новый компактный контрол именно чипы. Регресс стерегут `test_ui_panels.py:244-304`.
7. **Не пушить сырцы без лока.**
   Причина: G14 — `vn assets push` требует валидный лок (`cli.py:897-908`); `vn assets lock --force` = снятие ЧУЖОГО лока, эскалация на лида. Реальность: хранилище `~/vn-assets-store` ещё не существует, `vn assets status` отвечает «манифестов нет — сырцы ещё не пушились», TTL и атомарность лока NOT IMPLEMENTED — тем важнее не обходить процедуру руками.
8. **Не менять раздел 0 `docs/ARCHITECTURE.md` без ADR.**
   Причина: `../ARCHITECTURE.md:36` — «Изменение любого пункта — только через ADR». Правка нормы без ADR делает контракт ревью недоказуемым.
9. **Не слать синтетический ввод (SendKeys, AutoHotkey, эмуляция мыши) на рабочий стол.**
   Причина: недетерминированно, попадает в чужие окна, невоспроизводимо в CI. Штатный путь — in-process автопилот: `vn test smoke` (`cli.py:1347-1401`) + `vn_qa.autopilot_choose` (`game/framework/00_core/030_flow.rpy:130-150`), который обязан `return renpy.run(items[idx].action)` — без возврата non-None интеракция меню не завершается и автопилот зациклится.
10. **Не обходить логины, капчи и gated-загрузки за моделями.**
    Причина: `vn pipeline models --pull` намеренно не считает manual/auth-шаги ошибкой — они выполняются человеком. Агент печатает, что требуется, и останавливается.
11. **Не коммитить ключи и токены.**
    Причина: `CIVITAI_API_KEY` живёт в User-окружении Windows, `PATRON_TOKEN` — в `secrets` GitHub. Грабля: `setx` виден только новым процессам; `vn pipeline doctor` умеет отличить «ключ есть в User-окружении, но не виден этому процессу» (`pipeline.py:321-336`).
12. **Не делать тихих no-op вместо заглушки.**
    Причина: контракт `_stub(phase)` — жёлтое сообщение «эта команда появится в фазе N» + **exit 3** (`cli.py:34-38`). Молчаливая пустая функция создаёт ложное «работает». Тот же принцип в рантайме: `vn_qa.choice()` — честный `pass` с комментарием «Фаза 2» (`030_flow.rpy:98-101`), а не имитация записи.
13. **Не изобретать флаги и команды CLI.**
    Причина: несуществующая команда — usage error (exit 2), в CI это красный шаг с непонятной причиной. Проверять по `vn --help` и `cli.py`.
14. **Не понижать `status` главы, чтобы граф-проверки стали предупреждениями.**
    Причина: G15 — при `status: draft` ошибки scene_order/entry/exits/reachability понижаются до warning (`tools/vn/src/vn/content/lint.py:209,231,270`). Понижение статуса ради зелёного линта — подлог, а не починка.
15. **Не редактировать `docs/CHANGELOG.md` до `vn release changelog`** и **не ставить тег без бампа `project.yaml: version`.**
    Причина: генератор вставляет свой блок выше вашего текста; `release.yml:47-54` сверяет тег с `project.yaml` первым шагом и падает до сборки.
16. **Не менять `project.yaml: save_schema` без файла миграции и записи в реестре.**
    Причина: G5 — номер резервируется в том же PR (`content/migrations/registry.yaml`, `schema: migrations_registry@1`; сейчас занят один номер — `{number: 2, slug: route_prologue}`). Внешнего `vn save migrate` не существует (`_stub(3)`, `cli.py:1260`) — единственная проверка миграции — `vn save corpus`. С 2026-08-08 она настоящая: в корпусе 2 фикстуры, и `ci/fixtures/saves/schema1-demo.save` (`vn_save_schema=1`) реально прогоняет цепочку в игре — прогон печатает «schema после загрузки: 2 (цель 2)», а в `log.txt` появляется строка `[vn] migration 0002`.

---

## 4. Карта «хочу сделать X → читать Y»

| Задача | Точка входа (команда / файл) | Хендбук | Код |
|---|---|---|---|
| Поднять окружение с нуля | `pip install -e "tools/vn[dev]"`, `vn doctor` | [03-getting-started.md](03-getting-started.md) | `doctor.py` |
| Добавить главу | `vn chapter new <slug>` (`cli.py:449`) | [09-chapters.md](09-chapters.md) | `tools/vn/src/vn/content/scaffold.py` |
| Добавить сцену | `vn scene new ch01 <slug>` (`cli.py:470`) | [12-scenes.md](12-scenes.md) | `tools/vn/src/vn/content/scaffold.py`, `tools/vn/src/vn/content/scenes.py` |
| Заглушить объявленный, но не написанный переход | `vn scene stub ch01 s040` (`cli.py:506-520`) | [12-scenes.md](12-scenes.md) | `tools/vn/src/vn/content/scaffold.py` |
| Написать реплики и выборы | `content/chapters/*/scenes/*.scene.rpy` | [13-dialogue.md](13-dialogue.md) | `tools/vn/src/vn/content/analyze.py`, `00_core/050_build_bridge.rpy` |
| Добавить персонажа | вручную `content/characters/<id>/character.yaml` (`vn char new` — заглушка фазы 1, exit 3, `cli.py:958`) | [10-characters.md](10-characters.md) | `tools/schemas/character@1.schema.json` |
| Добавить локацию | вручную `content/locations/<id>/location.yaml` | [11-locations.md](11-locations.md) | `tools/schemas/location@1.schema.json` |
| Добавить фон / CG / спрайт | `assets_src/png/...` → `vn assets build` | [16-assets.md](16-assets.md) | `tools/vn/src/vn/assets/pipeline.py` |
| Добавить видео-луп | `assets_src/video_src/...` → `vn assets video build`, `vn assets video validate` | [21-video-generation.md](21-video-generation.md), [16-assets.md](16-assets.md) | `tools/vn/src/vn/assets/video.py` |
| Добавить трек / SFX | `content/audio/bgm.yaml`, `content/audio/sfx.yaml` | [23-audio.md](23-audio.md) | `tools/vn/src/vn/content/compile.py` |
| Добавить строку интерфейса | `content/ui/strings.yaml` → `vn loc extract` | [14-localization.md](14-localization.md), [06-frontend.md](06-frontend.md) | `00_core/040_localization.rpy` |
| Добавить язык | `vn loc add de --name Deutsch` → `vn loc import` | [14-localization.md](14-localization.md) | `tools/vn/src/vn/loc/po.py`, ADR-0005 |
| Добавить UI-панель | `content/ui/panels.yaml` → `vn build` | [06-frontend.md](06-frontend.md) | `tools/vn/src/vn/assets/ui.py`, ADR-0009 |
| Добавить/поправить экран | `game/framework/20_ui/screens/` | [06-frontend.md](06-frontend.md) | `20_ui/components.rpy`, `game/gui.rpy` |
| Добавить элемент галереи | `content/gallery/*.gallery.yaml` | [15-gallery.md](15-gallery.md) | `00_core/090_gallery.rpy`, ADR-0010 |
| Добавить достижение | `content/achievements/core.achievements.yaml` | [15-gallery.md](15-gallery.md) §Достижения | `00_core/080_achievements.rpy` |
| Добавить переменную состояния | `content/variables/core.vars.yaml` или `content/chapters/chNN_*/vars.yaml` | [07-backend.md](07-backend.md) | `00_core/020_state.rpy` |
| Добавить миграцию сейва | `content/migrations/NNNN_slug.py` + `registry.yaml` + бамп `save_schema` | [07-backend.md](07-backend.md) | `00_core/020_state.rpy` |
| Добавить команду CLI | `tools/vn/src/vn/cli.py` + модуль домена | [25-custom-engine.md](25-custom-engine.md) | `cli.py`, `repo.py` |
| Добавить правило линтера | `tools/vn/src/vn/content/lint.py` + `tools/vn/tests/test_lint.py` | [08-content-pipeline.md](08-content-pipeline.md) §7 | `tools/vn/src/vn/content/lint.py` (411 строк) |
| Добавить схему | `tools/schemas/<name>@1.schema.json` (имя файла = `properties.schema.const`) | [08-content-pipeline.md](08-content-pipeline.md) §8 | `schemas.py:13-51` |
| Добавить выход компилятора | `tools/vn/src/vn/content/compile.py` + ожидания в `tests/test_compile.py` | [08-content-pipeline.md](08-content-pipeline.md) §2 | `tools/vn/src/vn/content/compile.py` (923 строки) |
| Завести пак / DLC | `packs/<id>/manifest.yaml` → `vn pack validate`, `vn pack build <id>` | [30-packs-and-dlc.md](30-packs-and-dlc.md) | `cli.py:1573,1600` |
| Зарегистрировать лицензию ассета | `content/licenses.yaml` → `vn assets licenses` | [16-assets.md](16-assets.md) §10, [33-security-and-legal.md](33-security-and-legal.md) | `tools/vn/src/vn/assets/licenses.py` |
| Добавить тест | `tools/vn/tests/test_*.py` | [27-testing.md](27-testing.md) | `tests/conftest.py` |
| Добавить проверку в CI | сначала команда в `vn`, потом шаг в `.github/workflows/ci.yml` | [04-development-workflow.md](04-development-workflow.md) §4 | `.github/workflows/` |
| Изменить бюджет размера/старта | `project.yaml: budgets` | [32-performance-and-scalability.md](32-performance-and-scalability.md) | `release.py:29-54` |
| Изменить/добавить флейвор | `project.yaml: flavors` | [29-build-and-release.md](29-build-and-release.md) | `release.py:258-299`, `00_core/060_build_info.rpy` (флейвор читается как `build_info@2`, метка получателя — `patron_tag`, ADR-0011) |
| Переименовать сцену / переменную | `content/renames.yaml` (новый id, старый не переиспользовать) | [02-architecture.md](02-architecture.md) §8 | `tools/vn/src/vn/content/compile.py` |
| Изменить норму G/C | новый ADR по `../adr/template.md` | [02-architecture.md](02-architecture.md) §6 | `docs/adr/` |
| Понять, почему падает игра | `vn test smoke`, dev-меню, `log.txt` | [28-debugging.md](28-debugging.md) | `00_core/070_crash.rpy` |
| Разобраться с красным CI | воспроизвести ту же команду локально | [04-development-workflow.md](04-development-workflow.md) §6, [36-troubleshooting.md](36-troubleshooting.md) | `.github/workflows/` |

---

## 5. Как агенту проверять свои утверждения

**Базовое правило: не уверен — прочитай файл.** Стоимость `Read` на порядок ниже стоимости неверного утверждения в отчёте, по которому владелец примет решение. Особенно это касается номеров строк: в этом репозитории они плывут при каждой правке — цитируя `cli.py:NNN`, открой эти строки.

### Чему верить и в каком порядке

| Источник | Степень доверия |
|---|---|
| `vn --help`, `vn <group> --help` | **Факт.** Реальный набор команд и флагов на этой машине |
| Код: `tools/vn/src/vn/**`, `game/framework/**`, `tools/schemas/**` | **Факт.** Конечная инстанция |
| `docs/handbook/*` со статус-пометками | Проверенный факт на 2026-08-08; при расхождении с кодом побеждает код |
| `docs/adr/*` со статусом «принято» | Решение и его обоснование. Код мог отстать — сверять |
| `docs/ARCHITECTURE.md` | **Намерение, не реализация.** Целевой документ на 4182 строки; бо́льшая часть — будущие фазы |
| `README.md:43` («Статус: фаза 0») | Устарело: реализованы компилятор, локализация, галерея, флейворы, сейв-корпус, smoke |
| `docs/onboarding/localizer.md` («появится в фазе 2») | Устарело: весь `vn loc *` работает |
| `docs/runbooks/pipeline-broken-at-night.md` про откат через `git revert tools/vn.lock` | **Исполнимо с 2026-08-08:** лок ставится перед editable-установкой во всех в 8 джобах установки тулчейна (7 строк в конфигах: GitLab-шаблон `.with-sdk` разворачивается в `build` и `test`). Остаток: транзитивные зависимости в локе не закреплены (`pygments`) |

### Как отличить намерение от реализации

```bash
# Команда/флаг реально существует?
vn --help | grep <команда>
grep -n "\-\-<флаг>" tools/vn/src/vn/cli.py

# Что отложено честной заглушкой (exit 3)?
grep -n "_stub(\|_stub_group(" tools/vn/src/vn/cli.py
# одиночные заглушки:  393, 394 (migrate, shell), 1281 (voice tts),
#                      1484 (save migrate), 1659 (test replay|screens|paths)
# НЕ заглушка: release steam (cli.py:1819) — реализована по ADR-0014
# группы заглушек:     _stub_group — генератор cli.py:523-527, вызов :1097 (char)
# определение:         def _stub — cli.py:34
# ЛОЖНЫЕ срабатывания шаблона "_stub(": scene_stub / new_stub — это рабочий код

# Механизм упоминается в ARCHITECTURE.md, но есть ли он в коде?
grep -rn "<термин>" tools/vn/src/vn/ game/framework/ | head
```

**Полный список заглушек (exit 3), исчерпывающе:**

| Фаза | Команды |
|---|---|
| 1 | `vn char new`, `vn char validate` |
| 2 | `vn migrate`, `vn shell`, `vn char sheet`, `vn voice tts` (остальной `vn voice` — живой), `vn test replay`, `vn test paths` |
| 3 | `vn save migrate`, `vn test screens` |

**Отсутствуют вовсе** (даже заглушки нет — click вернёт usage error, exit 2): `vn validate` (группы не существует), `vn build --use-artifact <sha>`, `vn content lint --strict/--arch/--schemas`, `vn content rename`, `vn content who-writes`, `vn play --scene`, `vn test perf`, `vn loc report --gate`, `vn release changelog --from`.

**Код есть, но он инертен** — самая опасная категория, потому что grep находит файл и создаёт впечатление работающего механизма:

| Механизм | Что на самом деле |
|---|---|
| `content/flags.yaml`, `content/anchors.yaml` | Обязаны существовать (`tools/vn/src/vn/content/lint.py:35-43`), читает их **только** проверка существования. Ни компилятор, ни рантайм к ним не обращаются |
| `content/registry/id_registry.json` | Все массивы пусты: `stamp_id_registry` пишет только главы со `status: release`, а `ch01` — `draft`. Страховка G7 инертна |
| `vn.beat()` | Реализован в `00_core/030_flow.rpy`, не эмитится компилятором и не вызывается контентом |
| `vn_qa.choice()` | `pass`-заглушка (`030_flow.rpy:98-101`), при том что C1 требует эмиссии первым стейтментом каждой ветки |
| ~~`flavors.<id>.packs`, `flavors.<id>.early_content`~~ | **Больше не мертвы:** `packs` читает рантайм-гейт установленности `pack_registry.installed()` (`030_flow.rpy:77-91`), `early_content` — проверка зрелости контента в релизном гейте (`early_content_checks`, `tools/vn/src/vn/release.py:403-438`; самоактивирующаяся — WARN до первой главы `status: release`, строгая после). Остаток честный: `vn_build.early_content` в `game/` по-прежнему не читает никто |
| ~~`pack_registry.owned()`~~ | **Больше не мёртв (ADR-0014):** провайдер владения подключается в `game/framework/00_core/035_platform.rpy:75` (`init 999`) при живом Steam, маппинг — `steam_dlc_appid` в манифесте пака. Остаток честный: вне Steam (standalone, dev-прогоны) и для пака без маппинга `owned()` по-прежнему `True` — [39-platforms.md](39-platforms.md) §5 |
| ~~`tools/vn.lock`~~ | **Больше не мёртв (2026-08-08):** `pip install --quiet -r tools/vn.lock` идёт перед editable-установкой во всех в 8 джобах установки тулчейна (7 строк в конфигах: GitLab-шаблон `.with-sdk` разворачивается в `build` и `test`); G17 закрыт для 18 пиннованных пакетов. Остаток — транзитивные зависимости не закреплены (`pygments`), и тест `test_ci_config.py` стережёт именно порядок «лок раньше editable» |
| ~~`assets_manifest@1`~~ | **Больше не мёртв (2026-08-08):** `tools/schemas/assets_manifest@1.schema.json` заведена, и манифест валидируется ею при каждой записи (`pipeline.py:441-450`) — нарушение G16 закрыто |
| ~~`copy_audio`~~ | **Больше не мёртв (2026-08-08):** конвейер читает нормативную зону `assets_src/audio_stems/{bgm,amb,sfx}/` (`pipeline.py:159-170`), каталоги заведены, тест `test_assets.py:test_audio_stems_branch_copies_ogg` стережёт ветку. Но на данных она ещё не работала: `content/audio/{bgm,sfx}.yaml` — `tracks: {}`, в репозитории ноль `.ogg`; поля `loop`/`loop_start`/`volume` схемы `audio@1` эмиттер игнорирует; loudnorm нет |

Формулировать в отчёте следует так: «`ARCHITECTURE.md` §X требует Y — сейчас NOT IMPLEMENTED», а не «Y работает».

---

## 6. Формат отчёта агента о работе

Агент возвращает владельцу **ровно эту структуру**. Отчёт без блока «Проверки» с фактическим выводом команд считается незавершённой работой.

```markdown
## Что сделано
<1-3 строки: суть, а не перечисление файлов>

## Изменённые файлы
| Файл | Что изменено |
|---|---|
| content/chapters/ch01_awakening/scenes/s040_rooftop.scene.yaml | новая сцена: exits, vars |
| content/chapters/ch01_awakening/chapter.yaml | s040 в scene_order |

## Проверки
| Команда | Результат |
|---|---|
| `vn content lint` | OK, 3 предупреждения (перечислены ниже) |
| `vn build` | `build: OK`; generated: 2 записано, 17 без изменений |
| `python -m pytest tools/vn/tests -q` | 400 passed |
| `vn test smoke --picks 0,0` | НЕ ЗАПУСКАЛОСЬ: нет RENPY_SDK в этой сессии |

## Затронутые нормы
G7 (новый id ch01_s040, переиспользования нет), C2 (метки __body/__branch), G15 (глава draft).
ADR не требуется: раздел 0 ARCHITECTURE.md не менялся.

## Не сделано и почему
- Локализация новой сцены: `vn loc keys` требует SDK, запустить не смог.

## Что нужно от владельца
- Прогнать `vn loc keys` и `vn test smoke --picks 0,0` в сессии с RENPY_SDK.
```

Требования к содержанию:

- **Фактический вывод, а не пересказ.** «Тесты прошли» — недостаточно; нужно `400 passed`.
- **Не запускавшаяся проверка называется прямо** («НЕ ЗАПУСКАЛОСЬ: причина»), а не опускается. Типичная причина в этом репозитории — отсутствие `RENPY_SDK` в bash-сессии агента.
- **Предупреждения линтера перечисляются**, даже если exit 0: `vn content lint` печатает warnings, которые в главе со `status: release` станут ошибками (G15).
- **Затронутые нормы называются номерами** — это язык ревью в этом проекте.
- **«Не сделано» — обязательный раздел.** Пустой он бывает редко; молчание о недоделанном хуже недоделанного.

---

## 7. Работа с ошибками

### Проверка красная

1. **Прочитать сообщение целиком.** `vn` никогда не падает голым трейсбеком: exit 1 всегда сопровождается строкой `ошибка: …` на stderr (`cli.py:22-24`), даже внутренняя ошибка компилятора обёрнута. Коды: `0` успех, `1` ошибка проверки/сборки, `2` usage error (click), `3` заглушка фазы.
2. **Понять класс отказа перед правкой:**
   | Симптом | Класс |
   |---|---|
   | `эта команда появится в фазе N` (exit 3) | Не баг. Механизма нет — сообщить владельцу, не имитировать |
   | `Usage: vn …` (exit 2) | Выдуманный флаг/команда. Свериться с `vn --help` |
   | `lint: N ошибок — сборка остановлена` | Нарушен контракт контента. Читать конкретное правило в `tools/vn/src/vn/content/lint.py` |
   | `генерат не свеж` / `game/assets не свеж` | Забыт `vn build` |
   | `FreetypeError` / шрифты | LFS: `git lfs install && git lfs pull` |
   | `Ren'Py SDK не найден` | `export RENPY_SDK=...` в этой bash-сессии |
3. **Чинить причину, а не симптом.** Запрещённые «починки»: понизить `status` главы до `draft` ради зелёного графа, закомментировать правило линтера, положить файл в производную зону руками, ослабить схему `additionalProperties`.
4. **Не пытаться в третий раз.** Если одна и та же проверка красная после двух попыток исправления, задача упирается в непонятый механизм. Остановиться, вернуть отчёт §6 с фактическим выводом и гипотезой — это дешевле, чем третья правка вслепую.

### Когда откатываться

```bash
git diff                          # прочитать целиком
git checkout -- <файл>            # точечный откат одного файла
git stash -u                      # снять всё, проверить чистый чекаут: vn content lint
```

Откатывать, если: правка расползлась за исходный scope; изменение затронуло производную зону; правка требует ADR, которого нет; проверка была зелёной до правки и красная после, а причина непонятна. **Автоматические чекпойнты агента не покрывают то, что записали bash-команды** — единственная надёжная страховка здесь `git`, поэтому промежуточный коммит перед рискованной правкой дешевле любого отката.

### Когда заводить ADR вместо правки

| Ситуация | Действие |
|---|---|
| Чинить приходится норму G/C раздела 0 | ADR со ссылкой на заменяемую норму (`../adr/template.md`) |
| Решение дорого откатывать: формат сейва, именование, зона хранения, релизная механика | ADR до кода |
| Документ и код расходятся, и код прав | ADR фиксирует расхождение как решение (прецедент: ADR-0003 сдвинул init-шкалу C8 после реального `renpy lint`; ADR-0010 уточнил C9) |
| Расхождение обнаружено при инциденте | Post-mortem в `docs/adr/` — прямое требование `../runbooks/pipeline-broken-at-night.md` |
| Правка тактическая, нормы не трогает | ADR не нужен: коммит + обновление хендбука |

**Ни один ADR в проекте пока не имеет статуса «заменено»** — заменяющий ADR должен явно проставить старому статус «заменено ADR-XXXX».

---

## Как изменить / Как расширить

По приоритету — от максимальной отдачи к минимальной:

1. **Создать `CLAUDE.md`** из черновика §1. 10 минут, снимает большинство типовых ошибок агента (правка генерата, выдуманные флаги, литералы в экранах). Дальше — держать его синхронным с кодом: устаревший `CLAUDE.md` вреднее отсутствующего.
2. **Завести `.claude/settings.json`** с `permissions.deny` на `game/generated/**`, `game/assets/**`, `game/tl/**`, `build/**`, `.vncache/**`, `**/*.rpyc` — генерат не будет съедать контекст. Честное ограничение: deny-правила не фильтруют вывод рекурсивного поиска и не действуют на подпроцессы, которые открывают файлы сами.
3. **Повесить детерминированный гейт** на завершение хода агента: `vn content lint` (5–10 с) или полный `vn content lint && vn build`. Текстовое правило «всегда прогоняй линт» — это контекст, а не гарантия; гарантия — только хук или CI-шаг.
4. **Завести `AGENTS.md`** — только когда появится агент другого вендора. Тонким указателем на `CLAUDE.md`, без дублирования содержимого.
5. **Поднять PR-процесс для правок агента.** Инфраструктура готова: `ci.yml` уже триггерится на `pull_request`; не хватает только реальных хэндлов в `../../CODEOWNERS` (сейчас все — плейсхолдеры) и branch protection.
6. **Закрыть непокрытые зоны в `CODEOWNERS`**: `/content/gallery/`, `/content/achievements/`, `/content/ui/`, `/content/licenses.yaml`, `/packs/`, `/assets_src/`, `/game/fonts/`, `/.github/` — формально ничьи, а `/.github/` содержит релизный workflow.

## Чего НЕ делать

- **Не копировать `../ARCHITECTURE.md` в `CLAUDE.md`.** 4182 строки утопят инструкции; агент начнёт игнорировать файл целиком.
- **Не превращать `CLAUDE.md` в карту каталогов.** Раскладка выводится из репозитория за один `ls`. В файл идут грабли, конвенции и решения, которые нельзя вывести из кода.
- **Не держать `CLAUDE.md` и `AGENTS.md` с пересекающимся содержимым.** Два источника правды расходятся молча, и расхождение проявляется как дублированная подсистема.
- **Не делать симлинк `AGENTS.md → CLAUDE.md`** на Windows без Developer Mode: команда просто не выполнится. Импорт первой строкой (`@AGENTS.md`) решает ту же задачу.
- **Не описывать в правилах агента то, что должно быть гарантией.** «Никогда не коммить генерат» текстом — пожелание; `.gitignore` + CI-шаг — гарантия.
- **Не оставлять статусы механизмов без обновления.** `IMPLEMENTED` рядом с удалённым кодом — прямая инструкция агенту строить поверх пустоты.
- **Не заводить `REVIEW.md` «на будущее»** — локальное ревью его не читает, а лишний файл начнёт расходиться с `CLAUDE.md`.

## Проверка

```bash
# 1. Правила согласованы с реальностью CLI
vn --help                                        # 20 команд/групп; список = таблице §4
grep -n "_stub(" tools/vn/src/vn/cli.py          # 371,372,958,1087,1260,1405,1565 (+ _stub_group :501-505)

# 2. Запретные зоны не тронуты
git status --short                               # ничего из game/generated|assets|tl|build|.vncache
git diff --stat                                  # объём правки совпадает с заявленным в отчёте

# 3. Обязательный хвост
vn content lint
vn build
vn content compile --check
python -m pytest tools/vn/tests -q               # 400 passed

# 4. По зоне правки
vn loc keys --check                              # реплики/меню
vn test smoke --picks 0,0                        # рантайм, экраны, флоу
vn save check && vn save corpus                  # состояние, миграции
vn release validate --flavor public              # релизный путь
```

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `docs/handbook/README.md` → профильный файл; `../../tools/vn/src/vn/cli.py` (истина по командам и флагам); `../../tools/vn/src/vn/content/lint.py` (33 диагностики — что вообще считается ошибкой); `../../.gitignore`; [02-architecture.md](02-architecture.md) §2–3 (зоны) и §6 (нормы G/C); [04-development-workflow.md](04-development-workflow.md) §5 (чеклисты) |
| **Не трогать** | `game/generated/**`, `game/assets/**`, `game/tl/**`, `game/build_id.json`, `build/**`, `.vncache/**` — производные зоны; `ci/fixtures/rpyc-line/**` — линия statement-имён (G6), управляется только через `vn save corpus`; `docs/ARCHITECTURE.md` раздел 0 — только через ADR |
| **Зависимости** | Этот файл описывает правила, а не механизм: сломать им можно только доверие к отчётам. Обратная зависимость сильная — при появлении `CLAUDE.md` его содержимое обязано совпадать с §1 и §3, иначе агент получит два расходящихся набора правил |
| **Валидация** | `vn --help` (команды существуют), `grep -n "_stub(" tools/vn/src/vn/cli.py` (список заглушек актуален), `vn content lint && vn build && python -m pytest tools/vn/tests -q` |
| **Частые ошибки** | 1) выдать текст `ARCHITECTURE.md` за работающую функциональность; 2) выдумать флаг (`--use-artifact`, `vn validate`, `--strict`) — их нет, exit 2; 3) отчитаться «готово» без фактического вывода команд; 4) починить симптом понижением `status` главы до `draft` (G15) или ослаблением схемы; 5) править `game/generated/**.gen.rpy`, увидев там ошибку; 6) счесть работающим механизм, у которого есть файл, но нет читателей (`flags.yaml`, `anchors.yaml`, `vn.beat()` — а вот `tools/vn.lock` с 2026-08-08 читается в CI, список инертного сузился, сверяйтесь с §5) |
