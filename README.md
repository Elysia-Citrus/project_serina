# Project Serina

Project Serina 当前是一个桌面 `agent` 文本聊天原型，目标不是一次性做成“最强系统”，而是先把人格、记忆、回复质量控制做成可信、克制、可回归的基础设施。

当前已完成的主链路：
- CLI 多轮聊天
- `persona / policy / runtime` 三层配置
- `Coordinator / DialogueEngine / PromptBuilder / LLMGateway / Provider` 分层
- `profile_memory / episodic_memory` 两层记忆
- `retrieval -> prompt -> generate -> postprocess -> reply_guard -> write_turn`
- 规则化 memory write / retrieve
- 轻量 reply self-check
- pytest regression eval + unittest smoke tests
- `/memory ...` review / manual override 命令
- explicit follow-up 的 scheduler adapter

推荐先看这些文档：
- [docs/05_architecture.md](docs/05_architecture.md)
- [docs/08_eval_framework_guide.md](docs/08_eval_framework_guide.md)
- [docs/09_memory_reply_guard_v0.1.md](docs/09_memory_reply_guard_v0.1.md)
- [docs/10_memory_reply_guard_v0.2.md](docs/10_memory_reply_guard_v0.2.md)
- [docs/11_reply_guard_regression_hardening.md](docs/11_reply_guard_regression_hardening.md)

常用测试命令：

```powershell
uv run --with pytest --python 3.12 --no-project pytest -q
uv run --python 3.12 --no-project python -m unittest discover -s tests -v
```
