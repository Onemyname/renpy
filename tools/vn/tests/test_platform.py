"""Платформенный слой (ADR-0014): эмиттер platform.gen.rpy, Steam-поставка,
платформенные инварианты вёрстки (подсказки управления).

Принцип под тестом: Steam — данные и один файл фасада, не ветвление по коду.
Без appid генерат выключает Steam; депоты и VDF — чистая генерация без
credentials; отсутствие библиотек — предупреждение, а не поломка сборки."""

from __future__ import annotations

import re
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


# Подсказки управления в вёрстке: vn_ui.hint("<ключ>") (components.rpy).
_HINT_RE = re.compile(r'vn_ui\.hint\(\s*"([a-z0-9_.]+)"\s*\)')


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


def _mk_dist(dist, wrapped=False):
    """Артефакты distribute: win-zip и linux-tar.bz2. wrapped — с каталогом-обёрткой
    по имени артефакта, как их реально отдаёт launcher (prepend для zip/tar.bz2)."""
    import tarfile

    dist.mkdir(parents=True, exist_ok=True)
    win = "vn-0.0.1-win/" if wrapped else ""
    linux = "vn-0.0.1-linux/" if wrapped else ""
    with zipfile.ZipFile(dist / "vn-0.0.1-win.zip", "w") as zf:
        zf.writestr(f"{win}vn.exe", b"bin")
        zf.writestr(f"{win}game/script.rpyc", b"gen")
    payload = dist / "vn.sh"
    payload.write_bytes(b"#!/bin/sh\n")
    with tarfile.open(dist / "vn-0.0.1-linux.tar.bz2", "w:bz2") as tf:
        tf.add(payload, arcname=f"{linux}vn.sh")
    payload.unlink()


def test_steam_stage_content_unpacks_dist(tmp_path, repo_root):
    """Форматы distribute различаются по платформам: win — zip, linux — tar.bz2
    (SDK 00build.rpy). Раскладка обязана понимать оба, иначе Linux-депот молча
    не доезжает, а команда падает после корректной сборки."""
    root = _steam_root(tmp_path, repo_root)
    _mk_dist(root / "build" / "dist" / "0.0.1-public")

    staged, errors = steam_stage_content(root, "public")
    assert sorted(staged) == ["linux", "windows"], errors
    content = root / "build" / "steam" / "content" / "public"
    assert (content / "windows" / "vn.exe").is_file()
    assert (content / "linux" / "vn.sh").is_file()
    # mac-депот не объявлен в project.yaml -> его артефакт и не требуется
    assert errors == []


def test_steam_stage_content_strips_wrapper_dir(tmp_path, repo_root):
    """Депот обязан нести игру В КОРНЕ: путь запуска в Steamworks задаётся от корня
    депота, а артефакты distribute завёрнуты в каталог с именем и ВЕРСИЕЙ сборки —
    без разворачивания его пришлось бы править руками после каждого бампа."""
    root = _steam_root(tmp_path, repo_root)
    _mk_dist(root / "build" / "dist" / "0.0.1-public", wrapped=True)

    staged, errors = steam_stage_content(root, "public")
    assert sorted(staged) == ["linux", "windows"], errors
    content = root / "build" / "steam" / "content" / "public"
    assert (content / "windows" / "vn.exe").is_file()
    assert (content / "windows" / "game" / "script.rpyc").is_file()
    assert not (content / "windows" / "vn-0.0.1-win").exists()
    # tar.bz2 завёрнут так же — разворачивается тем же правилом
    assert [p.name for p in sorted((content / "linux").iterdir())] == ["vn.sh"]


def test_steam_stage_content_keeps_mac_app_bundle(tmp_path, repo_root):
    """app-zip идёт БЕЗ обёртки: в корне лежит сам VN.app — единственный верхний
    каталог, и поднятие его Contents/ в корень депота сломало бы приложение."""
    root = _steam_root(tmp_path, repo_root, depots={"mac": 483})
    dist = root / "build" / "dist" / "0.0.1-public"
    dist.mkdir(parents=True)
    with zipfile.ZipFile(dist / "vn-0.0.1-mac.zip", "w") as zf:
        zf.writestr("VN.app/Contents/MacOS/VN", b"bin")

    staged, errors = steam_stage_content(root, "public")
    assert staged == ["mac"], errors
    assert (root / "build" / "steam" / "content" / "public" / "mac"
            / "VN.app" / "Contents" / "MacOS" / "VN").is_file()


