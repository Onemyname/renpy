# Тестовая сцена qa_flow (ADR-0021).

label ch73_s030__body:
    "T4: развилка концовок." id ch73_s030_0001

    $ vn_menu = "ch73_s030_m001"
    menu:
        "Уйти домой":
            return "normal"
        "Вернуться к находке":
            return "secret"
