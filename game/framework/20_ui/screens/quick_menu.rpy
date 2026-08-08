# Quick menu (новый): back / history / skip / auto / save / qsave / load / prefs.
# Подключение — через config.overlay_screens (образец — build_overlay.rpy):
# прячется вместе с интерфейсом (клавиша H) и не требует правок say.
# Высота кликабельной зоны ≥ 48px (норма геймпада/клавиатуры) — за счёт padding.

init offset = 0

screen vn_quick_menu():
    zorder 100
    # Поверх экранов игрового меню (галерея, настройки, сейвы) quick menu не
    # нужен: там своя навигация, а наложение двух панелей мешает.
    if not main_menu and not renpy.get_screen("menu", layer="screens"):
        hbox:
            style_prefix "vn_quick"
            xanchor 1.0
            xpos 1864
            yanchor 1.0
            ypos 1066
            spacing gui.sp_xs // 2
            $ _q_back = vn_loc.t("ui.quick.back").upper()
            $ _q_hist = vn_loc.t("ui.quick.history").upper()
            $ _q_skip = vn_loc.t("ui.quick.skip").upper()
            $ _q_auto = vn_loc.t("ui.quick.auto").upper()
            $ _q_save = vn_loc.t("ui.quick.save").upper()
            $ _q_qsave = vn_loc.t("ui.quick.qsave").upper()
            $ _q_load = vn_loc.t("ui.quick.load").upper()
            $ _q_prefs = vn_loc.t("ui.quick.prefs").upper()
            textbutton _q_back action Rollback()
            textbutton _q_hist action ShowMenu("history")
            textbutton _q_skip action Skip()
            textbutton _q_auto action Preference("auto-forward", "toggle")
            textbutton _q_save action ShowMenu("save")
            # QuickSave: движковое уведомление — layout-строка (англ. в переводах);
            # свой notify-обёртка — кандидат ADR (см. README патча).
            textbutton _q_qsave action QuickSave()
            textbutton _q_load action ShowMenu("load")
            textbutton _q_prefs action ShowMenu("preferences")

init python:
    config.overlay_screens.append("vn_quick_menu")

style vn_quick_button:
    padding (13, 17)
    background None
    hover_background Solid("#ffffff12")

style vn_quick_button_text:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    kerning 1.3
    color "#e4e4e79e"
    hover_color gui.selected_color
    selected_color gui.accent_color
    outlines [(1, "#00000059", 0, 1)]
