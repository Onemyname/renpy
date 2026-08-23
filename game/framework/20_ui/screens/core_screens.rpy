# Основные экраны фазы 0.5: новый визуал на токенах gui.*, контракты фазы 0
# сохранены (id окна/who/what, сигнатуры choice/confirm, vn_lang/vn_loc, гейты).
# Локализация (ADR-0005): в экранах НЕТ строковых литералов — только ключи
# content/ui/strings.yaml через vn_loc.t(key). Смена языка горячая.

init offset = 0

init python:
    # Закрытие окна ОС (X / Alt+F4): подменяем движковый confirm на свой
    # локализованный текст. Лямбда — сообщение вычисляется в момент показа.
    config.quit_action = lambda: renpy.run(
        Confirm(vn_loc.t("ui.confirm.quit"), Quit(confirm=False)))

    # Скриншоты сейв-слотов: масштаб миниатюры (16:9 при 1920×1080)
    config.thumbnail_width = gui.slot_width
    config.thumbnail_height = gui.slot_thumb_height


## ── Диалог ───────────────────────────────────────────────────────────────────

screen say(who, what):
    # Scrim вместо глухой плашки: обязан читаться поверх яркого движущегося
    # WebM-лупа (ADR-0006). Окно прозрачное, подложка — vn_scrim.
    use vn_scrim
    window:
        id "window"
        hbox:
            spacing gui.sp_l + gui.sp_s
            yalign 1.0
            # Резерв под side-image (C7: assets/spr/<char>/side/) — подключится
            # с ассет-пайплайном; ширина колонки уже заложена в композицию.
            vbox:
                spacing gui.sp_m - 2
                if who is not None:
                    text who id "who" style "say_label"
                text what id "what" style "say_dialogue"
        add "vn_ctc" at vn_ctc_blink align (1.0, 1.0) yoffset -8

style window:
    xalign 0.5
    yalign 1.0
    xfill True
    ysize gui.textbox_height
    background None
    padding (gui.textbox_side_pad, 0, gui.textbox_side_pad, gui.textbox_bottom_pad)

style say_label:
    font gui.name_text_font
    size gui.name_text_size
    color gui.accent_color        # Character(color=…) переопределяет через who_color
    outlines [(2, "#00000059", 0, 1)]

style say_dialogue:
    xmaximum gui.dialogue_width
    line_spacing gui.sp_s + 3
    outlines [(2, "#00000047", 0, 1)]


screen input(prompt):
    use vn_scrim
    window:
        vbox:
            spacing gui.sp_m - 2
            yalign 1.0
            text prompt style "input_prompt"
            input id "input"


## ── Навигация: рельса игрового меню / колонна главного меню ─────────────────

