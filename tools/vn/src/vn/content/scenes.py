"""Компиляция сцен (фаза 1, раздел 3): валидация контракта авторского scene.rpy
и эмиссия label-обвязки. Вход — метаданные глав/сцен + AST-сводка от build-bridge.

Контракт (G3/G7/C2):
- авторские метки: только <full_id>__body и <full_id>__<branch>;
- jump/call только на метки своей сцены, без expression-целей;
- переходы между сценами — return "<exit_id>", цели в exits: scene.yaml;
- имя генерата — только по id (game/generated/scenes/chNN/<full_id>.gen.rpy).
"""

from __future__ import annotations

import ast as pyast
import re
from dataclasses import dataclass, field
from pathlib import Path

LABEL_RE = re.compile(r"^(?P<scene>ch\d{2}_s\d{3})__[a-z0-9_]+$")


@dataclass
class SceneUnit:
    full_id: str            # ch01_s010
    chapter_id: str         # ch01
    short_id: str           # s010
    yaml_rel: str
    rpy_rel: str
    meta: dict
    rpy_text: str
    analysis: dict


@dataclass
class SceneCompileReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _exit_entries(spec) -> list[dict]:
    """Нормализация exits-значения: строка | {to,when} | список -> список {to, when?}."""
    if isinstance(spec, str):
        return [{"to": spec}]
    if isinstance(spec, dict):
        return [spec]
    return list(spec)


def resolve_target(chapter_id: str, target: str) -> str:
    """s060 -> chNN_s060; ch04/s010 -> ch04_s010 (метка сцены = полный id, G7)."""
    if "/" in target:
        ch, s = target.split("/", 1)
        return f"{ch}_{s}"
    return f"{chapter_id}_{target}"


def _literal_exit(expr: str | None) -> tuple[bool, str | None]:
    """Return-выражение -> (является ли строковым литералом/None, значение)."""
    if expr is None:
        return True, None
    try:
        value = pyast.literal_eval(expr)
    except (ValueError, SyntaxError):
        return False, None
    if value is None or isinstance(value, str):
        return True, value
    return False, None


