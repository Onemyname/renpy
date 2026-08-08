"""vn assets build — ассет-конвейер (раздел 2, G13).

Зоны: assets_src/ (сырцы) -> трансформации -> game/assets/ (game-ready). Художник
никогда не пишет в game/ (G2). Кэш — контентно-адресуемый: ключ = blake3(сырец) +
id и ВЕРСИЯ конкретной трансформации + профиль (G13: бамп версии png2webp не
инвалидирует аудио-ветку). Очистка game/assets — точечная, по диффу манифестов.

Конвенция источников (открытый промежуточный формат; PSD нарезается в неё же — psd.py):
  assets_src/png/characters/<key>/<pose>/base.png
  assets_src/png/characters/<key>/<pose>/outfits/<outfit>.png
  assets_src/png/characters/<key>/<pose>/faces/<emotion>.png
  assets_src/png/characters/<key>/<pose>/overlays/<name>.png
  assets_src/png/backgrounds/<location>/<variant>.png
  assets_src/png/cg/<...>/<name>.png                     # CG-стиллы (DAZ-рендеры, ADR-0006)
  assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg
  assets_src/video_src/<group>/<name>.(mp4|mov|mkv|webm|m4v|avi)   # видео (ADR-0006)
Выходы:
  game/assets/spr/<key>/<pose>/{base@2.webp, outfits/<o>@2.webp, faces/<e>@2.webp, overlays/<n>@2.webp}
  game/assets/bg/<location>/<variant>.webp
  game/assets/cg/<...>/<name>.webp
  game/assets/audio/{bgm,amb,sfx}/<id>.ogg
  game/assets/mov/<group>/<name>.webm (+ .webm.meta.json — mov_meta@1)
"""

from __future__ import annotations

import io
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import blake3

# Версии трансформаций (G13): бамп инвалидирует только свою ветку кэша.
# video2webm: версия = пресет ffmpeg (video.encode_args) — меняете пресет, бампайте.
TRANSFORMS = {
    "png2webp_sprite": "1",
    "png2webp_bg": "1",
    "png2webp_cg": "1",
    "png2webp_cg_thumb": "1",
    "ui_panel": "1",
    "copy_audio": "1",
    "video2webm": "1",
}

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MANIFEST = "assets-manifest.json"


class AssetError(RuntimeError):
    pass


