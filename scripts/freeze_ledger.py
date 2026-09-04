#!/usr/bin/env python3
"""Freeze a phase's raw data before the preregistered analysis runs.

The seal proves the protocol predates the data. This proves the data predates
the analysis. Without it, "we analysed exactly what we collected" rests on the
analyst's word, and the ledger's own hash chain only shows that records were not
reordered — not that the file the analysis read is the file collection produced.

Records the chain state, the file digests and the governing seal, then makes the
raw files read-only. Deliberately reports nothing about outcomes: freezing is not
an occasion to look at results.
"""
import argparse
import hashlib
import json
import os
import stat
import time
from collections import Counter
from pathlib import Path

import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings
from contextfidelity.ledger import Ledger

EXPECTED_RUNS = {"phase1": 340}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["phase1", "phase2", "phase3"])
    ap.add_argument("--allow-partial", action="store_true",
                    help="freeze fewer runs than the design expects; records the shortfall")
    args = ap.parse_args()

    s = Settings.load()
    ledger_path = s.ledger_dir / f"{args.phase}.jsonl"
    scored_path = s.scored_dir / f"{args.phase}.jsonl"
    if not ledger_path.exists():
        print(f"no ledger at {ledger_path}")
        return 1

    led = Ledger(ledger_path)
    ok, msg = led.verify()
    print(f"chain: {'ok' if ok else 'BROKEN'} ({msg})")
    if not ok:
        print("refusing to freeze a broken chain")
        return 1

    recs = list(led.read())
    statuses = Counter(r.status for r in recs)
    seals = sorted({r.seal_hash for r in recs})
    print(f"runs: {len(recs)}   statuses: {dict(sorted(statuses.items()))}")

    if len(seals) != 1:
        print(f"refusing to freeze: records span {len(seals)} seals {[h[:12] for h in seals]}; "
              "the protocol changed mid-phase and the runs do not share one governing manifest")
        return 1

    current = sealmod.load(s.seal_path)
    if seals[0] != current.manifest_hash:
        print(f"refusing to freeze: runs carry seal {seals[0][:12]} but the working tree is "
              f"{current.manifest_hash[:12]}")
        return 1
    verify = sealmod.verify(s.root, s.seal_path)
    wstate = sealmod.witness_state(current, s.seal_path)
    print(f"seal: {verify.summary()}")
    print(f"witness: {wstate.status}")
    if not (verify.ok and wstate.ok):
        print("refusing to freeze under a broken seal or witness")
        return 1

    expected = EXPECTED_RUNS.get(args.phase)
    shortfall = None
    if expected is not None and len(recs) != expected:
        shortfall = expected - len(recs)
        if not args.allow_partial:
            print(f"refusing to freeze: {len(recs)} runs, design expects {expected}. "
                  "Use --allow-partial only for a deliberately stopped phase.")
            return 1

    record = {
        "phase": args.phase,
        "frozen_at": round(time.time(), 3),
        "runs": len(recs),
        "expected_runs": expected,
        "shortfall": shortfall,
        "statuses": dict(sorted(statuses.items())),
        "chain_ok": ok,
        "governing_seal": current.manifest_hash,
        "seal_version": current.version,
        "witness": f"{wstate.witness.kind}:{wstate.witness.identifier}" if wstate.witness else None,
        "ledger_path": str(ledger_path),
        "ledger_sha256": sha256_file(ledger_path),
        "scored_path": str(scored_path) if scored_path.exists() else None,
        "scored_sha256": sha256_file(scored_path) if scored_path.exists() else None,
    }
    out = s.runs_dir / f"{args.phase}.freeze.json"
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for p in (ledger_path, scored_path):
        if p.exists():
            os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    print(f"\nwrote {out}")
    print(f"ledger sha256 {record['ledger_sha256']}")
    if record["scored_sha256"]:
        print(f"scored sha256 {record['scored_sha256']}")
    print("raw files are now read-only. Analysis may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
