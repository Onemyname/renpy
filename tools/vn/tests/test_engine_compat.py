"""Контракт-тесты engine_compat (G18): каждое допущение о недокументированных API Ren'Py
покрыто проверкой против пиннованного SDK. Без SDK — skip (canary-джоба CI гоняет с SDK)."""

import os
import re
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

@requires_sdk
def test_defined_screens_registry(repo_root):
    """G18: перечисления объявленных экранов в публичном API Ren'Py нет, реестр —
    внутренний `renpy.display.screen.screens`. Контракт-тест держит два допущения:
    реестр существует и ключуется парой (имя, вариант), а у Screen есть `location`,
    по которому мы отделяем экраны проекта от экранов движка."""
    screen_py = (Path(SDK) / "renpy" / "display" / "screen.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "screens = {}" in screen_py, "реестр экранов переименован — правьте vn_compat"
    assert "screens[name[0], v] = self" in screen_py, "ключ реестра изменился"
    assert "self.location = location" in screen_py, "у Screen пропал location"
    compat = (repo_root / "game" / "framework" / "00_core" / "engine_compat"
              / "000_compat.rpy").read_text(encoding="utf-8")
    assert "from renpy.display.screen import screens" in compat
    assert 'getattr(screen, "location", None)' in compat, \
        "фильтр по месту объявления пропал — тур начнёт требовать экраны движка"


@requires_sdk
def test_gui_rebuild_exists(repo_root):
    """G18: `gui.rebuild()` — функция ШАБЛОНА SDK (gui.rpy), а не API движка.
    Контракт: она в шаблоне есть, вызывается только из engine_compat, и её
    отсутствие не валит переключение масштаба."""
    # Фактическое место объявления в 8.5.3 — renpy/common/00gui.rpy (store gui):
    # это общий слой движка, но НЕ документированный API, поэтому контракт держим.
    common_gui = Path(SDK) / "renpy" / "common" / "00gui.rpy"
    assert "def rebuild" in common_gui.read_text(encoding="utf-8", errors="ignore"), \
        "gui.rebuild пропал из 00gui.rpy — правьте vn_compat.gui_rebuild"
    compat = (repo_root / "game" / "framework" / "00_core" / "engine_compat"
              / "000_compat.rpy").read_text(encoding="utf-8")
    assert 'getattr(renpy.store.gui, "rebuild", None)' in compat
    # Ищем ВЫЗОВ в начале стейтмента, а не упоминание: комментарии и докстринги,
    # объясняющие механику, — это документация, а не нарушение правила.
    call = re.compile(r"^\s*(\$\s*)?(renpy\.store\.)?gui\.rebuild\(\)", re.M)
    direct = [f.name for f in (repo_root / "game" / "framework" / "20_ui").rglob("*.rpy")
              if call.search(f.read_text(encoding="utf-8"))]
    assert direct == [], f"прямой вызов gui.rebuild в {direct} — только через фасад (G18)"


def test_framework_reads_generated_names_defensively(repo_root):
    """Пустой чекаут обязан стартовать и честно сказать, что контента нет
    (010_registry.rpy) — значит framework не имеет права читать имена генерата
    голыми на init: game/generated/ в .gitignore, а persistent глобален и
    переживает переклон. Голое `vn_build_max_oversampling` в 095_quality.rpy при
    непустом persistent.vn_quality_cap роняло старт в NameError.

    Проверяются только обращения ВНЕ функций, то есть исполняемые на init: тело
    функции работает уже в рантайме, там голое имя — вопрос стиля, а не старта.
    Иначе тест стал бы ловушкой для будущего автора, который читает генерат из
    функции совершенно законно."""
    core = repo_root / "game" / "framework" / "00_core"
    bare = []
    for f in sorted(core.rglob("*.rpy")):
        def_indent = None
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if not code.strip():
                continue
            indent = len(code) - len(code.lstrip())
            if def_indent is not None and indent <= def_indent:
                def_indent = None                     # тело функции закончилось
            if code.lstrip().startswith("def "):
                def_indent = indent
                continue
            if def_indent is not None:
                continue                              # внутри функции — рантайм
            for name in ("vn_build_max_oversampling",):
                if name in code and "getattr(" not in code:
                    bare.append(f"{f.name}:{i}")
    assert bare == [], f"имя генерата читается голым на init: {bare} (нужен getattr)"


# ── Контракт vn_compat.revertable ─────────────────────────────────────────────
# Тест, обещанный докстрингом revertable(), физически отсутствовал — и ровно
# поэтому в нём годами жила ошибка: имена list/dict/set внутри стора подменены
# Revertable-аналогами (SDK renpy/minstore.py:41-53), так что isinstance по ним
# НЕ распознаёт обычные контейнеры из json/миграций, то есть конвертация не
# срабатывала в единственном случае, ради которого написана. Тест исполняет блок
# с той же подменой, что делает движок.

def _compat_module(repo_root, monkeypatch):
    import sys
    import textwrap
    import types

    class RevertableDict(dict):
        pass

    class RevertableList(list):
        pass

    class RevertableSet(set):
        pass

    src = (repo_root / "game" / "framework" / "00_core" / "engine_compat"
           / "000_compat.rpy").read_text(encoding="utf-8")
    tail = src.partition("python in vn_compat:")[2]
    body = []
    for line in tail.splitlines():
        if line.strip() and not line.startswith("    "):
            break
        body.append(line)

    revertable_mod = types.ModuleType("renpy.revertable")
    revertable_mod.RevertableDict = RevertableDict
    revertable_mod.RevertableList = RevertableList
    revertable_mod.RevertableSet = RevertableSet
    renpy_mod = types.ModuleType("renpy")
    renpy_mod.revertable = revertable_mod
    fake_store = types.ModuleType("store")
    fake_store.renpy = renpy_mod
    monkeypatch.setitem(sys.modules, "store", fake_store)
    monkeypatch.setitem(sys.modules, "renpy", renpy_mod)
    monkeypatch.setitem(sys.modules, "renpy.revertable", revertable_mod)

    mod = types.ModuleType("vn_compat")
    # Как движок: типы в сторе — Revertable-аналоги.
    mod.__dict__.update(dict=RevertableDict, list=RevertableList, set=RevertableSet)
    exec(compile(textwrap.dedent("\n".join(body)), "000_compat.rpy", "exec"), mod.__dict__)
    return mod, (RevertableDict, RevertableList, RevertableSet)


def test_revertable_types(repo_root, monkeypatch):
    """Значения из json/миграций обязаны стать Revertable: без этого их изменения
    не попадают в rollback (G5), а именно такие значения apply_snapshot и пишет
    обратно в сторы после миграции."""
    mod, (RDict, RList, RSet) = _compat_module(repo_root, monkeypatch)

    out = mod.revertable({"a": [1, {"b": {2}}]})
    assert isinstance(out, RDict)
    assert isinstance(out["a"], RList)
    assert isinstance(out["a"][1], RDict)
    assert isinstance(out["a"][1]["b"], RSet)
    # Скаляры и кортежи проходят как есть — конвертировать нечего.
    assert mod.revertable("s") == "s" and mod.revertable((1, 2)) == (1, 2)
