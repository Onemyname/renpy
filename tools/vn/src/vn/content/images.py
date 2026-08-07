"""Реестр образов (разделы 1.2/4): компилятор эмитит ЯВНЫЕ image-стейтменты и
layeredimage — автоопределение по game/images/ не используется (тихие коллизии имён).

Канон эмиттера layeredimage (G11): селекторные группы `attribute X default Null()`,
гейтинг слоёв только if_any, каждый attribute с явным displayable, oversampling @2,
пути с префиксом "assets/". Тонировка — сгенерированный config.tag_layer + camera sprites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImagesReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_locations(root: Path, src, registry, errors: list[str]) -> dict[str, dict]:
    """content/locations/<id>/location.yaml -> {id: meta}. Файлы фонов сверяются
    с собранной зоной game/assets (сборка ассетов идёт до компиляции контента)."""
    from ..repo import load_yaml

    locations: dict[str, dict] = {}
    base = root / "content" / "locations"
    if not base.is_dir():
        return locations
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        f = d / "location.yaml"
        if not f.is_file():
            errors.append(f"content/locations/{d.name}: нет location.yaml")
            continue
        rel, _digest = src(f)
        meta = load_yaml(f)
        errs = registry.validate(meta, rel)
        if errs:
            errors.extend(errs)
            continue
        if meta["id"] != d.name:
            errors.append(f"{rel}: id ({meta['id']}) != имени папки ({d.name})")
            continue
        locations[meta["id"]] = meta
    return locations


def emit_images(root: Path, locations: dict[str, dict],
                char_docs: list[tuple[str, dict]], rep: ImagesReport, header: str) -> str:
    from ..assets.pipeline import sprite_tree

    # image/layeredimage имеют СОБСТВЕННЫЙ базовый приоритет 500: offset 500 дал бы
    # суммарные 1000 — вне допустимого диапазона движка (ADR-0003). Оффсет 0 кладёт
    # образы ровно на канонические 500 (контентные define, C8).
    out = [header, "init offset = 0\n"]

    # ── Фоны локаций: image bg <loc> <variant> ────────────────────────────────
    assets = root / "game" / "assets"
    n_bg = 0
    for loc_id, meta in sorted(locations.items()):
        for variant, path in sorted((meta.get("backgrounds") or {}).items()):
            if not (assets / Path(path).relative_to("assets")).is_file():
                rep.errors.append(
                    f"content/locations/{loc_id}/location.yaml: {variant}: файла {path} нет "
                    f"в game/assets — прогоните vn assets build"
                )
                continue
            out.append(f'image bg {loc_id} {variant} = "{path}"')
            n_bg += 1
    if n_bg:
        out.append("")

    # ── CG-стиллы (ADR-0006): скан собранной зоны, image cg <...> ────────────
    # Реестр — от фактических выходов конвейера (как sprite_tree): CG не имеют
    # своей декларации, их источник истины — assets_src/png/cg + провенанс.
    cg_root = assets / "cg"
    n_cg = 0
    if cg_root.is_dir():
        for f in sorted(cg_root.rglob("*.webp")):
            rel = "cg/" + f.relative_to(cg_root).as_posix()
            tokens = " ".join(rel[:-len(".webp")].split("/"))
            out.append(f'image {tokens} = "assets/{rel}"')
            n_cg += 1
    if n_cg:
        out.append("")

    # ── Видео-лупы (ADR-0006): image mov <...> = Movie(...) из meta.json ─────
    from ..assets.video import movie_tree

    n_mov = 0
    for rel, meta in sorted(movie_tree(root).items()):
        tokens = " ".join(rel[:-len(".webm")].split("/"))
        loop = bool(meta.get("loop", True))
        out.append(f'image {tokens} = Movie(play="assets/{rel}", loop={loop})')
        n_mov += 1
    if n_mov:
        out.append("")

    # ── layeredimage персонажей из matrix + собранных слоёв (G11) ────────────
    tree = sprite_tree(root)
    tagged: list[str] = []
    for rel, doc in sorted(char_docs):
        char_id = doc["id"]
        matrix = doc.get("matrix")
        poses_files = tree.get(char_id, {})
        if not matrix:
            if poses_files:
                rep.warnings.append(
                    f"{rel}: спрайты собраны, но в character.yaml нет блока matrix — "
                    f"layeredimage не эмитится"
                )
            continue
        if not poses_files:
            rep.warnings.append(
                f"{rel}: объявлен matrix, но в game/assets/spr/{char_id}/ пусто — "
                f"layeredimage не эмитится (статика появится после vn assets build)"
            )
            continue

        # Дизъюнктность имён групп: одинаковый токен в двух группах ломает гейтинг.
        names = [set(matrix["poses"]), set(matrix["outfits"]), set(matrix["emotions"])]
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                for clash in sorted(a & b):
                    rep.errors.append(
                        f"{rel}: имя {clash!r} используется в двух группах matrix — "
                        f"атрибуты layeredimage обязаны быть уникальны между группами"
                    )

        # Валидация: required-комбинации обязаны существовать в собранных слоях.
        for req in matrix.get("required", []):
            pose = req["pose"]
            have = poses_files.get(pose)
            if have is None or not have["base"]:
                rep.errors.append(f"{rel}: matrix.required: нет base для позы {pose!r}")
                continue
            for outfit in req.get("outfits", []):
                if outfit not in have["outfits"]:
                    rep.errors.append(
                        f"{rel}: matrix.required: нет слоя outfits/{outfit} для позы {pose!r}"
                    )
            for emotion in req.get("emotions", []):
                if emotion not in have["faces"]:
                    rep.errors.append(
                        f"{rel}: matrix.required: нет слоя faces/{emotion} для позы {pose!r}"
                    )
        # forbidden-комбинации ОБЯЗАНЫ отсутствовать в собранных слоях — иначе
        # запрещённый арт молча уезжает в layeredimage (смысл декларации).
        for forb in matrix.get("forbidden", []):
            pose = forb["pose"]
            have = poses_files.get(pose, {"outfits": [], "faces": []})
            for outfit in forb.get("outfits", []):
                if outfit in have["outfits"]:
                    rep.errors.append(
                        f"{rel}: matrix.forbidden: слой outfits/{outfit} для позы {pose!r} "
                        f"собран, но комбинация запрещена — удалите арт или декларацию"
                    )
            for emotion in forb.get("emotions", []):
                if emotion in have["faces"]:
                    rep.errors.append(
                        f"{rel}: matrix.forbidden: слой faces/{emotion} для позы {pose!r} "
                        f"собран, но комбинация запрещена — удалите арт или декларацию"
                    )

        # Слои вне matrix — предупреждение (осиротевший арт).
        for pose, have in poses_files.items():
            if pose not in matrix["poses"]:
                rep.warnings.append(f"{rel}: поза {pose!r} есть в assets, но не в matrix")
                continue
            for o in have["outfits"]:
                if o not in matrix["outfits"]:
                    rep.warnings.append(f"{rel}: outfits/{o} ({pose}) вне matrix")
            for e in have["faces"]:
                if e not in matrix["emotions"]:
                    rep.warnings.append(f"{rel}: faces/{e} ({pose}) вне matrix")
            if have["overlays"]:
                rep.warnings.append(
                    f"{rel}: overlays ({pose}) собраны, но эмиссия overlay-группы "
                    f"появится позже — сейчас мёртвый груз в дистрибутиве"
                )

        # Поза без base не эмитится: always-слой ссылался бы в пустоту (рантайм-краш).
        poses = []
        for p in matrix["poses"]:
            if p not in poses_files:
                continue
            if not poses_files[p]["base"]:
                rep.errors.append(f"{rel}: у позы {p!r} нет base@2.webp — поза не собрана")
                continue
            poses.append(p)
        if not poses:
            rep.errors.append(f"{rel}: ни одна поза из matrix не собрана в assets")
            continue

        lines = [f"layeredimage {char_id}:"]
        lines.append("    group pose:")
        for i, pose in enumerate(poses):
            default = " default" if i == 0 else ""
            lines.append(f"        attribute {pose}{default} Null()")
        lines.append("")
        for pose in poses:
            lines.append(
                f'    always "assets/spr/{char_id}/{pose}/base@2.webp" if_any ["{pose}"]'
            )
        for group, mkey in (("outfit", "outfits"), ("face", "emotions")):
            gdir = "outfits" if group == "outfit" else "faces"
            declared = matrix[mkey]
            lines.append("")
            lines.append(f"    group {group}:")
            emitted_any = False
            default_pending = True        # default — первому РЕАЛЬНО собранному имени
            for name in declared:
                for pose in poses:
                    if name in poses_files[pose][gdir]:
                        default = " default" if default_pending else ""
                        default_pending = False
                        lines.append(
                            f'        attribute {name}{default} '
                            f'"assets/spr/{char_id}/{pose}/{gdir}/{name}@2.webp" '
                            f'if_any ["{pose}"]'
                        )
                        emitted_any = True
            if emitted_any and declared and not any(
                declared[0] in poses_files[p][gdir] for p in poses
            ):
                rep.warnings.append(
                    f"{rel}: {gdir}/{declared[0]} объявлен первым, но не собран — "
                    f"default достался {gdir} следующему собранному имени"
                )
            if not emitted_any:
                lines.pop()               # пустая группа не эмитится
                lines.pop()
        out.append("\n".join(lines))
        out.append("")
        tagged.append(char_id)

    # ── Привязка тегов к слою sprites: camera sprites тонирует всех (G11) ────
    if tagged:
        mapping = ", ".join(f'"{t}": "sprites"' for t in tagged)
        out.append("# Тонировка: matrixcolor-профиль локации применяется camera sprites (раздел 4)")
        out.append(f"define config.tag_layer = {{{mapping}}}")
    else:
        out.append("# Образы не объявлены: нет локаций с фонами и персонажей со спрайтами.")
    return "\n".join(out) + "\n"
