"""vn content graph — экспорт графа сцен в Mermaid (раздел 3): сценаристы смотрят
ветвление глазами, ревьюеры — диффом. Читает только декларации (SDK не нужен)."""

from __future__ import annotations

from pathlib import Path

from ..repo import chapter_zones, load_yaml
from .compile import CHAPTER_DIR_RE, SCENE_YAML_RE
from .scenes import _exit_entries, resolve_target


def build_graph(root: Path) -> str:
    """Граф включает главы паков наравне с ядром: межпаковые `exits` иначе выглядят
    висячими — цель у них есть, просто она в зоне, которую граф не обошёл. Пак
    подписан в заголовке подграфа, потому что «эта глава уедет не всем» — первое,
    что нужно знать, глядя на переход в неё."""
    lines = ["flowchart TD"]
    edges: list[str] = []
    for pack_id, chapters_dir in chapter_zones(root):
        for d in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
            m = CHAPTER_DIR_RE.match(d.name)
            if not m:
                continue
            ch_id = f"ch{m.group(1)}"
            meta = load_yaml(d / "chapter.yaml") if (d / "chapter.yaml").is_file() else {}
            tag = "" if pack_id == "core" else f" · pack {pack_id}"
            lines.append(
                f'    subgraph {ch_id}["{d.name} ({meta.get("status", "?")}){tag}"]')
            scenes_dir = d / "scenes"
            for f in sorted(scenes_dir.glob("*.scene.yaml")) if scenes_dir.is_dir() else []:
                sm = SCENE_YAML_RE.match(f.name)
                if not sm:
                    continue
                full_id = f"{ch_id}_s{sm.group(1)}"
                slug = f.name.split("_", 1)[1][: -len(".scene.yaml")]
                lines.append(f'        {full_id}["{full_id}<br/>{slug}"]')
                smeta = load_yaml(f)
                for exit_id, spec in (smeta.get("exits") or {}).items():
                    for e in _exit_entries(spec):
                        target = resolve_target(ch_id, e["to"])
                        label = exit_id + (f" [{e['when']}]" if e.get("when") else "")
                        # Экранирование для Mermaid: кавычки/скобки в when ломают синтаксис
                        label = (label.replace('"', "#quot;")
                                 .replace("<", "#lt;").replace(">", "#gt;"))
                        edges.append(f'    {full_id} -->|"{label}"| {target}')
                if not (smeta.get("exits") or {}):
                    edges.append(f"    {full_id} --> vn_end([конец контента])")
            lines.append("    end")
    lines.extend(edges)
    return "\n".join(lines) + "\n"
