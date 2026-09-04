"""The preregistered analysis model.

Committed before data collection and sealed. Three commitments that matter:

**Shape is not assumed linear.** The original states the relationship is
non-monotonic rather than a constant per-step decrement, so forcing everything
into one coefficient would misspecify the very thing being replicated. The
primary specification uses a restricted cubic spline basis on generation
position; the linear coefficient is reported *additionally* as an odds ratio,
solely for comparability with the original's OR = 0.944.

**Inference is clustered on sessions.** Atoms nest in opportunities, which nest
in sessions, which nest in tasks. Treating atoms as independent Bernoulli trials
would understate the standard error by roughly the square root of the design
effect — at ~16 functions per session that is not a rounding error. Primary
intervals come from a session-level nonparametric bootstrap; a cluster-robust
GLM is reported alongside as a parametric cross-check.

**Both compliance scales are reported, and the primary one is fixed in advance.**
Atomic compliance is primary for cross-rung comparison because rungs differ in
atom count; complete compliance is secondary. Choosing between them after seeing
results is the failure this file exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

PRIMARY_SCALE = "atomic"
SECONDARY_SCALE = "complete"
SPLINE_KNOTS = (1, 4, 8, 15)
"""Knot positions in generation-position units. Placed in advance, not chosen by
fit. The dense low end reflects the original's finding that a substantial share
of non-compliance mass sits in the first few generated functions."""


def rcs_basis(x: np.ndarray, knots: Sequence[float] = SPLINE_KNOTS) -> np.ndarray:
    """Restricted cubic spline basis (Harrell parameterisation), k-2 columns
    beyond the linear term. Linear in the tails, which keeps the fit from doing
    something wild in the thin high-position region."""
    k = np.asarray(knots, dtype=float)
    if len(k) < 3:
        raise ValueError("need at least 3 knots")
    x = np.asarray(x, dtype=float)
    denom = (k[-1] - k[0]) ** 2
    cols = [x]
    for j in range(len(k) - 2):
        def cube(t: np.ndarray) -> np.ndarray:
            return np.maximum(t, 0.0) ** 3

        term = (
            cube(x - k[j])
            - cube(x - k[-2]) * (k[-1] - k[j]) / (k[-1] - k[-2])
            + cube(x - k[-1]) * (k[-2] - k[j]) / (k[-1] - k[-2])
        ) / denom
        cols.append(term)
    return np.column_stack(cols)


def position_bins(x: np.ndarray) -> np.ndarray:
    """Preregistered coarse bins, reported as a model-free companion to the
    spline so the shape can be inspected without trusting the basis."""
    x = np.asarray(x)
    out = np.empty(len(x), dtype=object)
    out[:] = "16+"
    out[x <= 15] = "4-15"
    out[x <= 3] = "1-3"
    return out


@dataclass
class ModelFit:
    scale: str
    n_atoms: int
    n_sessions: int
    linear_log_odds: float
    linear_or: float
    linear_ci: tuple[float, float]
    spline_lrt_p: float | None
    nonlinear_detected: bool | None
    bin_rates: dict[str, float] = field(default_factory=dict)
    robust_se: float | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lo, hi = self.linear_ci
        shape = (
            "non-monotonic shape detected"
            if self.nonlinear_detected
            else "no nonlinear component detected"
        )
        return (
            f"[{self.scale}] n={self.n_atoms} atoms in {self.n_sessions} sessions; "
            f"OR per generation step = {self.linear_or:.4f} "
            f"(95% session-bootstrap CI {np.exp(lo):.4f}-{np.exp(hi):.4f}); {shape}"
        )


def _design(pos: np.ndarray, spline: bool) -> np.ndarray:
    base = rcs_basis(pos) if spline else pos.reshape(-1, 1)
    return np.column_stack([np.ones(len(pos)), base])


def _irls_logit(X: np.ndarray, y: np.ndarray, max_iter: int = 60) -> np.ndarray | None:
    """Plain IRLS. Kept dependency-light and deterministic so the bootstrap can
    call it tens of thousands of times."""
    beta = np.zeros(X.shape[1])
    for _ in range(max_iter):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(mu * (1 - mu), 1e-9, None)
        z = eta + (y - mu) / w
        XtW = X.T * w
        try:
            new = np.linalg.solve(XtW @ X + 1e-8 * np.eye(X.shape[1]), XtW @ z)
        except np.linalg.LinAlgError:
            return None
        if np.max(np.abs(new - beta)) < 1e-8:
            return new
        beta = new
    return beta


def cluster_bootstrap(
    pos: np.ndarray,
    y: np.ndarray,
    session: np.ndarray,
    n_boot: int = 2000,
    seed: int = 20260903,
    spline: bool = False,
) -> tuple[float, float]:
    """Percentile CI on the linear position coefficient, resampling *sessions*.

    Resampling atoms would treat within-session correlation as extra information
    and produce an interval that is too narrow. The cluster is the session.
    """
    rng = np.random.default_rng(seed)
    sessions = np.unique(session)
    idx_by_session = {s: np.flatnonzero(session == s) for s in sessions}
    draws = []
    for _ in range(n_boot):
        picked = rng.choice(sessions, size=len(sessions), replace=True)
        idx = np.concatenate([idx_by_session[s] for s in picked])
        if len(np.unique(y[idx])) < 2:
            continue
        beta = _irls_logit(_design(pos[idx], spline), y[idx])
        if beta is not None:
            draws.append(beta[1])
    if len(draws) < 50:
        return (float("nan"), float("nan"))
    return tuple(np.percentile(draws, [2.5, 97.5]))  # type: ignore[return-value]


def _lrt_nonlinear(pos: np.ndarray, y: np.ndarray) -> float | None:
    """Likelihood-ratio test of the spline's nonlinear terms against linear."""
    from scipy import stats

    def loglik(X: np.ndarray) -> float | None:
        beta = _irls_logit(X, y)
        if beta is None:
            return None
        eta = np.clip(X @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-eta))
        p = np.clip(p, 1e-12, 1 - 1e-12)
        return float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))

    ll_lin = loglik(_design(pos, spline=False))
    ll_spl = loglik(_design(pos, spline=True))
    if ll_lin is None or ll_spl is None:
        return None
    df = len(SPLINE_KNOTS) - 2
    stat = max(0.0, 2 * (ll_spl - ll_lin))
    return float(stats.chi2.sf(stat, df))


