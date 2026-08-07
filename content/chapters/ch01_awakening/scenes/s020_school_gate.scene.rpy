label ch01_s020__body:
    show mira a school neutral at center with dissolve
    mira "Ты опять проспал?" id ch01_s020_0001

    $ vn_menu = "ch01_s020_m001"
    menu:
        "Соврать":
            show mira angry
            mira "Ну-ну. Очень убедительно." id ch01_s020_0002
            jump ch01_s020__caught
        "Сказать правду":
            show mira smile
            mira "Хотя бы честно. Пойдём, провожу до крыши." id ch01_s020_0003
            return "roof"

label ch01_s020__caught:
    show mira smile
    mira "Ладно. Беги, звонок уже был." id ch01_s020_0004
    return "roof"
