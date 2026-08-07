# Кастомный screen choice (G8/C1): перевод пунктов меню идёт НЕ через translate strings
# (коллизии «Да»/«Нет» между сценами неизбежны), а по choice-id из реестра меню
# (lookup vn_loc.choice_text — framework/00_core/040_localization.rpy).
# Идентичность меню держит переменная vn_menu (default — во framework/00_core/020_state.rpy),
# которую vn loc keys вставляет в авторский scene.rpy перед каждым menu-стейтментом.

screen choice(items):
    style_prefix "choice"
    vbox:
        for idx, i in enumerate(items):
            textbutton vn_loc.choice_text(vn_menu, idx, i.caption) action i.action
    # QA-автопилот (vn test smoke): авто-выбор пункта; вне автопилота — no-op.
    # Побочных эффектов в screen-выражениях нет: выбор делает Function в момент тика.
    if vn_qa.autopilot_active():
        timer 1.0 action Function(vn_qa.autopilot_choose, items) repeat True


style choice_vbox is vbox:
    xalign 0.5
    ypos 405
    spacing 33

style choice_button:
    xsize 1180
    background Solid("#00000099")
    hover_background Solid("#000000cc")
    padding (30, 15)

style choice_button_text:
    xalign 0.5
    text_align 0.5
    color "#cccccc"
    hover_color "#ffffff"
    insensitive_color "#8888887f"
