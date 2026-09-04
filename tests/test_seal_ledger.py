import pytest
from contextfidelity import seal as sealmod
from contextfidelity.ledger import Ledger

BASE = dict(
    run_id="r1", phase="phase1", cell_id="C", rung="L0", arm="A1", task_id="T3",
    replicate=1, seal_hash="abc", target_commit="deadbeef", harness="replay",
    harness_version="0", model_id="m", config_sha256="x",
)



def _replay_factory(planned):
    from contextfidelity.harness import ReplayHarness, ReplaySpec

    return ReplayHarness(
        ReplaySpec(
            slope_log_odds=-0.0578,
            seed=1,
            config_present=planned.config,
            single_function=(planned.task_id == "F1"),
        ),
        planned.rung,
    )


def test_seal_detects_modified_file(settings):
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    assert sealmod.verify(settings.root, settings.seal_path).ok
    (settings.root / "protocol" / "analysis_plan.md").write_text("tampered")
    result = sealmod.verify(settings.root, settings.seal_path)
    assert not result.ok and result.modified


def test_seal_detects_edited_manifest(settings):
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    raw = settings.seal_path.read_text().replace('"v1"', '"v2"')
    settings.seal_path.write_text(raw)
    assert not sealmod.verify(settings.root, settings.seal_path).manifest_intact


def test_seal_covers_scorer_and_model(settings):
    """A frozen protocol with a mutable scorer is not a preregistration."""
    files = sealmod.create(settings.root, "v1").files
    assert any("scoring.py" in f for f in files)
    assert any("analysis/model.py" in f for f in files)
    assert any("gate.py" in f for f in files)


def test_seal_without_witness_reports_unwitnessed(settings):
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    assert sealmod.witness_state(seal, settings.seal_path).status == "UNWITNESSED"


def test_recording_a_witness_does_not_change_the_manifest_hash(settings):
    """The defect this architecture exists to remove.

    An external witness attests a hash, so the hash must predate it. The earlier
    design folded the timestamp into compute_hash, which made witnessing with
    OpenTimestamps impossible in principle: stamping the hash changed the hash.
    """
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    before = sealmod.load(settings.seal_path).manifest_hash

    w = sealmod.create_witness(seal, "doi", "10.5281/zenodo.1")
    sealmod.write_witness(w, sealmod.witness_path(settings.seal_path))

    after = sealmod.load(settings.seal_path).manifest_hash
    assert before == after
    assert sealmod.verify(settings.root, settings.seal_path).ok
    assert sealmod.witness_state(seal, settings.seal_path).status == "WITNESSED"


def test_witness_for_a_different_manifest_is_rejected(settings):
    """A witness attesting some other hash is worse than none: it looks like
    evidence while proving nothing about the manifest in force."""
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    stale = sealmod.Witness(
        manifest_hash="0" * 64, kind="doi", identifier="10.5281/zenodo.stale", created_at=0.0
    )
    sealmod.write_witness(stale, sealmod.witness_path(settings.seal_path))

    state = sealmod.witness_state(seal, settings.seal_path)
    assert state.status == "MISMATCHED"
    with pytest.raises(RuntimeError, match="MISMATCHED"):
        sealmod.require_witnessed(seal, settings.seal_path)


def test_witness_referencing_a_missing_proof_is_rejected(settings):
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    w = sealmod.create_witness(seal, "ots", "protocol.ots", proof_file="protocol.ots")
    sealmod.write_witness(w, sealmod.witness_path(settings.seal_path))

    assert sealmod.witness_state(seal, settings.seal_path).status == "PROOF_MISSING"
    with pytest.raises(RuntimeError, match="PROOF_MISSING"):
        sealmod.require_witnessed(seal, settings.seal_path)


def test_require_witnessed_refuses_when_absent(settings):
    seal = sealmod.create(settings.root, "v1")
    sealmod.write(seal, settings.seal_path)
    with pytest.raises(RuntimeError, match="UNWITNESSED"):
        sealmod.require_witnessed(seal, settings.seal_path)


def test_witness_rejects_empty_identifier(settings):
    seal = sealmod.create(settings.root, "v1")
    with pytest.raises(ValueError):
        sealmod.create_witness(seal, "doi", "   ")


def test_run_refuses_without_seal(settings):
    with pytest.raises(RuntimeError, match="no seal"):
        sealmod.require_intact(settings.root, settings.seal_path)


def test_ledger_chain_and_tamper(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    for i in range(4):
        led.append(**{**BASE, "run_id": f"r{i}"})
    assert led.verify()[0]
    recs = list(led.read())
    recs[1].turns = 99
    assert not Ledger.verify_records(recs)[0]


def test_ledger_resumes(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.append(**BASE)
    assert Ledger(tmp_path / "l.jsonl").completed_cells() == {"C|T3": 1}


def test_ledger_surfaces_multiple_seals(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.append(**BASE)
    led.append(**{**BASE, "run_id": "r2", "seal_hash": "different"})
    assert len(led.seal_hashes()) == 2


def test_run_phase_refuses_real_collection_before_any_run_executes(settings):
    """Fail-closed must fire before the first session, not after.

    The factory raises if it is ever called; reaching it would mean budget was
    spent under a protocol with no evidence of predating the data.
    """
    from contextfidelity.design import build
    from contextfidelity.runner import run_phase

    sealmod.write(sealmod.create(settings.root, "v1"), settings.seal_path)

    def factory(planned):
        raise AssertionError("a run was started despite an unwitnessed seal")

    with pytest.raises(RuntimeError, match="refusing to collect real data"):
        run_phase(build(2)["phase1"], settings, factory, require_witness=True)


def test_run_phase_allows_replay_without_a_witness(settings):
    """Synthetic runs claim nothing about when the protocol existed, so the
    witness gate must not block pipeline validation."""
    from contextfidelity.design import build
    from contextfidelity.runner import run_phase

    sealmod.write(sealmod.create(settings.root, "v1"), settings.seal_path)
    out = run_phase(build(1)["phase1"], settings, _replay_factory, limit=2)
    assert out["executed"] == 2
    assert out["seal_status"] == "UNWITNESSED"


def test_verify_summaries_render(settings):
    """Regression: summary() referenced a field removed when the witness was
    split out of the seal, so `seal_protocol.py --verify` crashed while every
    unit test still passed."""
    sealmod.write(sealmod.create(settings.root, "v1"), settings.seal_path)
    assert "intact" in sealmod.verify(settings.root, settings.seal_path).summary()

    target = settings.root / "protocol" / "stopping_rules.yaml"
    target.write_text(target.read_text() + "\n# edited after sealing\n")
    broken = sealmod.verify(settings.root, settings.seal_path)
    assert not broken.ok
    assert "SEAL BROKEN" in broken.summary()
