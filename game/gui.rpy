# Токены дизайн-системы UI. ЕДИНСТВЕННОЕ место констант оформления:
# в экранах — только gui.* (никаких магических чисел). Имена выбраны так,
# чтобы миграция в theme.yaml фазы 2 (раздел 7.8) была механической:
# palette.* / typography.* / spacing.* / radius.* / components.*.

init offset = -2

init python:
    gui.init(1920, 1080)

## Палитра (palette.*) ─────────────────────────────────────────────────────────
define gui.interface_bg      = "#09090b"    # palette.bg
define gui.menu_bg           = "#0b0b0e"    # palette.bg_content (канва игрового меню)
define gui.panel_bg          = "#18181b"    # palette.surface
define gui.panel_bg_hover    = "#27272a"    # palette.surface_hover
define gui.panel_bg_deep     = "#131316"    # palette.surface_deep (вложенные панели)
define gui.rail_bg           = "#0f0f13fa"  # palette.rail
define gui.panel_border      = "#27272a"    # palette.border
define gui.panel_border2     = "#3f3f46"    # palette.border_strong
define gui.divider_color     = "#1f1f23"    # palette.divider

define gui.text_color        = "#fafafa"    # palette.text.primary
define gui.sub_color         = "#d4d4d8"    # palette.text.secondary
define gui.muted_color       = "#a1a1aa"    # palette.text.muted
define gui.faint_color       = "#71717a"    # palette.text.faint
define gui.insensitive_color = "#52525b"    # palette.text.insensitive

define gui.accent_color      = "#fbbf24"    # palette.accent.primary
define gui.hover_color       = "#fcd34d"    # palette.accent.hover
define gui.on_accent_color   = "#1c1917"    # palette.accent.contrast (текст на акценте)
define gui.selected_color    = "#ffffff"
define gui.idle_color        = gui.muted_color
define gui.danger_color      = "#ef4444"    # palette.danger

## Диалоговое окно (components.say_window) ─────────────────────────────────────
define gui.textbox_scrim       = "#000000"
define gui.textbox_scrim_alpha = 0.82       # плотность scrim у нижнего края
define gui.textbox_height      = 500        # высота зоны scrim
define gui.textbox_side_pad    = 240
define gui.textbox_bottom_pad  = 78
define gui.dialogue_width      = 1180

## Шрифты (typography.fonts; файлы + LICENSE — game/fonts/) ────────────────────
# ЯЗЫКОВЫЕ ПАКЕТЫ переопределяют шрифты через gui.* и манифесты — не хардкодить
# font в стилях мимо этих констант.
define gui.text_font               = "fonts/Literata-Regular.ttf"   # диалоги
define gui.name_text_font          = "fonts/Inter-SemiBold.ttf"     # имя персонажа
define gui.interface_text_font     = "fonts/Inter-Regular.ttf"      # UI
define gui.interface_semibold_font = "fonts/Inter-SemiBold.ttf"     # заголовки/кнопки

## Размеры текста (typography.sizes; px при 1920×1080) ─────────────────────────
## Интерфейсные кегли умножаются на gui.ui_scale (>= 1.0, 20_ui/scale.rpy):
## базовые значения читаемы на мониторе, но малы на Deck/ТВ (аудит r1) —
## профиль «крупный» решается токенами, экраны не копируются. Диалоговые
## кегли (text/name/label/title) масштаб НЕ трогает: они проходят пороги.
define gui.text_size           = 34    # диалоги
define gui.name_text_size      = 29
define gui.interface_text_size = round(21 * gui.ui_scale)   # пункты меню/навигации
define gui.button_text_size    = round(17 * gui.ui_scale)   # кнопки-действия (confirm и т.п.)
define gui.label_text_size     = 34    # заголовки экранов
define gui.group_text_size     = round(13 * gui.ui_scale)   # caps-заголовки групп настроек
define gui.small_text_size     = round(15 * gui.ui_scale)
define gui.tiny_text_size      = round(13 * gui.ui_scale)   # quick menu
define gui.choice_text_size    = round(25 * gui.ui_scale)
define gui.choice_width        = 880   # components.choice.width (стек в диалоговой зоне)
define gui.title_text_size     = 110   # wordmark главного меню

## Шкала отступов (spacing.*) ───────────────────────────────────────────────────
define gui.sp_xs = 4
define gui.sp_s  = 8
define gui.sp_m  = 16
define gui.sp_l  = 32
define gui.sp_xl = 64

## Радиусы (radius.*) — задекларированы для theme.yaml; применятся с ui-ассетами
define gui.radius_button = 8
define gui.radius_panel  = 12

## Сейв-слоты (components.save_slot) ────────────────────────────────────────────
define gui.slot_width        = 440
define gui.slot_thumb_height = 248
define gui.slot_height       = 330

## Скролл-зоны (components.scroll): высота сеток игрового меню (галерея, главы)
define gui.scroll_height = 800

## Карточка достижения (screens/achievements.rpy: vn_ach_card) ─────────────────
## Ширина: две колонки со зазором sp_m укладываются в контентную зону игрового
## меню вместе со скроллбаром (1584 - 2*72 padding = 1440 -> 2*704 + 16 = 1424).
## Высота — бюджет на ЧЕТЫРЕ строки (название + описание в две строки + «не
## получено») в крупном профиле ui_scale 1.4: там строки 36+27+27+23 плюс три
## зазора sp_xs и padding sp_m сверху-снизу дают 157 px. Карточка не клипует
## содержимое, поэтому запас держится осознанно: переполнение проверяется
## псевдолокализацией (vn loc pseudo удлиняет строки на 40%).
define gui.ach_card_width  = 704
define gui.ach_card_height = 168

## Приоритеты default focus (controller-first; 42-big-picture.md §5.1, §5.2) ────
## Первый фокус движок отдаёт НАИБОЛЬШЕМУ default_focus (focus.py:430-437), то
## есть «кто главнее» — это число, а не порядок объявления в файле. Отсюда два
## уровня вместо True: контент экрана перебивает левую рельсу навигации всегда,
## а рельса подхватывает фокус только там, где контент своего default focus не
## объявил. Числа сравниваются, не складываются — промежуточных уровней не надо.
define gui.focus_rail    = 1   # левая рельса игрового меню: резервный владелец
define gui.focus_content = 2   # контент экрана: приоритетный владелец фокуса
