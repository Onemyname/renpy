# engine_compat (G18): ЕДИНСТВЕННЫЙ модуль, которому разрешено касаться
# недокументированных/полудокументированных API Ren'Py. Каждое допущение обязано быть
# покрыто контракт-тестом (tools/vn/tests/, canary-джоба CI гоняет их на свежем Ren'Py).

init -950 python in vn_compat:
    from store import renpy

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

        if isinstance(value, dict):
            return RevertableDict({k: revertable(v) for k, v in value.items()})
        if isinstance(value, list):
            return RevertableList(revertable(v) for v in value)
        if isinstance(value, set):
            return RevertableSet(revertable(v) for v in value)
        return value