def test_steam_stage_content_refuses_ambiguous_wrapper(tmp_path, repo_root):
    """Внутри обёртки занято её же имя: поднять содержимое без потери файла нельзя,
    и депот с чужой раскладкой хуже отсутствующего — честная ошибка."""
    root = _steam_root(tmp_path, repo_root, depots={"windows": 481})
    dist = root / "build" / "dist" / "0.0.1-public"
    dist.mkdir(parents=True)
    with zipfile.ZipFile(dist / "vn-0.0.1-win.zip", "w") as zf:
        zf.writestr("vn-0.0.1-win/vn-0.0.1-win/vn.exe", b"bin")

    staged, errors = steam_stage_content(root, "public")
    assert staged == []
    assert any("vn-0.0.1-win" in e and "windows" in e for e in errors)


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


def test_main_menu_exposes_persistent_collections(repo_root):
    """Галерея и достижения обязаны быть достижимы из ГЛАВНОГО меню, а не только
    из игрового: их состояние живёт в persistent, и игрок без активного сейва
    иначе не может посмотреть открытое. Гейты — те же, что в рельсе, чтобы
    пустой раздел не показывался."""
    src = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "core_screens.rpy").read_text(encoding="utf-8")
    menu = src.split("screen main_menu():", 1)[1].split("\nstyle ", 1)[0]
    for screen_name, gate in (("gallery", "vn_gal.categories()"),
                              ("achievements", "vn_ach.visible_ids()")):
        assert f'ShowMenu("{screen_name}")' in menu, \
            f"{screen_name} недостижим из главного меню"
        assert gate in menu, f"{screen_name} в главном меню без гейта {gate}"


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


def test_control_hints_declare_both_key_variants(repo_root):
    """Подсказка управления читает ПАРУ ключей: vn_ui.hint("X") отдаёт X_pad на
    controller-first окружении (Deck/Big Picture) и X_kbd на остальных. Забытая
    половина не падает и не видна разработчику: vn_loc.t вернёт сам ключ, и
    ровно на том окружении, которое он не открывает.

    Проверкой «ключ vn_loc.t объявлен» такая пара не ловится по построению —
    ключ собирается конкатенацией в рантайме, в исходнике его нет. Отсюда
    отдельный гард, и живёт он здесь: пара существует ИЗ-ЗА платформы.

    Разбор вёрстки регексом допустим: тест сторожит исходник и компилятором не
    является (G24 — про Content Compiler), а вызовов hint в UI единицы."""
    from vn.repo import load_yaml

    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    calls = {}
    for f in sorted((repo_root / "game").rglob("*.rpy")):
        for key in _HINT_RE.findall(f.read_text(encoding="utf-8")):
            calls.setdefault(key, set()).add(str(f.relative_to(repo_root)))

    # Парсер молча «починился бы», сломавшись: подсказки в вёрстке есть.
    assert "ui.history.hint" in calls, calls
    for key, where in sorted(calls.items()):
        for suffix in ("_kbd", "_pad"):
            assert key + suffix in strings, (
                f"{key}{suffix}: нет в content/ui/strings.yaml — "
                f"{sorted(where)} покажет игроку сам ключ вместо подсказки")

# ── Платформенные возможности, добавленные 2026-08-18 ────────────────────────

