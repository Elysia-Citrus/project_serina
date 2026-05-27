# Assist-LLM 受控辅助通道

## 为什么要引入 assist-llm

Project Serina 仍然以规则、状态机和回归测试作为主控制面。

assist-llm 通道的存在，仅仅是因为少数狭窄任务受益于一次简短的模型调用：
- 压缩嘈杂的开发者 trace 数据
- 从 trace 数据中草拟 badcase 回归用例
- 为待审核的记忆候选添加简短评审注释
- 压缩已合并的事件记忆组
- 当 reply guard 判定初稿不合格时，尝试一次受控重写
- 当某条记忆引用看起来处于边界状态时，给出一次可选的低成本判断

目标不是"自我反思"或"自我对话"。
目标是"在明确边界内，提供小规模、可追踪的辅助"。

## 开发任务 vs 运行时任务

开发期任务：
- `summarize_trace_cluster` —— 压缩 trace 事件簇
- `draft_badcase_case` —— 从 trace 数据草拟 badcase 用例
- `review_pending_memory_note` —— 为待审核记忆候选添加注释
- `summarize_episodic_merge` —— 压缩已合并的事件记忆组

运行时近邻任务：
- `guard_retry_rewrite` —— reply guard 拒绝初稿后的受控重写
- `optional_memory_reference_check` —— 记忆引用边界模糊时的辅助判断

这个区分很重要：开发任务永远不接触面向用户的回复路径，而运行时任务必须遵守更严格的预算和回退规则。

## 为什么运行时 assist 上限为一次调用

运行时 assist-llm 故意保持轻量：
- 每轮用户对话最多 `1` 次运行时 assist 调用
- 每次调用都有超时限制
- 任何超时、解析错误或空结果都回退到保守路径
- 修改后的回复必须再次通过 reply guard
- 如果第二次 guard 仍然失败，系统直接进入 `safe_fallback`

这保持了通道的可解释性，防止在正常对话中出现隐藏的多步骤循环。

## 为什么 assist-llm 不能替代规则

Assist 的输出是**建议性**的。
它不能：
- 绕过 reply guard
- 直接激活记忆写入
- 递归调用更多 assist 任务
- 自行决定持续生成直到"看起来不错"

硬规则在以下场景中仍然胜出：
- AI 自我声明
- 无依据的强记忆声称
- 严重的禁止风格漂移

如果 assist 不可用，系统仍应以保守、可预测的方式运行。

## 当前安全模型

每次 assist 调用记录以下字段：
- `assist_llm_task` —— 任务名称
- `assist_llm_model` —— 使用的模型
- `assist_llm_timeout_ms` —— 超时设置
- `assist_llm_runtime_call_used` —— 本轮是否已用掉 runtime 配额
- `assist_llm_input_excerpt` —— 输入摘要
- `assist_llm_output_excerpt` —— 输出摘要
- `assist_llm_duration_ms` —— 耗时
- `assist_llm_success` —— 是否成功
- `assist_llm_fallback_to_rules` —— 是否回退到规则
- `assist_llm_error_type` —— 错误类型
- `assist_llm_trace_linked_turn_id` —— 关联的 turn id
- `assist_llm_pre_guard_action` —— assist 前 guard 的 action
- `assist_llm_post_guard_action` —— assist 后 guard 的 action

这很重要，因为仅仅"最终回复成功"是不够的。我们还需要知道 assist 是否被使用、被要求做什么、以及为什么最终 action 是 `accept`、`rewrite`、`retry_once` 或 `safe_fallback`。

## 轻量 CLI 入口

面向开发者的命令故意保持简洁：
- `/trace summary --file data/logs/serina_trace_xxx.jsonl --limit 12`
- `/badcase draft latest --file data/logs/serina_trace_xxx.jsonl`
- `/badcase draft <turn_id> --file data/logs/serina_trace_xxx.jsonl`

如果 file logging 关闭，这些命令在提供 `--file` 时仍然可以工作。
不写 `--file` 时，系统先尝试当前 logger 记录的 trace 文件，再尝试 `runtime.log_dir` 下最新的 trace 文件。

## 已知限制

这仍然不是：
- 自由形式的自我反思 agent
- 多步骤自我迭代循环
- regression 驱动的 guard 加固的替代品

已知限制：
- assist prompt 故意设计为短且可能有损
- 可选的记忆引用判断仍然只是辅助信号
- 不安全的合并摘要会被规则过滤，可能频繁回退
- 面向开发者的草稿在成为真正的 regression case 之前仍需人工审查

目前这些取舍是有意为之。
更大的风险不是"系统不够聪明"。
更大的风险是"系统变得更难解释、更难调试、更容易越界"。
