# Чит-меню QA (раздел 7): прыжок в любую сцену из Scene Registry (VN_SCENES).
# Только dev: файл вырезается из release-профиля (фаза packaging), плюс гейт
# config.developer в рантайме. Горячая клавиша в игре: Shift+J.

init python:
    if config.developer:
        config.overlay_screens.append("vn_debug_hotkeys")


screen vn_debug_hotkeys():
    key "shift_K_j" action ShowMenu("vn_debug_jump")


screen vn_debug_jump():
    tag menu
    add Solid("#101018")
    vbox:
        xpos 60
        ypos 60
        spacing 20
        label _("QA: прыжок в сцену")
        text _("Состояние глав НЕ выставляется — переменные останутся текущими") size 24 color gui.idle_color
        vpgrid:
            cols 4
            allow_underfull True
            spacing 12
            mousewheel True
            ymaximum 800
            for sc in getattr(store, "VN_SCENES", ()):
                textbutton "[sc[id]]":
                    action Function(renpy.jump_out_of_context, sc["label"])
        textbutton _("Назад") action Return()