def validate_scene(unit: SceneUnit, known_scenes: set[str], status: str,
                   rep: SceneCompileReport) -> dict:
    """Проверка контракта. Возвращает контекст эмиссии:
    {exit_id -> [{to_label, when?}]}; недостижимые цели draft-глав заменены на fallback."""
    a = unit.analysis
    src = unit.rpy_rel

    for err in a.get("errors", []):
        rep.errors.append(f"{src}: parse error: {err}")
    if a.get("errors"):
        return {}

    labels = {l["name"] for l in a["labels"]}
    for l in a["labels"]:
        m = LABEL_RE.match(l["name"])
        if not m or m.group("scene") != unit.full_id:
            rep.errors.append(
                f"{src}:{l['line']}: метка {l['name']!r} вне контракта "
                f"^{unit.full_id}__<suffix>$ (C2; naming.md)"
            )
    if f"{unit.full_id}__body" not in labels:
        rep.errors.append(f"{src}: нет обязательной метки {unit.full_id}__body (C2)")

    for kind, items in (("jump", a["jumps"]), ("call", a["calls"])):
        for j in items:
            if j["expression"]:
                rep.errors.append(
                    f"{src}:{j['line']}: {kind} expression запрещён в авторских сценах "
                    f"(динамические цели ломают статический анализ и prediction)"
                )
                continue
            if not str(j["target"]).startswith(f"{unit.full_id}__"):
                rep.errors.append(
                    f"{src}:{j['line']}: {kind} {j['target']} — переход вне своей сцены; "
                    f"межсценовые переходы только через return \"<exit_id>\" + exits (C2)"
                )

    # Условные пункты меню запрещены: движок фильтрует их ДО screen choice,
    # и перевод по runtime-индексу (G8) сдвинулся бы на соседние пункты.
    for menu in a.get("menus", []):
        for i, cond in enumerate(menu.get("conditions", [])):
            if cond not in ("True", "None"):
                rep.errors.append(
                    f"{src}:{menu['line']}: условный пункт меню #{i} ({cond!r}) — "
                    f"запрещено (ломает перевод по индексу); используйте ветвление сцены"
                )

    exits: dict = unit.meta.get("exits") or {}
    returned: set[str | None] = set()
    for r in a["returns"]:
        ok, value = _literal_exit(r["expr"])
        if not ok:
            rep.errors.append(
                f"{src}:{r['line']}: return с не-литеральным выражением — exit-id обязан "
                f"быть строковым литералом (валидируется против exits)"
            )
            continue
        returned.add(value)
        if value is None:
            if exits:
                rep.errors.append(
                    f"{src}:{r['line']}: пустой return в сцене с объявленными exits — "
                    f"завершайте return \"<exit_id>\""
                )
        elif value not in exits:
            rep.errors.append(
                f"{src}:{r['line']}: return {value!r} не объявлен в exits "
                f"({unit.yaml_rel}: {sorted(exits) or 'пусто'})"
            )

    for exit_id in exits:
        if exit_id not in returned:
            rep.warnings.append(
                f"{unit.yaml_rel}: exits.{exit_id} не достигается ни одним return в {src}"
            )

    complain = rep.warnings.append if status == "draft" else rep.errors.append
    dispatch: dict[str, list[dict]] = {}
    for exit_id, spec in exits.items():
        entries = []
        for e in _exit_entries(spec):
            label = resolve_target(unit.chapter_id, e["to"])
            if label not in known_scenes:
                complain(
                    f"{unit.yaml_rel}: exits.{exit_id} -> {e['to']}: сцена {label} не существует"
                    + ("; draft: переход уйдёт на «сцена недоступна»" if status == "draft" else "")
                )
                if status != "draft":
                    continue
                entries.append({"to_label": None, "when": e.get("when"), "todo": label})
            else:
                entries.append({"to_label": label, "when": e.get("when")})
        dispatch[exit_id] = entries
    return dispatch


def emit_scene(unit: SceneUnit, dispatch: dict, audio_ids: set[str],
               locations: dict, rep: SceneCompileReport, header: str) -> str:
    lines = [header]
    lines.append(f"label {unit.full_id}:")
    lines.append(f'    $ vn.checkpoint("{unit.full_id}")')
    # scene очищает ТОЛЬКО свой слой (master) — слой sprites чистим явно,
    # иначе персонажи предыдущей сцены протекают в следующую (сверено с SDK).
    lines.append('    $ renpy.scene("sprites")')

    location = unit.meta.get("location")
    if location:
        if "/" not in location:
            rep.errors.append(
                f"{unit.yaml_rel}: location {location!r} без варианта — нужно "
                f"<location>/<variant> (например {location}/day)"
            )
            location = None
        else:
            loc_id, variant = location.split("/", 1)
            loc = locations.get(loc_id)
            if loc is None:
                rep.errors.append(
                    f"{unit.yaml_rel}: location {loc_id!r} не объявлена в content/locations/"
                )
                location = None
            elif variant not in (loc.get("backgrounds") or {}):
                rep.errors.append(
                    f"{unit.yaml_rel}: у локации {loc_id!r} нет варианта {variant!r} "
                    f"(есть: {sorted(loc.get('backgrounds') or {})})"
                )
                location = None
            else:
                lines.append(f"    scene bg {loc_id} {variant} with dissolve")
    if not location:
        # Нейтральный фон: сцена без локации (или локация не прошла валидацию).
        lines.append("    scene vn_black with dissolve")

    music = unit.meta.get("music")
    if music:
        track = music.split("/", 1)[1]
        if track not in audio_ids:
            rep.errors.append(
                f"{unit.yaml_rel}: music {music}: трек {track!r} не объявлен в content/audio/"
            )
        else:
            lines.append(f"    play music {track} fadein 1.0")

    lines.append(f"    call {unit.full_id}__body from _call_{unit.full_id}__body")
    lines.append("    $ vn.check_scene_stack()")

    for exit_id, entries in dispatch.items():
        for e in entries:
            cond = f'_return == "{exit_id}"'
            if e.get("when"):
                cond += f" and vn.eval_when({e['when']!r})"
            lines.append(f"    if {cond}:")
            if e["to_label"] is None:
                lines.append(f"        # TODO(draft): цель {e['todo']} ещё не написана")
                lines.append("        $ vn.unwind_call_stack()")
                lines.append("        jump vn_scene_unavailable")
            else:
                lines.append(f"        jump {e['to_label']}")

    if not dispatch:
        lines.append("    if _return is None:")
        lines.append("        jump vn_end_of_content")
    lines.append("    # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)")
    lines.append("    $ vn.unwind_call_stack()")
    lines.append("    jump vn_scene_unavailable")
    lines.append("")
    lines.append(f"# ══ Авторский источник (копия): {unit.rpy_rel} ══")
    lines.append(unit.rpy_text.rstrip("\n"))
    lines.append("")
    return "\n".join(lines)


