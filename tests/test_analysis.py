import numpy as np
import pytest
from contextfidelity.analysis.gate import evaluate_phase1_gate
from contextfidelity.analysis.model import cluster_bootstrap, fit_position_model, position_bins, rcs_basis
from contextfidelity.analysis.positions import assign_generation_positions, first_omission, post_omission_rate
from contextfidelity.harness import ToolEvent
from contextfidelity.scoring import AtomResult, OpportunityScore


def synth(slope=-0.0578, n_sessions=60, seed=3, k=16, slope_sd=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sessions):
        re_i = rng.normal(0, 0.6)
        re_s = rng.normal(0, slope_sd)
        for i in range(k):
            eta = 0.74 + re_i + (slope + re_s) * i
            rows.append({
                "session_id": f"s{s}", "generation_position": i + 1,
                "opportunity_index": i, "atom_id": "marker",
                "passed": int(rng.random() < 1 / (1 + np.exp(-eta))),
                "complete": 0,
            })
    for r in rows:
        r["complete"] = r["passed"]
    return rows


def test_recovers_injected_slope():
    fit = fit_position_model(synth(-0.0578), n_boot=300)
    lo, hi = fit.linear_ci
    assert lo < -0.0578 < hi, (fit.linear_or, fit.linear_ci)


def test_null_slope_ci_contains_zero():
    lo, hi = fit_position_model(synth(0.0), n_boot=300).linear_ci
    assert lo < 0 < hi


def test_session_bootstrap_is_wider_than_naive():
    """The reason for clustering. Note this bites via random *slopes*: a session
    random intercept alone barely inflates the SE of a within-session predictor,
    which is why the power simulation carries a slope-variance term rather than
    an intercept term only."""
    rows = synth(-0.0578, n_sessions=40, slope_sd=0.05)
    pos = np.array([r["generation_position"] for r in rows], float)
    y = np.array([r["passed"] for r in rows])
    sess = np.array([r["session_id"] for r in rows])
    clustered = cluster_bootstrap(pos, y, sess, n_boot=300)
    naive = cluster_bootstrap(pos, y, np.arange(len(y)).astype(str), n_boot=300)
    assert (clustered[1] - clustered[0]) > (naive[1] - naive[0])


def test_spline_basis_shape():
    assert rcs_basis(np.arange(1, 20, dtype=float)).shape[1] == 3  # linear + k-2


def test_position_bins_are_preregistered():
    assert set(position_bins(np.array([1, 5, 20]))) == {"1-3", "4-15", "16+"}


def test_constant_outcome_raises_rather_than_returning_a_number():
    rows = synth(0.0, n_sessions=5)
    for r in rows:
        r["passed"] = 0
        r["complete"] = 0
    with pytest.raises(ValueError, match="constant"):
        fit_position_model(rows, n_boot=50)


def _scores(pattern):
    return [
        OpportunityScore("f.ts", f"fn{i}", i, "L0", "all", [AtomResult("marker", bool(p))])
        for i, p in enumerate(pattern, start=1)
    ]


def test_positions_from_timeline():
    scores = _scores([1, 1, 1])
    rep = assign_generation_positions(scores, [ToolEvent(1, "Write", "f.ts")])
    assert rep.coverage == 1.0
    assert [s.generation_position for s in scores] == [1, 2, 3]


def test_untouched_files_are_counted_not_dropped_silently():
    scores = _scores([1, 1])
    rep = assign_generation_positions(scores, [ToolEvent(1, "Write", "other.ts")])
    assert rep.unassigned == 2 and not rep.usable()


def test_empty_timeline_yields_unusable_coverage():
    assert not assign_generation_positions(_scores([1, 1]), []).usable()


def test_first_omission_and_post_omission_rate():
    scores = _scores([1, 1, 0, 1, 0])
    assign_generation_positions(scores, [ToolEvent(1, "Write", "f.ts")])
    assert first_omission(scores) == 3
    assert post_omission_rate(scores) == 0.5


class _Fit:
    def __init__(self, slope, lo, hi, n_sessions=60, n_atoms=2000):
        self.scale, self.linear_log_odds = "atomic", slope
        self.linear_or, self.linear_ci = float(np.exp(slope)), (lo, hi)
        self.n_sessions, self.n_atoms = n_sessions, n_atoms
        self.nonlinear_detected, self.bin_rates = False, {}


def test_gate_passes_on_true_effect():
    fit = _Fit(-0.0578, -0.07, -0.045)
    assert evaluate_phase1_gate(fit, 0.0, 0.70).outcome == "REPRODUCED"


def test_gate_rejects_null():
    assert evaluate_phase1_gate(_Fit(0.001, -0.01, 0.01), 0.0, 0.70).outcome == "NOT_REPRODUCED"


def test_gate_rejects_wrong_magnitude_with_explicit_note():
    g = evaluate_phase1_gate(_Fit(-0.30, -0.33, -0.27), 0.0, 0.70)
    assert g.outcome == "NOT_REPRODUCED"
    assert any("direction replicated but magnitude" in r for r in g.reasons)


def test_gate_inconclusive_when_underpowered():
    g = evaluate_phase1_gate(_Fit(-0.0578, -0.07, -0.045, n_sessions=5, n_atoms=50), 0.0, 0.70)
    assert g.outcome == "INCONCLUSIVE" and not g.proceed_to_phase2


def test_gate_fails_if_baseline_leaks():
    g = evaluate_phase1_gate(_Fit(-0.0578, -0.07, -0.045), 0.05, 0.70)
    assert g.outcome == "NOT_REPRODUCED"
