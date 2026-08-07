label ch01_s020__body:
    show mira a school neutral at center with dissolve
    mira "Ты опять проспал?"

    menu:
        "Соврать":
            show mira angry
            mira "Ну-ну. Очень убедительно."
            jump ch01_s020__caught
        "Сказать правду":
            show mira smile
            mira "Хотя бы честно. Пойдём, провожу до крыши."
            return "roof"

label ch01_s020__caught:
    show mira smile
    mira "Ладно. Беги, звонок уже был."
    return "roof"
