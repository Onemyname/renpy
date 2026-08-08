# Компонентная библиотека 20_ui (раздел 7.8). Имена: ^vn_[a-z0-9_]+$.
# Все значения — из gui.* (линт «магических чисел» проходит по построению).
# Без бинарных картинок: Solid / Frame / Transform / ATL / outlines / alpha.

init offset = 0

## ── Базовые стили ─────────────────────────────────────────────────────────────

style default:
    font gui.text_font
    size gui.text_size
    color gui.text_color

style button_text:
    font gui.interface_text_font
    size gui.interface_text_size
    color gui.idle_color
    hover_color gui.text_color
    selected_color gui.accent_color
    insensitive_color gui.insensitive_color

style label_text:
    font gui.interface_semibold_font
    size gui.label_text_size
    color gui.text_color

style frame:
    background Solid(gui.panel_bg)
    padding (gui.sp_l, gui.sp_l)

style input_prompt:
    color gui.accent_color

## ── CTC-индикатор (ромб из Solid — без картинок) ──────────────────────────────

image vn_ctc = Transform(Solid(gui.accent_color), xysize=(14, 14), rotate=45)

transform vn_ctc_blink:
    block:
        easein 0.7 alpha 0.3 yoffset 0
        easeout 0.7 alpha 1.0 yoffset 4
        repeat

transform vn_toast_in:
    alpha 0.0 yoffset -14
    easeout 0.25 alpha 1.0 yoffset 0

## ── vn_scrim: ступенчатый градиент затемнения (движок не умеет градиент
##    без картинок; плавная версия — кандидат png2webp_ui@1, см. README патча) ──

