"""Синтетический корпус масштаба (vn test corpus): валидность деклараций,
соблюдение масштаба, идемпотентность, изоляция от репозитория, очистка.

Измерительный прогон целиком (assets build -> lint -> compile -> memory) требует
парсер Ren'Py из пиннованного SDK — как и остальные e2e-тесты сцен, он под
skipif RENPY_SDK.
"""

import json
import os
import re
from pathlib import Path

import pytest

from vn import corpus
from vn.content.lint import lint
from vn.schemas import SchemaRegistry

# Малый корпус, в котором представлены ВСЕ классы образов: 20 мастеров дают
# и фоны, и одного персонажа целиком, и один послойный шот (см. IMAGE_MIX).
SMALL = corpus.CorpusSpec(scenes=6, images=20, lines=2, variables=4)


def _tree(root: Path) -> dict[str, int]:
    """Снимок дерева: путь -> размер. Сравнивается для проверки идемпотентности."""
    return {p.relative_to(root).as_posix(): p.stat().st_size
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_declarations_are_schema_valid_and_lint_clean(tmp_path, repo_root):
    """Корпус обязан быть валидным проектом: иначе прогон мерил бы не конвейер,
    а собственные ошибки генератора."""
    dest = tmp_path / "corpus"
    corpus.generate(dest, SMALL, repo_root)

    registry = SchemaRegistry(dest / "tools" / "schemas")
    docs = [dest / "project.yaml", dest / ".vnstorage.yaml",
            *sorted((dest / "content").rglob("*.yaml")),
            *sorted((dest / "content").rglob("*.json"))]
    from vn.repo import load_yaml

    errors: list[str] = []
    for path in docs:
        data = (json.loads(path.read_text(encoding="utf-8"))
                if path.suffix == ".json" else load_yaml(path))
        errors += registry.validate(data, path.relative_to(dest).as_posix())
    assert errors == []

    rep = lint(dest)
    assert rep.errors == []
    # Предупреждения тоже пусты не для красоты: на 2000 сцен шум по одному
    # warning на образ или главу утопил бы измерение (и это уже случалось —
    # незаявленный в галерее CG и title_key без строки).
    assert rep.warnings == []


def test_scale_is_respected(tmp_path, repo_root):
    dest = tmp_path / "corpus"
    res = corpus.generate(dest, SMALL, repo_root)
    layout = res.layout

    assert layout.scenes == SMALL.scenes
    assert layout.masters == SMALL.images
    assert layout.variables == SMALL.variables
    assert layout.videos == 0
    # Все классы образов представлены — иначе тест «валидных деклараций» ничего
    # не говорил бы о спрайтах и шотах.
    assert layout.locations and layout.characters and layout.shots and layout.cg

    # Факт на диске, а не только в отчёте: мастера, пары файлов сцены, декларации.
    masters = [p for p in (dest / "assets_src").rglob("*") if p.is_file()]
    assert len(masters) == SMALL.images
    scene_yaml = sorted((dest / "content" / "chapters").rglob("*.scene.yaml"))
    scene_rpy = sorted((dest / "content" / "chapters").rglob("*.scene.rpy"))
    assert len(scene_yaml) == len(scene_rpy) == SMALL.scenes
    declared = set()
    for f in sorted((dest / "content" / "variables").glob("*.vars.yaml")) + \
            sorted((dest / "content" / "chapters").glob("*/vars.yaml")):
        from vn.repo import load_yaml

        doc = load_yaml(f)
        declared |= {f"{doc['store']}.{name}" for name in doc["vars"]}
    assert len(declared) == SMALL.variables

    # Реплик столько, сколько обещано: их число — ось масштаба локализации.
    says = sum(text.count(" id ") for text in
               (p.read_text(encoding="utf-8") for p in scene_rpy))
    assert says == layout.says


def test_regenerate_is_idempotent(tmp_path, repo_root):
    """Повторный прогон не переписывает ни байта: иначе он сбивал бы mtime
    мастеров и следующее измерение мерило бы холодную сборку."""
    dest = tmp_path / "corpus"
    corpus.generate(dest, SMALL, repo_root)
    before = _tree(dest)
    again = corpus.generate(dest, SMALL, repo_root)
    assert again.written == []
    assert again.unchanged == len(before)
    assert _tree(dest) == before


def test_other_scale_rebuilds_from_scratch(tmp_path, repo_root):
    """Смена масштаба = другой корпус: остатки прошлого дерева обязаны исчезнуть,
    иначе lint нашёл бы главы, которых спека уже не описывает."""
    dest = tmp_path / "corpus"
    corpus.generate(dest, SMALL, repo_root)
    bigger = corpus.CorpusSpec(scenes=SMALL.scenes + 60, images=SMALL.images,
                               lines=SMALL.lines, variables=SMALL.variables)
    res = corpus.generate(dest, bigger, repo_root)
    assert res.layout.scenes == bigger.scenes
    assert res.unchanged == 0
    assert len(sorted((dest / "content" / "chapters").rglob("*.scene.yaml"))) \
        == bigger.scenes


def test_generate_writes_only_into_dest(tmp_path, repo_root):
    """Корпус не пишет в репозиторий: параллельно с ним работают люди, и запись
    в content/ или assets_src/ рабочего дерева была бы катастрофой."""
    watched = ["project.yaml", "content", "assets_src", "game", "tools", "docs"]

    def snapshot():
        out = {}
        for rel in watched:
            p = repo_root / rel
            if p.is_file():
                out[rel] = p.stat().st_mtime_ns
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    out[f.relative_to(repo_root).as_posix()] = f.stat().st_mtime_ns
        return out

    before = snapshot()
    dest = tmp_path / "corpus"
    corpus.generate(dest, SMALL, repo_root)
    assert snapshot() == before
    assert (dest / corpus.MARKER).is_file()
    # Каталог по умолчанию тоже вне git: .vncache — локальная зона (.gitignore),
    # иначе прогон корпуса пачкал бы рабочее дерево на каждой машине.
    assert corpus.default_dest(repo_root).is_relative_to(repo_root / ".vncache")


def test_default_dest_does_not_collide(repo_root):
    """Дефолтный каталог корпуса не совпадает ни с одной чужой рабочей зоной в
    .vncache. Иначе дефолт нерабочий: прогон сносит своё дерево целиком, а без
    маркера отказывается писать в занятую папку — ровно это и случилось с
    артефактами автопилота `vn save corpus` (.vncache/corpus)."""
    src = repo_root / "tools" / "vn" / "src" / "vn"
    others: set[str] = set()
    for py in sorted(src.rglob("*.py")):
        if py.name == "corpus.py":          # свой каталог корпус объявляет сам
            continue
        others |= set(re.findall(r'"\.vncache"\s*/\s*"([^"]+)"',
                                 py.read_text(encoding="utf-8")))
    assert others, "разметка каталогов .vncache изменилась — гард ослеп"
    assert corpus.default_dest(repo_root).name not in others


def test_writer_refuses_paths_outside_corpus(tmp_path):
    w = corpus._Writer(tmp_path / "corpus")
    with pytest.raises(corpus.CorpusError):
        w.write("../beyond.txt", b"x")


def test_cleanup_removes_only_own_tree(tmp_path, repo_root):
    dest = tmp_path / "corpus"
    corpus.generate(dest, SMALL, repo_root)
    corpus.cleanup(dest)
    assert not dest.exists()
    corpus.cleanup(dest)                    # повторная очистка — не ошибка

    # Чужой каталог не сносится даже по прямой просьбе: маркера нет.
    alien = tmp_path / "alien"
    (alien / "sub").mkdir(parents=True)
    (alien / "sub" / "important.txt").write_text("не трогать", encoding="utf-8")
    with pytest.raises(corpus.CorpusError):
        corpus.cleanup(alien)
    assert (alien / "sub" / "important.txt").is_file()


def test_generate_refuses_alien_dir(tmp_path, repo_root):
    alien = tmp_path / "alien"
    alien.mkdir()
    (alien / "important.txt").write_text("не трогать", encoding="utf-8")
    with pytest.raises(corpus.CorpusError):
        corpus.generate(alien, SMALL, repo_root)
    assert (alien / "important.txt").is_file()


def test_spec_limits_are_explicit():
    with pytest.raises(corpus.CorpusError):
        corpus.CorpusSpec(scenes=1).validate()
    with pytest.raises(corpus.CorpusError):
        corpus.CorpusSpec(variables=0).validate()
    # Потолок id: главы ^ch\d{2}$ x сцены ^s\d{3}$ — врать о больших корпусах нельзя.
    with pytest.raises(corpus.CorpusError):
        corpus.CorpusSpec(scenes=corpus.MAX_CHAPTERS * corpus.MAX_SCENES_PER_CHAPTER + 1
                          ).validate()


def test_chapter_layout_respects_id_capacity():
    """Раскладка по главам: пока глав хватает — фиксированный размер главы,
    дальше глава распухает, но число глав не выходит за ^ch\\d{2}$."""
    assert corpus._chapter_sizes(10) == [10]
    assert corpus._chapter_sizes(corpus.SCENES_PER_CHAPTER * 3) == \
        [corpus.SCENES_PER_CHAPTER] * 3
    huge = corpus._chapter_sizes(corpus.SCENES_PER_CHAPTER * corpus.MAX_CHAPTERS * 2)
    assert len(huge) <= corpus.MAX_CHAPTERS
    assert max(huge) <= corpus.MAX_SCENES_PER_CHAPTER
    assert sum(huge) == corpus.SCENES_PER_CHAPTER * corpus.MAX_CHAPTERS * 2


def test_masters_are_unique_per_index():
    """Мастера обязаны различаться байтами: кэш трансформаций контентно-адресуемый,
    и корпус из одинаковых картинок мерил бы дедупликацию вместо сборки."""
    blobs = {corpus._master_png(i, alpha=False) for i in range(300)}
    assert len(blobs) == 300
    assert corpus._master_png(7, alpha=False) == corpus._master_png(7, alpha=False)


def test_budget_overflow_is_not_a_green_run(tmp_path):
    """Превышенный бюджет G19 — такой же провал масштаба, как упавшая стадия.

    Измерено на 20 000 сцен: все стадии зелёные, а game/generated = 68 358 КБ
    против бюджета 65 536 КБ. Печатать при этом «test corpus: OK» значило бы врать
    о потолке корпуса — а он теперь именно бюджетный, а не ARG_MAX.
    """
    rep = corpus.MeasureReport(spec=SMALL, layout=corpus.CorpusLayout(), dest=tmp_path)
    assert rep.ok
    rep.budget_failures.append("game/generated: 68358 КБ > бюджета 65536 КБ")
    assert not rep.ok


SDK = os.environ.get("RENPY_SDK")


@pytest.mark.skipif(not (SDK and (Path(SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_measure_runs_whole_pipeline(tmp_path, repo_root):
    """Измерительный прогон целиком: конвейер по корпусу обязан быть зелёным, а
    отчёт — содержать числа по каждой стадии."""
    dest = tmp_path / "corpus"
    rep = corpus.run(dest, SMALL, repo_root, keep=True)

    assert [s.name for s in rep.stages] == [
        "generate", "assets build", "content lint", "content compile",
        "content compile (повторно)", "assets memory"]
    assert rep.ok, [(s.name, s.errors) for s in rep.stages if s.errors]
    assert all(s.seconds >= 0 for s in rep.stages)
    assert rep.asset_outputs > SMALL.images        # варианты + миниатюры
    assert rep.generated_files > 0
    assert rep.zones["game/generated"].bytes > 0
    assert rep.budget_failures == []
    # Модель памяти посчитала КАЖДУЮ сцену и уложилась в бюджет.
    assert rep.memory.worst_px > 0 and rep.memory.budget_px > rep.memory.worst_px
    assert rep.memory.worst_screens > 1
    assert f"{SMALL.scenes} сцен" in corpus.format_table([rep])

    corpus.cleanup(dest)


@pytest.mark.skipif(not (SDK and (Path(SDK) / "renpy.py").is_file()),
                    reason="RENPY_SDK не установлен")
def test_run_cleans_up_by_default(tmp_path, repo_root):
    dest = tmp_path / "corpus"
    corpus.run(dest, SMALL, repo_root)
    assert not dest.exists()
