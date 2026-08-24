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

    # ── Кэши горячего пути ───────────────────────────────────────────────────
    # Живут ПРОЦЕСС, а не сейв — и теперь это действительно так. Прежняя редакция
    # утверждала то же самое, но имена переприсваивались в рантайме через global
    # из выражения экрана галереи, а рантайм-присваивание имени в сторе движок
    # считает изменением и делает имя КОРНЕМ СЕЙВА навсегда (renpy/python.py:
    # get_changes -> ever_been_changed), после чего на загрузке корень пишется в
    # стор безусловно (renpy/rollback.py: unfreeze_core). Проверено сканом
    # реальных файлов: store.vn_gal._seen_index_cache и _seen_index_len лежали во
    # ВСЕХ автосейвах. Persistent авторы обошли сознательно, а кэш уехал в сейв —
    # что хуже: persistent хотя бы не подменяется снапшотом из чужого файла.
    #
    # Почему это опасно, а не только некрасиво. Единственная проверка валидности
    # индекса — равенство len(persistent._seen_images) сохранённой длине. Посылка
    # «ключ может быть только добавлен» верна в пределах ОДНОГО процесса (движок
    # из _seen_images не удаляет), но восстановленный из сейва индекс — снапшот
    # ЧУЖОГО persistent, и равенство длин про совпадение содержимого не говорит
    # ничего. Шаринг сейва «со всеми CG» — штатный канал в VN-сообществах.
    # Второе: каждая перестройка индекса кладёт полную предыдущую копию в запись
    # rollback-лога, а он весь пишется в файл — на целевом масштабе (десятки
    # тысяч ключей, см. докстринг _seen_index) это мегабайты в каждом слоте.
    #
    # Поэтому кэш — атрибуты объекта, созданного на init: имя _cache в рантайме
    # не переприсваивается, значит в корни сейва не попадает (тот же приём, что у
    # vn.pack_registry._owned_cache). Класс — наследник ОБЫЧНОГО python-object, а
    # не store-object: в сторе имя `object` подменено на RevertableObject
    # (renpy/minstore.py), и мутация его атрибутов попадала бы в rollback-лог.
    # Кэшу участие в rollback не нужно и вредно: он пересчитывается сам.
    import builtins as _builtins

    class _Cache(_builtins.object):

        def __init__(self):
            self.seen_index = None   # {тег: [frozenset(атрибуты), ...]}
            self.seen_len = -1       # по чему инвалидируем: размер _seen_images
            self.unlocked = {}       # item_id -> True (разблокировка монотонна)

    _cache = _Cache()

    def _seen_index():
        """Индекс показанных кадров по ТЕГУ образа.

        Без него _seen_shot линейно сканировал весь persistent._seen_images, а
        ранний выход там есть только при попадании — то есть для ЗАКРЫТОГО шота
        (а закрытым он остаётся почти всю игру) цена равна размеру словаря.
        Множитель сверху двойной: is_unlocked зовётся из vn_gal.check на каждом
        якоре сцены И из экрана галереи по ~2 раза на элемент при каждой сборке
        экрана, а SL2 пересобирает экран на каждой интеракции — то есть на каждом
        движении мыши по сетке.

        Размер _seen_images растёт не по числу файлов, а по числу РАЗЛИЧНЫХ
        комбинаций атрибутов: движок пишет имя КАК ПОКАЗАНО, с липкими
        атрибутами, а у layeredimage это резолвнутый набор всех слоёв — на
        целевом масштабе это десятки тысяч ключей.

        Инвалидация по длине: ключ может быть только добавлен (движок никогда не
        удаляет из _seen_images), поэтому длина — точный признак изменения."""
        seen = getattr(persistent, "_seen_images", None) or {}
        if _cache.seen_index is not None and len(seen) == _cache.seen_len:
            return _cache.seen_index
        index = {}
        for key in seen:
            if isinstance(key, tuple) and key:
                index.setdefault(key[0], []).append(frozenset(key[1:]))
        _cache.seen_index = index
        _cache.seen_len = len(seen)
        return index

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
        засчитывается по ТЕГУ образа сцены плюс атрибутам шота — как ПОДМНОЖЕСТВО
        показанного имени: свои атрибуты обязаны быть все, лишние (липкие от
        предыдущего кадра) не мешают. Подмножество, а не пересечение по склеенной
        строке: имя из двух и более атрибутов иначе не совпало бы никогда, то есть
        такой элемент навсегда остался бы «закрыт» у игрока, который кадр видел."""
        index = _seen_index()
        for name in _image_names(spec):
            parts = name.split()
            if len(parts) < 2:
                continue      # тег без атрибутов: «видел любой кадр тега» — не открытие
            wanted = frozenset(parts[1:])
            # Смотрим только кадры СВОЕГО тега, а не весь словарь увиденного.
            for shown in index.get(parts[0], ()):
                if wanted.issubset(shown):
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
        # Разблокировка монотонна в пределах процесса: открытый элемент закрыться
        # уже не может. Кэш снимает повторный опрос движка на каждой перерисовке
        # сетки — но НЕ в persistent: запись оттуда шла бы из выражения экрана.
        if _cache.unlocked.get(item_id):
            return True
        if unlock.get("seen_image"):
            if spec["kind"] == "shot":
                if _seen_shot(spec):
                    _cache.unlocked[item_id] = True
                    return True
            else:
                # image_name — имя образа через пробелы (cg ch01 rooftop_day).
                for name in _image_names(spec):
                    if renpy.seen_image(name):
                        _cache.unlocked[item_id] = True
                        return True
        if _store().get(item_id):
            _cache.unlocked[item_id] = True
            return True
        return False

    def unlock(item_id):
        """Разблокировать явно (идемпотентно). Возвращает True, только если
        состояние изменилось: на возвращаемом значении и строится уведомление
        (check -> vn._gallery_notify) — второй, отложенной очереди для этого нет."""
        spec = _registry().get(item_id)
        if spec is None:
            vn_log("gallery unknown item: %s" % item_id)
            return False
        if not visible(item_id) or is_unlocked(item_id):
            return False
        _store()[item_id] = True
        return True

    def _var_value(ref):
        store_name, _, attr = ref.partition(".")
        store = getattr(renpy.store, store_name, None)
        return getattr(store, attr, None) if store is not None else None

    def check(scene_id=None, beat_id=None, chapter_done=None):
        """Прогон якорей — зовётся из тех же точек, что и достижения
        (vn.checkpoint / vn.beat / завершение главы) плюс догоном после загрузки
        (vn.recheck_triggers). Дёшево: десятки записей."""
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

    def has_visible():
        """Есть ли хоть один видимый элемент — БЕЗ построения и сортировки списков.

        Рельса навигации гейтит пункт «Галерея» этим вопросом, а спрашивала его
        через categories(), который на каждую категорию звал items(), а тот
        фильтровал и СОРТИРОВАЛ весь реестр. Рельсу рисует каркас vn_game_menu,
        то есть КАЖДЫЙ экран игрового меню, и на предикции ShowMenu тоже —
        полный обход реестра платился там, где нужен ответ «да/нет»."""
        return any(visible(iid) for iid in _registry())

    def overview():
        """Всё, что нужно экрану галереи, за ОДИН проход по реестру.

        Экран пересчитывал производные заново на каждой сборке: categories()
        (внутри items() на каждую категорию), progress() по всем, progress(cid)
        в цикле по вкладкам, items(_cur) и is_unlocked в каждой ячейке — итого
        порядка (2·Nкатегорий + 2) проходов visible() и ~2N вызовов is_unlocked.
        А SL2 пересобирает экран на каждой интеракции и на каждом
        restart_interaction, то есть на каждом движении мыши по сетке.

        Возвращает {"cats": [(id, spec, открыто, всего)], "done", "total",
        "by_cat": {id: [(item_id, spec)]}, "open": {item_id: bool}}."""
        by_cat, opened = {}, {}
        for iid, spec in items():
            by_cat.setdefault(spec["category"], []).append((iid, spec))
            opened[iid] = is_unlocked(iid)
        cats = []
        for cid, cspec in _categories().items():
            rows = by_cat.get(cid) or []
            if not rows:
                continue        # пустая категория во вкладках не показывается
            cats.append((cid, cspec, sum(1 for i, _s in rows if opened[i]), len(rows)))
        return {"cats": cats, "by_cat": by_cat, "open": opened,
                "done": sum(1 for v in opened.values() if v), "total": len(opened)}

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
