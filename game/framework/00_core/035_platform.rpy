# Platform Services (ADR-0014): ЕДИНСТВЕННОЕ место, где игра касается платформы.
#
# Принцип: Game Core -> фасады ядра (vn_ach, vn.pack_registry) -> провайдеры,
# которые подключает ЭТОТ файл. Игровой код не знает слова «Steam»: он зовёт
# vn_ach.grant("id") и pack_registry.owned("pack") — куда это уходит, решается
# здесь. Нет платформы — работают локальные no-op/persistent-реализации, игра
# полноценна как standalone.
#
# Steam-специфика — через ШТАТНЫЙ стек движка (00steam.rpy/00achievement.rpy):
# сторонних биндингов нет. Движок сам (init -1499): импортирует steamapi, если
# steam_api-библиотека лежит рядом с исполняемым файлом; вставляет варианты
# steam_deck (+medium+touch) и steam_big_picture; включает экранную клавиатуру
# Deck для input(); регистрирует SteamBackend ачивок. Без библиотеки или с
# config.steam_appid = None (генерат platform.gen.rpy) всё это тихо выключено.

init -960 python in vn_platform:
    from store import renpy, vn_log

    def steam():
        """_renpysteam или None. Единственный легальный способ узнать про Steam;
        прямые обращения к _renpysteam вне этого файла запрещены ревью."""
        from store import achievement
        return getattr(achievement, "steam", None)

    def backend():
        """Идентичность платформы для логов/крэш-репортов: 'steam' | 'standalone'."""
        return "steam" if steam() is not None else "standalone"

    def is_steam_deck():
        """Handheld-окружение Steam Deck (вариант вставляет движок при init)."""
        return renpy.variant("steam_deck")

    def is_big_picture():
        return renpy.variant("steam_big_picture")

    def has_touch():
        return renpy.variant("touch")

    def controller_first():
        """Игрок, скорее всего, без мыши/клавиатуры: UI не должен требовать их."""
        return is_steam_deck() or is_big_picture()

    # ── Мобильная поставка (Android/iOS) ─────────────────────────────────────
    # Варианты вставляет САМ движок при старте (renpy/main.py: choose_variants):
    # Android -> android + mobile + touch + (phone+small | tablet+medium) по
    # физической диагонали экрана; iOS -> ios + mobile + touch + то же деление;
    # десктоп -> pc + large. Эмулятор лаунчера подставляет тот же набор через
    # RENPY_VARIANT, поэтому ветки проверяемы без устройства.

    def is_mobile():
        """Мобильная сборка: тач вместо мыши, нет окна и нет права выйти."""
        return renpy.variant("mobile")

    def is_android():
        """Именно Android (в логе/крэш-репорте: у iOS другие правила стора и UI)."""
        return renpy.variant("android")

    def is_phone():
        """Мелкий экран. Делит устройства ФИЗИЧЕСКАЯ диагональ, а не разрешение
        (renpy/main.py: >= 6 дюймов -> tablet+medium, иначе phone+small), поэтому
        минимальная тач-зона считается от этого варианта."""
        return renpy.variant("phone")

    def is_desktop():
        """ПК: есть окно, мышь и право закрыть приложение. Единственный вариант,
        под которым уместны «Выйти» и переключатель окно/полный экран: на iOS
        кнопка выхода запрещена правилами стора, на Android и в вебе бессмысленна,
        окном там не управляют. Так же гейтит их штатный шаблон SDK
        (gui/game/screens.rpy: `if renpy.variant("pc")`)."""
        return renpy.variant("pc")

    def overlay_enabled():
        s = steam()
        try:
            return bool(s is not None and s.is_overlay_enabled())
        except Exception:
            return False

    def describe():
        """Одна строка для крэш-репорта и дебага: по ней видно, какой профиль UI
        и памяти был активен (мобильные ветки иначе не отличить от десктопных)."""
        return "%s deck=%s bigpicture=%s touch=%s mobile=%s android=%s phone=%s" % (
            backend(), is_steam_deck(), is_big_picture(), has_touch(),
            is_mobile(), is_android(), is_phone())

    def _steam_owns_pack(pack_id):
        """Ownership-провайдер (G9): пак с steam_dlc_appid — по факту установки
        DLC (Steam скачивает депот только купившим), без маппинга — владение
        определяется установленностью, как в DRM-free поставке."""
        dlc = (getattr(renpy.store, "VN_STEAM_DLC", None) or {}).get(pack_id)
        if dlc is None:
            return True
        try:
            return bool(steam().dlc_installed(dlc))
        except Exception as e:
            # Ошибка API не должна отбирать купленный контент: fail-open,
            # гейт логический и не претендует на защиту (G9).
            vn_log("vn_platform: dlc_installed(%s) failed: %s" % (pack_id, e))
            return True


init 999 python:
    # Подключение провайдеров — после загрузки всех реестров (VN_ACHIEVEMENTS,
    # VN_STEAM_DLC) и инициализации Steam движком. Standalone: блок no-op.
    if vn_platform.steam() is not None:
        vn.pack_registry.set_ownership_provider(vn_platform._steam_owns_pack)

        # Ачивки: те же стабильные id, что в achievements.yaml, регистрируются
        # в движковом achievement-модуле (его SteamBackend батчит StoreStats).
        # В Steamworks API Name каждой ачивки обязан совпадать с её id.
        for _vn_aid in vn_ach.all_ids():
            achievement.register(_vn_aid)
        vn_ach.set_provider(achievement.grant)
        # Догон: выданное офлайн/до покупки Steam-версии доезжает при первом
        # запуске под Steam (grant идемпотентен, sync сводит бэкенды).
        for _vn_aid in vn_ach.all_ids():
            if vn_ach.has(_vn_aid):
                achievement.grant(_vn_aid)
        achievement.sync()

    # Идентичность платформы — в лог ВСЕГДА, а не только под Steam: мобильная
    # сборка отличается от десктопной ровно вариантами, и без этой строки
    # «на телефоне интерфейс мелкий» невозможно разобрать по логу игрока.
    vn_log("platform: %s" % vn_platform.describe())
