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
# - A и RT дополнительно шлют input_enter: у движка подтверждение ввода висит
#   ТОЛЬКО на Enter/KP_Enter клавиатуры (00keymap.rpy), и на Deck/ТВ первое же
#   renpy.input стало бы тупиком — экранную клавиатуру движок покажет сам, а
#   «ОК» нажать нечем. Свободных кнопок у пада не осталось (стики заняты выше),
#   поэтому событие уезжает на штатную пару «подтвердить» — ровно ту, где у
#   движка уже живут dismiss/button_select. Конфликта нет: input_enter забирает
#   только ЖИВОЕ поле ввода (behavior.py, Input.event: `if not self.editable:
#   return None`), а экран ввода кнопок не содержит (screen input,
#   core_screens.rpy) — dismiss/button_select там и так некому обработать. На
#   клавиатуре у движка та же схема: K_RETURN — это и dismiss, и input_enter.

init python:
    config.pad_bindings["pad_leftstick_press"] = ["toggle_skip"]
    config.pad_bindings["pad_rightstick_press"] = ["toggle_afm"]

    for _vn_pad_ev, _vn_pad_fn in (
            ("pad_leftshoulder_press", "viewport_pageup"),
            ("repeat_pad_leftshoulder_press", "viewport_pageup"),
            ("pad_rightshoulder_press", "viewport_pagedown"),
            ("repeat_pad_rightshoulder_press", "viewport_pagedown"),
            ("pad_a_press", "input_enter"),
            ("pad_righttrigger_pos", "input_enter")):
        if _vn_pad_fn not in config.pad_bindings[_vn_pad_ev]:
            config.pad_bindings[_vn_pad_ev].append(_vn_pad_fn)
