# State-инфраструктура и миграции сейвов (G5; механика — раздел 6 ARCHITECTURE.md).
# Всё сохраняемое состояние объявляется декларациями *.vars.yaml -> generated/state/defaults.gen.rpy.
# Здесь — только инфраструктурные переменные framework и раннер миграций.

# Маркер текущего меню (C1): вставляется vn loc keys в авторский scene.rpy.
# Имя БЕЗ "_"-префикса — значение обязано попадать в сейв и rollback.
default vn_menu = None

# Текущая сцена (пишет vn.checkpoint) — якорь восстановления позиции сейва.
default vn_scene = None

init -1000 python in vn_state:
    from store import renpy, vn_log

    # Цепочка миграций: генерат (фаза 2) наполняет из content/migrations/*.py.
    # Контракт (G5, раздел 6): migrate(state: dict) -> dict над плоским снапшотом stores.
    MIGRATIONS = []    # [(number, migrate), ...] по возрастанию number

    def current_schema():
        return getattr(renpy.store, "vn_save_schema", None)

    def snapshot():
        """stores -> плоский dict. Фаза 2: генерируемый маппинг (G5); пока пустой снапшот."""
        return {}

    def apply_snapshot(state):
        """dict -> stores + глубокая Revertable-конвертация (json-раундтрип). Фаза 2."""
        pass

    def run_migrations(from_schema):
        """Прогон цепочки строго по контракту migrate(state)->state.
        Возвращает номер последней применённой миграции (== from_schema, если нечего применять)."""
        state = snapshot()
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
