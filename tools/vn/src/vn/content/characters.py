"""vn char validate / vn char sheet — проверка персонажа и лист арт-ревью (раздел 4).

Зачем отдельная команда, если `vn build` и так всё проверяет. Отличие ровно одно, и
оно решает задачу художника: здесь НЕ запускается сборка ассетов и не нужен Ren'Py
SDK. Полный `vn build` перекодирует всё дерево (минуты) и тянет видео-ветку, которая
без ffmpeg объявляет ошибку — то есть цикл «поправил слой → узнал, что не так»
упирался в тракт, к персонажу не относящийся.

Что здесь принципиально: **новых проверок не вводится**. Контракт полноты матрицы —
одна функция `images.check_matrix`, ту же зовёт эмиттер layeredimage; геометрия
мастеров — `assets.pipeline.character_jobs`, та же ветка, что в сборке. Копия
проверки разошлась бы с оригиналом на первой правке, и «зелёный validate при красном
build» был бы хуже отсутствия команды.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..assets.imaging import ImagingError, composite, probe
from ..assets.pipeline import (
    AssetBuildResult,
    asset_ext,
    character_jobs,
    orphan_masters,
    sprite_tree,
)
from ..assets.render_config import load_render_config
from ..repo import load_yaml
from ..schemas import SchemaRegistry
from .images import LAYER_ORDER, check_matrix

CHAR_DIR = "characters"
REVIEW_REL = "build/review"
# Подложка ячеек листа: спрайты — вырезы с альфой, и на белом теряются светлые
# контуры, на чёрном — тёмные. Средне-серый честен к обоим.
SHEET_BG = (128, 128, 128)


class CharError(RuntimeError):
    """Команда не может продолжать: нет данных, а не «данные плохие»."""


@dataclass
class CharReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def char_dirs(root: Path) -> list[Path]:
    """Каталоги персонажей `content/characters/*/` (по наличию каталога, не файла:
    папка без character.yaml — это ошибка, о которой надо сказать, а не пропустить)."""
    base = root / "content" / CHAR_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir())


def declaration_errors(root: Path, char_dir: Path, doc: dict | None) -> list[str]:
    """Правила уровня файла: декларация есть и её id равен имени папки.

    Вынесено из `content.lint`, чтобы правило жило в одном месте: lint и
    `vn char validate` обязаны говорить одно и то же одними словами."""
    rel = (char_dir / "character.yaml").relative_to(root).as_posix()
    if not (char_dir / "character.yaml").is_file():
        return [f"content/{CHAR_DIR}/{char_dir.name}: нет character.yaml"]
    if not doc:
        return [f"{rel}: пустой или нечитаемый документ"]
    if doc.get("id") != char_dir.name:
        return [f"{rel}: id ({doc.get('id')!r}) != имени папки ({char_dir.name!r})"]
    return []


def load_docs(root: Path, only: str | None = None) -> tuple[list[tuple[str, dict]], list[str]]:
    """([(rel, документ)], ошибки). Документ с ошибкой схемы дальше не идёт: считать
    матрицу по невалидной декларации значит выдавать вторую ошибку про первую."""
    registry = SchemaRegistry(root / "tools" / "schemas")
    docs: list[tuple[str, dict]] = []
    errors: list[str] = []
    dirs = char_dirs(root)
    if only is not None:
        dirs = [d for d in dirs if d.name == only]
        if not dirs:
            raise CharError(
                f"персонажа {only!r} нет в content/{CHAR_DIR}/ — заведите его "
                f"командой vn char new {only}")
    for d in dirs:
        path = d / "character.yaml"
        doc = load_yaml(path) if path.is_file() else None
        decl_errs = declaration_errors(root, d, doc)
        if decl_errs:
            errors += decl_errs
            continue
        rel = path.relative_to(root).as_posix()
        schema_errs = registry.validate(doc, rel)
        if schema_errs:
            errors += schema_errs
            continue
        docs.append((rel, doc))
    return docs, errors


def _master_canvas(root: Path, char_id: str) -> tuple[int, int] | None:
    """Фактический холст мастеров персонажа (по первому найденному base)."""
    for art in (root / "assets_src" / "art", root / ".vncache" / "psd_png"):
        base_dir = art / CHAR_DIR / char_id
        if not base_dir.is_dir():
            continue
        for pose_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
            for f in sorted(pose_dir.glob("base.*")):
                try:
                    return tuple(probe(f)["size"])
                except (ImagingError, KeyError):
                    continue
    return None


def validate(root: Path, only: str | None = None) -> CharReport:
    """Декларация + геометрия мастеров + полнота матрицы против собранных слоёв."""
    rep = CharReport()
    docs, errors = load_docs(root, only)
    rep.errors += errors

    cfg = load_render_config(root)
    tree = sprite_tree(root)
    declared_ids = {doc["id"] for _rel, doc in docs}

    for rel, doc in docs:
        char_id = doc["id"]
        # Геометрия мастеров: формат, альфа, source_min, единство холста. Задания
        # выбрасываем — нужен только отчёт; ни один байт не пишется.
        arep = AssetBuildResult()
        consumed: set[Path] = set()
        character_jobs(root, arep, cfg, consumed, only=char_id)
        zones = [p / CHAR_DIR / char_id for p in
                 (root / "assets_src" / "art", root / ".vncache" / "psd_png")]
        orphan_masters(root, consumed, arep, zones=[z for z in zones if z.is_dir()])
        rep.errors += arep.errors
        rep.warnings += arep.warnings

        poses = check_matrix(root, rel, doc, tree.get(char_id, {}), rep)

        matrix = doc.get("matrix") or {}
        built = tree.get(char_id, {})
        layers = sum(len(v["outfits"]) + len(v["faces"]) + len(v["overlays"]) + 1
                     for v in built.values())
        rep.rows.append(
            f"{char_id}: поз {len(matrix.get('poses') or [])} / нарядов "
            f"{len(matrix.get('outfits') or [])} / эмоций "
            f"{len(matrix.get('emotions') or [])}; собрано слоёв {layers}, "
            f"эмитируемых поз {len(poses)}")
        canvas = _master_canvas(root, char_id)
        declared = doc.get("canvas")
        if canvas and not declared:
            rep.warnings.append(
                f"{rel}: холст мастеров не объявлен — впишите `canvas: "
                f"[{canvas[0]}, {canvas[1]}]` (ADR-0012: слои позы складываются в "
                f"(0,0), и расхождение холста смещает наряд относительно тела)")
        elif canvas and tuple(declared) != canvas:
            rep.errors.append(
                f"{rel}: canvas {list(declared)} != фактического холста мастеров "
                f"{list(canvas)}")

    # Мастера без декларации: художник рисует в пустоту — компилятор их не увидит.
    for art in (root / "assets_src" / "art", root / ".vncache" / "psd_png"):
        base = art / CHAR_DIR
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if (only is None or d.name == only) and d.name not in declared_ids:
                rep.warnings.append(
                    f"{d.relative_to(root).as_posix()}: мастера есть, декларации "
                    f"content/{CHAR_DIR}/{d.name}/character.yaml нет — слои не "
                    f"эмитируются")

    # Персонаж в паке: конвейер его мастера видит, а реестр компилятора — нет.
    packs = root / "packs"
    if packs.is_dir():
        for pack in sorted(p for p in packs.iterdir() if p.is_dir()):
            pack_chars = pack / CHAR_DIR
            if not pack_chars.is_dir():
                continue
            for d in sorted(p for p in pack_chars.iterdir() if p.is_dir()):
                if only is None or d.name == only:
                    rep.warnings.append(
                        f"{d.relative_to(root).as_posix()}: персонажи паков в реестр "
                        f"не попадают — компилятор читает только content/{CHAR_DIR}/")
    return rep


def _combinations(matrix: dict, built: dict) -> list[tuple[str, str, str]]:
    """(поза, наряд, эмоция) — только собранные и не запрещённые декларацией."""
    forbidden_outfits: dict[str, set[str]] = {}
    forbidden_faces: dict[str, set[str]] = {}
    for forb in matrix.get("forbidden") or []:
        pose = forb["pose"]
        forbidden_outfits.setdefault(pose, set()).update(forb.get("outfits") or [])
        forbidden_faces.setdefault(pose, set()).update(forb.get("emotions") or [])
    out: list[tuple[str, str, str]] = []
    for pose in matrix.get("poses") or []:
        have = built.get(pose)
        if not have or not have["base"]:
            continue
        for outfit in matrix.get("outfits") or []:
            if outfit not in have["outfits"] or outfit in forbidden_outfits.get(pose, ()):
                continue
            for emotion in matrix.get("emotions") or []:
                if emotion not in have["faces"] or emotion in forbidden_faces.get(pose, ()):
                    continue
                out.append((pose, outfit, emotion))
    return out


def _index_html(char_id: str, doc: dict, cells: list[tuple[str, str]],
                rep: CharReport) -> str:
    """Страница листа: сетка ячеек, счётчики, замечания валидатора."""
    import html

    rows = "".join(
        f'<figure><img src="cells/{html.escape(f)}" alt="{html.escape(cap)}" loading="lazy">'
        f"<figcaption>{html.escape(cap)}</figcaption></figure>" for f, cap in cells)
    problems = "".join(f"<li class='err'>{html.escape(e)}</li>" for e in rep.errors) + \
               "".join(f"<li class='warn'>{html.escape(w)}</li>" for w in rep.warnings)
    name = html.escape(str(doc.get("name") or char_id))
    canvas = doc.get("canvas")
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(char_id)} — лист арт-ревью</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 24px; background: #18181b; color: #e4e4e7 }}
 h1 {{ font-size: 22px; margin: 0 0 4px }}
 .meta {{ color: #a1a1aa; margin-bottom: 20px }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px }}
 figure {{ margin: 0; background: #27272a; border-radius: 8px; overflow: hidden }}
 img {{ width: 100%; display: block; background: #808080 }}
 figcaption {{ padding: 8px 10px; font-size: 13px; color: #d4d4d8 }}
 ul {{ padding-left: 20px }} .err {{ color: #f87171 }} .warn {{ color: #fbbf24 }}
</style>
<h1>{name} <code>{html.escape(char_id)}</code></h1>
<div class="meta">ячеек: {len(cells)}
 · холст мастеров: {html.escape(str(canvas) if canvas else "не объявлен")}
 · порядок слоёв: {" → ".join(LAYER_ORDER)}
 · сгенерировано <code>vn char sheet</code></div>
{"<ul>" + problems + "</ul>" if problems else ""}
<div class="grid">{rows}</div>
"""


