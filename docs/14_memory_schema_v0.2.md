# 14_memory_schema_v0.2.md

## 1. 这次 v0.2 修正要解决什么

这轮不是把 Serina 升级成自由反思型 agent，也不是把记忆系统做成更重的 autonomous loop。

这轮的目标更具体：

1. 把长期 memory 从单一 `memory_type` 语义，修正为“生命周期/用途”和“表达形式”两条轴。
2. 给 working memory 和 session memory 一个真实但克制的落点。
3. 把 `preference` 从 profile/procedure/impression 的隐式侧写中拆出来。
4. 让长期记忆支持更新、覆盖、冲突、确认，而不是“一次写入永久真理”。
5. 明确 user / agent / world 三类归属边界。
6. 维持当前 conservative runtime path，不放松 reply guard，也不放开 assist-llm 的写权限。

## 2. v0.1 的主要问题

v0.1 的 memory 已经能工作，但更像“能用的长期记忆基础设施草案”，还不够适合长期陪伴型 agent。

主要问题有：

1. `memory_type` 同时承担了“是什么记忆”和“怎么表达”两层语义。
2. working/session 主要隐含在 runtime history 里，没有被明确建模。
3. `preference` 不是一等公民，容易和事实混淆。
4. dedupe/upsert 语义偏“覆盖写”，不利于记录改口和更新。
5. user memory、agent self memory、external knowledge 没有明确命名空间边界。
6. impression 没被明确限制为 soft signal。
7. 文档设计比代码更理想化，尤其是 sleep / summarizer / decay。

## 3. 新 schema 设计

### 3.1 长期主表仍然是中央真相源

`memory_entries` 继续作为长期 memory 的唯一真相源。

新增或明确的关键字段包括：

- `memory_type`
  兼容字段。继续保留 v0.1 的 `profile / episodic` 语义，避免粗暴破坏旧路径。
- `memory_class`
  新轴，用来表达生命周期和用途。
- `representation`
  新轴，用来表达信息是以 raw / abstract / fact / preference / note 的哪种形式存在。
- `canonical_text`
  长期真相层的主文本。
- `structured_payload_json`
  结构化补充字段，面向后续 consolidation / promotion。
- `evidence_json`
  证据层保留位。
- `namespace`
  记忆属于哪个记忆域。
- `owner_kind`
  这个记忆的主体是谁。
- `review_state`
  事实/结论层的审核与演化状态。
- `last_confirmed_at`
  最近一次被确认或再次触发的时间。
- `supersedes_id`
  新记录覆盖旧记录时的关系。
- `contradicts_id`
  两条信息冲突但尚未收敛时的关系。
- `preference_*`
  偏好的目标、值、强度、上下文、极性。

### 3.2 `memory_type` 兼容保留，但不再承担主要语义

v0.2 不删除 `memory_type`，而是把它降为兼容层。

当前兼容规则：

1. `memory_type=profile`
   通常对应 `memory_class=profile`，再由 `representation` 区分 fact 与 preference。
2. `memory_type=episodic`
   继续承接短时/近期类记录，但明确 follow-up / commitment / deadline / recent task 信号时，可映射为 `memory_class=task`。

## 4. `memory_class` 与 `representation`

### 4.1 `memory_class`：它属于哪一类记忆

当前支持：

- `working`
- `session`
- `episodic`
- `semantic`
- `profile`
- `task`
- `impression`

`memory_class` 主要回答：

- 生命周期有多长
- 检索优先级怎样
- 它是给当前轮 continuity 用，还是给长期陪伴关系用

### 4.2 `representation`：它以什么形式存在

当前支持：

- `raw`
- `abstract`
- `fact`
- `preference`
- `note`

`representation` 主要回答：

- 这是原始观察，还是抽象归纳
- 这是硬事实，还是柔性偏好
- 这是面向外部知识索引的 note，还是关于用户/agent 的长期结论

### 4.3 为什么必须分开

