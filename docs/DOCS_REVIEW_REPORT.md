# Project Serina 文档沉淀报告

审查日期：2026-05-27 | 文档总数：25 篇 | 审查方式：全文通读 + 与代码现状对照

---

## 一、文档分类总览

| 分类 | 篇数 | 文档 |
|---|---|---|
| 入口/导航 | 1 | README_docs_index.md |
| 产品定义 | 2 | 00_product_overview.md, 01_prd_v0.1.md |
| 仓库/开发指南 | 3 | 01_repo_guide.md, 02_dev_onboarding.md, 18_repo_structure_review_report.md |
| 人格/对话策略 | 2 | 02_persona.md, 04_dialogue_policy.md |
| 架构/实现 | 3 | 03_memory_design.md, 05_architecture.md, 06_mvp_demo_implementation_guide.md |
| 可观测性/评测 | 2 | 07_observability_guide.md, 08_eval_framework_guide.md |
| 版本迭代记录 | 3 | 09_memory_reply_guard_v0.1.md, 10_memory_reply_guard_v0.2.md, 11_reply_guard_regression_hardening.md |
| 子系统专题 | 5 | 13_assist_llm_lane.md, 14_memory_schema_v0.2.md, 15_session_consolidation_min_loop.md, 16_startup_memory_usage.md, 17_voice_cli_usage.md |
| 技术债务 | 1 | 03_architecture_debt_register.md |
| 语音/记忆迁移 | 3 | voice_memory_migration_plan.md, voice_memory_demo_usage.md, voice_memory_developer_guide.md |
| 其他 | 1 | example.json（测试 case 数据文件） |

---

## 二、逐篇总结与改进建议

### 1. README_docs_index.md — 文档索引入口

**语言状态**：中文为主，少量英文术语（runtime、voice mode 等），无不适当英文段落。

**总结**：这份索引将 22 篇文档按「入口 → 运行时/验证 → 设计/迭代历史」三个层次组织，边界清楚。标注了语音模式是可选的、短时记忆在 Coordinator 中、本地配置含密钥需注意等信息。对新维护者有明确的阅读路径指引。

**改进建议**：
- 新增的 `voice_memory_developer_guide.md` 和 `DOCS_REVIEW_REPORT.md` 未入索引，需同步更新。
- 建议增加"文档新鲜度"标记，区分「反映当前实现」与「阶段设计、可能已偏离」。

---

### 2. 00_product_overview.md — 产品说明书

**语言状态**：全中文。

**总结**：面向未来维护者的高密度说明，核心价值在于清晰区分「已实现 / 部分实现 / 明确非目标」三类状态。对主链路、核心系统位置关系（memory 在哪、reply guard 在哪、assist-llm 在哪）均有精确描述。设计原则一节（规则为主干、受限读写、硬约束层、可回归优先）是对整个项目价值观的高度浓缩。

**改进建议**：
- 优秀文档，保持即可。唯一建议：`已知限制`节提到 `src/memory/decay.py` 和 `src/memory/summarizer.py` 为"占位或疑似历史残留"，但当前这两个文件已有实装代码，需更新描述使其与代码现状一致。

---

### 3. 01_prd_v0.1.md — 产品需求文档 v0.1

**语言状态**：全中文。

**总结**：定义了 Serina 的产品定位（以陪伴为主、带轻度恋人感的私人数字伴侣）、核心目标（私聊自然 + 记忆连续）、人格方向（以鹫见芹奈为参考的原创延展人格）、功能范围和非目标边界。作为项目的"宪法级"文档，其价值观贯穿始终。

**改进建议**：
- 作为历史文档保留，不再更新。当前实现已大幅超出 v0.1 PRD 范围，建议在文档开头加一条前置说明："本 PRD 定义 v0.1 的产品边界；当前 v0.2 代码的现实以 `00_product_overview.md` 为准"。

---

### 4. 02_persona.md — 人格定义文档

