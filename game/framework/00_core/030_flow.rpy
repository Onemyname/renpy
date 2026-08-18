# Фасад vn.* — ЕДИНСТВЕННЫЙ API, через который сгенерированный код обращается к движку
# (правило 1.8/3; его api_level проверяют манифесты DLC-паков, раздел 6).

init -999 python in vn:
    from store import renpy, vn_log, vn_registry
    # ВАЖНО: store vn_compat создаётся на init -950 (C8) — позже этого блока,
    # поэтому доступ к нему ТОЛЬКО ленивый, из тел функций (они зовутся в рантайме).

    API_LEVEL = 1

    # ── Обвязка сцен (C15) ───────────────────────────────────────────────────
    def checkpoint(scene_id):
        """Вход в сцену: якорь восстановления позиции сейва (раздел 6) и
        триггер достижений/галереи, привязанных к сцене."""
        renpy.store.vn_scene = scene_id
        # Счётчик прохождения: СПИСОК посещённых сцен, а не число — только так
        # повторный вход в сцену не накручивает прогресс, а сейв остаётся из
        # простых типов (G5). Прогрессивные ачивки считают его длину.
        seen = renpy.store.g.scenes_seen
        if scene_id not in seen:
            seen.append(scene_id)
        renpy.store.vn_ach.check(scene_id=scene_id)
        _gallery_notify(renpy.store.vn_gal.check(scene_id=scene_id))

    def beat(beat_id=None):
        """Мелкий якорь внутри сцены: триггер достижений/галереи и точка
        расширения для телеметрии/автотестов (фаза 2)."""
        if beat_id is not None:
            renpy.store.vn_ach.check(beat_id=beat_id)
            _gallery_notify(renpy.store.vn_gal.check(beat_id=beat_id))

    def chapter_done(chapter_id):
        """Глава пройдена: якорь для галереи/достижений «за прохождение».
        Зовётся обвязкой финальной сцены главы (компилятор) и вручную не нужен."""
        renpy.store.vn_ach.check(beat_id="chapter_done:%s" % chapter_id)
        _gallery_notify(renpy.store.vn_gal.check(chapter_done=chapter_id))

    def _gallery_notify(opened):
        """Уведомление о новом контенте галереи — через штатный notify-экран
        (тот же канал, что у остальных сообщений; своей системы не вводим)."""
        if not opened:
            return
        n = len(opened)
        key = "ui.gallery.unlocked_one" if n == 1 else "ui.gallery.unlocked_many"
        text = renpy.store.vn_loc.t(key)
        if n > 1:
            text = text.replace("[n]", str(n))
        renpy.notify(text)

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
        """Гейт владения — ЛОГИЧЕСКИЙ (наличие .rpa ничем не защищено, G9).
        Установленность — пересечение генерата VN_PACKS и поставки сборки
        (vn_build.packs); владение — через провайдера: Steam ownership-check
        подключается set_ownership_provider после инициализации Steam
        (label splashscreen). Без провайдера установленный пак считается
        купленным (dev/DRM-free поставка)."""

        def __init__(self):
            self._provider = None

        def set_ownership_provider(self, fn):
            self._provider = fn

        def installed(self, pack_id):
            if pack_id == "core":
                return True
            if pack_id not in getattr(renpy.store, "VN_PACKS", {}):
                return False
            # VN_PACKS перечисляет ВСЕ паки дерева, а уезжает в дистрибутив только
            # список флейвора (build_info@2: vn_build.packs). Без этой сверки пак
            # patron-флейвора считался бы в public-сборке установленным — а без
            # Steam-провайдера (DRM-free поставка владение = установленность) ещё и
            # купленным. В dev-чекауте build_id.json нет: разработчику видно всё
            # установленное, иначе dev-прогон и smoke гейтились бы вслепую.
            build = getattr(renpy.store, "vn_build", None)
            if build is None or not build.is_release:
                return True
            return pack_id in build.packs

        def owned(self, pack_id):
            if pack_id == "core":
                return True
            if not self.installed(pack_id):
                return False
            if self._provider is not None:
                return bool(self._provider(pack_id))
            return True

    pack_registry = _PackRegistry()


