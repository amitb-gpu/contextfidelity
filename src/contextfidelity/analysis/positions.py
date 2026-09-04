"""Reconstructing generation order.

The predictor of interest is *chronological* position: the order in which the
agent actually emitted each function within the session. It is recovered by
matching scored functions to the session's file-touching tool calls.

The original reported this as primary over an AST-traversal index, and used the
traversal index as a sensitivity. Both are implemented here for the same reason:
they answer slightly different questions, and disagreement between them is
informative rather than a nuisance.

Functions in files the agent never touched have no chronological position and
are excluded by construction — not dropped quietly, but counted and reported,
because a high exclusion rate means the timeline parse is failing and the run
should not be scored at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ..harness import ToolEvent
from ..scoring import OpportunityScore

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Update", "Create"}


@dataclass
class PositionReport:
    assigned: int
    unassigned: int
    files_touched: int
    method: str

    @property
    def coverage(self) -> float:
        total = self.assigned + self.unassigned
        return self.assigned / total if total else 0.0

    def usable(self, min_coverage: float = 0.80) -> bool:
        return self.coverage >= min_coverage


def _file_order(timeline: Sequence[ToolEvent]) -> dict[str, int]:
    """First touch order per file. A file edited repeatedly takes its earliest
    emission rank, matching the original's treatment."""
    order: dict[str, int] = {}
    rank = 0
    for evt in sorted(timeline, key=lambda e: e.order):
        if evt.tool not in FILE_TOOLS or not evt.path:
            continue
        key = evt.path.lstrip("./")
        if key not in order:
            rank += 1
            order[key] = rank
    return order


def assign_generation_positions(
    scores: list[OpportunityScore],
    timeline: Sequence[ToolEvent],
    method: str = "chronological",
) -> PositionReport:
    """Mutates `scores` in place, setting `generation_position` where derivable."""
    if method == "ast":
        for i, s in enumerate(sorted(scores, key=lambda s: (s.file, s.start_line)), start=1):
            s.generation_position = i
        return PositionReport(len(scores), 0, len({s.file for s in scores}), "ast")

    file_rank = _file_order(timeline)
    if not file_rank:
        for s in scores:
            s.generation_position = None
        return PositionReport(0, len(scores), 0, "chronological")

    # Order by (file emission rank, line number within file), then number 1..n.
    ranked = []
    unassigned = 0
    for s in scores:
        key = s.file.lstrip("./")
        rank = file_rank.get(key)
        if rank is None:
            s.generation_position = None
            unassigned += 1
        else:
            ranked.append((rank, s.start_line, s))

    ranked.sort(key=lambda t: (t[0], t[1]))
    for i, (_, _, s) in enumerate(ranked, start=1):
        s.generation_position = i

    return PositionReport(len(ranked), unassigned, len(file_rank), "chronological")


def positioned(scores: Iterable[OpportunityScore]) -> list[OpportunityScore]:
    return [s for s in scores if s.generation_position is not None]


def first_omission(scores: Sequence[OpportunityScore]) -> int | None:
    """Generation position of the first non-compliant opportunity, or None.

    The original found a median first omission at position 4 with post-omission
    compliance around 55%, which is why they could not tell early-loading failure
    apart from gradual drift. Recording it per run is what makes that separable
    here rather than another open question.
    """
    ordered = sorted(positioned(scores), key=lambda s: s.generation_position or 0)
    for s in ordered:
        if not s.complete:
            return s.generation_position
    return None


def post_omission_rate(scores: Sequence[OpportunityScore]) -> float | None:
    """Complete-compliance rate strictly after the first omission. A value near
    zero means the run abandoned the rule; a middling value means it kept
    intermittently re-complying, which is a different mechanism."""
    fo = first_omission(scores)
    if fo is None:
        return None
    after = [s for s in positioned(scores) if (s.generation_position or 0) > fo]
    if not after:
        return None
    return sum(1 for s in after if s.complete) / len(after)
