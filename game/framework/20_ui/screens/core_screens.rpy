# Минимальный набор экранов фазы 0: игра запускается, сохраняется и загружается.
# Компонентная библиотека UI и темы из токенов (раздел 7 ARCHITECTURE.md) — фаза 2;
# этот файл сознательно простой и без картинок (Solid-фоны): game/assets ещё не собирается.
#
# Локализация (ADR-0005): в экранах НЕТ строковых литералов — только ключи
# content/ui/strings.yaml через vn_loc.t(key). Смена языка горячая: интеракция
# перезапускается, экраны переоцениваются — включая открытый в этот момент.

init offset = -1

init python:
    # Закрытие окна ОС (X / Alt+F4): движковый путь показывает confirm с
    # английской layout.QUIT-строкой — подменяем на наш локализованный текст.
    # Лямбда, не Action: сообщение обязано вычисляться в момент показа,
    # а не кешироваться на init (иначе смена языка его не тронет).
    config.quit_action = lambda: renpy.run(
        Confirm(vn_loc.t("ui.confirm.quit"), Quit(confirm=False)))

## ── Базовые стили ────────────────────────────────────────────────────────────

style default:
    font gui.text_font
    size gui.text_size
    color gui.text_color

style button_text:
    size gui.interface_text_size
    color gui.idle_color
    hover_color gui.hover_color
    selected_color gui.selected_color
    insensitive_color gui.insensitive_color

style label_text:
    size gui.label_text_size
    color gui.accent_color

style frame:
    background Solid(gui.frame_bg)
    padding (30, 30)

style window:
    xalign 0.5
    yalign 1.0
    xfill True
    ysize 280
    background Solid(gui.textbox_bg)
    padding (240, 30)

style say_label:
    size gui.name_text_size
    color gui.accent_color
    bold True

style say_dialogue:
    xsize 1440

style input_prompt:
    color gui.accent_color


## ── Диалог ───────────────────────────────────────────────────────────────────

screen say(who, what):
    window:
        id "window"
        vbox:
            spacing 8
            if who is not None:
                text who id "who" style "say_label"
            text what id "what" style "say_dialogue"


screen input(prompt):
    window:
        vbox:
            spacing 8
            text prompt style "input_prompt"
            input id "input"


## ── Меню и навигация ─────────────────────────────────────────────────────────

screen navigation():
    vbox:
        xpos 60
        yalign 0.5
        spacing 14
        if main_menu:
            textbutton vn_loc.t("ui.nav.start") action Start()
            if vn_registry.chapters():
                textbutton vn_loc.t("ui.nav.chapters") action ShowMenu("chapter_select")
        else:
            textbutton vn_loc.t("ui.nav.return") action Return()
            textbutton vn_loc.t("ui.nav.save") action ShowMenu("save")
        textbutton vn_loc.t("ui.nav.load") action ShowMenu("load")
        textbutton vn_loc.t("ui.nav.prefs") action ShowMenu("preferences")
        if main_menu:
            # Confirm со СВОИМ текстом: дефолтные Quit(confirm)/MainMenu(confirm)
            # показывают layout.*-строки движка, которых нет в нашем конвейере переводов.
            textbutton vn_loc.t("ui.nav.quit") action Confirm(vn_loc.t("ui.confirm.quit"), Quit(confirm=False))
        else:
            textbutton vn_loc.t("ui.nav.main_menu") action Confirm(vn_loc.t("ui.confirm.main_menu"), MainMenu(confirm=False))


screen main_menu():
    tag menu
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xalign 0.97
        yalign 0.95
        spacing 8
        text "[config.name!t]" size gui.title_text_size color gui.accent_color xalign 1.0
        text vn_loc.t("ui.main.version") size 24 color gui.idle_color xalign 1.0


## ── Сохранение / загрузка ────────────────────────────────────────────────────

screen save():
    tag menu
    use file_menu(vn_loc.t("ui.file.save_title"), True)

screen load():
    tag menu
    use file_menu(vn_loc.t("ui.file.load_title"), False)

screen file_menu(title, is_save):
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xpos 420
        ypos 80
        spacing 24
        label title
        hbox:
            spacing 20
            textbutton vn_loc.t("ui.file.autopage") action FilePage("auto")
            for p in range(1, 4):
                textbutton "[p]" action FilePage(p)
        grid 3 3:
            spacing 20
            for i in range(1, 10):
                # Загрузка в игре теряет прогресс — подтверждаем СВОИМ текстом
                # (движковый confirm у FileLoad — английская layout-строка);
                # confirm_selected: подсветка свежайшего слота — от FileLoad.
                $ _slot_action = FileSave(i) if is_save else (FileLoad(i) if main_menu else Confirm(vn_loc.t("ui.confirm.load"), FileLoad(i, confirm=False), confirm_selected=True))
                button:
                    action _slot_action
                    sensitive (True if is_save else FileLoadable(i))
                    xsize 440
                    ysize 130
                    background Solid("#2a2a36")
                    hover_background Solid("#3a3a4a")
                    vbox:
                        spacing 6
                        text FileTime(i, format=vn_loc.t("ui.file.time_format"), empty=vn_loc.t("ui.file.empty_slot")) size 24
                        text FileSaveName(i) size 22 color gui.idle_color
        textbutton vn_loc.t("ui.common.back") action Return()


