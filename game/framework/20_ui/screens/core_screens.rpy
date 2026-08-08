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
    frame:
        style "vn_rail"
        fixed:
            add Solid(gui.panel_border) xsize 1 xalign 1.0
            vbox:
                spacing gui.sp_xl + gui.sp_m
                xpos gui.sp_l - gui.sp_xs
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
                            textbutton vn_loc.t("ui.nav.chapters") action ShowMenu("chapter_select") style "vn_nav_button"
                    else:
                        textbutton vn_loc.t("ui.nav.save") action ShowMenu("save") style "vn_nav_button"
                    textbutton vn_loc.t("ui.nav.load") action ShowMenu("load") style "vn_nav_button"
                    textbutton vn_loc.t("ui.nav.prefs") action ShowMenu("preferences") style "vn_nav_button"
                    # Галерея (ADR-0010): доступна из обоих контекстов; пункт
                    # исчезает, если галерея пуста или её элементы скрыты
                    # флейвором/владением — гейт в vn_gal, не здесь.
                    if vn_gal.categories():
                        textbutton vn_loc.t("ui.nav.gallery") action ShowMenu("gallery") style "vn_nav_button"
                    if not main_menu:
                        textbutton vn_loc.t("ui.nav.history") action ShowMenu("history") style "vn_nav_button"
            vbox:
                spacing gui.sp_xs
                xpos gui.sp_l - gui.sp_xs
                yanchor 1.0
                ypos 1080 - gui.sp_l
                add Solid(gui.panel_border) xsize 248 ysize 1
                null height gui.sp_m
                if main_menu:
                    # Confirm со СВОИМ текстом: движковые layout.*-строки наш
                    # конвейер переводов не покрывает.
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
        if _newest is not None:
            button:
                style "vn_main_continue"
                action Continue(confirm=False)
                vbox:
                    spacing gui.sp_xs + 1
                    text vn_loc.t("ui.nav.continue") style "vn_main_continue_text"
                    text FileTime(_newest, format=vn_loc.t("ui.file.time_format")) style "vn_main_meta"
        textbutton vn_loc.t("ui.nav.start") action Start() style "vn_main_item"
        if vn_registry.chapters():
            textbutton vn_loc.t("ui.nav.chapters") action ShowMenu("chapter_select") style "vn_main_item"
        textbutton vn_loc.t("ui.nav.load") action ShowMenu("load") style "vn_main_item"
        textbutton vn_loc.t("ui.nav.prefs") action ShowMenu("preferences") style "vn_main_item"
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
            for p in range(1, 5):
                textbutton "[p]" action FilePage(p) style "vn_page_button"
        grid 3 2:
            spacing gui.sp_l - gui.sp_s
            for i in range(1, 7):
                use vn_save_slot(i, is_save)

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
                vbox:
                    spacing gui.sp_m
                    $ _g = vn_loc.t("ui.prefs.display").upper()
                    text _g style "vn_group"
                    hbox:
                        spacing gui.sp_xs
                        textbutton vn_loc.t("ui.prefs.windowed") action Preference("display", "window") style "vn_seg_button"
                        textbutton vn_loc.t("ui.prefs.fullscreen") action Preference("display", "fullscreen") style "vn_seg_button"
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
            vbox:
                spacing gui.sp_l + gui.sp_s
                vbox:
                    spacing gui.sp_m
                    $ _g4 = vn_loc.t("ui.prefs.skip").upper()
                    text _g4 style "vn_group"
                    textbutton vn_loc.t("ui.prefs.skip_all") action Preference("skip", "toggle") style "vn_toggle_button"
                    textbutton vn_loc.t("ui.prefs.skip_after_choices") action Preference("after choices", "toggle") style "vn_toggle_button"
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

style vn_slider:
    xsize 560
    ysize 22
    left_bar Solid(gui.accent_color)
    right_bar Solid(gui.panel_border2)
    thumb Transform(Solid(gui.text_color), xysize=(20, 20))

style vn_seg_button:
    padding (gui.sp_l - 6, gui.sp_m - gui.sp_xs)
    background Solid(gui.panel_bg_deep)
    hover_background Solid(gui.panel_bg)
    selected_background Solid(gui.panel_bg_hover)

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
                mousewheel True
                draggable True
                pagekeys True
                scrollbars "vertical"
                xsize 460
                ymaximum 420
                yinitial (_sel / float(max(1, len(_langs) - 1)))
                vscrollbar_unscrollable "hide"
                vscrollbar_base_bar Solid(gui.panel_bg_deep)
                vscrollbar_thumb Solid(gui.panel_border2)
                vscrollbar_xsize 6
                vbox:
                    spacing gui.sp_xs // 2
                    for _l in _langs:
                        textbutton _l["name"]:
                            style "pref_lang_button"
                            text_font (_l["font"] if _l["font"] and renpy.loadable(_l["font"]) else gui.text_font)
                            action vn_lang.action(_l["code"])

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

screen confirm(message, yes_action, no_action):
    modal True
    zorder 200
    # QA-автопилот: модальные подтверждения отвечают «Да» сами; вне автопилота — no-op.
    if vn_qa.autopilot_active():
        timer 0.8 action yes_action repeat True
    add Solid("#0000009e")
    frame:
        style "vn_dialog"
        vbox:
            spacing gui.sp_l
            text message style "vn_dialog_text"
            hbox:
                xalign 0.5
                spacing gui.sp_m
                use vn_button(vn_loc.t("ui.confirm.yes"), yes_action, kind="primary")
                use vn_button(vn_loc.t("ui.confirm.no"), no_action, kind="secondary")

style vn_dialog:
    xalign 0.5
    yalign 0.5
    xsize 560
    background Solid(gui.panel_bg)
    padding (gui.sp_l + gui.sp_s, gui.sp_l + gui.sp_s)

style vn_dialog_text:
    font gui.interface_text_font
    size gui.interface_text_size + 3
    color gui.text_color
    xalign 0.5
    text_align 0.5
    line_spacing gui.sp_s


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
    xpos 36
    ypos 32
    background Solid("#18181bf2")
    padding (gui.sp_m + 6, gui.sp_m - 2)

style vn_toast_text:
    font gui.interface_text_font
    size gui.interface_text_size - gui.sp_xs
    color "#e4e4e7"
