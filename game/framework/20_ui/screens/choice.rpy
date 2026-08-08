# Кастомный screen choice (G8/C1). Контракты сохранены дословно: сигнатура,
# vn_loc.choice_text(vn_menu, idx, i.caption), таймер QA-автопилота.
#
# Композиция: выбор живёт в нижней диалоговой зоне — стек прижат к низу
# (yanchor 1.0) и растёт ВВЕРХ, лицо/ключевые части персонажа не перекрываются;
# 2–5 вариантов и длинные локализованные строки масштабируются без правок
# (авто-высота рядов, перенос текста).
#
# Фоны — генерируемые панели (ADR-0009): vn_frame_choice / _hover / _chosen.
# Ловушка 2*Borders: hover-панель = Borders(30) → минимум 60px; ряд держит
# min-высоту паддингами (15+15 + строка 25px ≈ 65px). Тени в panels.yaml
# не увеличивать без сверки с ui_frames.gen.rpy.
#
# i.chosen (вариант уже выбирали в прошлом прохождении): приглушённый текст,
# плоский фон _chosen и маленький ромб-маркер — заметно, но не доминирует.
# Условных пунктов меню не существует (запрещены компилятором) — состояния
# insensitive у выбора нет.

init offset = 0

# Маркер «уже выбирали» — ромб из Solid (без бинарных ассетов)
image vn_chosen_mark = Transform(Solid(gui.faint_color), xysize=(9, 9), rotate=45)

# Появление стека: лёгкий подъём с каскадом ~50 мс на пункт
transform vn_choice_in(d=0.0):
    alpha 0.0 yoffset 14
    pause d
    easeout 0.22 alpha 1.0 yoffset 0

screen choice(items):
    style_prefix "choice"
    # Мягкое общее затемнение + плотный scrim снизу: сцена видна, зона решений
    # читается поверх яркого WebM-лупа. Высота scrim следует числу вариантов.
    add Solid("#00000040")
    use vn_scrim(min(720, 280 + 100 * len(items)))
    vbox:
        for idx, i in enumerate(items):
            $ _num = idx + 1
            $ _mark = ("vn_chosen_mark" if i.chosen else Null())
            button:
                style ("choice_button_chosen" if i.chosen else "choice_button")
                at vn_choice_in(idx * 0.05)
                action i.action
                side "l c r":
                    spacing gui.sp_m
                    text "[_num]" style "choice_num"
                    text vn_loc.choice_text(vn_menu, idx, i.caption) style "choice_button_text"
                    add _mark yalign 0.5
            # Горячие клавиши 1–9 — аффорданс клавиатуры/геймпада
            if _num <= 9:
                key ("K_%d" % _num) action i.action
    # QA-автопилот (vn test smoke): авто-выбор пункта; вне автопилота — no-op.
    if vn_qa.autopilot_active():
        timer 1.0 action Function(vn_qa.autopilot_choose, items) repeat True


style choice_vbox is vbox:
    xpos gui.textbox_side_pad
    yanchor 1.0
    ypos 1080 - gui.sp_xl
    xsize gui.choice_width
    spacing gui.sp_m - gui.sp_xs

style choice_button:
    xfill True
    padding (gui.sp_l - 6, gui.sp_m - 1)
    background vn_frame_choice
    hover_background vn_frame_choice_hover

style choice_button_chosen is choice_button:
    background vn_frame_choice_chosen

style choice_num:
    min_width 26
    yalign 0.5
    font gui.interface_semibold_font
    size gui.small_text_size
    color gui.faint_color

style choice_button_text:
    xalign 0.0
    text_align 0.0
    yalign 0.5
    font gui.interface_text_font
    size gui.choice_text_size
    line_spacing gui.sp_xs + 1
    color "#e4e4e7"
    hover_color gui.selected_color
