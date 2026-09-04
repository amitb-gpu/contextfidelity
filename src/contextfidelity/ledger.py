"""Run ledger: append-only, hash-chained records of every executed session.

Each record binds a run to the seal hash in force, the exact model and harness
version, the target commit, and the configuration file hashes. That binding is
what lets a reader check that the runs and the protocol belong to each other.

Tamper-evident against post-hoc edits. Not evidence that the harness reported
its own version honestly — the executor still attests to itself.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

GENESIS = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class RunRecord:
    seq: int
    run_id: str
    ts: float

    # Design coordinates
    phase: str
    cell_id: str
    rung: str
    arm: str
    task_id: str
    replicate: int

    # Provenance
    seal_hash: str
    target_commit: str
    harness: str
    harness_version: str
    model_id: str
    config_sha256: str

    # Outcome
    status: str = "ok"  # ok | no_code | error | timeout
    functions_emitted: int = 0
    turns: int = 0
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    artifact_path: str = ""
    error: str = ""

    prev_hash: str = GENESIS
    record_hash: str = ""

    def compute_hash(self) -> str:
        payload = asdict(self)
        payload.pop("record_hash")
        return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev, self._seq = self._tail()

    def _tail(self) -> tuple[str, int]:
        if not self.path.exists():
            return GENESIS, 0
        last, count = GENESIS, 0
        for rec in self.read():
            last, count = rec.record_hash, rec.seq + 1
        return last, count

    def append(self, **kwargs: Any) -> RunRecord:
        rec = RunRecord(seq=self._seq, ts=round(time.time(), 3), prev_hash=self._prev, **kwargs)
        rec.record_hash = rec.compute_hash()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(canonical(asdict(rec)) + "\n")
        self._prev, self._seq = rec.record_hash, rec.seq + 1
        return rec

    def read(self) -> Iterator[RunRecord]:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield RunRecord(**json.loads(line))

    def completed_cells(self) -> dict[str, int]:
        """How many successful runs exist per cell. Used to resume a partial
        phase without re-running work, and to detect over-running a cell."""
        counts: dict[str, int] = {}
        for rec in self.read():
            if rec.status in ("ok", "no_code"):
                key = f"{rec.cell_id}|{rec.task_id}"
                counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def verify_records(records: Iterable[RunRecord]) -> tuple[bool, str]:
        prev = GENESIS
        for i, rec in enumerate(records):
            if rec.seq != i:
                return False, f"sequence gap at index {i} (found seq={rec.seq})"
            if rec.prev_hash != prev:
                return False, f"chain break at seq {rec.seq}"
            if rec.compute_hash() != rec.record_hash:
                return False, f"hash mismatch at seq {rec.seq}"
            prev = rec.record_hash
        return True, "ok"

    def verify(self) -> tuple[bool, str]:
        return self.verify_records(self.read())

    def seal_hashes(self) -> set[str]:
        """More than one distinct seal hash across a phase means the protocol
        changed mid-collection. That is not automatically fatal but it must be
        reported, so surface it rather than letting it pass silently."""
        return {rec.seal_hash for rec in self.read()}