同一条 profile 记忆，既可能是 fact，也可能是 preference。

例如：

- “用户是会计专业”  
  `memory_class=profile`，`representation=fact`
- “用户喜欢结构化回答”  
  `memory_class=profile`，`representation=preference`
- “用户通常先梳理后重构”  
  更接近 workflow preference，而不是 procedure 本体  
  `memory_class=profile`，`representation=preference`

同理，`task` 也不等于某种固定表达：

- 原始任务描述可以是 `raw`
- 合并后的近期任务摘要可以是 `abstract`

## 5. 旧字段迁移策略

### 5.1 迁移原则

1. 不删旧字段。
2. 先补新列，再做 backfill。
3. 旧数据默认能继续读、继续检索、继续通过 admin 路径查看。

### 5.2 当前映射规则

#### 旧 `profile`

- 若 dedupe/tag/文本命中偏好模式  
  映射为 `memory_class=profile` + `representation=preference`
- 否则  
  映射为 `memory_class=profile` + `representation=fact`

#### 旧 `episodic`

- 若存在明确 `followup / commitment / deadline / task` 信号  
  映射为 `memory_class=task`
- 其余继续保留为 `memory_class=episodic`
- 若已有 `summary` 或 `merge_count > 1`  
  优先映射为 `representation=abstract`
- 否则  
  优先映射为 `representation=raw`

### 5.3 `status` 与 `review_state`

这两个字段并存，但职责不同。

#### `status`

表示存储生命周期：

- `active`
- `expired`
- `archived`

#### `review_state`

表示事实/结论层状态：

- `active`
- `stale`
- `archived`
- `pending_review`
- `rejected`

简单说：

- `status` 解决“这条记录在存储层是不是还活着”
- `review_state` 解决“这条结论在语义层是不是还值得相信”

## 6. working / session / episodic 的关系

### 6.1 working memory

working memory 不进入 `memory_entries` 主表。

当前最小实现落点：

- `Coordinator.session.history`
- `Coordinator.session.working`

它服务于：

- 当前话题槽位
- 最近几轮未闭环事项
- 当前活跃任务提示
- 最近引用过的 memory id

working memory 是 runtime continuity，不是长期记忆本体。

### 6.2 session memory

session memory 单独落在 `session_memory_entries`。

它用于承接：

- 本次会话摘要
- 当前会话已确认的中间结论
- 本次会话待延续事项

session memory 的典型 TTL 是几天，不等同于 profile，也不等同于永久 factual memory。

### 6.3 episodic memory

episodic 是长期主表里“近期发生过的事”的保留层。

它和 session 的区别是：

- session 偏当前会话连续感
- episodic 偏跨会话但仍有时效性的近期记忆

### 6.4 和 pending / consolidation 的关系

当前仓库还没有完整落地独立 `pending_candidates / source_artifacts / note_index / sleep pipeline` 主路径。

v0.2 先把 schema、session、conflict 语义和 writer/reader 边界修正好：

- runtime 仍然优先规则写入
- repeated behavior -> preference candidate 的归纳，留给后续 consolidation
- semantic promotion 这轮保守，不做激进自动晋升

## 7. preference 如何建模

### 7.1 preference 是显式一等语义

偏好相关字段：

- `preference_target`
- `preference_value`
- `preference_strength`
- `preference_context`
- `preference_polarity`
- `last_confirmed_at`

### 7.2 本轮偏好策略

runtime 只处理显式偏好：

- 称呼偏好
- 互动方式偏好
- 明确喜欢/不喜欢的主题偏好

重复行为归纳型 preference，不放在 runtime 自反思里做，而是留给后续 consolidation。

### 7.3 retrieval 中 preference 与 fact 分开

在 prompt 注入时：

- fact 走 `[profile]` / `[semantic]`
- preference 走 `[preference]`

这样可以避免：

- 把偏好说成硬事实
- 把 workflow 倾向说成固定 procedure

## 8. 冲突、覆盖、确认机制

