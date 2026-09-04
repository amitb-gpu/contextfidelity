#!/usr/bin/env python3
"""Fit the preregistered model and evaluate the phase-1 gate."""
import argparse, json
import _boot  # noqa: F401
from contextfidelity.analysis.gate import evaluate_phase1_gate
from contextfidelity.analysis.model import PRIMARY_SCALE, fit_position_model
from contextfidelity.config import Settings
from contextfidelity.runner import load_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", default="phase1", nargs="?")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--scale", default=PRIMARY_SCALE, choices=["atomic", "complete"])
    ap.add_argument("--no-freeze-check", action="store_true",
                    help="replay/dry-run only; never for a real phase")
    args = ap.parse_args()

    s = Settings.load()

    # The raw data must be frozen before the analysis reads it. Ordering that is
    # merely remembered is not evidence; this makes it checkable. The freeze also
    # pins the digests, so "we analysed exactly what we collected" stops resting
    # on the analyst's word.
    freeze_path = s.runs_dir / f"{args.phase}.freeze.json"
    if not args.no_freeze_check:
        if not freeze_path.exists():
            print(f"refusing to analyse: no freeze record at {freeze_path}.")
            print(f"Run: python scripts/freeze_ledger.py {args.phase}")
            return 1
        freeze = json.loads(freeze_path.read_text())
        scored = s.scored_dir / f"{args.phase}.jsonl"
        import hashlib

        digest = hashlib.sha256(scored.read_bytes()).hexdigest()
        if freeze.get("scored_sha256") not in (None, digest):
            print("refusing to analyse: scored rows changed after the freeze")
            print(f"  frozen {freeze['scored_sha256'][:12]} != current {digest[:12]}")
            return 1
        print(f"freeze {freeze['runs']} runs, seal {freeze['governing_seal'][:12]}, "
              f"ledger {freeze['ledger_sha256'][:12]}")

    rows = load_rows(s.scored_dir / f"{args.phase}.jsonl")

    main_rows = [r for r in rows if r["cell_id"].endswith("-A1") and "FLOOR" not in r["cell_id"]]
    base_rows = [r for r in rows if "BASE" in r["cell_id"]]
    floor_rows = [r for r in rows if "FLOOR" in r["cell_id"]]

    fit = fit_position_model(main_rows, scale=args.scale, n_boot=args.boot)
    print(fit.summary())
    for n in fit.notes:
        print(f"  note: {n}")
    print(f"  position bins: {fit.bin_rates}")

    baseline_rate = (sum(r["passed"] for r in base_rows) / len(base_rows)) if base_rows else 0.0
    floor_first = [r for r in floor_rows if r.get("generation_position") == 1]
    floor_rate = (sum(r["passed"] for r in floor_first) / len(floor_first)) if floor_first else 0.0
    print(f"\n  no-config baseline marker rate: {baseline_rate:.4f}  (n={len(base_rows)})")
    print(f"  floor control position-1 rate:  {floor_rate:.4f}  (n={len(floor_first)})")

    if args.phase == "phase1":
        gate = evaluate_phase1_gate(fit, baseline_rate, floor_rate)
        print()
        print(gate.summary())
        out = s.results_dir / "phase1_gate.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"gate": gate.outcome, "checks": gate.checks,
                                   "detail": gate.detail, "reasons": gate.reasons},
                                  indent=2, default=str))
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
