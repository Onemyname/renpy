# Тестовая сцена qa_flow (ADR-0021).

label ch71_s020__body:
    "T2: вторая развилка на ветке доверия." id ch71_s020_0001

    $ vn_menu = "ch71_s020_m001"
    menu:
        "Рискнуть":
            $ ch71.bold = True
            return "bold"
        "Не рисковать":
            $ ch71.bold = False
            return "careful"