**语言状态**：全中文。

**总结**：定义了 Serina 的可执行人格模型，包括核心气质（温柔、耐心、稳定、理性、细腻）、关系定义（熟悉用户、明确偏爱感的私人伴侣）、语言风格（中等长度、自然细腻、带少女感）、场景化表达策略（日常闲聊/安慰/纠偏/被逗弄等 8 类场景）和完整的禁止项清单。末尾 10 段示例对话是验证"像不像她"的黄金标准。

**改进建议**：
- 质量极高，保持即可。可考虑未来增加"场景化人格偏移容忍度"矩阵：什么场景下允许偏离多少人设。

---

### 5. 03_memory_design.md — 记忆系统设计

**语言状态**：全中文。

**总结**：定义了四层记忆结构（即时会话/近日事件/稳定档案/关系记忆）、写入策略（高信号写入、低信号过滤）、读取策略（相关才用、自然才提）、遗忘与衰减机制。设计原则清晰：重要性优先于完整性、关系感优先于流水账、允许遗忘和轻微模糊。

**改进建议**：
- 已与代码实现基本一致。建议补充一节说明 v0.2 新增的 `memory_class` / `representation` / `namespace` 等 schema 字段与本文的对应关系。

---

### 6. 04_dialogue_policy.md — 对话策略文档

**语言状态**：全中文。

**总结**：定义了 8 类对话场景的策略规则，包括回复长度分级、场景化表达原则和大量正反示例。核心原则"自然优先、陪伴优先于炫技、短答比空长答更好"体现在后续所有代码实现中。

**改进建议**：
- 作为设计文档质量极高。建议增加一节描述当前代码中 `infer_scene()` 的关键词匹配逻辑与本文场景分类的映射关系，帮助维护者理解"文档中的 8 类场景 → 代码中的 5 类场景"的简化过程及原因。

---

### 7. 05_architecture.md — 架构文档

**语言状态**：全中文，少量架构图图例为英文。

**总结**：定义了 v0.1 的 7 层模块划分（UI → App → Dialogue → Memory / Scheduler / Config → LLM Gateway → DeepSeek API → Storage），包括每层的职责和非职责。文档开头诚实声明"当前代码已越过纯文本 v0.1"，承认语音子系统已接入。

**改进建议**：
- 这是当前与代码现状偏差**最大**的文档。主要差距：
  - 未反映 `reply_guard/` 已成为独立子系统（checks/classify/actions/service/models)
  - 未反映 `assist_llm/` 已成型
  - 未反映语音子系统已从"预留"升级为"第一类能力"
  - 目录结构示例仍为 v0.1 早期形态
- 建议：要么将此文档标为"v0.1 架构历史"不再更新，要么做一次全面刷新以反映 v0.2 实现。当前更推荐前者，因为 `01_repo_guide.md` 和 `00_product_overview.md` 已在承担"当前事实描述"职责。

---

### 8. 06_mvp_demo_implementation_guide.md — 最小 Demo 实现说明

**语言状态**：全中文，代码示例为英文。

**总结**：这是最长的文档（1133 行），以"面向项目主人的源码导览"方式，完整解说了 v0.1 的代码结构、每层职责、一条消息从输入到输出的完整流程（9 步）。对"为什么 system prompt 要分块"、"为什么 main.py 很薄"、"为什么 postprocess 很轻"等设计决策都有清晰论证。末尾给出了"最值得学到的 5 个思路"：

1. 先定义边界，再写代码
2. 让设计文档和运行配置分层
3. 让每层只做自己的职责
4. 先做可运行的最小闭环
5. 不假装复杂能力已经存在

**改进建议**：
- 这是最有价值的文档之一，但已显著过时。文中描述的"当前 Demo"没有 memory/scheduler/storage，实际 v0.2 已有成熟的 memory 系统、reply guard 和 assist-llm。
- 建议：保留为"v0.1 实现的历史参考"，或大幅刷新覆盖当前主链路。对于新维护者，优先推荐读 `01_repo_guide.md`。

