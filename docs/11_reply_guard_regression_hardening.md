# Reply Guard Regression Hardening

## 这轮目标

这次没有继续扩散 heuristic 数量，而是把 reply guard 收紧成一套更稳定、可解释、可回归的基础设施：

- 规则分层清楚
- violation taxonomy 稳定
- action 决策可解释
- regression bad cases 可以持续追加
- false positive 有单独看护
- fallback 仍然保留 Serina 的自然关系感

重点不是“多抓一点问题”，而是“稳定抓住最容易出戏的高频坏回复，同时不要乱杀正常回复”。

## 为什么改成 regression 驱动

reply guard 最容易出现的不是“完全没有规则”，而是：

- 新加一条规则之后，旧坏例又漏了
- 规则稍微收紧一点，正常 comfort / casual / correction 回复开始被误杀
- retry 能跑通，但语气变硬、人格被磨平

所以这轮优先把坏例集和 action 断言立住。后续调参时，先看 regression 是否稳，再决定要不要补规则。

## Violation Taxonomy

当前 guard 统一输出 `ReplyViolation`，核心字段包括：

- `rule_id`
- `category`
- `severity`
- `message`
- `evidence_excerpt`
- `should_block`
- `can_rewrite`
- `metadata`

当前稳定分类聚焦在高收益区域：

- `ai_self_disclosure`
- `fake_memory_claim`
- `unnatural_memory_reference`
- `over_preachy`
- `forbidden_style`
- `scene_conflict`
- `overlong`
- `templated_tone`
- `weak_boundary_in_correction`

这套 taxonomy 既给测试用，也给日志与后续统计用，避免不同层各自定义一套“违规名词”。

## Action 决策规则

reply guard 现在明确区分 `initial_action` 和 `final_action`：

- `accept`
  - 没有 violation，或只有不会改变结果的 info 级提示
- `rewrite`
  - 轻度问题
  - 只做本地规则化修复，不重新调用模型
  - rewrite 通过后，`final_action = accept`
- `retry_once`
  - 中度问题
  - 使用更保守的 prompt / generation 配置重试一次
  - 最多一次
- `safe_fallback`
  - 重度问题
  - 或 rewrite / retry 之后仍然失败

这套链路的关键点是：即使最终 `accept`，也保留初次 violations，方便后续排查为什么这轮触发过 guard。

## False Positive 控制

这轮专门把 false positive 拆成单独测试，不和 bad cases 混在一起。

当前控制原则：

- 不因为“稍微长一点”就直接杀掉合理深聊
- greeting 场景单独放宽长度判定，避免短问候被误判
- 只有当 scene + 结构 + 语气一起偏离时，才升级成 `retry_once`
- 正常的自然 memory 引用不应该被当成 fake memory

当 `expected_action == accept` 时，测试要求 `reply_guard_initial_violations` 必须为空，或者最多只允许不改变结果的 info 提示；否则视为 guard 过敏。

## 为什么 fallback 也要保留 persona

fallback 不是“系统报错文案”，而是 guard 最后一道兜底。

如果 fallback 写成：

- “抱歉，请再说一次”
- “作为系统，我无法……”
- “感谢理解，请继续输入……”

那即使 guard 挡住了坏回复，用户体验也一样会出戏。

所以这轮 fallback 仍然保持：

- 不暴露 AI 身份
- 不客服化
- 不机械报错
- 根据 `comfort / correction / greeting / deep_discussion / casual_chat` 做轻微 scene 化变化

## 已知限制

这仍然是一套规则系统，不是完整的人格反思器。

当前限制包括：

- 仍可能漏检某些更隐蔽的语气滑坡
- 仍可能对边界样本产生误判
- memory 引用判断仍以规则和轻量相关性为主
- 没有引入第二个 LLM 审稿器，也没有复杂 NLP 结构

这不是能力缺失，而是阶段性取舍。当前更大的风险不是“检索不够强”，而是“坏回复没被稳定挡住，或者正常回复被误杀”。
