label ch01_s020__body:
    mira "Ты опять проспал?"

    menu:
        "Соврать":
            mira "Ну-ну. Очень убедительно."
            jump ch01_s020__caught
        "Сказать правду":
            mira "Хотя бы честно. Пойдём, провожу до крыши."
            return "roof"

label ch01_s020__caught:
    mira "Ладно. Беги, звонок уже был."
    return "roof"
