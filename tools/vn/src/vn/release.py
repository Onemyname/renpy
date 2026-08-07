"""vn release — манифест релиза и changelog (раздел 7/1.9): версии контента
считаются по фактическому диффу реестров, а не по ручным пометкам («их забывают»)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .content.compile import CHAPTER_DIR_RE, SCENE_YAML_RE
from .repo import load_project, load_yaml

MANIFEST_REL = "ci/release-manifest.json"


@dataclass
class ReleaseReport:
    added_chapters: list[str] = field(default_factory=list)
    added_scenes: list[str] = field(default_factory=list)
    removed_scenes: list[str] = field(default_factory=list)
    changed: bool = False


def snapshot_content(root: Path) -> dict:
    chapters: dict[str, dict] = {}
    base = root / "content" / "chapters"
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        m = CHAPTER_DIR_RE.match(d.name)
        if not m:
            continue
        ch_id = f"ch{m.group(1)}"
        meta = load_yaml(d / "chapter.yaml") if (d / "chapter.yaml").is_file() else {}
        scenes = []
        for f in sorted((d / "scenes").glob("*.scene.yaml")) if (d / "scenes").is_dir() else []:
            sm = SCENE_YAML_RE.match(f.name)
            if sm:
                scenes.append(f"{ch_id}_s{sm.group(1)}")
        chapters[ch_id] = {"status": meta.get("status", "draft"), "scenes": scenes}
    return chapters


def update_changelog(root: Path) -> ReleaseReport:
    rep = ReleaseReport()
    project = load_project(root)
    manifest_path = root / MANIFEST_REL
    prev = {}
    if manifest_path.is_file():
        prev = json.loads(manifest_path.read_text(encoding="utf-8")).get("chapters", {})
    cur = snapshot_content(root)

    prev_scenes = {s for ch in prev.values() for s in ch["scenes"]}
    cur_scenes = {s for ch in cur.values() for s in ch["scenes"]}
    rep.added_chapters = sorted(set(cur) - set(prev))
    rep.added_scenes = sorted(cur_scenes - prev_scenes)
    rep.removed_scenes = sorted(prev_scenes - cur_scenes)
    rep.changed = bool(rep.added_chapters or rep.added_scenes or rep.removed_scenes)

    if rep.changed:
        lines = [f"## {project['version']}", ""]
        if rep.added_chapters:
            lines.append("Новые главы: " + ", ".join(rep.added_chapters))
        if rep.added_scenes:
            lines.append(f"Новые сцены ({len(rep.added_scenes)}): " + ", ".join(rep.added_scenes))
        if rep.removed_scenes:
            lines.append("Удалены сцены (см. renames.yaml): " + ", ".join(rep.removed_scenes))
        lines.append("")
        changelog = root / "docs" / "CHANGELOG.md"
        old = changelog.read_text(encoding="utf-8") if changelog.is_file() else "# Changelog\n\n"
        head, _, tail = old.partition("\n")
        changelog.write_text(head + "\n\n" + "\n".join(lines) + tail.lstrip("\n"),
                             encoding="utf-8")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(
        {"schema": "release_manifest@1", "version": project["version"], "chapters": cur},
        ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rep
