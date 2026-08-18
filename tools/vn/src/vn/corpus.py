"""Синтетический корпус масштаба и измерительный прогон по нему (P1 аудита).

Зачем это существует. Все утверждения проекта о масштабе — «64 МБ генерата ≈
сотни глав», «конвейер линеен по числу сцен», «модель памяти удержит худшую
сцену» — до сих пор были МОДЕЛЬЮ: в репозитории одна демо-глава на три сцены, и
проверить их было нечем. Здесь строится настоящий проект нужного размера (валидные
по схемам декларации, настоящие мастера, настоящие авторские сцены) и по нему
гоняется настоящий конвейер с замером времени, памяти и объёма генерата. Вывод о
деградации делается по числам с конкретной машины, а не по рассуждению.

Где живёт корпус. Только в переданном каталоге (по умолчанию `.vncache/test-corpus`
— зона локальных артефактов, вне git). В сам репозиторий корпус не пишет ничего:
схемы и framework он КОПИРУЕТ из шаблонного корня, а собирает, компилирует и
кэширует исключительно у себя. Чужой каталог не трогается: генератор отказывается
писать в непустую папку без своего маркера, а очистка — удалять её.

Почему мастера крошечные. Корпус объявляет СВОЙ render-профиль с экраном 64x48
(как юнит-тесты, tests/helpers.py): те же ветки кода, те же валидации, но мастер —
128x96, а не 4K. Иначе прогон на 2000 сцен мерил бы скорость libwebp, а не
масштабируемость конвейера. Прямое следствие для отчёта: объём game/assets с
боевым профилем НЕ сопоставим (масштабируется площадью мастера), а объём
game/generated — сопоставим, он зависит от числа сцен и реплик, а не от пикселей.

Кэш образов корпуса выведен из боевого в тех же «экранах» (см. `_cache_mb`),
поэтому доли бюджета сцены у модели памяти остаются сопоставимыми с боевыми.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .assets.pipeline import SHOT_ENV

try:                                    # POSIX: единственный способ узнать пик RSS
    import resource                     # без внешних зависимостей (psutil нет)
except ImportError:                     # pragma: no cover — Windows
    resource = None                     # type: ignore[assignment]

# ru_maxrss измеряется в байтах на macOS и в килобайтах на Linux — иначе цифры
# памяти разошлись бы в 1024 раза между платформами (getrusage(2)).
_RSS_UNIT = 1 if sys.platform == "darwin" else 1024


class CorpusError(RuntimeError):
    pass


# ── Параметры корпуса ────────────────────────────────────────────────────────

# Виртуальный экран корпуса. Мелкий намеренно: конвейер обязан быть data-driven,
# и прогон масштаба не должен вырождаться в бенчмарк энкодера.
SCREEN = (64, 48)
# Мастер вдвое крупнее вёрстки: даёт и референсный вариант, и @2 (как боевой профиль).
MASTER_SCALE = 2
MASTER_SIZE = (SCREEN[0] * MASTER_SCALE, SCREEN[1] * MASTER_SCALE)

# Потолки id из схем: глава — ^ch\d{2}$, сцена — ^s\d{3}$. Корпус крупнее
# 99*999 сцен физически не выражается в наших id, и врать об этом нельзя.
MAX_CHAPTERS = 99
MAX_SCENES_PER_CHAPTER = 999
# Правдоподобный размер главы: масштаб набирается главами, а не одной гигантской.
SCENES_PER_CHAPTER = 50

# Раскладка мастеров по классам. Доли — профиль боевого корпуса VN: фонов немного
# (локации переиспользуются сценами), CG и спрайтов много, послойные шоты — самый
# дорогой класс и потому редкий. Остаток от округлений забирает CG: у него нет
# структурных требований (декларации, обязательные слои), поэтому только он может
# принять любое число мастеров и сохранить ТОЧНОЕ соблюдение масштаба.
IMAGE_MIX = {"bg": 0.2, "spr": 0.3, "shot": 0.1}
# Слои одной позы персонажа: base + наряды + эмоции (минимум для валидной matrix).
SPR_OUTFITS = 2
SPR_EMOTIONS = 2
LAYERS_PER_CHARACTER = 1 + SPR_OUTFITS + SPR_EMOTIONS
# Слои шота: обязательная непрозрачная подложка (её имя — конвенция конвейера,
# SHOT_ENV) + один вырезанный слой с альфой.
SHOT_LAYERS = (SHOT_ENV, "subject")
SHOT_ID = "main"
# Сколько CG кладём в один каталог: плоская папка на тысячу файлов — не то дерево,
# которое конвейер видит в бою (rglob по вложенности стоит иначе).
CG_PER_SET = 25
# Участников на сцену: столько спрайтов одновременно держит в кэше худшая сцена.
PARTICIPANTS_PER_SCENE = 2

# Видео-мастер: 1 c при 24 fps проходит валидацию собранного webm (длительность
# > 0.2 c, fps из SANE_FPS) и остаётся самым дешёвым, что можно закодировать.
VIDEO_SECONDS = 1
VIDEO_FPS = 24
VIDEO_GROUP = "loops"

# Пол image_cache_mb из схемы project@1 и запасное число поколений кэша, если
# шаблон его не объявил (дефолт render_config).
MIN_CACHE_MB = 16
DEFAULT_CACHE_GENERATIONS = 3

MARKER = ".vncorpus.json"
# Что копируется из шаблонного корня: схемы (без них нет ни корня, ни валидации)
# и framework вместе с gui/options — их грузит Ren'Py при вызове build-bridge.
TEMPLATE_TREES = ("tools/schemas", "game/framework")
TEMPLATE_FILES = ("game/gui.rpy", "game/options.rpy")
# Каталоги нормативного дерева (1.2), которые обязаны существовать даже пустыми
# (их отсутствие — ошибка lint), и которые не гарантирует ни копия шаблона
# (пустых каталогов в git не бывает), ни генерация: docs корпусу не нужен,
# characters не создаётся при нулевой доле спрайтов, 10_systems в шаблоне может
# оказаться пустым.
REQUIRED_EMPTY_DIRS = ("docs", "content/characters", "game/framework/10_systems")


@dataclass(frozen=True)
class CorpusSpec:
    """Масштаб корпуса. Всё, что влияет на генерат, — здесь: сравнение спеки с
    маркером решает, можно ли переиспользовать уже собранный корпус."""

    scenes: int = 100
    images: int = 100
    videos: int = 0
    lines: int = 8              # реплик (say) на сцену
    variables: int = 50         # объявленных сохраняемых переменных всего

    def validate(self) -> None:
        for name, value, low in (("scenes", self.scenes, 2), ("images", self.images, 1),
                                 ("videos", self.videos, 0), ("lines", self.lines, 1),
                                 ("variables", self.variables, 1)):
            if value < low:
                raise CorpusError(f"--{name} = {value}: минимум {low}")
        if self.scenes > MAX_CHAPTERS * MAX_SCENES_PER_CHAPTER:
            raise CorpusError(
                f"--scenes = {self.scenes}: потолок корпуса {MAX_CHAPTERS * MAX_SCENES_PER_CHAPTER} "
                f"сцен — id главы это ^ch\\d{{2}}$, id сцены ^s\\d{{3}}$ (схемы chapter@1/scene@1)")

    def label(self) -> str:
        base = f"{self.scenes} сцен / {self.images} образов"
        return base + (f" / {self.videos} видео" if self.videos else "")


@dataclass
class CorpusLayout:
    """Что фактически сгенерировано. Отдельно от спеки: спека — запрос, раскладка —
    факт (число глав, персонажей и шотов выводится из спеки, а не задаётся)."""

    chapters: int = 0
    scenes: int = 0
    locations: int = 0
    characters: int = 0
    cg: int = 0
    shots: int = 0
    videos: int = 0
    masters: int = 0            # файлов-мастеров всего (== spec.images)
    says: int = 0               # реплик всего
    variables: int = 0


@dataclass
class GenerateResult:
    layout: CorpusLayout
    written: list[str] = field(default_factory=list)
    unchanged: int = 0


def default_dest(root: Path) -> Path:
    """Каталог корпуса по умолчанию: .vncache/ — локальная зона вне git (.gitignore).

    Имя каталога = имя команды (`vn test corpus`), а не просто «corpus»: в той же
    зоне уже живут артефакты автопилота `vn save corpus` (.vncache/corpus). При
    совпадении имён генератор упирался в собственный отказ «каталог не пуст и не
    является корпусом» после каждого сейв-корпуса — то есть дефолт был нерабочим.
    Гард на разъезд имён — test_corpus.py::test_default_dest_does_not_collide."""
    return root / ".vncache" / "test-corpus"


# ── Раскладка масштаба ───────────────────────────────────────────────────────

def _chapter_sizes(scenes: int) -> list[int]:
    """Сцены по главам. Пока глав хватает — SCENES_PER_CHAPTER на главу; когда
    упираемся в потолок id главы, глава распухает (иначе корпус просто не выразим)."""
    chapters = math.ceil(scenes / SCENES_PER_CHAPTER)
    if chapters > MAX_CHAPTERS:
        chapters = MAX_CHAPTERS
    per = math.ceil(scenes / chapters)
    sizes = [per] * (scenes // per)
    if scenes % per:
        sizes.append(scenes % per)
    return sizes


@dataclass(frozen=True)
class _ImagePlan:
    """Сколько мастеров какого класса и сколько сущностей они образуют."""

    locations: int
    characters: int
    shots: int
    cg: int

    @property
    def masters(self) -> int:
        return (self.locations + self.characters * LAYERS_PER_CHARACTER
                + self.shots * len(SHOT_LAYERS) + self.cg)


def _image_plan(images: int, scenes: int) -> _ImagePlan:
    """Мастера -> сущности. Классы со структурными требованиями (персонаж = 5
    слоёв, шот = 2 слоя, шот принадлежит сцене) берут целое число сущностей,
    остаток забирает CG — так сумма мастеров ТОЧНО равна запрошенной."""
    locations = max(1, int(images * IMAGE_MIX["bg"]))
    characters = int(images * IMAGE_MIX["spr"]) // LAYERS_PER_CHARACTER
    shots = min(int(images * IMAGE_MIX["shot"]) // len(SHOT_LAYERS), scenes)
    cg = images - locations - characters * LAYERS_PER_CHARACTER - shots * len(SHOT_LAYERS)
    if cg < 0:
        raise CorpusError(
            f"--images = {images}: не хватает на раскладку классов "
            f"(нужно минимум {locations} фон + структурные классы)")
    return _ImagePlan(locations=locations, characters=characters, shots=shots, cg=cg)


def _plan(spec: CorpusSpec) -> tuple[list[int], _ImagePlan, list[int]]:
    """(сцены по главам, раскладка образов, переменные по главам)."""
    spec.validate()
    sizes = _chapter_sizes(spec.scenes)
    plan = _image_plan(spec.images, spec.scenes)
    # Одна переменная всегда глобальная (роут) — остальные раскладываются по
    # главам round-robin: сцена пишет переменную СВОЕЙ главы, и если главе
    # переменных не досталось, её сцены обходятся без записей в стор.
    per_chapter = [0] * len(sizes)
    for i in range(spec.variables - 1):
        per_chapter[i % len(sizes)] += 1
    return sizes, plan, per_chapter


def _scene_table(sizes: list[int]) -> list[tuple[int, int]]:
    """Плоский список сцен как (индекс главы, индекс сцены в главе)."""
    return [(ci, si) for ci, n in enumerate(sizes) for si in range(n)]


def _chapter_id(index: int) -> str:
    return f"ch{index + 1:02d}"


def _chapter_dir(index: int) -> str:
    return f"{_chapter_id(index)}_corpus{index + 1:02d}"


def _scene_id(index: int) -> str:
    return f"s{index + 1:03d}"


def _location_id(index: int) -> str:
    return f"loc_{index + 1:03d}"


def _character_id(index: int) -> str:
    return f"chr_{index + 1:03d}"


# ── Запись файлов ────────────────────────────────────────────────────────────

class _Writer:
    """Пишет только внутрь корпуса и только при фактическом изменении байтов.

    Идемпотентность здесь не косметика: повторный прогон не должен трогать mtime
    мастеров, иначе следующее измерение мерило бы холодную сборку вместо тёплой.
    Проверка «путь внутри dest» — предохранитель: ошибка в сборке относительного
    пути иначе означала бы запись в рабочий репозиторий."""

    def __init__(self, dest: Path):
        self.dest = dest.resolve()
        self.written: list[str] = []
        self.unchanged = 0

    def path(self, rel: str) -> Path:
        p = (self.dest / rel).resolve()
        if not p.is_relative_to(self.dest):
            raise CorpusError(f"путь {rel!r} ведёт за пределы корпуса {self.dest}")
        return p

    def write(self, rel: str, data: bytes) -> Path:
        p = self.path(rel)
        if p.is_file() and p.read_bytes() == data:
            self.unchanged += 1
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.written.append(rel)
        return p

    def write_text(self, rel: str, text: str) -> Path:
        return self.write(rel, text.encode("utf-8"))

    def write_yaml(self, rel: str, doc: dict, header: str = "") -> Path:
        body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        return self.write_text(rel, (header + body) if header else body)

    def mkdir(self, rel: str) -> None:
        self.path(rel).mkdir(parents=True, exist_ok=True)


_HEADER = ("# AUTO-GENERATED vn test corpus — синтетический корпус масштаба.\n"
           "# Это НЕ контент проекта: файл существует только ради измерений.\n")


# ── Мастера ──────────────────────────────────────────────────────────────────

def _master_png(index: int, alpha: bool) -> bytes:
    """Мастер MASTER_SIZE с содержимым, уникальным для index.

    Уникальность обязательна: кэш трансформаций контентно-адресуемый, и корпус из
    одинаковых картинок мерил бы дедупликацию, а не сборку. Индекс кладётся прямо
    в пиксели, поэтому уникальность гарантирована, а не «вероятна».

    alpha=True — реальная прозрачная рамка: класс spr/слои шота требуют альфу, и
    непрозрачный мастер конвейер обязан отбраковать."""
    import io

    from PIL import Image

    mode = "RGBA" if alpha else "RGB"
    base = (index * 37 % 256, index * 91 % 256, index * 53 % 256)
    im = Image.new(mode, MASTER_SIZE, base + ((255,) if alpha else ()))
    px = im.load()
    for i in range(4):                      # 4 байта индекса -> 4 пикселя
        byte = (index >> (8 * i)) & 0xFF
        px[i, 0] = (byte, byte, byte) + ((255,) if alpha else ())
    if alpha:
        edge = max(1, MASTER_SIZE[1] // 16)
        for x in range(MASTER_SIZE[0]):
            for y in range(MASTER_SIZE[1] - edge, MASTER_SIZE[1]):
                px[x, y] = (0, 0, 0, 0)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _video_master(dest: Path, index: int) -> None:
    """Видео-мастер через ffmpeg. Существующий файл не перекодируется: энкод —
    самая дорогая операция конвейера, и идемпотентность корпуса не должна стоить
    лишнего прогона ffmpeg."""
    if dest.is_file():
        return
    from .pipeline import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise CorpusError(
            "видео-мастера требуют ffmpeg, а он не найден (vn pipeline doctor): "
            "прогоняйте корпус без --videos либо поставьте ffmpeg")
    colour = f"0x{index * 37 % 256:02x}{index * 91 % 256:02x}{index * 53 % 256:02x}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"color=c={colour}:s={MASTER_SIZE[0]}x{MASTER_SIZE[1]}:r={VIDEO_FPS}",
           "-t", str(VIDEO_SECONDS), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.is_file():
        raise CorpusError(f"ffmpeg не сделал видео-мастер {dest.name}: "
                          f"{(proc.stderr or '').strip()[-400:]}")


# ── Генерация проекта ────────────────────────────────────────────────────────

def _cache_mb(render: dict) -> int:
    """image_cache_mb корпуса = боевой кэш, пересчитанный в «экранах».

    Копировать боевое число нельзя: 1024 МБ на экран 64x48 — это бесконечный кэш,
    и модель памяти на корпусе всегда показывала бы 0 % бюджета. Пересчёт в
    экранах сохраняет боевую пропорцию «сколько экранов образов влезает в кэш».

    ОГОВОРКА, которая обязана попасть в отчёт: схема project@1 держит пол
    image_cache_mb = 16 МБ, и для экрана 64x48 пропорциональное значение ниже
    этого пола. Значит доли бюджета сцены на корпусе занижены относительно боевых
    ровно во столько раз, во сколько пол выше пропорции. Масштабно-инвариантная
    величина, которую сравнивать с боем можно, — стоимость сцены В ЭКРАНАХ."""
    from .assets.render_config import DEFAULTS

    prod_screen = tuple(render.get("screen") or DEFAULTS["screen"])
    prod_mb = int(render.get("image_cache_mb") or DEFAULTS["image_cache_mb"])
    ratio = (SCREEN[0] * SCREEN[1]) / (prod_screen[0] * prod_screen[1])
    return max(MIN_CACHE_MB, round(prod_mb * ratio))


def _project_doc(template_root: Path) -> dict:
    """project.yaml корпуса: свой render-профиль, боевые бюджеты.

    Бюджеты берутся из шаблона намеренно: смысл прогона — узнать, где корпус
    упирается в ЗАЯВЛЕННЫЕ пределы (G19), а не в удобные."""
    template = yaml.safe_load((template_root / "project.yaml").read_text(encoding="utf-8"))
    render = template.get("render") or {}
    return {
        "schema": "project@1",
        "version": template["version"],
        # У корпуса нет истории сейвов, поэтому save_schema первая: цепочка
        # миграций обязана быть непрерывной (G5), а синтетические миграции
        # мерили бы python-импорт вместо конвейера.
        "save_schema": 1,
        "min_tools": template["min_tools"],
        "render": {
            "screen": list(SCREEN),
            "image_cache_mb": _cache_mb(render),
            "cache_generations": render.get("cache_generations",
                                            DEFAULT_CACHE_GENERATIONS),
            "classes": {
                "bg": {"variants": [1, MASTER_SCALE]},
                "cg": {"variants": [1, MASTER_SCALE]},
                "spr": {"master_scale": MASTER_SCALE, "variants": [1, MASTER_SCALE]},
                "shot": {"variants": [1, MASTER_SCALE]},
            },
        },
        "budgets": dict(template.get("budgets") or {}),
    }


def _copy_template(w: _Writer, template_root: Path) -> None:
    """Схемы и framework — из шаблонного корня. Копией, а не симлинком: Ren'Py
    пишет .rpyc рядом с .rpy, и симлинк означал бы запись в рабочий репозиторий."""
    for tree in TEMPLATE_TREES:
        base = template_root / tree
        if not base.is_dir():
            raise CorpusError(f"шаблонный корень {template_root} без {tree}/ — "
                              f"корпус не из чего собрать")
        for src in sorted(base.rglob("*")):
            # .rpyc — производные байткоды движка (G2): их место в корпусе займут
            # собственные, скомпилированные из скопированных исходников.
            if not src.is_file() or src.suffix in (".rpyc", ".rpymc"):
                continue
            w.write(f"{tree}/{src.relative_to(base).as_posix()}", src.read_bytes())
    for rel in TEMPLATE_FILES:
        src = template_root / rel
        if src.is_file():
            w.write(rel, src.read_bytes())
    for rel in REQUIRED_EMPTY_DIRS:
        w.mkdir(rel)


def _write_registries(w: _Writer, template_root: Path) -> None:
    """Безусловные входы компилятора и реестры G7 (REQUIRED_FILES линтера)."""
    w.write_yaml("project.yaml", _project_doc(template_root), _HEADER)
    w.write_yaml(".vnstorage.yaml", {
        "schema": "storage@1",
        # Хранилище синтетическое: корпус ничего не тянет и не пушит, но декларация
        # обязана существовать и быть валидной.
        "storages": {"default": {"type": "file", "path": "vn-assets-store"}},
    }, _HEADER)
    w.write_yaml("content/renames.yaml", {"schema": "renames@1"}, _HEADER)
    w.write_yaml("content/anchors.yaml", {"schema": "anchors@1", "anchors": []}, _HEADER)
    w.write_yaml("content/flags.yaml", {"schema": "flags@1", "flags": {}}, _HEADER)
    w.write_yaml("content/migrations/registry.yaml",
                 {"schema": "migrations_registry@1", "reserved": []}, _HEADER)
    # id_registry пустой: корпус ничего «не выпускал», поэтому G7-проверки
    # исчезнувших id на нём не срабатывают и не мешают измерению.
    w.write_text("content/registry/id_registry.json", json.dumps({
        "schema": "id_registry@1", "chapters": [], "scenes": [],
        "characters": [], "vars": [],
    }, ensure_ascii=False, indent=1) + "\n")


def _write_variables(w: _Writer, sizes: list[int], per_chapter: list[int]) -> None:
    w.write_yaml("content/variables/core.vars.yaml", {
        "schema": "vars@1", "store": "g",
        "vars": {"route": {"type": "str", "default": "prologue",
                           "doc": "Активный роут корпуса"}},
    }, _HEADER)
    for ci, count in enumerate(per_chapter):
        w.write_yaml(f"content/chapters/{_chapter_dir(ci)}/vars.yaml", {
            "schema": "vars@1", "store": _chapter_id(ci),
            "vars": {f"v_{i + 1:03d}": {"type": "bool", "default": False,
                                        "doc": "Синтетический флаг корпуса"}
                     for i in range(count)},
        }, _HEADER)


def _write_characters(w: _Writer, plan: _ImagePlan, first_master: int) -> int:
    """Персонажи: декларация + слои одной позы. Возвращает следующий индекс мастера."""
    index = first_master
    outfits = [f"out_{i + 1}" for i in range(SPR_OUTFITS)]
    emotions = [f"emo_{i + 1}" for i in range(SPR_EMOTIONS)]
    for ci in range(plan.characters):
        char = _character_id(ci)
        w.write_yaml(f"content/characters/{char}/character.yaml", {
            "schema": "character@1", "id": char, "name": f"Корпус {ci + 1}",
            "color": f"#{ci * 37 % 256:02x}7c4f",
            "canvas": list(MASTER_SIZE),
            "matrix": {"poses": ["a"], "outfits": outfits, "emotions": emotions,
                       "required": [{"pose": "a", "outfits": outfits,
                                     "emotions": emotions}]},
        }, _HEADER)
        pose = f"assets_src/art/characters/{char}/a"
        w.write(f"{pose}/base.png", _master_png(index, alpha=True))
        index += 1
        for name in outfits:
            w.write(f"{pose}/outfits/{name}.png", _master_png(index, alpha=True))
            index += 1
        for name in emotions:
            w.write(f"{pose}/faces/{name}.png", _master_png(index, alpha=True))
            index += 1
    return index


def _write_locations(w: _Writer, plan: _ImagePlan, first_master: int) -> int:
    index = first_master
    for li in range(plan.locations):
        loc = _location_id(li)
        w.write_yaml(f"content/locations/{loc}/location.yaml", {
            "schema": "location@1", "id": loc,
            "title_key": f"corpus.locations.{loc}.title",
            "backgrounds": {"day": f"assets/bg/{loc}/day.webp"},
        }, _HEADER)
        w.write(f"assets_src/art/backgrounds/{loc}/day.png",
                _master_png(index, alpha=False))
        index += 1
    return index


def _cg_logical(index: int) -> str:
    """Логический id CG: он же ссылка галереи, он же имя образа в генерате."""
    return f"cg/set_{index // CG_PER_SET + 1:03d}/cg_{index + 1:04d}"


def _write_cg(w: _Writer, plan: _ImagePlan, first_master: int) -> int:
    index = first_master
    for i in range(plan.cg):
        w.write(f"assets_src/art/{_cg_logical(i)}.png", _master_png(index, alpha=False))
        index += 1
    return index


def _write_gallery_and_strings(w: _Writer, sizes: list[int], plan: _ImagePlan,
                               table: list[tuple[int, int]]) -> None:
    """Галерея (ADR-0010) на весь CG и все шоты + строки UI под все title_key.

    Зачем это корпусу. Незаявленный в галерее CG и title_key без строки — это
    warning на КАЖДЫЙ образ и КАЖДУЮ главу: на тысяче образов прогон утонул бы в
    шуме вместо измерения. Заодно так честнее — в бою CG объявлены, и реестр
    галереи с ними растёт наравне с остальным генератом."""
    category = "cg"
    items: dict[str, dict] = {}
    strings: dict[str, str] = {
        f"corpus.gallery.cat.{category}.title": "Галерея корпуса",
    }
    for ci in range(len(sizes)):
        strings[f"corpus.chapters.{_chapter_id(ci)}.title"] = f"Глава {ci + 1}"
    for li in range(plan.locations):
        strings[f"corpus.locations.{_location_id(li)}.title"] = f"Локация {li + 1}"
    for i in range(plan.cg):
        gid = f"cg_{i + 1:04d}"
        items[gid] = {"category": category, "kind": "image", "asset": _cg_logical(i),
                      "title_key": f"corpus.gal.{gid}.title",
                      "unlock": {"seen_image": True}}
        strings[f"corpus.gal.{gid}.title"] = f"Кадр {i + 1}"
    for si in range(plan.shots):
        ci, scene_i = table[si]
        gid = f"shot_{_chapter_id(ci)}_{_scene_id(scene_i)}_{SHOT_ID}"
        items[gid] = {"category": category, "kind": "shot",
                      "asset": f"shots/{_chapter_id(ci)}/{_scene_id(scene_i)}/{SHOT_ID}",
                      "title_key": f"corpus.gal.{gid}.title",
                      "unlock": {"seen_image": True}}
        strings[f"corpus.gal.{gid}.title"] = f"Шот {si + 1}"
    w.write_yaml("content/gallery/core.gallery.yaml", {
        "schema": "gallery@1",
        "categories": {category: {"title_key":
                                  f"corpus.gallery.cat.{category}.title"}},
        "items": items,
    }, _HEADER)
    w.write_yaml("content/ui/strings.yaml",
                 {"schema": "strings@1", "strings": strings}, _HEADER)


def _write_shots(w: _Writer, plan: _ImagePlan, table: list[tuple[int, int]],
                 first_master: int) -> int:
    """Шоты вешаются на первые сцены корпуса: декларация + слои на общем холсте."""
    index = first_master
    for si in range(plan.shots):
        ci, scene_i = table[si]
        ch_id, scene_id = _chapter_id(ci), _scene_id(scene_i)
        w.write_yaml(
            f"content/chapters/{_chapter_dir(ci)}/shots/{scene_id}.shots.yaml", {
                "schema": "shots@1", "scene": scene_id,
                "shots": {SHOT_ID: {"layers": {name: {} for name in SHOT_LAYERS},
                                    "order": list(SHOT_LAYERS)}},
            }, _HEADER)
        for layer in SHOT_LAYERS:
            # Подложка обязана быть непрозрачной, остальные слои — вырезанными:
            # это политика конвейера для класса shot, а не украшение корпуса.
            w.write(f"assets_src/art/shots/{ch_id}/{scene_id}/{SHOT_ID}/{layer}.png",
                    _master_png(index, alpha=(layer != SHOT_ENV)))
            index += 1
    return index


def _write_videos(w: _Writer, spec: CorpusSpec) -> None:
    for i in range(spec.videos):
        _video_master(w.path(f"assets_src/video_src/{VIDEO_GROUP}/clip_{i + 1:03d}.mp4"), i)


def _scene_rpy(full_id: str, ch_id: str, spec: CorpusSpec, participants: list[str],
               var_name: str | None, has_shot: bool, has_skip: bool) -> str:
    """Авторская сцена по контракту C2: метка __body, переходы через return.

    Тело намеренно «как настоящее»: show/hide реальных образов, чтение и запись
    переменной своей главы, меню с маркером для реестра выборов. Синтетика без
    этого не нагружала бы ни сверку ссылок, ни Variable Registry — то есть мерила
    бы не тот конвейер, который работает на боевом контенте."""
    out = [_HEADER, f"label {full_id}__body:"]
    num = 0

    def say(text: str, indent: str = "    ") -> None:
        nonlocal num
        num += 1
        out.append(f'{indent}"{text}" id {full_id}_{num:04d}')

    for char in participants:
        out.append(f"    show {char} a out_1 emo_1 with dissolve")
    for i in range(spec.lines):
        say(f"Синтетическая реплика {i + 1} сцены {full_id}.")
    if var_name:
        out.append(f"    if {ch_id}.{var_name}:")
        say("Ветка по флагу главы.", indent="        ")
    if has_shot:
        out.append(f"    scene shot_{full_id} {SHOT_ID} with dissolve")
        say("Послойный шот в кадре.")
    for char in participants:
        out.append(f"    hide {char}")
    if has_skip:
        out.append("")
        out.append(f'    $ vn_menu = "{full_id}_m001"')
        out.append("    menu:")
        out.append('        "Дальше":')
        if var_name:
            out.append(f"            $ {ch_id}.{var_name} = True")
        out.append('            return "next"')
        out.append('        "Срезать":')
        out.append('            return "skip"')
    else:
        if var_name:
            out.append(f"    $ {ch_id}.{var_name} = True")
        out.append('    return "next"')
    return "\n".join(out) + "\n"


def _write_chapters(w: _Writer, spec: CorpusSpec, sizes: list[int],
                    plan: _ImagePlan, per_chapter: list[int],
                    table: list[tuple[int, int]]) -> int:
    """Главы и сцены. Граф — цепочка next с ветвлением skip через одну сцену:
    все сцены достижимы от entry_scene, тупик один и он последний в scene_order,
    поэтому lint на корпусе молчит по делу, а не потому, что главы в draft."""
    shot_scenes = {table[i] for i in range(plan.shots)}
    says = 0
    for ci, count in enumerate(sizes):
        ch_id, ch_dir = _chapter_id(ci), _chapter_dir(ci)
        order = [_scene_id(i) for i in range(count)]
        w.write_yaml(f"content/chapters/{ch_dir}/chapter.yaml", {
            "schema": "chapter@1", "id": ch_id,
            "title_key": f"corpus.chapters.{ch_id}.title",
            # release, а не draft: в draft статусе битые ссылки становятся
            # предупреждениями, и генератор с ошибкой давал бы «зелёный» прогон.
            "status": "release",
            "entry_scene": order[0], "scene_order": order,
        }, _HEADER)
        for si in range(count):
            scene_id, full_id = _scene_id(si), f"{ch_id}_{_scene_id(si)}"
            exits: dict[str, str] = {}
            if si + 1 < count:
                exits["next"] = _scene_id(si + 1)
            if si + 2 < count:
                exits["skip"] = _scene_id(si + 2)
            meta: dict = {
                "schema": "scene@1", "id": scene_id,
                "title_key": f"corpus.scenes.{full_id}.title",
                "location": f"{_location_id(si % plan.locations)}/day",
            }
            if not exits:
                # Последняя сцена главы: exits нет, поэтому и return пустой —
                # иначе компилятор справедливо потребует объявленный exit-id.
                # Переменных и участников у неё тоже нет: объявить и не
                # использовать значит получить предупреждение по делу.
                w.write_yaml(f"content/chapters/{ch_dir}/scenes/{scene_id}_gen.scene.yaml",
                             meta, _HEADER)
                w.write_text(
                    f"content/chapters/{ch_dir}/scenes/{scene_id}_gen.scene.rpy",
                    _HEADER + f"label {full_id}__body:\n"
                    + f'    "Финал главы {ch_id}." id {full_id}_0001\n'
                    + "    return\n")
                says += 1
                continue
            var_name = f"v_{si % per_chapter[ci] + 1:03d}" if per_chapter[ci] else None
            participants = [_character_id((si + k) % plan.characters)
                            for k in range(min(PARTICIPANTS_PER_SCENE, plan.characters))]
            has_shot = (ci, si) in shot_scenes
            if participants:
                meta["participants"] = sorted(set(participants))
            if var_name:
                meta["vars"] = {"reads": [f"{ch_id}.{var_name}"],
                                "writes": [f"{ch_id}.{var_name}"]}
            meta["exits"] = exits
            w.write_yaml(f"content/chapters/{ch_dir}/scenes/{scene_id}_gen.scene.yaml",
                         meta, _HEADER)
            w.write_text(
                f"content/chapters/{ch_dir}/scenes/{scene_id}_gen.scene.rpy",
                _scene_rpy(full_id, ch_id, spec, participants, var_name, has_shot,
                           "skip" in exits))
            says += spec.lines + (1 if var_name else 0) + (1 if has_shot else 0)
    return says


def generate(dest: Path, spec: CorpusSpec, template_root: Path) -> GenerateResult:
    """Собрать корпус в dest. Существующий корпус той же спеки переиспользуется
    (перезаписываются только разошедшиеся файлы), другой — сносится начисто."""
    dest = Path(dest)
    marker = dest / MARKER
    if dest.exists() and any(dest.iterdir()):
        if not marker.is_file():
            raise CorpusError(
                f"{dest} не пуст и не является корпусом (нет {MARKER}) — "
                f"укажите другой каталог: корпус удаляет за собой всё дерево")
        if json.loads(marker.read_text(encoding="utf-8")).get("spec") != asdict(spec):
            shutil.rmtree(dest)

    sizes, plan, per_chapter = _plan(spec)
    table = _scene_table(sizes)
    w = _Writer(dest)
    dest.mkdir(parents=True, exist_ok=True)

    _copy_template(w, template_root)
    _write_registries(w, template_root)
    _write_variables(w, sizes, per_chapter)
    # Индекс мастера сквозной по классам: он и делает содержимое каждой картинки
    # уникальным (см. _master_png).
    index = _write_locations(w, plan, 0)
    index = _write_characters(w, plan, index)
    index = _write_shots(w, plan, table, index)
    index = _write_cg(w, plan, index)
    if index != plan.masters:
        raise CorpusError(f"генератор записал {index} мастеров вместо "
                          f"{plan.masters} — масштаб корпуса не соблюдён")
    _write_videos(w, spec)
    _write_gallery_and_strings(w, sizes, plan, table)
    says = _write_chapters(w, spec, sizes, plan, per_chapter, table)

    layout = CorpusLayout(
        chapters=len(sizes), scenes=spec.scenes, locations=plan.locations,
        characters=plan.characters, cg=plan.cg, shots=plan.shots, videos=spec.videos,
        masters=plan.masters, says=says, variables=1 + sum(per_chapter))
    # Маркер — паспорт корпуса: по нему measure знает масштаб, generate решает о
    # переиспользовании, а cleanup отличает свой каталог от чужого. Поля schema
    # здесь нет намеренно: это не декларация проекта, линтер её не читает.
    w.write_text(MARKER, json.dumps(
        {"tool": "vn test corpus", "spec": asdict(spec), "layout": asdict(layout)},
        ensure_ascii=False, indent=1) + "\n")
    return GenerateResult(layout=layout, written=w.written, unchanged=w.unchanged)


def read_spec(dest: Path) -> tuple[CorpusSpec, CorpusLayout]:
    marker = Path(dest) / MARKER
    if not marker.is_file():
        raise CorpusError(f"{dest} не корпус: нет {MARKER}")
    doc = json.loads(marker.read_text(encoding="utf-8"))
    return CorpusSpec(**doc["spec"]), CorpusLayout(**doc["layout"])


def cleanup(dest: Path) -> None:
    """Снести корпус. Только свой: без маркера удалять чужое дерево нельзя."""
    dest = Path(dest)
    if not dest.exists():
        return
    if not (dest / MARKER).is_file():
        raise CorpusError(f"{dest} не корпус (нет {MARKER}) — удаление отменено")
    shutil.rmtree(dest)


# ── Измерение ────────────────────────────────────────────────────────────────

@dataclass
class Stage:
    """Одна стадия прогона. rss_peak — ВЫСШАЯ ВОДА процесса на момент конца
    стадии (getrusage не даёт пик за интервал), поэтому цифра честно читается как
    «сколько памяти процесс занимал максимум к этому моменту», а не «за стадию».
    child_rss_peak — пик самого тяжёлого дочернего процесса (build-bridge Ren'Py)."""

    name: str
    seconds: float = 0.0
    cpu_self_s: float = 0.0
    cpu_child_s: float = 0.0
    rss_peak_mb: float = 0.0
    child_rss_peak_mb: float = 0.0
    note: str = ""
    warnings: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ZoneSize:
    files: int = 0
    bytes: int = 0


@dataclass
class MemoryFacts:
    """Итог модели памяти. worst_px хранится и в пикселях, и в «экранах»: доля
    бюджета зависит от пола image_cache_mb (см. _cache_mb), а стоимость сцены в
    экранах — нет, и именно она сравнима с боевым профилем."""

    scale: int = 0
    budget_px: int = 0
    worst_scene: str = ""
    worst_px: int = 0
    over_80pct: int = 0
    recommended_cache_mb: int = 0

    @property
    def worst_screens(self) -> float:
        return self.worst_px / (SCREEN[0] * SCREEN[1])


@dataclass
class MeasureReport:
    spec: CorpusSpec
    layout: CorpusLayout
    dest: Path
    stages: list[Stage] = field(default_factory=list)
    zones: dict[str, ZoneSize] = field(default_factory=dict)
    memory: MemoryFacts = field(default_factory=MemoryFacts)
    asset_outputs: int = 0
    generated_files: int = 0
    budget_failures: list[str] = field(default_factory=list)
    budget_use: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # Превышенный бюджет G19 — такой же провал масштаба, как упавшая стадия:
        # это тот же гейт, что валит релиз. Измерено на 20 000 сцен: конвейер
        # зелёный, а game/generated = 68 358 КБ против бюджета 65 536 КБ, и
        # печатать при этом «OK» значило бы врать о потолке корпуса.
        return not any(s.errors for s in self.stages) and not self.budget_failures

    def stage(self, name: str) -> Stage | None:
        return next((s for s in self.stages if s.name == name), None)


def _rusage() -> tuple[float, float, float, float]:
    """(cpu процесса, cpu детей, пик RSS процесса, пик RSS самого тяжёлого ребёнка)."""
    if resource is None:                        # pragma: no cover — Windows
        return (0.0, 0.0, 0.0, 0.0)
    me = resource.getrusage(resource.RUSAGE_SELF)
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (me.ru_utime + me.ru_stime, kids.ru_utime + kids.ru_stime,
            me.ru_maxrss * _RSS_UNIT / 1e6, kids.ru_maxrss * _RSS_UNIT / 1e6)


class _Timer:
    """Бухгалтерия одной стадии (время, cpu, память). Общая для генерации и для
    стадий конвейера: два места, считающие одно и то же по-разному, рано или
    поздно разошлись бы в цифрах."""

    def __init__(self, name: str):
        self.stage = Stage(name=name)
        self._cpu0, self._kid0, _rss, _krss = _rusage()
        self._t0 = time.perf_counter()

    def finish(self) -> Stage:
        st = self.stage
        st.seconds = time.perf_counter() - self._t0
        cpu1, kid1, rss1, krss1 = _rusage()
        st.cpu_self_s, st.cpu_child_s = cpu1 - self._cpu0, kid1 - self._kid0
        st.rss_peak_mb, st.child_rss_peak_mb = rss1, krss1
        return st


@contextmanager
def _stage(rep: MeasureReport, name: str):
    timer = _Timer(name)
    try:
        yield timer.stage
    except Exception as e:      # noqa: BLE001
        # Падение стадии — это РЕЗУЛЬТАТ измерения (например «на 8000 сцен
        # build-bridge не запускается: argv длиннее ARG_MAX»), а не причина
        # потерять отчёт: остальные стадии всё равно дают числа.
        timer.stage.errors.append(f"{type(e).__name__}: {e}")
    rep.stages.append(timer.finish())


def _zone(root: Path, rel: str) -> ZoneSize:
    base = root / rel
    z = ZoneSize()
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            try:
                z.bytes += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
            z.files += 1
    return z


# Зоны, объём которых сравнивается между масштабами. Порядок = порядок в таблице.
ZONES = ("game/generated", "game/assets", "content", "assets_src", ".vncache")


def _budgets(dest: Path) -> dict:
    from .repo import load_project

    return dict(load_project(dest).get("budgets") or {})


def measure(dest: Path, profile: str = "full") -> MeasureReport:
    """Полный конвейер по готовому корпусу с замером каждой стадии.

    Стадии зовутся ФУНКЦИЯМИ, а не подпроцессами vn: иначе в замер попадал бы
    старт интерпретатора и импорт click, а не работа конвейера. Единственный
    подпроцесс внутри — build-bridge Ren'Py, и он учтён отдельной строкой cpu."""
    from .assets.memory import analyze, recommended_cache_mb
    from .assets.pipeline import build_assets
    from .assets.render_config import load_render_config
    from .content.compile import compile_content
    from .content.lint import lint
    from .release import budget_failures

    dest = Path(dest)
    spec, layout = read_spec(dest)
    rep = MeasureReport(spec=spec, layout=layout, dest=dest)

    with _stage(rep, "assets build") as st:
        res = build_assets(dest, profile=profile)
        st.errors = list(res.errors)
        st.warnings = len(res.warnings) + len(res.skipped_variants)
        rep.asset_outputs = len(res.built) + len(res.from_cache) + len(res.fresh)
        st.note = (f"{len(res.built)} собрано, {len(res.from_cache)} из кэша, "
                   f"{len(res.fresh)} актуально")

    with _stage(rep, "content lint") as st:
        lrep = lint(dest)
        st.errors = list(lrep.errors)
        st.warnings = len(lrep.warnings)
        st.note = "OK" if lrep.ok else f"{len(lrep.errors)} ошибок"

    with _stage(rep, "content compile") as st:
        cres = compile_content(dest)
        st.warnings = len(cres.warnings)
        rep.generated_files = len(cres.written) + len(cres.skipped)
        st.note = f"{len(cres.written)} записано, {len(cres.skipped)} без изменений"

    with _stage(rep, "content compile (повторно)") as st:
        cres2 = compile_content(dest)
        st.warnings = len(cres2.warnings)
        # Повторная компиляция обязана быть байт-в-байт: перезапись генерата
        # заставляет Ren'Py перекомпилировать все .rpyc, и это самая заметная
        # для разработчика деградация из всех возможных.
        if cres2.written:
            st.errors.append(f"повторная компиляция перезаписала {len(cres2.written)} "
                             f"файлов — генерат не идемпотентен")
        st.note = f"{len(cres2.written)} записано, {len(cres2.skipped)} без изменений"

    with _stage(rep, "assets memory") as st:
        cfg = load_render_config(dest)
        mrep = analyze(dest, cfg)
        st.errors = list(mrep.errors)
        st.warnings = len(mrep.warnings)
        worst = mrep.worst
        rep.memory = MemoryFacts(
            scale=mrep.scale, budget_px=mrep.budget_px,
            worst_scene=worst.scene_id if worst else "",
            worst_px=worst.px if worst else 0,
            over_80pct=sum(1 for s in mrep.scenes if s.px > mrep.budget_px * 0.8),
            recommended_cache_mb=recommended_cache_mb(mrep, cfg.cache_generations))
        st.note = f"{len(mrep.scenes)} сцен посчитано"

    for rel in ZONES:
        rep.zones[rel] = _zone(dest, rel)
    rep.budget_failures = budget_failures(dest)
    budgets = _budgets(dest)
    if budgets.get("generated_total_kb"):
        rep.budget_use["generated_total_kb"] = (
            rep.zones["game/generated"].bytes / 1024 / budgets["generated_total_kb"])
    if budgets.get("assets_total_mb"):
        rep.budget_use["assets_total_mb"] = (
            rep.zones["game/assets"].bytes / (1024 * 1024) / budgets["assets_total_mb"])
    return rep


def run(dest: Path, spec: CorpusSpec, template_root: Path, profile: str = "full",
        keep: bool = False) -> MeasureReport:
    """Сгенерировать корпус, измерить конвейер, убрать за собой (если не keep).

    Каталог сносится и при аварии: корпус на 2000 сцен — это сотни мегабайт, и
    оставлять их после падения значит копить мусор в .vncache молча."""
    try:
        rep_gen = _generate_stage(dest, spec, template_root)
        rep = measure(dest, profile=profile)
        rep.stages.insert(0, rep_gen)
    finally:
        # Маркер проверяем здесь, а не в cleanup: если generate отказался писать в
        # ЧУЖОЙ каталог, снос этого каталога затёр бы и причину отказа, и данные.
        if not keep and (Path(dest) / MARKER).is_file():
            cleanup(dest)
    return rep


def _generate_stage(dest: Path, spec: CorpusSpec, template_root: Path) -> Stage:
    """Генерация как измеряемая стадия: её стоимость — часть ответа на вопрос
    «во что обходится корпус такого масштаба».

    Ошибка генератора здесь НЕ глотается, в отличие от стадий конвейера: если
    корпус не построен, мерить нечего, и отчёт был бы про пустоту."""
    timer = _Timer("generate")
    gen = generate(dest, spec, template_root)
    timer.stage.note = (f"{len(gen.written)} файлов записано, "
                        f"{gen.unchanged} без изменений")
    return timer.finish()


# ── Отчёт ────────────────────────────────────────────────────────────────────

def _fmt_int(value: int) -> str:
    return f"{value:_}".replace("_", " ")


def _fmt_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} МБ"


