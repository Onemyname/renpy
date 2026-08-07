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
