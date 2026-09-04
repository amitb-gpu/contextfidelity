from contextfidelity.power import SimConfig, design_effect, power_interaction, power_replication


def test_power_high_for_replication_at_planned_n():
    assert power_replication(SimConfig(n_sessions=50), n_sims=80)["power"] > 0.8


def test_power_low_when_no_effect():
    cfg = SimConfig(n_sessions=50, slope_log_odds=0.0, seed=5)
    assert power_replication(cfg, n_sims=80)["power"] < 0.15


def test_contrast_is_harder_than_detection():
    """A design powered to detect a slope is not automatically powered to
    detect a difference in slopes."""
    n, sims = 25, 80
    detect = power_replication(SimConfig(n_sessions=n, seed=11), n_sims=sims)["power"]
    a = SimConfig(n_sessions=n, seed=11)
    b = SimConfig(n_sessions=n, seed=11, slope_log_odds=SimConfig().slope_log_odds * 1.5)
    contrast = power_interaction(a, b, n_sims=sims)["power"]
    assert contrast < detect


def test_design_effect_grows_with_cluster_size():
    assert design_effect(16, 0.1) > design_effect(2, 0.1) > 1.0
