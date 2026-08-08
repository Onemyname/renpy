"""Провенанс (ADR-0006): автоизвлечение параметров из PNG ComfyUI, композиция
цепочек DAZ->AI, verify с локальными файлами и манифестами хранилища."""

import json
import shutil

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from vn.assets.daz import validate_renders
from vn.assets.provenance import (comfyui_step_from_graph, extract_comfyui_png,
                                  record, verify)

# tools/vn/tests -> корень: схемы нужны verify/validate_renders
from conftest import REPO_ROOT

API_GRAPH = {
    "3": {"class_type": "KSampler",
          "inputs": {"seed": 123456, "steps": 4, "cfg": 1.0, "denoise": 0.75,
                     "sampler_name": "euler", "model": ["10", 0],
                     "positive": ["6", 0], "negative": ["7", 0]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "cinematic rooftop kiss"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, lowres"}},
    "10": {"class_type": "LoraLoader",
           "inputs": {"lora_name": "detail_slider.safetensors", "strength_model": 0.8,
                      "model": ["11", 0]}},
    "11": {"class_type": "CheckpointLoaderSimple",
           "inputs": {"ckpt_name": "sdxl_photoreal.safetensors"}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 1920, "height": 1080, "batch_size": 1}},
}


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "assets_src" / "png" / "cg").mkdir(parents=True)
    (root / "tools").mkdir()
    # Реестр схем — общий с боевым (schemas читаются verify/validate_renders)
    shutil.copytree(REPO_ROOT / "tools" / "schemas", root / "tools" / "schemas")
    # Хранилище сырцов: workflow-графы провенанса едут сюда, не в git-сайдкары
    store = (root.parent / "vn-store").resolve()
    (root / ".vnstorage.yaml").write_text(
        f'schema: storage@1\nstorages:\n  default: {{type: file, path: "{store.as_posix()}"}}\n',
        encoding="utf-8")
    return root


