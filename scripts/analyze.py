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
    args = ap.parse_args()

    s = Settings.load()
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
