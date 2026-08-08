# Брендированный экран краха: движок сам подхватывает пользовательский
# screen _exception (renpy/display/error.py: has_screen("_exception")).
# Отчёт к этому моменту уже записан (00_core/070_crash.rpy).
#
# Экран обязан выживать при крашах init-фазы: никаких gui.*-зависимостей,
# строки — через защищённый _vn_ct (fallback на исходник, если локализация
# ещё/уже не жива). Действия rollback/ignore/reload передаёт движок — их
# семантика штатная и безопасная в контексте ошибки.

init python:
    def _vn_ct(key, fallback):
        """vn_loc.t с жёстким fallback: экран краша не имеет права упасть сам."""
        try:
            value = vn_loc.t(key)
            return fallback if value == key else value
        except Exception:
            return fallback

screen _exception(traceback_exception, rollback_action=None, reload_action=None,
                  ignore_action=None):
    modal True
    zorder 2000
    add Solid("#16121a")

    frame:
        align (0.5, 0.45)
        xmaximum 960
        xfill True
        background Solid("#241d2b")
        padding (32, 28)

        vbox:
            spacing 14
            text _vn_ct("ui.crash.title", "Что-то пошло не так"):
                size 30
                color "#ffffff"
            text _vn_ct("ui.crash.body",
                        "Игра столкнулась с ошибкой. Прогресс до последнего "
                        "сохранения не пострадал."):
                size 17
                color "#d8d2e0"
            $ _report = getattr(renpy.store, "_vn_last_crash_report", None)
            if _report:
                text _vn_ct("ui.crash.report", "Отчёт сохранён:") + "\n" + _report:
                    size 13
                    color "#8f86a0"

            if config.developer:
                # Только для разработчика: сам трейсбек на экране.
                viewport:
                    ymaximum 260
                    scrollbars "vertical"
                    mousewheel True
                    text str(traceback_exception) size 12 color "#c0b8cc"

            hbox:
                spacing 18
                if rollback_action:
                    textbutton _vn_ct("ui.crash.rollback", "Откатиться назад"):
                        action rollback_action
                if ignore_action:
                    textbutton _vn_ct("ui.crash.ignore", "Попробовать продолжить"):
                        action ignore_action
                if reload_action and config.developer:
                    textbutton "Reload" action reload_action
                textbutton _vn_ct("ui.crash.quit", "Закрыть игру"):
                    action Quit(confirm=False)