---

### 9. 07_observability_guide.md — 可观察性说明

**语言状态**：全中文。

**总结**：介绍了 debug trace 的配置开关、日志写入位置（JSONL 格式）、一轮 trace 的典型事件序列、CLI 诊断信息和隐私边界。配置建议（日常安静 / 调试全开两套模式）实用。

**改进建议**：
- 事件列表缺少 v0.2 新增的 guard/assist 相关事件（如 `reply_guard_checked`、`reply_guard_retry_completed`、`assist_llm_*` 等）。当前 `02_dev_onboarding.md` 中已有更完整的事件枚举，建议同步到此文档或通过交叉引用避免维护两份不同的事件清单。

---

### 10. 08_eval_framework_guide.md — 评测框架指南

**语言状态**：全中文，代码命令为英文。

**总结**：描述了评测体系的两层结构（unittest smoke + pytest regression），定义了回归 case 的标准字段（case_id / input_history / user_input / expected_* ），列出了当前覆盖的 4 个维度（memory write、memory retrieve、reply guard、conversation flow）的大致内容。

**改进建议**：
- 覆盖面描述使用了定性语言（"显式称呼偏好"等），建议用具体数字量化：如"memory write 8 条、memory retrieve 8 条、reply guard 34 条、conversation flow 6 条"。当前报告末尾已包含此信息。
- 建议补充一节说明 `src/evals/` 独立 runner 和 `tests/regression/` pytest 参数化路径的分工定位。

---

### 11. 09_memory_reply_guard_v0.1.md — memory+reply guard v0.1 改造说明

**语言状态**：全中文。

**总结**：记录了从纯对话 Demo 到接入 memory + guard 基础设施的过渡设计。关键决策包括：不引入向量库、先拆 profile/episodic 两层、high-signal 写入、最多注入 2~4 条、reply guard 用轻量规则不做复杂 NLP。每个决策都有详细的 WHY 论证，设计价值超过记录价值。

**改进建议**：
- 质量高，保持即可。建议在文首加一条交叉引用："v0.2 的演进见 `10_memory_reply_guard_v0.2.md`"。

---

### 12. 10_memory_reply_guard_v0.2.md — memory+reply guard v0.2 迭代说明

**语言状态**：全中文，少量英文术语（regression、manual override 等）。

**总结**：记录了 v0.2 迭代的优先级（先可回归 → 再可纠错 → 最后才考虑更强检索）。核心新增能力包括：regression eval（约 30 条回放样例）、manual override（/memory 命令组）、merge + summary（同主题合并）、follow-up adapter、guard observability（区分 initial_action / final_action）。

**改进建议**：
- 文档中写"30 条左右的 memory / guard / flow 回放样例"，当前实际已增长至 56 条回归 case + 23 条 eval case，建议更新此数字或注明"截至 v0.2 发布时"。

---

### 13. 11_reply_guard_regression_hardening.md — reply guard 回归加固

**语言状态**：全中文，taxonomy 字段名保留英文。

**总结**：定义了稳定的违规分类体系（9 类 violation taxonomy）、action 决策规则（accept / rewrite / retry_once / safe_fallback 四级链路）、false positive 单独控制原则和 fallback 保留 persona 而不暴露 AI 身份的规则。这是 reply guard 子系统的核心规范，代码实现直接参照此文档。

**改进建议**：
- 这是与代码实现一致性最高的文档之一。建议补充一个"违规严重度判定速查表"：什么条件下从 light → medium → severe 的升级规则，使分类决策更可解释。

---

### 14. 13_assist_llm_lane.md — 辅助 LLM 通道说明

**语言状态**：全英文。