长期陪伴 agent 必须允许“改口”和“更新”。

原因很简单：

1. 用户偏好会变。
2. 用户状态会变。
3. 用户会纠正 agent 之前记错的东西。
4. 陪伴关系里，历史痕迹应该保留，但默认引用应该跟随最新版本。

### 8.1 supersedes

当同一 dedupe 语义下出现新的高置信 preference/fact 且文本已变化时：

- 新记录插入为新 row
- 新记录通过 `supersedes_id` 指向旧记录
- 旧记录不删除，改为 `review_state=stale`

### 8.2 contradicts

`contradicts_id` 用于表示冲突并存但尚未自动归并的情况。

本轮只把它落到 schema / update path，不做激进自动判冲突。

### 8.3 last_confirmed_at

新的显式写入会刷新 `last_confirmed_at`。

retrieval 默认更偏好：

- `review_state=active`
- 最近确认过
- 置信度更高

## 9. namespace / owner_kind

### 9.1 两个字段都保留

这两个字段职责不同：

- `namespace`
  这条记忆属于哪个记忆域
- `owner_kind`
  这条记忆的主体是谁

### 9.2 当前允许组合

本轮只允许以下明确组合：

1. `user_memory + user`
2. `agent_self_memory + agent`
3. `external_knowledge + world`

这样做是为了避免：

- 把网页/文档知识直接写成用户事实
- 把 agent 自己的经历、承诺、状态和用户事实混在一起

## 10. retrieval 顺序与注入预算

### 10.1 retrieval 原则

当前原则是：

1. working  
   通过 runtime conversation history / working state 先行满足，不额外挤占长期注入预算
2. session
3. task
4. episodic
5. profile / preference
6. semantic
7. external knowledge

### 10.2 注入预算

注入数量继续受 runtime config 限制：

- 默认仍是小预算
- 不为了“显得懂用户”而过量注入

### 10.3 仍坚持 rules / token overlap / conservative ranking

本轮没有把 vector / graph 提升为主入口。

当前仍然坚持：

- deterministic extraction first
- token overlap / tags / topic_key first
- session + task continuity first
- vector 未来若引入，也只能是 optional enhancer

## 11. persona_text 降权原则

当前仓库没有长期保存 `persona_text` 字段。

v0.2 明确继续保持：

- 长期真相层以 `canonical_text + structured payload + evidence` 为主
- persona 化表达更适合在注入阶段或回复阶段动态生成

避免“角色腔表达污染事实层”。

## 12. impression 只做软信号

impression 允许存在，但必须是 soft signal。

它更适合影响：

- retrieval 排序微调
- 语气
- 主动性预算
- 熟悉度/关系温度

它不应该轻易被当成高置信 factual claim 直接口头断言。

在 prompt 注入里，impression 使用 `[impression-soft]` 前缀，并显式标注 `soft signal only`。

## 13. sleep consolidation / decay / archive / promotion

本轮只做了最小接口准备，没有把系统升级成重型 sleep loop。

当前落点：

- schema 已支持 `review_state / supersedes / contradicts / last_confirmed_at`
- session 已有独立承接层
- future consolidation 可以把 repeated signals 晋升为 preference candidate
- semantic promotion 仍然保守，不做激进自动化

也就是说：

- 这轮修的是“语义正确性”和“可演进性”
- 不是把 summarizer / decay / maintenance 全部一次性做满

## 14. 为什么这仍然不是自由反思型 agent

因为以下边界仍然保留：

1. runtime 仍优先规则和确定性逻辑。
2. assist-llm 不允许直接写 active memory。
3. reply guard 没有被绕开。
4. runtime assist 调用上限没有提升。
5. session 的引入不等于自由自我对话。
6. semantic / preference consolidation 没有被放到在线回复链路里。

v0.2 的方向是：

让 memory 更像长期陪伴体需要的记忆系统，
但仍然保持“保守、可维护、可测试”的主链路。
