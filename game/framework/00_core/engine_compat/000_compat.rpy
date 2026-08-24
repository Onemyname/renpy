# engine_compat (G18): ЕДИНСТВЕННЫЙ модуль, которому разрешено касаться
# недокументированных/полудокументированных API Ren'Py. Каждое допущение обязано быть
# покрыто контракт-тестом (tools/vn/tests/, canary-джоба CI гоняет их на свежем Ren'Py).

# ── Слияние persistent между инсталляциями (G18) ─────────────────────────────
#
# Ren'Py сливает persistent ПОФИЛДОВО, и по умолчанию побеждает более новое
# значение поля ЦЕЛИКОМ (persistent.py: default_merge). Для своих полей-
# множеств движок специально регистрирует объединение — _seen_images,
# _seen_audio, _seen_ever, _chosen. Наши накопители (открытая галерея, выданные
# ачивки, виденные сцены, цели walkthrough) — такие же множества, и без
# регистрации при слиянии уникальные записи одной из сторон молча исчезают.
#
# Merge — не гипотетический путь: savelocation.init поднимает МИНИМУМ две
# локации на десктопе (config.savedir и <gamedir>/saves), пишет во все и
# сливает всё, что новее. Steam Auto-Cloud синхронизирует только первую, так
# что расхождение между ними — штатное состояние.
#
# ПОЧЕМУ `python early`, а не init. Первое слияние движок делает ДО исполнения
# любого init-блока:
#     renpy/main.py:466   renpy.persistent.update()          # слияние всех локаций
#     renpy/main.py:481   for … in game.script.initcode: …   # только здесь init -949
# То есть на момент стартового merge в persistent.registry лежат ТОЛЬКО
# движковые регистрации, и наши поля сливались заглушкой default_merge —
# «новее забирает поле целиком». Анлоки одной из сторон исчезали, прогресс
# прогрессивной ачивки уезжал назад, и на выходе main.py:608 update(True)
# записывал усечённое состояние во ВСЕ локации: восстановить нечем.
# `python early` исполняется внутри load_script (renpy/script.py:737
# node.early_execute(), то есть main.py:391) — раньше persistent.init().
# ast.EarlyPython.early_execute сам зовёт create_store, поэтому стор vn_compat
# здесь и создаётся; `renpy` в сторе — это renpy.exports (minstore), и
# register_persistent в нём есть (renpy/exports/__init__.py).
#
# Функции обязаны быть защитными: исключение внутри update() при
# developer=True роняет игру на старте. Вход не-dict (persistent старой
# версии, None) приводим к текущему значению, а не к TypeError.
# vn_log здесь звать НЕЛЬЗЯ — на этой фазе его ещё не существует; громкий
# вариант с логом отрабатывает на init -949 (в конце файла).
# КОНТРАКТ-ТЕСТЫ: test_engine_compat::test_persistent_containers_merge_by_union,
#                 test_engine_compat::test_merges_are_registered_before_the_first_merge.

