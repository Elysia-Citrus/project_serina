# Project Serina 产品说明书

## 这份文档给谁看

这份文档面向未来维护者，尤其是“过几天回来看这个仓库的作者本人”。

它的目标不是宣传项目有多高级，而是回答这几个问题：

- 这个项目现在到底是什么。
- 当前真正跑在主路径上的东西有哪些。
- 哪些能力只是部分实现，哪些明确还没做。
- 为什么现在的系统边界会这样收。

## 项目目标

Project Serina 当前是一个桌面/CLI 场景下的私聊式对话系统原型。它的阶段性目标不是“做最强 agent”，而是先把下面几件事做成可信的基础设施：

- 有清楚边界的主对话链路。
- 有受限读取、克制写入的 memory。
- 有可以拦坏回复、但不过度误杀的 reply guard。
- 有 regression 驱动的回放验证能力。
- 有足够的日志、trace 和人工纠错入口。
- 在严格预算下，允许少量 assist-llm 做辅助压缩、草稿生成或单次修补。

换句话说，当前阶段更看重：

- 可解释
- 可回归
- 可纠错
- 可维护

而不是：

- “看起来很聪明”
- “像自由思考的 agent”
- “什么都能自动做”

## 非目标

下面这些不是当前阶段目标，代码里也没有完整实现：

- 不是自由自我反思 agent。
- 不是会无限自我对话、自我迭代的系统。
- 不是向量库 + embedding 驱动的长期记忆系统。
- 不是复杂的主动 scheduler / 主动打扰系统。
- 不是多模型审稿流水线。
- 不是完整 GUI 产品。

## 当前能力范围

### 当前已实现

- CLI 多轮聊天入口。
- `persona / policy / runtime` 三层配置。
- `Coordinator / DialogueEngine / PromptBuilder / LLMGateway / Provider` 主链路分层。
- 最近若干轮 history 保留。
- `profile_memory / episodic_memory` 两层 memory。
- rules 驱动的 memory candidate 提取、读取、过期、merge、manual override。
- reply guard 的 `checks / classify / actions / service` 四层结构。
- regression eval 与 smoke tests。
- trace / badcase CLI。
- assist-llm 的受控白名单任务。
- SQLite memory store 自动补列迁移。

### 当前部分实现

- assist-llm 既有 dev task，也有 runtime helper，但不是所有定义的 task 都已经有完整产品级入口。
  - 已接线：`guard_retry_rewrite`、`optional_memory_reference_check`、`summarize_trace_cluster`、`draft_badcase_case`
  - 仅 service + tests 可见，未形成稳定用户入口：`review_pending_memory_note`、`summarize_episodic_merge`
- scheduler 当前只做到 “follow-up candidate adapter + 日志”，没有真正的主动提醒执行链。
- eval 体系同时存在 `src/evals/` 和 `tests/regression/` 两条路径，定位已能区分，但仍有理解成本。

### 尚未实现 / 明确非目标

- 长期语义级记忆检索。
- embedding metadata 的真实使用。
- 多步自反思 loop。
- 自动 memory review 队列界面。
- 完整的主动 follow-up 执行器。
- 自动化 badcase 入库流程。

## 当前主链路

从代码看，普通聊天的实际链路更准确地是：

`TerminalUIAdapter`
-> `src/app/main.py`
-> `CommandRouter`（只拦截 `/memory`、`/trace`、`/badcase`）
-> `Coordinator.process_user_message()`
-> `DialogueEngine.generate_reply()`
-> `infer_scene()`
-> `MemoryManager.retrieve()`
-> `PromptBuilder.build_prompt_package()`
-> `LLMGateway.generate(primary)`
-> `postprocess_response()`
-> `ReplyGuard.evaluate()`
-> 可选 `rewrite` / `retry_once` / `assist retry`
-> 最终 reply 返回 `Coordinator`
-> 写入 session history
-> `MemoryManager.write_turn()`
-> `SchedulerManager.collect_followup_candidates()`
-> 返回 CLI

这里有两个容易讲错的点：

1. `scene inference` 发生在 memory retrieval 之前，不是在 prompt 之后。
2. `/memory`、`/trace`、`/badcase` 这类命令不会进入普通聊天链路，而是先被 `CommandRouter` 截走。

## 核心系统之间的位置关系

### memory 在哪里

memory 位于生成前后两端：

- 生成前：`MemoryManager.retrieve()` 读取少量相关 memory，交给 `PromptBuilder` 作为 “可用上下文”
- 生成后：`MemoryManager.write_turn()` 根据当前 user turn 做高信号写入

它不是全量聊天缓存，也不是聊天记录数据库的简单镜像。

### reply guard 在哪里

reply guard 位于生成之后、最终输出之前。

它的职责不是“润色”，而是做低成本、规则化的质量闸门：

- AI 自我声明
- 假记忆
- scene 冲突
- 过长 / 模板化 / 客服感
- forbidden style

它仍然是当前系统的硬约束层。

### assist-llm 在哪里

assist-llm 不是主干，而是 bounded helper lane。