def test_beta_badge_is_driven_by_platform(repo_root):
    """Плашка «BETA» берёт имя ветки у платформы, а не у флейвора: тестер обязан
    видеть бету в ЛЮБОЙ сборке, а вотермарка включена только у patron."""
    overlay = (repo_root / "game" / "framework" / "20_ui" / "screens"
               / "build_overlay.rpy").read_text(encoding="utf-8")
    assert "vn_platform.beta_branch()" in overlay
    assert 'config.overlay_screens.append("vn_beta_overlay")' in overlay
    facade = (repo_root / "game" / "framework" / "00_core"
              / "035_platform.rpy").read_text(encoding="utf-8")
    assert "def beta_branch(" in facade and "get_current_beta_name" in facade


def test_store_offer_never_leaves_dead_button(repo_root):
    """Непринадлежащая глава показывается ТОЛЬКО когда платформа умеет открыть
    магазин: иначе карточка была бы кнопкой, которая ничего не делает."""
    facade = (repo_root / "game" / "framework" / "00_core"
              / "035_platform.rpy").read_text(encoding="utf-8")
    assert "def store_page(" in facade and "activate_overlay_to_store" in facade
    # None при отсутствии Steam/маппинга/оверлея — три причины, все проверяются
    store = facade.split("def store_page(", 1)[1].split("def ", 1)[0]
    assert "overlay_enabled()" in store and "VN_STEAM_DLC" in store

    card = (repo_root / "game" / "framework" / "20_ui"
            / "components.rpy").read_text(encoding="utf-8")
    assert "vn_platform.store_page(ch[\"pack\"])" in card

    emitter = (repo_root / "tools" / "vn" / "src" / "vn" / "content"
               / "scenes.py").read_text(encoding="utf-8")
    assert "vn_platform.store_page(ch[\"pack\"]) is not None" in emitter


def test_crash_report_records_platform_profile(repo_root):
    """Мобильная и Deck-ветки отличаются от десктопной только вариантами —
    без строки платформы «на телефоне мелкий шрифт» неотличимо по трейсбеку."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "070_crash.rpy").read_text(encoding="utf-8")
    assert "vn_platform.describe()" in src


def test_save_name_feeds_slots_and_timeline(repo_root):
    """save_name — штатное «где я в игре»: движок кладёт его в заголовок слота и
    открывает по нему фазу Steam Timeline. Значение — локализованный заголовок
    главы, а не служебный id."""
    flow = (repo_root / "game" / "framework" / "00_core"
            / "030_flow.rpy").read_text(encoding="utf-8")
    assert "renpy.store.save_name = renpy.store.vn_registry.chapter_title(" in flow
    registry = (repo_root / "game" / "framework" / "00_core"
                / "010_registry.rpy").read_text(encoding="utf-8")
    assert "def chapter_title(" in registry and "vn_loc.t(row[\"title_key\"])" in registry


def test_achievement_sync_button_uses_engine_action(repo_root):
    """Синхронизацию делает движковый achievement.Sync: своей логики «доталкивания»
    в платформу мы не пишем — она уже есть и знает про все бэкенды."""
    src = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "core_screens.rpy").read_text(encoding="utf-8")
    assert "achievement.Sync()" in src

def test_every_control_hint_has_both_key_variants(repo_root):
    """`vn_ui.hint("X")` читает ПАРУ ключей: `X_kbd` и `X_pad`. Забытый суффикс не
    падает — `vn_loc.t` вернёт сам ключ, и игрок увидит `ui.history.hint_pad`
    строкой на экране. Механизм парных подсказок есть, страховки к нему не было."""
    import re

    strings = (repo_root / "content" / "ui" / "strings.yaml").read_text(encoding="utf-8")
    used = set()
    for rpy in sorted((repo_root / "game" / "framework").rglob("*.rpy")):
        used |= set(re.findall(r'vn_ui\.hint\("([a-z0-9_.]+)"\)', rpy.read_text(encoding="utf-8")))
    assert used, "ни одной подсказки не найдено — проверка выродилась"
    for key in sorted(used):
        for suffix in ("_kbd", "_pad"):
            assert f"{key}{suffix}:" in strings, (
                f"{key}{suffix} нет в content/ui/strings.yaml — игрок увидит ключ "
                f"вместо подсказки на {'паде' if suffix == '_pad' else 'клавиатуре'}")