def format_table(reports: list[MeasureReport]) -> str:
    """Таблица «метрика x масштаб». Одна колонка на прогон: так один запуск и
    сравнение нескольких масштабов печатаются одним и тем же кодом."""
    if not reports:
        return "измерений нет"
    rows: list[tuple[str, list[str]]] = []

    def add(label: str, values) -> None:
        rows.append((label, [str(v) for v in values]))

    add("глав / сцен", [f"{r.layout.chapters} / {_fmt_int(r.layout.scenes)}"
                        for r in reports])
    add("реплик / переменных", [f"{_fmt_int(r.layout.says)} / {r.layout.variables}"
                                for r in reports])
    add("мастеров (bg/spr/shot/cg)",
        [f"{r.layout.masters} ({r.layout.locations}/"
         f"{r.layout.characters * LAYERS_PER_CHARACTER}/"
         f"{r.layout.shots * len(SHOT_LAYERS)}/{r.layout.cg})" for r in reports])
    rows.append(("── время, c", ["" for _ in reports]))
    stage_names = [s.name for s in reports[0].stages]
    for name in stage_names:
        add(f"  {name}", [f"{(r.stage(name).seconds if r.stage(name) else 0):.2f}"
                          for r in reports])
    add("  ИТОГО", [f"{sum(s.seconds for s in r.stages):.2f}" for r in reports])
    add("  в т.ч. cpu самого vn", [f"{sum(s.cpu_self_s for s in r.stages):.2f}"
                                   for r in reports])
    # Дети конвейера — build-bridge Ren'Py и ffmpeg: их cpu не виден в cpu vn,
    # а именно он объясняет, почему compile дороже, чем выглядит по коду.
    add("  в т.ч. cpu детей (bridge/ffmpeg)",
        [f"{sum(s.cpu_child_s for s in r.stages):.2f}" for r in reports])
    rows.append(("── память, МБ", ["" for _ in reports]))
    add("  пик RSS vn", [f"{max((s.rss_peak_mb for s in r.stages), default=0):.0f}"
                         for r in reports])
    add("  пик RSS ребёнка (bridge/ffmpeg)",
        [f"{max((s.child_rss_peak_mb for s in r.stages), default=0):.0f}"
         for r in reports])
    rows.append(("── объём", ["" for _ in reports]))
    for rel in ZONES:
        add(f"  {rel}", [f"{_fmt_int(r.zones[rel].files)} ф / {_fmt_mb(r.zones[rel].bytes)}"
                         for r in reports])
    add("  генерата на сцену, КБ",
        [f"{r.zones['game/generated'].bytes / 1024 / max(1, r.layout.scenes):.1f}"
         for r in reports])
    add("  бюджет generated_total_kb",
        [f"{r.budget_use.get('generated_total_kb', 0):.1%}" for r in reports])
    add("  бюджет assets_total_mb",
        [f"{r.budget_use.get('assets_total_mb', 0):.2%}" for r in reports])
    rows.append(("── модель памяти", ["" for _ in reports]))
    add("  масштаб / бюджет сцены, Мпикс",
        [f"@{r.memory.scale} / {r.memory.budget_px / 1e6:.2f}" for r in reports])
    add("  худшая сцена, Мпикс (доля)",
        [f"{r.memory.worst_px / 1e6:.3f} "
         f"({r.memory.worst_px / r.memory.budget_px:.0%})" if r.memory.budget_px else "—"
         for r in reports])
    add("  худшая сцена, экранов", [f"{r.memory.worst_screens:.1f}" for r in reports])
    add("  сцен свыше 80 % бюджета", [r.memory.over_80pct for r in reports])
    add("  рекомендуемый image_cache_mb",
        [r.memory.recommended_cache_mb for r in reports])
    rows.append(("── итог", ["" for _ in reports]))
    add("  предупреждений", [sum(s.warnings for s in r.stages) for r in reports])
    add("  ошибок", [sum(len(s.errors) for s in r.stages) for r in reports])
    add("  бюджеты G19", ["OK" if not r.budget_failures else
                          f"{len(r.budget_failures)} превышений" for r in reports])

    head = [r.spec.label() for r in reports]
    label_w = max(len(label) for label, _ in rows)
    col_w = [max(len(h), *(len(row[1][i]) for row in rows)) for i, h in enumerate(head)]
    lines = ["корпус".ljust(label_w) + "  " + "  ".join(
        h.rjust(col_w[i]) for i, h in enumerate(head))]
    lines.append("-" * len(lines[0]))
    for label, values in rows:
        lines.append(label.ljust(label_w) + "  " + "  ".join(
            v.rjust(col_w[i]) for i, v in enumerate(values)))
    if len(reports) == 1:
        # Один прогон — есть место на подробности стадий (сколько собрано, сколько
        # взято из кэша). В сравнении масштабов эти строки только мешали бы.
        for st in reports[0].stages:
            if st.note:
                lines.append(f"{st.name}: {st.note}")
    for r in reports:
        for st in r.stages:
            for err in st.errors:
                lines.append(f"[{r.spec.label()}] {st.name}: {err}")
        for f in r.budget_failures:
            lines.append(f"[{r.spec.label()}] бюджет: {f}")
    lines.append("объём game/assets снят на render-профиле корпуса "
                 f"({SCREEN[0]}x{SCREEN[1]}) и с боевым 4K не сопоставим; "
                 "game/generated сопоставим — он зависит от сцен и реплик")
    return "\n".join(lines)
