"""vn test deck-kit — комплект приёмки для ЖИВОГО устройства (Steam Deck / ТВ).

Зачем. Всё, что можно проверить на build-машине, у нас уже автоматизировано:
тесты, движковый lint, сейв-корпус, прогоны автопилота в вариантах steam_deck и
steam_big_picture. Не автоматизируется ровно одно — то, что видно только на
железе: читаемость с расстояния вытянутой руки, реальный Steam Input, сон и
пробуждение, оверлей, время загрузки с eMMC. Раньше человек с Deck в руках
должен был сам догадываться, что смотреть, и сам собирать окружение.

Комплект отвечает на это: скриншоты обоих окружений, машинная сводка (включая
кегли, пересчитанные в ФИЗИЧЕСКИЕ пиксели Deck) и чек-лист, ПОСТРОЕННЫЙ ИЗ
docs/handbook/43-steam-qa.md — с уже отмеченными пунктами, которые закрыла
автоматика, и пустыми чекбоксами для того, что требует устройства.

Чек-лист парсится, а не копируется: копия разъехалась бы с документом на первой
же правке приёмки, и человек проверял бы прошлогодний список.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from .repo import write_text_lf

QA_DOC_REL = "docs/handbook/43-steam-qa.md"
KIT_REL = "build/deck-kit"

# Физическое разрешение Steam Deck (окно Game Mode). Виртуальная сетка проекта
# берётся из project.yaml: render.screen, поэтому здесь только железо.
DECK_PHYSICAL = (1280, 800)

# Уровни приёмки в порядке строгости — заголовки разделов документа.
LEVELS = ("MUST PASS", "SHOULD PASS", "NICE TO HAVE")

_LEVEL_RE = re.compile(r"^##\s+\d+\.\s+(?P<level>MUST PASS|SHOULD PASS|NICE TO HAVE)\s*$", re.M)
_ITEM_RE = re.compile(r"^###\s+(?P<num>\d+\.\d+)\s+(?P<title>.+?)\s*$", re.M)
_TABLE_ROW_RE = re.compile(r"^\|(?P<first>[^|]+)\|", re.M)


@dataclass
class ChecklistItem:
    level: str
    number: str
    title: str
    done: str = ""          # непустое = закрыто автоматикой, с фактом в тексте


def parse_checklist(doc: Path) -> list[ChecklistItem]:
    """Пункты приёмки из 43-steam-qa.md: раздел «## N. LEVEL» -> его «### N.M».

    Парсим заголовки, а не таблицы: таблицы внутри пунктов описывают КАК
    проверять и меняются чаще, чем сам перечень, а комплекту нужен перечень."""
    text = doc.read_text(encoding="utf-8")
    # Границей раздела служит ЛЮБОЙ заголовок «## », а не только следующий
    # уровень приёмки: иначе последний уровень тянулся бы до конца файла и
    # затягивал соседние разделы (у нас это «что автоматизировано» и BLOCKED —
    # тоже таблицы, и они дали бы 38 фантомных пунктов вместо четырёх).
    heads = [(m.start(), _LEVEL_RE.match(text, m.start()))
             for m in re.finditer(r"^##\s+.+$", text, re.M)]
    bounds = [(pos, m.group("level")) for pos, m in heads if m]
    if not bounds:
        return []
    starts = [pos for pos, _m in heads] + [len(text)]
    ends = {pos: starts[i + 1] for i, pos in enumerate(starts[:-1])}
    items: list[ChecklistItem] = []
    for start, level in bounds:
        section = text[start:ends[start]]
        found = [ChecklistItem(level=level, number=m.group("num"),
                               title=m.group("title").strip())
                 for m in _ITEM_RE.finditer(section)]
        if not found:
            # Уровень может быть оформлен ТАБЛИЦЕЙ, а не подразделами (так сегодня
            # написан Nice to Have): берём первую колонку строк, пропуская шапку и
            # разделитель. Иначе целый уровень приёмки молча выпал бы из комплекта.
            n = 0
            for row in _TABLE_ROW_RE.finditer(section):
                cell = row.group("first").strip()
                if not cell or set(cell) <= set("-: ") or cell.startswith("Пункт"):
                    continue
                n += 1
                found.append(ChecklistItem(
                    level=level, number=f"{LEVELS.index(level) + 1}.{n}",
                    title=_strip_md(cell)))
        items.extend(found)
    return items


def _strip_md(text: str) -> str:
    """Убрать разметку из ячейки таблицы: в чек-листе нужен пункт, не вёрстка."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # ссылки
    return text.replace("**", "").replace("`", "").strip()


def deck_scale(virtual: tuple[int, int]) -> float:
    """Во сколько раз виртуальный пиксель мельче физического на Deck.

    Движок вписывает виртуальную сетку в окно с сохранением пропорций
    (renpy/display/core.py), поэтому масштаб — минимум по обеим осям, а разница
    уходит в letterbox. Именно поэтому текст на Deck принципиально мягче
    нативного: он рисуется в виртуальных пикселях и уменьшается (ADR-0015)."""
    return min(DECK_PHYSICAL[0] / virtual[0], DECK_PHYSICAL[1] / virtual[1])


# Кегли объявлены двумя формами: голое число (диалоги — они не масштабируются)
# и round(N * gui.ui_scale) для интерфейсных (scale.rpy делает их крупнее в
# controller-first окружении). Разбираем обе, иначе в комплекте окажется треть
# типографики.
_TOKEN_RE = re.compile(
    r"^define\s+gui\.(?P<name>[a-z_]+_size)\s*=\s*"
    r"(?:round\(\s*(?P<scaled>\d+)\s*\*\s*gui\.ui_scale\s*\)|(?P<plain>\d+))", re.M)


