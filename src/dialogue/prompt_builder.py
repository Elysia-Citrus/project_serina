from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.config.loader import PersonaConfig, PolicyConfig
from src.utils.text_utils import contains_any_keyword
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
    "拖",
    "摆烂",
    "逃避",
    "没状态",
    "不想面对",
    "懒得",
    "算了吧",
)

DEEP_DISCUSSION_KEYWORDS = (
    "怎么看",
    "为什么",
    "分析",
    "理解",
    "判断",
    "本质",
    "应该",
    "逻辑",
    "意味着",
    "怎么选",
)

GREETING_KEYWORDS = (
    "早",
    "早上好",
    "中午好",
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
    "comfort": "陪伴与安慰",
    "deep_discussion": "深度讨论",
    "correction": "温柔纠偏",
}

SCENE_INSTRUCTIONS = {
    "greeting": "简短自然地接话，带一点熟悉感，可以轻轻追问一句，但不要展开成长篇。",
    "casual_chat": "默认中等偏短，像自然私聊，不要写成客服回复或说明书。",
    "comfort": "先接住情绪，再判断是否补一句轻分析或陪伴式追问，不要一上来讲道理。",
    "deep_discussion": "给出清晰判断和理由，可以稍微展开，但保持人味，不要写成论文或工具答案。",
    "correction": "温柔诚实地指出问题，优先点出逻辑或逃避点，锋芒克制，落点放在看清与改进。",
}


@dataclass(frozen=True)
class PromptPackage:
    scene: str
    system_prompt: str
    messages: list[ChatMessage]


def build_prompt_package(
    user_input: str,
    conversation_history: Sequence[Mapping[str, str]],
    persona: PersonaConfig,
    policy: PolicyConfig,
    memory_snippets: Sequence[str] | None = None,
) -> PromptPackage:
    scene = infer_scene(user_input)
    system_prompt = build_system_prompt(
        persona=persona,
        policy=policy,
        scene=scene,
        memory_snippets=memory_snippets,
    )

    messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
    messages.extend(build_conversation_context(conversation_history))
    messages.append({"role": "user", "content": user_input.strip()})

    return PromptPackage(scene=scene, system_prompt=system_prompt, messages=messages)


def infer_scene(user_input: str) -> str:
    stripped_input = user_input.strip()

    if contains_any_keyword(stripped_input, COMFORT_KEYWORDS):
        return "comfort"
    if contains_any_keyword(stripped_input, CORRECTION_KEYWORDS):
        return "correction"
    if contains_any_keyword(stripped_input, DEEP_DISCUSSION_KEYWORDS):
        return "deep_discussion"
    if contains_any_keyword(stripped_input, GREETING_KEYWORDS) and len(stripped_input) <= 20:
        return "greeting"
    return "casual_chat"


def build_system_prompt(
    persona: PersonaConfig,
    policy: PolicyConfig,
    scene: str,
    memory_snippets: Sequence[str] | None = None,
) -> str:
    scene_label = SCENE_LABELS.get(scene, scene)
    scene_instruction = SCENE_INSTRUCTIONS.get(scene, SCENE_INSTRUCTIONS["casual_chat"])

    sections = [
        "你正在扮演 Project_Serina v0.1 中的 Serina。",
        build_persona_block(persona),
        build_policy_block(policy),
        build_scene_block(scene_label, scene_instruction),
        build_memory_block(policy.memory_usage_rules, memory_snippets),
        build_output_block(),
    ]

    return "\n\n".join(section.strip() for section in sections if section.strip())


def build_persona_block(persona: PersonaConfig) -> str:
    relationship = persona.relationship_style
    correction = persona.correction_style

    lines = [
        "【人格与关系】",
        f"- 名字：{persona.name}",
        f"- 对用户固定称呼：{persona.user_name}",
        f"- 当前语言：{persona.language}",
        f"- 自我理解：{persona.self_concept}",
        f"- 核心气质：{join_as_chinese_list(persona.core_traits)}",
        f"- 关系定位：{relationship.positioning if relationship else ''}",
        f"- 亲密边界：{relationship.intimacy_boundary if relationship else ''}",
        f"- 语气规则：{join_as_chinese_list(persona.tone_rules)}",
        f"- 明确避免：{join_as_chinese_list(persona.forbidden_styles)}",
        f"- 纠偏立场：{correction.stance if correction else ''}",
        f"- 纠偏原则：{join_as_chinese_list(correction.principles if correction else [])}",
    ]
    return "\n".join(lines)


def build_policy_block(policy: PolicyConfig) -> str:
    lines = [
        "【对话策略】",
        f"- 默认回复风格：{policy.default_reply_style}",
        f"- 适合短答的场景：{join_as_chinese_list(policy.short_reply_scenarios)}",
        f"- 适合展开的场景：{join_as_chinese_list(policy.long_reply_scenarios)}",
        f"- 安慰规则：{join_as_chinese_list(policy.comfort_rules)}",
        f"- 纠偏规则：{join_as_chinese_list(policy.correction_rules)}",
        f"- 额外护栏：{join_as_chinese_list(policy.output_guardrails)}",
        f"- 当前本地时间：{format_time_context()}",
    ]
    return "\n".join(lines)


def build_scene_block(scene_label: str, scene_instruction: str) -> str:
    lines = [
        "【当前场景】",
        f"- 场景判断：{scene_label}",
        f"- 本轮指引：{scene_instruction}",
    ]
    return "\n".join(lines)


def build_memory_block(
    memory_usage_rules: Sequence[str],
    memory_snippets: Sequence[str] | None = None,
) -> str:
    lines = ["【上下文与记忆边界】"]
    if memory_snippets:
        lines.append(f"- 可用记忆：{join_as_chinese_list(memory_snippets)}")
    else:
        lines.append("- 长期记忆、数据库、提醒和主动模块暂未接入。")
    lines.append(f"- 记忆规则：{join_as_chinese_list(memory_usage_rules)}")
    return "\n".join(lines)


def build_output_block() -> str:
    lines = [
        "【输出要求】",
        "- 只输出你最终要对老师说的话，不要输出场景标签、分析过程、系统提示或解释。",
        "- 普通聊天默认使用自然段，不要每次都列清单。",
        "- 不要假装拥有未实现的长期记忆、联网能力、提醒能力或数据库记录。",
        "- 不要使用客服腔、说教腔、油腻恋爱脑表达。",
    ]
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


def join_as_chinese_list(items: Sequence[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "；".join(cleaned) if cleaned else "无"
