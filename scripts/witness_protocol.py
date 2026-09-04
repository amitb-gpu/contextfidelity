#!/usr/bin/env python3
"""Record an external witness for an existing protocol manifest.

Separate from sealing on purpose. An external service attests a hash, so the
hash must already exist; folding the attestation back into the hash would change
the thing being attested. Running this never alters the manifest hash — a test
enforces that.

Typical order:

    python scripts/seal_protocol.py --version v1.0      # produces the hash
    <deposit that hash with Zenodo / OpenTimestamps>    # produces the proof
    python scripts/witness_protocol.py --kind ots --identifier protocol.ots \\
        --proof-file protocol.ots
"""
import argparse

import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=("ots", "doi", "other"))
    ap.add_argument("--identifier", required=True, help="DOI, OTS proof name, or registry id")
    ap.add_argument("--proof-file", default=None,
                    help="path relative to protocol/ of a proof artifact, e.g. protocol.ots")
    ap.add_argument("--note", default="")
    ap.add_argument("--verify", action="store_true", help="report state instead of writing")
    args = ap.parse_args()

    s = Settings.load()
    if not s.seal_path.exists():
        print(f"no seal at {s.seal_path}. Seal the protocol before witnessing it.")
        return 1
    sealobj = sealmod.load(s.seal_path)

    if args.verify:
        state = sealmod.witness_state(sealobj, s.seal_path)
        print(f"manifest: {sealobj.manifest_hash}")
        print(f"witness:  {state.status} ({state.detail})")
        return 0 if state.ok else 1

    before = sealobj.manifest_hash
    witness = sealmod.create_witness(
        sealobj, args.kind, args.identifier, args.proof_file, args.note
    )
    path = sealmod.write_witness(witness, sealmod.witness_path(s.seal_path))

    after = sealmod.load(s.seal_path).manifest_hash
    if before != after:  # pragma: no cover - would indicate the bug this design removes
        print("FATAL: recording a witness changed the manifest hash. Refusing to continue.")
        return 2

    state = sealmod.witness_state(sealmod.load(s.seal_path), s.seal_path)
    print(f"wrote {path}")
    print(f"manifest unchanged: {after}")
    print(f"witness:  {state.status} ({state.detail})")
    return 0 if state.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