python early in vn_compat:
    import builtins as _builtins

    # В сторах Ren'Py имена list/dict/set подменены Revertable-аналогами
    # (SDK renpy/minstore.py:41-53). Значит проверять тип по этим именам здесь
    # нельзя: json.loads и чистый python отдают ОБЫЧНЫЕ контейнеры, которые
    # экземплярами Revertable-классов не являются — и конвертация в revertable()
    # молча ничего не делала бы ровно в том случае, ради которого написана.
    # Объявлено в early-блоке, потому что функции слияния ниже нужны раньше init.
    _PLAIN = (_builtins.dict, _builtins.list, _builtins.set)

    def _merge_dict_union(old, new, current):
        """Объединение по ключам: анлок, сделанный на любой из машин, остаётся."""
        out = {}
        for src in (current, old, new):
            if isinstance(src, _PLAIN[0]):
                out.update(src)
        return out

    def _merge_progress_max(old, new, current):
        """Счётчики прогресса: по каждому ключу берётся БОЛЬШЕЕ. Прогресс,
        показанный игроку, не должен уезжать назад после синхронизации."""
        out = {}
        for src in (current, old, new):
            if not isinstance(src, _PLAIN[0]):
                continue
            for k, v in src.items():
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
                out[k] = max(out.get(k, v), v)
        return out

    def _merge_list_union(old, new, current):
        """Список целей walkthrough: объединение с сохранением порядка."""
        out = []
        for src in (current, old, new):
            if not isinstance(src, _PLAIN[1]):
                continue
            for v in src:
                if v not in out:
                    out.append(v)
        return out

    # Поле -> как сливать. Список ведётся ЗДЕСЬ, а не у каждого владельца, чтобы
    # «накопитель в persistent» нельзя было завести, не ответив на вопрос о
    # слиянии: забытая регистрация не падает, она молча теряет прогресс игрока.
    # Полноту списка сверяет test_engine_compat::
    # test_every_persistent_accumulator_is_registered_for_merge — он смотрит и
    # рукописный каркас, и ДЕКЛАРАЦИИ vars@1 (накопитель из декларации рождается
    # в генерате, куда скан по game/framework не заглядывал).
    PERSISTENT_MERGES = {
        "vn_gallery_unlocked": _merge_dict_union,
        "vn_achievements": _merge_dict_union,
        "vn_story_seen": _merge_dict_union,
        "vn_ach_progress": _merge_progress_max,
        "vn_story_targets": _merge_list_union,
    }

    def register_persistent_merges(log=None):
        """Зарегистрировать слияние своих накопителей. Возвращает список полей.

        Идемпотентна (registry[field] = func), поэтому зовётся дважды: здесь, до
        стартового merge, и на init -949 — страховка на случай reload скрипта
        разработчиком. `log` передаётся только со второго вызова: на early-фазе
        vn_log ещё не существует."""
        fn = getattr(renpy, "register_persistent", None)
        if fn is None:
            if log is not None:
                log("persistent: renpy.register_persistent недоступен — "
                    "накопители будут сливаться заменой")
            return []
        for field, merge in sorted(PERSISTENT_MERGES.items()):
            fn(field, merge)
        return sorted(PERSISTENT_MERGES)

    register_persistent_merges()


