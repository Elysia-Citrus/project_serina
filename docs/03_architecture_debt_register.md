# Project Serina 架构债登记册

## 这份文档怎么用

这不是重构方案，也不是拍板文档。

它只做三件事：

1. 记录当前代码里真正存在的结构债和理解债。
2. 说明这些问题的影响。
3. 给出“整理方向”级别的建议，方便后续排优先级。

下面所有条目都尽量区分：

- 当前代码事实
- 影响
- 建议方向

不会把“未来想做的理想设计”伪装成“现在已经实现”。

## P0：高优先级债

### 1. 本地配置与远端发布边界需要显式标注

- 问题  
  `src/config/runtime_config.yaml` 和 `src/config/voice_config.yaml` 当前是本地私有运行配置，允许保留 inline key。这个选择对本地项目可接受，但必须和“可上传远端的默认配置”区分开。
- 影响  
  如果未来要上传远端或开放仓库，维护者必须先做密钥迁移；否则本地配置形态会被误当成可发布形态。
- 建议方向  
  当前保持 key 不变，只在 README 和 onboarding 中写清“本地私有配置”。未来若发布，再另做 env/template 迁移。

### 2. `DialogueEngine` 负担过重

- 问题  
  `src/dialogue/engine.py` 当前同时负责 scene 后的主流程编排、primary generation、postprocess、reply guard、assist retry、retry prompt rebuild、fallback 收束与日志。
- 影响  
  这是当前最容易被误改的高耦合文件。任何对 guard / assist / prompt / gateway 的改动，都可能在这里连锁影响别的路径。
- 建议方向  
  未来可以在不打散边界的前提下，把“主调用流程”和“guard retry 分支”再整理成更清晰的局部 helper，但前提是先保 regression 护栏，不要盲拆。

### 3. migration 仍是隐式补列，没有 schema version

- 问题  
  `src/memory/store.py` 现在通过 `_ensure_columns()` 和 `_ensure_indexes()` 做增量迁移，能修复旧库缺列问题，但没有 schema version、没有迁移序列管理。
- 影响  
  对当前简单场景够用，但后续如果出现字段重命名、数据修复、非加列式迁移，就容易失控。
- 建议方向  
  后续如果 memory store 继续演进，优先补一个极轻量的 schema version 机制，不需要上完整 migration framework。

### 4. runtime path 与 dev-only path 的边界主要靠“理解”，不是靠结构显眼性

- 问题  
  现在虽然代码上已经区分了普通聊天路径和 `/memory`、`/trace`、`/badcase` 这些命令路径，但这种边界主要分散在 `main.py`、`command_router.py`、`trace_admin.py`、`assist_llm/service.py` 中。
- 影响  
  新维护者容易把开发期辅助能力误当成主链路的一部分，或者误把 dev 输出混进 runtime reply path。
- 建议方向  
  先靠文档和 docs index 固化边界；后续如果命令继续增多，再考虑更明确的“runtime vs dev tool”目录或命名约定。

### 5. 一部分 assist task 已定义，但产品入口不完整

- 问题  
  从代码扫描看，assist task 一共有 6 类，但真正稳定接线的主要是：
  - runtime：`guard_retry_rewrite`、`optional_memory_reference_check`
  - dev CLI：`summarize_trace_cluster`、`draft_badcase_case`
  `review_pending_memory_note`、`summarize_episodic_merge` 目前主要存在于 service 和 tests 中。
- 影响  
  如果只看 `src/assist_llm/`，容易误以为所有 task 都已经进入稳定开发工作流。
- 建议方向  
  后续要么给这些 task 明确入口，要么在文档里持续标“部分实现 / 仅 service 级可用”，避免误读。

## P1：中优先级债

### 6. `src/storage/` 是预留持久化命名空间

- 问题  
  `src/storage/db.py`、`src/storage/models.py`、`src/storage/repositories.py` 当前是预留接口；真实 memory SQLite 实现仍在 `src/memory/store.py`。
- 影响  
  如果没有说明，维护者容易误以为这里已有另一套 store 抽象。
- 建议方向  
  已补最小模块说明。后续只有在引入跨域存储抽象时才从这里接线。

### 7. scheduler 预留 lane 与 memory 已实装模块容易混读

- 问题  
  `src/scheduler/proactive.py`、`src/scheduler/reminder.py` 是预留 lane；`src/memory/decay.py`、`src/memory/summarizer.py` 已有实装，不能继续按空占位理解。
- 影响  
  容易把已进入主路径的 memory 维护逻辑和未接线的 scheduler 未来 lane 混在一起。
- 建议方向  
  已在 repo guide 和模块 docstring 中标注。后续减重应优先针对 memory 已实装模块，而不是删除预留 lane。

### 8. `src/evals/` 与 `tests/regression/` 存在概念重叠

- 问题  
  两套系统都在服务验证：
  - `src/evals/` 是独立 eval runner
  - `tests/regression/` 是 pytest 回放护栏
- 影响  
  新维护者容易分不清“什么时候跑 eval，什么时候跑 regression”，也容易在两个地方重复沉淀样例。