def emit_chapter_registry(chapters: list[dict], packs: dict, header: str) -> str:
    rows = tuple(
        {
            "id": c["id"],
            "title_key": c["title_key"],
            "entry_label": f"{c['id']}_{c['entry_scene']}",
            "status": c["status"],
            "pack": c.get("pack", "core"),
        }
        for c in chapters
    )
    pack_rows = {
        pid: {"kind": m["kind"], "version": m["version"]} for pid, m in sorted(packs.items())
    }
    return header + (
        "init offset = -100\n\n"
        "# Chapter Registry: читается vn_registry.chapters() (framework/00_core/010_registry.rpy).\n"
        f"define VN_CHAPTERS = {rows!r}\n\n"
        "# Установленные паки (G9): владение проверяет vn.pack_registry.owned().\n"
        f"define VN_PACKS = {pack_rows!r}\n"
    )


def emit_scene_registry(units: list[SceneUnit], header: str) -> str:
    rows = tuple(
        {"id": u.full_id, "label": u.full_id, "chapter": u.chapter_id} for u in units
    )
    return header + (
        "init offset = -100\n\n"
        "# Scene Registry: чит-меню QA (фаза 2) и валидаторы.\n"
        f"define VN_SCENES = {rows!r}\n"
    )


def emit_characters(char_docs: list[tuple[str, dict]], header: str) -> str:
    out = [header, "init offset = 500\n"]
    if not char_docs:
        out.append("# Персонажи не объявлены (content/characters/ пуст).")
    for rel, doc in sorted(char_docs):
        args = [f"_({doc['name']!r})", f"color={doc['color']!r}", f"image={doc['id']!r}"]
        if doc.get("voice_tag"):
            args.append(f"voice_tag={doc['voice_tag']!r}")
        out.append(f"define {doc['id']} = Character({', '.join(args)})")
    out.append("")
    out.append("# layeredimage появятся вместе с ассет-пайплайном (раздел 2/4, G11).")
    return "\n".join(out) + "\n"


def emit_chapter_select(header: str) -> str:
    return header + '''
# Экран выбора глав (C14): собран из данных Chapter Registry.
screen chapter_select():
    tag menu
    add Solid(gui.interface_bg)
    use navigation
    vbox:
        xpos 420
        ypos 80
        spacing 24
        label vn_loc.t("ui.nav.chapters")
        vbox:
            spacing 12
            for ch in VN_CHAPTERS:
                # Владение паком — логический гейт (G9): непокупные главы не видны
                if vn.pack_registry.owned(ch["pack"]):
                    textbutton vn_loc.t(ch["title_key"]) action Start(ch["entry_label"])
        textbutton vn_loc.t("ui.common.back") action Return()
'''