screen navigation():
    # Рельса — РЕЗЕРВНЫЙ владелец первого фокуса (42-big-picture.md §5.1):
    # приоритет gui.focus_rail ниже контентного gui.focus_content, поэтому
    # экран, объявивший свой default focus, забирает его себе. И резерв садится
    # на пункт ТЕКУЩЕГО экрана, а не на первый: слепой A тогда переоткрывает
    # то же меню (no-op) вместо «Загрузка -> Сохранение» и вместо Start() на
    # экране выбора глав. Экран без своего пункта в рельсе остаётся без default
    # focus — это безопасно (A не делает ничего), лечится default_focus'ом
    # gui.focus_content в его контенте.
    $ _here = vn_ui.menu_screen()
    frame:
        style "vn_rail"
        fixed:
            add Solid(gui.panel_border) xsize 1 xalign 1.0
            vbox:
                spacing gui.sp_xl + gui.sp_m
                # Safe-area ТВ (§5.6): содержимое рельсы отодвигается от кромки
                # на gui.overscan_pad — это ОСНОВНОЙ способ ходить по меню, и
                # обрезанные слева пункты дороже всего. Фон (style vn_rail,
                # xsize 336) остаётся у кромки: обрезаться ему не мешает.
                xpos gui.sp_l - gui.sp_xs + gui.overscan_pad
                ypos gui.sp_xl - 12
                hbox:
                    spacing gui.sp_m - gui.sp_xs
                    text "[config.name!t]" style "vn_brand"
                    add Solid(gui.accent_color) xysize (22, 4) yalign 0.8
                vbox:
                    spacing gui.sp_xs
                    if main_menu:
                        textbutton vn_loc.t("ui.nav.start") action Start() style "vn_nav_button"
                        if vn_registry.chapters():
                            textbutton vn_loc.t("ui.nav.chapters") action ShowMenu("chapter_select") style "vn_nav_button" default_focus (gui.focus_rail if _here == "chapter_select" else 0)
                    else:
                        textbutton vn_loc.t("ui.nav.save") action ShowMenu("save") style "vn_nav_button" default_focus (gui.focus_rail if _here == "save" else 0)
                    textbutton vn_loc.t("ui.nav.load") action ShowMenu("load") style "vn_nav_button" default_focus (gui.focus_rail if _here == "load" else 0)
                    textbutton vn_loc.t("ui.nav.prefs") action ShowMenu("preferences") style "vn_nav_button" default_focus (gui.focus_rail if _here == "preferences" else 0)
                    # Галерея (ADR-0010): доступна из обоих контекстов; пункт
                    # исчезает, если галерея пуста или её элементы скрыты
                    # флейвором/владением — гейт в vn_gal, не здесь.
                    if vn_gal.categories():
                        textbutton vn_loc.t("ui.nav.gallery") action ShowMenu("gallery") style "vn_nav_button" default_focus (gui.focus_rail if _here == "gallery" else 0)
                    # Достижения (achievements@1): как и галерея, доступны из
                    # обоих контекстов (прогресс в persistent). Пункт исчезает,
                    # если ачивок нет или все скрыты флейвором/владением — гейт
                    # в vn_ach.visible_ids(), не здесь.
                    if vn_ach.visible_ids():
                        textbutton vn_loc.t("ui.nav.achievements") action ShowMenu("achievements") style "vn_nav_button" default_focus (gui.focus_rail if _here == "achievements" else 0)
                    # Карта главы (ADR-0021): проекция скомпилированного графа.
                    # Доступна из обоих контекстов — что игрок видел, помнит
                    # persistent. Пункт исчезает, если ни одна глава не
                    # принадлежит игроку: гейт в vn_story, не здесь.
                    if vn_story.chapter_list():
                        textbutton vn_loc.t("ui.chart.open") action ShowMenu("story_flow") style "vn_nav_button" default_focus (gui.focus_rail if _here == "story_flow" else 0)
                    if not main_menu:
                        textbutton vn_loc.t("ui.nav.history") action ShowMenu("history") style "vn_nav_button" default_focus (gui.focus_rail if _here == "history" else 0)
            vbox:
                spacing gui.sp_xs
                xpos gui.sp_l - gui.sp_xs + gui.overscan_pad
                yanchor 1.0
                # Safe-area ТВ (§5.6): «Выход»/«Главное меню» и строка версии
                # уезжают из полосы overscan вместе с содержимым рельсы.
                ypos 1080 - gui.sp_l - gui.overscan_pad
                add Solid(gui.panel_border) xsize 248 ysize 1
                null height gui.sp_m
                if main_menu:
                    # «Выйти» — только на десктопе: на iOS кнопка выхода запрещена
                    # правилами стора, на Android приложение снимает система, и
                    # игрок, вышедший «внутри» приложения, видит чёрный экран.
                    # Штатный шаблон SDK гейтит её так же (gui/game/screens.rpy:
                    # `if renpy.variant("pc")`). Confirm со СВОИМ текстом:
                    # движковые layout.*-строки наш конвейер переводов не покрывает.
                    if vn_platform.is_desktop():
                        textbutton vn_loc.t("ui.nav.quit") action Confirm(vn_loc.t("ui.confirm.quit"), Quit(confirm=False)) style "vn_nav_button"
                else:
                    textbutton vn_loc.t("ui.nav.return") action Return() style "vn_nav_button"
                    textbutton vn_loc.t("ui.nav.main_menu") action Confirm(vn_loc.t("ui.confirm.main_menu"), MainMenu(confirm=False)) style "vn_nav_button"
                null height gui.sp_m
                text vn_loc.t("ui.main.version") style "vn_version"

