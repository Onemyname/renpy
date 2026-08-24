"""vn loc keys — стабильные идентификаторы строк (G8, раздел 5).

Физически дописывает в авторские scene.rpy:
- клаузы `id chNN_sNNN_NNNN` к say-стейтментам без id;
- маркеры `$ vn_menu = "chNN_sNNN_mNNN"` перед menu-стейтментами без маркера.

Разбор — ТОЛЬКО парсером Ren'Py через build-bridge (G24). После правки файл
перечитывается мостом заново: если parse упал или тексты/структура разошлись —
файл откатывается и выдаётся ошибка. Правка опечатки в реплике не теряет перевод:
id уже в исходнике и не пересчитывается.

Ledger (loc/ledger/chNN.json, шардирован по главам) — не зеркало сцен, а ЖУРНАЛ:
живые id -> исходный текст ПЛЮС `retired` — номера, которые больше не живут, но
остаются занятыми. Номер, однажды выданный реплике, не достаётся другой реплике
никогда: иначе новая реплика унаследовала бы перевод удалённой (msgctxt в PO совпал
бы), а fuzzy пометился бы только при несовпадении текста байт в байт.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from ..repo import write_text_lf

SAY_ID_RE = re.compile(r"^(?P<scene>ch\d{2}_s\d{3})_(?P<num>\d{4})$")
# Правило близости маркера к оператору `menu` и его регексп — ОДИН на проект
# (content/scenes.py). Здесь была своя копия и литерал «3» в двух местах, хотя
# комментарий в scenes.py называл себя единственным местом правила: расхождение
# значений разъехало бы аллокатор id и компилятор молча — маркер, который видит
# один, второй считал бы отсутствующим.
from ..content.scenes import MENU_ID_IN_SOURCE_RE as MENU_ID_RE
from ..content.scenes import menu_markers_map
# Ключ меню как он лежит в журнале (без обёртки vn_menu = "…").
MENU_KEY_RE = re.compile(r"^(?P<scene>ch\d{2}_s\d{3})_m(?P<num>\d{3})$")
LEDGER_SCHEMA = "ledger@2"
# Разрядность id: номера не переиспользуются, значит потолок достижим. Пятизначный
# номер молча испортил бы исходник (следующий прогон забракует его как «вне
# конвенции»), поэтому упираемся ДО записи в файл.
MAX_SAY_NUM = 9999
MAX_MENU_NUM = 999


class KeysError(RuntimeError):
    pass


@dataclass
class KeysReport:
    changed: list[str] = field(default_factory=list)    # файлы с правками
    missing: list[str] = field(default_factory=list)    # --check: что не хватает
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ledgers: list[str] = field(default_factory=list)


def _next_counter(existing: set[int]) -> int:
    return (max(existing, default=0)) + 1


def _journal(root: Path, ch_ids: set[str], rep: KeysReport
             ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(занятые id по главам, ранее отставленные по главам).

    «Занятые» = живые из прошлого прогона + retired: из них засеваются счётчики, и
    именно поэтому номер не переиспользуется. Шард на ledger@1 (журнала ещё нет)
    досеивается из PO: obsolete-записи `#~` — единственный сохранившийся след id,
    удалённых до появления журнала."""
    from .po import known_contexts

    known: dict[str, set[str]] = {}
    prior: dict[str, set[str]] = {}
    for ch_id in sorted(ch_ids):
        path = root / "loc" / "ledger" / f"{ch_id}.json"
        doc: dict | None = None
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as e:
                # Тихо начать с нуля нельзя: это сброс метки аллокации, то есть
                # повторная выдача уже использованных номеров.
                rep.errors.append(
                    f"loc/ledger/{ch_id}.json не парсится: {e} — восстановите файл из "
                    f"git: высокая метка номеров живёт только здесь")
                continue
        prior[ch_id] = set((doc or {}).get("retired") or {})
        occupied = set(prior[ch_id])
        occupied |= set((doc or {}).get("says") or {})
        occupied |= set((doc or {}).get("menus") or {})
        if doc is None or "retired" not in doc:
            # Миграция: журнала нет — досеиваем из PO. Суффикс индекса пункта у
            # msgctxt меню (chNN_sNNN_mNNN[i]) срезается, иначе в retired попал бы
            # ключ с «[0]» и шард не прошёл бы свою же схему.
            for ctx in known_contexts(root, ch_id):
                base = ctx.split("[", 1)[0]
                if not base.startswith(f"{ch_id}_"):
                    continue
                if SAY_ID_RE.match(base) or MENU_KEY_RE.match(base):
                    occupied.add(base)
        known[ch_id] = occupied
    return known, prior


