# Фасад vn.* — ЕДИНСТВЕННЫЙ API, через который сгенерированный код обращается к движку
# (правило 1.8/3; его api_level проверяют манифесты DLC-паков, раздел 6).

init -999 python in vn:
    from store import renpy, vn_log, vn_registry
    # ВАЖНО: store vn_compat создаётся на init -950 (C8) — позже этого блока,
    # поэтому доступ к нему ТОЛЬКО ленивый, из тел функций (они зовутся в рантайме).

    API_LEVEL = 1

    # ── Обвязка сцен (C15) ───────────────────────────────────────────────────
    def in_replay():
        """Идёт ли реплей сцены из галереи (ADR-0021). Движок изолирует СТОРЫ, но
        не persistent: без этого гейта пересмотр кадра начислял бы достижения,
        открывал галерею и накручивал прогресс главы заново."""
        return bool(getattr(renpy.store, "_in_replay", None))

    def checkpoint(scene_id):
        """Вход в сцену: якорь восстановления позиции сейва (раздел 6) и
        триггер достижений/галереи, привязанных к сцене.

        В реплее (ADR-0021) прогресс не пишется: сцена уже пройдена, и повторный
        просмотр не должен ни выдавать ачивки, ни двигать счётчики."""
        if in_replay():
            renpy.store.vn_scene = scene_id
            return
        renpy.store.vn_scene = scene_id
        # save_name — штатное имя текущего места в игре: движок кладёт его в
        # заголовок сейв-слота И открывает по нему фазу Steam Timeline
        # (config.automatic_steam_timeline, 00steam.rpy: periodic). Значение —
        # локализованный заголовок главы, а не служебный id: и в списке сейвов,
        # и в записи Steam игрок видит человеческий текст.
        renpy.store.save_name = renpy.store.vn_registry.chapter_title(scene_id[:4])
        # Счётчик прохождения: СПИСОК посещённых сцен, а не число — только так
        # повторный вход в сцену не накручивает прогресс, а сейв остаётся из
        # простых типов (G5). Прогрессивные ачивки считают его длину.
        seen = renpy.store.g.scenes_seen
        if scene_id not in seen:
            seen.append(scene_id)
        # Флоучарт (ADR-0021) показывает и то, что игрок видел в ПРОШЛЫХ
        # прохождениях: g.scenes_seen живёт в сейве, поэтому «когда-либо
        # виденное» ведётся рядом в persistent (C9, плоское имя vn_).
        ever = renpy.store.vn_story.ever_seen()
        if scene_id not in ever:
            ever[scene_id] = True
        _progress({"scene_id": scene_id}, {"scene_id": scene_id})

    def beat(beat_id=None):
        """Мелкий якорь внутри сцены: триггер достижений/галереи и точка
        расширения для телеметрии/автотестов (фаза 2)."""
        if beat_id is not None:
            _progress({"beat_id": beat_id}, {"beat_id": beat_id})

    def chapter_done(chapter_id):
        """Глава пройдена: якорь для галереи/достижений «за прохождение».
        Зовётся обвязкой финальной сцены главы (компилятор) и вручную не нужен."""
        _progress({"beat_id": "chapter_done:%s" % chapter_id},
                  {"chapter_done": chapter_id})

    def _progress(ach=None, gal=None):
        """ЕДИНСТВЕННАЯ точка, где якорь превращается в прогресс: выдачу
        достижений, разблокировку галереи и уведомление о них.

        Гейт реплея стоит здесь, а не у каждого якоря по отдельности, и это
        существенно. Движок изолирует СТОРЫ (StoreBackup в call_replay), но не
        persistent — а ачивки и галерея живут именно в нём. Пока гейт стоял
        только в checkpoint, метка chNN_sNNN__replay зовёт не обвязку сцены, а
        сразу её тело, поэтому checkpoint в реплее не вызывается вовсе, зато
        вызывается vn.beat() из тела — и пересмотр кадра выдавал скрытую ачивку
        за ветку, которую игрок не проходил (ch01_s030: `$ vn.beat("roof_alone")`).
        Тем же путём прогресс начислял и гейт `vn test revisit`, который
        проигрывает КАЖДОЕ состояние входа.

        Гейт у якоря — это правило, которое обязан помнить автор нового якоря;
        гейт здесь — свойство конструкции. Структурный гард:
        test_achievements::test_progress_side_effects_go_through_one_replay_gate."""
        if in_replay():
            return
        _notify_progress(renpy.store.vn_ach.check(**(ach or {})),
                         renpy.store.vn_gal.check(**(gal or {})))

    def recheck_triggers():
        """Догон триггеров, привязанных не к якорю, а к ПЕРЕМЕННОЙ.

        Триггеры прогоняются на якорях (checkpoint/beat/chapter_done), а переменная
        может измениться в хвосте сцены — после последнего якоря. Игрок, который
        там сохранился и вышел, иначе получал бы ачивку (и элемент галереи) только
        на входе в следующую сцену следующей сессии: after_load триггеры не гонял.
        Зовётся из label after_load (020_state.rpy) — единственная точка, где
        состояние приходит извне, а не из якоря."""
        _progress()

    def _notify_progress(granted, opened):
        """ОДНО уведомление на тик про ачивки и галерею.

        renpy.notify держит один слот: второй вызов в том же тике прячет экран и
        показывает заново (SDK: display_notify), то есть первый текст игрок не
        увидит вовсе. А ачивка и элемент галереи регулярно открываются одним
        якорем — в 1.0.0 это гарантировано на главном пути (сцена ch01_s030
        открывает и ачивку, и видео галереи). Тост по вёрстке однострочный
        (screen notify), поэтому части идут разделителем, а не переносом."""
        parts = [t for t in (_ach_text(granted), _gallery_text(opened)) if t]
        if parts:
            renpy.notify(" · ".join(parts))

    def _ach_text(granted):
        """Текст о выданном достижении или None. Под Steam попап рисует оверлей,
        но он есть не у всех игроков (standalone, оверлей выключен настройкой), а
        «получил и не заметил» — худший исход для ачивки: она вся про обратную
        связь. Поэтому уведомляем сами, тем же каналом, что и галерея."""
        if not granted:
            return None
        names = renpy.store.vn_ach.names(granted)
        n = len(granted)
        key = "ui.ach.granted_one" if n == 1 else "ui.ach.granted_many"
        text = renpy.store.vn_loc.t(key)
        if n == 1:
            text = text.replace("[name]", names[0])
        else:
            text = text.replace("[n]", str(n))
        return text

    def _gallery_text(opened):
        """Текст о новом материале галереи или None — штатный notify-канал, тот же,
        что у остальных сообщений; своей системы уведомлений не вводим."""
        if not opened:
            return None
        n = len(opened)
        key = "ui.gallery.unlocked_one" if n == 1 else "ui.gallery.unlocked_many"
        text = renpy.store.vn_loc.t(key)
        if n > 1:
            text = text.replace("[n]", str(n))
        return text

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

    def first_entry_label():
        """Метка входа первой доступной главы или None (пустой проект).

        Существует ради ОДНОГО свойства: label start не должен заводить
        store-переменную под копию реестра. `$ _chapters = vn_registry.chapters()`
        клал в дефолтный стор список словарей всех глав, а рантайм-присваивание
        делает переменную корнем сейва навсегда (python.py: ever_been_changed) —
        и реестр уезжал в КАЖДЫЙ сейв игрока. Проверено на фактическом сейве:
        корень `store._chapters` со всем содержимым VN_CHAPTERS. Строка в корнях
        безвредна, реестр — нет: он растёт с каждой главой и с каждым паком."""
        rows = renpy.store.vn_registry.chapters()
        return rows[0]["entry_label"] if rows else None

    def eval_when(expr):
        """Условия переходов из exits: (scene.yaml); здесь — только исполнение.

        Что именно гарантирует сборка (scenes.py: _validate_when): каждое имя вида
        <store>.<имя> объявлено в Variable Registry, свободных имён нет, выражение
        разбирается как Python. ФОРМА не проверяется намеренно — вызовы и
        арифметику компилятор пропускает, потому что подмножество, которое он
        умеет превращать в ограничения графа (ADR-0021 §2), уже множества
        легальных условий.

        Прежняя редакция этого докстринга обещала проверку «против реестра
        переменных» в те времена, когда её не делал никто, — и маскировала дыру:
        опечатка в имени доезжала до игрока NameError'ом в точке перехода между
        сценами."""
        return renpy.python.py_eval(expr)

    # ── Владение паками (G9/C14) ─────────────────────────────────────────────
    class _PackRegistry(object):
        """Гейт владения — ЛОГИЧЕСКИЙ (наличие .rpa ничем не защищено, G9).
        Установленность — пересечение генерата VN_PACKS и поставки сборки
        (vn_build.packs); владение — через провайдера: Steam ownership-check
        подключает set_ownership_provider фасад платформы на init 999
        (035_platform.rpy) — после того, как движок поднял Steam на init -1499.
        Без провайдера установленный пак считается купленным (dev/DRM-free
        поставка, ADR-0014: fail-open)."""

        def __init__(self):
            self._provider = None
            # Ответ провайдера на процесс. Владение DLC без перезапуска Steam не
            # меняется, а сам провайдер подключается один раз на init 999 — то
            # есть сценария «купил, не выходя из игры» тут не было и раньше.
            # Зато цена была: owned() зовётся из visible() КАЖДОГО элемента
            # галереи и КАЖДОЙ ачивки, а visible() — на каждом якоре сцены и на
            # каждой сборке экрана. Под Steam это steam.dlc_installed(), то есть
            # FFI-вызов; на четырёх сотнях элементов выходили тысячи вызовов на
            # один кадр.
            self._owned_cache = {}

        def set_ownership_provider(self, fn):
            self._provider = fn
            self._owned_cache = {}      # сменился источник — кэш недействителен

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
            cached = self._owned_cache.get(pack_id)
            if cached is not None:
                return cached
            if not self.installed(pack_id):
                self._owned_cache[pack_id] = False
                return False
            if self._provider is not None:
                rv = bool(self._provider(pack_id))
            else:
                rv = True
            self._owned_cache[pack_id] = rv
            return rv

    pack_registry = _PackRegistry()