**总结**：定义了 assist-llm 的设计约束：白名单任务制、runtime 每 turn 最多 1 次、4 秒超时、不允许绕过 reply guard、不允许递归。区分了 dev tasks（4 个）和 runtime tasks（2 个）。记录了每次调用的完整可观测字段。核心原则是"assist 不能替代规则、只能作为受控辅助"。

**改进建议**：
- 需翻译为中文（全篇英文，是文档体系中唯一一篇纯英文文档）。
- 建议增加一节"asist-llm 何时不适用"，明确列出不适合引入 assist 的场景，反向约束白名单扩展。

---

### 15. 14_memory_schema_v0.2.md — memory schema v0.2

**语言状态**：全中文，字段名保留英文。

**总结**：定义了 v0.2 记忆 schema 修正：将原来 `memory_type` 承担的"是什么记忆"和"怎么表达"两层语义拆分为 `memory_type`（兼容层）+ `memory_class`（生命周期/用途轴）+ `representation`（表达形式轴）。新增了 preference 显式一等语义、冲突/覆盖/确认机制（supersedes_id / contradicts_id / last_confirmed_at）、namespace/owner_kind 边界。

**改进建议**：
- 为与当前代码实现保持可追溯性，建议增加"schema 实现清单"：每个新字段在 `store.py` 的 `_ensure_columns()` 中是否已迁移、写入路径是否已支持。
- 文档中"本轮只做了最小接口准备"等措辞意味着部分字段尚未完全投入检索/注入路径，建议明确标注。

---

### 16. 15_session_consolidation_min_loop.md — 会话合并最小闭环

**语言状态**：全英文。

**总结**：定义了 session memory 到长期 memory 的最小提升循环。核心约束包括：只允许 3 类候选（episodic / task / preference）、确定性规则优先、idempotency 保护（promotion_fingerprint）、触发点克制（turn-end 每次最多处理 1 条）、不强依赖 assist-llm。明确标注了"为什么这仍然不是自由反思型 agent"。

**改进建议**：
- 需翻译为中文。
- 建议增加交叉引用到 `16_startup_memory_usage.md`，说明 consolidation 和 startup continuity 的关系。

---

### 17. 16_startup_memory_usage.md — 启动记忆使用指南

**语言状态**：全英文。

**总结**：描述了跨会话 continuity 的轻量实现：启动时从 profile / episodic / open loops / last session summary 四个来源组装 startup memory pack，仅在最先 1-2 轮注入。"继续"/"上次那个问题"等续接线索触发优先路径，普通问候不走。包含完整的验证方式（SQLite 查询、CLI 手工验证步骤）和 reset 数据的方法。

**改进建议**：
- 需翻译为中文。
- 建议增加一节说明"为什么只有 summary，不做完整 history replay"的设计理念，与 memory 系统"克制"原则保持一致。

---

### 18. 17_voice_cli_usage.md — 语音 CLI 使用说明

**语言状态**：全英文，命令示例中少量中文路径。

**总结**：记录了语音 CLI 的当前运行形态：录音（BlockingWavRecorder + 端点检测）→ ASR（sherpa-onnx SenseVoice）→ 复用文本 Coordinator → TTS（CosyVoice local）→ 播放（BlockingAudioPlayback）。包括 auto-listen 和 manual 两种模式、依赖说明、debug 音频保存和当前限制清单。

**改进建议**：
- 需翻译为中文。
- 文档中描述的是当前本地语音配置形态，但 `voice_config.yaml` 中同时保留了 myneuro_asr / gpt_sovits_v2 的配置字段。建议在文档中明确区分"当前默认部署配置"和"可选的外部服务配置"。
- 补充与 `voice_memory_developer_guide.md` 的交叉引用。

---

### 19. 18_repo_structure_review_report.md — 仓库结构审查报告

**语言状态**：全中文，数据和表格列名为英文。

