"""Environment capture and the replication-mode go/no-go.

The original study pinned Claude Code CLI 2.1.92 with Sonnet 4.6. Those pins
*are* the replication. If they cannot be reproduced, what you run is a different
system and calling it the same name is the error the original authors avoided:
their Opus 4.7 block was forced onto CLI 2.1.123, which enables adaptive
thinking by default, and they refused to draw a model-level conclusion because
model, CLI version, and thinking mode all moved at once.

So this module answers one question before any design work matters:

    EXACT      pinned CLI and pinned model both available -> direct replication
    CONCEPTUAL something moved -> still worth running, but the deviation is
               named in the protocol, the title, and every claim

The failure this prevents is discovering the answer halfway through collection,
at which point the runs already spent belong to neither mode.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import ORIGINAL


@dataclass
class EnvironmentReport:
    checked_at: float
    mode: str  # EXACT | CONCEPTUAL | BLOCKED
    cli_found: bool
    cli_version: str | None
    cli_matches_pin: bool
    model_requested: str
    model_pin: str
    model_matches_pin: bool
    deviations: list[str] = field(default_factory=list)
    platform: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"replication mode: {self.mode}"]
        lines.append(f"  CLI: {self.cli_version or 'not found'} (pin {ORIGINAL['pinned_cli']})")
        lines.append(f"  model: {self.model_requested or 'unset'} (pin {self.model_pin})")
        for d in self.deviations:
            lines.append(f"  deviation: {d}")
        if self.mode == "CONCEPTUAL":
            lines.append("")
            lines.append("  This is a conceptual replication. Record the deviations in")
            lines.append("  protocol/PREREGISTRATION.md and say so in the title. Do not")
            lines.append("  describe results as a direct replication of the original.")
        if self.mode == "BLOCKED":
            lines.append("")
            lines.append("  No usable agent CLI. Fix this before sealing the protocol.")
        return "\n".join(lines)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def _cli_version(cli_path: str) -> tuple[bool, str | None, str]:
    exe = shutil.which(cli_path) or (cli_path if Path(cli_path).exists() else None)
    if exe is None:
        return False, None, ""
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return True, None, f"{type(exc).__name__}: {exc}"
    raw = (proc.stdout or proc.stderr).strip()
    version = None
    for token in raw.replace("(", " ").replace(")", " ").split():
        if token and token[0].isdigit() and "." in token:
            version = token.strip(",")
            break
    return True, version, raw


def check(cli_path: str = "claude", model: str = "") -> EnvironmentReport:
    found, version, raw = _cli_version(cli_path)
    cli_pin = ORIGINAL["pinned_cli"]
    model_pin = ORIGINAL["pinned_primary_model"]

    cli_ok = bool(version) and version == cli_pin
    model_ok = bool(model) and model_pin.replace("-", "") in model.replace("-", "").lower()

    deviations: list[str] = []
    if not found:
        deviations.append(f"agent CLI {cli_path!r} not on PATH")
    elif version is None:
        deviations.append(f"could not parse CLI version from: {raw[:80]!r}")
    elif not cli_ok:
        deviations.append(f"CLI {version} != pinned {cli_pin}")
    if not model:
        deviations.append("no model specified (set CONTEXTFIDELITY_MODEL)")
    elif not model_ok:
        deviations.append(f"model {model!r} != pinned {model_pin}")

    if not found:
        mode = "BLOCKED"
    elif cli_ok and model_ok:
        mode = "EXACT"
    else:
        mode = "CONCEPTUAL"

    return EnvironmentReport(
        checked_at=round(time.time(), 3),
        mode=mode,
        cli_found=found,
        cli_version=version,
        cli_matches_pin=cli_ok,
        model_requested=model,
        model_pin=model_pin,
        model_matches_pin=model_ok,
        deviations=deviations,
        platform={
            "python": sys.version.split()[0],
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        raw={"cli_version_output": raw},
    )


def target_repo_state(repo: Path) -> dict[str, str]:
    """Capture the target repository's pinned state. A replication that does not
    record which commit it ran against cannot be rerun."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        return {"error": f"{repo} is not a git repository"}
    out: dict[str, str] = {}
    for key, args in [
        ("commit", ["rev-parse", "HEAD"]),
        ("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
        ("remote", ["config", "--get", "remote.origin.url"]),
    ]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30
            )
            out[key] = proc.stdout.strip() if proc.returncode == 0 else ""
        except Exception as exc:  # noqa: BLE001
            out[key] = f"error: {exc}"
    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
    )
    out["clean"] = "true" if not dirty.stdout.strip() else "false"
    return out
