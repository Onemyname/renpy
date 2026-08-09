"""Внешние источники графики (DAZ / VaM / Sims 4): единый контракт деклараций.

Главное, что здесь проверяется, — сквозной путь DAZ → Wan/ComfyUI → игра, и то,
что игра о нём НЕ знает: на выходе обычный ассет, а происхождение живёт в
провенансе рядом с мастером, а не в рантайме.
"""

import json
import shutil

import pytest
from helpers import img, mk_root

from vn.assets import sources
from vn.assets.pipeline import build_assets


def _mk(tmp_path, repo_root):
    root = mk_root(tmp_path)
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    return root


def _decl(root, kind, text):
    p = root / "assets_src" / kind.dirname / "ch01" / "kiss.render.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_scaffold_matches_validator_expectations(tmp_path, repo_root):
    """Скаффолдер и валидатор обязаны одинаково считать output из id — иначе
    заготовка сразу красная."""
    root = _mk(tmp_path, repo_root)
    scene = root / "assets_src" / "daz" / "ch01" / "kiss" / "scene.duf"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"duf")

    dest = sources.scaffold(root, sources.DAZ, "cg/ch01/kiss",
                            "daz/ch01/kiss/scene.duf", (128, 96))
    assert dest.is_file()
    rep = sources.validate(root, sources.DAZ)
    assert rep.errors == []                       # выход ещё не отрендерен -> warning
    assert any("ещё не получен" in w for w in rep.warnings)

    # Скаффолдер целится в зону мастеров art/, а не в исторический png/
    assert sources.output_for_id("cg/ch01/kiss") == "art/cg/ch01/kiss.png"
    assert sources.output_for_id("spr/anna/stand/base") == "art/characters/anna/stand/base.png"
    assert sources.output_for_id("bg/roof/day", ext="jpg") == "art/backgrounds/roof/day.jpg"
    assert sources.output_for_id("mov/ch01/rain") == "video_src/ch01/rain.mp4"


def test_id_must_match_output(tmp_path, repo_root):
    """Расхождение id и output означало бы провенанс, привязанный не к тому кадру."""
    root = _mk(tmp_path, repo_root)
    scene = root / "assets_src" / "daz" / "ch01" / "kiss" / "scene.duf"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"duf")
    _decl(root, sources.DAZ,
          "schema: daz_render@1\n"
          "id: cg/ch01/WRONG\n".replace("WRONG", "other") +
          "source: daz/ch01/kiss/scene.duf\n"
          "output: art/cg/ch01/kiss.png\n"
          "render: {resolution: [128, 96], renderer: iray, camera: cam}\n")
    rep = sources.validate(root, sources.DAZ)
    assert any("не соответствует выходу" in e for e in rep.errors)


def test_declared_resolution_must_match_file(tmp_path, repo_root):
    """«Отрендерил в 4K» в YAML при 1080p на диске раньше проходило молча."""
    root = _mk(tmp_path, repo_root)
    scene = root / "assets_src" / "daz" / "ch01" / "kiss" / "scene.duf"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"duf")
    img(root / "assets_src" / "art" / "cg" / "ch01" / "kiss.png", (128, 96), "RGB", "PNG")
    _decl(root, sources.DAZ,
          "schema: daz_render@1\n"
          "id: cg/ch01/kiss\n"
          "source: daz/ch01/kiss/scene.duf\n"
          "output: art/cg/ch01/kiss.png\n"
          "render: {resolution: [3840, 2160], renderer: iray, camera: cam}\n")
    rep = sources.validate(root, sources.DAZ)
    assert any("не описывает то, что лежит на диске" in e for e in rep.errors)


def test_daz_then_wan_chain_reaches_the_game(tmp_path, repo_root):
    """Сквозной production-путь ветки DAZ + WAN:

        .duf -> DAZ-рендер -> AI-полировка (ComfyUI/Wan) -> мастер
             -> ассет-конвейер -> image в игре

    Проверяется и то, что провенанс сохраняет ОБА шага, и то, что в игру уезжает
    обычный ассет — ни имя источника, ни параметры генерации в game/ не попадают."""
    from vn.assets import provenance as prov
    from vn.content.images import ImagesReport, emit_images

    root = _mk(tmp_path, repo_root)
    scene = root / "assets_src" / "daz" / "ch01" / "kiss" / "scene.duf"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"duf-scene")

    # 1) DAZ-рендер лёг в зону мастеров
    master = root / "assets_src" / "art" / "cg" / "ch01" / "kiss.png"
    img(master, (128, 96), "RGB", "PNG")
    _decl(root, sources.DAZ,
          "schema: daz_render@1\n"
          "id: cg/ch01/kiss\n"
          "source: daz/ch01/kiss/scene.duf\n"
          "output: art/cg/ch01/kiss.png\n"
          "render: {resolution: [128, 96], renderer: iray, camera: cam_main}\n")
    rep = sources.validate(root, sources.DAZ)
    assert rep.errors == [] and rep.provenance_written

    # 2) Поверх рендера — шаг AI-обработки (Wan/ComfyUI): цепочка, а не замена
    prov.record(root, master, source=None, note="Wan I2V polish, denoise 0.35")
    chain = json.loads((master.parent / (master.name + ".provenance.json"))
                       .read_text(encoding="utf-8"))["chain"]
    assert [s["kind"] for s in chain] == ["daz_render", "manual"]
    assert chain[0]["settings"]["renderer"] == "iray"

    # 3) Общий конвейер: мастер -> game-ready варианты
    res = build_assets(root)
    assert res.errors == []
    assert (root / "game/assets/cg/ch01/kiss.webp").is_file()
    assert (root / "game/assets/cg/ch01/kiss@2.webp").is_file()

    # 4) Игра видит обычный образ и ничего не знает про DAZ/Wan
    irep = ImagesReport()
    text = emit_images(root, {}, [], irep, "# h\n")
    assert 'image cg ch01 kiss = "assets/cg/ch01/kiss.webp"' in text
    for forbidden in ("daz", "duf", "wan", "comfy", "iray"):
        assert forbidden not in text.lower()


def test_all_sources_share_one_contract(tmp_path, repo_root):
    """Три источника — одна кодовая ветка: расхождение поведения означало бы,
    что новая проверка добавлена не везде."""
    root = _mk(tmp_path, repo_root)
    for kind, scene_rel, extra in (
        (sources.DAZ, "daz/s.duf", "render: {resolution: [128, 96], renderer: iray, camera: c}"),
        (sources.VAM, "vam/s.json", "capture: {resolution: [128, 96], mode: screenshot}"),
        (sources.SIMS4, "sims4/s.zip",
         "capture: {resolution: [128, 96], mode: screenshot, game_version: '1.126'}"),
    ):
        (root / "assets_src" / kind.dirname).mkdir(parents=True, exist_ok=True)
        (root / "assets_src" / scene_rel).write_bytes(b"scene")
        img(root / "assets_src" / "art" / "cg" / kind.dirname / "shot.png",
            (128, 96), "RGB", "PNG")
        p = root / "assets_src" / kind.dirname / "shot.render.yaml"
        p.write_text(
            f"schema: {kind.schema_id}\n"
            f"id: cg/{kind.dirname}/shot\n"
            f"{kind.scene_key}: {scene_rel}\n"
            f"output: art/cg/{kind.dirname}/shot.png\n{extra}\n", encoding="utf-8")
        rep = sources.validate(root, kind)
        assert rep.errors == [], f"{kind.label}: {rep.errors}"
        assert len(rep.checked) == 1 and rep.provenance_written
