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

    def _nonstring_key_path(value, _depth=0):
        """Путь до первого не-строкового ключа dict внутри value, либо "".

        Возвращает человекочитаемый суффикс вида `["counters"][1]` — автору
        миграции нужно знать не только ИМЯ переменной, но и где именно ключ, иначе
        по логу непонятно, что чинить. Глубина ограничена: состояние приходит из
        сейва игрока, и зацикленную структуру json-раундтрип бы не пережил, но
        рекурсия по чужим данным без потолка — сама по себе способ уронить старт.
        Тот же обход обязан быть в компиляторе (compile.py: _py_literal), иначе
        половина защиты снова смотрит на один уровень."""
        if _depth > 12:
            return ""
        if isinstance(value, _PLAIN_DICT):
            for k in value:
                if not isinstance(k, str):
                    return "[%r]" % (k,)
            for k, v in value.items():
                inner = _nonstring_key_path(v, _depth + 1)
                if inner:
                    return "[%r]%s" % (k, inner)
            return ""
        if isinstance(value, (_builtins.list, _builtins.tuple)):
            for i, v in enumerate(value):
                inner = _nonstring_key_path(v, _depth + 1)
                if inner:
                    return "[%d]%s" % (i, inner)
        return ""

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
        # Что объявлено декларациями — по сторам. Нужно ниже: объявленное имя
        # всегда НАШЕ, чем бы оно ни было в minstore.
        declared = {}
        for _s, _v in SNAPSHOT_VARS:
            declared.setdefault(_s, set()).add(_v)
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
            #
            # Но вычитать ВСЕ имена minstore нельзя: их там 70, и 39 подходят под
            # шаблон имени контентной переменной (C21) — `round`, `position`,
            # `input`, `open`, `set`, `range`, `sorted`… Объявленная переменная с
            # таким именем МОЛЧА выпадала из снапшота, и миграция её не видела:
            # проверено прогоном, `g.round` и `g.position` в state.json
            # отсутствовали при исправной контрольной переменной рядом. Поэтому
            # вычитается РАЗНИЦА: объявленное имя из декларации — наше по
            # определению, что бы движок ни положил в стор под тем же именем.
            engine = vn_compat_names() - declared.get(store_name, frozenset())
            for var, value in vars(module).items():
                if var.startswith("_") or callable(value) or type(value).__name__ == "module":
                    continue
                if var in engine:
                    # Пропуск больше не молчит: остальные две ветки отбраковки
                    # логируют имя, а эта — нет, и «снапшот обещает показывать
                    # ВСЁ» расходилось с фактом без следа в логе.
                    vn_log("snapshot: %s.%s пропущен (имя движка из minstore; "
                           "объявите переменную, если она ваша)"
                           % (store_name, var))
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
            try:
                result = migrate(state)
            except Exception as e:
                # Третий способ сломать цепочку, и раньше он был единственным
                # НЕперехваченным: исключение из тела миграции (KeyError по
                # переменной, которой в старом сейве нет; TypeError на None;
                # опечатка) вылетало из run_migrations, из блока python: в
                # label after_load и попадало в движковый обработчик — крэш-скрин
                # вместо игры. Хуже побочный эффект: apply_snapshot стоит ПОСЛЕ
                # цикла, поэтому результат УСПЕШНО прошедших миграций 2..N−1
                # терялся целиком, а vn_save_schema оставался старым — и каждая
                # следующая загрузка того же слота падала снова.
                # Обрываем так же, как на забытом return и на дыре в нумерации:
                # applied остаётся на последней успешной, apply_snapshot её
                # запишет, а after_load честно скажет «migrations incomplete».
                vn_log("migration %04d упала: %s: %s — цепочка прервана"
                       % (number, type(e).__name__, e))
                break
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
                        # Рекурсивно, а не по верхнему уровню: раундтрип приводит
                        # ключи к строкам на ЛЮБОЙ глубине, а проверка смотрела
                        # только свои ключи. `{counters: {1: 0}}` возвращался в
                        # стор как `{counters: {"1": 0}}`, и следующее
                        # d["counters"][1] промахивалось у КАЖДОГО игрока — без
                        # единой строки в логе.
                        path = _nonstring_key_path(_orig.get(k))
                        if path:
                            vn_log("migration: %s%s — ключи dict нормализованы в "
                                   "строки json-раундтрипом; обращения по "
                                   "не-строковому ключу перестанут находить "
                                   "значение" % (k, path))
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
