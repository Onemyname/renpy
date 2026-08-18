# Галерея (gallery@1, ADR-0010): состояние разблокировки и прогресс.
# Данные — из generated/registry/gallery.gen.rpy; UI (20_ui/screens/gallery.rpy)
# спрашивает этот стор и НЕ содержит ни списка элементов, ни логики unlock.
#
# Два источника разблокировки, и это осознанно:
#   1) kind: image / kind: shot + unlock.seen_image — ШТАТНЫЙ
#      persistent._seen_images движка. Кадр засчитывается самим фактом показа в
#      сцене, ручного кода нет (обещание раздела 3.7 ARCHITECTURE сохранено).
#   2) остальные якоря (scene/beat/var/chapter_done) и ВИДЕО — движок про них
#      ничего не знает, поэтому ведётся persistent.vn_gallery_unlocked
#      (id -> True; C9: persistent-имена с vn_). Дублирования нет: для картинок
#      с seen_image свой набор не используется.
#
# Идемпотентность: unlock — вставка в dict по стабильному id, повторный вызов
# ничего не меняет и не создаёт дубликатов. Состояние переживает новую игру,
# слоты и перепрохождение (persistent — глобальный), а добавление новых записей
# в будущих версиях просто даёт locked до их открытия: сейв-схема не завязана
# на количество элементов.

