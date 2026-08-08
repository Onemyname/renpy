# Достижения (achievements@1): выдача по СТАБИЛЬНЫМ якорям из реестра
# (generated/registry/achievements.gen.rpy), а не по тексту сцен — поэтому
# ачивки добавляются без правки уже написанных и переведённых сцен.
#
# Хранилище — persistent (ачивки не откатываются rollback'ом и переживают
# перезапуск): persistent.vn_achievements = {id: True} (C9: persistent-имена с vn_).
#
# Steam/платформенная синхронизация НЕ здесь: vn_ach.set_provider(fn) — тот же
# приём, что pack_registry.set_ownership_provider (G9). Без провайдера ачивки
# живут локально; подключение платформы не трогает контент-код.

init -980 python in vn_ach:
    from store import renpy, persistent, vn_log

    _provider = None

    def set_provider(fn):
        """fn(achievement_id) -> None: проброс в платформенный бэкенд (Steam и т.п.).
        Подключается после инициализации платформы, до этого — локальные ачивки."""
        global _provider
        _provider = fn

    def _registry():
        return getattr(renpy.store, "VN_ACHIEVEMENTS", {})

    def _unlocked():
        if persistent.vn_achievements is None:
            persistent.vn_achievements = {}
        return persistent.vn_achievements

    def visible(ach_id):
        """Показывать ли ачивку в UI: NSFW-ачивки скрыты в SFW-сборке, чужие
        паки — по владению (G9)."""
        spec = _registry().get(ach_id)
        if spec is None:
            return False
        build = getattr(renpy.store, "vn_build", None)
        if spec.get("nsfw") and build is not None and not build.nsfw:
            return False
        pack = spec.get("pack", "core")
        return renpy.store.vn.pack_registry.owned(pack)

    def has(ach_id):
        return bool(_unlocked().get(ach_id))

    def grant(ach_id):
        """Выдать достижение (идемпотентно). Неизвестный id — лог, не краш:
        сейв старой версии может ссылаться на удалённую ачивку."""
        spec = _registry().get(ach_id)
        if spec is None:
            vn_log("achievement unknown: %s" % ach_id)
            return False
        if not visible(ach_id):
            return False
        if has(ach_id):
            return False
        _unlocked()[ach_id] = True
        if _provider is not None:
            try:
                _provider(ach_id)
            except Exception as e:
                vn_log("achievement provider failed for %s: %s" % (ach_id, e))
        return True

    def _var_value(ref):
        store_name, _, attr = ref.partition(".")
        store = getattr(renpy.store, store_name, None)
        return getattr(store, attr, None) if store is not None else None

    def check(scene_id=None, beat_id=None):
        """Прогон триггеров: зовётся обвязкой сцены (checkpoint), vn.beat и
        после каждой смены состояния. Дёшево: словарь на десятки записей."""
        granted = []
        for ach_id, spec in _registry().items():
            if has(ach_id):
                continue
            trigger = spec.get("trigger") or {}
            hit = False
            if scene_id is not None and trigger.get("scene") == scene_id:
                hit = True
            elif beat_id is not None and trigger.get("beat") == beat_id:
                hit = True
            elif "var" in trigger:
                hit = _var_value(trigger["var"]) == trigger.get("equals", True)
            if hit and grant(ach_id):
                granted.append(ach_id)
        return granted

    def all_ids():
        return sorted(_registry())

default persistent.vn_achievements = {}
