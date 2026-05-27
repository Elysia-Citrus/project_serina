# 会话合并最小闭环

## 目的

本文档定义了在 memory v0.2 之后新增的、以 session 为起点的最小合并闭环。

目标不是构建完整的 sleep pipeline 或反思式自主记忆系统。
目标是让 `session_memory_entries` 不再是一个死胡同缓冲区，而成为一条通向长期记忆的小型、保守的桥梁。

闭环故意保持狭窄：

1. session 条目在每轮对话后创建
2. session 条目支持检索中的短期连续性
3. 一个有界的、确定性的合并步骤可以将 session 条目提升为长期候选
4. 只允许三种长期候选类型
5. session 条目最终会被清理，而非无限累积

这保持了当前 reply guard、运行时 assist-llm 上限和确定性记忆通道的完整性。

## 为什么先从 session 开始

memory v0.2 之后的下一个安全步骤不是完整的 sleep 编排层。

原因：

- session memory 已经作为独立层存在，所以它是缺失环节中最小的补丁。
- session 条目比长期真相更接近近期交互上下文，出错代价更小。
- 确定性的提升循环比完整的后台记忆管线更容易测试和回滚。
- 这避免了引入自由形式的自我反思、递归 agent 循环或额外的运行时模型调用。

## 范围与非目标

本闭环做以下事情：

- 管理 session 条目的生命周期
- 生成轻量摘要
- 产出 `episodic`、`task` 或 `preference` 类型的长期候选
- 复用已有的长期 writer/store 路径
- 过期并归档 session 条目

本闭环不做以下事情：

- 语义自动晋升
- 自由形式反思
- 无限制自我对话
- 外部知识到用户记忆的晋升
- assist-llm 运行时依赖
- 重量级后台编排

## Session 条目生命周期

`session_memory_entries` 现在有一个 session 专属的生命周期面：

- `created_at` —— 创建时间
- `updated_at` —— 更新时间
- `last_touched_at` —— 最近被使用时间
- `expires_at` —— 过期时间
- `consolidation_state` —— 合并处理状态
- `last_consolidated_at` —— 最近一次合并时间
- `archived_at` —— 归档时间
- `origin_kind` —— 来源类型
- `promotion_fingerprint` —— 提升指纹
- `produced_memory_refs_json` —— 产出的长期记忆引用

`status` 仍然表示存储生命周期：

- `active` —— 活跃
- `expired` —— 已过期
- `archived` —— 已归档

`consolidation_state` 表示 session 处理进度：

- `pending`：新的或被重新打开的 session 条目，尚未处理提升
- `summarized`：摘要已存在，但本轮有意不提升；可被新证据或未来的显式重新运行重新打开
- `promoted`：长期候选已通过正常的 writer/store 路径写入
- `skipped`：本轮明确判定该条目不可提升；暂时保留用于连续性，但除非有新证据重新打开，否则不应重试
- `archived`：session 层终端状态

重要区分：

- `summarized` 意思是"尚未提升，以后仍可重新检查"
- `skipped` 意思是"不要从这个确切的证据集中提升"

这与长期 `review_state` 是分开的。Session 生命周期关乎处理进度，而不是真相审查。

## Session 条目的来源

目前有两种 session 来源：

1. `long_term_bridge`
   这些是新写入长期记忆的短期连续性副本。
   它们已有长期记忆作为支撑，所以初始状态即为 `promoted`。

2. `session_only`
   这些仅存在于短期连续性，可能后续被提升。
   创建是白名单制的。当前允许的来源：

   - 显式的未解决 follow-up / 提醒 / deadline / 回查信号
   - 当前会话的中间结论
   - 轻量话题摘要

   不允许：

   - 普通闲聊碎片
   - 模糊的语气印象
   - 仅基于 impression 的信号

## Summarizer 的职责

`src/memory/summarizer.py` 现在是一个确定性的 session 摘要/合并器。

其职责故意保持狭窄：

- 将 session 条目规范化为轻量摘要
- 判断是否可以产出长期候选
- 返回结构化的合并结果

它不做：

- 创建语义记忆
- 从自由文本推断人格
- 调用 assist-llm
- 运行多步骤推理链

当前实现是规则优先且确定性的。

## 候选规则

只允许三种长期候选类型。

### Episodic 候选

仅当 session 条目包含值得跨会话携带的近期事件时允许。