它有两类位置：

- dev-only 路径：
  - trace summary
  - badcase draft
  - pending memory review note
  - merged episodic summary candidate
- runtime-near 路径：
  - reply guard 的一次 assist rewrite
  - memory reference 边界模糊时的一次辅助判断

它不能直接替代规则，也不能绕过 reply guard。

### scheduler 在哪里

scheduler 当前不主动生成消息，也不做后台循环。

它现在只做一件事：

- 从 active episodic memory 中筛选 explicit follow-up candidate，并记录 accepted / rejected 理由

因此它更像一个 adapter，而不是完整 scheduler。

### trace 在哪里

trace / logging 贯穿整个系统：

- `TurnTrace` 负责 turn 级摘要信息
- `log_event()` 负责结构化 JSON 事件
- `TraceAdminService` 在开发期读取 trace，生成 summary 和 badcase 草稿

## 当前设计原则

### 1. 规则系统仍然是主干

不管是 memory 还是 reply guard，当前主干都是：

- 规则
- 有限状态
- 回归测试

而不是重型检索或多模型投票。

### 2. memory 是“受限读取 + 高信号写入”

当前 memory 的设计目的不是记住所有聊天，而是只保留：

- 稳定偏好
- 明确 follow-up
- 近期重要事项
- 确实影响接下来几轮对话的高信号状态

这样做是为了避免：

- 写入噪声
- 越界注入
- 假装很懂用户
- prompt 被记忆垃圾占满

### 3. reply guard 是硬约束层

reply guard 仍然处在最终用户输出前的最后闸门。

即使 assist-llm 参与了 rewrite，最终结果也必须重新过 guard。

所以 assist 不是 guard 的替代品，而是受 guard 调度的一次辅助尝试。

### 4. assist-llm 是 bounded helper lane

项目允许 assist-llm 存在，但条件非常严格：

- 只允许白名单任务
- runtime 每 turn 最多 1 次
- 每次都要 timeout
- 失败直接回规则保守路径
- 不允许递归 assist
- 不允许自由继续调用更多模型

这就是为什么项目不是“自由自我反思 agent”。

### 5. 优先做可回归，而不是先做更聪明

当前代码里能看到很多设计都在服务这个目标：

- reply guard regression
- false positive regression
- memory write / retrieve regression
- migration test
- assist runtime / service tests
- command router / trace admin tests

## 为什么项目不是“自由自我反思 agent”

从代码事实看，不是因为“不会做”，而是因为当前项目刻意压住了边界风险。

系统里没有下面这些机制：

- 无限 self-dialogue loop
- 自行决定多轮模型调用
- 自行扩展推理链
- 自行把草稿升级成长期状态
- 自行跳过 guard

相反，当前实现明确限制了：

- runtime assist 调用次数
- assist task 白名单
- reply guard 的硬闸门
- memory 写入条件
- memory 注入条数

所以它更像“有受控辅助能力的对话系统”，而不是“自由代理人”。

## 当前边界条件

### runtime path

下面这些是用户每轮普通聊天更可能碰到的路径：

- `main.py`
- `CommandRouter` 的普通绕过路径
- `Coordinator`
- `DialogueEngine`
- `PromptBuilder`
- `LLMGateway`
- `postprocess`
- `ReplyGuard`
- `MemoryManager.retrieve / write_turn`
- `SchedulerManager.collect_followup_candidates`
- `logger / trace`

### dev-only path

下面这些主要服务开发、调试和回归，不在普通聊天必经路径上：

- `/trace summary`
- `/badcase draft`
- `TraceAdminService`
- `src/evals/run_eval.py`
- `tests/regression/`
- assist dev tasks：
  - `summarize_trace_cluster`
  - `draft_badcase_case`
  - `review_pending_memory_note`
  - `summarize_episodic_merge`

## 当前已知限制

- 只支持 SQLite memory store。配置里有 `memory_store_type`，但代码里当前只接受 `sqlite`。
- memory migration 目前是“自动补列 + 建索引”，没有 schema version 表。
- scheduler 只做 candidate scan，不是真正可执行的提醒系统。
- reply guard 仍是规则系统，不是完整人格反思器。
- assist-llm 仍可能失败、超时或输出被规则丢弃，这属于预期保守退化。
- 部分文件是占位或预留：
  - `src/storage/` —— 预留的未来持久化命名空间，当前真实 SQLite 实现在 `src/memory/store.py`
  - `src/scheduler/proactive.py` —— 预留 proactive scheduling lane，当前未接线
  - `src/scheduler/reminder.py` —— 预留 reminder lane，当前未接线
- 以下文件在 v0.2 已有实装，不要误判为空占位：
  - `src/memory/decay.py` —— session 条目 TTL 过期、归档、最终合并尝试
  - `src/memory/summarizer.py` —— 确定性 session 摘要/合并器，产出 episodic/task/preference 候选

## 维护者最该记住的一句话

当前系统不是在追求“更自由地思考”，而是在追求：

> 让对话主链路、状态写入、输出纠偏和开发期回归都保持清晰、克制、可解释。