init -999 python in vn_qa:
    import os
    import time
    from store import renpy, vn_log

    _T0 = time.time()    # init-время: точка отсчёта cold start (G19)

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
        chapter = os.environ.get("VN_AUTOPILOT_CHAPTER")
        if chapter:
            # Вход в главу, у которой своя точка входа (эпизод, DLC): без него
            # покрытие ветвления не может быть полным — Start() ведёт только в
            # первую главу реестра, а в остальные никакая последовательность
            # выборов не приводит.
            #
            # Путь ровно тот же, что у игрока: карточка главы делает
            # Start(ch["entry_label"]) (20_ui/components.rpy), а Start — это
            # renpy.jump_out_of_context (SDK 00action_menu.rpy). Своего способа
            # входа автопилот не изобретает: иначе он проверял бы не игру.
            for row in renpy.store.VN_CHAPTERS:
                if row["id"] == chapter:
                    renpy.jump_out_of_context(row["entry_label"])   # не возвращается
            vn_log("autopilot: главы %s нет в реестре — старт по умолчанию" % chapter)

    def autopilot_tour():
        """Список экранов тура: [(имя, kwargs)].

        Два источника, и это не дублирование: VN_AUTOPILOT_SCREENS_FILE (JSON от
        декларации content/ui/screens.yaml, с аргументами экрана) — основной,
        VN_AUTOPILOT_SCREENS=a,b — короткая форма без аргументов, ею пользуются
        ночная джоба и deck-kit."""
        path = os.environ.get("VN_AUTOPILOT_SCREENS_FILE")
        if path:
            try:
                import json
                with open(path, encoding="utf-8") as f:
                    return [(e["name"], e.get("kwargs") or {}) for e in json.load(f)]
            except Exception as e:
                vn_log("autopilot tour file failed: %s" % e)
                return []
        return [(s.strip(), {}) for s in
                os.environ.get("VN_AUTOPILOT_SCREENS", "").split(",") if s.strip()]

    def autopilot_screens():
        """Показать экраны тура и снять по скриншоту каждого.

        Проверка вёрстки меню/галереи в CI: движковый lint не видит визуальных
        поломок, а прохождение сцен эти экраны не открывает. Результат тура пишется
        в screens.json — раньше неудача уходила в vn_log, то есть прогон оставался
        зелёным при экране, который не открылся вовсе."""
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        shown, failed, missing = [], {}, []
        for name, kwargs in autopilot_tour():
            if not renpy.has_screen(name):
                missing.append(name)
                continue
            try:
                renpy.show_screen(name, **kwargs)
                # show_screen лишь помечает экран к показу: кадр рисуется только
                # интеракцией, а screenshot() пишет последний нарисованный кадр.
                # Короткая пауза даёт кадр с уже показанным экраном.
                #
                # modal=False обязателен, и это не перестраховка. Модальный экран
                # ставит ev.modal на TIMEEVENT (layout.check_modal), а
                # PauseBehavior при modal=True такой тик не считает истечением и
                # перевзводит таймаут заново (behavior.py: PauseBehavior.event) —
                # то есть пауза под модалкой не кончается НИКОГДА. Тур на такой
                # модалке вис до убийства по таймауту, и именно поэтому модальные
                # экраны в туре не проверялись вовсе: их либо не заводили, либо
                # им приходилось иметь свой autopilot-таймер. С modal=False тур
                # снимает и модалки — механизм перестал диктовать состав тура.
                renpy.pause(0.3, modal=False)
                if shots_dir:
                    renpy.screenshot(os.path.join(shots_dir, "screen_%s.png" % name))
                renpy.hide_screen(name)
                shown.append(name)
            except Exception as e:
                failed[name] = "%s: %s" % (type(e).__name__, e)
                vn_log("autopilot screen %s failed: %s" % (name, e))
        if shots_dir:
            try:
                import json
                with open(os.path.join(shots_dir, "screens.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({"shown": shown, "failed": failed, "missing": missing,
                               "defined": sorted(renpy.store.vn_compat.defined_screens()
                                                 - {"vn_autopilot"})}, f,
                              ensure_ascii=False, indent=1)
            except Exception as e:
                vn_log("autopilot screens dump failed: %s" % e)

    def autopilot_replays():
        """Прогнать реплей КАЖДОЙ сцены графа во всех объявленных состояниях входа.

        Зачем прогоном, а не проверкой компилятора: прекондиция — это обещание
        «сцена запустится с этим состоянием», и сдержать его может только движок.
        Ошибка внутри реплея (нет переменной, нет ассета, разъехавшийся exit)
        видна лишь здесь. Результат — replays.json, гейт разбирает его в
        `vn test revisit`.

        Реплей не портит основной прогон: движок изолирует сторы (StoreBackup)
        и не пишет прогресс, а config.no_replay_seen = True (100_story_graph.rpy)
        не даёт пересмотру открывать галерею."""
        if not os.environ.get("VN_AUTOPILOT_REPLAYS"):
            return
        shots_dir = os.environ.get("VN_AUTOPILOT_DIR")
        story = renpy.store.vn_story
        done, failed, skipped = [], {}, []
        for sid in sorted(story.scenes()):
            label = story.replay_label(sid)
            if not renpy.has_label(label):
                skipped.append(sid)
                continue
            for i, state in enumerate(story.preconds(sid) or [{}]):
                tag = "%s#%d" % (sid, i)
                try:
                    renpy.call_replay(label, scope=dict(state))
                    done.append(tag)
                except Exception as e:
                    failed[tag] = "%s: %s" % (type(e).__name__, e)
                    vn_log("autopilot replay %s failed: %s" % (tag, e))
        if shots_dir:
            try:
                import json
                with open(os.path.join(shots_dir, "replays.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({"done": done, "failed": failed, "skipped": skipped},
                              f, ensure_ascii=False, indent=1)
            except Exception as e:
                vn_log("autopilot replays dump failed: %s" % e)

    def _peak_rss():
        """{"baseline_rss_mb": <МБ>|None, "why": ...} — пик RSS процесса игры.

        Три источника, потому что единого кроссплатформенного нет:
          * POSIX — resource.getrusage(RUSAGE_SELF).ru_maxrss (macOS отдаёт
            байты, Linux — килобайты; поправка та же, что в corpus.py: _RSS_UNIT);
          * Windows — GetProcessMemoryInfo().PeakWorkingSetSize через ctypes:
            модуля resource там нет, и раньше на этом падал ВЕСЬ блок дампа;
          * иначе — None с причиной.

        None пишется явно, а не «файла нет»: отсутствие файла гейт бюджета
        трактовал как «в рамках», то есть непроверенный бюджет выглядел
        проверенным."""
        import sys as _sys
        if _sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class _PMC(ctypes.Structure):
                    _fields_ = [("cb", wintypes.DWORD),
                                ("PageFaultCount", wintypes.DWORD),
                                ("PeakWorkingSetSize", ctypes.c_size_t),
                                ("WorkingSetSize", ctypes.c_size_t),
                                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                                ("PagefileUsage", ctypes.c_size_t),
                                ("PeakPagefileUsage", ctypes.c_size_t)]

                # argtypes/restype обязательны: без них ctypes считает HANDLE
                # обычным int и на 64-битной Windows усекает его до 32 бит —
                # вызов возвращает 0, то есть «не измерили» вместо числа.
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetCurrentProcess.restype = wintypes.HANDLE
                # K32GetProcessMemoryInfo живёт в kernel32 начиная с Windows 7 и
                # не требует psapi.dll; psapi — запасной путь для старых систем.
                fn = getattr(kernel32, "K32GetProcessMemoryInfo", None)
                if fn is None:
                    fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
                fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
                fn.restype = wintypes.BOOL

                counters = _PMC()
                counters.cb = ctypes.sizeof(_PMC)
                if not fn(kernel32.GetCurrentProcess(), ctypes.byref(counters),
                          counters.cb):
                    return {"baseline_rss_mb": None,
                            "why": "GetProcessMemoryInfo: err %d"
                                   % ctypes.get_last_error()}
                return {"baseline_rss_mb":
                        round(counters.PeakWorkingSetSize / (1024 * 1024), 1)}
            except Exception as e:
                return {"baseline_rss_mb": None, "why": "ctypes: %s" % e}
        try:
            import resource
            unit = 1 if _sys.platform == "darwin" else 1024
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit
            return {"baseline_rss_mb": round(rss / (1024 * 1024), 1)}
        except Exception as e:
            return {"baseline_rss_mb": None, "why": "resource: %s" % e}

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
            try:
                # Пик RSS ИМЕННО процесса игры: снаружи его не измерить точно —
                # renpy.sh это скрипт-обёртка, и getrusage родителя показал бы
                # максимум по дереву.
                #
                # perf.json пишется ВСЕГДА, даже когда измерить нечем: раньше
                # весь блок падал на `import resource` (модуля нет на Windows),
                # файла не появлялось, а гейт бюджета трактует «числа нет» как
                # «в рамках» — то есть бюджет baseline_rss_mb на Windows не
                # проверялся вообще и молчал об этом.
                import json
                with open(os.path.join(shots_dir, "perf.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(_peak_rss(), f, ensure_ascii=False, indent=1)
            except Exception as e:
                vn_log("autopilot perf dump failed: %s" % e)
        renpy.quit(save=False)


# ── Точка входа ──────────────────────────────────────────────────────────────
# Реплики framework-меток — через vn_loc.t(): литерал в label не попадает
# в PO-экстракцию (леджер собирается только из сцен) и не переводился бы (ADR-0005).
label start:
    # Одноразовое значение — СТРОКА, а не список глав: любое присваивание в
    # дефолтный стор становится корнем сейва навсегда, и реестр уезжал бы
    # игроку в каждом файле сохранения (см. vn.first_entry_label).
    $ _entry = vn.first_entry_label()
    if not _entry:
        $ renpy.say(None, vn_loc.t("ui.flow.no_content"))
        $ renpy.say(None, vn_loc.t("ui.flow.no_content_hint"))
        return
    # Маршрутизация к entry-сцене первой доступной главы (генерат кладёт метку в реестр).
    $ renpy.jump(_entry)


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
        # Пересмотр сцен — после тура экранов и до выхода: реплей поднимает
        # свои контексты, и всё, что он мог бы сломать, уже снято.
        $ vn_qa.autopilot_replays()
        $ vn_qa.autopilot_finish("OK: vn_end_of_content")
    $ renpy.say(None, vn_loc.t("ui.flow.end_of_content"))
    $ renpy.full_restart()
