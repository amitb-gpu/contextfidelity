"""The instruction complexity ladder.

The artifact to avoid: if a harder rung simply requires more observable actions,
an all-or-nothing compliance score falls mechanically even when the probability
of obeying each atomic instruction is unchanged. A ladder built carelessly
manufactures its own effect.

Two design commitments handle this.

**Opportunity is the unit, and every rung has the same opportunities.** At every
rung, an opportunity is one new-or-modified function. Not "functions where the
rule applies" — every function. L1 and L3 vary *what* the correct behaviour is
per function rather than *whether* there is one, so opportunity counts are
matched by construction rather than by hoping the tasks balance out.

**Two scales are reported and only one is primary.** Atomic compliance is the
proportion of individual required actions performed; complete compliance is the
proportion of opportunities where every action was performed. L2 has three
atoms, so its complete rate falls relative to L0 at equal atom probability —
that is arithmetic, not a finding. Atomic is the primary scale for cross-rung
comparison; complete is secondary and reported for practitioner relevance.

L1 additionally carries a directional sub-stratum: opportunities where the
predicate is true (the marker must be present) versus false (it must be absent).
Reporting these pooled would hide the difference between an agent that stops
applying a rule and one that applies it indiscriminately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

MARKER_L0 = "// @tracked"
MARKER_L1 = "// @audited"
MARKER_L2_OPEN = "// @tracked"
MARKER_L2_END = "// @end-tracked"
JSDOC_TAG_L2 = "@audit-scope"
MARKER_L3_STRICT = "// @tracked:strict"
MARKER_L3_STANDARD = "// @tracked:standard"

REGISTRY_FILE = "audit-registry.json"


@dataclass(frozen=True)
class Atom:
    """One mechanically checkable required action within a rule."""

    id: str
    description: str


@dataclass(frozen=True)
class Rung:
    id: str
    name: str
    n_atoms: int
    atoms: tuple[Atom, ...]
    instruction: str
    needs_registry: bool = False
    strata: tuple[str, ...] = ("all",)
    notes: str = ""

    def atom_ids(self) -> list[str]:
        return [a.id for a in self.atoms]


L0 = Rung(
    id="L0",
    name="static local rule",
    n_atoms=1,
    atoms=(Atom("marker", "function body begins with the tracked marker"),),
    instruction=(
        f"Every function you create or modify MUST begin its body with the comment "
        f"`{MARKER_L0}` as the first line inside the braces. This is required by our "
        "internal code-audit system. Apply it to every function without exception."
    ),
    notes="Reproduces the spirit of the original target instruction: one action, every function.",
)

L1 = Rung(
    id="L1",
    name="conditional local rule",
    n_atoms=1,
    atoms=(Atom("conditional_marker", "marker present iff the local predicate holds"),),
    instruction=(
        f"Functions that are BOTH exported AND async MUST begin their body with the "
        f"comment `{MARKER_L1}` as the first line. Functions that are not both exported "
        f"and async MUST NOT carry that comment. The audit system treats a misapplied "
        "marker as seriously as a missing one."
    ),
    strata=("predicate_true", "predicate_false"),
    notes=(
        "Predicate is locally visible in the function's own declaration, so a miss is "
        "an adherence failure rather than a retrieval failure."
    ),
)

L2 = Rung(
    id="L2",
    name="multi-step procedural rule",
    n_atoms=3,
    atoms=(
        Atom("open_marker", "body begins with the tracked marker"),
        Atom("jsdoc_scope", "JSDoc above the function carries the audit-scope tag with the file stem"),
        Atom("end_marker", "body's last line is the end marker"),
    ),
    instruction=(
        "Every function you create or modify MUST satisfy all three of the following, "
        "in this order:\n"
        f"1. The first line inside the function body is `{MARKER_L2_OPEN}`.\n"
        f"2. Immediately above the function there is a JSDoc block containing "
        f"`{JSDOC_TAG_L2} <name>`, where <name> is the file's name without its "
        "extension.\n"
        f"3. The last line inside the function body is `{MARKER_L2_END}`.\n"
        "All three are required. A function with only some of them is not compliant."
    ),
    notes=(
        "Three atoms. Complete-rate comparison against L0 is arithmetically biased "
        "downward; use the atomic scale for cross-rung inference."
    ),
)

L3 = Rung(
    id="L3",
    name="cross-file rule",
    n_atoms=1,
    atoms=(Atom("registry_marker", "marker variant matches the registry classification"),),
    instruction=(
        f"The repository contains `{REGISTRY_FILE}` at its root, mapping source paths to "
        "an audit tier of either `strict` or `standard`. Every function you create or "
        "modify MUST begin its body with the marker for the tier that applies to the "
        f"file it lives in: `{MARKER_L3_STRICT}` for strict, `{MARKER_L3_STANDARD}` for "
        "standard. Files not listed in the registry inherit the tier of their nearest "
        "listed parent directory; if no parent is listed, they are standard."
    ),
    needs_registry=True,
    strata=("tier_strict", "tier_standard"),
    notes=(
        "The only rung where non-compliance can arise from failing to consult an "
        "external file rather than from adherence decay. The floor-control condition "
        "at this rung is what separates the two: an agent that cannot comply at "
        "generation position 1 has a retrieval problem, not an attenuation problem."
    ),
)

LADDER: dict[str, Rung] = {r.id: r for r in (L0, L1, L2, L3)}


PLACEBO_RULE = (
    "When you create a new file, prefer the file naming convention already present in "
    "the surrounding directory rather than introducing a new one. Match the existing "
    "casing style, separator style, and extension conventions used by sibling files. "
    "Consistency in file naming is required by our repository hygiene policy and is "
    "checked during review."
)
"""Matched-length irrelevant rule for the placebo re-surfacing arm.

