"""vn assets build — ассет-конвейер (раздел 2, G13, ADR-0012).

Зоны: assets_src/ (мастера) -> трансформации -> game/assets/ (game-ready). Художник
никогда не пишет в game/ (G2). Кэш — контентно-адресуемый: ключ = blake3(мастер +
параметры трансформации) + id и ВЕРСИЯ трансформации + профиль (G13: бамп версии
png2webp не инвалидирует аудио-ветку). Очистка game/assets — точечная, по диффу
манифестов.

Что решает конвейер, а что конфиг. Разрешения, форматы мастеров, политика
прозрачности, качество энкода и набор отгружаемых масштабов заданы данными —
project.yaml: render (render_config.py). Здесь только исполнение.

Мастера (открытый промежуточный формат; PSD нарезается в него же — psd.py).
Зона `assets_src/art/` — основная; `assets_src/png/` поддерживается как
исторический алиас, чтобы работа художника не ломалась на переходе:
  <art>/characters/<key>/<pose>/base.<ext>
  <art>/characters/<key>/<pose>/{outfits,faces,overlays}/<name>.<ext>
  <art>/backgrounds/<...>/<name>.<ext>      # вложенность разрешена
  <art>/cg/<...>/<name>.<ext>
  <art>/shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>].<ext>   # послойные шоты (shots@1)
  assets_src/audio_stems/{bgm,amb,sfx}/<id>.ogg
  assets_src/voice/<lang>/<chNN>/<line_id>.(wav|flac|ogg|opus)  # мастера озвучки (§4.9)
  assets_src/video_src/<group>/<name>.(mp4|mov|mkv|webm|m4v|avi)
Допустимые расширения мастера — per-class (render.classes.<c>.formats).

Выходы. Референсный вариант каждого ассета — БЕЗ суффикса, крупные варианты
рядом как `@2`/`@4`: Ren'Py включает автоподбор оверсэмпла только для
безсуффиксного имени (renpy/display/im.py: get_oversampled_image). Игрок на 1080p
грузит маленький вариант, игрок на 4K — крупный.
  game/assets/spr/<key>/<pose>/{base,outfits/<o>,faces/<e>,overlays/<n>}[@N].webp
  game/assets/bg/<...>/<name>[@N].webp   (+ <name>.thumb.webp)
  game/assets/cg/<...>/<name>[@N].webp   (+ <name>.thumb.webp)
  game/assets/shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>][@N].webp
  game/assets/audio/{bgm,amb,sfx}/<id>.ogg
  game/assets/voice/<lang>/<chNN>/<line_id>.opus
  game/assets/mov/<group>/<name>[@N].webm (+ .webm.meta.json — mov_meta@1)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import blake3

from . import imaging
from .render_config import RenderConfig, load_render_config

# Версии трансформаций (G13): бамп инвалидирует только свою ветку кэша.
# @2 у растровых веток — переход на data-driven варианты и bbox-модель (ADR-0012).
# video2webm: версия = пресет ffmpeg (video.encode_args) — меняете пресет, бампайте.
TRANSFORMS = {
    "img_sprite": "2",
    "img_bg": "2",
    "img_cg": "2",
    "img_shot": "1",
    "img_thumb": "2",
    "ui_panel": "1",
    "copy_audio": "1",
    "voice_opus": "1",
    "video2webm": "2",
    "mov_poster": "1",
}

# Растровый класс -> трансформация. Ключи совпадают с render.classes.
CLASS_TRANSFORM = {"spr": "img_sprite", "bg": "img_bg", "cg": "img_cg",
                   "shot": "img_shot"}

# Конвенция путей послойных шотов (shots@1): shots/<chNN>/<sNNN>/<shot>/<файл>.
SHOT_CH_RE = re.compile(r"^ch\d{2}$")
SHOT_SCENE_RE = re.compile(r"^s\d{3}$")
# Опорный слой шота: непрозрачная подложка, задаёт холст всем слоям.
SHOT_ENV = "env"

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MANIFEST = "assets-manifest.json"
# Постер-кадр видео: fallback для Movie(image=) и постер в сетке галереи.
POSTER_SUFFIX = ".poster.webp"

# Зоны растровых мастеров: art/ — основная, png/ — исторический алиас.
ART_ROOTS = ("art", "png")
# Зарезервировано под портреты say-окна (Ren'Py side images): не поза.
SIDE_DIR = "side"
# Спутники мастеров, которые конвейер не собирает, но и не считает мусором.
SIDECAR_SUFFIXES = (".meta.yaml", ".provenance.json", ".manifest.json",
                    ".video.yaml", ".render.yaml", ".md", ".txt")
SIDECAR_NAMES = (".gitkeep", ".gitignore")


class AssetError(RuntimeError):
    pass


@dataclass
class AssetBuildResult:
    built: list[str] = field(default_factory=list)      # прогнаны трансформацией
    from_cache: list[str] = field(default_factory=list)  # взяты из кэша
    fresh: list[str] = field(default_factory=list)       # на диске уже актуальные
    deleted: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)       # только в режиме check
    skipped_variants: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Job:
    src: Path
    transform: str
    out_rel: str
    params: dict                       # входит в хеш источника (G13)
    extra: dict | None = None          # видео/панели: нефайловые входы


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


def _check_slug(rep: AssetBuildResult, rel: str, *parts: str) -> bool:
    for p in parts:
        if not SLUG_RE.match(p):
            rep.errors.append(f"{rel}: сегмент {p!r} вне конвенции ^[a-z][a-z0-9_]*$ (naming.md)")
            return False
    return True


def _art_roots(root: Path) -> list[Path]:
    return [root / "assets_src" / name for name in ART_ROOTS
            if (root / "assets_src" / name).is_dir()]


def _is_sidecar(path: Path) -> bool:
    name = path.name
    return name in SIDECAR_NAMES or any(name.endswith(s) for s in SIDECAR_SUFFIXES)


# ── Проба и валидация мастера ────────────────────────────────────────────────

def _validate_master(rep: AssetBuildResult, rel: str, src: Path, cls,
                     alpha: str | None = None) -> dict | None:
    """Формат, прозрачность, минимальный размер, пропорции. None = мастер отбракован.

    alpha — переопределение классовой политики прозрачности для классов, где она
    зависит от роли файла (shot: env — forbid, слои — require).

    Ни одна из проверок не «молча пропускает»: неподходящий файл обязан назвать
    себя ошибкой, иначе он исчезает из сборки и всплывает чёрным экраном в игре."""
    ext = src.suffix.lower().lstrip(".")
    if ext not in cls.formats:
        rep.errors.append(
            f"{rel}: формат .{ext} не разрешён для класса {cls.name} "
            f"(разрешены: {', '.join('.' + f for f in cls.formats)}; "
            f"project.yaml: render.classes.{cls.name}.formats)")
        return None
    try:
        info = imaging.probe(src)
    except imaging.ImagingError as e:
        rep.errors.append(f"{rel}: {e}")
        return None

    if alpha is None:
        alpha = cls.alpha
    if alpha == "require" and not info["has_alpha"]:
        rep.errors.append(
            f"{rel}: класс {cls.name} требует прозрачности, а мастер непрозрачен "
            f"(альфа-минимум {info['alpha_min']}) — фон не вырезан; "
            f"такой слой ляжет в игре прямоугольником поверх фона")
        return None
    if alpha == "forbid" and info["has_alpha"]:
        rep.warnings.append(
            f"{rel}: у класса {cls.name} прозрачность не используется — "
            f"альфа-канал будет отброшен при сборке")

    smallest = cls.scales[0]
    if cls.layout == "screen":
        need = (cls.screen[0] * smallest, cls.screen[1] * smallest)
        if info["width"] < need[0] or info["height"] < need[1]:
            rep.errors.append(
                f"{rel}: мастер {info['width']}x{info['height']} меньше отгружаемого "
                f"{need[0]}x{need[1]} — апскейл запрещён, отдайте мастер крупнее")
            return None
        if cls.aspect_tolerance:
            miss = imaging.aspect_mismatch(info["size"], cls.screen)
            if miss > cls.aspect_tolerance:
                rep.errors.append(
                    f"{rel}: пропорции {info['width']}x{info['height']} расходятся с "
                    f"экраном {cls.screen[0]}x{cls.screen[1]} на {miss:.1%} — "
                    f"кадр в игре обрежется или оставит поля")
                return None
    sm = cls.source_min
    if sm and (info["width"] < sm[0] or info["height"] < sm[1]):
        rep.errors.append(
            f"{rel}: мастер {info['width']}x{info['height']} меньше требуемого "
            f"минимума {sm[0]}x{sm[1]} (project.yaml: render.classes.{cls.name}.source_min)")
        return None
    return info


def _image_jobs(rep: AssetBuildResult, cfg: RenderConfig, rel: str, src: Path,
                cls_name: str, out_base: str,
                expect_size: tuple[int, int] | None = None,
                alpha: str | None = None) -> list[Job]:
    """Мастер -> задания на все отгружаемые варианты (+ миниатюра).

    expect_size — обязательный холст (спрайты одной позы, слои шота): слои
    layeredimage складываются по координате (0,0), поэтому разный холст =
    поехавшая композиция. alpha — per-role политика прозрачности (шоты)."""
    cls = cfg.cls(cls_name)
    info = _validate_master(rep, rel, src, cls, alpha=alpha)
    if info is None:
        return []
    if expect_size and info["size"] != tuple(expect_size):
        rep.errors.append(
            f"{rel}: холст {info['width']}x{info['height']} != {expect_size[0]}x"
            f"{expect_size[1]} — слои одной позы обязаны лежать на ОДНОМ холсте, "
            f"иначе layeredimage смещает наряд/эмоцию относительно тела")
        return []
    variants, skipped = cls.variants_for(info["size"])
    for scale in skipped:
        rep.skipped_variants.append(
            f"{rel}: вариант @{scale} не собран — мастер {info['width']}x{info['height']} "
            f"мал для него (нужен вдвое крупнее); игра останется на меньшем варианте")
    jobs: list[Job] = []
    keep_alpha = (alpha or cls.alpha) != "forbid"
    for v in variants:
        jobs.append(Job(
            src=src,
            transform=CLASS_TRANSFORM[cls_name],
            out_rel=f"{out_base}{v.suffix}{cls.out_ext}",
            # quality едет в params целиком: правка качества в project.yaml обязана
            # инвалидировать кэш, а профиль (full/draft) известен только при сборке.
            params={"target": [v.width, v.height],
                    "quality": dict(cls.spec.get("quality") or {}),
                    "out_format": cls.spec.get("out_format", "webp"),
                    "keep_alpha": keep_alpha, "scale": v.scale},
        ))
    if cls.wants_thumb:
        jobs.append(Job(
            src=src,
            transform="img_thumb",
            out_rel=f"{out_base}.thumb{_thumb_ext(cfg)}",
            params={"max_side": int(cfg.thumb["max_side"]),
                    "quality": int(cfg.thumb["quality"]),
                    "out_format": cfg.thumb.get("out_format", "webp"),
                    "keep_alpha": keep_alpha},
        ))
    return jobs


def _thumb_ext(cfg: RenderConfig) -> str:
    from .render_config import OUT_FORMATS

    return OUT_FORMATS[cfg.thumb.get("out_format", "webp")]


# ── Discovery ────────────────────────────────────────────────────────────────

def _discover(root: Path, rep: AssetBuildResult,
              cfg: RenderConfig | None = None) -> tuple[list[Job], set[Path]]:
    """Задания сборки + множество ФАКТИЧЕСКИ ПОТРЕБЛЁННЫХ файлов-мастеров.
    Второе нужно, чтобы поймать мастер, который никуда не поехал: раньше файл
    неподдерживаемого формата или в неожиданной папке исчезал молча."""
    cfg = cfg or load_render_config(root)
    jobs: list[Job] = []
    consumed: set[Path] = set()

    # ── Персонажи: ручной экспорт + staging PSD-нарезки, одна конвенция ──────
    canvases = _declared_canvases(root)
    char_bases = [p / "characters" for p in _art_roots(root)]
    char_bases.append(root / ".vncache" / "psd_png" / "characters")
    for chars in char_bases:
        if not chars.is_dir():
            continue
        for key_dir in sorted(p for p in chars.iterdir() if p.is_dir()):
            # side/ — зарезервированный каталог портретов для say-окна (naming.md),
            # а не поза: у него свой холст и своё имя образа (image side <char> …).
            side_dir = key_dir / SIDE_DIR
            if side_dir.is_dir():
                side_canvas = None
                for f in sorted(side_dir.iterdir()):
                    if not f.is_file() or _is_sidecar(f):
                        continue
                    consumed.add(f)
                    if not _check_slug(rep, _rel(root, f), key_dir.name, f.stem):
                        continue
                    if side_canvas is None:
                        try:
                            side_canvas = imaging.probe(f)["size"]
                        except imaging.ImagingError:
                            pass
                    jobs += _image_jobs(rep, cfg, _rel(root, f), f, "spr",
                                        f"spr/{key_dir.name}/{SIDE_DIR}/{f.stem}",
                                        expect_size=side_canvas)
            for pose_dir in sorted(p for p in key_dir.iterdir()
                                   if p.is_dir() and p.name != SIDE_DIR):
                prel = _rel(root, pose_dir)
                if not _check_slug(rep, prel, key_dir.name, pose_dir.name):
                    continue
                # Все файлы base.* потребляем сразу: иначе base.jpg дал бы и
                # «нет base», и «файл не подобран» — две ошибки об одном.
                for f in pose_dir.iterdir():
                    if f.is_file() and f.stem == "base":
                        consumed.add(f)
                base = _pick_master(pose_dir, "base", cfg.cls("spr").formats)
                # Холст позы: объявленный в character.yaml (canvas) либо, если не
                # объявлен, — холст base. Остальные слои обязаны ему соответствовать.
                canvas = canvases.get(key_dir.name)
                if base is None:
                    rep.errors.append(
                        f"{prel}: нет обязательного base.* "
                        f"({', '.join('.' + f for f in cfg.cls('spr').formats)})")
                else:
                    if canvas is None:
                        try:
                            canvas = imaging.probe(base)["size"]
                        except imaging.ImagingError:
                            canvas = None
                    jobs += _image_jobs(rep, cfg, _rel(root, base), base, "spr",
                                        f"spr/{key_dir.name}/{pose_dir.name}/base",
                                        expect_size=canvases.get(key_dir.name))
                # Слои обрабатываются даже без base: художник должен получить ВСЕ
                # претензии за один прогон, а не по одной за сборку.
                for group in ("outfits", "faces", "overlays"):
                    gdir = pose_dir / group
                    if not gdir.is_dir():
                        continue
                    for f in sorted(gdir.iterdir()):
                        if not f.is_file() or _is_sidecar(f):
                            continue
                        consumed.add(f)
                        if not _check_slug(rep, _rel(root, f), f.stem):
                            continue
                        jobs += _image_jobs(
                            rep, cfg, _rel(root, f), f, "spr",
                            f"spr/{key_dir.name}/{pose_dir.name}/{group}/{f.stem}",
                            expect_size=canvas)

    # ── Фоны и CG: произвольная вложенность каталогов ───────────────────────
    # Вложенность — организационная (apartment/living_room/), id локации при этом
    # остаётся плоским: location.yaml ссылается на путь файла, а не на дерево.
    for cls_name, zone in (("bg", "backgrounds"), ("cg", "cg")):
        for art in _art_roots(root):
            base_dir = art / zone
            if not base_dir.is_dir():
                continue
            for f in sorted(base_dir.rglob("*")):
                if not f.is_file() or _is_sidecar(f):
                    continue
                consumed.add(f)
                parts = f.relative_to(base_dir).parts
                rel = _rel(root, f)
                if not _check_slug(rep, rel, *parts[:-1], f.stem):
                    continue
                out_base = f"{cls_name}/" + "/".join([*parts[:-1], f.stem])
                jobs += _image_jobs(rep, cfg, rel, f, cls_name, out_base)

    # ── Послойные шоты (shots@1, ADR-0013): жёсткая глубина, единый холст ────
    # art/shots/<chNN>/<sNNN>/<shot>/<layer>[__<variant>].<ext>. env — подложка
    # без альфы, задаёт холст шота; остальные слои обязаны быть вырезаны (альфа)
    # и лежать на ТОМ ЖЕ холсте: layeredimage кладёт слои в (0,0).
    for art in _art_roots(root):
        shots_dir = art / "shots"
        if not shots_dir.is_dir():
            continue
        for shot_dir in sorted(d for d in shots_dir.glob("*/*/*") if d.is_dir()):
            ch, sid, shot = shot_dir.relative_to(shots_dir).parts
            files = [f for f in sorted(shot_dir.iterdir())
                     if f.is_file() and not _is_sidecar(f)]
            for f in files:
                consumed.add(f)
            drel = _rel(root, shot_dir)
            if not (SHOT_CH_RE.match(ch) and SHOT_SCENE_RE.match(sid)
                    and SLUG_RE.match(shot)):
                rep.errors.append(
                    f"{drel}: путь вне конвенции shots/<chNN>/<sNNN>/<shot>/")
                continue
            env = _pick_master(shot_dir, SHOT_ENV, cfg.cls("shot").formats)
            canvas = None
            if env is None:
                rep.errors.append(
                    f"{drel}: нет обязательного слоя {SHOT_ENV}.* — подложка задаёт "
                    f"холст и не даёт кадру просвечивать")
            else:
                try:
                    canvas = imaging.probe(env)["size"]
                except imaging.ImagingError:
                    canvas = None
            for f in files:
                rel = _rel(root, f)
                layer, _, variant = f.stem.partition("__")
                if not SLUG_RE.match(layer) or (variant and not SLUG_RE.match(variant)):
                    rep.errors.append(
                        f"{rel}: имя слоя вне конвенции <layer>[__<variant>].<ext>")
                    continue
                jobs += _image_jobs(
                    rep, cfg, rel, f, "shot", f"shots/{ch}/{sid}/{shot}/{f.stem}",
                    # env задаёт холст (сам не сверяется), остальные — на нём же
                    expect_size=(None if f == env else canvas),
                    alpha=("forbid" if layer == SHOT_ENV else "require"))

    # ── Звук: побайтовое копирование ────────────────────────────────────────
    audio = root / "assets_src" / "audio_stems"
    if audio.is_dir():
        for kind in ("bgm", "amb", "sfx"):
            kdir = audio / kind
            if not kdir.is_dir():
                continue
            for f in sorted(kdir.iterdir()):
                if not f.is_file() or _is_sidecar(f):
                    continue
                consumed.add(f)
                if f.suffix.lower() != ".ogg":
                    rep.errors.append(f"{_rel(root, f)}: в audio_stems только .ogg")
                    continue
                if not _check_slug(rep, _rel(root, f), f.stem):
                    continue
                jobs.append(Job(f, "copy_audio", f"audio/{kind}/{f.name}", {}))

    # ── Голос (§4.9/C18): мастера дублей -> Opus 96k / −19 LUFS ─────────────
    # Конвенция пути и line_id — те же, что у voice-манифестов (voice.py);
    # сверку «файл ↔ строка манифеста» делает vn voice validate, здесь — только
    # физика: транскод каждого мастера в game/assets/voice/.
    voice_src = root / "assets_src" / "voice"
    if voice_src.is_dir():
        from ..voice import LANG_RE, LINE_ID_RE, MASTER_EXTS

        vfiles = [f for f in sorted(voice_src.rglob("*"))
                  if f.is_file() and not _is_sidecar(f)]
        for f in vfiles:
            consumed.add(f)
        if vfiles:
            from ..pipeline import find_ffmpeg

            if find_ffmpeg() is None:
                rep.errors.append(
                    "assets_src/voice: есть мастера озвучки, но ffmpeg не найден "
                    "(vn pipeline doctor) — голосовая ветка не собирается")
                vfiles = []
        for f in vfiles:
            rel = _rel(root, f)
            parts = f.relative_to(voice_src).parts
            if len(parts) != 3 or not LANG_RE.match(parts[0]) \
                    or not LINE_ID_RE.match(f.stem) or not f.stem.startswith(parts[1] + "_"):
                rep.errors.append(
                    f"{rel}: путь вне конвенции voice/<lang>/<chNN>/<line_id>.<ext>")
                continue
            if f.suffix.lower() not in MASTER_EXTS:
                rep.errors.append(
                    f"{rel}: формат {f.suffix} не поддержан "
                    f"({', '.join(MASTER_EXTS)})")
                continue
            jobs.append(Job(f, "voice_opus",
                            f"voice/{parts[0]}/{parts[1]}/{f.stem}.opus", {}))

    # ── Видео (ADR-0006) + оверсэмпл-варианты ───────────────────────────────
    jobs += _video_jobs(root, rep, cfg, consumed)

    # ── UI-панели (ADR-0009): источник — декларация, а не файл ──────────────
    panels_decl = root / "content" / "ui" / "panels.yaml"
    if panels_decl.is_file():
        from ..repo import load_yaml

        doc = load_yaml(panels_decl)
        for pid, spec in sorted((doc.get("panels") or {}).items()):
            if not SLUG_RE.match(pid):
                rep.errors.append(f"content/ui/panels.yaml: панель {pid!r} вне "
                                  f"конвенции ^[a-z][a-z0-9_]*$")
                continue
            jobs.append(Job(panels_decl, "ui_panel", f"ui/{pid}.webp", {},
                            extra={"spec": spec}))

    return jobs, consumed


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _declared_canvases(root: Path) -> dict[str, tuple[int, int]]:
    """character.yaml: canvas -> обязательный холст мастеров этого персонажа.

    Поле долго было мёртвой поверхностью схемы. Теперь это контракт: холст —
    единственное, что связывает слои позы между собой (layeredimage кладёт их
    в (0,0)), и единственное, из чего выводится экранный рост персонажа."""
    out: dict[str, tuple[int, int]] = {}
    zones = [root / "content" / "characters"]
    if (root / "packs").is_dir():
        zones += sorted((root / "packs").glob("*/characters"))
    for zone in zones:
        if not zone.is_dir():
            continue
        for d in sorted(p for p in zone.iterdir() if p.is_dir()):
            f = d / "character.yaml"
            if not f.is_file():
                continue
            try:
                from ..repo import load_yaml

                doc = load_yaml(f) or {}
            except Exception:
                continue
            canvas = doc.get("canvas")
            if isinstance(canvas, list) and len(canvas) == 2:
                out[d.name] = (int(canvas[0]), int(canvas[1]))
    return out


def _pick_master(directory: Path, stem: str, formats: tuple[str, ...]) -> Path | None:
    """Мастер с заданным stem в любом из допустимых форматов (порядок = приоритет)."""
    for ext in formats:
        cand = directory / f"{stem}.{ext}"
        if cand.is_file():
            return cand
    return None


def _video_jobs(root: Path, rep: AssetBuildResult, cfg: RenderConfig,
                consumed: set[Path]) -> list[Job]:
    from . import video as videomod

    vsrc = root / "assets_src" / "video_src"
    if not vsrc.is_dir():
        return []
    vfiles = [f for f in sorted(vsrc.rglob("*"))
              if f.is_file() and not _is_sidecar(f)]
    for f in vfiles:
        consumed.add(f)
    media = [f for f in vfiles if f.suffix.lower() in videomod.VIDEO_EXTS]
    for f in vfiles:
        if f not in media:
            rep.errors.append(
                f"{_rel(root, f)}: формат не поддержан видео-треком "
                f"({', '.join(videomod.VIDEO_EXTS)})")
    if not media:
        return []

    from ..pipeline import find_ffmpeg, find_ffprobe

    if find_ffmpeg() is None or find_ffprobe() is None:
        rep.errors.append(
            "assets_src/video_src: есть видео-мастера, но ffmpeg/ffprobe не найдены "
            "(vn pipeline doctor) — видео-трек не собирается")
        return []

    mov = cfg.cls("mov")
    heights = {int(k): int(v) for k, v in (mov.spec.get("heights") or {}).items()}
    jobs: list[Job] = []
    for f in media:
        parts = f.relative_to(vsrc).parts
        rel = _rel(root, f)
        if len(parts) < 2:
            rep.errors.append(f"{rel}: видео кладутся в группу — "
                              f"video_src/<group>/<name>.<ext> (naming.md)")
            continue
        if not _check_slug(rep, rel, *parts[:-1], f.stem):
            continue
        sidecar = f.with_name(f.stem + videomod.SIDECAR_SUFFIX)
        opts, opt_errors = videomod.load_opts(sidecar)
        if opt_errors:
            rep.errors.extend(opt_errors)
            continue
        try:
            src_h = videomod.summarize(f)["height"]
        except videomod.VideoError as e:
            rep.errors.append(f"{rel}: {e}")
            continue
        out_base = "mov/" + "/".join([*parts[:-1], f.stem])
        for scale in mov.scales:
            target_h = heights.get(scale, cfg.screen[1] * scale)
            if opts.get("max_height"):
                target_h = min(target_h, int(opts["max_height"]))
            if target_h > src_h and scale != mov.scales[0]:
                rep.skipped_variants.append(
                    f"{rel}: вариант @{scale} не собран — мастер {src_h}p ниже "
                    f"целевых {target_h}p")
                continue
            vopts = dict(opts, max_height=target_h)
            jobs.append(Job(f, "video2webm", f"{out_base}{mov.suffix_for(scale)}.webm",
                            {"max_height": target_h, "scale": scale},
                            extra={"opts": vopts,
                                   "sidecar": sidecar if sidecar.is_file() else None}))
    return jobs


def _orphan_masters(root: Path, consumed: set[Path], rep: AssetBuildResult) -> None:
    """Файл в зоне мастеров, который не взяла ни одна ветка конвейера.

    Это главный источник «тихой потери»: JPG в спрайтах, лишний уровень
    вложенности, опечатка в имени папки — раньше всё это просто исчезало."""
    zones = [*_art_roots(root)]
    for extra in ("audio_stems", "video_src", "voice"):
        d = root / "assets_src" / extra
        if d.is_dir():
            zones.append(d)
    for zone in zones:
        for f in sorted(zone.rglob("*")):
            if not f.is_file() or _is_sidecar(f) or f in consumed:
                continue
            rep.errors.append(
                f"{_rel(root, f)}: файл лежит в зоне мастеров, но не подобран ни одной "
                f"веткой конвейера — проверьте путь и конвенцию каталогов "
                f"(docs/conventions/folder-layout.md)")


# ── Трансформации ────────────────────────────────────────────────────────────

def _transform(job: Job, profile: str, cfg: RenderConfig) -> bytes:
    t = job.transform
    if t in ("img_sprite", "img_bg", "img_cg", "img_shot"):
        q = job.params["quality"]
        quality = int(q.get(profile, q.get("full", 90)))
        return imaging.encode(
            job.src, tuple(job.params["target"]), quality=quality,
            out_format=job.params["out_format"], keep_alpha=job.params["keep_alpha"])
    if t == "img_thumb":
        return imaging.encode(
            job.src, None, quality=job.params["quality"],
            out_format=job.params["out_format"], keep_alpha=job.params["keep_alpha"],
            max_side=job.params["max_side"])
    if t == "copy_audio":
        return job.src.read_bytes()
    raise AssetError(f"неизвестная трансформация {t!r}")


def _transform_ui_panel(spec: dict, profile: str) -> bytes:
    """UI-панель: рисуется из декларации (источник — не файл, а параметры)."""
    import io

    from PIL import Image

    from . import ui as uimod

    png = uimod.render_panel(spec)
    with Image.open(io.BytesIO(png)) as im:
        buf = io.BytesIO()
        # lossless: 9-patch тянется движком, артефакты сжатия поехали бы по краям
        im.convert("RGBA").save(buf, format="WEBP", lossless=True,
                                quality=100, method=4 if profile == "full" else 0)
        return buf.getvalue()


# ── Сборка ───────────────────────────────────────────────────────────────────

def build_assets(root: Path, profile: str = "full", check: bool = False,
                 only_transforms: set[str] | None = None) -> AssetBuildResult:
    """Инкрементальная сборка game/assets из assets_src (+ нарезка PSD, psd.py).
    check=True: НИЧЕГО не пишется — только discovery-ошибки и список несвежих выходов.
    only_transforms: собрать подмножество трансформаций (например {"video2webm"});
    манифест и orphan-очистка остальных веток не трогаются."""
    from . import video as videomod
    from ..voice import VoiceError, encode_opus

    rep = AssetBuildResult()
    cfg = load_render_config(root)
    out_root = root / "game" / "assets"
    cache_dir = root / ".vncache" / "assets"
    video_tmp = root / ".vncache" / "video-tmp"
    if not check:
        cache_dir.mkdir(parents=True, exist_ok=True)

        # PSD -> staging PNG-дерево той же конвенции (боевой путь художника, раздел 2)
        from .psd import slice_all_psd
        slice_all_psd(root, rep)

    jobs, consumed = _discover(root, rep, cfg)
    _orphan_masters(root, consumed, rep)
    if rep.errors:
        return rep

    # Подмножество трансформаций: у видео два выхода (webm + meta), они одна ветка.
    effective_only = set(only_transforms) if only_transforms else None
    if effective_only and "video2webm" in effective_only:
        effective_only.update(("mov_meta", "mov_poster"))
    if effective_only and not check:
        jobs = [j for j in jobs if j.transform in effective_only]

    from ..repo import load_project
    try:
        file_budget = (load_project(root).get("budgets") or {}).get("video_file_mb")
    except Exception:
        file_budget = None

    seen_outputs: dict[str, dict] = {}
    for job in jobs:
        out_rel = job.out_rel
        if out_rel in seen_outputs:
            rep.errors.append(f"{out_rel}: два источника претендуют на один выход")
            continue
        try:
            src_bytes = job.src.read_bytes()
        except OSError as e:
            # Залоченный/дописываемый файл (Photoshop, антивирус) — ошибка, не трейсбек.
            rep.errors.append(f"{_rel(root, job.src)}: не читается: {e}")
            continue

        # Параметры трансформации — ЧАСТЬ источника: правка render-профиля или
        # сайдкара инвалидирует ровно свои выходы, не трогая чужие ветки (G13).
        extra_params = dict(job.params)
        if job.transform == "video2webm" and job.extra:
            sidecar = job.extra.get("sidecar")
            src_bytes = src_bytes + b"\x00" + (sidecar.read_bytes() if sidecar else b"")
        elif job.transform == "ui_panel" and job.extra:
            from . import ui as uimod
            src_bytes = uimod.panel_hash_source(job.extra["spec"])
        src_hash = _b3_bytes(
            src_bytes + b"\x00" + cfg.params_digest(job.transform, extra_params))

        key = _b3_bytes(
            f"{src_hash}:{job.transform}:{TRANSFORMS[job.transform]}:{profile}".encode()
        )
        blob = cache_dir / key[:2] / key
        dest = out_root / out_rel
        meta_rel = out_rel + videomod.META_SUFFIX if job.transform == "video2webm" else None
        # Постер — только у референсного варианта: он один попадает в Movie(image=)
        # и в сетку галереи, крупные варианты своего постера не требуют.
        poster_rel = (out_rel[: -len(".webm")] + POSTER_SUFFIX
                      if job.transform == "video2webm" and job.params.get("scale") == 1
                      else None)

        if check:
            seen_outputs[out_rel] = {
                "src_hash": src_hash,
                "transform": f"{job.transform}@{TRANSFORMS[job.transform]}",
                "profile": profile,
            }
            if not dest.is_file():
                rep.stale.append(f"{out_rel} (нет файла)")
            if meta_rel:
                seen_outputs[meta_rel] = {
                    "src_hash": src_hash,
                    "transform": f"mov_meta@{TRANSFORMS[job.transform]}",
                    "profile": profile,
                }
                if dest.is_file() and not (out_root / meta_rel).is_file():
                    rep.stale.append(f"{meta_rel} (нет файла)")
            if poster_rel:
                seen_outputs[poster_rel] = {
                    "src_hash": src_hash,
                    "transform": f"mov_poster@{TRANSFORMS['mov_poster']}",
                    "profile": profile,
                }
                if dest.is_file() and not (out_root / poster_rel).is_file():
                    rep.stale.append(f"{poster_rel} (нет файла)")
            continue

        if blob.is_file():
            data = blob.read_bytes()
            origin = "cache"
        else:
            try:
                if job.transform == "video2webm":
                    data = videomod.encode_video(job.src, job.extra["opts"], profile, video_tmp)
                elif job.transform == "ui_panel":
                    data = _transform_ui_panel(job.extra["spec"], profile)
                elif job.transform == "voice_opus":
                    data = encode_opus(job.src, root / ".vncache" / "voice-tmp")
                else:
                    data = _transform(job, profile, cfg)
            except (OSError, imaging.ImagingError, videomod.VideoError, VoiceError) as e:
                rep.errors.append(f"{_rel(root, job.src)}: трансформация упала: {e}")
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

        entry = {
            "src": _rel(root, job.src),
            "src_hash": src_hash,
            "out_hash": _b3_bytes(data),
            "transform": f"{job.transform}@{TRANSFORMS[job.transform]}",
            "profile": profile,
        }
        # Стоимость в пикселях кэша Ren'Py — считаем один раз при сборке и храним
        # в манифесте: модель памяти (memory.py) не должна декодировать тысячи
        # файлов на каждый прогон QA.
        if job.transform in ("img_sprite", "img_bg", "img_cg", "img_shot"):
            try:
                entry["cost_px"] = imaging.decoded_cost_px(data)
            except Exception:
                pass
        seen_outputs[out_rel] = entry

        if meta_rel:
            # Валидация лупа/совместимости + метаданные (mov_meta@1) — контракт
            # для эмиттера Movie-образов. Ошибки валидации = красная сборка.
            meta_dest = out_root / meta_rel
            if wrote_now or not meta_dest.is_file():
                v_errors, v_warnings, summary = videomod.validate_output(
                    dest, job.extra["opts"], video_tmp, file_budget_mb=file_budget)
                rep.warnings.extend(v_warnings)
                if v_errors:
                    rep.errors.extend(v_errors)
                    continue
                meta = videomod.build_meta(
                    out_rel, job.extra["opts"], summary,
                    _rel(root, job.src), src_hash, entry["out_hash"],
                    f"{job.transform}@{TRANSFORMS[job.transform]}", profile)
                _write_atomic(meta_dest, (json.dumps(
                    meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
            seen_outputs[meta_rel] = {
                "src": _rel(root, job.src),
                "src_hash": src_hash,
                "out_hash": _b3_bytes(meta_dest.read_bytes()),
                "transform": f"mov_meta@{TRANSFORMS[job.transform]}",
                "profile": profile,
            }

        if poster_rel:
            poster_dest = out_root / poster_rel
            if wrote_now or not poster_dest.is_file():
                try:
                    poster = videomod.poster_frame(
                        dest, video_tmp, max_side=int(cfg.thumb["max_side"]),
                        quality=int(cfg.thumb["quality"]))
                except videomod.VideoError as e:
                    rep.errors.append(str(e))
                    continue
                _write_atomic(poster_dest, poster)
            seen_outputs[poster_rel] = {
                "src": _rel(root, job.src),
                "src_hash": src_hash,
                "out_hash": _b3_bytes(poster_dest.read_bytes()),
                "transform": f"mov_poster@{TRANSFORMS['mov_poster']}",
                "profile": profile,
                "cost_px": imaging.decoded_cost_px(poster_dest.read_bytes()),
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
    мастера оставляет прошлый блоб навсегда. Возвращает (удалено, освобождено байт)."""
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


