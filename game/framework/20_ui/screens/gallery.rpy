# Галерея (ADR-0010): сетка превью по категориям + просмотрщик.
#
# Экран НЕ знает ни списка элементов, ни правил разблокировки — только спрашивает
# store vn_gal (данные из generated/registry/gallery.gen.rpy). Добавление
# элемента, категории или типа контента не требует правок этого файла.
#
# Производительность: в сетке — ТОЛЬКО превью (thumb из конвейера, 512px по
# длинной стороне; у послойного шота — композитное превью, ADR-0013).
# Полноразмерный кадр, живой layeredimage шота и видео появляются лишь в
# просмотрщике и уходят из дерева отображения при его закрытии — движок сам
# освобождает текстуру, Movie останавливается вместе с экраном.
#
# Локализация: подписи — только ключи (vn_loc.t и *_key элементов). Новый язык
# не требует правок этого файла.

init offset = 0

# Выбранная вкладка и режим увеличения — состояние ЭКРАНА, а не игры, поэтому
# объявлены внутри экранов, а не store-default'ами. Store-default попадает в
# ever_been_changed движка, то есть в КАЖДЫЙ сейв и в rollback-лог (SDK
# rollback.py: freeze/roots) — сохранённая вкладка галереи возвращалась бы из
# сейва, а откат колесом за вход в меню сбрасывал бы её; «_»-префикс от этого не
# спасает. Цена решения: вкладка и зум живут, пока показан экран.


screen gallery():
    tag menu

    default category = None         # None -> первая доступная категория

    $ _cats = vn_gal.categories()
    $ _cat_ids = [c[0] for c in _cats]
    $ _cur = category if category in _cat_ids else (
        _cat_ids[0] if _cat_ids else None)
    $ _done, _total = vn_gal.progress()

    use vn_game_menu(vn_loc.t("ui.nav.gallery")):
        vbox:
            spacing gui.sp_l

            # ── Прогресс и вкладки: и то и другое считается из реестра ────────
            hbox:
                spacing gui.sp_l
                text "[_done] / [_total]" style "vn_counter" yalign 0.5
                hbox:
                    spacing gui.sp_xs
                    for _cid, _cspec in _cats:
                        $ _cd, _ct = vn_gal.progress(_cid)
                        textbutton "%s  %d/%d" % (vn_loc.t(_cspec["title_key"]), _cd, _ct):
                            style "vn_gal_tab"
                            # ScreenVariable адресует переменную ВЕРХНЕГО экрана —
                            # в том числе из transclude-тела use vn_game_menu, где
                            # живёт эта кнопка (док движка, «Data Actions»); там же
                            # сказано, что LocalVariable нужна только внутри
                            # use'нутого экрана, а в остальных случаях предпочтителен
                            # ScreenVariable (кэширование экрана).
                            action SetScreenVariable("category", _cid)
                            selected (_cid == _cur)

            if not _cats:
                text vn_loc.t("ui.gallery.empty") style "vn_empty_note"
            else:
                # Пад/клавиатура (аудит ui.md P0 №2): ряды за фолдом ysize
                # недостижимы фокусом — ячейки докручивают сетку через
                # vn_ui.reveal (hovered ловит и клавиатурный фокус).
                $ _items = vn_gal.items(_cur)
                $ _rows = (len(_items) + 2) // 3
                vpgrid id "vp_gallery":
                    properties vn_scroll_props
                    cols 3
                    allow_underfull True
                    spacing gui.sp_m
                    ysize gui.scroll_height
                    for _i, (_iid, _spec) in enumerate(_items):
                        # Первая ячейка забирает default focus у рельсы (§5.1):
                        # иначе слепой A уводил из галереи в «Сохранение».
                        use vn_gal_cell(_iid, _spec, _i // 3, _rows,
                                        focus_default=(_i == 0))


# ── Ячейка сетки: открытая (превью) или закрытая (заглушка без контента) ──────
# Закрытые ячейки ОСТАЮТСЯ в dpad-пути сознательно (аудит ui.md P2 №14
# отклонён): выпади целый ряд закрытых из фокус-цепочки — следующий открытый
# ряд за фолдом стал бы недостижим (reveal некому дёрнуть).

