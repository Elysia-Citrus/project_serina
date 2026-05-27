# Project Serina 仓库导览

## 这份文档解决什么问题

这份文档的目标是让你快速知道：

- 仓库从哪里开始看
- 哪些目录是 runtime 主路径
- 哪些目录是 dev-only 工具
- 如果你要改 memory / reply guard / assist-llm，先看哪些文件
- 哪些地方可能是历史残留或半接线路径

## 顶层目录导览

### 核心目录

- `src/`：主要源码。
- `tests/`：单测、回归测试、辅助 fixture。
- `docs/`：专题设计文档与维护者文档。
- `scripts/`：eval、语音运行、语音诊断、本地 TTS sidecar 等开发/本地运行脚本。
- `evals/`：独立 eval case 数据。
- `artifacts/`：eval、voice tmp 等本地运行产物。
- `data/`：运行期数据，当前包括 `serina.db` 和可选 trace logs。
- `pyproject.toml`：依赖入口和 pytest 默认收集边界。
- `.gitignore`：本地生成物、缓存、运行产物的忽略规则。

### 其他目录

- `docx/`：作者自己生成的阶段性归档文档，不属于 runtime 必需目录。

### 需要谨慎解读的目录

- `memory_selection/`：外部记忆项目参考资料，不属于默认测试/打包/依赖扫描边界。
- `Neuro/`：外部语音/代理项目参考资料，不属于默认测试/打包/依赖扫描边界。
- `src/storage/`：预留的未来持久化命名空间；当前真实 memory SQLite 实现在 `src/memory/store.py`。

## `src/` 下关键模块导览

### 主链路相关

- `src/app/main.py`：CLI 入口，组装运行时对象。
- `src/app/main_voice.py`：语音 CLI 入口，复用文本主链路。
- `src/app/runtime.py`：文本/语音共享运行时装配 factory。
- `src/app/ui_adapter.py`：终端 UI 封装。
- `src/app/command_router.py`：拦截 `/memory`、`/trace`、`/badcase` 命令。
- `src/app/coordinator.py`：turn 级编排、history、memory write、follow-up scan。
- `src/dialogue/engine.py`：主对话引擎，是 runtime 编排核心。
- `src/dialogue/prompt_builder.py`：scene 推断、system prompt block 组装。
- `src/dialogue/postprocess.py`：生成后轻量清洗和 fallback。
- `src/llm/gateway.py`：统一网关。
- `src/llm/providers/deepseek.py`：当前唯一 provider。

### memory 相关

- `src/memory/models.py`：memory 数据结构。
- `src/memory/manager.py`：memory 对上层的统一门面。
- `src/memory/reader.py`：读取和排序。
- `src/memory/writer.py`：候选提取后的写入与 merge。
- `src/memory/rules.py`：high-signal、相关性、topic_key、merge 规则。
- `src/memory/store.py`：SQLite 持久化和迁移。
- `src/memory/admin.py`：manual override 服务。
- `src/memory/decay.py`：session memory 衰减、final attempt、归档扫尾。
- `src/memory/summarizer.py`：session consolidation 摘要、promotion candidate 构造。

### voice 相关

- `src/voice/controller.py`：语音 turn 编排。
- `src/voice/recorder.py` / `src/voice/microphone_stream.py` / `src/voice/endpoint.py`：录音和端点检测。
- `src/voice/asr.py`：ASR provider，包括本地 sherpa-onnx SenseVoice。
- `src/voice/synthesis.py` / `src/voice/tts.py` / `src/voice/local_runtime_server.py`：TTS 选择、本地 runtime server、合成服务。
- `src/voice/playback.py`：音频播放。
- `src/voice/profiles.py`：voice profile registry。

### config 相关

- `src/config/loader.py`：对外加载入口，保留原 public API。
- `src/config/models.py`：配置 dataclass 模型。
- `src/config/yaml_utils.py`：YAML 读取和最小 fallback parser。
- `src/config/validators.py`：配置字段校验与转换 helper。
- `src/config/runtime_config.yaml`、`voice_config.yaml` 等：当前本地运行配置，保留 local inline key 形态。

### reply guard 相关

- `src/dialogue/reply_guard/models.py`：统一 violation / assessment / decision 结构。
- `src/dialogue/reply_guard/checks.py`：单项检查器。
- `src/dialogue/reply_guard/classify.py`：severity 与 action 决策。
- `src/dialogue/reply_guard/actions.py`：rewrite / retry / fallback 逻辑。
- `src/dialogue/reply_guard/service.py`：统一入口，接入 optional assist。

### assist-llm 相关