# ── Скан собранной зоны ──────────────────────────────────────────────────────

_VARIANT_RE = re.compile(r"^(?P<stem>.+?)(?:@(?P<scale>\d+))?$")


def variant_scale(name: str) -> int:
    """Масштаб варианта из имени файла (без расширения): base -> 1, base@2 -> 2."""
    m = _VARIANT_RE.match(name)
    return int(m.group("scale")) if m and m.group("scale") else 1


def reference_name(name: str) -> str:
    """Имя без оверсэмпл-суффикса: base@2 -> base."""
    return _VARIANT_RE.match(name).group("stem")


def sprite_tree(root: Path) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Скан собранных спрайтов: {char: {pose: {'base': [...], 'outfits': [...],
    'faces': [...], 'overlays': [...]}}}. Возвращает РЕФЕРЕНСНЫЕ имена (без @N):
    эмиттер образов обязан ссылаться именно на них, иначе Ren'Py не включит
    автоподбор варианта под физический экран."""
    tree: dict = {}
    spr = root / "game" / "assets" / "spr"
    if not spr.is_dir():
        return tree
    for char_dir in sorted(p for p in spr.iterdir() if p.is_dir()):
        poses: dict = {}
        for pose_dir in sorted(p for p in char_dir.iterdir()
                               if p.is_dir() and p.name != SIDE_DIR):
            entry: dict[str, list[str]] = {"base": [], "outfits": [], "faces": [],
                                           "overlays": []}
            for f in pose_dir.iterdir():
                if f.is_file() and reference_name(f.stem) == "base" \
                        and variant_scale(f.stem) == 1:
                    entry["base"].append("base")
            for group in ("outfits", "faces", "overlays"):
                gdir = pose_dir / group
                if gdir.is_dir():
                    entry[group] = sorted(
                        f.stem for f in gdir.iterdir()
                        if f.is_file() and variant_scale(f.stem) == 1)
            poses[pose_dir.name] = entry
        tree[char_dir.name] = poses
    return tree


def shot_tree(root: Path) -> dict[str, dict[str, dict[str, dict[str, list[str]]]]]:
    """Скан собранных шотов: {chNN: {sNNN: {shot: {layer: [варианты]}}}}.
    Безвариантный слой — {layer: [""]}. Только референсные имена (без @N):
    эмиттер и валидация ссылаются на них, движок сам подберёт крупный вариант."""
    tree: dict = {}
    base = root / "game" / "assets" / "shots"
    if not base.is_dir():
        return tree
    for shot_dir in sorted(d for d in base.glob("*/*/*") if d.is_dir()):
        ch, sid, shot = shot_dir.relative_to(base).parts
        layers: dict[str, list[str]] = {}
        for f in sorted(shot_dir.iterdir()):
            if not f.is_file() or variant_scale(f.stem) != 1:
                continue
            layer, _, variant = reference_name(f.stem).partition("__")
            layers.setdefault(layer, []).append(variant)
        if layers:
            tree.setdefault(ch, {}).setdefault(sid, {})[shot] = layers
    return tree


def side_tree(root: Path) -> dict[str, list[str]]:
    """Портреты say-окна: {char: [референсные имена]}. Ren'Py ищет их как
    `side <tag> <атрибуты>` — отдельная ветка образов, не часть layeredimage."""
    tree: dict[str, list[str]] = {}
    spr = root / "game" / "assets" / "spr"
    if not spr.is_dir():
        return tree
    for char_dir in sorted(p for p in spr.iterdir() if p.is_dir()):
        sdir = char_dir / SIDE_DIR
        if not sdir.is_dir():
            continue
        names = sorted(f.stem for f in sdir.iterdir()
                       if f.is_file() and variant_scale(f.stem) == 1)
        if names:
            tree[char_dir.name] = names
    return tree


def asset_ext(root: Path, rel_base: str) -> str:
    """Расширение собранного референсного варианта (bg/cg могут быть не webp)."""
    from .render_config import OUT_FORMATS

    assets = root / "game" / "assets"
    for ext in OUT_FORMATS.values():
        if (assets / (rel_base + ext)).is_file():
            return ext
    return ".webp"
