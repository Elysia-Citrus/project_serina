from __future__ import annotations

import json
from pathlib import Path

from src.evals.models import EvalCase


DEFAULT_SUITE = "smoke"


def resolve_case_path(
    *,
    cases_path: str | Path | None = None,
    suite_name: str = DEFAULT_SUITE,
) -> Path:
    if cases_path is not None:
        return Path(cases_path).resolve()

    return (
        Path(__file__).resolve().parents[2]
        / "evals"
        / "cases"
        / f"{suite_name}_cases.jsonl"
    ).resolve()


def load_eval_cases(
    path: str | Path,
    *,
    enabled_only: bool = True,
) -> list[EvalCase]:
    resolved_path = Path(path).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Eval case file not found: {resolved_path}")

    cases: list[EvalCase] = []
    for index, line in enumerate(
        resolved_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw_case = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {index}: {resolved_path}") from exc

        case = EvalCase.from_mapping(raw_case)
        if enabled_only and not case.enabled:
            continue
        cases.append(case)

    return cases
