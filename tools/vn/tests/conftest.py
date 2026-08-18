"""Общее для всего набора: корень репозитория, src на sys.path, разделяемые данные.

Почему разделяемые данные живут ЗДЕСЬ, а не в одном из test_*-модулей: conftest
импортируется pytest'ом при любом cwd, поэтому `from conftest import ...` работает
и из tools/vn, и из корня репозитория. Импорт набора как пакета
(`from tests.test_compile import ...`) работал только из tools/vn и делал прогон
из корня красным — см. test_verify_regressions.test_suite_never_imports_itself_as_package.
"""

import sys
from pathlib import Path

import pytest

# tools/vn/tests -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Выходы компилятора на проекте БЕЗ глав. Нужны двум наборам: test_compile сверяет
# по ним записанное, test_verify_regressions — что в режиме --check «устарело»
# ровно всё. Один источник истины: добавленный генерат обязан появиться в обоих
# проверках сразу, иначе один из наборов молча перестаёт его покрывать.
BASE_OUTPUTS = frozenset({
    "version.gen.rpy",
    "render.gen.rpy",       # ADR-0012: config.image_cache_size_mb из project.yaml
    "platform.gen.rpy",     # ADR-0014: config.steam_appid + карта DLC-владения
    "state/defaults.gen.rpy",
    "state/snapshot.gen.rpy",
    "state/migrations.gen.rpy",
    "registry/achievements.gen.rpy",
    "registry/audio.gen.rpy",
    "registry/chapters.gen.rpy",
    "registry/scenes.gen.rpy",
    "registry/characters.gen.rpy",
    "registry/images.gen.rpy",
    "registry/menus.gen.rpy",
    "registry/overrides.gen.rpy",
    "registry/ui_frames.gen.rpy",     # ADR-0009: Frame'ы генерируемых панелей
    "registry/gallery.gen.rpy",       # ADR-0010: реестр галереи
})


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT
