# Фасад vn.* — ЕДИНСТВЕННЫЙ API, через который сгенерированный код обращается к движку
# (правило 1.8/3; его api_level проверяют манифесты DLC-паков, раздел 6).

init -1000 python in vn:
    from store import renpy, vn_log, vn_registry
    # ВАЖНО: store vn_compat создаётся на init -950 (C8) — позже этого блока,
    # поэтому доступ к нему ТОЛЬКО ленивый, из тел функций (они зовутся в рантайме).

    API_LEVEL = 1

    # ── Обвязка сцен (C15) ───────────────────────────────────────────────────
    def checkpoint(scene_id):
        """Вход в сцену: якорь восстановления позиции сейва (раздел 6)."""
        renpy.store.vn_scene = scene_id

    def beat(beat_id=None):
        """Мелкий якорь внутри сцены (фаза 2: телеметрия/автотест)."""
        pass

    def check_scene_stack():
        """Инвариант G7: глубина call-стека на границе сцены = 0."""
        depth = renpy.store.vn_compat.call_stack_depth()
        if depth != 0:
            vn_log("scene stack invariant violated: depth=%d" % depth)

    def unwind_call_stack():
        """Размотать call-стек до инварианта (глубина 0). ТОЛЬКО разматывает — куда идти
        дальше, решает вызывающий код (shim-метка делает jump на новый id, обвязка сцены
        при неизвестном exit — jump vn_scene_unavailable)."""
        while renpy.store.vn_compat.call_stack_depth() > 0:
            renpy.pop_call()

    def eval_when(expr):
        """Условия переходов из exits: (scene.yaml). Выражение валидируется компилятором
        против реестра переменных на этапе сборки (раздел 3.11); здесь — только исполнение."""
        return renpy.python.py_eval(expr)

    # ── Владение паками (G9/C14) ─────────────────────────────────────────────
    class _PackRegistry(object):
        def owned(self, pack_id):
            # Фаза 3: Steam ownership-check после инициализации (label splashscreen).
            return pack_id == "core"

        def installed(self, pack_id):
            return pack_id == "core"

    pack_registry = _PackRegistry()


init -1000 python in vn_qa:
    def choice(scene_id, menu_id, idx):
        """Якорь ветки выбора (C1): эмитится компилятором первым стейтментом каждой ветки.
        Фаза 2: запись в прогон-лог QA/телеметрию."""
        pass


# ── Точка входа ──────────────────────────────────────────────────────────────
label start:
    $ _chapters = vn_registry.chapters()
    if not _chapters:
        "Контент не найден."
        "Добавьте главу в content/chapters/ и выполните {b}vn build{/b} (раздел 3 ARCHITECTURE.md)."
        return
    # Маршрутизация к entry-сцене первой доступной главы (генерат кладёт метку в реестр).
    $ renpy.jump(_chapters[0]["entry_label"])


label vn_scene_unavailable:
    "Эта сцена недоступна в текущей версии игры."
    "Возврат в главное меню."
    $ renpy.full_restart()
