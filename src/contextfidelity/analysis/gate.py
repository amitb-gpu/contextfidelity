"""The phase-1 gate: what counts as "reproduced", decided before the data exist.

This is the file that makes accepting an unfavourable result cheap. If the
criterion is written down first, a null is a finding rather than a
disappointment, and there is no live decision to agonise over afterwards.

Four conditions, all required:

1. **Zero floor holds.** The marker must not appear in the no-configuration
   baseline. If it does, the outcome is measuring something other than
   instruction-driven behaviour and nothing downstream is interpretable.
2. **Floor control passes.** Compliance at generation position 1 in the
   single-function control must clear a threshold. Without this, a flat slope
   cannot be told apart from never having complied.
3. **Direction and exclusion.** The linear position slope is negative and its
   95% session-clustered bootstrap CI excludes zero.
4. **Magnitude compatibility.** The CI on the odds ratio overlaps a
   preregistered band around the original's reported 0.944. A slope that is
   real but ten times steeper is not the same finding, and saying so in advance
   prevents a directional hit being reported as a replication.

Outcomes are REPRODUCED, NOT_REPRODUCED, or INCONCLUSIVE. The third is a real
outcome, not a failure to reach one: an underpowered or non-converged phase 1
should stop the study rather than be rounded toward whichever answer is nearer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import ORIGINAL

OR_COMPATIBILITY_BAND = (0.85, 1.00)
"""Preregistered band the estimated OR's CI must overlap. Wide on purpose: the
question is whether the same phenomenon is present, not whether the point
estimate lands on 0.944."""

FLOOR_CONTROL_MIN = 0.50
"""Minimum position-1 compliance in the floor control.

Calibrated deliberately, not picked round. The original's reference cell sat at
67.7% compliance overall, and its per-task rates ranged from 45% to 84%. A
threshold of 60% would therefore sit inside the range of ordinary healthy
behaviour and could fail a perfectly sound study — a dry run on the replay
harness failed this check at 45% for exactly that reason. 50% keeps the check
meaningful (an agent complying at chance on a binary marker is genuinely
unmeasurable) while leaving room for a low-compliance task.

The check is a floor on measurability, not a quality bar."""

ZERO_FLOOR_MAX = 0.01
"""Maximum tolerated spontaneous marker rate in the no-configuration baseline."""

MIN_SESSIONS = 30
MIN_ATOMS = 1500


@dataclass
class GateResult:
    outcome: str  # REPRODUCED | NOT_REPRODUCED | INCONCLUSIVE
    checks: dict[str, bool | None] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def proceed_to_phase2(self) -> bool:
        return self.outcome == "REPRODUCED"

    def summary(self) -> str:
        lines = [f"PHASE 1 GATE: {self.outcome}"]
        for name, passed in self.checks.items():
            mark = {True: "pass", False: "FAIL", None: "n/a"}[passed]
            lines.append(f"  [{mark}] {name}")
        for r in self.reasons:
            lines.append(f"  - {r}")
        lines.append("")
        if self.outcome == "REPRODUCED":
            lines.append("  Proceed to phase 2.")
        elif self.outcome == "NOT_REPRODUCED":
            lines.append("  Do not proceed. The post-hoc finding did not replicate under")
            lines.append("  this protocol. That is a publishable result; write it up as one.")
        else:
            lines.append("  Do not proceed. The phase is underpowered or the fit did not")
            lines.append("  converge. Report the shortfall; do not round toward an answer.")
        return "\n".join(lines)


def evaluate_phase1_gate(
    fit: Any,
    baseline_marker_rate: float,
    floor_control_rate: float,
    or_band: tuple[float, float] = OR_COMPATIBILITY_BAND,
) -> GateResult:
    checks: dict[str, bool | None] = {}
    reasons: list[str] = []

    zero_ok = baseline_marker_rate <= ZERO_FLOOR_MAX
    checks["zero floor holds in no-configuration baseline"] = zero_ok
    if not zero_ok:
        reasons.append(
            f"baseline emitted the marker at {baseline_marker_rate:.3%} "
            f"(max {ZERO_FLOOR_MAX:.1%}); the outcome is not purely instruction-driven"
        )

    floor_ok = floor_control_rate >= FLOOR_CONTROL_MIN
    checks["floor control shows the agent can comply"] = floor_ok
    if not floor_ok:
        reasons.append(
            f"floor-control compliance {floor_control_rate:.1%} < {FLOOR_CONTROL_MIN:.0%}; "
            "a flat slope would be ambiguous between no attenuation and no compliance"
        )

    lo, hi = fit.linear_ci
    powered = fit.n_sessions >= MIN_SESSIONS and fit.n_atoms >= MIN_ATOMS
    checks["sample meets preregistered minimum"] = powered
    if not powered:
        reasons.append(
            f"{fit.n_sessions} sessions / {fit.n_atoms} atoms below the preregistered "
            f"minimum ({MIN_SESSIONS} / {MIN_ATOMS})"
        )

    converged = not (np.isnan(lo) or np.isnan(hi))
    checks["bootstrap interval estimable"] = converged
    if not converged:
        reasons.append("session bootstrap did not produce a usable interval")

    if not converged or not powered:
        return GateResult("INCONCLUSIVE", checks, _detail(fit, baseline_marker_rate, floor_control_rate), reasons)

    negative_excl = fit.linear_log_odds < 0 and hi < 0
    checks["slope negative and CI excludes zero"] = negative_excl
    if not negative_excl:
        reasons.append(
            f"slope {fit.linear_log_odds:+.4f}, 95% CI on log-odds "
            f"[{lo:+.4f}, {hi:+.4f}] does not exclude zero in the negative direction"
        )

    or_lo, or_hi = float(np.exp(lo)), float(np.exp(hi))
    compatible = not (or_hi < or_band[0] or or_lo > or_band[1])
    checks["magnitude compatible with the original"] = compatible
    if not compatible:
        reasons.append(
            f"OR CI [{or_lo:.3f}, {or_hi:.3f}] does not overlap the preregistered "
            f"compatibility band {or_band}; a real but different-magnitude effect is "
            "not the same finding as the one under replication"
        )

    all_pass = zero_ok and floor_ok and negative_excl and compatible
    outcome = "REPRODUCED" if all_pass else "NOT_REPRODUCED"
    if not all_pass and negative_excl and not compatible:
        reasons.append(
            "note: direction replicated but magnitude did not. Report this explicitly "
            "rather than as either a clean replication or a clean null."
        )
    return GateResult(outcome, checks, _detail(fit, baseline_marker_rate, floor_control_rate), reasons)


def _detail(fit: Any, baseline: float, floor: float) -> dict[str, Any]:
    lo, hi = fit.linear_ci
    return {
        "scale": fit.scale,
        "n_sessions": fit.n_sessions,
        "n_atoms": fit.n_atoms,
        "or_per_step": fit.linear_or,
        "or_ci": (float(np.exp(lo)), float(np.exp(hi))) if not np.isnan(lo) else (None, None),
        "nonlinear_detected": fit.nonlinear_detected,
        "bin_rates": fit.bin_rates,
        "baseline_marker_rate": baseline,
        "floor_control_rate": floor,
        "original_or": ORIGINAL["reported_or_per_step"],
    }
