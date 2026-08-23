# Тестовая сцена qa_flow (ADR-0021).

label ch70_s040__body:
    "T1: ветки сошлись — узел слияния." id ch70_s040_0001
    if ch70.path == "left":
        "Пришли слева." id ch70_s040_0002

    $ vn_menu = "ch70_s040_m001"
    menu:
        "Ускориться":
            $ ch70.pace = "fast"
            return "fast"
        "Идти медленно":
            $ ch70.pace = "slow"
            return "slow"