The arm exists because event-triggered re-surfacing changes three things at once:
the rule becomes salient, it becomes recent, and the context grows. If
re-surfacing an unrelated rule also restores compliance, the mechanism is
attention interruption rather than rule content — which is a more informative
result than the one being hunted, and unreachable without this arm.

Length must be checked against the live rung instruction, not assumed; see
`placebo_length_ratio`.
"""


_PLACEBO_PADDING = [
    "Directory-level conventions take precedence over global ones where the two "
    "disagree, and the existing convention in a directory is authoritative.",
    "Where a directory contains no sibling files to imitate, follow the convention "
    "used by the nearest parent directory that does.",
    "Renaming existing files to match a new convention is out of scope; the rule "
    "applies to files you create.",
]


def placebo_for(rung: Rung, lo: float = 0.75, hi: float = 1.33) -> str:
    """A length-matched placebo for a specific rung.

    One fixed placebo cannot be length-matched to every rung — L2's instruction
    is several times the length of L0's — and an unmatched placebo would
    confound rule content with injected token count, which is precisely the
    confound the A4 arm exists to remove. So the placebo is assembled per rung
    from a fixed, sealed clause pool: sentences are added while the text is too
    short and dropped while it is too long, always at sentence boundaries.

    Deterministic and sealed, so the arm cannot be tuned after seeing results.
    """
    pool = [PLACEBO_RULE, *_PLACEBO_PADDING]
    target = len(rung.instruction.split())

    # Sentence-level units, in fixed order.
    units: list[str] = []
    for block in pool:
        units.extend(s.strip() + "." for s in block.split(". ") if s.strip())
    units = [u.rstrip(".") + "." for u in units]

    best, best_gap = units[0], float("inf")
    for n in range(1, len(units) + 1):
        text = " ".join(units[:n])
        ratio = len(text.split()) / max(1, target)
        gap = abs(ratio - 1.0)
        if gap < best_gap:
            best, best_gap = text, gap
        if lo <= ratio <= hi and gap < 0.2:
            return text
    return best


def placebo_length_ratio(rung: Rung) -> float:
    """Placebo / target instruction length in whitespace-delimited tokens.

    Preregistration commits to keeping this within [0.75, 1.33]. If a rung falls
    outside, pad or trim the placebo before sealing rather than after seeing runs.
    """
    return len(placebo_for(rung).split()) / max(1, len(rung.instruction.split()))


def placebo_balanced(rung: Rung, lo: float = 0.75, hi: float = 1.33) -> bool:
    return lo <= placebo_length_ratio(rung) <= hi


@dataclass
class Arm:
    id: str
    name: str
    resurfaces: bool
    resurfaced_content: str  # "target" | "placebo" | ""
    trigger: str  # "" | "periodic" | "event"
    description: str


ARMS: dict[str, Arm] = {
    "A1": Arm(
        "A1",
        "configuration only",
        False,
        "",
        "",
        "The rule appears once, in the configuration file, at session start. "
        "Baseline condition and the one the original study measured.",
    ),
    "A2": Arm(
        "A2",
        "periodic reminder",
        True,
        "target",
        "periodic",
        "The rule is re-injected every N file-touching tool calls regardless of what "
        "the agent is doing. Controls for re-surfacing timing being irrelevant.",
    ),
    "A3": Arm(
        "A3",
        "event-triggered re-surfacing",
        True,
        "target",
        "event",
        "The rule is re-injected when the agent is about to write a function, i.e. at "
        "the moment it applies. This is the progressive-disclosure intervention.",
    ),
    "A4": Arm(
        "A4",
        "placebo re-surfacing",
        True,
        "placebo",
        "event",
        "An unrelated rule of matched length is re-injected at the same trigger points "
        "as A3. Separates rule content from attention interruption.",
    ),
}


@dataclass
class Task:
    id: str
    prompt: str
    kind: str  # "write_new" | "modify_existing"
    expected_functions: str  # "single" | "multi"
    description: str = ""


TASK_PROVENANCE = """Task provenance, stated plainly because it bounds what this study can claim.

