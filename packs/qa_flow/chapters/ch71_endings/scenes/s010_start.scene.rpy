# Тестовая сцена qa_flow (ADR-0021).

label ch71_s010__body:
    "T2: первая развилка — доверие." id ch71_s010_0001

    $ vn_menu = "ch71_s010_m001"
    menu:
        "Довериться":
            $ ch71.trust = True
            return "trust"
        "Сомневаться":
            $ ch71.trust = False
            return "doubt"