**总结**：这是一份高价值的**静态结构审查报告**，由 CDR 系统生成（非人工编写）。报告覆盖了：仓库边界污染（memory_selection/ 和 Neuro/ 混入外部 .git）、核心复杂度集中（10 个大文件）、测试体系健康度抽样（209 passed，但仓库级 pytest 被外部文件污染）、文档与实现漂移案例、面向重构负责人的 5 条建议。

**改进建议**：
- 这是当前仓库治理最重要的参考文档。报告中指出的 P0 问题（仓库边界、依赖治理、超大文件）至今仍部分存在（如 `memory_selection/` 和 `Neuro/` 仍在根目录），建议作为后续重构的 checklist 来跟踪推进状态。
- 建议在报告头部标注审查日期与"当前解决状态"，避免报告本身也变成过时文档。

---

### 20. 03_architecture_debt_register.md — 架构债登记册

**语言状态**：全中文。

**总结**：完整的技术债清单，按 P0/P1/P2 三级排序。P0 包括：配置与密钥边界、DialogueEngine 过重、migration 隐式补列、runtime/dev path 边界模糊、assist task 入口不完整。每项都有"问题 → 影响 → 建议方向"三段式结构。末尾附有测试覆盖盲区、文档不一致风险和优先处理建议。

**改进建议**：
- 建议为每项债务增加一个"当前状态"标记（已修复/部分缓解/未处理/已接受），将登记册从静态记录变为活的跟踪看板。
- P0 第 1 项（配置与密钥边界）在 dev onboarding 中已被提及，但未实质解决，建议标注优先级。

---

### 21. voice_memory_migration_plan.md — 语音+记忆迁移方案

**语言状态**：全中文，代码接口定义为英文。

**总结**：一份**已经执行完毕**的方案文档。它规划了从纯文本到语音+记忆的迁移路径，包括 STT/TTS/Memory 的接口设计（Protocol 风格）、SQLite schema v6 新增 `conversation_turns` 表、可打断 TTS 事件流设计（ESC + 麦克风 RMS 双通道打断）、以及最小可运行 Demo 路线（10 步）。当前代码已完全实现此方案。

**改进建议**：
- 在文首标注"此方案已执行完毕，当前实现见 `main_voice.py` 和 `voice/` 子系统"，将文档从"计划"转为"实现记录"。
- 方案中计划的模块（`voice_loop.py`、`stt_service.py` 等）已创建，但实际文件名和接口可能有微调，建议做一次对照更新。

---

### 22. voice_memory_demo_usage.md — 语音记忆 Demo 使用说明

**语言状态**：全中文，命令为英文。

**总结**：面向用户的语音 Demo 一键启动指南，包括 5 种启动模式（DryRun / Manual / AutoListen / NoTTS / SkipServices）、前置条件检查清单、启动后流程（9 步）、打断 TTS 方式（ESC 或麦克风说话）、短期/长期记忆验证方法、常见失败排查。实用性强。

**改进建议**：
- 文档中提到的 my-neuro ASR 和 GPT-SoVITS v2 是外部服务依赖，当前本地配置已切换到 sherpa-onnx SenseVoice + CosyVoice。建议明确标注哪套是"当前本地默认"，哪套是"外部服务可选"。
- 补充以本地语音配置（sherpa-onnx + CosyVoice）启动的说明。

---

### 23. voice_memory_developer_guide.md — 语音记忆开发者指南

**语言状态**：全中文，代码示例为英文。

**总结**：面向开发者的语音子系统指南，覆盖了入口文件职责说明（main.py / main_voice.py / controller.py / voice_loop.py 等）、文字和语音两条运行路径的流程对比图、TTS interrupt 机制原理、SQLite 四个表的用途、配置说明（ASR/TTS/interrupt 关键字段）、常见调试命令（设备列表、ASR/TTS 健康检查、SQLite 检查）、以及 ASR/TTS 替换和 Live2D 扩展教程。

