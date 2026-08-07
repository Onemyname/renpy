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
  assets_src/audio/{bgm,amb,sfx}/<id>.ogg
Выходы:
  game/assets/spr/<key>/<pose>/{base@2.webp, outfits/<o>@2.webp, faces/<e>@2.webp, overlays/<n>@2.webp}
  game/assets/bg/<location>/<variant>.webp
  game/assets/audio/{bgm,amb,sfx}/<id>.ogg
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
TRANSFORMS = {
    "png2webp_sprite": "1",
    "png2webp_bg": "1",
    "copy_audio": "1",
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


def _webp_encode(src: Path, quality: int) -> bytes:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=quality, method=4)
        return buf.getvalue()


def _check_slug(rep: AssetBuildResult, rel: str, *parts: str) -> bool:
    for p in parts:
        if not SLUG_RE.match(p):
            rep.errors.append(f"{rel}: сегмент {p!r} вне конвенции ^[a-z][a-z0-9_]*$ (naming.md)")
            return False
    return True


def _discover(root: Path, rep: AssetBuildResult) -> list[tuple[Path, str, str]]:
    """[(источник, транформация, выход относительно game/assets/)].
    Слои персонажей собираются из двух деревьев одной конвенции: ручной экспорт
    (assets_src/png) и staging PSD-нарезки (.vncache/psd_png); конфликт на один
    выход ловится в build_assets."""
    jobs: list[tuple[Path, str, str]] = []
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
                                 f"spr/{key_dir.name}/{pose_dir.name}/base@2.webp"))
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
                                     f"spr/{key_dir.name}/{pose_dir.name}/{group}/{name}@2.webp"))

    bgs = png / "backgrounds"
    if bgs.is_dir():
        for loc_dir in sorted(p for p in bgs.iterdir() if p.is_dir()):
            for f in sorted(loc_dir.glob("*.png")):
                rel = f"assets_src/png/backgrounds/{loc_dir.name}/{f.name}"
                if not _check_slug(rep, rel, loc_dir.name, f.stem):
                    continue
                jobs.append((f, "png2webp_bg", f"bg/{loc_dir.name}/{f.stem}.webp"))

    audio = root / "assets_src" / "audio"
    if audio.is_dir():
        for kind in ("bgm", "amb", "sfx"):
            kdir = audio / kind
            if not kdir.is_dir():
                continue
            for f in sorted(kdir.glob("*.ogg")):
                if not _check_slug(rep, f"assets_src/audio/{kind}/{f.name}", f.stem):
                    continue
                jobs.append((f, "copy_audio", f"audio/{kind}/{f.name}"))

    return jobs


def _transform(src: Path, transform: str, profile: str) -> bytes:
    if transform == "png2webp_sprite":
        return _webp_encode(src, quality=50 if profile == "draft" else 95)
    if transform == "png2webp_bg":
        return _webp_encode(src, quality=50 if profile == "draft" else 90)
    if transform == "copy_audio":
        return src.read_bytes()
    raise AssetError(f"неизвестная трансформация {transform!r}")


def build_assets(root: Path, profile: str = "full", check: bool = False) -> AssetBuildResult:
    """Инкрементальная сборка game/assets из assets_src (+ нарезка PSD, psd.py).
    check=True: НИЧЕГО не пишется — только discovery-ошибки и список несвежих выходов."""
    rep = AssetBuildResult()
    out_root = root / "game" / "assets"
    cache_dir = root / ".vncache" / "assets"
    if not check:
        cache_dir.mkdir(parents=True, exist_ok=True)

        # PSD -> staging PNG-дерево той же конвенции (боевой путь художника, раздел 2)
        from .psd import slice_all_psd
        slice_all_psd(root, rep)

    jobs = _discover(root, rep)
    if rep.errors:
        return rep

    seen_outputs: dict[str, dict] = {}
    for src, transform, out_rel in jobs:
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
        key = _b3_bytes(
            f"{src_hash}:{transform}:{TRANSFORMS[transform]}:{profile}".encode()
        )
        blob = cache_dir / key[:2] / key
        dest = out_root / out_rel

        if check:
            seen_outputs[out_rel] = {
                "src_hash": src_hash,
                "transform": f"{transform}@{TRANSFORMS[transform]}",
                "profile": profile,
            }
            if not dest.is_file():
                rep.stale.append(f"{out_rel} (нет файла)")
            continue

        if blob.is_file():
            data = blob.read_bytes()
            origin = "cache"
        else:
            try:
                data = _transform(src, transform, profile)
            except OSError as e:
                rep.errors.append(f"{src.relative_to(root).as_posix()}: трансформация упала: {e}")
                continue
            _write_atomic(blob, data)
            origin = "built"

        if dest.is_file() and dest.read_bytes() == data:
            rep.fresh.append(out_rel)
        else:
            _write_atomic(dest, data)
            (rep.from_cache if origin == "cache" else rep.built).append(out_rel)

        seen_outputs[out_rel] = {
            "src": src.relative_to(root).as_posix(),
            "src_hash": src_hash,
            "out_hash": _b3_bytes(data),
            "transform": f"{transform}@{TRANSFORMS[transform]}",
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
    for orphan in sorted(set(old_manifest) - set(seen_outputs)):
        p = out_root / orphan
        if p.is_file():
            p.unlink()
            rep.deleted.append(orphan)
            parent = p.parent
            while parent != out_root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent

    _write_atomic(manifest_path, (json.dumps(
        {"schema": "assets_manifest@1", "outputs": seen_outputs},
        ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return rep


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
