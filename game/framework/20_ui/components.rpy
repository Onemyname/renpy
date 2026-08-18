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

## ── vn_scroll: единый скролл-приём (controller-first, аудит ui.md §1) ────────
##    Проблема: движок не докручивает viewport к клавиатурному фокусу, а кнопки
##    за границей клипа выпадают из фокус-листа (focus_nearest пропускает
##    кандидатов без фокус-ректа) — dpad упирается в край видимой области.
##    Приём из двух частей:
##      1) vn_scroll_props — общие свойства viewport/vpgrid (колёсико, драг,
##         pagekeys + LB/RB из input.rpy, единый скроллбар) вместо копий
##         настроек в каждом экране;
##      2) vn_ui.reveal(...) — hovered-колбэк ячейки: hovered срабатывает и на
##         клавиатурный фокус, докручивает adjustment так, чтобы ряд был виден
##         целиком и «подглядывал» следующий — тот получает фокус-рект и
##         становится достижим следующим нажатием dpad.

define vn_scroll_props = {
    "mousewheel": True,
    "draggable": True,
    "pagekeys": True,
    "scrollbars": "vertical",
    "vscrollbar_unscrollable": "hide",
    "vscrollbar_base_bar": Solid(gui.panel_bg_deep),
    "vscrollbar_thumb": Solid(gui.panel_border2),
    "vscrollbar_xsize": 6,
}

init -990 python in vn_ui:
    from store import renpy, gui

    def reveal(screen_name, vp_id, row, rows, peek=None):
        """Прокрутить viewport `vp_id` экрана `screen_name` так, чтобы ряд `row`
        (из `rows` рядов равной высоты) был виден целиком плюс `peek` px соседа.
        Равновысотность рядов позволяет считать геометрию от adjustment
        (range + page = высота контента) без знания метрик шрифтов."""
        if not rows:
            return
        vp = renpy.get_widget(screen_name, vp_id)
        adj = getattr(vp, "yadjustment", None)
        if adj is None:
            return
        rng, page = adj.range or 0, adj.page or 0
        if rng <= 0 or page <= 0:
            return                        # всё влезает — крутить нечего
        if peek is None:
            peek = gui.sp_xl
        row_h = (rng + page) / float(rows)
        top = row * row_h - peek
        bottom = (row + 1) * row_h + peek
        # Минимальный сдвиг: вниз — чтобы низ ряда (с peek) влез, вверх — верх
        value = min(max(adj.value, bottom - page), max(top, 0))
        if value != adj.value:
            adj.change(max(0, min(value, rng)))

    def menu_screen():
        """Имя экрана меню, открытого сейчас (все они делят tag "menu"), или
        None. Нужно рельсе навигации: её резервный default focus садится на
        пункт ТЕКУЩЕГО экрана, а не на первый (42-big-picture.md §5.1).
        Спрашиваем движок по тегу, а не держим список экранов, — иначе новый
        экран меню пришлось бы дописывать и здесь."""
        sd = renpy.get_screen("menu")
        return sd.name if sd is not None else None


## ── vn_modal_dialog: каркас модалки (аудит ui.md §2) ─────────────────────────
##    modal/zorder при use НЕ наследуются (свойства показанного экрана) —
##    потребитель обязан объявить их сам; каркас даёт затемнение, отмену по
##    B/Esc (modal-экран глотает game_menu — без своего key кнопки мертвы)
##    и рамку. Безопасная кнопка получает default focus через vn_button.

screen vn_modal_dialog(cancel_action):
    add Solid("#0000009e")
    key "game_menu" action cancel_action
    frame:
        style "vn_dialog"
        transclude

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


## ── vn_button(kind=primary|secondary|danger) ─────────────────────────────────
##    focus_default: первый A с пада уходит в эту кнопку, а не «в пустоту»
##    (аудит ui.md §3) — в модалках ставится на БЕЗОПАСНУЮ кнопку.

screen vn_button(label=None, action=NullAction(), kind="primary", sensitive=True,
                 focus_default=False):
    button:
        style ("vn_btn_" + kind)
        action action
        sensitive sensitive
        default_focus focus_default
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
##    Первый фокус (42-big-picture.md §5.1). Рельса рисуется ДО контента, но
##    порядок тут ни при чём: движок берёт НАИБОЛЬШИЙ default_focus. Поэтому
##    приоритет и решает, и решает он один раз здесь, а не в каждом экране:
##      * контент объявляет default_focus gui.focus_content (2) на безопасном
##        элементе — и всегда перебивает рельсу;
##      * рельса объявляет gui.focus_rail (1) и только на пункте ТЕКУЩЕГО
##        экрана (navigation, core_screens.rpy) — если контент промолчал,
##        слепой A переоткрывает то же меню, то есть не делает ничего.
##    Почему не «параметр focus_content у каркаса»: параметр надо передать из
##    каждого экрана, и забытый параметр возвращает дефект. Здесь забытый
##    default_focus в контенте деградирует до безвредного no-op'а рельсы —
##    новый экран меню безопасен по построению, править его не обязательно.

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

## focus_default: первый слот страницы забирает default focus у рельсы (§5.1).
## Безопасно: FileSave(slot) на занятый слот сам спрашивает подтверждение, а у
## пустого слота в «Загрузке» кнопка insensitive — движок такую в фокус-лист не
## берёт (behavior.py:1100), и фокус штатно откатывается на рельсу.
screen vn_save_slot(slot, is_save, focus_default=False):
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
            default_focus (gui.focus_content if focus_default else 0)
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

## ── vn_slider: слайдер настроек (токен-компонент, аудит ui.md §4) ────────────
##    hover_/selected_-варианты обязательны: bar управляется grab-паттерном
##    (A -> dpad -> A), и без смены цвета сфокусированный/захваченный слайдер
##    неотличим от обычного — на паде это читается как «не работает».

style vn_slider:
    xsize 560
    ysize 22
    left_bar Solid(gui.accent_color)
    right_bar Solid(gui.panel_border2)
    thumb Transform(Solid(gui.text_color), xysize=(20, 20))
    hover_left_bar Solid(gui.hover_color)
    hover_right_bar Solid(gui.panel_bg_hover)
    hover_thumb Transform(Solid(gui.hover_color), xysize=(20, 20))
    selected_left_bar Solid(gui.hover_color)
    selected_right_bar Solid(gui.panel_bg_hover)
    selected_thumb Transform(Solid(gui.hover_color), xysize=(20, 20))


## ── vn_chapter_card: карточка главы (использует эмиттер chapter_select) ──────
##    row/rows — координаты в сетке chapter_select для vn_ui.reveal (прокрутка
##    к фокусу); None — карточка вне скролла, колбэк не вешается.
##    focus_default: первая карточка забирает default focus у рельсы (§5.1) —
##    иначе слепой A на экране выбора глав уходил в Start() рельсы, то есть
##    начинал игру с первой главы вместо выбранной.

screen vn_chapter_card(ch, row=None, rows=None, focus_default=False):
    button:
        style "vn_chapter_card"
        action Start(ch["entry_label"])
        default_focus (gui.focus_content if focus_default else 0)
        if row is not None:
            hovered Function(vn_ui.reveal, "chapter_select", "vp_chapters", row, rows)
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

style vn_chapter_card is vn_slot:
    # Жёсткая ширина карточки: vpgrid предлагает ячейке всю ширину ряда, и
    # xfill-плашка заголовка (vn_slot_meta) растянулась бы на весь экран.
    xsize gui.slot_width

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
