#!/usr/bin/env python3
"""Seal the protocol. Nothing that produces data may run before this."""
import argparse
import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="e.g. v1.0")
    ap.add_argument("--timestamp", default=None,
                    help="external witness: Zenodo DOI, OTS proof, registry id")
    ap.add_argument("--note", default="")
    ap.add_argument("--verify", action="store_true", help="verify instead of creating")
    args = ap.parse_args()

    s = Settings.load()
    if args.verify:
        result = sealmod.verify(s.root, s.seal_path)
        print(result.summary())
        return 0 if result.ok else 1

    if s.seal_path.exists():
        existing = sealmod.load(s.seal_path)
        print(f"existing seal {existing.short()} version {existing.version}")
        print("Re-sealing creates a new version. Record the deviation in")
        print("protocol/PREREGISTRATION.md section 9 and report both seals.")

    seal = sealmod.create(s.root, args.version, args.timestamp, args.note)
    sealmod.write(seal, s.seal_path)
    print(f"sealed {len(seal.files)} files -> {seal.manifest_hash}")
    print(f"status: {seal.status}")
    if not seal.witnessed:
        print()
        print("  UNWITNESSED. A self-issued timestamp proves nothing about when this")
        print("  protocol existed. Deposit the manifest (Zenodo DOI or an")
        print("  OpenTimestamps proof) and re-seal with --timestamp before running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