style vn_rail:
    xsize 336
    yfill True
    background Solid(gui.rail_bg)
    padding (0, 0)

style vn_brand:
    font gui.text_font
    size gui.label_text_size - gui.sp_xs
    color gui.text_color

style vn_nav_button:
    xsize 248
    padding (gui.sp_m, 13)
    background None
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg)
    # selected_hover обязателен, иначе фокус НА ТЕКУЩЕМ пункте не виден: префиксы
    # hover_ и selected_ оба задают состояние selected_hover, и последний
    # выигрывает (style_properties.html, «implications»). Резервный фокус рельсы
    # (§5.1) садится ровно на текущий пункт — без своего фона он неотличим.
    selected_hover_background Solid(gui.panel_bg_hover)

style vn_nav_button_text:
    font gui.interface_text_font
    size gui.interface_text_size - 1
    color gui.muted_color
    hover_color gui.text_color
    selected_color gui.accent_color
    insensitive_color gui.insensitive_color

style vn_version:
    font gui.interface_text_font
    size gui.tiny_text_size
    color gui.insensitive_color
    xpos gui.sp_m


## ── Главное меню (композиция A: колонна слева, wordmark сверху) ─────────────

screen main_menu():
    tag menu
    add Solid(gui.interface_bg)
    # Key-art / WebM-луп главного меню подключится ассет-пайплайном (bg/mov);
    # до тех пор — токен-фон. Композиция рассчитана на тёмный левый край.
    vbox:
        xpos 96
        ypos 96
        spacing gui.sp_m + 2
        text "[config.name!t]" style "vn_wordmark"
        add Solid(gui.accent_color) xysize (56, 5)
    vbox:
        xpos 96
        yanchor 1.0
        ypos 1080 - 140
        spacing gui.sp_s + 2
        $ _newest = renpy.newest_slot()
        # default_focus (аудит ui.md §3): на ТВ/Deck первый A продолжает игру
        # (или начинает новую) — вместо «ничего не произошло».
        if _newest is not None:
            button:
                style "vn_main_continue"
                action Continue(confirm=False)
                default_focus True
                vbox:
                    spacing gui.sp_xs + 1
                    text vn_loc.t("ui.nav.continue") style "vn_main_continue_text"
                    text FileTime(_newest, format=vn_loc.t("ui.file.time_format")) style "vn_main_meta"
        textbutton vn_loc.t("ui.nav.start") action Start() style "vn_main_item" default_focus (_newest is None)
        if vn_registry.chapters():
            textbutton vn_loc.t("ui.nav.chapters") action ShowMenu("chapter_select") style "vn_main_item"
        textbutton vn_loc.t("ui.nav.load") action ShowMenu("load") style "vn_main_item"
        # Галерея и достижения — из ГЛАВНОГО меню тоже, а не только из игрового:
        # их состояние живёт в persistent и не зависит от сейва, поэтому игрок,
        # вышедший в меню, обязан видеть открытое, не начиная игру заново.
        # Гейты — те же, что в рельсе (vn_gal.categories() / vn_ach.visible_ids()):
        # пустой раздел не показывается, дублирования условий нет.
        if vn_gal.categories():
            textbutton vn_loc.t("ui.nav.gallery") action ShowMenu("gallery") style "vn_main_item"
        if vn_ach.visible_ids():
            textbutton vn_loc.t("ui.nav.achievements") action ShowMenu("achievements") style "vn_main_item"
        textbutton vn_loc.t("ui.nav.prefs") action ShowMenu("preferences") style "vn_main_item"
        # «Выйти» — только на десктопе (та же причина и тот же гейт, что в рельсе
        # navigation): мобильное приложение закрывает система, а не пункт меню.
        if vn_platform.is_desktop():
            textbutton vn_loc.t("ui.nav.quit") action Confirm(vn_loc.t("ui.confirm.quit"), Quit(confirm=False)) style "vn_main_item"
    text vn_loc.t("ui.main.version"):
        style "vn_version"
        xpos 96
        yanchor 1.0
        ypos 1080 - 56