screen vn_gal_cell(item_id, spec, row=None, rows=None, focus_default=False):
    $ _open = vn_gal.is_unlocked(item_id)
    button:
        # Стиль ОДИН на оба состояния, и это принципиально: у закрытой ячейки был
        # свой стиль ровно ради hover_background = обычному фону, то есть ради
        # ОТСУТСТВИЯ подсветки — и на dpad-проходе по ряду закрытых игрок терял
        # курсор из вида (закрытые остаются в фокус-цепочке, см. выше).
        # «Закрытость» держится содержимым (знак вопроса вместо превью и подпись
        # «Закрыто»), а не отключённым фокусом.
        style "vn_gal_cell"
        action (Show("gallery_viewer", item_id=item_id) if _open else NullAction())
        default_focus (gui.focus_content if focus_default else 0)
        if row is not None:
            hovered Function(vn_ui.reveal, "gallery", "vp_gallery", row, rows)
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
    default zoom = False

    $ _spec = VN_GALLERY[item_id]
    # Что листает кнопка «Вариант», решает стор: у плоской CG это файлы-варианты,
    # у послойного шота — комбинации вариантов слоёв (имя образа + атрибуты).
    $ _looks = vn_gal.looks(_spec)
    $ _sibs = vn_gal.unlocked_ids(_spec["category"])
    $ _pos = _sibs.index(item_id) if item_id in _sibs else 0
    $ _idx = variant % len(_looks)

    add Solid("#000000f2")

    if _spec["kind"] == "movie":
        # Movie существует ровно пока экран показан: Hide освобождает ресурс.
        # Листаем ИМЕННО _looks[_idx]: варианты видео объявлялись в gallery.yaml,
        # счётчик «1/2» и кнопка показывались, а играл всегда основной ассет.
        add Movie(play=_looks[_idx], loop=True) fit "contain" xysize (1920, 1080)
    else:
        # Шот попадает сюда ЖИВЫМ layeredimage, а не превью: ровно в этом ценность
        # послойного кадра для галереи — наряд листается, а не перерисовывается.
        # fit contain — без растягивания при любых пропорциях (portrait/landscape);
        # zoom переключает на cover (заполнение экрана с обрезкой).
        add _looks[_idx] fit ("cover" if zoom else "contain") xysize (1920, 1080)

    vbox:
        xpos gui.sp_xl
        yanchor 1.0
        ypos 1080 - gui.sp_xl - 48
        spacing gui.sp_xs
        text vn_loc.t(_spec["title_key"]) style "vn_gal_view_title"
        if _spec.get("desc_key"):
            text vn_loc.t(_spec["desc_key"]) style "vn_gal_view_desc"
        if len(_looks) > 1:
            text "%d / %d" % (_idx + 1, len(_looks)) style "vn_gal_view_desc"

    hbox:
        xalign 0.5
        yanchor 1.0
        # overscan_pad (scale.rpy): на ТВ Big Picture нижняя кромка срезается
        ypos 1080 - gui.sp_m - gui.overscan_pad
        spacing gui.sp_s
        style_prefix "vn_gal_ctl"
        if len(_sibs) > 1:
            textbutton vn_loc.t("ui.gallery.prev") action Show(
                "gallery_viewer", item_id=_sibs[(_pos - 1) % len(_sibs)])
        if len(_looks) > 1:
            # Один чип на все виды кадра — он же единственный путь с пада: dpad
            # доводит фокус до чипа, A переключает (плечи заняты листанием
            # элементов). Отдельной кнопки на слой нет сознательно: их число
            # заранее не известно, а ряд чипов на ТВ уехал бы за кромку.
            textbutton vn_loc.t("ui.gallery.variant") action SetLocalVariable(
                "variant", _idx + 1)
        if _spec["kind"] != "movie":
            # LocalVariable — как у variant рядом: экран верхний (его Show'ят
            # напрямую), и оба действия пишут в его же scope.
            textbutton vn_loc.t("ui.gallery.zoom") action ToggleLocalVariable("zoom")
        # Movie перезапускается сменой _looks[_idx] — отдельного действия не нужно
        if len(_sibs) > 1:
            textbutton vn_loc.t("ui.gallery.next") action Show(
                "gallery_viewer", item_id=_sibs[(_pos + 1) % len(_sibs)])
        # default_focus: первый A с пада — безопасное «Назад», не листание
        textbutton vn_loc.t("ui.common.back") action Hide("gallery_viewer") default_focus True

    # Клавиатура/геймпад: стрелки и LB/RB листают (ui.md §6: dpad шлёт
    # focus_*, а не keysym — плечи здесь единственный пад-способ листать,
    # не гоняя фокус по чипам), Esc/B закрывают.
    if len(_sibs) > 1:
        key "K_LEFT" action Show("gallery_viewer", item_id=_sibs[(_pos - 1) % len(_sibs)])
        key "K_RIGHT" action Show("gallery_viewer", item_id=_sibs[(_pos + 1) % len(_sibs)])
        key "pad_leftshoulder_press" action Show("gallery_viewer", item_id=_sibs[(_pos - 1) % len(_sibs)])
        key "pad_rightshoulder_press" action Show("gallery_viewer", item_id=_sibs[(_pos + 1) % len(_sibs)])
    if len(_looks) > 1:
        # Вверх/вниз листают виды кадра — клавиатурная симметрия к стрелкам
        # «влево/вправо». Пад-события сюда не мапятся (dpad шлёт focus_*), и
        # своей пад-кнопки эти стрелки не получают: с пада вид переключает чип.
        key "K_UP" action SetLocalVariable("variant", _idx - 1)
        key "K_DOWN" action SetLocalVariable("variant", _idx + 1)
    key "K_ESCAPE" action Hide("gallery_viewer")
    key "game_menu" action Hide("gallery_viewer")


# Метка «видео» на превью: ромб из Solid, без бинарных ассетов
image vn_gal_play = Transform(Solid(gui.text_color), xysize=(26, 26), rotate=45,
                              alpha=0.85)


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

style vn_gal_cell:
    xysize (472, 266)
    padding (0, 0)
    background vn_frame_slot
    hover_background vn_frame_choice_hover

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
