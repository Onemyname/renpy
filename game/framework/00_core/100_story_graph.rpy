# Граф истории в рантайме (flow@1, ADR-0021): один стор — три проекции.
#
# Данные приходят готовыми из generated/registry/flow.gen.rpy: узлы и рёбра,
# миры достижимости, принятые решения на пути к каждой сцене, пары
# несовместимых сцен и состояния входа для реплея. Здесь НЕТ ни одного правила
# сюжета — только ответы на вопросы UI:
#   * флоучарт: какие узлы, как связаны, что игрок уже видел, сколько пройдено;
#   * walkthrough: план к выбранным целям и подсветка нужного пункта меню;
#   * реплей: с каким состоянием входить в сцену.
#
# Почему подсказки привязаны к паре (menu_id, индекс), а не к тексту пункта:
# правка формулировки или перевода не должна отвязывать гайд (у референса
# отвязывает — docs/competitive-audit-reclaiming.md §4.2). Индексы устойчивы,
# потому что условные пункты меню запрещены компилятором.

init -980 python in vn_story:
    from store import renpy, persistent, vn_log

    def _flow():
        return getattr(renpy.store, "VN_FLOW", {}) or {}

    def scenes():
        return _flow().get("scenes") or {}

    def edges():
        return _flow().get("edges") or []

    def chapters():
        return _flow().get("chapters") or {}

    def node(scene_id):
        return scenes().get(scene_id)

    # ── Что игрок видел ──────────────────────────────────────────────────────

    def ever_seen():
        """persistent-словарь «сцена когда-либо посещалась» (C9). Ведётся
        vn.checkpoint; в реплее не пишется."""
        if persistent.vn_story_seen is None:
            persistent.vn_story_seen = {}
        return persistent.vn_story_seen

    def seen_now(scene_id):
        """Пройдена в ТЕКУЩЕМ прохождении (данные сейва)."""
        return scene_id in (getattr(renpy.store, "g", None).scenes_seen
                            if hasattr(renpy.store, "g") else [])

    def revealed(scene_id):
        """Показывать содержимое узла или силуэт «???» (fog of war). Открывается
        и прошлым прохождением: игрок не должен терять карту после новой игры."""
        return bool(seen_now(scene_id) or ever_seen().get(scene_id))

    # ── Флоучарт ─────────────────────────────────────────────────────────────

    def chapter_scenes(chapter_id):
        """Узлы главы в объявленном порядке (scene_order)."""
        rows = [(sid, spec) for sid, spec in scenes().items()
                if spec.get("chapter") == chapter_id]
        rows.sort(key=lambda r: (r[1].get("order", 0), r[0]))
        return rows

    def progress(chapter_id):
        """(увидено, всего) по главе — считается из графа, не хранится нигде."""
        rows = chapter_scenes(chapter_id)
        return sum(1 for sid, _s in rows if revealed(sid)), len(rows)

    def layers(chapter_id):
        """Слои узлов слева направо: слой = длина самого долгого пути от входа.
        Ручных координат в декларациях нет и не будет (ADR-0021), поэтому
        геометрию считает алгоритм, а порядок ВНУТРИ слоя берётся из scene_order.

        Что именно устойчиво: порядок внутри слоя и, при неизменном контенте,
        весь результат. Позиция узла — НЕ инвариант, и раньше здесь обещалось
        больше, чем алгоритм даёт. Правка контента карту двигает: вставка сцены в
        цепочку сдвигает всё ниже по потоку на колонку, а появление сквозного
        ребра добавляет ряд в пропущенные колонки (layout ведёт такое ребро
        точками перегиба) и сдвигает карточки по вертикали — в ch01 это 2 узла
        из 3. Плата принята осознанно: без ряда под сквозное ребро развилка на
        карте не отличима от цепочки, и ровно этим карта врала игроку."""
        ids = [sid for sid, _s in chapter_scenes(chapter_id)]
        index = {sid: i for i, sid in enumerate(ids)}
        outgoing = {}
        for e in edges():
            if e["from"] in index and e["to"] in index:
                outgoing.setdefault(e["from"], set()).add(e["to"])
        depth = {sid: 0 for sid in ids}
        # Топологическая релаксация с потолком по числу узлов: цикл в графе не
        # должен вешать экран, поэтому итераций ровно столько, сколько узлов.
        for _ in range(len(ids)):
            changed = False
            for src in ids:
                for dst in outgoing.get(src, ()):  # noqa: SIM118
                    if depth[dst] < depth[src] + 1:
                        depth[dst] = depth[src] + 1
                        changed = True
            if not changed:
                break
        out = {}
        for sid in ids:
            out.setdefault(depth[sid], []).append(sid)
        return [(col, sorted(out[col], key=lambda s: index[s]))
                for col in sorted(out)]

    def cluster_title(scene_id):
        spec = node(scene_id) or {}
        return spec.get("cluster")

    # ── Совместимость целей ──────────────────────────────────────────────────

    def _decision_sets(scene_id):
        return (node(scene_id) or {}).get("decisions") or []

    class _Cache(object):
        """Мемоизация горячего пути: индекс матрицы конфликтов и план прохождений.

        Живёт АТРИБУТАМИ объекта, созданного на init, а не именами стора — и это
        не стиль, а обязательное условие. Рантайм-присваивание имени в сторе
        движок считает изменением и делает имя КОРНЕМ СЕЙВА навсегда
        (renpy/python.py: get_changes -> ever_been_changed; фильтра ни по «_», ни
        по «это named store» там нет), а на загрузке корни пишутся обратно в стор
        безусловно (renpy/rollback.py: unfreeze_core). Проверено дампом
        get_roots(): store.vn_story._conflict_index и _plan_cache лежали в файле
        сейва, а инвалидатора у индекса конфликтов нет вовсе — то есть после
        патча контента загруженный сейв всю сессию подсовывал СТАРУЮ матрицу:
        карта рисовала конфликт, которого в новой сборке нет, plan() делил цели
        на лишние прохождения, а гайд говорил «этот вариант закрывает цель X».

        Образец — vn.pack_registry._owned_cache (030_flow.rpy): имя объекта в
        рантайме не переприсваивается, поэтому в корни сейва не попадает, а сам
        объект из корней недостижим и не сериализуется. При reload скрипта
        разработчиком init исполняется заново и кэш создаётся чистым — отдельный
        инвалидатор для этого не нужен."""

        def __init__(self):
            self.conflicts = None
            self.plan = None        # (ключ, результат)
            self.layout = None      # (ключ, результат)
            # Есть ли на диске превью фона локации: ответ зависит только от
            # файлов, поэтому за сессию не меняется.
            self.loc_thumb = {}

    _cache = _Cache()

    def _conflicts_set():
        """Пары конфликтов как множество — вместо линейного скана списка.

        Список в артефакте — до 4096 пар (потолок compute_compat), а зовут
        compatible() пачками: карточка КАЖДОГО узла спрашивает conflicts() по
        всем целям, план — по каждой паре целей, а подсказка гайда — на КАЖДЫЙ
        пункт меню в точке выбора. Линейный скан там платился в каждом кадре."""
        if _cache.conflicts is None:
            _cache.conflicts = frozenset(
                (x, y) for x, y in (_flow().get("incompatible") or []))
        return _cache.conflicts

    def _drop_plan_cache():
        """Сбрасывается при смене целей — иначе карта перестаёт реагировать на
        отметку цели, а это тише и хуже, чем медленная карта."""
        _cache.plan = None

    def compatible(a, b):
        """Достижимы ли обе сцены в ОДНОМ прохождении. Сначала готовый список
        конфликтов из артефакта, иначе — сверка решений на лету (артефакт мог
        не эмитить матрицу: см. потолок в компиляторе)."""
        pair = tuple(sorted((a, b)))
        if pair in _conflicts_set():
            return False
        da, db = _decision_sets(a), _decision_sets(b)
        if not da or not db:
            return True
        for wa in da:
            for wb in db:
                if all(wb.get(m, i) == i for m, i in wa.items()):
                    return True
        return False

    def conflicts(scene_id, targets):
        """С какими из выбранных целей эта сцена несовместима."""
        return [t for t in targets if t != scene_id and not compatible(scene_id, t)]

    # ── Цели игрока и план ───────────────────────────────────────────────────

    def targets():
        """Список целей (id сцен). persistent: цели живут между прохождениями —
        план на несколько заходов иначе не имеет смысла."""
        if persistent.vn_story_targets is None:
            persistent.vn_story_targets = []
        return persistent.vn_story_targets

    def toggle_target(scene_id):
        rows = targets()
        if scene_id in rows:
            rows.remove(scene_id)
        else:
            rows.append(scene_id)
        _drop_plan_cache()
        return scene_id in rows

    def clear_targets():
        persistent.vn_story_targets = []
        _drop_plan_cache()

    def plan():
        """Разбивка целей на минимальное число прохождений: жадно набираем в
        текущий заход всё, что совместимо со уже набранным. Это шаг вперёд
        относительно референса, где игрок сам догадывается, что две сцены
        несовместимы (docs/competitive-audit-reclaiming.md §4.2).

        Жадность здесь честна: точное разбиение — это раскраска графа
        конфликтов, а на десятках целей разница не наблюдаема, зато порядок
        стабилен и объясним игроку («сначала это, потом то»)."""
        key = tuple(targets())
        if _cache.plan is not None and _cache.plan[0] == key:
            return _cache.plan[1]
        rows = [t for t in targets() if node(t) is not None]
        rows.sort(key=lambda sid: (scenes()[sid].get("chapter"),
                                   scenes()[sid].get("order", 0), sid))
        runs = []
        for sid in rows:
            for run in runs:
                if all(compatible(sid, other) for other in run):
                    run.append(sid)
                    break
            else:
                runs.append([sid])
        # План зовут из подвала карты и из подсказки гайда на КАЖДЫЙ пункт меню,
        # а зависит он только от набора целей — значит считать его в каждом кадре
        # незачем. Ключ — сам набор: сброс по toggle/clear страхует от промаха.
        _cache.plan = (key, runs)
        return runs

    def current_run():
        """Цели текущего прохождения плана (первая группа)."""
        rows = plan()
        return rows[0] if rows else []

    # ── Подсказки в точке выбора ─────────────────────────────────────────────

    def guide_on():
        """Гайд выключен по умолчанию: подсветка «правильного» пункта на первом
        прохождении ломает то, за чем игрок пришёл. Включается в настройках."""
        return bool(persistent.vn_guide)

    def _required_decisions(scene_id):
        """Решения, без которых до сцены не добраться: пересечение всех её миров.
        Именно пересечение, а не объединение: то, что требуется в КАЖДОМ пути."""
        sets = _decision_sets(scene_id)
        if not sets:
            return {}
        common = dict(sets[0])
        for row in sets[1:]:
            common = {m: i for m, i in common.items() if row.get(m) == i}
        return common

    def hint(menu_id):
        """Подсказка для активного меню: (индекс пункта, id цели) или None.

        Причина берётся из графа: пункт нужен, если он входит в требования
        какой-то цели текущего прохождения. Рукописных строк «нужно для X»
        не существует — текст собирает UI из id цели и её заголовка."""
        if not menu_id:
            return None
        for sid in current_run():
            need = _required_decisions(sid)
            if menu_id in need:
                return (need[menu_id], sid)
        return None

    def blocked_targets(menu_id, idx):
        """Какие цели текущего прохождения закроет этот пункт: игрок отклоняется
        от плана — честно сказать об этом, а не молча вести не туда."""
        out = []
        for sid in current_run():
            need = _required_decisions(sid)
            if menu_id in need and need[menu_id] != idx:
                out.append(sid)
        return out

    def guide_note(menu_id, idx):
        """Что сказать про пункт меню: ("goal", текст) — ведёт к цели текущего
        прохождения; ("block", текст) — уводит от неё; None — гайд молчит.

        Обе строки собираются из графа и локализованных заголовков сцен.
        Рукописных «этот вариант нужен для X» в контенте не существует: они
        разъезжаются с историей при первой же правке ветки."""
        if not guide_on() or not menu_id:
            return None
        t = renpy.store.vn_loc.t
        row = hint(menu_id)
        if row and row[0] == idx:
            return ("goal", t("ui.guide.reason").replace(
                "[list]", display_title(row[1])))
        blocked = blocked_targets(menu_id, idx)
        if blocked:
            return ("block", t("ui.guide.blocks").replace(
                "[list]", ", ".join(display_title(s) for s in blocked)))
        return None

    # ── Реплей сцены ─────────────────────────────────────────────────────────

    def preconds(scene_id):
        """Состояния входа в сцену: по одному на класс путей. Из артефакта —
        руками не пишется ничего (у референса это ручной пин переменных, и
        забытый флаг даёт ошибку у игрока)."""
        return (node(scene_id) or {}).get("preconds") or []

    def replay_label(scene_id):
        return "%s__replay" % scene_id

    def can_replay(scene_id):
        """Реплей доступен для пройденной сцены, у которой есть обвязка."""
        return bool(revealed(scene_id) and node(scene_id) is not None
                    and renpy.has_label(replay_label(scene_id)))

    def precond_label(scene_id, variant):
        """Подпись варианта входа. Один вариант — просто «Переиграть»; несколько
        (разные пути дают разный контекст) — с номером и составом состояния, чтобы
        игрок понимал, ЧЕМ они отличаются. Значения — из графа, руками не пишутся."""
        rows = preconds(scene_id)
        t = renpy.store.vn_loc.t
        if len(rows) <= 1:
            return t("ui.chart.replay")
        state = rows[variant] if variant < len(rows) else {}
        detail = ", ".join("%s=%s" % (ref.split(".")[-1], value)
                           for ref, value in sorted(state.items()))
        return "%s %d — %s" % (t("ui.chart.replay_variant"), variant + 1, detail)

    def start_replay(scene_id, variant=0):
        """Запустить реплей сцены в песочнице движка.

        Состояние входа уезжает как scope: call_replay пишет переменные сторов по
        путям «store.var» уже после clean_stores и default-ов (SDK
        renpy/game.py), поэтому своего кода для расстановки состояния не нужно —
        и не должно быть: он бы работал ДО инициализации сторов."""
        rows = preconds(scene_id)
        state = dict(rows[variant]) if variant < len(rows) else {}
        label = replay_label(scene_id)
        if not renpy.has_label(label):
            vn_log("story: нет реплей-метки %s" % label)
            return
        renpy.call_replay(label, scope=state)

    # ── Данные для экрана флоучарта ──────────────────────────────────────────

    def has_chapters():
        """Есть ли хоть одна доступная глава — без построения и сортировки списка
        (тот же гейт рельсы, тот же аргумент)."""
        return any(renpy.store.vn.pack_registry.owned(spec.get("pack") or "core")
                   for spec in chapters().values())

    def chapter_list():
        """Главы, доступные игроку: пак должен быть во владении (G9)."""
        rows = []
        for ch_id, spec in sorted(chapters().items()):
            if not renpy.store.vn.pack_registry.owned(spec.get("pack") or "core"):
                continue
            rows.append((ch_id, spec))
        return rows

    def default_chapter():
        """Глава, открываемая по умолчанию: та, где игрок был последним, иначе
        первая доступная."""
        current = getattr(renpy.store, "vn_scene", None)
        rows = chapter_list()
        if current and any(ch == current[:4] for ch, _s in rows):
            return current[:4]
        return rows[0][0] if rows else None

    def title(scene_id):
        """Заголовок узла: локализованный title_key, иначе сам id (для QA-глав
        это и нужно — id информативнее выдуманного названия)."""
        spec = node(scene_id) or {}
        key = spec.get("title_key")
        return renpy.store.vn_loc.t(key) if key else scene_id

    def display_title(scene_id):
        """Имя узла ДЛЯ ПОКАЗА: заголовок, если сцена уже открыта, иначе «???».

        Единственная функция отображаемого имени во всём UI — и это не удобство,
        а требование тумана войны. Правило соблюдалось в одном месте (карточка
        узла), а план прохождений, список конфликтующих целей и подсказки гайда
        печатали настоящий заголовок НЕПРОЙДЕННОЙ сцены: целью можно отметить
        любой узел, включая закрытый, — и его название тут же выдавалось.
        title() остаётся для мест, где показ безусловен (например, отладка)."""
        return title(scene_id) if revealed(scene_id) else "???"

    def thumb(scene_id):
        """Кадр для карточки узла: элемент галереи, привязанный к этой сцене,
        иначе фон её локации.

        Своего реестра ОТКРЫТИЙ у флоучарта нет и не будет — два источника правды
        про «что игроку уже доступно» разъехались бы (ADR-0010). Но кадр и
        открытие — разные вещи, и на этом месте они были спутаны: отбор шёл по
        `unlock.scene`, то есть по УСЛОВИЮ РАЗБЛОКИРОВКИ, как будто это привязка
        картинки к сцене. Из шести элементов галереи проекта такой якорь ровно у
        одного (видео-луп mov_ch01_ambient -> ch01_s030), поэтому превью могла
        получить единственная сцена игры из двадцати шести — и получала превью
        ВИДЕО, а не свой CG. Остальные карточки оставались пустыми рамками, и
        именно это выглядело как «карта недоделана». Привязки элемента к сцене в
        gallery@1 нет вовсе: элемент объявляется к ГЛАВЕ.

        Поэтому второй источник — локация сцены из её же декларации (scene.yaml:
        `location`, проецируется flow.py). Это не второй реестр открытий: фон
        локации ничего не открывает, а карточка вообще рисуется только для
        revealed(), то есть игрок в этой сцене уже был и этот фон видел.

        Приоритет у галереи: если автор привязал к сцене элемент, показываем его
        (карточка ch01_s030 не меняется). Превью фона берётся, только если
        конвейер его сделал — та же проверка существования, что у превью галереи
        (compile.py: GALLERY_THUMB_SUFFIX), иначе уходит сам образ `bg <loc>
        <вариант>` из images.gen.rpy, который гарантирован сборкой."""
        registry = getattr(renpy.store, "VN_GALLERY", {}) or {}
        for item_id in sorted(registry):
            spec = registry[item_id]
            if (spec.get("unlock") or {}).get("scene") != scene_id:
                continue
            if not renpy.store.vn_gal.is_unlocked(item_id):
                continue
            return spec.get("thumb") or spec.get("asset")
        return location_frame(scene_id)

    def location_frame(scene_id):
        """Кадр локации сцены или None. Отдельной функцией — её же спрашивает
        гард геометрии и она же остаётся точкой расширения, если у сцены появится
        собственный объявленный кадр."""
        loc = (node(scene_id) or {}).get("location")
        if not loc or "/" not in loc:
            return None
        if loc not in _cache.loc_thumb:
            loc_id, _, variant = loc.partition("/")
            small = "assets/bg/%s/%s.thumb.webp" % (loc_id, variant)
            _cache.loc_thumb[loc] = (small if renpy.loadable(small)
                                     else "bg %s %s" % (loc_id, variant))
        return _cache.loc_thumb[loc]

    def _chapter_edges(ids):
        """Рёбра главы в детерминированном порядке.

        Фильтр по составу главы — тот же, что в layers(). Порядок берётся из
        scene_order и адреса пункта меню, а не из порядка списка в артефакте: от
        него зависят разнос веера и номера дорожек, то есть КАРТИНКА, а зависеть
        она обязана только от контента."""
        index = {sid: i for i, sid in enumerate(ids)}
        rows = [e for e in edges() if e["from"] in index and e["to"] in index]
        rows.sort(key=lambda e: (index[e["from"]], index[e["to"]],
                                 e.get("exit") or "", e.get("menu") or "",
                                 -1 if e.get("idx") is None else e["idx"]))
        return rows

    def layout(chapter_id, node_w, node_h, gap_x, gap_y):
        """Полная геометрия карты главы: позиции узлов И сегменты рёбер.

        Раскладка и маршрутизация считаются ОДНИМ проходом, и это условие
        правдивости, а не удобство. Пока их считали раздельно, карта врала
        игроку про структуру: слой узла = длина самого долгого пути от входа,
        поэтому в цепочке с пропуском (s010 -> s020 -> s030 плюс s010 -> s030) в
        каждой колонке оказывался ровно один узел, все узлы стояли на одной
        высоте, а маршрут ребра шёл от середины источника к середине цели.
        Ребро-пропуск рисовалось горизонталью ровно по центрам карточек — то
        есть НАСКВОЗЬ под промежуточной карточкой (рёбра рисуются до узлов), а
        его видимые обрезки ложились точно на коридоры цепочки. Замерено на
        кадре самого движка: в каждом промежутке карты ch01 горела ОДНА строка
        пикселей, а рёбер через промежуток проходило ДВА. Игрок видел прямую
        цепочку и не мог узнать, что из первой сцены есть второй путь. То же
        было в ch73 — QA-главе, заведённой ради этой топологии (ADR-0021
        перечисляет «пропускаемые сцены» среди проверяемых).

        Лечение — классическое для слоевых раскладок: ребро, перепрыгивающее
        колонку, получает в каждой пропущенной колонке ТОЧКУ ПЕРЕГИБА, и точка
        занимает в колонке такой же слот, как карточка. Следствий два, и оба
        нужные: колонка с пропуском становится двухрядной, то есть развилка
        выглядит развилкой, а каждый сегмент лежит в коридоре между колонками,
        где карточек нет по построению. Ширина у точки перегиба та же, что у
        карточки, и это не мелочь: с нулевой шириной её сегмент растягивался на
        всю колонку и излом попадал внутрь чужой карточки — на синтетике это
        давало 9 нарушений инварианта, с шириной карточки 0.

        Ручных координат здесь нет и не появляется (ADR-0021): всё выводится из
        графа и четырёх констант сетки, которые задаёт экран.

        Мемоизация — АТРИБУТОМ объекта _Cache, никогда именем стора: присваивание
        имени стора в рантайме делает имя корнем сейва навсегда (механизм
        расписан в докстринге _Cache). Считать раскладку в каждом кадре нельзя:
        экран зовёт её на каждом обновлении, а маршруты дороже прежнего расчёта.
        """
        key = (chapter_id, node_w, node_h, gap_x, gap_y)
        if _cache.layout is not None and _cache.layout[0] == key:
            return _cache.layout[1]
        cols = layers(chapter_id)
        ids = [sid for _d, col_ids in cols for sid in col_ids]
        rows = _chapter_edges(ids)
        depth = {}
        slots = {}
        for col, (_d, col_ids) in enumerate(cols):
            slots[col] = list(col_ids)
            for sid in col_ids:
                depth[sid] = col
        # Точки перегиба: по одной в каждой пропущенной колонке. Имя включает
        # номер ребра в ОТСОРТИРОВАННОМ списке, поэтому устойчиво между сборками.
        bends = {}
        for k, e in enumerate(rows):
            span = depth[e["to"]] - depth[e["from"]]
            if span <= 1:
                continue
            chain = []
            for col in range(depth[e["from"]] + 1, depth[e["to"]]):
                bid = ("bend", k, col)
                slots[col].append(bid)
                chain.append(bid)
            bends[k] = chain
        ncols = len(cols)
        rows_max = max([len(slots[c]) for c in range(ncols)] or [0])
        nodes, is_bend = {}, {}
        for col in range(ncols):
            items = slots[col]
            offset = (rows_max - len(items)) * (node_h + gap_y) // 2
            for row, sid in enumerate(items):
                nodes[sid] = (col * (node_w + gap_x), offset + row * (node_h + gap_y))
                is_bend[sid] = not isinstance(sid, str)
        block_h = max(rows_max * (node_h + gap_y) - gap_y, node_h)
        # Сколько рёбер у пары: несколько пунктов меню могут вести в одну сцену
        # (в проекте это ch70_s040 -> s050 двумя выходами и ТРИ пункта
        # ch72_s010 -> s020), и без разноса они рисовались одной линией — то
        # есть на карте не было развилки там, где принимается решение.
        pairs = {}
        for k, e in enumerate(rows):
            pairs.setdefault((e["from"], e["to"]), []).append(k)
        # ── Звенья ломаных: сначала собираем ВСЕ, потом рисуем ──────────────
        # Разнос нельзя решить, глядя на одно ребро. У «креста» (две сцены
        # колонки ведут в две сцены следующей — одно меню там, одно тут) все
        # четыре ребра давали РАЗНЫЕ наборы сегментов и при этом НИ ОДНОГО
        # своего пикселя: прямые рёбра целиком накрывались стубами косых, а
        # косые накрывали друг друга, потому что излом у всех стоял на одной
        # середине промежутка. Карта показывала прямоугольник, и какие из
        # четырёх переходов существуют, узнать было нельзя. Поэтому решение о
        # положении излома и о дуге принимается по всему КОРИДОРУ сразу, а
        # годный инвариант — пиксельный: у каждого ребра обязан быть хоть один
        # пиксель, которого не рисует никто другой.
        step = node_w + gap_x
        links, lane_edges = [], []
        for k, e in enumerate(rows):
            src, dst = e["from"], e["to"]
            # Каждое звено называет своё ребро. Экран ключ игнорирует, а гард по
            # нему группирует линии — иначе ему пришлось бы пересказывать
            # раскладку и он проверял бы собственный пересказ.
            mark = (src, dst, pairs[(src, dst)].index(k))
            if depth[dst] <= depth[src]:
                lane_edges.append((mark, src, dst))
                continue
            # Ломаная задаётся ТОЧКАМИ, а точка перегиба даёт их две — свой левый
            # и свой правый край. Иначе линия рвётся ровно на ширину карточки:
            # перегиб невидим, и участок «сквозь» него не рисуется вообще. На
            # карте ch01 это выглядело как два обрубка и две скобки вместо
            # непрерывного объезда — то есть как артефакт отрисовки, а не как
            # второй путь.
            pts = [(nodes[src][0] + node_w, nodes[src][1] + node_h // 2)]
            for bid in bends.get(k, ()):
                bx, by = nodes[bid]
                pts.append((bx, by + node_h // 2))
                pts.append((bx + node_w, by + node_h // 2))
            pts.append((nodes[dst][0], nodes[dst][1] + node_h // 2))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                # Звено «сквозь перегиб» лежит ВНУТРИ колонки (начинается на её
                # левой границе), остальные — в коридоре справа от колонки.
                through = x1 % step == 0
                links.append({"mark": mark, "corridor": None if through else x1 // step,
                              "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        by_corridor = {}
        for ln in links:
            if ln["corridor"] is not None:
                by_corridor.setdefault(ln["corridor"], []).append(ln)
        segments, lanes = [], []
        for ln in links:
            if ln["corridor"] is None:
                segments.append(_seg(ln["x1"], ln["y1"], ln["x2"] - ln["x1"], SEG))
                segments[-1]["edge"] = ln["mark"]
                continue
            group = by_corridor[ln["corridor"]]
            j, m = group.index(ln), len(group)
            x1, y1, x2, y2 = ln["x1"], ln["y1"], ln["x2"], ln["y2"]
            # Свой излом каждому звену коридора: иначе два косых ребра рисуют
            # одну и ту же вертикаль на всю её длину.
            mid = x1 + gap_x * (j + 1) // (m + 1)
            if y1 != y2:
                at = len(segments)
                segments += _elbow(x1, y1, x2, y2, mid)
            else:
                # Прямое звено: если его высоту в этом коридоре занимает ещё
                # кто-то, оно обязано уйти на СВОЙ уровень. Нулевого смещения
                # здесь быть не может — именно оно и делало ребро невидимым.
                touching = [o for o in group
                            if o is not ln and y1 in (o["y1"], o["y2"])]
                at = len(segments)
                if touching:
                    rank = len([o for o in group[:j]
                                if o["y1"] == o["y2"] == y1])
                    off = (rank // 2 + 1) * (gap_y // 2)
                    level = y1 - off if rank % 2 == 0 else y1 + off
                    segments += _bow(x1, y1, x2, y2, gap_x, level)
                else:
                    segments.append(_seg(x1, y1, x2 - x1, SEG))
            for s in segments[at:]:
                s["edge"] = ln["mark"]
        for mark, src, dst in lane_edges:
            at = len(segments)
            segments += _lane_route(nodes, src, dst, node_w, node_h,
                                    gap_x, gap_y, block_h, lanes)
            for s in segments[at:]:
                s["edge"] = mark
        out = {
            "nodes": dict((sid, xy) for sid, xy in nodes.items() if not is_bend[sid]),
            "width": max(ncols * (node_w + gap_x) - gap_x, node_w),
            "height": max([block_h] + [s["y"] + s["h"] for s in segments]),
            "entry": cols[0][1][0] if cols and cols[0][1] else None,
            "segments": segments,
        }
        _cache.layout = (key, out)
        return out

    # Толщина линии ребра в виртуальных пикселях. Не константа экрана: сегменты
    # считает стор, а экран их только рисует.
    SEG = 2

    def _seg(x, y, w, h):
        # Ни один сегмент не тоньше SEG: нулевую высоту даёт любая прямая
        # горизонталь, а Solid нулевого размера движок рисует как ничто.
        return {"x": x, "y": y, "w": max(SEG, w), "h": max(SEG, h)}

    def _elbow(x1, y1, x2, y2, mid):
        """Ортогональный излом: горизонталь, вертикаль на `mid`, горизонталь.
        Излом гарантированно в коридоре между колонками — оба конца лежат на
        границах соседних колонок, потому что пропуски разобраны точками
        перегиба, а `mid` выдаёт коридор, а не середина отрезка: два косых ребра
        на одной середине рисовали одну и ту же вертикаль на всю её длину."""
        out = [_seg(x1, y1, mid - x1, SEG)]
        if y1 != y2:
            out.append(_seg(mid, min(y1, y2), SEG, abs(y2 - y1)))
        out.append(_seg(mid, y2, x2 - mid, SEG))
        return out

    def _bow(x1, y1, x2, y2, gap_x, level):
        """Прямое звено, уведённое на свой уровень в коридоре: так у каждого
        пункта меню и у каждого ребра «креста» есть отрезок, которого не рисует
        никто другой."""
        xa, xb = x1 + gap_x // 3, x2 - gap_x // 3
        return [_seg(x1, y1, xa - x1, SEG),
                _seg(xa, min(y1, level), SEG, abs(level - y1)),
                _seg(xa, level, xb - xa, SEG),
                _seg(xb, min(level, y2), SEG, abs(y2 - level)),
                _seg(xb, y2, x2 - xb, SEG)]

    def _lane_route(nodes, src, dst, node_w, node_h, gap_x, gap_y, block_h, lanes):
        """Ребро, которое НЕ идёт вперёд (цель в той же или в более левой колонке).

        Возможно только при цикле в `exits`; компилятор его пока лишь помечает
        предупреждением. Прежний код рисовал здесь обрубок: `mid = x1 + 24`,
        третий сегмент вырождался в 2 px, и всё это СПРАВА от источника, тогда
        как цель слева. Возврат не был нарисован вовсе, а игрок видел крючок в
        пустоте, утверждающий переход вперёд. Здесь ребро выходит левым краем
        источника, идёт по свободной дорожке ниже всех карточек и входит в цель
        справа."""
        x1 = nodes[src][0]
        y1 = nodes[src][1] + node_h // 2
        x2 = nodes[dst][0] + node_w
        y2 = nodes[dst][1] + node_h // 2
        xa, xb = x1 - gap_x // 3, x2 + gap_x // 3
        lo, hi = min(xa, xb), max(xa, xb)
        lane = block_h + gap_y
        while any(lane == y and lo < b and a < hi for a, b, y in lanes):
            lane += gap_y
        lanes.append((lo, hi, lane))
        return [_seg(xa, y1, x1 - xa, SEG),
                _seg(xa, y1, SEG, lane - y1),
                _seg(lo, lane, hi - lo, SEG),
                _seg(xb, y2, SEG, lane - y2),
                _seg(x2, y2, xb - x2, SEG)]


    # Поля подложки кластера: сверху больше — там живёт его заголовок.
    CLUSTER_PAD = 16
    CLUSTER_TITLE_H = 34

    def cluster_boxes(chapter_id, pos, node_w, node_h):
        """Подложки фаз главы: рамка по узлам кластера. Геометрия выводится из
        раскладки, в декларации кластера только заголовок и состав (ADR-0021)."""
        spec = chapters().get(chapter_id) or {}
        nodes = pos["nodes"]
        out = []
        for cl in spec.get("clusters") or []:
            xs = [nodes[s] for s in cl.get("scenes") or [] if s in nodes]
            if not xs:
                continue
            x0 = min(p[0] for p in xs) - CLUSTER_PAD
            y0 = min(p[1] for p in xs) - CLUSTER_TITLE_H
            x1 = max(p[0] for p in xs) + node_w + CLUSTER_PAD
            y1 = max(p[1] for p in xs) + node_h + CLUSTER_PAD
            out.append({"title_key": cl["title_key"], "x": x0, "y": y0,
                        "w": x1 - x0, "h": y1 - y0})
        return out


default persistent.vn_story_seen = {}
default persistent.vn_story_targets = []
# Встроенный гайд по умолчанию выключен (см. vn_story.guide_on).
default persistent.vn_guide = False


init python:
    # Реплей не должен ничего открывать: движок по умолчанию считает показанные
    # в реплее кадры увиденными (config.no_replay_seen = False), то есть пересмотр
    # сцены открывал бы галерею заново. Прогресс главы и достижения гасит
    # vn.in_replay() в фасаде, кадры — этот флаг (ADR-0021).
    config.no_replay_seen = True
