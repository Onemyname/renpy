"""Графовый компилятор истории (flow@1, ADR-0021): подмножество условий, алгебра
ограничений, четыре топологии, свойства артефакта и валидация.

Три проекции (флоучарт, walkthrough, реплей) читают ОДИН документ и ничего не
считают заново, поэтому цена ошибки здесь не «некрасивый граф», а прямой обман
игрока: ложное «недостижимо» красит настоящий путь красным, ложное значение в
прекондиции роняет реплей NameError'ом. Отсюда стиль набора — проверяется
РЕШЕНИЕ модели (какие миры, какие пары, какое состояние входа), а не наличие
строк в артефакте.

Топологии поднимаются на СИНТЕТИЧЕСКОМ корне: тест обязан ловить регрессию
компилятора, а не переезд боевых глав. Разбор авторских .rpy при этом настоящий —
build-bridge парсером Ren'Py (G24), поэтому группа топологий скипается без
RENPY_SDK по конвенции проекта (см. test_engine_compat.py). Юниты подмножества
условий, алгебры ограничений и валидации SDK не требуют и гоняются всегда.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from vn.content.analyze import analyze_scene_files
from vn.content.flow import (Constraint, DECISION_PREFIX, build_model, flow_json,
                             parse_condition, validate_flow, world_and,
                             world_decisions, world_vars)

from conftest import REPO_ROOT

SDK = os.environ.get("RENPY_SDK")

requires_sdk = pytest.mark.skipif(
    not (SDK and (Path(SDK) / "renpy.py").is_file()),
    reason="RENPY_SDK не установлен — топологии графа гоняет canary-джоба CI",
)


# ── 1. Подмножество условий `when` ───────────────────────────────────────────

VAR_TYPES = {
    "ch80.trust": {"type": "bool", "default": False},
    "ch80.path": {"type": "str", "default": "none"},
    "ch80.donation": {"type": "int", "default": 0},
}


def _worlds(expr: str):
    """Дизъюнкция как простые данные: сравниваем миры ЦЕЛИКОМ, а не по одному
    ограничению — лишнее ограничение так же опасно, как потерянное."""
    got = parse_condition(expr, VAR_TYPES)
    return None if got is None else [{v: c.as_data() for v, c in w.items()} for w in got]


def test_parse_condition_covers_declared_subset():
    """Подмножество из ADR-0021 §2 — это контракт с автором сцены: что в нём, то
    компилятор обязан понять точно. Недобор молча теряет подсказки walkthrough и
    конфликты целей; перебор (ограничение строже, чем у рантайма) красит в UI
    настоящий путь как недостижимый.

    Отдельно сторожатся границы строгих сравнений: `> 5` — это `lo == 6`, а не
    `lo == 5`. Ошибка на единицу здесь означает, что сцена за порогом объявлена
    достижимой при значении, с которым движок в неё не пустит.
    """
    assert _worlds("") == [{}]                       # безусловное ребро
    assert _worlds("ch80.trust") == [{"ch80.trust": {"allow": [True]}}]
    assert _worlds("not ch80.trust") == [{"ch80.trust": {"allow": [False]}}]
    assert _worlds("ch80.path == 'left'") == [{"ch80.path": {"allow": ["left"]}}]
    assert _worlds("'left' == ch80.path") == [{"ch80.path": {"allow": ["left"]}}]
    assert _worlds("ch80.trust != True") == [{"ch80.trust": {"allow": [False]}}]
    assert _worlds("ch80.donation >= 5000") == [{"ch80.donation": {"lo": 5000}}]
    assert _worlds("ch80.donation > 5000") == [{"ch80.donation": {"lo": 5001}}]
    assert _worlds("ch80.donation <= 5000") == [{"ch80.donation": {"hi": 5000}}]
    assert _worlds("ch80.donation < 5000") == [{"ch80.donation": {"hi": 4999}}]
    # and — конъюнкция в ОДНОМ мире, or — два мира: иначе дизъюнкция веток
    # склеилась бы в противоречие и ребро стало бы мёртвым.
    assert _worlds("ch80.trust and ch80.donation >= 5000") == [
        {"ch80.trust": {"allow": [True]}, "ch80.donation": {"lo": 5000}}]
    assert _worlds("ch80.trust or ch80.donation >= 5000") == [
        {"ch80.trust": {"allow": [True]}}, {"ch80.donation": {"lo": 5000}}]
    assert _worlds("(ch80.trust or not ch80.trust) and ch80.path == 'left'") == [
        {"ch80.trust": {"allow": [True]}, "ch80.path": {"allow": ["left"]}},
        {"ch80.trust": {"allow": [False]}, "ch80.path": {"allow": ["left"]}}]
    # `!=` по строке не сужает домен (запрещённых литералов у нас нет), но ребро
    # остаётся проходимым: мир один и без ограничений — не None и не пусто.
    assert _worlds("ch80.path != 'left'") == [{}]
    # Перевёрнутая форма «литерал OP переменная»: сторон две, отношение одно.
    # Отражение (`5000 <= x` ≡ `x >= 5000`), а не отрицание: спутать таблицы —
    # значит сдвинуть границу на единицу и объявить сцену на самом пороге
    # недостижимой, хотя игра её показывает.
    assert _worlds("5000 <= ch80.donation") == _worlds("ch80.donation >= 5000")
    assert _worlds("5000 >= ch80.donation") == _worlds("ch80.donation <= 5000")
    assert _worlds("5000 < ch80.donation") == _worlds("ch80.donation > 5000")
    assert _worlds("5000 > ch80.donation") == _worlds("ch80.donation < 5000")
    assert _worlds("5000 <= ch80.donation") == [{"ch80.donation": {"lo": 5000}}]
    assert _worlds("5000 > ch80.donation") == [{"ch80.donation": {"hi": 4999}}]


def test_parse_condition_returns_none_outside_subset():
    """Условие вне подмножества обязано стать НЕПРОЗРАЧНЫМ (None), а не тихо
    развернуться во что-то похожее: из вызова функции, `in` и арифметики
    ограничение не вывести, и любая догадка тут — ложное «недостижимо».

    None и `[{}]` — разные ответы: первый значит «ребро проходимо, ограничений не
    знаем» (плюс предупреждение сборки), второй — «ребро безусловно». Спутать их
    значит либо потерять предупреждение, либо соврать про безусловность.
    """
    opaque = [
        "ch80.path.startswith('l')",          # вызов метода
        "len(ch80.path) > 0",                 # вызов функции
        "'l' in ch80.path",                   # оператор in
        "ch80.donation + 1 > 5000",           # арифметика
        "ch80.donation * 2 == 10",
        "ch80.path",                          # истинность НЕ-bool не моделируем
        "not (ch80.trust and ch80.donation >= 5000)",   # отрицание составного
        "ch80.donation >= 5000 and (",        # синтаксическая ошибка
        "0 <= ch80.donation <= 10",           # цепочка сравнений
    ]
    for expr in opaque:
        assert parse_condition(expr, VAR_TYPES) is None, expr
    assert parse_condition("", VAR_TYPES) == [{}]      # контраст: безусловное ребро


def test_parse_condition_contradiction_is_empty_disjunction():
    """Противоречивое условие даёт ПУСТУЮ дизъюнкцию, а не мир без ограничений.

    Разница несущая: `[]` — «такого прохождения нет», ребро мёртвое и целевая
    сцена от него достижимости не получает; `[{}]` объявило бы её достижимой
    безусловно. Оба ответа при этом отличаются от None (непрозрачности), где
    ребро проходимо, но ограничений не извлечь.
    """
    assert parse_condition("ch80.trust and not ch80.trust", VAR_TYPES) == []
    assert parse_condition("ch80.path == 'left' and ch80.path == 'right'",
                           VAR_TYPES) == []
    assert parse_condition("ch80.donation >= 5000 and ch80.donation <= 3000",
                           VAR_TYPES) == []


# ── 2. Алгебра ограничений ───────────────────────────────────────────────────

def test_constraint_intersection_keeps_both_forms_honest():
    """Пересечение — единственное место, где сходятся две формы ограничения
    (перечисление литералов и интервал). Ошибка здесь не видна глазом в
    артефакте, а стоит либо ложного конфликта (потеряли значение, которое
    проходит), либо ложной совместимости (оставили то, которое не проходит).
    """
    allow = Constraint(allow=frozenset({0, 1000, 5000}))
    # allow x allow — пересечение множеств
    assert allow.intersect(Constraint(allow=frozenset({1000, 5000, 9000}))) \
        .as_data() == {"allow": [1000, 5000]}
    # allow x интервал — фильтр перечисления порогом (это и есть «сцена за
    # порогом»: из трёх сумм остаётся одна)
    assert allow.intersect(Constraint(lo=5000)).as_data() == {"allow": [5000]}
    assert allow.intersect(Constraint(hi=999)).as_data() == {"allow": [0]}
    assert allow.intersect(Constraint(lo=1, hi=4999)).as_data() == {"allow": [1000]}
    # интервал x интервал — сужение с обеих сторон, односторонняя граница не
    # теряется (иначе порог из чужой главы просто исчезал бы)
    assert Constraint(lo=1, hi=10).intersect(Constraint(lo=5)).as_data() == \
        {"lo": 5, "hi": 10}
    assert Constraint(lo=1).intersect(Constraint(hi=10)).as_data() == \
        {"lo": 1, "hi": 10}
    # строка против числового порога — не «пропустим», а противоречие: значение,
    # которое рантайм сравнить не сможет, не должно попасть в прекондиции
    assert Constraint(allow=frozenset({"left"})).intersect(
        Constraint(lo=5000)).is_empty()


def test_constraint_is_empty_only_on_real_contradiction():
    """`is_empty` — критерий, по которому мир объявляется недостижимым, то есть
    по нему в UI и красится «в одном прохождении не бывает». Пустое перечисление
    и перевёрнутый интервал — противоречие; односторонняя граница и обычный
    интервал — нет, иначе конфликтом станет любой порог.
    """
    assert Constraint(allow=frozenset()).is_empty()
    assert Constraint(lo=5, hi=4).is_empty()
    assert not Constraint(lo=5, hi=5).is_empty()
    assert not Constraint(lo=5).is_empty()
    assert not Constraint(hi=5).is_empty()
    assert not Constraint().is_empty()
    assert not Constraint(allow=frozenset({None})).is_empty()   # None — значение
    # Конъюнкция миров опирается ровно на этот критерий.
    assert world_and({"v": Constraint(allow=frozenset({"a"}))},
                     {"v": Constraint(allow=frozenset({"b"}))}) is None
    assert world_and({"v": Constraint(allow=frozenset({"a", "b"}))},
                     {"v": Constraint(allow=frozenset({"b"}))}) is not None


def test_constraint_witness_prefers_default_and_is_deterministic():
    """Свидетель — это значение, которое реплей ПОДСТАВИТ игроку при входе в
    сцену. Требований два, и оба видны здесь.

    1. Если значение по умолчанию само проходит ограничение, берётся оно: тогда
       состояние входа отличается от обычного прохождения минимально, и сцена не
       начинает вести себя иначе, чем у игрока.
    2. Иначе выбор детерминирован. Без устойчивого ключа сортировки перечисление
       из значений разных типов уронило бы сборку TypeError'ом (`sorted` не
       сравнивает str с int), а перечисление строк дало бы артефакт, который
       меняется от запуска к запуску.
    """
    both = Constraint(allow=frozenset({"left", "right"}))
    assert both.witness("right") == "right"          # default проходит — берём его
    assert both.witness("none") == "left"            # не проходит — минимальный
    assert Constraint(lo=5000).witness(6000) == 6000
    assert Constraint(lo=5000).witness(0) == 5000    # default вне интервала
    assert Constraint(hi=10).witness(50) == 10
    assert Constraint(allow=frozenset({True})).witness(False) is True
    # Смесь типов в перечислении: ответ есть и он один и тот же при любом порядке
    # построения множества.
    mixed = [Constraint(allow=frozenset(order)).witness(None)
             for order in (("none", 5), (5, "none"))]
    assert mixed == [5, 5]


# ── 3. Топологии на синтетическом корне ──────────────────────────────────────
#
# T1 ромб со слиянием, T2 четыре взаимоисключающие концовки, T3 числовой порог с
# гейтом по чужой главе, T4 пропускаемая сцена и секретная концовка. Плюс ch84 —
# переменная без default, которую выставляют все пути (контроль к разделу 5).

def _menu_lines(menu_id: str, items) -> list[str]:
    """Авторская форма меню: маркер `$ vn_menu` НАД оператором (C1), в пункте —
    присваивания литералов и `return "<exit_id>"`."""
    out = [f'    $ vn_menu = "{menu_id}"', "    menu:"]
    for caption, assigns, exit_id in items:
        out.append(f'        "{caption}":')
        for var, value in assigns:
            out.append(f"            $ {var} = {value!r}")
        out.append(f'            return "{exit_id}"')
    return out


TOPOLOGIES = {
    # ── T1: развилка сходится обратно ────────────────────────────────────────
    "ch80_diamond": {
        "store": "ch80",
        "vars": {"path": {"type": "str", "default": "none"}},
        "entry": "s010",
        "order": ["s010", "s020", "s030", "s040"],
        "clusters": [{"title_key": "t.split", "scenes": ["s010", "s020", "s030"]}],
        "scenes": {
            "s010_fork": {
                "writes": ["ch80.path"],
                "exits": {"left": "s020", "right": "s030"},
                "menu": ("ch80_s010_m001", [
                    ("Налево", [("ch80.path", "left")], "left"),
                    ("Направо", [("ch80.path", "right")], "right"),
                ]),
            },
            "s020_left": {"reads": ["ch80.path"], "exits": {"merge": "s040"},
                          "returns": ["merge"]},
            "s030_right": {"reads": ["ch80.path"], "exits": {"merge": "s040"},
                           "returns": ["merge"]},
            "s040_merge": {"reads": ["ch80.path"]},
        },
    },
    # ── T2: две развилки, четыре несовместимые концовки ──────────────────────
    "ch81_endings": {
        "store": "ch81",
        "vars": {"trust": {"type": "bool", "default": False},
                 "bold": {"type": "bool", "default": False}},
        "entry": "s010",
        "order": ["s010", "s020", "s030", "s040", "s050", "s060", "s070"],
        "endings": ["s040", "s050", "s060", "s070"],
        "scenes": {
            "s010_start": {
                "writes": ["ch81.trust"],
                "exits": {"trust": "s020", "doubt": "s030"},
                "menu": ("ch81_s010_m001", [
                    ("Довериться", [("ch81.trust", True)], "trust"),
                    ("Сомневаться", [("ch81.trust", False)], "doubt"),
                ]),
            },
            "s020_trusted": {
                "reads": ["ch81.trust"], "writes": ["ch81.bold"],
                "exits": {"bold": "s040", "careful": "s050"},
                "menu": ("ch81_s020_m001", [
                    ("Рискнуть", [("ch81.bold", True)], "bold"),
                    ("Не рисковать", [("ch81.bold", False)], "careful"),
                ]),
            },
            "s030_doubted": {
                "reads": ["ch81.trust"], "writes": ["ch81.bold"],
                "exits": {"bold": "s060", "careful": "s070"},
                "menu": ("ch81_s030_m001", [
                    ("Рискнуть", [("ch81.bold", True)], "bold"),
                    ("Не рисковать", [("ch81.bold", False)], "careful"),
                ]),
            },
            "s040_end_a": {"reads": ["ch81.trust", "ch81.bold"]},
            "s050_end_b": {"reads": ["ch81.trust", "ch81.bold"]},
            "s060_end_c": {"reads": ["ch81.trust", "ch81.bold"]},
            "s070_end_d": {"reads": ["ch81.trust", "ch81.bold"]},
        },
    },
    # ── T3: числовой порог + гейт по переменной ЧУЖОЙ главы ──────────────────
    "ch82_gates": {
        "store": "ch82",
        "vars": {"donation": {"type": "int", "default": 0}},
        "entry": "s010",
        "order": ["s010", "s020", "s030", "s040"],
        "scenes": {
            "s010_amount": {
                "writes": ["ch82.donation"],
                "exits": {"done": "s020"},
                "menu": ("ch82_s010_m001", [
                    ("Ничего", [("ch82.donation", 0)], "done"),
                    ("Немного", [("ch82.donation", 1000)], "done"),
                    ("Всё", [("ch82.donation", 5000)], "done"),
                ]),
            },
            "s020_check": {
                "reads": ["ch82.donation"],
                "exits": {"next": [
                    {"when": "ch82.donation >= 5000 and ch80.path == 'left'",
                     "to": "s030"},
                    {"to": "s040"},
                ]},
                "returns": ["next"],
            },
            "s030_secret": {"reads": ["ch82.donation"]},
            "s040_plain": {"reads": ["ch82.donation"]},
        },
    },
    # ── T4: пропускаемая сцена и секретная концовка за ней ───────────────────
    "ch83_hidden": {
        "store": "ch83",
        "vars": {"found": {"type": "bool", "default": False}},
        "entry": "s010",
        "order": ["s010", "s020", "s030", "s040", "s050"],
        "endings": ["s040", "s050"],
        "scenes": {
            "s010_choice": {
                "exits": {"explore": "s020", "leave": "s030"},
                "menu": ("ch83_s010_m001", [
                    ("Свернуть в переулок", [], "explore"),
                    ("Пройти мимо", [], "leave"),
                ]),
            },
            # Присваивание в ТЕЛЕ сцены, а не в пункте меню: пропускаемая сцена
            # тем и опасна, что её эффект не привязан к выбору.
            "s020_alley": {"writes": ["ch83.found"], "exits": {"done": "s030"},
                           "body": [("ch83.found", True)], "returns": ["done"]},
            "s030_gate": {
                "reads": ["ch83.found"],
                "exits": {"normal": "s040",
                          "secret": [{"when": "ch83.found", "to": "s050"}]},
                "menu": ("ch83_s030_m001", [
                    ("Уйти домой", [], "normal"),
                    ("Вернуться к находке", [], "secret"),
                ]),
            },
            "s040_normal_end": {},
            "s050_secret_end": {"reads": ["ch83.found"]},
        },
    },
    # ── Контроль к разделу 5: default'а нет, но его дают ВСЕ пути ────────────
    "ch84_setters": {
        "store": "ch84",
        "vars": {"codeword": {"type": "str"}},
        "entry": "s010",
        "order": ["s010", "s020"],
        "scenes": {
            "s010_pick": {
                "writes": ["ch84.codeword"],
                "exits": {"done": "s020"},
                "menu": ("ch84_s010_m001", [
                    ("Назвать иву", [("ch84.codeword", "willow")], "done"),
                    ("Назвать клён", [("ch84.codeword", "maple")], "done"),
                ]),
            },
            "s020_use": {"reads": ["ch84.codeword"]},
        },
    },
}


def _write_topologies(root: Path) -> list[Path]:
    """Синтетическое дерево деклараций + авторские .rpy. project.yaml и схемы не
    нужны: графовый компилятор читает только `chapter.yaml`/`vars.yaml`/
    `scene.yaml` и сводку моста."""
    rpys: list[Path] = []
    for dirname, spec in TOPOLOGIES.items():
        ch_id = dirname[:4]
        d = root / "content" / "chapters" / dirname
        (d / "scenes").mkdir(parents=True)
        chapter = {"schema": "chapter@1", "id": ch_id,
                   "title_key": f"meta.chapters.{ch_id}.title",
                   "status": "release", "entry_scene": spec["entry"],
                   "scene_order": spec["order"]}
        for key in ("endings", "clusters"):
            if spec.get(key):
                chapter[key] = spec[key]
        (d / "chapter.yaml").write_text(
            yaml.safe_dump(chapter, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        (d / "vars.yaml").write_text(
            yaml.safe_dump({"schema": "vars@1", "store": spec["store"],
                            "vars": spec["vars"]}, allow_unicode=True,
                           sort_keys=False), encoding="utf-8")
        for name, sc in spec["scenes"].items():
            sid = f"{ch_id}_{name.split('_')[0]}"
            meta = {"schema": "scene@1", "id": name.split("_")[0]}
            declared = {k: sc[k] for k in ("reads", "writes") if k in sc}
            if declared:
                meta["vars"] = declared
            if "exits" in sc:
                meta["exits"] = sc["exits"]
            (d / "scenes" / f"{name}.scene.yaml").write_text(
                yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            lines = [f"label {sid}__body:", f'    "{sid}"', ""]
            for var, value in sc.get("body") or []:
                lines.append(f"    $ {var} = {value!r}")
            for exit_id in sc.get("returns") or []:
                lines.append(f'    return "{exit_id}"')
            if "menu" in sc:
                lines += _menu_lines(*sc["menu"])
            p = d / "scenes" / f"{name}.scene.rpy"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            rpys.append(p)
    return rpys


@pytest.fixture(scope="module")
def topologies(tmp_path_factory):
    """Модель графа синтетического корня, посчитанная НАСТОЯЩИМ конвейером.

    Мост — команда движка, и проектом для неё может быть только настоящее дерево;
    анализируются при этом файлы из переданного списка, то есть наши сцены (см.
    analyze.py). Так топология не зависит от боевого контента, а разбор остаётся
    парсером Ren'Py, без моков и без второго разборщика (G24).
    """
    root = tmp_path_factory.mktemp("flow") / "root"
    rpys = _write_topologies(root)
    cache = REPO_ROOT / ".vncache"
    before = set(cache.glob("analyze-*.json")) if cache.is_dir() else set()

    analyses = analyze_scene_files(REPO_ROOT, rpys)
    broken = {k: v["errors"] for k, v in analyses.items() if v.get("errors")}
    assert broken == {}, broken
    model = build_model(root, analyses=analyses)
    assert model.complete is True

    yield {"root": root, "analyses": analyses, "model": model}

    # Ключ кэша анализа включает пути входов, а они у нас из tmp: запись в кэше
    # репозитория не пригодится больше никогда — убираем за собой.
    for f in set(cache.glob("analyze-*.json")) - before:
        f.unlink()


def _pairs(model) -> set[tuple[str, str]]:
    return {tuple(p) for p in model.incompatible}


def _choices(node, menu_id: str) -> list[int]:
    """Какие индексы данного меню встречаются в мирах достижимости сцены.

    Один индекс — сцена требует этого выбора; оба — она достижима при любом.
    Именно на этом стоит и подсветка walkthrough, и «???» во флоучарте."""
    return sorted({d[menu_id] for d in (world_decisions(w) for w in node.reach)
                   if menu_id in d})


def _allowed(node, var: str) -> set:
    """Значения переменной, разрешённые хотя бы в одном мире достижимости."""
    out = set()
    for w in node.reach:
        con = world_vars(w).get(var)
        if con is not None and con.allow is not None:
            out |= set(con.allow)
    return out


@requires_sdk
def test_t1_merge_node_inherits_worlds_of_both_branches(topologies):
    """T1: узел слияния достижим из обеих ветвей — значит он обязан получить миры
    ОБЕИХ, а не последней посчитанной.

    Если распространение затирает миры вместо объединения, ромб рушится сразу в
    трёх местах: флоучарт покажет узел слияния недостижимым из одной ветви,
    конфликтная матрица объявит его несовместимым с этой ветвью (ложное красное),
    а реплей предложит одно состояние входа вместо двух.
    """
    model = topologies["model"]
    merge = model.scenes["ch80_s040"]
    assert _allowed(merge, "ch80.path") == {"left", "right"}
    assert _choices(merge, "ch80_s010_m001") == [0, 1]
    # Два класса состояния входа — ровно то, что просмотрщик предложит игроку.
    assert model.preconds["ch80_s040"] == [{"ch80.path": "left"},
                                           {"ch80.path": "right"}]
    # Ветви друг другу противоречат, а слияние совместимо с каждой из них.
    pairs = _pairs(model)
    assert ("ch80_s020", "ch80_s030") in pairs
    assert not [p for p in pairs if "ch80_s040" in p]
    # Каждая ветвь помнит ровно свой выбор — иначе подсказка walkthrough повела
    # бы игрока не туда.
    assert _choices(model.scenes["ch80_s020"], "ch80_s010_m001") == [0]
    assert _choices(model.scenes["ch80_s030"], "ch80_s010_m001") == [1]


@requires_sdk
def test_t2_four_exclusive_endings_conflict_pairwise(topologies):
    """T2: четыре концовки за двумя развилками несовместимы попарно — все 6 пар.

    Это тот самый рукописный список из аудита референса (6 групп id), который у
    нас обязан выводиться. Потеря хотя бы одной пары = walkthrough разрешит
    игроку взять две концовки в один проход и обманет его; лишняя пара на общей
    стартовой сцене = красное там, где путь есть.
    """
    model = topologies["model"]
    endings = ["ch81_s040", "ch81_s050", "ch81_s060", "ch81_s070"]
    pairs = _pairs(model)
    expected = {(a, b) for i, a in enumerate(endings) for b in endings[i + 1:]}
    assert len(expected) == 6
    assert expected <= pairs
    # Общая стартовая сцена лежит на любом пути — конфликтовать ей не с чем.
    assert not [p for p in pairs if "ch81_s010" in p]
    # Развилка второго уровня несовместима с концовками ЧУЖОЙ ветви, но не своей.
    assert ("ch81_s020", "ch81_s060") in pairs
    assert ("ch81_s020", "ch81_s070") in pairs
    assert ("ch81_s020", "ch81_s040") not in pairs
    assert ("ch81_s020", "ch81_s050") not in pairs
    # Концовки объявлены концовками (флоучарт рисует их иначе).
    assert all(model.scenes[sid].ending for sid in endings)


@requires_sdk
def test_t3_numeric_threshold_and_cross_chapter_gate(topologies):
    """T3: сцена за числовым порогом достижима только с нужной суммой, и это
    видно в прекондициях; гейт по переменной ЧУЖОЙ главы даёт конфликт с ветвью
    той главы.

    Порог — это место, где перечисление значений встречается с интервалом: если
    фильтр теряется, секретная сцена объявляется достижимой при любой сумме, и
    реплей войдёт в неё с donation=0, то есть покажет игроку сцену, в которую он
    попасть не мог. Второй половиной сторожится перевод чужой переменной в
    РЕШЕНИЯ: внутри своей главы решений чужой нет, и без этого перевода конфликт
    «нужна левая ветвь прошлой главы» не виден вовсе.
    """
    model = topologies["model"]
    secret, plain = model.scenes["ch82_s030"], model.scenes["ch82_s040"]
    assert _allowed(secret, "ch82.donation") == {5000}
    assert _allowed(plain, "ch82.donation") == {0, 1000, 5000}
    assert _choices(secret, "ch82_s010_m001") == [2]
    assert model.preconds["ch82_s030"] == [{"ch82.donation": 5000}]
    assert model.preconds["ch82_s040"] == [{"ch82.donation": 0},
                                           {"ch82.donation": 1000},
                                           {"ch82.donation": 5000}]
    # Гейт требует ch80.path == 'left', а его выставляет пункт 0 меню чужой
    # главы: правая ветвь той главы и есть настоящий конфликт.
    assert _choices(secret, "ch80_s010_m001") == [0]
    pairs = _pairs(model)
    assert ("ch80_s030", "ch82_s030") in pairs
    assert ("ch80_s020", "ch82_s030") not in pairs
    # Сцена ЗА гейтом (обычная ветвь) ни с одной ветвью чужой главы не спорит.
    assert not [p for p in pairs if "ch82_s040" in p]


@requires_sdk
def test_t4_skippable_scene_and_secret_ending_need_the_detour(topologies):
    """T4: пропускаемая сцена и секретная концовка достижимы НЕ всегда, обычная —
    всегда.

    Проверяется по решениям, а не по переменным: `ch83.found` внутри главы
    мутирует, и «false на входе в s030» ничего не говорит о том, был ли игрок в
    переулке. Требование «нужен пункт 0 первого меню» — необратимо, и ровно его
    показывает walkthrough. Если бы модель посчитала секретную концовку
    достижимой при обоих пунктах, подсказка молчала бы там, где игрок теряет
    концовку навсегда.
    """
    model = topologies["model"]
    detour = model.scenes["ch83_s020"]
    normal, secret = model.scenes["ch83_s040"], model.scenes["ch83_s050"]
    assert _choices(detour, "ch83_s010_m001") == [0]
    assert _choices(secret, "ch83_s010_m001") == [0]
    assert _choices(normal, "ch83_s010_m001") == [0, 1]
    # Секретная концовка требует и найденного переулка, и второго выбора.
    assert _allowed(secret, "ch83.found") == {True}
    assert _choices(secret, "ch83_s030_m001") == [1]
    assert _allowed(normal, "ch83.found") == {True, False}
    # Две концовки одной развилки — настоящий конфликт.
    assert ("ch83_s040", "ch83_s050") in _pairs(model)
    # Развилка концовок достижима всегда: она не концовка и не конфликтует.
    assert not [p for p in _pairs(model) if "ch83_s030" in p]


# ── 4. Свойства модели ───────────────────────────────────────────────────────

@requires_sdk
def test_incompatible_is_canonical_symmetric_and_complete(topologies):
    """Матрица конфликтов — разреженный список пар, который читает рантайм. Три
    свойства, без которых он неверен: пара упомянута ОДИН раз в каноническом
    порядке (иначе рантайм, ищущий (b, a), конфликта не найдёт), отношение
    симметрично, и в списке ровно те пары, которые следуют из миров — ни
    потерянных (обман игрока), ни лишних (ложное красное).
    """
    model = topologies["model"]
    pairs = list(model.incompatible)
    assert pairs == sorted(pairs)
    assert len(pairs) == len(set(pairs))
    assert all(a < b for a, b in pairs)

    decs = {sid: [{k: v for k, v in w.items() if k.startswith(DECISION_PREFIX)}
                  for w in node.reach]
            for sid, node in model.scenes.items() if node.reach}

    def compatible(a: str, b: str) -> bool:
        return any(world_and(wa, wb) is not None
                   for wa in decs[a] for wb in decs[b])

    ids = sorted(decs)
    expected = {(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
                if not compatible(a, b)}
    assert set(pairs) == expected
    for a, b in pairs:
        assert not compatible(a, b) and not compatible(b, a)   # симметрия


@requires_sdk
def test_reachable_scene_never_conflicts_with_itself(topologies):
    """Сцена, у которой есть хоть один мир достижимости, обязана быть совместима
    сама с собой: иначе UI объявит недостижимым то, что игрок только что прошёл.

    Свойство держится ровно на том, что ни один мир не содержит пустого
    ограничения. Пустое ограничение означало бы, что распространение довело до
    сцены противоречие — и достижимость, и прекондиции такой сцены были бы
    выдумкой.
    """
    model = topologies["model"]
    reachable = [sid for sid, n in model.scenes.items() if n.reach]
    assert len(reachable) == len(model.scenes)      # висячих сцен в топологиях нет
    for sid in reachable:
        for w in model.scenes[sid].reach:
            assert not [v for v, con in w.items() if con.is_empty()], sid
            assert world_and(w, w) is not None, sid
        assert (sid, sid) not in _pairs(model)


@requires_sdk
def test_flow_json_is_byte_identical_across_runs_and_hash_seeds(topologies):
    """Артефакт сравнивают диффом между сборками, поэтому он обязан быть
    побайтово одинаковым — иначе каждый прогон даёт шум в ревью и в git.

    Второй прогон в том же процессе ловит зависимость от порядка обхода
    структур, а процессы с разным PYTHONHASHSEED — зависимость от порядка
    итерации МНОЖЕСТВ строк (в артефакте из них собраны списки чтений
    переменных, меню, перечисления литералов в ограничениях). Внутри одного
    процесса такая утечка невидима: равные множества обходятся одинаково,
    поэтому одного прогона мало.
    """
    root, analyses = topologies["root"], topologies["analyses"]
    first = flow_json(topologies["model"])
    assert flow_json(build_model(root, analyses=analyses)) == first

    work = root.parent
    (work / "dump.json").write_text(json.dumps(analyses), encoding="utf-8")
    # Пишем БАЙТАМИ: текстовый stdout на Windows подменил бы \n на \r\n и сравнение
    # с артефактом перестало бы быть побайтовым.
    (work / "runner.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from vn.content.flow import build_model, flow_json\n"
        "sys.stdout.buffer.write(flow_json(build_model(\n"
        "    Path(sys.argv[2]),\n"
        "    analyses=json.loads(Path(sys.argv[3]).read_text('utf-8'))\n"
        ")).encode('utf-8'))\n",
        encoding="utf-8")

    # Несколько семян, а не два: у множества из двух строк всего два порядка
    # обхода, и пара «неудачных» семян случайно совпадёт.
    outs = {}
    for seed in ("0", "7", "12345", "999983"):
        proc = subprocess.run(
            [sys.executable, str(work / "runner.py"),
             str(REPO_ROOT / "tools" / "vn" / "src"), str(root),
             str(work / "dump.json")],
            capture_output=True, env=dict(os.environ, PYTHONHASHSEED=seed))
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        outs[seed] = proc.stdout
    assert set(outs.values()) == {first.encode("utf-8")}


@requires_sdk
def test_precondition_comes_from_the_path_not_from_default(topologies):
    """Прекондиция выводится из ПУТЕЙ: переменная без `default` в vars@1 — не
    ошибка, если каждый путь до сцены ей что-то присваивает.

    Это обратная сторона проверки из раздела 5 и её обязательный контроль: если
    компилятор смотрит только на `default`, он либо ругается на исправный
    контент (и автор учится игнорировать ошибки сборки), либо не ругается никогда.
    Значений тут два — по одному на пункт меню, — то есть и «классов состояния»
    для реплея тоже два.
    """
    model = topologies["model"]
    # Ключа default тут нет ВООБЩЕ — и модель это сохраняет, а не сплющивает в
    # None: `default: null` схема разрешает явно, «default не написан» запрещает,
    # и различить их обязана именно модель (иначе проверка достижимости ругается
    # на легальную декларацию).
    assert model.var_types["ch84.codeword"] == {"type": "str"}
    # Порядок вариантов детерминирован (миры канонизированы) и идёт по пунктам
    # меню — так его и читает просмотрщик: «как в прохождении, где …».
    assert model.preconds["ch84_s020"] == [{"ch84.codeword": "willow"},
                                           {"ch84.codeword": "maple"}]
    errors, warnings = validate_flow(model)
    assert errors == []
    # Ни одного непрозрачного условия в топологиях нет — предупреждать не о чем.
    assert [w for w in warnings if "вне поддержанного подмножества" in w] == []


# ── 5. Валидация ─────────────────────────────────────────────────────────────

def _val_root(tmp_path: Path) -> Path:
    """Корень с двумя главами: в ch84 сцена читает переменную, которой никто не
    даёт значения, в ch85 — переменную с default. Второй главой сторожится
    обратная сторона: проверка обязана молчать на исправном контенте."""
    root = tmp_path / "root"
    specs = {
        "ch84_missing": {
            "store": "ch84",
            "vars": {"secret": {"type": "str"}, "mood": {"type": "str",
                                                         "default": "calm"}},
            "scenes": {
                "s010_open": {"exits": {"next": "s020"}},
                "s020_read": {"reads": ["ch84.secret", "ch84.mood"]},
            },
        },
        "ch85_ok": {
            "store": "ch85",
            "vars": {"name": {"type": "str", "default": "мира"}},
            "scenes": {"s010_read": {"reads": ["ch85.name"]}},
        },
    }
    for dirname, spec in specs.items():
        ch_id = dirname[:4]
        d = root / "content" / "chapters" / dirname
        (d / "scenes").mkdir(parents=True)
        order = sorted(n.split("_")[0] for n in spec["scenes"])
        (d / "chapter.yaml").write_text(yaml.safe_dump(
            {"schema": "chapter@1", "id": ch_id, "entry_scene": order[0],
             "scene_order": order}, allow_unicode=True), encoding="utf-8")
        (d / "vars.yaml").write_text(yaml.safe_dump(
            {"schema": "vars@1", "store": spec["store"], "vars": spec["vars"]},
            allow_unicode=True), encoding="utf-8")
        for name, sc in spec["scenes"].items():
            meta = {"schema": "scene@1", "id": name.split("_")[0]}
            if "reads" in sc:
                meta["vars"] = {"reads": sc["reads"]}
            if "exits" in sc:
                meta["exits"] = sc["exits"]
            (d / "scenes" / f"{name}.scene.yaml").write_text(
                yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    return root


def test_read_without_default_and_without_setter_is_error(tmp_path):
    """Сцена читает переменную, которой ни один путь не даёт значения и у которой
    нет `default`. Это ОШИБКА сборки, а не предупреждение: реплей такой сцены
    подставит None вместо строки, и игрок получит исключение движка — ровно тот
    «забытый флаг = NameError», за который в аудите ругали референс.

    Проверяется и обратная сторона: переменная с default (и глава, где всё в
    порядке) в ошибки не попадает, иначе ошибка сборки обесценится шумом.
    """
    model = build_model(_val_root(tmp_path))
    errors, _warnings = validate_flow(model)

    assert [e for e in errors if "ch84.secret" in e and "ch84_s020" in e]
    assert not [e for e in errors if "ch84.mood" in e]
    assert not [e for e in errors if "ch85" in e]
    # Причина названа так, чтобы автор понял, что делать: нет ни пути-сеттера, ни
    # значения по умолчанию.
    assert all("default" in e for e in errors if "ch84.secret" in e)
    # Именно на этом значении спотыкается реплей — оно и в прекондициях.
    assert model.preconds["ch84_s020"] == [{"ch84.secret": None,
                                            "ch84.mood": "calm"}]


def test_opaque_when_is_a_warning_not_an_error(tmp_path):
    """Условие вне поддержанного подмножества — ПРЕДУПРЕЖДЕНИЕ, а не ошибка.

    Сторона выбрана осознанно (ADR-0021 §2-3): `when` исполняет py_eval, то есть
    в общем случае это произвольный Python, и ронять сборку за него значит
    запретить автору половину языка. Цена — потеря точности, о ней и сообщается.
    Ошибкой это делать нельзя, предупреждение терять — тоже: без него автор не
    узнает, почему подсказки walkthrough на этом ребре молчат.
    """
    root = _val_root(tmp_path)
    scene = root / "content/chapters/ch84_missing/scenes/s010_open.scene.yaml"
    scene.write_text(yaml.safe_dump(
        {"schema": "scene@1", "id": "s010",
         "exits": {"next": [{"when": "ch84.mood.startswith('c')", "to": "s020"}]}},
        allow_unicode=True), encoding="utf-8")

    model = build_model(root)
    errors, warnings = validate_flow(model)

    opaque = [e for e in model.edges if e.opaque]
    assert [(e.src, e.exit_id) for e in opaque] == [("ch84_s010", "next")]
    assert [w for w in warnings if "ch84_s010.next" in w
            and "вне поддержанного подмножества" in w]
    assert not [e for e in errors if "ch84_s010" in e]
    # Ребро осталось проходимым: сцена за непрозрачным условием достижима, иначе
    # флоучарт объявил бы её «???» навсегда.
    assert model.scenes["ch84_s020"].reach


def test_read_of_unregistered_var_is_error(tmp_path):
    """Сцена объявила чтение переменной, которой нет в реестре vars@1 — опечатка
    в имени. Состояние входа в реплей по такой переменной не собрать вовсе,
    поэтому это ошибка сборки, а не молчаливый пропуск: иначе опечатка доедет до
    игрока и обвалится там.
    """
    root = _val_root(tmp_path)
    scene = root / "content/chapters/ch84_missing/scenes/s020_read.scene.yaml"
    scene.write_text(yaml.safe_dump(
        {"schema": "scene@1", "id": "s020",
         "vars": {"reads": ["ch84.mooood"]}}, allow_unicode=True), encoding="utf-8")

    errors, _warnings = validate_flow(build_model(root))
    assert [e for e in errors if "ch84.mooood" in e and "ch84_s020" in e]


# ── 6. Масштаб: 500 сцен ─────────────────────────────────────────────────────

def _write_scale_root(root: Path, chapters: int, per_chapter: int) -> list[Path]:
    """Дерево из chapters×per_chapter сцен: в каждой главе цепочка сцен, и через
    каждые две — развилка на два пункта меню, которая сходится обратно. Форма
    выбрана нарочно: слияния — единственное место, где миры достижимости
    размножаются произведением, то есть именно они и стоят времени."""
    rpys: list[Path] = []
    for c in range(chapters):
        ch_id = "ch%02d" % (50 + c)
        names = ["s%03d" % (10 * (i + 1)) for i in range(per_chapter)]
        d = root / "content" / "chapters" / f"{ch_id}_scale"
        (d / "scenes").mkdir(parents=True)
        (d / "chapter.yaml").write_text(yaml.safe_dump(
            {"schema": "chapter@1", "id": ch_id,
             "title_key": f"meta.chapters.{ch_id}.title", "status": "release",
             "entry_scene": names[0], "scene_order": names},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        (d / "vars.yaml").write_text(yaml.safe_dump(
            {"schema": "vars@1", "store": ch_id,
             "vars": {"flag": {"type": "bool", "default": False}}},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        for i, name in enumerate(names):
            meta: dict = {"schema": "scene@1", "id": name}
            lines = [f"label {ch_id}_{name}__body:", f'    "{ch_id} {name}"', ""]
            nxt = names[i + 1] if i + 1 < len(names) else None
            if nxt is None:
                # Последняя сцена главы: exits не объявляются вовсе — так же, как
                # у концовок в боевом контенте.
                lines.append('    return "done"')
            elif i % 2 == 0:
                meta["exits"] = {"yes": nxt, "no": nxt}
                meta["vars"] = {"writes": [f"{ch_id}.flag"]}
                lines += _menu_lines("%s_%s_m001" % (ch_id, name), [
                    ("Да", [(f"{ch_id}.flag", True)], "yes"),
                    ("Нет", [(f"{ch_id}.flag", False)], "no")])
            else:
                meta["exits"] = {"next": [{"when": f"{ch_id}.flag", "to": nxt},
                                          {"to": nxt}]}
                meta["vars"] = {"reads": [f"{ch_id}.flag"]}
                lines.append('    return "next"')
            (d / "scenes" / f"{name}_step.scene.yaml").write_text(
                yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            p = d / "scenes" / f"{name}_step.scene.rpy"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            rpys.append(p)
    return rpys


@requires_sdk
def test_five_hundred_scenes_stay_in_seconds(tmp_path):
    """Бюджет масштаба из ADR-0021: граф на ~500 сцен считается секундами.

    Мерится ИМЕННО модель (миры достижимости, матрица конфликтов, прекондиции), а
    не разбор AST: разбор — цена существующего конвейера, её держит `vn test
    corpus`. Потолок с большим запасом к наблюдаемому времени: тест обязан ловить
    смену класса сложности (например матрицу конфликтов, ставшую кубической), а
    не дрожание раннера.
    """
    import time

    root = tmp_path / "scale"
    rpys = _write_scale_root(root, chapters=10, per_chapter=50)
    assert len(rpys) == 500
    cache = REPO_ROOT / ".vncache"
    before = set(cache.glob("analyze-*.json")) if cache.is_dir() else set()
    try:
        analyses = analyze_scene_files(REPO_ROOT, rpys)

        t0 = time.perf_counter()
        model = build_model(root, analyses=analyses)
        elapsed = time.perf_counter() - t0
    finally:
        for f in set(cache.glob("analyze-*.json")) - before:
            f.unlink()

    assert len(model.scenes) == 500
    assert model.complete is True
    errors, _warnings = validate_flow(model)
    assert errors == []
    # Прекондиции посчитаны у всех, кто читает переменные: пустой словарь здесь
    # означал бы, что бюджет измерен на недоделанной модели.
    assert sum(1 for sid in model.scenes if model.preconds.get(sid)) >= 500
    # Наблюдаемое время на этой машине — ~7 с (build_flow 0.9 + достижимость
    # 5.9 + конфликты 0.6). Потолок с запасом: он ловит смену класса
    # сложности, а не дрожание раннера.
    assert elapsed < 18.0, f"модель 500 сцен считалась {elapsed:.1f} с"


def test_null_default_is_a_value_not_a_missing_one(tmp_path):
    """`default: null` — легальное состояние входа, а не отсутствие значения.

    Схема vars@1 разрешает его явно и с описанием: «не выбрано/не назначено» —
    валидный простой тип для сейва и rollback. Проверка достижимости различала
    их по значению (`default is None`), поэтому любая str/int-переменная стора
    g/chNN с null-дефолтом, прочитанная хоть одной сценой, роняла vn build
    сообщением «в vars@1 нет default» — про поле, которое схема делает
    обязательным и которое в декларации стоит. Обойти можно было только отказом
    от null-дефолта, то есть отказом от того, что схема разрешает.

    Обратная половина инварианта проверяется тут же: переменная БЕЗ ключа
    default по-прежнему ошибка — реплей в такую сцену войти не сможет."""
    root = tmp_path / "root"
    specs = {
        "ch86_null": {"store": "ch86",
                      "vars": {"gift": {"type": "str", "default": None}},
                      "scenes": {"s010_read": {"reads": ["ch86.gift"]}}},
        "ch87_nokey": {"store": "ch87",
                       "vars": {"secret": {"type": "str"}},
                       "scenes": {"s010_read": {"reads": ["ch87.secret"]}}},
    }
    for dirname, spec in specs.items():
        ch_id = dirname[:4]
        d = root / "content" / "chapters" / dirname
        (d / "scenes").mkdir(parents=True)
        (d / "chapter.yaml").write_text(yaml.safe_dump(
            {"schema": "chapter@1", "id": ch_id, "entry_scene": "s010",
             "title_key": f"meta.chapters.{ch_id}.title", "status": "release",
             "scene_order": ["s010"]}, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        (d / "vars.yaml").write_text(yaml.safe_dump(
            {"schema": "vars@1", "store": spec["store"], "vars": spec["vars"]},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        for name, sc in spec["scenes"].items():
            (d / "scenes" / f"{name}.scene.yaml").write_text(yaml.safe_dump(
                {"schema": "scene@1", "id": name.split("_")[0],
                 "vars": {"reads": sc["reads"]}}, allow_unicode=True,
                sort_keys=False), encoding="utf-8")

    errors, _warnings = validate_flow(build_model(root))
    assert [e for e in errors if "ch86" in e] == [], (
        "null-дефолт принят за отсутствие значения — сборка падает на легальной "
        "по схеме декларации")
    assert [e for e in errors if "ch87.secret" in e], (
        "переменная без ключа default обязана оставаться ошибкой")
    # И само состояние входа: реплей входит в сцену с None, а не «никак».
    assert build_model(root).preconds["ch86_s010"] == [{"ch86.gift": None}]


@requires_sdk
def test_body_assign_survives_a_conditional_exit_list(tmp_path):
    """Присваивание ТЕЛА сцены не должно исчезать из модели.

    Ключ (src, exit_id, menu, idx) адресует пункт меню, но рёбер с таким ключом
    бывает несколько: exit со списком условных целей даёт по ребру на каждую цель
    с одинаковой атрибуцией к пункту. Список присваиваний пункта попадал в
    аккумулятор по разу на ЦЕЛЬ, а вычитается он из общего списка сцены
    мультимножеством — и вычитал больше, чем нужно: присваивание тела,
    совпадающее с присваиванием пункта по (переменная, значение), выбрасывалось.

    Дальше по цепочке это ложное «сцена недостижима»: пустой reach -> пустые
    preconds -> в модалке карты нет кнопки «Переиграть», walkthrough не ведёт к
    цели, а матрица конфликтов начинает выдавать ложное «несовместимо» — то
    самое красное, которое ADR-0021 §3 называет прямым обманом игрока.

    Такой топологии не было ни в юнит-тестах, ни в packs/qa_flow: в ch72
    условный список есть, но его exit не возвращается из меню."""
    root = tmp_path / "root"
    d = root / "content" / "chapters" / "ch88_bodyassign"
    (d / "scenes").mkdir(parents=True)
    (d / "chapter.yaml").write_text(yaml.safe_dump(
        {"schema": "chapter@1", "id": "ch88", "title_key": "meta.chapters.ch88.title",
         "status": "release", "entry_scene": "s010",
         "scene_order": ["s010", "s020", "s030", "s040"]},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    (d / "vars.yaml").write_text(yaml.safe_dump(
        {"schema": "vars@1", "store": "ch88", "vars": {
            "flag": {"type": "bool", "default": False, "doc": "t", "since": 1},
            "mood": {"type": "str", "default": "calm", "doc": "t", "since": 1}}},
        allow_unicode=True, sort_keys=False), encoding="utf-8")

    metas = {
        # exit go — СПИСОК условных целей: два ребра с одной атрибуцией к пункту 0.
        "s010_fork": {"exits": {"go": [{"when": "ch88.mood == 'calm'", "to": "s020"},
                                       {"to": "s030"}],
                                "alt": [{"when": "ch88.flag", "to": "s040"}]}},
        "s020_left": {}, "s030_right": {},
        # Сцена за условием читает тот же флаг — тогда осмысленны и preconds.
        "s040_gate": {"vars": {"reads": ["ch88.flag"]}},
    }
    for name, meta in metas.items():
        doc = {"schema": "scene@1", "id": name.split("_")[0]}
        doc.update(meta)
        (d / "scenes" / f"{name}.scene.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rpys = []
    body = (
        'label ch88_s010__body:\n'
        '    $ ch88.flag = True\n'            # присваивание ТЕЛА
        '    $ vn_menu = "ch88_s010_m001"\n'
        '    menu:\n'
        '        "Подтвердить":\n'
        '            $ ch88.flag = True\n'    # то же (переменная, значение), что в теле
        '            return "go"\n'
        '        "Отказаться":\n'
        '            return "alt"\n')
    for name in metas:
        sid = f"ch88_{name.split('_')[0]}"
        f = d / "scenes" / f"{name}.scene.rpy"
        f.write_text(body if sid == "ch88_s010"
                     else f"label {sid}__body:\n    return\n", encoding="utf-8")
        rpys.append(f)

    model = build_model(root, analyses=analyze_scene_files(REPO_ROOT, rpys))
    assert model.scenes["ch88_s040"].reach, (
        "присваивание тела вычтено вместе с присваиванием пункта — сцена за "
        "условием ch88.flag объявлена недостижимой")
    assert model.preconds["ch88_s040"] == [{"ch88.flag": True}]


def test_conflict_matrix_does_not_grow_quadratically():
    """Матрица конфликтов обязана расти ЛИНЕЙНО по числу сцен.

    Одноточечный бюджет (500 сцен за N секунд) класс сложности не ловит — ADR-0021
    сам ставит гейту эту задачу, а поймать её можно только двумя точками. Прежний
    обход был честным квадратом: cap ограничивал число НАЙДЕННЫХ пар, а не сам
    перебор, поэтому на здоровом графе (конфликтов мало) цикл всегда проходил
    n(n−1)/2. Замер до правки на этой же модели: 500 сцен — 0.23 с, 2000 — 4.5 с,
    8000 — 51 с, то есть на целевых 20 000 (G19) минуты на КАЖДЫЙ vn content
    compile, и в отчёте сборки этого не видно.

    Модель синтетическая и без движка: мерить надо матрицу, а не разбор AST.
    Порог по ОТНОШЕНИЮ времён, а не по абсолютному: абсолютное зависит от
    раннера, отношение — от алгоритма."""
    import time

    from vn.content.flow import Constraint, FlowModel, SceneNode, compute_compat

    def build(n, per_chapter=50):
        m = FlowModel()
        for i in range(n):
            ch = i // per_chapter
            sid = "ch%04d_s%04d" % (ch, i)
            key = f"{DECISION_PREFIX}ch%04d_m001" % ch
            node = SceneNode(id=sid, chapter="ch%04d" % ch, pack="core", order=i)
            node.reach = [{key: Constraint(allow=frozenset({0}))},
                          {key: Constraint(allow=frozenset({1}))}]
            m.scenes[sid] = node
        return m

    def measure(n):
        m = build(n)
        t = time.perf_counter()
        compute_compat(m)
        return time.perf_counter() - t

    measure(200)                       # прогрев: первый вызов платит за импорты
    small, big = measure(1000), measure(4000)
    # Линейный рост дал бы ×4, квадратичный — ×16. Потолок ×8 отделяет одно от
    # другого с запасом на дрожание раннера и на константу индекса.
    assert big < max(small * 8, 0.5), (
        f"матрица конфликтов растёт быстрее линейного: {small:.3f} c на 1000 сцен "
        f"против {big:.3f} c на 4000 (×{big / max(small, 1e-9):.1f})")