style vn_wordmark:
    font gui.text_font
    size gui.title_text_size
    color gui.text_color

style vn_main_continue:
    background None
    padding (0, gui.sp_s + 1)

style vn_main_continue_text:
    font gui.interface_semibold_font
    size gui.label_text_size - gui.sp_xs
    color gui.text_color
    hover_color gui.hover_color

style vn_main_meta:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.muted_color

style vn_main_item:
    background None
    padding (0, gui.sp_s + 1)

style vn_main_item_text:
    font gui.interface_text_font
    size gui.label_text_size - gui.sp_s
    color gui.muted_color
    hover_color gui.text_color
    selected_color gui.accent_color


## ── Сохранение / загрузка ────────────────────────────────────────────────────

screen save():
    tag menu
    use file_menu(vn_loc.t("ui.file.save_title"), True)

screen load():
    tag menu
    use file_menu(vn_loc.t("ui.file.load_title"), False)

screen file_menu(title, is_save):
    use vn_game_menu(title):
        hbox:
            spacing gui.sp_xs
            textbutton vn_loc.t("ui.file.autopage") action FilePage("auto") style "vn_page_button"
            # Страница квиксейвов (аудит ui.md P0 №5): QuickSave() пишет на
            # страницу "quick" — без пункта в пейджере её нельзя было загрузить.
            textbutton vn_loc.t("ui.file.quickpage") action FilePage("quick") style "vn_page_button"
            for p in range(1, 5):
                textbutton "[p]" action FilePage(p) style "vn_page_button"
        grid 3 2:
            spacing gui.sp_l - gui.sp_s
            for i in range(1, 7):
                # Первый слот забирает default focus у рельсы (§5.1): с пада
                # сразу видно, что сетка слотов интерактивна.
                use vn_save_slot(i, is_save, focus_default=(i == 1))

style vn_page_button:
    padding (gui.sp_m - 1, gui.sp_s)
    background None
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg)

style vn_page_button_text:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.faint_color
    hover_color gui.text_color
    selected_color gui.accent_color


## ── Настройки ────────────────────────────────────────────────────────────────

