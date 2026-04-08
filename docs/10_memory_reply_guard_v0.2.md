# Memory + Reply Guard v0.2 Transition Note

## 1. 这次迭代的定位

这次不是继续“堆功能”，而是把已经接进主链路的 memory + reply guard 做成更可信的产品基础设施。

优先级顺序是：

1. 先可回归
2. 再可纠错
3. 最后才考虑更强检索

一句话说：

> 当前阶段最大的风险不是“记不住”，而是“写错、读偏、假装记得、出了问题却没法纠正”。

## 2. 为什么下一步先做 regression eval

memory 和 guard 都不是单点功能，它们的风险是链路级的：

- 写入规则改一点，可能会把噪声写爆
- retrieval 排序改一点，可能会开始强行注入旧记忆
- guard 规则改一点，可能会把正常回复误杀

所以这轮优先补的是“真实对话回放式” regression，而不是继续增加更多 heuristic。

当前 regression 设计原则：

- case 数据和断言逻辑分离
- 能快速看出失败属于 `write / retrieve / guard / flow` 哪一层
- 允许后续持续追加真实坏例

## 3. 为什么 memory review 比更强检索更重要

一条写错的 memory，伤害通常比“暂时没记住”更大。

原因很直接：

- 它会被后续多轮对话反复引用
- 它会让用户觉得系统在“自作聪明”
- 它会让 debug 很难，因为问题不是生成瞬时错误，而是状态污染

所以在引入更强 retrieval 之前，必须先给出最小可用的纠错入口：

- `/memory list`
- `/memory archive <id>`
- `/memory delete <id>`
- `/memory expire <id>`
- `/memory pin <id>` / `/memory unpin <id>`
- `/memory update <id> ...`

这类 manual override 的价值，不是“方便运营”，而是给系统一个可以被人纠偏的出口。

## 4. 为什么要做重复事件合并和短期摘要

如果 episodic memory 不做合并，它很快会退化成：

- 同一项目不同说法反复堆积
- retrieval 命中多个几乎相同的条目
- prompt 注入上限被重复信息占满

这轮做的是最小合并，不做复杂聚类：

- 近时间窗口
- 同 topic_key / 重叠 tags / 轻量字符串相似度
- 合并后刷新 `updated_at / expires_at / tags / merge_count`
- 为代表条目生成一个短 summary

summary 的目标不是“更聪明”，而是“更短、更稳、更好注入”。

## 5. 为什么 scheduler 只先复用显式 follow-up

这轮 scheduler 只接 explicit follow-up episodic memory，例如：

- “过两天再问我这个项目的进展”
- “之后提醒我继续这个任务”
- “下次可以继续追问”

故意不做的事情：

- 不把普通项目记忆自动升级成主动打扰
- 不做复杂主动策略
- 不做后台无限触发

原因是主动系统一旦越界，体验伤害会非常大。当前更适合先做到：

- 候选识别清楚
- 过期过滤清楚
- 冷却时间清楚
- 接受 / 拒绝原因可观测

## 6. 为什么继续不引入向量库

这不是因为“不会做 embedding retrieval”，而是因为当前更大的风险根本不在那里。

现在最需要先控制的是：

- 写入噪声
- 记忆污染
- 越界注入
- 风格不稳定
- 无法回放和纠错

在这些问题没压住之前，上向量库只会把问题从“规则可解释”变成“行为更难解释”。

因此当前阶段继续坚持：

- 不引入向量数据库
- 不做 embedding 索引
- 不做复杂语义检索

但边界上已经为未来留了口子：

- retriever 不直接绑定某个具体检索实现
- store 不假设永远只有 SQLite / JSON
- memory record 结构允许未来追加 embedding metadata

## 7. 当前新增的关键能力

### 7.1 regression eval

- pytest 参数化 regression suite
- 30 条左右的 memory / guard / flow 回放样例
- case 数据和断言逻辑分离

### 7.2 manual override

- 命令式 memory review 入口
- 不影响普通聊天主链路
- manual override 日志独立可追踪

### 7.3 merge + summary

- 同主题近期 episodic 合并
- retrieval 优先读代表条目
- merge_count / summary 可观察

### 7.4 follow-up adapter

- 只从 explicit follow-up episodic 中筛候选
- 考虑有效期与 cooldown
- 接受 / 拒绝原因写日志

### 7.5 guard observability

- 区分 `reply_guard_initial_action`
- 额外暴露 `reply_guard_initial_violations`
- 便于排查 `retry -> accept` 这类链路

## 8. 当前已知限制

- 还不是语义级长期记忆系统
- 还没有 summary memory 层级提升
- 规则仍可能误判
- scheduler 目前只是 candidate adapter，不是完整主动系统
- retrieval 仍以保守规则和词面相关性为主

## 9. 下一步最值得做什么

最优先建议仍然是两件事：

1. 把真实线上坏例持续沉淀进 regression cases
2. 在 manual override 之上补一层轻量 memory review 流程，例如“待确认候选”或“低置信度待复核”

在这两步做稳之前，不建议把重点切到更重的检索系统上。