## ── Настройки ────────────────────────────────────────────────────────────────

screen preferences():
    tag menu
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xpos 420
        ypos 80
        spacing 30
        label vn_loc.t("ui.prefs.title")
        hbox:
            spacing 80
            vbox:
                spacing 10
                label vn_loc.t("ui.prefs.display")
                textbutton vn_loc.t("ui.prefs.windowed") action Preference("display", "window")
                textbutton vn_loc.t("ui.prefs.fullscreen") action Preference("display", "fullscreen")
            vbox:
                spacing 10
                label vn_loc.t("ui.prefs.skip")
                textbutton vn_loc.t("ui.prefs.skip_all") action Preference("skip", "toggle")
                textbutton vn_loc.t("ui.prefs.skip_after_choices") action Preference("after choices", "toggle")
            use language_picker
        vbox:
            spacing 14
            label vn_loc.t("ui.prefs.volume")
            hbox:
                text vn_loc.t("ui.prefs.volume_music") min_width 260 size 28
                bar value Preference("music volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
            hbox:
                text vn_loc.t("ui.prefs.volume_sound") min_width 260 size 28
                bar value Preference("sound volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
            hbox:
                text vn_loc.t("ui.prefs.volume_voice") min_width 260 size 28
                bar value Preference("voice volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
        textbutton vn_loc.t("ui.common.back") action Return()


# Список языков (ADR-0005): данные — ТОЛЬКО из Language Registry (vn_lang).
# Native-названия, вертикальный список, скролл (мышь/колесо/драг/клавиатура/
# геймпад — фокус сам доскролливает viewport), автопрокрутка к выбранному.
# Масштабируется на десятки языков без правок UI: добавление языка = пакет
# loc/po/<code>/ (тулинг) или каталог game/tl/<code>/ (мод) — кода не требует.
screen language_picker():
    $ _langs = vn_lang.available()
    $ _cur = vn_lang.current()
    $ _sel = next((_i for _i, _l in enumerate(_langs) if _l["code"] == _cur), 0)
    vbox:
        spacing 10
        label vn_loc.t("ui.prefs.language")
        viewport id "vp_languages":
            mousewheel True
            draggable True
            pagekeys True
            scrollbars "vertical"
            xsize 460
            ymaximum 420
            # Автопрокрутка к выбранному языку при открытии экрана
            yinitial (_sel / float(max(1, len(_langs) - 1)))
            # Скроллбар — Solid-стили: gui-ассетов (картинок бара) в проекте нет,
            # дефолтный vscrollbar без них не отрисовывается (как и volume-бары выше)
            vscrollbar_unscrollable "hide"
            vscrollbar_base_bar Solid("#2a2a36")
            vscrollbar_thumb Solid(gui.accent_color)
            vscrollbar_xsize 10
            vbox:
                spacing 4
                for _l in _langs:
                    textbutton _l["name"]:
                        style "pref_lang_button"
                        # Шрифт пакета (CJK и т.п.): native-название рисуется им же;
                        # битый путь из манифеста не должен ронять экран настроек
                        text_font (_l["font"] if _l["font"] and renpy.loadable(_l["font"]) else gui.text_font)
                        action vn_lang.action(_l["code"])

style pref_lang_button:
    xsize 420
    padding (16, 8)
    background None
    hover_background Solid("#2a2a36")
    selected_background Solid("#2f2b22")

style pref_lang_button_text:
    size 30
    color gui.idle_color
    hover_color gui.hover_color
    selected_color gui.accent_color


## ── Служебные ────────────────────────────────────────────────────────────────

screen confirm(message, yes_action, no_action):
    modal True
    zorder 200
    # QA-автопилот: модальные подтверждения (в т.ч. предупреждение save-токенов
    # «сейв с другого устройства» при загрузке фикстур корпуса на CI) отвечают «Да»
    # сами — иначе прогон висит до таймаута. Вне автопилота — no-op.
    if vn_qa.autopilot_active():
        timer 0.8 action yes_action repeat True
    add Solid("#00000088")
    frame:
        xalign 0.5
        yalign 0.5
        vbox:
            spacing 30
            xmaximum 900
            text message xalign 0.5 text_align 0.5
            hbox:
                xalign 0.5
                spacing 100
                textbutton vn_loc.t("ui.confirm.yes") action yes_action
                textbutton vn_loc.t("ui.confirm.no") action no_action


screen notify(message):
    zorder 100
    frame:
        xalign 0.02
        yalign 0.04
        background Solid("#000000aa")
        padding (20, 12)
        text "[message!tq]" size 26
    timer 3.25 action Hide("notify")