init -950 python in vn_compat:
    import os

    from store import renpy

    def _read_engine_store_names():
        """Имена, которые движок кладёт в КАЖДЫЙ named store.

        renpy/python.py: create_store() копирует в новый стор всё содержимое
        renpy.minstore. Почти всё оттуда снапшот отсеивает своим фильтром
        («не `_`, не callable, не модуль»), но не всё: `PY2 = False` — обычный
        bool без подчёркивания, и он исправно доезжал до состояния миграций
        (`ch01.PY2`, `g.PY2` в state.json прогона). Автор миграции видит в
        плоском состоянии переменные, которых не объявлял, и любая из них может
        появиться или исчезнуть с версией движка.

        Касание renpy.minstore живёт здесь по G18. Пустое множество — честный
        ответ на неизвестной версии: фильтр просто останется прежним."""
        try:
            import renpy.minstore
            return frozenset(vars(renpy.minstore))
        except Exception:
            return frozenset()

    # Считается ОДИН раз на init, а не лениво с global: рантайм-присваивание имени
    # в сторе движок считает изменением и делает имя корнем сейва навсегда
    # (renpy/python.py: get_changes -> ever_been_changed). Прежний ленивый кэш
    # исправно лежал в файлах сейва — безвредно по содержимому, но это лишний
    # корень в каждом слоте, а инвариант «имена стора в рантайме не
    # переприсваиваются» должен быть без исключений (см. кэши в vn_gal/vn_story).
    _ENGINE_STORE_NAMES = _read_engine_store_names()

    def engine_store_names():
        """Готовый набор имён движка (см. _read_engine_store_names)."""
        return _ENGINE_STORE_NAMES

    def call_stack_depth():
        """Глубина call-стека. renpy.call_stack_depth() документирован в новых версиях;
        fallback — длина return-стека (полудокументированный renpy.get_return_stack()).
        КОНТРАКТ-ТЕСТ: test_engine_compat::test_call_stack_depth."""
        try:
            return renpy.call_stack_depth()
        except AttributeError:
            return len(renpy.get_return_stack())

    def revertable(value):
        """Глубокая конвертация плоских контейнеров в Revertable-типы (G5): значения,
        созданные вне renpy-python (миграции, json), не участвуют в rollback без этого.
        Касание внутреннего модуля renpy.revertable — только здесь.
        КОНТРАКТ-ТЕСТ: test_engine_compat::test_revertable_types."""
        from renpy.revertable import RevertableDict, RevertableList, RevertableSet

        if isinstance(value, _PLAIN[0]):
            return RevertableDict({k: revertable(v) for k, v in value.items()})
        if isinstance(value, _PLAIN[1]):
            return RevertableList(revertable(v) for v in value)
        if isinstance(value, _PLAIN[2]):
            return RevertableSet(revertable(v) for v in value)
        return value

    def defined_screens():
        """Имена экранов, объявленных ЭТИМ ПРОЕКТОМ (для тура vn test screens).

        `renpy.has_screen(name)` документирован и отвечает про один экран, а
        перечисления объявленных в публичном API нет: реестр живёт в
        `renpy.display.screen.screens` — словарь {(имя, вариант): Screen}. Касание
        внутреннего модуля разрешено только здесь (G18); нужно оно ровно для того,
        чтобы гейт «экран есть в игре, но его никто не проверяет» вообще был
        возможен — иначе список экранов пришлось бы поддерживать руками.

        Экраны САМОГО ДВИЖКА (updater, sync_*, director_*, downloader, iconbutton,
        gallery_navigation…) отфильтрованы по месту объявления: они приходят из
        renpy/common/, их вёрстку задаёт Ren'Py, и требовать их в нашем туре
        означало бы держать список чужих экранов в своей декларации.
        КОНТРАКТ-ТЕСТ: test_engine_compat::test_defined_screens_registry."""
        from renpy.display.screen import screens

        # location[0] — не абсолютный путь, а ELIDED-имя: путь ОТНОСИТЕЛЬНО basedir
        # (или renpy_base у файлов движка). Так его кладёт лексер —
        # renpy/lexer.py: elide_filename, вызываемый из list_logical_lines.
        # Прежняя редакция гнала это относительное имя через os.path.abspath, то
        # есть склеивала его с ТЕКУЩИМ рабочим каталогом процесса: фильтр
        # «наш/движковый» зависел от того, откуда запущена игра. Оба исхода ложные
        # и противоположные — при одном cwd своими не признавался НИ ОДИН экран
        # (гейт «экран есть, но его никто не проверяет» молча выключался), при
        # другом своими становились и движковые, и тур требовал их в декларации.
        #
        # Склейка с basedir, а не renpy.unelide_filename(): движковый инверс
        # проверяет существование файла на диске, а в поставке .rpy нет (только
        # .rpyc) — он вернул бы имя как есть. Здесь же ответ нужен независимо от
        # того, лежат ли исходники рядом. Имена движка, отэлайженные относительно
        # renpy_base, после склейки с basedir под gamedir всё равно не попадают.
        basedir = renpy.config.basedir
        gamedir = os.path.normcase(os.path.abspath(renpy.config.gamedir))
        out = set()
        for (name, _variant), screen in screens.items():
            where = (getattr(screen, "location", None) or ("", 0))[0]
            if not where:
                continue
            full = os.path.normcase(os.path.abspath(os.path.join(basedir, where)))
            if full.startswith(gamedir):
                out.add(name)
        return out

    def gui_rebuild():
        """Пересчитать производные значения gui.* после смены масштаба интерфейса.

        `gui.rebuild()` объявлен в шаблоне SDK (`gui.rpy`), а не в документированном
        API движка: это функция ШАБЛОНА, которую проект может и переопределить.
        Поэтому вызов живёт здесь, а не в 20_ui (G18), и отсутствие функции не
        валит переключение масштаба — просто ничего не пересчитывается.
        КОНТРАКТ-ТЕСТ: test_engine_compat::test_gui_rebuild_exists."""
        fn = getattr(renpy.store.gui, "rebuild", None)
        if fn is None:
            return False
        fn()
        return True

    # Слияние persistent (PERSISTENT_MERGES и функции _merge_*) живёт в блоке
    # `python early` в начале этого файла: первое слияние движок делает до
    # исполнения init-кода, см. врезку там.


init -949 python:
    # Повторная регистрация — СТРАХОВКА, а не основной путь: основной отработал
    # в `python early` (до renpy.persistent.init(), см. врезку в начале файла).
    # Здесь она нужна на случай reload скрипта разработчиком и заодно даёт
    # громкий лог, если движок вдруг без register_persistent: на early-фазе
    # vn_log ещё не существует, поэтому логгер передаётся только отсюда.
    vn_compat.register_persistent_merges(log=vn_log)
