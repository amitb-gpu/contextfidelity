#!/usr/bin/env python3
"""Simulation-based power, clustered on sessions. Run before sealing and record
the numbers in PREREGISTRATION.md section 7."""
import argparse, json
import _boot  # noqa: F401
from contextfidelity.power import (SimConfig, design_effect, power_interaction,
                                   power_replication, sweep_sessions)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=50)
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--icc", type=float, default=0.10)
    args = ap.parse_args()

    base = SimConfig(n_sessions=args.sessions)
    rep = power_replication(base, n_sims=args.sims)
    print(f"RQ1 power (detect negative slope), n={args.sessions} sessions/cell:")
    print(f"  power {rep['power']:.3f}   recovered OR {rep['mean_or']:.4f}   "
          f"failures {rep['convergence_failures']}")

    de = design_effect(base.mean_functions, args.icc)
    print(f"\ndesign effect at {base.mean_functions:.0f} functions/session, ICC {args.icc}: {de:.2f}")
    print(f"  a naive per-atom analysis would overstate precision by ~{de**0.5:.2f}x on the SE")

    print("\nRQ2/RQ3 power (detect a DIFFERENCE in slope) - the harder test:")
    for mult, label in ((1.5, "1.5x steeper"), (2.0, "2x steeper")):
        a = SimConfig(n_sessions=args.sessions, seed=7)
        b = SimConfig(n_sessions=args.sessions, seed=7,
                      slope_log_odds=SimConfig().slope_log_odds * mult)
        res = power_interaction(a, b, n_sims=args.sims)
        print(f"  {label:<14} power {res['power']:.3f}")

    print("\nsessions-per-cell sweep (RQ1):")
    for row in sweep_sessions(base, (20, 30, 50, 75, 100), n_sims=max(100, args.sims // 3)):
        print(f"  n={row['n_sessions']:>4}  power {row['power']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
