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
    # Start every test from an unsealed, unwitnessed tree. The real protocol/
    # directory is copied in wholesale, so once the repository carries a live
    # seal, witness and .ots proof they would otherwise leak into fixtures and
    # make "no witness present" untestable.
    s.seal_path.unlink(missing_ok=True)
    (s.protocol_dir / "WITNESS.json").unlink(missing_ok=True)
    for stale in s.protocol_dir.glob("*.ots"):
        stale.unlink()
    return s
