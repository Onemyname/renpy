"""Android-поставка (RAPT): готовность тулчейна, предпосылки проекта, секреты.

Принцип под тестом: тулчейн ставится ТОЛЬКО в лаунчере (RAPT — апдейтер, Android
SDK — Install SDK, ключи — Generate Keys), поэтому от нашего кода требуется одно —
точно сказать, чего не хватает и каким шагом это ставится, и ничего не выдумать про
то, чего он проверить не может. Плюс инварианты поставки: секретов в репозитории и
в дистрибутиве нет, потолок канала считается по тому, что РЕАЛЬНО уедет в пакет.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from helpers import mk_root
from vn import android
from vn.android import (
    AndroidError,
    build_apk,
    find_adb,
    jdk_major,
    keystore_leaks,
    oversample_suffixes,
    package_facts,
    preflight,
    rapt_status,
    setup_step,
)
from vn.assets.render_config import load_render_config

MB = android.MB

no_windows = pytest.mark.skipif(sys.platform == "win32",
                                reason="фейковый javac — sh-скрипт")
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="нужен git")


# ── Синтетические окружения ───────────────────────────────────────────────────

def _mk_sdk(tmp_path, *, rapt=True, hash_ok=True, adb=True):
    """SDK нужной степени готовности: launcher/game/rapt_hash.txt есть всегда
    (как в настоящем SDK), rapt/ и Android SDK — по флагам."""
    sdk = tmp_path / "sdk"
    (sdk / "launcher" / "game").mkdir(parents=True)
    (sdk / "launcher" / "game" / "rapt_hash.txt").write_text("deadbeef\n", encoding="utf-8")
    if rapt:
        rapt_dir = sdk / "rapt"
        rapt_dir.mkdir()
        (rapt_dir / "hash.txt").write_text(
            "deadbeef\n" if hash_ok else "otherhash\n", encoding="utf-8")
        if adb:
            tools = rapt_dir / "android-sdk" / "platform-tools"
            tools.mkdir(parents=True)
            (tools / "adb").write_bytes(b"")
    return sdk


def _configure_project(root):
    """Проект в состоянии «лаунчер уже сделал Generate Keys и Configure»."""
    for name in ("android.keystore", "bundle.keystore"):
        (root / name).write_bytes(b"not-a-real-key")
    (root / ".android.json").write_text(
        json.dumps({"package": "com.example.vn"}), encoding="utf-8")


def _game_file(root, rel, mb):
    path = root / "game" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * int(mb * MB))
    return path


def _fake_javac(tmp_path, text, *, stream=1):
    """JDK-раскладка с фейковым javac: JAVA_HOME важнее PATH, поэтому проверяется
    именно он. stream=2 — старая Java печатала версию в stderr."""
    home = tmp_path / "jdk"
    (home / "bin").mkdir(parents=True)
    exe = home / "bin" / "javac"
    exe.write_text(f'#!/bin/sh\necho "{text}" 1>&{stream}\n', encoding="utf-8")
    exe.chmod(0o755)
    return home


def _topics(gaps):
    return " | ".join(gaps)


# ── rapt_status: пусто / частично / полно ─────────────────────────────────────

def test_rapt_status_without_sdk_names_the_env_var():
    gaps = rapt_status(None)
    assert len(gaps) == 1 and "RENPY_SDK" in gaps[0]


def test_rapt_status_empty_sdk_names_the_setup_command(tmp_path):
    """Без rapt/ остальные проверки бессмысленны: ровно один пункт, и он называет
    команду, которая это лечит (и лаунчер как второй путь)."""
    gaps = rapt_status(_mk_sdk(tmp_path, rapt=False), tmp_path / "repo")
    assert len(gaps) == 1
    assert "RAPT" in gaps[0] and "setup sdk --download-rapt" in gaps[0]
    assert "лаунчер" in gaps[0]


def test_rapt_status_hash_mismatch_is_reported(tmp_path):
    """Лаунчер не импортирует RAPT с чужим hash.txt (check_hash_txt) — молчать об
    этом нельзя: снаружи это выглядит как «RAPT есть, но сборки нет»."""
    gaps = rapt_status(_mk_sdk(tmp_path, hash_ok=False))
    assert any("другой версии SDK" in g for g in gaps)


def test_rapt_status_missing_android_sdk(tmp_path):
    gaps = rapt_status(_mk_sdk(tmp_path, adb=False))
    assert any("adb" in g and "setup sdk" in g for g in gaps)


def test_rapt_status_accepts_external_sdk_via_sdk_txt(tmp_path):
    """rapt/sdk.txt (doc/android.html, Step 2) — штатный способ не качать SDK
    заново: adb ищется по указанному пути."""
    sdk = _mk_sdk(tmp_path, adb=False)
    external = tmp_path / "android-sdk-elsewhere" / "platform-tools"
    external.mkdir(parents=True)
    (external / "adb").write_bytes(b"")
    (sdk / "rapt" / "sdk.txt").write_text(str(external.parent) + "\n", encoding="utf-8")
    assert find_adb(sdk) == external / "adb"
    assert not any("adb" in g for g in rapt_status(sdk))


def test_rapt_status_project_side_gaps(tmp_path):
    """Ключи и конфиг живут в КОРНЕ ПРОЕКТА (launcher: keys_exist(project.path)),
    поэтому без root эта часть не проверяется, а с root — перечисляется."""
    sdk = _mk_sdk(tmp_path)
    root = mk_root(tmp_path)
    gaps = _topics(rapt_status(sdk, root))
    assert "android.keystore" in gaps and "bundle.keystore" in gaps
    assert "setup keys" in gaps and "setup config" in gaps
    assert "android.keystore" not in _topics(rapt_status(sdk))


def test_rapt_status_full_leaves_only_jdk_question(tmp_path):
    """Полностью готовое окружение: не остаётся НИ ОДНОГО пункта про rapt, adb,
    ключи и конфиг. Про JDK судить нельзя — он зависит от машины, а не от нас."""
    sdk = _mk_sdk(tmp_path)
    root = mk_root(tmp_path)
    _configure_project(root)
    gaps = rapt_status(sdk, root)
    assert all("javac" in g or "JDK" in g for g in gaps), gaps


# ── JDK ───────────────────────────────────────────────────────────────────────

@no_windows
@pytest.mark.parametrize("text,stream,expected", [
    ("javac 21.0.5", 1, 21),
    ("javac 24", 1, 24),
    ("javac 1.8.0_292", 2, 8),        # Java 8: мажор — вторая цифра, вывод в stderr
    ("no version here", 1, None),
])
def test_jdk_major_parses_both_formats(tmp_path, monkeypatch, text, stream, expected):
    monkeypatch.setenv("JAVA_HOME", str(_fake_javac(tmp_path, text, stream=stream)))
    assert jdk_major() == expected


@no_windows
def test_rapt_status_rejects_old_jdk(tmp_path, monkeypatch):
    monkeypatch.setenv("JAVA_HOME", str(_fake_javac(tmp_path, "javac 17.0.9")))
    gaps = rapt_status(_mk_sdk(tmp_path))
    assert any(f"JDK {android.JDK_REQUIRED}+" in g for g in gaps)


# ── Предпосылки проекта: что реально уедет в пакет ────────────────────────────

def test_oversample_suffixes_come_from_render_profile(tmp_path):
    """Набор масштабов решает project.yaml (ADR-0012): суффиксы считаются, а не
    зашиты списком — иначе '@4' в профиле молча выпал бы из подсчёта."""
    root = mk_root(tmp_path, render_extra={"classes": {"bg": {"variants": [1, 2, 4]}}})
    assert oversample_suffixes(load_render_config(root)) == {"@2", "@4"}


def test_preflight_counts_only_what_ships(tmp_path):
    root = mk_root(tmp_path)
    _game_file(root, "assets/bg/room.webp", 1.5)
    _game_file(root, "assets/bg/room@2.webp", 3.0)
    rep = preflight(root)
    assert rep.game_mb == pytest.approx(4.5, abs=0.01)
    assert rep.oversample_mb == pytest.approx(3.0, abs=0.01)
    # @N-варианты классифицированы в desktop-списки (game/options.rpy) и в пакет
    # не едут — считаем только референсы плюс накладные расходы самого пакета.
    assert rep.mobile_mb == pytest.approx(1.5 + android.PACKAGE_OVERHEAD_MB, abs=0.01)
    assert rep.ok


def test_preflight_blocks_when_channel_limit_exceeded(tmp_path, monkeypatch):
    monkeypatch.setattr(android, "PACKAGE_OVERHEAD_MB", 0)
    monkeypatch.setattr(android, "PACKAGE_LIMIT_MB", 1)
    root = mk_root(tmp_path)
    _game_file(root, "assets/bg/room.webp", 1.5)
    rep = preflight(root)
    assert not rep.ok
    assert any("universal APK" in e and "не соберётся" in e for e in rep.errors)


def test_preflight_warns_before_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(android, "PACKAGE_OVERHEAD_MB", 0)
    monkeypatch.setattr(android, "PACKAGE_LIMIT_MB", 2)
    root = mk_root(tmp_path)
    _game_file(root, "assets/bg/room.webp", 1.8)   # 90 % потолка
    rep = preflight(root)
    assert rep.ok and any("потолка" in w for w in rep.warnings)


def test_preflight_bundle_rejects_oversized_file(tmp_path, monkeypatch):
    """Play-бандл режется на 4 пакета по 500 МБ, и один файл целиком живёт в одном
    пакете: крупный файл — блокер именно бандла, а не APK (doc/android.html)."""
    monkeypatch.setattr(android, "BUNDLE_PACK_LIMIT_MB", 1)
    root = mk_root(tmp_path)
    _game_file(root, "assets/mov/intro.webm", 1.5)
    assert any("intro.webm" in e for e in preflight(root, bundle=True).errors)
    assert not any("intro.webm" in e for e in preflight(root, bundle=False).errors)


def test_preflight_uses_mobile_memory_profile(tmp_path):
    """Мобильный лимит кэша приезжает из project.yaml (render.mobile) и участвует
    в расчёте — иначе мобильный бюджет памяти был бы десктопным."""
    root = mk_root(tmp_path, render_extra={"mobile": {"image_cache_mb": 32}})
    assert preflight(root).mobile_cache_mb == 32


def test_preflight_flags_mobile_cache_above_desktop(tmp_path):
    root = mk_root(tmp_path, render_extra={"mobile": {"image_cache_mb": 4096}})
    rep = preflight(root)
    assert any("не меньше десктопного" in w for w in rep.warnings)


def test_preflight_reminds_about_icons(tmp_path):
    rep = preflight(mk_root(tmp_path))
    assert any("android-icon_foreground.png" in w for w in rep.warnings)
    assert any("android-presplash.jpg" in w for w in rep.warnings)


def test_render_config_for_mobile_changes_only_the_cache(tmp_path):
    root = mk_root(tmp_path, render_extra={"mobile": {"image_cache_mb": 32}})
    cfg = load_render_config(root)
    mob = cfg.for_mobile()
    assert (mob.image_cache_mb, cfg.image_cache_mb) == (32, 64)
    assert mob.cache_limit_px < cfg.cache_limit_px
    assert (mob.screen, mob.cache_generations, mob.classes) == (
        cfg.screen, cfg.cache_generations, cfg.classes)


def test_mobile_cache_limit_reaches_the_engine(tmp_path):
    """Мобильный лимит кэша обязан доезжать до движка, а не только до preflight:
    на телефоне десктопный потолок означает вытеснение образов под давлением ОС.
    Ветка — условие по варианту, а не второй define на тот же config."""
    from vn.content.compile import _emit_render

    root = mk_root(tmp_path, render_extra={"mobile": {"image_cache_mb": 32}})
    out = _emit_render(root, [])
    assert "define config.image_cache_size_mb = 64" in out
    assert "if renpy.variant('mobile'):" in out
    assert "config.image_cache_size_mb = 32" in out
    assert out.count("define config.image_cache_size_mb") == 1


# ── Секреты: ключей подписи нет ни в git, ни в конфиге ────────────────────────

@needs_git
def test_keystore_not_ignored_is_a_blocker(tmp_path):
    root = mk_root(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "android.keystore").write_bytes(b"key")
    errors, _ = keystore_leaks(root)
    assert any("не игнорируется git" in e for e in errors)


@needs_git
def test_ignored_keystore_is_clean(tmp_path):
    root = mk_root(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("*.keystore\n", encoding="utf-8")
    (root / "android.keystore").write_bytes(b"key")
    assert keystore_leaks(root) == ([], [])


@needs_git
def test_tracked_keystore_is_a_blocker(tmp_path):
    """Ключ, попавший в git, считается скомпрометированным навсегда: .gitignore
    его уже не спасает, поэтому это отдельный, более резкий вердикт."""
    root = mk_root(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("*.keystore\n", encoding="utf-8")
    (root / "android.keystore").write_bytes(b"key")
    subprocess.run(["git", "add", "-f", "android.keystore"], cwd=root, check=True)
    errors, _ = keystore_leaks(root)
    assert any("под версионным контролем" in e for e in errors)


def test_no_keystore_no_verdict(tmp_path):
    assert keystore_leaks(mk_root(tmp_path)) == ([], [])


def test_project_schema_carries_no_android_secrets(repo_root):
    """В project.yaml нет и не должно появиться полей под пароли/ключи подписи:
    мобильные настройки — это числа профиля памяти, а не credentials."""
    text = (repo_root / "tools" / "schemas" / "project@1.schema.json").read_text(
        encoding="utf-8").lower()
    for word in ("keystore", "password", "passphrase", "secret", "token", "credential"):
        assert word not in text, f"схема проекта упоминает {word}"


def test_options_excludes_keystores_and_oversample_from_mobile(repo_root):
    """Два инварианта дистрибутива в game/options.rpy:
    1) ключи подписи не уезжают игрокам (корневые файлы иначе попадают в "all");
    2) @N-варианты не уезжают в мобильные пакеты, и этот паттерн стоит ПОСЛЕ
       флейворных исключений — правило первого совпадения иначе вернуло бы
       NSFW-ассеты с суффиксом @N в desktop-поставку SFW-флейвора."""
    text = (repo_root / "game" / "options.rpy").read_text(encoding="utf-8")
    assert 'build.classify("**.keystore", None)' in text
    oversample = text.index('build.classify("**@[2-9].*", "windows linux mac")')
    assert oversample > text.index("build_id.json")


def test_touch_targets_are_token_driven(repo_root):
    """Тач-профиль живёт в токенах (scale.rpy), а не в копиях экранов: quick menu
    читает gui.touch_min, а сам токен нулевой на десктопе."""
    scale = (repo_root / "game" / "framework" / "20_ui" / "scale.rpy").read_text(encoding="utf-8")
    quick = (repo_root / "game" / "framework" / "20_ui" / "screens" / "quick_menu.rpy").read_text(
        encoding="utf-8")
    assert "define gui.touch_min = gui.vn_touch_min()" in scale
    assert "xminimum gui.touch_min" in quick and "yminimum gui.touch_min" in quick
    assert "vn_platform.is_mobile()" in scale


DESKTOP_ONLY_CONTROLS = ("Quit(", 'Preference("display"')

DESKTOP_GATE = "if vn_platform.is_desktop():"


def test_desktop_only_controls_are_gated(repo_root):
    """«Выйти» и переключатель окно/полный экран существуют только на десктопе:
    на iOS кнопка выхода запрещена правилами стора, на Android приложение снимает
    система, а окном на мобильном не управляют вовсе. Гард на текст экрана, а не
    на прогон: ветка выбирается вариантом (RENPY_VARIANT), и её легко потерять при
    следующей правке — тогда мобильная поставка молча вернёт мёртвые пункты.

    Проверяется не число вхождений (оно меняется с каждым экраном), а то, что у
    каждого такого управления есть ОХВАТЫВАЮЩИЙ гейт: строка `if
    vn_platform.is_desktop():` выше по файлу с меньшим отступом, между которой и
    управлением нет строк с отступом меньше её (иначе блок уже закрылся).

    Смотрим только внутрь `screen`: config.quit_action — обработчик закрытия окна
    ОС (крестик/Alt+F4), он гейта не требует и не может его получить (на мобильном
    закрывать окно нечем, событие просто не приходит)."""
    lines = (repo_root / "game" / "framework" / "20_ui" / "screens" / "core_screens.rpy").read_text(
        encoding="utf-8").splitlines()

    def indent(line):
        return len(line) - len(line.lstrip())

    in_screen = False
    for lineno, line in enumerate(lines, 1):
        if line.strip() and not line.startswith((" ", "#")):
            in_screen = line.startswith("screen ")
        if not in_screen or line.lstrip().startswith("#"):
            continue
        if not any(control in line for control in DESKTOP_ONLY_CONTROLS):
            continue
        gated = False
        limit = indent(line)
        for prev in reversed(lines[:lineno - 1]):
            if not prev.strip():
                continue
            if indent(prev) >= limit:
                continue
            limit = indent(prev)
            # Гейт — это УСЛОВИЕ, содержащее предикат, а не строка, в точности
            # ему равная: `if main_menu and vn_platform.is_desktop():` гейтит ровно
            # так же. Точное сравнение делало проверку зависимой от формы записи
            # соседнего условия и краснело на верном коде.
            head = prev.strip()
            if (head.startswith(("if ", "elif ")) and head.endswith(":")
                    and DESKTOP_GATE.removeprefix("if ").removesuffix(":") in head):
                gated = True
                break
        assert gated, f"core_screens.rpy:{lineno}: {line.strip()} — без гейта is_desktop()"


# ── Сборка: без тулчейна — объяснение, а не стектрейс ─────────────────────────

def test_build_apk_without_sdk_names_the_env_var(tmp_path):
    with pytest.raises(AndroidError, match="RENPY_SDK"):
        build_apk(mk_root(tmp_path), None)


def test_build_apk_without_rapt_explains_the_setup_path(tmp_path):
    root = mk_root(tmp_path)
    with pytest.raises(AndroidError, match="setup"):
        build_apk(root, _mk_sdk(tmp_path, rapt=False))


# ── Факт по собранному пакету против потолков канала ──────────────────────────

def test_package_facts_reports_share_of_channel_limit(tmp_path):
    """Предполётная оценка считается по `game/` + фиксированные накладные; когда
    пакет собран, потолок сверяется с ФАЙЛОМ, иначе проверка бессмысленна."""
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"\0" * (50 * MB))
    facts, warnings, errors = package_facts(apk)
    assert not warnings and not errors
    assert "50.0 МБ" in facts[0] and "universal APK" in facts[0]


def test_package_facts_blocks_above_channel_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(android, "PACKAGE_LIMIT_MB", 10)
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"\0" * (11 * MB))
    _, _, errors = package_facts(apk)
    assert errors and "стор" in errors[0]


def test_package_facts_warns_before_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(android, "PACKAGE_LIMIT_MB", 10)
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"\0" * (9 * MB))
    _, warnings, errors = package_facts(apk)
    assert warnings and not errors


def test_bundle_facts_check_the_largest_entry(tmp_path, monkeypatch):
    """Пофайловый лимит fast-follow пакета внутри `.aab` по `game/` не виден вовсе:
    крупнейший файл там — нативная библиотека движка, а не наш ассет."""
    import zipfile

    monkeypatch.setattr(android, "BUNDLE_PACK_LIMIT_MB", 1)
    aab = tmp_path / "app-release.aab"
    with zipfile.ZipFile(aab, "w") as zf:
        zf.writestr("base/lib/arm64-v8a/librenpython.so", b"\0" * (2 * MB))
        zf.writestr("base/assets/x-game/script.rpyb", b"\0" * 1024)
    facts, _, errors = package_facts(aab)
    assert any("librenpython.so" in f for f in facts)
    assert errors and "fast-follow" in errors[0]


def test_bundle_facts_survive_unreadable_zip(tmp_path):
    """Битый архив — предупреждение, а не трейсбек: вес пакета уже измерен, и это
    само по себе полезнее падения."""
    aab = tmp_path / "app-release.aab"
    aab.write_bytes(b"not-a-zip")
    facts, warnings, errors = package_facts(aab)
    assert facts and warnings and not errors


# ── Подготовка тулчейна: те же функции RAPT, что у лаунчера, но без GUI ────────

def test_setup_step_rejects_unknown_step(tmp_path):
    with pytest.raises(AndroidError, match="неизвестный шаг"):
        setup_step(mk_root(tmp_path), _mk_sdk(tmp_path), "everything")


def test_setup_step_without_rapt_points_at_the_download(tmp_path):
    with pytest.raises(AndroidError, match="--download-rapt"):
        setup_step(mk_root(tmp_path), _mk_sdk(tmp_path, rapt=False), "sdk")


@no_windows
def test_setup_step_without_engine_names_the_env_var(tmp_path):
    """Шаг живёт ВНУТРИ движка: без renpy.sh запускать нечего, и сказать об этом
    надо до попытки выполнить шаг."""
    with pytest.raises(AndroidError, match="RENPY_SDK"):
        setup_step(mk_root(tmp_path), _mk_sdk(tmp_path), "keys")


@no_windows
def test_setup_step_runs_the_engine_command_from_rapt(tmp_path, monkeypatch):
    """Контракт запуска: движок + КОРЕНЬ ПРОЕКТА + движковая команда + шаг, и cwd =
    rapt/ (RAPT строит пути к buildlib и android-sdk от текущего каталога).
    Ни stdout, ни stdin не перехватываются: шаги интерактивные."""
    sdk = _mk_sdk(tmp_path)
    (sdk / "renpy.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    root = mk_root(tmp_path)
    seen = {}

    def fake_call(cmd, cwd=None, **kwargs):
        seen["cmd"], seen["cwd"], seen["kwargs"] = cmd, cwd, kwargs
        return 0

    monkeypatch.setattr(android.subprocess, "call", fake_call)
    assert setup_step(root, sdk, "config") == 0
    assert seen["cmd"] == [str(sdk / "renpy.sh"), str(root),
                           android.TOOLCHAIN_COMMAND, str(sdk / "rapt"), "config"]
    assert seen["cwd"] == sdk / "rapt"
    assert not seen["kwargs"], "перехват потоков убил бы интерактивность шага"


def test_setup_step_returns_the_engine_exit_code(tmp_path, monkeypatch):
    """Провал шага обязан доехать до CLI кодом выхода: иначе упавшая подготовка
    отрапортует OK (движковая команда падает через SystemExit ровно за этим)."""
    sdk = _mk_sdk(tmp_path)
    (sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")).write_text(
        "#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(android.subprocess, "call", lambda *a, **k: 1)
    assert setup_step(mk_root(tmp_path), sdk, "keys") == 1


def test_engine_step_names_match_the_dev_command(repo_root):
    """Шаги CLI и шаги движковой команды — один список. Разъехались бы — CLI
    предлагал бы шаг, которого в движке нет, и падал бы на аргументах."""
    src = (repo_root / "game" / "framework" / "90_debug"
           / "040_android_toolchain.rpy").read_text(encoding="utf-8")
    assert f'register_command("{android.TOOLCHAIN_COMMAND}"' in src
    for step in android.SETUP_STEPS:
        assert f'"{step}": _vn_android_step_' in src, f"шаг {step} не объявлен в движке"
    declared = src.count('": _vn_android_step_')
    assert declared == len(android.SETUP_STEPS), "в движке шагов больше, чем знает CLI"


def test_rapt_install_preserves_the_executable_bit():
    """Обход гарда FWA-003: тот же дефект в установке Android-тулчейна.

    `install_rapt` распаковывал скачанный архив обычным `zf.extractall(sdk)`, а
    zipfile прав не переносит ВООБЩЕ (CPython ZipFile._extract_member не читает
    external_attr и не зовёт chmod). Штатный путь Ren'Py так не делает: лаунчер
    ставит RAPT своим апдейтером, который несёт отдельный список исполняемых
    файлов и восстанавливает бит руками (SDK renpy/common/00updater.rpy).

    Отказ: на Linux/macOS `vn release android setup sdk --download-rapt` кладёт
    rapt/** без бита x, и следующий `vn release android build` падает Permission
    denied посреди gradle — при том что диагностика врёт, `rapt_status` проверяет
    только НАЛИЧИЕ каталога, хеш и adb. На Windows дефект невидим полностью.

    Гард FWA-003 покрывал только release._extract_archive и про этот путь не знал."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "vn"
           / "android.py").read_text(encoding="utf-8")
    body = src.split("def install_rapt(", 1)[1].split("\ndef ", 1)[0]
    assert "extract_zip_preserving_modes" in body, \
        "установка RAPT снова распаковывает архив без восстановления прав"
    assert "zf.extractall(" not in body, \
        "в install_rapt вернулся extractall — zipfile прав не переносит"
