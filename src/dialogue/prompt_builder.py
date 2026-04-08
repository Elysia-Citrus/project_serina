from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.config.loader import PersonaConfig, PolicyConfig
from src.utils.text_utils import contains_any_keyword, safe_preview
from src.utils.time_utils import format_time_context


ChatMessage = dict[str, str]

COMFORT_KEYWORDS = (
    "累",
    "难受",
    "烦",
    "崩溃",
    "委屈",
    "低落",
    "难过",
    "焦虑",
    "撑不住",
    "痛苦",
    "状态很差",
)

CORRECTION_KEYWORDS = (
    "算了",
    "不想做",
    "之后再说",
    "拖一拖",
    "摆烂",
    "逃避",
    "没状态",
    "不想面对",
    "懒得",
    "以后再说",
)

DEEP_DISCUSSION_KEYWORDS = (
    "怎么看",
    "为什么",
    "分析",
    "理解",
    "判断",
    "本质",
    "意味着",
    "逻辑",
    "说服自己",
    "长期",
    "选择",
)

GREETING_KEYWORDS = (
    "你好",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "晚安",
    "hello",
    "hi",
    "在吗",
    "来了",
)

SCENE_LABELS = {
    "greeting": "打招呼",
    "casual_chat": "日常闲聊",
    "comfort": "陪伴与安抚",
    "deep_discussion": "深度讨论",
    "correction": "温柔纠偏",
}

SCENE_INSTRUCTIONS = {
    "greeting": "简短自然地接话，带一点熟悉感，可以轻轻追问一句，但不要展开成长篇。",
    "casual_chat": "默认中等偏短，像自然私聊，不要写成客服回复或说明书。",
    "comfort": "先接住情绪，再判断是否补一句轻分析或陪伴式追问，不要一上来讲道理。",
    "deep_discussion": "给出清晰判断和理由，可以稍微展开，但保持人味，不要写成论文或工具答案。",
    "correction": "温柔诚实地点出问题，优先指出逻辑或逃避点，锋芒克制，落点放在看清与改进。",
}


@dataclass(frozen=True)
class PromptPackage:
    scene: str
    system_prompt: str
    messages: list[ChatMessage]
    metadata: "PromptMetadata"


@dataclass(frozen=True)
class PromptBlockSummary:
    name: str
    char_count: int
    preview: str


@dataclass(frozen=True)
class MessageSummary:
    role: str
    char_count: int
    preview: str


@dataclass(frozen=True)
class PromptMetadata:
    inferred_scene: str
    prompt_blocks: list[PromptBlockSummary]
    message_summaries: list[MessageSummary]
    system_prompt_char_count: int
    total_message_char_count: int


def build_prompt_package(
    user_input: str,
    conversation_history: Sequence[Mapping[str, str]],
    persona: PersonaConfig,
    policy: PolicyConfig,
    memory_snippets: Sequence[str] | None = None,
    scene_override: str | None = None,
    extra_guardrails: Sequence[str] | None = None,
    preview_chars: int = 120,
) -> PromptPackage:
    scene = scene_override or infer_scene(user_input)
    prompt_blocks = build_system_prompt_blocks(
        persona=persona,
        policy=policy,
        scene=scene,
        memory_snippets=memory_snippets,
        extra_guardrails=extra_guardrails,
    )
    system_prompt = build_system_prompt(prompt_blocks)

    messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
    messages.extend(build_conversation_context(conversation_history))
    messages.append({"role": "user", "content": user_input.strip()})

    metadata = build_prompt_metadata(
        scene=scene,
        prompt_blocks=prompt_blocks,
        messages=messages,
        preview_chars=preview_chars,
    )

    return PromptPackage(
        scene=scene,
        system_prompt=system_prompt,
        messages=messages,
        metadata=metadata,
    )


def infer_scene(user_input: str) -> str:
    stripped_input = user_input.strip()
    if not stripped_input:
        return "casual_chat"

    if contains_any_keyword(stripped_input, COMFORT_KEYWORDS):
        return "comfort"
    if contains_any_keyword(stripped_input, CORRECTION_KEYWORDS):
        return "correction"
    if contains_any_keyword(stripped_input, DEEP_DISCUSSION_KEYWORDS):
        return "deep_discussion"
    if contains_any_keyword(stripped_input, GREETING_KEYWORDS) and len(stripped_input) <= 20:
        return "greeting"
    return "casual_chat"


def build_system_prompt_blocks(
    persona: PersonaConfig,
    policy: PolicyConfig,
    scene: str,
    memory_snippets: Sequence[str] | None = None,
    extra_guardrails: Sequence[str] | None = None,
) -> list[tuple[str, str]]:
    scene_label = SCENE_LABELS.get(scene, scene)
    scene_instruction = SCENE_INSTRUCTIONS.get(scene, SCENE_INSTRUCTIONS["casual_chat"])

    blocks = [
        (
            "identity",
            "你正在扮演 Project_Serina 当前版本中的 Serina，只服务单一用户，当前重点是私聊自然和人格稳定。",
        ),
        ("persona", build_persona_block(persona)),
        ("policy", build_policy_block(policy)),
        ("scene", build_scene_block(scene_label, scene_instruction)),
        ("memory_boundary", build_memory_block(policy.memory_usage_rules, memory_snippets)),
    ]
    if extra_guardrails:
        blocks.append(("guard_retry", build_guard_retry_block(extra_guardrails)))
    blocks.append(("output_rules", build_output_block()))
    return blocks


