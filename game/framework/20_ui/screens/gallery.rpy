# Галерея (ADR-0010): сетка превью по категориям + просмотрщик.
#
# Экран НЕ знает ни списка элементов, ни правил разблокировки — только спрашивает
# store vn_gal (данные из generated/registry/gallery.gen.rpy). Добавление
# элемента, категории или типа контента не требует правок этого файла.
#
# Производительность: в сетке — ТОЛЬКО превью (thumb из конвейера, 512px по
# длинной стороне). Полноразмерный кадр и видео появляются лишь в просмотрщике
# и уходят из дерева отображения при его закрытии — движок сам освобождает
# текстуру, Movie останавливается вместе с экраном.
#
# Локализация: подписи — только ключи (vn_loc.t и *_key элементов). Новый язык
# не требует правок этого файла.

init offset = 0

default vn_gal_category = None      # выбранная вкладка; None -> первая доступная
default vn_gal_zoom = False         # режим увеличения в просмотрщике


screen gallery():
    tag menu

    $ _cats = vn_gal.categories()
    $ _cat_ids = [c[0] for c in _cats]
    $ _cur = vn_gal_category if vn_gal_category in _cat_ids else (
        _cat_ids[0] if _cat_ids else None)
    $ _done, _total = vn_gal.progress()

    use vn_game_menu(vn_loc.t("ui.nav.gallery")):
        vbox:
            spacing gui.sp_l

            # ── Прогресс и вкладки: и то и другое считается из реестра ────────
            hbox:
                spacing gui.sp_l
                text "[_done] / [_total]" style "vn_gal_progress" yalign 0.5
                hbox:
                    spacing gui.sp_xs
                    for _cid, _cspec in _cats:
                        $ _cd, _ct = vn_gal.progress(_cid)
                        textbutton "%s  %d/%d" % (vn_loc.t(_cspec["title_key"]), _cd, _ct):
                            style "vn_gal_tab"
                            action SetVariable("vn_gal_category", _cid)
                            selected (_cid == _cur)

            if not _cats:
                text vn_loc.t("ui.gallery.empty") style "vn_gal_empty"
            else:
                vpgrid:
                    cols 3
                    spacing gui.sp_m
                    ysize 800
                    mousewheel True
                    draggable True
                    pagekeys True
                    scrollbars "vertical"
                    vscrollbar_unscrollable "hide"
                    vscrollbar_base_bar Solid(gui.panel_bg_deep)
                    vscrollbar_thumb Solid(gui.panel_border2)
                    vscrollbar_xsize 6
                    for _iid, _spec in vn_gal.items(_cur):
                        use vn_gal_cell(_iid, _spec)


# ── Ячейка сетки: открытая (превью) или закрытая (заглушка без контента) ──────

screen vn_gal_cell(item_id, spec):
    $ _open = vn_gal.is_unlocked(item_id)
    button:
        style ("vn_gal_cell" if _open else "vn_gal_cell_locked")
        action (Show("gallery_viewer", item_id=item_id) if _open else NullAction())
        fixed:
            xysize (472, 266)
            if _open:
                add (spec["thumb"] or spec["asset"]) fit "cover" xysize (472, 266)
                # Плашка под подпись: текст обязан читаться на любом кадре
                add Solid("#0a0a0cd9") xysize (472, 48) yalign 1.0
                text vn_loc.t(spec["title_key"]) style "vn_gal_caption"
                if spec["kind"] == "movie":
                    add "vn_gal_play" align (0.5, 0.42)
            else:
                # Закрытый элемент НЕ показывает контент: только знак вопроса
                add Solid(gui.panel_bg_deep)
                text "?" style "vn_gal_lock_mark" align (0.5, 0.4)
                text vn_loc.t("ui.gallery.locked") style "vn_gal_caption_locked"


# ── Просмотрщик: полноразмерный кадр/видео, варианты, листание, зум ──────────

