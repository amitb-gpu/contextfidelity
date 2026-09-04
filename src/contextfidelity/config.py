"""Configuration. Paths resolve from the repo root unless overridden."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def repo_root() -> Path:
    return Path(os.environ.get("CONTEXTFIDELITY_ROOT", Path(__file__).resolve().parents[2]))


@dataclass
class Settings:
    root: Path = field(default_factory=repo_root)

    protocol_dir: Path = field(init=False)
    fixtures_dir: Path = field(init=False)
    runs_dir: Path = field(init=False)
    ledger_dir: Path = field(init=False)
    scored_dir: Path = field(init=False)
    results_dir: Path = field(init=False)
    seal_path: Path = field(init=False)

    # Target repository under test. Must be pinned to a commit; see
    # protocol/design.yaml. Not vendored here — clone it yourself.
    target_repo: Path | None = None
    target_commit: str | None = None

    # Harness. "replay" is the offline deterministic stand-in used by tests and
    # by the pipeline dry run; "claude-code" shells out to the real CLI.
    harness: str = "replay"
    cli_path: str = "claude"
    model: str = ""
    max_turns: int = 100
    run_timeout_s: int = 900

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.protocol_dir = self.root / "protocol"
        self.fixtures_dir = self.root / "fixtures"
        self.runs_dir = self.root / "runs"
        self.ledger_dir = self.runs_dir / "ledger"
        self.scored_dir = self.runs_dir / "scored"
        self.results_dir = self.root / "results"
        self.seal_path = self.protocol_dir / "SEAL.json"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        cfg = Path(path) if path else repo_root() / "config.yaml"
        overrides: dict[str, Any] = {}
        if cfg.exists() and yaml is not None:
            overrides = yaml.safe_load(cfg.read_text()) or {}
        s = cls(root=Path(overrides.pop("root", repo_root())))
        for k, v in overrides.items():
            if hasattr(s, k):
                setattr(s, k, Path(v) if k == "target_repo" and v else v)
        for env, attr in [
            ("CONTEXTFIDELITY_HARNESS", "harness"),
            ("CONTEXTFIDELITY_MODEL", "model"),
            ("CONTEXTFIDELITY_CLI", "cli_path"),
        ]:
            if os.environ.get(env):
                setattr(s, attr, os.environ[env])
        return s
