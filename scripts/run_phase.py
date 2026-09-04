#!/usr/bin/env python3
"""Execute a phase. Refuses to run without an intact seal, and refuses real
collection without a valid external witness.

    python scripts/run_phase.py phase1 --harness replay --limit 60
    python scripts/run_phase.py phase1 --harness claude-code
"""
import argparse, json
import _boot  # noqa: F401
from contextfidelity.config import Settings
from contextfidelity.design import build
from contextfidelity.harness import ClaudeCodeHarness, ReplayHarness, ReplaySpec
from contextfidelity.runner import run_phase


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["phase1", "phase2", "phase3"])
    ap.add_argument("--harness", default=None, choices=["replay", "claude-code"])
    ap.add_argument("--replicates", type=int, default=50)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--target-rung", default=None, help="resolves phase3's TARGET")
    ap.add_argument("--replay-slope", type=float, default=-0.0578,
                    help="replay only: the slope to inject, for pipeline validation")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    s = Settings.load()
    if args.harness:
        s.harness = args.harness
    phase = build(args.replicates)[args.phase]

    counter = {"n": 0}

    def factory(planned):
        if s.harness == "claude-code":
            return ClaudeCodeHarness(s.cli_path, s.model)
        counter["n"] += 1
        return ReplayHarness(
            ReplaySpec(
                slope_log_odds=args.replay_slope,
                seed=args.seed + counter["n"],
                config_present=planned.config,
                single_function=(planned.task_id == "F1"),
            ),
            planned.rung,
        )

    def progress(out):
        if out["run_id"].endswith(("r010", "r030", "r050")):
            print(f"  {out['run_id']}  {out['status']}  "
                  f"{out['opportunities']} opportunities  "
                  f"coverage {out['position_coverage']:.2f}")

    # Real collection is fail-closed on the witness as well as the seal; replay
    # is exempt because a synthetic run claims nothing about when the protocol
    # existed.
    result = run_phase(
        phase, s, factory, args.target_rung, args.limit, progress,
        require_witness=(s.harness != "replay"),
    )
    print(json.dumps(result, indent=2))
    if s.harness == "replay":
        print("\nREPLAY HARNESS: these are synthetic sessions from a specified")
        print("generative process, not model behaviour. Useful only for confirming")
        print("the pipeline recovers a slope that was put in on purpose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
