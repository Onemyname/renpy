"""Флейворы и build-info (ADR-0006): конфиг, вычисление исключений, схема,
бюджеты видео. Полный validate_release гоняется в CI/вручную (нужен SDK) —
здесь юнит-уровень."""

import json
import shutil

import pytest

from vn.release import (BUILD_INFO_REL, ReleaseError, budget_failures,
                        clear_build_info, compute_build_info, flavor_config,
                        nsfw_exclude_globs, patron_tag, write_build_info)

from conftest import REPO_ROOT

PROJECT = """\
schema: project@1
version: 0.2.0
save_schema: 1
min_tools: "0.1"
budgets:
  video_total_mb: 10
  video_file_mb: 1
flavors:
  public:
    packs: [ep_beach]
    nsfw: false
    early_content: false
    watermark: false
  patron:
    packs: [nsfw, ep_beach]
    nsfw: true
    early_content: true
    watermark: true
"""


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "tools" / "schemas", root / "tools" / "schemas")
    (root / "project.yaml").write_text(PROJECT, encoding="utf-8")
    (root / "game").mkdir()
    return root


def test_flavor_config_and_unknown():
    import yaml
    project = yaml.safe_load(PROJECT)
    assert flavor_config(project, "public")["nsfw"] is False
    with pytest.raises(ReleaseError) as ei:
        flavor_config(project, "steam_deck")
    assert "public" in str(ei.value)     # перечисляет доступные


def test_build_info_excludes_nsfw_assets_for_public(tmp_path):
    root = _mk_root(tmp_path)
    for d in ("cg/nsfw/ch01", "mov/nsfw", "bg/city"):
        (root / "game" / "assets" / d).mkdir(parents=True)

    info = compute_build_info(root, "public")
    assert info["schema"] == "build_info@2"
    assert info["nsfw"] is False and info["watermark"] is False
    assert info["exclude"] == ["game/assets/cg/nsfw/**", "game/assets/mov/nsfw/**"]
    assert info["build_id"].startswith("0.2.0+")
    assert ".public." in info["build_id"]

    patron = compute_build_info(root, "patron", patron_token="tok_abc123")
    assert patron["exclude"] == []                     # полный контент
    assert patron["packs"] == ["ep_beach", "nsfw"]     # сортировано
    assert patron["early_content"] is True and patron["watermark"] is True
    # build_info@2: наружу уходит производная метка, а не сам токен — документ
    # целиком уезжает игроку внутри дистрибутива (game/build_id.json).
    assert "patron_token" not in patron
    assert patron["patron_tag"] == patron_tag("tok_abc123")
    assert "tok_abc123" not in json.dumps(patron)


def test_patron_tag_is_short_stable_and_not_the_token():
    """Регрессия на утечку секрета: до build_info@2 токен уезжал игроку как есть."""
    tag = patron_tag("tok_abc123")
    assert tag == patron_tag("tok_abc123")             # детерминирована
    assert len(tag) == 8 and all(c in "0123456789abcdef" for c in tag)
    assert "tok_abc123" not in tag
    assert patron_tag("tok_abc124") != tag             # различает получателей
    assert patron_tag(None) is None and patron_tag("") is None


def test_write_build_info_validates_schema_and_cleanup(tmp_path):
    root = _mk_root(tmp_path)
    info = compute_build_info(root, "public")
    path = write_build_info(root, info)
    assert path == root / BUILD_INFO_REL and path.is_file()
    clear_build_info(root)
    assert not path.exists()

    info["flavor"] = "Не-Слуг"                         # ломаем схему
    with pytest.raises(ReleaseError):
        write_build_info(root, info)


def test_nsfw_globs_only_from_real_dirs(tmp_path):
    root = _mk_root(tmp_path)
    assert nsfw_exclude_globs(root) == []              # нет assets вовсе
    (root / "game" / "assets" / "bg" / "city").mkdir(parents=True)
    assert nsfw_exclude_globs(root) == []              # nsfw-подпапок нет


def test_video_budget_failures(tmp_path):
    root = _mk_root(tmp_path)
    mov = root / "game" / "assets" / "mov" / "demo"
    mov.mkdir(parents=True)
    (mov / "big.webm").write_bytes(b"\0" * (2 * 1024 * 1024))   # 2 МБ > 1 МБ на файл
    failures = budget_failures(root)
    assert any("big.webm" in f and "на файл" in f for f in failures)
    # 2 МБ < video_total_mb: 10 — суммарный бюджет не нарушен
    assert not any("game/assets/mov:" in f for f in failures)


PACK_MANIFEST = """\
schema: pack_manifest@1
id: {pid}
kind: dlc
version: 1.0.0
api_level: {{min: 1, below: 2}}
"""


def _mk_pack(root, pid, chapters=()):
    """Пак на диске: манифест + (опционально) каталоги глав. Генерат сцен — отдельно,
    именно его отсутствие и проверяет охранник."""
    pack = root / "packs" / pid
    (pack / "chapters").mkdir(parents=True)
    (pack / "manifest.yaml").write_text(PACK_MANIFEST.format(pid=pid), encoding="utf-8")
    for ch in chapters:
        (pack / "chapters" / f"{ch}_demo").mkdir()
    return pack


def _run_pack_build(root, pid, monkeypatch):
    from click.testing import CliRunner

    from vn.cli import pack_build

    monkeypatch.chdir(root)                            # _root() ищет корень от cwd
    return CliRunner().invoke(pack_build, [pid])


