# Project Serina 开发者上手文档

## 这份文档适合谁

这份文档默认读者就是未来几天后回来的项目作者本人。

目标很简单：

- 能把项目跑起来
- 能看懂日志和 trace
- 能用 memory / trace CLI
- 能跑测试
- 能完成一次最小开发闭环

## 0. 先知道几件事

- 当前入口是 CLI，不是 GUI。
- 当前默认 provider 是 DeepSeek。
- 当前配置文件在 `src/config/`。
- 当前 memory store 默认是 SQLite，路径是 `data/serina.db`。
- 当前 trace file logging 默认关闭；不开启时，`/trace` 和 `/badcase` 最好手动传 `--file`。
- 当前语音 CLI 入口是 `src/app/main_voice.py`，并复用文本主链路。
- 当前 `memory_selection/` 和 `Neuro/` 是外部参考资料，不属于默认测试边界。

## 1. 环境准备

### 推荐环境

- Windows / PowerShell 或 Anaconda Prompt
- Python 3.12
- 可选：`uv`
- 推荐：`pytest`
- 推荐：`PyYAML`
- 语音测试推荐：`numpy`

### 为什么说 `PyYAML` 是可选

`src/config/loader.py` 里带了一个最小 YAML fallback parser。

这意味着：

- 没装 `PyYAML`，配置通常也能读
- 但为了减少边界问题，开发时仍建议装 `PyYAML`

## 2. 安装依赖

当前仓库使用 `pyproject.toml` 作为最小依赖和 pytest 配置入口。

### 最小推荐安装

```powershell
python -m pip install pyyaml pytest numpy
```

如果你使用 `uv`，可以直接按仓库里现在常用的方式跑，不一定要先固定装本地依赖。

```powershell
uv run --with pytest --with pyyaml --with numpy --python 3.12 --no-project pytest -q
```

## 3. 配置文件位置

配置都在 `src/config/`：

- `src/config/persona_config.yaml`
- `src/config/policy_config.yaml`
- `src/config/runtime_config.yaml`
- `src/config/voice_config.yaml`
- `src/config/voice_profiles.yaml`
- `src/config/local_tts_runtime.yaml`

### 最关键的配置项

#### provider / model

- `provider`
- `model`
- `reasoner_model`
- `base_url`
- `api_key_env`
- `api_key`

当前项目按本地私有配置使用，inline key 保持不变；如果未来要上传远端，再单独做密钥迁移。

#### memory

- `memory_enabled`
- `memory_write_enabled`
- `memory_store_type`
- `memory_store_path`
- `max_memory_injection_items`
- `episodic_memory_ttl_days`
- `merge_time_window_hours`
- `memory_review_enabled`

#### reply guard

- `reply_guard_enabled`
- `reply_guard_retry_once`
- `max_reply_chars`
- `max_reply_chars_soft_limit`

#### assist-llm

- `assist_llm_enabled`
- `assist_llm_runtime_model`
- `assist_llm_dev_model`
- `assist_llm_timeout_ms`
- `assist_llm_max_runtime_calls_per_turn`
- `assist_llm_enable_guard_retry_rewrite`
- `assist_llm_enable_memory_reference_check`
- `assist_llm_enable_trace_summary`
- `assist_llm_enable_badcase_draft`

#### trace / logging

- `enable_file_logging`
- `log_dir`
- `log_level`
- `debug_trace_enabled`
- `debug_show_prompt_blocks`
- `debug_show_messages`
- `debug_cli_diagnostics_enabled`

## 4. 启动方式

### 从仓库根目录启动

推荐：

```powershell
python src/app/main.py
```

### 从 `src/app` 目录启动

也可以：

```powershell
cd src/app
python main.py
```

`main.py` 已经做了 `sys.path` 处理，所以这两种方式都能工作。

## 5. 常见运行模式

### 模式 A：普通 CLI 聊天

```powershell
python src/app/main.py
```

适合：

