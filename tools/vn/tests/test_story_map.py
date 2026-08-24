"""Геометрия карты главы (ADR-0021): раскладка узлов и маршруты рёбер.

Зачем отдельный набор. Топология графа проверялась плотно (test_flow.py), а её
ИЗОБРАЖЕНИЕ — ничем: до этого файла в tools/vn/tests не было ни одного
упоминания layers/grid/connectors, то есть класс дефектов «картинка противоречит
графу» не обнаруживался вовсе. И он не был теоретическим: карта ch01 рисовала
прямую цепочку вместо развилки. Слой узла считается как длина самого долгого
пути от входа, поэтому в цепочке с пропуском (s010 -> s020 -> s030 плюс
s010 -> s030) в каждой колонке оказывался ровно один узел, все узлы стояли на
одной высоте, а маршрут ребра шёл от середины источника к середине цели —
значит ребро-пропуск ложилось горизонталью ровно по центрам карточек, то есть
НАСКВОЗЬ под промежуточной. Замер кадра самого движка: в каждом промежутке карты
горела ОДНА строка пикселей, а рёбер через промежуток проходило ДВА. То же было
в ch73 — QA-главе, заведённой ради этой топологии (ADR-0021 перечисляет
«пропускаемые сцены» среди проверяемых), и её никто не рисовал ни в одном гейте.

Почему проверка геометрическая, а не пиксельная: пиксельные эталоны привязаны к
окружению, в котором сняты, и проектом отвергнуты (ADR-0019, докстринг
`vn test screens`). Инвариант же выражается числами и проверяется без движка —
поэтому гоняется на каждом прогоне, а не в canary-джобе.

Проверяемый инвариант: ни один сегмент ребра не заходит внутрь карточки узла,
который этому ребру не принадлежит; у любых двух рёбер линии различимы; маршрут
ребра непрерывен от источника до цели. Топологии собирает НАСТОЯЩИЙ компилятор
из деклараций — мока артефакта здесь нет, иначе тест не доказывал бы, что такой
артефакт вообще бывает.
"""

import ast
import re
import sys
import textwrap
import types
from pathlib import Path

import pytest
import yaml

from vn.content.flow import build_model, emit_flow

from conftest import REPO_ROOT

STORE_REL = "game/framework/00_core/100_story_graph.rpy"
SCREEN_REL = "game/framework/20_ui/screens/story_flow.rpy"


# ── Стор без движка ──────────────────────────────────────────────────────────

def _story(flow, gallery=None, loadable=()):
    """Стор vn_story, исполненный без движка: тело `init python in vn_story` —
    обычный Python, а его внешний мир это persistent, реестры и renpy.loadable.
    Приём принятый в наборе (test_gallery.py::_store_module, test_saves.py,
    test_engine_compat.py): проверяются НАСТОЯЩИЕ функции, а не их пересказ."""
    tail = (REPO_ROOT / STORE_REL).read_text(encoding="utf-8") \
        .partition("python in vn_story:")[2]
    assert tail, f"{STORE_REL}: блок `python in vn_story:` не найден"
    body = []
    for line in tail.splitlines():
        if line.strip() and not line.startswith("    "):
            break                     # блок кончился (default persistent.… и т. п.)
        body.append(line)

    persistent = types.SimpleNamespace(
        vn_story_seen={}, vn_story_targets=[], vn_guide=False)
    renpy_store = types.SimpleNamespace(
        VN_FLOW=flow, VN_GALLERY=dict(gallery or {}),
        vn_gal=types.SimpleNamespace(is_unlocked=lambda item_id: True))
    fake_store = types.ModuleType("store")
    fake_store.persistent = persistent
    fake_store.renpy = types.SimpleNamespace(
        store=renpy_store, loadable=lambda path: path in set(loadable))
    fake_store.vn_log = lambda msg: None
    ns = {}
    sys.modules["store"] = fake_store
    try:
        exec(compile(textwrap.dedent("\n".join(body)), STORE_REL, "exec"), ns)
    finally:
        del sys.modules["store"]
    return types.SimpleNamespace(**ns)


