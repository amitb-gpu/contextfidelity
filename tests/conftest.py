import shutil, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contextfidelity.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    for name in ("protocol", "fixtures", "src"):
        src = ROOT / name
        if src.exists():
            shutil.copytree(src, tmp_path / name)
    s = Settings(root=tmp_path)
    s.seal_path.unlink(missing_ok=True)  # start every test from an unsealed tree
    return s
