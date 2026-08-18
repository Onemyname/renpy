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
#
# Мобильная поставка живёт в этом же профиле: тач получает крупные кегли и пол
# хит-зоны через токены, а НЕ через `variant`-копии экранов. Копия экрана — это
# вторая вёрстка, которая расходится с первой на первой же правке.

init -4 python in gui:

    # «Крупный»: interface 21 -> 29, button 17 -> 24, tiny 13 -> 18 — интерфейс
    # проходит порог читаемости Deck (~26-28 вирт. px строчных) и ТВ 10-foot.
    VN_UI_SCALE_LARGE = 1.4

    # Минимальная сторона тач-зоны в ВИРТУАЛЬНЫХ px нашей сетки (screen 1920x1080).
    # Считается от 48 dp Material (палец, а не курсор) через два известных факта:
    # плотность типового устройства и то, что движок натягивает виртуальную канву
    # на физический экран целиком.
    #   phone:  ~400 dpi, канва 1080p ложится на 1080-пиксельную сторону ~1:1
    #           -> 48 dp = 48 * 400/160 ≈ 120 вирт. px
    #   tablet: ~300 dpi, канва растянута ~1.5x -> 48 * 300/160 / 1.5 ≈ 72 вирт. px
    # Это ПОЛ, а не размер: кнопка выше — законно, ниже — палец не попадает.
    VN_TOUCH_MIN_PHONE = 120
    VN_TOUCH_MIN_TABLET = 72

    # Safe-area: сколько виртуальных px у края экрана считать «не своими».
    # Худший из двух случаев — ТВ-overscan ~5% (54px из 1080); мобильные вырезы,
    # скругления и зоны системных жестов укладываются в ту же величину.
    VN_SAFE_AREA_PAD = 48

    def vn_ui_scale():
        """Множитель интерфейсных кеглей: выбор игрока или авто по платформе.
        Авто = 1.0; крупный — там, где до экрана далеко (controller-first: Steam
        Deck / Big Picture, читают с 60+ см) ИЛИ экран физически мелкий (мобильный:
        те же 21 вирт. px на 5-дюймовой стороне — нечитаемо). Платформу знает
        только фасад vn_platform (ADR-0014)."""
        pref = getattr(persistent, "vn_ui_scale", None)
        if pref == "normal":
            return 1.0
        if pref == "large":
            return VN_UI_SCALE_LARGE
        from store import vn_platform
        if vn_platform.controller_first() or vn_platform.is_mobile():
            return VN_UI_SCALE_LARGE
        return 1.0

    def vn_touch_min():
        """Пол тач-зоны для мобильной поставки; на десктопе 0 — мышь точна, и
        xminimum/yminimum 0 вёрстку не меняет вовсе (ветвления экранов не нужно)."""
        from store import vn_platform
        if vn_platform.is_phone():
            return VN_TOUCH_MIN_PHONE
        if vn_platform.is_mobile():
            return VN_TOUCH_MIN_TABLET
        return 0


init offset = -3

define gui.ui_scale = gui.vn_ui_scale()

# Safe-area (аудит r1 P2): отступ прижатых к кромке оверлеев (quick menu, контролы
# просмотрщика, вотермарка) от края экрана. Два источника, оба съедают край:
#   ТВ Big Picture — overscan, кромка физически не видна;
#   мобильный — системные жесты (в ландшафте свайп-назад по боковым кромкам),
#     вырезы камеры и скругления корпуса; движок под них не инсетит (в SDK нет
#     ни обработки cutout, ни safe-area — проверено grep'ом по renpy/).
# На мониторах/Deck токен нулевой и вёрстку не меняет.
define gui.overscan_pad = (gui.VN_SAFE_AREA_PAD if (vn_platform.is_big_picture()
                                                    or vn_platform.is_mobile()) else 0)

# Пол тач-зоны (0 на десктопе): xminimum/yminimum кликабельных оверлеев.
define gui.touch_min = gui.vn_touch_min()

init offset = 0

# Профиль дисплея — в лог рядом со строкой платформы (035_platform.rpy). Жалобы
# «интерфейс мелкий» и «не попадаю по кнопке» разбираются ровно этими тремя
# числами, а в логе игрока их иначе не видно вовсе.
init -2 python:
    vn_log("display: ui_scale=%.2f overscan=%d touch_min=%d"
           % (gui.ui_scale, gui.overscan_pad, gui.touch_min))

init -998 python in vn:

    def ui_scale_pref():
        """Выбор игрока: None = авто, 'normal' | 'large' (settings.vars.yaml)."""
        return renpy.store.persistent.vn_ui_scale

    def set_ui_scale(mode):
        """Сменить масштаб на лету: gui.rebuild() пересчитывает define gui.*
        (включая gui.ui_scale) и перестраивает стили; завершается
        restart_interaction — экран настроек переоценивается сам."""
        renpy.store.persistent.vn_ui_scale = mode
        # Через фасад: gui.rebuild — функция ШАБЛОНА SDK, не документированный API
        # движка (G18). Прямой вызов из 20_ui был единственным местом, где это
        # правило нарушалось.
        renpy.store.vn_compat.gui_rebuild()