当前启发式形态：

- 显式的 `carryover_kind=episodic`，或强事件型 session 摘要
- 明确的时间/行动/结果信号
- 在 final-attempt 模式下阈值更高

普通闲聊不应成为 episodic memory。

### Task 候选

仅当条目明确指出一个开放循环时允许。

示例：

- follow-up
- 提醒
- deadline
- "下次回查"
- 显式的待完成承诺

Task 提升仍然通过正常的长期 schema 写入，使用 `memory_class=task`。

### Preference 候选

此闭环在偏好方面保持保守。

仅允许来自显式偏好形态的 session 条目。
当前运行时路径不会激进地从 session-only 行创建偏好；已有对显式偏好 session 条目和未来保守来源的支持，但偏好不应来自模糊的语气或一次性行为猜测。

偏好与事实保持区分：

- 事实示例："用户是会计专业"
- 偏好示例："用户偏好结构化回答"
- 工作流偏好示例："用户通常想先梳理再重构"

## 提升路径

提升不绕过已有的记忆写入路径。

流程：

1. session 条目进入合并器
2. summarizer 返回结构化结果
3. 如果存在候选，`MemoryWriter.persist_candidates()` 写入它
4. 长期 store 应用正常的 schema、去重、supersedes、review-state 和 namespace 规则
5. session 条目记录 `promotion_fingerprint` 和 `produced_memory_refs`

这保持了唯一的长期写入通道。

## 幂等性

此闭环增加了显式的幂等性保护。

每个可提升结果会得到一个 `promotion_fingerprint`，由以下内容派生：

- 来源 session 条目 id
- 候选类型
- 规范文本

如果 session 条目未获得新证据，相同的提升不会再次写入。

这防止一个 session 条目反复创建相同的长期 task/episodic/preference 记录。

## 检索顺序与预算

检索原则保持保守：

1. working memory
2. session memory
3. task memory
4. episodic memory
5. profile / preference
6. semantic
7. external knowledge

注入预算仍然很小。
Session 检索位于长期记忆之前，但 `last_touched_at` 会在使用时更新，以便 session 清理可以尊重实际的连续性。

此闭环不增加每轮运行时 assist-llm 调用次数。

## 衰减与归档

`src/memory/decay.py` 现在是一个最小的 session-only 衰减层。

它当前处理：

- 基于 TTL 的 session 条目过期
- `promoted` 后的短宽限期保留
- `skipped` 后更短的保留期
- 已过期/已处理 session 条目的归档
- 对接近 TTL 到期的 pending 条目做一次轻量的最终合并尝试

最终尝试仍然保持狭窄：

- 仅强 task
- 仅显式 preference
- 仅强 episodic

不引入重量级后台工作流。

## 触发点

此闭环使用两个保守的触发点：

1. turn-end 触发
   仅在回复已完成之后运行。
   每次最多处理一条 session 条目。
   失败是静默的，不阻塞主回复路径。

2. scheduler/dev 触发
   使用完全相同的确定性维护路径。

本轮迭代中没有常驻的自主 sleep worker。

## 人格与印象边界

长期真相仍然以以下内容为中心：

- `canonical_text`
- 结构化 payload
- evidence/source 字段

这里仍然没有 `persona_text` 真相层。

`impression` 仍然仅是软信号：

- 对检索排序和连续性有用
- 不是硬事实声明
- 不可通过 session 合并提升为长期硬事实

## 为什么这仍然不是反思型 agent

此闭环仍然故意保持非反思性。

原因：

- 无自我对话
- 无递归工具使用
- 无自由形式记忆解释循环
- 无语义自动蒸馏
- 无额外运行时 assist 依赖
- 无对 reply guard 或长期 writer 的直接绕过

系统通过设计保持保守。

## 已知限制

当前限制是有意为之：

- preference 提升已支持，但 session-only preference 创建仍然保守
- 语义提升保持禁用
- turn-end 路径中合并每次最多处理一条条目
- session 话题摘要故意保持浅层
- 尚无完整的多阶段 sleep 编排

## 推荐的下一步

下一个安全步骤不是"更多反思"。

下一个安全步骤是有界的离线合并通道，仅处理：

- `session → episodic 候选`
- `session → task 候选`
- 重复的显式偏好确认
- session 归档报告 / badcase 检查

这应该在考虑任何更广泛的语义或自主学习系统之前完成。
