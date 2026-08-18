"""Реестр образов (разделы 1.2/4): компилятор эмитит ЯВНЫЕ image-стейтменты и
layeredimage — автоопределение по game/images/ не используется (тихие коллизии имён).

Канон эмиттера layeredimage (G11): селекторные группы `attribute X default Null()`,
гейтинг слоёв только if_any, каждый attribute с явным displayable, пути с префиксом
"assets/". Тонировка — сгенерированный config.tag_layer + camera sprites.

Оверсэмпл (ADR-0012). Ссылаемся ВСЕГДА на референсный (безсуффиксный) вариант.
Ren'Py сам подберёт `<base>@2`/`@4`, если физический экран крупнее виртуального
(renpy/display/im.py: get_oversampled_image), и делает это только для имени без
собственного `@N`. Захардкоженный `@2` в ссылке отключал бы автоподбор и заставлял
игрока на 1080p грузить вчетверо более тяжёлую текстуру, чем он способен увидеть.
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


SIDE_DIR_TOKEN = "side"

# Образы, объявленные рукописным framework (game/framework/20_ui/images.rpy), а не
# компилятором. Список короткий и ведётся вручную осознанно: разбирать .rpy регексом
# запрещено (G24), а гонять build-bridge ради двух служебных имён — дороже пользы.
FRAMEWORK_IMAGE_TAGS = frozenset({"vn_black"})


@dataclass
class ImageIndex:
    """Что игра сможет показать после сборки — в форме, пригодной для сверки
    ссылок `show`/`scene`/`hide` из авторских сцен (ADR-0012, раздел 3.9).

    exact     — полные имена образов (bg/cg/mov/side): кортеж токенов.
    tags      — первые токены всех известных образов (для `hide <tag>`).
    layered   — layeredimage: {tag: множество допустимых атрибутов}.
    available — был ли вообще собран game/assets. Без собранной зоны индекс пуст
                и сверка ссылок не имеет смысла (всё было бы «не существует»).
    """

    exact: set[tuple[str, ...]] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    layered: dict[str, set[str]] = field(default_factory=dict)
    available: bool = False


def shot_tag(chapter_id: str, scene_short: str) -> str:
    """Тег layeredimage послойных шотов сцены: один тег на сцену (ADR-0013).
    Смена шота = смена атрибута группы shot: движок сам снимает предыдущий
    (групповая эксклюзивность), а выбранные варианты слоёв (наряд) ПЕРЕЖИВАЮТ
    смену шота — атрибуты тега липкие."""
    return f"shot_{chapter_id}_{scene_short}"


def _shot_attrs(doc: dict) -> set[str]:
    """Все атрибуты layeredimage шотов сцены: id шотов + <layer>_auto/<layer>_<variant>."""
    attrs: set[str] = set()
    for shot_id, spec in (doc.get("shots") or {}).items():
        attrs.add(shot_id)
        for layer, lspec in (spec.get("layers") or {}).items():
            for v in (lspec.get("variants") or []):
                attrs.add(f"{layer}_{v}")
            if lspec.get("var"):
                attrs.add(f"{layer}_auto")
    return attrs


def build_image_index(root: Path, locations: dict[str, dict],
                      char_docs: list[tuple[str, dict]],
                      shots_docs: list[tuple[str, str, dict]] | None = None) -> ImageIndex:
    """Индекс образов из ТЕХ ЖЕ источников, что и emit_images: декларации локаций,
    собранные деревья спрайтов/CG/видео/портретов и matrix персонажей.

    Отдельный проход (а не побочный эффект эмиссии) нужен потому, что сверка ссылок
    идёт на этапе валидации сцен — до того, как образы эмитятся."""
    from ..assets.pipeline import side_tree, sprite_tree, variant_scale
    from ..assets.video import movie_tree

    idx = ImageIndex(available=(root / "game" / "assets").is_dir())
    idx.tags |= FRAMEWORK_IMAGE_TAGS
    idx.exact |= {(t,) for t in FRAMEWORK_IMAGE_TAGS}

    for loc_id, meta in locations.items():
        for variant in (meta.get("backgrounds") or {}):
            idx.exact.add(("bg", loc_id, variant))
    if locations:
        idx.tags.add("bg")

    cg_root = root / "game" / "assets" / "cg"
    if cg_root.is_dir():
        for f in sorted(cg_root.rglob("*")):
            if not f.is_file() or f.suffix not in (".webp", ".png", ".jpg"):
                continue
            if f.stem.endswith(".thumb") or variant_scale(f.stem) != 1:
                continue
            rel = "cg/" + f.relative_to(cg_root).as_posix()
            idx.exact.add(tuple(rel[: -len(f.suffix)].split("/")))
        idx.tags.add("cg")

    for rel in movie_tree(root):
        idx.exact.add(tuple(rel[: -len(".webm")].split("/")))
        idx.tags.add("mov")

    for char_id, names in side_tree(root).items():
        for name in names:
            idx.exact.add(("side", char_id) if name == "base" else ("side", char_id, name))
        idx.tags.add("side")

    # layeredimage: допустимые атрибуты — пересечение matrix и фактически собранных
    # слоёв, ровно как в emit_images (несобранное имя атрибутом не станет).
    tree = sprite_tree(root)
    for _rel, doc in char_docs:
        char_id = doc["id"]
        matrix = doc.get("matrix")
        poses_files = tree.get(char_id, {})
        if not matrix or not poses_files:
            continue
        attrs: set[str] = set()
        for pose, have in poses_files.items():
            if pose not in matrix["poses"] or not have["base"]:
                continue
            attrs.add(pose)
            for group_key, gdir in (("outfits", "outfits"), ("emotions", "faces"),
                                    ("overlays", "overlays")):
                declared = matrix.get(group_key) or []
                attrs |= {n for n in have[gdir] if n in declared}
        if attrs:
            idx.layered[char_id] = attrs
            idx.tags.add(char_id)

    # Послойные шоты (shots@1): атрибуты — из деклараций. Расхождение деклараций
    # с собранными слоями ловит эмиттер (ошибка сборки), поэтому индексу
    # пересечение с файловой системой не требуется.
    for chapter_id, _rel, doc in (shots_docs or []):
        tag = shot_tag(chapter_id, doc["scene"])
        idx.layered[tag] = _shot_attrs(doc)
        idx.tags.add(tag)
    return idx


def _spr_ext(root: Path, char_id: str, poses_files: dict) -> str:
    from ..assets.pipeline import asset_ext

    for pose in poses_files:
        return asset_ext(root, f"spr/{char_id}/{pose}/base")
    return ".webp"


def _emit_shots(root: Path, shots_docs: list[tuple[str, str, dict]],
                rep: ImagesReport) -> list[str]:
    """layeredimage на сцену из shots@1 (ADR-0013): нативная композиция вместо
    перехвата show у референсов-конкурентов.

    Канон эмиттера — G11, как у персонажей: селекторная группа shot
    (`attribute <id> default Null()`), слои гейтятся if_any по шоту, каждый
    attribute несёт явный displayable. Слой с `var:` получает атрибут
    <layer>_auto (default): ConditionSwitch выбирает вариант по переменной
    гардероба — rollback и смена посреди сцены работают штатно, предикция
    прогревает обе ветки (predict_all). Явные атрибуты <layer>_<variant>
    позволяют сценаристу переопределить выбор на конкретном шоте."""
    from ..assets.pipeline import SHOT_ENV, asset_ext, shot_tree

    out: list[str] = []
    tree = shot_tree(root)
    for chapter_id, rel, doc in sorted(shots_docs, key=lambda t: (t[0], t[2]["scene"])):
        scene_short = doc["scene"]
        tag = shot_tag(chapter_id, scene_short)
        built = (tree.get(chapter_id) or {}).get(scene_short) or {}
        shots = doc.get("shots") or {}

        lines = [f"layeredimage {tag}:"]
        lines.append("    group shot:")
        for i, shot_id in enumerate(shots):
            default = " default" if i == 0 else ""
            lines.append(f"        attribute {shot_id}{default} Null()")

        ok = True
        defaults_done: set[str] = set()    # группы, у которых default уже назначен
        for shot_id, spec in shots.items():
            built_layers = built.get(shot_id) or {}
            base = f"assets/shots/{chapter_id}/{scene_short}/{shot_id}"
            ext = asset_ext(root, f"shots/{chapter_id}/{scene_short}/{shot_id}/{SHOT_ENV}")
            layers = spec["layers"]
            # Слои, собранные конвейером, но не объявленные — осиротевший арт.
            for l, variants in sorted(built_layers.items()):
                if l not in layers:
                    rep.warnings.append(
                        f"{rel}: {shot_id}: слой {l} собран в game/assets, но не "
                        f"объявлен — в кадр не попадёт")
                    continue
                declared_v = set(layers[l].get("variants") or [])
                for v in variants:
                    if v and v not in declared_v:
                        rep.warnings.append(
                            f"{rel}: {shot_id}: вариант {l}__{v} собран, но не объявлен")

            lines.append("")
            lines.append(f"    # шот {shot_id}: z-порядок {', '.join(spec['order'])}")
            for layer in spec["order"]:
                lspec = layers[layer]
                variants = lspec.get("variants") or []
                have = set(built_layers.get(layer) or [])
                if not variants:
                    if "" not in have:
                        rep.errors.append(
                            f"{rel}: {shot_id}: слоя {layer} нет в собранных ассетах "
                            f"({base}/{layer}{ext}) — прогоните vn assets build")
                        ok = False
                        continue
                    lines.append(f'    always "{base}/{layer}{ext}" if_any ["{shot_id}"]')
                    continue
                missing = [v for v in variants if v not in have]
                if missing:
                    rep.errors.append(
                        f"{rel}: {shot_id}: у слоя {layer} не собраны варианты "
                        f"{', '.join(missing)} ({base}/{layer}__<вариант>{ext})")
                    ok = False
                    continue
                var = lspec.get("var")
                lines.append(f"    group {layer}:")
                if var:
                    default = "" if layer in defaults_done else " default"
                    defaults_done.add(layer)
                    # Первый вариант — ветка по умолчанию (значение вне списка =
                    # дефолт, а не пустой слой).
                    cond = []
                    for v in variants[1:]:
                        cond.append(f"\"{var} == '{v}'\"")
                        cond.append(f'"{base}/{layer}__{v}{ext}"')
                    cond += ['"True"', f'"{base}/{layer}__{variants[0]}{ext}"']
                    lines.append(
                        f"        attribute {layer}_auto{default} ConditionSwitch("
                        f"{', '.join(cond)}, predict_all=True) if_any [\"{shot_id}\"]")
                for j, v in enumerate(variants):
                    default = ""
                    if not var and j == 0 and layer not in defaults_done:
                        default = " default"
                        defaults_done.add(layer)
                    lines.append(
                        f'        attribute {layer}_{v}{default} '
                        f'"{base}/{layer}__{v}{ext}" if_any ["{shot_id}"]')
        if ok:
            out.append("\n".join(lines))
            out.append("")
    return out


# z-порядок слоёв персонажа: его задаёт эмиттер layeredimage, и лист арт-ревью
# (vn char sheet) обязан склеивать ячейки в том же порядке — иначе ревью смотрит не
# на то, что увидит игрок.
LAYER_ORDER = ("base", "outfits", "faces", "overlays")


def check_matrix(rel: str, doc: dict, poses_files: dict, rep) -> list[str]:
    """Контракт полноты матрицы персонажа: возвращает позы, пригодные к эмиссии.

    Один носитель контракта на двух потребителей: эмиттер layeredimage (здесь же) и
    `vn char validate`, который зовёт эту же функцию без сборки ассетов. Копия
    разошлась бы с оригиналом на первой правке — а расхождение здесь означает
    «сборка зелёная, а у игрока слой ссылается в пустоту».

    `poses_files` — срез собранных слоёв персонажа (`assets.pipeline.sprite_tree`),
    `rep` — любой отчёт с полями `errors`/`warnings`.
    """
    matrix = doc.get("matrix")
    char_id = doc["id"]
    if not matrix:
        if poses_files:
            rep.warnings.append(
                f"{rel}: спрайты собраны, но в character.yaml нет блока matrix — "
                f"layeredimage не эмитится"
            )
        return []
    if not poses_files:
        rep.warnings.append(
            f"{rel}: объявлен matrix, но в game/assets/spr/{char_id}/ пусто — "
            f"layeredimage не эмитится (статика появится после vn assets build)"
        )
        return []

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
        for o in have["overlays"]:
            if o not in (matrix.get("overlays") or []):
                rep.warnings.append(f"{rel}: overlays/{o} ({pose}) вне matrix")

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
    return poses


def emit_images(root: Path, locations: dict[str, dict],
                char_docs: list[tuple[str, dict]], rep: ImagesReport, header: str,
                shots_docs: list[tuple[str, str, dict]] | None = None) -> str:
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
    # своей декларации, их источник истины — зона мастеров + провенанс.
    from ..assets.pipeline import variant_scale

    cg_root = assets / "cg"
    n_cg = 0
    if cg_root.is_dir():
        for f in sorted(cg_root.rglob("*")):
            if not f.is_file() or f.suffix not in (".webp", ".png", ".jpg"):
                continue
            if f.stem.endswith(".thumb"):
                continue    # миниатюры галереи — не самостоятельные образы
            if variant_scale(f.stem) != 1:
                continue    # @2/@4 — варианты одного образа, движок берёт их сам
            rel = "cg/" + f.relative_to(cg_root).as_posix()
            tokens = " ".join(rel[: -len(f.suffix)].split("/"))
            out.append(f'image {tokens} = "assets/{rel}"')
            n_cg += 1
    if n_cg:
        out.append("")

    # ── Видео-лупы (ADR-0006): image mov <...> = Movie(...) из meta.json ─────
    from ..assets.video import movie_tree

    from ..assets.pipeline import POSTER_SUFFIX

    n_mov = 0
    for rel, meta in sorted(movie_tree(root).items()):
        tokens = " ".join(rel[:-len(".webm")].split("/"))
        loop = bool(meta.get("loop", True))
        # image= — кадр, который движок показывает, пока видео не заиграло, и на
        # платформах, где оно не играет вовсе. Без него там чёрная дыра в кадре.
        poster = rel[: -len(".webm")] + POSTER_SUFFIX
        args = f'play="assets/{rel}", loop={loop}'
        if (assets / poster).is_file():
            args += f', image="assets/{poster}"'
        else:
            rep.warnings.append(
                f"{rel}: нет постер-кадра {poster} — пока видео не заиграло, "
                f"в кадре будет пусто (пересоберите vn assets video build)")
        out.append(f"image {tokens} = Movie({args})")
        n_mov += 1
    if n_mov:
        out.append("")

    # ── Послойные шоты (shots@1, ADR-0013): layeredimage на сцену ────────────
    if shots_docs:
        out += _emit_shots(root, shots_docs, rep)

    # ── layeredimage персонажей из matrix + собранных слоёв (G11) ────────────
    tree = sprite_tree(root)
    tagged: list[str] = []
    for rel, doc in sorted(char_docs):
        char_id = doc["id"]
        matrix = doc.get("matrix")
        poses_files = tree.get(char_id, {})
        poses = check_matrix(rel, doc, poses_files, rep)
        if not poses:
            continue

        # Расширение референсного варианта: класс spr может отгружаться не в webp
        # (render.classes.spr.out_format) — путь обязан соответствовать факту.
        spr_ext = _spr_ext(root, char_id, poses_files)
        lines = [f"layeredimage {char_id}:"]
        lines.append("    group pose:")
        for i, pose in enumerate(poses):
            default = " default" if i == 0 else ""
            lines.append(f"        attribute {pose}{default} Null()")
        lines.append("")
        for pose in poses:
            lines.append(
                f'    always "assets/spr/{char_id}/{pose}/base{spr_ext}" if_any ["{pose}"]'
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
                            f'"assets/spr/{char_id}/{pose}/{gdir}/{name}{spr_ext}" '
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

        # Overlays — НЕЗАВИСИМЫЕ атрибуты, а не группа: слёзы, румянец и пот
        # сочетаются друг с другом, а группа допускает ровно один атрибут.
        # Раньше слой собирался, но не эмитился — мёртвый груз в дистрибутиве.
        overlay_lines = []
        for name in (matrix.get("overlays") or []):
            for pose in poses:
                if name in poses_files[pose]["overlays"]:
                    overlay_lines.append(
                        f'    attribute {name} '
                        f'"assets/spr/{char_id}/{pose}/overlays/{name}{spr_ext}" '
                        f'if_any ["{pose}"]'
                    )
        if overlay_lines:
            lines.append("")
            lines += overlay_lines
        out.append("\n".join(lines))
        out.append("")
        tagged.append(char_id)

    # ── Портреты say-окна (side images) ──────────────────────────────────────
    # Ren'Py ищет их как `side <tag> <атрибуты>`; base -> безатрибутный образ.
    # Ветка была объявлена в naming.md и не реализована — портрет собирался бы
    # в spr/<char>/side/, но игра его не видела.
    from ..assets.pipeline import side_tree

    n_side = 0
    for char_id, names in sorted(side_tree(root).items()):
        ext = _spr_ext(root, char_id, {SIDE_DIR_TOKEN: None})
        for name in names:
            tokens = f"side {char_id}" if name == "base" else f"side {char_id} {name}"
            out.append(f'image {tokens} = "assets/spr/{char_id}/side/{name}{ext}"')
            n_side += 1
    if n_side:
        out.append("")

    # ── Привязка тегов к слою sprites: camera sprites тонирует всех (G11) ────
    if tagged:
        mapping = ", ".join(f'"{t}": "sprites"' for t in tagged)
        out.append("# Тонировка: matrixcolor-профиль локации применяется camera sprites (раздел 4)")
        out.append(f"define config.tag_layer = {{{mapping}}}")
    else:
        out.append("# Образы не объявлены: нет локаций с фонами и персонажей со спрайтами.")
    return "\n".join(out) + "\n"
