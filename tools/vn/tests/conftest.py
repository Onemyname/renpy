import sys
from pathlib import Path

import pytest

# tools/vn/tests -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT
