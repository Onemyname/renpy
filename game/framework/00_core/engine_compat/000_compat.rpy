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
