"""Флейворы и build-info (ADR-0006): конфиг, вычисление исключений, схема,
бюджеты видео. Полный validate_release гоняется в CI/вручную (нужен SDK) —
здесь юнит-уровень."""

import shutil

import pytest

from vn.release import (BUILD_INFO_REL, ReleaseError, budget_failures,
                        clear_build_info, compute_build_info, flavor_config,
                        nsfw_exclude_globs, write_build_info)

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
    assert info["schema"] == "build_info@1"
    assert info["nsfw"] is False and info["watermark"] is False
    assert info["exclude"] == ["game/assets/cg/nsfw/**", "game/assets/mov/nsfw/**"]
    assert info["build_id"].startswith("0.2.0+")
    assert ".public." in info["build_id"]

    patron = compute_build_info(root, "patron", patron_token="tok_abc123")
    assert patron["exclude"] == []                     # полный контент
    assert patron["packs"] == ["ep_beach", "nsfw"]     # сортировано
    assert patron["patron_token"] == "tok_abc123"
    assert patron["early_content"] is True and patron["watermark"] is True


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