screen preferences():
    tag menu
    use vn_game_menu(vn_loc.t("ui.prefs.title")):
        hbox:
            spacing gui.sp_xl
            vbox:
                spacing gui.sp_l + gui.sp_s
                # Режим экрана — только там, где окно есть: на мобильном приложение
                # всегда занимает экран целиком, Preference("display", …) там ничего
                # не меняет, а группа занимает место и ловит палец. Гейт вариантом, а
                # не копией экрана (scale.rpy: вторая вёрстка расходится с первой);
                # штатный шаблон SDK гейтит эту же группу так же (gui/game/screens.rpy:
                # `if renpy.variant("pc")`). Побочное следствие осознанно: на мобильном
                # у экрана не остаётся своего default focus (gui.focus_content жил
                # на сегментах) — первый фокус берёт рельса (navigation), и слепой A
                # там переоткрывает «Настройки», то есть ничего не делает.
                if vn_platform.is_desktop():
                    vbox:
                        spacing gui.sp_m
                        $ _g = vn_loc.t("ui.prefs.display").upper()
                        text _g style "vn_group"
                        hbox:
                            spacing gui.sp_xs
                            # Контент забирает default focus у рельсы (§5.1), но
                            # садится на УЖЕ выбранный сегмент: слепой A тогда
                            # переустанавливает текущий режим экрана (no-op), а не
                            # выбивает игрока из полноэкранного режима на ТВ.
                            $ _fs = _preferences.fullscreen
                            textbutton vn_loc.t("ui.prefs.windowed"):
                                action Preference("display", "window")
                                style "vn_seg_button"
                                default_focus (0 if _fs else gui.focus_content)
                            textbutton vn_loc.t("ui.prefs.fullscreen"):
                                action Preference("display", "fullscreen")
                                style "vn_seg_button"
                                default_focus (gui.focus_content if _fs else 0)
                vbox:
                    spacing gui.sp_m
                    $ _g2 = vn_loc.t("ui.prefs.text").upper()
                    text _g2 style "vn_group"
                    use vn_pref_slider(vn_loc.t("ui.prefs.text_speed"), Preference("text speed"))
                    use vn_pref_slider(vn_loc.t("ui.prefs.auto_forward"), Preference("auto-forward time"))
                vbox:
                    spacing gui.sp_m
                    $ _g3 = vn_loc.t("ui.prefs.volume").upper()
                    text _g3 style "vn_group"
                    use vn_pref_slider(vn_loc.t("ui.prefs.volume_music"), Preference("music volume"))
                    use vn_pref_slider(vn_loc.t("ui.prefs.volume_sound"), Preference("sound volume"))
                    use vn_pref_slider(vn_loc.t("ui.prefs.volume_voice"), Preference("voice volume"))
                    # Дакинг: пока звучит голос, остальные каналы приглушаются.
                    # Тумблер здесь, а не «включено навсегда»: механизм движка и
                    # так гейтится этой настройкой, а игроку с плохим слухом или
                    # без озвучки в его языке приглушение музыки может мешать.
                    textbutton vn_loc.t("ui.prefs.duck_voice"):
                        action Preference("emphasize audio", "toggle")
                        style "vn_toggle_button"
            vbox:
                spacing gui.sp_l + gui.sp_s
                vbox:
                    spacing gui.sp_m
                    $ _g4 = vn_loc.t("ui.prefs.skip").upper()
                    text _g4 style "vn_group"
                    textbutton vn_loc.t("ui.prefs.skip_all") action Preference("skip", "toggle") style "vn_toggle_button"
                    textbutton vn_loc.t("ui.prefs.skip_after_choices") action Preference("after choices", "toggle") style "vn_toggle_button"
                vbox:
                    spacing gui.sp_m
                    # Потолок качества текстур (00_core/095_quality.rpy): «авто» =
                    # потолок сборки, «экономно» = без @N-вариантов — случай
                    # «4K-монитор + слабый GPU», который автоподбор сам не покрывает.
                    $ _g5 = vn_loc.t("ui.prefs.graphics").upper()
                    text _g5 style "vn_group"
                    hbox:
                        spacing gui.sp_xs
                        textbutton vn_loc.t("ui.prefs.quality_auto"):
                            action Function(vn.set_quality_cap, None)
                            selected vn.quality_cap() is None
                            style "vn_seg_button"
                        textbutton vn_loc.t("ui.prefs.quality_eco"):
                            action Function(vn.set_quality_cap, 1)
                            selected vn.quality_cap() == 1
                            style "vn_seg_button"
                vbox:
                    spacing gui.sp_m
                    # Масштаб интерфейса (20_ui/scale.rpy): «авто» следует
                    # платформе (Deck/Big Picture -> крупный), выбор игрока
                    # применяется на лету через gui.rebuild().
                    $ _g6 = vn_loc.t("ui.prefs.ui_scale").upper()
                    text _g6 style "vn_group"
                    hbox:
                        spacing gui.sp_xs
                        textbutton vn_loc.t("ui.prefs.scale_auto"):
                            action Function(vn.set_ui_scale, None)
                            selected vn.ui_scale_pref() is None
                            style "vn_seg_button"
                        textbutton vn_loc.t("ui.prefs.scale_large"):
                            action Function(vn.set_ui_scale, "large")
                            selected vn.ui_scale_pref() == "large"
                            style "vn_seg_button"
                        textbutton vn_loc.t("ui.prefs.scale_normal"):
                            action Function(vn.set_ui_scale, "normal")
                            selected vn.ui_scale_pref() == "normal"
                            style "vn_seg_button"
                # Синхронизация достижений: движковый Sync доталкивает локально
                # выданные ачивки в платформенный бэкенд (типовой случай — Steam
                # был офлайн). Кнопка sensitive только при фактическом
                # рассинхроне, поэтому в standalone она просто неактивна.
                vbox:
                    spacing gui.sp_m
                    $ _g7 = vn_loc.t("ui.prefs.achievements").upper()
                    text _g7 style "vn_group"
                    textbutton vn_loc.t("ui.prefs.ach_sync"):
                        action achievement.Sync()
                        style "vn_toggle_button"
                # Подсказки встроенного гайда (ADR-0021). Выключены по умолчанию
                # и остаются выключенными, пока игрок не отметит цели на карте
                # главы: подсветка «правильного» варианта на первом прохождении
                # отнимает у выбора смысл.
                if vn_story.chapter_list():
                    vbox:
                        spacing gui.sp_m
                        $ _g8 = vn_loc.t("ui.chart.title").upper()
                        text _g8 style "vn_group"
                        textbutton vn_loc.t("ui.prefs.guide"):
                            action ToggleField(persistent, "vn_guide")
                            style "vn_toggle_button"
                use language_picker