- `src/assist_llm/models.py`：任务、请求、响应、call record。
- `src/assist_llm/config.py`：assist 配置映射。
- `src/assist_llm/tasks.py`：白名单任务注册表。
- `src/assist_llm/prompts.py`：每个任务的短 prompt 和解析器。
- `src/assist_llm/service.py`：预算、超时、递归保护、统一调用入口。

### trace / observability 相关

- `src/observability/trace.py`：`TurnTrace`。
- `src/utils/logger.py`：日志初始化、JSON 事件 trace、trace file path 管理。
- `src/observability/trace_admin.py`：trace summary / badcase draft 开发命令服务。

### scheduler 相关

- `src/scheduler/followup_adapter.py`：从 episodic memory 中筛 explicit follow-up candidate。
- `src/scheduler/manager.py`：scheduler 统一门面。
- `src/scheduler/proactive.py`：预留 proactive scheduling lane，当前未接线。
- `src/scheduler/reminder.py`：预留 reminder lane，当前未接线。

### eval / regression 相关

- `src/evals/loader.py`：eval case 加载。
- `src/evals/checker.py`：response checks。
- `src/evals/reporter.py`：eval 结果写出。
- `src/evals/run_eval.py`：独立 eval CLI。

## 每个关键模块一句话职责

- `Coordinator`：会话层编排，不直接碰底层 SQL。
- `DialogueEngine`：回复生成主流程总控。
- `PromptBuilder`：把 persona / policy / scene / memory 变成 prompt。
- `MemoryManager`：把 retrieve / write / admin 操作统一起来。
- `ReplyGuard`：把生成后的回复拉回边界内。
- `AssistLLMService`：严格受控的辅助 LLM 通道。
- `TraceAdminService`：把 trace 变成开发者可读摘要或 badcase 草稿。
- `SchedulerManager`：当前只负责 follow-up candidate 扫描。

## 主链路相关模块怎么读

如果你要理解“用户输入后到底发生了什么”，推荐顺序：

1. `src/app/main.py`
2. `src/app/runtime.py`
3. `src/app/command_router.py`
4. `src/app/coordinator.py`
5. `src/dialogue/engine.py`
6. `src/dialogue/prompt_builder.py`
7. `src/llm/gateway.py`
8. `src/dialogue/postprocess.py`
9. `src/dialogue/reply_guard/service.py`
10. `src/memory/manager.py`
11. `src/utils/logger.py`

## 如果你要理解 voice，请先看这些文件

推荐顺序：

1. `docs/17_voice_cli_usage.md`
2. `src/app/main_voice.py`
3. `src/app/runtime.py`
4. `src/voice/controller.py`
5. `src/voice/recorder.py`
6. `src/voice/asr.py`
7. `src/voice/synthesis.py`
8. `src/voice/tts.py`
9. `src/voice/local_runtime_server.py`
10. `tests/test_voice_*`

真实关系是：voice shell 只负责录音、转写、合成、播放；对话、记忆、reply guard 和 scheduler 仍走文本主链路。

## 如果你要理解 memory，请先看这些文件

推荐顺序：

1. `src/memory/models.py`
2. `src/memory/manager.py`
3. `src/memory/rules.py`
4. `src/memory/writer.py`
5. `src/memory/reader.py`
6. `src/memory/store.py`
7. `src/memory/admin.py`
8. `tests/test_memory_writer.py`
9. `tests/test_memory_reader.py`
10. `tests/test_memory_merge.py`
11. `tests/test_memory_store_migration.py`
12. `tests/regression/cases_memory_write.py`
13. `tests/regression/cases_memory_retrieve.py`

为什么这样读：

- `models -> manager` 先建立对象边界。
- `rules -> writer/reader` 再看行为逻辑。
- `store` 最后看持久化和迁移。
- `tests` 用来反查真实预期。

## 如果你要理解 manual override，请先看这些文件

推荐顺序：

1. `src/app/command_router.py`
2. `src/memory/admin.py`
3. `src/memory/manager.py`
4. `src/memory/store.py`
5. `tests/test_command_router.py`

真实链路是：

`/memory ... -> CommandRouter -> MemoryAdminService -> MemoryManager -> SQLiteMemoryStore`

## 如果你要改 reply guard，请先看这些文件

推荐顺序：

1. `src/dialogue/reply_guard/models.py`
2. `src/dialogue/reply_guard/checks.py`
3. `src/dialogue/reply_guard/classify.py`
4. `src/dialogue/reply_guard/actions.py`
5. `src/dialogue/reply_guard/service.py`
6. `src/dialogue/engine.py`
7. `tests/test_reply_guard.py`
8. `tests/regression/cases_reply_guard.py`
9. `tests/regression/test_reply_guard_regression.py`
10. `tests/regression/test_reply_guard_actions.py`
11. `tests/regression/test_reply_guard_false_positive.py`