- 建议方向  
  当前先在 onboarding 和 repo guide 中明确分工。后续如果继续积累评测能力，再考虑是否统一 case 来源或输出格式。

### 9. `CommandRouter` 继续长大会变成 if-else 集中地

- 问题  
  现在 `CommandRouter` 已经负责三类命令：
  - `/memory`
  - `/trace`
  - `/badcase`
- 影响  
  目前规模还可控，但如果再加更多开发命令，这里很容易变成新的耦合点。
- 建议方向  
  短期继续保持就好；若命令继续增长，可以再拆成 `memory_commands.py`、`trace_commands.py` 这类小模块，但现在不必提前设计。

### 10. scheduler 名称容易让人误判成熟度

- 问题  
  当前 `SchedulerManager` 和 `FollowUpSchedulerAdapter` 名字听起来像完整调度系统，但实际上只做 candidate 扫描。
- 影响  
  容易让维护者高估它的真实能力，误以为已经存在主动 follow-up 执行链。
- 建议方向  
  后续要么补真正 consumer，要么在文档和命名上持续强调“candidate adapter only”。

### 11. 依赖清单刚建立，需要持续维护

- 问题  
  仓库已经有 `pyproject.toml`，但语音 runtime 依赖仍有平台差异，后续新增依赖时容易忘记同步 extras。
- 影响  
  新环境启动体验已经改善，但 voice 运行依赖仍需要维护者按平台验证。
- 建议方向  
  新增测试或 voice/runtime 依赖时同步更新 `pyproject.toml`、README 和 onboarding。

## P2：较低优先级债

### 12. 旧文档很多，但缺统一入口

- 问题  
  `docs/` 里已有很多专题文档，但在新增维护者入口文档之前，缺少统一索引与阅读顺序说明。
- 影响  
  回来维护时会先被文档数量淹没，不知道先看哪份。
- 建议方向  
  这轮通过 `README_docs_index.md` 已经缓解，但后续仍需要保持索引持续更新，否则很快再次失效。

### 13. 中文在当前终端环境里存在显示乱码风险

- 问题  
  在当前 Windows/PowerShell 环境里，一部分中文输出存在乱码现象。  
  待确认：这是文件编码问题，还是终端 code page / 字体问题。
- 影响  
  会影响日志排查和文档阅读体验，也可能误导维护者判断“代码里字符串坏了”。
- 建议方向  
  后续可单独做一次编码检查：统一 UTF-8、确认编辑器和终端设置，并写进 onboarding。

### 14. `memory_snippets` 仍保留了一条非标准旁路入口

- 问题  
  `DialogueEngine.generate_reply()` 允许直接传 `memory_snippets`，从而绕过正常 `MemoryManager.retrieve()`。
- 影响  
  这对测试和局部注入有用，但如果后续被随意扩用，容易让主路径和测试路径的行为偏离。
- 建议方向  
  暂时保留，但在文档里明确它不是普通 runtime 路径；后续若继续保留，应补更清晰注释或测试说明。

## 测试覆盖盲区

### 已有较好覆盖

- memory write / retrieve / merge
- memory store migration
- reply guard regression / false positive / actions
- assist-llm runtime / service
- command router
- dialogue pipeline smoke
- follow-up adapter

### 仍偏弱或待补的区域

- `main.py` 的真实 CLI loop 没有端到端自动测试。
- live provider 路径没有稳定自动化测试，主要还是 mock 和手工验证。
- trace file logging 的真实文件生命周期没有更完整的回归。
- `review_pending_memory_note`、`summarize_episodic_merge` 只有 service/tests，没有完整工作流回归。
- 占位/待确认模块没有测试，这本身也说明它们未进入稳定主路径。

## 文档与实现不一致风险

### 已经明确修正的点

- 普通主链路不应写成“直接 UI -> Coordinator”，因为 `/memory`、`/trace`、`/badcase` 先经过 `CommandRouter`。
- 主链路里 `scene inference` 发生在 memory retrieval 前，而不是之后。
- assist-llm 不是纯 dev tool，也不是默认主路径，而是 “dev tool + runtime helper” 双角色。

### 仍需持续小心的点

- 旧文档可能默认按阶段设计写得更理想化，而当前代码是更保守的落地版。
- 对空文件、占位模块、未接线 task 的描述必须坚持写“待确认/部分实现”，不能替它们补故事。

## 未来整理优先级建议

### P0

- 配置与密钥管理收敛
- `DialogueEngine` 可读性整理
- store schema version / migration 规范化

### P1

- 明确空目录 / 占位模块命运
- 统一 eval 与 regression 的分工说明
- 给 scheduler 补更明确的能力命名或消费路径

### P2

- 统一依赖清单
- 编码/终端体验整理
- 持续维护 docs index

## 最后一句提醒

当前最危险的不是“系统还不够强”，而是：

> 未来维护者在没搞清主路径和占位路径之前，就开始顺手改高耦合文件。

这份债登记册的目的，就是先把这些坑标出来。
