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


AUDIO_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Какие kind'ы треков допустимы на каком канале (C18 + канал ambient из
# framework/00_core/045_audio.rpy). Каналы вне карты (voice, movie) не проверяются.
CHANNEL_KINDS = {"music": {"bgm", "amb"}, "ambient": {"amb"}, "sound": {"sfx"}}


def _validate_refs(unit: SceneUnit, rep: SceneCompileReport, complain,
                   image_index=None, audio_tracks: dict[str, dict] | None = None) -> None:
    """Сверка ссылок авторской сцены с тем, что реально существует после сборки.

    Зачем отдельно от остальных проверок. `show mira hapy` и `play music clam_theme`
    компилятор раньше пропускал молча: генерат собирался, lint был зелёным, а падало
    это в рантайме у игрока (`show` на несуществующий образ — исключение движка,
    `play` — тишина вместо музыки). Ошибка вида «опечатка в имени» — самый частый
    класс правок в сценарии, и ловить её обязан билд.
    """
    a = unit.analysis
    src = unit.rpy_rel

    if image_index is not None and image_index.available:
        for ref in a.get("image_refs") or []:
            if ref.get("expression"):
                rep.errors.append(
                    f"{src}:{ref['line']}: {ref['kind']} expression — динамический образ "
                    f"запрещён в авторских сценах (не проверяется и ломает prediction)"
                )
                continue
            name = tuple(ref.get("name") or ())
            if not name:
                continue
            tag = name[0]
            if ref["kind"] == "hide":
                # hide адресует ТЕГ, а не полное имя: атрибуты движок игнорирует.
                if tag not in image_index.tags:
                    complain(f"{src}:{ref['line']}: hide {tag} — нет такого образа/тега")
                continue
            if tag in image_index.layered:
                unknown = [t for t in name[1:] if t not in image_index.layered[tag]]
                if unknown:
                    complain(
                        f"{src}:{ref['line']}: {ref['kind']} {' '.join(name)} — у персонажа "
                        f"{tag} нет атрибут(ов) {', '.join(sorted(unknown))} "
                        f"(есть: {', '.join(sorted(image_index.layered[tag]))})"
                    )
            elif name not in image_index.exact:
                hint = ""
                if tag not in image_index.tags:
                    hint = f"; тега {tag!r} нет вовсе"
                complain(
                    f"{src}:{ref['line']}: {ref['kind']} {' '.join(name)} — такого образа "
                    f"нет в собранных ассетах{hint}"
                )

    if audio_tracks is not None:
        for ref in a.get("audio_refs") or []:
            expr = ref.get("file")
            if not isinstance(expr, str):
                continue
            # Ссылка на логический id — только если это голый идентификатор.
            # Строковый литерал/выражение статически не разрешаются: пропускаем.
            if not AUDIO_ID_RE.match(expr.strip()):
                continue
            tid = expr.strip()
            if tid not in audio_tracks:
                complain(
                    f"{src}:{ref['line']}: {ref['stmt']} {expr} — трек не объявлен "
                    f"в content/audio/*.yaml (в рантайме будет тишина)"
                )
                continue
            # Канал обязан соответствовать kind трека: sfx на канале music занял бы
            # его и оборвал музыку, bgm на sound не зациклится.
            channel = (ref.get("stmt") or "").split(" ")[-1]
            kind = audio_tracks[tid].get("kind")
            allowed = CHANNEL_KINDS.get(channel)
            if allowed and kind and kind not in allowed:
                complain(
                    f"{src}:{ref['line']}: {ref['stmt']} {tid} — трек объявлен как "
                    f"{kind}, каналу {channel} разрешены только "
                    f"{'/'.join(sorted(allowed))}"
                )


def validate_scene(unit: SceneUnit, known_scenes: set[str], status: str,
                   rep: SceneCompileReport, var_registry: set[str] | None = None,
                   image_index=None, audio_tracks: dict[str, dict] | None = None) -> dict:
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

    # ── Переменные (G5/C-save-integrity): фактические чтения/записи store-атрибутов
    # из build-bridge сверяются с Variable Registry. Незадекларированный атрибут =
    # молчаливый фантом-стор вне сейва/миграций (write) или NameError-риск (read).
    if var_registry is not None:
        actual_writes = set(a.get("var_writes") or [])
        actual_reads = set(a.get("var_reads") or [])
        var_complain = rep.warnings.append if status == "draft" else rep.errors.append
        for ref in sorted(actual_writes | actual_reads):
            if ref not in var_registry:
                kind = "пишется" if ref in actual_writes else "читается"
                var_complain(
                    f"{src}: {ref} {kind}, но не объявлена в Variable Registry "
                    f"(content/variables/*.vars.yaml или chapters/*/vars.yaml) — "
                    f"молчаливый фантом-стор вне сейва/миграций (G5)"
                )
        # Направленная сверка с манифестом: ругаемся, только если автор ОБЪЯВИЛ
        # vars.reads/writes и они разошлись с фактом — иначе не навязываем декларацию.
        declared = unit.meta.get("vars") or {}
        if "writes" in declared:
            for ref in sorted(actual_writes - set(declared["writes"])):
                if ref in var_registry:
                    rep.warnings.append(f"{unit.yaml_rel}: {ref} пишется в {src}, "
                                        f"но не указан в vars.writes")
            for ref in sorted(set(declared["writes"]) - actual_writes):
                rep.warnings.append(f"{unit.yaml_rel}: vars.writes.{ref} объявлен, "
                                    f"но не пишется в {src}")
        if "reads" in declared:
            for ref in sorted(actual_reads - set(declared["reads"])):
                if ref in var_registry:
                    rep.warnings.append(f"{unit.yaml_rel}: {ref} читается в {src}, "
                                        f"но не указан в vars.reads")

    complain = rep.warnings.append if status == "draft" else rep.errors.append
    _validate_refs(unit, rep, complain, image_index=image_index, audio_tracks=audio_tracks)

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


