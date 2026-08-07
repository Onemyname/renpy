"""vn loc keys — стабильные идентификаторы строк (G8, раздел 5).

Физически дописывает в авторские scene.rpy:
- клаузы `id chNN_sNNN_NNNN` к say-стейтментам без id;
- маркеры `$ vn_menu = "chNN_sNNN_mNNN"` перед menu-стейтментами без маркера.

Разбор — ТОЛЬКО парсером Ren'Py через build-bridge (G24). После правки файл
перечитывается мостом заново: если parse упал или тексты/структура разошлись —
файл откатывается и выдаётся ошибка. Правка опечатки в реплике не теряет перевод:
id уже в исходнике и не пересчитывается.

Ledger (loc/ledger/chNN.json, шардирован по главам): id -> исходный текст; источник
для PO-экстракции и детектора коллизий.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SAY_ID_RE = re.compile(r"^(?P<scene>ch\d{2}_s\d{3})_(?P<num>\d{4})$")
MENU_ID_RE = re.compile(r'vn_menu\s*=\s*"(?P<id>ch\d{2}_s\d{3}_m\d{3})"')


class KeysError(RuntimeError):
    pass


@dataclass
class KeysReport:
    changed: list[str] = field(default_factory=list)    # файлы с правками
    missing: list[str] = field(default_factory=list)    # --check: что не хватает
    errors: list[str] = field(default_factory=list)
    ledgers: list[str] = field(default_factory=list)


def _next_counter(existing: set[int]) -> int:
    return (max(existing, default=0)) + 1


def assign_ids(root: Path, check: bool = False) -> KeysReport:
    from ..content.analyze import analyze_scene_files
    from ..content.compile import CHAPTER_DIR_RE, SCENE_YAML_RE

    rep = KeysReport()
    zones = [root / "content" / "chapters"]
    zones += sorted((root / "packs").glob("*/chapters")) if (root / "packs").is_dir() else []
    scene_files: list[tuple[str, str, Path]] = []   # (ch_id, full_id, rpy)
    for chapters_dir in zones:
        if not chapters_dir.is_dir():
            continue
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
            m = CHAPTER_DIR_RE.match(d.name)
            if not m:
                continue
            ch_id = f"ch{m.group(1)}"
            for f in sorted((d / "scenes").glob("*.scene.rpy")) if (d / "scenes").is_dir() else []:
                sm = SCENE_YAML_RE.match(f.name[:-len(".rpy")] + ".yaml")
                if sm:
                    scene_files.append((ch_id, f"{ch_id}_s{sm.group(1)}", f))
    if not scene_files:
        return rep

    analysis = analyze_scene_files(root, [f for _, _, f in scene_files])

    ledgers: dict[str, dict] = {}   # ch_id -> ledger dict
    originals: dict[Path, str] = {}  # изменённые файлы -> исходный текст (для отката)

    for ch_id, full_id, rpy in scene_files:
        a = analysis.get(str(rpy)) or analysis.get(str(rpy).replace("\\", "/"))
        if not a:
            rep.errors.append(f"{rpy.name}: build-bridge не вернул анализ")
            continue
        if a.get("errors"):
            rep.errors.extend(f"{rpy.name}: {e}" for e in a["errors"])
            continue

        lines = rpy.read_text(encoding="utf-8").splitlines()
        original = list(lines)

        # ── say-id: существующие сохраняются, новым — следующий номер ────────
        used_nums: set[int] = set()
        ledger = ledgers.setdefault(ch_id, {"schema": "ledger@1", "chapter": ch_id,
                                            "says": {}, "menus": {}})
        for say in a["say_list"]:
            sid = say.get("id")
            if sid:
                sm = SAY_ID_RE.match(sid)
                if not sm or sm.group("scene") != full_id:
                    rep.errors.append(
                        f"{rpy.name}:{say['line']}: id {sid!r} вне конвенции "
                        f"{full_id}_NNNN (naming.md)"
                    )
                    continue
                if sid in ledger["says"]:
                    rep.errors.append(
                        f"{rpy.name}:{say['line']}: дубликат say-id {sid} (copy-paste?) — "
                        f"переводы перезаписали бы друг друга"
                    )
                    continue
                used_nums.add(int(sm.group("num")))
                ledger["says"][sid] = {"who": say["who"], "text": say["what"]}

        # Назначение id — в порядке чтения (переводчику приятнее монотонные номера),
        # применение правок — снизу вверх, чтобы номера строк не съезжали.
        pending_says = sorted((s for s in a["say_list"] if not s.get("id")),
                              key=lambda s: s["line"])
        assignments = []
        for say in pending_says:
            num = _next_counter(used_nums)
            used_nums.add(num)
            assignments.append((say, f"{full_id}_{num:04d}"))
        for say, new_id in sorted(assignments, key=lambda t: -t[0]["line"]):
            idx = say["line"] - 1
            if idx >= len(lines):
                rep.errors.append(f"{rpy.name}: строка {say['line']} вне файла (анализ разошёлся)")
                continue
            if check:
                rep.missing.append(f"{rpy.name}:{say['line']}: say без id (будет {new_id})")
                continue
            lines[idx] = lines[idx].rstrip() + f" id {new_id}"
            ledger["says"][new_id] = {"who": say["who"], "text": say["what"]}

        # ── маркеры меню ─────────────────────────────────────────────────────
        marker_lines = {mk["line"] for mk in a["menu_markers"]}
        used_menu_nums: set[int] = set()
        for mk in a["menu_markers"]:
            mm = MENU_ID_RE.search(mk["source"])
            if mm and mm.group("id").startswith(full_id):
                used_menu_nums.add(int(mm.group("id")[-3:]))

        menus_without_marker = []
        for menu in a["menus"]:
            # Маркер считается существующим, если python vn_menu-стейтмент стоит
            # в пределах 3 строк над menu (между ними могут быть пустые строки).
            if not any(menu["line"] - 3 <= ml < menu["line"] for ml in marker_lines):
                menus_without_marker.append(menu)
            else:
                for mk in a["menu_markers"]:
                    mm = MENU_ID_RE.search(mk["source"])
                    if mm and menu["line"] - 3 <= mk["line"] < menu["line"]:
                        if not mm.group("id").startswith(full_id):
                            rep.errors.append(
                                f"{rpy.name}:{mk['line']}: маркер {mm.group('id')} "
                                f"принадлежит чужой сцене (copy-paste?) — ledger главы "
                                f"загрязнился бы чужими переводами"
                            )
                            continue
                        ledger["menus"][mm.group("id")] = {"items": menu["items"]}

        menu_assignments = []
        for menu in sorted(menus_without_marker, key=lambda m: m["line"]):
            num = _next_counter(used_menu_nums)
            used_menu_nums.add(num)
            menu_assignments.append((menu, f"{full_id}_m{num:03d}"))
        for menu, menu_id in sorted(menu_assignments, key=lambda t: -t[0]["line"]):
            idx = menu["line"] - 1
            if idx >= len(lines):
                rep.errors.append(f"{rpy.name}: строка {menu['line']} вне файла (анализ разошёлся)")
                continue
            if check:
                rep.missing.append(f"{rpy.name}:{menu['line']}: menu без маркера (будет {menu_id})")
                continue
            indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
            lines.insert(idx, f'{indent}$ vn_menu = "{menu_id}"')
            ledger["menus"][menu_id] = {"items": menu["items"]}

        if not check and lines != original:
            rpy.write_text("\n".join(lines) + "\n", encoding="utf-8")
            rep.changed.append(rpy.relative_to(root).as_posix())
            originals[rpy] = "\n".join(original) + ("\n" if original else "")

    if rep.errors or check:
        return rep

    # ── Верификация раунд-трипа парсером: правки не должны ломать сцены.
    # Любой провал = ПОЛНЫЙ ОТКАТ изменённых файлов (ledger не пишется).
    if rep.changed:
        changed_paths = [root / c for c in rep.changed]
        re_analysis = analyze_scene_files(root, changed_paths)
        problems: list[str] = []
        for p in changed_paths:
            a2 = re_analysis.get(str(p)) or re_analysis.get(str(p).replace("\\", "/"))
            if not a2 or a2.get("errors"):
                problems.append(f"{p.name}: parse после правки: "
                                f"{'; '.join((a2 or {}).get('errors', ['нет анализа']))}")
            elif any(not s.get("id") for s in a2["say_list"]):
                # say с хвостовым комментарием: id приклеился в комментарий
                problems.append(f"{p.name}: после правки остались say без id "
                                f"(say с хвостовым комментарием?)")
        if problems:
            for p, original_text in originals.items():
                p.write_text(original_text, encoding="utf-8")
            raise KeysError(
                "верификация раунд-трипа не прошла — файлы ОТКАЧЕНЫ:\n"
                + "\n".join(problems)
            )

    # ── Ledger: шардированная запись + очистка шардов удалённых глав ─────────
    ledger_dir = root / "loc" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    for ch_id, ledger in sorted(ledgers.items()):
        path = ledger_dir / f"{ch_id}.json"
        data = json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        if not path.is_file() or path.read_text(encoding="utf-8") != data:
            path.write_text(data, encoding="utf-8")
            rep.ledgers.append(f"loc/ledger/{ch_id}.json")
    alive = {ch_id for ch_id, _f, _p in scene_files}
    for stale in sorted(ledger_dir.glob("ch*.json")):
        if stale.stem not in alive:
            stale.unlink()
            rep.ledgers.append(f"удалён (глава исчезла): loc/ledger/{stale.name}")
    return rep
