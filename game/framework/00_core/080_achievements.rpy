# Достижения (achievements@1): выдача по СТАБИЛЬНЫМ якорям из реестра
# (generated/registry/achievements.gen.rpy), а не по тексту сцен — поэтому
# ачивки добавляются без правки уже написанных и переведённых сцен.
#
# Хранилище — persistent (ачивки не откатываются rollback'ом и переживают
# перезапуск): persistent.vn_achievements = {id: True} (C9: persistent-имена с vn_).
#
# Steam/платформенная синхронизация НЕ здесь: vn_ach.set_provider(fn) — тот же
# приём, что pack_registry.set_ownership_provider (G9). Без провайдера ачивки
# живут локально; подключение платформы не трогает контент-код.

init -980 python in vn_ach:
    from store import renpy, persistent, vn_log

    _provider = None
    _progress_provider = None

    def set_provider(fn):
        """fn(achievement_id) -> None: проброс в платформенный бэкенд (Steam и т.п.).
        Подключается после инициализации платформы, до этого — локальные ачивки."""
        global _provider
        _provider = fn

    def set_progress_provider(fn):
        """fn(achievement_id, complete) -> None: прогресс прогрессивных ачивок в
        платформу (в Steam это попап «N из M» через IndicateAchievementProgress).
        Отдельно от set_provider: выдача и прогресс — разные события бэкенда."""
        global _progress_provider
        _progress_provider = fn

    def _registry():
        return getattr(renpy.store, "VN_ACHIEVEMENTS", {})

    def _unlocked():
        if persistent.vn_achievements is None:
            persistent.vn_achievements = {}
        return persistent.vn_achievements

    def _reported():
        """Последнее значение прогресса, о котором уже сообщили игроку и платформе.
        Старый persistent (до появления прогресса) читается как пустой — сейв и
        persistent прошлых версий обязаны грузиться без ошибок (G5/C9)."""
        if persistent.vn_ach_progress is None:
            persistent.vn_ach_progress = {}
        return persistent.vn_ach_progress

    def goal_of(ach_id):
        """Цель прогрессивной ачивки или None у обычной (бинарной)."""
        return (_registry().get(ach_id) or {}).get("goal")

    def counter(ach_id):
        """Текущий прогресс: значение переменной-счётчика либо ДЛИНА списка —
        в сейве Ren'Py список это естественный способ считать РАЗНЫЕ вещи
        (посещённые сцены, открытые CG), а число — однородные. Значение
        ограничено целью: перебор сверху игроку показывать нечего."""
        goal = goal_of(ach_id)
        if not goal:
            return 0
        value = _var_value(((_registry().get(ach_id) or {}).get("trigger") or {}).get("var"))
        if isinstance(value, (list, tuple, set, dict)):
            value = len(value)
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            value = 0
        return max(0, min(int(value), int(goal["total"])))

    def visible(ach_id):
        """Показывать ли ачивку в UI: NSFW-ачивки скрыты в SFW-сборке, чужие
        паки — по владению (G9)."""
        spec = _registry().get(ach_id)
        if spec is None:
            return False
        build = getattr(renpy.store, "vn_build", None)
        if spec.get("nsfw") and build is not None and not build.nsfw:
            return False
        pack = spec.get("pack", "core")
        return renpy.store.vn.pack_registry.owned(pack)

    def has(ach_id):
        return bool(_unlocked().get(ach_id))

    def grant(ach_id):
        """Выдать достижение (идемпотентно). Неизвестный id — лог, не краш:
        сейв старой версии может ссылаться на удалённую ачивку."""
        spec = _registry().get(ach_id)
        if spec is None:
            vn_log("achievement unknown: %s" % ach_id)
            return False
        if not visible(ach_id):
            return False
        if has(ach_id):
            return False
        _unlocked()[ach_id] = True
        if _provider is not None:
            try:
                _provider(ach_id)
            except Exception as e:
                vn_log("achievement provider failed for %s: %s" % (ach_id, e))
        return True

    def _var_value(ref):
        store_name, _, attr = ref.partition(".")
        store = getattr(renpy.store, store_name, None)
        return getattr(store, attr, None) if store is not None else None

    def _note_progress(ach_id):
        """Обновить прогресс ачивки. Возвращает True, если цель достигнута.

        Порог уведомления (step) считается по УЖЕ сообщённому значению, а не по
        текущему: check() зовётся после каждой смены состояния, и без этого
        игрок получал бы попап на каждый чих."""
        goal = goal_of(ach_id)
        if not goal:
            return False
        value = counter(ach_id)
        total, step = int(goal["total"]), max(1, int(goal.get("step", 1)))
        if value >= total:
            return True
        reported = int(_reported().get(ach_id, 0))
        if value > reported and (value // step) > (reported // step):
            _reported()[ach_id] = value
            if _progress_provider is not None:
                try:
                    _progress_provider(ach_id, value)
                except Exception as e:
                    vn_log("achievement progress provider failed for %s: %s" % (ach_id, e))
        elif value > reported:
            _reported()[ach_id] = value
        return False

    def check(scene_id=None, beat_id=None):
        """Прогон триггеров: зовётся обвязкой сцены (checkpoint), vn.beat и
        после каждой смены состояния. Дёшево: словарь на десятки записей."""
        granted = []
        for ach_id, spec in _registry().items():
            if has(ach_id):
                continue
            trigger = spec.get("trigger") or {}
            hit = False
            if scene_id is not None and trigger.get("scene") == scene_id:
                hit = True
            elif beat_id is not None and trigger.get("beat") == beat_id:
                hit = True
            elif spec.get("goal"):
                # Прогрессивная: цель достигнута — выдаём; иначе сообщаем шаг,
                # но только когда он ПЕРЕСЁК границу step (иначе попап Steam и
                # уведомление игроку дёргались бы на каждой смене состояния).
                hit = _note_progress(ach_id)
            elif "var" in trigger:
                hit = _var_value(trigger["var"]) == trigger.get("equals", True)
            if hit and grant(ach_id):
                granted.append(ach_id)
        return granted

    def names(ids):
        """Локализованные названия по списку id — для уведомления о выдаче.
        Скрытые ачивки к этому моменту уже получены, поэтому раскрывать нечего."""
        reg = _registry()
        return [renpy.store.vn_loc.t((reg.get(i) or {}).get("name_key") or i) for i in ids]

    def all_ids():
        return sorted(_registry())

    # ── Данные для UI ─────────────────────────────────────────────────────────
    # Производные для игрока живут в фасаде, а не в вёрстке: и экран достижений,
    # и пункт рельсы навигации задают ОДИН вопрос — «что показывать игроку», —
    # поэтому ответ существует в одном месте (как vn_gal.items/progress).
    # all_ids() остаётся «всё, что есть в реестре» — платформенная регистрация
    # ачивок в Steam (035_platform.rpy) идёт по нему, а не по видимым.

    def visible_ids():
        """Видимые игроку ачивки в стабильном порядке (по id, как all_ids)."""
        return [ach_id for ach_id in all_ids() if visible(ach_id)]

    def progress():
        """(получено, всего) по ВИДИМЫМ ачивкам. Тотальных чисел нигде не
        хранится — счётчик пересчитывается из реестра (как vn_gal.progress)."""
        ids = visible_ids()
        return sum(1 for ach_id in ids if has(ach_id)), len(ids)

default persistent.vn_achievements = {}
# Сообщённый прогресс прогрессивных ачивок: {id: значение}. Отдельно от
# vn_achievements, чтобы выданное и «докуда дошли» не путались (C9).
default persistent.vn_ach_progress = {}
