"""Платформенный слой (ADR-0014): эмиттер platform.gen.rpy, Steam-поставка.

Принцип под тестом: Steam — данные и один файл фасада, не ветвление по коду.
Без appid генерат выключает Steam; депоты и VDF — чистая генерация без
credentials; отсутствие библиотек — предупреждение, а не поломка сборки."""

from __future__ import annotations

import zipfile

import pytest
import yaml

from helpers import mk_root, write_project
from vn.content.compile import _emit_platform
from vn.release import (
    ReleaseError,
    steam_app_build,
    steam_config,
    steam_libs_status,
    steam_stage_content,
)


def test_emit_platform_disabled_by_default():
    out = _emit_platform({}, {}, [("project.yaml", "0" * 16)])
    assert "define config.steam_appid = None" in out
    assert "define VN_STEAM_DLC = {}" in out


def test_emit_platform_appid_and_dlc_map():
    project = {"platform": {"steam": {"appid": 480}}}
    packs = {"ep_beach": {"steam_dlc_appid": 481}, "nsfw": {}}
    out = _emit_platform(project, packs, [("project.yaml", "0" * 16)])
    assert "define config.steam_appid = 480" in out
    assert "define VN_STEAM_DLC = {'ep_beach': 481}" in out   # пак без маппинга не попадает


def _steam_root(tmp_path, repo_root, appid=480, depots=None):
    root = mk_root(tmp_path)
    proj = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8"))
    proj["platform"] = {"steam": {"appid": appid,
                                  "depots": depots if depots is not None
                                  else {"windows": 481, "linux": 482}}}
    (root / "project.yaml").write_text(
        yaml.safe_dump(proj, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (root / "ci" / "steam").mkdir(parents=True)
    src_tmpl = repo_root / "ci" / "steam" / "app_build.vdf.tmpl"
    (root / "ci" / "steam" / "app_build.vdf.tmpl").write_text(
        src_tmpl.read_text(encoding="utf-8"), encoding="utf-8")
    return root


def test_steam_app_build_renders_vdf(tmp_path, repo_root):
    root = _steam_root(tmp_path, repo_root)
    vdf, warnings = steam_app_build(root, "public", branch="beta")
    assert '"AppID" "480"' in vdf
    assert '"SetLive" "beta"' in vdf
    assert '"481"' in vdf and "content/public/windows/*" in vdf
    assert '"482"' in vdf and "content/public/linux/*" in vdf
    assert any("mac" in w for w in warnings)      # депот mac не задан — предупреждение


def test_steam_app_build_requires_appid(tmp_path, repo_root):
    root = _steam_root(tmp_path, repo_root, appid=None)
    with pytest.raises(ReleaseError, match="appid"):
        steam_app_build(root, "public")
    with pytest.raises(ReleaseError, match="appid"):
        steam_config({"platform": {"steam": {"appid": None}}})


def test_steam_app_build_requires_depots(tmp_path, repo_root):
    root = _steam_root(tmp_path, repo_root, depots={})
    with pytest.raises(ReleaseError, match="depots"):
        steam_app_build(root, "public")


def test_steam_stage_content_unpacks_dist(tmp_path, repo_root):
    """Форматы distribute различаются по платформам: win — zip, linux — tar.bz2
    (SDK 00build.rpy). Раскладка обязана понимать оба, иначе Linux-депот молча
    не доезжает, а команда падает после корректной сборки."""
    import tarfile

    root = _steam_root(tmp_path, repo_root)
    dist = root / "build" / "dist" / "0.0.1-public"
    dist.mkdir(parents=True)
    with zipfile.ZipFile(dist / "vn-0.0.1-win.zip", "w") as zf:
        zf.writestr("vn.exe", b"bin")
    payload = dist / "vn.sh"
    payload.write_bytes(b"#!/bin/sh\n")
    with tarfile.open(dist / "vn-0.0.1-linux.tar.bz2", "w:bz2") as tf:
        tf.add(payload, arcname="vn.sh")
    payload.unlink()

    staged, errors = steam_stage_content(root, "public")
    assert sorted(staged) == ["linux", "windows"], errors
    content = root / "build" / "steam" / "content" / "public"
    assert (content / "windows" / "vn.exe").is_file()
    assert (content / "linux" / "vn.sh").is_file()
    # mac-депот не объявлен в project.yaml -> его артефакт и не требуется
    assert errors == []


def test_steam_stage_content_reports_missing_declared_platform(tmp_path, repo_root):
    """Депот объявлен, а артефакта нет — честная ошибка, а не пустой депот."""
    root = _steam_root(tmp_path, repo_root)
    (root / "build" / "dist" / "0.0.1-public").mkdir(parents=True)
    staged, errors = steam_stage_content(root, "public")
    assert staged == []
    assert any("windows" in e for e in errors) and any("linux" in e for e in errors)


def test_steam_stage_content_without_dist(tmp_path, repo_root):
    root = _steam_root(tmp_path, repo_root)
    staged, errors = steam_stage_content(root, "public")
    assert staged == [] and any("vn release build" in e for e in errors)


def test_steam_libs_status_reports_missing(tmp_path):
    assert steam_libs_status(None)                       # SDK не задан — предупреждение
    missing = steam_libs_status(tmp_path)                # пустой SDK — всех трёх нет
    assert len(missing) == 3
    lib = tmp_path / "lib" / "py3-windows-x86_64"
    lib.mkdir(parents=True)
    (lib / "steam_api64.dll").write_bytes(b"x")
    assert len(steam_libs_status(tmp_path)) == 2


def test_platform_facade_is_single_steam_touchpoint(repo_root):
    """Игровой код не знает про Steam: прямые касания _renpysteam/steamapi
    разрешены только фасаду 035_platform.rpy (и генерат-эмиттеру define'ов)."""
    game = repo_root / "game"
    offenders = []
    for f in game.rglob("*.rpy"):
        text = f.read_text(encoding="utf-8")
        if "_renpysteam" in text or "steamapi" in text:
            if f.name != "035_platform.rpy":
                offenders.append(str(f.relative_to(repo_root)))
    assert offenders == [], f"Steam-специфика вне фасада: {offenders}"
