"""Контракт-тесты engine_compat (G18): каждое допущение о недокументированных API Ren'Py
покрыто проверкой против пиннованного SDK. Без SDK — skip (canary-джоба CI гоняет с SDK)."""

import os
from pathlib import Path

import pytest

SDK = os.environ.get("RENPY_SDK")

requires_sdk = pytest.mark.skipif(
    not (SDK and (Path(SDK) / "renpy.py").is_file()),
    reason="RENPY_SDK не установлен — контракт-тесты движка гоняет canary-джоба CI",
)


def _sdk_sources_contain(symbol: str) -> bool:
    renpy_dir = Path(SDK) / "renpy"
    return any(
        symbol in path.read_text(encoding="utf-8", errors="ignore")
        for path in renpy_dir.rglob("*.py")
    )


@requires_sdk
def test_call_stack_depth_assumption():
    """000_compat.rpy: renpy.call_stack_depth() либо fallback renpy.get_return_stack()."""
    assert _sdk_sources_contain("def call_stack_depth") or _sdk_sources_contain(
        "def get_return_stack"
    ), "оба API исчезли из SDK — engine_compat.call_stack_depth() сломан, нужен новый fallback"


@requires_sdk
def test_voice_statement_contract():
    """045_audio.rpy / emit_scene (C5): три допущения о voice-подсистеме движка.

    1. voice-оператор принимает simple expression — генерат пишет
       `voice vn.voice_path("<id>")`.
    2. Имя проходит через config.voice_filename_format ("{filename}") и кладётся
       в _voice.play как есть.
    3. Falsy-имя не играет: потребление голоса гейтится truthiness `_voice.play`,
       поэтому vn.voice_path возвращает "" (а не None: format(None) дал бы
       строку "None" — «файл» с таким именем движок честно попытался бы играть).
    """
    src = (Path(SDK) / "renpy" / "common" / "00voice.rpy").read_text(encoding="utf-8")
    parse_region = src.split("def parse_voice", 1)[1].split("def ", 1)[0]
    assert "simple_expression" in parse_region, \
        "voice-стейтмент больше не принимает simple expression — генерат сломан"
    assert 'config.voice_filename_format = "{filename}"' in src, \
        "дефолт voice_filename_format изменился — пересмотреть vn.voice_path"
    assert "_voice.play = fn" in src and "if _voice.play:" in src, \
        "потребление _voice.play больше не гейтится truthiness — '' перестал быть no-op"


@requires_sdk
def test_emphasize_audio_contract():
    """045_audio.rpy: дакинг под голос — штатные config.emphasize_audio_*."""
    assert _sdk_sources_contain("emphasize_audio_channels"), \
        "config.emphasize_audio_channels исчез из движка — дакинг 045_audio.rpy мёртв"


@requires_sdk
def test_steam_engine_contract():
    """035_platform.rpy (ADR-0014): допущения о штатном Steam-стеке движка.

    1. steam_init: без steam_api-библиотеки рядом с исполняемым файлом —
       тихий no-op (standalone-сборка не ломается).
    2. При инициализации движок вставляет варианты steam_deck / steam_big_picture
       и регистрирует SteamBackend ачивок — на этом стоят controller-first UI
       и синк ачивок.
    3. dlc_installed существует — на нём ownership-провайдер паков (G9).
    4. config.steam_appid обрабатывается define-пассом (движок читает его на
       init -1499, раньше пользовательского кода)."""
    src = (Path(SDK) / "renpy" / "common" / "00steam.rpy").read_text(encoding="utf-8")
    init_region = src.split("def steam_init", 1)[1]
    assert "has_steam = os.path.exists(dll_path)" in init_region and \
           "if not has_steam:" in init_region, \
        "движок больше не пропускает Steam тихо без библиотеки — standalone сломан"
    assert 'config.variants.insert(0, "steam_deck")' in src, \
        "вариант steam_deck исчез — детект Deck в vn_platform мёртв"
    assert 'config.variants.insert(0, "steam_big_picture")' in src, \
        "вариант steam_big_picture исчез — детект Big Picture мёртв"
    assert "backends.insert(0, SteamBackend())" in src, \
        "SteamBackend больше не регистрируется — синк ачивок мёртв"
    assert "def dlc_installed" in src, \
        "dlc_installed исчез — ownership-провайдер паков мёртв"
    assert "steam_init()" in src.split("init -1499 python in achievement:", 2)[-1], \
        "steam_init больше не на init -1499 — проверить, что define appid успевает"


def test_api_level_sync():
    """VN_API_LEVEL (tools) обязан совпадать с API_LEVEL фасада vn.* (framework)."""
    import re
    from pathlib import Path

    from vn.content.compile import VN_API_LEVEL

    flow = (Path(__file__).resolve().parents[3] / "game" / "framework" / "00_core"
            / "030_flow.rpy").read_text(encoding="utf-8")
    m = re.search(r"^\s+API_LEVEL = (\d+)$", flow, re.M)
    assert m, "API_LEVEL не найден в 030_flow.rpy"
    assert int(m.group(1)) == VN_API_LEVEL