def font_sizes(gui_rpy: Path, ui_scale: float) -> dict[str, dict]:
    """Кегли интерфейса из gui.rpy -> {токен: {virtual, deck_physical}}.

    Читаем ФАКТИЧЕСКИЕ define'ы: держать в комплекте свою копию чисел значит
    рапортовать вчерашнюю типографику. Множитель ui_scale учитывается там, где
    он применён в самом файле (на Deck интерфейсные кегли крупнее — scale.rpy)."""
    out: dict[str, dict] = {}
    for m in _TOKEN_RE.finditer(gui_rpy.read_text(encoding="utf-8")):
        if m.group("scaled"):
            virtual = round(int(m.group("scaled")) * ui_scale)
            scales = True
        else:
            virtual = int(m.group("plain"))
            scales = False
        out[m.group("name")] = {"virtual": virtual, "scales_on_deck": scales}
    return out


def build_summary(root: Path, deck_ui_scale: float = 1.4) -> tuple[dict, list[str]]:
    """Машинная сводка: что за сборка, сколько весит, какие кегли увидит игрок.

    deck_ui_scale — множитель интерфейсных кеглей в controller-first окружении
    (framework/20_ui/scale.rpy). Передаётся параметром, а не читается регексом:
    значение живёт в коде рантайма, и дублировать его разбор здесь значит
    завести второй источник истины."""
    from .assets.memory import analyze
    from .assets.render_config import load_render_config
    from .repo import git_sha, load_project

    warnings: list[str] = []
    project = load_project(root)
    cfg = load_render_config(root)
    scale = deck_scale(cfg.screen)

    sizes = font_sizes(root / "game" / "gui.rpy", deck_ui_scale)
    for name, row in sizes.items():
        row["deck_physical"] = round(row["virtual"] * scale, 1)

    def zone_mb(rel: str) -> float:
        p = root / rel
        total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0
        return round(total / (1024 * 1024), 2)

    mem = analyze(root)
    warnings.extend(mem.warnings)
    worst = mem.worst
    return {
        "version": project["version"],
        "git_sha": git_sha(root),
        "save_schema": project["save_schema"],
        "virtual_screen": list(cfg.screen),
        "deck_window": list(DECK_PHYSICAL),
        "deck_scale": round(scale, 4),
        "deck_letterbox_px": round((DECK_PHYSICAL[1] - cfg.screen[1] * scale) / 2, 1),
        "max_oversampling": cfg.max_oversampling,
        "image_cache_mb": cfg.image_cache_mb,
        "worst_scene": {"id": worst.scene_id, "mpx": round(worst.px / 1e6, 2),
                        "budget_mpx": round(mem.budget_px / 1e6, 2)} if worst else None,
        "zones_mb": {"game/assets": zone_mb("game/assets"),
                     "game/generated": zone_mb("game/generated")},
        "budgets": project.get("budgets") or {},
        "font_sizes": sizes,
    }, warnings


def render_checklist(items: list[ChecklistItem], summary: dict,
                     automated: list[tuple[str, str]] | None = None) -> str:
    """Markdown-чек-лист: отмеченное автоматикой — с фактом, остальное — пустое.

    Пустой чекбокс здесь не признак недоделки, а разделение труда: эти пункты
    физически требуют устройства, и отметить их может только человек."""
    lines = ["# Приёмка на устройстве",
             "",
             f"Сборка {summary['version']}+{summary['git_sha']}, "
             f"save_schema {summary['save_schema']}. Перечень построен из "
             f"`{QA_DOC_REL}` — правьте документ, а не этот файл.",
             ""]
    # Что уже закрыто машиной — отдельным блоком с ФАКТИЧЕСКИМ выводом команд.
    # Сознательно не пытаемся сопоставить это с пунктами документа по тексту:
    # угаданное соответствие давало бы ложные галочки в приёмке, а цена ошибки
    # здесь — «проверено» там, где не проверено.
    if automated:
        lines += ["## Закрыто автоматикой на build-машине", ""]
        lines += [f"- [x] {name} — {result}" for name, result in automated]
        lines += ["",
                  "Ниже — только то, что видно ИСКЛЮЧИТЕЛЬНО на устройстве: "
                  "читаемость, реальный Steam Input, сон/пробуждение, оверлей, "
                  "время загрузки с eMMC.", ""]
    for level in LEVELS:
        rows = [i for i in items if i.level == level]
        if not rows:
            continue
        lines += [f"## {level}", ""]
        for item in rows:
            mark = "x" if item.done else " "
            suffix = f" — {item.done}" if item.done else ""
            lines.append(f"- [{mark}] {item.number} {item.title}{suffix}")
        lines.append("")
    return "\n".join(lines)


def write_kit(root: Path, items: list[ChecklistItem], summary: dict,
              shots: dict[str, list[Path]],
              automated: list[tuple[str, str]] | None = None) -> list[str]:
    """Разложить комплект в build/deck-kit/ (идемпотентно: перезапись, не накопление)."""
    import shutil

    kit = root / KIT_REL
    if kit.is_dir():
        shutil.rmtree(kit)
    kit.mkdir(parents=True)
    written: list[str] = []

    write_text_lf((kit / "summary.json"),
        json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    written.append("summary.json")

    write_text_lf((kit / "checklist.md"),
        render_checklist(items, summary, automated))
    written.append("checklist.md")

    for variant, files in sorted(shots.items()):
        dest = kit / "screens" / variant
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copyfile(f, dest / f.name)
            written.append(f"screens/{variant}/{f.name}")
    return written
