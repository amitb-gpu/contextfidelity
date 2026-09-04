"""Simulation-based power, clustered on sessions.

The trap this exists to avoid: the original produced 16,050 function-level
observations, which looks like an enormous sample and is not. Functions are
nested inside sessions and sessions inside tasks, so the effective sample for a
between-condition contrast is closer to the number of sessions than the number
of functions. Powering on n=functions would overstate precision by roughly the
design effect, which at ~15 functions per session and even modest intra-session
correlation is a factor of several.

So power is simulated on the generative structure — sessions drawn, functions
drawn within sessions, a session random intercept, a position slope — and read
off as the proportion of simulated studies whose cluster-robust interval
excludes the null.

Defaults are anchored on the original's reported values: OR 0.944 per generation
step, 15 to 17.5 functions per multi-function session, per-task compliance
intercepts between 45% and 84%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SimConfig:
    n_sessions: int = 50
    mean_functions: float = 16.0
    dispersion: float = 0.45  # sd of log function count; sessions vary a lot
    intercept_p: float = 0.677  # baseline compliance at generation position 1
    slope_log_odds: float = -0.0578  # the original's reported per-step effect
    session_sd: float = 0.6  # random intercept sd on the logit scale
    session_slope_sd: float = 0.03
    """Between-session sd of the attenuation slope itself.

    This term is the one that matters and it is easy to omit. Generation
    position is a *within*-session predictor, so a session random intercept
    barely inflates its standard error — clustering appears not to matter, and a
    power calculation carrying only an intercept term comes out optimistic.
    Random slopes are what actually inflate it. The original reported
    substantial per-task slope heterogeneity (per-task ORs from 1.005 to 0.831),
    so a nonzero default is the conservative choice; set it to 0 only to
    reproduce the naive calculation and see the difference."""
    n_atoms: int = 1
    seed: int = 0


def _logit(p: float) -> float:
    return float(np.log(p / (1 - p)))


def simulate_sessions(cfg: SimConfig, rng: np.random.Generator) -> dict[str, np.ndarray]:
    n_funcs = np.maximum(
        1, np.round(rng.lognormal(np.log(cfg.mean_functions), cfg.dispersion, cfg.n_sessions))
    ).astype(int)
    session_re = rng.normal(0.0, cfg.session_sd, cfg.n_sessions)
    session_slope = rng.normal(0.0, cfg.session_slope_sd, cfg.n_sessions)

    sess_ids, positions, outcomes = [], [], []
    base = _logit(cfg.intercept_p)
    for s in range(cfg.n_sessions):
        k = n_funcs[s]
        pos = np.arange(1, k + 1)
        eta = base + session_re[s] + (cfg.slope_log_odds + session_slope[s]) * (pos - 1)
        p = 1.0 / (1.0 + np.exp(-eta))
        for _ in range(cfg.n_atoms):
            y = rng.binomial(1, p)
            sess_ids.append(np.full(k, s))
            positions.append(pos)
            outcomes.append(y)
    return {
        "session": np.concatenate(sess_ids),
        "position": np.concatenate(positions),
        "y": np.concatenate(outcomes),
    }


def _fit_slope(data: dict[str, np.ndarray]) -> tuple[float, float] | None:
    """Logistic slope on generation position with session-cluster-robust SE."""
    import statsmodels.api as sm

    X = sm.add_constant(data["position"].astype(float) - 1.0)
    try:
        model = sm.GLM(data["y"], X, family=sm.families.Binomial())
        res = model.fit(cov_type="cluster", cov_kwds={"groups": data["session"]})
    except Exception:  # noqa: BLE001 - separation or singular fits are expected occasionally
        return None
    return float(res.params[1]), float(res.bse[1])


def power_replication(cfg: SimConfig, n_sims: int = 300, alpha: float = 0.05) -> dict[str, Any]:
    """Power to detect a negative slope at all — the phase-1 question."""
    rng = np.random.default_rng(cfg.seed)
    crit = 1.959963984540054 if alpha == 0.05 else float(abs(np.sqrt(2) * _erfinv(1 - alpha)))
    hits, ests, fails = 0, [], 0
    for _ in range(n_sims):
        fit = _fit_slope(simulate_sessions(cfg, rng))
        if fit is None:
            fails += 1
            continue
        beta, se = fit
        ests.append(beta)
        if se > 0 and (beta + crit * se) < 0:
            hits += 1
    n_ok = n_sims - fails
    return {
        "n_sims": n_sims,
        "convergence_failures": fails,
        "power": hits / n_ok if n_ok else float("nan"),
        "mean_slope": float(np.mean(ests)) if ests else float("nan"),
        "mean_or": float(np.exp(np.mean(ests))) if ests else float("nan"),
        "config": cfg.__dict__.copy(),
    }


def power_interaction(
    cfg_a: SimConfig, cfg_b: SimConfig, n_sims: int = 300, alpha: float = 0.05
) -> dict[str, Any]:
    """Power to detect a *difference* in slope between two rungs or arms.

    This is the phase-2 and phase-3 question and it is a much harder test than
    detecting a slope, because the contrast has roughly twice the variance. A
    design powered to replicate is not automatically powered to compare.
    """
    rng = np.random.default_rng(cfg_a.seed + 9973)
    crit = 1.959963984540054
    hits, diffs, fails = 0, [], 0
    for _ in range(n_sims):
        fa = _fit_slope(simulate_sessions(cfg_a, rng))
        fb = _fit_slope(simulate_sessions(cfg_b, rng))
        if fa is None or fb is None:
            fails += 1
            continue
        diff = fb[0] - fa[0]
        se = float(np.sqrt(fa[1] ** 2 + fb[1] ** 2))
        diffs.append(diff)
        if se > 0 and abs(diff) - crit * se > 0:
            hits += 1
    n_ok = n_sims - fails
    return {
        "n_sims": n_sims,
        "convergence_failures": fails,
        "power": hits / n_ok if n_ok else float("nan"),
        "mean_slope_difference": float(np.mean(diffs)) if diffs else float("nan"),
        "true_difference": cfg_b.slope_log_odds - cfg_a.slope_log_odds,
    }


def design_effect(mean_cluster_size: float, icc: float) -> float:
    """How much a naive per-function analysis would overstate precision."""
    return 1.0 + (mean_cluster_size - 1.0) * icc


def _erfinv(x: float) -> float:
    from scipy.special import erfinv

    return float(erfinv(x))


def sweep_sessions(
    base: SimConfig, sizes: tuple[int, ...] = (20, 30, 50, 75, 100), n_sims: int = 200
) -> list[dict[str, Any]]:
    out = []
    for n in sizes:
        cfg = SimConfig(**{**base.__dict__, "n_sessions": n})
        res = power_replication(cfg, n_sims=n_sims)
        out.append({"n_sessions": n, "power": res["power"], "mean_or": res["mean_or"]})
    return out
