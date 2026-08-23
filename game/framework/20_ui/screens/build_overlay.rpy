# Вотермарка сборки (ADR-0006): включается ТОЛЬКО у флейворов с watermark: true
# (project.yaml, обычно patron). Полупрозрачный build-id в углу: утечка раннего
# билда трассируется до конкретной сборки/токена. Никакого рантайм-трекинга —
# статичная подпись через штатный overlay-механизм движка.

screen vn_build_overlay():
    zorder 1090
    text vn_build.label():
        size 12
        color "#ffffff59"
        outlines [(1, "#00000040", 0, 0)]
        xalign 0.995
        yalign 0.995
        # overscan_pad (scale.rpy): вотермарка в углу — первое, что срезает ТВ
        xoffset -gui.overscan_pad
        yoffset -gui.overscan_pad

# Плашка бета-ветки Steam: имя ветки приходит из платформы (vn_platform.beta_branch),
# то есть появляется САМА, когда игрок запустил бета-версию из клиента. Отдельный
# экран, а не строчка в вотермарке: вотермарка включается только у patron-флейвора,
# а знать «это бета» тестеру нужно в любой сборке (43-steam-qa §2/§5).
screen vn_beta_overlay():
    zorder 1091
    # Экран переоценивается на каждой интеракции и в предикции, поэтому спрашивать
    # платформу отсюда можно ровно потому, что beta_branch() кэширует ответ на
    # процесс (035_platform.rpy) — в Steam этот вызов не ходит.
    $ _branch = vn_platform.beta_branch()
    if _branch:
        text ("BETA: " + _branch):
            size 12
            color "#ffcc0099"
            outlines [(1, "#00000059", 0, 0)]
            xalign 0.005
            yalign 0.995
            xoffset gui.overscan_pad
            yoffset -gui.overscan_pad


init python:
    if vn_build.watermark:
        config.overlay_screens.append("vn_build_overlay")
    # Плашка беты вешается всегда: экран сам ничего не рисует вне бета-ветки, и
    # держать для этого второй гейт (по платформе) значило бы дублировать условие.
    config.overlay_screens.append("vn_beta_overlay")
