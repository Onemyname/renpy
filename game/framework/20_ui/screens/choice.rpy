# Кастомный screen choice (G8/C1): перевод пунктов меню идёт НЕ через translate strings
# (коллизии «Да»/«Нет» между сценами неизбежны), а по choice-id из реестра меню.
# Идентичность меню держит переменная vn_menu (default — во framework/00_core/020_state.rpy),
# которую vn loc keys вставляет в авторский scene.rpy перед каждым menu-стейтментом.

init -999 python in vn_loc:
    from store import renpy

    def _lang():
        return renpy.game.preferences.language

    def choice_text(menu_id, idx, caption):
        """Перевод пункта (menu_id, idx) по VN_MENUS_TL (наполняется tl/<lang>/common.rpy).
        Исходный язык / нет перевода -> авторский caption."""
        tl = getattr(renpy.store, "VN_MENUS_TL", {}).get(_lang())
        if tl and menu_id in tl and idx < len(tl[menu_id]):
            return tl[menu_id][idx]
        return caption

    def t(key):
        """UI/мета-строка по ключу (content/ui/strings.yaml): исходник или перевод."""
        source = getattr(renpy.store, "VN_STRINGS", {}).get(key, key)
        tl = getattr(renpy.store, "VN_STRINGS_TL", {}).get(_lang())
        if tl and key in tl:
            return tl[key]
        return source


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