def _grid_constants():
    """Размер карточки и зазоры — из объявлений экрана, а не второй копией здесь:
    расхождение констант сделало бы гард зелёным при съехавшей карте."""
    src = (REPO_ROOT / SCREEN_REL).read_text(encoding="utf-8")
    out = {}
    for name in ("NODE_W", "NODE_H", "GAP_X", "GAP_Y"):
        m = re.search(r"^define VN_FLOW_%s = (\d+)$" % name, src, re.M)
        assert m, f"{SCREEN_REL}: не найдено define VN_FLOW_{name}"
        out[name] = int(m.group(1))
    return out["NODE_W"], out["NODE_H"], out["GAP_X"], out["GAP_Y"]


NW, NH, GX, GY = _grid_constants()


# ── Синтетические топологии: только декларации, компилятор настоящий ─────────

TOPOLOGIES = {
    # Пропуск через одну колонку — форма боевой ch01 и QA-главы ch73.
    "ch60_skip": {
        "order": ["s010", "s020", "s030"],
        "scenes": {"s010": {"exits": {"gate": "s020", "roof": "s030"}},
                   "s020": {"exits": {"roof": "s030"},
                            "location": "school_gate/day"},
                   "s030": {}},
    },
    # Пропуск через три колонки: излом обязан остаться в коридоре и на большом
    # пролёте, а не сползти внутрь чужой карточки.
    "ch61_long": {
        "order": ["s010", "s020", "s030", "s040", "s050"],
        "scenes": {"s010": {"exits": {"go": "s020", "far": "s050"}},
                   "s020": {"exits": {"go": "s030"}},
                   "s030": {"exits": {"go": "s040"}},
                   "s040": {"exits": {"go": "s050"}},
                   "s050": {}},
    },
    # Два выхода в ОДНУ цель: без разноса рисовались одной линией, то есть
    # развилки на карте не было там, где принимается решение. В проекте это
    # ch70_s040 -> s050 (fast/slow) и три пункта ch72_s010 -> s020.
    "ch62_dup": {
        "order": ["s010", "s020"],
        "scenes": {"s010": {"exits": {"fast": "s020", "slow": "s020"}},
                   "s020": {}},
    },
    # Три вложенных пропуска — на них ломался первый вариант лечения (точка
    # перегиба нулевой ширины растягивала свой сегмент на всю колонку).
    "ch63_nested": {
        "order": ["s010", "s020", "s030", "s040", "s050"],
        "scenes": {"s010": {"exits": {"a": "s020", "b": "s030", "c": "s040"}},
                   "s020": {"exits": {"a": "s030", "b": "s050"}},
                   "s030": {"exits": {"a": "s040"}},
                   "s040": {"exits": {"a": "s050"}},
                   "s050": {}},
    },
    # «Крест»: две сцены колонки ведут в две сцены следующей (по меню там и тут).
    # На нём провалился первый вариант инварианта «наборы сегментов различны»:
    # наборы РАЗНЫЕ у всех четырёх рёбер, а своих пикселей нет НИ У ОДНОГО —
    # прямые рёбра целиком накрывались стубами косых, а косые накрывали друг
    # друга, потому что излом у всех стоял на одной середине промежутка. Карта
    # показывала прямоугольник, и какие из четырёх переходов есть, узнать было
    # нельзя. Отсюда и пиксельный инвариант ниже.
    "ch66_cross": {
        "order": ["s010", "s020", "s030", "s040"],
        "scenes": {"s010": {"exits": {"up": "s030", "down": "s040"}},
                   "s020": {"exits": {"up": "s030", "down": "s040"}},
                   "s030": {}, "s040": {}},
    },
    # КОНТРОЛЬ: ромб равной длины. Геометрия была верна и до правки — значит
    # правка не должна её менять.
    "ch64_diamond": {
        "order": ["s010", "s020", "s030", "s040"],
        "scenes": {"s010": {"exits": {"l": "s020", "r": "s030"}},
                   "s020": {"exits": {"m": "s040"}},
                   "s030": {"exits": {"m": "s040"}},
                   "s040": {}},
    },
    # Цикл в exits: единственный источник ребра «не вперёд». Компилятор его
    # принимает, значит карта обязана его нарисовать, а не рисовать обрубок.
    "ch65_cycle": {
        "order": ["s010", "s020", "s030"],
        "scenes": {"s010": {"exits": {"a": "s020"}},
                   "s020": {"exits": {"b": "s030"}},
                   "s030": {"exits": {"back": "s010"}}},
    },
}


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """VN_FLOW синтетического корня, посчитанный настоящим компилятором.

    Авторские `.rpy` не нужны: рёбра карты берутся из `exits` деклараций, а
    пер-пунктовые данные меню (мост, SDK) на геометрию не влияют — поэтому набор
    гоняется без RENPY_SDK, на каждом прогоне."""
    root = tmp_path_factory.mktemp("storymap") / "root"
    for dirname, spec in TOPOLOGIES.items():
        ch_id = dirname[:4]
        d = root / "content" / "chapters" / dirname
        (d / "scenes").mkdir(parents=True)
        (d / "chapter.yaml").write_text(yaml.safe_dump(
            {"schema": "chapter@1", "id": ch_id,
             "title_key": f"meta.chapters.{ch_id}.title", "status": "release",
             "entry_scene": spec["order"][0], "scene_order": spec["order"]},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        (d / "vars.yaml").write_text(yaml.safe_dump(
            {"schema": "vars@1", "store": ch_id, "vars": {}},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        for sid, meta in spec["scenes"].items():
            doc = {"schema": "scene@1", "id": sid}
            doc.update(meta)
            (d / "scenes" / f"{sid}_node.scene.yaml").write_text(yaml.safe_dump(
                doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    model = build_model(root)
    assert model.errors == [], model.errors
    flow = ast.literal_eval(re.search(
        r"define VN_FLOW = (\{.*)", emit_flow(model, ""), re.S).group(1).strip())
    return flow


@pytest.fixture(scope="module")
def shipped():
    """VN_FLOW боевого дерева — если генерат на месте. Синтетика ловит регрессию
    алгоритма, а этот вход ловит «в контенте появилась топология, которой
    алгоритм не умеет»."""
    p = REPO_ROOT / "game" / "generated" / "registry" / "flow.gen.rpy"
    if not p.is_file():
        pytest.skip("генерата нет — прогоните vn build")
    return ast.literal_eval(re.search(
        r"define VN_FLOW = (\{.*)", p.read_text(encoding="utf-8"), re.S).group(1).strip())


# ── Помощники разбора геометрии ──────────────────────────────────────────────

def _rects(segments):
    return [(s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]) for s in segments]


def _overlap(a, b, slack=0):
    """Пересекаются ли прямоугольники (slack>0 — считать касание пересечением)."""
    return (a[0] - slack < b[2] and b[0] - slack < a[2]
            and a[1] - slack < b[3] and b[1] - slack < a[3])


def _connected(rects):
    """Связны ли прямоугольники как множество (касание считается связью)."""
    if not rects:
        return True
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for j in range(len(rects)):
            if j not in seen and _overlap(rects[i], rects[j], slack=1):
                seen.add(j)
                stack.append(j)
    return len(seen) == len(rects)


def _edge_segments(store, chapter_id):
    """Сегменты, разложенные по рёбрам, по ключу `edge` самого сегмента.

    Группировка по ключу, а не пересчётом длин: гард, пересказывающий раскладку,
    проверял бы собственный пересказ."""
    pos = store.layout(chapter_id, NW, NH, GX, GY)
    per_edge = {}
    for s in pos["segments"]:
        assert "edge" in s, "сегмент не называет своё ребро — гард ослеп"
        per_edge.setdefault(s["edge"], []).append(s)
    return pos, per_edge


CHAPTERS_SYNTH = sorted(d[:4] for d in TOPOLOGIES)


@pytest.mark.parametrize("chapter_id", CHAPTERS_SYNTH)
def test_no_edge_segment_is_drawn_under_a_foreign_card(synthetic, chapter_id):
    """Ни один сегмент ребра не заходит внутрь карточки постороннего узла.

    Это и есть тот инвариант, нарушение которого делало развилку невидимой:
    ребро-пропуск шло горизонталью по центрам карточек и его видимые обрезки
    ложились точно на коридоры цепочки, то есть два разных ребра занимали одни
    и те же пиксели."""
    store = _story(synthetic)
    pos = store.layout(chapter_id, NW, NH, GX, GY)
    cards = {sid: (x, y, x + NW, y + NH) for sid, (x, y) in pos["nodes"].items()}
    bad = [(sid, s) for s in pos["segments"] for sid, box in cards.items()
           if _overlap((s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]), box)]
    assert bad == [], (
        f"{chapter_id}: сегменты рёбер под карточками — линия невидима: {bad[:4]}")


def test_no_edge_segment_is_drawn_under_a_foreign_card_on_the_shipped_tree(shipped):
    """То же на боевом дереве: синтетика ловит регрессию алгоритма, а этот вход —
    появление в контенте топологии, которой алгоритм не умеет."""
    store = _story(shipped)
    problems = {}
    for chapter_id in sorted(shipped.get("chapters") or {}):
        store._cache.layout = None
        pos = store.layout(chapter_id, NW, NH, GX, GY)
        cards = {sid: (x, y, x + NW, y + NH) for sid, (x, y) in pos["nodes"].items()}
        bad = [(sid, s) for s in pos["segments"] for sid, box in cards.items()
               if _overlap((s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]), box)]
        if bad:
            problems[chapter_id] = bad[:3]
    assert problems == {}, f"карта врёт про структуру: {problems}"


@pytest.mark.parametrize("chapter_id,skipped", [("ch60", "ch60_s020"),
                                                ("ch61", "ch61_s020")])
def test_a_skipped_scene_gives_its_column_a_second_row(synthetic, chapter_id, skipped):
    """Пропускаемая сцена делает свою колонку МНОГОРЯДНОЙ — то есть развилка
    выглядит развилкой, а не цепочкой.

    Мало нарисовать ребро так, чтобы оно не пряталось: игрок должен увидеть
    ВЕТВЛЕНИЕ. Точка перегиба занимает в пропущенной колонке такой же слот, как
    карточка, поэтому у колонки появляется второй ряд и обход виден как второй
    путь. Без этого узлы остаются на одной высоте и карта читается линейной."""
    store = _story(synthetic)
    pos = store.layout(chapter_id, NW, NH, GX, GY)
    ys = {sid: xy[1] for sid, xy in pos["nodes"].items()}
    assert len(set(ys.values())) > 1, (
        f"{chapter_id}: все узлы на одной высоте — карта читается цепочкой: {ys}")
    # У пропускаемой сцены соседи по потоку стоят НЕ на её высоте: объезд ушёл
    # в свой ряд.
    others = [y for sid, y in ys.items() if sid != skipped]
    assert any(y != ys[skipped] for y in others), ys


def _own_pixels(per_edge):
    """Пиксели, которые рисует ТОЛЬКО это ребро, по каждому ребру."""
    drawn = {}
    for mark, segs in per_edge.items():
        pts = set()
        for s in segs:
            for x in range(s["x"], s["x"] + s["w"]):
                for y in range(s["y"], s["y"] + s["h"]):
                    pts.add((x, y))
        drawn[mark] = pts
    out = {}
    for mark, pts in drawn.items():
        others = set()
        for other, pts2 in drawn.items():
            if other != mark:
                others |= pts2
        out[mark] = pts - others
    return out


@pytest.mark.parametrize("chapter_id", CHAPTERS_SYNTH)
def test_every_edge_has_pixels_nobody_else_draws(synthetic, chapter_id):
    """У каждого ребра есть отрезок, которого не рисует никто другой.

    Инвариант именно пиксельный, и это не педантизм: проверка «наборы сегментов
    различны» его НЕ заменяет. На «кресте» ch66 наборы различны у всех четырёх
    рёбер, а своих пикселей нет ни у одного — прямые рёбра целиком накрываются
    стубами косых. Ребро, у которого нет ни одного своего пикселя, для игрока
    не существует, а карта при этом утверждает связь, которую он не видит.

    Живые случаи того же класса: ch70_s040 -> s050 двумя выходами (fast/slow) и
    ТРИ пункта ch72_s010 -> s020, где выбранная сумма открывает или закрывает
    скрытую сцену."""
    store = _story(synthetic)
    _pos, per_edge = _edge_segments(store, chapter_id)
    mute = [mark for mark, own in _own_pixels(per_edge).items() if not own]
    assert mute == [], (
        f"{chapter_id}: рёбра нарисованы целиком поверх других, игрок их не "
        f"видит: {mute}")


@pytest.mark.parametrize("chapter_id", CHAPTERS_SYNTH)
def test_no_two_edges_share_a_vertical(synthetic, chapter_id):
    """Никакие два ребра не рисуют ОДНУ И ТУ ЖЕ вертикаль.

    Пиксельный инвариант это не покрывает и покрывать не должен: у пересечения
    (ch66) оба косых ребра имели свои горизонтали, но вертикаль — общую, всю её
    длину, потому что излом у всех звеньев коридора стоял на одной середине
    промежутка. Формально каждое ребро видно, а фактически на месте пересечения
    нарисован один провод, и по какой ветке пойдёт игрок, по картинке не
    определить. Поэтому излом выдаётся слотом коридора, а не серединой."""
    store = _story(synthetic)
    _pos, per_edge = _edge_segments(store, chapter_id)
    seen = {}
    for mark, segs in sorted(per_edge.items()):
        for s in segs:
            if s["w"] > s["h"]:
                continue                        # горизонтали делить нормально
            key = (s["x"], s["y"], s["w"], s["h"])
            assert key not in seen, (
                f"{chapter_id}: рёбра {seen[key]} и {mark} рисуют одну вертикаль "
                f"{key} — на пересечении виден один провод вместо двух")
            seen[key] = mark


def test_every_edge_has_its_own_pixels_on_the_shipped_tree(shipped):
    """Тот же пиксельный инвариант на боевом дереве."""
    store = _story(shipped)
    problems = {}
    for chapter_id in sorted(shipped.get("chapters") or {}):
        store._cache.layout = None
        _pos, per_edge = _edge_segments(store, chapter_id)
        mute = [mark for mark, own in _own_pixels(per_edge).items() if not own]
        if mute:
            problems[chapter_id] = mute
    assert problems == {}, f"рёбра без своих пикселей: {problems}"


@pytest.mark.parametrize("chapter_id", CHAPTERS_SYNTH)
def test_every_edge_route_is_continuous_from_source_to_target(synthetic, chapter_id):
    """Маршрут ребра непрерывен и упирается в обе карточки.

    Точка перегиба невидима, и первый вариант лечения рвал линию ровно на её
    ширину: объезд выглядел двумя обрубками и двумя скобками, то есть артефактом
    отрисовки, а не вторым путём. Проверяется связность сегментов как множества
    и касание карточек источника и цели."""
    store = _story(synthetic)
    pos, per_edge = _edge_segments(store, chapter_id)
    for (src, dst, dup), segs in sorted(per_edge.items()):
        rects = _rects(segs)
        assert _connected(rects), (
            f"{chapter_id}: маршрут {src} -> {dst} (#{dup}) разорван: {segs}")
        for end in (src, dst):
            x, y = pos["nodes"][end]
            box = (x, y, x + NW, y + NH)
            assert any(_overlap(r, box, slack=1) for r in rects), (
                f"{chapter_id}: маршрут {src} -> {dst} не доходит до {end}")


def test_a_backward_edge_reaches_its_target(synthetic):
    """Ребро «не вперёд» (цикл в exits) доходит до цели, а не рисуется обрубком.

    Прежний код на этой ветке ставил `mid = x1 + 24`, третий сегмент вырождался в
    2 px, и всё это СПРАВА от источника, тогда как цель слева: возврат не был
    нарисован вовсе, а игрок видел крючок в пустоте, утверждающий переход
    вперёд. Обратных рёбер в контенте пока нет — но компилятор цикл принимает,
    значит вход достижим."""
    store = _story(synthetic)
    pos, per_edge = _edge_segments(store, "ch65")
    back = [(mark, segs) for mark, segs in per_edge.items()
            if pos["nodes"][mark[1]][0] <= pos["nodes"][mark[0]][0]]
    assert back, "синтетика ch65 перестала давать обратное ребро — вход потерян"
    for (src, dst, _dup), segs in back:
        src_x = pos["nodes"][src][0]
        # Ключевое: линия УХОДИТ ВЛЕВО. Прежний код держал все сегменты справа от
        # источника, то есть утверждал переход вперёд — и это ложь, которую
        # проверка «доходит до цели» не поймала бы: обрубок формально лежал в
        # промежутке. Стрелок на карте нет, направление читается только по
        # «слева направо», поэтому сторона выхода и есть направление.
        assert min(s["x"] for s in segs) < src_x, (
            f"возврат {src} -> {dst} нарисован справа от источника — линия "
            f"утверждает переход ВПЕРЁД: {segs}")
        # И упирается в ПРАВЫЙ край цели, а не обрывается в промежутке.
        dst_right = pos["nodes"][dst][0] + NW
        assert any(s["x"] <= dst_right <= s["x"] + s["w"] + 1 for s in segs), (
            f"возврат {src} -> {dst} не доходит до правого края цели "
            f"({dst_right}): {segs}")
    # Дорожка возврата уходит НИЖЕ блока карточек — там карточек нет по построению.
    block_h = max(y + NH for _x, y in pos["nodes"].values())
    assert any(s["y"] >= block_h for s in pos["segments"]), \
        "дорожка возврата не вышла из полосы карточек"


def test_layout_is_memoized_and_lives_on_the_cache_object(synthetic):
    """Раскладка считается один раз на ключ, и кэш — АТРИБУТ объекта.

    Экран зовёт layout() на каждом обновлении, а маршруты дороже прежнего
    расчёта. При этом кэш нельзя держать именем стора: рантайм-присваивание
    имени делает его корнем сейва навсегда (renpy/python.py: get_changes ->
    ever_been_changed), и ровно этот класс уже закрывали для матрицы конфликтов
    и плана прохождений."""
    store = _story(synthetic)
    first = store.layout("ch60", NW, NH, GX, GY)
    assert store.layout("ch60", NW, NH, GX, GY) is first, "раскладка не мемоизирована"
    # Другой ключ — другой результат, старый не выдаётся.
    other = store.layout("ch61", NW, NH, GX, GY)
    assert other is not first
    src = (REPO_ROOT / STORE_REL).read_text(encoding="utf-8")
    assert "self.layout = None" in src, "кэш раскладки не объявлен атрибутом _Cache"
    assert not re.search(r"^\s{4}_layout_cache\s*=", src, re.M), \
        "кэш раскладки переехал в имя стора — это корень сейва навсегда"


# ── Кадр карточки ────────────────────────────────────────────────────────────

def test_scene_location_reaches_the_flow_artifact(synthetic):
    """`location` сцены доезжает до рантайма.

    Без этого карточка узла не имеет ни одного источника кадра, кроме элемента
    галереи с якорем `unlock.scene` — а такой якорь в проекте ровно один, то
    есть превью могла получить единственная сцена из двадцати шести."""
    assert synthetic["scenes"]["ch60_s020"].get("location") == "school_gate/day"
    assert synthetic["scenes"]["ch60_s010"].get("location") is None


def test_node_frame_falls_back_to_the_scene_location(synthetic):
    """Кадр карточки: элемент галереи с якорем на сцену, иначе фон её локации.

    Приоритет у галереи — привязку автор сделал осознанно. Локация — второй
    источник КАДРА, но не второй реестр ОТКРЫТИЙ (ADR-0010): карточка рисуется
    только для пройденной сцены, то есть этот фон игрок уже видел."""
    small = "assets/bg/school_gate/day.thumb.webp"
    store = _story(synthetic, loadable=[small])
    assert store.thumb("ch60_s020") == small, "превью локации не подхвачено"
    assert store.thumb("ch60_s010") is None, "кадр взялся из ниоткуда"

    # Превью конвейер мог не сделать — тогда уходит сам образ из images.gen.rpy.
    bare = _story(synthetic)
    assert bare.thumb("ch60_s020") == "bg school_gate day"

    # Элемент галереи с якорем на сцену перебивает локацию.
    gal = {"mov": {"unlock": {"scene": "ch60_s020"},
                   "thumb": "assets/cg/x.thumb.webp"}}
    withgal = _story(synthetic, gallery=gal, loadable=[small])
    assert withgal.thumb("ch60_s020") == "assets/cg/x.thumb.webp"


def test_the_screen_draws_the_routes_the_store_computed(synthetic):
    """Экран не считает геометрию сам: он рисует `segments` из layout().

    Пока экран звал layers/grid/connectors по отдельности, маршрут ребра
    вычислялся БЕЗ знания раскладки — отсюда и брались линии под карточками.
    Гард текстовый намеренно: движковый экран из pytest не поднять, а факт
    «геометрия в одном месте» проверяется по объявлениям."""
    src = (REPO_ROOT / SCREEN_REL).read_text(encoding="utf-8")
    assert "vn_story.layout(" in src, "экран не зовёт единую раскладку"
    for gone in ("vn_story.grid(", "vn_story.connectors(", "vn_story.layers("):
        assert gone not in src, (
            f"{SCREEN_REL}: {gone} вернулся — геометрия снова считается в двух "
            f"местах, и маршрут опять не знает раскладки")
    assert '_pos["segments"]' in src, "экран рисует не те сегменты"
