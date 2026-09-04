"""contextfidelity — a preregistered replication of within-session instruction
attenuation in coding agents, extended along instruction complexity.

Target finding (McMillan 2026, arXiv:2605.10039): compliance with a repository
configuration instruction declines as an agent generates more code within a
session, ~5.6% lower odds per generation step (OR = 0.944). That finding was
identified during analysis rather than pre-specified, and the author flags it as
warranting independent replication.

This package is a harness for testing it under a sealed protocol. The design
rule throughout: everything that could be tuned after seeing results is frozen
and hashed before the first run. See contextfidelity.seal.

Nothing here claims the effect is real. The point is to find out.
"""

__version__ = "0.1.0"

ORIGINAL = {
    "citation": "McMillan, D. (2026). Instruction Adherence in Coding Agent "
    "Configuration Files. arXiv:2605.10039",
    "reported_or_per_step": 0.944,
    "reported_ci": (0.937, 0.951),
    "reported_log_odds_slope": -0.0578,
    "pinned_cli": "2.1.92",
    "pinned_primary_model": "sonnet-4.6",
    "sessions": 1650,
    "function_observations": 16050,
    "status": "identified during analysis; not pre-specified; author requests replication",
}
