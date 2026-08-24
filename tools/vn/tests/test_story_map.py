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
        _write_chapter(root, dirname, spec)
    return _compile(root)


def _write_chapter(root, dirname, spec):
    """Декларации одной синтетической главы. Каталог обязан быть chNN_slug, а имя
    файла сцены — sNNN_slug (слаг не короче трёх символов): и то, и другое —
    настоящие требования компилятора, а не украшение."""
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


def _write_chapters(root, chapters):
    for dirname, spec in chapters.items():
        _write_chapter(root, dirname, spec)


def _compile(root):
    model = build_model(root)
    assert model.errors == [], model.errors
    return ast.literal_eval(re.search(
        r"define VN_FLOW = (\{.*)", emit_flow(model, ""), re.S).group(1).strip())


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


# ── Что показано игроку помимо линий ─────────────────────────────────────────

def test_the_ending_badge_is_gated_by_fog_of_war():
    """Метка «Финал» — только у пройденного узла.

    Метка стояла ВНЕ ветки `if _open`, поэтому карта заранее сообщала, какая из
    закрытых ветвей кончается концовкой: в ch71 это 4 подписи «Финал» на 7 ещё
    не открытых узлов, а в ch73 подписана СЕКРЕТНАЯ концовка s050 — прямая выдача
    того, что игрок должен найти. Проверка текстовая намеренно: движковый экран из
    pytest не поднять, а порядок ветвей проверяется по объявлению."""
    src = (REPO_ROOT / SCREEN_REL).read_text(encoding="utf-8")
    m = re.search(r'^(\s*)if (.+?)_spec\.get\("ending"\)', src, re.M)
    assert m, "ветка метки «Финал» не найдена — экран переписали"
    cond = m.group(0)
    assert "_open" in cond, (
        f"метка «Финал" + '"' + f" вне тумана войны: {cond.strip()!r} — карта выдаёт "
        f"концовки у непройденных узлов")


def test_a_cross_chapter_exit_is_reported_and_is_not_an_ending(tmp_path):
    """Выход в ДРУГУЮ главу: сцена не тупик и не «Финал».

    Межглавные цели компилятор поддерживает штатно (resolve_target), но на карте
    главы целевого узла нет, и ребро молча исчезало: узел без исходящих линий
    читается как тупик, а будучи последним в scene_order он ещё и получал
    ending=True — карта прямо писала «Финал» там, где сюжет продолжается."""
    root = tmp_path / "root"
    _write_chapters(root, {
        "ch67_bridge": {"order": ["s010", "s020"],
                        "scenes": {"s010": {"exits": {"go": "s020"}},
                                   "s020": {"exits": {"next": "ch68/s010"}}}},
        "ch68_target": {"order": ["s010"], "scenes": {"s010": {}}},
    })
    model = build_model(root)
    assert model.errors == [], model.errors
    flow = ast.literal_eval(re.search(
        r"define VN_FLOW = (\{.*)", emit_flow(model, ""), re.S).group(1).strip())

    # Ребро существует и уходит за пределы главы.
    out = [e for e in flow["edges"] if e["from"] == "ch67_s020"]
    assert [e["to"] for e in out] == ["ch68_s010"], out
    # Последняя в scene_order, но НЕ концовка: у неё есть выход.
    assert flow["scenes"]["ch67_s020"]["ending"] is False
    # …а настоящая концовка целевой главы концовкой осталась.
    assert flow["scenes"]["ch68_s010"]["ending"] is True

    store = _story(flow)
    pos = store.layout("ch67", NW, NH, GX, GY)
    assert pos["continues"] == ["ch67_s020"], (
        f"карта не знает, что сцена продолжается в другой главе: {pos['continues']}")
    src = (REPO_ROOT / SCREEN_REL).read_text(encoding="utf-8")
    assert "in continues" in src, "экран не показывает продолжение в другой главе"


