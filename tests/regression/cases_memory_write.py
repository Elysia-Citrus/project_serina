from __future__ import annotations

from tests.regression.models import RegressionCase


MEMORY_WRITE_CASES: tuple[RegressionCase, ...] = (
    RegressionCase(
        case_id="mw_01_address_preference",
        user_input="以后叫我阿周吧。",
        expected_write_candidates=("address_preference",),
        expected_written_memory_types=("profile",),
        expected_behavior_notes="显式称呼偏好应进入 profile memory。",
    ),
    RegressionCase(
        case_id="mw_02_avoid_preachy_interaction",
        user_input="别总是上课式地说教我，我更喜欢你直接一点。",
        expected_write_candidates=("interaction_preference",),
        expected_written_memory_types=("profile",),
        expected_behavior_notes="明确讨厌某种互动方式应进入 profile memory。",
    ),
    RegressionCase(
        case_id="mw_03_long_term_topic_preference",
        user_input="我一直很喜欢聊产品设计。",
        expected_write_candidates=("stable_preference",),
        expected_written_memory_types=("profile",),
        expected_behavior_notes="长期稳定喜欢的话题应进入 profile memory。",
    ),
    RegressionCase(
        case_id="mw_04_small_talk_no_write",
        user_input="早，今天吃了吗？",
        expected_write_candidates=(),
        expected_written_memory_types=(),
        expected_behavior_notes="普通寒暄不应写入 memory。",
    ),
    RegressionCase(
        case_id="mw_05_low_signal_complaint_no_write",
        user_input="今天有点烦。",
        expected_write_candidates=(),
        expected_written_memory_types=(),
        expected_behavior_notes="低信息量抱怨一句不应进入 episodic。",
    ),
    RegressionCase(
        case_id="mw_06_recent_project_task",
        user_input="我这周在做桌面 agent 的 memory guard 模块改造。",
        expected_write_candidates=("recent_task",),
        expected_written_memory_types=("episodic",),
        expected_behavior_notes="近期项目推进应进入 episodic memory。",
    ),
    RegressionCase(
        case_id="mw_07_explicit_followup_commitment",
        user_input="过两天再问我这个项目的进展。",
        expected_write_candidates=("explicit_follow_up",),
        expected_written_memory_types=("episodic",),
        expected_behavior_notes="显式 follow-up 约定应进入 episodic memory。",
    ),
    RegressionCase(
        case_id="mw_08_persistent_emotion_state",
        user_input="我这几天状态很差，真的有点焦虑。",
        expected_write_candidates=("recent_emotion",),
        expected_written_memory_types=("episodic",),
        expected_behavior_notes="影响后续对话的持续情绪状态可进入 episodic。",
    ),
)
