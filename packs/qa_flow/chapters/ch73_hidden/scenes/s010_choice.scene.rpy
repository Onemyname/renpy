# Тестовая сцена qa_flow (ADR-0021).

label ch73_s010__body:
    "T4: свернуть в переулок или пройти мимо." id ch73_s010_0001

    $ vn_menu = "ch73_s010_m001"
    menu:
        "Свернуть в переулок":
            return "explore"
        "Пройти мимо":
            return "leave"