**改进建议**：
- 文档中描述的 my-neuro + GPT-SoVITS v2 组合与当前本地 sherpa-onnx + CosyVoice 配置并行存在，建议增加一节"本地配置与外部服务配置的切换方法"。
- 扩展教程部分的代码示例可考虑与当前 `tests/` 中的 mock provider 实现对应。

---

### 24. example.json — reply guard 回归 case 数据

**语言状态**：全英文（字段名和值），中文注释。

**总结**：实际是 `tests/regression/cases_reply_guard.py` 的早期版本/备份数据文件。包含 34 条 REPLY_GUARD_CASES，覆盖 AI 自我声明(4)、假记忆(6)、场景冲突(6)、模板化(6)、action 链路(6)、false positive(6) 六大类。所有 case 使用相同的五字段结构（case_id / scene / assistant_reply / expected_* / notes）。

**改进建议**：
- 此文件与 `tests/regression/cases_reply_guard.py` 功能重叠但格式略有差异（前者缺少 `expected_initial_action`/`expected_final_action` 字段，后者使用了 `_case()` 辅助函数和更新的断言逻辑）。
- 建议：如果此文件已不作为实际测试数据源，应将其删除或移到 `docs/` 中作为"case 设计参考"标注用途。避免维护两条不同步的 case 数据。

---

### 25. DOCS_REVIEW_REPORT.md — 本文档

即本文档，作为所有文档的集中审查、总结与改进建议。

---

## 三、英文文档清单（需翻译为中文）

以下 4 篇文档为全英文撰写，需翻译为中文：

| 文档 | 内容 | 优先级 |
|---|---|---|
| `13_assist_llm_lane.md` | assist-llm 通道设计 | 高 — 核心子系统 |
| `15_session_consolidation_min_loop.md` | 会话合并最小闭环 | 高 — 新增机制 |
| `16_startup_memory_usage.md` | 启动记忆使用指南 | 中 — 使用指南 |
| `17_voice_cli_usage.md` | 语音 CLI 使用说明 | 中 — 使用指南 |

---

## 四、与代码现状偏差较大的文档

| 文档 | 主要偏差 | 影响 |
|---|---|---|
| `05_architecture.md` | 仍为 v0.1 纯文本架构，缺少 voice/reply_guard/assist 子系统 | 高 |
| `06_mvp_demo_implementation_guide.md` | 描述的是 v0.1 最小 Demo，不含 memory/guard/scheduler | 中 |
| `17_voice_cli_usage.md` | 描述旧 voice provider 组合 | 中 |
| `example.json` | 与 `cases_reply_guard.py` 数据重复且格式不同步 | 低 |
| `voice_memory_migration_plan.md` | 方案已执行完毕但未标注 | 低 |

---

## 五、评测用例统计

### 5.1 回归测试用例（pytest 参数化，tests/regression/）

| 测试集 | 用例数 | 文件 |
|---|---|---|
| Memory Write（记忆写入） | 8 | `cases_memory_write.py` |
| Memory Retrieve（记忆检索） | 8 | `cases_memory_retrieve.py` |
| Reply Guard（回复护栏） | 34 | `cases_reply_guard.py` |
| Conversation Flow（对话流程） | 6 | `cases_conversation_flow.py` |
| **回归用例合计** | **56** | |

### 5.2 独立评测用例（JSONL，evals/cases/）

| 测试套件 | 用例数 | 文件 |
|---|---|---|
| Smoke Cases（冒烟测试） | 18（+1 禁用） | `smoke_cases.jsonl` |
| Startup Continuity（启动续接） | 4 | `startup_continuity_cases.jsonl` |
| **独立评测用例合计** | **22（启用）** | |

### 5.3 全部评测用例合计：78 条

---

## 六、回归用例覆盖的 Bad Case 类型

### Reply Guard (34 条) — 覆盖 6 类 bad case：