init -999 python in vn_qa:
    import os
    import time
    from store import renpy, vn_log

    _T0 = time.time()    # init-время: точка отсчёта cold start (G19)

    def choice(scene_id, menu_id, idx):
        """Якорь ветки выбора (C1): эмитится компилятором первым стейтментом каждой ветки.
        Фаза 2: запись в прогон-лог QA/телеметрию."""
        pass

    # ── Автопилот (vn test smoke, G23): работает ТОЛЬКО внутри процесса игры, ──
    # без синтетического ввода на рабочий стол. Активируется переменной окружения
    # VN_AUTOPILOT; label main_menu-override подкладывает раннер (cli: vn test smoke).
    def autopilot_active():
        return "VN_AUTOPILOT" in os.environ

    def autopilot_tick():
        """Каждый тик: скриншот средствами движка + продвижение диалога.
        VN_AUTOPILOT_SAVE_AT=N: на тике N создаётся сейв (фикстуры корпуса, G5/G6)."""
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        n = getattr(renpy.store, "_vn_ap_shot", 0)       # служебный счётчик автопилота
        renpy.store._vn_ap_shot = n + 1
        if n == 0 and shots_dir:
            # Cold start (G19): init-фаза -> первая интеракция
            with open(os.path.join(shots_dir, "startup.txt"), "w", encoding="utf-8") as f:
                f.write("%.2f\n" % (time.time() - _T0))
        if shots_dir:
            try:
                renpy.screenshot(os.path.join(shots_dir, "shot%03d.png" % n))
            except Exception as e:
                vn_log("autopilot screenshot failed: %s" % e)
        save_at = os.environ.get("VN_AUTOPILOT_SAVE_AT")
        if save_at and int(save_at) == n:
            renpy.save("1-1")
            vn_log("autopilot: fixture save at tick %d" % n)
        renpy.queue_event("dismiss")

    def autopilot_choose(items):
        """Выбор пункта меню — вызывается ТОЛЬКО из timer-action (side effect в
        screen-выражении запрещён: экран переоценивается предикцией и каждым тиком
        оверлея, и счётчик picks дрейфовал бы). Пишет фактический путь в picks.log."""
        actionable = [(i, it) for i, it in enumerate(items) if it.action is not None]
        if not actionable:
            return
        picks = [p for p in os.environ.get("VN_AUTOPILOT_PICKS", "").split(",") if p.strip()]
        n = getattr(renpy.store, "_vn_ap_menu", 0)
        renpy.store._vn_ap_menu = n + 1
        idx = int(picks[n]) if n < len(picks) else 0
        idx = min(idx, len(items) - 1)
        if items[idx].action is None:
            idx = actionable[0][0]
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        if shots_dir:
            with open(os.path.join(shots_dir, "picks.log"), "a", encoding="utf-8") as f:
                f.write("menu %d -> pick %d (%s)\n" % (n, idx, renpy.store.vn_menu))
        # ВАЖНО: значение action обязано вернуться из Function — интеракция меню
        # завершается только non-None результатом action (иначе вечное перевыбирание).
        return renpy.run(items[idx].action)

    def autopilot_boot():
        """Вызывается из label main_menu qa-файла ОДНИМ выражением: никаких import
        в рантайм-python — rollback-лог записал бы модуль в сейв (module_pickle)."""
        lang = os.environ.get("VN_AUTOPILOT_LANG") or None
        if lang == "@source":
            # Прогон на исходном языке: явный сброс (персистентный language
            # от прошлых прогонов иначе тихо подменил бы язык теста)
            renpy.change_language(None)
        elif lang:
            renpy.change_language(lang)
        slot = os.environ.get("VN_AUTOPILOT_LOAD")
        if slot:
            renpy.load(slot)    # не возвращается: контекст перезапускается, затем after_load

    def autopilot_screens():
        """VN_AUTOPILOT_SCREENS=gallery,preferences — показать перечисленные экраны
        и снять по скриншоту. Проверка вёрстки меню/галереи в CI: движковый lint
        не видит визуальных поломок, а прохождение сцен эти экраны не открывает."""
        names = [s.strip() for s in
                 os.environ.get("VN_AUTOPILOT_SCREENS", "").split(",") if s.strip()]
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        for name in names:
            try:
                renpy.show_screen(name)
                # show_screen лишь помечает экран к показу: кадр рисуется только
                # интеракцией, а screenshot() пишет последний нарисованный кадр.
                # Короткая пауза даёт кадр с уже показанным экраном.
                renpy.pause(0.3)
                if shots_dir:
                    renpy.screenshot(os.path.join(shots_dir, "screen_%s.png" % name))
                renpy.hide_screen(name)
            except Exception as e:
                vn_log("autopilot screen %s failed: %s" % (name, e))

    def autopilot_finish(reason):
        """Конец прогона: маркер результата + снапшот состояния + выход из процесса.
        state.json позволяет корпусу проверить фактическую пост-миграционную схему,
        а gallery.json — что разблокировка доехала до persistent (ADR-0010)."""
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        if shots_dir:
            with open(os.path.join(shots_dir, "RESULT.txt"), "w", encoding="utf-8") as f:
                f.write(reason + "\n")
            try:
                import json
                from store import vn_state
                with open(os.path.join(shots_dir, "state.json"), "w", encoding="utf-8") as f:
                    json.dump(vn_state.snapshot(), f, ensure_ascii=False, indent=1)
            except Exception as e:
                vn_log("autopilot state dump failed: %s" % e)
            try:
                import json
                from store import vn_gal
                done, total = vn_gal.progress()
                with open(os.path.join(shots_dir, "gallery.json"), "w", encoding="utf-8") as f:
                    json.dump({"unlocked": done, "total": total,
                               "ids": vn_gal.unlocked_ids()}, f,
                              ensure_ascii=False, indent=1)
            except Exception as e:
                vn_log("autopilot gallery dump failed: %s" % e)
        renpy.quit(save=False)


