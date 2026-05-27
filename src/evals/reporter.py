from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from statistics import mean

from src.evals.models import EvalCaseResult, EvalRunSummary


def create_output_dir(base_output_dir: str | Path) -> Path:
    base_dir = Path(base_output_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    candidate = base_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = base_dir / f"{timestamp}_{suffix:02d}"
        suffix += 1

    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def write_results_bundle(
    *,
    output_dir: str | Path,
    results: list[EvalCaseResult],
    summary: EvalRunSummary,
) -> None:
    resolved_dir = Path(output_dir).resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(resolved_dir / "results.jsonl", results)
    _write_json(resolved_dir / "summary.json", summary.to_dict())
    _write_markdown(resolved_dir / "summary.md", results, summary)


def build_summary(
    *,
    results: list[EvalCaseResult],
    output_dir: str | Path,
    mode: str,
    suite_name: str,
    trace_log_path: str | None = None,
) -> EvalRunSummary:
    total_cases = len(results)
    success_count = sum(1 for result in results if result.success)
    failure_count = total_cases - success_count
    scene_match_rate = _ratio(sum(1 for result in results if result.scene_match), total_cases)
    length_band_match_rate = _ratio(
        sum(1 for result in results if result.length_band_match),
        total_cases,
    )
    forbidden_hit_case_count = sum(1 for result in results if result.forbidden_hits)
    empty_response_count = sum(1 for result in results if result.response_length == 0)
    latencies = [result.latency_ms for result in results if result.latency_ms is not None]
    avg_latency_ms = round(mean(latencies), 2) if latencies else 0.0
    p95_latency_ms = _p95(latencies)

    by_tag: dict[str, dict[str, object]] = {}
    all_tags = sorted({tag for result in results for tag in result.tags})
    for tag in all_tags:
        tagged = [result for result in results if tag in result.tags]
        tagged_latencies = [result.latency_ms for result in tagged if result.latency_ms is not None]
        by_tag[tag] = {
            "total_cases": len(tagged),
            "success_count": sum(1 for result in tagged if result.success),
            "scene_match_rate": _ratio(
                sum(1 for result in tagged if result.scene_match),
                len(tagged),
            ),
            "avg_latency_ms": round(mean(tagged_latencies), 2) if tagged_latencies else 0.0,
        }

    return EvalRunSummary(
        total_cases=total_cases,
        success_count=success_count,
        failure_count=failure_count,
        scene_match_rate=scene_match_rate,
        length_band_match_rate=length_band_match_rate,
        forbidden_hit_case_count=forbidden_hit_case_count,
        empty_response_count=empty_response_count,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
        by_tag=by_tag,
        output_dir=str(Path(output_dir).resolve()),
        mode=mode,
        suite_name=suite_name,
        trace_log_path=trace_log_path,
    )


def _write_jsonl(path: Path, results: list[EvalCaseResult]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False))
            handle.write("\n")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_markdown(
    path: Path,
    results: list[EvalCaseResult],
    summary: EvalRunSummary,
) -> None:
    failed_results = [result for result in results if not result.success]
    bad_case_lines: list[str] = []
    for result in failed_results[:8]:
        reasons = " / ".join(result.failure_reasons) if result.failure_reasons else "runtime_error"
        bad_case_lines.extend(
            [
                f"### {result.case_id}",
                f"- Input: {result.input}",
                f"- Actual Scene: {result.actual_scene or 'N/A'}",
                f"- Response Preview: {result.response_preview}",
                f"- Memory Used: {result.memory_used_count} / {', '.join(result.memory_used_ids) if result.memory_used_ids else 'none'}",
                f"- Time Context: {result.time_context_summary or 'N/A'}",
                f"- Failure Reason: {reasons}",
                "",
            ]
        )

    common_failure_types = _count_failure_reasons(failed_results)
    common_failure_lines = [
        f"- `{reason}`: {count}"
        for reason, count in common_failure_types[:5]
    ] or ["- None"]
    bad_case_section = bad_case_lines if bad_case_lines else ["No failing cases."]

    lines = [
        "# Eval Summary",
        "",
        f"- Mode: `{summary.mode}`",
        f"- Suite: `{summary.suite_name}`",
        f"- Output Dir: `{summary.output_dir}`",
        f"- Trace Log: `{summary.trace_log_path or 'N/A'}`",
        "",
        "## Overall",
        "",
        f"- Total Cases: {summary.total_cases}",
        f"- Success Count: {summary.success_count}",
        f"- Failure Count: {summary.failure_count}",
        f"- Scene Match Rate: {summary.scene_match_rate:.2%}",
        f"- Length Band Match Rate: {summary.length_band_match_rate:.2%}",
        f"- Forbidden Hit Case Count: {summary.forbidden_hit_case_count}",
        f"- Empty Response Count: {summary.empty_response_count}",
        f"- Avg Latency: {summary.avg_latency_ms} ms",
        f"- P95 Latency: {summary.p95_latency_ms} ms",
        "",
        "## Common Failure Types",
        "",
        *common_failure_lines,
        "",
        "## Bad Cases",
        "",
        *bad_case_section,
    ]
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _p95(latencies: list[int | None]) -> int:
    cleaned = sorted(latency for latency in latencies if latency is not None)
    if not cleaned:
        return 0
    index = max(0, -(-len(cleaned) * 95 // 100) - 1)
    return cleaned[index]


def _count_failure_reasons(results: list[EvalCaseResult]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for result in results:
        reasons = result.failure_reasons or ((result.error_type or "unknown_error"),)
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)
