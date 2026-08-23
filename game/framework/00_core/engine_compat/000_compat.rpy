# engine_compat (G18): ЕДИНСТВЕННЫЙ модуль, которому разрешено касаться
# недокументированных/полудокументированных API Ren'Py. Каждое допущение обязано быть
# покрыто контракт-тестом (tools/vn/tests/, canary-джоба CI гоняет их на свежем Ren'Py).

init -950 python in vn_compat:
    import builtins as _builtins
    import os

    from store import renpy

    # В сторах Ren'Py имена list/dict/set подменены Revertable-аналогами
    # (SDK renpy/minstore.py:41-53). Значит проверять тип по этим именам здесь
    # нельзя: json.loads и чистый python отдают ОБЫЧНЫЕ контейнеры, которые
    # экземплярами Revertable-классов не являются — и конвертация ниже молча
    # ничего не делала бы ровно в том случае, ради которого написана.
    _PLAIN = (_builtins.dict, _builtins.list, _builtins.set)

    _engine_names_cache = None

    def engine_store_names():
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
        global _engine_names_cache
        if _engine_names_cache is None:
            try:
                import renpy.minstore
                _engine_names_cache = frozenset(vars(renpy.minstore))
            except Exception:
                _engine_names_cache = frozenset()
        return _engine_names_cache

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

        gamedir = os.path.abspath(renpy.config.gamedir)
        out = set()
        for (name, _variant), screen in screens.items():
            where = (getattr(screen, "location", None) or ("", 0))[0]
            if where and os.path.abspath(where).startswith(gamedir):
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

    # ── Слияние persistent между инсталляциями (G18) ─────────────────────────
    #
    # Ren'Py сливает persistent ПОФИЛДОВО, и по умолчанию побеждает более новое
    # значение поля ЦЕЛИКОМ (persistent.py: default_merge). Для своих полей-
    # множеств движок специально регистрирует объединение — _seen_images,
    # _seen_audio, _seen_ever, _chosen. Наши накопители (открытая галерея,
    # выданные ачивки, виденные сцены, цели walkthrough) — такие же множества,
    # но не были зарегистрированы ни разу, поэтому при слиянии уникальные записи
    # одной из сторон молча исчезали.
    #
    # Merge — не гипотетический путь: savelocation.init поднимает МИНИМУМ две
    # локации на десктопе (config.savedir и <gamedir>/saves), пишет во все и
    # сливает всё, что новее. Steam Auto-Cloud синхронизирует только первую, так
    # что расхождение между ними — штатное состояние. Асимметрия делала дефект
    # особенно неприятным: кадры, засчитанные движком через _seen_images,
    # слияние переживали, а видео и аудио галереи, открытые нашим кодом, — нет.
    #
    # Функции обязаны быть защитными: исключение внутри update() при
    # developer=True роняет игру на старте. Вход не-dict (persistent старой
    # версии, None) приводим к текущему значению, а не к TypeError.
    # КОНТРАКТ-ТЕСТ: test_engine_compat::test_persistent_containers_merge_by_union.

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
    PERSISTENT_MERGES = {
        "vn_gallery_unlocked": _merge_dict_union,
        "vn_achievements": _merge_dict_union,
        "vn_story_seen": _merge_dict_union,
        "vn_ach_progress": _merge_progress_max,
        "vn_story_targets": _merge_list_union,
    }

    def register_persistent_merges():
        """Зарегистрировать слияние своих накопителей. Возвращает список полей."""
        fn = getattr(renpy, "register_persistent", None)
        if fn is None:
            vn_log("persistent: renpy.register_persistent недоступен — "
                   "накопители будут сливаться заменой")
            return []
        for field, merge in sorted(PERSISTENT_MERGES.items()):
            fn(field, merge)
        return sorted(PERSISTENT_MERGES)


init -949 python:
    # Сразу после vn_compat (init -950) и задолго до первого слияния: update()
    # движок зовёт уже на старте, из renpy.main.
    vn_compat.register_persistent_merges()
