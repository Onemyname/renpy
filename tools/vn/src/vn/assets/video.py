"""Видео-трек ассет-конвейера (ADR-0006): assets_src/video_src -> game/assets/mov.

Конвенция источников (открытый промежуточный формат — как PNG у статики):
  assets_src/video_src/<group>/<name>.(mp4|mov|mkv|webm|m4v|avi)
  assets_src/video_src/<group>/<name>.video.yaml    # опции (schema video_src@1), опционален
Выходы:
  game/assets/mov/<group>/<name>.webm               # VP9, yuv420p, чётные размеры, без аудио
  game/assets/mov/<group>/<name>.webm.meta.json     # метаданные (schema mov_meta@1)

Ren'Py-совместимость зашита в production-пресет: контейнер WebM + libvpx-vp9 +
yuv420p — единственная комбинация, которую движок играет на всех платформах без
сюрпризов. Movie-образы эмитит компилятор (content/images.py) из meta.json.

NSFW-контент живёт в подпапке nsfw/ своей группы (mov/nsfw/..., cg/nsfw/...) —
флейвор public исключает эти поддеревья на этапе distribute (release.py)."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")
SIDECAR_SUFFIX = ".video.yaml"
META_SUFFIX = ".meta.json"

# Пороги валидации лупов/совместимости (эмпирика ADR-0006)
LOOP_SEAM_WARN = 18.0        # RMS-разница первого/последнего кадра (0..255)
MAX_LOOP_DURATION_S = 30.0
SANE_FPS = (23.976, 24.0, 25.0, 30.0, 60.0)

DEFAULT_OPTS = {
    "loop": True,
    "keep_audio": False,
    "fps": None,          # None = fps источника
    "max_height": 1080,   # потолок production-энкода; draft жмёт до 720
    "crf": None,          # None = дефолт пресета (30 production / 42 draft)
}


class VideoError(RuntimeError):
    pass


def _ffmpeg() -> Path:
    from ..pipeline import find_ffmpeg

    p = find_ffmpeg()
    if p is None:
        raise VideoError("ffmpeg не найден (PATH/VN_FFMPEG) — vn pipeline doctor подскажет")
    return p


def _ffprobe() -> Path:
    from ..pipeline import find_ffprobe

    p = find_ffprobe()
    if p is None:
        raise VideoError("ffprobe не найден (PATH/VN_FFPROBE) — vn pipeline doctor подскажет")
    return p


def load_opts(sidecar: Path, registry=None) -> tuple[dict, list[str]]:
    """Опции энкода из <name>.video.yaml поверх дефолтов. Возвращает (opts, errors)."""
    opts = dict(DEFAULT_OPTS)
    if not sidecar.is_file():
        return opts, []
    from ..repo import load_yaml

    doc = load_yaml(sidecar)
    errors: list[str] = []
    if registry is not None:
        errors = registry.validate(doc, sidecar.as_posix())
        if errors:
            return opts, errors
    for key in DEFAULT_OPTS:
        if key in doc:
            opts[key] = doc[key]
    return opts, errors


# ── Энкод ─────────────────────────────────────────────────────────────────────

def encode_args(opts: dict, profile: str) -> list[str]:
    """Аргументы ffmpeg между -i и выходом. Отдельной функцией — тестируемо
    и версия пресета видна в диффе (бамп TRANSFORMS при изменении!)."""
    max_h = opts.get("max_height") or 1080
    if profile == "draft":
        max_h = min(max_h, 720)
        crf = opts.get("crf") or 42
        cpu_used = 8
    else:
        crf = opts.get("crf") or 30
        cpu_used = 2
    filters = []
    if opts.get("fps"):
        filters.append(f"fps={opts['fps']}")
    # Даунскейл до потолка + принудительно чётные размеры (yuv420p того требует)
    filters.append(f"scale=-2:2*trunc(min({max_h}\\,ih)/2)")
    args = [
        "-vf", ",".join(filters),
        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
        "-row-mt", "1", "-cpu-used", str(cpu_used),
        "-pix_fmt", "yuv420p",
    ]
    if opts.get("keep_audio"):
        args += ["-c:a", "libopus", "-b:a", "96k"]
    else:
        args += ["-an"]
    return args


def encode_video(src: Path, opts: dict, profile: str, workdir: Path) -> bytes:
    """Кодирование в VP9/WebM через tmp-файл; возвращает байты результата."""
    ffmpeg = _ffmpeg()
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / (src.stem + ".tmp.webm")
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), *encode_args(opts, profile), "-f", "webm", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = (proc.stderr or "").strip()[-600:]
        raise VideoError(f"{src.name}: ffmpeg упал (код {proc.returncode}):\n{tail}")
    data = out.read_bytes()
    out.unlink()
    return data


# ── Probe / метаданные ────────────────────────────────────────────────────────

def probe(path: Path) -> dict:
    ffprobe = _ffprobe()
    cmd = [str(ffprobe), "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError(f"{path.name}: ffprobe не смог прочитать файл: "
                         f"{(proc.stderr or '').strip()[-300:]}")
    return json.loads(proc.stdout)


def _fps_of(stream: dict) -> float:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    num, _, den = raw.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def summarize(path: Path) -> dict:
    """Ключевые свойства видео: кодек/размер/fps/длительность/пиксели/аудио."""
    info = probe(path)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise VideoError(f"{path.name}: видеопоток не найден")
    fmt = info.get("format", {})
    duration = float(video.get("duration") or fmt.get("duration") or 0.0)
    return {
        "container": (fmt.get("format_name") or "").split(",")[0],
        "codec": video.get("codec_name"),
        "pix_fmt": video.get("pix_fmt"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(_fps_of(video), 3),
        "duration_s": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
    }


def loop_seam(path: Path, workdir: Path) -> float | None:
    """RMS-разница (0..255) первого и последнего кадров: грубая метрика «стыка»
    лупа. None = кадры извлечь не удалось (не валим сборку из-за метрики)."""
    from PIL import Image

    ffmpeg = _ffmpeg()
    workdir.mkdir(parents=True, exist_ok=True)
    first, last = workdir / "loop_first.png", workdir / "loop_last.png"
    r1 = subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                         "-i", str(path), "-frames:v", "1", str(first)],
                        capture_output=True)
    r2 = subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                         "-sseof", "-0.2", "-i", str(path), "-update", "1", str(last)],
                        capture_output=True)
    if r1.returncode != 0 or r2.returncode != 0 or not first.is_file() or not last.is_file():
        return None
    try:
        with Image.open(first) as a, Image.open(last) as b:
            pa = a.convert("L").resize((64, 64)).tobytes()
            pb = b.convert("L").resize((64, 64)).tobytes()
            rms = math.sqrt(sum((x - y) ** 2 for x, y in zip(pa, pb)) / (64 * 64))
    finally:
        first.unlink(missing_ok=True)
        last.unlink(missing_ok=True)
    return round(rms, 1)


def validate_output(path: Path, opts: dict, workdir: Path,
                    file_budget_mb: float | None = None) -> tuple[list[str], list[str], dict]:
    """Строгая проверка собранного .webm: Ren'Py-совместимость + луп + бюджет.
    Возвращает (errors, warnings, summary)."""
    errors: list[str] = []
    warnings: list[str] = []
    name = path.name
    try:
        s = summarize(path)
    except VideoError as e:
        return [str(e)], [], {}

    if s["container"] not in ("webm", "matroska"):
        errors.append(f"{name}: контейнер {s['container']!r}, ожидается webm")
    if s["codec"] != "vp9":
        errors.append(f"{name}: кодек {s['codec']!r}, ожидается vp9 (Ren'Py-канон ADR-0006)")
    if s["pix_fmt"] not in ("yuv420p",):
        if s["pix_fmt"] in ("yuva420p",):
            warnings.append(f"{name}: альфа-канал ({s['pix_fmt']}) — в Ren'Py прозрачность "
                            f"через side-mask, проверьте воспроизведение отдельно")
        else:
            errors.append(f"{name}: pix_fmt {s['pix_fmt']!r}, ожидается yuv420p")
    if s["width"] % 2 or s["height"] % 2:
        errors.append(f"{name}: нечётные размеры {s['width']}x{s['height']}")
    if s["height"] > 1080 or s["width"] > 1920:
        warnings.append(f"{name}: {s['width']}x{s['height']} больше 1080p — "
                        f"дороже декодировать на слабом железе")
    if s["duration_s"] < 0.2:
        errors.append(f"{name}: длительность {s['duration_s']} c — файл битый/пустой")
    if not any(abs(s["fps"] - x) < 0.06 for x in SANE_FPS):
        warnings.append(f"{name}: нетипичный fps {s['fps']} (ожидаются {SANE_FPS})")
    if s["has_audio"] and not opts.get("keep_audio"):
        errors.append(f"{name}: аудиодорожка при keep_audio: false — пересоберите "
                      f"(vn assets video build)")
    if file_budget_mb is not None and s["size_bytes"] > file_budget_mb * 1024 * 1024:
        errors.append(f"{name}: {s['size_bytes'] / 1024 / 1024:.1f} МБ > бюджета "
                      f"{file_budget_mb} МБ на файл (project.yaml: budgets.video_file_mb)")

    if opts.get("loop", True):
        if s["duration_s"] > MAX_LOOP_DURATION_S:
            warnings.append(f"{name}: луп {s['duration_s']:.1f} c длиннее "
                            f"{MAX_LOOP_DURATION_S:.0f} c — точно луп?")
        seam = loop_seam(path, workdir)
        s["loop_seam"] = seam
        if seam is not None and seam > LOOP_SEAM_WARN:
            warnings.append(f"{name}: стык лупа заметен (RMS {seam} > {LOOP_SEAM_WARN}) — "
                            f"первый/последний кадры расходятся")
    else:
        s["loop_seam"] = None
    return errors, warnings, s


def build_meta(out_rel: str, opts: dict, summary: dict, src_rel: str,
               src_hash: str, out_hash: str, transform: str, profile: str) -> dict:
    """Содержимое <out>.webm.meta.json (schema mov_meta@1): контракт для
    эмиттера Movie-образов и инспекции."""
    return {
        "schema": "mov_meta@1",
        "id": out_rel[:-len(".webm")],           # mov/<group>/<name>
        "loop": bool(opts.get("loop", True)),
        "keep_audio": bool(opts.get("keep_audio", False)),
        "width": summary["width"],
        "height": summary["height"],
        "fps": summary["fps"],
        "duration_s": summary["duration_s"],
        "size_bytes": summary["size_bytes"],
        "loop_seam": summary.get("loop_seam"),
        "src": src_rel,
        "src_hash": {"algo": "blake3", "hex": src_hash},
        "out_hash": {"algo": "blake3", "hex": out_hash},
        "transform": transform,
        "profile": profile,
    }


def opts_from_meta(path: Path) -> dict:
    """Опции валидации собранного .webm из его meta.json (loop/keep_audio)."""
    opts = dict(DEFAULT_OPTS)
    meta_path = path.with_name(path.name + META_SUFFIX)
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            opts["loop"] = meta.get("loop", True)
            opts["keep_audio"] = meta.get("keep_audio", False)
        except ValueError:
            pass
    return opts


def validate_all(root: Path, file_budget_mb: float | None = None) -> tuple[list[str], list[str]]:
    """Строгая проверка всех собранных game/assets/mov/**.webm (release-гейт)."""
    errors: list[str] = []
    warnings: list[str] = []
    mov = root / "game" / "assets" / "mov"
    if not mov.is_dir():
        return errors, warnings
    workdir = root / ".vncache" / "video-tmp"
    for f in sorted(mov.rglob("*.webm")):
        try:
            errs, warns, _s = validate_output(f, opts_from_meta(f), workdir,
                                              file_budget_mb=file_budget_mb)
        except VideoError as e:
            errors.append(str(e))
            continue
        errors.extend(errs)
        warnings.extend(warns)
    return errors, warnings


def movie_tree(root: Path) -> dict[str, dict]:
    """Скан собранных лупов: {"mov/<group>/<name>.webm": meta}. Источник meta —
    сгенерированный .meta.json; без него — консервативные дефолты.

    Возвращает только РЕФЕРЕНСНЫЕ варианты (без `@N`): крупные варианты движок
    подбирает сам (renpy/display/video.py: find_oversampled_filename), отдельными
    образами они не являются."""
    from .pipeline import variant_scale

    tree: dict[str, dict] = {}
    mov = root / "game" / "assets" / "mov"
    if not mov.is_dir():
        return tree
    for f in sorted(mov.rglob("*.webm")):
        if variant_scale(f.stem) != 1:
            continue
        rel = "mov/" + f.relative_to(mov).as_posix()
        meta_path = f.with_name(f.name + META_SUFFIX)
        meta = {"loop": True}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        tree[rel] = meta
    return tree
