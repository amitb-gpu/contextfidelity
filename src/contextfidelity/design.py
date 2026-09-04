"""The design: phases, cells, and the gates between them.

Phases are gated because RQ1 conditions RQ2 conditions RQ3. If within-session
attenuation does not reproduce, the complexity ladder measures the slope of
nothing and the remediation arms are a cure for a non-effect. Running all three
phases up front would spend the budget before the premise is tested.

Budget matters here. The original ran 50 sessions per condition across 24
conditions. Four rungs by four arms plus floor controls at that depth is 800+
sessions before a single question is answered. The gates exist so the expensive
phases are only reached if the cheap one earns them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from .rules import ALL_TASKS, ARMS, FLOOR_TASKS, LADDER, MULTI_TASKS, Task

PHASES = ("phase1", "phase2", "phase3")


@dataclass(frozen=True)
class Cell:
    cell_id: str
    phase: str
    rung: str
    arm: str
    config: bool  # False = no-configuration baseline
    tasks: tuple[str, ...]
    replicates: int
    purpose: str = ""

    def runs(self) -> int:
        return self.replicates * len(self.tasks)


@dataclass
class Phase:
    id: str
    question: str
    cells: list[Cell] = field(default_factory=list)
    gate: str = ""

    def runs(self) -> int:
        return sum(c.runs() for c in self.cells)


def build(replicates: int = 50, floor_replicates: int = 40) -> dict[str, Phase]:
    """The full plan. `replicates` is sessions per (cell, task)."""
    multi = tuple(t.id for t in MULTI_TASKS)
    floor = tuple(t.id for t in FLOOR_TASKS)

    p1 = Phase(
        "phase1",
        "RQ1: does within-session compliance attenuation replicate under a "
        "preregistered analysis?",
        gate="Proceed to phase 2 only if the phase-1 reproduction criterion in "
        "protocol/stopping_rules.yaml is met.",
    )
    p1.cells = [
        Cell("P1-BASE", "phase1", "L0", "A1", False, multi, replicates,
             "No-configuration baseline. Establishes the zero floor: the marker must "
             "never appear spontaneously, or the outcome measures something else."),
        Cell("P1-L0-A1", "phase1", "L0", "A1", True, multi, replicates,
             "The replication cell. Same rung spirit, same arm, same task shape as the "
             "original's primary pool."),
        Cell("P1-L0-FLOOR", "phase1", "L0", "A1", True, floor, floor_replicates,
             "Floor control. Compliance at generation position 1 must be high, or a "
             "flat slope is ambiguous between no attenuation and never complying."),
    ]

    p2 = Phase(
        "phase2",
        "RQ2: does the shape or magnitude of attenuation change with instruction "
        "complexity?",
        gate="Proceed to phase 3 only if at least one rung shows attenuation, and "
        "report the rung with the steepest preregistered slope as the phase-3 target.",
    )
    for rid in ("L1", "L2", "L3"):
        p2.cells.append(
            Cell(f"P2-{rid}-A1", "phase2", rid, "A1", True, multi, replicates,
                 f"Complexity rung {rid} under the baseline arm.")
        )
        p2.cells.append(
            Cell(f"P2-{rid}-FLOOR", "phase2", rid, "A1", True, floor, floor_replicates,
                 f"Floor control at {rid}. Separates inability to comply from decay in "
                 "compliance — decisive at L3, where a miss could be a retrieval failure.")
        )

    p3 = Phase(
        "phase3",
        "RQ3: can targeted rule re-surfacing reduce attenuation, and is any recovery "
        "attributable to rule content rather than attention interruption?",
    )
    for aid in ("A2", "A3", "A4"):
        p3.cells.append(
            Cell(f"P3-TARGET-{aid}", "phase3", "TARGET", aid, True, multi, replicates,
                 f"{ARMS[aid].name}: {ARMS[aid].description}")
        )

    return {"phase1": p1, "phase2": p2, "phase3": p3}


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    phase: str
    cell_id: str
    rung: str
    arm: str
    config: bool
    task_id: str
    replicate: int


def expand(phase: Phase, resolved_rung: str | None = None) -> Iterator[PlannedRun]:
    """Enumerate the runs for a phase in deterministic order.

    `resolved_rung` fills in phase 3's TARGET placeholder, which is not knowable
    until phase 2 completes — the placeholder exists so the plan can be sealed
    before the value is known, rather than the value being chosen after seeing
    phase-3 data.
    """
    for cell in phase.cells:
        rung = cell.rung
        if rung == "TARGET":
            if resolved_rung is None:
                raise ValueError(
                    f"cell {cell.cell_id} needs a resolved target rung from phase 2; "
                    "pass resolved_rung="
                )
            rung = resolved_rung
        for task_id in cell.tasks:
            for rep in range(1, cell.replicates + 1):
                yield PlannedRun(
                    run_id=f"{cell.cell_id}-{task_id}-r{rep:03d}",
                    phase=cell.phase,
                    cell_id=cell.cell_id,
                    rung=rung,
                    arm=cell.arm,
                    config=cell.config,
                    task_id=task_id,
                    replicate=rep,
                )


def budget(plan: dict[str, Phase]) -> dict[str, Any]:
    per_phase = {pid: ph.runs() for pid, ph in plan.items()}
    return {
        "runs_per_phase": per_phase,
        "total_runs": sum(per_phase.values()),
        "note": "Phases 2 and 3 are only reached if their gates pass. The realistic "
        "spend is phase 1 plus whatever the gates admit, not the total.",
    }


def task_by_id(task_id: str) -> Task:
    for t in ALL_TASKS:
        if t.id == task_id:
            return t
    raise KeyError(f"unknown task {task_id!r}")


def describe(plan: dict[str, Phase]) -> dict[str, Any]:
    return {
        pid: {
            "question": ph.question,
            "gate": ph.gate,
            "runs": ph.runs(),
            "cells": [asdict(c) for c in ph.cells],
        }
        for pid, ph in plan.items()
    }


def validate(plan: dict[str, Phase]) -> list[str]:
    """Structural checks that should hold before sealing."""
    problems: list[str] = []
    seen: set[str] = set()
    for ph in plan.values():
        for cell in ph.cells:
            if cell.cell_id in seen:
                problems.append(f"duplicate cell id {cell.cell_id}")
            seen.add(cell.cell_id)
            if cell.rung not in LADDER and cell.rung != "TARGET":
                problems.append(f"{cell.cell_id}: unknown rung {cell.rung}")
            if cell.arm not in ARMS:
                problems.append(f"{cell.cell_id}: unknown arm {cell.arm}")
            if cell.replicates < 1:
                problems.append(f"{cell.cell_id}: non-positive replicates")
    if not any(not c.config for c in plan["phase1"].cells):
        problems.append("phase1 has no no-configuration baseline cell")
    if not any("FLOOR" in c.cell_id for c in plan["phase1"].cells):
        problems.append("phase1 has no floor control")
    for rid in ("L1", "L2", "L3"):
        if not any(c.rung == rid and "FLOOR" in c.cell_id for c in plan["phase2"].cells):
            problems.append(f"phase2 has no floor control at {rid}")
    if not any(c.arm == "A4" for c in plan["phase3"].cells):
        problems.append("phase3 has no placebo arm; a positive A3 result would be uninterpretable")
    return problems
