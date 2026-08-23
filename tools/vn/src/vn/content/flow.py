"""Скомпилированный граф истории (ADR-0021): одна модель — три проекции.

Флоучарт главы, встроенный walkthrough и реплей сцены отвечают на один вопрос —
как устроен граф и где в нём игрок, — поэтому руками не ведётся ничего: ни
списки конфликтующих целей, ни переменные для входа в реплей, ни привязка
подсказок к пунктам меню. Всё выводится здесь и валидируется на сборке.

Два источника, оба уже есть в конвейере:
  * декларации — `graph.build_edges()` (сцены, exits, when, цели) и `vars@1`
    (типы и значения по умолчанию);
  * AST авторских сцен — build-bridge (какой пункт меню какой exit возвращает
    и что он присваивает). Без него модель строится в неполном режиме: рёбра
    известны, авторство выбора — нет.

Достижимость считается СВЕРХУ (over-approximation): порядок прохождения внутри
мира не моделируется, приоритет условных exits не отрицается. Следствие выбрано
осознанно (ADR-0021 §3): «несовместимы» говорится только про доказанное
противоречие ограничений, поэтому красным в UI помечается лишь настоящий
конфликт, а ложно-зелёное лечится пересчётом плана по ходу.
"""

from __future__ import annotations

import ast as pyast
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..repo import chapter_zones, load_yaml
from .compile import CHAPTER_DIR_RE, SCENE_YAML_RE
from .graph import build_edges
from .scenes import LABEL_RE, _literal_exit, menu_id_of

# Сколько миров достижимости держим на сцену. Слияние ветвей размножает миры
# произведением, поэтому потолок обязателен: при переполнении лишние ограничения
# ослабляются (widening) — модель остаётся корректной сверху, теряя точность.
FLOW_MAX_WORLDS = 32

# Потолок на дизъюнкцию, в которую разворачивается одно условие `when`.
FLOW_MAX_TERMS = 16


class FlowError(RuntimeError):
    pass


# ── Ограничения на переменную ────────────────────────────────────────────────

@dataclass(frozen=True)
class Constraint:
    """Ограничение на ОДНУ переменную. Ровно одна из двух форм:

    * `allow` — множество разрешённых литералов (bool, строки, перечисления чисел);
    * `lo`/`hi` — замкнутый числовой интервал (None = без границы).

    Пустое `allow` или `lo > hi` — противоречие: мир с таким ограничением
    недостижим. Обе формы намеренно примитивны: домены здесь крошечные (флаги,
    единицы литералов, пороги), а читаемость артефакта в диффе важнее общности
    (ADR-0021: BDD/SAT отвергнуты)."""

    allow: frozenset | None = None
    lo: float | None = None
    hi: float | None = None

    def is_empty(self) -> bool:
        if self.allow is not None:
            return not self.allow
        if self.lo is not None and self.hi is not None:
            return self.lo > self.hi
        return False

    def intersect(self, other: "Constraint") -> "Constraint":
        if self.allow is not None and other.allow is not None:
            return Constraint(allow=self.allow & other.allow)
        if self.allow is not None or other.allow is not None:
            allow_side = self if self.allow is not None else other
            range_side = other if self.allow is not None else self
            kept = frozenset(v for v in allow_side.allow
                             if _in_range(v, range_side.lo, range_side.hi))
            return Constraint(allow=kept)
        lo = max([v for v in (self.lo, other.lo) if v is not None], default=None)
        hi = min([v for v in (self.hi, other.hi) if v is not None], default=None)
        return Constraint(lo=lo, hi=hi)

    def witness(self, default):
        """Детерминированный представитель значения — для прекондиций реплея.
        `default` из vars@1 берётся, если он сам проходит ограничение: так
        состояние входа отличается от прохождения игрока минимально."""
        if self.allow is not None:
            if default in self.allow:
                return default
            return sorted(self.allow, key=_sort_key)[0] if self.allow else None
        if _in_range(default, self.lo, self.hi):
            return default
        if self.lo is not None:
            return int(self.lo) if float(self.lo).is_integer() else self.lo
        if self.hi is not None:
            return int(self.hi) if float(self.hi).is_integer() else self.hi
        return default

    def as_data(self) -> dict:
        if self.allow is not None:
            return {"allow": sorted(self.allow, key=_sort_key)}
        out: dict = {}
        if self.lo is not None:
            out["lo"] = self.lo
        if self.hi is not None:
            out["hi"] = self.hi
        return out


def _sort_key(value):
    """Устойчивый порядок для смеси типов: артефакт обязан быть детерминированным."""
    return (type(value).__name__, str(value))


def _in_range(value, lo, hi) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return lo is None and hi is None
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


# ── Мир: конъюнкция ограничений ──────────────────────────────────────────────