| Bad Case 类型 | 用例数 | 说明 |
|---|---|---|
| A. AI 自我声明（ai_self_disclosure） | 4 | "作为 AI"、"我是语言模型"、暴露程序身份等 |
| B. 假记忆/越界记忆引用（fake_memory_claim） | 6 | 无依据声称"我记得你之前"、低置信度被说成确定事实、短期事件上升为人格判断等 |
| C. 场景冲突（scene_conflict） | 6 | comfort 被训导、轻聊被分析、correction 太软、深聊太浮等 |
| D. 模板化/客服感/过长（templated_tone） | 6 | "下面我将从三个方面"、空泛鼓励、"亲爱的用户"、过长大纲式回复等 |
| E. Action 链路（action_chain） | 6 | 验证 rewrite → retry_once → safe_fallback 各级决策的正确性 |
| F. False Positive（误杀看护） | 6 | 正常 comfort、正常轻聊、自然 memory 引用等不该被误杀的边界 case |

### Memory Write (8 条) — 覆盖 5 类场景：

| 类型 | 用例数 |
|---|---|
| 显式偏好写入（称呼/互动/话题） | 3 |
| 低信号不写入（寒暄/低信息抱怨） | 2 |
| 近期事项写入（项目推进/情绪状态） | 2 |
| 显式 follow-up 写入 | 1 |

### Memory Retrieve (8 条) — 覆盖 6 类场景：

| 类型 | 用例数 |
|---|---|
| 正常命中（项目/偏好） | 2 |
| 不应注入（无关输入/低置信度/过期） | 3 |
| 注入质量控制（上限/去重/空退化） | 3 |

### Conversation Flow (6 条) — 覆盖 4 类场景：

| 类型 | 用例数 |
|---|---|
| 正常通过（memory 命中/未命中 + accept） | 2 |
| 轻度改写（rewrite → accept） | 2 |
| 中度重试（retry_once → accept） | 1 |
| 重度兜底（safe_fallback） | 1 |

### 独立 Eval (22 条) — 覆盖覆盖场景：

| 场景类别 | 用例数 |
|---|---|
| 问候（greeting） | 3 |
| 闲聊（casual_chat） | 7 |
| 安慰（comfort） | 3 |
| 纠偏（correction） | 2 |
| 深度讨论（deep_discussion） | 3 |
| 禁用风格（forbidden_style） | 2 |
| 启动续接（startup_memory） | 4 |

### 汇总：跨回归 + 独立评测，共覆盖约 15 类 bad case/验证场景

核心 bad case 维度包括：AI 身份暴露、假记忆、场景冲突、模板化、过长、客服腔、禁止风格、空泛鼓励、纠偏过软、误杀、记忆噪声、过期注入、低置信注入、注入上限、跨会话断裂等。

---

## 七、整体改进建议优先级

### P0 — 立即处理
1. 翻译 4 篇英文文档为中文（`13_assist_llm_lane.md`、`15_session_consolidation_min_loop.md`、`16_startup_memory_usage.md`、`17_voice_cli_usage.md`）
2. 在 `05_architecture.md` 文首标注"本文档反映 v0.1 架构设计，当前实现以 `01_repo_guide.md` 和 `00_product_overview.md` 为准"
3. 修正 `00_product_overview.md` 中关于 `decay.py`/`summarizer.py` 为"占位"的描述

### P1 — 近期处理
4. 删除或明确标注 `example.json`（与 `cases_reply_guard.py` 重复）
5. 在 `voice_memory_migration_plan.md` 标注"方案已执行完毕"
6. 为 `03_architecture_debt_register.md` 增加当前解决状态标记
7. 更新 `README_docs_index.md` 纳入新增和变更的文档

### P2 — 持续维护
8. 为所有阶段设计文档（`01_prd_v0.1.md`、`05_architecture.md`、`06_mvp_demo_implementation_guide.md`）增加版本叙事标签
9. 在 `08_eval_framework_guide.md` 中用具体数字替换定性描述
10. 为每篇专题文档增加"最后验证日期"与"对应代码版本"元信息