screen gallery_viewer(item_id):
    tag gallery_viewer
    modal True
    zorder 60
    default variant = 0

    $ _spec = VN_GALLERY[item_id]
    $ _shots = [_spec["asset"]] + list(_spec.get("variants") or [])
    $ _sibs = vn_gal.unlocked_ids(_spec["category"])
    $ _pos = _sibs.index(item_id) if item_id in _sibs else 0
    $ _idx = variant % len(_shots)

    add Solid("#000000f2")

    if _spec["kind"] == "movie":
        # Movie существует ровно пока экран показан: Hide освобождает ресурс
        add Movie(play=_spec["asset"], loop=True) fit "contain" xysize (1920, 1080)
    else:
        # fit contain — без растягивания при любых пропорциях (portrait/landscape);
        # zoom переключает на cover (заполнение экрана с обрезкой).
        add _shots[_idx] fit ("cover" if vn_gal_zoom else "contain") xysize (1920, 1080)

    vbox:
        xpos gui.sp_xl
        yanchor 1.0
        ypos 1080 - gui.sp_xl - 48
        spacing gui.sp_xs
        text vn_loc.t(_spec["title_key"]) style "vn_gal_view_title"
        if _spec.get("desc_key"):
            text vn_loc.t(_spec["desc_key"]) style "vn_gal_view_desc"
        if len(_shots) > 1:
            text "%d / %d" % (_idx + 1, len(_shots)) style "vn_gal_view_desc"

    hbox:
        xalign 0.5
        yanchor 1.0
        ypos 1080 - gui.sp_m
        spacing gui.sp_s
        style_prefix "vn_gal_ctl"
        if len(_sibs) > 1:
            textbutton vn_loc.t("ui.gallery.prev") action Show(
                "gallery_viewer", item_id=_sibs[(_pos - 1) % len(_sibs)])
        if len(_shots) > 1:
            textbutton vn_loc.t("ui.gallery.variant") action SetLocalVariable(
                "variant", _idx + 1)
        if _spec["kind"] == "image":
            textbutton vn_loc.t("ui.gallery.zoom") action ToggleVariable("vn_gal_zoom")
        if len(_sibs) > 1:
            textbutton vn_loc.t("ui.gallery.next") action Show(
                "gallery_viewer", item_id=_sibs[(_pos + 1) % len(_sibs)])
        textbutton vn_loc.t("ui.common.back") action Hide("gallery_viewer")

    # Клавиатура/геймпад: стрелки листают, Esc закрывает
    if len(_sibs) > 1:
        key "K_LEFT" action Show("gallery_viewer", item_id=_sibs[(_pos - 1) % len(_sibs)])
        key "K_RIGHT" action Show("gallery_viewer", item_id=_sibs[(_pos + 1) % len(_sibs)])
    key "K_ESCAPE" action Hide("gallery_viewer")
    key "game_menu" action Hide("gallery_viewer")


# Метка «видео» на превью: ромб из Solid, без бинарных ассетов
image vn_gal_play = Transform(Solid(gui.text_color), xysize=(26, 26), rotate=45,
                              alpha=0.85)


style vn_gal_progress:
    font gui.interface_semibold_font
    size gui.label_text_size
    color gui.accent_color

style vn_gal_tab:
    # Вкладка — 6+19+6 = 31 px. Панели choice* требуют 54-60 px, то есть
    # больше самой вкладки: фон сжался бы в пилюлю (ADR-0009, 2*Borders).
    # Чипы объявлены под этот размер — минимум 22x22.
    padding (gui.sp_m, gui.sp_xs + 2)
    background None
    hover_background vn_frame_chip
    selected_background vn_frame_chip_active

style vn_gal_tab_text:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.faint_color
    hover_color gui.text_color
    selected_color gui.accent_color

style vn_gal_empty:
    font gui.interface_text_font
    size gui.text_size
    color gui.faint_color

style vn_gal_cell:
    xysize (472, 266)
    padding (0, 0)
    background vn_frame_slot
    hover_background vn_frame_choice_hover

style vn_gal_cell_locked is vn_gal_cell:
    hover_background vn_frame_slot

style vn_gal_caption:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.text_color
    outlines [(2, "#000000b3", 0, 1)]
    xpos gui.sp_m
    yanchor 1.0
    ypos 266 - gui.sp_s - 2

style vn_gal_caption_locked is vn_gal_caption:
    color gui.faint_color
    outlines []

style vn_gal_lock_mark:
    font gui.interface_semibold_font
    size 52
    color gui.panel_border2

style vn_gal_view_title:
    font gui.interface_semibold_font
    size gui.label_text_size
    color gui.text_color
    outlines [(2, "#000000cc", 0, 1)]

style vn_gal_view_desc:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.faint_color
    outlines [(2, "#000000cc", 0, 1)]

style vn_gal_ctl_button:
    # Кнопка просмотрщика — 6+17+6 = 29 px, та же причина, что и у вкладки.
    padding (gui.sp_m, gui.sp_xs + 2)
    background vn_frame_chip
    hover_background vn_frame_chip_active

style vn_gal_ctl_button_text:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    kerning 1.2
    color "#e4e4e7"
    hover_color gui.selected_color
