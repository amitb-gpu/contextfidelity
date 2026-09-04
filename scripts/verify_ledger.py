#!/usr/bin/env python3
"""Verify run-ledger hash chains and check the seal is unbroken."""
import argparse
import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings
from contextfidelity.ledger import Ledger


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    args = ap.parse_args()
    s = Settings.load()

    if s.seal_path.exists():
        print(sealmod.verify(s.root, s.seal_path).summary())
    else:
        print("no seal present")

    paths = [args.path] if args.path else sorted(s.ledger_dir.glob("*.jsonl"))
    if not paths:
        print("no ledgers found")
        return 1
    failures = 0
    for p in paths:
        led = Ledger(p)
        ok, msg = led.verify()
        seals = sorted(h[:12] for h in led.seal_hashes())
        print(f"{'OK  ' if ok else 'FAIL'} {p} : {msg}  seals={seals}")
        if len(seals) > 1:
            print("     WARNING: more than one seal across this phase; the protocol")
            print("     changed mid-collection and this must be reported.")
        failures += 0 if ok else 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