World = dict            # var -> Constraint; отсутствие ключа = без ограничений

# Помимо переменных мир несёт ПРИНЯТЫЕ РЕШЕНИЯ — пункты меню, выбранные на пути
# к сцене. Ключ решения отличается префиксом, и это принципиально: переменная
# внутри главы МУТИРУЕТ (на входе в сцену s010 флаг ещё false, а в s020 уже
# true), поэтому по переменным нельзя судить, проходятся ли две сцены в одном
# прохождении — состояния относятся к разным моментам. Решение же необратимо:
# если одна сцена требует пункт 0, а другая пункт 1 того же меню, они
# несовместимы по-настоящему. Поэтому совместимость считается по решениям,
# а переменные остаются для прекондиций реплея и текстов подсказок.
DECISION_PREFIX = "@"


def decision_key(menu_id: str) -> str:
    return DECISION_PREFIX + menu_id


def world_vars(w: World) -> World:
    return {k: v for k, v in w.items() if not k.startswith(DECISION_PREFIX)}


def world_decisions(w: World) -> dict:
    """{menu_id: индекс} — путь, которым мир получен."""
    out = {}
    for k, con in w.items():
        if k.startswith(DECISION_PREFIX) and con.allow and len(con.allow) == 1:
            out[k[len(DECISION_PREFIX):]] = sorted(con.allow, key=_sort_key)[0]
    return out


def world_and(a: World, b: World) -> World | None:
    """Конъюнкция миров; None — противоречие."""
    out = dict(a)
    for var, con in b.items():
        merged = out[var].intersect(con) if var in out else con
        if merged.is_empty():
            return None
        out[var] = merged
    return out


def _con_key(con: Constraint) -> str:
    """Ключ одного ограничения.

    Мемоизировать по Constraint НЕЛЬЗЯ, хотя соблазн есть: в Python `0 == False`
    и хеши совпадают, поэтому `Constraint(allow={0})` и `Constraint(allow={False})`
    — один ключ кэша, и второй получил бы строку первого. Индексы пунктов меню
    (0, 1) и bool-переменные встречаются в мирах одновременно, так что подмена
    ключа меняла бы порядок миров в артефакте в зависимости от того, что
    посчитали раньше."""
    if con.allow is not None:
        return "={%s}" % ",".join(repr(v) for v in sorted(con.allow, key=_sort_key))
    return "[%r,%r]" % (con.lo, con.hi)


def world_key(w: World) -> str:
    """Канонический ключ мира — для дедупликации и стабильной сортировки.

    Строкой, а не json.dumps: ключ считается в самом горячем месте компилятора
    (дедупликация миров внутри фикспойнта), и сериализация через json на графе
    в 500 сцен занимала больше времени, чем весь остальной разбор."""
    return "|".join("%s%s" % (v, _con_key(w[v])) for v in sorted(w))


def _subsumes(a: World, b: World) -> bool:
    """a слабее либо равен b (b ⊆ a): тогда b можно выбросить из дизъюнкции.

    Сравнение — самим значением Constraint, а не его as_data(): формы ограничения
    различимы напрямую (frozenset против границ), а as_data по пути сортирует
    множество и собирает словарь. На графе в 500 сцен именно эта сортировка
    внутри поглощения миров и была всем временем компиляции."""
    if len(a) > len(b):
        return False           # a ограничивает переменную, свободную в b
    for var, con_a in a.items():
        con_b = b.get(var)
        if con_b is None:
            return False
        if con_a == con_b:
            continue           # частый случай: одно и то же решение на пути
        if con_a.intersect(con_b) != con_b:
            return False
    return True


def _merge_worlds(worlds: list[World]) -> list[World]:
    """Дедупликация + поглощение + потолок. При переполнении миры ослабляются до
    общих ограничений — модель остаётся корректной сверху (ADR-0021)."""
    unique: dict[str, World] = {}
    for w in worlds:
        unique.setdefault(world_key(w), w)
    kept: list[World] = []
    for w in sorted(unique.values(), key=lambda x: (len(x), world_key(x))):
        if any(_subsumes(k, w) for k in kept):
            continue
        kept = [k for k in kept if not _subsumes(w, k)]
        kept.append(w)
    if len(kept) <= FLOW_MAX_WORLDS:
        return sorted(kept, key=world_key)
    # Widening: оставляем ограничения только по переменным, которые ограничены
    # во ВСЕХ мирах, — то есть заведомо более слабое, но корректное множество.
    common = set(kept[0])
    for w in kept[1:]:
        common &= set(w)
    widened: World = {}
    for var in sorted(common):
        con = kept[0][var]
        for w in kept[1:]:
            other = w[var]
            if con.allow is not None and other.allow is not None:
                con = Constraint(allow=con.allow | other.allow)
            else:
                los = [c.lo for c in (con, other) if c.lo is not None]
                his = [c.hi for c in (con, other) if c.hi is not None]
                con = Constraint(lo=min(los) if len(los) == 2 else None,
                                 hi=max(his) if len(his) == 2 else None)
        if not con.is_empty() and con.as_data():
            widened[var] = con
    return [widened]