def sheet(root: Path, char_id: str, out_dir: Path | None = None,
          max_side: int | None = None) -> Path:
    """Лист арт-ревью: ячейки-композиции всех допустимых комбинаций + index.html.

    Склейка идёт в том же z-порядке, что у эмиттера (`images.LAYER_ORDER`), поэтому
    ревьюер смотрит на то, что увидит игрок, а не на слои по отдельности."""
    docs, errors = load_docs(root, only=char_id)
    if not docs:
        raise CharError("декларация не проходит проверку, лист не строится:\n  - "
                        + "\n  - ".join(errors))
    rel, doc = docs[0]
    built = sprite_tree(root).get(char_id) or {}
    if not built:
        raise CharError(f"в game/assets/spr/{char_id}/ пусто — сначала vn assets build")
    combos = _combinations(doc.get("matrix") or {}, built)
    if not combos:
        raise CharError(f"{rel}: ни одной допустимой комбинации поза+наряд+эмоция — "
                        f"нечего показывать (проверьте matrix и собранные слои)")

    cfg = load_render_config(root)
    out_dir = out_dir or root / REVIEW_REL / char_id
    if out_dir.exists():
        shutil.rmtree(out_dir)          # идемпотентность: старые ячейки — не результат
    (out_dir / "cells").mkdir(parents=True)
    ext = asset_ext(root, f"spr/{char_id}/{combos[0][0]}/base")
    thumb = cfg.thumb
    cells: list[tuple[str, str]] = []
    for pose, outfit, emotion in combos:
        base = root / "game" / "assets" / "spr" / char_id / pose
        layers = [base / f"base{ext}", base / "outfits" / f"{outfit}{ext}",
                  base / "faces" / f"{emotion}{ext}"]
        data = composite([p for p in layers if p.is_file()],
                         quality=int(thumb["quality"]),
                         out_format=str(thumb.get("out_format") or "webp"),
                         max_side=max_side or int(thumb["max_side"]),
                         background=SHEET_BG)
        name = f"{pose}__{outfit}__{emotion}.{str(thumb.get('out_format') or 'webp')}"
        (out_dir / "cells" / name).write_bytes(data)
        cells.append((name, f"{pose} · {outfit} · {emotion}"))

    rep = validate(root, only=char_id)
    (out_dir / "index.html").write_text(_index_html(char_id, doc, cells, rep),
                                        encoding="utf-8")
    return out_dir / "index.html"


def sheet_index(root: Path, pages: dict[str, Path]) -> Path:
    """Общая страница со ссылками на листы — для `--all`."""
    import html

    out = root / REVIEW_REL / "index.html"
    items = "".join(
        f'<li><a href="{html.escape(p.parent.name)}/index.html">'
        f"{html.escape(cid)}</a></li>" for cid, p in sorted(pages.items()))
    out.write_text(
        "<!doctype html>\n<meta charset=\"utf-8\">\n<title>Листы арт-ревью</title>\n"
        "<style>body{font:15px/1.6 system-ui,sans-serif;margin:24px;background:#18181b;"
        "color:#e4e4e7}a{color:#93c5fd}</style>\n"
        f"<h1>Листы арт-ревью ({len(pages)})</h1>\n<ul>{items}</ul>\n",
        encoding="utf-8")
    return out
