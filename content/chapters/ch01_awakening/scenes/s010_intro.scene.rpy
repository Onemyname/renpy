# Метки — только ch01_s010__body и ch01_s010__<branch> (C2, naming.md).
# Переходы между сценами — return "<exit_id>"; цели в exits: scene.yaml.

label ch01_s010__body:
    "Первый учебный день. Звонок уже прозвенел, а ты всё ещё стоишь у ворот."

    menu:
        "Подойти к воротам":
            $ ch01.met_mira = True
            "У ворот кто-то есть."
            return "gate"
        "Подняться сразу на крышу":
            return "roof"
