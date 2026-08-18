# Масштаб интерфейса (аудит r1 §Рекомендация): один display-профиль вместо
# вариантов вёрстки. Интерфейсные кегли gui.* (interface/button/small/tiny/
# choice/group) умножаются на gui.ui_scale в САМИХ define'ах gui.rpy —
# экраны не трогаются по построению (весь UI читает только токены).
#
# Порядок init: хелпер (-4) -> define-токены этого файла (-3) -> gui.rpy (-2)
# -> стили/экраны. Рантайм-переключение — vn.set_ui_scale: persistent +
# gui.rebuild() перезапускает ВСЕ define gui.* в исходном порядке, токены
# пересчитываются, стили перестраиваются — без перезапуска игры.
#
# ВАЖНО: только УВЕЛИЧЕНИЕ (масштаб >= 1.0). Генерируемые 9-patch панели
# (ADR-0009) считают минимумы 2*Borders от базовых кеглей: уменьшение сплющило
# бы фоны choice/chip. Рост безопасен — кнопки авто-высотные.

init -4 python in gui:

    # «Крупный»: interface 21 -> 29, button 17 -> 24, tiny 13 -> 18 — интерфейс
    # проходит порог читаемости Deck (~26-28 вирт. px строчных) и ТВ 10-foot.
    VN_UI_SCALE_LARGE = 1.4

    def vn_ui_scale():
        """Множитель интерфейсных кеглей: выбор игрока или авто по платформе.
        Авто = 1.0, а на controller-first (Steam Deck / Big Picture — экран
        дальше/меньше, читают с 60+ см) — крупный. Платформу знает только
        фасад vn_platform (ADR-0014)."""
        pref = getattr(persistent, "vn_ui_scale", None)
        if pref == "normal":
            return 1.0
        if pref == "large":
            return VN_UI_SCALE_LARGE
        from store import vn_platform
        return VN_UI_SCALE_LARGE if vn_platform.controller_first() else 1.0


init offset = -3

define gui.ui_scale = gui.vn_ui_scale()

# Safe-area ТВ (аудит r1 P2): при ~5% overscan срезается до 54px от краёв —
# прижатые к кромке оверлеи (quick menu, контролы просмотрщика, вотермарка)
# сдвигаются на этот токен. На мониторах/Deck он нулевой и вёрстку не меняет.
define gui.overscan_pad = (48 if vn_platform.is_big_picture() else 0)

init offset = 0

init -998 python in vn:

    def ui_scale_pref():
        """Выбор игрока: None = авто, 'normal' | 'large' (settings.vars.yaml)."""
        return renpy.store.persistent.vn_ui_scale

    def set_ui_scale(mode):
        """Сменить масштаб на лету: gui.rebuild() пересчитывает define gui.*
        (включая gui.ui_scale) и перестраивает стили; завершается
        restart_interaction — экран настроек переоценивается сам."""
        renpy.store.persistent.vn_ui_scale = mode
        renpy.store.gui.rebuild()