def test_a_cluster_backdrop_never_covers_a_foreign_node_synthetically(synthetic):
    """Тот же инвариант на топологии, где ОБЩИЙ bbox его заведомо нарушал:
    кластер из первого и третьего узла цепочки с пропуском — второй узел лежит
    ровно между ними и попадал внутрь рамки целиком."""
    flow = dict(synthetic)
    flow["chapters"] = dict(flow["chapters"])
    flow["chapters"]["ch60"] = dict(flow["chapters"]["ch60"])
    flow["chapters"]["ch60"]["clusters"] = [
        {"title_key": "qa.cluster", "scenes": ["ch60_s010", "ch60_s030"]}]
    store = _story(flow)
    pos = store.layout("ch60", NW, NH, GX, GY)
    boxes = store.cluster_boxes("ch60", pos, NW, NH)
    assert boxes, "подложка кластера не построена"
    x, y = pos["nodes"]["ch60_s020"]
    card = (x, y, x + NW, y + NH)
    for b in boxes:
        box = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
        assert not _overlap(card, box), (
            f"подложка {box} накрывает постороннюю ch60_s020 {card}")
    titled = [b for b in boxes if b["title_key"]]
    assert len(titled) == 1, (
        f"заголовок фазы должен быть один на кластер, а не на колонку: {len(titled)}")
    assert {b["cluster"] for b in boxes} == {"qa.cluster"},         "полоса подложки не называет свой кластер — гард не сможет их разделить"


def test_a_cluster_backdrop_never_covers_a_foreign_node_on_the_shipped_tree(shipped):
    """Тот же инвариант на боевом дереве: у ch70 ДВА кластера, и это единственный
    вход, где их больше одного — именно там ошибка группировки по заголовку и
    видна (полосы соседнего кластера безымянны так же)."""
    store = _story(shipped)
    problems = {}
    for chapter_id in sorted(shipped.get("chapters") or {}):
        spec = shipped["chapters"][chapter_id]
        if not (spec.get("clusters") or []):
            continue
        store._cache.layout = None
        pos = store.layout(chapter_id, NW, NH, GX, GY)
        boxes = store.cluster_boxes(chapter_id, pos, NW, NH)
        for cl in spec["clusters"]:
            members = set(cl.get("scenes") or [])
            mine = [b for b in boxes if b["cluster"] == cl["title_key"]]
            for sid, (x, y) in pos["nodes"].items():
                if sid in members:
                    continue
                card = (x, y, x + NW, y + NH)
                for b in mine:
                    box = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                    if _overlap(card, box):
                        problems.setdefault(chapter_id, []).append(
                            (cl["title_key"], sid))
    assert problems == {}, f"подложка фазы накрывает посторонние сцены: {problems}"


def _fan_with_cluster(members):
    """Веер r -> l0,l1,l2 -> z (три листа в одной колонке) с кластером из
    указанных листьев. Даёт все интересные формы состава: разрыв по рядам,
    разрыв по колонкам и «сверху тесно» — когда над каждым участником стоит
    посторонний."""
    ids = ["ch99_s%03d" % (i * 10) for i in range(5)]
    scenes = {sid: {"chapter": "ch99", "order": i} for i, sid in enumerate(ids)}
    edges = [{"from": ids[0], "to": ids[i], "exit": "e%d" % i, "menu": "m", "idx": i}
             for i in (1, 2, 3)]
    edges += [{"from": ids[i], "to": ids[4], "exit": "done", "menu": None, "idx": None}
              for i in (1, 2, 3)]
    return ids, {"schema": "flow@1", "scenes": scenes, "edges": edges,
                 "chapters": {"ch99": {"clusters": [
                     {"title_key": "qa.shape",
                      "scenes": [ids[i] for i in members]}]}}}