- 手工试玩
- 看主链路是否还通
- 感受 reply guard 有没有明显跑偏

### 模式 B：打开 file logging，看 trace

先在 `src/config/runtime_config.yaml` 里确认：

```yaml
enable_file_logging: true
log_dir: data/logs
```

然后再启动：

```powershell
python src/app/main.py
```

这样每次启动都会在 `data/logs/` 生成新的 `serina_trace_*.jsonl`。

### 模式 C：独立 eval

```powershell
python scripts/run_eval.py --mode mock
```

如果想带 trace artifact：

```powershell
python scripts/run_eval.py --mode mock --debug
```

默认 built-in suite 在：

- `evals/cases/smoke_cases.jsonl`

## 6. 如何查看日志 / trace

### 普通日志

控制台日志由 `src/utils/logger.py` 配置。

你会在控制台看到：

- 普通 info/error 日志
- 如果开了 `debug_trace_enabled`，还会看到 JSON 事件

### trace 文件

如果 `enable_file_logging: true`，trace 会写到：

- `data/logs/serina_trace_*.jsonl`

trace 里重点关注这些事件：

- `turn_received`
- `prompt_package_built`
- `llm_gateway_call_started`
- `postprocess_completed`
- `reply_guard_checked`
- `reply_guard_retry_completed`
- `reply_guard_assist_retry_completed`
- `dialogue_completed`
- `memory_retrieval_completed`
- `memory_write_completed`
- `followup_candidate_scan_completed`

### 重点字段

reply guard：

- `reply_guard_initial_action`
- `reply_guard_final_action`
- `reply_guard_initial_violations`
- `reply_guard_violations`
- `reply_guard_fallback_reason`

assist：

- `assist_llm_task`
- `assist_llm_success`
- `assist_llm_error_type`
- `assist_llm_pre_guard_action`
- `assist_llm_post_guard_action`

memory：

- `memory_selected_ids`
- `memory_written_ids`

## 7. 如何使用 memory CLI

启动 CLI 后，可以直接输入：

### 查看

```text
/memory list
/memory list profile
/memory list episodic active
/memory list archived
```

### 管理

```text
/memory archive <id>
/memory delete <id>
/memory expire <id>
/memory pin <id>
/memory unpin <id>
/memory update <id> content="..." confidence=0.95
```

这套命令路径是：

`CommandRouter -> MemoryAdminService -> MemoryManager -> SQLiteMemoryStore`

## 8. 如何使用 trace summary / badcase draft

### trace summary

```text
/trace summary --file data/logs/serina_trace_xxx.jsonl --limit 12
```

也可以按事件过滤：

```text
/trace summary --file data/logs/serina_trace_xxx.jsonl --event reply_guard_checked
```

### badcase draft

```text
/badcase draft latest --file data/logs/serina_trace_xxx.jsonl
/badcase draft <turn_id> --file data/logs/serina_trace_xxx.jsonl
```

### 如果不写 `--file`

系统会按下面顺序找 trace：

1. 当前 logger 记录的 trace file
2. `runtime.log_dir` 下最新的 `serina_trace_*.jsonl`

前提是 file logging 开着，或者目录里本来就有旧 trace 文件。

### fallback 行为

如果 assist-llm 不可用：

- `/trace summary` 会退回规则摘要
- `/badcase draft` 会退回规则化 JSON payload

## 9. 如何跑测试

### 全量 pytest regression + 其他 pytest tests

```powershell
uv run --with pytest --with pyyaml --with numpy --python 3.12 --no-project pytest -q
```

如果你本地已经装了 pytest，也可以直接：

```powershell
pytest -q
```

默认 pytest 收集范围由 `pyproject.toml` 限定到 `tests/`，不会进入 `memory_selection/` 或 `Neuro/`。

### unittest smoke

```powershell
uv run --python 3.12 --no-project python -m unittest discover -s tests -v
```

或本地环境直接：

```powershell
python -m unittest discover -s tests -v
```

## 10. 如何只跑某一类测试

