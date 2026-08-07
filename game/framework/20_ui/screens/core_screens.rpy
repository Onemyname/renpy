# Минимальный набор экранов фазы 0: игра запускается, сохраняется и загружается.
# Компонентная библиотека UI и темы из токенов (раздел 7 ARCHITECTURE.md) — фаза 2;
# этот файл сознательно простой и без картинок (Solid-фоны): game/assets ещё не собирается.

init offset = -1

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
            textbutton _("Начать игру") action Start()
        else:
            textbutton _("Вернуться") action Return()
            textbutton _("Сохранить") action ShowMenu("save")
        textbutton _("Загрузить") action ShowMenu("load")
        textbutton _("Настройки") action ShowMenu("preferences")
        if main_menu:
            textbutton _("Выход") action Quit(confirm=True)
        else:
            textbutton _("Главное меню") action MainMenu()


screen main_menu():
    tag menu
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xalign 0.97
        yalign 0.95
        spacing 8
        text "[config.name!t]" size gui.title_text_size color gui.accent_color xalign 1.0
        text _("версия [config.version]") size 24 color gui.idle_color xalign 1.0


## ── Сохранение / загрузка ────────────────────────────────────────────────────

screen save():
    tag menu
    use file_menu(_("Сохранение"))

screen load():
    tag menu
    use file_menu(_("Загрузка"))

screen file_menu(title):
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xpos 420
        ypos 80
        spacing 24
        label title
        hbox:
            spacing 20
            textbutton _("Авто") action FilePage("auto")
            for p in range(1, 4):
                textbutton "[p]" action FilePage(p)
        grid 3 3:
            spacing 20
            for i in range(1, 10):
                button:
                    action FileAction(i)
                    xsize 440
                    ysize 130
                    background Solid("#2a2a36")
                    hover_background Solid("#3a3a4a")
                    vbox:
                        spacing 6
                        text FileTime(i, format=_("{#file_time}%d.%m.%Y %H:%M"), empty=_("пустой слот")) size 24
                        text FileSaveName(i) size 22 color gui.idle_color
        textbutton _("Назад") action Return()


## ── Настройки ────────────────────────────────────────────────────────────────

screen preferences():
    tag menu
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xpos 420
        ypos 80
        spacing 30
        label _("Настройки")
        hbox:
            spacing 80
            vbox:
                spacing 10
                label _("Режим экрана")
                textbutton _("Оконный") action Preference("display", "window")
                textbutton _("Полный экран") action Preference("display", "fullscreen")
            vbox:
                spacing 10
                label _("Пропуск")
                textbutton _("Всего текста") action Preference("skip", "toggle")
                textbutton _("После выборов") action Preference("after choices", "toggle")
        vbox:
            spacing 14
            label _("Громкость")
            hbox:
                text _("Музыка") min_width 260 size 28
                bar value Preference("music volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
            hbox:
                text _("Звук") min_width 260 size 28
                bar value Preference("sound volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
            hbox:
                text _("Голос") min_width 260 size 28
                bar value Preference("voice volume") xsize 600 ysize 30 left_bar Solid(gui.accent_color) right_bar Solid("#444450")
        textbutton _("Назад") action Return()


## ── Служебные ────────────────────────────────────────────────────────────────

screen confirm(message, yes_action, no_action):
    modal True
    zorder 200
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
                textbutton _("Да") action yes_action
                textbutton _("Нет") action no_action


screen notify(message):
    zorder 100
    frame:
        xalign 0.02
        yalign 0.04
        background Solid("#000000aa")
        padding (20, 12)
        text "[message!tq]" size 26
    timer 3.25 action Hide("notify")
