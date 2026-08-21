"""Провенанс сырцов (ADR-0006): «хэш исходника -> параметры обработки -> хэш артефакта».

Каждый нетривиально полученный сырец (DAZ-рендер, AI-обработка, ручная правка)
несёт сайдкар <file>.provenance.json (schema provenance@1) с цепочкой шагов.
Дальше по конвейеру цепочку продолжают манифест сборки ассетов (.vncache) и
mov_meta@1 — второй системы метаданных сознательно нет.

Автоизвлечение ComfyUI: PNG-выходы ComfyUI несут полный граф в tEXt-чанках
(prompt = API-граф, workflow = UI-граф) — record() вытаскивает seed, модель,
LoRA, промпты и sampler из API-графа без ручного ввода."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import blake3

from .. import __version__
from ..repo import write_text_lf

PROV_SUFFIX = ".provenance.json"


class ProvenanceError(RuntimeError):
    pass


@dataclass
class ProvReport:
    checked: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _b3(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def _hash_of(path: Path) -> dict:
    return {"algo": "blake3", "hex": _b3(path.read_bytes())}


def _src_root(root: Path) -> Path:
    return root / "assets_src"


def _rel_to_src(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(_src_root(root).resolve()).as_posix()
    except ValueError:
        raise ProvenanceError(
            f"{path}: провенанс ведётся только для сырцов в assets_src/ (G2)")


def prov_path(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + PROV_SUFFIX)


def load(artifact: Path) -> dict | None:
    p = prov_path(artifact)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _write(root: Path, artifact: Path, doc: dict) -> Path:
    doc["pipeline"] = f"vn {__version__}"
    doc["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = prov_path(artifact)
    write_text_lf(out, json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return out


# ── Извлечение параметров из PNG ComfyUI ──────────────────────────────────────

def extract_comfyui_png(path: Path) -> dict | None:
    """API-граф из tEXt-чанка 'prompt' (+ UI-граф 'workflow' как запасной).
    None = это не выход ComfyUI."""
    from PIL import Image

    try:
        with Image.open(path) as im:
            text = dict(getattr(im, "text", None) or im.info or {})
    except OSError:
        return None
    result = {}
    for key in ("prompt", "workflow"):
        raw = text.get(key)
        if isinstance(raw, str):
            try:
                result[key] = json.loads(raw)
            except ValueError:
                pass
    return result or None


def _resolve_link(graph: dict, ref) -> dict | None:
    """inputs.positive = [node_id, slot] -> узел графа."""
    if isinstance(ref, list) and ref and str(ref[0]) in graph:
        return graph[str(ref[0])]
    return None


def _trace_text(graph: dict, node: dict | None) -> str | None:
    """Текст промпта: идём по ссылкам до узла с inputs.text (CLIPTextEncode и
    совместимые), максимум 8 переходов — графы бывают с Reroute-цепочками."""
    for _ in range(8):
        if node is None:
            return None
        inputs = node.get("inputs") or {}
        text = inputs.get("text")
        if isinstance(text, str):
            return text
        nxt = None
        for v in inputs.values():
            candidate = _resolve_link(graph, v)
            if candidate is not None:
                nxt = candidate
                break
        node = nxt
    return None


WORKFLOW_KEY_PREFIX = "workflows/"


def store_workflow(root: Path, api_graph: dict, workflow: dict | None = None) -> tuple[dict, bool]:
    """Положить граф(ы) ComfyUI в контент-адресуемое хранилище сырцов по
    workflow_hash (дедупликация: одинаковые графы = один объект). Возвращает
    (hash-док, stored): stored=False — хранилище недоступно, зовущий решает,
    инлайнить ли граф в сайдкар (git-вес против потери провенанса)."""
    from .storage import StorageError, backend_for

    blob = json.dumps({"prompt": api_graph, "workflow": workflow},
                      ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = _b3(json.dumps(api_graph, sort_keys=True).encode())
    try:
        backend = backend_for(root, "default")
        backend.put(WORKFLOW_KEY_PREFIX + digest, blob)
        return {"algo": "blake3", "hex": digest}, True
    except (StorageError, OSError):
        return {"algo": "blake3", "hex": digest}, False


def load_workflow(root: Path, workflow_hash: dict) -> dict | None:
    """Достать граф из хранилища по хэшу (обратная операция store_workflow)."""
    from .storage import StorageError, backend_for

    try:
        backend = backend_for(root, "default")
        return json.loads(backend.get(WORKFLOW_KEY_PREFIX + workflow_hash["hex"]))
    except (StorageError, OSError, ValueError):
        return None


def comfyui_step_from_graph(api_graph: dict, workflow: dict | None = None) -> dict:
    """Шаг chain[kind=comfyui] из API-графа ComfyUI (лучшее усилие: чего нет в
    графе — остаётся null и добивается флагами CLI).

    Граф НЕ инлайнится в шаг: при десятках тысяч AI-артефактов инлайн-JSON
    раздувает git на гигабайты. record() кладёт граф в хранилище по
    workflow_hash (store_workflow) и оставляет workflow=None; инлайн — только
    аварийный fallback без хранилища."""
    step = {"kind": "comfyui", "workflow": None,
            "workflow_hash": {"algo": "blake3",
                              "hex": _b3(json.dumps(api_graph, sort_keys=True).encode())},
            "model": None, "seed": None, "prompt": None, "negative_prompt": None,
            "loras": [], "resolution": None, "sampler": None, "steps": None,
            "cfg": None, "denoise": None}
    graph = {str(k): v for k, v in api_graph.items() if isinstance(v, dict)}
    sampler_node = None
    for node in graph.values():
        cls = node.get("class_type", "")
        inputs = node.get("inputs") or {}
        if "seed" in inputs or "noise_seed" in inputs:
            sampler_node = sampler_node or node
        if cls in ("CheckpointLoaderSimple", "CheckpointLoader"):
            step["model"] = step["model"] or inputs.get("ckpt_name")
        elif "UNETLoader" in cls or "UnetLoader" in cls:
            step["model"] = step["model"] or inputs.get("unet_name")
        elif "LoraLoader" in cls and inputs.get("lora_name"):
            step["loras"].append({"name": inputs["lora_name"],
                                  "strength": inputs.get("strength_model")})
        elif cls in ("EmptyLatentImage", "EmptySD3LatentImage") and inputs.get("width"):
            step["resolution"] = [int(inputs["width"]), int(inputs["height"])]
    if sampler_node is not None:
        inputs = sampler_node.get("inputs") or {}
        step["seed"] = inputs.get("seed", inputs.get("noise_seed"))
        step["steps"] = inputs.get("steps")
        step["cfg"] = inputs.get("cfg")
        step["sampler"] = inputs.get("sampler_name")
        step["denoise"] = inputs.get("denoise")
        step["prompt"] = _trace_text(graph, _resolve_link(graph, inputs.get("positive")))
        step["negative_prompt"] = _trace_text(graph, _resolve_link(graph, inputs.get("negative")))
    return step


# ── Запись ────────────────────────────────────────────────────────────────────

def record(root: Path, artifact: Path, source: Path | None = None,
           workflow_file: Path | None = None, note: str | None = None,
           overrides: dict | None = None) -> tuple[Path, dict]:
    """Создать/обновить провенанс артефакта.

    Цепочка: провенанс source (если есть) копируется как префикс; затем
    добавляется шаг этого артефакта — comfyui (автоизвлечение из PNG или
    --workflow) либо manual (с note). Возвращает (путь сайдкара, документ)."""
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise ProvenanceError(f"{artifact}: файла нет")
    art_rel = _rel_to_src(root, artifact)

    chain: list[dict] = []
    src_ref = None
    if source is not None:
        source = source.resolve()
        if not source.is_file():
            raise ProvenanceError(f"{source}: файла-источника нет")
        src_rel = _rel_to_src(root, source)
        src_ref = {"path": src_rel, "hash": _hash_of(source)}
        parent = load(source)
        if parent:
            chain.extend(parent["chain"])
    else:
        # Шаг ПОВЕРХ того же файла (штатный путь AI-полировки, ADR-0006: «обычный
        # comfyui-шаг поверх захвата»). Прошлая цепочка обязана уцелеть — иначе
        # запись полировки стирала происхождение рендера, и артефакт переставал
        # прослеживаться до .duf ровно в тот момент, когда становился финальным.
        existing = load(artifact)
        if existing:
            chain.extend(existing["chain"])

    step = None
    api_graph = ui_graph = None
    if workflow_file is not None:
        api_graph = json.loads(Path(workflow_file).read_text(encoding="utf-8"))
        step = comfyui_step_from_graph(api_graph)
    elif artifact.suffix.lower() == ".png":
        extracted = extract_comfyui_png(artifact)
        if extracted and "prompt" in extracted:
            api_graph, ui_graph = extracted["prompt"], extracted.get("workflow")
            step = comfyui_step_from_graph(api_graph, ui_graph)
    if step is not None and api_graph is not None:
        # Граф — в хранилище по хэшу (дедуп); сайдкар несёт только хэш+скаляры.
        # Без хранилища инлайним: потерять воспроизводимость хуже, чем раздуть git.
        _hash_doc, stored = store_workflow(root, api_graph, ui_graph)
        if not stored:
            step["workflow"] = api_graph
    if step is None:
        if note is None:
            raise ProvenanceError(
                f"{art_rel}: параметры генерации не извлекаются (не PNG ComfyUI) — "
                f"передайте --workflow <api.json> или опишите шаг через --note")
        step = {"kind": "manual", "source": src_ref, "note": note}
    else:
        step["source"] = src_ref
        for key, value in (overrides or {}).items():
            if value is not None:
                step[key] = value
    # Повторная запись того же шага не должна растить цепочку: команду гоняют
    # многократно (watch, повтор после правки), а история обработки от этого не
    # меняется. Сравниваем по содержимому шага, а не по факту вызова.
    if chain and chain[-1] == step:
        chain.pop()
    chain.append(step)

    doc = {
        "schema": "provenance@1",
        "artifact": {"path": art_rel, "hash": _hash_of(artifact)},
        "chain": chain,
    }
    return _write(root, artifact, doc), doc


def record_render(root: Path, decl_rel: str, output: Path, kind: str,
                  source_path: str, settings: dict) -> Path:
    """Провенанс объявленного рендера/захвата (DAZ, VaM, Sims 4): шаг-происхождение
    становится началом цепочки. Существующие последующие шаги (AI-обработка,
    ручная правка) сохраняются, если артефакт не менялся. Прошлый шаг-происхождение
    любого движка (*_render) заменяется — у артефакта один источник."""
    src = _src_root(root) / source_path
    source_ref = {"path": source_path,
                  "hash": _hash_of(src) if src.is_file() else _manifest_hash(root, source_path)}
    if source_ref["hash"] is None:
        raise ProvenanceError(
            f"{source_path}: нет ни файла, ни манифеста — сначала vn assets push")
    step = {"kind": kind, "source": source_ref,
            "declaration": decl_rel, "settings": settings}
    existing = load(output)
    chain = [step]
    if existing:
        tail = [s for s in existing["chain"]
                if not str(s.get("kind", "")).endswith("_render")]
        chain.extend(tail)
    doc = {
        "schema": "provenance@1",
        "artifact": {"path": _rel_to_src(root, output), "hash": _hash_of(output)},
        "chain": chain,
    }
    return _write(root, output, doc)


def _manifest_hash(root: Path, rel: str) -> dict | None:
    """Хэш из манифеста хранилища (файл может быть не вытянут локально)."""
    mf = _src_root(root) / (rel + ".manifest.json")
    if not mf.is_file():
        return None
    return json.loads(mf.read_text(encoding="utf-8"))["hash"]


# ── Проверка ──────────────────────────────────────────────────────────────────

def verify(root: Path, scope: str | None = None) -> ProvReport:
    """Все *.provenance.json под assets_src: схема, хэш артефакта, хэши источников
    (локальный файл или манифест хранилища). Restore-контракт: артефакт можно
    восстановить = известен источник + параметры, и они не разошлись с файлами."""
    from ..schemas import SchemaRegistry

    rep = ProvReport()
    registry = SchemaRegistry(root / "tools" / "schemas")
    base = _src_root(root)
    for prov in sorted(base.rglob(f"*{PROV_SUFFIX}")):
        rel = prov.relative_to(root).as_posix()
        if scope and not prov.relative_to(base).as_posix().startswith(scope.rstrip("/")):
            continue
        try:
            doc = json.loads(prov.read_text(encoding="utf-8"))
        except ValueError as e:
            rep.errors.append(f"{rel}: битый JSON: {e}")
            continue
        errs = registry.validate(doc, rel)
        if errs:
            rep.errors.extend(errs)
            continue
        rep.checked.append(rel)

        artifact = base / doc["artifact"]["path"]
        if not artifact.is_file():
            rep.errors.append(f"{rel}: артефакт {doc['artifact']['path']} отсутствует")
        elif _b3(artifact.read_bytes()) != doc["artifact"]["hash"]["hex"]:
            rep.errors.append(
                f"{rel}: артефакт {doc['artifact']['path']} изменён после записи "
                f"провенанса — перезапишите (vn assets provenance record …)")

        for i, step in enumerate(doc["chain"]):
            # comfyui-шаг без инлайн-графа обязан находить граф в хранилище
            # (иначе «воспроизводимость» — только скаляры).
            if step.get("kind") == "comfyui" and not step.get("workflow"):
                wh = step.get("workflow_hash")
                if wh and load_workflow(root, wh) is None:
                    rep.warnings.append(
                        f"{rel}: chain[{i}]: workflow-граф {wh['hex'][:16]}… отсутствует "
                        f"в хранилище — перезапишите провенанс из исходного PNG "
                        f"(vn assets provenance record)")
            src_ref = step.get("source")
            if not src_ref:
                continue
            src = base / src_ref["path"]
            if src.is_file():
                if _b3(src.read_bytes()) != src_ref["hash"]["hex"]:
                    rep.errors.append(
                        f"{rel}: chain[{i}]: источник {src_ref['path']} изменён — "
                        f"артефакт больше не воспроизводим из этой цепочки")
            else:
                mh = _manifest_hash(root, src_ref["path"])
                if mh is None:
                    rep.warnings.append(
                        f"{rel}: chain[{i}]: источника {src_ref['path']} нет локально "
                        f"и нет манифеста (vn assets push?)")
                elif mh["hex"] != src_ref["hash"]["hex"]:
                    rep.warnings.append(
                        f"{rel}: chain[{i}]: {src_ref['path']}: в хранилище уже другая "
                        f"версия — провенанс ссылается на историческую")
    return rep
