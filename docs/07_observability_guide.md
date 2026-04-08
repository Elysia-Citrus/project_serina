# Project_Serina v0.2 可观察性说明

## 1. 这次增强做了什么

当前仓库已经加入了一套轻量 observability 方案，目标是：

- 默认运行时尽量安静
- 开启调试后可以追踪完整单轮链路
- 不破坏当前 `UI -> Coordinator -> DialogueEngine -> Gateway -> Provider` 的边界
- 不泄露 API key

当前能观察到的内容包括：

- 原始输入 preview
- 清洗后输入 preview
- scene 识别结果
- prompt block 摘要
- messages 摘要
- provider / model / endpoint
- 模型调用耗时
- 原始输出 preview
- postprocess 后输出 preview
- postprocess 命中的规则
- memory / proactive 未来扩展字段是否出现

---

## 2. 相关配置

这些开关都在：

- `src/config/runtime_config.yaml`

新增字段如下：

- `enable_file_logging`
- `log_dir`
- `debug_trace_enabled`
- `debug_show_scene`
- `debug_show_prompt_blocks`
- `debug_show_messages`
- `debug_cli_diagnostics_enabled`
- `debug_max_preview_chars`

默认值偏保守：

- 控制台不默认刷 trace
- 不默认写文件日志
- prompt / messages 不默认展开

---

## 3. 如何开启 debug trace

最常见的开发调试方式是把这些开关改成下面这样：

```yaml
enable_file_logging: true
log_dir: data/logs
debug_trace_enabled: true
debug_show_scene: true
debug_show_prompt_blocks: true
debug_show_messages: true
debug_cli_diagnostics_enabled: true
debug_max_preview_chars: 160
```

然后正常运行：

```powershell
python src/app/main.py
```

或者：

```powershell
py -3 src/app/main.py
```

---

## 4. 日志会写到哪里

如果：

- `enable_file_logging: true`

那么结构化 trace 会写到：

- `log_dir` 指定目录

默认推荐目录：

- `data/logs`

文件名格式类似：

```text
serina_trace_20260408_121955.jsonl
```

这是 JSONL 文件，也就是：

- 一行一个 JSON 事件
- 很适合后续 grep、过滤、脚本分析

---

## 5. 如何理解一轮 trace

一轮对话会有同一个 `turn_id`。

你可以把一轮典型事件理解成：

1. `turn_received`
2. `input_cleaned`
3. `dialogue_started`
4. `scene_inferred`
5. `prompt_package_built`
6. `prompt_blocks_summary`（如果开启）
7. `prompt_messages_summary`（如果开启）
8. `llm_gateway_call_started`
9. `provider_request_started`
10. `provider_response_received`
11. `llm_gateway_call_completed`
12. `postprocess_completed`
13. `dialogue_completed`
14. `coordinator_history_updated`
15. `turn_completed`

如果出错，则会出现类似：

- `provider_config_error`
- `provider_request_failed`
- `provider_response_invalid`
- `llm_gateway_call_failed`
- `turn_failed`

---

## 6. CLI 开发者诊断信息

如果：

- `debug_cli_diagnostics_enabled: true`

那么 CLI 每轮回复后会额外显示一行简洁诊断，例如：

```text
[debug] > [turn=7f8b491e4f62] [scene=comfort] [history=6] [latency=1320ms]
```

这行信息给开发者看，不属于普通用户 UI。

如果不想看到它，直接关闭：

```yaml
debug_cli_diagnostics_enabled: false
```

---

## 7. 隐私与安全边界

当前实现遵守这些原则：

- 不记录 API key
- 不记录 Authorization header
- endpoint 日志使用安全版本
- 默认只记录 preview，而不是完整长文本
- preview 长度受 `debug_max_preview_chars` 控制

需要注意的是：

- 如果你主动开启 `debug_show_messages`，日志里仍会出现 prompt 和用户输入的摘要内容
- 这是开发调试能力，不适合长期无差别常开

---

## 8. 推荐使用方式

推荐把可观察性分成两种模式：

### 日常使用

```yaml
enable_file_logging: false
debug_trace_enabled: false
debug_show_prompt_blocks: false
debug_show_messages: false
debug_cli_diagnostics_enabled: false
```

### 调试模式

```yaml
enable_file_logging: true
debug_trace_enabled: true
debug_show_prompt_blocks: true
debug_show_messages: true
debug_cli_diagnostics_enabled: true
```

这样可以保持：

- 平时安静
- 出问题时有完整链路可查