# Ряд «подпись + слайдер»: bar со штатным value-действием Preference(...)
screen vn_pref_slider(label_text, value_action):
    hbox:
        spacing gui.sp_m
        text label_text style "vn_pref_label" min_width 230 yalign 0.5
        bar value value_action style "vn_slider" yalign 0.5

style vn_pref_label:
    font gui.interface_text_font
    size gui.interface_text_size - gui.sp_xs
    color gui.sub_color

# style vn_slider переехал в components.rpy (токен-компонент с hover-индикацией
# фокуса — аудит ui.md §4).

style vn_seg_button:
    padding (gui.sp_l - 6, gui.sp_m - gui.sp_xs)
    background Solid(gui.panel_bg_deep)
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg_hover)
    # Первый фокус настроек садится на ВЫБРАННЫЙ сегмент (§5.1), а состояние
    # selected_hover без своего фона выглядит как обычный selected — фокуса не
    # видно. Тот же приём, что у hover_-вариантов vn_slider.
    selected_hover_background Solid(gui.panel_border2)

style vn_seg_button_text:
    font gui.interface_text_font
    size gui.interface_text_size - gui.sp_xs
    color gui.muted_color
    hover_color gui.text_color
    selected_color gui.text_color

style vn_toggle_button:
    xsize 460
    padding (gui.sp_m, gui.sp_m - gui.sp_xs)
    background Solid(gui.panel_bg_deep)
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg)

style vn_toggle_button_text is vn_seg_button_text:
    selected_color gui.accent_color


