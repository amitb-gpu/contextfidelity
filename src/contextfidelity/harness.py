"""Agent harnesses.

Two implementations behind one interface:

  ClaudeCodeHarness  shells out to the real CLI in headless mode, captures the
                     streamed event log, and returns the post-run repository
                     diff plus the tool-call timeline.
  ReplayHarness      generates synthetic sessions from a specified compliance
                     process. Deterministic, offline, no cost. Used to test the
                     whole pipeline end to end, and to confirm the analysis
                     recovers a slope that was put in on purpose.

The replay harness is not a model simulator and must never be reported as one.
Its only job is to answer "if the effect were there, would this pipeline find
it?" — a question worth answering before spending the run budget.

The event-stream schema of a third-party CLI is not stable across versions. The
timeline parser below is written defensively and records the schema it saw, so a
silent format change surfaces as a parse warning rather than as an unexplained
drop in reconstructable positions.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np


@dataclass
class ToolEvent:
    order: int
    tool: str
    path: str | None = None


@dataclass
class SessionResult:
    status: str  # ok | no_code | error | timeout
    changed_files: dict[str, str] = field(default_factory=dict)
    timeline: list[ToolEvent] = field(default_factory=list)
    turns: int = 0
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    harness_version: str = ""
    model_id: str = ""
    raw_log: str = ""
    error: str = ""
    parse_warnings: list[str] = field(default_factory=list)


class Harness(Protocol):
    name: str

    def version(self) -> str: ...
    def run(self, repo: Path, prompt: str, timeout_s: int) -> SessionResult: ...


# -- real CLI ---------------------------------------------------------------

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Update", "Create"}


class ClaudeCodeHarness:
    name = "claude-code"

    def __init__(self, cli_path: str = "claude", model: str = "", extra_args: list[str] | None = None):
        self.cli_path = cli_path
        self.model = model
        self.extra_args = extra_args or []
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            try:
                proc = subprocess.run(
                    [self.cli_path, "--version"], capture_output=True, text=True, timeout=30
                )
                self._version = (proc.stdout or proc.stderr).strip()
            except Exception as exc:  # noqa: BLE001
                self._version = f"unknown ({type(exc).__name__})"
        return self._version

    def _argv(self, prompt: str) -> list[str]:
        argv = [self.cli_path, "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if self.model:
            argv += ["--model", self.model]
        return argv + self.extra_args

    def run(self, repo: Path, prompt: str, timeout_s: int = 900) -> SessionResult:
        started = time.time()
        try:
            proc = subprocess.run(
                self._argv(prompt),
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return SessionResult(
                status="timeout",
                duration_s=time.time() - started,
                harness_version=self.version(),
                model_id=self.model,
                error=f"exceeded {timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001
            return SessionResult(
                status="error",
                duration_s=time.time() - started,
                harness_version=self.version(),
                model_id=self.model,
                error=f"{type(exc).__name__}: {exc}",
            )

        result = parse_stream(proc.stdout)
        result.duration_s = time.time() - started
        result.harness_version = self.version()
        result.model_id = result.model_id or self.model
        result.raw_log = proc.stdout
        if proc.returncode != 0 and result.status == "ok":
            result.status = "error"
            result.error = (proc.stderr or "")[:2000]
        result.changed_files = changed_files(repo)
        if not result.changed_files:
            result.status = "no_code"
        return result


def parse_stream(stdout: str) -> SessionResult:
    """Extract the tool-call timeline and usage from a streamed JSON event log."""
    res = SessionResult(status="ok")
    order = 0
    seen_types: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            res.parse_warnings.append("non-JSON line in stream")
            continue
        seen_types.add(str(evt.get("type", "")))

        if evt.get("type") == "assistant":
            res.turns += 1
            for block in (evt.get("message", {}) or {}).get("content", []) or []:
                if block.get("type") == "tool_use":
                    order += 1
                    inp = block.get("input", {}) or {}
                    res.timeline.append(
                        ToolEvent(
                            order=order,
                            tool=str(block.get("name", "")),
                            path=inp.get("file_path") or inp.get("path") or inp.get("notebook_path"),
                        )
                    )
            usage = (evt.get("message", {}) or {}).get("usage", {}) or {}
            res.input_tokens += int(usage.get("input_tokens", 0) or 0)
            res.output_tokens += int(usage.get("output_tokens", 0) or 0)
            res.cache_read_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)
            res.cache_write_tokens += int(usage.get("cache_creation_input_tokens", 0) or 0)
            model = (evt.get("message", {}) or {}).get("model")
            if model:
                res.model_id = str(model)

    if not res.timeline:
        res.parse_warnings.append(
            f"no tool_use events recovered; event types seen: {sorted(seen_types)}. "
            "If the CLI changed its stream schema, generation positions cannot be "
            "reconstructed and the run must not be scored."
        )
    return res


def changed_files(repo: Path) -> dict[str, str]:
    """Post-run contents of every file differing from HEAD, including untracked."""
    out: dict[str, str] = {}
    tracked = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "HEAD"],
        capture_output=True, text=True,
    )
    untracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
    )
    for name in set((tracked.stdout + untracked.stdout).split()):
        p = Path(repo) / name
        if p.is_file():
            try:
                out[name] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


def reset_repo(repo: Path, commit: str) -> None:
    """Return the target to its pinned state between runs. Runs are independent
    by construction; carry-over would confound within-session attenuation with
    across-run drift."""
    subprocess.run(["git", "-C", str(repo), "reset", "--hard", commit], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-fdx"], capture_output=True, check=True)


# -- offline replay ---------------------------------------------------------


@dataclass
class ReplaySpec:
    """The generative process the replay harness draws from."""

    intercept_p: float = 0.677
    slope_log_odds: float = -0.0578
    session_sd: float = 0.6
    mean_functions: float = 16.0
    dispersion: float = 0.45
    no_code_rate: float = 0.0
    seed: int = 0
    config_present: bool = True
    single_function: bool = False


class ReplayHarness:
    """Synthesizes a TypeScript file whose functions comply or not according to
    ReplaySpec. Used to verify the pipeline recovers a known slope."""

    name = "replay"

    def __init__(self, spec: ReplaySpec | None = None, rung_id: str = "L0"):
        self.spec = spec or ReplaySpec()
        self.rung_id = rung_id
        self._rng = np.random.default_rng(self.spec.seed)
        self._n = 0

    def version(self) -> str:
        return f"replay/{self.spec.seed}"

    def run(self, repo: Path, prompt: str, timeout_s: int = 0) -> SessionResult:
        from .rules import LADDER

        self._n += 1
        rng = self._rng
        if rng.random() < self.spec.no_code_rate:
            return SessionResult(status="no_code", harness_version=self.version())

        k = (
            1
            if self.spec.single_function
            else int(max(1, round(rng.lognormal(
                np.log(self.spec.mean_functions), self.spec.dispersion))))
        )
        re_i = rng.normal(0.0, self.spec.session_sd)
        base = float(np.log(self.spec.intercept_p / (1 - self.spec.intercept_p)))
        rung = LADDER[self.rung_id]

        body_parts, timeline = [], []
        path = f"src/generated/session_{self._n:04d}.ts"
        for i in range(k):
            if not self.spec.config_present:
                # No configuration file means the rule was never stated. The
                # marker must never appear spontaneously; that zero floor is
                # what makes the outcome measure instruction-driven behaviour.
                comply = False
            else:
                eta = base + re_i + self.spec.slope_log_odds * i
                comply = rng.random() < 1.0 / (1.0 + np.exp(-eta))
            body_parts.append(_synth_function(f"fn{i:03d}", rung.id, comply, path))
            timeline.append(ToolEvent(order=i + 1, tool="Write", path=path))

        return SessionResult(
            status="ok",
            changed_files={path: "\n\n".join(body_parts) + "\n"},
            timeline=timeline,
            turns=k,
            duration_s=0.0,
            harness_version=self.version(),
            model_id="replay",
        )


def _synth_function(name: str, rung_id: str, comply: bool, path: str) -> str:
    from .rules import (
        JSDOC_TAG_L2, MARKER_L0, MARKER_L1, MARKER_L2_END, MARKER_L2_OPEN,
        MARKER_L3_STANDARD,
    )

    stem = Path(path).stem
    if rung_id == "L0":
        first = f"  {MARKER_L0}\n" if comply else ""
        return f"export async function {name}() {{\n{first}  return {name!r};\n}}"
    if rung_id == "L1":
        first = f"  {MARKER_L1}\n" if comply else ""
        return f"export async function {name}() {{\n{first}  return {name!r};\n}}"
    if rung_id == "L2":
        doc = f"/**\n * {name}\n * {JSDOC_TAG_L2} {stem}\n */\n" if comply else "/**\n * x\n */\n"
        open_m = f"  {MARKER_L2_OPEN}\n" if comply else ""
        end_m = f"\n  {MARKER_L2_END}" if comply else ""
        return f"{doc}export async function {name}() {{\n{open_m}  return {name!r};{end_m}\n}}"
    first = f"  {MARKER_L3_STANDARD}\n" if comply else ""
    return f"export async function {name}() {{\n{first}  return {name!r};\n}}"


def make_harness(settings: Any, rung_id: str = "L0", spec: ReplaySpec | None = None) -> Harness:
    if settings.harness == "claude-code":
        return ClaudeCodeHarness(settings.cli_path, settings.model)
    return ReplayHarness(spec, rung_id)
