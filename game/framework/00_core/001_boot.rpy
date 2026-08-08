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
    # (вторая линия обороны — lint-запрет каталога game/images в FORBIDDEN_PATHS)
    config.images_directory = None

    # Выделенный слой персонажей (раздел 4): сгенерированный config.tag_layer
    # привязывает к нему все персонажные теги, и `camera sprites` тонирует всех
    # разом matrixcolor-профилем локации. Без слоя show упадёт в рантайме.
    renpy.add_layer("sprites", above="master")

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
    #
    # Обработчика необработанных исключений здесь НЕТ и заводить второй не надо:
    # config.exception_handler — одно поле, и побеждает последнее присваивание.
    # Свой обработчик тут (init -999) молча затирался бы крэш-репортером
    # vn_crash_write_report из 070_crash.rpy (init -950) — ровно так и было,
    # мёртвый код с устаревшей трёхаргументной сигнатурой. Единственный
    # обработчик живёт в 070_crash.rpy: пишет строку "[vn] unhandled exception: …"
    # в log.txt, crash-отчёт в savedir и возвращает False, чтобы движок показал
    # брендированный screen _exception.
