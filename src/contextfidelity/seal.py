"""Sealing the protocol.

The claim this project intends to make is "preregistered replication of an
acknowledged post-hoc finding". That claim is worth exactly as much as the
evidence that the protocol predates the data — so the protocol is hashed into a
manifest, the manifest is hashed, and every run record carries the seal hash.

What the seal does: makes post-hoc edits to the protocol detectable, and binds
each run to the protocol version in force when it executed.

What the seal does not do: prove the protocol existed at a given wall-clock
time. Only an external witness does that. Deposit the manifest hash with a third
party (Zenodo DOI, OpenTimestamps proof, a registry) before the first run and
record it with `scripts/witness_protocol.py`, which writes `protocol/WITNESS.json`
alongside the seal. A self-issued timestamp is worth nothing; the tool refuses to
pretend otherwise and reports any unwitnessed manifest as UNWITNESSED.

The witness is a *separate file by design*. It attests the manifest hash, so it
cannot be an input to that hash without circularity — see `Seal`.
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


SEAL_EXCLUDE = frozenset({"protocol/DEVIATIONS.md"})
"""Files matched by SEALED_GLOBS that are deliberately NOT sealed.

The deviation log is append-only and operational: it records what happened
during execution, which by definition is not knowable when the protocol is
frozen. Sealing it would make recording a deviation break the seal, so honesty
would look like tampering and the only way to stay "intact" would be to say
nothing. Design and analysis changes are a different matter and still require a
new seal version — the log is not a side door for editing the protocol.
"""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Seal:
    """The immutable protocol manifest.

    The manifest hash deliberately covers the sealed *files* and the protocol
    metadata only. It does **not** cover witness information.

    That exclusion is the whole point. An external witness attests a hash, so the
    hash has to exist before the witness does. An earlier version of this class
    folded `external_timestamp` into `compute_hash`, which made the two mutually
    dependent: OpenTimestamps cannot stamp a hash that changes the moment you
    record the stamp. Witness metadata therefore lives in a separate file that
    references this hash, and can be added, replaced or upgraded without
    disturbing what was sealed.
    """

    version: str
    created_at: float
    files: dict[str, str]
    note: str = ""
    manifest_hash: str = field(default="")

    def compute_hash(self) -> str:
        payload = {
            "version": self.version,
            "created_at": self.created_at,
            "files": self.files,
            "note": self.note,
        }
        return hashlib.sha256(canonical(payload).encode()).hexdigest()

    def short(self) -> str:
        return self.manifest_hash[:12]


@dataclass
class Witness:
    """An external attestation that a given manifest hash existed at a time.

    Stored separately from the seal. Never an input to the manifest hash.
    """

    manifest_hash: str
    kind: str  # "ots" | "doi" | "other"
    identifier: str
    created_at: float
    proof_file: str | None = None
    note: str = ""


@dataclass
class WitnessState:
    status: str  # WITNESSED | UNWITNESSED | MISMATCHED | PROOF_MISSING
    witness: "Witness | None" = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "WITNESSED"


def collect(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in SEALED_GLOBS:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and str(p.relative_to(root)) not in SEAL_EXCLUDE:
                out[str(p.relative_to(root))] = sha256_file(p)
    if not out:
        raise RuntimeError(f"no sealable files found under {root}")
    return out


def create(root: Path, version: str, note: str = "") -> Seal:
    seal = Seal(
        version=version,
        created_at=round(time.time(), 3),
        files=collect(root),
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
            return f"seal {self.seal.short()} intact ({len(self.seal.files)} files)"
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


WITNESS_FILENAME = "WITNESS.json"


def witness_path(seal_path: Path) -> Path:
    """Witness lives beside the seal, never inside it."""
    return Path(seal_path).parent / WITNESS_FILENAME


def create_witness(
    seal: Seal, kind: str, identifier: str, proof_file: str | None = None, note: str = ""
) -> Witness:
    if kind not in ("ots", "doi", "other"):
        raise ValueError(f"unknown witness kind {kind!r}; expected ots, doi or other")
    if not identifier.strip():
        raise ValueError("a witness needs an identifier; refusing to record an empty one")
    return Witness(
        manifest_hash=seal.manifest_hash,
        kind=kind,
        identifier=identifier.strip(),
        created_at=round(time.time(), 3),
        proof_file=proof_file,
        note=note,
    )


def write_witness(witness: Witness, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(witness), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_witness(path: Path) -> Witness:
    return Witness(**json.loads(Path(path).read_text(encoding="utf-8")))


def witness_state(seal: Seal, seal_path: Path) -> WitnessState:
    """Resolve the witness for a seal, without ever mutating the seal.

    MISMATCHED is the case that matters: a witness attesting some *other*
    manifest hash is worse than no witness, because it looks like evidence.
    """
    wpath = witness_path(seal_path)
    if not wpath.exists():
        return WitnessState("UNWITNESSED", None, f"no {WITNESS_FILENAME} beside the seal")
    try:
        w = load_witness(wpath)
    except Exception as exc:  # noqa: BLE001
        return WitnessState("MISMATCHED", None, f"unreadable witness: {type(exc).__name__}: {exc}")
    if w.manifest_hash != seal.manifest_hash:
        return WitnessState(
            "MISMATCHED",
            w,
            f"witness attests {w.manifest_hash[:12]} but the seal is {seal.manifest_hash[:12]}; "
            "the protocol was re-sealed after witnessing, so this witness proves nothing "
            "about the current manifest",
        )
    if w.proof_file:
        proof = wpath.parent / w.proof_file
        if not proof.exists():
            return WitnessState(
                "PROOF_MISSING", w, f"witness references {w.proof_file}, which is not present"
            )
    return WitnessState("WITNESSED", w, f"{w.kind}:{w.identifier}")


def require_witnessed(seal: Seal, seal_path: Path) -> Witness:
    """Fail-closed gate for real data collection.

    An intact seal proves the protocol has not changed. It does not prove the
    protocol predates the data. Real runs require both.
    """
    state = witness_state(seal, seal_path)
    if not state.ok:
        raise RuntimeError(
            f"refusing to collect real data: witness status {state.status} — {state.detail}.\n"
            "Record an external witness with scripts/witness_protocol.py first. "
            "Replay runs are exempt and are marked synthetic."
        )
    assert state.witness is not None
    return state.witness
