# Флоучарт главы (ADR-0021): граф истории глазами игрока.
#
# Экран НЕ знает ни сюжета, ни раскладки: узлы, рёбра, слои, туман войны и
# прогресс отдаёт стор vn_story (данные — generated/registry/flow.gen.rpy).
# Ручных координат нет: и колонки, и ряды, и маршруты рёбер считает
# vn_story.layout — экран рисует ровно то, что она отдала. Порядок внутри колонки
# берётся из scene_order главы; позиция узла инвариантом НЕ является (правка
# контента карту двигает — см. докстринг vn_story.layers).
#
# Что видно игроку: пройденные узлы с заголовком, непройденные — силуэтом «???»
# (структура развилки видна, содержимое — нет), концовки помечены, фазы главы
# сгруппированы подложкой (clusters из chapter.yaml). Клик по узлу — цель для
# walkthrough, а у пройденной сцены ещё и «Переиграть».
#
# «Структура развилки видна» — это требование, а не пожелание, и держит его гард
# tools/vn/tests/test_story_map.py: ни один сегмент ребра не заходит под чужую
# карточку, и у каждого ребра есть пиксели, которых не рисует никто другой. Пока
# нормы не было, карта ch01 показывала прямую цепочку вместо развилки: ребро в
# обход второй сцены рисовалось ровно по центрам карточек, то есть насквозь под
# ней, а его видимые обрезки ложились на коридоры цепочки.
#
# Зум сделан ОДНИМ Transform над всем полотном, а не умножением каждого размера
# на коэффициент. Так панели-фоны (ADR-0009) не сплющиваются: Frame рендерится
# в свою полную геометрию и уже готовый уменьшается движком. Плюс в раскладке не
# остаётся ни одного «* zoom» — ломать её нечем, и шрифты не надо подпирать
# минимумами.

init offset = 0

# Геометрия сетки в виртуальных пикселях. Пропорция карточки — 16:9, как у
# превью галереи: тогда fit "cover" не выпускает картинку за края узла.
# Размер карточки продублирован литералом в style vn_flow_node ниже (как у
# vn_gal_cell): гейт панелей test_ui_panels читает объявления стилей текстом и
# знает только gui.*.
define VN_FLOW_NODE_W = 232
define VN_FLOW_NODE_H = 130
define VN_FLOW_GAP_X = 96
define VN_FLOW_GAP_Y = 28
# Поля полотна: тень карточки и рамка кластера не должны обрезаться клипом.
define VN_FLOW_PAD = 40
define VN_FLOW_ZOOMS = (0.55, 0.75, 1.0)
# Ширина рабочей области: 1920 минус рельса навигации и её отступы.
define VN_FLOW_VIEW_W = 1500
# Высота полосы вкладок глав: вычитается из полотна, чтобы подвал с планом
# оставался на экране.
define VN_FLOW_TABS_H = 52