def assign_ids(root: Path, check: bool = False) -> KeysReport:
    from ..content.analyze import analyze_scene_files
    from ..content.compile import CHAPTER_DIR_RE, SCENE_YAML_RE

    from ..repo import chapter_zones

    rep = KeysReport()
    scene_files: list[tuple[str, str, Path]] = []   # (ch_id, full_id, rpy)
    for _pack_id, chapters_dir in chapter_zones(root):
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
        # Сцен нет, но осиротевшие шарды ledger всё равно подлежат проверке/очистке:
        # ранний выход без этого тихо оставлял бы «переводы исчезнувших глав».
        _reconcile_stale_ledgers(root, alive=set(), check=check, rep=rep)
        return rep

    analysis = analyze_scene_files(root, [f for _, _, f in scene_files])

    # Занятые номера прошлых прогонов: из них засеваются счётчики (номер не
    # переиспользуется), из них же вычисляется новый retired.
    known, prior_retired = _journal(root, {c for c, _f, _p in scene_files}, rep)
    # Главы, чей анализ не состоялся: их журнал обязан переехать на диск БЕЗ
    # изменений — иначе одна опечатка в сцене отправила бы всю главу в retired и
    # сожгла её номера навсегда.
    broken: set[str] = set()

    ledgers: dict[str, dict] = {}   # ch_id -> ledger dict
    originals: dict[Path, str] = {}  # изменённые файлы -> исходный текст (для отката)

    for ch_id, full_id, rpy in scene_files:
        a = analysis.get(str(rpy)) or analysis.get(str(rpy).replace("\\", "/"))
        if not a:
            rep.errors.append(f"{rpy.name}: build-bridge не вернул анализ")
            broken.add(ch_id)
            continue
        if a.get("errors"):
            rep.errors.extend(f"{rpy.name}: {e}" for e in a["errors"])
            broken.add(ch_id)
            continue

        lines = rpy.read_text(encoding="utf-8").splitlines()
        original = list(lines)

        # ── say-id: существующие сохраняются, новым — следующий номер ────────
        # Счётчик засеян ЗАНЯТЫМИ номерами (живые прошлого прогона + retired), а не
        # только теми, что нашлись в файле: иначе удалённая реплика освобождала бы
        # свой номер, и новая унаследовала бы её перевод.
        used_nums: set[int] = {
            int(m.group("num")) for i in known.get(ch_id, ())
            if (m := SAY_ID_RE.match(i)) and m.group("scene") == full_id
        }
        ledger = ledgers.setdefault(ch_id, {"schema": LEDGER_SCHEMA, "chapter": ch_id,
                                            "says": {}, "menus": {}, "retired": {}})
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
            if num > MAX_SAY_NUM:
                rep.errors.append(
                    f"{rpy.name}:{say['line']}: номера сцены {full_id} исчерпаны "
                    f"(метка аллокации {num} > {MAX_SAY_NUM}, номера не "
                    f"переиспользуются) — разбейте сцену на две")
                continue
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
        used_menu_nums: set[int] = {
            int(m.group("num")) for i in known.get(ch_id, ())
            if (m := MENU_KEY_RE.match(i)) and m.group("scene") == full_id
        }
        for mk in a["menu_markers"]:
            mm = MENU_ID_RE.search(mk["source"])
            if mm and mm.group("id").startswith(full_id):
                used_menu_nums.add(int(mm.group("id")[-3:]))

        menus_without_marker = []
        # Привязка считается для ВСЕХ меню файла сразу: владение маркером
        # эксклюзивно, иначе вложенная развилка забирала маркер внешнего меню и
        # своего id не получала вовсе (content/scenes.py: menu_markers_map).
        owner = menu_markers_map(a["menus"], a["menu_markers"])
        for menu in a["menus"]:
            mk = owner.get(menu["line"])
            mm = MENU_ID_RE.search((mk or {}).get("source") or "")
            if mk is None or mm is None:
                menus_without_marker.append(menu)
            elif not mm.group("id").startswith(full_id):
                rep.errors.append(
                    f"{rpy.name}:{mk['line']}: маркер {mm.group('id')} "
                    f"принадлежит чужой сцене (copy-paste?) — ledger главы "
                    f"загрязнился бы чужими переводами"
                )
            else:
                ledger["menus"][mm.group("id")] = {"items": menu["items"]}

        menu_assignments = []
        for menu in sorted(menus_without_marker, key=lambda m: m["line"]):
            num = _next_counter(used_menu_nums)
            if num > MAX_MENU_NUM:
                rep.errors.append(
                    f"{rpy.name}:{menu['line']}: номера меню сцены {full_id} исчерпаны "
                    f"(метка аллокации {num} > {MAX_MENU_NUM}) — разбейте сцену")
                continue
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
            write_text_lf(rpy, "\n".join(lines) + "\n")
            rep.changed.append(rpy.relative_to(root).as_posix())
            originals[rpy] = "\n".join(original) + ("\n" if original else "")

    # ── Журнал retired: занятые, но больше не живые ─────────────────────────
    for ch_id, ledger in ledgers.items():
        live = set(ledger["says"]) | set(ledger["menus"])
        if ch_id in broken:
            # Анализ главы не состоялся: переносим прошлый журнал как есть.
            ledger["retired"] = {i: {"state": "retired"}
                                 for i in sorted(prior_retired.get(ch_id, ()))}
            continue
        ledger["retired"] = {i: {"state": "retired"}
                             for i in sorted(known.get(ch_id, set()) - live)}
        for i in sorted(prior_retired.get(ch_id, set()) & live):
            rep.warnings.append(
                f"{ch_id}: id {i} вернулся из retired — если это восстановленная "
                f"реплика (git revert), её перевод корректно вернётся из obsolete; "
                f"если реплика новая, удалите клаузу id и дайте vn loc keys выдать "
                f"новый номер")

    if check:
        # Свежесть ledger: правка ТЕКСТА реплики не трогает id в scene.rpy,
        # но обязана доехать до ledger — иначе extract и переводчики молча
        # работают со старым текстом. Сравниваем пересобранный ledger с диском.
        ledger_dir = root / "loc" / "ledger"
        for ch_id, ledger in sorted(ledgers.items()):
            path = ledger_dir / f"{ch_id}.json"
            data = json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
            on_disk = path.read_text(encoding="utf-8") if path.is_file() else ""
            old_schema = False
            if on_disk:
                try:
                    old_schema = json.loads(on_disk).get("schema") != LEDGER_SCHEMA
                except ValueError:
                    old_schema = False      # битый шард уже назван в rep.errors
            if old_schema:
                rep.missing.append(
                    f"loc/ledger/{ch_id}.json на схеме ledger@1 (журнала retired нет) "
                    f"— выполните vn loc keys: миграция журнала"
                )
            elif on_disk != data:
                rep.missing.append(
                    f"loc/ledger/{ch_id}.json устарел (тексты/структура разошлись "
                    f"со сценами) — выполните vn loc keys"
                )
        _reconcile_stale_ledgers(root, {ch_id for ch_id, _f, _p in scene_files},
                                 check=True, rep=rep)
        return rep
    if rep.errors:
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
                write_text_lf(p, original_text)
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
            write_text_lf(path, data)
            rep.ledgers.append(f"loc/ledger/{ch_id}.json")
    _reconcile_stale_ledgers(root, {ch_id for ch_id, _f, _p in scene_files},
                             check=False, rep=rep)
    return rep


def _reconcile_stale_ledgers(root: Path, alive: set[str], check: bool, rep: KeysReport):
    """Шарды ledger исчезнувших глав: --check репортует, обычный прогон удаляет."""
    ledger_dir = root / "loc" / "ledger"
    if not ledger_dir.is_dir():
        return
    for stale in sorted(ledger_dir.glob("ch*.json")):
        if stale.stem in alive:
            continue
        if check:
            rep.missing.append(
                f"loc/ledger/{stale.name}: глава исчезла — выполните vn loc keys"
            )
        else:
            stale.unlink()
            rep.ledgers.append(f"удалён (глава исчезла): loc/ledger/{stale.name}")
