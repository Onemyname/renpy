# Кастомный screen choice (G8/C1): контракт фазы 0 сохранён без изменений —
# сигнатура, vn_loc.choice_text(vn_menu, idx, i.caption), таймер QA-автопилота.
# Новое — только оформление на токенах gui.*.

init offset = 0

screen choice(items):
    style_prefix "choice"
    # Мягкое затемнение сцены на время выбора (поверх яркого видео)
    add Solid("#00000061")
    vbox:
        for idx, i in enumerate(items):
            textbutton vn_loc.choice_text(vn_menu, idx, i.caption) action i.action
    # QA-автопилот (vn test smoke): авто-выбор пункта; вне автопилота — no-op.
    if vn_qa.autopilot_active():
        timer 1.0 action Function(vn_qa.autopilot_choose, items) repeat True


style choice_vbox is vbox:
    xalign 0.5
    ypos 296
    spacing gui.sp_m

style choice_button:
    xsize 820
    padding (gui.sp_l + 2, gui.sp_m + 2)
    # Скруглённые фоны с тенью — генерируемые панели (ADR-0009), а не Solid:
    # прямые углы были главным «допотопным» признаком. Правка вида — в
    # content/ui/panels.yaml, вёрстка знает только имя.
    background vn_frame_choice
    hover_background vn_frame_choice_hover
    insensitive_background vn_frame_choice_chosen

style choice_button_text:
    xalign 0.5
    text_align 0.5
    font gui.interface_text_font
    size gui.choice_text_size
    color "#e4e4e7"
    hover_color gui.selected_color
    insensitive_color gui.insensitive_color