CLUSTER_SHAPES = {
    # Разрыв по РЯДАМ одной колонки: узел ряда 1 лежит между участниками.
    "разрыв по рядам": ([1, 3], [2]),
    # Разрыв по КОЛОНКАМ: вход и сток, между ними вся середина.
    "разрыв по колонкам": ([0, 4], [1, 2, 3]),
    # Сверху тесно: над единственным участником стоит посторонний, поэтому места
    # под заголовок нет ни у кого.
    "сверху тесно": ([2], [1, 3]),
    # Смежные ряды: плашки должны слиться, но не залезть на чужой ряд.
    "смежные ряды": ([1, 2], [3]),
}


@pytest.mark.parametrize("shape", sorted(CLUSTER_SHAPES))
def test_a_cluster_backdrop_never_covers_a_node_outside_the_phase(shape):
    """Подложка фазы не накрывает ни одну постороннюю карточку — ни при какой
    форме состава.

    Любая объединяющая фигура зачисляет в фазу посторонних, а подложка
    непрозрачна и рисуется ПОД узлами: чужая сцена внутри рамки читается как
    часть фазы. Один bbox по крайним участникам ломался на разрыве по колонкам,
    полосы на колонку — на разрыве по рядам, а полоса с заголовком — на «сверху
    тесно», где 34 px под подпись залезали на чужую карточку. Плашка на
    участника с отступом не больше половины зазора ряда закрывает все формы."""
    members, outsiders = CLUSTER_SHAPES[shape]
    ids, flow = _fan_with_cluster(members)
    store = _story(flow)
    pos = store.layout("ch99", NW, NH, GX, GY)
    boxes = store.cluster_boxes("ch99", pos, NW, NH, GY)
    assert boxes, f"{shape}: подложка кластера не построена"
    for i in outsiders:
        x, y = pos["nodes"][ids[i]]
        card = (x, y, x + NW, y + NH)
        for b in boxes:
            box = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
            assert not _overlap(card, box), (
                f"{shape}: подложка {box} накрывает постороннюю {ids[i]} {card}")
    titled = [b for b in boxes if b["title_key"]]
    assert len(titled) <= 1, f"{shape}: заголовков фазы больше одного"
    if shape == "сверху тесно":
        assert titled == [], (
            f"{shape}: заголовок нарисован там, где под него нет места — он "
            f"уедет под чужую карточку")
    else:
        assert len(titled) == 1, f"{shape}: заголовок фазы потерялся"