screen vn_scrim(height=None):
    $ _h = height or gui.textbox_height
    $ _steps = (0.0, 0.10, 0.24, 0.42, 0.60, 0.74, gui.textbox_scrim_alpha)
    vbox:
        xfill True
        yalign 1.0
        for _a in _steps:
            # xfill у add невалиден (это свойство контейнера) — Solid и так
            # растягивается на ширину, предложенную vbox'ом с xfill True.
            add Solid(gui.textbox_scrim) ysize (_h // len(_steps)) alpha _a

## ── vn_panel: универсальная панель (transclude) ──────────────────────────────

screen vn_panel(title=None):
    frame:
        style "vn_panel"
        vbox:
            spacing gui.sp_m
            if title:
                text title style "vn_panel_title"
            transclude

style vn_panel is frame
style vn_panel_title is label_text

## ── vn_button(kind=primary|secondary|danger) ─────────────────────────────────

screen vn_button(label=None, action=NullAction(), kind="primary", sensitive=True):
    button:
        style ("vn_btn_" + kind)
        action action
        sensitive sensitive
        if label is not None:
            text label style ("vn_btn_" + kind + "_text")

style vn_btn_primary:
    background Solid(gui.accent_color)
    hover_background Solid(gui.hover_color)
    insensitive_background Solid(gui.panel_border2)
    padding (gui.sp_xl - gui.sp_m, gui.sp_m)

style vn_btn_primary_text:
    font gui.interface_semibold_font
    size gui.button_text_size
    color gui.on_accent_color
    hover_color gui.on_accent_color
    insensitive_color gui.insensitive_color

style vn_btn_secondary is vn_btn_primary:
    background Solid(gui.panel_bg_hover)
    hover_background Solid(gui.panel_border2)
    insensitive_background Solid(gui.panel_bg_deep)

style vn_btn_secondary_text is vn_btn_primary_text:
    color gui.sub_color
    hover_color gui.text_color

style vn_btn_danger is vn_btn_secondary
style vn_btn_danger_text is vn_btn_secondary_text:
    color gui.danger_color
    hover_color gui.danger_color

## ── vn_game_menu: каркас игрового меню (рельса слева + контент) ──────────────

screen vn_game_menu(title):
    add Solid(gui.menu_bg)
    use navigation
    frame:
        style "vn_menu_content"
        vbox:
            spacing gui.sp_l
            label title
            transclude

style vn_menu_content:
    xpos 336
    ypos 0
    xsize 1584
    ysize 1080
    background None
    padding (gui.sp_xl + gui.sp_s, gui.sp_xl)

## ── vn_save_slot: карточка сейва (скриншот, время, имя, удаление) ────────────

screen vn_save_slot(slot, is_save):
    $ _loadable = FileLoadable(slot)
    # Загрузка в игре теряет прогресс — подтверждаем СВОИМ текстом (движковый
    # confirm у FileLoad — английская layout-строка); confirm_selected — от FileLoad.
    $ _action = FileSave(slot) if is_save else (FileLoad(slot) if main_menu else Confirm(vn_loc.t("ui.confirm.load"), FileLoad(slot, confirm=False), confirm_selected=True))
    fixed:
        xsize gui.slot_width
        ysize gui.slot_height
        button:
            style "vn_slot"
            action _action
            sensitive (True if is_save else _loadable)
            vbox:
                fixed:
                    xsize gui.slot_width
                    ysize gui.slot_thumb_height
                    if _loadable:
                        add FileScreenshot(slot) xysize (gui.slot_width, gui.slot_thumb_height)
                        if FileNewest(slot):
                            frame:
                                style "vn_slot_tag"
                                align (0.04, 0.92)
                                text vn_loc.t("ui.file.latest") style "vn_slot_tag_text"
                    else:
                        add Solid(gui.panel_bg_deep)
                        text vn_loc.t("ui.file.empty_slot") style "vn_slot_empty" align (0.5, 0.5)
                    frame:
                        style "vn_slot_num"
                        align (0.04, 0.08)
                        text "[slot]" style "vn_slot_num_text"
                frame:
                    style "vn_slot_meta"
                    vbox:
                        spacing gui.sp_xs
                        text FileTime(slot, format=vn_loc.t("ui.file.time_format"), empty=vn_loc.t("ui.file.empty_slot")) style "vn_slot_time"
                        text FileSaveName(slot) style "vn_slot_name"
        if _loadable:
            # Удаление — свой confirm (FileDelete(confirm=True) показал бы layout-строку)
            textbutton vn_loc.t("ui.file.delete_mark"):
                style "vn_slot_delete"
                align (0.97, 0.03)
                action Confirm(vn_loc.t("ui.confirm.delete"), FileDelete(slot, confirm=False))

style vn_slot:
    background Solid(gui.panel_bg)
    hover_background Solid(gui.panel_bg_hover)
    insensitive_background Solid(gui.panel_bg_deep)
    padding (0, 0)

style vn_slot_meta:
    background None
    xfill True
    padding (gui.sp_m + gui.sp_xs, gui.sp_m)

style vn_slot_time:
    font gui.interface_semibold_font
    size gui.small_text_size + 2
    color gui.text_color

style vn_slot_name:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.muted_color

style vn_slot_empty:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.faint_color

style vn_slot_num:
    background Solid("#00000090")
    padding (gui.sp_s + 2, gui.sp_xs)

style vn_slot_num_text:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    color gui.sub_color

style vn_slot_tag:
    background Solid(gui.accent_color)
    padding (gui.sp_s + 2, gui.sp_xs)

style vn_slot_tag_text:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    color gui.on_accent_color

style vn_slot_delete:
    background Solid("#00000080")
    hover_background Solid(gui.danger_color)
    padding (gui.sp_s + 4, gui.sp_xs + 2)

style vn_slot_delete_text:
    font gui.interface_text_font
    size gui.interface_text_size
    color gui.muted_color
    hover_color gui.text_color

## ── vn_chapter_card: карточка главы (использует эмиттер chapter_select) ──────

screen vn_chapter_card(ch):
    button:
        style "vn_chapter_card"
        action Start(ch["entry_label"])
        vbox:
            fixed:
                xsize gui.slot_width
                ysize 200
                add Solid(gui.panel_bg_deep)
                text ch["id"][2:] style "vn_chapter_num" align (0.06, 0.88)
                if ch["pack"] != "core":
                    frame:
                        style "vn_chapter_dlc"
                        align (0.95, 0.08)
                        text vn_loc.t("ui.chapters.dlc") style "vn_chapter_dlc_text"
            frame:
                style "vn_slot_meta"
                text vn_loc.t(ch["title_key"]) style "vn_chapter_title"

style vn_chapter_card is vn_slot

style vn_chapter_num:
    font gui.text_font
    size gui.sp_xl + gui.sp_s
    color "#ffffff29"

style vn_chapter_dlc:
    background None
    padding (gui.sp_s + 2, gui.sp_xs)

style vn_chapter_dlc_text:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    color gui.accent_color
    kerning 1.0

style vn_chapter_title:
    font gui.interface_semibold_font
    size gui.interface_text_size - 2
    color gui.text_color