init -980 python in vn_gal:
    from store import renpy, persistent, vn_log

    def _registry():
        return getattr(renpy.store, "VN_GALLERY", {})

    def _categories():
        return getattr(renpy.store, "VN_GALLERY_CATEGORIES", {})

    def _store():
        if persistent.vn_gallery_unlocked is None:
            persistent.vn_gallery_unlocked = {}
        return persistent.vn_gallery_unlocked

    def visible(item_id):
        """Показывать ли элемент: NSFW скрыт в SFW-сборке, чужие паки — по
        владению (G9), скрытая категория прячет свои элементы целиком."""
        spec = _registry().get(item_id)
        if spec is None:
            return False
        build = getattr(renpy.store, "vn_build", None)
        cat = _categories().get(spec["category"], {})
        if (spec.get("nsfw") or cat.get("nsfw")) and build is not None and not build.nsfw:
            return False
        return renpy.store.vn.pack_registry.owned(spec.get("pack", "core"))

    def _image_names(spec):
        """Имена образа элемента: текущее + исторические (renames.assets).
        Игрок, увидевший кадр до переименования, не должен терять его в галерее."""
        return [spec["image_name"]] + list(spec.get("image_name_history") or [])

    def _seen_shot(spec):
        """Показывался ли послойный шот. Точным кортежем имени тут не спросить.

        Движок пишет в persistent._seen_images имя образа КАК ПОКАЗАНО (SDK
        renpy/exports/displayexports.py: show), а у шота в это имя попадают ещё и
        липкие атрибуты слоёв: второй `show` того же тега приносит наряд из
        предыдущего кадра, причём порядок таких атрибутов — из множества, то есть
        произвольный (SDK 00layeredimage_ren.py: _choose_attributes). Поэтому
        renpy.seen_image («кортеж целиком») дал бы ложное «закрыто», и шот
        засчитывается по ТЕГУ образа сцены плюс атрибуту шота."""
        seen = getattr(persistent, "_seen_images", None) or {}
        wanted = {}
        for name in _image_names(spec):
            tag, _, attr = name.partition(" ")
            wanted.setdefault(tag, set()).add(attr)
        for key in seen:
            if not isinstance(key, tuple) or not key:
                continue
            attrs = wanted.get(key[0])
            if attrs and attrs.intersection(key[1:]):
                return True
        return False

    def is_unlocked(item_id):
        """Открыт ли элемент. Для кадров с seen_image ответ даёт движок —
        поэтому перепрохождение и старые сейвы работают без миграций."""
        spec = _registry().get(item_id)
        if spec is None or not visible(item_id):
            return False
        unlock = spec.get("unlock") or {}
        if unlock.get("always"):
            return True
        if unlock.get("seen_image"):
            if spec["kind"] == "shot":
                if _seen_shot(spec):
                    return True
            else:
                # image_name — имя образа через пробелы (cg ch01 rooftop_day).
                for name in _image_names(spec):
                    if renpy.seen_image(name):
                        return True
        return bool(_store().get(item_id))

    def unlock(item_id, silent=False):
        """Разблокировать явно (идемпотентно). Возвращает True, только если
        состояние изменилось — на этом строится уведомление."""
        spec = _registry().get(item_id)
        if spec is None:
            vn_log("gallery unknown item: %s" % item_id)
            return False
        if not visible(item_id) or is_unlocked(item_id):
            return False
        _store()[item_id] = True
        if not silent:
            _pending.append(item_id)
        return True

    _pending = []

    def take_pending():
        """Забрать очередь только что открытых элементов (для уведомления)."""
        global _pending
        out, _pending = list(_pending), []
        return out

    def _var_value(ref):
        store_name, _, attr = ref.partition(".")
        store = getattr(renpy.store, store_name, None)
        return getattr(store, attr, None) if store is not None else None

    def check(scene_id=None, beat_id=None, chapter_done=None):
        """Прогон якорей — зовётся из тех же точек, что и достижения
        (vn.checkpoint / vn.beat / завершение главы). Дёшево: десятки записей."""
        opened = []
        for item_id, spec in _registry().items():
            if is_unlocked(item_id):
                continue
            u = spec.get("unlock") or {}
            hit = False
            if scene_id is not None and u.get("scene") == scene_id:
                hit = True
            elif beat_id is not None and u.get("beat") == beat_id:
                hit = True
            elif chapter_done is not None and u.get("chapter_done") == chapter_done:
                hit = True
            elif "var" in u:
                hit = _var_value(u["var"]) == u.get("equals", True)
            if hit and unlock(item_id):
                opened.append(item_id)
        return opened

    # ── Данные для UI ─────────────────────────────────────────────────────────

    def categories():
        """[(id, spec)] в объявленном порядке, только видимые и непустые."""
        out = []
        for cid, spec in _categories().items():
            if not items(cid):
                continue
            out.append((cid, spec))
        return out

    def items(category=None):
        """Элементы категории (или все) в порядке order, chapter, id."""
        rows = [(iid, spec) for iid, spec in _registry().items()
                if visible(iid) and (category is None or spec["category"] == category)]
        rows.sort(key=lambda r: (r[1].get("order", 100),
                                 r[1].get("chapter") or "", r[0]))
        return rows

    def progress(category=None):
        """(открыто, всего) — считается динамически из реестра, вручную
        никакие тотальные числа не хранятся."""
        rows = items(category)
        return sum(1 for iid, _s in rows if is_unlocked(iid)), len(rows)

    def unlocked_ids(category=None):
        return [iid for iid, _s in items(category) if is_unlocked(iid)]

    def looks(spec):
        """Что просмотрщик листает кнопкой «Вариант»: список ссылок для add.

        У плоского ассета это сам кадр и его варианты — отдельные файлы. У
        послойного шота файла нет: «варианты» — комбинации вариантов слоёв, и
        ссылка собирается из имени образа шота плюс по одному атрибуту на слой
        (shot_layers из shots@1). Порядок — одометр по слоям: младший разряд —
        верхний слой, первая комбинация = ровно то, что игрок видел в игре
        (<layer>_auto для гардероба, иначе дефолтный вариант слоя).

        Список отдаётся целиком, потому что экран листает его по индексу: у
        реальных шотов это единицы строк, дерева отображения они не занимают."""
        if spec["kind"] != "shot":
            return [spec["asset"]] + list(spec.get("variants") or [])
        rows = [row["options"] for row in (spec.get("shot_layers") or [])]
        total = 1
        for options in rows:
            total *= len(options)
        out = []
        for i in range(total):
            attrs, rest = [], i
            for options in reversed(rows):
                attrs.insert(0, options[rest % len(options)])
                rest //= len(options)
            out.append(" ".join([spec["asset"]] + attrs))
        return out


default persistent.vn_gallery_unlocked = {}
