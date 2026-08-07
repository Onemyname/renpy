"""vn dev / vn assets watch — цикл итерации без ручных пересборок (раздел 2.13).

Polling-вотчер (без внешних зависимостей): скан mtime+size раз в секунду.
Изменение в assets_src/ -> vn assets build; в content/ -> vn content compile.
Классификация для художника: чистая замена пикселей подхватывается Shift+R в игре;
структурные изменения (новый слой/сцена) требуют Shift+R с возможным сбросом позиции.
"""

from __future__ import annotations

import time
from pathlib import Path


def _snapshot(paths: list[Path]) -> dict[str, tuple[float, int]]:
    state: dict[str, tuple[float, int]] = {}
    for base in paths:
        if not base.exists():
            continue
        for f in base.rglob("*"):
            try:
                if f.is_file():
                    st = f.stat()
                    state[str(f)] = (st.st_mtime, st.st_size)
            except OSError:
                # Файл исчез между rglob и stat / залочен — пропускаем, следующий тик увидит.
                continue
    return state


def watch(root: Path, on_assets, on_content, interval: float = 1.0, stop_check=None):
    """Блокирующий цикл. stop_check() -> True прерывает (для vn dev)."""
    assets_paths = [root / "assets_src"]
    content_paths = [root / "content"]
    prev_assets = _snapshot(assets_paths)
    prev_content = _snapshot(content_paths)
    while True:
        if stop_check is not None and stop_check():
            return
        time.sleep(interval)
        # Колбэк не должен убивать вотчер: залоченный Photoshop'ом файл или битый
        # YAML — повод напечатать ошибку и дождаться следующего тика, а не умереть.
        cur = _snapshot(assets_paths)
        if cur != prev_assets:
            prev_assets = cur
            try:
                on_assets()
            except Exception as e:
                print(f"[vn watch] пересборка ассетов упала: {type(e).__name__}: {e}")
        cur = _snapshot(content_paths)
        if cur != prev_content:
            prev_content = cur
            try:
                on_content()
            except Exception as e:
                print(f"[vn watch] компиляция контента упала: {type(e).__name__}: {e}")
