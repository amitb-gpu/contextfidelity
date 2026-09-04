"""Deterministic scoring.

Function extraction is AST-based via tree-sitter (TSX grammar, which parses both
.ts and .tsx). Marker checks operate on the function's own source span and the
comment block immediately above it. The scorer is pure: same diff in, same score
out, no model involved. It is sealed alongside the protocol, because a frozen
protocol with a mutable scorer is not a preregistration.

Every function in the changed set is an opportunity at every rung. What varies
by rung is the number of atoms per opportunity and what counts as correct, never
whether an opportunity exists. See rules.py for why.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .rules import (
    JSDOC_TAG_L2,
    MARKER_L0,
    MARKER_L1,
    MARKER_L2_END,
    MARKER_L2_OPEN,
    MARKER_L3_STANDARD,
    MARKER_L3_STRICT,
    Rung,
)

FUNCTION_NODES = {
    "function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
    "generator_function_declaration",
}

_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript as tst

        _parser = Parser(Language(tst.language_tsx()))
    return _parser


@dataclass
class FunctionSpan:
    file: str
    name: str
    start_line: int
    end_line: int
    source: str
    body_source: str
    is_exported: bool
    is_async: bool
    leading_comment: str = ""

    def key(self) -> tuple[str, str, int]:
        return (self.file, self.name, self.start_line)


def _node_text(src: bytes, node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _name_of(src: bytes, node) -> str:
    for field_name in ("name", "property"):
        child = node.child_by_field_name(field_name)
        if child is not None:
            return _node_text(src, child)
    parent = node.parent
    if parent is not None and parent.type in ("variable_declarator", "public_field_definition"):
        child = parent.child_by_field_name("name")
        if child is not None:
            return _node_text(src, child)
    return f"<anonymous@{node.start_point[0] + 1}>"


def _is_exported(src: bytes, node) -> bool:
    cur = node
    for _ in range(6):
        if cur is None:
            break
        if cur.type == "export_statement":
            return True
        cur = cur.parent
    return False


def _leading_comment(src: bytes, root, node) -> str:
    """Contiguous comment block immediately above the function (or its export
    statement), which is where a JSDoc block lives."""
    anchor = node
    cur = node
    for _ in range(4):
        if cur is None:
            break
        if cur.type in ("export_statement", "lexical_declaration", "variable_declaration"):
            anchor = cur
        cur = cur.parent

    prev = anchor.prev_sibling
    parts: list[str] = []
    while prev is not None and prev.type == "comment":
        parts.append(_node_text(src, prev))
        prev = prev.prev_sibling
    return "\n".join(reversed(parts))


def extract_functions(path: str, source: str) -> list[FunctionSpan]:
    parser = _get_parser()
    src = source.encode("utf-8")
    tree = parser.parse(src)
    out: list[FunctionSpan] = []

    def walk(node) -> None:
        if node.type in FUNCTION_NODES:
            body = node.child_by_field_name("body")
            body_src = _node_text(src, body) if body is not None else ""
            out.append(
                FunctionSpan(
                    file=path,
                    name=_name_of(src, node),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source=_node_text(src, node),
                    body_source=body_src,
                    is_exported=_is_exported(src, node),
                    is_async="async" in _node_text(src, node)[:40],
                    leading_comment=_leading_comment(src, tree.root_node, node),
                )
            )
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    out.sort(key=lambda f: (f.file, f.start_line))
    return out


# -- body line helpers ------------------------------------------------------


def _body_lines(body_source: str) -> list[str]:
    """Non-empty lines inside the braces, stripped."""
    inner = body_source.strip()
    if inner.startswith("{"):
        inner = inner[1:]
    if inner.endswith("}"):
        inner = inner[:-1]
    return [ln.strip() for ln in inner.splitlines() if ln.strip()]


def _first_line(body_source: str) -> str:
    lines = _body_lines(body_source)
    return lines[0] if lines else ""


def _last_line(body_source: str) -> str:
    lines = _body_lines(body_source)
    return lines[-1] if lines else ""


def _has_marker_anywhere(body_source: str, marker: str) -> bool:
    return any(ln == marker for ln in _body_lines(body_source))


# -- registry (L3) ----------------------------------------------------------


def load_registry(repo_root: Path, filename: str = "audit-registry.json") -> dict[str, str]:
    path = Path(repo_root) / filename
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k.strip("/"): v for k, v in raw.items()}


def registry_tier(file_path: str, registry: dict[str, str]) -> str:
    """Exact match, then nearest listed parent directory, then 'standard'."""
    norm = file_path.strip("/")
    if norm in registry:
        return registry[norm]
    parts = norm.split("/")
    for i in range(len(parts) - 1, 0, -1):
        prefix = "/".join(parts[:i])
        if prefix in registry:
            return registry[prefix]
    return "standard"


# -- scoring ----------------------------------------------------------------


@dataclass
class AtomResult:
    atom_id: str
    passed: bool


@dataclass
class OpportunityScore:
    file: str
    function: str
    start_line: int
    rung: str
    stratum: str
    atoms: list[AtomResult] = field(default_factory=list)
    generation_position: int | None = None

    @property
    def n_atoms(self) -> int:
        return len(self.atoms)

    @property
    def n_passed(self) -> int:
        return sum(1 for a in self.atoms if a.passed)

    @property
    def complete(self) -> bool:
        return bool(self.atoms) and all(a.passed for a in self.atoms)


def score_function(fn: FunctionSpan, rung: Rung, registry: dict[str, str] | None = None) -> OpportunityScore:
    registry = registry or {}
    body = fn.body_source

    if rung.id == "L0":
        return OpportunityScore(
            fn.file, fn.name, fn.start_line, "L0", "all",
            [AtomResult("marker", _first_line(body) == MARKER_L0)],
        )

    if rung.id == "L1":
        predicate = fn.is_exported and fn.is_async
        present = _has_marker_anywhere(body, MARKER_L1)
        first_ok = _first_line(body) == MARKER_L1
        passed = first_ok if predicate else not present
        return OpportunityScore(
            fn.file, fn.name, fn.start_line, "L1",
            "predicate_true" if predicate else "predicate_false",
            [AtomResult("conditional_marker", passed)],
        )

    if rung.id == "L2":
        stem = Path(fn.file).stem
        jsdoc = fn.leading_comment
        return OpportunityScore(
            fn.file, fn.name, fn.start_line, "L2", "all",
            [
                AtomResult("open_marker", _first_line(body) == MARKER_L2_OPEN),
                AtomResult(
                    "jsdoc_scope",
                    bool(re.search(rf"{re.escape(JSDOC_TAG_L2)}\s+{re.escape(stem)}\b", jsdoc)),
                ),
                AtomResult("end_marker", _last_line(body) == MARKER_L2_END),
            ],
        )

    if rung.id == "L3":
        tier = registry_tier(fn.file, registry)
        expected = MARKER_L3_STRICT if tier == "strict" else MARKER_L3_STANDARD
        return OpportunityScore(
            fn.file, fn.name, fn.start_line, "L3", f"tier_{tier}",
            [AtomResult("registry_marker", _first_line(body) == expected)],
        )

    raise KeyError(f"no scorer for rung {rung.id!r}")


def score_run(
    changed_files: dict[str, str],
    rung: Rung,
    registry: dict[str, str] | None = None,
) -> list[OpportunityScore]:
    """changed_files maps repo-relative path -> post-run file contents."""
    scores: list[OpportunityScore] = []
    for path, source in sorted(changed_files.items()):
        if not path.endswith((".ts", ".tsx")):
            continue
        for fn in extract_functions(path, source):
            scores.append(score_function(fn, rung, registry))
    return scores


def summarize(scores: list[OpportunityScore]) -> dict[str, Any]:
    """Both scales, never one. See rules.py for why complete-rate is not
    comparable across rungs with different atom counts."""
    n_opps = len(scores)
    n_atoms = sum(s.n_atoms for s in scores)
    n_atoms_passed = sum(s.n_passed for s in scores)
    n_complete = sum(1 for s in scores if s.complete)
    by_stratum: dict[str, dict[str, int]] = {}
    for s in scores:
        b = by_stratum.setdefault(s.stratum, {"opportunities": 0, "atoms": 0, "atoms_passed": 0, "complete": 0})
        b["opportunities"] += 1
        b["atoms"] += s.n_atoms
        b["atoms_passed"] += s.n_passed
        b["complete"] += int(s.complete)
    return {
        "opportunities": n_opps,
        "atoms": n_atoms,
        "atomic_rate": (n_atoms_passed / n_atoms) if n_atoms else None,
        "complete_rate": (n_complete / n_opps) if n_opps else None,
        "by_stratum": by_stratum,
    }


def to_rows(scores: list[OpportunityScore], **meta: Any) -> list[dict[str, Any]]:
    """Flatten to atom-level rows for analysis. One row per atom, carrying the
    session and opportunity identifiers needed for the nested random structure."""
    rows: list[dict[str, Any]] = []
    for opp_index, s in enumerate(scores):
        for atom in s.atoms:
            rows.append(
                {
                    **meta,
                    "file": s.file,
                    "function": s.function,
                    "start_line": s.start_line,
                    "rung": s.rung,
                    "stratum": s.stratum,
                    "opportunity_index": opp_index,
                    "generation_position": s.generation_position,
                    "atom_id": atom.atom_id,
                    "passed": int(atom.passed),
                    "complete": int(s.complete),
                }
            )
    return rows


def dump(scores: list[OpportunityScore]) -> list[dict[str, Any]]:
    return [asdict(s) for s in scores]
