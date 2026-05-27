# 启动记忆与会话合并使用指南

## 新增了什么

本次更新在现有记忆系统之上增加了一个轻量的跨会话连续性层。

目标不是重放完整历史。目标是让新窗口恢复少量高价值上下文，使助手能够自然地继续对话。

新的流程是：

1. session memory 仍然在每轮对话中写入。
2. 在会话退出时，应用运行一次小型最终合并步骤。
3. 高价值条目被提升为跨会话可见的长期记忆。
4. 最后一条会话摘要被写入会话连续性账本。
5. 在新会话的前 1-2 轮中，应用可以构建启动记忆包。
6. 如果用户以续接线索开头（如"继续"或"上次那个问题"），启动检索会优先处理开放循环、近期事件上下文和最后会话摘要。

## 记忆层级

启动记忆包从四个逻辑来源组装：

- Profile memory：稳定的偏好和用户背景。
- 近期 episodic memory：近期高价值摘要，适合跨会话呈现。
- 开放循环：活跃的 task 型记忆或未完成的承诺。
- 最后会话摘要：一条来自前一个会话连续性账本的简短摘要。

只有跨会话可见的长期记忆才有资格进入启动记忆包。

## 提升规则

长期记忆现在有两个额外字段：

- `cross_session_visible`
- `last_used_at`

默认情况下，`cross_session_visible` 对以下类型为 true：

- profile / preference 记忆
- task / follow-up 记忆
- session 合并后的 episodic 摘要

这使随机会话碎片远离启动检索，同时仍然呈现有用的延续信息。

## 启动记忆包何时构建

启动检索仅在配置的启动轮次窗口内活跃。

默认运行时配置：

- `startup_memory_enabled: true`
- `startup_memory_turn_window: 2`
- `startup_memory_profile_limit: 2`
- `startup_memory_episodic_limit: 2`
- `startup_memory_open_loop_limit: 2`
- `startup_memory_summary_limit: 1`
- `startup_memory_total_limit: 6`

实际上这意味着：

- 新窗口第一轮：启动检索可以运行
- 新窗口第二轮：启动检索仍然可以运行
- 后续轮次：应用回退到正常的基于查询的检索

## 续接线索检测

启动检索器使用一个小型启发式线索检测器。

触发启动优先路径的示例：

- `继续`
- `我们继续`
- `上次那个问题`
- `那然后呢`
- `刚刚那个`
- `接上次`

普通问候如`你好`不会触发续接优先级。

## Prompt 注入风格

启动上下文被注入到专用的 `continuing_context` prompt 块中。

该块明确告知模型：

- 这不是完整的聊天历史
- 这些只是有限的连续性提示
- 如果不确定，不要过度声称记忆

常规查询记忆仍然通过正常的 `memory_context` 块。
重复的启动片段会从正常记忆块中移除，确保同一信息不会被注入两次。

## 会话最终化

CLI 退出时，应用现在会调用 `Coordinator.finalize_session()`。

该最终化步骤：

1. 运行一次有界的合并通道
2. 收集已提升的记忆 id
3. 提取开放循环 id
4. 构建最终会话摘要
5. 将摘要和元数据写回 `session_continuity_entries`

这是一个同步的、有界的步骤。没有 scheduler，没有后台 worker。

## 如何检查

### 检查 SQLite 存储

默认存储位置：

- `data/serina.db`

相关表：

- `memory_entries`
- `session_memory_entries`
- `session_continuity_entries`

值得检查的列：

- `memory_entries.cross_session_visible`
- `memory_entries.last_used_at`
- `session_continuity_entries.summary_text`

### 检查启动检索元数据

Coordinator 现在在每轮结果上暴露以下结构化字段：

- `startup_memory_pack_present` —— 启动记忆包是否存在
- `startup_memory_pack_count` —— 包中条目数
- `startup_memory_memory_ids` —— 记忆 id 列表
- `startup_memory_categories` —— 类别分布
- `continuation_cue_detected` —— 是否检测到续接线索
- `last_session_summary_used` —— 是否使用了最后会话摘要
- `retrieval_mode` —— 检索模式（`startup` 或 `query`）

如果启用了 file logging 或 debug trace，相同的元数据也会写入可观测性日志。

## 如何运行

### 确定性测试

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.uv-python'
uv run --python 3.12 --no-project python -m unittest discover -s tests -v
```

### 完整 pytest 回归

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.uv-python'
uv run --with pytest --python 3.12 --no-project pytest -q tests
```

### 已有冒烟评测

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.uv-python'
uv run --python 3.12 --no-project python -m src.evals.run_eval --mode mock --suite smoke
```

### 启动连续性评测套件

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.uv-python'
uv run --python 3.12 --no-project python -m src.evals.run_eval --mode mock --cases evals/cases/startup_continuity_cases.jsonl
```

## 推荐的手工验证方式

1. 启动 CLI。
2. 提到一个真实的进行中任务或 follow-up 承诺。
3. 用 `exit` 干净地退出 CLI。
4. 在新窗口中重新启动 CLI。
5. 第一条消息：`继续` 或 `上次那个问题我们接着来`。

预期行为：

- 新会话不应表现得像完全失忆
- 启动检索应被标记为 `startup`
- 只应注入少量摘要
- 助手听起来应像有有限的连续性，而非完整的历史重放

## 如何重置数据

### 重置主记忆数据库

删除：

- `data/serina.db`

### 重置仅评测用的测试记忆

删除以下路径中每次运行生成的 SQLite 文件：

- `artifacts/evals/`

### 重置临时测试工作区

删除：

- `.tmp_test_workspaces/`

## 注意事项

- 启动连续性是故意以摘要为主的。
- 应用仍然不假装拥有完整的历史回忆能力。
- 本实现中没有向量搜索、scheduler 或后台摘要循环。
