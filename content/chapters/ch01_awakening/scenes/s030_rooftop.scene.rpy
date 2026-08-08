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

    "КОНЕЦ ДЕМО-ГЛАВЫ" id ch01_s030_0005
    return
