from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from src.app.coordinator import Coordinator, CoordinatorTurnResult
from src.config.loader import AppConfig, load_app_config
from src.dialogue.engine import DialogueEngine
from src.dialogue.prompt_builder import infer_scene
from src.evals.checker import run_response_checks
from src.evals.loader import DEFAULT_SUITE, load_eval_cases, resolve_case_path
from src.evals.models import EvalCase, EvalCaseResult
from src.evals.reporter import build_summary, create_output_dir, write_results_bundle
from src.llm.gateway import GatewayResponse
from src.utils.logger import configure_logging, get_trace_log_path
from src.utils.text_utils import safe_preview


MOCK_MODEL_NAME = "mock-serina-v1"


class MockLLMGateway:
    def __init__(self, model_name: str = MOCK_MODEL_NAME) -> None:
        self.model_name = model_name

    def generate(self, messages, turn_trace=None) -> GatewayResponse:
        user_input = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_input = str(message.get("content", ""))
                break

        scene = infer_scene(user_input)
        response = _generate_mock_response(scene, user_input)
        return GatewayResponse(
            text=response,
            provider_name="mock",
            model_name=self.model_name,
            latency_ms=0,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    case_path = resolve_case_path(cases_path=args.cases, suite_name=args.suite)
    cases = load_eval_cases(case_path, enabled_only=not args.include_disabled)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    if not cases:
        raise SystemExit("No eval cases were selected.")

    output_dir = create_output_dir(args.output_dir)
    app_config = _prepare_eval_config(
        output_dir=output_dir,
        debug=args.debug,
    )
    configure_logging(app_config.runtime)

    results = [run_single_case(case, app_config, mode=args.mode) for case in cases]
    summary = build_summary(
        results=results,
        output_dir=output_dir,
        mode=args.mode,
        suite_name=args.suite,
        trace_log_path=get_trace_log_path(),
    )
    write_results_bundle(output_dir=output_dir, results=results, summary=summary)

    print(f"Eval completed: {summary.success_count}/{summary.total_cases} passed")
    print(f"Artifacts: {output_dir}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> Namespace:
    parser = ArgumentParser(description="Run Project_Serina eval suites.")
    parser.add_argument("--cases", type=str, default=None, help="Path to a JSONL case file.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/evals",
        help="Base output directory for eval artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="mock",
        help="Run eval in deterministic mock mode or live provider mode.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Optionally limit the number of cases executed.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed trace logging into the eval artifact directory.",
    )
    parser.add_argument(
        "--suite",
        type=str,
        default=DEFAULT_SUITE,
        help="Named built-in suite to run when --cases is omitted.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled cases from the case file.",
    )
    return parser.parse_args(argv)


def run_single_case(case: EvalCase, app_config: AppConfig, *, mode: str) -> EvalCaseResult:
    coordinator = _build_coordinator(app_config, mode=mode)
    coordinator.session.history = [dict(message) for message in case.history_messages]

    try:
        turn_result = coordinator.process_user_message(case.input)
    except Exception as exc:
        return EvalCaseResult(
            case_id=case.id,
            input=case.input,
            turn_id=None,
            expected_scene=case.expected_scene,
            actual_scene=None,
            scene_match=False,
            response_text="",
            response_preview="",
            response_length=0,
            expected_length_band=case.expected_length_band,
            actual_length_band=None,
            length_band_match=False,
            forbidden_hits=(),
            preferred_hits=(),
            latency_ms=None,
            success=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
            provider_name=None,
            model_name=None,
            tags=case.tags,
            notes=case.notes,
            failure_reasons=("runtime_error",),
        )

    return _build_eval_case_result(case, turn_result)


def _prepare_eval_config(*, output_dir: Path, debug: bool) -> AppConfig:
    config = load_app_config()
    traces_dir = output_dir / "traces"
    runtime = replace(
        config.runtime,
        enable_file_logging=debug,
        log_dir=str(traces_dir),
        log_level="DEBUG" if debug else "INFO",
        debug_trace_enabled=False,
        debug_show_prompt_blocks=debug,
        debug_show_messages=debug,
        debug_cli_diagnostics_enabled=False,
    )
    return replace(config, runtime=runtime)


def _build_coordinator(app_config: AppConfig, *, mode: str) -> Coordinator:
    if mode == "live":
        return Coordinator(app_config)

    mock_runtime = replace(
        app_config.runtime,
        provider="mock",
        model=MOCK_MODEL_NAME,
    )
    mock_config = replace(app_config, runtime=mock_runtime)
    engine = DialogueEngine(mock_config, MockLLMGateway())
    return Coordinator(mock_config, engine=engine)


def _build_eval_case_result(
    case: EvalCase,
    turn_result: CoordinatorTurnResult,
) -> EvalCaseResult:
    check = run_response_checks(case, turn_result.reply_text)
    scene_match = turn_result.scene == case.expected_scene
    failure_reasons = list(check.failure_reasons)
    if not scene_match:
        failure_reasons.append("scene_mismatch")
    if turn_result.used_fallback:
        failure_reasons.append("used_fallback")

    success = not failure_reasons
    return EvalCaseResult(
        case_id=case.id,
        input=case.input,
        turn_id=turn_result.turn_id,
        expected_scene=case.expected_scene,
        actual_scene=turn_result.scene,
        scene_match=scene_match,
        response_text=turn_result.reply_text,
        response_preview=safe_preview(turn_result.reply_text, 160),
        response_length=check.response_length,
        expected_length_band=case.expected_length_band,
        actual_length_band=check.actual_length_band,
        length_band_match=check.length_band_match,
        forbidden_hits=check.forbidden_hits,
        preferred_hits=check.preferred_hits,
        latency_ms=turn_result.latency_ms,
        success=success,
        error_type=None,
        error_message=None,
        provider_name=turn_result.provider_name,
        model_name=turn_result.model_name,
        tags=case.tags,
        notes=case.notes,
        manual_review_needed=check.manual_review_needed,
        failure_reasons=tuple(failure_reasons),
        postprocess_applied_rules=turn_result.postprocess_applied_rules,
        used_fallback=turn_result.used_fallback,
        prompt_block_count=turn_result.prompt_block_count,
        prompt_message_count=turn_result.prompt_message_count,
        memory_write_candidate_present=turn_result.memory_write_candidate_present,
        proactive_followup_candidate_present=turn_result.proactive_followup_candidate_present,
    )


def _generate_mock_response(scene: str, user_input: str) -> str:
    if scene == "greeting":
        return "老师，我在。今天怎么样？"

    if scene == "comfort":
        return (
            "老师，先别把自己绷得太紧。今天已经很不容易了，我在这儿。"
            "如果你愿意，可以慢一点和我说说，最压着你的那一块是什么？"
        )

    if scene == "correction":
        return (
            "如果只是换个说法把问题往后拖，老师其实还是没有真的面对它。"
            "我不是要逼你，只是想提醒你，这种绕开会让你更累。"
        )

    if scene == "deep_discussion":
        if "状态" in user_input and len(user_input) <= 14:
            return "老师，我会觉得你今天是在硬撑。表面上还能往前走，但心里那根线已经绷得有点紧了。"
        return (
            "老师，如果认真拆开看，这件事真正的分歧不在表面的二选一，"
            "而在你更想守住什么、愿意承受什么代价。稳定给你的是可持续和回旋余地，"
            "速度给你的是窗口期和推进感，可一旦速度超过你能消化的范围，后面就会用返工和内耗把账补回来。"
            "所以更稳的做法不是盲目选一边，而是先定住不能丢的底线，再把能冲的部分冲起来。"
        )

    if "午饭" in user_input or "吃完" in user_input:
        return "老师，那还不错。现在状态松一点了吗？"
    if "日志" in user_input or "项目" in user_input:
        return "老师，这样已经是在往前推了。步子不大也没关系，能持续比一口气冲猛了更重要。"
    if "直接说" in user_input or "怎么想" in user_input:
        return "老师，我会直接一点说，但还是想把分寸留住。对我来说，真诚不是把话砸过来，而是把判断说清楚，也把你放在里面。"
    if "刚认识" in user_input:
        return "老师，那我会先自然一点陪你聊，不装熟，也不端着。你想先从今天开始，还是从你最近最在意的事开始？"
    return "老师，我在，继续说吧。"


if __name__ == "__main__":
    raise SystemExit(main())
