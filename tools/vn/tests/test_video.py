"""Видео-трек ассет-конвейера (ADR-0006): энкод, meta.json, loop-валидация,
sidecar-опции, нейминг, инкрементальность. Тесты синтезируют сырцы ffmpeg'ом
(lavfi) — без ffmpeg честно скипаются (в CI он установлен)."""

import json
import subprocess

import pytest

from helpers import write_project

from vn.assets.pipeline import build_assets
from vn.pipeline import find_ffmpeg, find_ffprobe

pytestmark = pytest.mark.skipif(
    find_ffmpeg() is None or find_ffprobe() is None,
    reason="нужны ffmpeg/ffprobe (vn pipeline doctor)",
)


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "assets_src" / "video_src").mkdir(parents=True)
    write_project(root)          # маленький render-профиль (helpers.TINY_SCREEN)
    return root


def _make_video(path, source="color=c=red", seconds=1.0, size="64x64", rate=24):
    """Синтетический сырец: color=* даёт идеальный луп, testsrc — заведомо рваный."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = ":" if "=" in source else "="       # lavfi: первый опции-разделитель — '='
    cmd = [str(find_ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"{source}{sep}duration={seconds}:size={size}:rate={rate}",
           "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


def test_build_video_with_meta_and_cache(tmp_path):
    root = _mk_root(tmp_path)
    _make_video(root / "assets_src/video_src/demo/loop01.mp4")

    res = build_assets(root)
    assert res.errors == []
    assert "mov/demo/loop01.webm" in res.built
    out = root / "game/assets/mov/demo/loop01.webm"
    meta_path = root / "game/assets/mov/demo/loop01.webm.meta.json"
    assert out.is_file() and meta_path.is_file()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["schema"] == "mov_meta@1"
    assert meta["id"] == "mov/demo/loop01"
    assert meta["loop"] is True
    assert meta["width"] % 2 == 0 and meta["height"] % 2 == 0
    assert meta["duration_s"] > 0.5
    # Идеальный луп (однотонный источник): стык практически нулевой
    assert meta["loop_seam"] is not None and meta["loop_seam"] < 5

    # Повторная сборка: ничего не перекодируется
    res2 = build_assets(root)
    assert res2.built == [] and res2.errors == []
    assert "mov/demo/loop01.webm" in res2.fresh

    # check-режим видит свежесть обоих выходов
    res3 = build_assets(root, check=True)
    assert res3.stale == [] and res3.errors == []


def test_loop_seam_warning_on_non_loop(tmp_path):
    root = _mk_root(tmp_path)
    _make_video(root / "assets_src/video_src/demo/pan.mp4", source="testsrc")
    res = build_assets(root)
    assert res.errors == []
    assert any("стык лупа" in w for w in res.warnings)


def test_sidecar_options_and_invalidation(tmp_path):
    root = _mk_root(tmp_path)
    src = root / "assets_src/video_src/demo/anim.mp4"
    _make_video(src, source="testsrc")
    sidecar = src.with_name("anim.video.yaml")
    sidecar.write_text("schema: video_src@1\nloop: false\n", encoding="utf-8")

    res = build_assets(root)
    assert res.errors == []
    meta = json.loads((root / "game/assets/mov/demo/anim.webm.meta.json")
                      .read_text(encoding="utf-8"))
    assert meta["loop"] is False and meta["loop_seam"] is None
    assert not any("стык лупа" in w for w in res.warnings)   # не луп — не проверяем стык

    # Правка sidecar инвалидирует выход (опции — часть источника)
    sidecar.write_text("schema: video_src@1\nloop: true\n", encoding="utf-8")
    res2 = build_assets(root)
    assert "mov/demo/anim.webm" in res2.built + res2.from_cache


def test_video_naming_and_group_required(tmp_path):
    root = _mk_root(tmp_path)
    _make_video(root / "assets_src/video_src/orphan.mp4")          # без группы
    _make_video(root / "assets_src/video_src/demo/Bad-Name.mp4")   # не-slug
    res = build_assets(root)
    text = "\n".join(res.errors)
    assert "video_src/<group>/<name>" in text
    assert "вне конвенции" in text


def test_orphan_video_cleanup_and_only_transforms(tmp_path):
    root = _mk_root(tmp_path)
    png = root / "assets_src/art/backgrounds/gate/day.png"
    from PIL import Image
    png.parent.mkdir(parents=True)
    Image.new("RGB", (128, 96), (10, 20, 30)).save(png, "PNG")
    _make_video(root / "assets_src/video_src/demo/loop01.mp4")
    res = build_assets(root)
    assert res.errors == []

    # Сборка только видео-ветки не должна снести статику и её манифест
    (root / "assets_src/video_src/demo/loop01.mp4").unlink()
    res2 = build_assets(root, only_transforms={"video2webm"})
    assert sorted(res2.deleted) == ["mov/demo/loop01.poster.webp",
                                   "mov/demo/loop01.webm",
                                   "mov/demo/loop01.webm.meta.json"]
    assert (root / "game/assets/bg/gate/day.webp").is_file()
    res3 = build_assets(root, check=True)
    assert res3.stale == []     # манифест статики пережил фильтрованную сборку


def test_cg_track_and_image_emission(tmp_path):
    from vn.content.images import ImagesReport, emit_images

    root = _mk_root(tmp_path)
    from PIL import Image
    cg = root / "assets_src/art/cg/ch01/rooftop_kiss.png"
    cg.parent.mkdir(parents=True)
    Image.new("RGB", (128, 96), (200, 30, 30)).save(cg, "PNG")
    _make_video(root / "assets_src/video_src/nsfw/scene01.mp4")

    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/cg/ch01/rooftop_kiss.webp").is_file()

    rep = ImagesReport()
    text = emit_images(root, {}, [], rep, "# h\n")
    assert 'image cg ch01 rooftop_kiss = "assets/cg/ch01/rooftop_kiss.webp"' in text
    # Movie получает постер-кадр как image= — заглушку до старта воспроизведения
    assert ('image mov nsfw scene01 = Movie(play="assets/mov/nsfw/scene01.webm", '
            'loop=True, image="assets/mov/nsfw/scene01.poster.webp")') in text


def test_validate_output_budget_and_codec(tmp_path):
    from vn.assets import video as videomod

    root = _mk_root(tmp_path)
    _make_video(root / "assets_src/video_src/demo/loop01.mp4")
    res = build_assets(root)
    assert res.errors == []
    out = root / "game/assets/mov/demo/loop01.webm"

    errors, warnings, s = videomod.validate_output(
        out, dict(videomod.DEFAULT_OPTS), tmp_path / "wd", file_budget_mb=0.000001)
    assert any("бюджета" in e for e in errors)

    # Сырец (mp4/h264) строгую проверку выхода не проходит — кодек не vp9
    src = root / "assets_src/video_src/demo/loop01.mp4"
    errors2, _w, _s = videomod.validate_output(src, dict(videomod.DEFAULT_OPTS), tmp_path / "wd")
    assert any("vp9" in e for e in errors2)


def test_sequence_assembles_into_video_master(tmp_path):
    """PNG-секвенция -> видео-мастер: захват из DAZ/Wan приходит кадрами, а
    видео-трек умеет только «готовый файл -> webm» (ADR-0012, AUDIT-005)."""
    from PIL import Image

    from vn.assets.video import VideoError, assemble_sequence

    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(1, 13):
        Image.new("RGB", (64, 48), (i * 15, 40, 80)).save(frames / f"frame_{i:04d}.png")

    root = _mk_root(tmp_path)
    dest = root / "assets_src" / "video_src" / "ch01" / "rain.mp4"
    info = assemble_sequence(frames, dest, fps=12.0)
    assert dest.is_file() and info["frames"] == 12
    assert (info["width"], info["height"]) == (64, 48)
    assert abs(info["duration_s"] - 1.0) < 0.2

    # Мастер проходит общий видео-трек без особой обработки
    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/mov/ch01/rain.webm").is_file()
    assert (root / "game/assets/mov/ch01/rain.poster.webp").is_file()


def test_sequence_with_gaps_is_error(tmp_path):
    """Дыра в нумерации: ffmpeg молча остановился бы на первой — видео оказалось
    бы обрезанным, и никто бы не заметил."""
    from PIL import Image

    from vn.assets.video import VideoError, assemble_sequence

    frames = tmp_path / "frames"
    frames.mkdir()
    for i in (1, 2, 5):
        Image.new("RGB", (64, 48), (10, 20, 30)).save(frames / f"f_{i:04d}.png")
    with pytest.raises(VideoError, match="дыр"):
        assemble_sequence(frames, tmp_path / "out.mp4")
