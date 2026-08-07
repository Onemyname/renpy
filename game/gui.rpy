# Тонкий gui.rpy: только константы, используемые framework/20_ui.
# Темы/токены (theme.yaml -> генерат) появятся в фазе 2 (раздел 7 ARCHITECTURE.md).

init offset = -2

init python:
    gui.init(1920, 1080)

define gui.text_font = "DejaVuSans.ttf"
define gui.text_size = 33
define gui.name_text_size = 45
define gui.interface_text_size = 33
define gui.label_text_size = 36
define gui.title_text_size = 75

define gui.accent_color = "#c9a15f"
define gui.idle_color = "#888888"
define gui.hover_color = "#e0c48f"
define gui.selected_color = "#ffffff"
define gui.insensitive_color = "#8888887f"
define gui.text_color = "#ffffff"
define gui.interface_bg = "#1a1a22"
define gui.textbox_bg = "#000000cc"
define gui.frame_bg = "#21212bee"