注意：

- `engine.py` 里有 runtime retry / assist retry 真实接线。
- false positive 守护主要在 regression tests 里，不是 runtime 独立模块。

## 如果你要理解 assist-llm，请先看这些文件

推荐顺序：

1. `src/assist_llm/models.py`
2. `src/assist_llm/config.py`
3. `src/assist_llm/tasks.py`
4. `src/assist_llm/prompts.py`
5. `src/assist_llm/service.py`
6. `src/dialogue/reply_guard/service.py`
7. `src/dialogue/engine.py`
8. `src/observability/trace_admin.py`
9. `tests/test_assist_llm_service.py`
10. `tests/test_assist_llm_runtime.py`

这里要先分清：

- runtime helper：`guard_retry_rewrite`、`optional_memory_reference_check`
- dev tool：`summarize_trace_cluster`、`draft_badcase_case`
- 已定义但未形成稳定入口：`review_pending_memory_note`、`summarize_episodic_merge`

## 如果你要理解 trace / badcase CLI，请先看这些文件

推荐顺序：

1. `src/app/command_router.py`
2. `src/observability/trace_admin.py`
3. `src/assist_llm/service.py`
4. `src/assist_llm/prompts.py`
5. `tests/test_command_router.py`
6. `docs/13_assist_llm_lane.md`

这条路径的真实关系是：

- `/trace summary` 和 `/badcase draft` 先由 `CommandRouter` 解析参数
- 再进入 `TraceAdminService`
- `TraceAdminService` 优先调用 assist dev task
- assist 不可用时退回规则 summary / 规则 badcase payload

## trace / observability 相关模块怎么读

推荐顺序：

1. `src/observability/trace.py`
2. `src/utils/logger.py`
3. `src/app/coordinator.py`
4. `src/dialogue/engine.py`
5. `src/observability/trace_admin.py`
6. `tests/test_command_router.py`

你会看到：

- trace 字段是怎样被逐步补全的
- 哪些事件来自 reply guard
- 哪些事件来自 assist-llm
- trace CLI 如何做规则 fallback

## scheduler 相关模块怎么读

推荐顺序：

1. `src/scheduler/followup_adapter.py`
2. `src/scheduler/manager.py`
3. `src/app/coordinator.py`
4. `tests/test_followup_adapter.py`

从代码事实看，当前 scheduler 只到 “扫描 candidate + 记录原因” 这一步。

## tests 的组织方式

`pyproject.toml` 已把默认 pytest 收集范围限定到 `tests/`，并排除 `memory_selection/`、`Neuro/`、`artifacts/` 等非主项目目录。

### `tests/` 根目录

这里主要放：

- smoke tests
- 单模块行为测试
- service 级集成测试

关键文件包括：

- `tests/test_dialogue_pipeline.py`
- `tests/test_reply_guard.py`
- `tests/test_memory_writer.py`
- `tests/test_memory_reader.py`
- `tests/test_memory_merge.py`
- `tests/test_memory_store_migration.py`
- `tests/test_followup_adapter.py`
- `tests/test_command_router.py`
- `tests/test_assist_llm_service.py`
- `tests/test_assist_llm_runtime.py`

### `tests/regression/`

这里是参数化 badcase / flow 回放：

- `cases_*.py`：case 数据
- `test_*_regression.py`：参数化测试
- `helpers.py`：构造 memory、run flow、run guard 等辅助函数

这部分是 guard 和 memory 的核心回归护栏。

## docs 的组织方式

当前 `docs/` 分两类：

### 维护者入口文档

- `00_product_overview.md`
- `01_repo_guide.md`
- `02_dev_onboarding.md`
- `03_architecture_debt_register.md`
- `README_docs_index.md`

### 专题/阶段性文档

- `01_prd_v0.1.md`
- `02_persona.md`
- `03_memory_design.md`
- `04_dialogue_policy.md`
- `05_architecture.md`
- `06_mvp_demo_implementation_guide.md`
- `07_observability_guide.md`
- `08_eval_framework_guide.md`
- `09_memory_reply_guard_v0.1.md`
- `10_memory_reply_guard_v0.2.md`
- `11_reply_guard_regression_hardening.md`
- `13_assist_llm_lane.md`
- `14_memory_schema_v0.2.md`
- `15_session_consolidation_min_loop.md`
- `16_startup_memory_usage.md`
- `17_voice_cli_usage.md`
- `18_repo_structure_review_report.md`

建议先读新的维护者入口文档，再按主题查旧文档。