# ── Точка входа ──────────────────────────────────────────────────────────────
# Реплики framework-меток — через vn_loc.t(): литерал в label не попадает
# в PO-экстракцию (леджер собирается только из сцен) и не переводился бы (ADR-0005).
label start:
    $ _chapters = vn_registry.chapters()
    if not _chapters:
        $ renpy.say(None, vn_loc.t("ui.flow.no_content"))
        $ renpy.say(None, vn_loc.t("ui.flow.no_content_hint"))
        return
    # Маршрутизация к entry-сцене первой доступной главы (генерат кладёт метку в реестр).
    $ renpy.jump(_chapters[0]["entry_label"])


# Причина попадания на «сцена недоступна»: draft_todo (ветка ещё не написана),
# missing_content (id из реестра отсутствует в сборке: пак/эпизод не установлен),
# unknown_exit (несовместимый сейв). Выставляется генератом перед jump.
default vn_unavailable_reason = None

label vn_scene_unavailable:
    if vn_qa.autopilot_active():
        $ vn_qa.autopilot_finish("FAIL: vn_scene_unavailable")
    # Гейт нельзя объехать колёсиком (тот же приём, что у version-skew в after_load):
    # rollback увёл бы игрока обратно в состояние, из которого сцена не продолжается.
    $ renpy.block_rollback()
    # Объяснение + выбор действия вместо безусловного выброса в меню: FW-аудит
    # показал, что «сказали и рестартнули» — худший UX этой ситуации.
    call screen vn_content_unavailable(vn_unavailable_reason)
    $ vn_unavailable_reason = None
    $ renpy.full_restart()


label vn_end_of_content:
    if vn_qa.autopilot_active():
        # Экраны меню/галереи снимаются ПЕРЕД выходом: к этому моменту
        # разблокировки уже произошли, и в кадре видно фактическое состояние.
        $ vn_qa.autopilot_screens()
        $ vn_qa.autopilot_finish("OK: vn_end_of_content")
    $ renpy.say(None, vn_loc.t("ui.flow.end_of_content"))
    $ renpy.full_restart()
