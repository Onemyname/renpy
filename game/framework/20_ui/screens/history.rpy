# History / backlog (новый): «кто сказал что», прокрутка, пустое состояние.
# Цвет имени — из who_args записи (Character(color=…) доезжает сам).

init offset = 0

define config.history_length = 250

screen history():
    tag menu
    add Solid("#09090bf2")
    hbox:
        xalign 0.5
        ypos 72
        xsize 1100
        text vn_loc.t("ui.nav.history") style "vn_hist_title"
        # Подсказка закрытия зависит от окружения (vn_ui.hint, components.rpy):
        # на Deck/ТВ «Esc» игроку не нажать — там пад-вариант той же строки.
        text vn_ui.hint("ui.history.hint") style "vn_hist_hint" xalign 1.0 yalign 1.0
    if not _history_list:
        vbox:
            align (0.5, 0.5)
            spacing gui.sp_s + 2
            text vn_loc.t("ui.history.empty") style "vn_hist_empty" xalign 0.5
            text vn_loc.t("ui.history.empty_hint") style "vn_hist_empty_hint" xalign 0.5
    else:
        # Пад/клавиатура (аудит ui.md P0 №1): список без фокусируемых детей —
        # arrowkeys True делает viewport фокусируемым (dpad/стрелки скроллят),
        # default_focus отдаёт ему фокус сразу; LB/RB листают через pagekeys
        # (пад-биндинги viewport_pageup/pagedown — input.rpy).
        viewport id "vp_history":
            properties vn_scroll_props
            arrowkeys True
            default_focus True
            xalign 0.5
            ypos 150
            xsize 1100
            ysize 830
            yinitial 1.0
            vbox:
                # xfill — чтобы разделитель тянулся на ширину вьюпорта;
                # вертикальный ритм — spacing (ypadding невалиден для hbox).
                xfill True
                spacing gui.sp_l - 6
                for h in _history_list:
                    hbox:
                        spacing gui.sp_l + gui.sp_xs
                        $ _c = ((h.who_args or {}).get("color") or gui.accent_color)
                        frame:
                            style "vn_hist_who_cell"
                            if h.who:
                                text h.who style "vn_hist_who" color _c xalign 1.0
                        text h.what style "vn_hist_what"
                    add Solid(gui.divider_color) ysize 1

style vn_hist_title:
    font gui.interface_semibold_font
    size gui.label_text_size
    color gui.text_color

style vn_hist_hint:
    font gui.interface_text_font
    size gui.small_text_size - 1
    color gui.faint_color

style vn_hist_empty:
    font gui.interface_text_font
    size gui.interface_text_size + 3
    color gui.muted_color

style vn_hist_empty_hint:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.insensitive_color

style vn_hist_who_cell:
    background None
    xsize 200
    padding (0, 3)

style vn_hist_who:
    font gui.name_text_font
    size gui.interface_text_size
    text_align 1.0

style vn_hist_what:
    font gui.text_font
    size gui.text_size - gui.sp_s
    color gui.sub_color
    xmaximum 860
    line_spacing gui.sp_s + 1
