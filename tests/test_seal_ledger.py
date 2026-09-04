import pytest
from contextfidelity import seal as sealmod
from contextfidelity.ledger import Ledger

BASE = dict(
    run_id="r1", phase="phase1", cell_id="C", rung="L0", arm="A1", task_id="T3",
    replicate=1, seal_hash="abc", target_commit="deadbeef", harness="replay",
    harness_version="0", model_id="m", config_sha256="x",
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


def test_unwitnessed_seal_is_marked(settings):
    assert sealmod.create(settings.root, "v1").status == "UNWITNESSED"
    assert sealmod.create(settings.root, "v1", "10.5281/zenodo.1").status == "WITNESSED"


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