screen story_flow(chapter_id=None):
    tag menu

    default zoom_step = 1
    default chapter = chapter_id or vn_story.default_chapter()

    # Раскладка и маршруты рёбер — ОДИН вызов: пока экран считал их двумя
    # (layers + grid, потом connectors по всем рёбрам игры), ребро-пропуск
    # рисовалось насквозь под промежуточной карточкой и развилка на карте
    # исчезала. Разбор — в докстринге vn_story.layout.
    $ _pos = vn_story.layout(chapter, VN_FLOW_NODE_W, VN_FLOW_NODE_H,
                             VN_FLOW_GAP_X, VN_FLOW_GAP_Y) if chapter else None
    $ _done, _total = vn_story.progress(chapter) if chapter else (0, 0)
    $ _zoom = VN_FLOW_ZOOMS[zoom_step]

    use vn_game_menu(vn_loc.t("ui.chart.title")):
        vbox:
            spacing gui.sp_m

            # ── Шапка: прогресс и зум ────────────────────────────────────────
            hbox:
                spacing gui.sp_l
                text "[_done] / [_total]" style "vn_counter" yalign 0.5
                if _total:
                    text "%d%%" % (100 * _done // _total) style "vn_flow_percent" yalign 0.5
                textbutton "%s ×%.2f" % (vn_loc.t("ui.chart.zoom"), _zoom):
                    style "vn_gal_tab"
                    action SetScreenVariable(
                        "zoom_step", (zoom_step + 1) % len(VN_FLOW_ZOOMS))

            # Вкладки глав — своей прокручиваемой полосой: их число растёт с
            # игрой и с паками, и на десятке глав ряд иначе уезжает за экран
            # вместе с кнопкой масштаба.
            viewport:
                properties vn_scroll_props
                xsize VN_FLOW_VIEW_W
                ysize VN_FLOW_TABS_H
                hbox:
                    spacing gui.sp_xs
                    for _cid, _cspec in vn_story.chapter_list():
                        textbutton (vn_loc.t(_cspec["title_key"]) if _cspec["title_key"] else _cid):
                            style "vn_gal_tab"
                            action SetScreenVariable("chapter", _cid)
                            selected (_cid == chapter)

            if not _pos or not _pos["nodes"]:
                text vn_loc.t("ui.chart.empty") style "vn_empty_note"
            else:
                # Полотно: прокрутка обеими осями и перетаскивание — граф шире
                # экрана уже на пяти узлах, а с пада его двигает dpad по фокусу
                # узлов (vn_scroll_props + default_focus входного узла).
                # Открывается на ВХОДНОМ узле, а не в левом верхнем углу полотна.
                # Полотно растёт с шириной развилки и ничем не ограничено: на
                # веере из 12 листьев оно 2026 px при видимой области 748, и
                # колонка входа при этом центрирована по вертикали — то есть
                # игрок, открыв карту, видел пустоту и середину чужой колонки, а
                # вход искал прокруткой. Движок гасит xinitial/yinitial после
                # первого кадра (SDK viewport.py: update_offsets -> xoffset=None),
                # поэтому это именно НАЧАЛЬНАЯ позиция: смена масштаба и ручная
                # прокрутка её не перебивают. Смещение — в масштабированных
                # пикселях: вьюпорт видит уже преобразованного ребёнка.
                #
                # id зависит от главы НАМЕРЕННО: при совпадающем id движок
                # переносит позицию прокрутки со старого вьюпорта (replaces), и
                # переключение вкладки оставляло бы игрока на координатах чужой
                # главы. Со своим id у каждой главы своя позиция — и центровка на
                # входе при первом открытии, и возврат туда, где игрок был.
                $ _vh = gui.scroll_height - VN_FLOW_TABS_H
                $ _x0, _y0 = vn_story.initial_offset(
                    _pos, VN_FLOW_PAD, VN_FLOW_VIEW_W, _vh, _zoom,
                    VN_FLOW_NODE_W, VN_FLOW_NODE_H)
                viewport id ("vp_flow_" + chapter):
                    properties vn_scroll_props_xy
                    xsize VN_FLOW_VIEW_W
                    ysize _vh
                    xinitial _x0
                    yinitial _y0
                    fixed:
                        # Полотно 1:1; зум применяется ко всему сразу.
                        xysize (_pos["width"] + 2 * VN_FLOW_PAD,
                                _pos["height"] + 2 * VN_FLOW_PAD)
                        at zoom_canvas(_zoom)
                        # Кластеры-фазы главы — подложкой ПОД узлами.
                        for _cl in vn_story.cluster_boxes(
                                chapter, _pos, VN_FLOW_NODE_W, VN_FLOW_NODE_H,
                                VN_FLOW_GAP_Y):
                            use vn_flow_cluster(_cl)
                        # Рёбра рисуются до узлов, чтобы концы линий уходили под
                        # карточки. Под ЧУЖИМИ карточками сегментов больше нет —
                        # маршрут это гарантирует по построению (vn_story.layout),
                        # и держит гард test_story_map.py.
                        for _seg in _pos["segments"]:
                            add Solid(gui.panel_border2):
                                xysize (_seg["w"], _seg["h"])
                                xpos _seg["x"] + VN_FLOW_PAD
                                ypos _seg["y"] + VN_FLOW_PAD
                        for _sid, _xy in _pos["nodes"].items():
                            use vn_flow_node(_sid, _xy,
                                             focus_default=(_sid == _pos["entry"]),
                                             continues=_pos["continues"])

            # ── Подвал: план walkthrough ────────────────────────────────────
            use vn_flow_plan

    # Зум — на «минус»/«плюс», НЕ на PageUp/PageDown. Оба вьюпорта экрана идут с
    # пресетом, где pagekeys включён, а движковый keymap связывает
    # viewport_pageup/pagedown ровно с этими клавишами (common/00keymap.rpy).
    # Viewport обрабатывает их без проверки фокуса, поэтому зум и постраничная
    # прокрутка полотна дрались за одно нажатие: граф шире экрана уже на пяти
    # узлах, и клавиатурная прокрутка нужнее, чем второй способ менять масштаб
    # (кнопка масштаба есть в шапке).
    key "K_MINUS" action SetScreenVariable(
        "zoom_step", max(0, zoom_step - 1))
    key "K_KP_MINUS" action SetScreenVariable(
        "zoom_step", max(0, zoom_step - 1))
    key "K_EQUALS" action SetScreenVariable(
        "zoom_step", min(len(VN_FLOW_ZOOMS) - 1, zoom_step + 1))
    key "K_KP_PLUS" action SetScreenVariable(
        "zoom_step", min(len(VN_FLOW_ZOOMS) - 1, zoom_step + 1))


# Уменьшение полотна от левого верхнего угла: без якорей zoom тянет картинку
# от центра и граф уезжает из вьюпорта.
transform zoom_canvas(z=1.0):
    zoom z
    anchor (0.0, 0.0)
    pos (0, 0)


# ── Узел графа ───────────────────────────────────────────────────────────────
# Пройденный: заголовок сцены (или её id, если заголовок не объявлен) и пометка
# концовки. Непройденный: «???» — видно, что развилка есть, но не куда ведёт.

screen vn_flow_node(scene_id, xy, focus_default=False, continues=()):
    $ _open = vn_story.revealed(scene_id)
    $ _spec = vn_story.node(scene_id) or {}
    $ _targeted = scene_id in vn_story.targets()
    $ _conflict = bool(_targeted and vn_story.conflicts(scene_id, vn_story.targets()))
    button:
        # Состояние узла — СТИЛЕМ, а не инлайновым background. Беспрефиксное
        # свойство на виджете задаёт все состояния разом, включая hover, и
        # съедает hover_background стиля: фокус на отмеченном или конфликтном
        # узле переставал быть виден вовсе — на карте это единственный способ
        # понять, где ты. Та же ловушка уже задокументирована в choice.rpy и
        # вылечена в vn_nav_button и vn_seg_button; здесь она вернулась в худшем
        # виде — свойством прямо на виджете, а не в дочернем стиле.
        style ("vn_flow_node_conflict" if _conflict
               else ("vn_flow_node_target" if _targeted else "vn_flow_node"))
        xpos xy[0] + VN_FLOW_PAD
        ypos xy[1] + VN_FLOW_PAD
        action Show("story_node_menu", scene_id=scene_id)
        default_focus (gui.focus_content if focus_default else 0)
        fixed:
            if _open:
                $ _thumb = vn_story.thumb(scene_id)
                if _thumb:
                    add _thumb fit "cover" xysize (VN_FLOW_NODE_W, VN_FLOW_NODE_H)
                    add Solid("#0a0a0cd9") xysize (VN_FLOW_NODE_W, 28) yalign 1.0
                text vn_story.display_title(scene_id):
                    style "vn_flow_node_text"
                    xsize VN_FLOW_NODE_W - 2 * gui.sp_s
            else:
                text "???" style "vn_flow_node_locked"
            # «Финал» — только у ПРОЙДЕННОГО узла. Метка стояла вне тумана войны,
            # и карта заранее говорила, какая из закрытых ветвей кончается
            # концовкой: в ch71 это 4 подписи «Финал» на 7 узлов, ещё не
            # открытых. Для скрытой концовки (ch73 s050 — секретная) это прямая
            # выдача того, что игрок должен найти. Структура развилки видна и без
            # метки — узел без исходящих линий и так лист графа.
            if _open and _spec.get("ending"):
                text vn_loc.t("ui.chart.ending") style "vn_flow_badge"
            # Выход в другую главу: целевого узла на этой карте нет, рисовать
            # ребро некуда, и раньше оно молча исчезало — узел читался тупиком.
            # Символ, а не подпись: у «★» ниже своей строки тоже нет. Словесная
            # метка потребовала бы строки в трёх языках сразу (de/en/pseudo) —
            # это решение владельца, а не молчаливая правка.
            if scene_id in continues:
                text "→" style "vn_flow_badge" xalign 1.0 yalign 1.0
            if _targeted:
                text "★" style "vn_flow_badge" xalign 1.0


screen vn_flow_cluster(box):
    # Подложка фазы главы: только группировка, геометрия — из раскладки узлов.
    # Полоса на колонку, а не общая рамка (см. vn_story.cluster_boxes), поэтому
    # заголовок несёт только первая — у остальных title_key пуст.
    fixed:
        xpos box["x"] + VN_FLOW_PAD
        ypos box["y"] + VN_FLOW_PAD
        xysize (box["w"], box["h"])
        add Solid(gui.panel_bg_deep)
        if box["title_key"]:
            text vn_loc.t(box["title_key"]) style "vn_flow_cluster_text"


# ── План walkthrough ─────────────────────────────────────────────────────────

screen vn_flow_plan():
    $ _runs = vn_story.plan()
    if _runs:
        vbox:
            spacing gui.sp_xs
            if len(_runs) == 1:
                text vn_loc.t("ui.chart.plan_one").replace(
                    "[n]", str(len(_runs[0]))) style "vn_flow_plan_text"
            else:
                # Несовместимые цели — не отказ, а план на несколько заходов:
                # игрок видит, что именно и в каком порядке достижимо.
                text vn_loc.t("ui.chart.plan_many").replace(
                    "[n]", str(len(_runs))) style "vn_flow_plan_text"
            for _i, _run in enumerate(_runs):
                text "%d) %s" % (_i + 1, ", ".join(vn_story.display_title(s) for s in _run)):
                    style "vn_flow_plan_run"
            textbutton vn_loc.t("ui.chart.clear_targets"):
                style "vn_gal_tab"
                action Function(vn_story.clear_targets)


# ── Действия над узлом ───────────────────────────────────────────────────────

screen story_node_menu(scene_id):
    modal True
    zorder 70
    $ _targeted = scene_id in vn_story.targets()
    $ _blockers = vn_story.conflicts(scene_id, vn_story.targets())
    # Каркас модалки — общий (components.rpy: vn_modal_dialog): затемнение, рамка,
    # отмена по B/Esc. Своей копии здесь быть не должно, и дело не в вкусе: этот
    # экран как раз держал вторую копию каркаса со своими стилями vn_modal /
    # vn_modal_title / vn_modal_text, которых в проекте нет ни одного объявления.
    # Ren'Py выводит родителя по подчёркиванию, но ТОЛЬКО если родитель существует;
    # стиля `modal` нет ни у нас, ни в SDK, поэтому build_style бросал
    # «Exception: Style 'vn_modal' does not exist» — клик по узлу карты роняли игру.
    # modal/zorder при use не наследуются — они объявлены выше, как требует каркас.
    use vn_modal_dialog(Hide("story_node_menu")):
        vbox:
            spacing gui.sp_m
            text vn_story.display_title(scene_id):
                style "vn_group"
                xalign 0.5
            if _blockers and not _targeted:
                text vn_loc.t("ui.chart.conflict_with").replace(
                    "[list]", ", ".join(vn_story.display_title(s) for s in _blockers)):
                    style "vn_dialog_text"
            vbox:
                xalign 0.5
                spacing gui.sp_m
                if vn_story.can_replay(scene_id):
                    for _i, _state in enumerate(vn_story.preconds(scene_id)):
                        use vn_button(vn_story.precond_label(scene_id, _i),
                                      [Hide("story_node_menu"),
                                       Function(vn_story.start_replay, scene_id, _i)],
                                      kind="secondary")
                use vn_button(vn_loc.t("ui.chart.target_remove" if _targeted
                                       else "ui.chart.target_add"),
                              [Function(vn_story.toggle_target, scene_id),
                               Hide("story_node_menu")],
                              kind="secondary")
                # Безопасная кнопка — ей же первый A с пада (каркас этого не делает).
                use vn_button(vn_loc.t("ui.common.back"), Hide("story_node_menu"),
                              kind="primary", focus_default=True)


# Размер карточки — литералом: см. комментарий у VN_FLOW_NODE_W выше.
style vn_flow_node:
    xysize (232, 130)
    padding (0, 0)
    background vn_frame_slot
    hover_background vn_frame_choice_hover

# Состояния узла — наследники, и у каждого СВОЙ hover_background: беспрефиксный
# background наследника задаёт все состояния разом и без этой строки съел бы
# hover родителя (см. choice_button_chosen — там же и объяснение).
style vn_flow_node_target is vn_flow_node:
    background vn_frame_chip_active
    hover_background vn_frame_choice_hover

# Конфликтная цель — своя рамка: игрок обязан видеть, что комбинация невозможна,
# ДО того как начнёт её добиваться.
style vn_flow_node_conflict is vn_flow_node:
    background vn_frame_choice_chosen
    hover_background vn_frame_choice_hover

style vn_flow_node_text:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.text_color
    outlines [(2, "#000000b3", 0, 1)]
    xpos gui.sp_s
    yalign 1.0
    yoffset -gui.sp_xs

style vn_flow_node_locked:
    font gui.interface_semibold_font
    size gui.text_size
    color gui.panel_border2
    align (0.5, 0.45)

style vn_flow_badge:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    color gui.accent_color
    xpos gui.sp_s
    ypos gui.sp_xs

style vn_flow_percent:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.accent_color

style vn_flow_cluster_text:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.faint_color
    xpos gui.sp_m
    ypos gui.sp_xs

style vn_flow_plan_text:
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.text_color

style vn_flow_plan_run:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.faint_color
