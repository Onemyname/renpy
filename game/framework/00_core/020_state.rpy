# State-инфраструктура и миграции сейвов (G5; механика — раздел 6 ARCHITECTURE.md).
# Всё сохраняемое состояние объявляется декларациями *.vars.yaml -> generated/state/defaults.gen.rpy.
# Здесь — только инфраструктурные переменные framework и раннер миграций.

# Маркер текущего меню (C1): вставляется vn loc keys в авторский scene.rpy.
# Имя БЕЗ "_"-префикса — значение обязано попадать в сейв и rollback.
default vn_menu = None

# Текущая сцена (пишет vn.checkpoint) — якорь восстановления позиции сейва.
default vn_scene = None

init -999 python in vn_state:
    from store import renpy, vn_log

    # Цепочка миграций: генерат (фаза 2) наполняет из content/migrations/*.py.
    # Контракт (G5, раздел 6): migrate(state: dict) -> dict над плоским снапшотом stores.
    MIGRATIONS = []    # [(number, migrate), ...] по возрастанию number

    def current_schema():
        return getattr(renpy.store, "vn_save_schema", None)

    # SNAPSHOT_VARS/SNAPSHOT_STORES наполняет generated/state/snapshot.gen.rpy (init -970)
    # из деклараций *.vars.yaml — единый маппинг stores<->dict (G5).
    SNAPSHOT_VARS = ()
    SNAPSHOT_STORES = ()

    _SIMPLE = (str, int, float, bool, list, dict, type(None))

    def snapshot():
        """stores -> плоский dict простых типов (ключи 'store.var').
        Читаются ВСЕ не-'_' переменные управляемых stores, а не только объявленные:
        переменная, удалённая из новой схемы, лежит в старом сейве и обязана быть
        видима migrate(state) — иначе миграциям нечего переносить (слепое пятно G5)."""
        out = {}
        for store_name in SNAPSHOT_STORES:
            module = getattr(renpy.store, store_name, None)
            if module is None:
                continue
            for var, value in vars(module).items():
                if var.startswith("_") or callable(value) or type(value).__name__ == "module":
                    continue
                if not isinstance(value, _SIMPLE):
                    vn_log("snapshot: %s.%s пропущен (не-простой тип %s)"
                           % (store_name, var, type(value).__name__))
                    continue
                out["%s.%s" % (store_name, var)] = value
        out["vn_save_schema"] = getattr(renpy.store, "vn_save_schema", None)
        return out

    def apply_snapshot(state):
        """dict -> stores. Значения проходят Revertable-конвертацию (rollback, G5)."""
        from store import vn_compat
        for store_name, var in SNAPSHOT_VARS:
            key = "%s.%s" % (store_name, var)
            if key in state:
                module = getattr(renpy.store, store_name, None)
                if module is not None:
                    setattr(module, var, vn_compat.revertable(state[key]))

    def run_migrations(from_schema):
        """Прогон цепочки строго по контракту migrate(state: dict) -> dict.
        Снапшот проходит json-раундтрип ДО цепочки: миграции видят только плоские
        типы (Revertable-обёртки движка не протекают в чистый python-код миграций).
        Возвращает номер последней применённой миграции."""
        import json as _json
        state = _json.loads(_json.dumps(snapshot()))
        applied = from_schema
        for number, migrate in MIGRATIONS:
            if number <= from_schema:
                continue
            if number != applied + 1:
                vn_log("migration chain gap: %d -> %d" % (applied, number))
            vn_log("migration %04d" % number)
            state = migrate(state)
            applied = number
        if applied != from_schema:
            apply_snapshot(state)
        return applied


# Контракт G5: весь control flow после загрузки — ТОЛЬКО в label after_load
# (config.after_load_callbacks — только чистая валидация без переходов).
label after_load:
    python:
        _loaded_schema = vn_state.current_schema()
        _target_schema = getattr(renpy.store, "vn_build_save_schema", _loaded_schema)
    if _loaded_schema is not None and _target_schema is not None and _loaded_schema > _target_schema:
        # Сейв из будущей версии: не мигрируем вниз.
        "Сохранение сделано в более новой версии игры. Обновите игру, чтобы продолжить."
        $ renpy.full_restart()
    if _loaded_schema is not None and _target_schema is not None and _loaded_schema < _target_schema:
        python:
            _applied_schema = vn_state.run_migrations(_loaded_schema)
            if _applied_schema != _loaded_schema:
                # Схема повышается ровно до фактически применённой миграции — не до цели:
                # дыра в цепочке не должна помечать сейв «актуальным» без миграции.
                store.vn_save_schema = _applied_schema
                # Откат за точку миграции запрещён — rollback вернул бы домиграционное состояние.
                renpy.block_rollback()
            if _applied_schema < _target_schema:
                vn_log("migrations incomplete: %s -> %s (target %s)"
                       % (_loaded_schema, _applied_schema, _target_schema))
    return