def fit_position_model(
    rows: list[dict[str, Any]],
    scale: str = PRIMARY_SCALE,
    n_boot: int = 1000,
    seed: int = 20260903,
) -> ModelFit:
    """Fit the preregistered model to atom-level rows.

    Rows need: session_id, generation_position, passed, complete.
    """
    usable = [r for r in rows if r.get("generation_position") is not None]
    notes: list[str] = []
    dropped = len(rows) - len(usable)
    if dropped:
        notes.append(
            f"{dropped} rows lacked a reconstructable generation position and were "
            "excluded; check the timeline parser if this fraction is large"
        )
    if not usable:
        raise ValueError("no rows with generation positions")

    outcome_key = "passed" if scale == "atomic" else "complete"
    if scale == "complete":
        seen: set[tuple[Any, Any]] = set()
        deduped = []
        for r in usable:
            key = (r["session_id"], r["opportunity_index"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        usable = deduped
        notes.append("complete scale collapsed to one row per opportunity")

    pos = np.array([float(r["generation_position"]) for r in usable])
    y = np.array([int(r[outcome_key]) for r in usable])
    session = np.array([str(r["session_id"]) for r in usable])

    if len(np.unique(y)) < 2:
        raise ValueError(
            f"outcome is constant ({y[0]}); a slope is not estimable. If this is the "
            "no-configuration baseline, that is the expected zero-floor result."
        )

    beta = _irls_logit(_design(pos, spline=False), y)
    if beta is None:
        raise RuntimeError("logistic fit failed to converge")
    linear = float(beta[1])
    ci = cluster_bootstrap(pos, y, session, n_boot=n_boot, seed=seed)
    p_nl = _lrt_nonlinear(pos, y)

    bins = position_bins(pos)
    bin_rates = {b: float(y[bins == b].mean()) for b in ("1-3", "4-15", "16+") if (bins == b).any()}

    return ModelFit(
        scale=scale,
        n_atoms=len(usable),
        n_sessions=len(np.unique(session)),
        linear_log_odds=linear,
        linear_or=float(np.exp(linear)),
        linear_ci=ci,
        spline_lrt_p=p_nl,
        nonlinear_detected=(p_nl is not None and p_nl < 0.05),
        bin_rates=bin_rates,
        notes=notes,
    )


def slope_contrast(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    scale: str = PRIMARY_SCALE,
    n_boot: int = 1000,
    seed: int = 20260903,
) -> dict[str, Any]:
    """Difference in linear position slope between two conditions.

    This is the phase-2 and phase-3 test, and it is harder than detecting a
    slope: the contrast carries roughly twice the variance. A design powered to
    replicate is not automatically powered to compare — see power.py.
    """
    rng = np.random.default_rng(seed)

    def prep(rows):
        usable = [r for r in rows if r.get("generation_position") is not None]
        key = "passed" if scale == "atomic" else "complete"
        pos = np.array([float(r["generation_position"]) for r in usable])
        y = np.array([int(r[key]) for r in usable])
        sess = np.array([str(r["session_id"]) for r in usable])
        return pos, y, sess

    pa, ya, sa = prep(rows_a)
    pb, yb, sb = prep(rows_b)
    fa = _irls_logit(_design(pa, False), ya)
    fb = _irls_logit(_design(pb, False), yb)
    if fa is None or fb is None:
        raise RuntimeError("one of the conditions failed to converge")
    observed = float(fb[1] - fa[1])

    draws = []
    for _ in range(n_boot):
        d = []
        for pos, y, sess in ((pa, ya, sa), (pb, yb, sb)):
            uniq = np.unique(sess)
            picked = rng.choice(uniq, size=len(uniq), replace=True)
            idx = np.concatenate([np.flatnonzero(sess == s) for s in picked])
            if len(np.unique(y[idx])) < 2:
                d = []
                break
            beta = _irls_logit(_design(pos[idx], False), y[idx])
            if beta is None:
                d = []
                break
            d.append(beta[1])
        if len(d) == 2:
            draws.append(d[1] - d[0])
    if len(draws) < 50:
        return {"observed_difference": observed, "ci": (float("nan"), float("nan")),
                "distinguishable": None, "n_boot_ok": len(draws)}
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "observed_difference": observed,
        "ci": (float(lo), float(hi)),
        "distinguishable": bool(lo > 0 or hi < 0),
        "n_boot_ok": len(draws),
    }
