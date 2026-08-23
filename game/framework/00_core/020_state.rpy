# State-инфраструктура и миграции сейвов (G5; механика — раздел 6 ARCHITECTURE.md).
# Всё сохраняемое состояние объявляется декларациями *.vars.yaml -> generated/state/defaults.gen.rpy.
# Здесь — только инфраструктурные переменные framework и раннер миграций.

# Маркер текущего меню (C1): вставляется vn loc keys в авторский scene.rpy.
# Имя БЕЗ "_"-префикса — значение обязано попадать в сейв и rollback.
default vn_menu = None

# Текущая сцена (пишет vn.checkpoint) — якорь восстановления позиции сейва.
default vn_scene = None

init -999 python in vn_state:
    import builtins as _builtins

    from store import renpy, vn_log

    # В сторах Ren'Py имена list/dict/set подменены Revertable-аналогами
    # (SDK renpy/minstore.py:41-53), поэтому проверять тип по имени `dict` здесь
    # нельзя: json.loads отдаёт ОБЫЧНЫЙ dict, а он не является RevertableDict —
    # и проверка «миграция вернула dict» отвергала бы корректный результат.
    # Поймано save-корпусом на живом движке; юнит-тест этого не видит, если не
    # воспроизвести подмену (см. tools/vn/tests/test_saves.py).
    _PLAIN_DICT = _builtins.dict

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

    def _json_safe(value):
        """Переживёт ли значение json-раундтрип цепочки миграций (run_migrations).

        isinstance по ВЕРХНЕМУ уровню на это не отвечает: set внутри объявленного
        списка проходит проверку типа, а json.dumps падает уже на нём — то есть
        внутри label after_load, и загрузка старого сейва превращается в крэш-скрин
        вместо игры. Оракул совместимости здесь только сам json: угадывать за него,
        какие вложенные типы сериализуемы, значит держать вторую реализацию json.

        Цена решения: такая переменная выпадает из видимости миграций (снапшот
        обещает показывать ВСЁ, см. ниже). Выбор между «миграция её не увидит» и
        «игрок не загрузит сейв» сделан в пользу первого, а факт пропуска пишется
        в лог отдельной строкой — с именем переменной, чтобы автор миграции знал."""
        import json as _json
        try:
            _json.dumps(value)
        except (TypeError, ValueError):
            return False
        return True

    def vn_compat_names():
        """Имена движка из vn_compat — лениво: стор создаётся на init -950, позже
        этого блока (C8)."""
        from store import vn_compat
        return vn_compat.engine_store_names()

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
            # Имена движка вычитаются ЯВНО, а не ловятся признаками: create_store
            # копирует в каждый named store всё содержимое renpy.minstore, и
            # фильтр «не `_`, не callable, не модуль» пропускал оттуда `PY2` —
            # обычный bool, доезжавший до состояния миграций как `g.PY2`. Автор
            # миграции не должен видеть в плоском состоянии переменные, которых
            # никто не объявлял (и которые меняются с версией движка).
            engine = vn_compat_names()
            for var, value in vars(module).items():
                if var.startswith("_") or callable(value) or type(value).__name__ == "module":
                    continue
                if var in engine:
                    continue
                if not isinstance(value, _SIMPLE):
                    vn_log("snapshot: %s.%s пропущен (не-простой тип %s)"
                           % (store_name, var, type(value).__name__))
                    continue
                if not _json_safe(value):
                    vn_log("snapshot: %s.%s пропущен (внутри значения тип, не "
                           "переживающий json-раундтрип миграций)" % (store_name, var))
                    continue
                out["%s.%s" % (store_name, var)] = value
        out["vn_save_schema"] = getattr(renpy.store, "vn_save_schema", None)
        return out

    def apply_snapshot(state):
        """dict -> stores. Значения проходят Revertable-конвертацию (rollback, G5).
        Пишутся только присутствующие в state ключи: run_migrations передаёт сюда
        ФАКТИЧЕСКИ изменённое, а не весь снапшот (см. там же, почему).

        Путь удаления здесь отсутствует по построению: `del state[key]` в миграции
        ничего не сбрасывает — переменная останется в сторе с прежним значением.
        Сброс делается ПРИСВАИВАНИЕМ нужного значения, а выведенная из схемы
        переменная убирается из деклараций (и тогда её просто никто не читает)."""
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
        # Канонический снимок «до цепочки», по ключам. Значения сразу превращаются
        # в строки, поэтому мутация state миграцией на него не влияет — второй
        # разбор снапшота для этого не нужен. Сравниваем сериализации, а не
        # значения: иначе True и 1 считались бы одинаковыми.
        before = {k: _json.dumps(v, sort_keys=True) for k, v in state.items()}
        # Значения ДО раундтрипа: нужны, чтобы отличить «ключи были строками» от
        # «ключи нормализованы» — по сериализации этого не видно.
        _orig = snapshot()
        applied = from_schema
        for number, migrate in MIGRATIONS:
            if number <= from_schema:
                continue
            if number != applied + 1:
                # Миграция N ждёт состояние ПОСЛЕ N-1; поверх непройденной
                # предыдущей её исполнять нельзя, поэтому цепочка обрывается —
                # схема останется прежней, и after_load честно скажет «incomplete»
                # (иначе сейв помечался бы актуальным, не пройдя шаг). Непрерывность
                # гарантирует компилятор (_collect_migrations), так что сюда доходит
                # только генерат, собранный в обход сборки.
                vn_log("migration chain gap: %d -> %d — цепочка прервана" % (applied, number))
                break
            vn_log("migration %04d" % number)
            result = migrate(state)
            if not isinstance(result, _PLAIN_DICT):
                # Контракт migrate(state) -> dict; типичная описка — забытый return.
                # Дальше идти нельзя (следующая миграция получила бы None), а падать
                # трейсбеком у игрока — тем более: обрываем цепочку как на дыре.
                vn_log("migration %04d вернула %s вместо dict — цепочка прервана"
                       % (number, type(result).__name__))
                break
            state = result
            applied = number
        if applied != from_schema:
            # Обратно пишем ТОЛЬКО фактически изменённое: json-раундтрип нужен
            # миграциям, но он же приводит ключи dict к строкам, и запись им всего
            # снапшота портила бы переменные, которых ни одна миграция не касалась.
            changed = {}
            for k, v in state.items():
                try:
                    same = _json.dumps(v, sort_keys=True) == before.get(k)
                except (TypeError, ValueError):
                    # Миграция положила не-json значение (нарушение своего же
                    # контракта). Записать его всё равно надо — иначе результат
                    # миграции потеряется молча, — но факт обязан быть в логе.
                    vn_log("migration: %s не сериализуется в json — "
                           "миграция нарушает контракт плоского состояния" % k)
                    same = False
                if not same:
                    # Вторая половина той же защиты. «Не трогали — не пишем»
                    # спасает переменные, которых миграция не касалась; но
                    # ТРОНУТУЮ мы записываем уже после json-раундтрипа, а json
                    # приводит ключи dict к строкам. Значит {1: …} вернулся бы в
                    # стор как {"1": …}, и следующий d[1] промахнулся бы у всех
                    # игроков. Компилятор такие дефолты запрещает (_py_literal),
                    # но переменную мог наполнить и рантайм-код сцены — здесь
                    # хотя бы остаётся след, а не тишина.
                    if isinstance(v, _PLAIN_DICT):
                        old_value = _orig.get(k)
                        if isinstance(old_value, _PLAIN_DICT) and any(
                                not isinstance(kk, str) for kk in old_value):
                            vn_log("migration: %s — ключи dict нормализованы в "
                                   "строки json-раундтрипом; обращения по "
                                   "не-строковому ключу перестанут находить "
                                   "значение" % k)
                    changed[k] = v
            apply_snapshot(changed)
        return applied


# Контракт G5: весь control flow после загрузки — ТОЛЬКО в label after_load
# (config.after_load_callbacks — только чистая валидация без переходов).
label after_load:
    python:
        _loaded_schema = vn_state.current_schema()
        _target_schema = getattr(renpy.store, "vn_build_save_schema", _loaded_schema)
    if _loaded_schema is not None and _target_schema is not None and _loaded_schema > _target_schema:
        # Сейв из будущей версии: не мигрируем вниз. block_rollback ДО say —
        # иначе гейт обходится колёсиком мыши (say = интеракция, откат за неё
        # вернул бы игрока в немигрируемое состояние). Текст — через vn_loc.t():
        # литерал в label не попадает в PO-экстракцию (ADR-0005).
        $ renpy.block_rollback()
        $ renpy.say(None, vn_loc.t("ui.flow.save_from_newer"))
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
    # Догон триггеров по переменным: состояние пришло из сейва, а не с якоря
    # (подробно — vn.recheck_triggers). После миграций, чтобы триггеры видели
    # уже актуальное состояние.
    $ vn.recheck_triggers()
    return