# Список языков (ADR-0005): данные — ТОЛЬКО из vn_lang; логика фазы 0 сохранена
# (native-названия, шрифт из манифеста с fallback, hot-swap без кеша строк).
screen language_picker():
    $ _langs = vn_lang.available()
    $ _cur = vn_lang.current()
    $ _sel = next((_i for _i, _l in enumerate(_langs) if _l["code"] == _cur), 0)
    vbox:
        spacing gui.sp_m
        $ _g5 = vn_loc.t("ui.prefs.language").upper()
        text _g5 style "vn_group"
        frame:
            style "vn_lang_panel"
            viewport id "vp_languages":
                properties vn_scroll_props
                xsize 460
                ymaximum 420
                yinitial (_sel / float(max(1, len(_langs) - 1)))
                vbox:
                    spacing gui.sp_xs // 2
                    # hovered/reveal (components.rpy): языки за фолдом 420px были
                    # недостижимы с пада — фокус не ходит в клипнутые кнопки.
                    for _li, _l in enumerate(_langs):
                        textbutton _l["name"]:
                            style "pref_lang_button"
                            text_font (_l["font"] if _l["font"] and renpy.loadable(_l["font"]) else gui.text_font)
                            action vn_lang.action(_l["code"])
                            hovered Function(vn_ui.reveal, "preferences", "vp_languages", _li, len(_langs))

style vn_group:
    font gui.interface_semibold_font
    size gui.group_text_size
    color gui.faint_color
    kerning 2.0

style vn_lang_panel:
    background Solid(gui.panel_bg_deep)
    padding (gui.sp_s, gui.sp_s)

style pref_lang_button:
    xsize 444
    padding (gui.sp_m - 2, 11)
    background None
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg)

style pref_lang_button_text:
    size gui.interface_text_size - gui.sp_xs
    color gui.sub_color
    hover_color gui.text_color
    selected_color gui.accent_color


## ── Служебные ────────────────────────────────────────────────────────────────

# Каркас vn_modal_dialog (components.rpy): затемнение, B/Esc = «Нет», рамка.
# Безопасная кнопка «Нет» получает default focus — слепой A не удалит сейв.
screen confirm(message, yes_action, no_action):
    modal True
    zorder 200
    # QA-автопилот: модальные подтверждения отвечают «Да» сами; вне автопилота — no-op.
    if vn_qa.autopilot_active():
        timer 0.8 action yes_action repeat True
    use vn_modal_dialog(no_action):
        vbox:
            spacing gui.sp_l
            text message style "vn_dialog_text"
            hbox:
                xalign 0.5
                spacing gui.sp_m
                use vn_button(vn_loc.t("ui.confirm.yes"), yes_action, kind="primary")
                use vn_button(vn_loc.t("ui.confirm.no"), no_action, kind="secondary", focus_default=True)


screen notify(message):
    zorder 100
    frame at vn_toast_in:
        style "vn_toast"
        hbox:
            spacing gui.sp_m - gui.sp_xs
            add Solid(gui.accent_color) xysize (8, 8) yalign 0.5
            text "[message!tq]" style "vn_toast_text"
    timer 3.25 action Hide("notify")

style vn_toast:
    # Safe-area ТВ (§5.6): тост прижат к левому верхнему углу и попадал в полосу
    # overscan целиком — уведомление «открыт новый материал» срезалось. Базовые
    # 36/32 px собраны из шкалы отступов, чтобы в стиле не осталось литералов.
    xpos gui.sp_l + gui.sp_xs + gui.overscan_pad
    ypos gui.sp_l + gui.overscan_pad
    # Фон — генерируемая панель toast (ADR-0009), как у выборов и слотов: тост
    # висит над кадром (в т.ч. над ярким WebM-лупом) и обязан отделяться от него
    # скруглением, обводкой и тенью, а Solid ничего из этого не рисует. Цвет
    # уехал в декларацию content/ui/panels.yaml — в вёрстке пикселей не осталось.
    # Геометрия: панель объявлена под фактическую высоту тоста (padding + строка
    # ~50 px), минимум 2*Borders = 40 px — сторожит test_ui_panels.
    background vn_frame_toast
    padding (gui.sp_m + 6, gui.sp_m - 2)

style vn_toast_text:
    font gui.interface_text_font
    size gui.interface_text_size - gui.sp_xs
    color gui.sub_color