def test_cluster_padding_cannot_reach_the_neighbouring_row():
    """Отступ подложки ограничен половиной зазора ряда — иначе плашка достаёт до
    соседней карточки в той же колонке. Гейт на СООТНОШЕНИЕ констант: он краснеет
    от правки CLUSTER_PAD или VN_FLOW_GAP_Y, а не от сегодняшних чисел."""
    src = (REPO_ROOT / STORE_REL).read_text(encoding="utf-8")
    m = re.search(r"^\s{4}CLUSTER_PAD = (\d+)$", src, re.M)
    assert m, "CLUSTER_PAD не найден"
    pad = min(int(m.group(1)), (GY - 2) // 2)
    assert 2 * pad <= GY, (
        f"плашка подложки ({NH + 2 * pad} px) не влезает в шаг ряда "
        f"({NH + GY} px) — она накроет соседнюю карточку")


def test_the_entry_node_is_inside_the_first_screen(synthetic):
    """Карта открывается на входном узле, а не в углу полотна.

    Проверяется на веере: полотно там выше видимой области, а колонка входа
    центрируется по вертикали, поэтому вход уезжал за первый экран. Начальное
    смещение считает стор (initial_offset), потому что арифметику в экране
    проверить нечем."""
    view_w, view_h = 1500, 748
    store = _story(synthetic)
    for chapter_id in CHAPTERS_SYNTH + ["ch69"]:
        if chapter_id == "ch69":
            store = _story(_fan_flow(14))
        store._cache.layout = None
        pos = store.layout(chapter_id, NW, NH, GX, GY)
        for zoom in (0.55, 0.75, 1.0):
            x0, y0 = store.initial_offset(pos, 40, view_w, view_h, zoom, NW, NH)
            ex, ey = pos["nodes"][pos["entry"]]
            cx = (ex + NW // 2 + 40) * zoom
            cy = (ey + NH // 2 + 40) * zoom
            assert x0 <= cx <= x0 + view_w, (
                f"{chapter_id} zoom {zoom}: вход по X за первым экраном "
                f"({cx} вне [{x0}, {x0 + view_w}])")
            assert y0 <= cy <= y0 + view_h, (
                f"{chapter_id} zoom {zoom}: вход по Y за первым экраном "
                f"({cy} вне [{y0}, {y0 + view_h}])")


def _fan_flow(leaves):
    """Веер: корень -> N листьев -> сток, плюс сквозное ребро корень->сток."""
    ids = ["ch69_s%03d" % (i * 10) for i in range(leaves + 2)]
    root, sink, mid = ids[0], ids[-1], ids[1:-1]
    scenes = {sid: {"chapter": "ch69", "order": i} for i, sid in enumerate(ids)}
    edges = [{"from": root, "to": m, "exit": "e%d" % i, "menu": "m", "idx": i}
             for i, m in enumerate(mid)]
    edges += [{"from": m, "to": sink, "exit": "done", "menu": None, "idx": None}
              for m in mid]
    edges.append({"from": root, "to": sink, "exit": "skip", "menu": "m",
                  "idx": len(mid)})
    return {"schema": "flow@1", "scenes": scenes, "edges": edges,
            "chapters": {"ch69": {}}}


def test_line_thickness_survives_the_smallest_zoom():
    """Толщина линии не растворяется на самом мелком масштабе.

    Solid покрывает долю min(1, толщина * zoom) физического пикселя, а сглаживания
    у него нет: на 2 виртуальных px и zoom 0.55 это 1.1 — запас 10%. Появление
    пресета мельче 0.5 начнёт съедать рёбра, и карта снова начнёт врать —
    молча, потому что геометрия при этом верна. Гейт держит связь между
    константой стора и списком пресетов экрана."""
    store_src = (REPO_ROOT / STORE_REL).read_text(encoding="utf-8")
    m = re.search(r"^\s{4}SEG = (\d+)$", store_src, re.M)
    assert m, "константа толщины SEG не найдена"
    seg = int(m.group(1))
    screen_src = (REPO_ROOT / SCREEN_REL).read_text(encoding="utf-8")
    z = re.search(r"^define VN_FLOW_ZOOMS = \(([^)]+)\)$", screen_src, re.M)
    assert z, "список масштабов не найден"
    zooms = [float(v) for v in z.group(1).split(",") if v.strip()]
    assert seg * min(zooms) >= 1.0, (
        f"на масштабе {min(zooms)} линия в {seg} px даёт "
        f"{seg * min(zooms):.2f} физического пикселя — рёбра начнут пропадать; "
        f"либо поднимите SEG, либо уберите пресет")


BUDGET_SOLIDS = 400


def test_the_chapter_map_stays_within_the_frame_budget(shipped):
    """Число Solid-ов карты главы в бюджете кадра.

    Каждый сегмент — свой Solid в одном fixed, и цена линейна по числу детей
    (~28 мкс на Solid в замере, то есть порядка 500 на кадр при 60 fps).
    Потолок здесь ниже замера намеренно: карта делит кадр с рельсой, вкладками и
    подвалом плана. Боевые главы сегодня 0..27, так что гейт ловит не сегодняшний
    контент, а главу, которую кто-то напишет: на цепочке из 40 сцен с пятью
    пропусками получается 104, на патологическом веере — за 600."""
    store = _story(shipped)
    heavy = {}
    for chapter_id in sorted(shipped.get("chapters") or {}):
        store._cache.layout = None
        n = len(store.layout(chapter_id, NW, NH, GX, GY)["segments"])
        if n > BUDGET_SOLIDS:
            heavy[chapter_id] = n
    assert heavy == {}, (
        f"карта главы не влезает в бюджет кадра (потолок {BUDGET_SOLIDS} "
        f"Solid-ов): {heavy}")
