"""Платформенный слой (ADR-0014): эмиттер platform.gen.rpy, Steam-поставка,
платформенные инварианты вёрстки (подсказки управления).

Принцип под тестом: Steam — данные и один файл фасада, не ветвление по коду.
Без appid генерат выключает Steam; депоты и VDF — чистая генерация без
credentials; отсутствие библиотек — предупреждение, а не поломка сборки."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
import yaml

from helpers import mk_root, write_project
from vn.content.compile import _emit_platform
from vn.release import (
    ReleaseError,
    steam_app_build,
    steam_config,
    steam_libs_status,
    _extract_archive,
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


def _exec_zipinfo(name):
    """Запись zip с битом исполняемости — так их кладёт САМ Ren'Py
    (SDK launcher/game/package_formats.rpy: external_attr = 0o100755 << 16).
    Фикстура без прав была бы неверной моделью артефакта: mac-депот, собранный
    из такого архива, у игрока не запускается — а тест этого не замечал."""
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o100755 << 16
    return info


def _mk_dist(dist, wrapped=False):
    """Артефакты distribute: win-zip и linux-tar.bz2. wrapped — с каталогом-обёрткой
    по имени артефакта, как их реально отдаёт launcher (prepend для zip/tar.bz2)."""
    import io
    import tarfile

    dist.mkdir(parents=True, exist_ok=True)
    win = "vn-0.0.1-win/" if wrapped else ""
    linux = "vn-0.0.1-linux/" if wrapped else ""
    with zipfile.ZipFile(dist / "vn-0.0.1-win.zip", "w") as zf:
        zf.writestr(_exec_zipinfo(f"{win}vn.exe"), b"bin")
        zf.writestr(f"{win}game/script.rpyc", b"gen")
    body = b"#!/bin/sh\n"
    with tarfile.open(dist / "vn-0.0.1-linux.tar.bz2", "w:bz2") as tf:
        # TarInfo вручную, а не tf.add(файл): режим взялся бы из файловой системы,
        # а на Windows x-бита в ней нет — фикстура молча стала бы неисполняемой,
        # то есть моделировала бы ровно тот дефект, который проверяется ниже.
        ti = tarfile.TarInfo(f"{linux}vn.sh")
        ti.size = len(body)
        ti.mode = 0o755
        tf.addfile(ti, io.BytesIO(body))


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
        zf.writestr(_exec_zipinfo("VN.app/Contents/MacOS/VN"), b"bin")

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
    # Пункты берутся из ОБЩЕГО списка, а не из тела main_menu: два независимых
    # перечня и были причиной «шафла» — порядок в них разошёлся, и пункты прыгали
    # при переходе из главного меню в подэкран. Поэтому здесь два утверждения:
    # главное меню действительно берёт общий список, и в нём есть эти разделы под
    # своими гейтами. Читать тело main_menu, как раньше, теперь значило бы
    # требовать возврата второго перечня.
    menu = src.split("screen main_menu():", 1)[1].split("\nstyle ", 1)[0]
    assert "use vn_nav_items(" in menu, (
        "главное меню больше не берёт общий список пунктов — перечни разъедутся")
    items = src.split("screen vn_nav_items(", 1)[1].split("\nscreen ", 1)[0]
    # Гейт — дешёвый предикат «есть ли что показывать»: главное меню рисуется
    # постоянно, и строить ради ответа «да/нет» отсортированный реестр нельзя.
    for screen_name, gate in (("gallery", "vn_gal.has_visible()"),
                              ("achievements", "vn_ach.has_visible()")):
        assert f'ShowMenu("{screen_name}")' in items, \
            f"{screen_name} недостижим из главного меню"
        assert gate in items, f"{screen_name} в главном меню без гейта {gate}"
    # Карта главы — тот же случай, и её отсутствие в колонне главного меню было
    # отдельной жалобой: пункт появлялся «только после захода в главы», хотя его
    # гейт vn_story.has_chapters() в главном меню истинен.
    assert 'ShowMenu("story_flow")' in items, "карта главы недостижима из главного меню"
    assert "vn_story.has_chapters()" in items, "карта главы в главном меню без гейта"


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


def test_beta_branch_is_read_at_init_and_never_at_runtime(repo_root):
    """Два инварианта, и оба ломаются молча.

    (1) Плашку беты рисует overlay-экран, то есть beta_branch() зовётся на каждой
    интеракции и в предикции: обращаться из неё к платформе запрещает свой же
    регламент (030_flow.rpy), поэтому в теле функции не должно быть вызовов Steam.

    (2) Значение обязано присваиваться ТОЛЬКО в init. Рантайм-присваивание
    переменной стора движок считает изменением и кладёт её в сейв (python.py:
    get_changes -> ever_been_changed; фильтра по «_» там нет) — то есть ветка
    чужой машины приезжала бы игроку из сейва."""
    facade = (repo_root / "game" / "framework" / "00_core"
              / "035_platform.rpy").read_text(encoding="utf-8")
    body = facade.split("def beta_branch(", 1)[1].split("\n    def ", 1)[0]
    code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
    assert "get_current_beta_name" not in code and "steam()" not in code, \
        "beta_branch обращается к платформе — это выражение экрана, так нельзя"
    assert "global _beta" not in code, "рантайм-присваивание _beta уедет в сейв"
    assert "return _beta" in code

    # Чтение — из init-блока, где Steam уже поднят движком (init -1499).
    init999 = facade.split("init 999 python:", 1)[1]
    assert "vn_platform._beta = vn_platform._read_beta_branch()" in init999
    assert "get_current_beta_name" in facade.split("def _read_beta_branch(", 1)[1]


def test_dev_console_is_gated_by_developer_flag(repo_root):
    """Второй слой защиты dev-зоны. Первый (вырезание 90_debug из поставки,
    options.rpy) держится на одной строке classify — регрессия в упаковке
    открывала бы игроку консоль. Гейт возможен: в 8.5.3 config.developer к
    обычному init — настоящий bool (движок разрешает его на init -1000), а не
    строка "auto", как утверждал прежний комментарий файла."""
    dev = (repo_root / "game" / "framework" / "90_debug"
           / "010_dev.rpy").read_text(encoding="utf-8")
    assert "config.console = bool(config.developer)" in dev
    assert "config.console = True" not in dev


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


def test_zip_extraction_restores_the_executable_bit(tmp_path):
    """zipfile прав НЕ переносит: CPython ZipFile._extract_member открывает цель
    обычным open(targetpath, "wb") и external_attr не читает вообще. Ren'Py права
    в архив кладёт и при своей распаковке восстанавливает их руками
    (SDK launcher/game/installer.py) — значит это обязан делать и наш конвейер,
    иначе .app уезжает в депот с 0644 и Steam на macOS его не запускает.

    Раньше тест целиком скипался вне POSIX — и это делало ЕДИНСТВЕННЫЙ гейт,
    наблюдающий x-бит, неисполняемым на машине владельца (все 13 skipped в наборе
    ровно такого рода). Класс «архив теряет права» из-за этого не проверялся ни
    разу, и второй его экземпляр (android.install_rapt) появился незамеченным.
    Поэтому проверка разделена: наблюдение st_mode остаётся POSIX-only, а
    наблюдение КОДА (читает ли он external_attr, зовёт ли chmod) идёт всегда —
    тот же приём, что в test_peak_rss_is_measured_on_every_platform."""
    import os
    import stat

    # Часть, работающая на любой ОС: распаковка обязана СПРАШИВАТЬ права у архива.
    helper = (Path(__file__).resolve().parents[3] / "tools" / "vn" / "src" / "vn"
              / "archive.py").read_text(encoding="utf-8")
    assert "external_attr" in helper and "chmod" in helper,         "распаковка перестала восстанавливать права — .app уедет в депот с 0644"

    if os.name != "posix":
        pytest.skip("наблюдение st_mode возможно только на POSIX (проверка кода выше)")

    src = tmp_path / "a.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr(_exec_zipinfo("VN.app/Contents/MacOS/VN"), b"bin")
        zf.writestr("VN.app/Contents/Info.plist", b"<plist/>")
    dest = tmp_path / "out"
    _extract_archive(src, dest)

    exe = dest / "VN.app" / "Contents" / "MacOS" / "VN"
    plain = dest / "VN.app" / "Contents" / "Info.plist"
    assert exe.stat().st_mode & stat.S_IXUSR, "бит исполняемости потерян"
    assert not (plain.stat().st_mode & stat.S_IXUSR), \
        "права выставлены не по архиву, а всем подряд"


def test_stage_refuses_depot_without_any_executable(tmp_path, repo_root):
    """Депот, в котором нет ни одного исполняемого файла, не запустится у игрока —
    и это единственный момент, когда такое ещё можно заметить: сборка, VDF и
    аплоад проходят целиком, а дефект виден только на живой macOS.

    Спрашиваем архив, а не распакованное дерево: артефакт одинаков на любом
    хосте, а x-бит после распаковки на Windows не существует в принципе."""
    root = _steam_root(tmp_path, repo_root, depots={"mac": 483})
    dist = root / "build" / "dist" / "0.0.1-public"
    dist.mkdir(parents=True)
    with zipfile.ZipFile(dist / "vn-0.0.1-mac.zip", "w") as zf:
        zf.writestr("VN.app/Contents/MacOS/VN", b"bin")     # БЕЗ прав

    staged, errors = steam_stage_content(root, "public")
    assert staged == []
    assert any("бит" in e and "mac" in e for e in errors), errors


def test_peak_rss_is_measured_on_every_platform(repo_root):
    """perf.json обязан писаться ВСЕГДА, даже когда измерить нечем.

    Раньше весь блок дампа падал на `import resource` — модуля нет на Windows, —
    файла не появлялось, а гейт бюджета трактовал «числа нет» как «в рамках».
    То есть baseline_rss_mb на Windows не проверялся вообще и молчал об этом.

    Windows-ветка идёт через GetProcessMemoryInfo, и argtypes/restype там
    обязательны: без них ctypes считает HANDLE обычным int, на 64 битах усекает
    его — вызов возвращает 0, то есть «не измерили» вместо числа. Ровно на этом
    первая редакция и споткнулась, поэтому типы закреплены тестом."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "030_flow.rpy").read_text(encoding="utf-8")
    fn = src.split("def _peak_rss(", 1)[1].split("\n    def ", 1)[0]

    assert "K32GetProcessMemoryInfo" in fn and "resource" in fn, \
        "измеряется не на всех платформах"
    assert "restype = wintypes.HANDLE" in fn, \
        "HANDLE без restype усекается на 64 битах — вызов вернёт 0"
    assert "argtypes" in fn and "wintypes.BOOL" in fn
    # Ни одна ветка не имеет права вернуть «ничего»: только число или явный None
    # с причиной — иначе гейт снова не отличит «не измерили» от «в рамках».
    assert fn.count('"baseline_rss_mb"') >= 4
    assert '"why"' in fn

    dump = src.split("def autopilot_finish(", 1)[1].split("\n    def ", 1)[0]
    assert "_peak_rss()" in dump and "perf.json" in dump
