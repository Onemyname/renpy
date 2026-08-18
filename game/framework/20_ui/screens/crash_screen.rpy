# Брендированный экран краха: движок сам подхватывает пользовательский
# screen _exception (renpy/display/error.py: has_screen("_exception")).
# Отчёт к этому моменту уже записан (00_core/070_crash.rpy).
#
# Экран обязан выживать при крашах init-фазы: никаких gui.*-зависимостей,
# строки — через защищённый _vn_ct (fallback на исходник, если локализация
# ещё/уже не жива). Действия rollback/ignore/reload передаёт движок — их
# семантика штатная и безопасная в контексте ошибки.
#
# ПОЭТОМУ здесь легальны числовые литералы (кегли, приоритеты фокуса, геометрия)
# — единственное такое место в 20_ui. Токены gui.* объявляются на init -3/-2
# (scale.rpy -> gui.rpy): падение любого init'а до них оставит gui без
# половины атрибутов, и экран краха упал бы сам, не показав игроку ничего.
# Кегли держатся на уровне ВЕРХНЕГО профиля масштаба («крупный» ×1.4,
# 20_ui/scale.rpy: интерфейс 29, кнопочный 24, мелкий 21 — они и проходят порог
# читаемости Deck/ТВ). Экран редкий и короткий: дешевле всегда рисовать его
# читаемым с дивана, чем читать gui.ui_scale и зависеть от него.

init python:
    def _vn_ct(key, fallback):
        """vn_loc.t с жёстким fallback: экран краша не имеет права упасть сам."""
        try:
            value = vn_loc.t(key)
            return fallback if value == key else value
        except Exception:
            return fallback

# Кнопки экрана краха стилизуются здесь же и на литералах: style button_text из
# components.rpy читает gui.* и при падении init'а мог не примениться, а
# движковый дефолт (button_text is default, 00style.rpy) не различает
# idle/hover — фокус стал бы невидимым, и «куда я нажимаю» с пада не понять.
style vn_crash_button_text is default:
    size 29
    color "#b7aec4"
    hover_color "#ffffff"

screen _exception(traceback_exception, rollback_action=None, reload_action=None,
                  ignore_action=None):
    modal True
    zorder 2000
    add Solid("#16121a")

    frame:
        align (0.5, 0.45)
        xmaximum 1200
        xfill True
        background Solid("#241d2b")
        padding (40, 36)

        vbox:
            spacing 20
            text _vn_ct("ui.crash.title", "Что-то пошло не так"):
                size 40
                color "#ffffff"
            text _vn_ct("ui.crash.body",
                        "Игра столкнулась с ошибкой. Прогресс до последнего "
                        "сохранения не пострадал."):
                size 24
                color "#d8d2e0"
            $ _report = getattr(renpy.store, "_vn_last_crash_report", None)
            if _report:
                text _vn_ct("ui.crash.report", "Отчёт сохранён:") + "\n" + _report:
                    size 21
                    color "#8f86a0"

            if config.developer:
                # Только для разработчика: сам трейсбек на экране. arrowkeys
                # делает viewport фокусируемым — dpad/стрелки прокручивают его
                # сами (без этого трейсбек с пада не листается вообще), а на
                # краях viewport событие не съедает (viewport.py:503-522) и
                # фокус штатно уходит к кнопкам — фокус-ловушки нет. pagekeys
                # подхватывает LB/RB (пад-биндинги viewport_page* — input.rpy).
                viewport:
                    ymaximum 340
                    mousewheel True
                    arrowkeys True
                    pagekeys True
                    # Полоса прокрутки — ЛИТЕРАЛАМИ, и это не косметика:
                    # картинок полосы в проекте нет (ADR-0009: фоны генерируются),
                    # а vn_scroll_props из components.rpy считает свои Solid'ы от
                    # gui.* — этому экрану они запрещены. Без явных base_bar/thumb
                    # движковый дефолт полосы пуст, и side-раскладка scrollbars
                    # отдаёт вьюпорту нулевую площадь: трейсбек не рисовался
                    # ВООБЩЕ (проверено автопилотным прогоном).
                    scrollbars "vertical"
                    vscrollbar_base_bar Solid("#1b1620")
                    vscrollbar_thumb Solid("#5a5168")
                    vscrollbar_xsize 8
                    vscrollbar_unscrollable "hide"
                    text str(traceback_exception) size 20 color "#c0b8cc"

            hbox:
                spacing 28
                # Первый фокус: слепой A с пада обязан попадать в безопасное
                # действие, а не в «выйти». Движок отдаёт фокус НАИБОЛЬШЕМУ
                # default_focus (focus.py), поэтому приоритет — число:
                #   2 — откат: движок возвращает состояние к точке ДО упавшего
                #       стейтмента, игра остаётся согласованной;
                #   1 — «продолжить»: едем дальше с уже испорченным состоянием,
                #       годится только когда откат недоступен (движок не передал
                #       rollback_action) — тогда единица становится максимумом;
                #   0 (нет свойства) — «выйти» и dev-only Reload: потеря сессии
                #       не должна случаться от одного нажатия наугад.
                if rollback_action:
                    textbutton _vn_ct("ui.crash.rollback", "Откатиться назад"):
                        action rollback_action
                        default_focus 2
                        text_style "vn_crash_button_text"
                if ignore_action:
                    textbutton _vn_ct("ui.crash.ignore", "Попробовать продолжить"):
                        action ignore_action
                        default_focus 1
                        text_style "vn_crash_button_text"
                if reload_action and config.developer:
                    textbutton "Reload":
                        action reload_action
                        text_style "vn_crash_button_text"
                textbutton _vn_ct("ui.crash.quit", "Закрыть игру"):
                    action Quit(confirm=False)
                    text_style "vn_crash_button_text"
