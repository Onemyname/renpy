# Тестовая сцена qa_flow (ADR-0021).

label ch70_s010__body:
    "T1: развилка первого ромба." id ch70_s010_0001

    $ vn_menu = "ch70_s010_m001"
    menu:
        "Пойти налево":
            $ ch70.path = "left"
            return "left"
        "Пойти направо":
            $ ch70.path = "right"
            return "right"
