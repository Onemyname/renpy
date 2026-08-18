# 06. Фронтенд: UI-слой

> **Статус подсистемы:** IMPLEMENTED — все экраны игры написаны вручную (23 объявления `screen` в 9 файлах `20_ui/screens/` + 7 переиспользуемых компонентов `vn_*` в `components.rpy`, включая controller-first каркас `vn_modal_dialog`; единственный генерируемый экран — `chapter_select`), работают на токенах `gui.*` и восьми генерируемых 9-patch панелях — теперь в двух масштабах каждая (`<id>.webp` + `<id>@2.webp`, ADR-0012). Главное «но»: `theme.yaml` фазы 2 не существует, токены `gui.radius_*` мертвы. Правило `2*Borders` теперь под тестом со стороны потребителей — **нарушений в вёрстке нет** (последнее, в галерее, закрыто парой панелей `chip`/`chip_active`).
> **Отвечает на вопрос:** «Куда положить новую кнопку/панель/строку интерфейса, чтобы не сломать локализацию, панели и smoke-прогон».

UI-слой — это `game/gui.rpy` (85 строк токенов) + `game/framework/20_ui/` (12 файлов `.rpy`, 1553 строки рукописного Ren'Py: `components.rpy` 385, `scale.rpy` 57 и `input.rpy` 29 — платформенные токены и раскладка пада ([39](39-platforms.md)), `images.rpy` 5 и восемь экранов в `screens/`) + два генерата: `game/generated/registry/ui_frames.gen.rpy` (фоны-панели) и `game/generated/screens/chapter_select.gen.rpy` (единственный генерируемый экран). Всё остальное в `game/generated/` к UI отношения не имеет. Ни одного бинарного UI-ассета в git нет: скругления, тени и градиенты рисует конвейер из `content/ui/panels.yaml` (ADR-0009), маркеры и индикаторы собраны из `Solid` + `Transform`.

## Быстрый ответ

```bash
# Поменять цвет/размер/отступ           -> game/gui.rpy (только define gui.*)
# Поменять форму фона (радиус/тень)     -> content/ui/panels.yaml + vn build
# Поменять текст интерфейса             -> content/ui/strings.yaml + vn loc extract/import
# Поменять вёрстку экрана               -> game/framework/20_ui/screens/<экран>.rpy
# Переиспользуемый кусок вёрстки        -> game/framework/20_ui/components.rpy (screen vn_*)
vn build                                    # схемы -> панели -> генерат -> импорт переводов
"$RENPY_SDK/renpy.exe" . lint                # движковый линт
vn test smoke --picks 0,0                    # автопрохождение, скриншоты в .vncache/smoke/
```

Магических чисел в экранах быть не должно — только `gui.*`. Строковых литералов в экранах быть не должно — только `vn_loc.t("ui.…")`. Путей к картинкам в стилях быть не должно — только `vn_frame_<id>`.

## Архитектура UI-слоя: четыре этажа

| Этаж | Файл | Что содержит | Кто пишет |
|---|---|---|---|
| 1. Токены | `game/gui.rpy` (`init offset = -2`, :6) | палитра, шрифты, размеры, шкала отступов, радиусы, габариты слотов | человек |
| 2. Компоненты | `game/framework/20_ui/components.rpy` (`init offset = 0`, :5) | базовые стили + 7 переиспользуемых `screen vn_*` (в т.ч. `vn_modal_dialog`) + пресет `vn_scroll_props` + `vn_ui.reveal` + `image vn_ctc` + 2 трансформа | человек |
| 2a. Платформенные токены | `game/framework/20_ui/scale.rpy` (`init -4` / `offset = -3`), `input.rpy` (`init python`) | `gui.ui_scale`, `gui.overscan_pad`, дополнения `config.pad_bindings` — [39-platforms.md](39-platforms.md) | человек |
| 3. Экраны | `game/framework/20_ui/screens/*.rpy` (8 файлов) | say/choice/history/quick_menu/main_menu/navigation/preferences/save/load/gallery/crash/watermark/unavailable | человек |
| 4. Генерат | `game/generated/registry/ui_frames.gen.rpy`, `game/generated/screens/chapter_select.gen.rpy` | `define vn_frame_<id> = Frame(...)`, экран выбора глав | `vn build` |

Порядок инициализации обязателен именно такой: `gui.rpy` на `-2` должен выполниться **до** стилей на `0`, иначе `gui.accent_color` в `style` будет неопределён. `ui_frames.gen.rpy` тоже на `0` — Ren'Py сортирует `.rpy` одного приоритета по пути, `game/generated/...` идёт раньше `game/framework/...`, поэтому `vn_frame_choice` уже определён к моменту разбора `style choice_button`. Полная карта init-приоритетов — [05-renpy-development.md](05-renpy-development.md), норматив — [ADR-0003](../adr/0003-init-scale-engine-limit.md).

**Статус: IMPLEMENTED.** Единственная нештатная зависимость этажей — `chapter_select.gen.rpy:11,19` использует компоненты `vn_game_menu` и `vn_chapter_card` из этажа 2; генерат не самодостаточен и упадёт, если эти компоненты переименовать.

## Дизайн-токены (`game/gui.rpy`) — полная таблица

`gui.init(1920, 1080)` (`gui.rpy:9`) — виртуальное разрешение всей игры. Все числа ниже — пиксели этой сетки.

Комментарий `gui.rpy:1-4` фиксирует замысел: имена выбраны так, чтобы миграция в `theme.yaml` фазы 2 (`palette.* / typography.* / spacing.* / radius.* / components.*`) была механической. **`theme.yaml` — NOT IMPLEMENTED**: ни файла, ни схемы, ни кода-читателя не существует; сегодня `gui.rpy` — единственный источник токенов.

### Палитра (`gui.rpy:12-33`)

| Токен | Hex | Семантика (комментарий в коде) |
|---|---|---|
| `gui.interface_bg` | `#09090b` | `palette.bg` — фон главного меню |
| `gui.menu_bg` | `#0b0b0e` | `palette.bg_content` — канва игрового меню |
| `gui.panel_bg` | `#18181b` | `palette.surface` |
| `gui.panel_bg_hover` | `#27272a` | `palette.surface_hover` |
| `gui.panel_bg_deep` | `#131316` | `palette.surface_deep` — вложенные панели |
| `gui.rail_bg` | `#0f0f13fa` | `palette.rail` — левая рельса меню |
| `gui.panel_border` | `#27272a` | `palette.border` |
| `gui.panel_border2` | `#3f3f46` | `palette.border_strong` |
| `gui.divider_color` | `#1f1f23` | `palette.divider` |
| `gui.text_color` | `#fafafa` | `text.primary` |
| `gui.sub_color` | `#d4d4d8` | `text.secondary` |
| `gui.muted_color` | `#a1a1aa` | `text.muted` |
| `gui.faint_color` | `#71717a` | `text.faint` |
| `gui.insensitive_color` | `#52525b` | `text.insensitive` |
| `gui.accent_color` | `#fbbf24` | `accent.primary` (янтарь) |
| `gui.hover_color` | `#fcd34d` | `accent.hover` |
| `gui.on_accent_color` | `#1c1917` | `accent.contrast` — текст на акценте |
| `gui.selected_color` | `#ffffff` | — |
| `gui.idle_color` | `= gui.muted_color` | алиас |
| `gui.danger_color` | `#ef4444` | `palette.danger` |

### Диалоговое окно (`gui.rpy:36-41`)

| Токен | Значение | Где применяется |
|---|---|---|
| `gui.textbox_scrim` | `#000000` | цвет ступеней `vn_scrim` |
| `gui.textbox_scrim_alpha` | `0.82` | плотность нижней ступени |
| `gui.textbox_height` | `500` | высота зоны scrim по умолчанию |
| `gui.textbox_side_pad` | `240` | боковые поля `style window`, `xpos` стека выборов |
| `gui.textbox_bottom_pad` | `78` | нижний отступ `style window` |
| `gui.dialogue_width` | `1180` | `xmaximum` реплики |

### Типографика (`gui.rpy:46-62`)

Шрифты лежат в `game/fonts/` вместе с лицензиями OFL. **Хардкодить `font "..."` в стилях запрещено** (`gui.rpy:44-45`): языковые пакеты переопределяют шрифты через `gui.*` и манифест `tl/<code>/language.json`.

| Токен шрифта | Файл | Роль |
|---|---|---|
| `gui.text_font` | `fonts/Literata-Regular.ttf` | диалоги, wordmark, номер главы |
| `gui.name_text_font` | `fonts/Inter-SemiBold.ttf` | имя персонажа |
| `gui.interface_text_font` | `fonts/Inter-Regular.ttf` | интерфейс |
| `gui.interface_semibold_font` | `fonts/Inter-SemiBold.ttf` | заголовки, кнопки, caps-группы |

| Токен размера | px | Где |
|---|---|---|
| `gui.text_size` | 34 | реплика |
| `gui.name_text_size` | 29 | имя говорящего |
| `gui.interface_text_size` | 21 | пункты меню/навигации |
| `gui.button_text_size` | 17 | `vn_button` (confirm) |
| `gui.label_text_size` | 34 | заголовки экранов, прогресс галереи |
| `gui.group_text_size` | 13 | caps-заголовки групп настроек |
| `gui.small_text_size` | 15 | подписи, номера выборов, вкладки галереи |
| `gui.tiny_text_size` | 13 | quick menu, чипы, DLC-бейдж |
| `gui.choice_text_size` | 25 | текст пункта выбора |
| `gui.choice_width` | 880 | ширина стека выборов (не размер шрифта) |
| `gui.title_text_size` | 110 | wordmark главного меню |

**Интерфейсные кегли умножаются на `gui.ui_scale`** (`gui.rpy:52,58-64`): числа выше — база при масштабе 1.0. На Steam Deck / Big Picture (или при выборе «крупный» в настройках) множитель 1.4 даёт `interface 21 → 29`, `button 17 → 24`, `tiny 13 → 18`. Масштаб только вверх: `< 1.0` сплющил бы 9-patch панели, считающие минимумы `2*Borders` от базовых кеглей. Подробности — [39-platforms.md](39-platforms.md) §8.

### Шкала отступов (`gui.rpy:65-69`)

`gui.sp_xs 4` · `gui.sp_s 8` · `gui.sp_m 16` · `gui.sp_l 32` · `gui.sp_xl 64`.

Практика в коде — арифметика поверх шкалы, а не новые числа: `padding (gui.sp_l - 6, gui.sp_m - 1)` (`choice.rpy:66`), `size gui.label_text_size - gui.sp_s` (`core_screens.rpy:222`), `spacing gui.sp_xl + gui.sp_m` (`core_screens.rpy:77`). Так и продолжайте.

### Радиусы (`gui.rpy:72-73`) — **IMPLEMENTED / МЁРТВЫЕ**

`gui.radius_button = 8`, `gui.radius_panel = 12`. Комментарий обещает «применятся с ui-ассетами», но **ни одной ссылки на них в `game/**/*.rpy` нет**. Настоящие радиусы живут в `content/ui/panels.yaml` (`choice` 14, `panel` 18, `slot` 10, `toast` 12). Это два источника истины — ровно та проблема, против которой писался ADR-0009. Меняя радиус, правьте `panels.yaml`; трогать `gui.radius_*` бесполезно.

### Сейв-слоты (`gui.rpy:76-78`)

`gui.slot_width 440`, `gui.slot_thumb_height 248`, `gui.slot_height 330`. Первые два дополнительно управляют скриншотом сейва: `config.thumbnail_width/height` (`core_screens.rpy:15-16`).

### Чего в токенах НЕТ (жёстко зашито в экранах)

Это не ошибка, а честный долг: рельса `xsize 336` (`core_screens.rpy:125`), кнопка навигации `xsize 248` (:130), контент-фрейм `xpos 336 / xsize 1584 / ysize 1080` (`components.rpy:141-157`), ячейка галереи `(472, 266)` и сетка `ysize 800` (`gallery.rpy:53,74,183`), viewport истории `1100×830` (`history.rpy:29-30`), якорь quick menu `(1864, 1066)` (`quick_menu.rpy:17-18`), диалог подтверждения `xsize 560` (`core_screens.rpy:426`). Плюс несколько цветовых литералов мимо палитры: `"#e4e4e7"` (`choice.rpy:87`, `gallery.rpy:231`), `"#e4e4e79e"` (`quick_menu.rpy:51`), `Solid("#18181bf2")` у тоста (`core_screens.rpy:452`). Добавляя код, не увеличивайте этот список.

## Библиотека компонентов (`components.rpy`)

Правило именования — `^vn_[a-z0-9_]+$` (`components.rpy:1`). Без бинарных картинок: `Solid` / `Frame` / `Transform` / ATL / outlines / alpha (`components.rpy:3`).

**Базовые стили** (наследуются всем UI): `style default` :9 (шрифт диалога), `style button_text` :14, `style label_text` :22, `style frame` :27, `style input_prompt` :31.

**Образы и трансформы**

| Символ | Определение | Где используется |
|---|---|---|
| `image vn_ctc` :36 | `Transform(Solid(gui.accent_color), xysize=(14,14), rotate=45)` — ромб «жду клика» | `screen say` (`core_screens.rpy:37`) |
| `transform vn_ctc_blink` :38 | ATL-цикл 0.7 с: alpha 1.0↔0.3 + `yoffset` 0↔4 | там же |
| `transform vn_toast_in` :44 | alpha 0→1, `yoffset -14`→0 за 0.25 с | `screen notify` (`core_screens.rpy:463-465`) |

**Компоненты**

| `screen` | Параметры | Что рисует | Где используется |
|---|---|---|---|
| `vn_scrim(height=None)` :51 | `height`, по умолчанию `gui.textbox_height` | 7-ступенчатый градиент из `Solid(gui.textbox_scrim)` с alpha `(0.0, 0.10, 0.24, 0.42, 0.60, 0.74, gui.textbox_scrim_alpha)` — движок не рисует градиент без картинки (:48-49) | `say` (`core_screens.rpy:24`), `input` (:60), `choice` (`choice.rpy:35`) |
| `vn_panel(title=None)` :64 | `title` + `transclude` | фрейм `style vn_panel` + заголовок | **нигде. IMPLEMENTED / UNUSED** — ноль `use vn_panel` в репозитории |
| `vn_modal_dialog(cancel_action)` :171 | безопасное действие отмены | затемнение + `key "game_menu"` → отмена + рамка; `modal`/`zorder` объявляет **потребитель** (при `use` не наследуются) | `confirm`, `vn_content_unavailable` |
| `vn_button(label, action, kind, sensitive)` :198 | `kind ∈ primary\|secondary\|danger` → стили `vn_btn_<kind>` / `vn_btn_<kind>_text` (:208-233) | кнопка-действие на `Solid` (акцент / поверхность / красный текст) | `screen confirm` (`core_screens.rpy:493-494`), `vn_content_unavailable` |
| `vn_game_menu(title)` :249 | `title` + `transclude` | `Solid(gui.menu_bg)` + `use navigation` + контент-фрейм `xpos 336, xsize 1584` (:259-265) | `file_menu`, `preferences`, `gallery`, **`achievements`**, `chapter_select` |
| `vn_save_slot(slot, is_save, focus_default)` :273 | номер слота, режим, флаг первого фокуса | скриншот `FileScreenshot`, бейдж «новейший» (`FileNewest`), чип с номером, время+имя, кнопка `×` с собственным `Confirm` (:311-315) | `file_menu` (`core_screens.rpy:276`) |
| `vn_chapter_card(ch, row, rows, focus_default)` :398 | элемент `VN_CHAPTERS` + координаты в сетке | карточка главы: номер из `ch["id"][2:]`, бейдж DLC при `ch["pack"] != "core"`, `action Start(ch["entry_label"])` | `chapter_select.gen.rpy:24` |

**Общие стили экранов-коллекций** (`components.rpy:76-89`) — один набор на галерею и достижения, потому что «счётчик N из M» и «здесь пока ничего нет» выглядят одинаково по определению, а копии в каждом экране разъезжаются при первой правке кегля:

| Стиль | Что это | Кто использует |
|---|---|---|
| `style vn_counter` :81 | счётчик прогресса акцентом, кегль `gui.label_text_size` | `gallery.rpy:37` («N / M»), `achievements.rpy:49` («Получено N из M») |
| `style vn_empty_note` :86 | «пусто» приглушённым текстом | `gallery.rpy:48`, `achievements.rpy:54` |

**Хелперы `vn_ui`** (`init -990 python in vn_ui`, `components.rpy:115-163`):

| Функция | Что делает | Зачем не в вёрстке |
|---|---|---|
| `reveal(screen, vp_id, row, rows, peek)` :118 | докручивает `adjustment` скролл-зоны к сфокусированному ряду и «подглядывает» следующий | движок не докручивает viewport к клавиатурному фокусу; вешается на `hovered` ячейки |
| `hint(key)` :142 | подсказка управления по **паре** ключей: `key + "_pad"` при `vn_platform.controller_first()`, иначе `key + "_kbd"` | «Esc» на паде не нажать; глифов кнопок картинками у нас нет, поэтому кнопка называется словом и падеж решает переводчик. Оба суффикса явные — забытый ключ виден сразу |
| `menu_screen()` :155 | имя открытого экрана меню (по тегу `menu`) | нужно резервному фокусу рельсы: он садится на пункт **текущего** экрана |

Важная деталь (`components.rpy:276-277`): загрузка внутри игры оборачивается в **свой** `Confirm(vn_loc.t("ui.confirm.load"), FileLoad(slot, confirm=False), confirm_selected=True)`, потому что движковый confirm у `FileLoad` — английская layout-строка, которую наш конвейер переводов не покрывает. Тот же приём — у удаления (`:311-315`), выхода (`core_screens.rpy:11-12,132`) и возврата в главное меню (`:135`).

В `core_screens.rpy` живут ещё три переиспользуемых экрана, не вынесенных в `components.rpy`: `file_menu(title, is_save)` :261, `vn_pref_slider(label_text, value_action)` :382, `language_picker()` :426.

## Инвентарь экранов

| Экран | Файл:строка | Назначение | Ключевые особенности |
|---|---|---|---|
| `say(who, what)` | `core_screens.rpy:21` | реплика | прозрачное окно + `vn_scrim`; id `window`/`who`/`what` сохранены (контракт движка); CTC-ромб; **зарезервирована колонка под side-image — сам side-image NOT IMPLEMENTED** |
| `input(prompt)` | `core_screens.rpy:59` | ввод текста | тот же scrim; потребителей нет (`renpy.input` не вызывается), но подтверждение с пада есть — A/RT шлют `input_enter` (`input.rpy:37-38`) |
| `navigation()` | `core_screens.rpy:71` | левая рельса / колонка меню | ветвится по `main_menu`; пункт «Главы» только если `vn_registry.chapters()`; «Галерея» — если `vn_gal.categories()` (:110); «Достижения» — если `vn_ach.visible_ids()` (:116) |
| `main_menu()` | `core_screens.rpy:179` | главное меню | `tag menu`; wordmark `[config.name!t]`; «Продолжить» появляется по `renpy.newest_slot()` (:195). Ни «Галереи», ни «Достижений» в колонке нет — оба доступны только через рельсу игрового меню (осознанно, как у галереи) |
| `save()` / `load()` / `file_menu` | `core_screens.rpy:253,257,261` | сейвы | 4 страницы + autopage, сетка 3×2 из `vn_save_slot` |
| `preferences()` | `core_screens.rpy:294` | настройки | экран/текст/громкости/пропуск + `language_picker`; никаких настроек шрифта |
| `language_picker()` | `core_screens.rpy:426` | список языков | данные **только** из `vn_lang.available()`; шрифт пункта из манифеста языка с fallback; `viewport` со всеми четырьмя `vscrollbar_*` — без них полоса не рисуется |
| `confirm(message, yes, no)` | `core_screens.rpy:480` | модальное подтверждение | `modal True`, `zorder 200`; в автопилоте сам жмёт «Да» (:484-485) |
| `notify(message)` | `core_screens.rpy:497` | тост | `at vn_toast_in`, авто-`Hide` через 3.25 с; используется галереей для «открыт новый материал» |
| `choice(items)` | `choice.rpy:30` | выбор | см. отдельный раздел |
| `history()` | `history.rpy:8` | бэклог | `config.history_length = 250` (:6); цвет имени берётся из `h.who_args["color"]` (:47); подсказка закрытия — `vn_ui.hint("ui.history.hint")` (:18), парные ключи `_kbd`/`_pad`; вертикальный ритм через `spacing`, **не** `ypadding` |
| `achievements()` / `vn_ach_card` | `achievements.rpy:38,79` | достижения | экран не знает ни одной ачивки: список, названия и «скрытость» спрашивает у `vn_ach`. Спойлер-гейт один (`_spoiler = spec["hidden"] and not _got`) — настоящий текст скрытой неполученной в дерево отображения не попадает вовсе. Счётчик считает только `visible()`, поэтому 100 % достижимы в любом флейворе |
| `vn_quick_menu()` | `quick_menu.rpy:8` | нижняя панель быстрых действий | подключается через `config.overlay_screens` (:41); прячется, когда открыт экран с `tag menu` (:12); высота кликабельной зоны ≥ 48 px за счёт `padding (13, 17)` |
| `gallery()` / `vn_gal_cell` / `gallery_viewer` | `gallery.rpy:21,73,105` | галерея | экран не знает ни элементов, ни правил разблокировки — только спрашивает `vn_gal`; подробности — [15-gallery.md](15-gallery.md) |
| `_exception(...)` | `crash_screen.rpy:37` | брендированный экран краха | движок подхватывает сам; **нулевые зависимости от `gui.*`** (:5-18) — экран обязан пережить краш init-фазы; строки через защищённый `_vn_ct(key, fallback)` :21. Единственное место, где легальны числовые литералы: кегли, приоритеты фокуса, геометрия и визуалы скроллбара |
| `vn_build_overlay()` | `build_overlay.rpy:6` | вотермарка билда | вешается в `config.overlay_screens` только при `vn_build.watermark` (:19-20) |
| `chapter_select()` | `game/generated/screens/chapter_select.gen.rpy:17` | выбор глав | **генерат**, правки перезапишутся; гейт владения паком `vn.pack_registry.owned(ch["pack"])` :21 |
| `vn_debug_hotkeys` / `vn_debug_jump` | `game/framework/90_debug/020_jump_menu.rpy:10,14` | Shift+J — прыжок в сцену | только при `config.developer`; вырезается из релиза через `build.classify` (`game/options.rpy:24`) |

Итого 23 объявления `screen` в `20_ui/screens/` (9 файлов) + 7 компонентов в `components.rpy` + 1 генерат = **31**; `renpy.sh . lint` печатает **33** — плюс два дев-экрана из `90_debug/`.

**Экран достижений существует с этой итерации** (`achievements.rpy`) — раньше `080_achievements.rpy` начислял и хранил, а показать было негде. Подробности подсистемы — [15-gallery.md](15-gallery.md), путь ачивки до Steamworks — [40-steamworks.md](40-steamworks.md) §6.

## Экран выбора (`choice.rpy`, 88 строк)

**Статус: IMPLEMENTED.** Реализован по брифу `docs/pipeline/design-brief-choices.md` (коммит `de888de`). Из 7 названных в брифе проблем закрыто 6; пункт 4 («визуальная иерархия: обычный ответ vs ключевое решение») **NOT IMPLEMENTED** — механизма приоритета нет ни в `choice.rpy`, ни в `panels.yaml`.

Устройство:

- Стек прижат к низу и растёт **вверх**: `style choice_vbox` :57 — `xpos gui.textbox_side_pad` (240), `yanchor 1.0`, `ypos 1080 - gui.sp_xl` (1016), `xsize gui.choice_width` (880). Лицо персонажа не перекрывается, 2 и 5 вариантов выглядят одинаково.
- Ряд — `button` с `side "l c r"` (:44): слева номер `text "[_num]"` (`style choice_num`, `min_width 26`), в центре текст, справа маркер «уже выбирали».
- Текст пункта — **только** `vn_loc.choice_text(vn_menu, idx, i.caption)` (:47). Это жёсткий контракт G8/C1.
- `i.chosen` (вариант выбирали в прошлом прохождении): стиль переключается на `choice_button_chosen` (:41) с плоским фоном `vn_frame_choice_chosen`, плюс ромб `image vn_chosen_mark` 9×9 (:22).
- Появление: `transform vn_choice_in(d)` :25 (alpha 0 + `yoffset 14` → `easeout 0.22`), применяется как `at vn_choice_in(idx * 0.05)` :42 — каскад 50 мс на пункт.
- Клавиатура: `key ("K_%d" % _num) action i.action` для `_num <= 9` (:49-51).
- Затемнение: `Solid("#00000040")` на весь экран + `use vn_scrim(min(720, 280 + 100 * len(items)))` :34-35 — высота scrim следует числу вариантов.
- Фоны — генерируемые панели: `vn_frame_choice` / `_hover` / `_chosen` (:67-71).
- QA-автопилот :53-54 — блок обязан остаться дословно, иначе ломается `vn test smoke`. Он сделан **таймером**, а не выражением экрана, потому что экраны переоцениваются предсказанием (`030_flow.rpy:131-133`).
- Состояния `insensitive` нет и не будет: условные пункты меню запрещены компилятором (:16-17) — условный ответ делается ветвлением сцены, см. [13-dialogue.md](13-dialogue.md).

**Как это переводится.** Автор пишет `menu:` в `*.scene.rpy`, компилятор эмитит перед ним `$ vn_menu = "chNN_sNNN_mNNN"` (реально: `game/generated/scenes/ch01/ch01_s010.gen.rpy:29`). Исходные подписи попадают в `define VN_MENUS` (`game/generated/registry/menus.gen.rpy:11`), переводы — в `VN_MENUS_TL[lang]` из `game/tl/<lang>/common.rpy` на `init 600`. Рантайм: `vn_loc.choice_text(menu_id, idx, caption)` (`040_localization.rpy:143-149`) ищет `VN_MENUS_TL[lang][menu_id][idx]`, при промахе возвращает авторский caption. Отсюда следствие: **порядок пунктов меню — часть ключа перевода**. Переставили пункты — переводы поедут молча.

## Генерируемые UI-панели (ADR-0009)

**Статус: IMPLEMENTED / UNDOCUMENTED в `docs/ARCHITECTURE.md`** — grep по `ui_panel|panels.yaml|vn_frame` в ARCHITECTURE.md даёт 0 попаданий. Единственный норматив — [ADR-0009](../adr/0009-generated-ui-panels.md).

Цепочка:

```
content/ui/panels.yaml  --(ui_panel@1)-->  game/assets/ui/<id>.webp     (lossless WebP, 9-patch)
                                           game/assets/ui/<id>@2.webp   (то же, нарисованное вдвое крупнее)
                        --(compile)------>  define vn_frame_<id> = Frame(..., Borders(r,r,r,r), tile=False)
```

**Варианты `@N` — с этой итерации (ADR-0012).** Декларация задана в виртуальных пикселях, а физический
экран бывает крупнее: на 4K одна и та же картинка растягивалась бы, размывая углы и обводку 1 px.
Поэтому панель **рисуется заново** в каждом отгружаемом масштабе (набор — `render.classes.ui.variants`,
сегодня `[1, 2]`): умножаются `radius`, `border.width`, `shadow.blur`, `shadow.dy` и тянущаяся полоса.
Вёрстку это не касается вовсе — в `Frame` уезжает **безсуффиксное** имя, а `Borders` остаются
**виртуальными**: оверсэмпленную картинку движок «считает меньше в N раз для целей вёрстки»
(`renpy/display/im.py: Cache._make_render`, `imagelike.py: Frame.render` — `xborder = min(bw, sw - 2, dw)`).
Масштабировать `Borders` нельзя: это удвоило бы поля вёрстки на 4K. Подробности и оговорка про Steam Deck
(там `draw_per_virt ≈ 0.667`, оверсэмпл не включается вообще) — [42-big-picture.md](42-big-picture.md) §5.4.

Ключи панели (`ui_panels@1`, `additionalProperties: false`): `radius` (0…64), `fill` (строка-цвет **или** `{from, to}` — вертикальный градиент), `border.{color,width}` (0…8), `shadow.{color,blur,dy}`, `tile`, `doc`. Id панели — `^[a-z][a-z0-9_]*$`.

Восемь генерируемых панелей и их геометрия (`content/ui/panels.yaml:19-79` → `ui_frames.gen.rpy:12-19`). Панелей стало восемь: пара `chip` / `chip_active` добавлена, чтобы закрыть нарушение `2*Borders` в галерее (ADR-0009, см. ниже):

| id | radius | Borders | минимум элемента | Кто использует |
|---|---|---|---|---|
| `choice` | 14 | 27 | **54×54** | `choice.rpy:77` |
| `choice_chosen` | 14 | 15 | **30×30** | `choice.rpy:81` |
| `choice_hover` | 14 | 30 | **60×60** | `choice.rpy:78,86`, `gallery.rpy:199` |
| `chip` | 8 | 11 | **22×22** | `gallery.rpy:185,234` |
| `chip_active` | 8 | 11 | **22×22** | `gallery.rpy:186,235` |
| `panel` | 18 | 56 | **112×112** | никто |
| `slot` | 10 | 11 | **22×22** | `gallery.rpy:198`, `achievements.rpy:101` |
| `toast` | 12 | 38 | **76×76** | никто |

Пары читаются как один набор: `chip`/`chip_active` повторяют заливку и обводку
`choice`/`choice_hover` (та же система выборов), но с малым радиусом и почти
прижатой тенью — чтобы поместиться в кнопку высотой 29-31 px.

### Практическое правило: элемент не меньше `2*Borders`

`Borders = radius + max(blur + |dy|, border.width)`. Элемент **меньше `2*Borders` по любой оси** заставляет движок сжать 9-patch: фон «сплющивается», кнопка превращается в тонкую пилюлю. Это уже случалось (`ADR-0009:44-47`: `blur: 18` дал `Borders(38)` → минимум 76 px при кнопке ниже).

Минимальный размер каждой панели печатается комментарием прямо в генерате:

```renpy
define vn_frame_choice = Frame("assets/ui/choice.webp", Borders(27, 27, 27, 27), tile=False)   # минимум 54x54 px
```

Считайте высоту кнопки как `верхний padding + нижний padding + высота строки`. Эталон — сам экран выбора: `padding (26, 15)` + строка 25 px ≈ 65 px ≥ 60 (`choice.rpy:10-12,66`).

**Элемент меньше панели — чините панель, а не элемент.** Так закрыт бывший дефект галереи: вкладка (`vn_gal_tab`, 6+19+6 = **31 px**) и кнопка просмотрщика (`vn_gal_ctl_button`, 6+17+6 = **29 px**) стояли на `vn_frame_choice_hover` (60 px) и `vn_frame_choice` (54 px) — вдвое выше самих кнопок, фон сплющивался. Растить кнопки до 54-60 px значило превратить ряд вкладок в панель выше заголовка, а ряд кнопок просмотрщика — в толстый тулбар поверх кадра. Вместо этого объявлена пара `chip`/`chip_active` под реальный размер (минимум 22×22): рамка подгоняется под вёрстку декларацией, как и требует ADR-0009.

Проверяют это два теста в `tools/vn/tests/test_ui_panels.py`:

| Тест | Что ловит |
|---|---|
| `test_repo_panels_declaration_is_valid` (:226) | декларации `choice*` не толще 60 px |
| `test_every_frame_consumer_is_not_smaller_than_2x_borders` (:244) | **каждый** `background vn_frame_<id>` в `game/**/*.rpy`: разбирает `style`-блоки и токены `gui.*`, считает высоту как `padding + ascent + descent` шрифта и сверяет с `2*Borders` |
| `test_gallery_chips_fit_their_small_buttons` (:284) | чипы не растолстели, и вкладка/кнопка просмотрщика не вернулись на `choice*` |

Ограничение потребительского теста: ось, которую задаёт содержимое (текст без `xsize`/`xfill`), не проверяется — её ширину знает только рантайм. Высота текста берётся по метрикам шрифта из репозитория, то есть это оценка того, что посчитает Ren'Py, а не сам движок.

Ещё три факта, о которые спотыкаются:

- `vn_frame_panel` и `vn_frame_toast` **генерируются и не используются**: `style frame` (`components.rpy:27-29`) и `style vn_slot` (:178-182) до сих пор на плоском `Solid`. Две WebP едут в сборку мёртвым грузом. Подключить их — самая дешёвая визуальная победа в проекте.
- Эмиттер **не проверяет**, что `game/assets/ui/<id>.webp` существует: объявили панель, но не собрали ассеты — получите `Frame` на несуществующий файл, узнаете об этом в рантайме или из `renpy lint`.
- Ключ кэша — весь спек панели целиком, включая `doc:` и `tile:`. Правка комментария вызывает перерисовку (байты выхода те же, файл не переписывается, но работа делается).
- `tile: true` схемой поддержан и эмитится, но **ни одна панель его не объявляет** — ветка не проверена ни разу.
- Отдельной команды на панели нет: `vn assets build --only ui_panel` не существует (`--only` есть только у `vn pipeline models`). Панели пересобираются полным `vn assets build` / `vn build`.

## Локализация UI

**Статус: IMPLEMENTED.** Строковых литералов в экранах нет — 95 ключей в `content/ui/strings.yaml` (`schema: strings@1`, плоская карта `key: "text"`, ключ `^[a-z0-9_.]+$`).

Путь строки:

```
content/ui/strings.yaml  --compile-->  define VN_STRINGS (registry/menus.gen.rpy, init offset -100)
                         --vn loc extract-->  loc/po/<lang>/common.po  (msgctxt "string:<key>")
                         --vn loc import--->  game/tl/<lang>/common.rpy: VN_STRINGS_TL['<lang>'] = {...}  (init 600)
рантайм: vn_loc.t("ui.nav.save")  ->  перевод -> исходник -> САМ КЛЮЧ
```

`vn_loc.t` (`040_localization.rpy:151-157`) при промахе возвращает **сам ключ** — опечатка не падает, а показывается игроку строкой `ui.nav.sve`. Проверок нет: **валидация литеральных ключей `vn_loc.t("…")` против `strings.yaml` — NOT IMPLEMENTED**. Проверяются только декларативные `title_key` глав (жёсткая ошибка) и `title_key`/`desc_key` галереи с достижениями (предупреждение).

`translate strings` для UI сознательно **не** используется (коллизии одинаковых текстов, `tools/vn/src/vn/loc/po.py:403-404`); `translate <lang> strings:` остался только для имён персонажей.

**Как добавить строку интерфейса:**

1. Ключ в `content/ui/strings.yaml` в подходящую секцию (`ui.nav.*`, `ui.prefs.*`, `ui.gallery.*`, `gal.*`, `meta.*`, …).
2. В экране — `text vn_loc.t("ui.…")`. Никаких литералов и никакого `_( )`.
3. `vn loc extract` — ключ уедет в `loc/po/{en,de,pseudo}/common.po` в домен `common`.
4. Перевести `en` и `de` (иначе релизный гейт покрытия 0.98 из `loc/loc.yaml` покраснеет).
5. `vn build` — он сам вызовет импорт переводов; либо отдельно `vn loc import`.
6. `vn loc report` — все языки должны остаться 100%.

Подробности round-trip — [14-localization.md](14-localization.md).

> Расхождение с нормативом: `docs/ARCHITECTURE.md:2648,2653-2657` описывает схему `ui_strings@1` с объектными значениями `{text, note}` и «кодогенератор экранов, подставляющий `_("…")`». В реальности схема называется `strings@1`, значения плоские строки, кодогенератора экранов нет. Побеждает код.

## Как изменить / Как расширить

### Чеклист «нужен новый элемент UI»

Идите строго сверху вниз и останавливайтесь на первом «да»:

1. **Есть готовый `vn_*` компонент или общий стиль?** — `vn_scrim`, `vn_panel`, `vn_modal_dialog`, `vn_button`, `vn_game_menu`, `vn_save_slot`, `vn_chapter_card`; плюс `style vn_counter` / `vn_empty_note` для экранов-коллекций и `vn_ui.hint(key)` для подсказок управления. Экран меню собирается из `use vn_game_menu(title):` + `transclude`, кнопка действия — `use vn_button(...)`. `vn_panel` ждёт первого потребителя.
2. **Есть нужный токен в `gui.*`?** — берите его или арифметику от шкалы (`gui.sp_l - 6`). Нового числа в экране быть не должно. Не хватает токена — заводите его в `gui.rpy` с семантическим комментарием (`palette.* / typography.* / spacing.*`), а не константу в экране.
3. **Нужна новая форма фона (скругление/тень/градиент/обводка)?** — панель в `content/ui/panels.yaml`, потом `background vn_frame_<id>` в стиле. Ни путей, ни пикселей в вёрстке.
4. **И только теперь — новый `screen`.** Имя `^vn_[a-z0-9_]+$`, файл в `game/framework/20_ui/` (переиспользуемое — в `components.rpy`, экран — в `screens/`), `init offset = 0`, тексты через `vn_loc.t`.

### Добавить панель

```yaml
# content/ui/panels.yaml
  tooltip:
    radius: 8
    fill: "#1c1c20f2"
    border: {color: "#ffffff1a", width: 1}
    shadow: {color: "#00000073", blur: 8, dy: 2}
    doc: "Всплывающая подсказка"
```

Минимум считается до сборки: `Borders = 8 + max(8 + 2, 1) = 18` → элемент не меньше **36×36 px**. Дальше `vn build`, сверить напечатанный минимум в `game/generated/registry/ui_frames.gen.rpy`, применить `background vn_frame_tooltip`. Удаление панели из YAML само удалит `game/assets/ui/tooltip.webp` (orphan-очистка по диффу манифеста).

### Поменять палитру целиком

Правите `gui.rpy:12-33` **и** hex-значения в `content/ui/panels.yaml` (комментарий `panels.yaml:9` требует держать их согласованными — автоматической связи нет). Затем `vn build`.

### Добавить экран в навигацию

Пункт в `screen navigation()` (`core_screens.rpy:97-119`) и/или в `main_menu()` (`:206-212`), с ключом строки и, если экран может быть пустым, — с гейтом-условием **по данным** (образцы: `if vn_gal.categories():` `:110` и `if vn_ach.visible_ids():` `:116` — гейт живёт в сторе, не в экране).

## Чего НЕ делать

- **Не править `game/generated/` и `game/assets/ui/`** — обе зоны gitignored и перезаписываются `vn build`. Правка `ui_frames.gen.rpy` живёт до следующей сборки.
- **Не подставлять `i.caption` напрямую** в `screen choice` — переводы пунктов сломаются молча и всплывут только на релизе другого языка.
- **Не переставлять пункты `menu:`** после того, как строки ушли переводчикам: ключ перевода — пара (`menu_id`, индекс).
- **Не трогать блок автопилота** в `choice.rpy:63-64` и `core_screens.rpy:484-485` — без них `vn test smoke` виснет на меню.
- **Не ставить панель под мелкий элемент.** Меньше `2*Borders` — фон схлопнется. Проверьте комментарий `# минимум NxM px` в генерате; под кнопку ниже 40 px берите `chip`/`chip_active`, а не `choice*`.
- **Не наращивать `blur`/`dy` у кнопочных панелей.** `blur > 12` у `choice*` уронит тест `test_ui_panels.py:325` (`test_every_frame_consumer_is_not_smaller_than_2x_borders`, параметризован по `ui_scale` 1.0/1.4) и сплющит кнопки; у `chip*` бюджет ещё жёстче — `blur + |dy| <= 4`.
- **Не хардкодить `font "..."`** в стилях — языковые пакеты переопределяют шрифты через `gui.*`, хардкод переживёт смену языка и покажет тофу.
- **Не писать литералы в экранах** (кроме `game/framework/90_debug/**` — этот каталог вырезан из релиза).
- **`viewport`/`vpgrid` со `scrollbars "vertical"` рисуется ПУСТЫМ**, пока не заданы визуалы полосы (`vscrollbar_base_bar` / `vscrollbar_thumb` / `vscrollbar_xsize`): картинок скроллбара в проекте нет, движковый дефолт полосы пуст, и side-раскладка отдаёт вьюпорту нулевую площадь. Штатный путь — `properties vn_scroll_props` (`components.rpy:104-113`); собственные визуалы нужны только там, где `gui.*` запрещены. **Этот дефект реально жил в экране краха**: трейсбек в dev-режиме не рисовался вообще — исправлено ([42-big-picture.md](42-big-picture.md) §5.3). И задавайте `xsize`/`ysize`: viewport без них съест всё доступное место.
- **`ypadding` невалиден для `hbox`** — вертикальный ритм задаётся `spacing` (`history.rpy:41-42`; в корне репозитория лежит устаревший `errors.txt` ровно про этот случай).
- **Голый `[` в тексте — интерполяция Ren'Py.** В строках `strings.yaml` это фича (`ui.main.version: "версия [config.version]"`), в случайном тексте — краш.
- **В контексте `label main_menu` overlay-экраны и таймеры не тикают** — не рассчитывайте на `timer` в главном меню.
- **Не добавлять условные пункты меню** — компилятор их запрещает.

## Проверка

```bash
vn build                                   # схемы -> панели -> генерат -> импорт переводов
"$RENPY_SDK/renpy.exe" . lint              # движковый линт: чисто
vn loc report                              # все языки 100%, fuzzy 0
vn test smoke --picks 0,0                  # автопрохождение; скриншоты .vncache/smoke/shot*.png
vn test smoke --lang pseudo                # псевдолокаль +40% длины строк — проверка вёрстки
vn test smoke --lang de
vn test oversample --scale 2               # движок обязан подобрать @2-варианты панелей
python -m pytest tools/vn/tests -q         # 278 тестов (в т.ч. 15 в test_ui_panels.py, 6 в test_crash_handler.py,
                                           #            10 в test_achievements.py)
vn release validate --flavor patron        # релизный гейт (21 проверка); у public штатный WARN по зрелости, exit 0
```

**Скриншоты смотреть глазами обязательно.** Движковый lint не ловит визуальные поломки: сплющенный 9-patch, обрезанный текст, тофу вместо глифов, съехавший стек выборов. `vn build --check` в CI падает с «`game/assets` не свеж», если объявленная панель не собрана, и «генерат не свеж», если `ui_frames.gen.rpy` отстал.

**Грабля окружения:** в bash-сессиях агента `RENPY_SDK` не наследуется — экспортируйте вручную: `export RENPY_SDK="C:/Users/Vadim/renpy-sdk/renpy-8.5.3-sdk"`. Кавычки и прямые слэши обязательны: без кавычек bash съедает обратные слэши как экранирование, и значение приезжает битым (`C:UsersVadim…`), после чего `sdk_path()` не находит `renpy.py` и `vn doctor` краснеет «Ren'Py SDK не найден».

## Доступность и адаптивность

Честно, без приукрашивания.

| Тема | Статус | Как есть |
|---|---|---|
| Разрешение | IMPLEMENTED | `gui.init(1920, 1080)` — единственная виртуальная сетка; движок масштабирует всю поверхность под окно. Отдельных раскладок под другие пропорции нет, брейкпоинтов нет |
| Клавиатура | PARTIALLY IMPLEMENTED | выбор — цифры 1–9 (`choice.rpy:59-61`); просмотрщик галереи — `K_LEFT`/`K_RIGHT`/`K_ESCAPE`/`game_menu` (`gallery.rpy:166-171`); Shift+J в dev-сборке. Остальные экраны полагаются на штатную навигацию движка |
| Геймпад / controller-first | PARTIALLY IMPLEMENTED ([ADR-0014](../adr/0014-platform-services.md); приёмы — [39-platforms.md](39-platforms.md) §7, разбор экран за экраном и оставшиеся открытые пункты — [42-big-picture.md](42-big-picture.md)) | скролл-пресет `vn_scroll_props` + `vn_ui.reveal` (докрутка к клавиатурному фокусу), `vn_modal_dialog` с B/Esc и `default_focus` на безопасной кнопке, `keyboard_focus False` у quick menu (уходит из dpad-пути), пад-биндинги в `20_ui/input.rpy` (L3=skip, R3=auto, LB/RB=листание вьюпортов), `FilePage("quick")`, LB/RB в просмотрщике галереи. Не проверено: живой пад — smoke под `RENPY_VARIANT` пад-события не шлёт |
| Масштабирование шрифта игроком | IMPLEMENTED | сегмент «авто / крупный / обычный» в `screen preferences()` (`core_screens.rpy:335-348`) → `vn.set_ui_scale` → `gui.ui_scale` (`20_ui/scale.rpy`). Авто = 1.4 на Steam Deck / Big Picture. **Только увеличение** (< 1.0 сплющит 9-patch панели ADR-0009) |
| Safe-area ТВ (overscan) | IMPLEMENTED | `gui.overscan_pad = 48` в Big Picture (`scale.rpy:42`); токен применён в четырёх файлах (`quick_menu.rpy:17,19`, `gallery.rpy:144`, `build_overlay.rpy:15-16`, `core_screens.rpy:91,122,126,511-512`) — все прижатые к кромке места закрыты, разбор — [42-big-picture.md](42-big-picture.md) §4, §5.6 |
| Высокая контрастность / альтернативная палитра | NOT IMPLEMENTED | одна тёмная палитра, переключателя нет; `theme.yaml` фазы 2 не существует |
| Озвучка интерфейса (self-voicing) | NOT IMPLEMENTED (проектных средств) | ни настройки, ни `alt`-подписей у декоративных элементов |
| Локализация вёрстки | IMPLEMENTED | шрифт пункта языка берётся из манифеста пакета с fallback; псевдолокаль `--lang pseudo` — штатный способ проверить, переживёт ли вёрстка +40% длины. Подсказки управления не зависят от лексики устройства: `vn_ui.hint` выбирает между парой ключей `_kbd` / `_pad` |
| RTL, plurals, локализуемые изображения | NOT IMPLEMENTED | см. [14-localization.md](14-localization.md) |

Всё, что помечено NOT IMPLEMENTED, — долг; приоритеты и фазы — [37-roadmap.md](37-roadmap.md).

## Анимации и переходы

Реально используются четыре вещи, все — чистый ATL без ассетов:

| Что | Где | Параметры |
|---|---|---|
| `vn_ctc_blink` | индикатор «жду клика» в `say` | цикл 0.7 с, alpha 1.0↔0.3, `yoffset` 0↔4 (`components.rpy:38-42`) |
| `vn_toast_in` | тост `notify` | 0.25 с, alpha 0→1, `yoffset -14`→0 (`components.rpy:44-46`) |
| `vn_choice_in` | появление стека выборов | 0.22 с `easeout`, каскад 50 мс на пункт (`choice.rpy:25-28,42`) |
| `with dissolve` | вход в сцену | эмитится обвязкой сцен в `game/generated/scenes/**`, к UI-слою не относится — см. [12-scenes.md](12-scenes.md) |

Ховер-состояния сделаны без анимации — сменой фона на другую панель (`vn_frame_choice` → `vn_frame_choice_hover`) и цвета текста. Переходов между экранами меню нет.

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `game/gui.rpy`, `game/framework/20_ui/components.rpy`, целевой файл в `game/framework/20_ui/screens/`, `content/ui/panels.yaml`, `content/ui/strings.yaml`, `game/generated/registry/ui_frames.gen.rpy` (для минимумов `2*Borders`), `docs/adr/0009-generated-ui-panels.md` |
| **Не трогать** | `game/generated/**` (генерат `vn build`), `game/assets/ui/**` (рисует конвейер), `game/tl/**` (пишет `vn loc import`) — все три gitignored; `docs/ARCHITECTURE.md` §5.4 считать устаревшим относительно `strings@1` |
| **Зависимости** | новый ключ строки → `vn loc extract` → переводы `en`/`de` → релизный гейт покрытия 0.98; новая панель → `vn build` (иначе `Frame` на несуществующий файл); переименование `vn_game_menu`/`vn_chapter_card` сломает генерат `chapter_select.gen.rpy`; перестановка пунктов `menu:` ломает переводы выборов |
| **Валидация** | `vn build && "$RENPY_SDK/renpy.exe" . lint && vn loc report && vn test smoke --picks 0,0 && python -m pytest tools/vn/tests -q`; глазами — `.vncache/smoke/shot*.png` |
| **Частые ошибки** | 1) элемент меньше `2*Borders` → фон схлопывается (так уже ломалась галерея; теперь ловится `test_every_frame_consumer_is_not_smaller_than_2x_borders`); 2) литерал в экране вместо `vn_loc.t` → строка не попадёт в PO и останется непереведённой; 3) `i.caption` вместо `vn_loc.choice_text(vn_menu, idx, i.caption)` → тихая потеря переводов выборов; 4) магическое число вместо `gui.*` → расползание дизайн-системы; 5) удаление блока `vn_qa.autopilot_active()` → `vn test smoke` виснет; 6) `scrollbars "vertical"` без `vscrollbar_base_bar/thumb` → полосы не видно |

Смежные файлы: [05-renpy-development.md](05-renpy-development.md) (init-приоритеты, движковые контракты), [07-backend.md](07-backend.md) (сторы `vn_*`, состояние), [13-dialogue.md](13-dialogue.md) (выборы со стороны контента), [14-localization.md](14-localization.md), [15-gallery.md](15-gallery.md), [16-assets.md](16-assets.md) (конвейер и кэш, куда встроен `ui_panel@1`), [25-custom-engine.md](25-custom-engine.md) (эмиттеры), [27-testing.md](27-testing.md), [36-troubleshooting.md](36-troubleshooting.md).
