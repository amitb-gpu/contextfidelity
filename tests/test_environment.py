from contextfidelity import environment


def test_canonical_sonnet_46_pin_is_exact(monkeypatch):
    monkeypatch.setattr(
        environment,
        "_cli_version",
        lambda _: (True, "2.1.92", "2.1.92 (Claude Code)"),
    )

    report = environment.check(
        "claude",
        "claude-sonnet-4-6",
    )

    assert report.mode == "EXACT"
    assert report.cli_matches_pin
    assert report.model_matches_pin
    assert report.deviations == []