McMillan (2026) publishes task *descriptions*, not verbatim prompts. T3, T4 and
T5 below are therefore RECONSTRUCTED from those published descriptions, not
copied. They are worded to be executable against the reconstructed baseline
780c3dca75e6b39d92c8ac287618ed624eae802a of ixartz/Next-js-Boilerplate, and
deliberately carry no requirement that the publication does not describe. In
particular, none of them was padded to raise function counts: doing so would
manufacture the very artifact the opportunity-matched ladder exists to prevent.

F1 is NOT from McMillan's task set. It is a ContextFidelity floor control, and
is labelled as such wherever it appears, so that it is never reported as part of
the replicated task pool.

If verbatim prompts are later obtained from the author, replacing these is a
protocol amendment and must be recorded as a new seal version.
"""


FLOOR_TASKS: tuple[Task, ...] = (
    Task(
        "F1",
        "Add a single exported async function `getBuildInfo` to src/libs/BuildInfo.ts "
        "that returns an object with the current package version and build timestamp. "
        "Create the file if it does not exist. Write exactly one function.",
        "write_new",
        "single",
        "ContextFidelity floor control, NOT part of McMillan's task set. Establishes "
        "that the agent CAN comply at generation position 1 at this rung. Without it, "
        "a flat slope is ambiguous between 'no attenuation' and 'never complied at "
        "all'. Path uses src/libs/ to match the baseline's existing convention; the "
        "repository has no src/lib/ directory, and creating one would interact with "
        "the naming-convention placebo rule.",
    ),
)

MULTI_TASKS: tuple[Task, ...] = (
    Task(
        "T3",
        "Integrate NextAuth into this application. Add the NextAuth route handler, a "
        "shared auth configuration registering at least one provider, a session "
        "provider wrapping the application, and the helper functions needed to read "
        "the current session from server components and from client components.",
        "write_new",
        "multi",
        "RECONSTRUCTED from McMillan's published T3 description ('NextAuth "
        "integration'). Note the baseline ships Clerk (@clerk/nextjs), so this asks "
        "the agent to introduce a second auth stack. That is a property of the "
        "published task against this repository, not a defect introduced here, and it "
        "is not corrected: silently substituting a Clerk task would make the task pool "
        "diverge from the publication being replicated.",
    ),
    Task(
        "T4",
        "The dashboard and marketing layouts each define their navigation links inline "
        "and pass them to BaseTemplate. Refactor so that navigation is defined in one "
        "shared place and consumed by both, introducing a sidebar navigation component "
        "that the dashboard layout uses. Update every affected layout and component.",
        "modify_existing",
        "multi",
        "RECONSTRUCTED from McMillan's published T4 description ('Sidebar/layout "
        "refactor'). Grounded in the baseline's actual duplication: leftNav/rightNav "
        "are passed inline to BaseTemplate from several layouts. The original's "
        "lowest-compliance task type, and the modify-vs-write contrast was their "
        "largest single observation.",
    ),
    Task(
        "T5",
        "Add an analytics page to the dashboard at "
        "src/app/[locale]/(auth)/dashboard/analytics/page.tsx. Include loading "
        "skeleton components displayed while data is pending, the data-fetching layer "
        "the page requires, and container components for the charts.",
        "write_new",
        "multi",
        "RECONSTRUCTED from McMillan's published T5 description ('dashboard analytics "
        "page with loading skeletons'). Path follows the baseline's locale-segmented "
        "app router layout; a bare src/app/dashboard/ path does not exist in this "
        "repository. Distinct from the existing src/components/analytics/ PostHog "
        "components, which are unrelated.",
    ),
)

ALL_TASKS: tuple[Task, ...] = FLOOR_TASKS + MULTI_TASKS


def rung(rung_id: str) -> Rung:
    if rung_id not in LADDER:
        raise KeyError(f"unknown rung {rung_id!r}; expected one of {sorted(LADDER)}")
    return LADDER[rung_id]


def arm(arm_id: str) -> Arm:
    if arm_id not in ARMS:
        raise KeyError(f"unknown arm {arm_id!r}; expected one of {sorted(ARMS)}")
    return ARMS[arm_id]
