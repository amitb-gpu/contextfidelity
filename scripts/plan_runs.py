#!/usr/bin/env python3
"""Show the design, its budget, and structural validation."""
import argparse, json
import _boot  # noqa: F401
from contextfidelity.design import budget, build, describe, validate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicates", type=int, default=50)
    ap.add_argument("--floor-replicates", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    plan = build(args.replicates, args.floor_replicates)
    problems = validate(plan)

    if args.json:
        print(json.dumps({"design": describe(plan), "budget": budget(plan),
                          "problems": problems}, indent=2))
        return 0 if not problems else 1

    for pid, phase in plan.items():
        print(f"\n{pid.upper()}  ({phase.runs()} runs)")
        print(f"  {phase.question}")
        for c in phase.cells:
            cfg = "config" if c.config else "NO CONFIG"
            print(f"    {c.cell_id:<16} {c.rung:<7} {c.arm:<4} {cfg:<9} "
                  f"{len(c.tasks)} tasks x {c.replicates} = {c.runs():>4} runs")
        if phase.gate:
            print(f"  GATE: {phase.gate}")

    b = budget(plan)
    print(f"\ntotal if every phase runs: {b['total_runs']} sessions")
    print(f"  {b['note']}")
    if problems:
        print("\nSTRUCTURAL PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ndesign validates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
