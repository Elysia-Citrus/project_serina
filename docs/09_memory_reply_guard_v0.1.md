# 09_memory_reply_guard_v0.1.md

## 1. 这次改造的目标

这次不是要把 Project_Serina 一步做成“完整长期记忆系统”或“人格反思中台”。

这次的目标更克制：

- 给主链路接入第一版可信的 memory 基础设施
- 给最终回复补一层低成本、可观察、可回归的质量自检
- 不破坏 v0.1 已有的清晰分层

一句话说：

> 先把 memory 和 self-check 做成“可信、克制、不出戏”的基础设施，再考虑更强能力。

---

## 2. 为什么这次不引入向量库

当前阶段不引入向量库，原因很明确：

- 这次的核心风险不在“召回不够强”，而在“写入过多、读取越界、假装记得”
- v0.1 的首要任务是把写入规则、读取边界、TTL、日志、测试先做扎实
- 记忆量还很小，规则 + 轻量词面相关性已经足够覆盖第一版连续陪伴体验
- 过早接入 embedding / vector retrieval 会让问题从“边界清晰”变成“行为不可解释”

所以这次优先的是：

- high-signal 才写
- 最多注入 2~4 条
- 过期默认不读
- 每次命中、拒绝、重试都能被日志和测试看见

而不是追求“看起来更高级”的检索栈。

---

## 3. 为什么把 memory 先拆成 profile / episodic

memory v0.1 只分两层：

- `profile_memory`
- `episodic_memory`

这样拆是为了先解决两类最常见、最容易混淆的问题。

### 3.1 profile_memory

存稳定信息，例如：

- 称呼偏好
- 互动方式偏好
- 明确喜欢 / 不喜欢
- 长期关系设定

这类信息的特点是：

- 更新频率低
- 生命周期长
- 需要高置信度
- 更适合“覆盖更新”而不是反复堆积

### 3.2 episodic_memory

存 3~14 天内的重要近期事项，例如：

- 最近在做的项目
- 明确约定的 follow-up
- 近期会影响几轮对话的状态变化

这类信息的特点是：

- 有时效
- 读写频率更高
- 必须有 TTL
- 过期后默认不注入

先拆这两层，有两个直接好处：

- 写入规则更容易解释
- 读取边界更容易控制

---

## 4. 为什么必须 high-signal 才写入

如果每轮都写，memory 很快就会退化成聊天流水账。

这次写入只接受高信号内容，主要是为了避免三种坏结果：

- 记忆膨胀
- 对话被无关旧信息污染
- 用户产生“被监控”的感觉

所以 v0.1 的写入规则非常保守：

- 显式稳定偏好，才候选 `profile_memory`
- 明确长期喜欢 / 讨厌，才候选 `profile_memory`
- 明确近期计划、任务推进、follow-up 约定，才候选 `episodic_memory`
- 只有明显且会影响后续对话的近期情绪状态，才候选 `episodic_memory`
- 普通寒暄、低信息量闲聊、一次性碎片默认不写

这不是能力弱，而是刻意控制写入噪声。

---

## 5. 为什么读取最多只注入 2~4 条

memory 的目标不是证明“系统记得很多”，而是让回复更自然。

如果一次注入太多，会出现几个问题：

- prompt 变脏，主模型更容易跑偏
- 模型为了显得聪明，容易硬提无关旧信息
- 当前轮次真正重要的记忆反而被稀释

所以这次 retrieval 的原则是：

- 只选少量、最相关、仍有效的记忆
- `profile_memory` 只注入高置信度条目
- `episodic_memory` 只注入未过期条目
- 无关时宁可不注入，也不强行展示记忆能力

这也是为什么 prompt 里把 memory 明确标成“可用上下文”，而不是“绝对事实”。

---

## 6. 为什么 reply self-check 先用轻量规则

这次 reply guard 不调用第二个 LLM，也不做复杂 NLP。

原因是当前更重要的是先解决那些高频、低成本、破坏感又很强的问题：

- AI 自我声明
- 过度说教
- 没有依据的“我记得你之前……”
- persona 明示禁止的风格滑坡
- scene 冲突
- 过长、模板化、客服化

这些问题大多可以先用规则拦下来。

轻量规则的优势是：

- 成本低
- 可解释
- 好调试
- 好写回归测试

当前的处理策略也保持克制：

- 轻度问题：规则化 rewrite / 裁剪
- 中度问题：用更保守的 prompt 和 generation 配置重试一次
- 重度问题：直接落到简短自然的 safe fallback

最多只重试一次，不做无限循环。

---

## 7. 当前主链路

这次接入后的主链路是：

```text
UI
  -> Coordinator
  -> DialogueEngine
      -> infer_scene
      -> MemoryManager.retrieve
      -> PromptBuilder
      -> LLMGateway / Provider
      -> Postprocess
      -> ReplyGuard
          -> accept / rewrite / retry once / safe fallback
  -> 返回最终回复
  -> MemoryManager.write_turn
```

这里的关键边界是：

- `PromptBuilder` 只负责把筛好的 memory 片段安全注入 prompt
- `DialogueEngine` 负责 retrieval、generation、guard 的编排
- `MemoryManager` 负责读写规则和存储隔离
- `Coordinator` 只在回合结束后触发写入，不碰 SQL 细节

---

## 8. 当前已知限制

这版能力刻意有限，已知限制包括：

- 还不是语义级长期记忆系统
- 还没有 embedding / vector retrieval
- 还没有 summary memory / scheduler 联动
- 还不是完整的人格反思器
- reply guard 仍然是规则系统，可能会有误判
- retrieval 目前仍以词面相关性和时效性为主，覆盖面有限

这些限制是当前阶段有意保留的。

---

## 9. 下一步更值得做什么

在这版基础设施稳定后，优先级建议是：

1. 补 memory review / manual override 入口
2. 增加更稳的短期摘要或重复事件合并
3. 让 scheduler 复用 episodic follow-up
4. 再考虑 embedding / vector retrieval 是否真的有必要

顺序上，应该先把“可信”和“可维护”做扎实，再扩能力。
