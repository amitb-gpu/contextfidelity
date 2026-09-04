#!/usr/bin/env python3
"""Seal the protocol. Nothing that produces data may run before this."""
import argparse
import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="e.g. v1.0")
    ap.add_argument("--note", default="")
    ap.add_argument("--verify", action="store_true", help="verify instead of creating")
    args = ap.parse_args()

    s = Settings.load()
    if args.verify:
        result = sealmod.verify(s.root, s.seal_path)
        print(result.summary())
        if result.ok:
            state = sealmod.witness_state(result.seal, s.seal_path)
            print(f"witness: {state.status} ({state.detail})")
        return 0 if result.ok else 1

    if s.seal_path.exists():
        existing = sealmod.load(s.seal_path)
        print(f"existing seal {existing.short()} version {existing.version}")
        print("Re-sealing creates a new version. Record the deviation in")
        print("protocol/PREREGISTRATION.md section 9 and report both seals.")

    seal = sealmod.create(s.root, args.version, args.note)
    sealmod.write(seal, s.seal_path)
    print(f"sealed {len(seal.files)} files -> {seal.manifest_hash}")

    state = sealmod.witness_state(seal, s.seal_path)
    print(f"witness: {state.status} ({state.detail})")
    if not state.ok:
        print()
        print("  UNWITNESSED. A self-issued timestamp proves nothing about when this")
        print("  protocol existed. Deposit THIS manifest hash with a third party")
        print("  (Zenodo DOI or an OpenTimestamps proof), then record it with:")
        print()
        print("    python scripts/witness_protocol.py --kind ots|doi --identifier <id>")
        print()
        print("  Recording a witness does NOT change the manifest hash, by design.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
