# Eval Framework Guide

## 1. 目标

这套 eval 不是为了做华丽指标看板，而是为了尽快回答两个问题：

- memory 有没有写错、读偏、越界注入
- guard 有没有把回复风格拉回到可信范围

所以这里分成两层：

- `unittest`：保留已有的规则级 smoke tests，跑得快，适合日常改动后快速确认主链路没坏
- `pytest regression`：用更接近真实对话的 case 回放 memory / guard / flow 行为

## 2. 运行方式

### 2.1 运行 pytest regression

```powershell
uv run --with pytest --python 3.12 --no-project pytest -q
```

这会覆盖：

- `tests/regression/cases_memory_write.py`
- `tests/regression/cases_memory_retrieve.py`
- `tests/regression/cases_reply_guard.py`
- `tests/regression/cases_conversation_flow.py`
- memory merge / follow-up adapter / command router 的专项测试

### 2.2 运行原有 unittest smoke

```powershell
uv run --python 3.12 --no-project python -m unittest discover -s tests -v
```

说明：

- 这个命令仍然适合快速确认旧主链路
- regression pytest 模块在没有 pytest 时会被标记为 `skipped`，不会把 smoke 命令打坏

## 3. regression case 结构

每条 case 至少包含这些字段：

- `case_id`
- `input_history`
- `user_input`
- `existing_memories`
- `expected_write_candidates`
- `expected_injected_memory_ids`
- `expected_guard_flags`
- `expected_behavior_notes`

不同测试可以只消费其中一部分字段。

## 4. 当前覆盖面

### 4.1 memory write

- 显式称呼偏好
- 互动方式讨厌 / 偏好
- 长期喜欢话题
- 普通寒暄不写入
- 低信息量抱怨不写入
- 近期项目推进
- 显式 follow-up
- 持续情绪状态

### 4.2 memory retrieve

- 项目相关 episodic 命中
- 称呼偏好 profile 命中
- 无关输入不强注
- 注入条数上限
- 过期 episodic 过滤
- 低置信度 profile 过滤
- 同主题重复项去重
- 空 store 正常退化

### 4.3 reply guard

- AI 自我声明
- 假记忆
- comfort 场景过度说教
- casual chat 模板化长回复
- correction 场景过软
- 过长重复
- forbidden style

### 4.4 conversation flow

- memory 命中正常通过
- memory 未命中正常通过
- 轻度 rewrite
- 中度 retry once
- 重度 safe fallback

## 5. 为什么这轮先做 regression eval

因为 memory / reply guard 最大的问题从来不是“规则有没有写出来”，而是：

- 真实输入稍微一变，行为会不会跑偏
- 一次修复会不会破坏别的场景
- 我们能不能快速知道是写入、检索、guard，还是整条链路出了问题

所以 case 数据和测试逻辑必须分离，才能持续追加样例，而不是把经验埋在一堆测试函数里。
