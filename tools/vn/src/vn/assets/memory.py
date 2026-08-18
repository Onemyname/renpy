"""Модель памяти образов Ren'Py и worst-case по сценам (ADR-0012).

Зачем. Размер дистрибутива — вопрос диска и решается одним числом в бюджете.
Настоящий потолок производства другой: КЭШ ДЕКОДИРОВАННЫХ ОБРАЗОВ. Он ограничен
`config.image_cache_size_mb`, и при переполнении Ren'Py не падает — он перестаёт
предзагружать и начинает перерасшифровывать образы посреди сцены. Игрок видит
необъяснимые фризы, а сборка при этом зелёная. Поэтому worst-case считается здесь
и гейтится наравне с размерными бюджетами.

Формулы — из движка (renpy/display/im.py, см. imaging.py):
  лимит кэша (пиксели) = image_cache_size_mb * 1024 * 1024 // 4
  стоимость образа     = bbox_непрозрачного(+8 px) * 1.34

Стоимость каждого выхода посчитана один раз на сборке и лежит в манифесте
(`cost_px`), поэтому отчёт не декодирует тысячи файлов заново.

Что считается сценой (модель, а не догадка):
    фон локации  +  Σ по участникам (base + самый тяжёлый outfit + самая тяжёлая face)
    + самый тяжёлый послойный шот сцены (env + худший вариант каждого слоя, shots@1)
Плюс запас на UI. Это верхняя граница того, что одновременно живёт в кэше при
показе сцены. Оверсэмпл учитывается честно: на 4K-экране движок грузит `@2`,
поэтому worst-case считается для КРУПНЕЙШЕГО отгружаемого варианта.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .render_config import RenderConfig, load_render_config

# Запас на UI-панели, текстбокс, скриншот сейва и прочее, что живёт в кэше
# одновременно со сценой. Меряется в пикселях экрана.
UI_RESERVE_SCREENS = 1.5


@dataclass
class SceneCost:
    scene_id: str
    px: int
    parts: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class MemoryReport:
    scale: int = 1
    limit_px: int = 0
    budget_px: int = 0
    scenes: list[SceneCost] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def worst(self) -> SceneCost | None:
        return max(self.scenes, key=lambda s: s.px) if self.scenes else None


def load_costs(root: Path) -> dict[str, int]:
    """{выход относительно game/assets: стоимость в пикселях кэша}."""
    mf = root / ".vncache" / "assets-manifest.json"
    if not mf.is_file():
        return {}
    try:
        outputs = json.loads(mf.read_text(encoding="utf-8"))["outputs"]
    except Exception:
        return {}
    return {k: int(v["cost_px"]) for k, v in outputs.items() if "cost_px" in v}


def _cost_of(costs: dict[str, int], logical: str, scale: int) -> int:
    """Стоимость логического ассета на заданном масштабе: сначала вариант @scale,
    иначе референсный (движок откатится на него, если крупного варианта нет)."""
    for ext in (".webp", ".png", ".jpg"):
        if scale > 1 and (key := f"{logical}@{scale}{ext}") in costs:
            return costs[key]
    for ext in (".webp", ".png", ".jpg"):
        if (key := f"{logical}{ext}") in costs:
            return costs[key]
    return 0


def _shot_cost(costs: dict[str, int], chapter_id: str, scene_short: str,
               shots_doc: dict, scale: int) -> tuple[int, str]:
    """Худший послойный шот сцены: env + самый тяжёлый вариант каждого слоя.
    Одновременно показывается один шот, но кэш держит его целиком."""
    worst, worst_id = 0, ""
    for shot_id, spec in (shots_doc.get("shots") or {}).items():
        total = 0
        for layer, lspec in (spec.get("layers") or {}).items():
            base = f"shots/{chapter_id}/{scene_short}/{shot_id}/{layer}"
            variants = lspec.get("variants") or []
            if variants:
                total += max(_cost_of(costs, f"{base}__{v}", scale) for v in variants)
            else:
                total += _cost_of(costs, base, scale)
        if total > worst:
            worst, worst_id = total, shot_id
    return worst, worst_id


SPR_PREFIX = "spr/"
# Группы слоёв позы: spr/<char>/<pose>/base + <pose>/outfits/<name> + <pose>/faces/<name>
CHAR_GROUPS = ("base", "outfits", "faces")


def _character_index(costs: dict[str, int], scale: int) -> dict[str, tuple[int, str]]:
    """{персонаж: (худшая поза в пикселях, её имя)} — ОДНИМ проходом по манифесту.

    Худшая поза = base + самый тяжёлый наряд + самая тяжёлая эмоция.

    Почему предындексация, а не расчёт по требованию: стоимость персонажа от сцены
    не зависит, а участников у сцен тысячи. Расчёт «на каждого участника каждой
    сцены» перебирал бы весь манифест заново, то есть стоил бы ПРОИЗВЕДЕНИЕ
    «сцены × участники × выходы» — на корпусе 2000 сцен и 2000 образов это
    ~20 млн итераций и секунды на ровном месте (7.6 ARCHITECTURE.md). Здесь —
    один проход и словарь, дальше стоимость берётся lookup'ом.
    """
    # {масштаб: {персонаж: {поза: {группа: [стоимости]}}}}. Масштабов держим два:
    # запрошенный и референсный — на референсный движок откатывается, если крупного
    # варианта у персонажа нет вовсе. Остальные в модель не входят: они не грузятся.
    scales = (scale, 1) if scale > 1 else (1,)
    tree: dict[int, dict[str, dict[str, dict[str, list[int]]]]] = {s: {} for s in scales}
    for key, px in costs.items():
        if not key.startswith(SPR_PREFIX):
            continue
        parts = key[len(SPR_PREFIX):].split("/")
        if len(parts) == 3:                   # <char>/<pose>/base[@N].ext
            char, pose, leaf = parts
            group = "base"
        elif len(parts) == 4:                 # <char>/<pose>/<group>/<name>[@N].ext
            char, pose, group, leaf = parts
        else:
            continue
        stem = leaf.rsplit(".", 1)[0]
        want_scale = int(stem.split("@")[1]) if "@" in stem else 1
        if want_scale not in tree:
            continue
        poses = tree[want_scale].setdefault(char, {})
        # Поза заводится и при незнакомой группе: она реально существует, просто
        # ничего не стоит, — иначе персонаж «без спрайтов» и персонаж с одними
        # незнакомыми группами перестали бы различаться.
        groups = poses.setdefault(pose, {g: [] for g in CHAR_GROUPS})
        if group in groups:
            groups[group].append(px)

    index: dict[str, tuple[int, str]] = {}
    for want_scale in scales:                 # запрошенный масштаб идёт первым
        for char, poses in tree[want_scale].items():
            if char in index:
                continue                      # референсный вариант — только откат
            worst, worst_pose = 0, ""
            for pose, groups in poses.items():
                total = sum(max(groups[g], default=0) for g in CHAR_GROUPS)
                if total > worst:
                    worst, worst_pose = total, pose
            index[char] = (worst, worst_pose)
    return index


def analyze(root: Path, cfg: RenderConfig | None = None,
            scale: int | None = None) -> MemoryReport:
    """Worst-case по каждой сцене для заданного масштаба (по умолчанию — крупнейший
    отгружаемый: именно он грузится у игрока на 4K-мониторе)."""
    from ..repo import load_yaml

    cfg = cfg or load_render_config(root)
    if scale is None:
        scale = max(cfg.cls("bg").scales + cfg.cls("spr").scales)
    rep = MemoryReport(scale=scale, limit_px=cfg.cache_limit_px,
                       budget_px=cfg.scene_budget_px)
    costs = load_costs(root)
    if not costs:
        rep.warnings.append(
            "модель памяти: манифест сборки пуст — соберите vn assets build")
        return rep

    # Всё, что не зависит от сцены, считается ДО цикла по сценам: и стоимость
    # персонажа, и раскладка локаций. Иначе стоимость отчёта — произведение
    # «сцены × выходы манифеста», а не сумма (замеры — 7.6 ARCHITECTURE.md).
    char_index = _character_index(costs, scale)

    # Локации: <loc>/<variant> -> логический путь ассета
    locations: dict[str, dict[str, str]] = {}
    loc_dir = root / "content" / "locations"
    if loc_dir.is_dir():
        for d in sorted(p for p in loc_dir.iterdir() if p.is_dir()):
            f = d / "location.yaml"
            if not f.is_file():
                continue
            try:
                doc = load_yaml(f) or {}
            except Exception:
                continue
            variants = {}
            for var, path in (doc.get("backgrounds") or {}).items():
                logical = str(path)
                if logical.startswith("assets/"):
                    logical = logical[len("assets/"):]
                variants[var] = logical.rsplit(".", 1)[0]
            locations[doc.get("id", d.name)] = variants

    ui_reserve = int(cfg.screen[0] * cfg.screen[1] * UI_RESERVE_SCREENS * 1.34)

    zones = [root / "content" / "chapters"]
    if (root / "packs").is_dir():
        zones += sorted((root / "packs").glob("*/chapters"))
    for chapters in zones:
        if not chapters.is_dir():
            continue
        for ch_dir in sorted(p for p in chapters.iterdir() if p.is_dir()):
            ch_id = ch_dir.name[:4]
            # Декларации послойных шотов главы: короткий id сцены -> документ
            shots_by_scene: dict[str, dict] = {}
            for shf in sorted((ch_dir / "shots").glob("*.shots.yaml")) \
                    if (ch_dir / "shots").is_dir() else []:
                try:
                    sdoc = load_yaml(shf) or {}
                except Exception:
                    continue
                if sdoc.get("scene"):
                    shots_by_scene[sdoc["scene"]] = sdoc
            for sf in sorted((ch_dir / "scenes").glob("*.scene.yaml")) \
                    if (ch_dir / "scenes").is_dir() else []:
                try:
                    meta = load_yaml(sf) or {}
                except Exception:
                    continue
                short = meta.get("id", sf.stem)
                sid = f"{ch_id}_{short}"
                parts: list[tuple[str, int]] = []
                total = ui_reserve
                parts.append(("ui+текстбокс", ui_reserve))
                loc = meta.get("location")
                if loc and "/" in loc:
                    loc_id, variant = loc.split("/", 1)
                    logical = locations.get(loc_id, {}).get(variant)
                    if logical:
                        c = _cost_of(costs, logical, scale)
                        total += c
                        parts.append((f"bg {loc}", c))
                for char in (meta.get("participants") or []):
                    c, pose = char_index.get(char, (0, ""))
                    total += c
                    parts.append((f"{char} ({pose or 'нет спрайтов'})", c))
                if short in shots_by_scene:
                    c, shot_id = _shot_cost(costs, ch_id, short,
                                            shots_by_scene[short], scale)
                    if c:
                        total += c
                        parts.append((f"shot {shot_id}", c))
                rep.scenes.append(SceneCost(sid, total, parts))

    for sc in rep.scenes:
        if sc.px > rep.budget_px:
            rep.errors.append(
                f"{sc.scene_id}: сцена стоит {sc.px / 1e6:.1f} Мпикс кэша при бюджете "
                f"{rep.budget_px / 1e6:.1f} Мпикс (масштаб @{scale}) — движок начнёт "
                f"вытеснять и перерасшифровывать образы: фризы посреди сцены. "
                f"Поднимите render.image_cache_mb или облегчите сцену")
        elif sc.px > rep.budget_px * 0.8:
            rep.warnings.append(
                f"{sc.scene_id}: {sc.px / 1e6:.1f} Мпикс — 80 % бюджета сцены "
                f"({rep.budget_px / 1e6:.1f} Мпикс, масштаб @{scale})")
    return rep


def recommended_cache_mb(rep: MemoryReport, generations: int) -> int:
    """Какой image_cache_mb нужен, чтобы худшая сцена умещалась `generations` раз."""
    worst = rep.worst
    if worst is None:
        return 0
    need_px = worst.px * generations
    return int((need_px * 4) // (1024 * 1024)) + 1
