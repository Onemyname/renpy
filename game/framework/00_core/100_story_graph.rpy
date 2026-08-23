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
        """Раскладка узлов по колонкам слева направо: слой = длина самого долгого
        пути от входа. Ручных координат в декларациях нет и не будет (ADR-0021),
        поэтому геометрию считает алгоритм, а порядок внутри слоя берётся из
        scene_order — так узлы не прыгают между сборками."""
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

    def compatible(a, b):
        """Достижимы ли обе сцены в ОДНОМ прохождении. Сначала готовый список
        конфликтов из артефакта, иначе — сверка решений на лету (артефакт мог
        не эмитить матрицу: см. потолок в компиляторе)."""
        pair = sorted((a, b))
        for x, y in _flow().get("incompatible") or []:
            if [x, y] == pair:
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
        return scene_id in rows

    def clear_targets():
        persistent.vn_story_targets = []

    def plan():
        """Разбивка целей на минимальное число прохождений: жадно набираем в
        текущий заход всё, что совместимо со уже набранным. Это шаг вперёд
        относительно референса, где игрок сам догадывается, что две сцены
        несовместимы (docs/competitive-audit-reclaiming.md §4.2).

        Жадность здесь честна: точное разбиение — это раскраска графа
        конфликтов, а на десятках целей разница не наблюдаема, зато порядок
        стабилен и объясним игроку («сначала это, потом то»)."""
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
            return ("goal", t("ui.guide.reason").replace("[list]", title(row[1])))
        blocked = blocked_targets(menu_id, idx)
        if blocked:
            return ("block", t("ui.guide.blocks").replace(
                "[list]", ", ".join(title(s) for s in blocked)))
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

    def thumb(scene_id):
        """Превью узла — из галереи, если её элемент привязан к этой сцене и уже
        открыт. Своего реестра картинок у флоучарта нет: два источника правды на
        один кадр разъехались бы (ADR-0010)."""
        registry = getattr(renpy.store, "VN_GALLERY", {}) or {}
        for item_id in sorted(registry):
            spec = registry[item_id]
            if (spec.get("unlock") or {}).get("scene") != scene_id:
                continue
            if not renpy.store.vn_gal.is_unlocked(item_id):
                continue
            return spec.get("thumb") or spec.get("asset")
        return None

    def grid(cols, node_w, node_h, gap_x, gap_y):
        """Координаты узлов: колонка = слой графа, ряд = порядок в scene_order.
        Колонки центрируются по вертикали — так ромб выглядит ромбом."""
        rows_max = max([len(ids) for _d, ids in cols] or [0])
        nodes = {}
        for col, (_depth, ids) in enumerate(cols):
            offset = (rows_max - len(ids)) * (node_h + gap_y) // 2
            for row, sid in enumerate(ids):
                nodes[sid] = (col * (node_w + gap_x), offset + row * (node_h + gap_y))
        entry = cols[0][1][0] if cols and cols[0][1] else None
        return {
            "nodes": nodes,
            "width": max(len(cols) * (node_w + gap_x) - gap_x, node_w),
            "height": max(rows_max * (node_h + gap_y) - gap_y, node_h),
            "entry": entry,
        }

    def connectors(chapter_id, pos, node_w, node_h):
        """Ортогональные линии рёбер: горизонталь от правого края узла, вертикаль
        по середине промежутка, горизонталь до левого края цели. Такой же излом,
        как на референсе; рисуется Solid-ами, бинарных ассетов у UI нет."""
        nodes = pos["nodes"]
        out = []
        for e in edges():
            a, b = nodes.get(e["from"]), nodes.get(e["to"])
            if a is None or b is None:
                continue
            x1, y1 = a[0] + node_w, a[1] + node_h // 2
            x2, y2 = b[0], b[1] + node_h // 2
            mid = (x1 + x2) // 2 if x2 > x1 else x1 + 24
            out.append({"x": x1, "y": y1, "w": max(2, mid - x1), "h": 2})
            top, bottom = min(y1, y2), max(y1, y2)
            if bottom > top:
                out.append({"x": mid, "y": top, "w": 2, "h": bottom - top})
            out.append({"x": mid, "y": y2, "w": max(2, x2 - mid), "h": 2})
        return out

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
