# Ввод с геймпада (controller-first, аудит ui.md §5-6): ЕДИНСТВЕННОЕ место
# дополнений config.pad_bindings — правки раскладки пада ищутся здесь, а не
# по экранам. Дефолтная раскладка движка (00keymap.rpy) НЕ переопределяется:
# занятые кнопки (A/B/X/Y, LB/LT=rollback, RB=rollforward, RT=подтверждение,
# Start/Guide=game_menu) сохраняют штатные роли — только дополняем свободное.
#
# Что добавляется и почему:
# - skip/auto на клики стиков (L3/R3): единственные незанятые кнопки пада.
#   Вместе с keyboard_focus False у quick menu (quick_menu.rpy) это закрывает
#   P0 «фокус-ловушку»: quick menu уходит из dpad-пути, а его функции
#   получают прямые пад-кнопки. Обработчики движковые (_default_keymap):
#   toggle_skip/toggle_afm сами no-op'ятся в меню-контекстах.
# - LB/RB дополнительно шлют viewport_pageup/pagedown: у движка НЕТ пад-биндинга
#   листания (только PageUp/Down клавиатуры), и длинные списки (history,
#   галерея, языки) на паде было не пролистать. В игровом контексте события
#   безвредны: rollback/rollforward перехватываются раньше (underlay), а
#   pagekeys-вьюпортов там нет.

init python:
    config.pad_bindings["pad_leftstick_press"] = ["toggle_skip"]
    config.pad_bindings["pad_rightstick_press"] = ["toggle_afm"]

    for _vn_pad_ev, _vn_pad_fn in (
            ("pad_leftshoulder_press", "viewport_pageup"),
            ("repeat_pad_leftshoulder_press", "viewport_pageup"),
            ("pad_rightshoulder_press", "viewport_pagedown"),
            ("repeat_pad_rightshoulder_press", "viewport_pagedown")):
        if _vn_pad_fn not in config.pad_bindings[_vn_pad_ev]:
            config.pad_bindings[_vn_pad_ev].append(_vn_pad_fn)
