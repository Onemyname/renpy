"""Общий валидатор деклараций внешних источников: DAZ, VaM, The Sims 4.

Все три источника подчиняются ОДНОМУ контракту (ADR-0006, ADR-0007):

    декларация (что и чем снято) -> выход в зоне мастеров -> провенанс

Отличаются только имена ключей (`source`/`scene`, `render`/`capture`) и тексты.
Раньше это были три структурные копии, и каждая новая проверка означала три
одинаковые правки в трёх файлах — здесь ровно одно место.

Что проверяется сверх схемы (без этого декларация — просто необязательный YAML):

- **сцена существует** локально или манифестом хранилища — иначе рендер
  невоспроизводим, а провенанс ссылается в пустоту;
- **выход не объявлен дважды** — два источника на один файл дают гонку;
- **id соответствует выходу** — `id` адресует ассет в игре, `output` даёт файл;
  расхождение означает, что декларация описывает не тот кадр, который поедет
  в сборку, и провенанс привязывается не к тому ассету;
- **объявленное разрешение совпадает с фактическим** — «отрендерил в 4K»
  в YAML при 1080p на диске раньше проходило молча, а мастер меньше
  отгружаемого размера ловился уже конвейером и без связи с декларацией.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repo import load_yaml
from ..schemas import SchemaRegistry
from . import provenance as prov

RENDER_SUFFIX = ".render.yaml"

# Зоны мастеров, куда легально смотрит output деклараций.
_ART_PREFIXES = ("art/", "png/")


@dataclass
class SourceReport:
    checked: list[str] = field(default_factory=list)
    provenance_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceKind:
    """Различия между источниками — данные, а не три копии кода."""

    dirname: str            # assets_src/<dirname>
    schema_id: str          # daz_render@1 | vam_render@1 | sims4_render@1
    scene_key: str          # source | scene
    settings_key: str       # render | capture
    prov_kind: str          # daz_render | vam_render | sims4_render
    label: str              # для текстов ошибок
    missing_scene_hint: str


DAZ = SourceKind("daz", "daz_render@1", "source", "render", "daz_render", "DAZ",
                 "vn assets push после сохранения .duf")
VAM = SourceKind("vam", "vam_render@1", "scene", "capture", "vam_render", "VaM",
                 "vn assets push после экспорта сцены")
SIMS4 = SourceKind("sims4", "sims4_render@1", "scene", "capture", "sims4_render",
                   "Sims4", "vn assets push после экспорта Tray-бандла/сейва")

ALL = (DAZ, VAM, SIMS4)


def _logical_id_of_output(output: str) -> str | None:
    """`art/cg/ch01/kiss.png` -> `cg/ch01/kiss`; `video_src/ch01/rain.mp4` -> `mov/ch01/rain`.

    Это та же арифметика, по которой конвейер строит выходы, — поэтому декларация
    и сборка не могут разойтись в понимании того, какой ассет получится."""
    for prefix in _ART_PREFIXES:
        if output.startswith(prefix):
            rest = output[len(prefix):]
            if rest.startswith("characters/"):
                # characters/<key>/<pose>/… -> spr/<key>/<pose>/…
                rest = "spr/" + rest[len("characters/"):]
            elif rest.startswith("backgrounds/"):
                rest = "bg/" + rest[len("backgrounds/"):]
            return rest.rsplit(".", 1)[0]
    if output.startswith("video_src/"):
        return "mov/" + output[len("video_src/"):].rsplit(".", 1)[0]
    return None


def output_for_id(logical_id: str, video: bool = False, ext: str = "png") -> str:
    """Логический id ассета -> путь выхода в зоне мастеров. Обратная операция
    к _logical_id_of_output: скаффолдер и валидатор обязаны считать одинаково."""
    if logical_id.startswith("mov/") or video:
        rest = logical_id.split("/", 1)[1] if logical_id.startswith("mov/") else logical_id
        return f"video_src/{rest}.mp4"
    if logical_id.startswith("spr/"):
        return f"art/characters/{logical_id[len('spr/'):]}.{ext}"
    if logical_id.startswith("bg/"):
        return f"art/backgrounds/{logical_id[len('bg/'):]}.{ext}"
    return f"art/{logical_id}.{ext}"


def scaffold(root: Path, kind: SourceKind, logical_id: str, scene: str,
             resolution: tuple[int, int], ext: str = "png",
             video: bool = False) -> Path:
    """Заготовка декларации по схеме источника.

    Писать YAML руками против схемы с additionalProperties: false — самый частый
    способ потерять полчаса на опечатке в необязательном поле. Скаффолдер
    заполняет обязательные поля и сразу кладёт файл туда, где его найдёт
    валидатор."""
    import yaml

    output = output_for_id(logical_id, video=video, ext=ext)
    decl: dict = {
        "schema": kind.schema_id,
        "id": logical_id,
        kind.scene_key: scene,
        "output": output,
        kind.settings_key: {"resolution": [int(resolution[0]), int(resolution[1])]},
    }
    settings = decl[kind.settings_key]
    if kind is DAZ:
        settings["renderer"] = "iray"
        settings["camera"] = "cam_main"
    else:
        settings["mode"] = "sequence" if video else "screenshot"
    if kind is SIMS4:
        # Обязателен схемой: патчи EA меняют картинку и ломают моды.
        settings["game_version"] = "ЗАПОЛНИТЕ: версия игры на момент захвата"

    tail = logical_id.split("/", 1)[1] if "/" in logical_id else logical_id
    dest = root / "assets_src" / kind.dirname / f"{tail}{RENDER_SUFFIX}"
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        f"# Декларация {kind.label}: что и чем снято. Проверяется "
        f"vn assets {kind.dirname} validate.\n"
        f"# Лицензии использованных продуктов — content/licenses.yaml, поле license.\n"
        + yaml.safe_dump(decl, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return dest


def validate(root: Path, kind: SourceKind, scope: str | None = None,
             write_provenance: bool = True) -> SourceReport:
    rep = SourceReport()
    registry = SchemaRegistry(root / "tools" / "schemas")
    base = root / "assets_src"
    src_dir = base / kind.dirname
    if not src_dir.is_dir():
        return rep
    seen_outputs: dict[str, str] = {}
    for decl_path in sorted(src_dir.rglob(f"*{RENDER_SUFFIX}")):
        rel = decl_path.relative_to(root).as_posix()
        if scope and not decl_path.relative_to(src_dir).as_posix().startswith(
                scope.rstrip("/")):
            continue
        decl = load_yaml(decl_path)
        errs = registry.validate(decl, rel)
        if errs:
            rep.errors.extend(errs)
            continue
        rep.checked.append(rel)

        scene_rel = decl[kind.scene_key]
        scene = base / scene_rel
        scene_manifest = base / (scene_rel + ".manifest.json")
        if not scene.is_file() and not scene_manifest.is_file():
            rep.errors.append(
                f"{rel}: сцены {scene_rel} нет ни локально, ни в манифестах "
                f"({kind.missing_scene_hint})")

        output = decl["output"]
        if output in seen_outputs:
            rep.errors.append(f"{rel}: выход {output} уже объявлен "
                              f"в {seen_outputs[output]}")
            continue
        seen_outputs[output] = rel

        # id vs output: декларация обязана описывать тот ассет, который реально
        # получится из её выхода, иначе провенанс привязан не к тому кадру.
        expected_id = _logical_id_of_output(output)
        if expected_id and decl["id"] != expected_id:
            rep.errors.append(
                f"{rel}: id {decl['id']!r} не соответствует выходу {output} "
                f"(ожидался {expected_id!r}) — декларация описывает не тот ассет, "
                f"который поедет в сборку")

        out_path = base / output
        if not out_path.is_file():
            rep.warnings.append(f"{rel}: выход {output} ещё не получен")
            continue

        _check_resolution(rep, rel, decl, kind, out_path)

        if write_provenance:
            try:
                p = prov.record_render(
                    root, decl_path.relative_to(base).as_posix(), out_path,
                    kind.prov_kind, scene_rel, decl[kind.settings_key])
                rep.provenance_written.append(p.relative_to(root).as_posix())
            except prov.ProvenanceError as e:
                rep.errors.append(f"{rel}: {e}")
    return rep


def _check_resolution(rep: SourceReport, rel: str, decl: dict, kind: SourceKind,
                      out_path: Path) -> None:
    """Объявленное разрешение против фактического файла.

    Растр меряем напрямую; видео — только если рядом есть ffprobe (в его
    отсутствие молчим: видео-трек и так объявляет о себе отдельной ошибкой)."""
    declared = (decl.get(kind.settings_key) or {}).get("resolution")
    if not declared:
        return
    want = (int(declared[0]), int(declared[1]))
    actual: tuple[int, int] | None = None
    if out_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        from . import imaging

        try:
            actual = imaging.probe(out_path)["size"]
        except imaging.ImagingError as e:
            rep.errors.append(f"{rel}: выход {out_path.name} не читается: {e}")
            return
    else:
        from . import video as videomod
        from ..pipeline import find_ffprobe

        if find_ffprobe() is None:
            return
        try:
            s = videomod.summarize(out_path)
            actual = (s["width"], s["height"])
        except videomod.VideoError:
            return
    if actual and actual != want:
        rep.errors.append(
            f"{rel}: объявлено {kind.settings_key}.resolution {want[0]}x{want[1]}, "
            f"а файл {actual[0]}x{actual[1]} — декларация не описывает то, что "
            f"лежит на диске (пере-рендер или правка декларации)")
