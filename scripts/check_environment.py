#!/usr/bin/env python3
"""Go/no-go: can this machine run an EXACT replication, or only a CONCEPTUAL one?

Run this FIRST, before sealing. Discovering the answer mid-collection means the
runs already spent belong to neither mode.
"""
import argparse, json
import _boot  # noqa: F401
from contextfidelity.config import Settings
from contextfidelity.environment import check, target_repo_state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    s = Settings.load()
    report = check(args.cli or s.cli_path, args.model or s.model)
    print(report.summary())

    if s.target_repo:
        print("\ntarget repository:")
        for k, v in target_repo_state(s.target_repo).items():
            print(f"  {k}: {v}")
    else:
        print("\ntarget repository: not configured (set target_repo in config.yaml)")

    out = args.out or (s.protocol_dir / "ENVIRONMENT.json")
    report.write(out)
    print(f"\nwrote {out}")
    print("Record the mode in protocol/PREREGISTRATION.md before sealing.")
    return 0 if report.mode != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
