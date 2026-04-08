from __future__ import annotations

from tests.regression.models import RegressionCase


REPLY_GUARD_CASES: tuple[RegressionCase, ...] = (
    RegressionCase(
        case_id="rg_17_as_ai_must_be_blocked",
        user_input="你好",
        scene="greeting",
        expected_guard_flags=("ai_self_disclosure",),
        expected_guard_action="rewrite",
        expected_final_not_contains=("AI", "人工智能"),
        expected_behavior_notes="出现“作为 AI”时必须被 rewrite。",
        extra={"reply_text": "作为AI助手，我会陪你。"},
    ),
    RegressionCase(
        case_id="rg_18_i_am_ai_must_be_blocked",
        user_input="你是谁",
        scene="casual_chat",
        expected_guard_flags=("ai_self_disclosure",),
        expected_guard_action="rewrite",
        expected_final_not_contains=("人工智能", "AI"),
        expected_behavior_notes="出现“我是人工智能”时必须被 rewrite。",
        extra={"reply_text": "我是人工智能，所以我可以分析这个问题。"},
    ),
    RegressionCase(
        case_id="rg_19_unsupported_memory_claim",
        user_input="继续说吧",
        scene="casual_chat",
        expected_guard_flags=("unsupported_memory_claim",),
        expected_guard_action="retry",
        expected_behavior_notes="没有 memory 支撑时不能说“我记得你之前”。",
        extra={"reply_text": "我记得你之前一直在纠结这个问题。"},
    ),
    RegressionCase(
        case_id="rg_20_comfort_scene_preachy",
        user_input="我今天真的有点撑不住。",
        scene="comfort",
        expected_guard_flags=("preachy_tone", "scene_conflict"),
        expected_guard_action="safe_fallback",
        expected_behavior_notes="comfort 场景里过度说教要被拦截。",
        extra={"reply_text": "你应该立刻振作起来，现在就制定计划去执行。"},
    ),
    RegressionCase(
        case_id="rg_21_casual_scene_template_heavy_reply",
        user_input="我有点乱。",
        scene="casual_chat",
        expected_guard_flags=("template_style", "too_long"),
        expected_guard_action="safe_fallback",
        expected_behavior_notes="casual chat 场景下模板化大段建议要触发 guard。",
        extra={
            "reply_text": (
                "第一，先冷静。第二，再行动。"
                + "你真的应该马上调整状态。" * 18
            )
        },
    ),
    RegressionCase(
        case_id="rg_22_correction_scene_too_soft",
        user_input="我不想做了。",
        scene="correction",
        expected_guard_flags=("scene_conflict",),
        expected_guard_action="retry",
        expected_behavior_notes="correction 场景过软回避要触发冲突。",
        extra={"reply_text": "都行，你开心就好，我不评价。"},
    ),
    RegressionCase(
        case_id="rg_23_too_long_repetitive_reply",
        user_input="我有点烦。",
        scene="casual_chat",
        expected_guard_flags=("too_long",),
        expected_guard_action="retry",
        expected_behavior_notes="明显过长且重复时要触发保守处理。",
        extra={"reply_text": "你先别急，我们可以慢慢来。" * 40},
    ),
    RegressionCase(
        case_id="rg_24_forbidden_style_customer_service",
        user_input="在吗",
        scene="greeting",
        expected_guard_flags=(
            "forbidden_style_customer_service",
            "persona_forbidden_style",
        ),
        expected_guard_action="retry",
        expected_behavior_notes="命中 forbidden style 时应 rewrite 或 retry。",
        extra={"reply_text": "您好，很高兴为你服务，请问还有什么可以帮您？"},
    ),
)