## 最值得先读的 Top 15 文件

1. `src/app/main.py`
2. `src/app/runtime.py`
3. `src/app/main_voice.py`
4. `src/app/coordinator.py`
5. `src/dialogue/engine.py`
6. `src/dialogue/prompt_builder.py`
7. `src/dialogue/reply_guard/service.py`
8. `src/memory/manager.py`
9. `src/memory/rules.py`
10. `src/memory/store.py`
11. `src/voice/controller.py`
12. `src/assist_llm/service.py`
13. `src/observability/trace_admin.py`
14. `tests/test_dialogue_pipeline.py`
15. `tests/regression/test_reply_guard_regression.py`

## 推荐阅读顺序

### 第一次进入仓库

1. `docs/00_product_overview.md`
2. `docs/01_repo_guide.md`
3. `docs/02_dev_onboarding.md`
4. `README.md`
5. `src/app/main.py`
6. `src/app/runtime.py`
7. `src/app/coordinator.py`
8. `src/dialogue/engine.py`

### 想改 memory

1. `docs/03_memory_design.md`
2. `src/memory/models.py`
3. `src/memory/manager.py`
4. `src/memory/rules.py`
5. `src/memory/writer.py`
6. `src/memory/reader.py`
7. `src/memory/store.py`
8. `tests/test_memory_*`
9. `tests/regression/test_memory_*`

### 想改 reply guard

1. `docs/11_reply_guard_regression_hardening.md`
2. `src/dialogue/reply_guard/models.py`
3. `src/dialogue/reply_guard/checks.py`
4. `src/dialogue/reply_guard/classify.py`
5. `src/dialogue/reply_guard/actions.py`
6. `src/dialogue/reply_guard/service.py`
7. `src/dialogue/engine.py`
8. `tests/regression/test_reply_guard_*`

### 想改 assist-llm

1. `docs/13_assist_llm_lane.md`
2. `src/assist_llm/tasks.py`
3. `src/assist_llm/prompts.py`
4. `src/assist_llm/service.py`
5. `src/dialogue/reply_guard/service.py`
6. `src/dialogue/engine.py`
7. `tests/test_assist_llm_*`

## 哪些模块耦合较高，改动要小心

- `src/dialogue/engine.py`
  - 它同时知道 prompt、LLM、postprocess、guard、assist retry。
- `src/app/coordinator.py`
  - 它串了 history、engine、memory write、follow-up scan、日志。
- `src/dialogue/reply_guard/service.py`
  - 它既调用 checks/classify/actions，又和 assist-llm 交叉。
- `src/memory/rules.py`
  - 它同时影响 write candidate、retrieve relevance、merge、summary。
- `src/memory/store.py`
  - 它不只是 CRUD，还承担迁移责任。

这些地方一改，最容易连带打坏 regression。

## 哪些模块是预留接口 / 暂未完全接线

### 明确预留

- `src/storage/db.py`
- `src/storage/models.py`
- `src/storage/repositories.py`

当前是未来非 memory 持久化的命名空间；主项目真实 memory SQLite 实现仍在 `src/memory/store.py`。这些文件保留但不代表已有第二套数据库抽象。

### 未来调度 lane

- `src/scheduler/proactive.py`
- `src/scheduler/reminder.py`

当前 scheduler 只处理 explicit follow-up candidate。proactive 和 reminder lane 是预接口，保留但不进入运行时。

### 已实装但仍偏重

- `src/memory/decay.py`
- `src/memory/summarizer.py`
- `src/memory/store.py`
- `src/memory/manager.py`
- `src/dialogue/engine.py`

这些是当前主路径的一部分，不应按“空占位”理解。后续适合做低风险内部减重，而不是重写。

### assist-llm 部分接线

- `AssistLLMService.review_pending_memory_note()`
- `AssistLLMService.summarize_episodic_merge()`

当前能在 service 和 tests 中看到，但还没有稳定 CLI / runtime 入口。

### 待确认的概念重叠

- `src/evals/` 与 `tests/regression/`

二者都服务开发验证，但定位不完全一样：

- `src/evals/` 更像独立 eval runner
- `tests/regression/` 更像 pytest 回放护栏

后续可以再统一说明，但当前不要假设它们是重复无用代码。

## 外部参考项目边界

- `memory_selection/` 和 `Neuro/` 是本地参考资料，不进入默认 pytest。
- 全局搜索主项目时建议排除它们：`rg <pattern> src tests docs scripts --glob '!memory_selection/**' --glob '!Neuro/**'`。
- 不要从这些目录直接引入 runtime 依赖；如果要吸收设计，先落成主项目内的文档或受测模块。