### 只跑 memory 相关

```powershell
pytest tests/test_memory_writer.py tests/test_memory_reader.py tests/test_memory_merge.py -q
pytest tests/regression/test_memory_write_regression.py tests/regression/test_memory_retrieve_regression.py -q
```

### 只跑 reply guard 相关

```powershell
pytest tests/test_reply_guard.py tests/regression/test_reply_guard_regression.py tests/regression/test_reply_guard_actions.py tests/regression/test_reply_guard_false_positive.py -q
```

### 只跑 assist-llm 相关

```powershell
pytest tests/test_assist_llm_service.py tests/test_assist_llm_runtime.py -q
```

### 只跑 migration / command router

```powershell
pytest tests/test_memory_store_migration.py tests/test_command_router.py -q
```

### 只跑独立 eval

```powershell
python scripts/run_eval.py --mode mock
```

## 11. 如何验证一次小改动没有把系统搞坏

如果你只是改了一个小点，不需要每次都跑所有东西。推荐这个最小闭环：

1. 跑对应模块的单测。
2. 跑一组相关 regression。
3. 跑 `tests/test_dialogue_pipeline.py`。
4. 手工启动一次 CLI，走一轮真实对话。
5. 如果改到了日志 / guard / assist，再看一次 trace。

### 具体建议

- 改 memory 规则：
  - `tests/test_memory_writer.py`
  - `tests/test_memory_reader.py`
  - `tests/test_memory_merge.py`
  - `tests/regression/test_memory_*`
- 改 guard：
  - `tests/test_reply_guard.py`
  - `tests/regression/test_reply_guard_*`
  - `tests/test_dialogue_pipeline.py`
- 改 assist：
  - `tests/test_assist_llm_service.py`
  - `tests/test_assist_llm_runtime.py`
  - `tests/test_command_router.py`
- 改 store / migration：
  - `tests/test_memory_store_migration.py`
  - `tests/test_memory_reader.py`

## 12. 提交前 checklist

- 主链路还能正常聊天。
- 没把 `/memory`、`/trace`、`/badcase` 命令打坏。
- 相关单测和 regression 已通过。
- 没新增未经控制的 runtime LLM 调用。
- 没绕过 reply guard。
- 没把 dev-only 输出混到用户回复里。
- 如果改了 memory store，确认旧库还能启动。
- 如果改了 docs，确认写的是“当前事实”，不是“未来计划”。

## 13. 新人第一次应该做什么

### 应该做

1. 先读：
   - `docs/00_product_overview.md`
   - `docs/01_repo_guide.md`
   - `docs/03_memory_design.md`
   - `docs/11_reply_guard_regression_hardening.md`
2. 跑一次 CLI。
3. 跑一次 `tests/test_dialogue_pipeline.py`。
4. 跑一次 reply guard regression。
5. 看一眼 `src/dialogue/engine.py` 和 `src/memory/manager.py`。

### 不应该做

- 不要一上来改 `DialogueEngine` 大段流程。
- 不要把 assist-llm 扩成自由 loop。
- 不要把 memory 当聊天缓存加大量写入。
- 不要在没看 regression 的情况下直接改 reply guard 规则。
- 不要假设 `src/storage/` 这类目录已经真的在运行。

## 14. 第一次最值得做的小练习

如果你要重新熟悉项目，推荐做一个小练习：

1. 启动 CLI。
2. 输入一条会写入 profile memory 的偏好句。
3. 用 `/memory list` 确认写入。
4. 再输入一条会触发 reply guard rewrite 或 retry 的句子。
5. 打开 trace，观察：
   - `reply_guard_initial_action`
   - `reply_guard_final_action`
   - `reply_guard_initial_violations`
   - `assist_llm_task` 是否出现
6. 最后运行 `/badcase draft latest --file ...` 看 badcase 草稿。

做完这一步，你就基本把：

- 主链路
- memory
- guard
- assist
- trace

五个核心系统重新走通了一遍。
