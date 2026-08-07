# Слой 0, ядро (init -999). Правило 1.8: 00_core не знает ни об одной главе,
# системе или персонаже — ни одного chNN-идентификатора
# (CI-проверка vn content lint --arch появится в фазе 2).

init -999 python:

    # ── Базовая конфигурация движка ──────────────────────────────────────────
    config.rollback_enabled = True
    config.hard_rollback_limit = 100
    config.autosave_on_quit = True
    # Рекомендация renpy lint: ловить конфликтующие style-свойства на этапе анализа.
    config.check_conflicting_properties = True

    # Автоопределение образов по game/images/ НЕ используется (раздел 1.2):
    # компилятор эмитит явные image-стейтменты из Asset Registry.
    config.automatic_images = None

    # ── Логгер ────────────────────────────────────────────────────────────────
    def vn_log(msg):
        """Единый лог надстройки: попадает в log.txt Ren'Py."""
        renpy.write_log("[vn] %s", msg)

    # ── Сейвы: версия схемы и версия игры в JSON-заголовке слота ─────────────
    # Оффлайн-инструменты (vn save check) читают их без unpickle (G5).
    def _vn_save_json(d):
        d["vn_save_schema"] = getattr(store, "vn_save_schema", None)
        d["vn_version"] = config.version
        d["vn_scene"] = getattr(store, "vn_scene", None)

    config.save_json_callbacks.append(_vn_save_json)

    # ── Последний эшелон обороны (G7) ────────────────────────────────────────
    # config-хука «перехват jump на несуществующую метку» в Ren'Py не существует;
    # основная защита — shim-метки из generated/registry/overrides.gen.rpy.
    # Здесь — только перехват необработанного ScriptError: не даём игре упасть.
    def _vn_exception_handler(short, full, traceback_fn):
        vn_log("unhandled exception: %s" % (short.splitlines()[0] if short else "?"))
        return False    # False = показать стандартный экран ошибки (dev); фаза 2: свой экран

    config.exception_handler = _vn_exception_handler
