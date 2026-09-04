"""Sealing the protocol.

The claim this project intends to make is "preregistered replication of an
acknowledged post-hoc finding". That claim is worth exactly as much as the
evidence that the protocol predates the data — so the protocol is hashed into a
manifest, the manifest is hashed, and every run record carries the seal hash.

What the seal does: makes post-hoc edits to the protocol detectable, and binds
each run to the protocol version in force when it executed.

What the seal does not do: prove the protocol existed at a given wall-clock
time. Only an external timestamp does that. Deposit the sealed manifest with a
third party (Zenodo DOI, OpenScience registry, an OpenTimestamps proof) before
the first run and record the identifier in `external_timestamp`. A self-issued
timestamp is worth nothing; the tool refuses to pretend otherwise and marks any
seal without one as UNWITNESSED.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SEALED_GLOBS = [
    "protocol/*.md",
    "protocol/*.yaml",
    "fixtures/**/*.md",
    "fixtures/**/*.json",
    "src/contextfidelity/rules.py",
    "src/contextfidelity/scoring.py",
    "src/contextfidelity/design.py",
    "src/contextfidelity/analysis/model.py",
    "src/contextfidelity/analysis/gate.py",
    "src/contextfidelity/analysis/positions.py",
]
"""Everything whose contents could change a result if edited after seeing data.

The scorers and the analysis model are in here deliberately. A frozen protocol
document with a mutable scoring function is not a preregistration.
"""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Seal:
    version: str
    created_at: float
    files: dict[str, str]
    external_timestamp: str | None = None
    note: str = ""
    manifest_hash: str = field(default="")

    def compute_hash(self) -> str:
        payload = {
            "version": self.version,
            "created_at": self.created_at,
            "files": self.files,
            "external_timestamp": self.external_timestamp,
            "note": self.note,
        }
        return hashlib.sha256(canonical(payload).encode()).hexdigest()

    @property
    def witnessed(self) -> bool:
        return bool(self.external_timestamp)

    @property
    def status(self) -> str:
        return "WITNESSED" if self.witnessed else "UNWITNESSED"

    def short(self) -> str:
        return self.manifest_hash[:12]


def collect(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in SEALED_GLOBS:
        for p in sorted(root.glob(pattern)):
            if p.is_file():
                out[str(p.relative_to(root))] = sha256_file(p)
    if not out:
        raise RuntimeError(f"no sealable files found under {root}")
    return out


def create(root: Path, version: str, external_timestamp: str | None = None, note: str = "") -> Seal:
    seal = Seal(
        version=version,
        created_at=round(time.time(), 3),
        files=collect(root),
        external_timestamp=external_timestamp,
        note=note,
    )
    seal.manifest_hash = seal.compute_hash()
    return seal


def write(seal: Seal, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(seal), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Seal:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Seal(**raw)


@dataclass
class VerifyResult:
    ok: bool
    seal: Seal
    modified: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    manifest_intact: bool = True

    def summary(self) -> str:
        if self.ok:
            return f"seal {self.seal.short()} intact ({self.seal.status}, {len(self.seal.files)} files)"
        bits = []
        if not self.manifest_intact:
            bits.append("manifest hash mismatch (the seal itself was edited)")
        for label, items in (
            ("modified", self.modified),
            ("missing", self.missing),
            ("added", self.added),
        ):
            if items:
                bits.append(f"{label}: {', '.join(items)}")
        return "SEAL BROKEN — " + "; ".join(bits)


def verify(root: Path, seal_path: Path) -> VerifyResult:
    seal = load(seal_path)
    manifest_intact = seal.compute_hash() == seal.manifest_hash
    current = collect(root)
    modified = [f for f, h in seal.files.items() if f in current and current[f] != h]
    missing = [f for f in seal.files if f not in current]
    added = [f for f in current if f not in seal.files]
    ok = manifest_intact and not (modified or missing or added)
    return VerifyResult(ok, seal, modified, missing, added, manifest_intact)


def require_intact(root: Path, seal_path: Path) -> Seal:
    """Call this before any run that will produce data. A broken seal means the
    protocol changed after sealing, and results produced under it are not
    preregistered — better to stop than to discover it at write-up."""
    if not Path(seal_path).exists():
        raise RuntimeError(
            f"no seal at {seal_path}. Run scripts/seal_protocol.py before collecting data."
        )
    result = verify(root, seal_path)
    if not result.ok:
        raise RuntimeError(
            result.summary()
            + "\n\nRe-seal with a new version if the change is intended, and report both "
            "seals. Do not silently overwrite: the version history is the audit trail."
        )
    return result.seal