def _comfy_png(path, graph=API_GRAPH, color=(90, 60, 30, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    info.add_text("prompt", json.dumps(graph))
    Image.new("RGBA", (64, 48), color).save(path, "PNG", pnginfo=info)


def test_extract_and_step_from_graph(tmp_path):
    png = tmp_path / "x.png"
    _comfy_png(png)
    extracted = extract_comfyui_png(png)
    assert extracted and "prompt" in extracted

    step = comfyui_step_from_graph(extracted["prompt"])
    assert step["seed"] == 123456
    assert step["model"] == "sdxl_photoreal.safetensors"
    assert step["loras"] == [{"name": "detail_slider.safetensors", "strength": 0.8}]
    assert step["prompt"] == "cinematic rooftop kiss"
    assert step["negative_prompt"] == "blurry, lowres"
    assert step["sampler"] == "euler" and step["steps"] == 4
    assert step["resolution"] == [1920, 1080]


def test_record_and_verify_roundtrip(tmp_path):
    root = _mk_root(tmp_path)
    art = root / "assets_src/png/cg/ch01/kiss_ai.png"
    _comfy_png(art)

    path, doc = record(root, art)
    assert path.name == "kiss_ai.png.provenance.json"
    step = doc["chain"][-1]
    assert step["kind"] == "comfyui"
    assert step["seed"] == 123456
    # Граф НЕ инлайнится: в сайдкаре только хэш, блоб — в хранилище (дедуп)
    assert step["workflow"] is None
    blob = tmp_path / "vn-store" / "objects" / "workflows" / step["workflow_hash"]["hex"]
    assert blob.is_file()
    from vn.assets.provenance import load_workflow
    restored = load_workflow(root, step["workflow_hash"])
    assert restored and restored["prompt"]["3"]["inputs"]["seed"] == 123456

    rep = verify(root)
    assert rep.errors == [] and rep.warnings == [] and len(rep.checked) == 1

    # Пропажа графа из хранилища — предупреждение verify (восстановимость)
    blob.unlink()
    repw = verify(root)
    assert any("workflow-граф" in w for w in repw.warnings)
    _comfy_png(art)   # вернуть артефакт в исходное состояние хэша не нужно — ниже подмена

    # Подмена артефакта после записи провенанса — ошибка verify
    Image.new("RGBA", (64, 48), (1, 2, 3, 255)).save(art, "PNG")
    rep2 = verify(root)
    assert any("изменён после записи" in e for e in rep2.errors)


def test_record_inlines_workflow_without_store(tmp_path):
    """Без хранилища граф инлайнится (потеря воспроизводимости хуже веса git)."""
    root = _mk_root(tmp_path)
    (root / ".vnstorage.yaml").unlink()
    art = root / "assets_src/png/cg/solo.png"
    _comfy_png(art)
    _path, doc = record(root, art)
    assert doc["chain"][-1]["workflow"] is not None


def test_chain_composition_daz_then_ai(tmp_path):
    root = _mk_root(tmp_path)
    base = root / "assets_src"
    # DAZ-сцена + декларация рендера + «рендер»
    duf = base / "daz/ch01/kiss/scene.duf"
    duf.parent.mkdir(parents=True)
    duf.write_text('{"scene": "stub"}', encoding="utf-8")
    render_png = base / "png/cg/ch01/kiss.png"
    _comfy_png(render_png, graph={})     # содержимое не важно — это «рендер»
    decl = base / "daz/ch01/kiss/kiss.render.yaml"
    decl.write_text(
        "schema: daz_render@1\n"
        "id: cg/ch01/kiss\n"
        "source: daz/ch01/kiss/scene.duf\n"
        "output: png/cg/ch01/kiss.png\n"
        "render:\n"
        "  resolution: [1920, 1080]\n"
        "  renderer: iray\n"
        "  camera: cam_main\n"
        "  lighting: hdri_studio_03\n"
        "  character_presets: [mira_v2]\n",
        encoding="utf-8")

    rep = validate_renders(root)
    assert rep.errors == []
    assert rep.provenance_written == ["assets_src/png/cg/ch01/kiss.png.provenance.json"]

    # AI-обработка поверх рендера: цепочка = daz_render + comfyui
    ai = base / "png/cg/ch01/kiss_polished.png"
    _comfy_png(ai)
    _path, doc = record(root, ai, source=render_png)
    kinds = [s["kind"] for s in doc["chain"]]
    assert kinds == ["daz_render", "comfyui"]
    assert doc["chain"][0]["settings"]["camera"] == "cam_main"
    assert doc["chain"][1]["source"]["path"] == "png/cg/ch01/kiss.png"

    assert verify(root).errors == []


def test_daz_validate_missing_source_and_output(tmp_path):
    root = _mk_root(tmp_path)
    base = root / "assets_src"
    decl = base / "daz/ch02/alley/alley.render.yaml"
    decl.parent.mkdir(parents=True)
    decl.write_text(
        "schema: daz_render@1\n"
        "id: bg/alley/night\n"
        "source: daz/ch02/alley/scene.duf\n"       # нет ни файла, ни манифеста
        "output: png/backgrounds/alley/night.png\n"  # ещё не отрендерен
        "render: {resolution: [1920, 1080], renderer: iray, camera: cam}\n",
        encoding="utf-8")
    rep = validate_renders(root)
    assert any("ни локально, ни в манифестах" in e for e in rep.errors)
    assert any("ещё не отрендерен" in w for w in rep.warnings)


def test_vam_validate_and_chain(tmp_path):
    from vn.assets.vam import validate_scenes

    root = _mk_root(tmp_path)
    base = root / "assets_src"
    scene = base / "vam/ch01/beach/scene.json"
    scene.parent.mkdir(parents=True)
    scene.write_text('{"atoms": []}', encoding="utf-8")
    shot = base / "png/cg/ch01/beach.png"
    _comfy_png(shot, graph={})
    decl = base / "vam/ch01/beach/beach.render.yaml"
    decl.write_text(
        "schema: vam_render@1\n"
        "id: cg/ch01/beach\n"
        "scene: vam/ch01/beach/scene.json\n"
        "output: png/cg/ch01/beach.png\n"
        "capture:\n"
        "  resolution: [1920, 1080]\n"
        "  mode: screenshot\n"
        "  camera: WindowCamera\n"
        "  plugins: [ScreenshotHelper]\n"
        "  vamx: true\n",
        encoding="utf-8")

    rep = validate_scenes(root)
    assert rep.errors == []
    assert rep.provenance_written == ["assets_src/png/cg/ch01/beach.png.provenance.json"]

    doc = json.loads((shot.with_name("beach.png.provenance.json")).read_text(encoding="utf-8"))
    assert doc["chain"][0]["kind"] == "vam_render"
    assert doc["chain"][0]["settings"]["camera"] == "WindowCamera"
    assert verify(root).errors == []

    # AI-полировка поверх VaM-захвата: цепочка vam_render + comfyui
    ai = base / "png/cg/ch01/beach_polished.png"
    _comfy_png(ai)
    _p, aidoc = record(root, ai, source=shot)
    assert [s["kind"] for s in aidoc["chain"]] == ["vam_render", "comfyui"]


def test_vam_validate_missing_scene_and_output(tmp_path):
    from vn.assets.vam import validate_scenes

    root = _mk_root(tmp_path)
    decl = root / "assets_src/vam/ch02/room/room.render.yaml"
    decl.parent.mkdir(parents=True)
    decl.write_text(
        "schema: vam_render@1\n"
        "id: cg/room/night\n"
        "scene: vam/ch02/room/scene.json\n"          # нет ни файла, ни манифеста
        "output: png/cg/room/night.png\n"            # ещё не захвачен
        "capture: {resolution: [1280, 720], mode: screenshot}\n",
        encoding="utf-8")
    rep = validate_scenes(root)
    assert any("ни локально, ни в манифестах" in e for e in rep.errors)
    assert any("ещё не захвачен" in w for w in rep.warnings)


def test_sims4_validate_and_chain(tmp_path):
    from vn.assets.sims4 import validate_scenes

    root = _mk_root(tmp_path)
    base = root / "assets_src"
    scene = base / "sims4/ch01/loft/tray_bundle.zip"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"stub-tray-bundle")
    shot = base / "png/cg/ch01/loft.png"
    _comfy_png(shot, graph={})
    decl = base / "sims4/ch01/loft/loft.render.yaml"
    decl.write_text(
        "schema: sims4_render@1\n"
        "id: cg/ch01/loft\n"
        "scene: sims4/ch01/loft/tray_bundle.zip\n"
        "output: png/cg/ch01/loft.png\n"
        "capture:\n"
        "  resolution: [1920, 1080]\n"
        "  mode: screenshot\n"
        "  game_version: '1.115.216.1020'\n"
        "  camera: tab_free\n"
        "  mods: [wickedwhims, reshade_photoreal]\n",
        encoding="utf-8")

    rep = validate_scenes(root)
    assert rep.errors == []
    assert rep.provenance_written == ["assets_src/png/cg/ch01/loft.png.provenance.json"]

    doc = json.loads(shot.with_name("loft.png.provenance.json").read_text(encoding="utf-8"))
    assert doc["chain"][0]["kind"] == "sims4_render"
    assert doc["chain"][0]["settings"]["game_version"] == "1.115.216.1020"
    assert verify(root).errors == []

    # AI-полировка поверх захвата: цепочка sims4_render + comfyui
    ai = base / "png/cg/ch01/loft_polished.png"
    _comfy_png(ai)
    _p, aidoc = record(root, ai, source=shot)
    assert [s["kind"] for s in aidoc["chain"]] == ["sims4_render", "comfyui"]


def test_sims4_capture_requires_game_version(tmp_path):
    from vn.assets.sims4 import validate_scenes

    root = _mk_root(tmp_path)
    decl = root / "assets_src/sims4/ch02/bar/bar.render.yaml"
    decl.parent.mkdir(parents=True)
    decl.write_text(
        "schema: sims4_render@1\n"
        "id: cg/ch02/bar\n"
        "scene: sims4/ch02/bar/save.zip\n"            # нет ни файла, ни манифеста
        "output: png/cg/ch02/bar.png\n"               # ещё не захвачен
        "capture: {resolution: [1920, 1080], mode: screenshot}\n",  # нет game_version
        encoding="utf-8")
    rep = validate_scenes(root)
    # без game_version кадр невоспроизводим (патчи EA) — это ошибка схемы
    assert any("game_version" in e for e in rep.errors)


def test_sims4_validate_missing_scene_and_output(tmp_path):
    from vn.assets.sims4 import validate_scenes

    root = _mk_root(tmp_path)
    decl = root / "assets_src/sims4/ch02/bar/bar.render.yaml"
    decl.parent.mkdir(parents=True)
    decl.write_text(
        "schema: sims4_render@1\n"
        "id: cg/ch02/bar\n"
        "scene: sims4/ch02/bar/save.zip\n"            # нет ни файла, ни манифеста
        "output: png/cg/ch02/bar.png\n"               # ещё не захвачен
        "capture: {resolution: [1920, 1080], mode: screenshot, game_version: '1.115'}\n",
        encoding="utf-8")
    rep = validate_scenes(root)
    assert any("ни локально, ни в манифестах" in e for e in rep.errors)
    assert any("ещё не захвачен" in w for w in rep.warnings)


def test_manual_step_requires_note(tmp_path):
    root = _mk_root(tmp_path)
    art = root / "assets_src/png/cg/plain.png"
    art.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8)).save(art, "PNG")     # PNG без метаданных ComfyUI
    with pytest.raises(Exception) as ei:
        record(root, art)
    assert "--note" in str(ei.value) or "--workflow" in str(ei.value)
    _path, doc = record(root, art, note="ручная правка в Krita")
    assert doc["chain"][-1] == {"kind": "manual", "source": None,
                                "note": "ручная правка в Krita"}
