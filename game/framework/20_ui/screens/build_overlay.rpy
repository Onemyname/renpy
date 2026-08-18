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

init python:
    if vn_build.watermark:
        config.overlay_screens.append("vn_build_overlay")
