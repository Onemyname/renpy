"""PSD-нарезка (раздел 2): боевой путь художника. PSD режется по конвенции слоёв
в то же PNG-дерево, что и прямые PNG-источники (открытый промежуточный формат),
дальше — общие трансформации pipeline.py.

Конвенция слоёв PSD (assets_src/psd/characters/<key>/<key>_<pose>.psd):
  base                — пиксельный слой: тело/поза
  outfits/<outfit>    — группа outfits, в ней слой на каждый наряд
  faces/<emotion>     — группа faces, в ней слой на каждую эмоцию
  overlays/<name>     — группа overlays (опционально)
Каждый слой экспортируется на полном холсте PSD (позиция слоя сохраняется).

Нарезка идёт в staging .vncache/psd_png/characters/<key>/<pose>/ — та же конвенция,
что и у ручного PNG-экспорта, но БЕЗ записи в source-зону assets_src (она принадлежит
художнику и git-манифестам). Конфликт «PSD и ручной PNG на один выход» ловится в
pipeline.py (два источника на один выход).
"""

from __future__ import annotations

import re
from pathlib import Path

from .pipeline import SLUG_RE, AssetBuildResult

PSD_NAME_RE = re.compile(r"^(?P<key>[a-z][a-z0-9_]{1,23})_(?P<pose>[a-z][a-z0-9_]*)\.psd$")


def _export_layer(psd, layer, dest: Path, rep: AssetBuildResult, rel: str):
    """Слой -> PNG на полном холсте PSD (позиция сохраняется).

    КОНВЕНЦИЯ ВИДИМОСТИ: экспортируются ВСЕ слои конвенционных групп независимо от
    флага видимости — видимость в рабочем PSD отражает состояние работы художника,
    а не состав ассетов (psd-tools по умолчанию фильтрует is_visible и молча дал бы
    прозрачные PNG для скрытых нарядов/эмоций)."""
    from PIL import Image

    canvas = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
    pil = layer.composite(layer_filter=lambda l: True)
    if pil is not None:
        canvas.paste(pil, (layer.left, layer.top), pil.convert("RGBA"))
    if canvas.getbbox() is None:
        rep.warnings.append(f"{rel}: слой {dest.stem!r} полностью прозрачный — пустой арт?")
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG")


def slice_psd(psd_path: Path, out_pose_dir: Path, rep: AssetBuildResult) -> None:
    import shutil

    from psd_tools import PSDImage

    rel = psd_path.name
    try:
        psd = PSDImage.open(psd_path)
    except (OSError, ValueError) as e:
        # Файл залочен/дописывается (Photoshop, антивирус) — ошибка, не трейсбек;
        # watch-цикл пересоберёт следующим тиком.
        rep.errors.append(f"{rel}: не читается: {e}")
        return
    top = {layer.name: layer for layer in psd}

    # Staging чистится целиком перед нарезкой (G13): переименованный/удалённый слой
    # не должен переживать пересборку устаревшим PNG.
    if out_pose_dir.is_dir():
        shutil.rmtree(out_pose_dir)

    base = top.get("base")
    if base is None or base.is_group():
        rep.errors.append(f"{rel}: нет пиксельного слоя 'base' на верхнем уровне (конвенция PSD)")
        return
    _export_layer(psd, base, out_pose_dir / "base.png", rep, rel)

    for group_name in ("outfits", "faces", "overlays"):
        group = top.get(group_name)
        if group is None:
            if group_name != "overlays":
                rep.warnings.append(f"{rel}: нет группы '{group_name}'")
            continue
        if not group.is_group():
            rep.errors.append(f"{rel}: '{group_name}' должен быть группой слоёв")
            continue
        for layer in group:
            if not SLUG_RE.match(layer.name):
                rep.errors.append(
                    f"{rel}: слой {group_name}/{layer.name!r} вне конвенции ^[a-z][a-z0-9_]*$"
                )
                continue
            _export_layer(psd, layer, out_pose_dir / group_name / f"{layer.name}.png", rep, rel)


def slice_all_psd(root: Path, rep: AssetBuildResult) -> None:
    """Нарезка всех PSD персонажей в staging PNG-дерево. Инкрементальность обеспечивает
    общий кэш трансформаций (нарезка дешёвая относительно энкода; послойный кэш — при
    первых боевых PSD, G13). Staging-каталоги без соответствующего PSD удаляются —
    удалённый PSD не должен вечно жить устаревшими источниками."""
    import shutil

    staging = root / ".vncache" / "psd_png" / "characters"
    expected: set[Path] = set()
    psd_root = root / "assets_src" / "psd" / "characters"
    if psd_root.is_dir():
        for key_dir in sorted(p for p in psd_root.iterdir() if p.is_dir()):
            for psd_file in sorted(key_dir.glob("*.psd")):
                m = PSD_NAME_RE.match(psd_file.name)
                if not m:
                    rep.errors.append(
                        f"assets_src/psd/characters/{key_dir.name}/{psd_file.name}: "
                        f"имя вне конвенции <key>_<pose>.psd"
                    )
                    continue
                if m.group("key") != key_dir.name:
                    rep.errors.append(
                        f"{psd_file.name}: key {m.group('key')!r} != имени папки {key_dir.name!r}"
                    )
                    continue
                out_dir = staging / m.group("key") / m.group("pose")
                expected.add(out_dir)
                slice_psd(psd_file, out_dir, rep)

    if staging.is_dir():
        for key_dir in sorted(p for p in staging.iterdir() if p.is_dir()):
            for pose_dir in sorted(p for p in key_dir.iterdir() if p.is_dir()):
                if pose_dir not in expected:
                    shutil.rmtree(pose_dir)
            if not any(key_dir.iterdir()):
                key_dir.rmdir()