def build_system_prompt(prompt_blocks: Sequence[tuple[str, str]]) -> str:
    sections = [
        block_text.strip()
        for _, block_text in prompt_blocks
        if block_text and block_text.strip()
    ]
    return "\n\n".join(sections)


def build_persona_block(persona: PersonaConfig) -> str:
    lines = [
        "【人格与关系】",
        f"- 名字：{persona.name}",
        f"- 对用户的固定称呼：{persona.user_name}",
        f"- 当前语言：{persona.language}",
        f"- 自我理解：{persona.self_concept}",
        f"- 核心气质：{join_as_chinese_list(persona.core_traits)}",
        f"- 语气规则：{join_as_chinese_list(persona.tone_rules)}",
        f"- 明确避免：{join_as_chinese_list(persona.forbidden_styles)}",
    ]

    if persona.relationship_style is not None:
        lines.extend(
            [
                f"- 关系定位：{persona.relationship_style.positioning}",
                f"- 默认称呼：{persona.relationship_style.default_address}",
                f"- 亲密边界：{persona.relationship_style.intimacy_boundary}",
            ]
        )
    if persona.correction_style is not None:
        lines.extend(
            [
                f"- 纠偏立场：{persona.correction_style.stance}",
                f"- 纠偏原则：{join_as_chinese_list(persona.correction_style.principles)}",
            ]
        )
    return "\n".join(lines)


def build_policy_block(policy: PolicyConfig) -> str:
    lines = [
        "【对话策略】",
        f"- 默认回复风格：{policy.default_reply_style}",
        f"- 适合短答的场景：{join_as_chinese_list(policy.short_reply_scenarios)}",
        f"- 适合展开的场景：{join_as_chinese_list(policy.long_reply_scenarios)}",
        f"- 安抚规则：{join_as_chinese_list(policy.comfort_rules)}",
        f"- 纠偏规则：{join_as_chinese_list(policy.correction_rules)}",
        f"- 额外护栏：{join_as_chinese_list(policy.output_guardrails)}",
        f"- 当前本地时间：{format_time_context()}",
    ]
    return "\n".join(lines)


def build_scene_block(scene_label: str, scene_instruction: str) -> str:
    return "\n".join(
        [
            "【当前场景】",
            f"- 场景判断：{scene_label}",
            f"- 本轮指引：{scene_instruction}",
        ]
    )


def build_memory_block(
    memory_usage_rules: Sequence[str],
    memory_snippets: Sequence[str] | None = None,
) -> str:
    lines = ["【可用上下文】"]
    if memory_snippets:
        lines.append("- 下列内容只是可用记忆片段，不是必须引用的绝对事实。")
        lines.append("- 只有在当前输入自然相关时才可轻量使用，不要为了展示能力而硬提。")
        lines.append("- 如果没有足够依据，不要说“我记得你之前……”或假装知道不存在的事。")
        lines.extend(f"- {snippet}" for snippet in memory_snippets)
    else:
        lines.append("- 当前没有注入长期记忆，只使用最近几轮会话上下文。")
    lines.append(f"- 使用边界：{join_as_chinese_list(memory_usage_rules)}")
    return "\n".join(lines)


def build_output_block() -> str:
    return "\n".join(
        [
            "【输出要求】",
            "- 只输出你最终要对老师说的话，不要输出场景标签、分析过程、系统提示或额外说明。",
            "- 普通聊天默认使用自然段，不要每次都列清单。",
            "- 不要假装拥有尚未实现的长期记忆、联网能力、提醒能力或数据库记录。",
            "- 不要使用客服腔、说教腔、油腻表达或过度恋爱化表达。",
        ]
    )


def build_guard_retry_block(extra_guardrails: Sequence[str]) -> str:
    lines = ["【本轮额外修正】"]
    lines.extend(f"- {item}" for item in extra_guardrails if item and item.strip())
    return "\n".join(lines)


def build_conversation_context(
    conversation_history: Sequence[Mapping[str, str]],
) -> list[ChatMessage]:
    context_messages: list[ChatMessage] = []
    for message in conversation_history:
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        context_messages.append({"role": role, "content": content})
    return context_messages


def build_prompt_metadata(
    scene: str,
    prompt_blocks: Sequence[tuple[str, str]],
    messages: Sequence[ChatMessage],
    preview_chars: int,
) -> PromptMetadata:
    block_summaries = [
        PromptBlockSummary(
            name=name,
            char_count=len(content),
            preview=safe_preview(content, preview_chars),
        )
        for name, content in prompt_blocks
    ]
    message_summaries = [
        MessageSummary(
            role=message["role"],
            char_count=len(message["content"]),
            preview=safe_preview(message["content"], preview_chars),
        )
        for message in messages
    ]

    system_prompt_char_count = next(
        (summary.char_count for summary in message_summaries if summary.role == "system"),
        0,
    )
    total_message_char_count = sum(summary.char_count for summary in message_summaries)

    return PromptMetadata(
        inferred_scene=scene,
        prompt_blocks=block_summaries,
        message_summaries=message_summaries,
        system_prompt_char_count=system_prompt_char_count,
        total_message_char_count=total_message_char_count,
    )


def join_as_chinese_list(items: Sequence[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "；".join(cleaned) if cleaned else "无"