def test_pack_build_fails_when_declared_chapters_have_no_generated_scenes(tmp_path, monkeypatch):
    """Охранник был мёртв (счётчик общий с манифестом) — пак без генерата уезжал
    архивом из одного манифеста и печатал OK."""
    root = _mk_root(tmp_path)
    _mk_pack(root, "ep_winter", chapters=["ch91"])     # главы объявлены, vn build не звали

    res = _run_pack_build(root, "ep_winter", monkeypatch)
    assert res.exit_code == 1
    assert "ch91" in res.output and "vn build" in res.output
    # Неполный zip не должен оставаться на диске: он выглядит как готовый депот
    assert not (root / "build" / "packs" / "ep_winter.zip").exists()


def test_pack_build_ok_for_container_pack_without_chapters(tmp_path, monkeypatch):
    """packs/nsfw — пак-контейнер для ассетов: глав нет легитимно, «ноль сцен» не ошибка."""
    import zipfile

    root = _mk_root(tmp_path)
    _mk_pack(root, "nsfw")

    res = _run_pack_build(root, "nsfw", monkeypatch)
    assert res.exit_code == 0
    out = root / "build" / "packs" / "nsfw.zip"
    assert zipfile.ZipFile(out).namelist() == ["packs/nsfw/manifest.yaml"]
    # Про «1 файл в архиве» команда обязана сказать вслух, иначе это читается как поломка
    assert "не объявляет глав" in res.output


def test_pack_build_packs_generated_scenes_of_declared_chapters(tmp_path, monkeypatch):
    import zipfile

    root = _mk_root(tmp_path)
    _mk_pack(root, "ep_winter", chapters=["ch91"])
    scenes = root / "game" / "generated" / "scenes" / "ch91"
    scenes.mkdir(parents=True)
    (scenes / "ch91_s010.gen.rpy").write_text("label ch91_s010:\n    return\n", encoding="utf-8")

    res = _run_pack_build(root, "ep_winter", monkeypatch)
    assert res.exit_code == 0
    assert zipfile.ZipFile(root / "build" / "packs" / "ep_winter.zip").namelist() == [
        "packs/ep_winter/manifest.yaml",
        "game/generated/scenes/ch91/ch91_s010.gen.rpy",
    ]
    assert "warning:" not in res.output              # у пака с главами лишней строки нет


def test_release_gate_fails_on_lfs_pointer_fonts(tmp_path):
    """Битый LFS-чекаут не должен превращаться в падающий у игрока дистрибутив:
    гейт обязан валить сборку, даже если конфигурация CI разъехалась."""
    from vn.doctor import _lfs_pointer_fonts

    root = _mk_root(tmp_path)
    fonts = root / "game" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "Ok.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 60)
    (fonts / "Ptr.ttf").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:x\nsize 1\n")

    bad, total = _lfs_pointer_fonts(root)
    assert total == 2 and bad == ["Ptr.ttf"]

    # Та же функция питает и vn doctor, и релизный гейт — один источник истины
    # (иначе одна из проверок разойдётся с другой и снова пропустит указатель).
    from vn import release as rel
    import inspect
    assert "_lfs_pointer_fonts" in inspect.getsource(rel.validate_release)


def test_gate_reports_all_sources_even_when_empty():
    """Молчание гейта при нуле деклараций читалось как «источника нет».
    Провайдеров теперь три (DAZ / VaM / Sims 4), и отчитываться обязаны все:
    иначе выпавшая ветка валидатора незаметна (AUDIT-020)."""
    import inspect

    import vn.release as rel

    src = inspect.getsource(rel.validate_release)
    for label in ("DAZ-декларации", "VaM-декларации", "Sims4-декларации"):
        assert label in src
    # Ни один источник не должен печатать PASS «только если что-то проверено»
    assert "elif vrep.checked" not in src
    assert "elif srep.checked" not in src


def test_built_asset_ids_ignores_derivatives(tmp_path):
    """Выпущенные id ассетов — только референсные варианты: миниатюры, постеры и
    @2 адресуются движком, а не сценарием (AUDIT-013)."""
    import vn.release as rel

    assets = tmp_path / "game" / "assets"
    for rel_path in ("cg/ch01/a.webp", "cg/ch01/a@2.webp", "cg/ch01/a.thumb.webp",
                     "bg/roof/day.webp", "mov/demo/x.webm", "mov/demo/x.poster.webp",
                     "spr/mira/a/base.webp", "spr/mira/a/base@2.webp"):
        p = assets / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    assert rel.built_asset_ids(tmp_path) == [
        "bg/roof/day", "cg/ch01/a", "mov/demo/x", "spr/mira/a/base",
    ]


def test_options_rpy_ships_assets_loose_without_rpa(repo_root):
    """Ассеты едут россыпью намеренно: Steam дельта-патчит отдельные файлы, а
    монолитный .rpa перекачивался бы игроком целиком при правке одного спрайта;
    защиты архив всё равно не добавляет — распаковывается извне (G9).
    Появление .rpa — осознанное решение с ADR (мобильная поставка фазы 3,
    ARCHITECTURE.md §2.4), а не случайная правка options.rpy — её и ловим."""
    import re

    text = (repo_root / "game" / "options.rpy").read_text(encoding="utf-8")
    assert "build.archive" not in text, (
        "в game/options.rpy появился build.archive — desktop-поставка должна "
        "остаться россыпью (Steam delta-патчи); если это осознанно — нужен ADR")
    # Второй путь к .rpa — классификация ассетов в имя архива вместо None
    for pattern, target in re.findall(r"build\.classify\(\s*([^,]+),\s*([^)]+)\)", text):
        if "game/assets" in pattern:
            assert target.strip() == "None", (
                f"game/assets классифицирован в {target.strip()!r} — это упаковка "
                "в архив, см. докстринг теста")