def _inject_voice(rpy_text: str, say_list: list[dict], voiced: set[str]) -> str:
    """Вставить `voice vn.voice_path("<id>")` перед каждой озвученной репликой
    копии авторского текста (C5: компилятор инжектирует voice-операторы в генерат,
    авторский источник не трогается).

    Номера строк — из AST build-bridge (G24), вставки идут снизу вверх, чтобы
    номера ещё не обработанных строк не сдвигались. Отступ наследуется от самой
    реплики — say внутри ветки меню получает voice на той же глубине."""
    if not voiced:
        return rpy_text
    lines = rpy_text.split("\n")
    for say in sorted(say_list, key=lambda s: -int(s.get("line") or 0)):
        sid = say.get("id")
        i = int(say.get("line") or 0) - 1
        if not sid or sid not in voiced or not (0 <= i < len(lines)):
            continue
        indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        lines.insert(i, f'{indent}voice vn.voice_path("{sid}")')
    return "\n".join(lines)


def _emit_track(lines: list[str], unit: SceneUnit, decl: str,
                audio_tracks: dict[str, dict], rep: SceneCompileReport,
                field_name: str) -> None:
    """`music:`/`ambient:` из scene.yaml -> play-оператор на канале по kind трека.

    bgm играет на штатном music (fadeout+fadein = мягкая смена темы между
    сценами), amb — на канале ambient (framework/00_core/045_audio.rpy):
    музыка и эмбиенс локации сосуществуют, а не вытесняют друг друга.
    Объявленная в audio@1 громкость трека применяется здесь же (клауза volume
    play-оператора) — рантайм-кода для неё не существует."""
    kind, _, track = decl.partition("/")
    spec = audio_tracks.get(track)
    if spec is None:
        rep.errors.append(
            f"{unit.yaml_rel}: {field_name} {decl}: трек {track!r} не объявлен "
            f"в content/audio/")
        return
    if spec.get("kind") != kind:
        rep.errors.append(
            f"{unit.yaml_rel}: {field_name} {decl}: трек объявлен как "
            f"{spec.get('kind')}, а не {kind}")
        return
    channel = "music" if kind == "bgm" else "ambient"
    stmt = f"    play {channel} {track} fadeout 1.0 fadein 1.0"
    volume = spec.get("volume")
    if volume is not None and volume != 1:
        stmt += f" volume {volume}"
    lines.append(stmt)


def emit_scene(unit: SceneUnit, dispatch: dict, audio_tracks: dict[str, dict],
               locations: dict, rep: SceneCompileReport, header: str,
               voiced: set[str] | None = None) -> str:
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

    for field_name in ("music", "ambient"):
        decl = unit.meta.get(field_name)
        if decl:
            _emit_track(lines, unit, decl, audio_tracks, rep, field_name)

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
                lines.append('        $ vn_unavailable_reason = "draft_todo"')
                lines.append("        jump vn_scene_unavailable")
            else:
                lines.append(f"        jump {e['to_label']}")

    if not dispatch:
        # Терминальная сцена главы (нет exits) = глава пройдена: якорь для
        # галереи/достижений «за прохождение». Ручного кода в сценах не требует.
        lines.append(f'    $ vn.chapter_done("{unit.chapter_id}")')
        lines.append("    if _return is None:")
        lines.append("        jump vn_end_of_content")
    lines.append("    # Неизвестный exit: разматываем стек и уходим на «сцена недоступна» (G7)")
    lines.append("    $ vn.unwind_call_stack()")
    lines.append('    $ vn_unavailable_reason = "unknown_exit"')
    lines.append("    jump vn_scene_unavailable")
    lines.append("")
    lines.append(f"# ══ Авторский источник (копия): {unit.rpy_rel} ══")
    body = _inject_voice(unit.rpy_text, unit.analysis.get("say_list") or [],
                         voiced or set())
    lines.append(body.rstrip("\n"))
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
# Экран выбора глав (C14): собран из данных Chapter Registry
# и компонентов framework/20_ui (vn_game_menu / vn_chapter_card).
screen chapter_select():
    tag menu
    use vn_game_menu(vn_loc.t("ui.nav.chapters")):
        hbox:
            spacing gui.sp_l
            box_wrap True
            box_wrap_spacing gui.sp_l
            for ch in VN_CHAPTERS:
                # Владение паком — логический гейт (G9): непокупные главы не видны
                if vn.pack_registry.owned(ch["pack"]):
                    use vn_chapter_card(ch)
'''