@dataclass
class AssetBuildResult:
    built: list[str] = field(default_factory=list)      # прогнаны трансформацией
    from_cache: list[str] = field(default_factory=list)  # взяты из кэша
    fresh: list[str] = field(default_factory=list)       # на диске уже актуальные
    deleted: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)       # только в режиме check
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _b3_bytes(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    """tmp + os.replace: прерванная запись (Ctrl+C в watch, kill по таймауту) не должна
    оставлять обрезанный файл — обрезанный кэш-блоб отравлял бы сборки навсегда."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _webp_encode(src: Path, quality: int, max_side: int | None = None) -> bytes:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGBA")
        if max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=quality, method=4)
        return buf.getvalue()


def _check_slug(rep: AssetBuildResult, rel: str, *parts: str) -> bool:
    for p in parts:
        if not SLUG_RE.match(p):
            rep.errors.append(f"{rel}: сегмент {p!r} вне конвенции ^[a-z][a-z0-9_]*$ (naming.md)")
            return False
    return True


def _discover(root: Path, rep: AssetBuildResult) -> list[tuple[Path, str, str, dict | None]]:
    """[(источник, транформация, выход относительно game/assets/, extra)].
    Слои персонажей собираются из двух деревьев одной конвенции: ручной экспорт
    (assets_src/png) и staging PSD-нарезки (.vncache/psd_png); конфликт на один
    выход ловится в build_assets. extra — только у видео (опции sidecar)."""
    jobs: list[tuple[Path, str, str, dict | None]] = []
    png = root / "assets_src" / "png"

    char_bases = [png / "characters", root / ".vncache" / "psd_png" / "characters"]
    for chars in char_bases:
        if not chars.is_dir():
            continue
        for key_dir in sorted(p for p in chars.iterdir() if p.is_dir()):
            for pose_dir in sorted(p for p in key_dir.iterdir() if p.is_dir()):
                rel = pose_dir.relative_to(root).as_posix()
                if not _check_slug(rep, rel, key_dir.name, pose_dir.name):
                    continue
                base = pose_dir / "base.png"
                if base.is_file():
                    jobs.append((base, "png2webp_sprite",
                                 f"spr/{key_dir.name}/{pose_dir.name}/base@2.webp", None))
                else:
                    rep.errors.append(f"{rel}: нет обязательного base.png")
                for group in ("outfits", "faces", "overlays"):
                    gdir = pose_dir / group
                    if not gdir.is_dir():
                        continue
                    for f in sorted(gdir.glob("*.png")):
                        name = f.stem
                        if not _check_slug(rep, f"{rel}/{group}/{f.name}", name):
                            continue
                        jobs.append((f, "png2webp_sprite",
                                     f"spr/{key_dir.name}/{pose_dir.name}/{group}/{name}@2.webp",
                                     None))

    bgs = png / "backgrounds"
    if bgs.is_dir():
        for loc_dir in sorted(p for p in bgs.iterdir() if p.is_dir()):
            for f in sorted(loc_dir.glob("*.png")):
                rel = f"assets_src/png/backgrounds/{loc_dir.name}/{f.name}"
                if not _check_slug(rep, rel, loc_dir.name, f.stem):
                    continue
                jobs.append((f, "png2webp_bg", f"bg/{loc_dir.name}/{f.stem}.webp", None))

    # CG-стиллы (DAZ-рендеры и AI-обработка, ADR-0006): вложенность произвольная,
    # каждый сегмент — slug; nsfw-контент живёт в cg/nsfw/** (гейт флейворов).
    cg = png / "cg"
    if cg.is_dir():
        for f in sorted(cg.rglob("*.png")):
            rel_parts = f.relative_to(cg).parts
            rel = f"assets_src/png/cg/{f.relative_to(cg).as_posix()}"
            if not _check_slug(rep, rel, *rel_parts[:-1], f.stem):
                continue
            base = "cg/" + "/".join([*rel_parts[:-1], f.stem])
            jobs.append((f, "png2webp_cg", base + ".webp", None))
            jobs.append((f, "png2webp_cg_thumb", base + ".thumb.webp", None))

    # Зона звука — audio_stems (ARCHITECTURE.md:393, conventions/folder-layout.md:29):
    # имя нормативное, менять его пришлось бы через ADR, поэтому код идёт к норме.
    audio = root / "assets_src" / "audio_stems"
    if audio.is_dir():
        for kind in ("bgm", "amb", "sfx"):
            kdir = audio / kind
            if not kdir.is_dir():
                continue
            for f in sorted(kdir.glob("*.ogg")):
                if not _check_slug(rep, f"assets_src/audio_stems/{kind}/{f.name}", f.stem):
                    continue
                jobs.append((f, "copy_audio", f"audio/{kind}/{f.name}", None))

    # Видео-лупы (ADR-0006): assets_src/video_src/<group>/<name>.<ext> [+ <name>.video.yaml]
    from . import video as videomod

    vsrc = root / "assets_src" / "video_src"
    if vsrc.is_dir():
        vfiles = [f for f in sorted(vsrc.rglob("*"))
                  if f.is_file() and f.suffix.lower() in videomod.VIDEO_EXTS]
        if vfiles:
            from ..pipeline import find_ffmpeg, find_ffprobe

            if find_ffmpeg() is None or find_ffprobe() is None:
                rep.errors.append(
                    "assets_src/video_src: есть видео-сырцы, но ffmpeg/ffprobe не найдены "
                    "(vn pipeline doctor) — видео-трек не собирается")
                return jobs
        for f in vfiles:
            rel_parts = f.relative_to(vsrc).parts
            rel = f"assets_src/video_src/{f.relative_to(vsrc).as_posix()}"
            if len(rel_parts) < 2:
                rep.errors.append(f"{rel}: видео кладутся в группу — "
                                  f"video_src/<group>/<name>.<ext> (naming.md)")
                continue
            if not _check_slug(rep, rel, *rel_parts[:-1], f.stem):
                continue
            sidecar = f.with_name(f.stem + videomod.SIDECAR_SUFFIX)
            opts, opt_errors = videomod.load_opts(sidecar)
            if opt_errors:
                rep.errors.extend(opt_errors)
                continue
            out = "mov/" + "/".join([*rel_parts[:-1], f.stem]) + ".webm"
            extra = {"opts": opts, "sidecar": sidecar if sidecar.is_file() else None}
            jobs.append((f, "video2webm", out, extra))

    # UI-панели (ADR-0009): источник — не файл, а декларация; рисует конвейер.
    panels_decl = root / "content" / "ui" / "panels.yaml"
    if panels_decl.is_file():
        from ..repo import load_yaml

        doc = load_yaml(panels_decl)
        for pid, spec in sorted((doc.get("panels") or {}).items()):
            if not SLUG_RE.match(pid):
                rep.errors.append(f"content/ui/panels.yaml: панель {pid!r} вне "
                                  f"конвенции ^[a-z][a-z0-9_]*$")
                continue
            jobs.append((panels_decl, "ui_panel", f"ui/{pid}.webp", {"spec": spec}))

    return jobs


def _transform(src: Path, transform: str, profile: str) -> bytes:
    if transform == "png2webp_sprite":
        return _webp_encode(src, quality=50 if profile == "draft" else 95)
    if transform == "png2webp_bg":
        return _webp_encode(src, quality=50 if profile == "draft" else 90)
    if transform == "png2webp_cg":
        return _webp_encode(src, quality=50 if profile == "draft" else 90)
    if transform == "png2webp_cg_thumb":
        # Превью галереи: длинная сторона 512 — галерея не должна декодировать
        # полноразмерные CG ради сетки миниатюр.
        return _webp_encode(src, quality=80, max_side=512)
    if transform == "copy_audio":
        return src.read_bytes()
    raise AssetError(f"неизвестная трансформация {transform!r}")


def _transform_ui_panel(spec: dict, profile: str) -> bytes:
    """UI-панель: рисуется из декларации (источник — не файл, а параметры)."""
    from . import ui as uimod
    from PIL import Image

    png = uimod.render_panel(spec)
    with Image.open(io.BytesIO(png)) as im:
        buf = io.BytesIO()
        # lossless: 9-patch тянется движком, артефакты сжатия поехали бы по краям
        im.convert("RGBA").save(buf, format="WEBP", lossless=True,
                                quality=100, method=4 if profile == "full" else 0)
        return buf.getvalue()


def build_assets(root: Path, profile: str = "full", check: bool = False,
                 only_transforms: set[str] | None = None) -> AssetBuildResult:
    """Инкрементальная сборка game/assets из assets_src (+ нарезка PSD, psd.py).
    check=True: НИЧЕГО не пишется — только discovery-ошибки и список несвежих выходов.
    only_transforms: собрать подмножество трансформаций (например {"video2webm"});
    манифест и orphan-очистка остальных веток не трогаются."""
    from . import video as videomod

    rep = AssetBuildResult()
    out_root = root / "game" / "assets"
    cache_dir = root / ".vncache" / "assets"
    video_tmp = root / ".vncache" / "video-tmp"
    if not check:
        cache_dir.mkdir(parents=True, exist_ok=True)

        # PSD -> staging PNG-дерево той же конвенции (боевой путь художника, раздел 2)
        from .psd import slice_all_psd
        slice_all_psd(root, rep)

    jobs = _discover(root, rep)
    if rep.errors:
        return rep

    # Подмножество трансформаций: у видео два выхода (webm + meta), они одна ветка.
    effective_only = set(only_transforms) if only_transforms else None
    if effective_only and "video2webm" in effective_only:
        effective_only.add("mov_meta")
    if effective_only and not check:
        jobs = [j for j in jobs if j[1] in effective_only]

    from ..repo import load_project
    try:
        file_budget = (load_project(root).get("budgets") or {}).get("video_file_mb")
    except Exception:
        file_budget = None

    seen_outputs: dict[str, dict] = {}
    for src, transform, out_rel, extra in jobs:
        if out_rel in seen_outputs:
            rep.errors.append(f"{out_rel}: два источника претендуют на один выход")
            continue
        try:
            src_bytes = src.read_bytes()
        except OSError as e:
            # Залоченный/дописываемый файл (Photoshop, антивирус) — ошибка, не трейсбек.
            rep.errors.append(f"{src.relative_to(root).as_posix()}: не читается: {e}")
            continue
        src_hash = _b3_bytes(src_bytes)
        if transform == "video2webm" and extra:
            # Sidecar-опции — часть источника: правка <name>.video.yaml инвалидирует выход.
            sidecar = extra.get("sidecar")
            sidecar_bytes = sidecar.read_bytes() if sidecar else b""
            src_hash = _b3_bytes(src_bytes + b"\x00" + sidecar_bytes)
        elif transform == "ui_panel" and extra:
            # Источник панели — её параметры, а не весь файл деклараций: правка
            # одной панели не должна перерисовывать все остальные.
            from . import ui as uimod
            src_hash = _b3_bytes(uimod.panel_hash_source(extra["spec"]))
        key = _b3_bytes(
            f"{src_hash}:{transform}:{TRANSFORMS[transform]}:{profile}".encode()
        )
        blob = cache_dir / key[:2] / key
        dest = out_root / out_rel
        meta_rel = out_rel + videomod.META_SUFFIX if transform == "video2webm" else None

        if check:
            seen_outputs[out_rel] = {
                "src_hash": src_hash,
                "transform": f"{transform}@{TRANSFORMS[transform]}",
                "profile": profile,
            }
            if not dest.is_file():
                rep.stale.append(f"{out_rel} (нет файла)")
            if meta_rel:
                seen_outputs[meta_rel] = {
                    "src_hash": src_hash,
                    "transform": f"mov_meta@{TRANSFORMS[transform]}",
                    "profile": profile,
                }
                if dest.is_file() and not (out_root / meta_rel).is_file():
                    rep.stale.append(f"{meta_rel} (нет файла)")
            continue

        if blob.is_file():
            data = blob.read_bytes()
            origin = "cache"
        else:
            try:
                if transform == "video2webm":
                    data = videomod.encode_video(src, extra["opts"], profile, video_tmp)
                elif transform == "ui_panel":
                    data = _transform_ui_panel(extra["spec"], profile)
                else:
                    data = _transform(src, transform, profile)
            except (OSError, videomod.VideoError) as e:
                rep.errors.append(f"{src.relative_to(root).as_posix()}: трансформация упала: {e}")
                continue
            _write_atomic(blob, data)
            origin = "built"

        wrote_now = False
        if dest.is_file() and dest.read_bytes() == data:
            rep.fresh.append(out_rel)
        else:
            _write_atomic(dest, data)
            (rep.from_cache if origin == "cache" else rep.built).append(out_rel)
            wrote_now = True

        seen_outputs[out_rel] = {
            "src": src.relative_to(root).as_posix(),
            "src_hash": src_hash,
            "out_hash": _b3_bytes(data),
            "transform": f"{transform}@{TRANSFORMS[transform]}",
            "profile": profile,
        }

        if meta_rel:
            # Валидация лупа/совместимости + метаданные (mov_meta@1) — контракт
            # для эмиттера Movie-образов. Ошибки валидации = красная сборка.
            meta_dest = out_root / meta_rel
            if wrote_now or not meta_dest.is_file():
                v_errors, v_warnings, summary = videomod.validate_output(
                    dest, extra["opts"], video_tmp, file_budget_mb=file_budget)
                rep.warnings.extend(v_warnings)
                if v_errors:
                    rep.errors.extend(v_errors)
                    continue
                meta = videomod.build_meta(
                    out_rel, extra["opts"], summary,
                    src.relative_to(root).as_posix(), src_hash,
                    seen_outputs[out_rel]["out_hash"],
                    f"{transform}@{TRANSFORMS[transform]}", profile)
                _write_atomic(meta_dest, (json.dumps(
                    meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
            seen_outputs[meta_rel] = {
                "src": src.relative_to(root).as_posix(),
                "src_hash": src_hash,
                "out_hash": _b3_bytes(meta_dest.read_bytes()),
                "transform": f"mov_meta@{TRANSFORMS[transform]}",
                "profile": profile,
            }

    manifest_path = root / ".vncache" / MANIFEST
    old_manifest: dict = {}
    if manifest_path.is_file():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["outputs"]
        except Exception:
            pass

    if check:
        # Несвежесть = источник/трансформация/профиль разошлись с манифестом сборки.
        for out_rel, info in seen_outputs.items():
            prev = old_manifest.get(out_rel)
            if not (out_root / out_rel).is_file():
                continue    # уже помечен как «нет файла»
            if prev is None:
                rep.stale.append(f"{out_rel} (нет в манифесте — соберите vn assets build)")
            elif any(prev.get(k) != info[k] for k in ("src_hash", "transform", "profile")):
                rep.stale.append(f"{out_rel} (источник изменился)")
        for orphan in sorted(set(old_manifest) - set(seen_outputs)):
            if (out_root / orphan).is_file():
                rep.stale.append(f"{orphan} (осиротел)")
        return rep

    # Точечная очистка: выходы прошлого манифеста, исчезнувшие из текущего,
    # плюс опустевшие каталоги (генерат не должен ссылаться в пустоту).
    # При only_transforms чужие ветки не трогаем — ни очисткой, ни манифестом.
    def _branch(info: dict) -> str:
        return (info.get("transform") or "@").split("@")[0]

    candidates = set(old_manifest) - set(seen_outputs)
    if effective_only:
        candidates = {o for o in candidates if _branch(old_manifest[o]) in effective_only}
    for orphan in sorted(candidates):
        p = out_root / orphan
        if p.is_file():
            p.unlink()
            rep.deleted.append(orphan)
            parent = p.parent
            while parent != out_root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent

    final_outputs = dict(seen_outputs)
    if effective_only:
        for out_rel, info in old_manifest.items():
            if _branch(info) not in effective_only and out_rel not in final_outputs:
                final_outputs[out_rel] = info

    manifest = {"schema": "assets_manifest@1", "outputs": final_outputs}
    # G16: объявленный id схемы проверяем на живом документе — иначе расхождение
    # писателя и схемы всплывёт у читателя (cache_gc, --check) уже в виде мусора.
    # Реестра нет только у синтетических корней (тесты) — там сверять не с чем.
    schemas_dir = root / "tools" / "schemas"
    if schemas_dir.is_dir():
        from ..schemas import SchemaRegistry

        rep.errors.extend(
            SchemaRegistry(schemas_dir).validate(manifest, f".vncache/{MANIFEST}"))
    # Пишем даже при ошибке схемы: манифест описывает то, что уже лежит на диске,
    # и без записи следующая сборка потеряет точечную очистку сирот.
    _write_atomic(manifest_path, (json.dumps(
        manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return rep


def cache_gc(root: Path, dry_run: bool = False) -> tuple[int, int]:
    """Убрать блобы кэша трансформаций, не упомянутые в текущем манифесте сборки
    (mark & sweep от манифеста). Кэш иначе растёт неограниченно: каждая правка
    сырца оставляет прошлый блоб навсегда. Возвращает (удалено, освобождено байт)."""
    cache_dir = root / ".vncache" / "assets"
    if not cache_dir.is_dir():
        return 0, 0
    manifest_path = root / ".vncache" / MANIFEST
    live: set[str] = set()
    if manifest_path.is_file():
        try:
            outputs = json.loads(manifest_path.read_text(encoding="utf-8"))["outputs"]
        except Exception:
            outputs = {}
        for info in outputs.values():
            src_hash = info.get("src_hash")
            transform = (info.get("transform") or "@").split("@")[0]
            version = (info.get("transform") or "@").split("@")[-1]
            profile = info.get("profile", "full")
            if src_hash and transform in TRANSFORMS:
                live.add(_b3_bytes(
                    f"{src_hash}:{transform}:{version}:{profile}".encode()))
    removed = freed = 0
    for blob in cache_dir.rglob("*"):
        if not blob.is_file() or blob.name in {MANIFEST}:
            continue
        if blob.name in live:
            continue
        size = blob.stat().st_size
        if not dry_run:
            blob.unlink()
        removed += 1
        freed += size
    return removed, freed


def sprite_tree(root: Path) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Скан собранных спрайтов: {char: {pose: {'base': [...], 'outfits': [...], 'faces': [...], 'overlays': [...]}}}."""
    tree: dict = {}
    spr = root / "game" / "assets" / "spr"
    if not spr.is_dir():
        return tree
    for char_dir in sorted(p for p in spr.iterdir() if p.is_dir()):
        poses: dict = {}
        for pose_dir in sorted(p for p in char_dir.iterdir() if p.is_dir()):
            entry = {"base": [], "outfits": [], "faces": [], "overlays": []}
            if (pose_dir / "base@2.webp").is_file():
                entry["base"].append("base")
            for group in ("outfits", "faces", "overlays"):
                gdir = pose_dir / group
                if gdir.is_dir():
                    entry[group] = sorted(f.name[: -len("@2.webp")] for f in gdir.glob("*@2.webp"))
            poses[pose_dir.name] = entry
        tree[char_dir.name] = poses
    return tree
