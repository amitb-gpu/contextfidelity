"""Executing a phase.

Order of operations per run, and the order matters:

  verify seal -> reset target repo -> inject config -> invoke agent ->
  capture diff + timeline -> score -> assign positions -> append to ledger

The seal is verified once before the phase, not per run, but its hash is written
into every record so a mid-phase re-seal is visible afterwards.

Repos are reset between runs. The original's design relies on run independence,
and carry-over would confound within-session attenuation with across-run drift.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from . import seal as sealmod
from .analysis.positions import assign_generation_positions, first_omission, post_omission_rate
from .config import Settings
from .design import Phase, PlannedRun, expand, task_by_id
from .harness import Harness, SessionResult, reset_repo
from .ledger import Ledger
from .rules import ARMS, LADDER, Rung, placebo_for
from .scoring import load_registry, score_run, summarize, to_rows

CONFIG_FILENAME = "CLAUDE.md"

CONFIG_TEMPLATE = """# Project conventions

{preamble}

## Required: audit annotations

{instruction}

This requirement applies for the whole session, to every function you write or
modify, however many that is.
"""

PREAMBLE = (
    "This repository follows the conventions below. They are maintained by the team "
    "and are expected to hold across every session."
)


def render_config(rung: Rung) -> str:
    return CONFIG_TEMPLATE.format(preamble=PREAMBLE, instruction=rung.instruction)


def resurfacing_text(arm_id: str, rung: Rung) -> str:
    arm = ARMS[arm_id]
    if not arm.resurfaces:
        return ""
    return placebo_for(rung) if arm.resurfaced_content == "placebo" else rung.instruction


def inject_config(repo: Path, rung: Rung, enabled: bool) -> str:
    """Write (or deliberately omit) the configuration file. Returns its sha256,
    or the empty string for the no-configuration baseline."""
    import hashlib

    target = Path(repo) / CONFIG_FILENAME
    if not enabled:
        if target.exists():
            target.unlink()
        return ""
    text = render_config(rung)
    target.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def assert_target_cwd(run_cwd: Path, settings: Settings, commit: str) -> None:
    """Refuse to invoke the real agent anywhere but the configured target.

    Without this, an unset target_repo silently resolves to Path(".") and the
    agent is turned loose on the study's own working tree — editing the very
    scorers and protocol files the seal exists to protect.
    """
    if settings.target_repo is None:
        raise RuntimeError(
            "refusing to run the real CLI with no target_repo configured: it would "
            "execute in the study's own working directory"
        )
    want = Path(settings.target_repo).resolve()
    got = Path(run_cwd).resolve()
    if got != want:
        raise RuntimeError(f"refusing to run: cwd {got} is not the configured target {want}")
    if not (got / ".git").exists():
        raise RuntimeError(f"refusing to run: {got} is not a git repository")
    head = subprocess.run(
        ["git", "-C", str(got), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if commit not in ("HEAD", "") and head != commit:
        raise RuntimeError(f"refusing to run: target HEAD {head[:12]} != pinned {commit[:12]}")


def execute_run(
    planned: PlannedRun,
    settings: Settings,
    harness: Harness,
    seal_hash: str,
    ledger: Ledger,
    artifacts_dir: Path,
) -> dict[str, Any]:
    rung = LADDER[planned.rung]
    task = task_by_id(planned.task_id)
    repo = settings.target_repo
    commit = settings.target_commit or "HEAD"

    if repo is not None:
        reset_repo(Path(repo), commit)
        config_sha = inject_config(Path(repo), rung, planned.config)
        registry = load_registry(Path(repo))
    else:
        config_sha = "" if not planned.config else "replay"
        registry = {}

    run_cwd = Path(repo) if repo else Path(".")
    if getattr(harness, "name", "") == "claude-code":
        assert_target_cwd(run_cwd, settings, commit)

    started = time.time()
    result: SessionResult = harness.run(run_cwd, task.prompt, settings.run_timeout_s)

    scores = score_run(result.changed_files, rung, registry)
    pos_report = assign_generation_positions(scores, result.timeline)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifacts_dir / f"{planned.run_id}.json"
    artifact.write_text(
        json.dumps(
            {
                "run_id": planned.run_id,
                "planned": asdict(planned),
                "status": result.status,
                "summary": summarize(scores),
                "positions": asdict(pos_report),
                "first_omission": first_omission(scores),
                "post_omission_rate": post_omission_rate(scores),
                "parse_warnings": result.parse_warnings,
                "scores": [asdict(s) for s in scores],
                "changed_files": sorted(result.changed_files),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    ledger.append(
        run_id=planned.run_id,
        phase=planned.phase,
        cell_id=planned.cell_id,
        rung=planned.rung,
        arm=planned.arm,
        task_id=planned.task_id,
        replicate=planned.replicate,
        seal_hash=seal_hash,
        target_commit=commit,
        harness=harness.name,
        harness_version=result.harness_version,
        model_id=result.model_id,
        config_sha256=config_sha,
        status=result.status,
        functions_emitted=len(scores),
        turns=result.turns,
        duration_s=round(time.time() - started, 3),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_write_tokens=result.cache_write_tokens,
        total_cost_usd=result.total_cost_usd,
        permission_denials=result.permission_denials,
        artifact_path=str(artifact),
        error=result.error[:500],
    )

    return {
        "run_id": planned.run_id,
        "status": result.status,
        "opportunities": len(scores),
        "position_coverage": pos_report.coverage,
        "rows": to_rows(scores, session_id=planned.run_id, cell_id=planned.cell_id,
                        arm=planned.arm, task_id=planned.task_id, phase=planned.phase),
    }


def run_phase(
    phase: Phase,
    settings: Settings,
    harness_factory: Callable[[PlannedRun], Harness],
    resolved_rung: str | None = None,
    limit: int | None = None,
    on_run: Callable[[dict[str, Any]], None] | None = None,
    require_witness: bool = False,
    max_consecutive_invalid: int = 5,
) -> dict[str, Any]:
    """Execute a phase. Verifies the seal once up front and refuses to run
    without it — data collected under a broken seal is not preregistered.

    `require_witness` additionally refuses to run without a valid external
    witness. Callers set it for real collection and leave it off for replay: an
    intact seal shows the protocol did not change, but only a witness shows it
    predates the data, and synthetic runs make no such claim.
    """
    seal = sealmod.require_intact(settings.root, settings.seal_path)
    if require_witness:
        sealmod.require_witnessed(seal, settings.seal_path)
    wstate = sealmod.witness_state(seal, settings.seal_path)
    ledger = Ledger(settings.ledger_dir / f"{phase.id}.jsonl")
    done = ledger.completed_cells()

    executed, skipped, rows = 0, 0, []
    consecutive_invalid = 0
    aborted: str | None = None
    for planned in expand(phase, resolved_rung):
        if limit is not None and executed >= limit:
            break
        key = f"{planned.cell_id}|{planned.task_id}"
        # Resume support: a phase interrupted halfway should not redo work.
        if done.get(key, 0) >= planned.replicate:
            skipped += 1
            continue
        harness = harness_factory(planned)
        out = execute_run(
            planned, settings, harness, seal.manifest_hash, ledger,
            settings.runs_dir / "artifacts" / phase.id,
        )
        rows.extend(out.pop("rows"))
        executed += 1
        if on_run:
            on_run(out)

        # Abort rather than grind on through a dead environment. When the quota
        # was exhausted mid-phase the run continued for 281 more sessions,
        # producing nothing and taking 40 minutes to do it. A run of consecutive
        # invalid sessions is an environment fault, and continuing only makes the
        # wreckage larger.
        consecutive_invalid = consecutive_invalid + 1 if out["status"] == "blocked" else 0
        if consecutive_invalid >= max_consecutive_invalid:
            aborted = (
                f"aborted after {consecutive_invalid} consecutive invalid sessions "
                f"(last: {out['run_id']}). The environment is not collecting data; "
                "these runs are excluded and the phase is resumable once it recovers."
            )
            break

    rows_path = settings.scored_dir / f"{phase.id}.jsonl"
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with rows_path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")

    ok, msg = ledger.verify()
    return {
        "phase": phase.id,
        "executed": executed,
        "skipped_already_done": skipped,
        "atom_rows": len(rows),
        "ledger": str(ledger.path),
        "ledger_intact": ok,
        "ledger_message": msg,
        "seal": seal.manifest_hash[:12],
        "seal_status": wstate.status,
        "witness": wstate.detail,
        "distinct_seals_in_ledger": sorted(h[:12] for h in ledger.seal_hashes()),
        "aborted": aborted,
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
