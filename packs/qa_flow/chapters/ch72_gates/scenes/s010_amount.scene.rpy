# Тестовая сцена qa_flow (ADR-0021).

label ch72_s010__body:
    "T3: сколько перевести." id ch72_s010_0001

    $ vn_menu = "ch72_s010_m001"
    menu:
        "Ничего не переводить":
            $ ch72.donation = 0
            return "done"
        "Перевести 1000":
            $ ch72.donation = 1000
            return "done"
        "Перевести 5000":
            $ ch72.donation = 5000
            return "done"
