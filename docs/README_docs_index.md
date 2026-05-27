# Project Serina Docs Index

## 当前现状入口（推荐新维护者先读）

这些文档描述代码的**当前事实**，而非历史设计：

1. [产品说明书](00_product_overview.md) —— 当前能做什么、不能做什么、设计原则
2. [仓库导览](01_repo_guide.md) —— 目录结构、关键模块一句话职责、推荐阅读顺序
3. [开发者上手](02_dev_onboarding.md) —— 环境准备、启动方式、测试命令、最小开发闭环
4. [语音 CLI 使用说明](17_voice_cli_usage.md) —— 语音入口的运行形态、配置、限制
5. [语音记忆开发者指南](voice_memory_developer_guide.md) —— 语音子系统开发教程
6. [语音记忆 Demo 使用说明](voice_memory_demo_usage.md) —— 一键启动 Demo 的操作指南

## 运行时与验证

- [架构概述](05_architecture.md) ⚠️ v0.1 历史叙事，当前事实以上方入口文档为准
- [记忆系统设计](03_memory_design.md) —— 设计原则，已与 v0.2 实现基本一致
- [对话策略](04_dialogue_policy.md) —— 8 类场景的回复策略规则
- [可观测性](07_observability_guide.md) —— debug trace 配置、日志格式、隐私边界
- [评测/回归指南](08_eval_framework_guide.md) —— 两层评测体系与 case 结构
- [回复护栏回归加固](11_reply_guard_regression_hardening.md) —— 稳定的 violation taxonomy 与 action 决策规则
- [辅助 LLM 通道](13_assist_llm_lane.md) —— 受控白名单任务、安全约束、可观测字段
- [Memory Schema v0.2](14_memory_schema_v0.2.md) —— memory_class / representation / preference / 冲突机制
- [会话合并闭环](15_session_consolidation_min_loop.md) —— session → 长期记忆的最小提升闭环
- [启动记忆使用](16_startup_memory_usage.md) —— 跨会话连续性层的配置与验证方式

## 设计迭代与历史记录

- [PRD v0.1](01_prd_v0.1.md) ⚠️ 产品边界定义，当前实现已超出此范围
- [人格定义](02_persona.md) —— Serina 的可执行人格模型
- [MVP Demo 实现说明](06_mvp_demo_implementation_guide.md) ⚠️ v0.1 最小 Demo 的源码导览
- [Memory + Reply Guard v0.1](09_memory_reply_guard_v0.1.md) —— 首次接入 memory 和 guard 的设计记录
- [Memory + Reply Guard v0.2](10_memory_reply_guard_v0.2.md) —— v0.2 迭代的优先顺序与新增能力
- [语音+记忆迁移方案](voice_memory_migration_plan.md) ✅ 已执行完毕，保留为实现记录

## 治理与审查

- [架构债登记册](03_architecture_debt_register.md) —— P0/P1/P2 技术债清单与测试覆盖盲区
- [仓库结构审查报告](18_repo_structure_review_report.md) —— 2026-04-27 静态结构审查
- [文档沉淀报告](DOCS_REVIEW_REPORT.md) —— 2026-05-27 全部 25 篇文档的总结、改进建议与评测用例统计

## 边界说明

- 语音模式是可选的。`src/app/main.py` 仍然是文本 CLI 入口。
- 语音 Demo 使用 my-neuro ASR（端口 1000）和 GPT-SoVITS v2（端口 5000）。当前本地默认语音配置使用 sherpa-onnx SenseVoice + CosyVoice，详见 `voice_config.yaml`。
- 短期记忆在 `Coordinator.session.history` 中；长期记忆在 SQLite 中。
- 本地配置文件可能包含本地私有的 API key。如需发布仓库，需先做密钥迁移。

## 最近更新

- 2026-05-27：4 篇英文文档翻译为中文（13/15/16/17）；`05_architecture.md` 加 v0.1 叙事标注；`00_product_overview.md` 修正 decay.py/summarizer.py 状态描述；`voice_memory_migration_plan.md` 标记为已执行；删除冗余 `example.json`；新增 `DOCS_REVIEW_REPORT.md`

---

新增或修改文档时，请同步更新此索引。
