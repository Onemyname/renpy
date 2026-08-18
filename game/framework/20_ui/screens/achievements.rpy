# Достижения (achievements@1): экран прогресса игрока.
#
# Экран НЕ знает ни одной ачивки: список, названия, описания и «скрытость» он
# спрашивает у store vn_ach (данные из generated/registry/achievements.gen.rpy),
# ровно как галерея спрашивает vn_gal. Добавление ачивки в
# content/achievements/*.yaml не требует правок этого файла.
#
# Спойлеры — главное требование к вёрстке: у скрытой (hidden) и ещё не
# полученной ачивки название рисуется как «???», а описание подменяется общей
# строкой. Настоящий текст в дерево отображения НЕ попадает вовсе — раскрыть его
# нечем (ни выделением, ни скриншотом, ни автопилотом QA).
#
# Невидимые ачивки (NSFW в SFW-флейворе, чужой пак — vn_ach.visible(), G9) не
# показываются и не входят в знаменатель счётчика: игрок не должен пересчитывать
# «а сколько их всего на самом деле» и видеть намёк на непроданный контент.
#
# Локализация: подписи — только ключи (vn_loc.t и *_key реестра). Новый язык не
# требует правок этого файла.

init offset = 0


screen achievements():
    tag menu

    $ _ids = vn_ach.visible_ids()
    # Имена _done/_total — часть контракта со строкой ui.ach.progress: она
    # интерполирует их сама (переименование ловит тест test_achievements).
    $ _done, _total = vn_ach.progress()

    use vn_game_menu(vn_loc.t("ui.nav.achievements")):
        vbox:
            spacing gui.sp_l
            text vn_loc.t("ui.ach.progress") style "vn_counter"

            if not _ids:
                # Флейвор/владение могут скрыть все ачивки до единой — пустой
                # экран без объяснения читался бы как поломка.
                text vn_loc.t("ui.ach.empty") style "vn_empty_note"
            else:
                # Скролл-пресет vn_scroll_props (components.rpy) + arrowkeys:
                # карточка ачивки НИЧЕГО не делает по нажатию (просмотрщика у
                # достижений нет), поэтому фокусируемых детей в сетке нет — и
                # докручивать нечего. Фокус берёт сам вьюпорт (dpad/стрелки
                # скроллят, LB/RB листают страницами), тот же приём, что в
                # history.rpy. Приоритет gui.focus_content: контент перебивает
                # рельсу, иначе слепой A уводил бы из достижений в «Сохранение».
                vpgrid id "vp_achievements":
                    properties vn_scroll_props
                    arrowkeys True
                    default_focus gui.focus_content
                    cols 2
                    allow_underfull True
                    spacing gui.sp_m
                    ysize gui.scroll_height
                    for _aid in _ids:
                        use vn_ach_card(_aid, VN_ACHIEVEMENTS[_aid])


# ── Карточка достижения ───────────────────────────────────────────────────────
# Полученная читается с одного взгляда: название акцентом и без строки
# состояния. Не полученная — приглушённое название плюс «Не получено».

screen vn_ach_card(ach_id, spec):
    $ _got = vn_ach.has(ach_id)
    $ _spoiler = spec["hidden"] and not _got
    # Единственная точка, где решается «показать настоящий текст или заглушку»:
    # ниже в вёрстке ключей реестра нет, поэтому спойлер невозможен по построению.
    # desc_key схемой не обязателен — пустой ключ даёт пустую строку, и абзац с
    # описанием просто не рисуется.
    $ _name = "???" if _spoiler else vn_loc.t(spec["name_key"])
    $ _desc = vn_loc.t("ui.ach.hidden" if _spoiler else spec["desc_key"] or "")
    frame:
        style "vn_ach_card"
        vbox:
            spacing gui.sp_xs
            text _name style ("vn_ach_name" if _got else "vn_ach_name_locked")
            if _desc:
                text _desc style "vn_ach_desc"
            # Прогрессивная ачивка (goal): вместо «не получено» — сколько
            # осталось. У скрытой прогресс не показывается вовсе: он выдал бы,
            # ЧТО именно надо собрать, то есть тот же спойлер, что и описание.
            $ _goal = None if _spoiler else vn_ach.goal_of(ach_id)
            if _goal and not _got:
                $ _done = vn_ach.counter(ach_id)
                $ _total = _goal["total"]
                vbox:
                    spacing gui.sp_xs
                    bar:
                        value _done
                        range _total
                        style "vn_ach_bar"
                    text vn_loc.t("ui.ach.progress_of").replace("[done]", str(_done)).replace("[total]", str(_total)) style "vn_ach_state"
            elif not _got:
                text vn_loc.t("ui.ach.locked") style "vn_ach_state"


style vn_ach_card:
    xysize (gui.ach_card_width, gui.ach_card_height)
    background vn_frame_slot
    padding (gui.sp_m, gui.sp_m)

style vn_ach_bar:
    # Полоса прогресса ачивки: тонкая, тех же токенов, что слайдеры настроек —
    # отдельной графики не заводим (ADR-0009: панели рисует конвейер, полосы —
    # Solid из палитры).
    ysize gui.sp_s
    xsize gui.ach_card_width - 2 * gui.sp_m
    left_bar Solid(gui.accent_color)
    right_bar Solid(gui.panel_bg_hover)
    thumb None
    thumb_shadow None

style vn_ach_name:
    font gui.interface_semibold_font
    size gui.interface_text_size
    color gui.accent_color

style vn_ach_name_locked is vn_ach_name:
    color gui.muted_color

style vn_ach_desc:
    font gui.interface_text_font
    size gui.small_text_size
    color gui.sub_color
    # Перенос внутри карточки: длинное описание (перевод бывает вдвое длиннее
    # исходника) обязано ложиться в две строки, а не уезжать за край панели.
    xmaximum gui.ach_card_width - 2 * gui.sp_m

style vn_ach_state:
    font gui.interface_semibold_font
    size gui.tiny_text_size
    color gui.faint_color
    kerning 1.2
