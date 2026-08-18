# «Контент недоступен»: объяснение причины + выбор действия (вызывается из
# label vn_scene_unavailable, 00_core/030_flow.rpy). Модальный, по образцу confirm.
#
# Возврат только через Return("menu") -> full_restart в вызывающем label;
# «Загрузить сохранение» открывает штатное меню загрузки поверх (успешная
# загрузка сама заменяет контекст), «Выйти» завершает игру без подтверждения —
# подтверждать нечего, прогресс до этой точки уже в сейвах.

# Каркас vn_modal_dialog (components.rpy): B/Esc = безопасное «В главное меню»
# (тот же Return("menu")); ему же — default focus для первого A с пада.
screen vn_content_unavailable(reason=None):
    modal True
    zorder 200
    # QA-автопилот: прогон не должен зависнуть на модалке (смоук уже зафиксировал
    # FAIL в vn_scene_unavailable до показа экрана; сюда попадает только скриншот
    # вёрстки через VN_AUTOPILOT_SCREENS).
    if vn_qa.autopilot_active():
        timer 0.8 action Return("menu") repeat True
    $ _msg_key = {
        "draft_todo": "ui.flow.unavailable_draft",
        "missing_content": "ui.flow.unavailable_missing",
    }.get(reason, "ui.flow.unavailable_unknown")
    use vn_modal_dialog(Return("menu")):
        vbox:
            spacing gui.sp_l
            text vn_loc.t("ui.flow.unavailable_title").upper() style "vn_group" xalign 0.5
            text vn_loc.t(_msg_key) style "vn_dialog_text"
            vbox:
                xalign 0.5
                spacing gui.sp_m
                use vn_button(vn_loc.t("ui.flow.act_main_menu"), Return("menu"), kind="primary", focus_default=True)
                use vn_button(vn_loc.t("ui.flow.act_load"), ShowMenu("load"), kind="secondary")
                use vn_button(vn_loc.t("ui.flow.act_quit"), Quit(confirm=False), kind="secondary")
