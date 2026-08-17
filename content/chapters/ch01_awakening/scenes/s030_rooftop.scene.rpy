label ch01_s030__body:
    "Крыша. Ветер. Город до горизонта." id ch01_s030_0001

    if ch01.met_mira:
        show mira a casual smile at center with dissolve
        mira "А ты быстрее, чем кажешься." id ch01_s030_0002
        "Она смеётся. Кажется, этот год будет интересным." id ch01_s030_0003
    else:
        "Ты здесь один. Тихо. Слишком тихо." id ch01_s030_0004

    # CG-кадр: показ сам засчитывает его в галерею через штатный
    # persistent._seen_images (ADR-0010) — ручного unlock-кода в сценах нет.
    scene cg ch01 rooftop_day with dissolve
    "Город лежит внизу, будто выдохнул." id ch01_s030_0006

    # Послойный шот (shots@1, ADR-0013): env + слой Миры. Наряд берёт из
    # g.mira_outfit (атрибут mira_auto по умолчанию) — смена переменной
    # перекомпоновывает кадр без повторного show.
    scene shot_ch01_s030 sunset with dissolve
    "Закат раскрашивает крышу заново." id ch01_s030_0007
    $ g.mira_outfit = "casual"
    "Мира успела переодеться — кадр это уже знает." id ch01_s030_0008

    "КОНЕЦ ДЕМО-ГЛАВЫ" id ch01_s030_0005
    return