# ── Разбор условий `when` в дизъюнкцию миров ─────────────────────────────────

VAR_TYPES = dict          # "ch01.flag" -> {"type": ..., "default": ...}


def parse_condition(expr: str, var_types: VAR_TYPES) -> list[World] | None:
    """`when` → дизъюнкция миров. None = условие вне поддержанного подмножества
    («непрозрачное»): ребро остаётся проходимым, ограничений из него не берём.

    Поддержано (ADR-0021 §2): `var`, `not var`, `var == лит`, `var != лит`,
    `var >= N`, `var > N`, `var <= N`, `var < N`, `and`, `or`, скобки."""
    if not expr or not expr.strip():
        return [{}]
    try:
        tree = pyast.parse(expr.strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return None
    return _cond(tree, var_types)


def _var_name(node) -> str | None:
    if isinstance(node, pyast.Attribute) and isinstance(node.value, pyast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _cond(node, var_types) -> list[World] | None:
    if isinstance(node, pyast.BoolOp):
        parts = [_cond(v, var_types) for v in node.values]
        if any(p is None for p in parts):
            return None
        if isinstance(node.op, pyast.Or):
            out: list[World] = []
            for p in parts:
                out.extend(p)
            return out[:FLOW_MAX_TERMS] or None
        acc: list[World] = [{}]
        for p in parts:
            nxt: list[World] = []
            for a in acc:
                for b in p:
                    merged = world_and(a, b)
                    if merged is not None:
                        nxt.append(merged)
                    if len(nxt) >= FLOW_MAX_TERMS:
                        break
            acc = nxt
            if not acc:
                return []          # противоречие внутри самого условия
        return acc
    if isinstance(node, pyast.UnaryOp) and isinstance(node.op, pyast.Not):
        inner = _negate(node.operand, var_types)
        return inner
    if isinstance(node, pyast.Compare):
        return _compare(node, var_types)
    name = _var_name(node)
    if name is not None:
        return _truthy(name, var_types, positive=True)
    return None


def _negate(node, var_types) -> list[World] | None:
    """Отрицание — только атомарных форм: полное отрицание дизъюнкции раздувает
    модель, а в реальных условиях его нет."""
    if isinstance(node, pyast.Compare):
        return _compare(node, var_types, invert=True)
    name = _var_name(node)
    if name is not None:
        return _truthy(name, var_types, positive=False)
    return None


def _truthy(name, var_types, positive: bool) -> list[World] | None:
    kind = (var_types.get(name) or {}).get("type")
    if kind == "bool":
        return [{name: Constraint(allow=frozenset({positive}))}]
    return None            # истинность строки/числа/списка не моделируем


_CMP_OPS = {pyast.Eq: "==", pyast.NotEq: "!=", pyast.Gt: ">", pyast.GtE: ">=",
            pyast.Lt: "<", pyast.LtE: "<="}
_INVERTED = {"==": "!=", "!=": "==", ">": "<=", ">=": "<", "<": ">=", "<=": ">"}
# Отражение (перестановка сторон), НЕ отрицание: «5000 <= x» — это «x >= 5000».
# Путать эти две таблицы дорого: граница уезжает на единицу и на пороге ровно
# в 5000 сцена считается недостижимой, хотя игра её показывает.
_REFLECTED = {">": "<", ">=": "<=", "<": ">", "<=": ">="}


def _compare(node, var_types, invert: bool = False) -> list[World] | None:
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op = _CMP_OPS.get(type(node.ops[0]))
    if op is None:
        return None
    name = _var_name(node.left)
    literal_node = node.comparators[0]
    if name is None:                       # форма «литерал == var» — тоже валидна
        name = _var_name(node.comparators[0])
        literal_node = node.left
        op = _REFLECTED.get(op, op)
    if name is None:
        return None
    try:
        value = pyast.literal_eval(literal_node)
    except (ValueError, SyntaxError, TypeError):
        return None
    if invert:
        op = _INVERTED[op]
    if op == "==":
        return [{name: Constraint(allow=frozenset({value}))}]
    if op == "!=":
        kind = (var_types.get(name) or {}).get("type")
        if kind == "bool":
            return [{name: Constraint(allow=frozenset({not value}))}]
        return [{}]                        # «не равно» по строке не сужаем
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if op == ">=":
        return [{name: Constraint(lo=value)}]
    if op == ">":
        return [{name: Constraint(lo=value + 1 if isinstance(value, int) else value)}]
    if op == "<=":
        return [{name: Constraint(hi=value)}]
    return [{name: Constraint(hi=value - 1 if isinstance(value, int) else value)}]


# ── Модель ───────────────────────────────────────────────────────────────────

@dataclass
class SceneNode:
    id: str
    chapter: str
    pack: str
    order: int
    title_key: str | None = None
    cluster: str | None = None
    ending: bool = False
    menus: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    assigns: list[dict] = field(default_factory=list)
    reach: list[World] = field(default_factory=list)


@dataclass
class FlowEdge:
    src: str
    exit_id: str
    target: str
    when: str | None = None
    menu: str | None = None
    idx: int | None = None
    opaque: bool = False          # условие вне поддержанного подмножества


@dataclass
class FlowModel:
    scenes: dict[str, SceneNode] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)
    menus: dict[str, dict] = field(default_factory=dict)
    chapters: dict[str, dict] = field(default_factory=dict)
    var_types: VAR_TYPES = field(default_factory=dict)
    # (сцена, exit, меню, индекс) -> присваивания этого пункта: эффект ребра
    edge_assigns: dict = field(default_factory=dict)
    # (переменная, значение) -> решения-сеттеры; заполняется в compute_reach
    _setters_cache: dict = field(default_factory=dict)
    incompatible: list[tuple[str, str]] = field(default_factory=list)
    preconds: dict[str, list[dict]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    complete: bool = True         # False, если AST разобран не у всех сцен


def _var_types(root: Path, packs=None) -> VAR_TYPES:
    """Типы и значения по умолчанию из vars@1 — те же зоны, что у компилятора."""
    out: VAR_TYPES = {}
    variables_dir = root / "content" / "variables"
    docs = []
    if variables_dir.is_dir():
        docs.extend(sorted(variables_dir.glob("*.vars.yaml")))
    for _pack_id, chapters_dir in chapter_zones(root, packs):
        docs.extend(sorted(chapters_dir.glob("*/vars.yaml")))
    for f in docs:
        doc = load_yaml(f) or {}
        store = doc.get("store")
        if not store or store == "persistent":
            continue
        for name, spec in (doc.get("vars") or {}).items():
            out[f"{store}.{name}"] = {
                "type": (spec or {}).get("type"),
                "default": (spec or {}).get("default"),
            }
    return out


# ── Сборка модели ────────────────────────────────────────────────────────────

def _chapter_meta(root: Path, packs=None) -> dict[str, dict]:
    """chapter.yaml по зонам: entry, порядок, кластеры, концовки, пак."""
    out: dict[str, dict] = {}
    for pack_id, chapters_dir in chapter_zones(root, packs):
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()) \
                if chapters_dir.is_dir() else []:
            m = CHAPTER_DIR_RE.match(d.name)
            if not m:
                continue
            meta = load_yaml(d / "chapter.yaml") if (d / "chapter.yaml").is_file() else {}
            ch_id = f"ch{m.group(1)}"
            out[ch_id] = {
                "pack": pack_id,
                "dir": d,
                "title_key": (meta or {}).get("title_key"),
                "entry": (meta or {}).get("entry_scene"),
                "order": list((meta or {}).get("scene_order") or []),
                "endings": list((meta or {}).get("endings") or []),
                "clusters": list((meta or {}).get("clusters") or []),
                "status": (meta or {}).get("status"),
            }
    return out


def _scene_meta(chapters: dict[str, dict]) -> dict[str, dict]:
    """scene.yaml всех глав: заголовок и объявленные чтения."""
    out: dict[str, dict] = {}
    for ch_id, ch in chapters.items():
        scenes_dir = ch["dir"] / "scenes"
        for f in sorted(scenes_dir.glob("*.scene.yaml")) if scenes_dir.is_dir() else []:
            sm = SCENE_YAML_RE.match(f.name)
            if not sm:
                continue
            doc = load_yaml(f) or {}
            out[f"{ch_id}_s{sm.group(1)}"] = {
                "title_key": doc.get("title_key"),
                "reads": list(((doc.get("vars") or {}).get("reads")) or []),
                "rel": f,
            }
    return out


def build_flow(root: Path, packs=None, analyses: dict | None = None) -> FlowModel:
    """Модель графа. `analyses` — сводки build-bridge по относительным путям
    авторских .rpy (их даёт компилятор). Без них авторство выбора неизвестно:
    модель помечается неполной, подсказки walkthrough из неё строить нельзя."""
    model = FlowModel()
    model.var_types = _var_types(root, packs)
    chapters = _chapter_meta(root, packs)
    scene_meta = _scene_meta(chapters)
    declared_scenes, edges = build_edges(root)

    # ── Узлы ────────────────────────────────────────────────────────────────
    cluster_of: dict[str, str] = {}
    for ch_id, ch in chapters.items():
        for cl in ch["clusters"]:
            for sid in cl.get("scenes") or []:
                cluster_of[f"{ch_id}_{sid}"] = cl["title_key"]
        model.chapters[ch_id] = {
            "pack": ch["pack"],
            "title_key": ch["title_key"],
            "entry": f"{ch_id}_{ch['entry']}" if ch["entry"] else None,
            "order": [f"{ch_id}_{s}" for s in ch["order"]],
            "clusters": [{"title_key": c["title_key"],
                          "scenes": [f"{ch_id}_{s}" for s in (c.get("scenes") or [])]}
                         for c in ch["clusters"]],
        }
    for sid in sorted(declared_scenes):
        ch_id = sid[:4]
        ch = chapters.get(ch_id) or {}
        short = sid[5:]
        order = ch.get("order") or []
        meta = scene_meta.get(sid) or {}
        model.scenes[sid] = SceneNode(
            id=sid, chapter=ch_id, pack=ch.get("pack", "core"),
            order=order.index(short) if short in order else len(order),
            title_key=meta.get("title_key"),
            cluster=cluster_of.get(sid),
            ending=(short in (ch.get("endings") or [])
                    or (bool(order) and short == order[-1])),
            reads=sorted(meta.get("reads") or []),
        )

    # ── Рёбра из деклараций + авторство выбора из AST ────────────────────────
    exit_choices: dict[tuple[str, str], list[dict]] = {}
    analysed: set[str] = set()
    if analyses:
        for rel, analysis in sorted(analyses.items()):
            markers = analysis.get("menu_markers") or []
            scene_ids = sorted({m.group("scene") for m in
                                (LABEL_RE.match(lb["name"])
                                 for lb in analysis.get("labels") or [])
                                if m})
            if len(scene_ids) != 1:
                continue                    # не наша форма файла: молчим
            sid = scene_ids[0]
            node = model.scenes.get(sid)
            if node is None:
                continue
            analysed.add(sid)
            node.assigns = list(analysis.get("assigns") or [])
            actual_reads = sorted(analysis.get("var_reads") or [])
            node.reads = sorted(set(node.reads) | set(actual_reads))
            for menu in analysis.get("menus") or []:
                menu_id = menu_id_of(menu, markers)
                if menu_id is None:
                    model.warnings.append(
                        f"{rel}: меню на строке {menu['line']} без маркера vn_menu — "
                        f"подсказки walkthrough к нему привязать не к чему (C1)")
                    continue
                node.menus.append(menu_id)
                model.menus[menu_id] = {
                    "scene": sid,
                    "items": len(menu.get("items") or []),
                }
                for choice in menu.get("choices") or []:
                    for raw in choice.get("returns") or []:
                        ok, exit_id = _literal_exit(raw)
                        if not ok or not exit_id:
                            continue
                        exit_choices.setdefault((sid, exit_id), []).append({
                            "menu": menu_id,
                            "idx": choice["idx"],
                            "assigns": list(choice.get("assigns") or []),
                        })
            node.menus.sort()

    # Полнота — это «AST разобран у КАЖДОЙ объявленной сцены», а не «аргумент
    # analyses не None»: на дереве без авторских .rpy модель иначе объявляла бы
    # себя полной, ни разу не позвав мост, и подсказки walkthrough строились бы
    # по графу без авторства выборов.
    model.complete = analysed >= set(model.scenes)

    for e in edges:
        src, exit_id = e.scene, e.exit_id
        when_worlds = parse_condition(e.when or "", model.var_types)
        attribution = exit_choices.get((src, exit_id)) or [None]
        for choice in attribution:
            menu_id = (choice or {}).get("menu")
            idx = (choice or {}).get("idx")
            model.edges.append(FlowEdge(
                src=src, exit_id=exit_id, target=e.target, when=e.when,
                menu=menu_id, idx=idx, opaque=when_worlds is None,
            ))
            if menu_id is not None:
                model.edge_assigns[(src, exit_id, menu_id, idx)] = \
                    list((choice or {}).get("assigns") or [])
    model.edges.sort(key=lambda x: (x.src, x.exit_id, x.target,
                                    x.menu or "", -1 if x.idx is None else x.idx))
    return model


# ── Достижимость ─────────────────────────────────────────────────────────────

def _assign_counts(assigns: list[dict]) -> dict:
    out: dict = {}
    for a in assigns:
        out[(a["var"], repr(a["value"]))] = out.get((a["var"], repr(a["value"])), 0) + 1
    return out


def _scene_level_assigns(node: SceneNode, menu_assigns: list[dict]) -> list[dict]:
    """Присваивания ТЕЛА сцены, без тех, что сделаны внутри пунктов меню.

    Мост сливает пер-пунктовые присваивания в общий список сцены, поэтому
    применять его целиком нельзя: у развилки там лежат ВСЕ ветки сразу
    (`path = left` и `path = right`), и ветвление исчезло бы. Вычитание
    мультимножеством, а не по значению: тело и пункт могут писать одно и то же."""
    left = _assign_counts(node.assigns)
    for key, count in _assign_counts(menu_assigns).items():
        left[key] = left.get(key, 0) - count
    out: list[dict] = []
    for a in node.assigns:
        key = (a["var"], repr(a["value"]))
        if left.get(key, 0) > 0:
            left[key] -= 1
            out.append(a)
    return out


def _apply(world: World, assigns: list[dict]) -> World:
    out = dict(world)
    for a in assigns:
        out[a["var"]] = Constraint(allow=frozenset({a["value"]}))
    return out


def _setters(model: FlowModel) -> dict:
    """(переменная, значение) -> решения, которые это значение выставляют.

    Нужно, чтобы условие по переменной ЧУЖОЙ главы превратить в требование к
    решениям: сама переменная к моменту этой главы уже зафиксирована, а вот
    выбор, которым её выставили, — это и есть то, что конфликтует с другим
    выбором того же меню."""
    out: dict = {}
    for (_src, _exit_id, menu_id, idx), assigns in sorted(
            model.edge_assigns.items(), key=lambda kv: (kv[0][0], kv[0][1],
                                                        kv[0][2], kv[0][3])):
        for a in assigns:
            out.setdefault((a["var"], repr(a["value"])), []).append((menu_id, idx))
    return out


def _foreign_requirements(model: FlowModel, term: World, chapter: str) -> list[World]:
    """Миры-требования по решениям для ограничений term на переменные ЧУЖИХ глав.
    Пустой список — требований нет (все переменные свои или сеттеры неизвестны)."""
    reqs: list[World] = [{}]
    setters = model._setters_cache
    for var, con in sorted(term.items()):
        if var.startswith(DECISION_PREFIX) or var.startswith(chapter + "."):
            continue
        if con.allow is None or len(con.allow) != 1:
            continue                      # порог/интервал в решения не переводим
        value = sorted(con.allow, key=_sort_key)[0]
        options = setters.get((var, repr(value))) or []
        if not options:
            continue                      # переменную пишет тело сцены, не выбор
        grown: list[World] = []
        for base in reqs:
            for menu_id, idx in options:
                merged = world_and(base, {decision_key(menu_id):
                                          Constraint(allow=frozenset({idx}))})
                if merged is not None:
                    grown.append(merged)
                if len(grown) >= FLOW_MAX_TERMS:
                    break
        reqs = grown or reqs
    return [] if reqs == [{}] else reqs


def compute_reach(model: FlowModel) -> None:
    """Прямое распространение миров от входной сцены каждой главы до фикспойнта.

    Порядок внутри ребра: сначала присваивания (тело сцены и выбранный пункт),
    потом условие exit — так же, как исполняет генерат: `when` проверяется уже
    после возврата из тела."""
    edges_by_src: dict[str, list[FlowEdge]] = {}
    for e in model.edges:
        edges_by_src.setdefault(e.src, []).append(e)

    choice_assigns: dict[str, list[dict]] = {}
    for e in model.edges:
        if e.menu is not None:
            choice_assigns.setdefault(e.src, []).extend(
                model.edge_assigns.get((e.src, e.exit_id, e.menu, e.idx), []))

    body_assigns = {sid: _scene_level_assigns(node, choice_assigns.get(sid, []))
                    for sid, node in model.scenes.items()}
    model._setters_cache = _setters(model)

    # Условия рёбер разбираются ОДИН раз: внутри фикспойнта каждое ребро
    # проходится многократно, а разбор `when` от номера шага не зависит.
    gates: dict[str, list[World] | None] = {}
    for e in model.edges:
        if e.when not in gates:
            gates[e.when] = parse_condition(e.when or "", model.var_types)

    # Затравка: своя глава начинается со значений по умолчанию своего стора —
    # так же, как её видит игра. Переменные чужих сторов не ограничены: до
    # главы могли быть любые прохождения (корректно сверху).
    worklist: list[str] = []
    for ch_id, ch in sorted(model.chapters.items()):
        entry = ch.get("entry")
        if not entry or entry not in model.scenes:
            continue
        seed: World = {}
        for var, spec in sorted(model.var_types.items()):
            if var.startswith(ch_id + "."):
                seed[var] = Constraint(allow=frozenset({spec.get("default")}))
        model.scenes[entry].reach = [seed]
        worklist.append(entry)

    guard = 0
    limit = 200 * max(1, len(model.scenes))
    while worklist:
        guard += 1
        if guard > limit:
            model.warnings.append(
                "граф: распространение достижимости не сошлось за отведённые шаги "
                "— модель обрезана (проверьте циклы в exits)")
            break
        sid = worklist.pop()
        node = model.scenes[sid]
        for e in edges_by_src.get(sid, []):
            target = model.scenes.get(e.target)
            if target is None:
                continue
            effects = list(body_assigns.get(sid, []))
            decision: World = {}
            if e.menu is not None:
                effects += model.edge_assigns.get((sid, e.exit_id, e.menu, e.idx), [])
                decision = {decision_key(e.menu): Constraint(allow=frozenset({e.idx}))}
            gate = gates[e.when]
            produced: list[World] = []
            for w in node.reach:
                after = _apply(w, effects)
                if decision:
                    after = world_and(after, decision)
                    if after is None:
                        continue                 # тот же выбор дважды по-разному
                if gate is None:                 # непрозрачное условие: не сужаем
                    produced.append(after)
                    continue
                for term in gate:
                    merged = world_and(after, term)
                    if merged is None:
                        continue
                    # Условие по ЧУЖОЙ переменной переводится в решения: иначе
                    # конфликт «эта сцена требует левую ветку прошлой главы, а та
                    # — правую» не виден, ведь внутри своей главы решений другой
                    # главы нет. Разворачиваем в мир на каждого сеттера.
                    foreign = _foreign_requirements(model, term, node.chapter)
                    if not foreign:
                        produced.append(merged)
                        continue
                    for extra in foreign:
                        with_dec = world_and(merged, extra)
                        if with_dec is not None:
                            produced.append(with_dec)
            if not produced:
                continue
            before = {world_key(w) for w in target.reach}
            target.reach = _merge_worlds(target.reach + produced)
            if {world_key(w) for w in target.reach} != before:
                worklist.append(e.target)


def compute_compat(model: FlowModel, cap: int = 4096) -> None:
    """Пары сцен, недостижимых в ОДНОМ прохождении: пересечения миров нет.

    Список разреженный (только конфликты) и с потолком: при переполнении он не
    эмитится вовсе, а рантайм считает совместимость по тем же мирам на лету для
    выбранных игроком целей — данных в артефакте для этого достаточно."""
    ids = [sid for sid in sorted(model.scenes) if model.scenes[sid].reach]
    # Сравниваем ТОЛЬКО решения (см. DECISION_PREFIX): переменные внутри главы
    # мутируют, и их состояния относятся к разным моментам прохождения.
    decs = {sid: [{k: v for k, v in w.items() if k.startswith(DECISION_PREFIX)}
                  for w in model.scenes[sid].reach] for sid in ids}
    out: list[tuple[str, str]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if any(world_and(wa, wb) is not None
                   for wa in decs[a] for wb in decs[b]):
                continue
            out.append((a, b))
            if len(out) > cap:
                model.warnings.append(
                    f"граф: конфликтующих пар больше {cap} — матрица не эмитится, "
                    f"рантайм считает совместимость по мирам на лету")
                model.incompatible = []
                return
    model.incompatible = out


def compute_preconds(model: FlowModel) -> None:
    """Прекондиции реплея: на каждый мир достижимости — по одному значению для
    каждой переменной, которую сцена читает. Значение берётся из ограничения
    мира, иначе из vars@1; отсутствие и того и другого — ошибка сборки."""
    for sid in sorted(model.scenes):
        node = model.scenes[sid]
        if not node.reads:
            model.preconds[sid] = [{}] if node.reach else []
            continue
        variants: list[dict] = []
        for w in node.reach:
            state: dict = {}
            wv = world_vars(w)
            for var in node.reads:
                spec = model.var_types.get(var)
                if spec is None:
                    model.errors.append(
                        f"{sid}: читает {var}, которой нет в реестре переменных — "
                        f"состояние входа в реплей не определить")
                    continue
                con = wv.get(var)
                value = con.witness(spec.get("default")) if con is not None \
                    else spec.get("default")
                if value is None and spec.get("default") is None \
                        and con is not None and con.allow == frozenset({None}):
                    value = None
                state[var] = value
            if state not in variants:
                variants.append(state)
        model.preconds[sid] = variants


# ── Артефакт ─────────────────────────────────────────────────────────────────

def flow_data(model: FlowModel) -> dict:
    """Документ артефакта. Детерминированный по построению: все словари
    сортируются, миры канонизируются, значения — только простые типы."""
    scenes: dict = {}
    for sid in sorted(model.scenes):
        n = model.scenes[sid]
        scenes[sid] = {
            "chapter": n.chapter,
            "pack": n.pack,
            "order": n.order,
            "title_key": n.title_key,
            "cluster": n.cluster,
            "ending": n.ending,
            "menus": sorted(n.menus),
            "reads": sorted(n.reads),
            "reach": [{v: c.as_data() for v, c in sorted(world_vars(w).items())}
                      for w in n.reach],
            "decisions": [world_decisions(w) for w in n.reach],
            "preconds": model.preconds.get(sid) or [],
        }
    return {
        "schema": "flow@1",
        "complete": model.complete,
        "scenes": scenes,
        "edges": [
            {"from": e.src, "exit": e.exit_id, "to": e.target,
             "when": e.when, "menu": e.menu, "idx": e.idx, "opaque": e.opaque}
            for e in model.edges
        ],
        "menus": {mid: model.menus[mid] for mid in sorted(model.menus)},
        "chapters": {ch: model.chapters[ch] for ch in sorted(model.chapters)},
        "incompatible": [list(p) for p in sorted(model.incompatible)],
    }


def flow_json(model: FlowModel) -> str:
    """Артефакт для диффа и ревью: тот же документ, что уезжает в генерат."""
    return json.dumps(flow_data(model), ensure_ascii=False, indent=1,
                      sort_keys=True) + "\n"


def build_model(root: Path, packs=None, analyses: dict | None = None) -> FlowModel:
    """Полный проход: модель -> достижимость -> конфликты -> прекондиции."""
    model = build_flow(root, packs=packs, analyses=analyses)
    compute_reach(model)
    compute_compat(model)
    compute_preconds(model)
    return model


def model_from_repo(root: Path) -> FlowModel:
    """Модель по репозиторию: декларации + AST авторских сцен через build-bridge.

    Один вход для CLI: `vn content flow` и `vn test revisit` обязаны считать
    графом одно и то же, иначе гейт пересмотра сверяет прогон со своей
    собственной, неполной картиной."""
    from .analyze import analyze_scene_files

    rpys: list[Path] = []
    for _pack_id, zone in chapter_zones(root):
        rpys.extend(sorted(zone.glob("*/scenes/*.scene.rpy")))
    analyses = analyze_scene_files(root, rpys) if rpys else {}
    return build_model(root, analyses=analyses)


def emit_flow(model: FlowModel, header: str) -> str:
    """Реестр графа для рантайма. Три проекции (флоучарт, walkthrough, реплей)
    читают ЭТОТ документ и ничего не считают заново из деклараций."""
    data = flow_data(model)
    return header + (
        "init offset = -100\n\n"
        "# Скомпилированный граф истории (flow@1, ADR-0021). Единственный источник\n"
        "# правды для флоучарта главы, встроенного walkthrough и реплея сцены.\n"
        "#\n"
        "# scenes[sid]: chapter/pack/order, title_key, cluster, ending, menus, reads,\n"
        "#   reach   — миры достижимости (ограничения на переменные НА ВХОДЕ в сцену),\n"
        "#   decisions — принятые решения {menu_id: индекс} для каждого мира,\n"
        "#   preconds  — состояния входа для реплея (по одному на мир).\n"
        "# edges: from/exit/to + when + (menu, idx) — какой ПУНКТ меню даёт переход.\n"
        "# incompatible: пары сцен, недостижимых в одном прохождении (по решениям).\n"
        f"define VN_FLOW = {data!r}\n"
    )


def validate_flow(model: FlowModel) -> tuple[list[str], list[str]]:
    """Ошибки и предупреждения сборки по модели графа.

    Ошибка — то, что делает фичи неработоспособными молча: сцена читает
    переменную, которой ни один путь не присваивает значения и у которой нет
    значения по умолчанию (реплей в такую сцену войти не сможет).
    Предупреждение — потеря точности: непрозрачное условие, меню без маркера."""
    errors = list(model.errors)
    warnings = list(model.warnings)
    for sid in sorted(model.scenes):
        node = model.scenes[sid]
        if not node.reach:
            continue                    # недостижимость ловит lint (раздел 3a)
        for variants in [model.preconds.get(sid) or []]:
            for state in variants:
                for var, value in sorted(state.items()):
                    spec = model.var_types.get(var) or {}
                    if value is None and spec.get("default") is None \
                            and spec.get("type") not in (None, "dict", "list"):
                        errors.append(
                            f"{sid}: читает {var}, но ни один путь до сцены не даёт "
                            f"ей значения и в vars@1 нет default — реплей сцены "
                            f"не сможет собрать состояние входа")
    opaque = sorted({f"{e.src}.{e.exit_id}" for e in model.edges if e.opaque})
    for ref in opaque:
        warnings.append(
            f"{ref}: условие when вне поддержанного подмножества (ADR-0021 §2) — "
            f"ограничений из него не извлечь: подсказки walkthrough и конфликты "
            f"целей на этом ребре будут менее точными")
    return errors, warnings
